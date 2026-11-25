"""Sol's same-call endpoint conditions, real input routes and sparse sampling."""
from pathlib import Path
from .common import dump
from ..whitebox_eval.codex import obj, arr, S, I, B, plan_schema_for_budget
from ..whitebox_eval.runtime import native_actions, validate_native_plan
from ..whitebox_eval.endpoint_sparse import CAPTURE_VERSION


def schema(engine, budget):
    endpoint = obj({'task_id': S, 'executable': B, 'reason': S, 'rubric_quote': S,
                    'visible_conditions': arr(S), 'nonvisual_conditions': arr(S),
                    'last_action_id': S, 'at_ms': I, 'stable_after_ms': I,
                    'window_start_ms': I, 'window_end_ms': I})
    return obj({'native_plan': plan_schema_for_budget(engine, budget), 'endpoints': arr(endpoint)})


def task_specs(game):
    result = [{'task_id': r['selection_id'], 'kind': r['selection_kind'],
               'goal': r['repair_goal'], 'test_action': r['test_action'],
               'pass_condition': r['pass_condition'], 'needs_window': r['selection_kind'] in ('gamefeel', 'vfx')}
              for r in game['repairs']]
    for item in game['imports']:
        simple, detail = item['simple'], item['detail']
        result.append({'task_id': simple['import_id'], 'kind': 'import',
            'asset_kind': simple['asset_kind'], 'goal': simple['import_goal'],
            'description': simple.get('description', ''), 'target': simple.get('target'),
            'requirements': simple.get('asset_requirements'),
            'acceptance_criteria': detail.get('acceptance_criteria'),
            'trigger_contract': detail.get('trigger_contract'),
            'motion_contract': detail.get('motion_contract'),
            'runtime_evidence_required': detail.get('runtime_evidence_required'),
            'payload_status': item['payload']['status'],
            'needs_window': simple['asset_kind'] in ('motion', 'audio', 'cg_video')})
    return result


def compile_plan(result, project, engine, tasks, budget, schedule_path):
    plan = result['native_plan']
    validate_native_plan(plan, Path(project), engine, max_duration_ms=budget)
    actions = native_actions(plan)
    by_id = {r['action_id']: r for r in actions}
    specs = {r['task_id']: r for r in tasks}
    endpoints = result['endpoints']
    if len(endpoints) != len(specs) or {e['task_id'] for e in endpoints} != set(specs):
        raise ValueError('Plan must cover every frozen task exactly once, including unreachable tasks')
    points, contracts, windows = {}, {}, []
    def point(at, capture, ident):
        if not isinstance(at, int) or not 0 <= at <= plan['max_duration_ms'] - 500:
            raise ValueError('Capture outside native recording budget')
        row = points.setdefault(at, {'at_ms': at, 'capture_ids': [], 'criterion_ids': []})
        if capture not in row['capture_ids']:
            row['capture_ids'].append(capture)
        if ident not in row['criterion_ids']:
            row['criterion_ids'].append(ident)
    for endpoint in endpoints:
        ident = endpoint['task_id']
        if not endpoint['reason'] or not endpoint['rubric_quote']:
            raise ValueError('Endpoint requires frozen rubric source and reachability explanation')
        spec = specs[ident]
        frozen = str(spec.get('pass_condition') or spec.get('acceptance_criteria') or spec['goal'])
        if endpoint['rubric_quote'] not in frozen:
            raise ValueError('Endpoint rubric quote is not from frozen task condition')
        if spec.get('payload_status', 'READY') != 'READY' and endpoint['executable']:
            raise ValueError('Missing/ambiguous payload cannot claim executable import')
        if not endpoint['executable']:
            if endpoint['last_action_id'] or endpoint['at_ms']:
                raise ValueError('Unreachable task cannot claim synthetic endpoint')
            continue
        if not endpoint['visible_conditions']:
            raise ValueError('Executable task needs visible endpoint conditions')
        action = by_id.get(endpoint['last_action_id'])
        if (not action or action['action'] == 'wait' or ident not in action['criterion_ids']
                or endpoint['stable_after_ms'] < 150
                or action['planned_end_t_ms'] + endpoint['stable_after_ms'] > endpoint['at_ms']):
            raise ValueError('Endpoint must follow its actual criterion-bound last input and settling delay')
        later = [a for a in actions if ident in a['criterion_ids'] and a['action'] != 'wait'
                 and a['planned_end_t_ms'] > action['planned_end_t_ms']]
        if later:
            raise ValueError('Declared endpoint action is not the last task input')
        contracts[ident] = {**endpoint, 'reachability': 'EXECUTABLE', 'probe_ids': [action['probe_id']]}
        point(endpoint['at_ms'], 'endpoint/' + ident, ident)
        if spec['needs_window']:
            start, end = endpoint['window_start_ms'], endpoint['window_end_ms']
            if not (action['planned_t_ms'] <= start < end <= endpoint['at_ms'] and end - start >= 600
                    and end - start <= 4000):
                raise ValueError('Short continuous window must follow real task trigger, span 600..4000ms')
            wid = 'window/' + ident
            windows.append({'id': wid, 'task_id': ident, 'start_ms': start, 'end_ms': end})
            for at in range(start, end + 1, 200):
                point(at, wid, ident)
            point(end, wid, ident)
    if points and actions[-1]['planned_end_t_ms'] < max(points) + 200:
        raise ValueError('Plan needs explicit final wait through last observation plus 200ms')
    # Extremely close distinct slots cannot physically capture on native clocks reliably.
    times = sorted(points)
    if any(b-a < 100 for a, b in zip(times, times[1:])):
        raise ValueError('Sampling points must share a slot or be at least 100ms apart')
    schedule = {'version': CAPTURE_VERSION, 'warmup_ms': 1000, 'tolerance_ms': 350,
                'points': [points[t] for t in times], 'plan': {'endpoints': contracts, 'windows': windows}}
    if not times:
        raise ValueError('No executable tasks; no runtime recording to perform')
    dump(schedule_path, schedule)
    from engine_adapters.unity3d.playtest.endpoint_settle import guards
    guards(schedule_path, actions)
    return actions, schedule
