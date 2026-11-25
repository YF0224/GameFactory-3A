"""Keep real actions usable while withdrawing incomplete endpoint proof claims."""
import copy
from pathlib import Path


def normalize(plan, protocol, root):
    from . import batch, core12, endpoint_sparse
    from .runtime import native_actions
    root = Path(root)
    policy = root/'route_metadata_repair.json'
    if not policy.is_file():
        return copy.deepcopy(plan), []
    authorization = batch.read(policy)
    if authorization.get('version') != 'whitebox-route-metadata-repair.v1' or not authorization.get('authorization'):
        raise ValueError('Incomplete plan requires explicit metadata authorization')
    result = copy.deepcopy(plan)
    targets = core12.targets(protocol)
    coverage = result.get('coverage', {})
    if not isinstance(coverage, (dict,list)):
        raise ValueError('Coverage must be an object or list')
    aliases = {r['endpoint_id']:r['id'] for r in targets}
    compact = isinstance(coverage,dict)
    windows = {aliases.get(k,k):v for k,v in coverage.items()} if compact else {v['atom_id']:v for v in coverage}
    capture = result.setdefault('capture_plan', {})
    endpoints = capture.setdefault('endpoints', {})
    shared_path = root/'input/endpoint_conditions.json'
    if not shared_path.is_file():
        shared_path = endpoint_sparse.shared_conditions_path(root.parent.parent,protocol)
    shared = batch.read(shared_path).get('endpoints', {}) if shared_path.is_file() else {}
    withdrawn, changes = set(), []
    required = {'at_ms','condition','probe_ids','limitation','reachability','legal_route',
                'last_action_id','stable_after_ms','stable_condition','source_evidence','rubric'}
    rubric_keys = {'requirement','visible_conditions','state_event_conditions','rubric_basis'}
    for row in targets:
        ident = row['id']
        endpoint, window = endpoints.get(ident), windows.get(ident)
        incomplete = (window is None or endpoint is None or not required <= set(endpoint)
            or not isinstance(endpoint.get('rubric'),dict) or not rubric_keys <= set(endpoint['rubric'])
            or not endpoint['rubric'].get('visible_conditions') or not endpoint['rubric'].get('rubric_basis')
            or not endpoint.get('source_evidence'))
        if not incomplete:
            continue
        # A supplied source SHA or path is never ignored merely because other
        # metadata is absent. The normal validator must still check it.
        references = copy.deepcopy((endpoint or {}).get('source_evidence', []))
        if not isinstance(references,list):
            raise ValueError('Invalid source reference list')
        reason = 'HARNESS_PLAN_LIMITATION: incomplete planner endpoint metadata; retained physical route is observable, but no endpoint completion is claimed.'
        defaults = {'requirement':row['requirement'], 'visible_conditions':[row['requirement']],
            'state_event_conditions':[], 'rubric_basis':[row['requirement']]}
        supplied_rubric = (endpoint or {}).get('rubric')
        rubric = copy.deepcopy(shared.get(ident, {**defaults, **(supplied_rubric if isinstance(supplied_rubric, dict) else {})}))
        for key in ('visible_conditions', 'rubric_basis'):
            if not rubric.get(key):
                rubric[key] = defaults[key]
        endpoints[ident] = dict(at_ms=0,condition=row['requirement'],probe_ids=[],limitation=reason,
            reachability='UNREACHABLE',legal_route=reason,last_action_id='',stable_after_ms=0,
            stable_condition='UNAVAILABLE',source_evidence=references,rubric=rubric)
        window = dict(status='UNVERIFIED',start_ms=0,end_ms=0,expected_game_time_ms=0,probe_ids=[],stop_condition=reason)
        if compact:
            coverage[row['endpoint_id']] = window
        else:
            window['atom_id'] = ident
            coverage[:] = [v for v in coverage if v['atom_id']!=ident]+[window]
        withdrawn.add(ident)
        changes.append({'kind':'withdraw_incomplete_endpoint_claim','endpoint_id':ident,
            'original_endpoint':copy.deepcopy(endpoint),'original_coverage':copy.deepcopy(windows.get(ident)),
            'requirement_unchanged':True,'physical_steps_unchanged':True})
    result['coverage'] = coverage
    for probe in result.get('probes',[]):
        probe['criterion_ids'] = [k for k in probe.get('criterion_ids',[]) if aliases.get(k,k) not in withdrawn]
    # Existing valid metadata is retained. Missing capture windows become short
    # observation opportunities at actual physical route boundaries, never
    # mechanism evidence or a claim that a visual criterion passed.
    if 'version' not in capture:
        capture['version'] = endpoint_sparse.capture_policy(protocol)['version']
    gameness = capture.setdefault('gameness', {})
    generated = []
    if not capture.get('windows') and result.get('probes'):
        spans = {}
        for action in native_actions(result):
            if action['probe_id']=='system':
                continue
            spans.setdefault(action['probe_id'],[action['planned_t_ms'],action['planned_end_t_ms']])[1] = action['planned_end_t_ms']
        for index, (probe_id, span) in enumerate(dict(list(spans.items())[:1]+list(spans.items())[-1:]).items()):
            start, end = span
            if end-start >= 200:
                generated.append(dict(id=f'partial_observation_{index+1}',start_ms=max(start,end-1000),end_ms=end,
                    probe_ids=[probe_id],reason='Observe the retained route; this is an opportunity for visual review, not endpoint proof.'))
        capture['windows'] = generated
        if generated:
            changes.append({'kind':'schedule_retained_route_observations','windows':copy.deepcopy(generated),
                'physical_steps_unchanged':True,'endpoint_proof_claimed':False})
    for row in endpoint_sparse.gameness_mapping(protocol):
        ident = row['criterion_id']
        if ident not in gameness or generated:
            observed_windows = generated or capture.get('windows', [])
            gameness[ident] = dict(window_ids=[v['id'] for v in observed_windows],
                reason='Review only the available retained-route observations; missing evidence remains unverified.')
            changes.append({'kind':'map_retained_observation_windows','criterion_id':ident,
                'window_ids':list(gameness[ident]['window_ids']), 'criterion_pass_claimed':False})
    if changes:
        result['summary'] = '[PARTIAL_OBSERVATION] '+result.get('summary','')
    return result, changes
