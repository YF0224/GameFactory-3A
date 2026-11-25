"""Synthetic-only tests: no model, Unity, actual recovery or published score."""
import json
import os
from pathlib import Path
import shutil
import struct
from types import SimpleNamespace

import pytest

from pipeline.eval.stage1 import plan, playable_rules, prepare, record
from pipeline.eval.repair import unity_imgui_transport_recovery as recovery
from pipeline.eval.stage1.paths import DELIVERY_SCHEMA, read_json, sha256, write_json


def jsonl(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(row) + '\n' for row in data))


def native_result(out, take, *, queued):
    executable = read_json(out / f'takes/{take}/plan.json')
    r = out / f'takes/{take}/record'
    native = r / 'native'
    native.mkdir(parents=True)
    actions = plan.native_actions(executable, 'unity3d')
    write_json(r / 'action_schedule.json', {'version': record.VERSION, 'actions': actions})
    trace = []
    for a in actions:
        if a['action'] != 'mouse_click':
            continue
        for phase in ('down', 'up'):
            trace.append({**a, 'phase': phase, 'sent': True, 'imgui_queued': queued,
                          'x': struct.unpack('<f', struct.pack('<f', a['x']))[0],
                          'y': struct.unpack('<f', struct.pack('<f', a['y']))[0],
                          'cleanup_release': False, 'source': 'internal_driver',
                          'transport': 'InputSystem.QueueStateEvent', 'error': ''})
    frames = [{'path': f'frames/f{i}.png', 't_ms': i * 1000} for i in (1, 2)]
    for base in (r, native):
        jsonl(base / 'actions.jsonl', trace)
        jsonl(base / 'frame_index.jsonl', frames)
        for f in frames:
            (base / f['path']).parent.mkdir(exist_ok=True)
            (base / f['path']).write_bytes(b'synthetic frame pixels')
        write_json(base / 'editor_cleanup.json', {k: True for k in (
            'ok', 'process_exit_verified', 'group_exit_verified', 'detached_exit_verified')})
    write_json(native / 'background_input_cleanup.json', {k: True for k in (
        'ok', 'keys_and_buttons_released', 'virtual_devices_removed', 'settings_restored',
        'muted_devices_restored', 'input_filter_removed')})
    write_json(native / 'background_view_cleanup.json', {'ok': True})
    write_json(native / 'report.json', {'status': 'passed', 'engine': 'unity3d',
        'requested_seconds': 75, 'errors': [], 'frames': len(frames),
        'url': str(out / 'runtime/project'), 'output_dir': str(native)})
    result = {'engine': 'unity3d', 'take': take, 'plan_sha256': sha256(out / f'takes/{take}/plan.json'),
              'failed_actions': [], 'frames': len(frames)}
    write_json(r / 'record_result.json', result)
    return result


