"""Read-only timing/link diagnostics; acceptance remains in the original validators."""
import copy
import json
from . import codex, runtime, endpoint_sparse, multiclient

VERSION = 'whitebox-native-comprehensive-plan-diagnostics.v1'


def collect(protocol, plan):
    plan = codex.decode_plan_coverage(copy.deepcopy(plan))
    actions = runtime.native_actions(plan)
    coverage = {row['atom_id']: row for row in plan['coverage']}
    capture = plan['capture_plan']
    rows = []
    for ident, endpoint in capture['endpoints'].items():
        window = coverage[ident]
        stamp = endpoint['at_ms']
        relevant = [a for a in actions if a['probe_id'] in endpoint['probe_ids']
                    and ident in a['criterion_ids'] and a['action'] != 'wait'
                    and (not multiclient.enabled(protocol)
                         or a.get('client_role') in {endpoint['client_role'], 'BOTH'})]
        earlier = [a for a in relevant if window['start_ms'] <= a['planned_t_ms'] < stamp]
        last = earlier[-1] if earlier else None
        path = '/capture_plan/endpoints/' + ident.replace('~','~0').replace('/','~1')
        issues = []
        if window['status'] == 'PLANNED':
            if (endpoint['probe_ids'] != window['probe_ids']
                    or not window['start_ms'] <= stamp < window['end_ms']
                    or not window['end_ms'] - 500 <= stamp <= window['end_ms'] - 150):
                issues.append('final observation/probe assignments differ from current strict coverage rule')
            if endpoint_sparse.closed_endpoints(protocol) and (
                    last is None or last['action_id'] != endpoint['last_action_id']
                    or endpoint['stable_after_ms'] < 150 or not endpoint['stable_condition'].strip()
                    or last['planned_end_t_ms'] + endpoint['stable_after_ms'] > stamp
                    or any(stamp <= a['planned_t_ms'] < window['end_ms'] for a in relevant)):
                issues.append('actual last input, settling interval or later input fails current strict rule')
        if not endpoint.get('legal_route','').strip():issues.append('legal_route is blank')
        rows.append({'path':path, 'reason':'; '.join(issues) or 'timing/link context for complete review; no acceptance asserted',
            'endpoint_id':ident, 'coverage_status':window['status'],
            'coverage_start_ms':window['start_ms'], 'coverage_end_ms':window['end_ms'],
            'coverage_probe_ids':window['probe_ids'], 'endpoint_probe_ids':endpoint['probe_ids'],
            'at_ms':stamp, 'final_observation_min_ms':max(window['start_ms'],window['end_ms']-500),
            'final_observation_max_ms':window['end_ms']-150,
            'declared_last_action_id':endpoint.get('last_action_id'),
            'actual_last_action_id':last['action_id'] if last else None,
            'actual_last_input_end_ms':last['planned_end_t_ms'] if last else None,
            'stable_after_ms':endpoint.get('stable_after_ms'),
            'later_input_ids':[a['action_id'] for a in relevant if stamp <= a['planned_t_ms'] < window['end_ms']],
            'detected_issue':bool(issues)})
    known = {window['id'] for window in capture['windows']}
    used = {ident for mapping in capture['gameness'].values() for ident in mapping['window_ids']}
    rows.append({'path':'/capture_plan/gameness',
        'reason':'Every declared visual window must retain a source-grounded frozen Gameness purpose; no window may be silently dropped.',
        'unmapped_window_ids':sorted(known-used), 'unknown_window_ids':sorted(used-known),
        'windows':copy.deepcopy(capture['windows']), 'mapping':copy.deepcopy(capture['gameness']),
        'detected_issue':known != used})
    return rows


def enrich(error, protocol, plan):
    """Attach additional factual context without changing an error or deciding validity."""
    original = copy.deepcopy(getattr(error, 'diagnostics', []))
    try:
        rows = collect(protocol, plan)
    except (ValueError, KeyError, TypeError, IndexError) as diagnostic_error:
        rows = [{'path':'', 'reason':'comprehensive context unavailable: '+str(diagnostic_error)}]
    error.diagnostics = original + [{'path':'','reason':str(error)}] + rows
    return error
