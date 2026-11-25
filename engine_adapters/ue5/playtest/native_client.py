"""Public playtest bridge to the formal, source-pinned native backend.

Admission is an explicit dependency: no gameplay relay is synthesized, no
workspace Python is imported, and an unsupported candidate fails before launch.
"""
import json
import math
from pathlib import Path

from . import native_record


def plan_actions(actions, bindings):
    """Translate public actions to the delivered relay's real key/chord contract."""
    result, at = [], 0
    for index, action in enumerate(actions):
        name = action['action']
        duration = int(action.get('duration_ms', 100))
        if name == 'key':
            key = str(action.get('key', ''))
        elif name == 'move':
            keys = []
            x, y = float(action.get('x', 0)), float(action.get('y', 0))
            if x:
                keys.append('d' if x > 0 else 'a')
            if y:
                keys.append('w' if y > 0 else 's')
            key = '+'.join(keys)
            if not key:
                name = 'wait'
        elif name == 'look':
            keys = []
            yaw, pitch = float(action.get('yaw_delta', 0)), float(action.get('pitch_delta', 0))
            if yaw:
                keys.append('right_arrow' if yaw > 0 else 'left_arrow')
            if pitch:
                keys.append('up_arrow' if pitch > 0 else 'down_arrow')
            key = '+'.join(keys)
            if not key:
                name = 'wait'
        elif name in native_record.POINTER_KINDS:
            # viewport_pointer.v1: any mouse step anywhere in the game viewport (Slate buttons included)
            row = {**action, 'action_id': action.get('action_id') or f'playtest/{index:05d}',
                   'requested_action': name, 'planned_t_ms': at, 'planned_end_t_ms': at + duration,
                   'duration_ms': duration, 'pointer_policy': native_record.VIEWPORT_POINTER_POLICY}
            for k in ('x', 'y') + (('to_x', 'to_y') if name == 'mouse_drag' else ()):
                v = row.get(k)
                if type(v) not in (int, float) or not 0 <= v <= 1:
                    raise ValueError(f'viewport pointer {k} must be a viewport fraction 0..1')
            if name != 'mouse_move' and name != 'mouse_wheel' and row.get('button', 'left') not in ('left', 'right', 'middle'):
                raise ValueError('viewport pointer button must be left / right / middle')
            result.append(row)
            at += duration
            continue
        elif name == 'wait':
            key = ''
        elif name in bindings:
            key = bindings[name]
        else:
            raise ValueError(f'Native viewport relay cannot execute {name}; no desktop fallback')
        row = {**action, 'action': 'wait' if name == 'wait' else 'key', 'key': key,
               'requested_action': action['action'],
               'action_id': action.get('action_id') or f'playtest/{index:05d}',
               'planned_t_ms': at, 'planned_end_t_ms': at + duration,
               'duration_ms': duration}
        result.append(row)
        at += duration
    native_record.expand(result)  # Reject unsupported keys before any launch.
    return result, at


