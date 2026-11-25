"""Identity carried by input adapters without interpreting gameplay outcomes."""
from copy import deepcopy

FIELDS = ('action_id', 'probe_id', 'step_id', 'criterion_ids', 'purpose',
          'expected_observation', 'planned_t_ms', 'planned_end_t_ms')


def action_metadata(action):
    return {key: deepcopy(action[key]) for key in FIELDS if key in action}


def action_duration_ms(action):
    duration = action.get('duration_ms', 100)
    return duration if action.get('action') in {
        'wait', 'mouse_move', 'mouse_down', 'mouse_up', 'mouse_click',
        'mouse_drag', 'mouse_hold', 'mouse_wheel'} else max(duration, 100)
