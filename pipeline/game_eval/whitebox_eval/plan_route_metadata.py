"""Recompute route metadata from existing physical steps, never create gameplay."""
import copy
from pathlib import Path

POLICY = 'route_metadata_repair.json'


def normalize(plan, protocol, root):
    from . import batch, core12, multiclient
    from .protocol import checked_path, sha
    if not (Path(root)/POLICY).is_file():
        return copy.deepcopy(plan), []
    policy = batch.read(Path(root)/POLICY)
    if policy.get('version') != 'whitebox-route-metadata-repair.v1' or not policy.get('authorization'):
        raise ValueError('Missing route repair authorization')
    result = copy.deepcopy(plan)
    original = copy.deepcopy(plan)
    targets = core12.targets(protocol)
    aliases = {row['endpoint_id']:row['id'] for row in targets}
    requirements = {row['id']: row['requirement'] for row in targets}
    frozen = batch.read(Path(root)/'input_manifest.json')['snapshot_hashes']
    coverage = result['coverage']
    windows = {aliases[key]:value for key,value in coverage.items()} if isinstance(coverage,dict) else {
        row['atom_id']:row for row in coverage}
    # Use the same durations and action identities as the native recorder,
    # including wait_until timeouts, minimum input holds and mouse actions.
    from .runtime import native_actions
    actions = native_actions(result)
    spans, inputs = {}, {}
    cursor = actions[-1]['planned_end_t_ms']
    for action in actions:
        if action['probe_id'] == 'system':
            continue
        probe_id = action['probe_id']
        if probe_id not in spans:
            spans[probe_id] = (action['planned_t_ms'], action['planned_end_t_ms'])
        else:
            spans[probe_id] = (spans[probe_id][0], action['planned_end_t_ms'])
        if action['action'] != 'wait':
            for ident in action['criterion_ids']:
                inputs.setdefault(aliases.get(ident, ident), []).append({
                    'action_id':action['action_id'], 'end_ms':action['planned_end_t_ms'], 'probe_id':probe_id,
                    'client_role':action.get('client_role')})
    withdrawn = set()
    context = (Path(root)/'input/requirement.txt').read_text()+'\n'+(Path(root)/'input/frozen_rubric.json').read_text()
    for ident, window in windows.items():
        endpoint = result['capture_plan']['endpoints'][ident]
        rubric = endpoint.get('rubric', {})
        # A truncated digest is recoverable only against the exact delivered path
        # and immutable manifest. A full-length wrong digest remains an error.
        for reference in endpoint.get('source_evidence', []):
            digest = reference.get('sha256', '')
            expected = frozen.get(reference.get('path'))
            if (isinstance(digest, str) and 32 <= len(digest) < 64 and expected
                    and all(char in '0123456789abcdef' for char in digest)):
                stream = iter(expected)
                if (all(any(char == candidate for candidate in stream) for char in digest)
                        and sha(checked_path(Path(root)/'input/project', reference['path'])) == expected):
                    reference['sha256'] = expected
        # A source-code citation is not a rubric quote. Bind the already exact
        # requirement without changing either visible or state/event conditions.
        if (rubric.get('requirement') == requirements[ident]
                and rubric.get('rubric_basis')
                and any(text not in context and text != requirements[ident] for text in rubric['rubric_basis'])):
            rubric['rubric_basis'] = [requirements[ident]]
        if window['status']=='UNVERIFIED':
            if not endpoint['legal_route'].strip() and endpoint.get('limitation', '').strip():
                endpoint['legal_route'] = 'UNREACHABLE: '+endpoint['limitation']
            continue
        references = [probe['id'] for probe in result['probes']
                      if any(aliases.get(key,key)==ident for key in probe['criterion_ids'])]
        # Keep the final contiguous related probe group. Earlier related inputs
        # remain physical steps, but cannot claim a continuous observation across
        # intervening unrelated probes.
        suffix = references[-1:]
        for probe_id in reversed(references[:-1]):
            if spans[probe_id][1] != spans[suffix[0]][0]:
                break
            suffix.insert(0, probe_id)
        if suffix != references:
            for probe in result['probes']:
                if probe['id'] in references and probe['id'] not in suffix:
                    probe['criterion_ids'] = [key for key in probe['criterion_ids'] if aliases.get(key,key) != ident]
            references = suffix
        actual = [action for action in inputs.get(ident,[])
                  if action['probe_id'] in references
                  and (not multiclient.enabled(protocol)
                       or action['client_role'] in (endpoint.get('client_role'), 'BOTH'))]
        settle = max(150, endpoint['stable_after_ms'])
        low = actual[-1]['end_ms']+settle if actual else cursor+1
        high = spans[references[-1]][1]-150 if references else -1
        if not actual or low > high:
            reason = 'HARNESS_PLAN_LIMITATION: retained route has no actual input followed by the declared stable observation; no endpoint proof claimed.'
            window.update(status='UNVERIFIED',start_ms=0,end_ms=0,expected_game_time_ms=0,probe_ids=[],stop_condition=reason)
            endpoint.update(reachability='UNREACHABLE',at_ms=0,probe_ids=[],last_action_id='',
                            stable_after_ms=0,stable_condition='UNAVAILABLE',limitation=reason,legal_route=reason)
            withdrawn.add(ident)
            continue
        sample = min(high,max(low,endpoint['at_ms']))
        window.update(start_ms=spans[references[0]][0],end_ms=sample+150,probe_ids=references)
        endpoint.update(at_ms=sample,probe_ids=references,last_action_id=actual[-1]['action_id'],stable_after_ms=settle)
    for probe in result['probes']:
        probe['criterion_ids'] = [key for key in probe['criterion_ids'] if aliases.get(key,key) not in withdrawn]
    capture = result['capture_plan']
    kept = []
    for window in capture['windows']:
        refs = window['probe_ids']
        if not refs or any(key not in spans for key in refs):
            continue
        start = max(window['start_ms'],spans[refs[0]][0])
        end = min(window['end_ms'],spans[refs[-1]][1])
        if end-start < 200:
            continue
        # Keep a short subset of the originally declared observation interval.
        window.update(start_ms=max(start,end-1000),end_ms=end)
        kept.append(window)
    known = {window['id'] for window in kept}
    capture['windows'] = kept
    for mapping in capture['gameness'].values():
        if set(mapping['window_ids'])-known:
            mapping['window_ids'] = [key for key in mapping['window_ids'] if key in known]
            mapping['reason'] += '; absent/invalid observation windows omitted; no proof claimed for them.'
    used = {ident for mapping in capture['gameness'].values() for ident in mapping['window_ids']}
    capture['windows'] = [window for window in kept if window['id'] in used]
    changes = []
    for field in ('coverage','capture_plan','probes'):
        if original[field] != result[field]:
            changes.append({'kind':'recompute_route_metadata','field':field,
                            'before':original[field],'after':copy.deepcopy(result[field]),
                            'physical_steps_unchanged':True})
    return result, changes
