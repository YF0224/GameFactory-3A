"""One remaining global take2 for exact Kimi G025; formal install required.

Retain failed take1, plan, source and producer. G020 sealed UI native acceptance
is mandatory. One feedback model response, one 75s record, no replay or retry.
Only formal Stage1 rules score the isolated child; KEEP_PROJECTS always.
"""

from ..model_config import PLANNER_MODEL
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sys
import tempfile
import traceback

from ..stage1 import pipeline, plan, playable_rules, prepare, record
from ..stage1.llm import accepted_response
from ..stage1.paths import BENCH, read_json, sha256

VERSION = 'stage1-kimi-g025-ui-take2-recovery.v1'
REL = Path('recovery/ue_ui_take2_v1')
from pipeline.eval.stage1.paths import DATA_ROOT
ROOT = DATA_ROOT / 'outputs/eval/whitebox/stage1_playable_kimi_all_20261109__plan-gpt-6-astra'
OUT = ROOT / 'kimi_k3/G025_broken_continent_rts/retest'
G020 = ROOT / 'kimi_k3/G020_tidal_glyphs/retest'
G020_REL = Path('recovery/ue_missing_recorder_v1/continuation_v1')
SELF = 'pipeline/eval/repair/ue_g025_take2_recovery.py'
MODELS = {'planner': PLANNER_MODEL, 'judge': 'none'}
IDENTITY = {'model': 'Kimi', 'case': 'G025', 'game_id': 'G025_broken_continent_rts',
            'engine': 'ue5', 'entry': 'BrokenContinentRTS.uproject', 'required_real_clients': 1}
LIMITS = {'parent_native_takes': 1, 'new_native_takes': 1, 'global_take': 2,
          'max_total_native_takes': 2, 'new_planner_calls': 1, 'max_attempts': 1,
          'gameplay_ms': 75000, 'cache_policy': 'KEEP_PROJECTS'}
HOLD = {'version': VERSION, 'qualified': False, 'require': 'verified replacement.json'}


def require(value, message):
    if not value:
        raise ValueError(message)


def runner():
    scripts = str(BENCH / 'scripts/eval')
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from pipeline.eval.stage1 import recovery_support as kimi_playable_retest
    return kimi_playable_retest


def installed():
    require(Path(__file__).resolve() == BENCH / SELF, 'install reviewed formal module before execution')


def plain(path):
    path = Path(path).absolute()
    require(not any(p.is_symlink() for p in (path, *path.parents)), 'linked path: ' + str(path))
    return path


