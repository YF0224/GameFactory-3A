"""Exact Kimi G009 zero-native recovery. Install formally before --execute.

One original builder invocation on a fresh runtime copy; one corrective plan,
optional feedback plan2, at most two actual 75s takes. No original changes,
scene fabrication, parent replay, snapshot execution, cleanup deletion or judge.
"""

from ..model_config import PLANNER_MODEL
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import traceback

os.environ.setdefault('A3GAME_GUI_SLOTS', '2')
os.environ.setdefault('A3GAME_CODEX_INLINE_SCHEMA', '1')
os.environ.setdefault('GAMEFACTORY_UNITY_IMGUI_FORWARD', '1')

from ..stage1 import plan, prepare, pipeline, playable_rules, record, unity_input, unity_editor
from ..stage1.llm import accepted_response, validate_schema, READ_ONLY_INSTRUCTIONS
from ..stage1.paths import BENCH, FRAMEWORK, read_json, sha256, write_json

VERSION = 'stage1-kimi-g009-handler-builder-recovery.v1'
REL = Path('recovery/kimi_builder_v1')
ROOT = BENCH / 'test_data/outputs/eval/whitebox/stage1_playable_kimi_all_20261109__plan-gpt-6-astra'
GAME = 'G009_blackout_stealth'
OUT = ROOT / 'kimi_k3' / GAME / 'retest'
SELF = 'GameFactory-3A/pipeline/eval/stage1/unity_g009_builder_recovery.py'
SOURCE = 'Assets/Blackout/Editor/BlackoutSceneBuilder.cs'
SOURCE_SHA = 'b054eae738fc88e6d505a520f2200be2af94cbfce3a19c33cb6d7a3bddecde10'
METHOD = 'BlackoutStealth.Whitebox.EditorTools.BlackoutSceneBuilder.Build'
SCENE = 'Assets/Scenes/BlackoutStealth.unity'
DONE = '[SCENE-BUILD] done -> ' + SCENE
PARENT_DIGEST = 'd80a401bd23abef7597713ab67fd41d4561d5d4198f76761a4380a2f6a428487'
MODELS = {'planner': PLANNER_MODEL, 'judge': 'none'}
LIMITS = {'parent_native_takes': 0, 'max_new_native_takes': 2, 'max_builder_calls': 1,
          'max_new_planner_calls': 2, 'max_attempts_per_call': 1, 'duration_ms': 75000,
          'cache_policy': 'KEEP_PROJECTS'}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def runner():
    scripts = str(BENCH / 'scripts_new')
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import kimi_playable_retest
    return kimi_playable_retest


def plain(path):
    path = Path(path).absolute()
    require(not any(p.is_symlink() for p in (path, *path.parents)), 'linked path: ' + str(path))
    return path


