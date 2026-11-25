"""Explicit, source-bound observation schedule edits before native execution.

Only declared observation clocks and extensions of existing passive waits can
change. Gameplay inputs, requirements, sampling limits and scoring stay intact.
The ordinary schema/native/capture validators still decide admissibility.
"""
import copy
from .mechanic_v3_runner import read
from .protocol import sha


def apply(operation, repair_path, response_path):
    receipt=read(repair_path)
    if receipt.get('classification')!='NON_SCORING_PRERECORD_OBSERVATION_SCHEDULE':
        raise ValueError('Explicit observation schedule diagnosis required')
    if receipt['response_sha256']!=sha(response_path) or not receipt.get('root_cause','').strip():
        raise ValueError('Observation repair original response binding differs')
    result=copy.deepcopy(operation);seen=set()
    for edit in receipt['edits']:
        path=edit['path'];signature=tuple(path)
        if signature in seen:raise ValueError('Duplicate observation schedule edit')
        seen.add(signature)
        allowed=(len(path)==3 and path[0]=='coverage' and type(path[1]) is int and path[2] in {'start_ms','end_ms'})
        allowed=allowed or (len(path)==4 and path[:2]==['capture_plan','windows'] and type(path[2]) is int and path[3] in {'start_ms','end_ms'})
        if len(path)==5 and path[0]=='probes' and type(path[1]) is int and path[2]=='steps' and type(path[3]) is int and path[4]=='duration_ms':
            step=result['probes'][path[1]]['steps'][path[3]]
            allowed=(step['kind']=='wait' and 'button' not in step
                     and type(edit['after']) is int and edit['after']>edit['before'])
        if not allowed:raise ValueError('Observation repair cannot alter gameplay or capture/scoring conditions')
        target=result
        for key in path[:-1]:target=target[key]
        if target[path[-1]]!=edit['before']:raise ValueError('Observation repair original value differs')
        if type(edit['after']) is not int or edit['after']<0:raise ValueError('Invalid observation clock')
        target[path[-1]]=edit['after']
    if not seen:raise ValueError('Empty observation repair')
    return result,receipt['edits']
