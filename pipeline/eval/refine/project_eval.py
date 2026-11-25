"""Explicit whole-project planning revision for the final G008 candidate.

One planner deadline and one cumulative native recording cap. Prior attempts,
source identity and completed judgments remain immutable. Legacy grouped runners
and their policies are unchanged.
"""
from pathlib import Path
import argparse
import json
import shutil
import time

from .common import read, dump, sha, once
from .session import snapshot, inventory
from . import planning, evidence
from .evaluation import require_checks
from .outcome_groups import gameplay_source_bundle, settle_log
from .vfx_groups import validate_reuse, plan_schema, ref
from ..stage1.codex import call_codex

VERSION = 'refine.project-plan1800-record300.v1'
ROOT_NAME = 'project_eval_20261104'


def load_policy(output):
    output = Path(output).resolve()
    policy = read(output/'project_evaluation_policy.json')
    if (policy.get('version') != VERSION or policy.get('output') != str(output)
            or policy.get('plan_timeout_seconds') != 1800 or policy.get('recording_ms') != 300000
            or policy.get('planner_model') != 'gpt-6-astra'
            or policy.get('configuration') != ref(output/'configuration.json')
            or policy.get('inventory') != ref(output/'inventory.json')):
        raise ValueError('Project policy differs from authorized frozen revision')
    for key in ('authorization', 'boundary', 'parent_migration'):
        item = policy[key]
        if ref(item['path']) != item:
            raise ValueError('Changed project policy lineage: '+key)
    if read(policy['boundary']['path'])['status'] != 'OLD_WORKER_EXITED':
        raise ValueError('Previous worker must exit before project planning')
    return policy


def existing_results(parent):
    """Use only final saved results with native evidence, preserving low scores."""
    parent = Path(parent)
    inherited = {}
    path = parent/'outcome_groups/report_source_001.json'
    report = read(path)
    for name, group in report['groups'].items():
        if group['status'] != 'SCORED_PENDING_AUDIT':
            continue
        root = parent/'outcome_groups'/name
        # Source review has an independent result but retains the original take.
        evidence.verify_manifest(root, read(root/'evidence/manifest.json'))
        from .ue_cleanup import verify
        verify(root)
        if sha(root/'input/source_manifest.json') != sha(parent/'input/source_manifest.json'):
            raise ValueError('Reused outcome source differs')
        for row in group['checks']:
            if row['task_id'] in inherited:
                raise ValueError('Duplicate inherited judgment')
            inherited[row['task_id']] = {'check': row, 'report': ref(path), 'group': name,
                'native_evidence': ref(root/'evidence/manifest.json'),
                'original_result': ref(root/'result.json')}
    path = parent/'vfx_groups/firing/result.json'
    if path.exists():
        from .audit import audit
        result = read(path)
        if result['status'] != 'SCORED_PENDING_AUDIT':
            raise ValueError('Incomplete firing result cannot be reused')
        # The exact frozen task subset is verified by the existing formal audit.
        audit(path.parent, {}, result['checks'], judge_stages=['judge_001'])
        for row in result['checks']:
            inherited[row['task_id']] = {'check': row, 'report': ref(path), 'group': 'firing',
                'native_evidence': ref(path.parent/'evidence/manifest.json')}
    return inherited


def prepare(output, policy):
    output = Path(output)
    games = read(output/'inventory.json')['games']
    if len(games) != 1 or games[0]['game_id'] != 'G008_dock_beacon_cs':
        raise ValueError('Only final G008 is authorized')
    parent = output/'games'/games[0]['game_id']
    root = parent/ROOT_NAME
    def freeze():
        admitted = validate_reuse(parent)
        inherited = existing_results(parent)
        files = read(parent/'input/source_manifest.json')['files']
        size = sum((parent/'input/project'/p).stat().st_size for p in files)
        if shutil.disk_usage(output).free < size+8*1024**3:
            raise RuntimeError('Project snapshot requires 8GiB reserve')
        if snapshot(parent/'input/project', root/'input/project') != files:
            raise ValueError('Project snapshot changed')
        for relative in ['input/source_manifest.json', 'input/tasks.json', 'static.json',
                         'native_admission.json', 'original_project.json']:
            target = root/relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(parent/relative, target)
        dump(root/'reference_renders.json', {})
        dump(root/'reused_results.json', inherited)
        dump(root/'revision.json', {'version': VERSION, 'policy': ref(output/'project_evaluation_policy.json'),
            'parent_source': ref(parent/'input/source_manifest.json'),
            'parent_tasks': ref(parent/'input/tasks.json'), 'reused_results': ref(root/'reused_results.json'),
            'plan_calls_prior': [ref(p) for p in sorted(parent.glob('**/model_calls/plan*/invocation.json'))
                                 if ROOT_NAME not in p.parts],
            'repair_calls_added': 0, 'recording_cap_ms': policy['recording_ms'],
            'scoring': 'Mechanic/Gamefeel retain outcome v2; VFX retain refine-tiered.v1; import appearance assessed separately'})
        return {'root': str(root)}
    once(root, 'prepare', freeze)
    validate_reuse(parent)
    if inventory(root/'input/project') != read(parent/'input/source_manifest.json')['files']:
        raise ValueError('Whole-project source changed')
    return parent, root, games[0]


