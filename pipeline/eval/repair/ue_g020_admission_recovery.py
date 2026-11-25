"""Exact Kimi G020 pre-native admission recovery; retained parent, isolated child.

Install in the formal pipeline before execution. One activation, cached plan1,
at most two 75s native takes; only formal eligibility permits a feedback plan2.
No parent reset, deletion, score overwrite, automatic retry or project cleanup.
"""

from ..model_config import PLANNER_MODEL
import argparse
import json
import math
import os
from pathlib import Path
import shutil
import sys
import tempfile
import traceback

os.environ.setdefault('A3GAME_GUI_SLOTS', '2')
os.environ.setdefault('A3GAME_CODEX_INLINE_SCHEMA', '1')
from ..stage1 import pipeline, plan, playable_rules, prepare
from ..stage1.llm import accepted_response
from ..stage1.paths import BENCH, read_json, sha256

VERSION = 'stage1-kimi-g020-admission-recovery.v1'
REL = Path('recovery/ue_missing_recorder_v1')
from pipeline.eval.stage1.paths import DATA_ROOT
ROOT = DATA_ROOT / 'outputs/eval/whitebox/stage1_playable_kimi_all_20261109__plan-gpt-6-astra'
OUT = ROOT / 'kimi_k3/G020_tidal_glyphs/retest'
SELF = 'pipeline/eval/repair/ue_g020_admission_recovery.py'
MODELS = {'planner': PLANNER_MODEL, 'judge': 'none'}
IDENTITY = {'model': 'Kimi', 'case': 'G020', 'game_id': 'G020_tidal_glyphs',
            'engine': 'ue5', 'entry': 'TidalGlyphs.uproject', 'required_real_clients': 1}
PARENT = {
    '_kimi_batch/failure.json': 'e8000e5d87e5cbfa6a340fe81a3bbdefdc0a04264ae3fae535a46637c4f414dc',
    '_kimi_batch/attempt.json': '4ea735cc67ef8791fdd6f7e769dcdca037ecd6aa2b916c89072f9963bc59aced',
    '_kimi_batch/producer_start.json': '2d7e051f9e3ad049a006c2d592f76bd5fd35754b246a99742e678c9e0003ee86',
    '_kimi_batch/producer_end.json': 'e52f3d96f9ceb6633d10db12ae8f3629ccac397d38fdb79e4dcdc5e5e46d0c6f',
    'model_calls/plan_t1/accepted_response.json': '8e5f3e99bc79885c4c331aab961ab01001509f215cb313727856f37b2ba04169',
    'takes/1/plan.json': '9a2fe1071aca346b0bf687208a79764d2bfe473beba77b2a6b591061b53711e1',
    'manifest.json': 'ad2285b5b5281e600972daf9a0559e5c6ec9ec0692566689ddd15c931582f15c',
    'runtime/ue_admission/disk_admission.json': '7b73a243db70869d3988abd2903cbe6e2ab38722b0602593707d2f4d77d68353',
}
LIMITS = {'parent_native_takes': 0, 'max_total_native_takes': 2, 'recording_ms': 75000,
          'plan1': 'reuse exact accepted response; no new model call',
          'plan2': 'only operate != PASS and launch != FAIL; formal bounded correction <=2 responses',
          'cache_policy': 'KEEP_PROJECTS'}
HOLD = {'version': VERSION, 'qualified': False, 'require': 'verified replacement.json; retain this hold'}


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


def parent_tree(out):
    result = tree(out, skip=(str(REL),))
    # The shared flock file's bytes are evidence too; never remove/reset it.
    p = out / 'takes/1/record/.postprocess.lock'
    result[str(p.relative_to(out))] = sha256(plain(p))
    return result


def producer_archive(values):
    for value in set(values.values()):
        require(sha256(plain(ROOT / '_kimi_batch/producer_blobs' / value)) == value,
                'producer archive missing/changed')


