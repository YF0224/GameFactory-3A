"""Synthetic preflight guard tests. No Unity, models, input or score invocation."""
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import json
import shutil
import sys

import pytest

from pipeline.eval.stage1 import unity_original_scene_job_preflight as p


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value if isinstance(value, str) else json.dumps(value))


@pytest.fixture
def case(tmp_path, monkeypatch):
    source = tmp_path / 'original/run/project'
    root = tmp_path / 'results'
    out = root / 'gpt_astra6/G045_daily_street_lightlane/retest'
    code = 'Assets/Editor/ComposeScene.cs'
    put(source / code, '// synthetic test author bytes; never executed')
    put(source / 'Packages/manifest.json', {'dependencies': {}})
    put(source / 'ProjectSettings/ProjectVersion.txt', 'm_EditorVersion: 2022.3.62t13')
    spec = {'output_scene': 'Assets/Scenes/Lightlane.unity', 'objects': [{'name': 'original'}]}
    put(source.parent / 'scene_spec.json', spec)
    for rel in ('input/project', 'runtime/project'):
        shutil.copytree(source, out / rel)
    tree = p.prepare.tree_digest(p.prepare.tree_hashes(source))
    entry = {'model': 'Astra', 'game_id': 'G045_daily_street_lightlane', 'project': str(source),
             'mode': 'compose', 'code': code, 'code_sha256': p.sha256(source / code),
             'recipe_rel': 'scene_spec.json', 'recipe_kind': 'direct',
             'recipe_sha256': p.sha256(source.parent / 'scene_spec.json'),
             'scene': spec['output_scene'], 'project_digest': tree, 'snapshot_digest': tree}
    put(out / 'manifest.json', {'delivery': {'model': 'astra', 'project_root': str(source), 'required_real_clients': 1},
        'game_id': entry['game_id'], 'engine': 'unity3d', 'project_source': str(source), 'project_digest': tree,
        'snapshot_digest': tree, 'input_hashes': {}, 'models': {'planner': 'gpt-6-astra', 'judge': 'none'}})
    put(out / 'status.json', {'step': 'plan_t1', 'state': 'HARNESS_ERROR'})
    put(out / 'model_calls/plan_t1_002/failure.json', {'rejected': True})
    target = {'model': 'Astra', 'game_id': entry['game_id'], 'project': str(source), 'engine': 'unity3d', 'required_real_clients': 1}
    targets = tmp_path / 'targets.json'
    put(targets, {'targets': [target]})
    monkeypatch.setattr(p, 'TARGETS', targets)
    monkeypatch.setattr(p, 'OUTPUT_ROOT', root)
    monkeypatch.setattr(p, 'ENTRIES', {'Astra:G045': entry})
    monkeypatch.setattr(p.shutil, 'disk_usage', lambda _: SimpleNamespace(free=30*1024**3))
    monkeypatch.setattr(p.unity_editor, 'choose', lambda _: {'editor': {'binary': sys.executable}})
    monkeypatch.setattr(p, 'producer', lambda: {str(Path(p.__file__).resolve().relative_to(p.FRAMEWORK)): p.sha256(Path(p.__file__))})
    monkeypatch.setattr(p, 'processes', lambda: {})
    monkeypatch.setattr(p, 'windows', lambda _: [])
    @contextmanager
    def slot():
        yield tmp_path / 'formal-gui.lock'
    monkeypatch.setattr(p.record, 'gui_slot', slot)
    calls = []
    def native(cmd, folder):
        calls.append(cmd)
        put(folder / 'console.log', 'Synthetic native fixture, not real evidence')
        put(folder / 'builder.log', 'Synthetic success')
        put(folder / 'process_started.json', {'pid': 123456, 'pgid': 123456, 'cmd': cmd})
        put(folder / 'cleanup.json', {'process_cleanup_verified': True, 'view_cleanup_verified': True,
                                     'owned_processes_alive': [], 'remaining_windows': [], 'window_query_error': None})
        if entry['mode'] == 'compose':
            put(folder / 'project' / entry['scene'], 'synthetic scene bytes')
            put(folder / 'compose_report.json', {'ok': True, 'scenePath': entry['scene']})
        return {'cmd': cmd, 'pid': 123456, 'pgid': 123456, 'exit_code': 0, 'timeout': False, 'spawn_error': None}
    monkeypatch.setattr(p, 'native', native)
    return SimpleNamespace(out=out, source=source, entry=entry, target=target, targets=targets, calls=calls, native=native)


