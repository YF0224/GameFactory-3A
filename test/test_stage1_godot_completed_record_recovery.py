"""Recovery consumes completed native evidence and never launches another game."""
import json
import shutil
from types import SimpleNamespace

from PIL import Image
import pytest

from pipeline.eval.stage1 import prepare, record
from pipeline.eval.stage1.paths import read_json, write_json
from pipeline.eval.stage1.llm import HarnessError
from pipeline.eval.repair import godot_completed_record_recovery as recovery


@pytest.fixture
def completed(tmp_path, monkeypatch):
    out = tmp_path / 'run'
    source = out / 'input/project'
    source.mkdir(parents=True)
    (source / 'project.godot').write_text('test fixture project')
    shutil.copytree(source, out / 'runtime/project')
    manifest = {'engine': 'godot', 'budget': {'recording_ms': 4000}, 'input_hashes': {},
                'snapshot_digest': prepare.tree_digest(prepare.tree_hashes(source))}
    write_json(out / 'manifest.json', manifest)
    write_json(out / 'status.json', {'state': 'HARNESS_ERROR', 'error': 'unfinished native'})
    plan = {'probes': [{'id': 'p', 'steps': [{'id': 's', 'kind': 'input', 'key': 'Space'}]}]}
    runtime = out / 'takes/1/record'
    native = runtime / 'native'
    (native / 'frames').mkdir(parents=True)
    write_json(runtime.parent / 'plan.json', plan)
    write_json(runtime / 'recording_plan.json', {**plan, 'recording_ms': 4000})
    write_json(runtime / 'capture_mode.json', {'mode': 'dense'})
    write_json(native / 'launch_diagnostics.json',
               {'project_root': str(out / 'runtime/project'), 'classification': 'LAUNCHABLE'})
    write_json(native / 'execution.json', {
        'complete': True, 'status': 'CAPTURED', 'no_state_injection': True,
        'clock': 'session_monotonic', 'capture_errors': [], 'duration_ms': 4005,
        'frames': 2, 'states': 2, 'probes': [{'id': 'p', 'status': 'EXECUTED',
          'preconditions_met': True, 'steps': [{'id': 's', 'kind': 'input', 'sent': True}]}]})
    rows = []
    for num, timestamp in enumerate([10, 3000], 1):
        path = f'frames/f{num:05}.png'
        Image.new('RGB', (8, 6), (num * 50, 20, 30)).save(native / path)
        rows.append({'path': path, 't_ms': timestamp, 'viewport': {'width': 8, 'height': 6}})
    (native / 'frame_index.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
    (native / 'state_trace.jsonl').write_text('{"t_ms":0}\n{"t_ms":4005}\n')
    actions = [{'kind': 'observation', 'phase': 'start', 'probe_id': 'p', 'step_id': 's'},
               {'kind': 'press', 'action_id': 'p/s', 'key': 'Space', 'sent': True},
               {'kind': 'observation', 'phase': 'end', 'probe_id': 'p', 'step_id': 's'}]
    (native / 'actions.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in actions))
    (native / 'engine.log').write_text('PILOT_COMPLETE frames=2 states=2\n')
    write_json(native / 'input_view_cleanup.json', {'input_cleanup': True,
        'held_keys_after_release': 0, 'capture_callback_disconnected': True, 'process_exit_requested': True})
    monkeypatch.setattr(record, 'make_client', lambda *a: pytest.fail('must not launch an engine'))
    monkeypatch.setattr(recovery.subprocess, 'run', lambda *a, **k: SimpleNamespace(stdout=''))
    return out, runtime, native, manifest, plan


def test_standard_record_resumes_without_touching_native(completed):
    out, runtime, native, manifest, plan = completed
    before = prepare.tree_hashes(native)
    result = record.record(out, manifest, plan)
    assert result['frames'] == 2
    assert result['recovery']['re_recorded'] is False
    assert result['elapsed_ms'] is None
    assert result['cleanup']['host_process_cleanup.json']['original_exit_code'] is None
    assert read_json(out / 'recovery/godot_completed_record_v1/take_1/receipt.json')['unobserved_tail_ms'] == 1000
    assert prepare.tree_hashes(native) == before
    assert record.record(out, manifest, plan) == result


@pytest.mark.parametrize('damage', ['unfinished', 'frame_missing', 'bad_image', 'source_changed',
    'wrong_plan', 'failed_input', 'wrong_key', 'short_state', 'missing_cleanup', 'live_process',
    'canonical_conflict', 'host_failure'])
def test_unsafe_recovery_preserves_evidence(completed, damage, monkeypatch):
    out, runtime, native, manifest, plan = completed
    if damage == 'unfinished':
        data = read_json(native / 'execution.json'); data['complete'] = False
        write_json(native / 'execution.json', data)
    if damage == 'frame_missing': (native / 'frames/f00002.png').unlink()
    if damage == 'bad_image': (native / 'frames/f00002.png').write_text('not a png')
    if damage == 'source_changed': (out / 'runtime/project/project.godot').write_text('changed source')
    if damage == 'wrong_plan': write_json(runtime / 'recording_plan.json', {})
    if damage in ('failed_input', 'wrong_key'):
        text = (native / 'actions.jsonl').read_text()
        text = text.replace('true', 'false') if damage == 'failed_input' else text.replace('Space', 'Left')
        (native / 'actions.jsonl').write_text(text)
    if damage == 'short_state': (native / 'state_trace.jsonl').write_text('{"t_ms":0}\n{"t_ms":3000}\n')
    if damage == 'missing_cleanup': (native / 'input_view_cleanup.json').unlink()
    if damage == 'live_process':
        monkeypatch.setattr(recovery.subprocess, 'run', lambda *a, **k:
            SimpleNamespace(stdout='123 1 Godot --path ' + str(out / 'runtime/project')))
    if damage == 'canonical_conflict': (runtime / 'actions.jsonl').write_text('conflicting canonical evidence')
    if damage == 'host_failure': write_json(runtime / 'record_error.json', {'error': 'different failure'})
    before = prepare.tree_hashes(native)
    with pytest.raises(HarnessError, match='recovery refused'):
        record.record(out, manifest, plan)
    assert not (runtime / 'record_result.json').exists()
    assert prepare.tree_hashes(native) == before