def review_parent(out):
    out = plain(out)
    require(out.resolve() == OUT.resolve(), 'only exact canonical Kimi G020 may recover')
    for rel, value in PARENT.items():
        require(sha256(plain(out / rel)) == value, 'frozen parent changed: ' + rel)
    r = runner()
    claim = read_json(out / '_kimi_batch/attempt.json')
    t = claim['target']
    require(all(t.get(k) == v for k, v in IDENTITY.items()), 'wrong G020 identity')
    require(claim['models'] == MODELS and claim['max_takes'] == 2, 'parent budget/model changed')
    require(claim['scope_sha256'] == r.FULL_SHA, 'not frozen full60 scope')
    scope = ROOT / '_kimi_batch/scopes' / (r.FULL_SHA + '.json')
    require(sha256(plain(scope)) == r.FULL_SHA and t in read_json(scope)['targets'], 'scope changed')
    auth = ROOT / '_kimi_batch/authorization.json'
    require(sha256(plain(auth)) == claim['authorization_sha256']
            and read_json(auth) == r.authorization(), 'authorization changed')
    require(r.source_binding(t, r.selection(t)) == claim['source'], 'source/provenance changed')
    start = read_json(out / '_kimi_batch/producer_start.json')['files']
    require(start == read_json(out / '_kimi_batch/producer_end.json')['files'], 'historical producer drift')
    producer_archive(start)
    manifest = prepare.verify(out)
    require(manifest['project_source'] == t['project'] and manifest['models'] == MODELS
            and manifest['engine'] == 'ue5', 'parent manifest differs')
    delivery = Path(manifest['delivery_dir']) / 'delivery.json'
    require(read_json(delivery) == manifest['delivery'], 'delivery shim changed')
    require(snapshot_files(Path(t['project'])) == tree(out / 'input/project'),
            'original/frozen snapshot differ under formal prepare exclusions')
    require(tree(out / 'runtime/project') == tree(out / 'input/project'), 'parent working copy changed')
    status = read_json(out / 'status.json')
    require(status['step'] == 'record_t1' and status['state'] == 'HARNESS_ERROR', 'parent not terminal admission failure')
    require({p.name for p in (out / 'takes').iterdir()} == {'1'}, 'another parent take exists')
    record = out / 'takes/1/record'
    require({p.name for p in record.iterdir()} == {'native', '.postprocess.lock'}
            and (record / 'native').is_dir() and not list((record / 'native').iterdir()),
            'parent has native artifacts; zero-native policy no longer applies')
    require({p.name for p in (out / 'runtime/ue_admission').iterdir()} == {'disk_admission.json'},
            'parent admission progressed beyond installer failure')
    require({p.name for p in (out / 'model_calls').iterdir()} == {'plan_t1'}, 'extra parent model calls')
    executable = accepted_response(out / 'model_calls', 'plan_t1')
    require(executable is not None and executable == read_json(out / 'takes/1/plan.json'), 'accepted plan mismatch')
    plan.validate(executable, short_manifest(manifest), out / 'input/project')
    require(not (out / 'playable_score.json').exists(), 'unexpected canonical score')
    return {'target': t, 'source': claim['source'], 'parent_files': parent_tree(out),
            'delivery_sha256': sha256(delivery), 'limits': LIMITS}


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


def should_second(score):
    return score['checks'].get('play.operate') != 'PASS' and score['checks'].get('play.launch') != 'FAIL'


def rules(child, count):
    with tempfile.TemporaryDirectory(prefix='g020-rule-verify-') as temp:
        verdicts = playable_rules.evaluate(child, read_json(child / 'manifest.json'), count, report_dir=Path(temp))
    return {i: verdicts.get(i, {}).get('status', 'HARNESS_ERROR') for i in playable_rules.IDS}


def rows(path):
    return [json.loads(s) for s in path.read_text(encoding='utf-8-sig').splitlines() if s.strip()]