@pytest.fixture
def parent(tmp_path, monkeypatch):
    out, source = tmp_path / 'parent', tmp_path / 'original'
    (source / 'Assets').mkdir(parents=True)
    (source / 'Assets/Main.unity').write_text('synthetic source, never executed')
    source_sha = prepare.tree_digest(prepare.tree_hashes(source))
    monkeypatch.setattr(recovery, 'SOURCE_SHA', source_sha)
    monkeypatch.setattr(recovery, 'production', lambda: {'producer.py': 'frozen-producer'})
    monkeypatch.setattr(recovery.shutil, 'disk_usage', lambda _: SimpleNamespace(free=50 * 1024 ** 3))
    write_json(out / 'input/criteria.json', {'checks': 'frozen'})
    (out / 'input/requirement.txt').write_text('frozen requirement')
    delivery_dir = tmp_path / 'shims' / recovery.CASE / 'retest'
    delivery = {'schema': DELIVERY_SCHEMA, 'stage': 'stage1', 'game_id': recovery.CASE,
                'model': 'sol', 'run_id': 'retest', 'engine': 'unity3d',
                'project_root': str(source), 'entry': 'Assets/Main.unity',
                'created_at': '2026-11-09T00:00:00Z', 'generator': {'kind': 'legacy'}}
    write_json(delivery_dir / 'delivery.json', delivery)
    manifest = {'game_id': recovery.CASE, 'engine': 'unity3d', 'entry': 'Assets/Main.unity',
                'suite': 'stage1', 'project_source': str(source), 'project_digest': source_sha,
                'snapshot_digest': source_sha, 'models': {'planner': 'gpt-6-astra', 'judge': 'none'},
                'input_hashes': prepare.tree_hashes(out / 'input'),
                'criteria_sha256': sha256(out / 'input/criteria.json'),
                'delivery': delivery, 'delivery_dir': str(delivery_dir),
                'budget': {'gameplay_ms': 180000, 'recording_ms': 180000,
                           'total_wall_clock_ms': 405000, 'engine_call_ms': 450000}}
    write_json(out / 'manifest.json', manifest)
    write_json(out / 'cleanup.json', {'removed': ['input/project', 'runtime/project'],
                                    'freed_bytes': 1490111280})
    write_json(out / 'qualification_hold.json', {'kind': 'HARNESS_UI_INPUT_NOT_DELIVERED',
                                               'affected_takes': [1, 2]})
    write_json(out / 'playable_score.json', {'complete': True, 'playable': 66.67})
    write_json(out / 'status.json', {'state': 'done'})
    accepted = {}
    for take in (1, 2):
        executable = {'engine': 'unity3d', 'launch_source': 'Assets/Main.unity',
            'max_duration_ms': 75000, 'summary': f'accepted take {take}',
            'probes': [{'id': 'entry', 'criterion_ids': ['play.operate'], 'steps': [
                {'id': 'click', 'kind': 'mouse_click', 'duration_ms': 150,
                 'x': 0.1953125, 'y': 0.4597222, 'button': 'left'}]}]}
        write_json(out / f'takes/{take}/plan.json', executable)
        folder = out / f'model_calls/plan_t{take}'
        write_json(folder / 'response.json', executable)
        accepted[take] = sha256(folder / 'response.json')
        write_json(folder / 'accepted_response.json', {'path': 'response.json', 'sha256': accepted[take]})
        write_json(folder / 'invocation.json', {'model_requested': 'gpt-6-astra', 'exit_code': 0})
        native_result(out, take, queued=False)
    monkeypatch.setattr(recovery, 'ACCEPTED', accepted)
    # Fail immediately if a test accidentally enters the official recording/model path.
    monkeypatch.setattr(record, 'record', lambda *a: pytest.fail('unexpected native call'))
    monkeypatch.setattr(plan, 'make_plan', lambda *a, **kw: pytest.fail('planner must never be invoked'))
    return out


def verdicts(op):
    return {k: {'status': op if k == 'play.operate' else 'PASS'}
            for k in ('play.import', 'play.launch', 'play.operate')}


def fake_recorder(monkeypatch, calls, *, queued=True, failure=False):
    def run(out, manifest, executable, take):
        assert os.environ[recovery.ENV_KEY] == '1'
        assert manifest['budget']['recording_ms'] == 75000
        assert manifest['budget']['total_wall_clock_ms'] == 300000
        assert executable == read_json(out / f'takes/{take}/plan.json')
        assert (out.parent / f'take{take}.claim.json').is_file()
        calls.append(take)
        if failure:
            raise RuntimeError('synthetic native failure')
        return native_result(out, take, queued=queued)
    monkeypatch.setattr(record, 'record', run)


def test_preview_read_only(parent):
    before = recovery.files(parent)
    preview = recovery.preview(parent)
    assert preview['state'] == 'PREVIEW_ONLY'
    assert preview['binding']['max_native_calls'] == 2
    assert recovery.files(parent) == before
    assert not (parent / 'recovery').exists()


@pytest.mark.parametrize('damage', ['source', 'metadata', 'plan', 'response', 'acceptance', 'hold',
                                   'editor_cleanup', 'input_cleanup', 'transport', 'copy',
                                   'source_symlink', 'artifact_symlink', 'other_lineage', 'third_take'])
def test_preflight_rejects_drift(parent, damage):
    if damage == 'source':
        Path(read_json(parent / 'manifest.json')['project_source'], 'Assets/Main.unity').write_text('changed')
    elif damage == 'metadata': (parent / 'input/requirement.txt').write_text('changed')
    elif damage == 'plan': write_json(parent / 'takes/1/plan.json', {})
    elif damage == 'response': write_json(parent / 'model_calls/plan_t1/response.json', {})
    elif damage == 'acceptance': write_json(parent / 'model_calls/plan_t1/accepted_response.json', {})
    elif damage == 'hold': write_json(parent / 'qualification_hold.json', {})
    elif damage == 'editor_cleanup': write_json(parent / 'takes/1/record/native/editor_cleanup.json', {})
    elif damage == 'input_cleanup': write_json(parent / 'takes/1/record/native/background_input_cleanup.json', {})
    elif damage == 'transport':
        p = parent / 'takes/1/record'
        for base in (p, p / 'native'):
            trace = recovery.rows(base / 'actions.jsonl')
            trace[0]['imgui_queued'] = True
            jsonl(base / 'actions.jsonl', trace)
    elif damage == 'copy': (parent / 'input/project').mkdir()
    elif damage == 'source_symlink':
        Path(read_json(parent / 'manifest.json')['project_source'], 'link').symlink_to(parent)
    elif damage == 'artifact_symlink': (parent / 'link').symlink_to(parent / 'status.json')
    elif damage == 'other_lineage': (parent / 'recovery/other').mkdir(parents=True)
    elif damage == 'third_take': (parent / 'takes/3').mkdir()
    with pytest.raises((ValueError, KeyError)):
        recovery.preview(parent)


