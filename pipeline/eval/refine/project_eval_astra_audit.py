"""Deterministic provenance and score replay for the independent Astra run."""
from pathlib import Path
import argparse
import json
from .common import read, dump, sha
from .project_eval_audit import verify_delivery
from .project_eval_astra import MODEL, VERSION, normalized_static, configuration, effective_static
from .project_eval_judge import checked_appearance, ref
from .scoring import score, static_credit, reference
from .outcome_groups import judge_result
from . import evidence


def model_calls(root, prefix):
    calls = []
    for path in sorted((root/'model_calls').glob(prefix+'*')):
        invocation = path/'invocation.json'
        if not invocation.exists():
            continue
        value = read(invocation)
        command = value['command']
        if '--model' not in command or command[command.index('--model')+1] != MODEL:
            raise ValueError('Non-Astra model in independent reassessment')
        calls.append(path)
    if not calls:
        raise ValueError('Missing saved Astra invocation: '+prefix)
    return calls


def verify_audio(root, task, row, judgment):
    if row['confirmed'] != judgment['confirmed'] or row['reason'] != judgment['reason']:
        raise ValueError('Final audio judgment differs from Astra response')
    if row['final_judge_model'] != MODEL or row['acoustic_model'] != 'qwen3.8-omni-flash':
        raise ValueError('Audio model attribution changed')
    if row['astra_observation_paths'] != judgment['observation_paths']:
        raise ValueError('Audio observation references changed')
    lineage = row['evidence']
    paths = set()
    for item in lineage.values():
        if isinstance(item, dict) and 'path' in item:
            if sha(item['path']) != item['sha256']:
                raise ValueError('Acoustic evidence changed')
            paths.add(item['path'])
    if not set(judgment['observation_paths']) <= paths:
        raise ValueError('Unknown acoustic observation path')
    if not row['confirmed']:
        return
    if not judgment['observation_paths'] or row['product_score'] != 100:
        raise ValueError('Unsupported acoustic credit')
    delivered = read(lineage['delivery']['path'])
    if 'source_path' in delivered:
        if sha(delivered['source_path']) != delivered['source_sha256']:
            raise ValueError('Historic native WAV changed')
        observed = read(lineage['observation']['path'])['parsed_observation']
        if observed['audible_pistol_like_shot'] != 'yes':
            raise ValueError('Gunshot observation unsupported')
        from .common import jsonl
        if not any(r.get('event') == 'fire' and r.get('actor_id') == 0 and r.get('weapon_id') == 0
                   for _, r in jsonl(lineage['native_pistol_events']['path'])):
            raise ValueError('Native pistol trigger missing')
    else:
        if delivered['audio'] != lineage['audio']:
            raise ValueError('Audio delivery mismatch')
        if delivered.get('transport') == 'pcm_segments_v1':
            from .project_eval_astra_audio import verify_segments
            if ref(delivered['segments']['path']) != delivered['segments']:
                raise ValueError('Segment manifest changed')
            verify_segments(read(delivered['segments']['path']))
            for call in delivered['calls']:
                if any(ref(call[k]['path']) != call[k] for k in ('request', 'response')):
                    raise ValueError('Acoustic segment delivery changed')
        observed = json.loads(read(lineage['observation']['path'])['text'])
        key = 'gunshot' if task['target']['asset_name'] == 'pistol_shot' else 'rain'
        if observed[key]['audible'] != 'yes':
            raise ValueError('Audio confirmation unsupported')


