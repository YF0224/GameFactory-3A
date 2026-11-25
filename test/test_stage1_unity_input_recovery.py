import json
from pathlib import Path
from unittest.mock import patch
import pytest
from pipeline.eval.repair import unity_input_recovery as recovery
from pipeline.eval.stage1.paths import write_json, sha256
from pipeline.eval.stage1.llm import HarnessError


@pytest.fixture
def failed(tmp_path):
    out = tmp_path / 'eval'
    record = out / 'takes/1/record'
    native = record / 'native'
    native.mkdir(parents=True)
    project = out / 'runtime/project'
    (project / 'Packages').mkdir(parents=True)
    (out / 'input/project/Packages').mkdir(parents=True)
    source = tmp_path / 'original'
    source.mkdir()
    old = '/cache/' + recovery.OLD_PACKAGE
    write_json(out / 'status.json', {'state': 'HARNESS_ERROR', 'step': 'record_t1'})
    write_json(out / 'takes/1/plan.json', {'accepted': True})
    (record / 'import.log').write_text(recovery.OLD_PACKAGE + ' error CS0246 INavigationEventData')
    write_json(record / 'import_result.json', {'exit_code': 1, 'timeout': False})
    write_json(native / 'editor_cleanup.json', {k: True for k in ('ok', 'process_exit_verified', 'group_exit_verified', 'detached_exit_verified')})
    write_json(out / 'input/project/Packages/manifest.json', {'dependencies': {}})
    write_json(project / 'Packages/manifest.json', {'dependencies': {'com.unity.inputsystem': 'file:' + old}})
    write_json(out / 'runtime/unity_input_migration.json', {'migrated': True, 'input_system_package': old, 'changes': []})
    cache = tmp_path / 'cache'
    cache.mkdir()
    write_json(cache / 'package.json', {'version': '1.7.0'})
    with patch.object(recovery.prepare, 'verify', return_value={'engine': 'unity3d', 'project_source': str(source), 'project_digest': recovery.prepare.tree_digest({})}), patch.object(recovery.unity_input, 'package_root', return_value=cache):
        yield out


def test_archives_failure_retains_plan_and_recovers_once(failed):
    plan = failed / 'takes/1/plan.json'
    before = sha256(plan)
    result = recovery.recover(failed)
    assert result['prior_gameplay_recordings'] == 0
    assert sha256(plan) == before
    assert (failed / 'takes/1/input_import_recovery_v1/record/import.log').is_file()
    assert not (failed / 'takes/1/record/native').exists()
    assert (failed / 'takes/1/record/.postprocess.lock').is_file()
    with pytest.raises(HarnessError, match='already attempted'):
        recovery.recover(failed)


def test_refuses_any_recorded_frame(failed):
    (failed / 'takes/1/record/native/frame.png').write_bytes(b'frame')
    with pytest.raises(HarnessError, match='gameplay'):
        recovery.recover(failed)
    assert not (failed / 'takes/1/input_import_recovery_v1').exists()


def test_refuses_authored_dependency(failed):
    write_json(failed / 'input/project/Packages/manifest.json', {'dependencies': {'com.unity.inputsystem': '1.14.0'}})
    with pytest.raises(HarnessError, match='authored'):
        recovery.recover(failed)


def test_refuses_unverified_cleanup(failed):
    write_json(failed / 'takes/1/record/native/editor_cleanup.json', {'ok': False})
    with pytest.raises(HarnessError, match='cleanup'):
        recovery.recover(failed)
