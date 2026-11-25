"""Bounded mouse gestures, using fractions of the actual input viewport."""
import math

MOUSE_KINDS = frozenset({'mouse_move', 'mouse_click', 'mouse_drag', 'mouse_down', 'mouse_up', 'mouse_hold', 'mouse_wheel'})


# Unity currently implements only these gestures end-to-end. In particular,
# do not advertise wheel/hold/drag until its own translator supports them.
UNITY_MOUSE_KINDS = frozenset({"mouse_move", "mouse_click", "mouse_down", "mouse_up", "mouse_hold", "mouse_drag", "mouse_wheel"})
# UE: viewport_pointer.v1 (in-engine cursor + viewport InputKey; Slate buttons via the recorder virtual user).
UE_MOUSE_KINDS = frozenset({"mouse_move", "mouse_click", "mouse_down", "mouse_up", "mouse_hold", "mouse_drag", "mouse_wheel"})

def mouse_step_schema(kind, *, native=False):
    properties = {
        'id': {'type': 'string'}, 'kind': {'type': 'string', 'enum': [kind]},
        'duration_ms': {'type': 'integer', 'minimum': 100, 'maximum': 6000},
        'x': {'type': 'number', 'minimum': 0, 'maximum': 1},
        'y': {'type': 'number', 'minimum': 0, 'maximum': 1},
    }
    if kind not in {'mouse_move', 'mouse_wheel'}:
        properties['button'] = {'type': 'string', 'enum': ['left', 'right', 'middle']}
    if kind == 'mouse_drag':
        for field in ('to_x', 'to_y'):
            properties[field] = {'type': 'number', 'minimum': 0, 'maximum': 1}
    if kind == 'mouse_wheel':
        for field in ('delta_x', 'delta_y'):
            properties[field] = {'type': 'integer', 'minimum': -1200, 'maximum': 1200}
    if native:
        for field in ('purpose', 'expected_observation'):
            properties[field] = {'type': 'string'}
    return {'type': 'object', 'properties': properties,
            'required': list(properties), 'additionalProperties': False}


def validate_mouse_step(step):
    kind = step.get('kind')
    if kind not in MOUSE_KINDS:
        raise ValueError('unknown mouse gesture')
    duration = step.get('duration_ms')
    if type(duration) is not int or not 100 <= duration <= 6000:
        raise ValueError('mouse gesture duration must be 100..6000 ms')
    fields = ('x', 'y', 'to_x', 'to_y') if kind == 'mouse_drag' else ('x', 'y')
    for field in fields:
        value = step.get(field)
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError(f'mouse {field} must be a finite viewport fraction in 0..1')
    if kind == 'mouse_wheel':
        for field in ('delta_x', 'delta_y'):
            if type(step.get(field)) is not int or not -1200 <= step[field] <= 1200:
                raise ValueError('wheel deltas must be integer pixels in -1200..1200')
        if step['delta_x'] == step['delta_y'] == 0:
            raise ValueError('wheel needs nonzero delta')
    if kind not in {'mouse_move', 'mouse_wheel'} and step.get('button') not in {'left', 'right', 'middle'}:
        raise ValueError('unsupported physical mouse button')
    return step