def exclusive(path, value):
    path = plain(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def files(path):
    return runner().files(plain(path))


def parent_files(out):
    result = {n: sha256(plain(out / n)) for n in ('manifest.json', 'status.json')}
    for folder in ('takes', 'model_calls', '_kimi_batch'):
        result.update({folder + '/' + k: v for k, v in files(out / folder).items()})
    return result


def no_native(out):
    require({p.name for p in (out / 'takes').iterdir()} == {'1'}, 'parent take budget differs')
    native = out / 'takes/1/record/native'
    require(native.is_dir() and not list(native.iterdir()), 'parent already has native artifacts')
    names = {p.name for p in (out / 'takes/1/record').iterdir()}
    require(names <= {'native', 'unity_editor.json', '.postprocess.lock'} and 'unity_editor.json' in names,
            'parent advanced beyond input migration')
    require(not (out / 'playable_score.json').exists(), 'completed parent must not replay')


def snapshot_files(root):
    result = {}
    for directory, dirs, names in os.walk(root):
        ignored = prepare.IGNORE(directory, dirs + names)
        dirs[:] = [d for d in dirs if d not in ignored]
        for name in names:
            if name not in ignored:
                path = plain(Path(directory) / name)
                result[path.relative_to(root).as_posix()] = sha256(path)
    return result


def producer_archive(producer):
    for value in set(producer.values()):
        require(sha256(plain(ROOT / '_kimi_batch/producer_blobs' / value)) == value, 'producer blob changed')


def review_parent(out):
    out = plain(out).resolve()
    require(out == OUT.resolve(), 'only canonical frozen Kimi G009 may recover')
    retained = parent_files(out)
    require(digest(retained) == PARENT_DIGEST, 'parent failure/plan/claims/producer changed')
    no_native(out)
    claim = read_json(out / '_kimi_batch/attempt.json')
    target = claim['target']
    require(all(target.get(k) == v for k, v in {'model': 'Kimi', 'case': 'G009', 'game_id': GAME,
                'engine': 'unity3d', 'entry': 'ProjectSettings/ProjectVersion.txt', 'required_real_clients': 1}.items()),
            'wrong original identity or multiplayer target')
    r = runner()
    scope = Path(target['source']).parent.parent / 'targets.json'
    require(sha256(plain(scope)) == r.FULL_SHA and target in read_json(scope)['targets'], 'scope changed')
    auth = ROOT / '_kimi_batch/authorization.json'
    require(sha256(plain(auth)) == claim['authorization_sha256'] and read_json(auth) == r.authorization(),
            'authorization changed')
    require(r.source_binding(target, r.selection(target)) == claim['source'], 'source selection changed')
    manifest = prepare.verify(out)
    require(manifest['suite'] == 'stage1' and manifest['models'] == MODELS
            and manifest['engine'] == 'unity3d' and manifest['project_source'] == target['project'], 'parent binding differs')
    require(read_json(Path(manifest['delivery_dir']) / 'delivery.json') == manifest['delivery'], 'delivery shim changed')
    require(snapshot_files(Path(target['project'])) == files(out / 'input/project'), 'original snapshot differs')
    for base in (Path(target['project']), out / 'input/project'):
        require(sha256(plain(base / SOURCE)) == SOURCE_SHA and not list((base / 'Assets').rglob('*.unity')),
                'builder source changed or original scene present')
        _, binding = unity_input._handler_update((base / 'ProjectSettings/ProjectSettings.asset').read_text())
        require(binding['before_present'] is False, 'parent is not absent-handler canonical YAML')
    status = read_json(out / 'status.json')
    require(status['step'] == 'record_t1' and status['state'] == 'HARNESS_ERROR'
            and status['error'] == 'Unity input migration failed: cannot uniquely bind the input handler setting',
            'different parent failure')
    old = read_json(out / 'takes/1/plan.json')
    require({p.name for p in (out / 'model_calls').iterdir()} == {'plan_t1', 'plan_t1_002'}
            and read_json(out / 'model_calls/plan_t1/accepted_response.json')['attempt'] == 2
            and accepted_response(out / 'model_calls', 'plan_t1') == old and old['probes'] == []
            and old['launch_source'] == 'ProjectSettings/ProjectVersion.txt', 'parent accepted empty plan differs')
    for phase in ('start', 'end'):
        producer_archive(read_json(out / f'_kimi_batch/producer_{phase}.json')['files'])
    return {'target': target, 'source': claim['source'], 'parent_files': retained, 'limits': LIMITS,
            'delivery_sha256': sha256(Path(manifest['delivery_dir']) / 'delivery.json')}


def safe_environment():
    require(not any(os.environ.get(k) for k in ('BLACKOUT_SMOKE_DIR', 'BLACKOUT_REVIEW_DIR', 'BLACKOUT_BUILD_DIR')),
            'author smoke/build automation environment must be absent')


def short_manifest(child):
    m = prepare.verify(child)
    budget = dict(m['budget'])
    extra = 75000 - budget['gameplay_ms']
    for key in ('gameplay_ms', 'recording_ms', 'total_wall_clock_ms'):
        budget[key] += extra
    budget['engine_call_ms'] = max(budget['engine_call_ms'] + extra, budget['total_wall_clock_ms'])
    require(budget['gameplay_ms'] == budget['recording_ms'] == 75000, 'non-75s budget')
    return {**m, 'budget': budget}


def validate_builder_result(result, log):
    # The original void Build() does not implement the adapter's JSON-report protocol.
    # Accept ONLY its exact no-report exit0 fallback plus saved scene and author log.
    require(result.get('transport') != 'live_editor_bridge' and result.get('returncode') == 0
            and result.get('timed_out') is not True and result.get('class_method') == METHOD,
            'builder did not complete in the isolated synchronous batch process')
    require(result.get('ok') is False and str(result.get('error', '')).startswith('Unity wrote no report file (exit 0);'),
            'unexpected builder adapter report; review before accepting')
    require(DONE in log and not re.search(r'error CS\d+|Scripts have compiler errors|executeMethod.*(?:exception|failed)', log, re.I),
            'authored builder failed; preserve diagnostics, do not repair author code')


def verify_scripts(child):
    """Original C# is byte-identical except the formal device-read rewrite."""
    frozen, runtime = child / 'input/project', child / 'runtime/project'
    migration = read_json(child / 'runtime/unity_input_migration.json')
    changes = {r['path']: r for r in migration.get('changes', [])}
    require(migration.get('gameplay_changes') == [], 'gameplay migration forbidden')
    for source in (frozen / 'Assets').rglob('*.cs'):
        rel = source.relative_to(frozen).as_posix()
        actual = plain(runtime / rel)
        before = source.read_bytes()
        if actual.read_bytes() == before:
            require(rel not in changes, 'migration receipt contradicts source')
        else:
            expected = unity_input.migrate_device_reads(before.decode()).encode()
            require(actual.read_bytes() == expected and changes.get(rel) == {
                'path': rel, 'kind': 'input_device_reads_only', 'before_sha256': sha256(source),
                'after_sha256': sha256(actual)}, 'author script changed: ' + rel)
    require(sha256(runtime / SOURCE) == SOURCE_SHA, 'original builder modified')


def builder_cleanup(project):
    """Read-only check of this exact fresh runtime path; never kill or unlock anything."""
    import psutil
    from engine_adapters.unity3d._internal.transport.unity_editor import _editor_instance_is_live
    matches = []
    for proc in psutil.process_iter(['pid', 'cmdline']):
        args = proc.info.get('cmdline') or []
        for index, arg in enumerate(args[:-1]):
            if arg.lower() == '-projectpath' and Path(args[index + 1]).resolve() == project.resolve():
                matches.append(proc.info['pid'])
    require(not matches and not _editor_instance_is_live(project), 'builder project still has a live editor')
    return {'project': str(project), 'process_cleanup_ok': True, 'matching_project_pids': matches,
            'live_editor_instance': False, 'input_created': False, 'view_created': False}


def build_once(child):
    from engine_adapters.unity3d.config import UnityClientConfig
    from engine_adapters.unity3d._internal.transport.unity_editor import UnityEditorTransport, _editor_instance_is_live
    safe_environment()
    project, folder = child / 'runtime/project', child / 'builder'
    require(not folder.exists() and not (project / SCENE).exists(), 'builder already attempted or scene exists')
    require(prepare.tree_digest(prepare.tree_hashes(project)) == prepare.verify(child)['snapshot_digest'],
            'builder requires fresh original runtime snapshot')
    choice = unity_editor.choose(project)  # same-family chooser, version_gap retained
    exclusive(folder / 'claim.json', {'method': METHOD, 'source_sha256': SOURCE_SHA, 'editor': choice, 'limits': LIMITS})
    # Use the parent's repaired formal migration; do not inherit partially changed parent runtime.
    migration = unity_input.migrate(project, child / 'runtime/unity_input_migration.json')
    exclusive(folder / 'input_migration.json', migration)
    require(migration.get('gameplay_changes') == [], 'unexpected gameplay mutation')
    before = snapshot_files(project)
    exclusive(folder / 'runtime_before.json', before)
    require(not _editor_instance_is_live(project), 'fresh child unexpectedly has a live editor')
    config = UnityClientConfig.resolve(project_path=project, unity_root=choice['editor']['binary'])
    with record._record_lock(child, 1), record.gui_slot() as slot:
        check_unity_disk(child)
        result = UnityEditorTransport(config).execute_method(METHOD, timeout=600)
        exclusive(folder / 'execution.json', {**result, 'gui_slot': str(slot)})
        # Retain exact adapter-produced job/log/report bytes. Never execute archive bytes.
        for key in ('job_path', 'log_path', 'report_path'):
            if result.get(key) and Path(result[key]).is_file():
                shutil.copyfile(result[key], folder / (key + Path(result[key]).suffix))
    log = result.get('stdout', '')
    validate_builder_result(result, log)
    exclusive(folder / 'cleanup.json', builder_cleanup(project))
    require((project / SCENE).is_file() and sha256(project / SOURCE) == SOURCE_SHA, 'authored scene/save proof missing')
    verify_scripts(child)
    after = snapshot_files(project)
    # Retain all import/builder changes. Existing gameplay assets may not change.
    # Unity serializes ProjectSettings/metadata; generated author outputs live only in Scenes/Settings.
    changed = {k for k in before if before[k] != after.get(k)}
    require(all(k.startswith('ProjectSettings/') or k.startswith('Assets/Settings/')
                for k in changed), 'builder changed existing non-settings assets: ' + str(sorted(changed)))
    added_code = {k for k in after.keys() - before.keys() if k.endswith('.cs')}
    bridge = 'Assets/Editor/GameFactory3AEditorBridge.cs'
    require(added_code <= {bridge}, 'unreviewed generated C#')
    if bridge in added_code:
        require(after[bridge] == sha256(FRAMEWORK / 'engine_adapters/unity3d/import_generated/GameFactory3AEditorBridge.cs'),
                'bridge differs from formal adapter')
    exclusive(folder / 'runtime_after.json', after)
    receipt = {'method': METHOD, 'source_sha256': SOURCE_SHA, 'scene': SCENE, 'scene_sha256': sha256(project / SCENE),
               'editor': choice, 'execution_sha256': sha256(folder / 'execution.json'),
               'cleanup_sha256': sha256(folder / 'cleanup.json'),
               'before_sha256': sha256(folder / 'runtime_before.json'), 'after_sha256': sha256(folder / 'runtime_after.json'),
               'author_smoke_environment': 'absent', 'calls': 1}
    exclusive(folder / 'receipt.json', receipt)
    return receipt


def contract(child):
    receipt = read_json(child / 'builder/receipt.json')
    require(receipt['method'] == METHOD and receipt['source_sha256'] == SOURCE_SHA
            and receipt['calls'] == 1 and receipt['scene'] == SCENE, 'builder receipt differs')
    require(receipt['execution_sha256'] == sha256(child / 'builder/execution.json')
            and receipt['before_sha256'] == sha256(child / 'builder/runtime_before.json')
            and receipt['after_sha256'] == sha256(child / 'builder/runtime_after.json'), 'builder binding differs')
    cleanup = read_json(child / 'builder/cleanup.json')
    require(receipt['cleanup_sha256'] == sha256(child / 'builder/cleanup.json')
            and cleanup == {'project': str(child / 'runtime/project'), 'process_cleanup_ok': True,
                'matching_project_pids': [], 'live_editor_instance': False, 'input_created': False, 'view_created': False},
            'builder cleanup proof differs')
    result = read_json(child / 'builder/execution.json')
    command = result['command']
    require(command[0] == receipt['editor']['editor']['binary'] and '-batchmode' in command and '-quit' in command,
            'builder invocation is not isolated batch')
    for flag, value in {'-projectPath': str(child / 'runtime/project'), '-executeMethod': METHOD}.items():
        require(command.count(flag) == 1 and command[command.index(flag) + 1] == value, 'builder command differs')
    validate_builder_result(result, result.get('stdout', ''))
    require(sha256(plain(child / 'runtime/project' / SCENE)) == receipt['scene_sha256'], 'generated authored scene changed')
    verify_scripts(child)
    after = read_json(child / 'builder/runtime_after.json')
    for rel, value in after.items():
        if rel.startswith('Assets/'):
            require(sha256(plain(child / 'runtime/project' / rel)) == value, 'builder asset changed: ' + rel)
    from engine_adapters.unity3d._internal.transport.unity_editor import playtest_recorder_files
    allowed = {str(dst): sha256(src) for src, dst in playtest_recorder_files()}
    for path in (child / 'runtime/project/Assets').rglob('*.cs'):
        rel = path.relative_to(child / 'runtime/project').as_posix()
        if rel not in after:
            require(allowed.get(rel) == sha256(plain(path)), 'unreviewed added runtime script: ' + rel)
    return {'entry_mode': 'authored_builder', 'launch_source': SCENE, 'launch_scene': SCENE,
            'builder_source': SOURCE, 'builder_source_sha256': SOURCE_SHA, 'method': METHOD,
            'scene_sha256': receipt['scene_sha256'], 'receipt_sha256': sha256(child / 'builder/receipt.json'),
            'note': 'Frozen input remains original and has no scene; generated scene is in runtime/project only.'}


def corrected_plan(child, executable):
    ctx, m = contract(child), short_manifest(child)
    validate_schema(executable, plan.schema('unity3d', 75000, ['play.launch', 'play.operate'], ctx))
    # The original frozen input has no scene. Validate the exact generated author output,
    # not a placeholder, C# fallback, copy into input, or synthetic launch scene.
    plan.validate(executable, m, child / 'runtime/project')
    require(executable['max_duration_ms'] == 75000 and executable['probes'], 'empty corrected plan')
    require(any(s['kind'] == 'input' or s['kind'].startswith('mouse_')
                for p in executable['probes'] for s in p['steps']), 'no ordinary player input')


def rule_verdicts(child, count):
    with tempfile.TemporaryDirectory(prefix='g009-rule-verify-') as temp:
        return playable_rules.evaluate(child, prepare.verify(child), count, report_dir=Path(temp))


def feedback(child, take):
    if take == 1:
        return {'retained_parent_plan': str(OUT / 'takes/1/plan.json'),
                'reason': 'Old accepted plan has no probes because no builder contract existed. '
                          'The original builder now ran on the fresh runtime only; read original controls. '
                          'Never activate BLACKOUT_SMOKE_DIR or any author automated review/build mode.'}
    v = rule_verdicts(child, 1)
    return {'earlier_plans': [read_json(child / 'takes/1/plan.json')['summary']],
            'judge_reasons': {'play.operate': v.get('play.operate', {}).get('reason', 'No checkable input response')}}


def should_second(checks):
    return checks.get('play.operate') != 'PASS' and checks.get('play.launch') != 'FAIL'


def make_plan(child, take):
    require(take in (1, 2) and not (child / f'takes/{take}').exists(), 'plan/native take already attempted')
    if take == 2:
        require(should_second({k: v['status'] for k, v in rule_verdicts(child, 1).items()}), 'second take not authorized')
    m = short_manifest(child)
    rows = [r for r in read_json(child / 'input/criteria.json')['criteria'] if r['id'] in ('play.launch', 'play.operate')]
    prior = feedback(child, take)
    exclusive(child / f'plan_feedback_{take}.json', prior)
    executable = plan.call_model(child / 'model_calls', name=f'plan_t{take}_builder_correction_v1',
        prompt=plan.prompt(m, rows, prior, contract(child)), schema=plan.schema('unity3d', 75000,
                    ['play.launch', 'play.operate'], contract(child)), cwd=child / 'input',
        model=PLANNER_MODEL, timeout=m['budget']['plan_timeout_s'], max_attempts=1,
        validator=lambda value: corrected_plan(child, value))
    corrected_plan(child, executable)
    exclusive(child / f'takes/{take}/plan.json', executable)
    return executable


def verify_plan(child, take):
    name = f'plan_t{take}_builder_correction_v1'
    executable = read_json(child / f'takes/{take}/plan.json')
    require(accepted_response(child / 'model_calls', name) == executable, 'accepted plan differs')
    pointer = read_json(child / 'model_calls' / name / 'accepted_response.json')
    invocation = read_json(child / 'model_calls' / name / 'invocation.json')
    require(pointer['attempt'] == invocation['attempt'] == 1 and invocation['model_requested'] == PLANNER_MODEL
            and invocation['exit_code'] == 0, 'planner route/call budget differs')
    corrected_plan(child, executable)
    prior = feedback(child, take)
    require(read_json(child / f'plan_feedback_{take}.json') == prior, 'feedback changed')
    rows = [r for r in read_json(child / 'input/criteria.json')['criteria'] if r['id'] in ('play.launch', 'play.operate')]
    prompt = plan.prompt(short_manifest(child), rows, prior, contract(child))
    require((child / 'model_calls' / name / 'prompt.txt').read_text().startswith(READ_ONLY_INSTRUCTIONS + prompt),
            'source contract/feedback was not delivered to planner')
    return executable


def native_proof(child, take):
    from .unity_natural_entry_recovery import cleanup_ok, verify_capture_files
    executable = verify_plan(child, take)
    capture = child / f'takes/{take}/record'
    native = capture / 'native'
    cleanup_ok(capture)
    report = read_json(native / 'report.json')
    result = read_json(capture / 'record_result.json')
    ed = report.get('editor_report', {})
    require(report.get('engine') == 'unity3d' and report.get('status') == 'passed' and not report.get('errors')
            and report.get('requested_seconds') == 75 and ed.get('ok') is True and ed.get('duration') == 75
            and ed.get('actual_runtime_seconds', 0) >= 75, 'native 75s startup/duration not proven')
    project = child / 'runtime/project'
    require(Path(report['url']).resolve() == project and Path(report['output_dir']).resolve() == native
            and Path(report['scene']).resolve() == project / SCENE, 'native scene/project identity differs')
    command = read_json(native / 'editor_cleanup.json')['command']
    for flag, value in {'-projectPath': str(project), '-executeMethod': 'GameFactory3APlayTestRecorder.Enter',
        '--gamefactory-evaluation-scene': str(project / SCENE), '--gamefactory-evaluation-output': str(native),
        '--gamefactory-evaluation-duration': '75.0'}.items():
        require(command.count(flag) == 1 and command[command.index(flag) + 1] == value, 'native command differs: ' + flag)
    require(result['frames'] == report['frames'] and result['frames'] > 0 and not result['failed_actions']
            and result['plan_sha256'] == sha256(capture.parent / 'plan.json'), 'frames/input/plan failed')
    verify_capture_files(capture, result['frames'])
    actions = [json.loads(s) for s in (native / 'actions.jsonl').read_text().splitlines() if s.strip()]
    require(actions and any(a.get('action') in ('key', 'mouse_click', 'mouse_move', 'mouse_scroll')
                and a.get('sent') is True and a.get('source') == 'internal_driver' and not a.get('error') for a in actions)
            and report.get('executed_actions') and all(a.get('ok') is True and a.get('sent') is True
                for a in report['executed_actions']), 'native internal input proof missing')
    require(report.get('input_readiness', {}).get('input_transport') == 'internal', 'non-internal input transport')
    choice = read_json(capture / 'unity_editor.json')
    require(choice == read_json(child / 'builder/receipt.json')['editor'] and command[0] == choice['editor']['binary'],
            'native editor differs from source-bound builder import')
    # Author smoke code logs [SMOKE] only when it drives simulation. Never qualify that run.
    for log in native.rglob('*.log'):
        require('[SMOKE]' not in log.read_text(errors='replace'), 'author smoke driver was activated')
    contract(child)
    return {'take': take, 'frames': result['frames'], 'actual_runtime_seconds': ed['actual_runtime_seconds'],
            'editor': choice, 'native_report_sha256': sha256(native / 'report.json')}


def evidence(child):
    result = {name: sha256(plain(child / name)) for name in ('manifest.json', 'status.json', 'playable_score.json')}
    for folder in ('input', 'builder', 'takes', 'model_calls'):
        result.update({folder + '/' + k: v for k, v in files(child / folder).items()})
    for p in child.glob('*.json'):
        result[p.name] = sha256(plain(p))
    for p in (child / 'runtime').glob('*.json'):
        result['runtime/' + p.name] = sha256(plain(p))
    return result


def check_unity_disk(child):
    require(shutil.disk_usage(child).free >= 16 * 1024**3,
            'Unity disk reserve insufficient: 8GiB allowance plus 8GiB reserve')


def verify_recorded_producer(start, end):
    # Historical bytes are data only; never execute a producer archive.
    producer_archive(start)
    producer_archive(end)
    require(runner().producer_closure(start) == runner().producer_closure(end),
            'producer changed during recovery')


def check_producer(start):
    r = runner()
    require(r.producer_closure(start) == r.producer_closure(r.production()), 'Stage1 producer drift; preserve attempt')


def verify_completion(out):
    out = plain(out).resolve()
    proof = review_parent(out)
    folder, child = out / REL, out / REL / 'child'
    require(not (folder / 'failure.json').exists(), 'failed partial requires separately reviewed continuation')
    activation = read_json(folder / 'activation.json')
    require(activation == {'version': VERSION, 'parent': proof, 'limits': LIMITS}, 'activation changed')
    start = read_json(folder / 'producer_start.json')['files']
    end = read_json(folder / 'producer_end.json')['files']
    verify_recorded_producer(start, end)
    require(prepare.verify(child)['project_digest'] == prepare.verify(out)['project_digest'], 'child source differs')
    count = len(list((child / 'takes').iterdir()))
    require(count in (1, 2) and {p.name for p in (child / 'takes').iterdir()} == {str(k) for k in range(1, count + 1)},
            'extra native attempts')
    require({p.name for p in (child / 'model_calls').iterdir()} == {f'plan_t{k}_builder_correction_v1' for k in range(1, count+1)},
            'extra planner calls')
    if count == 2:
        require(should_second({k: v['status'] for k,v in rule_verdicts(child, 1).items()}), 'unnecessary second take')
    proofs = [native_proof(child, k) for k in range(1, count+1)]
    for k in range(1, count + 1):
        require(read_json(folder / f'native_{k}.claim.json') == {'take': k, 'duration_ms': 75000,
                'plan_sha256': sha256(child / f'takes/{k}/plan.json'), 'limits': LIMITS}, 'native claim changed')
    expected_names = {'activation.json', 'producer_start.json', 'producer_end.json', 'completion.json',
                      'replacement.json', 'child'} | {f'native_{k}.claim.json' for k in range(1, count + 1)}
    require({p.name for p in folder.iterdir()} == expected_names, 'unexpected recovery attempt/claim')
    receipt = read_json(folder / 'completion.json')
    require(receipt == {'qualified': True, 'version': VERSION, 'activation_sha256': sha256(folder / 'activation.json'),
        'producer_start_sha256': sha256(folder / 'producer_start.json'), 'producer_end_sha256': sha256(folder / 'producer_end.json'),
        'evidence': evidence(child), 'native': proofs, 'limits': LIMITS}, 'sealed evidence differs')
    score = read_json(child / 'playable_score.json')
    expected = score_value(child, count)
    require(score == expected and score['complete'] is True, 'formal rules score differs')
    replacement = read_json(folder / 'replacement.json')
    require(replacement == {'qualified': True, 'version': VERSION, 'required_real_clients': 1,
        'child': str(child), 'completion_sha256': sha256(folder / 'completion.json'),
        'score_sha256': sha256(child / 'playable_score.json')}, 'replacement binding differs')
    return score


def score_value(child, count):
    history = []
    for k in range(1, count+1):
        v = rule_verdicts(child, k)
        checks = {i: v[i]['status'] if i in v else 'HARNESS_ERROR' for i in playable_rules.IDS}
        history.append({'take': k, 'checks': checks})
    complete = 'HARNESS_ERROR' not in checks.values()
    return {'version': playable_rules.VERSION, 'game_id': GAME, 'engine': 'unity3d', 'planner': MODELS['planner'],
            'checks': checks, 'takes': history, 'complete': complete,
            'playable': round(100 * sum(v == 'PASS' for v in checks.values()) / 3, 2) if complete else None}


def qualified_replacement_score(out):
    try:
        return verify_completion(out)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError):
        return None


