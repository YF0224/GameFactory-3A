"""Offline regression fixtures; never start a browser or produce evaluation scores."""
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline.eval.stage1 import capture, prepare, record
from pipeline.eval.stage1.paths import read_json, sha256, write_json
from pipeline.eval.stage1.llm import HarnessError
from engine_adapters.three_js.playtest.client import ThreePlaytestClient


@pytest.fixture
def completed(tmp_path):
    out = tmp_path / 'run'
    project = out / 'input/project'
    project.mkdir(parents=True)
    (project / 'index.html').write_text('test fixture')
    shutil.copytree(project, out / 'runtime/project')
    manifest = {'engine': 'three_js', 'budget': {'recording_ms': 4000},
                'snapshot_digest': prepare.tree_digest(prepare.tree_hashes(project)), 'input_hashes': {}}
    write_json(out / 'manifest.json', manifest)
    plan = {'probes': [{'id': 'probe', 'criterion_ids': ['play.operate'],
                       'steps': [{'id': 'press', 'kind': 'input', 'key': 'Space', 'duration_ms': 100}]}]}
    write_json(out / 'takes/1/plan.json', plan)
    runtime = out / 'takes/1/record'
    folder = runtime / 'native/take'
    folder.mkdir(parents=True)
    actions = record.native_actions(plan, 'three_js')
    write_json(runtime / 'record_error.json', {'type': 'KeyError', 'error': "'plan'"})
    write_json(runtime / 'action_schedule.json', {'version': record.VERSION, 'actions': actions})
    action_plan = record.three_js_plan(actions)
    write_json(runtime / 'three_js_action_plan.json', action_plan)
    schedule, _ = capture.schedule(actions, 4000)
    write_json(runtime / 'capture_schedule.json', schedule)
    write_json(folder / 'capture_schedule.json', schedule)
    write_json(folder / 'play_started.json', {'recorder_elapsed_ms': 0})
    rows = []
    for n, point in enumerate(schedule['points']):
        path = f'frames/f{n}.jpg'
        (folder / path).parent.mkdir(exist_ok=True)
        (folder / path).write_bytes(b'unit-test-frame')
        rows.append({'frame_id': f'FRAME_{n}', 'path': path, 't_ms': point['at_ms'] + 2,
                     'sample_at_ms': point['at_ms'], 'capture_ids': point['capture_ids'],
                     'criterion_ids': point['criterion_ids']})
    (folder / 'frame_index.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
    traces = [{'action_id': a['action_id'], 't_ms': n * 100, 'end_t_ms': n * 100 + 50,
               'input_completed_t_ms': n * 100 + 5, 'sent': True} for n, a in enumerate(actions)]
    (folder / 'actions.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in traces))
    report = {'status': 'completed', 'engine': 'three_js', 'mode': 'gameplay', 'output_dir': str(folder),
              'source_hash': None, 'url': 'http://127.0.0.1:12345', 'fps': 10, 'viewport': {'width': 1280, 'height': 720},
              'sparse_capture': True, 'clock': 'realtime', 'fixed_tick': False, 'sampling_complete': True,
              'requested_seconds': 4, 'wallclock_seconds': 4.01, 'frames': len(rows),
              'action_plan': str(runtime / 'three_js_action_plan.json'), 'actions': action_plan['actions'],
              'executed_actions': [{**r, 'ok': True} for r in traces]}
    write_json(folder / 'report.json', report)
    native_manifest = {k: report[k] for k in ('status', 'output_dir', 'source_hash', 'url', 'mode', 'frames', 'fps', 'viewport')}
    native_manifest['report'] = 'take/report.json'
    write_json(folder / 'manifest.json', native_manifest)
    write_json(runtime / 'native/manifest.json', native_manifest)
    write_json(runtime / 'launch_selection.json', {'cwd': str(out / 'runtime/project'), 'url': report['url']})
    write_json(folder / 'browser_cleanup.json', {'input_cleanup': True, 'view_cleanup': True, 'browser_cleanup': True})
    write_json(folder / 'input_view_cleanup.json', {'input_cleanup': True, 'held_keys_after_release': 0, 'held_buttons_after_release': 0})
    write_json(folder / 'host_process_cleanup.json', {'process_cleanup': True, 'server_group_alive': False,
               'recorder': {'process_cleanup': True, 'group_alive': False, 'returncode': 0}})
    return out, runtime, folder, manifest, plan


def hashes(root):
    return {str(p.relative_to(root)): sha256(p) for p in root.rglob('*') if p.is_file()}


def test_recovery_is_offline_idempotent_and_preserves_native(completed, monkeypatch):
    out, runtime, folder, manifest, plan = completed
    monkeypatch.setattr(record, 'make_client', lambda *a, **k: pytest.fail('must not launch'))
    before = hashes(runtime / 'native')
    error = (runtime / 'record_error.json').read_bytes()
    result = record.record(out, manifest, plan)
    assert result['frames'] > 0
    assert read_json(Path(result['recovery_receipt']))['new_recording'] is False
    assert record.recover_completed_threejs(out) == result
    assert hashes(runtime / 'native') == before
    assert (runtime / 'record_error.json').read_bytes() == error
    assert not (out / 'playable_score.json').exists()


@pytest.mark.parametrize('damage', ['incomplete', 'cleanup', 'wrong_source', 'wrong_plan', 'wrong_schedule',
    'wrong_take', 'actions_missing', 'frame_missing', 'frame_escape', 'clock', 'mapping', 'unknown_failure',
    'ambiguous_take', 'canonical_conflict', 'nan_clock'])
def test_recovery_rejects_invalid_evidence(completed, damage):
    out, runtime, folder, manifest, plan = completed
    def change(path, key, value):
        data = read_json(path); data[key] = value; write_json(path, data)
    if damage == 'incomplete': change(folder / 'report.json', 'sampling_complete', False)
    if damage == 'cleanup': change(folder / 'host_process_cleanup.json', 'process_cleanup', False)
    if damage == 'wrong_source': (out / 'runtime/project/index.html').write_text('changed')
    if damage == 'wrong_plan': change(runtime / 'three_js_action_plan.json', 'actions', [])
    if damage == 'wrong_schedule': change(runtime / 'capture_schedule.json', 'points', [])
    if damage == 'wrong_take': change(folder / 'report.json', 'action_plan', '/wrong/plan.json')
    if damage == 'actions_missing': (folder / 'actions.jsonl').write_text('')
    if damage == 'frame_missing': next((folder / 'frames').iterdir()).unlink()
    if damage in ('frame_escape', 'clock', 'mapping', 'nan_clock'):
        rows = [json.loads(s) for s in (folder / 'frame_index.jsonl').read_text().splitlines()]
        if damage == 'frame_escape': rows[0]['path'] = '../../record_error.json'
        if damage == 'clock': rows[0]['t_ms'] = 1000
        if damage == 'nan_clock': rows[0]['t_ms'] = float('nan')
        if damage == 'mapping': rows[0]['capture_ids'] = ['invented']
        (folder / 'frame_index.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
    if damage == 'unknown_failure': change(runtime / 'record_error.json', 'error', 'other')
    if damage == 'ambiguous_take': write_json(runtime / 'native/other/report.json', {})
    if damage == 'canonical_conflict': (runtime / 'actions.jsonl').write_text('conflict')
    before = hashes(runtime / 'native')
    with pytest.raises(HarnessError): record.recover_completed_threejs(out)
    assert not (runtime / 'record_result.json').exists()
    assert hashes(runtime / 'native') == before


def test_missing_slots_are_preserved_as_gaps(completed):
    out, runtime, folder, manifest, plan = completed
    lines = (folder / 'frame_index.jsonl').read_text().splitlines()
    (folder / 'frame_index.jsonl').write_text('\n'.join(lines[1:]) + '\n')
    for p in (folder / 'report.json', folder / 'manifest.json', runtime / 'native/manifest.json'):
        data = read_json(p); data['frames'] -= 1; write_json(p, data)
    result = record.recover_completed_threejs(out)
    assert result['sparse_capture_audit']['missing_slots_ms'] == [0]
    assert result['frames'] == len(lines) - 1


@pytest.mark.parametrize('stage1', [True, False])
def test_client_dispatches_explicit_stage1_only(completed, monkeypatch, stage1):
    out, runtime, folder, manifest, plan = completed
    schedule = read_json(runtime / 'capture_schedule.json')
    if stage1: schedule['audit_protocol'] = capture.AUDIT_PROTOCOL
    write_json(runtime / 'capture_schedule.json', schedule)
    write_json(folder / 'capture_schedule.json', schedule)
    from pipeline.game_eval.whitebox_eval import sparse_evidence
    calls = []
    monkeypatch.setattr(sparse_evidence, 'audit_capture', lambda *a: calls.append('legacy') or {'legacy': True})
    report = read_json(folder / 'report.json')
    # Simulate only the toolchain boundary; the real client validates the saved native report.
    staged = runtime / 'staged'
    folder.rename(staged)
    def run_node(*args, **kwargs):
        staged.rename(folder)
        current = {'report': str(folder / 'report.json'), 'output_dir': str(folder), 'status': 'completed', 'source_hash': None}
        return SimpleNamespace(timed_out=False, returncode=0, stdout=json.dumps(current), stderr='', to_dict=lambda: {})
    client = ThreePlaytestClient.__new__(ThreePlaytestClient)
    client._toolchain = SimpleNamespace(run_node=run_node)
    result = client._record_take(out=runtime / 'native', url=report['url'], project_dir=out / 'runtime/project',
        environment={}, arguments=[], payload={'capture_schedule_path': str(runtime / 'capture_schedule.json')},
        duration=4, fps=10, width=1280, height=720, timeout=10, mode='gameplay', preview=False,
        allow_partial_plan=False, source_hash=None, dependency_notes=[], clock='realtime')
    assert result['ok'], result
    assert calls == ([] if stage1 else ['legacy'])


def test_native_release_rows_separate_end_clocks_and_schedule_whitespace(completed):
    out, runtime, folder, manifest, plan = completed
    rows = [json.loads(line) for line in (folder / 'actions.jsonl').read_text().splitlines()]
    rows[0]['end_t_ms'] += 1
    rows.insert(1, {'kind': 'release', 'action_id': rows[1]['action_id'], 'sent': True})
    (folder / 'actions.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows))
    (folder / 'capture_schedule.json').write_text(json.dumps(read_json(folder / 'capture_schedule.json')))
    before = (runtime / 'capture_schedule.json').read_bytes()
    result = record.recover_completed_threejs(out)
    assert result['actions'] == 3
    assert (runtime / 'capture_schedule.json').read_bytes() == before
