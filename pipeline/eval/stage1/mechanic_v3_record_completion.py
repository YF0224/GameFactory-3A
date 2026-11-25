"""Explicit v3 native recording ends after actions and all declared observations.

The frozen budget is a ceiling, not idle gameplay. No authored action, necessary
wait, coverage/window/endpoint, original plan, or source protocol is shortened.
Legacy/v2 calls without this opt-in policy retain their existing behavior.
"""
from pathlib import Path
import copy
from .protocol import sha
from .mechanic_v3_runner import read, exclusive_json
VERSION='whitebox-native-plan-completion.v1'
FILE='native_record_completion_policy.json'


def duration(root,protocol,plan):
    from .runtime import native_actions
    from . import endpoint_sparse
    actions=native_actions(plan)
    action_end=max((a['planned_end_t_ms'] for a in actions),default=0)
    if not endpoint_sparse.enabled(protocol):
        raise ValueError('Completion policy requires validated explicit observation schedule')
    engine=plan.get('engine') or read(Path(root)/'input_manifest.json')['entry']['actual_engine']
    schedule=endpoint_sparse.validate_plan(protocol,plan,engine,root=Path(root))
    capture_end=max((p['at_ms'] for p in schedule['points']),default=0)
    coverage_end=max((w['end_ms'] for w in plan.get('coverage',[]) if w.get('status')=='PLANNED'),default=0)
    # Native sparse sampling allows 350ms scheduling tolerance. This preserves
    # the final declared sample, rather than cutting at its nominal timestamp.
    bound=max(action_end,coverage_end,capture_end+schedule['tolerance_ms'])
    return dict(action_end_ms=action_end,last_predeclared_capture_ms=capture_end,
        coverage_end_ms=coverage_end,native_sampling_tolerance_ms=schedule['tolerance_ms'],
        recording_ms=max(1000,bound),all_declared_points=len(schedule['points']))


def freeze(root,plan):
    root=Path(root);path=root/FILE;proto=read(root/'input/pilot_rubric.json')
    value=dict(version=VERSION,authorization='User 2026-11-03: stop once action plan, required waits and all predeclared capture windows complete; cleanup then next case',
        plan_sha256=sha(root/'sol_plan.json'),protocol_sha256=sha(root/'input/pilot_rubric.json'),
        original_plan_unchanged=True,original_budget_is_ceiling=True,**duration(root,proto,plan))
    if path.exists():
        if read(path)!=value:raise ValueError('Retained recording completion policy changed')
    else:
        if (root/'native_capture_admission.json').exists():raise ValueError('Cannot change completion policy after native admission')
        exclusive_json(path,value)
    return value


def effective_budget(root,protocol,plan,budget):
    root=Path(root);value=read(root/FILE)
    if value['version']!=VERSION or value['plan_sha256']!=sha(root/'sol_plan.json') or value['protocol_sha256']!=sha(root/'input/pilot_rubric.json'):
        raise ValueError('Recording completion source changed')
    actual=duration(root,protocol,plan)
    if any(value[k]!=v for k,v in actual.items()):raise ValueError('Recording completion schedule changed')
    ceiling=budget.get('recording_ms',budget.get('gameplay_ms',plan['max_duration_ms']))
    if actual['recording_ms']>ceiling:raise ValueError('Declared observations exceed original recording ceiling')
    result=copy.deepcopy(budget);result['recording_ceiling_ms']=ceiling
    result['recording_ms']=actual['recording_ms'];result['completion_policy']=value
    return result
