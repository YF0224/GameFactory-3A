"""Offline, adversarial provenance tests; never invoke npm, models or recording."""
import fcntl
import json
import os
import shutil
from pathlib import Path

import pytest

from pipeline.eval.repair import completed_local_plugin_recovery as recovery
from pipeline.eval.stage1 import prepare, record
from pipeline.eval.stage1.llm import HarnessError
from pipeline.eval.stage1.paths import read_json, write_json
from test.test_stage1_record_recovery import completed


@pytest.fixture
def relocated(completed, monkeypatch, tmp_path):
    out, runtime, folder, manifest, plan = completed
    plugin = tmp_path / 'official/plugin'
    plugin.mkdir(parents=True)
    write_json(plugin / 'package.json', {'name': '@a3game/playable', 'version': '1.0.0'})
    monkeypatch.setattr(recovery, 'PLUGIN', plugin)
    source = tmp_path / 'original'
    source.mkdir()
    old_rel = os.path.relpath(plugin, source)
    new_rel = os.path.relpath(plugin, out / 'runtime/project')
    package = {'dependencies': {'@a3game/playable': 'file:' + str(plugin)}}
    lock = {'lockfileVersion': 3, 'packages': {
        '': package,
        old_rel: {'name': '@a3game/playable', 'version': '1.0.0'},
        'node_modules/@a3game/playable': {'resolved': old_rel, 'link': True},
        'node_modules/other': {'version': '1.0.0', 'integrity': 'fixture-integrity'}}}
    snapshot, project = out / 'input/project', out / 'runtime/project'
    write_json(snapshot / 'package.json', package)
    write_json(snapshot / 'package-lock.json', lock)
    shutil.copytree(snapshot, source, dirs_exist_ok=True)
    shutil.copytree(snapshot, project, dirs_exist_ok=True)
    (project / 'package-lock.json').write_bytes((snapshot / 'package-lock.json').read_bytes().replace(
        json.dumps(old_rel).encode(), json.dumps(new_rel).encode()))
    link = project / 'node_modules/@a3game/playable'
    link.parent.mkdir(parents=True)
    link.symlink_to(plugin, target_is_directory=True)
    manifest.update(project_source=str(source), project_digest=prepare.tree_digest(prepare.tree_hashes(source)),
                    snapshot_digest=prepare.tree_digest(prepare.tree_hashes(snapshot)))
    write_json(out / 'manifest.json', manifest)
    write_json(out / 'status.json', {'state': 'HARNESS_ERROR', 'step': 'record_t1', 'error': 'lock changed'})
    (runtime / 'dependency_install_stdout.log').write_text('added 1 package')
    (runtime / 'dependency_install_stderr.log').write_text('')
    return out, runtime, folder, source, project


def test_completed_recovery_preserves_sources_native_and_errors(relocated, monkeypatch):
    out, runtime, folder, source, project = relocated
    monkeypatch.setattr(record, 'make_client', lambda *a, **k: pytest.fail('no native invocation'))
    monkeypatch.setattr(record, 'record', lambda *a, **k: pytest.fail('no recording entry'))
    before = {str(p): p.read_bytes() for root in (source, out / 'input', project, runtime / 'native')
              for p in root.rglob('*') if p.is_file()}
    parents = {str(p): p.read_bytes() for p in (out / 'status.json', runtime / 'record_error.json',
                                             out / 'takes/1/plan.json')}
    result = recovery.recover(out)
    assert result['frames'] > 0
    receipt = read_json(Path(result['recovery_receipt']))
    assert receipt['new_recording'] is False
    assert receipt['source_proof']['transform'].startswith('two exact')
    assert all(Path(p).read_bytes() == data for p, data in {**before, **parents}.items())
    assert recovery.recover(out) == result
    assert len(list((runtime / 'postprocess_recovery').iterdir())) == 1


