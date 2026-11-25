from pathlib import Path
from unittest.mock import patch

import pytest

from pipeline.eval.repair import unity_audio_recovery as recovery
from pipeline.eval.stage1.paths import write_json, sha256, read_json
from pipeline.eval.stage1.llm import HarnessError


@pytest.fixture
def failed(tmp_path):
    out = tmp_path / 'eval'
    record = out / 'takes/1/record'
    native = record / 'native'
    native.mkdir(parents=True)
    project = out / 'runtime/project'
    source = tmp_path / 'original'
    source.mkdir()
    editor = tmp_path / 'Editor.app/Contents/MacOS/Unity'
    editor.parent.mkdir(parents=True)
    editor.touch()
    builtin = editor.parent.parent / 'Resources/PackageManager/BuiltInPackages/com.unity.modules.audio/package.json'
    write_json(builtin, {'name': 'com.unity.modules.audio', 'version': '1.0.0', 'type': 'module'})
    write_json(out / 'status.json', {'state': 'HARNESS_ERROR', 'step': 'record_t1'})
    write_json(out / 'takes/1/plan.json', {'accepted': True})
    write_json(record / 'adapter_result.json', {'ok': False, 'errors': ['injected Unity evaluation driver/recorder failed compilation']})
    write_json(native / 'editor_failure.json', {'tail': [recovery.ERROR], 'critical_context': [recovery.ERROR]})
    clean = {k: True for k in ('ok', 'process_exit_verified', 'group_exit_verified', 'detached_exit_verified')}
    clean['command'] = [str(editor), '-projectPath', str(project)]
    write_json(native / 'editor_cleanup.json', clean)
    write_json(record / 'unity_editor.json', {'editor': {'binary': str(editor)}})
    write_json(out / 'input/project/Packages/manifest.json', {'dependencies': {}})
    write_json(project / 'Packages/manifest.json', {'dependencies': {'com.unity.inputsystem': 'file:/cache/1.7.0'}})
    write_json(out / 'runtime/unity_input_migration.json', {'changes': []})
    with patch.object(recovery.prepare, 'verify', return_value={
            'engine': 'unity3d', 'project_source': str(source),
            'project_digest': recovery.prepare.tree_digest({})}):
        yield out


def test_preserves_failure_plan_and_runtime_then_recovers_only_once(failed):
    paths = [failed / 'takes/1/plan.json', failed / 'runtime/project/Packages/manifest.json']
    before = {str(p): sha256(p) for p in paths}
    result = recovery.recover(failed)
    assert result['prior_gameplay_recordings'] == 0
    assert {str(p): sha256(p) for p in paths} == before
    archive = failed / 'takes/1/audio_import_recovery_v1'
    assert all(sha256(archive / 'record' / p) == h for p, h in result['prior_artifacts'].items())
    assert not (failed / 'takes/1/record/native').exists()
    with pytest.raises(HarnessError, match='already attempted'):
        recovery.recover(failed)


@pytest.mark.parametrize('mutation', ['frame', 'cleanup', 'error', 'scored', 'recorded', 'authored_audio', 'runtime_audio', 'builtin', 'other_project', 'source'])
def test_rejects_inapplicable_or_unverified_recovery_without_archive(failed, mutation):
    record = failed / 'takes/1/record'
    if mutation == 'frame': (record / 'native/frame.png').write_bytes(b'frame')
    elif mutation == 'cleanup': write_json(record / 'native/editor_cleanup.json', {'ok': False})
    elif mutation == 'error': write_json(record / 'native/editor_failure.json', {'tail': 'unrelated error'})
    elif mutation == 'scored': write_json(failed / 'playable_score.json', {'complete': True})
    elif mutation == 'recorded': write_json(record / 'record_result.json', {'frames': ['a']})
    elif mutation in ('authored_audio', 'runtime_audio'):
        folder = 'input' if mutation == 'authored_audio' else 'runtime'
        write_json(failed / folder / 'project/Packages/manifest.json', {'dependencies': {'com.unity.modules.audio': '1.0.0'}})
    elif mutation == 'builtin':
        editor = Path(read_json(record / 'unity_editor.json')['editor']['binary'])
        write_json(editor.parent.parent / 'Resources/PackageManager/BuiltInPackages/com.unity.modules.audio/package.json', {'name': 'wrong'})
    elif mutation == 'other_project':
        f = record / 'native/editor_cleanup.json'
        data = read_json(f)
        data['command'][-1] = '/another/project'
        write_json(f, data)
    elif mutation == 'source': (failed.parent / 'original/authored.cs').write_text('changed')
    with pytest.raises(HarnessError): recovery.recover(failed)
    assert not (failed / 'takes/1/audio_import_recovery_v1').exists()
    assert (record / 'native').exists()
