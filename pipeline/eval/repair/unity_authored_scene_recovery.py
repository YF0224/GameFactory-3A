"""One corrective plan plus one feedback replan, at most two 75s captures, only Kimi G004.

Run only after installation into the formal pipeline. Old failed output is read-only.
--execute is one-shot; --verify is read-only; --finalize never calls a model/native.
"""

from ..model_config import PLANNER_MODEL
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import traceback

# Match the authorized batch runner before record.py captures its slot count.
# Never alter another process or shared slot files; explicit caller values win.
os.environ.setdefault('A3GAME_GUI_SLOTS', '2')
os.environ.setdefault('A3GAME_CODEX_INLINE_SCHEMA', '1')
os.environ.setdefault('GAMEFACTORY_UNITY_IMGUI_FORWARD', '1')

from ..stage1 import prepare, plan, pipeline, playable_rules, unity_authored_scene as entry
from ..stage1.llm import READ_ONLY_INSTRUCTIONS, accepted_response, call_model, validate_schema
from ..stage1.paths import BENCH, FRAMEWORK, read_json, sha256, write_json

VERSION = 'stage1-g004-authored-scene-recovery.v1'
REL = Path('recovery/tuanjie_scene_v1')
ROOT = BENCH / 'test_data/outputs/eval/whitebox/stage1_playable_kimi_all_20261109__plan-gpt-6-astra'
OUT = ROOT / 'kimi_k3' / entry.GAME / 'retest'
MODELS = {'planner': PLANNER_MODEL, 'judge': 'none'}
CALL = 'plan_t1_authored_scene_correction_v1'
SECOND_CALL = 'plan_t2_authored_scene_v1'
SECOND_POLICY = 'one formal feedback replan; only operate unresolved and launch not FAIL'
PARENT = {
    '_kimi_batch/failure.json': '9385d1e408071d340b65fe2b8d6886c5150b65fb96b0f516a6fae6f231828c21',
    'takes/1/plan.json': 'b8ff13ab5632b81b5f3ec8f36a101761a2e07111e22313a1a1d5533c61a6bbf3',
    'takes/1/record/import_result.json': 'a393756a9cc899042430e80ab807659407d84362d45979c6b02eb62b6449dd1f',
}
OFFLINE_VERSION = 'stage1-g004-offline-finalization.v1'
SELF_REL = 'GameFactory-3A/pipeline/eval/stage1/unity_authored_scene_recovery.py'
OFFLINE_BOUND = {'module_sha256': '88f45eeb22067200d30e53c8745195e0e968524da7822ec5beafe998d25735e2', 'failure_sha256': '220186c9e3eb764337194023ed1724b97aeaa940b218993d8a6ac41ec5b77ff1', 'producer_start_sha256': '3146f3005f26ee58a19ec8dba3f4572095320077db1c2272ed89db2bf6d38a35', 'producer_end_sha256': '3146f3005f26ee58a19ec8dba3f4572095320077db1c2272ed89db2bf6d38a35', 'child_evidence_digest': '23a690068a0d63acc0a17ab6896d4d40c16bfd178e914d840b24c716a102e4e1'}

ALLOWED_NATIVE = {'capture_schedule.json', 'endpoint_settle_guards.json'}
require = entry.require


def runner():
    scripts = str(BENCH / 'scripts_new')
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import kimi_playable_retest
    return kimi_playable_retest


def installed():
    require(Path(__file__).resolve() == FRAMEWORK / 'pipeline/eval/stage1/unity_authored_scene_recovery.py',
            'install reviewed patch first; never execute draft/snapshot evaluation code')