def plan_project(root, policy):
    root = Path(root)
    tasks = read(root/'input/tasks.json')
    static = read(root/'static.json')
    require_checks(static, tasks)
    reused = read(root/'reused_results.json')
    bundle, source_delivery = gameplay_source_bundle(root)
    dump(root/'input/model_source_delivery.json', source_delivery)
    admitted = read(root/'native_admission.json')
    budget = policy['recording_ms']
    schema = plan_schema(root, budget)
    instructions = (
        'Produce ONE whole-project native plan covering EVERY frozen task exactly once. '
        'All runtime gameplay source and task JSON are supplied ONCE below. '
        'Do not run tools, edit, repair, or launch anything. Return only JSON matching the EXACT OUTPUT SCHEMA. '
        'One planner deadline is 1800 seconds for the whole project including any bounded format correction. '
        'One continuous recording starts at the title, with TOTAL max_duration_ms <=300000 for this project. '
        'Probes are sequential route sections in that same recording, NOT fresh sessions or new budgets. '
        'Read actual source to choose a short shared route covering as many PENDING tasks as possible; do not require '
        'finishing the whole game or all branches. Do not wait 5 minutes if a shorter route suffices. '
        'For REUSED_COMPLETE tasks, return executable=false and explain that the existing completed native '
        'judgment is retained, not a product failure; do not retest low scores. For unsupported/unreachable '
        'tasks use executable=false with an honest specific limitation; never invent real peers. '
        'Use only source-supported native key inputs/waits; engine=ue5, launch_source=DockBeacon.uproject, '
        'launch_scene="", watchers=[], state_channel=adapter_discovery. Function keys and mouse input '
        'are unavailable in the accepted adapter. No OS input or callbacks or direct state mutation. '
        'All step IDs globally unique. At most 10 probes, each at most24 steps. Each step duration 1..6000ms. '
        'Canonical keys: uppercase letters/digits or Enter,Space,Escape,Shift,Tab,Left,Right,Up,Down. '
        'The compiler prepends1800ms startup. Compute input timeline by accumulating every step duration. '
        'Every criterion_id must be a task ID. Put task IDs only on the probe containing their FINAL '
        'meaningful non-wait input; auxiliary later inputs can have criterion_ids=[] in a separate probe. '
        'last_action_id is EXACTLY probeID/stepID of the LAST criterion-bound non-wait input for that task. '
        'Endpoint at_ms >= that input end+stable_after_ms, stable_after_ms>=150. '
        'For tasks needing windows, use 600..4000ms windows beginning no earlier than the anchor input START, '
        'ending no later than endpoint. Select a real trigger/context; automatic weather needs legitimate '
        'entry/context, never invent a lightning input. Include explicit final wait so final action ends '
        'at least200ms after every endpoint. max_duration_ms must cover sum(all steps)+2500ms and '
        'last endpoint+1000ms. Separate distinct captures by>=100ms or merge at identical times. '
        'For executable=false: last_action_id="", at_ms=0. All tasks retain exact rubric_quote from '
        'pass_condition or acceptance_criteria/goal. Source code is not runtime success. '
        'Import geometry/texture use real in-engine result pictures; motion needs actual action frame sequence; '
        'audio needs real recording, not pixels. Actual failed actions remain valid evidence. '
        'Known preserved producer failures were too-small declared plan duration, nonexistent action IDs, '
        '15-second windows exceeding4seconds, and a window before its claimed last input. Avoid those '
        'without relaxing the original compiler. Never pad routes with unrelated keys.\n')
    context = {'tasks': tasks, 'static': static,
        'coverage': {t['task_id']: ('REUSED_COMPLETE' if t['task_id'] in reused else 'PENDING') for t in tasks},
        'native_admission': {'engine': 'ue5', 'scene': admitted['scene'],
            'real_clients': 1, 'true_multiplayer': False},
        'preserved_blockers': {'disguise': 'F3 and pointer positioning unavailable; enemy view not connected',
            'rescue': 'No real connected second client; diagnostic entry is not multiplayer'}}
    prompt = instructions+'\nPROJECT TASKS AND COVERAGE\n'+json.dumps(context, ensure_ascii=False)+(
        '\nAUTHOR SOURCE\n'+bundle+'\nEXACT OUTPUT SCHEMA\n'+json.dumps(schema, ensure_ascii=False))
    def validate(value):
        for endpoint in value['endpoints']:
            if endpoint['task_id'] in reused and endpoint['executable']:
                raise ValueError('Completed task cannot be re-recorded: '+endpoint['task_id'])
        actions, _ = planning.compile_plan(value, root/'input/project', 'ue5', tasks, budget,
            root/'capture_schedule.json')
        from engine_adapters.ue5.playtest.native_record import expand
        expand(actions)
    def invoke():
        started = time.time()
        dump(root/'plan_budget_claim.json', {'started_unix': started,
            'deadline_unix': started+1800, 'total_seconds': 1800, 'max_model_attempts': 2,
            'format_correction_shares_original_deadline': True, 'repair_calls_added': 0})
        try:
            value = call_codex(root, name='plan', prompt=prompt, schema=schema,
                model=policy['planner_model'], executable=policy['executable'],
                timeout=1800, max_attempts=2, response_validator=validate, explicit_stdin_separator=True)
            dump(root/'plan.json', value)
            return value
        finally:
            calls = []
            for call in sorted((root/'model_calls').glob('plan*')):
                calls.append({name: ref(call/name) for name in ['prompt.txt','schema.json','invocation.json','response.json']
                    if (call/name).exists()})
            dump(root/'plan_actual_delivery.json', {'source_delivery': source_delivery,
                'tasks': ref(root/'input/tasks.json'), 'calls': calls, 'elapsed_seconds': time.time()-started})
    value = once(root, 'plan', invoke)
    validate(value)
    actions, schedule = planning.compile_plan(value, root/'input/project', 'ue5', tasks, budget,
        root/'capture_schedule.json')
    dump(root/'native_actions.json', {'actions': actions})
    return value, schedule