def test_compose_success_and_exact_job(case):
    result = p.execute(case.out)
    folder = case.out / p.REL
    assert result['classification'] == 'BUILDER_FINISHED_REQUIRES_ADMISSION'
    assert result['complete'] is False and result['score_written'] is False
    assert (folder / 'scene_spec.json').read_bytes() == (case.source.parent / 'scene_spec.json').read_bytes()
    assert case.calls[0][-6:] == ['-executeMethod', p.METHOD, '--job', str(folder / 'scene_spec.json'), '--report', str(folder / 'compose_report.json')]
    assert not (case.out / 'playable_score.json').exists()
    assert p.verify_receipt(case.out) == result


def test_payload_exact_archive_structural_derivation(case):
    report = {'payload': {'class_method': p.METHOD, 'project_path': str(case.source),
                         'spec': p.read_json(case.source.parent / 'scene_spec.json')}, 'old_failure': 'retained'}
    path = case.source.parent / 'validation/scene_compose.json'
    put(path, report)
    case.entry.update(recipe_rel='validation/scene_compose.json', recipe_kind='report_payload', recipe_sha256=p.sha256(path))
    p.execute(case.out)
    folder = case.out / p.REL
    assert (folder / 'original_recipe.json').read_bytes() == path.read_bytes()
    assert p.read_json(folder / 'scene_spec.json') == report['payload']['spec']


def test_import_only_no_method_or_job(case):
    case.entry.update(mode='import_only', recipe_rel=None, recipe_kind=None, recipe_sha256=None, scene=None)
    result = p.execute(case.out)
    assert result['classification'] == 'IMPORT_FINISHED_REQUIRES_ADMISSION'
    assert not {'--job', '--report', '-executeMethod'} & set(case.calls[0])


def test_max_one_even_after_success(case):
    p.execute(case.out)
    with pytest.raises(p.HarnessError, match='MAX1'):
        p.execute(case.out)
    assert len(case.calls) == 1


def test_existing_claim_consumed_without_result(case):
    put(case.out / p.REL / 'native.claim.json', {'failed_start': True})
    with pytest.raises(p.HarnessError, match='MAX1'):
        p.execute(case.out)
    assert not case.calls


@pytest.mark.parametrize('kind', ['recipe', 'code', 'frozen', 'runtime', 'status', 'target_source', 'multi_client', 'delivery_source', 'planner'])
def test_reject_preflight_tampering(case, kind):
    if kind in ('recipe', 'code', 'frozen', 'runtime'):
        path = {'recipe': case.source.parent / 'scene_spec.json', 'code': case.source / case.entry['code'],
                'frozen': case.out / 'input/project' / case.entry['code'],
                'runtime': case.out / 'runtime/project' / case.entry['code']}[kind]
        path.write_text('tampered')
    elif kind == 'status':
        put(case.out / 'status.json', {'step': 'plan_t1', 'state': 'RUNNING'})
    elif kind in ('target_source', 'multi_client'):
        case.target['project' if kind == 'target_source' else 'required_real_clients'] = '/other/source' if kind == 'target_source' else 2
        put(case.targets, {'targets': [case.target]})
    else:
        m = p.read_json(case.out / 'manifest.json')
        if kind == 'delivery_source': m['delivery']['project_root'] = '/wrong/run'
        else: m['models']['planner'] = 'other'
        put(case.out / 'manifest.json', m)
    with pytest.raises((p.HarnessError, RuntimeError)):
        p.execute(case.out)
    assert not case.calls


def test_wrong_output_route(case, tmp_path):
    other = tmp_path / 'arbitrary'
    shutil.copytree(case.out, other)
    with pytest.raises(p.HarnessError, match='result_dir'):
        p.qualification(other)


@pytest.mark.parametrize('path', ['takes/1/plan.json', 'takes/1/record/record_result.json',
                                  'model_calls/plan_t1/accepted.json', 'playable_score.json',
                                  'recovery/other/native.claim.json'])
def test_existing_evidence_forbids_native(case, path):
    put(case.out / path, {})
    with pytest.raises(p.HarnessError, match='existing accepted/native/score'):
        p.execute(case.out)
    assert not case.calls