def audit(root):
    from .ue_cleanup import verify
    from .vfx_groups import validate_reuse
    root = Path(root).resolve()
    parent = root.parent
    output = parent.parents[1]
    configuration(output, root)
    cleanup = verify(root)
    validate_reuse(parent)
    manifest = read(root/'evidence/manifest.json')
    evidence.verify_manifest(root, manifest)
    result = read(root/'result.json')
    task_list = read(root/'input/tasks.json')
    tasks = {t['task_id']: t for t in task_list}
    rows = {r['task_id']: r for r in result['checks']}
    if len(rows) != len(result['checks']) or set(rows) != set(tasks):
        raise ValueError('Result identity mismatch')
    if (result['version'] != VERSION or result['planner_model'] != MODEL or result['judge_model'] != MODEL
            or result['reused_completed'] != 0 or read(root/'reused_results.json') != {}):
        raise ValueError('Independent model/result identity changed')
    for name, relative in [('source', 'input/source_manifest.json'), ('plan', 'plan.json'),
                           ('native_evidence', 'evidence/manifest.json'), ('policy', 'policy.json')]:
        if result[name] != ref(root/relative):
            raise ValueError('Result lineage changed: '+name)
    static, _ = normalized_static(root, read(root/'static_astra_raw.json'), task_list)
    if static != read(root/'static.json'):
        raise ValueError('Static assessment changed')
    from .outcome_groups import gameplay_source_bundle
    bundle, source_delivery = gameplay_source_bundle(root)
    static_calls = model_calls(root, 'static_astra')
    if bundle not in (static_calls[0]/'prompt.txt').read_text():
        raise ValueError('Independent static request omitted authored runtime source')
    model_calls(root, 'plan')
    planned_delivery = read(root/'plan_actual_delivery.json')
    if planned_delivery['source_delivery'] != source_delivery or planned_delivery['tasks'] != ref(root/'input/tasks.json'):
        raise ValueError('Planner source/task delivery changed')
    for call in planned_delivery['calls']:
        if any(ref(item['path']) != item for item in call.values()):
            raise ValueError('Planner request/response lineage changed')
    if not planned_delivery['calls'] or bundle not in Path(planned_delivery['calls'][0]['prompt.txt']['path']).read_text():
        raise ValueError('Whole-project primary plan omitted authored runtime source')
    claim = read(root/'plan_budget_claim.json')
    if (claim['total_seconds'] != 1800 or claim['repair_calls_added'] != 0
            or not claim['format_correction_shares_original_deadline']
            or read(root/'stages/plan.json')['elapsed_seconds'] > claim['total_seconds']
            or read(root/'plan.json')['native_plan']['max_duration_ms'] > 300000):
        raise ValueError('Whole-project plan/record budget changed')
    static = effective_static(root)
    if (root/'effective_static.json').exists():
        model_calls(root, 'static_source_tier_recovery')
    if result['static_assessment'] != ref(root/('effective_static.json' if (root/'effective_static.json').exists() else 'static.json')):
        raise ValueError('Effective static binding changed')
    codes = {r['task_id']: static_credit(root/'input', r) for r in static['checks']}
    endpoints = {e['task_id']: e for e in read(root/'plan.json')['endpoints']}
    checked = set()
    for path in sorted(root.glob('judge_astra_*.json')):
        stage = path.stem
        delivery = verify_delivery(root, stage)
        model_calls(root, stage)
        judgments = read(path)['checks']
        selection = [tasks[r['task_id']] for r in judgments]
        if len(selection) != len({t['task_id'] for t in selection}):
            raise ValueError('Duplicate Astra judgment')
        if stage.startswith('judge_astra_outcome_'):
            replay = judge_result(root, selection, judgments, codes, delivery)
        elif stage.startswith('judge_astra_vfx_'):
            replay = []
            for row in judgments:
                if not all(reference(root, c) for c in row['state_event_refs']+row['log_refs']):
                    raise ValueError('Invalid VFX citation')
                task = tasks[row['task_id']]
                gates = evidence.proof(root, row, endpoints[row['task_id']], manifest, None, delivery)
                replay.append(score(row, codes[row['task_id']], gates, needs_window=task['needs_window']))
        elif stage.startswith('judge_astra_import_'):
            replay = [checked_appearance(r, tasks[r['task_id']], delivery, manifest, root) for r in judgments]
        elif stage == 'judge_astra_audio':
            for row in judgments:
                ident = row['task_id']
                verify_audio(root, tasks[ident], rows[ident], row)
            replay = []
        else:
            raise ValueError('Unknown Astra judgment stage')
        for row in replay:
            if any(rows[row['task_id']].get(k) != v for k, v in row.items()):
                raise ValueError('Saved score differs from deterministic replay')
        for row in judgments:
            ident = row['task_id']
            if ident in checked or rows[ident]['judge'] != ref(path):
                raise ValueError('Duplicate or stale judgment lineage')
            checked.add(ident)
    missing = set()
    for ident, task in tasks.items():
        row = rows[ident]
        if task.get('payload_status', 'READY') != 'READY':
            if (row['status'] != 'BLOCKED_MISSING_PAYLOAD' or row.get('product_score') is not None
                    or row.get('confirmed') or row.get('texture_confirmed')):
                raise ValueError('Missing original payload mis-scored')
            missing.add(ident)
    if checked | missing != set(tasks) or checked & missing:
        raise ValueError('Incomplete independent judgment coverage')
    imports = [rows[i] for i, t in tasks.items() if t['kind'] == 'import']
    summary = result['import_summary']
    expected = {'confirmed': sum(bool(r.get('confirmed')) for r in imports), 'denominator': len(imports),
                'unverified': sum(r.get('status') == 'UNVERIFIED' for r in imports), 'missing_payload': len(missing),
                'texture_confirmed': sum(bool(r.get('texture_confirmed')) for r in imports), 'texture_denominator': 10}
    if summary != expected:
        raise ValueError('Import aggregation changed')
    publication = read(root/'publication.json')
    if publication['result'] != ref(root/'result.json') or publication['status'] != result['status']:
        raise ValueError('Stale publication')
    value = {'status': 'PASS', 'scope': 'deterministic provenance and score replay; semantic audit pending',
             'result': ref(root/'result.json'), 'model': MODEL, 'reused_verdicts': 0,
             'independent_judgments': len(checked), 'missing_payload': len(missing), 'task_identities': len(rows),
             'cleanup': cleanup, 'semantic_audit': 'PENDING', 'official_eight_column_total': None}
    dump(root/'deterministic_audit.json', value)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.root), ensure_ascii=False))


if __name__ == '__main__':
    main()