@pytest.mark.parametrize('first_pass,expected', [(True, [1]), (False, [1, 2])])
def test_bounded_recovery_preserves_parent_and_reuses_plans(parent, monkeypatch, first_pass, expected):
    before = recovery.files(parent, parent=True)
    calls = []
    fake_recorder(monkeypatch, calls)
    monkeypatch.setattr(playable_rules, 'evaluate', lambda o, m, t: verdicts(
        'PASS' if first_pass or t == 2 else 'UNVERIFIED'))
    monkeypatch.setenv(recovery.ENV_KEY, 'prior-env')
    review = recovery.preview(parent)['review_sha256']
    result = recovery.execute(parent, review)
    assert calls == expected
    assert os.environ[recovery.ENV_KEY] == 'prior-env'
    assert result['native_calls_consumed'] == len(expected)
    assert result['models_invoked'] == 0
    assert result['state'] == 'RECORDED_PENDING_PARENT_REVIEW'
    assert recovery.files(parent, parent=True) == before
    assert recovery.files(parent / recovery.LINEAGE / 'archive') == before
    child = Path(result['child'])
    assert not (child / 'playable_score.json').exists()
    prepare.verify(child)
    assert recovery.execute(parent, review)['takes'] == result['takes']
    assert calls == expected  # idempotence never invokes native again
    assert read_json(parent / 'playable_score.json')['playable'] == 66.67


def test_failed_claim_cannot_retry_or_create_second_take(parent, monkeypatch):
    calls = []
    fake_recorder(monkeypatch, calls, failure=True)
    review = recovery.preview(parent)['review_sha256']
    with pytest.raises(RuntimeError, match='synthetic'):
        recovery.execute(parent, review)
    with pytest.raises(ValueError, match='consumed native claim'):
        recovery.execute(parent, review)
    assert calls == [1]
    assert (parent / recovery.LINEAGE / 'take1.failure.json').exists()
    assert not (parent / recovery.LINEAGE / 'take2.claim.json').exists()


def test_invalid_new_transport_retains_claim_and_no_score(parent, monkeypatch):
    calls = []
    fake_recorder(monkeypatch, calls, queued=False)
    review = recovery.preview(parent)['review_sha256']
    for _ in range(2):
        with pytest.raises(ValueError, match='mouse transport'):
            recovery.execute(parent, review)
    assert calls == [1]
    assert not (parent / recovery.LINEAGE / 'run/playable_score.json').exists()


def test_review_drift_refuses_restore(parent):
    with pytest.raises(ValueError, match='review binding changed'):
        recovery.execute(parent, 'wrong')
    assert not (parent / recovery.LINEAGE).exists()


def test_low_disk_refuses_restore(parent, monkeypatch):
    review = recovery.preview(parent)['review_sha256']
    monkeypatch.setattr(recovery.shutil, 'disk_usage', lambda _: SimpleNamespace(free=1))
    with pytest.raises(ValueError, match='disk reserve'):
        recovery.execute(parent, review)
    assert not (parent / recovery.LINEAGE).exists()


def test_existing_partial_prepare_is_preserved(parent):
    review = recovery.preview(parent)['review_sha256']
    p = parent / recovery.LINEAGE
    p.mkdir(parents=True)
    (p / 'partial').write_text('preserve')
    with pytest.raises(ValueError, match='partial preparation'):
        recovery.execute(parent, review)
    assert (p / 'partial').read_text() == 'preserve'


def test_identity_lock_blocks(parent):
    review = recovery.preview(parent)['review_sha256']
    with recovery.locked(parent / 'takes/1/record/.postprocess.lock'):
        with pytest.raises(ValueError, match='identity already active'):
            recovery.execute(parent, review)
    assert not (parent / recovery.LINEAGE).exists()


