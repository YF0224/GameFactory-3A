"""Explicitly authorized omission of unsupported Unity actions, without fake execution."""
import copy
from pathlib import Path

from .protocol import dump

POLICY = 'unsupported_input_policy.json'
VERSION = 'whitebox-omit-unsupported-inputs.v1'


def authorize(root, authorization):
    from . import batch
    root = Path(root)
    if (root/'background_record').exists() or (root/'sol_plan.json').exists():
        raise ValueError('Existing plan/capture protected')
    if not authorization.strip():
        raise ValueError('Explicit omission authorization required')
    value = {'version':VERSION, 'authorization':authorization,
             'behavior':'replace unsupported physical actions with equal-duration waits; withdraw affected evidence claims',
             'classification':'HARNESS_INPUT_LIMITATION; never product failure or executed input'}
    if (root/POLICY).exists() and batch.read(root/POLICY) != value:
        raise ValueError('Unsupported-input authorization already frozen')
    dump(root/POLICY, value)


def normalize(plan, protocol, root):
    from . import batch, runtime, core12
    root = Path(root)
    if not (root/POLICY).is_file():
        return copy.deepcopy(plan), []
    policy = batch.read(root/POLICY)
    if policy.get('version') != VERSION or not policy.get('authorization', '').strip():
        raise ValueError('Invalid unsupported-input policy')
    result = copy.deepcopy(plan)
    changes, affected, intervals = [], set(), []
    allowed = {'input','wait'} | runtime.UNITY_MOUSE_KINDS
    cursor = 1800
    for probe in result['probes']:
        for step in probe['steps']:
            kind = step['kind']
            key = step.get('key','')
            supported = kind in allowed and (kind != 'input' or (
                isinstance(key,str) and 1 <= len(key.split('+')) <= 3
                and all(part in runtime.NATIVE_KEYS for part in key.split('+'))))
            duration = step['duration_ms']
            if not supported:
                if type(duration) != int or not 0 <= duration <= 6000:
                    raise ValueError('Cannot preserve unsupported action timing')
                duration = max(100,duration) if kind == 'input' else duration
                before = copy.deepcopy(step)
                step.clear()
                step.update(id=before['id'], kind='wait', key='', duration_ms=duration,
                            watch='', op='eq', value=0, target_watch='', timeout_ms=0,
                            purpose='HARNESS_INPUT_LIMITATION: omitted unsupported action '+kind+' '+str(key),
                            expected_observation='No input sent; this wait proves no gameplay outcome.')
                affected.update(probe['criterion_ids'])
                intervals.append((cursor,cursor+duration))
                changes.append({'kind':'omit_unsupported_input','probe_id':probe['id'],
                    'step_id':step['id'],'original':before,'replacement':copy.deepcopy(step),
                    'sent':False,'classification':'HARNESS_INPUT_LIMITATION'})
            cursor += max(100,duration) if kind == 'input' else duration
    if not changes:
        return result, []
    targets = core12.targets(protocol)
    aliases = {row['endpoint_id']:row['id'] for row in targets}
    affected = {aliases.get(ident,ident) for ident in affected}
    coverage = result['coverage']
    if isinstance(coverage,dict):
        windows = {aliases[key]:value for key,value in coverage.items()}
    else:
        windows = {row['atom_id']:row for row in coverage}
    reason = 'HARNESS_INPUT_LIMITATION: unsupported inputs omitted by explicit user authorization; no execution or final-frame claim for this route.'
    for ident in sorted(affected):
        window = windows[ident]
        window.update(status='UNVERIFIED',start_ms=0,end_ms=0,probe_ids=[],expected_game_time_ms=0,stop_condition=reason)
        endpoint = result['capture_plan']['endpoints'][ident]
        endpoint.update(reachability='UNREACHABLE',at_ms=0,probe_ids=[],last_action_id='',
                        stable_after_ms=0,stable_condition='UNAVAILABLE',limitation=reason,
                        legal_route=reason)
    for probe in result['probes']:
        probe['criterion_ids'] = [ident for ident in probe['criterion_ids'] if aliases.get(ident,ident) not in affected]
    capture = result['capture_plan']
    removed = set()
    for window in capture['windows']:
        if any(window['start_ms'] < end and start < window['end_ms'] for start,end in intervals):
            removed.add(window['id'])
    capture['windows'] = [window for window in capture['windows'] if window['id'] not in removed]
    for mapping in capture['gameness'].values():
        if removed.intersection(mapping['window_ids']):
            mapping['window_ids'] = [ident for ident in mapping['window_ids'] if ident not in removed]
            mapping['reason'] += '; '+reason
    changes.append({'kind':'withdraw_unsupported_route_evidence','endpoint_ids':sorted(affected),
                    'removed_window_ids':sorted(removed),'classification':'HARNESS_INPUT_LIMITATION'})
    return result, changes