def input_proof(native, executable, launch, ready, *, allow_slate=False):
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
        if event.get('type') == 'slate_mouse':
            require(allow_slate is True, 'Slate input not authorized for this proof')
            packet = native_record.wire_message(event, launch['native_input_token'])
            require(all(request.get(k) == v for k, v in packet.items()), 'Slate host request differs')
            native_record.verify_mouse_receipt(receipt, event, ready, launch['pid'], launch['native_input_token'])
        else:
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
    if any(e.get('type') == 'slate_mouse' for e in events):
        require(allow_slate is True and '-A3NativeSlateMouse=viewport_button.v1' in launch['command'],
                'Slate launch policy missing')
        native_record.verify_mouse_cleanup(native, ready, launch['pid'], launch['native_input_token'])
        verification = read_json(native / 'verification.json')
        require(verification['slate_mouse_receipts'] == sum(e.get('type') == 'slate_mouse' for e in events)
                and verification['native_pointer_cleanup_sha256'] == sha256(native / 'native_pointer_cleanup.json'),
                'Slate verification/cleanup binding differs')
    return len(events)


def channel_proof(capture, native, name, *, expected_none=False):
    collected, source = plain(capture / name), plain(native / name)
    require(collected.is_file(), 'missing collected channel: ' + name)
    if source.exists():
        require(source.is_file() and collected.read_bytes() == source.read_bytes(),
                'collected channel differs: ' + name)
    else:
        require(name != 'frame_index.jsonl' and expected_none is True
                and collected.read_bytes() == b'', 'unexpected missing native channel: ' + name)