def execute(out):
    require(Path(__file__).resolve() == BENCH / SELF, 'install reviewed formal module first; draft execution forbidden')
    out = plain(out).resolve()
    require(out == OUT.resolve(), 'wrong recovery output')
    safe_environment()
    os.environ.setdefault('A3GAME_GUI_SLOTS', '2')
    os.environ.setdefault('A3GAME_CODEX_INLINE_SCHEMA', '1')
    os.environ.setdefault('GAMEFACTORY_UNITY_IMGUI_FORWARD', '1')
    r = runner()
    with r.locked(ROOT / '_kimi_batch/locks/G009.lock'), r.locked(out / 'takes/1/record/.postprocess.lock'):
        proof = review_parent(out)
        r.check_disk(ROOT, proof['target'], proof['source'])
        folder, child = out / REL, out / REL / 'child'
        require(not folder.exists(), 'recovery already claimed; no retry or replay')
        exclusive(folder / 'activation.json', {'version': VERSION, 'parent': proof, 'limits': LIMITS})
        start = r.production()
        r.archive_producer(ROOT, start)
        exclusive(folder / 'producer_start.json', {'files': start})
        try:
            parent = prepare.verify(out)
            prepare.prepare(Path(parent['delivery_dir']), child, models=MODELS, suite='stage1', playable_only=True)
            require(prepare.verify(child)['project_digest'] == parent['project_digest'], 'fresh child source differs')
            check_producer(start)
            build_once(child)
            for take in (1, 2):
                safe_environment()
                require(review_parent(out) == proof, 'parent/source changed before take')
                check_producer(start)
                r.check_disk(ROOT, proof['target'], proof['source'])
                prior = files(child / 'takes/1') if take == 2 else None
                executable = make_plan(child, take)
                check_producer(start)
                exclusive(folder / f'native_{take}.claim.json', {'take': take, 'duration_ms': 75000,
                    'plan_sha256': sha256(child / f'takes/{take}/plan.json'), 'limits': LIMITS})
                check_unity_disk(child)
                record.record(child, short_manifest(child), executable, take)
                native_proof(child, take)
                require(prior is None or files(child / 'takes/1') == prior, 'take1 changed during take2')
                verdicts = playable_rules.evaluate(child, prepare.verify(child), take)
                checks = {k: v['status'] for k,v in verdicts.items()}
                if not should_second(checks):
                    break
            result = score_value(child, take)
            require(result['complete'], 'formal rules incomplete')
            write_json(child / 'playable_score.json', result)
            pipeline._status(child, 'playable', 'done', complete=True)
            require(review_parent(out) == proof, 'parent/source changed')
            end = r.production()
            r.archive_producer(ROOT, end)
            exclusive(folder / 'producer_end.json', {'files': end})
            check_producer(start)
            exclusive(folder / 'completion.json', {'qualified': True, 'version': VERSION,
                'activation_sha256': sha256(folder / 'activation.json'),
                'producer_start_sha256': sha256(folder / 'producer_start.json'),
                'producer_end_sha256': sha256(folder / 'producer_end.json'), 'evidence': evidence(child),
                'native': [native_proof(child,k) for k in range(1,take+1)], 'limits': LIMITS})
            exclusive(folder / 'replacement.json', {'qualified': True, 'version': VERSION, 'required_real_clients': 1,
                'child': str(child), 'completion_sha256': sha256(folder / 'completion.json'),
                'score_sha256': sha256(child / 'playable_score.json')})
            return verify_completion(out)
        except BaseException as exc:
            if not (folder / 'producer_end.json').exists():
                end = r.production()
                r.archive_producer(ROOT, end)
                exclusive(folder / 'producer_end.json', {'files': end})
            exclusive(folder / 'failure.json', {'error': str(exc), 'type': type(exc).__name__, 'traceback': traceback.format_exc()})
            raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    group = parser.add_mutually_exclusive_group(required=True)
    for option in ('inspect', 'execute', 'verify'):
        group.add_argument('--'+option, action='store_true')
    args = parser.parse_args(argv)
    require(Path(__file__).resolve() == BENCH / SELF, 'install reviewed formal module before CLI use')
    value = execute(args.out) if args.execute else review_parent(args.out) if args.inspect else verify_completion(args.out)
    print(json.dumps(value, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