def exclusive(path, value):
    plain(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write('\n')


def tree(root, *, skip=()):
    return runner().files(plain(root), skip=skip)


def producer_archive(values):
    for value in set(values.values()):
        require(sha256(plain(ROOT / '_kimi_batch/producer_blobs' / value)) == value,
                'producer archive missing/changed')


def snapshot_files(root):
    result = {}
    for directory, dirs, names in os.walk(root):
        ignored = prepare.IGNORE(directory, dirs + names)
        dirs[:] = [d for d in dirs if d not in ignored]
        for name in names:
            if name not in ignored:
                p = plain(Path(directory) / name)
                result[str(p.relative_to(root))] = sha256(p)
    return result


def short_manifest(manifest):
    budget = dict(manifest['budget'])
    extra = pipeline.PLAYABLE_GAMEPLAY_MS - budget['gameplay_ms']
    for key in ('gameplay_ms', 'recording_ms', 'total_wall_clock_ms'):
        budget[key] += extra
    budget['engine_call_ms'] = max(budget['engine_call_ms'] + extra, budget['total_wall_clock_ms'])
    require(budget['gameplay_ms'] == budget['recording_ms'] == 75000, 'non-75s formal budget')
    return {**manifest, 'budget': budget}


def rows(path):
    return [json.loads(s) for s in path.read_text(encoding='utf-8-sig').splitlines() if s.strip()]


def input_proof(native, executable, launch, ready):
    from engine_adapters.ue5.playtest import native_client, native_record
    normalized, end_ms = native_client.plan_actions(plan.native_actions(executable, 'ue5'), {})
    require(end_ms <= 75000 and read_json(native / 'action_schedule.json') == {'actions': normalized},
            'native action schedule differs from accepted plan')
    events = native_record.expand(normalized)
    def channel(name):
        p = native / name
        return rows(p) if p.exists() else []
    receipts = channel('raw_native_input.jsonl')
    requests = channel('host_input_requests.jsonl')
    collected = channel('actions.jsonl')
    require(len(receipts) == len(requests) == len(collected) == len(events), 'native input count differs')
    by_seq = {r['seq']: r for r in receipts}
    require(len(by_seq) == len(events), 'duplicate native input receipt')
    for event, request, actual in zip(events, requests, collected):
        receipt = by_seq[event['seq']]
        require(all(receipt[k] == request[k] == event[k] for k in ('seq', 'key', 'phase'))
                and request['type'] == 'key' and request['action_id'] == event['action']['action_id']
                and receipt['pid'] == launch['pid'] and receipt['routed'] is True
                and receipt['source'] == 'UGameViewportClient::InputKey'
                and receipt['token'] == request['token'] == launch['native_input_token'],
                'native input routing/ownership differs')
        at = receipt['t_ms'] - ready['native_origin_seconds'] * 1000
        expected = {**event['action'], 'phase': receipt['phase'], 'key': receipt['key'],
                    'seq': receipt['seq'], 'sent': True, 't_ms': at, 'end_t_ms': at,
                    'source': 'native_receiver', 'source_t_ms': receipt['t_ms']}
        require(actual == expected, 'collected native action differs')
    return len(events)


def native_proof(child, take=2):
    from pipeline.eval.stage1.sparse_evidence import audit_capture
    capture = child / f'takes/{take}/record'
    native = capture / 'native/take'
    result = read_json(capture / 'record_result.json')
    require(result['engine'] == 'ue5' and result['take'] == take and result['frames'] > 0
            and not result['failed_actions'] and result['plan_sha256'] == sha256(capture.parent / 'plan.json'),
            'record result/plan changed')
    launch = read_json(native / 'launch.json')
    cleanup = read_json(native / 'cleanup.json')
    command = launch['command']
    project = child / 'runtime/project'
    require(command[1] == str(project / 'BrokenContinentRTS.uproject') and '-game' in command
            and '-A3PlaytestOutput=' + str(native) in command, 'native launched wrong copy/output')
    schedule = read_json(native / 'capture_schedule.json')
    duration = (75000 + schedule['warmup_ms'] + 1000) / 1000
    require([v for v in command if v.startswith('-A3PlaytestDuration=')] == [f'-A3PlaytestDuration={duration}'],
            'native duration command differs')
    require(read_json(native / 'runner_exit.json')['returncode'] == 0, 'native nonzero exit')
    require(all(cleanup.get(k) is True for k in ('process_cleanup_ok', 'view_cleanup_ok', 'input_cleanup_ok', 'ownership_verified'))
            and cleanup['pid'] == launch['pid'] and not cleanup['remaining_descendants']
            and not cleanup['input_release_errors'], 'native cleanup incomplete')
    clocks = rows(native / 'clock_trace.jsonl')
    ready = read_json(native / 'play_started.json')
    require(clocks and all(math.isfinite(r['t_ms']) for r in clocks)
            and all(b['t_ms'] > a['t_ms'] for a, b in zip(clocks, clocks[1:])), 'native clock invalid')
    elapsed = clocks[-1]['t_ms'] - ready['recorder_elapsed_ms'] - schedule['warmup_ms']
    require(elapsed >= 75000, 'actual native clock shorter than 75s')
    audit = audit_capture(native)
    require(not audit['missing_slots_ms'] and audit['actual_screenshots'] == result['frames'], 'native capture incomplete')
    inputs = input_proof(native, read_json(capture.parent / 'plan.json'), launch, ready)
    verification = read_json(native / 'verification.json')
    require(verification['ok'] is True and verification['native_receipts'] == inputs
            and verification['capture_audit'] == audit
            and verification['pin_sha256'] == sha256(child / 'runtime/ue_admission/pin.json'), 'native verification mismatch')
    executable = read_json(capture.parent / 'plan.json')
    expected_empty = set()
    if executable['state_channel'] == 'UNAVAILABLE_STATE_CHANNEL' and executable['watchers'] == []:
        expected_empty.update(('state_trace.jsonl', 'event_trace.jsonl'))
    for name in ('frame_index.jsonl', 'actions.jsonl', 'state_trace.jsonl', 'event_trace.jsonl'):
        source, collected = native / name, capture / name
        if not source.exists():
            require(name in expected_empty and collected.read_bytes() == b'', 'unexpected absent native channel: ' + name)
        else:
            require(collected.read_bytes() == source.read_bytes(), 'collected channel differs: ' + name)
    for frame in rows(native / 'frame_index.jsonl'):
        rel = Path(frame['path'])
        require(not rel.is_absolute() and '..' not in rel.parts, 'external frame')
        require(sha256(plain(native / rel)) == sha256(plain(capture / rel)), 'collected frame differs')
    from engine_adapters.ue5.playtest import native_record
    native_record._validate_startup_boundary(ready)
    native_record._validate_capture_surface(ready)
    count = native_record._validate_ui_frame_sources(native)
    require('-RenderOffscreen' not in command and '-A3CaptureSurface=slate_window.v1' in command,
            'UI capture command not qualified')
    require(verification['capture_surface_policy'] == 'slate_window.v1'
            and verification['ui_surface_frame_count'] == count == result['frames'], 'UI capture count differs')
    require(inputs > 0, 'G025 take2 must exercise real native input, not a wait-only plan')
    return {'take': take, 'frames': result['frames'], 'actual_clock_ms': elapsed,
            'native_verification_sha256': sha256(native / 'verification.json')}


def verify_overlay(child):
    """G025 already ships A3GamePlayable; only three formal adapter files may change."""
    from engine_adapters.ue5.playtest import native_admission, native_record
    folder, project = child / 'runtime/ue_admission', child / 'runtime/project'
    original = native_admission.source_manifest(child / 'input/project')
    require(read_json(folder / 'source_binding.json') == {
        'source_project': str(child / 'input/project'), 'validation_project': str(project),
        'files': original, 'status': 'SOURCE_BOUND_BEFORE_ADAPTER_OVERLAY'}, 'overlay source binding differs')
    overlay = read_json(folder / 'overlay.json')
    require(overlay.get('mode') is None and overlay['source_binding'] == str(folder / 'source_binding.json'),
            'G025 must retain its existing authored plugin')
    prefix = 'Plugins/A3GamePlayable/Source/A3GamePlayable/'
    expected = {prefix + rel for rel in native_record.RECORDER_FILES}
    require(len(overlay['overlays']) == 3 and {r['path'] for r in overlay['overlays']} == expected,
            'unexpected authored overlay paths')
    allowed = {}
    for row in overlay['overlays']:
        rel = row['path'][len(prefix):]
        archive = folder / 'before' / rel
        require(row['before_sha256'] == original[row['path']] == sha256(plain(archive))
                and row['before_archive'] == str(archive), 'overlay old bytes changed')
        expected_bytes = (native_admission.dependency_overlay(archive.read_text(encoding='utf-8')).encode()
                          if rel.endswith('.Build.cs') else (native_record.PLUGIN / rel).read_bytes())
        expected_sha = hashlib.sha256(expected_bytes).hexdigest()
        require(row['after_sha256'] == expected_sha == sha256(plain(project / row['path'])),
                'overlay differs from formal transport/dependency changes')
        allowed[row['path']] = expected_sha
    require(native_admission.source_manifest(project) == {**original, **allowed}, 'authored runtime code/assets changed')


PARENT_DIGEST = 'b66273fd9d003e9cd7972a0abbc5d00c6e5f56a5bab03438004de97818df5bea'
UI_PRODUCER = {'engine_adapters/ue5/playtest/native_admission.py': '00811f2edf6e70b21f93bec26badc2f76f5cc36ea6a9a1a34b5fe4737787a078', 'engine_adapters/ue5/playtest/native_record.py': '68247db82044b639df419897a93d18119379196da2fe1b8e4a66e0305efd85f3', 'engine_adapters/ue5/plugin/A3GamePlayable/Source/A3GamePlayable/A3GamePlayable.Build.cs': '1d35dd9f1dfc5d312144a96ee50a63191add79f57c9685b54c19efc11f08f049', 'engine_adapters/ue5/plugin/A3GamePlayable/Source/A3GamePlayable/Private/Playtest/A3GamePlaytestRecorderSubsystem.cpp': '2fbd8c34c6fa5bfdc086dab30ee4349e4cad489172ccd011c4685e2a0bec9655', 'engine_adapters/ue5/plugin/A3GamePlayable/Source/A3GamePlayable/Public/Playtest/A3GamePlaytestRecorderSubsystem.h': '1d580f8c5234825106f4d2d80bf43e06b165bb5d1e5c7eac9a5f44b3de5da10e', 'engine_adapters/ue5/playtest/native_client.py': '02c2eb4fc1fae68251a9ef4c13b39969138b502cc314c08701e55c01e04fc76f', 'pipeline/eval/stage1/plan.py': 'cf1577b9c46cb3a99f46b4269f5f2a1b365ee64eec13e685018c040accc42eaf'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def parent_tree(out):
    values = tree(out, skip=(str(REL), 'runtime/project', 'input/project'))
    lock = out / 'takes/1/record/.postprocess.lock'
    values[str(lock.relative_to(out))] = sha256(plain(lock))
    return values


def review_parent(out):
    out = plain(out)
    require(out == OUT, 'only exact canonical Kimi G025 may recover')
    retained = parent_tree(out)
    require(digest(retained) == PARENT_DIGEST, 'frozen parent evidence changed or extra attempt exists')
    r = runner()
    claim = read_json(out / '_kimi_batch/attempt.json')
    target = claim['target']
    require(all(target.get(k) == v for k, v in IDENTITY.items()), 'wrong G025 identity')
    require(claim['models'] == MODELS and claim['max_takes'] == 2, 'parent budget/model changed')
    require(claim['scope_sha256'] == r.FULL_SHA, 'not frozen full60 scope')
    scope = ROOT / '_kimi_batch/scopes' / (r.FULL_SHA + '.json')
    require(sha256(plain(scope)) == r.FULL_SHA and target in read_json(scope)['targets'], 'scope changed')
    auth = ROOT / '_kimi_batch/authorization.json'
    require(sha256(plain(auth)) == claim['authorization_sha256']
            and read_json(auth) == r.authorization(), 'authorization changed')
    require(r.source_binding(target, r.selection(target)) == claim['source'], 'source/provenance changed')
    for phase in ('start', 'end'):
        producer_archive(read_json(out / f'_kimi_batch/producer_{phase}.json')['files'])
    manifest = prepare.verify(out)
    require(manifest['suite'] == 'stage1' and manifest['models'] == MODELS and manifest['engine'] == 'ue5'
            and manifest['project_source'] == target['project'] and manifest['entry'] == IDENTITY['entry'],
            'parent source/engine mismatch')
    delivery = Path(manifest['delivery_dir']) / 'delivery.json'
    require(read_json(delivery) == manifest['delivery'], 'delivery shim changed')
    require(snapshot_files(Path(target['project'])) == tree(out / 'input/project'), 'snapshot differs from original')
    require({p.name for p in (out / 'takes').iterdir()} == {'1'}, 'parent budget already exhausted')
    require({p.name for p in (out / 'model_calls').iterdir()} == {'plan_t1'}, 'extra parent calls')
    executable = accepted_response(out / 'model_calls', 'plan_t1')
    require(executable == read_json(out / 'takes/1/plan.json'), 'parent accepted plan differs')
    plan.validate(executable, short_manifest(manifest), out / 'input/project')
    status = read_json(out / 'status.json')
    require(status['step'] == 'record_t1' and status['state'] == 'HARNESS_ERROR'
            and 'native screenshot missed its predeclared capture slot' in status['error'], 'different parent failure')
    old_native = out / 'takes/1/record/native/take'
    require(len(list((old_native / 'frames').glob('*.png'))) == 129, 'retained frame count changed')
    cleanup = read_json(old_native / 'cleanup.json')
    require(all(cleanup.get(k) is True for k in ('process_cleanup_ok', 'view_cleanup_ok', 'input_cleanup_ok', 'ownership_verified'))
            and not cleanup['remaining_descendants'] and not cleanup['input_release_errors'], 'parent cleanup incomplete')
    require(not (out / 'playable_score.json').exists(), 'unexpected parent score; do not duplicate success')
    return {'target': target, 'source': claim['source'], 'parent_files': retained,
            'delivery_sha256': sha256(delivery), 'limits': LIMITS}


def ui_acceptance():
    """Require installed formal G020 continuation AND its sealed, reviewed real take2.

    Never import engineering drafts. Missing module/receipt is a dispatch blocker.
    Reuse the parent's exact g020-native-ui-acceptance.v1 review contract.
    """
    from . import ue_g020_capture_continuation as g020
    require(Path(g020.__file__).resolve() == BENCH / 'pipeline/eval/repair/ue_g020_capture_continuation.py',
            'G020 verifier is not the formal installed module')
    require(g020.REL == G020_REL, 'unexpected G020 acceptance lineage')
    score = g020.verify_completion(G020)
    require(score['complete'] is True, 'G020 acceptance not formally sealed')
    folder = G020 / G020_REL
    review = read_json(folder / 'ui_acceptance.json')
    require(review['ui_visible'] is True and review['frames'] and review['reviewer'].strip()
            and review['observations'].strip(), 'G020 visual review absent')
    # Capability pin is the actual producer used for the validated native capture.
    producer = read_json(folder / 'producer_start.json')['files']
    for rel, value in UI_PRODUCER.items():
        require(producer.get(rel) == value == sha256(plain(BENCH / rel)), 'UI acceptance producer mismatch: ' + rel)
    bindings = {name: sha256(plain(folder / name)) for name in (
        'activation.json', 'producer_start.json', 'producer_end.json', 'completion.json',
        'replacement.json', 'ui_acceptance.json', 'native_finished.json')}
    return {'path': str(folder), 'files': bindings, 'capture_policy': 'slate_window.v1',
            'native_take': 2, 'ui_producer': UI_PRODUCER}


def feedback(out):
    return {'earlier_plans': [read_json(out / 'takes/1/plan.json')['summary']],
            'judge_reasons': {'play.operate':
                'Retained global take1 failed native predeclared capture slots during startup. '
                'Its frames also used scene-only capture; no valid operate verdict exists. '
                'Read the full authored G025 source and controls, enter gameplay through authored UI '
                'using only the formal native key relay (Enter confirms each menu phase; no mouse steps), then probe visible responses. The tool now '
                'waits for startup completion and captures the owning Slate window including UI. '
                'Only global take2 remains: use a source-informed 75s plan; no OS input or author repairs.'},
            'retained_failure': {'path': str(out / 'takes/1/record/record_error.json'),
                                 'sha256': sha256(out / 'takes/1/record/record_error.json')}}


def key_only_schema(ids):
    value = plan.schema('ue5', 75000, ids)
    steps = value['properties']['probes']['items']['properties']['steps']
    variants = steps['items'].get('anyOf', [steps['items']])
    steps['items'] = next(v for v in variants
                          if v['properties']['kind']['enum'] == ['input', 'wait'])
    return value


def require_key_plan(executable):
    require(all(step['kind'] in ('input', 'wait')
                for probe in executable['probes'] for step in probe['steps']),
            'G025 reviewed recovery permits only keyboard/wait steps')


def make_plan2(child, manifest, prior_feedback):
    require(not (child / 'model_calls').exists() and not (child / 'takes').exists(), 'planner already claimed')
    selected = [r for r in plan.targets(read_json(child / 'input/criteria.json')['criteria'])
                if r['id'] in ('play.launch', 'play.operate')]
    ids = [r['id'] for r in selected]
    require(set(ids) == {'play.launch', 'play.operate'}, 'playable criteria missing')
    executable = plan.call_model(child / 'model_calls', name='plan_t2',
        prompt=plan.prompt(manifest, selected, prior_feedback),
        schema=key_only_schema(ids), cwd=child / 'input', model=MODELS['planner'],
        timeout=manifest['budget']['plan_timeout_s'], max_attempts=1,
        validator=lambda value: plan.validate(value, manifest, child / 'input/project'))
    plan.validate(executable, manifest, child / 'input/project')
    require_key_plan(executable)
    from engine_adapters.ue5.playtest import native_client, native_record
    normalized, end = native_client.plan_actions(plan.native_actions(executable, 'ue5'), {})
    require(end <= 75000 and native_record.expand(normalized), 'plan2 lacks executable native input')
    folder = child / 'takes/2'
    covered = sorted({c for p in executable['probes'] for c in p['criterion_ids']})
    exclusive(folder / 'plan_coverage.json', {'take': 2, 'targets': ids, 'planned': covered,
                                             'unplanned': sorted(set(ids) - set(covered))})
    exclusive(folder / 'plan.json', executable)
    return executable


def verify_plan2(child):
    require({p.name for p in (child / 'takes').iterdir()} == {'2'}, 'only global take2 is allowed')
    require({p.name for p in (child / 'model_calls').iterdir()} == {'plan_t2'}, 'extra planner calls forbidden')
    executable = read_json(child / 'takes/2/plan.json')
    require(accepted_response(child / 'model_calls', 'plan_t2') == executable, 'take2 accepted plan differs')
    invocation = read_json(child / 'model_calls/plan_t2/invocation.json')
    require(invocation['model_requested'] == MODELS['planner'] and invocation['attempt'] == 1
            and invocation['exit_code'] == 0 and invocation.get('retry_of') is None, 'planner retry/model mismatch')
    pointer = read_json(child / 'model_calls/plan_t2/accepted_response.json')
    require(pointer['path'] == 'response.json', 'accepted pointer is not the sole plan2 response')
    plan.validate(executable, short_manifest(prepare.verify(child)), child / 'input/project')
    require_key_plan(executable)
    return executable


def verify_admission(child):
    from engine_adapters.ue5.playtest.native_record import verify_pin
    admission = read_json(child / 'runtime/ue_admission/admission.json')
    require(admission['project'] == str(child / 'runtime/project')
            and admission['source_project'] == str(child / 'input/project')
            and admission['pin'] == str(child / 'runtime/ue_admission/pin.json')
            and admission['uproject'] == str(child / 'runtime/project' / IDENTITY['entry'])
            and admission['relay_kind'] == 'formal_native_viewport.v1', 'admission copy/relay differs')
    require(read_json(Path(admission['pin']))['build_receipt_sha256'] == sha256(child / 'runtime/ue_admission/build.json')
            and read_json(child / 'runtime/ue_admission/build.json')['ok'] is True, 'build receipt differs')
    verify_pin(admission)
    verify_overlay(child)


def expected_schedule(executable):
    from engine_adapters.ue5.playtest import native_client
    normalized, _ = native_client.plan_actions(plan.native_actions(executable, 'ue5'), {})
    require(record.UE_WARMUP_S == 3.0 and record.UE_LATE_TOLERANCE_MS == 3000
            and record.FPS_BY_ENGINE['ue5'] == 4, 'formal capture policy changed')
    try:
        schedule, _ = record.capture.schedule(normalized, 75000)
    except ValueError:
        schedule = {'version': record.capture.VERSION, 'interval_ms': 250,
                    'points': [{'at_ms': i * 250, 'capture_ids': [f'playtest/frame/{i:05d}'],
                                'criterion_ids': []} for i in range(300)]}
    schedule.update(warmup_ms=3000, tolerance_ms=3000, plan={'windows': [], 'endpoints': []})
    return schedule


def verify_child(child):
    parent, manifest = prepare.verify(OUT), prepare.verify(child)
    require(all(manifest[k] == parent[k] for k in ('delivery', 'delivery_dir', 'project_source', 'project_digest',
        'snapshot_digest', 'input_hashes', 'criteria_sha256', 'models', 'suite', 'engine', 'entry')), 'child source differs')
    executable = verify_plan2(child)
    native = child / 'takes/2/record/native/take'
    require(read_json(native / 'capture_schedule.json') == expected_schedule(executable), 'capture windows/policy changed')
    verify_admission(child)
    return native_proof(child, 2)


def formal_score(child, *, save=False):
    if save:
        verdicts = playable_rules.evaluate(child, prepare.verify(child), 2)
    else:
        with tempfile.TemporaryDirectory(prefix='g025-rule-verify-') as temp:
            verdicts = playable_rules.evaluate(child, prepare.verify(child), 2, report_dir=Path(temp))
    checks = {i: verdicts.get(i, {}).get('status', 'HARNESS_ERROR') for i in playable_rules.IDS}
    require('HARNESS_ERROR' not in checks.values(), 'incomplete formal rules; preserve failure without score')
    return {'version': playable_rules.VERSION, 'game_id': IDENTITY['game_id'], 'engine': 'ue5',
            'planner': MODELS['planner'], 'checks': checks, 'takes': [{'take': 2, 'checks': checks}],
            'complete': True, 'playable': round(100 * sum(x == 'PASS' for x in checks.values()) / 3, 2)}


def evidence(child):
    return tree(child, skip=('input/project', 'runtime/project'))


def verify_activation(out):
    proof = review_parent(out)
    folder = out / REL
    activation = read_json(folder / 'activation.json')
    acceptance = ui_acceptance()
    require(read_json(folder / 'ui_acceptance_binding.json') == acceptance, 'G020 acceptance changed')
    require(activation == {'version': VERSION, 'proof': proof, 'limits': LIMITS,
        'ui_acceptance_sha256': sha256(folder / 'ui_acceptance_binding.json'),
        'producer_start_sha256': sha256(folder / 'producer_start.json'),
        'feedback_sha256': sha256(folder / 'feedback.json')}, 'activation binding differs')
    require(read_json(folder / 'feedback.json') == feedback(out), 'feedback changed')
    require(read_json(folder / 'qualification_hold.json') == HOLD, 'hold changed')
    for rel, value in proof['parent_files'].items():
        require(sha256(plain(folder / 'parent_archive' / rel)) == value, 'parent archive changed: ' + rel)
    start = read_json(folder / 'producer_start.json')['files']
    producer_archive(start)
    require(start.get(SELF) == sha256(Path(__file__)), 'verifier changed since activation')
    return proof, start


def verify_current(start):
    require(runner().producer_closure(start) == runner().producer_closure(runner().production()),
            'producer drift; retained native must not be replayed')


def completion_payload(out):
    folder, child = out / REL, out / REL / 'child'
    _, start = verify_activation(out)
    require(not (folder / 'failure.json').exists(), 'failed recovery requires new explicit offline repair, never replay')
    require(read_json(folder / 'planner.claim.json') == {'take': 2, 'max_attempts': 1}, 'planner budget changed')
    require(read_json(folder / 'native_dispatch.claim.json') == LIMITS, 'native budget changed')
    end = read_json(folder / 'producer_end.json')['files']
    producer_archive(end)
    require(runner().producer_closure(start) == runner().producer_closure(end), 'native producer drift')
    # Pin all code actually used by this verifier and its runtime proof dependencies.
    # Additional unrelated modules do not invalidate a sealed historical run.
    prefixes = ('pipeline/eval/repair/',
                'engine_adapters/ue5/',
                'pipeline/eval/stage1/',
                'pipeline/eval/refine/')
    for rel, value in start.items():
        if rel.startswith(prefixes) or rel == 'pipeline/eval/stage1/recovery_support.py':
            require(sha256(plain(BENCH / rel)) == value, 'verification producer changed: ' + rel)
    native = verify_child(child)
    require(read_json(folder / 'native_finished.json') == native, 'native finish changed')
    score = formal_score(child)
    require(read_json(child / 'playable_score.json') == score, 'score differs from formal rules')
    require(read_json(child / 'status.json') == {'step': 'playable', 'state': 'done', 'complete': True,
                                               'version': VERSION}, 'child status changed')
    return {'version': VERSION, 'qualified': True, 'score': score, 'native': native,
            'activation_sha256': sha256(folder / 'activation.json'),
            'producer_end_sha256': sha256(folder / 'producer_end.json'),
            'child_evidence': evidence(child), 'limits': LIMITS, 'freed_bytes': 0}


def verify_completion(out):
    out = plain(out)
    payload = completion_payload(out)
    folder = out / REL
    require(read_json(folder / 'completion.json') == payload, 'completion evidence changed')
    require(read_json(folder / 'replacement.json') == {'version': VERSION, 'child': 'child',
        'completion_sha256': sha256(folder / 'completion.json'),
        'score_sha256': sha256(folder / 'child/playable_score.json')}, 'replacement binding changed')
    return payload['score']


def qualified_replacement_score(out):
    try:
        return verify_completion(Path(out))
    except Exception:
        return None


def execute(out):
    installed()
    out = plain(out)
    require(out == OUT, 'foreign recovery')
    r = runner()
    with r.locked(ROOT / '_kimi_batch/locks/G025.lock'), r.locked(out / 'takes/1/record/.postprocess.lock'):
        proof = review_parent(out)
        acceptance = ui_acceptance()  # Before any claims, copies, model, build or native.
        folder, child = out / REL, out / REL / 'child'
        require(not folder.exists(), 'one-shot recovery already claimed; preserve failed/partial child')
        r.check_disk(ROOT, proof['target'], proof['source'])
        start = r.production()
        r.archive_producer(ROOT, start)
        folder.mkdir(parents=True, exist_ok=False)
        exclusive(folder / 'qualification_hold.json', HOLD)
        exclusive(folder / 'producer_start.json', {'files': start})
        exclusive(folder / 'feedback.json', feedback(out))
        exclusive(folder / 'ui_acceptance_binding.json', acceptance)
        exclusive(folder / 'activation.json', {'version': VERSION, 'proof': proof, 'limits': LIMITS,
            'ui_acceptance_sha256': sha256(folder / 'ui_acceptance_binding.json'),
            'producer_start_sha256': sha256(folder / 'producer_start.json'),
            'feedback_sha256': sha256(folder / 'feedback.json')})
        try:
            for rel in proof['parent_files']:
                dest = folder / 'parent_archive' / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                with dest.open('xb') as handle:
                    handle.write((out / rel).read_bytes())
            parent = prepare.verify(out)
            manifest = prepare.prepare(Path(parent['delivery_dir']), child, models=MODELS, suite='stage1', playable_only=True)
            require(all(manifest[k] == parent[k] for k in ('delivery', 'project_source', 'snapshot_digest', 'input_hashes',
                    'criteria_sha256', 'models', 'suite', 'engine')), 'prepared child differs')
            verify_current(start)
            exclusive(folder / 'planner.claim.json', {'take': 2, 'max_attempts': 1})
            executable = make_plan2(child, short_manifest(manifest), read_json(folder / 'feedback.json'))
            verify_plan2(child)
            require(review_parent(out) == proof and ui_acceptance() == acceptance, 'source/acceptance changed before native')
            verify_current(start)
            r.check_disk(ROOT, proof['target'], proof['source'])
            exclusive(folder / 'native_dispatch.claim.json', LIMITS)
            record.record(child, short_manifest(manifest), executable, 2)
            native = verify_child(child)
            exclusive(folder / 'native_finished.json', native)
            score = formal_score(child, save=True)
            exclusive(child / 'playable_score.json', score)
            exclusive(child / 'status.json', {'step': 'playable', 'state': 'done', 'complete': True, 'version': VERSION})
            end = r.production()
            r.archive_producer(ROOT, end)
            exclusive(folder / 'producer_end.json', {'files': end})
            exclusive(folder / 'completion.json', completion_payload(out))
            exclusive(folder / 'replacement.json', {'version': VERSION, 'child': 'child',
                'completion_sha256': sha256(folder / 'completion.json'), 'score_sha256': sha256(child / 'playable_score.json')})
            return verify_completion(out)
        except BaseException as exc:
            exclusive(folder / 'failure.json', {'type': type(exc).__name__, 'error': str(exc), 'traceback': traceback.format_exc()})
            raise
        finally:
            if not (folder / 'producer_end.json').exists():
                end = r.production()
                r.archive_producer(ROOT, end)
                exclusive(folder / 'producer_end.json', {'files': end})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    for name in ('inspect', 'execute', 'verify'):
        group.add_argument('--' + name, action='store_true')
    args = parser.parse_args(argv)
    installed()
    result = review_parent(args.out) if args.inspect else execute(args.out) if args.execute else verify_completion(args.out)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
