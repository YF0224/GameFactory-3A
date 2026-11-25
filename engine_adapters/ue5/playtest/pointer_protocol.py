"""Opt-in scene-viewport pointer protocol; never sends desktop/OS input.

Integration with the pinned recorder is staged separately while legacy takes run.
A transport receipt proves coordinates and routing, never gameplay coverage.
"""
import math
import os

POLICY = 'scene_viewport_pointer.v1'
SOURCE = 'FSceneViewport::OnMouseMove+UGameViewportClient::InputKey.v1'
KINDS = frozenset({'mouse_move', 'mouse_click', 'mouse_down', 'mouse_up'})
BUTTON_KEYS = {'left': 'lmb', 'right': 'rmb', 'middle': 'mmb'}


def enabled():
    return os.environ.get('A3GAME_UE_POINTER_POLICY') == POLICY


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def validate(action):
    kind = action.get('action')
    if kind not in KINDS:
        raise ValueError('Viewport pointer supports move/click/down/up only')
    if any(not finite(action.get(k)) or not 0 <= action[k] <= 1 for k in ('x', 'y')):
        raise ValueError('Viewport pointer coordinates must be finite fractions in [0,1]')
    if kind != 'mouse_move' and action.get('button') not in BUTTON_KEYS:
        raise ValueError('Viewport pointer button must be left/right/middle')
    duration = action.get('duration_ms')
    if type(duration) is not int or not 100 <= duration <= 6000:
        raise ValueError('Viewport pointer duration must be integer 100..6000ms')
    if not isinstance(action.get('action_id'), str) or not action['action_id']:
        raise ValueError('Viewport pointer requires action identity')


def expand(actions, expand_keys):
    """Unity click timing: down now, up after min(duration,80ms).

    Explicit down/up may span moves and waits. Reject unmatched edges *before*
    launching. The receiver still releases tracked held buttons on interruption.
    """
    events, held = [], set()
    for action in actions:
        name = action['action']
        if name not in KINDS:
            if name.startswith('mouse_'):
                raise ValueError('Unsupported viewport pointer gesture')
            if name == 'key' and set(action.get('key', '').lower().split('+')) & {'lmb', 'rmb', 'mmb'}:
                raise ValueError('Use coordinate-bearing pointer actions for mouse buttons')
            events.extend(expand_keys([action]))
            continue
        validate(action)
        start, end = action.get('planned_t_ms'), action.get('planned_end_t_ms')
        if not finite(start) or not finite(end) or start < 0 or end - start != action['duration_ms']:
            raise ValueError('Invalid viewport pointer timeline')
        button = action.get('button', 'none') if name != 'mouse_move' else 'none'
        phases = [('move', start)]
        if name == 'mouse_click':
            if button in held:
                raise ValueError('Cannot click an already held button')
            phases = [('down', start), ('up', start + min(action['duration_ms'], 80))]
        elif name == 'mouse_down':
            if button in held:
                raise ValueError('Duplicate mouse_down')
            held.add(button)
            phases = [('down', start)]
        elif name == 'mouse_up':
            if button not in held:
                raise ValueError('mouse_up without mouse_down')
            held.remove(button)
            phases = [('up', start)]
        for phase, at in phases:
            events.append({'type': 'viewport_mouse', 'at_ms': at, 'seq': len(events),
                           'key': BUTTON_KEYS.get(button, 'pointer'), 'phase': phase,
                           'x': action['x'], 'y': action['y'], 'button': button, 'action': action})
    if held:
        raise ValueError('Plan ends with held pointer buttons; add explicit mouse_up')
    events.sort(key=lambda e: (e['at_ms'], e['seq']))
    # Sequences are global across keys and pointer events, never per action.
    for seq, event in enumerate(events):
        event['seq'] = seq
    return events


def wire_message(event, token):
    if not isinstance(token, str) or not token:
        raise ValueError('Viewport pointer needs a token-bound native relay')
    return {'type': 'viewport_mouse', 'policy': POLICY, 'token': token,
            **{k: event[k] for k in ('key', 'phase', 'seq', 'x', 'y', 'button')},
            'action_id': event['action']['action_id']}


def verify_receipt(receipt, event, ready, pid, token):
    expected = wire_message(event, token)
    if any(type(receipt.get(k)) is not type(v) or receipt[k] != v
           for k, v in expected.items() if k not in ('x', 'y')):
        raise RuntimeError('Viewport pointer receipt identity mismatch')
    if any(not finite(receipt.get(k)) or receipt[k] != expected[k] for k in ('x', 'y')):
        raise RuntimeError('Viewport pointer receipt coordinates differ')
    if (type(receipt.get('pid')) is not int or receipt['pid'] != pid
            or receipt.get('routed') is not True or receipt.get('owning_window') is not True
            or receipt.get('os_input_sent') is not False or receipt.get('source') != SOURCE
            or ready.get('viewport_pointer_policy') != POLICY
            or not ready.get('viewport_pointer_window_id')
            or receipt.get('window_id') != ready['viewport_pointer_window_id']):
        raise RuntimeError('Viewport pointer lacks native owning-window proof')
    # Handled=false is legal: Canvas HUD polls PlayerController edges later.
    # It must not be confused with a proven product failure or a successful click.
    if type(receipt.get('handled')) is not bool or not finite(receipt.get('t_ms')):
        raise RuntimeError('Viewport pointer lacks processing receipt')
    geometry = receipt.get('geometry', {})
    for field in ('width', 'height', 'readback_x', 'readback_y', 'controller_x', 'controller_y'):
        if not finite(geometry.get(field)):
            raise RuntimeError('Viewport pointer geometry/readback missing or nonfinite')
    for axis, size in (('x', 'width'), ('y', 'height')):
        if type(geometry[size]) is not int or geometry[size] < 2:
            raise RuntimeError('Viewport pointer viewport dimensions invalid')
        expected_pixel = math.floor(event[axis] * (geometry[size] - 1))
        if any(abs(geometry[k + axis] - expected_pixel) > 1 for k in ('readback_', 'controller_')):
            raise RuntimeError('Viewport pointer readback differs from requested location')


def verify_cleanup(value, ready, pid, token):
    if (value.get('policy') != POLICY or type(value.get('pid')) is not int or value['pid'] != pid
            or value.get('token') != token
            or value.get('window_id') != ready.get('viewport_pointer_window_id')
            or not ready.get('viewport_pointer_window_id')
            or value.get('buttons_after_cleanup') != []
            or value.get('pending_before_cleanup') is not False
            or value.get('os_input_sent') is not False):
        raise RuntimeError('Viewport pointer cleanup incomplete or plan interrupted')
    return value