@pytest.mark.parametrize('mutation', [
    'source_edit', 'source_delete', 'source_add', 'source_symlink', 'original_edit',
    'snapshot_edit', 'lock_version', 'lock_integrity', 'other_dependency', 'plugin_metadata',
    'plugin_destination', 'installed_destination', 'extra_lock_whitespace', 'missing_install_log',
    'incomplete', 'cleanup', 'frame_missing', 'frame_symlink', 'action_failed', 'plan_edit', 'canonical_conflict',
])
def test_rejects_unproven_changes_without_partial_publication(relocated, mutation, tmp_path):
    out, runtime, folder, source, project = relocated
    if mutation == 'source_edit':
        (project / 'index.html').write_text('changed')
    elif mutation == 'source_delete':
        (project / 'index.html').unlink()
    elif mutation == 'source_add':
        (project / 'injected.js').write_text('changed')
    elif mutation == 'source_symlink':
        (project / 'index.html').unlink()
        (project / 'index.html').symlink_to(source / 'index.html')
    elif mutation == 'original_edit':
        (source / 'index.html').write_text('changed')
    elif mutation == 'snapshot_edit':
        (out / 'input/project/index.html').write_text('changed')
    elif mutation in ('lock_version', 'lock_integrity', 'other_dependency', 'plugin_metadata', 'plugin_destination'):
        path = project / 'package-lock.json'
        obj = read_json(path)
        if mutation == 'lock_version': obj['lockfileVersion'] = 2
        elif mutation == 'lock_integrity': obj['packages']['node_modules/other']['integrity'] = 'changed'
        elif mutation == 'other_dependency': obj['packages']['node_modules/other']['version'] = '2.0.0'
        elif mutation == 'plugin_destination': obj['packages']['node_modules/@a3game/playable']['resolved'] = '../elsewhere'
        else:
            rel = obj['packages']['node_modules/@a3game/playable']['resolved']
            obj['packages'][rel]['version'] = '2.0.0'
        write_json(path, obj)
    elif mutation == 'installed_destination':
        link = project / 'node_modules/@a3game/playable'
        link.unlink()
        link.symlink_to(source, target_is_directory=True)
    elif mutation == 'extra_lock_whitespace':
        path = project / 'package-lock.json'
        path.write_bytes(path.read_bytes() + b'\n')
    elif mutation == 'missing_install_log':
        (runtime / 'dependency_install_stdout.log').unlink()
    elif mutation == 'incomplete':
        obj = read_json(folder / 'report.json'); obj['sampling_complete'] = False
        write_json(folder / 'report.json', obj)
    elif mutation == 'cleanup':
        obj = read_json(folder / 'host_process_cleanup.json'); obj['server_group_alive'] = True
        write_json(folder / 'host_process_cleanup.json', obj)
    elif mutation == 'frame_missing':
        next((folder / 'frames').iterdir()).unlink()
    elif mutation == 'frame_symlink':
        path = next((folder / 'frames').iterdir())
        path.unlink(); path.symlink_to(source / 'index.html')
    elif mutation == 'action_failed':
        path = folder / 'actions.jsonl'
        rows = [json.loads(l) for l in path.read_text().splitlines()]
        rows[0]['sent'] = False
        path.write_text(''.join(json.dumps(r) + '\n' for r in rows))
    elif mutation == 'plan_edit':
        path = out / 'takes/1/plan.json'; obj = read_json(path)
        obj['probes'][0]['steps'][0]['key'] = 'Enter'; write_json(path, obj)
    elif mutation == 'canonical_conflict':
        (runtime / 'actions.jsonl').write_text('conflicting')
    with pytest.raises(HarnessError):
        recovery.recover(out)
    assert not (runtime / 'record_result.json').exists()
    assert not (runtime / 'postprocess_recovery').exists()


def test_busy_take_refuses(relocated):
    out, runtime, *_ = relocated
    with (runtime / '.postprocess.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(HarnessError, match='already active'):
            recovery.recover(out)


def test_idempotent_reuse_rechecks_native(relocated):
    out, runtime, folder, *_ = relocated
    recovery.recover(out)
    next((folder / 'frames').iterdir()).write_bytes(b'changed')
    with pytest.raises(HarnessError, match='native evidence changed'):
        recovery.recover(out)