def test_archive_tamper_blocks_resume(parent, monkeypatch):
    calls = []
    fake_recorder(monkeypatch, calls)
    monkeypatch.setattr(playable_rules, 'evaluate', lambda *a: verdicts('PASS'))
    review = recovery.preview(parent)['review_sha256']
    recovery.execute(parent, review)
    (parent / recovery.LINEAGE / 'archive/status.json').write_text('{}')
    with pytest.raises(ValueError, match='archive changed'):
        recovery.execute(parent, review)
    assert calls == [1]


def test_producer_drift_cannot_launch_second_take(parent, monkeypatch):
    calls = []
    fake_recorder(monkeypatch, calls)
    def changed(*args):
        monkeypatch.setattr(recovery, 'production', lambda: {'producer.py': 'changed'})
        return verdicts('UNVERIFIED')
    monkeypatch.setattr(playable_rules, 'evaluate', changed)
    review = recovery.preview(parent)['review_sha256']
    with pytest.raises(ValueError, match='producer changed'):
        recovery.execute(parent, review)
    assert calls == [1]


@pytest.mark.parametrize('damage', ['frame', 'native_path', 'missing_frame', 'cleanup'])
def test_repaired_evidence_gate(parent, monkeypatch, damage):
    calls = []
    fake_recorder(monkeypatch, calls)
    original = record.record
    def damaged(out, manifest, executable, take):
        result = original(out, manifest, executable, take)
        r = out / f'takes/{take}/record'
        if damage == 'frame': (r / 'frames/f1.png').write_bytes(b'altered')
        if damage == 'missing_frame': (r / 'frames/f1.png').unlink()
        if damage == 'native_path':
            report = read_json(r / 'native/report.json'); report['output_dir'] = '/wrong'
            write_json(r / 'native/report.json', report)
        if damage == 'cleanup': write_json(r / 'native/background_input_cleanup.json', {})
        return result
    monkeypatch.setattr(record, 'record', damaged)
    review = recovery.preview(parent)['review_sha256']
    with pytest.raises((ValueError, FileNotFoundError)):
        recovery.execute(parent, review)
    assert calls == [1]
    assert not (parent / recovery.LINEAGE / 'ready_for_review.json').exists()


def ready_run(parent, monkeypatch, *, second=False):
    calls = []
    fake_recorder(monkeypatch, calls)
    monkeypatch.setattr(playable_rules, 'evaluate', lambda o, m, t:
                        verdicts('UNVERIFIED' if second and t == 1 else 'PASS'))
    review = recovery.preview(parent)['review_sha256']
    ready = recovery.execute(parent, review)
    monkeypatch.setattr(record, 'record', lambda *a: pytest.fail('finalization invoked native'))
    return review, ready, calls


@pytest.mark.parametrize('second', [False, True])
def test_official_finalize_cache_only_and_official_cleanup(parent, monkeypatch, second):
    before = recovery.files(parent, parent=True)
    review, ready, calls = ready_run(parent, monkeypatch, second=second)
    # Actual pipeline.run_playable generates score/status; only rules use synthetic frames.
    result = recovery.finalize(parent, review)
    assert result['schema'] == recovery.REPLACEMENT_SCHEMA
    child = Path(ready['child'])
    score = recovery.qualified_replacement_score(parent)
    assert score == read_json(child / 'playable_score.json')
    assert score['playable'] == 100.0
    assert len(score['takes']) == (2 if second else 1)
    assert calls == ([1, 2] if second else [1])
    assert recovery.files(parent, parent=True) == before
    assert recovery.finalize(parent, review) == result
    final = read_json(parent / recovery.LINEAGE / 'finalization.json')
    assert final['native_calls'] == final['model_calls'] == 0
    # Exercise actual runner cleanup, not a test facsimile.
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / 'scripts_new'))
    from pipeline.eval.stage1.playable_support import cleanup
    cleanup(child)
    assert recovery.qualified_replacement_score(parent) == score
    assert recovery.finalize(parent, review) == result
    assert not (child / 'input/project').exists()
    assert not (child / 'runtime/project').exists()
    assert recovery.files(parent, parent=True) == before
    # Later production changes never masquerade as the old producer, nor revoke a sealed result.
    monkeypatch.setattr(recovery, 'production', lambda: {'new_producer': 'new_hash'})
    assert recovery.qualified_replacement_score(parent) == score


@pytest.mark.parametrize('damage', ['source', 'archive', 'frame', 'ready', 'claim', 'score',
                                   'finalization', 'hold', 'partial_cleanup', 'cleanup_receipt',
                                   'path_escape', 'receipt_symlink', 'copy'])
