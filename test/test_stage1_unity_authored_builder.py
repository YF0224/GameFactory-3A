"""Synthetic source-bound builder tests; no Unity or model invocation."""
import hashlib
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline.eval.stage1 import plan, prepare, record, unity_editor
from pipeline.eval.stage1 import unity_authored_builder as b
from pipeline.eval.stage1.llm import HarnessError
from pipeline.eval.stage1.paths import read_json, write_json, sha256


def put(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture
def case(tmp_path, monkeypatch):
    out, source = tmp_path / 'out', tmp_path / 'original'
    put(source / b.SOURCE, '// synthetic authored builder, never executed\n')
    put(source / 'Assets/Bootstrap.cs', 'class Bootstrap { void Update() { Input.GetKey("w"); } }')
    put(source / 'Assets/Bootstrap.cs.meta', 'guid: ' + 'a' * 32 + '\n')
    put(source / 'ProjectSettings/EditorBuildSettings.asset', 'm_Scenes: []')
    for target in ('input/project', 'runtime/project'):
        shutil.copytree(source, out / target)
    write_json(out / 'input/criteria.json', {'criteria': []})
    digest = prepare.tree_digest(prepare.tree_hashes(source))
    manifest = {'engine': 'unity3d', 'game_id': b.GAME, 'entry': 'ProjectSettings/ProjectVersion.txt',
                'delivery': {'model': 'glm'}, 'models': {'planner': 'gpt-6-astra', 'judge': 'none'},
                'project_source': str(source), 'project_digest': digest, 'snapshot_digest': digest,
                'input_hashes': {'criteria.json': sha256(out / 'input/criteria.json')},
                'budget': {'gameplay_ms': 75000, 'plan_timeout_s': 1}}
    write_json(out / 'manifest.json', manifest)
    write_json(out / 'status.json', {'step': 'plan_t1', 'state': 'HARNESS_ERROR'})
    put(out / 'model_calls/plan_t1/response.json', '{"rejected":true}')
    files = []
    for rel in ('manifest.json', 'status.json', 'model_calls/plan_t1/response.json'):
        dst = out / b.REL / 'before' / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(out / rel, dst)
        files.append({'path': str(out / rel), 'archive': 'before/' + rel, 'sha256': sha256(dst)})
    write_json(out / b.REL / 'archive.json', {'files': files})
    monkeypatch.setattr(b, 'SOURCE_SHA', sha256(source / b.SOURCE))
    monkeypatch.setattr(b, 'producer', lambda: {})
    monkeypatch.setattr(b.shutil, 'disk_usage', lambda p: SimpleNamespace(free=30 * 1024 ** 3))
    monkeypatch.setattr(unity_editor, 'choose', lambda p: {'editor': {'binary': '/reviewed/Unity'}})
    calls = []
    def run(cmd, log, timeout):
        calls.append(cmd)
        put(log, 'synthetic command output')
        put(out / b.REL / 'builder.log', '[WbSceneTools] created ' + b.SCENE + ' and registered build scene')
        put(out / 'runtime/project' / b.SCENE, '%YAML 1.1\nguid: ' + 'a' * 32)
        put(out / 'runtime/project' / (b.SCENE + '.meta'), 'guid: ' + 'b' * 32)
        put(out / 'runtime/project/ProjectSettings/EditorBuildSettings.asset', 'path: ' + b.SCENE)
        put(out / 'runtime/project/Temp/wb_scene_report.json', '{}')
        return {'cmd': cmd, 'exit_code': 0, 'timeout': False}
    monkeypatch.setattr(record, '_run', run)
    # No shared production locks in synthetic tests.
    from contextlib import nullcontext
    monkeypatch.setattr(record, 'gui_slot', lambda: nullcontext('synthetic-slot'))
    return out, manifest, calls


def executable():
    return {'engine': 'unity3d', 'launch_source': b.SOURCE, 'launch_scene': b.SCENE,
            'probes': [], 'max_duration_ms': 75000}


def test_exact_builder_then_schema_and_dispatch(case):
    out, manifest, calls = case
    before = prepare.tree_hashes(out / 'input/project')
    receipt = b.build(out)
    assert len(calls) == 1 and calls[0][-3] == b.METHOD
    assert b.build(out) == receipt and len(calls) == 1
    entry = b.context(out)
    schema = plan.schema('unity3d', 75000, [], entry)
    assert schema['properties']['launch_source']['enum'] == [b.SOURCE]
    assert schema['properties']['launch_scene']['enum'] == [b.SCENE]
    plan.validate(executable(), manifest, out / 'input/project')
    write_json(out / 'runtime/unity_input_migration.json', {'migrated': False})
    assert b.record_scene(out / 'runtime/project', executable(), out / 'takes/1/record') == b.SCENE
    assert prepare.tree_hashes(out / 'input/project') == before
    assert b.record_scene(out / 'runtime/project', {'launch_source': 'Assets/Other.unity'}, out) == 'Assets/Other.unity'


@pytest.mark.parametrize('damage', ['original', 'input', 'archive', 'response', 'scene', 'log', 'identity', 'command'])
def test_receipt_source_and_evidence_tamper_rejected(case, damage):
    out, manifest, _ = case
    b.build(out)
    if damage == 'original': put(Path(manifest['project_source']) / b.SOURCE, 'tampered')
    elif damage == 'input': put(out / 'input/project' / b.SOURCE, 'tampered')
    elif damage == 'archive': put(out / b.REL / 'before/status.json', '{}')
    elif damage == 'response': put(out / 'model_calls/plan_t1/response.json', '{}')
    elif damage == 'scene': put(out / b.REL / 'generated' / b.SCENE, 'tampered')
    elif damage == 'log': put(out / b.REL / 'builder.log', 'tampered')
    else:
        receipt = read_json(out / b.REL / 'receipt.json')
        if damage == 'identity': receipt['scene'] = 'Assets/Fake.unity'
        else: receipt['execution']['cmd'][-3] = 'Other.Create'
        write_json(out / b.REL / 'receipt.json', receipt)
    with pytest.raises((HarnessError, RuntimeError)):
        b.context(out)


def test_cs_without_receipt_and_wrong_entry_rejected(case):
    out, manifest, _ = case
    with pytest.raises(ValueError, match='receipt'):
        plan.validate(executable(), manifest, out / 'input/project')
    b.build(out)
    p = executable(); p['launch_scene'] = 'Assets/Fake.unity'
    with pytest.raises(ValueError, match='differs'):
        plan.validate(p, manifest, out / 'input/project')


def test_bounded_claims_and_producer(case, monkeypatch):
    out, _, _ = case
    b.build(out)
    b.claim_plan(out, 1)
    with pytest.raises(FileExistsError): b.claim_plan(out, 1)
    with pytest.raises(HarnessError, match='two actual'): b.claim_plan(out, 3)
    monkeypatch.setattr(b, 'producer', lambda: {'changed': 'sha'})
    with pytest.raises(HarnessError, match='production changed'): b.claim_plan(out, 2)


def test_failed_builder_claim_is_not_reinvoked(case, monkeypatch):
    out, _, calls = case
    run = record._run
    def fail(*args, **kwargs):
        result = run(*args, **kwargs)
        result['exit_code'] = 1
        return result
    monkeypatch.setattr(record, '_run', fail)
    with pytest.raises(HarnessError, match='builder failed'): b.build(out)
    with pytest.raises(HarnessError): b.build(out)
    assert len(calls) == 1
    assert not (out / b.REL / 'receipt.json').exists()
    assert (out / b.REL / 'builder.claim.json').exists()


def test_exact_existing_input_migration_only(case):
    from pipeline.eval.stage1.unity_input import migrate_device_reads
    out, _, _ = case
    b.build(out)
    rel = 'Assets/Bootstrap.cs'
    src = out / 'runtime/project' / rel
    before = src.read_bytes(); after = migrate_device_reads(before.decode()).encode()
    src.write_bytes(after)
    write_json(out / 'runtime/unity_input_migration.json', {'migrated': True, 'gameplay_changes': [],
        'changes': [{'path': rel, 'kind': 'input_device_reads_only',
                     'before_sha256': hashlib.sha256(before).hexdigest(),
                     'after_sha256': hashlib.sha256(after).hexdigest()}]})
    assert b.record_scene(out / 'runtime/project', executable(), out / 'record') == b.SCENE
    src.write_bytes(after + b'// gameplay modification')
    with pytest.raises(HarnessError, match='non-input'): b.record_scene(out / 'runtime/project', executable(), out / 'record')


def test_corrected_call_name_and_cached_accepted_reuse(case, monkeypatch):
    out, manifest, _ = case
    b.build(out)
    calls = []
    def model(calls_dir, **kw):
        calls.append(kw)
        kw['validator'](executable())
        write_json(calls_dir / kw['name'] / 'response.json', executable())
        write_json(calls_dir / kw['name'] / 'accepted_response.json', {
            'path': 'response.json', 'sha256': sha256(calls_dir / kw['name'] / 'response.json'), 'attempt': 1})
        return executable()
    monkeypatch.setattr(plan, 'call_model', model)
    plan.make_plan(out, manifest)
    assert calls[0]['name'] == 'plan_t1_authored_builder_v1'
    assert 'VERIFIED AUTHORED BUILDER ENTRY' in calls[0]['prompt']
    (out / 'takes/1/plan.json').unlink()  # accepted reply survives interrupted persistence
    assert plan.make_plan(out, manifest) == executable()
    assert len(calls) == 1
    assert read_json(out / 'model_calls/plan_t1/response.json') == {'rejected': True}


def test_encrypted_meta_uses_exact_native_import_path(tmp_path):
    frozen, project = tmp_path / 'input', tmp_path / 'runtime'
    for root in (frozen, project): put(root / 'Assets/Core/Bootstrap.cs.meta', 'guid: encrypted+/=\n')
    guid = 'c' * 32
    text = 'Start importing Assets/Core/Bootstrap.cs using Guid(' + guid + ') Importer(Primary)'
    assert b.bootstrap_guid(project, frozen, text) == guid
    with pytest.raises(HarnessError, match='unique native import'):
        b.bootstrap_guid(project, frozen, text.replace('Core/', 'Other/'))
    with pytest.raises(HarnessError, match='unique native import'):
        b.bootstrap_guid(project, frozen, text + '\n' + text.replace(guid, 'd' * 32))
    put(project / 'Assets/Core/Bootstrap.cs.meta', 'guid: different\n')
    with pytest.raises(HarnessError, match='metadata GUID changed'):
        b.bootstrap_guid(project, frozen, text)


def test_completed_builder_postprocess_recovery_never_reruns_native(case, monkeypatch):
    out, _, calls = case
    key = 'pipeline/eval/stage1/unity_authored_builder.py'
    monkeypatch.setattr(b, 'producer', lambda: {key: 'before'})
    resolver = b.bootstrap_guid
    def fail(*args): raise HarnessError('old plain GUID assumption')
    monkeypatch.setattr(b, 'bootstrap_guid', fail)
    with pytest.raises(HarnessError, match='old plain'): b.build(out)
    monkeypatch.setattr(b, 'bootstrap_guid', resolver)
    monkeypatch.setattr(b, 'producer', lambda: {key: 'after'})
    assert b.build(out)['qualified'] is True
    assert len(calls) == 1
    assert read_json(out / b.REL / 'guid_postprocess.claim.json')['additional_builder_invocations'] == 0
    b.build(out)
    assert len(calls) == 1


def test_editor_may_remove_transient_temp_report_on_exit(case, monkeypatch):
    out, _, calls = case
    run = record._run
    def no_temp(*args, **kwargs):
        result = run(*args, **kwargs)
        (out / 'runtime/project/Temp/wb_scene_report.json').unlink()
        return result
    monkeypatch.setattr(record, '_run', no_temp)
    receipt = b.build(out)
    assert receipt['qualified'] and not receipt['transient_author_report_present_after_exit']
    assert len(calls) == 1
    assert not (out / b.REL / 'generated/Temp/wb_scene_report.json').exists()


def test_godot_only_drift_preserves_unity_and_shared_code():
    old = "import os\ndef _godot(): return 1\ndef _native(): return 75\n"
    b.godot_only_change(old, old.replace('return 1', 'return 2'))
    for bad in (old.replace('return 75', 'return 7'), old.replace('import os', 'import sys'),
                old.replace('_godot', '_other')):
        with pytest.raises(HarnessError): b.godot_only_change(old, bad)


def test_hold_retired_only_after_qualification_and_cleanup(tmp_path):
    out = tmp_path
    hold = {'version': 'stage1-authored-builder-finalization-hold.v1'}
    write_json(out / 'qualification_hold.json', hold)
    write_json(out / b.REL / 'finalization_hold.original.json', hold)
    write_json(out / b.REL / 'completion.json', {'qualified': False})
    with pytest.raises(HarnessError, match='incomplete'): b.retire_finalization_hold(out)
    write_json(out / b.REL / 'completion.json', {'qualified': True})
    write_json(out / 'cleanup.json', {'freed_bytes': 123})
    (out / 'runtime/project').mkdir(parents=True)
    with pytest.raises(HarnessError, match='incomplete'): b.retire_finalization_hold(out)
    (out / 'runtime/project').rmdir()
    b.retire_finalization_hold(out)
    assert not (out / 'qualification_hold.json').exists()
    assert read_json(out / b.REL / 'finalization_hold.original.json') == hold
    assert read_json(out / b.REL / 'hold_release.json')['hold_sha256'] == sha256(out / b.REL / 'finalization_hold.original.json')


def test_unrelated_or_tampered_hold_never_removed(tmp_path):
    write_json(tmp_path / 'qualification_hold.json', {'version': 'other'})
    write_json(tmp_path / b.REL / 'finalization_hold.original.json', {'version': 'other'})
    with pytest.raises(HarnessError, match='unrelated'): b.retire_finalization_hold(tmp_path)
    assert (tmp_path / 'qualification_hold.json').exists()


@pytest.fixture
def g009(case, monkeypatch):
    out, manifest, calls = case
    manifest['game_id'] = 'G009_blackout_stealth'
    original = Path(manifest['project_source'])
    builder = 'Assets/Scripts/Editor/G009EditorValidation.cs'
    bootstrap = 'Assets/Scripts/Mechanic/G009SceneBootstrap.cs'
    for root in (original, out / 'input/project', out / 'runtime/project'):
        (root / b.SOURCE).unlink()
        put(root / builder, '// synthetic G009 delivered BuildScene')
        put(root / bootstrap, (root / 'Assets/Bootstrap.cs').read_text())
        put(root / (bootstrap + '.meta'), (root / 'Assets/Bootstrap.cs.meta').read_text())
        (root / 'Assets/Bootstrap.cs').unlink(); (root / 'Assets/Bootstrap.cs.meta').unlink()
    monkeypatch.setattr(b, 'G009_SOURCE_SHA', sha256(original / builder))
    manifest['project_digest'] = manifest['snapshot_digest'] = prepare.tree_digest(prepare.tree_hashes(original))
    write_json(out / 'manifest.json', manifest)
    shutil.copyfile(out / 'manifest.json', out / b.REL / 'before/manifest.json')
    archive = read_json(out / b.REL / 'archive.json')
    archive['files'][0]['sha256'] = sha256(out / 'manifest.json')
    write_json(out / b.REL / 'archive.json', archive)
    entry = b.reviewed(out)
    def run(cmd, log, timeout):
        calls.append(cmd)
        put(log, 'synthetic command output')
        put(out / b.REL / 'builder.log', entry.completion_log)
        put(out / 'runtime/project' / entry.scene, '%YAML 1.1\nguid: ' + 'a' * 32)
        put(out / 'runtime/project' / (entry.scene + '.meta'), 'guid: ' + 'b' * 32)
        return {'cmd': cmd, 'exit_code': 0, 'timeout': False}
    monkeypatch.setattr(record, '_run', run)
    return out, manifest, calls, entry


def test_g009_only_delivered_build_scene_without_buildplayer(g009):
    out, manifest, calls, entry = g009
    receipt = b.build(out)
    assert calls[0][-3] == 'G009EditorValidation.BuildScene'
    assert receipt['qualified'] and not receipt['transient_author_report_present_after_exit']
    assert (out / 'runtime/project/ProjectSettings/EditorBuildSettings.asset').read_text() == 'm_Scenes: []'
    assert b.context(out)['launch_source'] == entry.source
    p = {**executable(), 'launch_source': entry.source, 'launch_scene': entry.scene}
    plan.validate(p, manifest, out / 'input/project')
    write_json(out / 'runtime/unity_input_migration.json', {'migrated': False})
    assert b.record_scene(out / 'runtime/project', p, out / 'record') == entry.scene
    assert len(calls) == 1


def test_g009_disallows_other_methods_and_registered_buildplayer(g009):
    out, _, _, _ = g009
    b.build(out)
    receipt = read_json(out / b.REL / 'receipt.json')
    receipt['execution']['cmd'][-3] = 'G009EditorValidation.ValidateStatic'
    write_json(out / b.REL / 'receipt.json', receipt)
    with pytest.raises(HarnessError, match='command differs'): b.context(out)


def test_g009_compile_failure_never_reinvokes_builder(g009, monkeypatch):
    out, _, calls, _ = g009
    run = record._run
    def failed(*args, **kw):
        result = run(*args, **kw); result['exit_code'] = 1
        put(out / b.REL / 'builder.log', 'error CS0000: delivered compiler error')
        return result
    monkeypatch.setattr(record, '_run', failed)
    with pytest.raises(HarnessError, match='builder failed'): b.build(out)
    with pytest.raises(HarnessError, match='cannot be reinvoked'): b.build(out)
    assert len(calls) == 1


def test_unreviewed_identity_has_no_builder_fallback(case):
    out, manifest, _ = case
    manifest['game_id'] = 'G047_other'
    write_json(out / 'manifest.json', manifest)
    assert b.context(out) is None
    with pytest.raises(HarnessError, match='only for GLM'): b.original(out)

@pytest.fixture
def g010_case(case, monkeypatch):
    out, manifest, calls = case
    source = Path(manifest['project_source'])
    for root in (source, out / 'input/project', out / 'runtime/project'):
        put(root / b.G010_SOURCE, '// synthetic exact original builder\n')
    manifest['game_id'] = 'G010_orbital_extraction'
    manifest['project_digest'] = manifest['snapshot_digest'] = prepare.tree_digest(prepare.tree_hashes(source))
    write_json(out / 'manifest.json', manifest)
    monkeypatch.setattr(b, 'G010_SHA', sha256(source / b.G010_SOURCE))
    import sys
    sys.path.insert(0, str(b.FRAMEWORK / 'scripts/eval'))
    from pipeline.eval.stage1 import playable_support as runner
    target_file = out / 'test_targets.json'
    write_json(target_file, {'targets': [{'model': 'GLM', 'case': 'G010', 'engine': 'unity3d',
                                         'project': str(source), 'required_real_clients': 1}]})
    monkeypatch.setattr(runner, 'TARGETS', target_file)
    monkeypatch.setattr(runner, 'result_dir', lambda root, target: out)
    def failed(cmd, log, timeout):
        calls.append(cmd)
        put(log, 'synthetic compiler failure')
        put(out / b.G010_PREFLIGHT / 'builder.log',
            "Assets/UI/Scripts/WhiteboxUIBuilder.cs(13,18): error CS0101: namespace already contains definition\n")
        return {'cmd': cmd, 'exit_code': 1, 'timeout': False}
    monkeypatch.setattr(record, '_run', failed)
    return out, manifest, calls, target_file


def test_g010_original_builder_failure_is_not_a_score_and_never_retries(g010_case):
    out, manifest, calls, _ = g010_case
    before = sha256(out / 'status.json')
    result = b.preflight_g010(out)
    assert result['classification'] == 'PRODUCT_COMPILE_FAILURE'
    assert result['complete'] is False and result['score_written'] is False
    assert result['gameplay_takes'] == result['additional_model_calls'] == 0
    assert result['production_drift'] == {}
    assert len(calls) == 1 and b.G010_METHOD in calls[0]
    assert sha256(out / 'status.json') == before
    assert not (out / 'playable_score.json').exists()
    assert not (out / b.REL / 'receipt.json').exists()
    with pytest.raises(HarnessError, match='already claimed'):
        b.preflight_g010(out)
    assert len(calls) == 1


def test_g010_multiclient_target_refuses_preflight(g010_case):
    out, _, calls, target = g010_case
    data = read_json(target)
    data['targets'][0]['required_real_clients'] = 2
    write_json(target, data)
    with pytest.raises(HarnessError, match='single-client'):
        b.preflight_g010(out)
    assert not calls


def test_g010_original_or_runtime_change_refuses_native(g010_case):
    out, manifest, calls, _ = g010_case
    put(out / 'runtime/project' / b.G010_SOURCE, 'fixed author source')
    with pytest.raises(HarnessError, match='original frozen copy'):
        b.preflight_g010(out)
    assert not calls


def test_g010_existing_plan_or_native_is_not_repeated(g010_case):
    out, _, calls, _ = g010_case
    write_json(out / 'takes/1/plan.json', {})
    with pytest.raises(HarnessError, match='no accepted/native/score'):
        b.preflight_g010(out)
    assert not calls