def exclusive(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def inventory(root):
    return runner().files(Path(root))


def parent_files(out):
    out = Path(out)
    result = {}
    for n in ('manifest.json', 'status.json'):
        result[n] = sha256(out / n)
    for folder in ('takes', 'model_calls', '_kimi_batch'):
        result.update({folder + '/' + p: digest for p, digest in inventory(out / folder).items()})
    return result


def review_parent(out):
    out = Path(out).resolve()
    require(out == OUT.resolve() and not Path(out).is_symlink(), 'only canonical frozen Kimi G004 may recover')
    for rel, digest in PARENT.items():
        require(sha256(entry.safe_file(out, rel)) == digest, 'original failure/plan/import changed: ' + rel)
    manifest = prepare.verify(out)
    contract = entry.context(out)
    require(contract is not None and manifest['models'] == MODELS, 'wrong source or planner route')
    status = read_json(out / 'status.json')
    require(status.get('state') == 'HARNESS_ERROR' and status.get('step') == 'record_t1', 'parent not terminal pre-native failure')
    old = read_json(out / 'takes/1/plan.json')
    require(old['probes'] == [] and old['launch_source'] == entry.SCENE and old['max_duration_ms'] == 75000,
            'parent is not the exact missing-contract plan')
    responses = [accepted_response(out / 'model_calls', p.name) for p in (out / 'model_calls').iterdir() if p.is_dir()]
    require(old in responses, 'old accepted plan proof missing')
    imp = read_json(out / 'takes/1/record/import_result.json')
    require(imp['exit_code'] == 0 and imp['timeout'] is False and imp['product_errors'] is False, 'parent import not successful')
    require({p.name for p in (out / 'takes').iterdir()} == {'1'}, 'parent has another take')
    native = out / 'takes/1/record/native'
    require({p.name for p in native.iterdir()} == ALLOWED_NATIVE
            and all(p.is_file() and not p.is_symlink() for p in native.iterdir()), 'native gameplay/unknown artifacts already exist')
    for name in ('playable_score.json', 'takes/1/record/record_result.json', 'takes/1/record/adapter_result.json'):
        require(not (out / name).exists(), 'parent has scored/recorded evidence: ' + name)
    r = runner()
    claim = read_json(out / '_kimi_batch/attempt.json')
    target = claim['target']
    require(r.formal.result_dir(ROOT, target).resolve() == out and target['required_real_clients'] == 1
            and target['model'] == 'Kimi' and target['case'] == 'G004', 'target route differs')
    require(read_json(ROOT / '_kimi_batch/authorization.json') == r.authorization()
            and sha256(ROOT / '_kimi_batch/authorization.json') == claim['authorization_sha256'], 'authorization differs')
    scope = ROOT / '_kimi_batch/scopes' / (claim['scope_sha256'] + '.json')
    require(claim['scope_sha256'] == r.FULL_SHA and sha256(scope) == r.FULL_SHA
            and target in read_json(scope)['targets'], 'full60 target binding differs')
    source = r.source_binding(target, r.selection(target))
    require(source == claim['source'], 'original source manifest or requirement differs')
    return {'target': target, 'source': source, 'parent_files': parent_files(out),
            'contract': contract, 'native_takes_before': 0, 'max_native_takes': 2,
            'max_corrective_model_calls': 1, 'max_feedback_model_calls': 1,
            'max_new_model_calls': 2, 'native_duration_ms': 75000}


def short_manifest(child):
    m = prepare.verify(child)
    budget = dict(m['budget'])
    extra = 75000 - budget['gameplay_ms']
    for key in ('gameplay_ms', 'recording_ms', 'total_wall_clock_ms'):
        budget[key] += extra
    budget['engine_call_ms'] = max(budget['engine_call_ms'] + extra, budget['total_wall_clock_ms'])
    return {**m, 'budget': budget}


def corrected_plan(child, executable):
    m = short_manifest(child)
    contract = entry.context(child)
    validate_schema(executable, plan.schema('unity3d', 75000, ['play.launch', 'play.operate'], contract))
    plan.validate(executable, m, child / 'input/project')
    entry.validate_plan(child, executable)
    require(executable['max_duration_ms'] == 75000 and executable['probes'], 'corrected playable plan must span 75s and contain probes')
    steps = [s for p in executable['probes'] for s in p['steps']]
    require(any(s['kind'] == 'input' or s['kind'].startswith('mouse_') for s in steps),
            'corrected plan has no normal player inputs')


def accepted_plan(child, take=1):
    calls = child / 'model_calls'
    name = CALL if take == 1 else SECOND_CALL
    require(take in (1, 2) and {p.name for p in calls.iterdir()} <= {CALL, SECOND_CALL}
            and (calls / CALL).is_dir() and (calls / name).is_dir(), 'extra/corrective model attempts are forbidden')
    pointer = read_json(calls / name / 'accepted_response.json')
    require(pointer.get('attempt') == 1, 'corrective plan used another model attempt')
    invocation = read_json(calls / name / 'invocation.json')
    require(invocation.get('model_requested') == PLANNER_MODEL and invocation.get('attempt') == 1
            and invocation.get('exit_code') == 0, 'planner route/attempt not proven')
    executable = accepted_response(calls, name)
    require(executable is not None, 'corrected plan not accepted')
    corrected_plan(child, executable)
    return executable


def should_second(result):
    return result['checks'].get('play.operate') != 'PASS' and result['checks'].get('play.launch') != 'FAIL'


def rule_verdicts(child, count):
    # Use official deterministic rules without writing back over retained evidence.
    with tempfile.TemporaryDirectory(prefix='g004-rule-verify-') as temp:
        v = playable_rules.evaluate(child, read_json(child / 'manifest.json'), count, report_dir=Path(temp))
    return v


def rule_score(child, count):
    v = rule_verdicts(child, count)
    return {i: v[i]['status'] if i in v else 'HARNESS_ERROR' for i in playable_rules.IDS}


def second_feedback(child):
    verdicts = rule_verdicts(child, 1)
    return {'earlier_plans': [read_json(child / 'takes/1/plan.json')['summary']],
            'judge_reasons': {'play.operate': (verdicts.get('play.operate') or {}).get(
                'reason', 'no checkable input in the recording')}}


def verify_model_prompt(child, take):
    name = CALL if take == 1 else SECOND_CALL
    feedback = None if take == 1 else second_feedback(child)
    if take == 2:
        require(read_json(child / 'second_plan_feedback.json') == feedback, 'second-take feedback changed')
    rows = [r for r in read_json(child / 'input/criteria.json')['criteria']
            if r['id'] in ('play.launch', 'play.operate')]
    prompt = plan.prompt(short_manifest(child), rows, feedback, entry.context(child))
    require((child / 'model_calls' / name / 'prompt.txt').read_text().startswith(READ_ONLY_INSTRUCTIONS + prompt),
            'planner did not receive the bound source contract/feedback')


def native_proof(child, k):
    child = Path(child).resolve()
    capture = child / f'takes/{k}/record'
    native = capture / 'native'
    executable = accepted_plan(child, k)
    require(read_json(capture.parent / 'plan.json') == executable, 'take differs from sole accepted plan')
    entry.validate_plan(child, executable)
    entry.verify_runtime(child, capture)
    from .unity_natural_entry_recovery import cleanup_ok, verify_capture_files
    cleanup_ok(capture)
    report = read_json(native / 'report.json')
    result = read_json(capture / 'record_result.json')
    ed = report.get('editor_report', {})
    require(report.get('engine') == 'unity3d' and report.get('status') == 'passed'
            and not report.get('errors') and report.get('requested_seconds') == 75
            and ed.get('ok') is True and ed.get('duration') == 75
            and ed.get('actual_runtime_seconds', 0) >= 75, 'native 75s duration/startup is not proven')
    project = child / 'runtime/project'
    require(Path(report['url']).resolve() == project and Path(report['output_dir']).resolve() == native
            and Path(report['scene']).resolve() == project / entry.SCENE, 'native scene/project identity differs')
    command = read_json(native / 'editor_cleanup.json')['command']
    expected = {'-projectPath': str(project), '-executeMethod': 'GameFactory3APlayTestRecorder.Enter',
                '--gamefactory-evaluation-scene': str(project / entry.SCENE),
                '--gamefactory-evaluation-output': str(native), '--gamefactory-evaluation-duration': '75.0'}
    for flag, value in expected.items():
        require(command.count(flag) == 1 and command[command.index(flag) + 1] == value, 'native command differs: ' + flag)
    require(result['frames'] == report['frames'] and result['frames'] > 0 and not result['failed_actions']
            and result['plan_sha256'] == sha256(capture.parent / 'plan.json'), 'native frames/actions/plan failed')
    verify_capture_files(capture, result['frames'])
    actions = [json.loads(line) for line in (native / 'actions.jsonl').read_text().splitlines() if line.strip()]
    require(actions and any(a.get('action') in ('key', 'mouse_click', 'mouse_move', 'mouse_scroll')
                and a.get('sent') is True and a.get('source') == 'internal_driver'
                and not a.get('error') for a in actions)
            and report.get('executed_actions') and all(a.get('ok') is True and a.get('sent') is True
                for a in report['executed_actions']), 'internal native input proof missing')
    require(report.get('input_readiness', {}).get('input_transport') == 'internal', 'wrong input transport')
    binding = read_json(capture / 'authored_scene_entry.json')
    choice = read_json(capture / 'unity_editor.json')
    require(binding['scene_sha256'] == entry.BOUND[entry.SCENE]
            and binding['builder_invoked'] is False and binding['plan_sha256'] == sha256(capture.parent / 'plan.json')
            and binding['editor_choice_sha256'] == sha256(capture / 'unity_editor.json')
            and binding['actual_editor_version'] == choice['editor']['version']
            and binding['version_gap'] == choice['version_gap'], 'native contract/editor receipt differs')
    require(command[0] == choice['editor']['binary'], 'wrong editor binary')
    return {'take': k, 'actual_runtime_seconds': ed['actual_runtime_seconds'],
            'last_frame_seconds': report['recorded_seconds'], 'frames': result['frames'],
            'editor_choice': choice, 'native_report_sha256': sha256(native / 'report.json')}


def evidence(child):
    result = {}
    for name in ('manifest.json', 'status.json', 'playable_score.json', 'contract.json'):
        result[name] = sha256(child / name)
    for name in ('second_plan_feedback.json',):
        if (child / name).exists():
            result[name] = sha256(child / name)
    for folder in ('takes', 'model_calls'):
        result.update({folder + '/' + p: v for p, v in inventory(child / folder).items()})
    claims = child / 'authored_scene_plan_claims'
    # Only formal take2 planning creates this directory; explicit t1 does not.
    if claims.exists() or claims.is_symlink():
        result.update({'authored_scene_plan_claims/' + p: v for p, v in inventory(claims).items()})
    else:
        require(not (child / 'takes/2').exists(), 'second take plan claims missing')
    # Rules contain file references; preserve their exact output alongside native bytes.
    for p in child.glob('*playable*json'):
        result[p.name] = sha256(p)
    return result


def verify_completion(child):
    manifest = prepare.verify(child)
    parent = prepare.verify(OUT)
    require(manifest['suite'] == 'stage1' and manifest['models'] == MODELS
            and all(manifest[k] == parent[k] for k in
                    ('delivery', 'project_source', 'snapshot_digest', 'input_hashes', 'criteria_sha256')),
            'child source/requirements differ from frozen parent')
    require(read_json(child / 'contract.json') == entry.context(child), 'child contract differs')
    status = read_json(child / 'status.json')
    require(status.get('step') == 'playable' and status.get('state') == 'done'
            and status.get('complete') is True, 'child formal pipeline not complete')
    score = read_json(child / 'playable_score.json')
    require(score.get('complete') is True and score.get('game_id') == entry.GAME
            and score.get('engine') == 'unity3d' and score.get('planner') == MODELS['planner'], 'wrong/incomplete official score')
    seq = [r['take'] for r in score['takes']]
    require(seq in ([1], [1, 2]) and {p.name for p in (child / 'takes').iterdir()} == set(map(str, seq)),
            'unexpected or excess native take')
    require({p.name for p in (child / 'model_calls').iterdir()} ==
            ({CALL} if seq == [1] else {CALL, SECOND_CALL}), 'planner call count differs from takes')
    for k in seq:
        verify_model_prompt(child, k)
    if seq == [1, 2]:
        require(read_json(child / 'authored_scene_plan_claims/take2.json') == {
            'version': entry.VERSION, 'take': 2, 'max_model_calls': 1}, 'formal second plan claim differs')
        receipt = read_json(child.parent / 'second_plan.claim.json')
        require(receipt == {'call': SECOND_CALL, 'model': PLANNER_MODEL, 'max_attempts': 1,
                'feedback_sha256': sha256(child / 'second_plan_feedback.json'),
                'take1_files': inventory(child / 'takes/1')}, 'take1 replay or second plan lineage changed')
    proofs = [native_proof(child, k) for k in seq]
    first = rule_score(child, 1)
    require((len(seq) == 2) == should_second({'checks': first}), 'second take eligibility/completion differs')
    for row in score['takes']:
        require(row['checks'] == rule_score(child, row['take']), 'take history differs from official rules')
    checks = rule_score(child, len(seq))
    require('HARNESS_ERROR' not in checks.values() and score['checks'] == checks
            and score['version'] == playable_rules.VERSION
            and score['playable'] == round(100 * sum(v == 'PASS' for v in checks.values()) / 3, 2), 'score differs from official rules')
    return score, proofs


def verify_activation(out):
    folder = out / REL
    activation = read_json(folder / 'activation.json')
    proof = review_parent(out)
    require(activation['version'] == VERSION and activation['proof'] == proof, 'parent/source lineage changed')
    for rel, digest in proof['parent_files'].items():
        require(sha256(entry.safe_file(folder / 'parent_archive', rel)) == digest, 'parent archive changed')
    require(activation.get('max_model_calls') == 2 and activation.get('max_native_takes') == 2,
            'activation limits differ')
    require(read_json(folder / 'corrective_plan.claim.json') == {
        'call': CALL, 'model': PLANNER_MODEL, 'max_attempts': 1}, 'corrective plan claim differs')
    child = folder / 'child'
    require(read_json(folder / 'native_dispatch.claim.json') == {
        'native_takes_before': 0, 'max_native_takes': 2, 'duration_ms': 75000,
        'accepted_plan_sha256': sha256(child / 'takes/1/plan.json'),
        'second_take_policy': SECOND_POLICY},
        'native dispatch limits/plan differ')
    r = runner()
    start = read_json(folder / 'producer_start.json')['files']
    require(activation['producer_start_sha256'] == sha256(folder / 'producer_start.json'), 'start producer binding changed')
    for digest in set(start.values()):
        require(sha256(ROOT / '_kimi_batch/producer_blobs' / digest) == digest, 'producer archive changed')
    return activation, start


def evidence_digest(values):
    return hashlib.sha256(json.dumps(values, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def offline_lineage(folder, start, end, finalizer):
    """Exact failed t1 only. Validate old capture and new finalizer separately."""
    require(folder.resolve() == (OUT / REL).resolve(), 'foreign offline finalization')
    for name in ('failure', 'producer_start', 'producer_end'):
        require(sha256(entry.safe_file(folder, name + '.json')) == OFFLINE_BOUND[name + '_sha256'],
                'frozen offline parent changed: ' + name)
    require(start == end and start.get(SELF_REL) == OFFLINE_BOUND['module_sha256'],
            'recorded producer changed or is not the reviewed old module')
    changed = {p for p in set(end) | set(finalizer) if end.get(p) != finalizer.get(p)}
    require(changed == {SELF_REL} and set(end) == set(finalizer),
            'offline finalizer must change only the recovery module')
    child = folder / 'child'
    require({p.name for p in (child / 'takes').iterdir()} == {'1'}
            and {p.name for p in (child / 'model_calls').iterdir()} == {CALL}
            and not (child / 'authored_scene_plan_claims').exists()
            and not (child / 'authored_scene_plan_claims').is_symlink()
            and not (folder / 'second_plan.claim.json').exists(), 'offline recovery is only the retained single take')
    require(evidence_digest(evidence(child)) == OFFLINE_BOUND['child_evidence_digest'],
            'retained native/plan/score evidence changed')
    return {'version': OFFLINE_VERSION, 'mode': 'offline_only_no_model_no_native',
            'frozen': OFFLINE_BOUND, 'changed_files': {
                SELF_REL: {'recorded': start[SELF_REL], 'finalizer': finalizer[SELF_REL]}},
            'finalizer_producer': 'offline_finalizer_producer_v1.json',
            'finalizer_producer_digest': evidence_digest(finalizer)}


def retain_exact(path, value):
    if path.exists():
        require(read_json(path) == value, 'retained offline receipt differs: ' + str(path))
    else:
        exclusive(path, value)


def finalize(out):
    """Offline qualification only; no recording, model call or project deletion."""
    out = Path(out).resolve()
    folder, child = out / REL, out / REL / 'child'
    activation, start = verify_activation(out)
    require((folder / 'native_dispatch.claim.json').is_file(), 'native dispatch claim missing')
    r = runner()
    if not (folder / 'producer_end.json').exists():
        end = r.production()
        r.archive_producer(ROOT, end)
        exclusive(folder / 'producer_end.json', {'files': end})
    end = read_json(folder / 'producer_end.json')['files']
    current = r.production()
    offline = None
    if (folder / 'failure.json').exists():
        offline = offline_lineage(folder, start, end, current)
    else:
        require(r.producer_closure(start) == r.producer_closure(end) == r.producer_closure(current),
                'producer drift; retained evidence cannot be reclassified')
    score, proofs = verify_completion(child)
    if offline is not None:
        # Keep old failure/start/end untouched; archive current finalizer independently.
        r.archive_producer(ROOT, current)
        retain_exact(folder / 'offline_finalizer_producer_v1.json', {'files': current})
        offline['finalizer_producer_sha256'] = sha256(folder / 'offline_finalizer_producer_v1.json')
        retain_exact(folder / 'offline_finalization_v1.json', offline)
    receipt = {'version': VERSION, 'qualified': True, 'required_real_clients': 1,
               'child': 'child', 'score': score, 'native_proof': proofs,
               'activation_sha256': sha256(folder / 'activation.json'),
               'producer_end_sha256': sha256(folder / 'producer_end.json'),
               'claim_sha256': sha256(folder / 'native_dispatch.claim.json'),
               'child_files': evidence(child), 'parent_files': activation['proof']['parent_files'],
               'cleanup_policy': 'NATIVE_PROCESS_INPUT_VIEW_VERIFIED; KEEP_PROJECTS'}
    if offline is not None:
        receipt['offline_finalization_receipt'] = 'offline_finalization_v1.json'
        receipt['offline_finalization_sha256'] = sha256(folder / 'offline_finalization_v1.json')
    if (folder / 'replacement.json').exists():
        require(read_json(folder / 'replacement.json') == receipt, 'replacement already exists with different proof')
    else:
        exclusive(folder / 'replacement.json', receipt)
    return score


def qualified_replacement_score(out):
    """Runner hook: fail closed, never fall back to old failed score or redispatch."""
    try:
        out = Path(out).resolve()
        folder, child = out / REL, out / REL / 'child'
        receipt = read_json(folder / 'replacement.json')
        activation, start = verify_activation(out)
        r = runner()
        end = read_json(folder / 'producer_end.json')['files']
        require(receipt['version'] == VERSION and receipt['qualified'] is True and receipt['required_real_clients'] == 1
                and receipt['child'] == 'child' and receipt['parent_files'] == activation['proof']['parent_files']
                and receipt['activation_sha256'] == sha256(folder / 'activation.json')
                and receipt['producer_end_sha256'] == sha256(folder / 'producer_end.json')
                and receipt['claim_sha256'] == sha256(folder / 'native_dispatch.claim.json'), 'replacement lineage differs')
        require(r.producer_closure(start) == r.producer_closure(end), 'producer changed during capture')
        # Recorded producer is immutable. This exact offline repair pins its own producer separately.
        verifier = start
        if (folder / 'failure.json').exists() or 'offline_finalization_receipt' in receipt:
            require(receipt.get('offline_finalization_receipt') == 'offline_finalization_v1.json'
                    and receipt.get('offline_finalization_sha256') == sha256(folder / 'offline_finalization_v1.json'),
                    'offline finalization receipt missing/changed')
            finalizer = read_json(folder / 'offline_finalizer_producer_v1.json')['files']
            expected = offline_lineage(folder, start, end, finalizer)
            expected['finalizer_producer_sha256'] = sha256(folder / 'offline_finalizer_producer_v1.json')
            require(read_json(folder / 'offline_finalization_v1.json') == expected, 'offline lineage changed')
            for digest in set(finalizer.values()):
                require(sha256(ROOT / '_kimi_batch/producer_blobs' / digest) == digest, 'finalizer archive changed')
            verifier = finalizer
        for rel in ('pipeline/eval/stage1/unity_authored_scene.py', 'pipeline/eval/stage1/unity_authored_scene_recovery.py',
                    'pipeline/eval/stage1/playable_rules.py', 'pipeline/eval/stage1/unity_natural_entry_recovery.py'):
            require(sha256(FRAMEWORK / rel) == verifier['GameFactory-3A/' + rel], 'offline verifier changed')
        for digest in set(end.values()):
            require(sha256(ROOT / '_kimi_batch/producer_blobs' / digest) == digest, 'end producer archive changed')
        require(evidence(child) == receipt['child_files'], 'retained child evidence changed')
        score, proofs = verify_completion(child)
        require(receipt['score'] == score and receipt['native_proof'] == proofs, 'replacement proof differs')
        return score
    except (OSError, ValueError, KeyError, TypeError, RuntimeError):
        return None


def execute(out):
    installed()
    out = Path(out).resolve()
    require(out == OUT.resolve(), 'foreign recovery path')
    require(os.environ.get('GAMEFACTORY_UNITY_IMGUI_FORWARD') == '1', 'IMGUI transport must be enabled')
    r = runner()
    # Same per-target lock as the batch runner, plus original record postprocessing lock.
    with r.locked(ROOT / '_kimi_batch/locks/G004.lock'), r.locked(out / 'takes/1/record/.postprocess.lock'):
        proof = review_parent(out)
        folder = out / REL
        require(not folder.exists(), 'one-shot recovery already exists; verify/finalize only, no retry')
        r.check_disk(ROOT, proof['target'], proof['source'])
        start = r.production()
        r.archive_producer(ROOT, start)
        folder.mkdir(parents=True)
        for rel, digest in proof['parent_files'].items():
            dest = folder / 'parent_archive' / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(out / rel, dest)
            require(sha256(dest) == digest, 'parent changed while archiving')
        exclusive(folder / 'producer_start.json', {'files': start})
        exclusive(folder / 'activation.json', {'version': VERSION, 'proof': proof,
                  'producer_start_sha256': sha256(folder / 'producer_start.json'),
                  'pid': os.getpid(), 'max_model_calls': 2, 'max_native_takes': 2})
        child = folder / 'child'
        try:
            parent = read_json(out / 'manifest.json')
            prepare.prepare(Path(parent['delivery_dir']), child, models=MODELS, suite='stage1', playable_only=True)
            m = short_manifest(child)
            contract = entry.context(child)
            write_json(child / 'contract.json', contract)
            rows = [r for r in read_json(child / 'input/criteria.json')['criteria'] if r['id'] in ('play.launch', 'play.operate')]
            require({r['id'] for r in rows} == {'play.launch', 'play.operate'}, 'playable targets missing')
            exclusive(folder / 'corrective_plan.claim.json', {'call': CALL, 'model': PLANNER_MODEL, 'max_attempts': 1})
            executable = call_model(child / 'model_calls', name=CALL,
                prompt=plan.prompt(m, rows, authored_entry=contract),
                schema=plan.schema('unity3d', 75000, ['play.launch', 'play.operate'], contract),
                cwd=child / 'input', model=PLANNER_MODEL, max_attempts=1,
                timeout=m['budget']['plan_timeout_s'], validator=lambda p: corrected_plan(child, p))
            require(executable == accepted_plan(child), 'accepted corrective response differs')
            write_json(child / 'takes/1/plan.json', executable)
            r.check_disk(ROOT, proof['target'], proof['source'])
            require(r.producer_closure(start) == r.producer_closure(r.production()), 'producer drift before native dispatch')
            require(review_parent(out) == proof, 'parent/source changed before native dispatch')
            exclusive(folder / 'native_dispatch.claim.json', {'native_takes_before': 0, 'max_native_takes': 2,
                'duration_ms': 75000, 'accepted_plan_sha256': sha256(child / 'takes/1/plan.json'),
                'second_take_policy': SECOND_POLICY})
            result = pipeline.run_playable(Path(parent['delivery_dir']), child, models=MODELS, takes=1)
            native_proof(child, 1)
            if should_second(result):
                r.check_disk(ROOT, proof['target'], proof['source'])
                require(r.producer_closure(start) == r.producer_closure(r.production()), 'producer drift before second take')
                require(not (child / 'takes/2').exists(), 'second native take already exists')
                feedback = second_feedback(child)
                write_json(child / 'second_plan_feedback.json', feedback)
                retained = inventory(child / 'takes/1')
                exclusive(folder / 'second_plan.claim.json', {'call': SECOND_CALL, 'model': PLANNER_MODEL,
                    'max_attempts': 1, 'feedback_sha256': sha256(child / 'second_plan_feedback.json'),
                    'take1_files': retained})
                # Patched formal make_plan selects the authored-scene provider and max_attempts=1.
                second = plan.make_plan(child, m, 2, ['play.launch', 'play.operate'], feedback)
                corrected_plan(child, second)
                require(second == accepted_plan(child, 2), 'second plan differs from accepted feedback response')
                verify_model_prompt(child, 2)
                require(inventory(child / 'takes/1') == retained, 'first take changed during replan')
                require(r.producer_closure(start) == r.producer_closure(r.production()), 'producer drift before second native')
                require(review_parent(out) == proof, 'parent/source drift before second native')
                # Formal record() returns retained record_result.json for t1; only t2 is newly captured.
                result = pipeline.run_playable(Path(parent['delivery_dir']), child, models=MODELS, takes=2)
                require(inventory(child / 'takes/1') == retained, 'first take replayed/changed during second native')
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
    group.add_argument('--execute', action='store_true')
    group.add_argument('--verify', action='store_true')
    group.add_argument('--finalize', action='store_true')
    group.add_argument('--inspect', action='store_true')
    args = parser.parse_args(argv)
    installed()
    if args.execute:
        result = execute(args.out)
    elif args.verify:
        result = qualified_replacement_score(args.out)
        require(result is not None, 'no qualified G004 replacement')
    elif args.inspect:
        result = review_parent(args.out)
    else:
        require(args.out.resolve() == OUT.resolve(), 'foreign recovery path')
        with runner().locked(ROOT / '_kimi_batch/locks/G004.lock'):
            result = finalize(args.out.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