def native_proof(child, take, *, expected_empty=(), allow_slate=False):
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
    require(command[1] == str(project / 'TidalGlyphs.uproject') and '-game' in command
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
    inputs = input_proof(native, read_json(capture.parent / 'plan.json'), launch, ready, allow_slate=allow_slate)
    verification = read_json(native / 'verification.json')
    require(verification['ok'] is True and verification['native_receipts'] == inputs
            and verification['capture_audit'] == audit
            and verification['pin_sha256'] == sha256(child / 'runtime/ue_admission/pin.json'), 'native verification mismatch')
    for name in ('frame_index.jsonl', 'actions.jsonl', 'state_trace.jsonl', 'event_trace.jsonl'):
        expected_none = ((name == 'actions.jsonl' and inputs == 0 and result.get('actions') == 0)
                         or (name in ('state_trace.jsonl', 'event_trace.jsonl') and name in expected_empty))
        expected_none = expected_none and result.get('channels', {}).get(name) is False
        channel_proof(capture, native, name, expected_none=expected_none)
    for frame in rows(native / 'frame_index.jsonl'):
        rel = Path(frame['path'])
        require(not rel.is_absolute() and '..' not in rel.parts, 'external frame')
        require(sha256(plain(native / rel)) == sha256(plain(capture / rel)), 'collected frame differs')
    return {'take': take, 'frames': result['frames'], 'actual_clock_ms': elapsed,
            'native_verification_sha256': sha256(native / 'verification.json')}


def verify_child(child, proof):
    parent = prepare.verify(OUT)
    manifest = prepare.verify(child)
    require(all(manifest[k] == parent[k] for k in ('delivery', 'delivery_dir', 'project_source', 'snapshot_digest',
            'project_digest', 'input_hashes', 'criteria_sha256', 'models', 'suite', 'engine')), 'child frozen inputs differ')
    require(tree(child / 'model_calls/plan_t1') == tree(OUT / 'model_calls/plan_t1')
            and sha256(child / 'takes/1/plan.json') == PARENT['takes/1/plan.json'], 'cached plan1/call changed')
    status = read_json(child / 'status.json')
    require(status['state'] == 'done' and status['step'] == 'playable' and status['complete'] is True, 'child not complete')
    score = read_json(child / 'playable_score.json')
    require(score['complete'] is True and score['game_id'] == IDENTITY['game_id'] and score['engine'] == 'ue5'
            and score['planner'] == MODELS['planner'] and score['version'] == playable_rules.VERSION, 'wrong official score')
    seq = [x['take'] for x in score['takes']]
    require(seq in ([1], [1, 2]) and {p.name for p in (child / 'takes').iterdir()} == set(map(str, seq)), 'excess/partial takes')
    names = {p.name for p in (child / 'model_calls').iterdir()}
    require(names == {'plan_t1'} if seq == [1] else names in ({'plan_t1', 'plan_t2'}, {'plan_t1', 'plan_t2', 'plan_t2_002'}),
            'extra model calls')
    require((len(seq) == 2) == should_second({'checks': rules(child, 1)}), 'second take eligibility differs')
    if len(seq) == 2:
        require(read_json(child.parent / 'second_plan.claim.json') == {'take': 2, 'max_model_responses': 2,
                'first_take_files': tree(child / 'takes/1')}, 'take1 changed/second plan claim differs')
        pointer = read_json(child / 'model_calls/plan_t2/accepted_response.json')
        require(type(pointer['attempt']) is int and pointer['attempt'] in (1, 2), 'plan2 correction budget exceeded')
        require(names == ({'plan_t1', 'plan_t2'} if pointer['attempt'] == 1 else {'plan_t1', 'plan_t2', 'plan_t2_002'}), 'plan2 call count differs')
        require(accepted_response(child / 'model_calls', 'plan_t2') == read_json(child / 'takes/2/plan.json'), 'plan2 not accepted')
        for name in names - {'plan_t1'}:
            require(read_json(child / 'model_calls' / name / 'invocation.json')['model_requested'] == MODELS['planner'], 'plan2 model route differs')
    for k in seq:
        plan.validate(read_json(child / f'takes/{k}/plan.json'), short_manifest(manifest), child / 'input/project')
        require(score['takes'][k-1]['checks'] == rules(child, k), 'take checks differ from official rules')
    checks = rules(child, seq[-1])
    require('HARNESS_ERROR' not in checks.values() and score['checks'] == checks
            and score['playable'] == round(100 * sum(x == 'PASS' for x in checks.values()) / 3, 2), 'official score differs')
    from engine_adapters.ue5.playtest.native_record import verify_pin
    admission = read_json(child / 'runtime/ue_admission/admission.json')
    require(admission['project'] == str(child / 'runtime/project')
            and admission['source_project'] == str(child / 'input/project')
            and admission['pin'] == str(child / 'runtime/ue_admission/pin.json'), 'admission copy identity differs')
    require(admission['uproject'] == str(child / 'runtime/project/TidalGlyphs.uproject'), 'admitted marker differs')
    require(read_json(Path(admission['pin']))['build_receipt_sha256'] ==
            sha256(child / 'runtime/ue_admission/build.json'), 'build receipt binding differs')
    verify_pin(admission)
    require(read_json(child / 'runtime/ue_admission/build.json')['ok'] is True, 'build not successful')
    verify_overlay(child)
    return score, [native_proof(child, k) for k in seq]


def verify_overlay(child):
    from engine_adapters.ue5.playtest.native_admission import source_manifest
    folder, project = child / 'runtime/ue_admission', child / 'runtime/project'
    original = source_manifest(child / 'input/project')
    binding = read_json(folder / 'source_binding.json')
    require(binding == {'source_project': str(child / 'input/project'), 'validation_project': str(project),
            'files': original, 'status': 'SOURCE_BOUND_BEFORE_ADAPTER_OVERLAY'}, 'overlay source binding differs')
    overlay = read_json(folder / 'overlay.json')
    require(overlay['mode'] == 'absent_plugin_recorder_only.v1'
            and overlay['source_binding'] == str(folder / 'source_binding.json'), 'wrong overlay mode/binding')
    allowed = {x['path']: x['after_sha256'] for x in overlay['overlays']}
    prefix = 'Plugins/A3GamePlayable/'
    expected = {prefix + n for n in ['A3GamePlayable.uplugin',
        'Source/A3GamePlayable/A3GamePlayable.Build.cs', 'Source/A3GamePlayable/Public/A3GamePlayableModule.h',
        'Source/A3GamePlayable/Private/A3GamePlayableModule.cpp',
        'Source/A3GamePlayable/Public/Playtest/A3GamePlaytestRecorderSubsystem.h',
        'Source/A3GamePlayable/Private/Playtest/A3GamePlaytestRecorderSubsystem.cpp']}
    require(set(allowed) == expected | {'TidalGlyphs.uproject'} and len(overlay['overlays']) == 7, 'unexpected overlay paths')
    require(source_manifest(project) == {**original, **allowed}, 'runtime authored source/content differs')
    for row in overlay['overlays']:
        if row['path'] in expected:
            require(row['before_sha256'] is None and row['before_archive'] is None
                    and row['formal_source'] == str(BENCH / 'engine_adapters/ue5/plugin/A3GamePlayable' / row['path'][len(prefix):])
                    and row['formal_source_sha256'] == row['after_sha256'] == sha256(plain(Path(row['formal_source']))),
                    'non-formal recorder scaffold')
        else:
            require(row['before_sha256'] == original[row['path']]
                    and row['before_archive'] == str(folder / 'before' / row['path'])
                    and sha256(folder / 'before' / row['path']) == row['before_sha256'], 'marker archive changed')
    before = read_json(child / 'input/project/TidalGlyphs.uproject')
    after = read_json(project / 'TidalGlyphs.uproject')
    require(after == {**before, 'Plugins': before.get('Plugins', []) + [{'Name': 'A3GamePlayable', 'Enabled': True}]},
            'project marker changed beyond enabling recorder')


def verify_activation(out):
    folder = out / REL
    activation = read_json(plain(folder / 'activation.json'))
    proof = review_parent(out)
    require(activation == {'version': VERSION, 'proof': proof, 'limits': LIMITS,
            'producer_start_sha256': sha256(folder / 'producer_start.json')}, 'activation/parent/source changed')
    require(read_json(folder / 'qualification_hold.json') == HOLD, 'qualification hold changed')
    for rel, value in proof['parent_files'].items():
        require(sha256(plain(folder / 'parent_archive' / rel)) == value, 'parent archive changed: ' + rel)
    start = read_json(folder / 'producer_start.json')['files']
    producer_archive(start)
    return proof, start


def evidence(child):
    return tree(child, skip=('input/project', 'runtime/project'))


def verify_completion(out):
    out = plain(out)
    proof, start = verify_activation(out)
    folder, child = out / REL, out / REL / 'child'
    require(not (folder / 'failure.json').exists(), 'failed recovery needs separately reviewed offline lineage')
    require(read_json(folder / 'native_dispatch.claim.json') == LIMITS, 'native dispatch budget changed')
    end = read_json(folder / 'producer_end.json')['files']
    require(runner().producer_closure(start) == runner().producer_closure(end), 'producer drift during recovery')
    producer_archive(end)
    score, native = verify_child(child, proof)
    require(read_json(folder / 'completion.json') == {'version': VERSION, 'qualified': True, 'score': score,
            'native': native, 'child_evidence': evidence(child), 'cache_policy': 'KEEP_PROJECTS',
            'freed_bytes': 0, 'producer_end_sha256': sha256(folder / 'producer_end.json')}, 'completion seal changed')
    require(read_json(folder / 'replacement.json') == {'version': VERSION, 'child': 'child',
            'activation_sha256': sha256(folder / 'activation.json'),
            'completion_sha256': sha256(folder / 'completion.json'),
            'score_sha256': sha256(child / 'playable_score.json')}, 'replacement binding changed')
    return score


def qualified_replacement_score(out):
    try:
        if (Path(out) / REL / 'continuation_v1').exists():
            from .ue_g020_capture_continuation import verify_completion as verify_continuation
            return verify_continuation(out)
        return verify_completion(out)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError):
        return None