def record(config, *, output_dir, admission, actions, bindings, duration, fps,
           warmup, timeout, map_path, dry_run):
    from ..contracts import UEOperationResult
    from pipeline.eval.refine.common import sha
    from pipeline.eval.stage1.endpoint_sparse import CAPTURE_VERSION

    if not admission:
        raise ValueError('Native recording requires native_admission (formal candidate pin/relay/build); '
                         'pass the admitted candidate, not a workspace script')
    admitted = (dict(admission) if isinstance(admission, dict)
                else json.loads(Path(admission).read_text(encoding='utf-8')))
    expected = config.project_file
    if expected is None or Path(admitted['uproject']).resolve() != expected.resolve():
        raise ValueError('Native admission must bind this exact candidate .uproject')
    if Path(admitted['project']).resolve() != expected.parent.resolve():
        raise ValueError('Native admission project root mismatch')
    from .client import _editor_binary
    if config.ue_root is None or Path(admitted['editor']).resolve() != _editor_binary(config.ue_root).resolve():
        raise ValueError('Native admission editor does not match the configured UE root')
    native_record.verify_pin(admitted)
    # Bind the relay and runtime source/binaries to this candidate, not a
    # same-name historical copy whose pin happens to remain valid.
    pin = json.loads(Path(admitted['pin']).read_text())
    relay = Path(pin['relay']).resolve()
    if not relay.is_relative_to(expected.parent.resolve()):
        raise ValueError('Native relay pin belongs to another candidate')
    formal_relay = admitted.get('relay_kind') == 'formal_native_viewport.v1'
    if formal_relay:
        source = native_record.PLUGIN/native_record.RECORDER_FILES[1]
        if sha(relay) != sha(source):
            raise ValueError('Candidate native viewport hook differs from the formal recorder')
    elif any(marker not in relay.read_text() for marker in
             ('DockInputPort=', 'UGameViewportClient', 'VC->InputKey(Args)', 'native_input.jsonl')):
        raise ValueError('Candidate has no supported delivered native viewport key relay')
    if not pin.get('runtime_sources') or not pin.get('runtime_binaries'):
        raise ValueError('Native admission requires candidate source and rebuilt binary pins')
    for name in ('runtime_sources', 'runtime_binaries'):
        if any(not Path(path).resolve().is_relative_to(expected.parent.resolve()) for path in pin[name]):
            raise ValueError('Native runtime pin belongs to another candidate')
    if admitted.get('native_acceptance'):
        accepted = Path(admitted['native_acceptance'])
        acceptance = json.loads(accepted.read_text())
        if (sha(accepted) != admitted['native_acceptance_sha256'] or not acceptance['ok']
                or acceptance['pin_sha256'] != sha(admitted['pin'])):
            raise ValueError('Native acceptance does not match this production pin')
        for path, digest in acceptance['files'].items():
            if sha(path) != digest:
                raise ValueError('Native acceptance evidence changed')

    normalized, end = plan_actions(actions, bindings)
    if any(a['action'] in native_record.POINTER_KINDS for a in normalized) and not formal_relay:
        raise ValueError('Viewport pointer requires formal source-pinned input; no legacy fallback')
    duration_ms = round(duration * 1000)
    if end > duration_ms:
        raise ValueError(f'Scenario needs {end / 1000:.1f}s but duration is {duration:.1f}s')
    schedule = {'version': CAPTURE_VERSION, 'warmup_ms': round(warmup * 1000),
                'tolerance_ms': max(350, math.ceil(1000 / fps)),
                'points': [{'at_ms': round(index * 1000 / fps),
                            'capture_ids': [f'playtest/frame/{index:05d}'], 'criterion_ids': []}
                           for index in range(math.ceil(duration * fps))],
                'plan': {'windows': [], 'endpoints': []}}
    out = Path(output_dir).expanduser().resolve()
    payload = {'engine': 'ue5', 'project_file': str(expected), 'output_dir': str(out),
               'report_path': str(out / 'report.json'), 'native_capture': True,
               'input_transport': ('formal_native_viewport_pointer_udp' if any(a['action'] in native_record.POINTER_KINDS for a in normalized)
                                   else 'formal_native_viewport_udp' if formal_relay else 'delivered_native_viewport_udp'),
               'native_client_only': True, 'native_admission': admitted,
               'runtime_port': config.runtime_port, 'remote_control_port': config.port,
               'python_command_port': config.python_command_port,
               'actions': normalized, 'capture_schedule': schedule, 'dry_run': dry_run}
    if dry_run:
        return UEOperationResult.success('playtest.record', payload=payload).to_dict()
    # The backend creates a fresh directory atomically and preserves old takes.
    try:
        native_record.record(admitted, normalized, schedule, out, duration_ms,
                             runtime_port=config.runtime_port,
                             remote_control_port=config.port, map_path=map_path,
                             ready_timeout=timeout or 240)
        report = json.loads((out / '_editor_report.json').read_text(encoding='utf-8-sig'))
        frames = sorted((out / 'frames').glob('*.png'))
        if not report.get('ok') or not frames:
            raise RuntimeError('Native recorder produced no usable viewport frames')
        payload['report'] = {**report, 'schema_version': 'gamefactory3a.ue5.playtest_report.v1',
                             'native_client_only': True, 'input_transport': payload['input_transport'],
                             'source': 'formal_native_record', 'frame_paths': list(map(str, frames)),
                             'verification_path': str(out / 'verification.json'),
                             'cleanup_path': str(out / 'cleanup.json')}
        (out / 'report.json').write_text(json.dumps(payload['report'], indent=2) + '\n')
    except Exception as exc:
        return UEOperationResult.failure('playtest.record', f'{type(exc).__name__}: {exc}',
                                         payload=payload).to_dict()
    return UEOperationResult.success('playtest.record', payload=payload, artifacts=[
        {'type': 'playtest_report', 'path': str(out / 'report.json')},
        {'type': 'playtest_actions', 'path': str(out / 'actions.jsonl')},
        {'type': 'playtest_frames', 'path': str(out / 'frames')},
        {'type': 'playtest_cleanup', 'path': str(out / 'cleanup.json')}]).to_dict()
