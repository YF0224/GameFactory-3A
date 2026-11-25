"""Read-only native coverage/timeline context; no acceptance or plan changes."""
import copy
from . import codex, native_plan_diagnostics
VERSION = 'whitebox-native-timeline-diagnostics.v1'


def collect(plan):
    plan = codex.decode_plan_coverage(copy.deepcopy(plan))
    cursor = 1800
    probes = []
    for probe in plan['probes']:
        start = cursor
        for step in probe['steps']:
            if step['kind'] in {'wait_until', 'move_until'}:
                cursor += step['timeout_ms']
            elif plan['engine'] != 'godot' and step['kind'] == 'input':
                cursor += max(100, step['duration_ms'])
            else:
                cursor += step['duration_ms']
        probes.append({'probe_id':probe['id'], 'start_ms':start, 'end_ms':cursor})
    bound = min(cursor, plan['max_duration_ms'])
    return {'path':'/coverage',
        'reason':'Exact existing core12 timeline bounds; changing these diagnostics does not change validation. Review every directly affected coverage and endpoint leaf against the preserved real actions.',
        'planned_action_timeline_end_ms':cursor, 'max_duration_ms':plan['max_duration_ms'],
        'coverage_end_upper_bound_ms':bound, 'probe_intervals':probes,
        'coverage_bounds':[{'index':i,'atom_id':row['atom_id'],'status':row['status'],
                           'start_ms':row['start_ms'],'end_ms':row['end_ms'],
                           'outside_planned_timeline': row['status']=='PLANNED' and not 1800 <= row['start_ms'] < row['end_ms'] <= bound}
                          for i,row in enumerate(plan['coverage'])],
        'detected_issue': any(row['status']=='PLANNED' and not 1800 <= row['start_ms'] < row['end_ms'] <= bound for row in plan['coverage'])}


def enrich(error, protocol, plan):
    native_plan_diagnostics.enrich(error, protocol, plan)
    try:
        detail = collect(plan)
    except (ValueError, KeyError, TypeError, IndexError) as diagnostic_error:
        detail = {'path':'/coverage','reason':'Timeline context unavailable: '+str(diagnostic_error)}
    error.diagnostics.append(detail)
    return error