def test_replacement_hook_fails_closed(parent, monkeypatch, damage):
    review, ready, _ = ready_run(parent, monkeypatch)
    recovery.finalize(parent, review)
    child = Path(ready['child'])
    lineage = parent / recovery.LINEAGE
    if damage == 'source':
        Path(read_json(parent / 'manifest.json')['project_source'], 'Assets/Main.unity').write_text('changed')
    elif damage == 'archive': (lineage / 'archive/status.json').write_text('{}')
    elif damage == 'frame': (child / 'takes/1/record/frames/f1.png').write_bytes(b'changed')
    elif damage == 'ready': write_json(lineage / 'ready_for_review.json', {})
    elif damage == 'claim': write_json(lineage / 'take1.claim.json', {})
    elif damage == 'score': write_json(child / 'playable_score.json', {'complete': True, 'playable': 100})
    elif damage == 'finalization': write_json(lineage / 'finalization.json', {})
    elif damage == 'hold': (parent / 'qualification_hold.json').unlink()
    elif damage == 'partial_cleanup': shutil.rmtree(child / 'input/project')
    elif damage == 'cleanup_receipt':
        shutil.rmtree(child / 'input/project'); shutil.rmtree(child / 'runtime/project')
        write_json(child / 'cleanup.json', {'removed': ['input/project', 'runtime/project'], 'freed_bytes': 0})
    elif damage == 'path_escape':
        r = read_json(lineage / 'replacement.json'); r['child_score'] = '../../playable_score.json'
        write_json(lineage / 'replacement.json', r)
    elif damage == 'receipt_symlink':
        p = lineage / 'finalization.json'
        content = p.read_bytes(); p.unlink(); other = parent.parent / 'receipt'
        other.write_bytes(content); p.symlink_to(other)
    elif damage == 'copy': (child / 'runtime/project/Assets/Main.unity').write_text('changed')
    assert recovery.qualified_replacement_score(parent) is None


def test_missing_replacement_returns_none(parent):
    assert recovery.qualified_replacement_score(parent) is None


def test_finalize_refuses_missing_second_cache_instead_of_recording(parent, monkeypatch):
    review, ready, calls = ready_run(parent, monkeypatch)
    # Force official pipeline to ask for take2, not present in the ready receipt.
    monkeypatch.setattr(playable_rules, 'evaluate', lambda *a: verdicts('UNVERIFIED'))
    with pytest.raises(ValueError, match='unqualified cached take'):
        recovery.finalize(parent, review)
    assert calls == [1]
    assert not (parent / recovery.LINEAGE / 'replacement.json').exists()
    assert recovery.qualified_replacement_score(parent) is None


def test_finalize_rejects_preexisting_drift_before_pipeline(parent, monkeypatch):
    review, ready, calls = ready_run(parent, monkeypatch)
    (Path(ready['child']) / 'takes/1/record/frames/f1.png').write_bytes(b'changed')
    with pytest.raises(ValueError, match='ready child evidence changed'):
        recovery.finalize(parent, review)
    assert calls == [1]
    assert not (parent / recovery.LINEAGE / 'replacement.json').exists()


def test_finalize_rejects_producer_change_before_scoring(parent, monkeypatch):
    review, ready, calls = ready_run(parent, monkeypatch)
    monkeypatch.setattr(recovery, 'production', lambda: {'different': 'producer'})
    with pytest.raises(ValueError, match='producer changed before finalization'):
        recovery.finalize(parent, review)
    assert not (Path(ready['child']) / 'playable_score.json').exists()


def test_execute_cannot_rewrite_finalized_ready_receipt(parent, monkeypatch):
    review, ready, calls = ready_run(parent, monkeypatch)
    recovery.finalize(parent, review)
    before = recovery.files(parent / recovery.LINEAGE)
    with pytest.raises(ValueError, match='finalization already started'):
        recovery.execute(parent, review)
    assert recovery.files(parent / recovery.LINEAGE) == before
    assert recovery.qualified_replacement_score(parent)['playable'] == 100.0
    assert calls == [1]


def test_partial_finalization_is_not_overwritten(parent, monkeypatch):
    review, ready, calls = ready_run(parent, monkeypatch)
    path = parent / recovery.LINEAGE / 'finalization.json'
    write_json(path, {'partial': 'preserve'})
    with pytest.raises(ValueError, match='partial finalization retained'):
        recovery.finalize(parent, review)
    assert read_json(path) == {'partial': 'preserve'}
    assert not (Path(ready['child']) / 'playable_score.json').exists()
    assert calls == [1]