def test_symlink_rejected(case):
    (case.source / 'Assets/alias.cs').symlink_to(case.source / case.entry['code'])
    with pytest.raises(p.HarnessError, match='symlink'):
        p.qualification(case.out)


@pytest.mark.parametrize('rel', ['scene_spec.json', 'original_recipe.json', 'builder.log', 'cleanup.json',
                                 'parent_archive/status.json', 'project/Assets/Editor/ComposeScene.cs'])
def test_receipt_tampering_rejected(case, rel):
    p.execute(case.out)
    (case.out / p.REL / rel).write_text('tampered')
    with pytest.raises((p.HarnessError, ValueError)):
        p.verify_receipt(case.out)


def test_compile_failure_current_only(case, monkeypatch):
    def fail(cmd, folder):
        execution = case.native(cmd, folder)
        put(folder / 'builder.log', 'Assets/Original.cs(12,1): error CS0102: duplicate Part')
        return {**execution, 'exit_code': 1}
    monkeypatch.setattr(p, 'native', fail)
    result = p.execute(case.out)
    assert result['classification'] == 'PRODUCT_COMPILE_FAILURE'
    assert 'CS0102' in result['errors'][0]


def test_no_old_error_promoted(case, monkeypatch):
    put(case.out / 'model_calls/old_compile.log', 'error CS1069: ParticleSystem historical only')
    def fail(cmd, folder):
        execution = case.native(cmd, folder)
        (folder / 'compose_report.json').unlink()
        put(folder / 'builder.log', 'current licensing failure')
        return {**execution, 'exit_code': 1}
    monkeypatch.setattr(p, 'native', fail)
    result = p.execute(case.out)
    assert result['classification'] == 'HARNESS_ERROR' and result['errors'] == []


def test_cleanup_unverified_is_harness(case, monkeypatch):
    def fail(cmd, folder):
        execution = case.native(cmd, folder)
        cleanup = p.read_json(folder / 'cleanup.json')
        cleanup['view_cleanup_verified'] = False
        put(folder / 'cleanup.json', cleanup)
        return execution
    monkeypatch.setattr(p, 'native', fail)
    assert p.execute(case.out)['classification'] == 'HARNESS_ERROR'


def test_disk_guard_before_copy(case, monkeypatch):
    monkeypatch.setattr(p.shutil, 'disk_usage', lambda _: SimpleNamespace(free=p.RESERVE))
    with pytest.raises(p.HarnessError, match='reserve'):
        p.execute(case.out)
    assert not case.calls and not (case.out / p.REL / 'project').exists()


def test_recheck_parent_after_wait(case, monkeypatch):
    @contextmanager
    def slot():
        put(case.out / 'model_calls/late.json', {'late': True})
        yield '/formal/lock'
    monkeypatch.setattr(p.record, 'gui_slot', slot)
    with pytest.raises(p.HarnessError, match='changed before native'):
        p.execute(case.out)
    assert not case.calls and not (case.out / p.REL / 'native.claim.json').exists()


def test_partial_staging_never_overwritten(case):
    put(case.out / p.REL / 'original_recipe.json', 'partial evidence')
    with pytest.raises(p.HarnessError, match='partial preflight'):
        p.execute(case.out)
    assert (case.out / p.REL / 'original_recipe.json').read_text() == 'partial evidence'
    assert not case.calls


def test_missing_artifact_binding_rejected(case):
    p.execute(case.out)
    path = case.out / p.REL / 'result.json'
    obj = p.read_json(path)
    del obj['artifacts']['execution.json']
    put(path, obj)
    with pytest.raises(p.HarnessError, match='required artifact'):
        p.verify_receipt(case.out)


def test_real_process_exit_and_cleanup_without_engine(tmp_path, monkeypatch):
    monkeypatch.setattr(p, 'windows', lambda _: [])
    command = [sys.executable, '-c', 'print("preflight process supervision test")']
    execution = p.native(command, tmp_path, timeout=10)
    assert execution['exit_code'] == 0 and execution['pid'] > 0
    cleanup = p.read_json(tmp_path / 'cleanup.json')
    assert cleanup['process_cleanup_verified'] and cleanup['view_cleanup_verified']
    assert cleanup['owned_processes_alive'] == [] and cleanup['signals'] == []
