"""Sol static -> same-call plan/conditions -> native record -> evidence -> Sol judge.

No generic Unity foreground fallback, no UE5 OS-input backend, no historic publication.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
from .common import dump, read, once, sha
from .session import snapshot, inventory
from . import planning, evidence, assets
from .scoring import static_credit, score
from ..stage1.codex import call_codex, obj, arr, S, I, B

REF = obj({'path': S, 'sha256': S, 'line': I, 'quote': S})
STATIC = obj({'checks': arr(obj({'task_id': S, 'implemented': B, 'binding_explanation': S,
            'implementation_refs': arr(REF), 'entry_refs': arr(REF)}))})
VERDICT = {'type': 'string', 'enum': ['PASS', 'FAIL', 'UNVERIFIED']}
JUDGE = obj({'checks': arr(obj({'task_id': S, 'verdict': VERDICT,
    'execution': {'type': 'string', 'enum': ['NORMAL', 'BUG', 'UNVERIFIED', 'HARNESS_ERROR']},
    'triggered': B, 'state_or_event_changed': B, 'logs_normal': B,
    'all_conditions_met': B, 'state_event_refs': arr(REF), 'log_refs': arr(REF), 'image_numbers': arr(I),
    'import_checks': obj({'integration': VERDICT, 'geometry': VERDICT, 'texture': VERDICT}),
    'reason': S}))})


def model(folder, stage, prompt, schema, config, *, images=(), validator=None):
    sol = config.get('sol', {})
    if not sol.get('model'):
        raise ValueError('Configure sol.model with the exact Sol model ID; no guessed model/fallback')
    timeouts = {'static': 900, 'plan': 1800, 'judge': 900, **sol.get('timeouts', {})}
    base = 'judge' if stage.startswith('judge') else stage
    def invoke():
        result = call_codex(Path(folder), name=stage, prompt=prompt, schema=schema,
            model=sol['model'], executable=sol.get('executable', 'codex'), images=images,
            timeout=timeouts[base], max_attempts=1, response_validator=validator)
        dump(Path(folder) / (stage + '.json'), result)
        return result
    marker = Path(folder) / 'stages' / (stage + '.json')
    if stage == 'plan' and (Path(folder) / 'partial_plan_authorization.json').is_file():
        from .partial_plan import recover
        return recover(folder, schema, config, validator)
    if (stage == 'plan' and marker.is_file() and read(marker).get('status') == 'ERROR'
            and (Path(folder) / 'plan_recovery_authorization.json').is_file()):
        from .plan_recovery import recover
        return recover(folder, prompt, schema, config, validator)
    result = once(folder, stage, invoke)
    if stage == 'static' or stage.startswith('judge_'):
        from .source_citations import normalize
        return normalize(folder, stage, result)
    return result


def require_checks(result, tasks):
    ids = [r['task_id'] for r in result['checks']]
    if len(set(ids)) != len(ids) or set(ids) != {t['task_id'] for t in tasks}:
        raise ValueError('Model response must cover the exact frozen task IDs once each')


def source_bundle(project, files, limit=150000):
    extensions = {'.cs', '.cpp', '.h', '.ini', '.json', '.uproject', '.unity', '.shader', '.ush'}
    candidates = [p for p in files if Path(p).suffix.lower() in extensions]
    def priority(path):
        generic = any(x.lower() in path.lower() for x in ('thirdparty', 'packages/', 'gamefactory', 'a3game'))
        return (generic, Path(path).suffix not in {'.cs', '.cpp', '.h'}, path)
    texts, sent, omitted = [], [], []
    remaining = limit
    for relative in sorted(candidates, key=priority):
        path = Path(project) / relative
        text = path.read_text(errors='replace')
        numbered = '\n'.join(f'{n}: {line}' for n, line in enumerate(text.splitlines(), 1))
        excerpt = numbered[:max(0, remaining)]
        if not excerpt:
            omitted.append(relative)
            continue
        sent.append({'path': 'project/' + relative, 'sha256': files[relative],
                     'characters_sent': len(excerpt), 'truncated': len(excerpt) < len(numbered)})
        texts.append(f'FILE project/{relative} SHA256={files[relative]}\n{excerpt}')
        remaining -= len(excerpt)
    return '\n\n'.join(texts), {'sent': sent, 'omitted': omitted,
                                   'note': 'All frozen files remain readable under input/project; excerpts retain physical line labels.'}


def freeze(folder, game):
    folder = Path(folder)
    files = snapshot(folder / 'workspace/project', folder / 'input/project')
    dump(folder / 'input/source_manifest.json', {'files': files})
    tasks = planning.task_specs(game)
    dump(folder / 'input/tasks.json', tasks)
    bundle, delivery = source_bundle(folder / 'input/project', files)
    (folder / 'input/source_bundle.txt').write_text(bundle)
    dump(folder / 'input/source_delivery.json', delivery)
    return {'source_manifest_sha256': sha(folder / 'input/source_manifest.json'), 'task_count': len(tasks)}


def record(folder, plan, schedule, config):
    admitted = read(Path(folder) / 'native_admission.json')
    if admitted.get('native_acceptance'):
        from .ue_native import record as ue_record
        return ue_record(folder, plan, schedule, config)
    from ..stage1 import unity_safety
    from engine_adapters.unity3d.playtest import native_acceptance, background_record
    unity = config['unity']
    admitted = read(Path(folder) / 'native_admission.json')
    receipt = Path(admitted.get('editor_acceptance', unity['editor_acceptance']))
    adapter, editor = Path(unity['adapter_root']).resolve(), Path(read(receipt)['editor']).resolve()
    # Loading another adapter into this interpreter would bypass module identities.
    if adapter != Path(__file__).resolve().parents[3]:
        raise ValueError('unity.adapter_root must be this delivered GameFactory-3A root')
    native_acceptance.verify(receipt, adapter, editor)
    unity_safety.check(unity)
    dump(Path(folder) / 'recorder_binding.json', {'acceptance': str(receipt),
        'acceptance_sha256': sha(receipt), 'adapter_root': str(adapter), 'editor': str(editor),
        'plan_sha256': sha(Path(folder) / 'plan.json'),
        'schedule_sha256': sha(Path(folder) / 'capture_schedule.json')})
    capture = Path(folder) / 'background_record'
    if capture.exists():
        raise FileExistsError('Capture exists: never silently re-record')
    old_control = os.environ.get('GAMEFACTORY_UNITY_CONTROL_ROOT')
    old_editor = background_record.KNOWN_EDITOR
    background_record.KNOWN_EDITOR = editor
    try:
        os.environ['GAMEFACTORY_UNITY_CONTROL_ROOT'] = unity['control_root']
        code = background_record.main(['record', '--output', str(capture), '--adapter-root', str(adapter),
            '--adapter-pin', str(receipt.parent / 'candidate_pin.json'), '--control-root', unity['control_root'],
            '--unity', str(editor), '--project', read(Path(folder) / 'native_admission.json')['project'],
            '--scene', plan['native_plan']['launch_scene'],
            '--duration', str(plan['native_plan']['max_duration_ms'] / 1000),
            '--actions', str(Path(folder) / 'native_actions.json'),
            '--capture-schedule', str(Path(folder) / 'capture_schedule.json')])
    finally:
        background_record.KNOWN_EDITOR = old_editor
        if old_control is None:
            os.environ.pop('GAMEFACTORY_UNITY_CONTROL_ROOT', None)
        else:
            os.environ['GAMEFACTORY_UNITY_CONTROL_ROOT'] = old_control
        # Any uncertain cleanup must propagate a SafetyStop, not be treated as a game failure.
        if capture.exists():
            try:
                cleanup = unity_safety.check(unity, capture)
                dump(Path(folder) / 'cleanup.json', cleanup)
            except Exception as exc:
                raise unity_safety.SafetyStop('Native cleanup uncertain: ' + str(exc)) from exc
    if code or read(capture / 'verification.json').get('ok') is not True:
        raise RuntimeError('HARNESS_ERROR: native verification failed; preserve capture and do not judge')
    return {'capture': str(capture)}


def evaluate(game, folder, config, *, static_only=False):
    folder = Path(folder)
    once(folder, 'freeze', lambda: freeze(folder, game))
    frozen = read(folder / 'input/source_manifest.json')['files']
    if inventory(folder / 'input/project') != frozen:
        raise ValueError('Frozen repaired source changed')
    tasks = read(folder / 'input/tasks.json')
    if (folder / 'result.json').is_file():
        if (folder / 'evidence/manifest.json').is_file():
            evidence.verify_manifest(folder, read(folder / 'evidence/manifest.json'))
        saved = read(folder / 'result.json')
        if saved.get('product_status') == 'COMPILE_FAILED':
            from .audit import audit_product_failure
            audit_product_failure(folder, game, saved)
        elif saved.get('checks') is not None:
            from .audit import audit
            audit(folder, game, saved['checks'])
        return saved
    if game['game_id'] in config.get('evaluation_sources', {}):
        from .reuse import evaluation_stages
        once(folder, 'reuse_evaluation', lambda: evaluation_stages(game, folder, config))
    static_prompt = ('Read real project source. For every frozen task, determine actual implementation AND binding '
        'to a real entry/scene/event. Return source references with path project/... SHA256, physical line and exact '
        'single-line quote. Existing code alone is not runtime success. No evidence fabrication or edits.\n'
        + json.dumps(tasks, ensure_ascii=False) + '\n' + (folder / 'input/source_bundle.txt').read_text())
    static = model(folder, 'static', static_prompt, STATIC, config,
                   validator=lambda r: require_checks(r, tasks))
    if inventory(folder / 'input/project') != frozen:
        raise ValueError('Frozen repaired source changed during static review')
    codes = {r['task_id']: static_credit(folder / 'input', r) for r in static['checks']}
    dump(folder / 'static_code_scores.json', {'checks': [{'task_id': t['task_id'],
        'credit_percent': 10 if codes[t['task_id']] else 0} for t in tasks],
        'note': 'Initial source credit only, not official total; refs/raw invocation saved separately'})
    references = {}
    for item in game['imports']:
        simple = item['simple']
        ident = simple['import_id']
        if simple['asset_kind'] not in ('3d_object', '3d_scene') or item['payload']['status'] != 'READY':
            continue
        payload = read(folder / 'payloads.json')[ident]
        if sha(payload['frozen_path']) != payload['sha256']:
            raise ValueError('Original frozen asset changed')
        try:
            references[ident] = once(folder, 'render_' + simple['task_id'], lambda p=payload, s=simple:
                assets.render(p['frozen_path'], folder / 'references' / s['task_id'], config,
                              scene=s['asset_kind'] == '3d_scene'))
        except (RuntimeError, ValueError) as exc:
            dump(folder / 'reference_blockers' / (simple['task_id'] + '.json'), {'reason': str(exc)})
    dump(folder / 'reference_renders.json', references)
    if static_only:
        result = {'status': 'STATIC_EVALUATED', 'game_id': game['game_id'], 'pipeline_completed': False,
                  'static_scores': read(folder / 'static_code_scores.json'),
                  'reference_count': len(references), 'runtime_executed': False, 'formal_whitebox_score': None}
        dump(folder / 'static_result.json', result)
        return result
    engine = game['project']['engine']
    blockers = []
    if engine == 'ue5':
        if config.get('ue_native_backend') != 'dock_native_sparse.v1':
            blockers.append('BLOCKED_MISSING_MATCHING_UE_NATIVE_BACKEND')
    elif engine != 'unity3d':
        blockers.append('BLOCKED_UNSUPPORTED_BACKGROUND_BACKEND: no matching native backend')
    else:
        if not config.get('unity', {}).get('editor_acceptance'):
            blockers.append('BLOCKED_MISSING_NATIVE_ACCEPTANCE')
    if blockers:
        result = {'status': 'BLOCKED_RUNTIME', 'blockers': blockers, 'formal_score': None,
                  'static_scores': read(folder / 'static_code_scores.json'), 'game_id': game['game_id']}
        dump(folder / 'result.json', result)
        return result
    if engine == 'ue5':
        from .ue_native import admission as open_project
    else:
        from .admission import open_project
    admitted = once(folder, 'native_admission', lambda: open_project(folder, game, config))
    dump(folder / 'native_admission.json', admitted)
    if admitted['status'] == 'PRODUCT_FAILURE':
        from .audit import product_failure_result, audit_product_failure
        result = product_failure_result(folder, game)
        audit_product_failure(folder, game, result)
        dump(folder / 'result.json', result)
        return result
    budget = config.get('recording_ms', 180000)
    prompt = ('Use frozen tasks unchanged and static findings. One native real-input plan; extract each rubric endpoint '
        'visible conditions and non-single-frame requirements IN THIS SAME CALL. Read input/project. No fabricated state '
        'channels or callbacks. Every task once. Executable last_action_id=probeID/stepID must be its last non-wait '
        'criterion-bound input, sampled at planned_end_t_ms + stable_after_ms (>=150ms). native_actions adds initial1800ms. '
        'Reserve explicit waits after actions until the endpoint/window observations complete. Tasks may share inputs '
        'and identical sample times. Distinct times >=100ms apart. Rubric_quote exact substring of pass_condition '
        '(or acceptance_criteria for imports). Gamefeel/motion/audio/video need 600..4000ms windows sampled every200ms, '
        'starting after relevant trigger, ending no later than endpoint. No unavailable import marked executable. '
        'Unavailable tasks require reason, executable=false,last_action_id="",at_ms=0. Hard tasks are not automatically '
        'unreachable: use real source routes. No OS input/foreground. Death/menu before later gameplay: plan real restart '
        'and a wait when supported, not a new call or a fake event. Entire plan budget ' + str(budget) + 'ms.\n'
        + json.dumps({'tasks': tasks, 'static': static, 'launch_scene': admitted['scene']}, ensure_ascii=False))
    if engine == 'ue5':
        prompt += ('\nAccepted native backend supports only key chords and wait. Read source real keys; no mouse steps. '
                   'Key press/hold uses actual duration_ms; reserved key aliases: enter,escape,space,leftshift,'
                   'leftcontrol,tab,lmb,rmb,left_arrow,right_arrow,up_arrow,down_arrow and letters/digits. '
                   'This acceptance is single-client only. Never treat bots, diagnostic peers or a flag as true dual-client '
                   'evidence. Tasks requiring real dual clients must remain UNVERIFIED when no such evidence exists.')
    schedule_path = folder / 'capture_schedule.json'
    def valid_plan(result):
        if result['native_plan']['launch_scene'] != admitted['scene']:
            raise ValueError('Plan launch scene must match actual admitted scene')
        planning.compile_plan(result, folder / 'input/project', engine, tasks, budget, schedule_path)
    plan = model(folder, 'plan', prompt, planning.schema(engine, budget), config, validator=valid_plan)
    if inventory(folder / 'input/project') != frozen:
        raise ValueError('Frozen repaired source changed during planning')
    actions, schedule = planning.compile_plan(plan, folder / 'input/project', engine, tasks, budget, schedule_path)
    dump(folder / 'native_actions.json', {'actions': actions})
    once(folder, 'record', lambda: record(folder, plan, schedule, config))
    manifest = once(folder, 'evidence', lambda: evidence.package(folder, schedule))
    endpoints = {e['task_id']: e for e in plan['endpoints']}
    # Greedy image-budget shards, preserving full windows and all original reference views.
    groups, current = [], []
    for task in tasks:
        candidate = current + [task]
        try:
            evidence.delivery(folder, candidate, plan['endpoints'], manifest, references)
            fits = len(candidate) <= config.get('judge_tasks_per_call', 8)
        except ValueError as exc:
            if '100 actual images' not in str(exc):
                raise
            fits = False
        if not fits and current:
            groups.append(current)
            current = [task]
        elif not fits:
            raise ValueError('One task exceeds image budget')
        else:
            current = candidate
    if current:
        groups.append(current)
    scored = []
    for index, group in enumerate(groups, 1):
        delivery = evidence.delivery(folder, group, plan['endpoints'], manifest, references)
        dump(folder / f'evidence/judge_{index:03d}_delivery.json', delivery)
        judge_prompt = ('Judge ONLY delivered task IDs against frozen original conditions and actual engine evidence. '
            'For geometry compare all original GLB Three.js views with in-engine screenshots: actual slot integration, '
            'proportions/axes/scale, deformation/skinning, missing/white/pink/misbound materials/textures. White original '
            'source is not a missing-texture defect. Lighting/viewpoint alone is not deformation. Cannot see target = '
            'UNVERIFIED, not PASS. NORMAL requires real input, gameplay state/event change and logs, never sent=true or '
            'no-errors alone. Exact physical state/event/log refs with path/SHA/line/quote required; time association '
            'is not causality. PASS needs all endpoint conditions and nonvisual requirements; preserve NORMAL even when '
            'full rubric UNVERIFIED. Gamefeel requires delivered continuous short window. Audio not proved by screenshots: '
            'if no actual audio channel, audio rubric stays UNVERIFIED. Cite delivered image_numbers for visual claims. '
            'HARNESS_ERROR differs from product BUG. '
            'Evidence paths are relative to the attempt root, the PARENT of current input directory; '
            'use ../background_record or ../evidence to read files; return refs without ../. '
            'No synthetic events or inferred missing frames.\n' + json.dumps(delivery, ensure_ascii=False))
        judged = model(folder, f'judge_{index:03d}', judge_prompt, JUDGE, config,
            images=[Path(r['path']) for r in delivery['images']],
            validator=lambda r, g=group: require_checks(r, g))
        evidence.verify_manifest(folder, manifest)
        specs = {t['task_id']: t for t in group}
        for row in judged['checks']:
            ident = row['task_id']
            spec = specs[ident]
            gates = evidence.proof(folder, row, endpoints[ident], manifest, references.get(ident), delivery)
            result = score(row, codes[ident], gates, needs_window=spec['needs_window'],
                is_geometry=spec.get('asset_kind') in ('3d_object', '3d_scene'), is_import=spec['kind'] == 'import')
            # No recorder audio channel is implemented here. Do not fake auditory success from pixels.
            if spec.get('asset_kind') == 'audio' and result['credit_percent'] == 100:
                result.update(credit_percent=50, verdict='UNVERIFIED',
                              limitation='No native audio evidence channel; runtime integration only')
            if spec.get('payload_status', 'READY') != 'READY':
                result.update(credit_percent=None, verdict='UNVERIFIED',
                              blocker=spec['payload_status'])
            scored.append(result)
    # Rebuild every deterministic gate independently of judge output before publishing this local report.
    from .audit import audit
    audit(folder, game, scored)
    result = {'version': 'refine.report.v1', 'game_id': game['game_id'], 'status': 'EVALUATED',
              'pipeline_completed': True, 'product_status': 'RUNTIME_EVALUATED',
              'checks': scored, 'formal_whitebox_score': None,
              'note': 'Separate repair/import report. No historic score tables changed. Missing evidence is not product BUG.'}
    dump(folder / 'result.json', result)
    return result
