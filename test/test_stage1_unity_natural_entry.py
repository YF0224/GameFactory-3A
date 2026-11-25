"""Source/lifecycle contract tests only; no model, Unity or authored code runs."""
from dataclasses import replace
import shutil

import pytest

from pipeline.eval.stage1 import prepare, unity_natural_entry as n
from pipeline.eval.stage1.llm import HarnessError
from pipeline.eval.stage1.paths import read_json, sha256, write_json


def put(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture
def case(tmp_path, monkeypatch):
    game = 'G039_sky_ring_flight'
    out, original = tmp_path / 'out', tmp_path / 'original'
    entry = n.PROFILES[game]
    put(original / entry.source, '// synthetic exact reviewed initializer\n')
    put(original / entry.automation_source, '// synthetic argument-gated automation\n')
    put(original / 'Assets/Other.cs', '// other frozen author code\n')
    put(original / 'ProjectSettings/EditorBuildSettings.asset', 'm_Scenes: []\n')
    entry = replace(entry, source_sha256=sha256(original / entry.source),
                    automation_sha256=sha256(original / entry.automation_source))
    monkeypatch.setitem(n.PROFILES, game, entry)
    monkeypatch.setattr(n, 'original_project', lambda value: original)
    monkeypatch.setattr(n, 'resolve_target', lambda game_id: (
        {'engine': 'unity3d', 'project': str(original), 'required_real_clients': 1}, out))
    shutil.copytree(original, out / 'input/project')
    put(out / 'input/criteria.json', '{}')
    manifest = {
        'game_id': game, 'engine': 'unity3d', 'delivery': {'model': 'astra'},
        'models': {'planner': 'gpt-6-astra', 'judge': 'none'},
        'project_source': str(original),
        'project_digest': prepare.tree_digest(prepare.tree_hashes(original)),
        'snapshot_digest': prepare.tree_digest(prepare.tree_hashes(out / 'input/project')),
        'input_hashes': {'criteria.json': sha256(out / 'input/criteria.json')},
    }
    write_json(out / 'manifest.json', manifest)
    return out, original, entry


def save_contract(out):
    value = n.review(out)
    write_json(out / n.REL / 'contract.json', value)
    return value


def test_review_readonly_and_requires_explicit_contract(case):
    out, original, entry = case
    before = prepare.tree_hashes(out)
    value = n.review(out)
    assert prepare.tree_hashes(out) == before
    assert n.context(out) is None
    assert value['launch_source'] == entry.source and value['launch_scene'] == ''
    assert value['native_startup_observed'] is False
    save_contract(out)
    assert n.validate_plan(out, {'engine': 'unity3d', 'launch_source': entry.source,
                                 'launch_scene': ''}) == value


def test_absent_contract_does_not_change_ordinary_identity(tmp_path):
    assert n.context(tmp_path) is None


@pytest.mark.parametrize('damage', ['original', 'input', 'automation', 'other_source', 'criteria',
                                     'model', 'planner', 'game', 'original_path'])
def test_source_and_identity_tamper_fail_closed(case, damage):
    out, original, entry = case
    save_contract(out)
    if damage == 'original':
        put(original / entry.source, 'changed')
    elif damage == 'input':
        put(out / 'input/project' / entry.source, 'changed')
    elif damage == 'automation':
        put(original / entry.automation_source, 'changed')
    elif damage == 'other_source':
        put(original / 'Assets/Other.cs', 'changed')
    elif damage == 'criteria':
        put(out / 'input/criteria.json', '{"changed":true}')
    else:
        m = read_json(out / 'manifest.json')
        if damage == 'model': m['delivery']['model'] = 'glm'
        elif damage == 'planner': m['models']['planner'] = 'another-model'
        elif damage == 'game': m['game_id'] = 'G049_underwater_salvage'
        else: m['project_source'] = str(out / 'input/project')
        write_json(out / 'manifest.json', m)
    with pytest.raises((HarnessError, RuntimeError)):
        n.context(out)


def test_rewriting_manifest_does_not_approve_changed_entry(case):
    out, original, entry = case
    put(original / entry.source, 'unreviewed initializer')
    put(out / 'input/project' / entry.source, 'unreviewed initializer')
    m = read_json(out / 'manifest.json')
    m['project_digest'] = prepare.tree_digest(prepare.tree_hashes(original))
    m['snapshot_digest'] = prepare.tree_digest(prepare.tree_hashes(out / 'input/project'))
    write_json(out / 'manifest.json', m)
    with pytest.raises(HarnessError, match='reviewed entry'):
        n.review(out)


def test_author_scene_and_symlink_denied(case):
    out, original, entry = case
    p = original / 'Assets/Scene.unity'
    put(p, '%YAML')
    with pytest.raises(HarnessError, match='existing authored scene'):
        n.verify_reviewed_files(original, entry)
    p.unlink()
    p.symlink_to(original / entry.source)
    with pytest.raises(HarnessError, match='symlinked'):
        n.verify_reviewed_files(original, entry)


def test_package_cache_scene_is_not_author_entry(case):
    _, original, entry = case
    put(original / 'Library/PackageCache/Example/Scene.unity', '%YAML')
    n.verify_reviewed_files(original, entry)


@pytest.mark.parametrize('key,value', [('launch_scene', 'Assets/Fake.unity'),
                                      ('method', 'OtherMethod'), ('native_startup_observed', True),
                                      ('extra', 'unknown'), ('version', 'legacy')])
def test_contract_tamper_and_unknown_fields_rejected(case, key, value):
    out, _, _ = case
    contract = save_contract(out)
    contract[key] = value
    write_json(out / n.REL / 'contract.json', contract)
    with pytest.raises(HarnessError, match='contract differs'):
        n.context(out)


@pytest.mark.parametrize('scene,source', [('Assets/Fake.unity', None), ('', 'Assets/Other.cs')])
def test_plan_cannot_invent_scene_or_choose_other_source(case, scene, source):
    out, _, entry = case
    save_contract(out)
    with pytest.raises(HarnessError, match='exact original'):
        n.validate_plan(out, {'engine': 'unity3d', 'launch_source': source or entry.source,
                              'launch_scene': scene})


@pytest.mark.parametrize('argument', ['--wb-output', '--g054-playtest', '--whitebox-take'])
def test_author_automation_forbidden(argument):
    for arguments in ([argument, '/tmp/report'], [argument + '=/tmp/report']):
        with pytest.raises(HarnessError, match='automation switch'):
            n.verify_arguments(arguments)
    n.verify_arguments(['-batchmode', '-projectPath', '/eval/project'])


def native(entry):
    return {
        'version': 'unity-runtime-initializer-native-record-entry.v1', 'error': '',
        'editor_version': 'synthetic', 'source': entry.source, 'source_sha256': entry.source_sha256,
        'type': entry.type, 'method': entry.method, 'after_scene_load_attribute': True,
        'startup_scene_unsaved': True, 'entered_play_mode': True, 'exited_play_mode': True,
        'observed_author_component': True, 'entry_method_invoked_by_wrapper': False,
        'scene_created_by_wrapper': False, 'gameplay_component_added_by_wrapper': False,
        'view_activated': False,
        'objects': [{'type': entry.type, 'script_path': entry.source, 'active': True,
                     'enabled': True, 'script_guid': 'a' * 32}],
    }


def test_native_lifecycle_uses_formal_proof_without_claiming_score(case):
    out, _, entry = case
    save_contract(out)
    assert n.verify_native_lifecycle(out, native(entry))['source'] == entry.source
    assert not (out / 'playable_score.json').exists()
    assert not (out / 'takes').exists()


@pytest.mark.parametrize('key,value', [('entry_method_invoked_by_wrapper', True),
                                      ('scene_created_by_wrapper', True),
                                      ('gameplay_component_added_by_wrapper', True),
                                      ('view_activated', True), ('startup_scene_unsaved', False),
                                      ('exited_play_mode', False), ('objects', []),
                                      ('source_sha256', '0' * 64), ('error', 'author exception')])
def test_native_lifecycle_tamper_rejected(case, key, value):
    out, _, entry = case
    save_contract(out)
    proof = native(entry)
    proof[key] = value
    with pytest.raises(HarnessError, match='lifecycle'):
        n.verify_native_lifecycle(out, proof)


def test_multiclient_target_never_routes_to_single_client(case, monkeypatch):
    out, original, _ = case
    monkeypatch.setattr(n, 'resolve_target', lambda game_id: (
        {'engine': 'unity3d', 'project': str(original), 'required_real_clients': 2}, out))
    with pytest.raises(HarnessError, match='single-client target'):
        n.review(out)


def test_runner_result_dir_must_match(case, monkeypatch):
    out, original, _ = case
    monkeypatch.setattr(n, 'resolve_target', lambda game_id: (
        {'engine': 'unity3d', 'project': str(original), 'required_real_clients': 1},
        out / 'retest_dual_client_v1'))
    with pytest.raises(HarnessError, match='runner result directory'):
        n.review(out)


@pytest.fixture
def ready(case, monkeypatch):
    out, original, entry = case
    put(original / 'ProjectSettings/ProjectSettings.asset', 'activeInputHandler: 1\n')
    put(original / 'Packages/manifest.json', '{"dependencies":{}}')
    shutil.rmtree(out / 'input/project')
    shutil.copytree(original, out / 'input/project')
    manifest = read_json(out / 'manifest.json')
    manifest.update(project_digest=prepare.tree_digest(prepare.tree_hashes(original)),
                    snapshot_digest=prepare.tree_digest(prepare.tree_hashes(out / 'input/project')))
    write_json(out / 'manifest.json', manifest)
    save_contract(out)
    project = out / 'runtime/project'
    shutil.copytree(out / 'input/project', project)
    folder = out / 'takes/1/record'
    folder.mkdir(parents=True)
    plan = {'engine': 'unity3d', 'launch_source': entry.source, 'launch_scene': ''}
    write_json(folder.parent / 'plan.json', plan)
    from pipeline.eval.stage1 import llm, unity_input
    from pipeline.game_eval.whitebox_eval import unity_runtime_dependencies as deps
    editor = out / 'fake-editor/Contents/MacOS/Unity'
    put(editor, '')
    put(editor.parent.parent / 'Resources/PackageManager/BuiltInPackages' / deps.AUDIO / 'package.json',
        '{"name":"com.unity.modules.audio","version":"1.0.0","type":"module"}')
    write_json(folder / 'unity_editor.json', {'editor': {'binary': str(editor)}})
    unity_input.migrate(project, folder / 'unity_input_migration.json')
    deps.prepare(project, editor, folder / 'observer_runtime_dependencies.json')
    monkeypatch.setattr(llm, 'accepted_response', lambda path, name: plan)
    return out, project, folder, plan


def test_official_observer_installation_after_binding_is_verified(ready):
    out, project, folder, plan = ready
    from engine_adapters.unity3d._internal.transport.unity_editor import _install_playtest_recorder
    frozen = prepare.tree_hashes(out / 'input/project')
    n.record_binding(project, plan, folder)
    # Real adapter ordering: binding is checked first, then official installation.
    _install_playtest_recorder(project)
    inventory = n.verify_runtime(out, folder)
    assert inventory['Assets/GameFactory3AEvaluation/installation.json']
    assert prepare.tree_hashes(out / 'input/project') == frozen
    assert not (folder / 'native').exists()


@pytest.mark.parametrize('damage', ['schema', 'extra_record', 'extra_field', 'missing_file',
                                     'edited_observer', 'author_edit', 'symlink'])
def test_official_observer_journal_cannot_authorize_changed_files(ready, damage):
    out, project, folder, plan = ready
    from engine_adapters.unity3d._internal.transport.unity_editor import _install_playtest_recorder
    n.record_binding(project, plan, folder)
    _install_playtest_recorder(project)
    journal = project / 'Assets/GameFactory3AEvaluation/installation.json'
    value = read_json(journal)
    observer = project / next(iter(value['files']))
    if damage == 'schema':
        value['schema'] = 'unreviewed'
    elif damage == 'extra_record':
        value['files']['Assets/Other.cs'] = sha256(project / 'Assets/Other.cs')
    elif damage == 'extra_field':
        value['authorized'] = True
    elif damage == 'missing_file':
        observer.unlink()
    elif damage == 'edited_observer':
        put(observer, 'changed observer')
        value['files'][str(observer.relative_to(project))] = sha256(observer)
    elif damage == 'author_edit':
        put(project / 'Assets/Other.cs', 'changed author source')
    write_json(journal, value)
    if damage == 'symlink':
        copied = out / 'journal.json'
        copied.write_bytes(journal.read_bytes())
        journal.unlink()
        journal.symlink_to(copied)
    with pytest.raises((HarnessError, OSError)):
        n.verify_runtime(out, folder)


def test_runtime_binding_replays_official_transforms_and_loads(ready):
    out, project, folder, plan = ready
    before = prepare.tree_hashes(out / 'input')
    arguments = n.record_binding(project, plan, folder)
    assert arguments['scene'] == ''
    binding = n.load_record_binding(arguments['runtime_entry'], project)
    assert binding['version'] == n.RECORD_VERSION and binding['take'] == 1
    assert before == prepare.tree_hashes(out / 'input')
    assert not (out / 'playable_score.json').exists()
    assert not (folder / 'native').exists()
    with pytest.raises(HarnessError, match='already exists'):
        n.record_binding(project, plan, folder)


@pytest.mark.parametrize('relative', ['Assets/Other.cs', 'Assets/Injected.cs',
                                      'Assets/Fake.unity', 'Packages/manifest.json',
                                      'ProjectSettings/ProjectSettings.asset'])
def test_runtime_author_edits_and_injections_rejected(ready, relative):
    out, project, folder, plan = ready
    put(project / relative, 'unreviewed change')
    with pytest.raises(HarnessError, match='unreviewed'):
        n.record_binding(project, plan, folder)
    assert not (folder / 'runtime_initializer_entry.json').exists()


def test_native_generated_metadata_does_not_authorize_source_change(ready):
    out, project, folder, plan = ready
    put(project / 'Assets/Other.cs.meta', 'fileFormatVersion: 2\nguid: ' + 'a' * 32 + '\n')
    binding = n.record_binding(project, plan, folder)['runtime_entry']
    put(project / 'Assets/Other.cs', 'changed after prelaunch audit')
    with pytest.raises(HarnessError, match='unreviewed runtime'):
        n.load_record_binding(binding, project)


def test_no_manually_accepted_plan(ready, monkeypatch):
    _, project, folder, plan = ready
    from pipeline.eval.stage1 import llm
    monkeypatch.setattr(llm, 'accepted_response', lambda path, name: None)
    with pytest.raises(HarnessError, match='actual accepted'):
        n.record_binding(project, plan, folder)


@pytest.mark.parametrize('field,value', [('take', 3), ('take', True), ('method', 'Fake'),
                                       ('version', 'unity-runtime-initializer-record-entry.v1'),
                                       ('extra', 1), ('plan_sha256', '0' * 64)])
def test_binding_tamper_fails_closed(ready, field, value):
    _, project, folder, plan = ready
    path = n.record_binding(project, plan, folder)['runtime_entry']
    binding = read_json(path)
    binding[field] = value
    write_json(path, binding)
    with pytest.raises(HarnessError):
        n.load_record_binding(path, project)


def test_migration_receipt_cannot_hide_author_rewrite(ready):
    _, project, folder, plan = ready
    write_json(folder / 'unity_input_migration.json', {'migrated': False, 'reason': 'forged'})
    with pytest.raises(HarnessError, match='deterministic official replay'):
        n.record_binding(project, plan, folder)


@pytest.fixture
def recovery_case(case, monkeypatch):
    from pipeline.eval.repair import unity_natural_entry_recovery as r
    out, original, entry = case
    write_json(out / 'status.json', {'step': 'plan_t1', 'state': 'HARNESS_ERROR', 'error': 'missing launch_source'})
    put(out / 'model_calls/plan_t1/response.json', '{"launch_source":""}')
    monkeypatch.setattr(r, 'producer', lambda: {})
    return out, original, entry


def test_recovery_activation_archives_rejected_calls_and_claim_is_bounded(recovery_case):
    from pipeline.eval.repair import unity_natural_entry_recovery as r
    out, original, entry = recovery_case
    before = (out / 'model_calls/plan_t1/response.json').read_bytes()
    with r.locked(out):
        r.activate(out)
    assert n.context(out)['launch_source'] == entry.source
    assert (out / 'qualification_hold.json').read_bytes() == (out / n.REL / 'hold.original.json').read_bytes()
    assert (out / n.REL / 'parent_archive/model_calls/plan_t1/response.json').read_bytes() == before
    r.claim_plan(out, 1)
    with pytest.raises(FileExistsError):
        r.claim_plan(out, 1)
    for bad in (0, 3, True, '1'):
        with pytest.raises(HarnessError):
            r.claim_plan(out, bad)
    with pytest.raises(HarnessError):
        r.activate(out)
    assert (out / 'model_calls/plan_t1/response.json').read_bytes() == before
    assert not (out / 'playable_score.json').exists()


@pytest.mark.parametrize('existing', ['running', 'plan', 'record', 'accepted', 'score', 'hold'])
def test_recovery_refuses_inflight_or_existing_evidence(recovery_case, existing):
    from pipeline.eval.repair import unity_natural_entry_recovery as r
    out, _, _ = recovery_case
    if existing == 'running':
        write_json(out / 'status.json', {'step': 'record_t1', 'state': 'running'})
    elif existing == 'plan':
        write_json(out / 'takes/1/plan.json', {})
    elif existing == 'record':
        (out / 'takes/1/record').mkdir(parents=True)
    else:
        path = {'accepted': 'model_calls/plan_t1/accepted_response.json',
                'score': 'playable_score.json', 'hold': 'qualification_hold.json'}[existing]
        write_json(out / path, {})
    with pytest.raises(HarnessError):
        r.activate(out)
    assert not (out / n.REL / 'contract.json').exists()


@pytest.mark.parametrize('where', ['parent', 'archive', 'contract', 'producer'])
def test_recovery_planner_claim_rejects_tamper(recovery_case, monkeypatch, where):
    from pipeline.eval.repair import unity_natural_entry_recovery as r
    out, _, _ = recovery_case
    r.activate(out)
    if where == 'producer':
        monkeypatch.setattr(r, 'producer', lambda: {'new.py': '0' * 64})
    else:
        path = {'parent': 'model_calls/plan_t1/response.json',
                'archive': str(n.REL / 'parent_archive/model_calls/plan_t1/response.json'),
                'contract': str(n.REL / 'contract.json')}[where]
        write_json(out / path, {'changed': True})
    with pytest.raises((HarnessError, KeyError)):
        r.claim_plan(out, 1)
    assert not (out / n.REL / 'planner_t1.claim.json').exists()


def test_recovery_failure_keeps_hold_and_cannot_reexecute(recovery_case, monkeypatch):
    from types import SimpleNamespace
    from pipeline.eval.stage1 import pipeline
    from pipeline.eval.repair import unity_natural_entry_recovery as r
    out, _, _ = recovery_case
    manifest = read_json(out / 'manifest.json')
    manifest['delivery_dir'] = str(out / 'delivery')
    write_json(out / 'manifest.json', manifest)
    monkeypatch.setattr(r.shutil, 'disk_usage', lambda p: SimpleNamespace(free=20 * 1024 ** 3))
    calls = []
    def run(*args, **kwargs):
        calls.append(kwargs)
        assert (out / 'qualification_hold.json').is_file()
        raise HarnessError('synthetic original compile failure')
    monkeypatch.setattr(pipeline, 'run_playable', run)
    with pytest.raises(HarnessError, match='compile failure'):
        r.execute(out)
    with pytest.raises(HarnessError):
        r.execute(out)
    assert len(calls) == 1 and calls[0]['takes'] == 2
    assert (out / 'qualification_hold.json').exists()
    assert not (out / 'playable_score.json').exists()


@pytest.fixture
def qualified_synthetic(recovery_case, monkeypatch):
    """Synthetic post-record checkpoint; all native verification is separately tested."""
    from pipeline.eval.repair import unity_natural_entry_recovery as r
    out, original, entry = recovery_case
    r.activate(out)
    shutil.copytree(out / 'input/project', out / 'runtime/project')
    result = {'complete': True, 'engine': 'unity3d', 'playable': 100,
              'checks': {'play.import': 'PASS', 'play.launch': 'PASS', 'play.operate': 'PASS'},
              'takes': [{'take': 1}]}
    write_json(out / 'playable_score.json', result)
    put(out / 'takes/1/record/native/frame.png', 'synthetic image, never native evidence')
    evidence = {str(p.relative_to(out)): sha256(p) for p in out.rglob('*') if p.is_file()
                and not any(p.is_relative_to(out / part) for part in ('input/project', 'runtime/project'))
                and p.name != 'qualification_hold.json'}
    write_json(out / n.REL / 'completion.json', {'version': r.VERSION, 'qualified': True,
               'out': str(out), 'score': result, 'evidence_sha256': evidence})
    # Verify real official cleanup and runner recognition, without invoking a model/engine.
    import sys
    sys.path.insert(0, str(n.BENCH / 'scripts/eval'))
    from pipeline.eval.stage1 import playable_support as runner
    monkeypatch.setattr(runner, 'completed_score', lambda path, target: (
        None if (path / 'qualification_hold.json').exists() else read_json(path / 'playable_score.json')))
    return out, original, result


def test_offline_cleanup_and_hold_release_preserve_evidence(qualified_synthetic):
    from pipeline.eval.repair import unity_natural_entry_recovery as r
    out, original, result = qualified_synthetic
    original_before = prepare.tree_hashes(original)
    assert r.complete_cleanup(out) == result
    assert not (out / 'qualification_hold.json').exists()
    assert not (out / 'runtime/project').exists() and not (out / 'input/project').exists()
    assert read_json(out / 'cleanup.json')['freed_bytes'] > 0
    assert (out / n.REL / 'hold.original.json').exists()
    assert r.finalize(out) == result
    assert original_before == prepare.tree_hashes(original)


@pytest.mark.parametrize('damage', ['frame', 'source', 'score', 'archive', 'hold'])
def test_cleanup_tamper_keeps_hold(qualified_synthetic, damage):
    from pipeline.eval.repair import unity_natural_entry_recovery as r
    out, original, result = qualified_synthetic
    paths = {'frame': out / 'takes/1/record/native/frame.png',
             'source': original / 'Assets/Other.cs', 'score': out / 'playable_score.json',
             'archive': out / n.REL / 'parent_archive/model_calls/plan_t1/response.json',
             'hold': out / 'qualification_hold.json'}
    put(paths[damage], '{"changed":true}')
    with pytest.raises((HarnessError, KeyError, ValueError)):
        r.complete_cleanup(out)
    assert (out / 'qualification_hold.json').exists()


def test_cleanup_resume_does_not_overwrite_freed_bytes(qualified_synthetic):
    from pipeline.eval.repair import unity_natural_entry_recovery as r
    out, _, result = qualified_synthetic
    from pipeline.eval.stage1 import playable_support as runner
    receipt = runner.cleanup(out)
    assert r.complete_cleanup(out) == result
    assert read_json(out / 'cleanup.json') == receipt


def test_formal_adapter_dispatch_uses_strict_stage1_binding(ready):
    from engine_adapters.unity3d.playtest import runtime_initializer as adapter
    out, project, folder, executable = ready
    path = n.record_binding(project, executable, folder)['runtime_entry']
    assert adapter.load(path, project)['source'] == executable['launch_source']
    value = read_json(path)
    value['method'] = 'InventedMethod'
    write_json(path, value)
    with pytest.raises(HarnessError):
        adapter.load(path, project)
    value['version'] = 'unknown'
    write_json(path, value)
    with pytest.raises(ValueError, match='Unknown runtime'):
        adapter.load(path, project)


def test_plan_schema_prompt_and_default_missing_entry_guard(case):
    from pipeline.eval.stage1 import plan
    out, _, entry = case
    manifest = read_json(out / 'manifest.json')
    manifest.update(entry='ProjectSettings/ProjectVersion.txt', budget={'gameplay_ms': 75000})
    executable = {'engine': 'unity3d', 'launch_source': entry.source, 'launch_scene': '',
                  'probes': [], 'max_duration_ms': 75000}
    with pytest.raises(ValueError):
        plan.validate(executable, manifest, out / 'input/project')
    contract = save_contract(out)
    plan.validate(executable, manifest, out / 'input/project')
    schema = plan.schema('unity3d', 75000, ['play.launch'], contract)
    assert schema['properties']['launch_source']['enum'] == [entry.source]
    assert schema['properties']['launch_scene']['enum'] == ['']
    prompt = plan.prompt(manifest, [], authored_entry=contract)
    assert 'REVIEWED NATURAL RUNTIME ENTRY' in prompt
    assert 'not proof that startup or gameplay works' in prompt
    assert 'already run successfully' not in prompt
    executable['launch_source'] = 'Assets/Other.cs'
    with pytest.raises(ValueError):
        plan.validate(executable, manifest, out / 'input/project')


def test_corrected_plan_uses_separate_claim_and_reuses_accepted(recovery_case, monkeypatch):
    from pipeline.eval.stage1 import plan, llm
    from pipeline.eval.repair import unity_natural_entry_recovery as r
    out, _, entry = recovery_case
    manifest = read_json(out / 'manifest.json')
    manifest.update(entry='ProjectSettings/ProjectVersion.txt', budget={'gameplay_ms': 75000, 'plan_timeout_s': 1})
    write_json(out / 'input/criteria.json', {'criteria': []})
    manifest['input_hashes']['criteria.json'] = sha256(out / 'input/criteria.json')
    write_json(out / 'manifest.json', manifest)
    r.activate(out)
    executable = {'engine': 'unity3d', 'launch_source': entry.source, 'launch_scene': '',
                  'probes': [], 'max_duration_ms': 75000}
    calls = []
    def model(folder, **kwargs):
        calls.append(kwargs['name'])
        kwargs['validator'](executable)
        assert (out / n.REL / 'planner_t1.claim.json').is_file()
        put(folder / kwargs['name'] / 'actual_response.json', __import__('json').dumps(executable))
        write_json(folder / kwargs['name'] / 'accepted_response.json', {
            'path': 'actual_response.json', 'sha256': sha256(folder / kwargs['name'] / 'actual_response.json')})
        return executable
    monkeypatch.setattr(plan, 'call_model', model)
    assert plan.make_plan(out, manifest) == executable
    # Simulate interruption after response acceptance but before plan persistence.
    (out / 'takes/1/plan.json').unlink()
    assert plan.make_plan(out, manifest) == executable
    assert calls == ['plan_t1_natural_entry_v1']
    assert (out / 'model_calls/plan_t1/response.json').read_text() == '{"launch_source":""}'


def test_formal_record_unity_dispatch_passes_binding(ready, monkeypatch):
    import time
    from types import SimpleNamespace
    from pipeline.eval.stage1 import record
    from engine_adapters.unity3d.playtest import runtime_initializer as adapter
    out, project, folder, executable = ready
    executable.update(probes=[], max_duration_ms=75000)
    write_json(folder.parent / 'plan.json', executable)
    monkeypatch.setattr(record, '_schedule', lambda *args: (None, None))
    calls = []
    def capture(**kwargs):
        calls.append(kwargs)
        assert kwargs['scene'] == '' and kwargs['input_transport'] == 'internal'
        adapter.load(kwargs['runtime_entry'], project)
        return {'synthetic': True}
    client = SimpleNamespace(playtest=SimpleNamespace(record=capture))
    result = record._native(client, 'unity3d', project, executable, folder / 'native',
                            {'recording_ms': 75000}, time.monotonic() + 200)
    assert result == {'synthetic': True} and len(calls) == 1 and calls[0]['duration'] == 75
    assert not (folder / 'native/report.json').exists()


@pytest.fixture
def captured_synthetic(ready):
    from pipeline.eval.repair import unity_natural_entry_recovery as r
    out, project, capture, executable = ready
    n.record_binding(project, executable, capture)
    result = {'complete': True, 'takes': [{'take': 1}]}
    write_json(out / 'playable_score.json', result)
    response = out / 'model_calls/plan_t1_natural_entry_v1/response.json'
    write_json(response, executable)
    write_json(response.parent / 'accepted_response.json', {'path': response.name, 'sha256': sha256(response)})
    command = ['/synthetic/Unity', '-projectPath', str(project), '-executeMethod',
               'GameFactory3ARuntimeInitializerRecorder.Enter', '--gamefactory-evaluation-scene', '',
               '--gamefactory-runtime-entry-source', executable['launch_source'],
               '--gamefactory-runtime-entry-receipt', str(capture / 'native/runtime_initializer_native.json')]
    cleanup = {'command': command, 'ok': True, 'process_exit_verified': True,
               'group_exit_verified': True, 'detached_exit_verified': True}
    for p in (capture / 'editor_cleanup.json', capture / 'native/editor_cleanup.json'):
        write_json(p, cleanup)
    write_json(capture / 'native/background_input_cleanup.json', {key: True for key in
        ('ok', 'keys_and_buttons_released', 'virtual_devices_removed', 'settings_restored',
         'muted_devices_restored', 'input_filter_removed')})
    write_json(capture / 'native/background_view_cleanup.json', {'ok': True})
    write_json(capture / 'record_result.json', {'frames': 1, 'failed_actions': [],
               'plan_sha256': sha256(capture.parent / 'plan.json')})
    write_json(capture / 'native/report.json', {'frames': 1, 'status': 'passed', 'requested_seconds': 75,
               'recorded_seconds': 75.01, 'errors': [], 'engine': 'unity3d', 'url': str(project),
               'output_dir': str(capture / 'native')})
    write_json(capture / 'native/runtime_initializer_native.json', native(n.reviewed('G039_sky_ring_flight')))
    for directory in (capture, capture / 'native'):
        for channel in ('actions.jsonl', 'state_trace.jsonl', 'event_trace.jsonl'):
            put(directory / channel, '{}\n')
        put(directory / 'frame_index.jsonl', '{"path":"frames/f00001.png"}\n')
        put(directory / 'frames/f00001.png', 'synthetic bytes; this fixture does not claim a real capture')
    return out, capture, result


def test_native_qualification_checks_existing_evidence_only(captured_synthetic):
    from pipeline.eval.repair import unity_natural_entry_recovery as r
    out, capture, result = captured_synthetic
    before = prepare.tree_hashes(out)
    r.verify_takes(out, result)
    assert prepare.tree_hashes(out) == before


@pytest.mark.parametrize('damage', ['duration', 'requested', 'native_source', 'wrapper_called',
                                   'automation', 'scene', 'input_cleanup', 'editor_cleanup',
                                   'canonical_frame', 'raw_frame', 'index', 'record_plan', 'accepted', 'third_take'])
def test_native_qualification_refuses_invalid_capture(captured_synthetic, damage):
    from pipeline.eval.repair import unity_natural_entry_recovery as r
    out, capture, result = captured_synthetic
    if damage in ('duration', 'requested'):
        path = capture / 'native/report.json'; value = read_json(path)
        value['recorded_seconds' if damage == 'duration' else 'requested_seconds'] = 37
        write_json(path, value)
    elif damage in ('native_source', 'wrapper_called'):
        path = capture / 'native/runtime_initializer_native.json'; value = read_json(path)
        value['source_sha256' if damage == 'native_source' else 'entry_method_invoked_by_wrapper'] = (
            '0' * 64 if damage == 'native_source' else True)
        write_json(path, value)
    elif damage in ('automation', 'scene'):
        value = read_json(capture / 'native/editor_cleanup.json')
        if damage == 'automation':
            value['command'].append('--g054-playtest=true')
        else:
            value['command'][value['command'].index('--gamefactory-evaluation-scene') + 1] = 'Fake.unity'
        for path in (capture / 'editor_cleanup.json', capture / 'native/editor_cleanup.json'):
            write_json(path, value)
    elif damage in ('input_cleanup', 'editor_cleanup'):
        path = capture / 'native' / ('background_input_cleanup.json' if damage == 'input_cleanup' else 'editor_cleanup.json')
        value = read_json(path); value['ok'] = False; write_json(path, value)
    elif damage in ('canonical_frame', 'raw_frame'):
        path = capture / ('frames/f00001.png' if damage == 'canonical_frame' else 'native/frames/f00001.png')
        put(path, 'changed')
    elif damage == 'index':
        for directory in (capture, capture / 'native'):
            put(directory / 'frame_index.jsonl', '{"path":"../escape.png"}\n')
    elif damage == 'record_plan':
        path = capture / 'record_result.json'; value = read_json(path)
        value['plan_sha256'] = '0' * 64; write_json(path, value)
    elif damage == 'accepted':
        put(out / 'model_calls/plan_t1_natural_entry_v1/response.json', '{}')
    else:
        (out / 'takes/3').mkdir()
    with pytest.raises((HarnessError, ValueError)):
        r.verify_takes(out, result)


def test_runner_interface_requires_release_and_never_recurses(qualified_synthetic, monkeypatch):
    from pipeline.eval.repair import unity_natural_entry_recovery as r
    out, _, result = qualified_synthetic
    assert r.qualified_completion_score(out) is None
    r.complete_cleanup(out)
    from pipeline.eval.stage1 import playable_support as runner
    def forbidden(*args, **kwargs):
        raise AssertionError('qualified verifier must not invoke runner, cleanup, engine or model')
    monkeypatch.setattr(runner, 'completed_score', forbidden)
    monkeypatch.setattr(runner, 'cleanup', forbidden)
    assert r.qualified_completion_score(out) == result
    put(out / 'takes/1/record/native/frame.png', 'tampered after cleanup')
    with pytest.raises(HarnessError):
        r.qualified_completion_score(out)


def test_runner_interface_missing_or_tampered_release(qualified_synthetic):
    from pipeline.eval.repair import unity_natural_entry_recovery as r
    out, _, result = qualified_synthetic
    r.complete_cleanup(out)
    path = out / n.REL / 'hold_release.json'
    value = read_json(path)
    value['cleanup_sha256'] = '0' * 64
    write_json(path, value)
    with pytest.raises(HarnessError, match='release'):
        r.qualified_completion_score(out)
    path.unlink()
    assert r.qualified_completion_score(out) is None


@pytest.fixture(params=[False, True], ids=['new-builtin', 'existing-builtin'])
def generated_input_lock(ready, monkeypatch, request):
    """Synthetic resolver output after the real official input migration."""
    out, project, folder, plan = ready
    from pipeline.eval.stage1 import unity_input
    from pipeline.game_eval.whitebox_eval import unity_runtime_dependencies as deps
    original = __import__('pathlib').Path(read_json(out / 'manifest.json')['project_source'])
    package = out / 'package-cache/com.unity.inputsystem@1.7.0'
    write_json(package / 'package.json', {'name': 'com.unity.inputsystem', 'version': '1.7.0',
               'dependencies': {'com.unity.modules.uielements': '1.0.0'}})
    monkeypatch.setattr(unity_input, 'package_root', lambda: package)
    put(original / 'ProjectSettings/ProjectSettings.asset', 'activeInputHandler: 0\n')
    put(original / 'ProjectSettings/InputManager.asset', 'InputManager:\n  m_Axes: []\n')
    children = {name: '1.0.0' for name in ('com.unity.modules.ui', 'com.unity.modules.imgui',
                                         'com.unity.modules.jsonserialize')}
    old = {'dependencies': {name: {'version': '1.0.0', 'depth': 0, 'source': 'builtin',
                                   'dependencies': {}} for name in children}}
    if request.param:
        old['dependencies']['com.unity.modules.uielements'] = {
            'version': '1.0.0', 'depth': 0, 'source': 'builtin', 'dependencies': children}
    write_json(original / 'Packages/packages-lock.json', old)
    for copy in (out / 'input/project', project):
        shutil.rmtree(copy)
        shutil.copytree(original, copy)
    manifest = read_json(out / 'manifest.json')
    manifest.update(project_digest=prepare.tree_digest(prepare.tree_hashes(original)),
                    snapshot_digest=prepare.tree_digest(prepare.tree_hashes(out / 'input/project')))
    write_json(out / 'manifest.json', manifest)
    save_contract(out)
    (folder / 'unity_input_migration.json').unlink()
    unity_input.migrate(project, folder / 'unity_input_migration.json')
    editor = __import__('pathlib').Path(read_json(folder / 'unity_editor.json')['editor']['binary'])
    builtin = editor.parent.parent / 'Resources/PackageManager/BuiltInPackages/com.unity.modules.uielements/package.json'
    write_json(builtin, {'name': 'com.unity.modules.uielements', 'version': '1.0.0',
                        'type': 'module', 'dependencies': children})
    (folder / 'observer_runtime_dependencies.json').unlink()
    deps.prepare(project, editor, folder / 'observer_runtime_dependencies.json')
    after = read_json(project / 'Packages/packages-lock.json')
    after['dependencies'].update({
        'com.unity.inputsystem': {'version': 'file:' + str(package), 'depth': 0, 'source': 'local',
                                 'dependencies': {'com.unity.modules.uielements': '1.0.0'}},
        'com.unity.modules.uielements': old['dependencies'].get('com.unity.modules.uielements',
            {'version': '1.0.0', 'depth': 1, 'source': 'builtin', 'dependencies': children})})
    write_json(project / 'Packages/packages-lock.json', after)
    return out, project, folder, plan, package, builtin


def test_generated_input_lock_keeps_source_guard_and_retains_exact_proof(generated_input_lock):
    out, project, folder, plan, package, builtin = generated_input_lock
    frozen = prepare.tree_hashes(out / 'input/project')
    args = n.record_binding(project, plan, folder)
    assert n.load_record_binding(args['runtime_entry'], project)['source'] == plan['launch_source']
    proof = read_json(folder / 'runtime_entry_source_audit.json')['generated_input_lock']
    expected = ['com.unity.inputsystem']
    if 'com.unity.modules.uielements' not in read_json(out / 'input/project/Packages/packages-lock.json')['dependencies']:
        expected.append('com.unity.modules.uielements')
    assert proof['added'] == expected
    import hashlib
    assert all(hashlib.sha256(row['text'].encode()).hexdigest() == row['sha256']
               for row in proof['evidence'].values())
    assert prepare.tree_hashes(out / 'input/project') == frozen
    assert not (folder / 'native').exists()


@pytest.mark.parametrize('damage', ['authored_record', 'arbitrary_package', 'package_version',
    'depth', 'depth_bool', 'metadata_hash', 'builtin_metadata', 'wrong_origin', 'root_field', 'source_edit'])
def test_generated_input_lock_cannot_bypass_source_or_dependency_guards(generated_input_lock, damage):
    out, project, folder, plan, package, builtin = generated_input_lock
    lock = project / 'Packages/packages-lock.json'
    value = read_json(lock)
    if damage == 'authored_record':
        value['dependencies']['com.unity.modules.ui']['depth'] = 2
    elif damage == 'arbitrary_package':
        value['dependencies']['com.unity.modules.particlesystem'] = {
            'version': '1.0.0', 'depth': 0, 'source': 'builtin', 'dependencies': {}}
    elif damage == 'package_version':
        value['dependencies']['com.unity.inputsystem']['version'] = '1.14.0'
    elif damage == 'depth':
        value['dependencies']['com.unity.inputsystem']['depth'] = 1
    elif damage == 'depth_bool':
        value['dependencies']['com.unity.inputsystem']['depth'] = False
    elif damage == 'metadata_hash':
        put(package / 'package.json', '{}')
    elif damage == 'builtin_metadata':
        write_json(builtin, {'name': 'com.unity.modules.uielements', 'version': '9.0.0'})
    elif damage == 'wrong_origin':
        path = folder / 'unity_input_migration.json'
        data = read_json(path); data['input_system_package_origin'] = 'author_preserved'
        write_json(path, data)
    elif damage == 'root_field':
        value['extra'] = 'not resolver metadata'
    elif damage == 'source_edit':
        put(project / 'Assets/Other.cs', 'authored change hidden behind valid lock')
    write_json(lock, value)
    with pytest.raises((HarnessError, ValueError)):
        n.record_binding(project, plan, folder)
    assert not (folder / 'runtime_initializer_entry.json').exists()