def record_project(parent, root, plan, schedule, config, policy):
    def record():
        if plan['native_plan']['max_duration_ms'] > policy['recording_ms']:
            raise ValueError('Cumulative project recording exceeds300000ms')
        estimate = max(512*1024**2, len(schedule['points'])*1280*720*4*2)
        free = shutil.disk_usage(root).free
        dump(root/'disk_before_record.json', {'free_bytes': free, 'estimate_bytes': estimate, 'reserve_bytes':8*1024**3})
        if free < estimate+8*1024**3:
            raise RuntimeError('Project recording needs8GiB reserve')
        validate_reuse(parent)
        from .ue_native import record as native_record
        result = native_record(root, plan, schedule, config)
        settle_log(root/'background_record/take/engine.log')
        from .ue_cleanup import verify
        dump(root/'cleanup_verified.json', verify(root))
        return result
    return once(root, 'record', record)


def run(output, phase='all'):
    from .batch import exclusive, code_identity
    from .migration import verify_migration
    from ..stage1.engine_execution import lease
    output = Path(output).resolve()
    with exclusive(output.parent/(output.name+'.batch.lock')):
        verify_migration(output, code_identity())
        policy = load_policy(output)
        config = read(output/'configuration.json')
        parent, root, game = prepare(output, policy)
        print(json.dumps({'phase':'plan', 'root':str(root), 'model':policy['planner_model'],
            'timeout_seconds':1800, 'recording_cap_ms':300000}), flush=True)
        plan, schedule = plan_project(root, policy)
        print(json.dumps({'phase':'PLAN_VALIDATED', 'duration_ms':plan['native_plan']['max_duration_ms'],
            'executable_tasks':sum(e['executable'] for e in plan['endpoints']),
            'reused_tasks':len(read(root/'reused_results.json'))}), flush=True)
        if phase == 'plan':
            return {'status':'PLAN_VALIDATED', 'root':str(root)}
        with lease(Path(config['unity']['control_root']), 'ue5', output,
            output/'engine_execution'/(str(time.time_ns())+'_project_eval.json'), policy=config['engine_execution_policy']):
            record_project(parent, root, plan, schedule, config, policy)
        manifest = once(root, 'evidence', lambda:evidence.package(root, schedule))
        evidence.verify_manifest(root, manifest)
        print(json.dumps({'phase':'RECORD_EVIDENCE_COMPLETE', 'root':str(root)}), flush=True)
        if phase == 'record':
            return {'status':'RECORD_EVIDENCE_COMPLETE', 'root':str(root)}
        from .project_eval_judge import evaluate
        return evaluate(parent, root, config)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--phase', choices=['plan','record','all'], default='all')
    args = parser.parse_args(argv)
    try:
        run(args.output, args.phase)
    except Exception as exc:
        root = args.output/'games/G008_dock_beacon_cs'/ROOT_NAME
        dump(root/'failure.json', {'status':'HARNESS_ERROR', 'error':f'{type(exc).__name__}: {exc}',
            'product_score':None, 'preserve_all_attempts':True, 'updated_unix':time.time()})
        raise

if __name__ == '__main__':
    main()