def finalize(out):
    installed()
    out = plain(out)
    proof, start = verify_activation(out)
    folder, child = out / REL, out / REL / 'child'
    require(not (folder / 'failure.json').exists(), 'failed recovery retained; no implicit retry')
    if (folder / 'replacement.json').exists():
        return verify_completion(out)
    require(read_json(folder / 'native_dispatch.claim.json') == LIMITS, 'missing native budget claim')
    current = runner().production()
    require(runner().producer_closure(start) == runner().producer_closure(current), 'producer drift before finalization')
    score, native = verify_child(child, proof)
    runner().archive_producer(ROOT, current)
    if not (folder / 'producer_end.json').exists():
        exclusive(folder / 'producer_end.json', {'files': current})
    require(read_json(folder / 'producer_end.json')['files'] == current, 'end producer differs')
    exclusive(folder / 'completion.json', {'version': VERSION, 'qualified': True, 'score': score,
        'native': native, 'child_evidence': evidence(child), 'cache_policy': 'KEEP_PROJECTS', 'freed_bytes': 0,
        'producer_end_sha256': sha256(folder / 'producer_end.json')})
    exclusive(folder / 'replacement.json', {'version': VERSION, 'child': 'child',
        'activation_sha256': sha256(folder / 'activation.json'),
        'completion_sha256': sha256(folder / 'completion.json'), 'score_sha256': sha256(child / 'playable_score.json')})
    return verify_completion(out)


def execute(out):
    installed()
    out = plain(out)
    require(out.resolve() == OUT.resolve(), 'foreign recovery')
    r = runner()
    with r.locked(ROOT / '_kimi_batch/locks/G020.lock'), r.locked(out / 'takes/1/record/.postprocess.lock'):
        proof = review_parent(out)
        folder, child = out / REL, out / REL / 'child'
        require(not folder.exists(), 'one-shot recovery already claimed; preserve partial child')
        r.check_disk(ROOT, proof['target'], proof['source'])
        start = r.production()
        r.archive_producer(ROOT, start)
        folder.mkdir(parents=True, exist_ok=False)
        exclusive(folder / 'qualification_hold.json', HOLD)
        exclusive(folder / 'producer_start.json', {'files': start})
        exclusive(folder / 'activation.json', {'version': VERSION, 'proof': proof, 'limits': LIMITS,
            'producer_start_sha256': sha256(folder / 'producer_start.json')})
        try:
            for rel in proof['parent_files']:
                dest = folder / 'parent_archive' / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                with dest.open('xb') as f:
                    f.write((out / rel).read_bytes())
            parent = prepare.verify(out)
            manifest = prepare.prepare(Path(parent['delivery_dir']), child, models=MODELS, suite='stage1', playable_only=True)
            require(all(manifest[k] == parent[k] for k in ('delivery', 'project_source', 'snapshot_digest', 'input_hashes', 'criteria_sha256')),
                    'new child input differs')
            shutil.copytree(out / 'model_calls', child / 'model_calls')
            (child / 'takes/1').mkdir(parents=True)
            for name in ('plan.json', 'plan_coverage.json'):
                shutil.copyfile(out / 'takes/1' / name, child / 'takes/1' / name)
            require(review_parent(out) == proof, 'parent changed during preparation')
            require(r.producer_closure(start) == r.producer_closure(r.production()), 'producer drift before native')
            exclusive(folder / 'native_dispatch.claim.json', LIMITS)
            result = pipeline.run_playable(Path(parent['delivery_dir']), child, models=MODELS, takes=1)
            native_proof(child, 1)
            if should_second(result):
                require(review_parent(out) == proof, 'parent/source changed before second take')
                require(r.producer_closure(start) == r.producer_closure(r.production()), 'producer drift before plan2')
                r.check_disk(ROOT, proof['target'], proof['source'])
                retained = tree(child / 'takes/1')
                exclusive(folder / 'second_plan.claim.json', {'take': 2, 'max_model_responses': 2, 'first_take_files': retained})
                # Formal pipeline reuses cached plan/record1 and creates feedback plan2 only when needed.
                pipeline.run_playable(Path(parent['delivery_dir']), child, models=MODELS, takes=2)
                require(tree(child / 'takes/1') == retained, 'first take changed/replayed')
            return finalize(out)
        except BaseException as exc:
            if not (folder / 'producer_end.json').exists():
                end = r.production()
                r.archive_producer(ROOT, end)
                exclusive(folder / 'producer_end.json', {'files': end})
            exclusive(folder / 'failure.json', {'type': type(exc).__name__, 'error': str(exc), 'traceback': traceback.format_exc()})
            raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    for name in ('inspect', 'execute', 'finalize', 'verify'):
        group.add_argument('--' + name, action='store_true')
    args = parser.parse_args(argv)
    installed()
    if args.inspect:
        result = review_parent(args.out)
    elif args.execute:
        result = execute(args.out)
    elif args.finalize:
        with runner().locked(ROOT / '_kimi_batch/locks/G020.lock'):
            result = finalize(args.out)
    else:
        result = verify_completion(args.out)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
