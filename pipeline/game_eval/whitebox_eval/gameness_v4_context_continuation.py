"""One diagnosed context-configuration recovery for the original Sol016 source.

The default window demonstrably compacted the original unabridged source.
A later complete same-model case proves an explicitly configured larger native
window. All original attempts remain; source/image/output limits stay frozen.
"""
from pathlib import Path
from . import mechanic_v3_runner as runner
from .protocol import sha
VERSION='gameness-v4-diagnosed-context-configuration-continuation.v1'
AUTH='engineering/gameness_sequential_context_continuation.json'
IDENTITY='Sol__G016_theater_sorting'


def path(root):
    child=Path(root)/AUTH
    from . import gameness_v4_sequential_recovery as seq
    return child if child.is_file() else Path(root)/seq.AUTH


def bound(item):
    p=Path(item['path']).resolve()
    if sha(p)!=item['sha256']:raise ValueError('Exact context recovery evidence changed: '+str(p))
    return p


def diagnose(root,repair, *, existing_child=None):
    from . import gameness_v4_sequential_recovery as seq,gameness_v4_persistent_text as base
    from . import gameness_v4_persistent_capacity as capacity
    value=runner.read(repair);parent=bound(value['parent_authorization'])
    if (value.get('version')!=VERSION or root.name!=IDENTITY or value.get('identity')!=root.name
        or parent!=(root/seq.AUTH).resolve() or value.get('maximum_new_source_conversations')!=1
        or value.get('model_context_window')!=1050000 or value.get('frozen_limits_unchanged') is not True):
        raise ValueError('Exact single diagnosed context continuation required')
    old=runner.read(parent)
    if old.get('model_context_window') is not None:raise ValueError('Only diagnosed default window mismatch may continue')
    call=root/'model_calls'/old['task'];failed=bound(value['parent_failure'])
    if (not failed.is_relative_to((root/'failures').resolve())
        or runner.read(failed).get('error')!="ValueError('Retained conversation contains compaction')"
        or (call/'persistent_turns/final').exists() or (call/'accepted_response.json').exists()
):
        raise ValueError('Actual retained pre-final default compaction without accepted judgment required')
    judgments=list((root/'judgments').glob('gameness_v4_*.json'))
    if judgments:
        # Readonly verification may encounter the exact authorized child result.
        # A parent acceptance or any unrelated judgment remains disqualifying.
        child_path=root/AUTH
        if (existing_child is None or not child_path.is_file()
                or runner.read(child_path)!=existing_child
                or existing_child.get('context_repair')!=str(Path(repair).resolve())
                or existing_child.get('task')!=old['task']+'_context1'
                or {p.name for p in judgments}!={existing_child['task']+'.json'}):
            raise ValueError('Only exact authorized context child judgment may be reused')
        child_call=root/'model_calls'/existing_child['task']
        accepted=runner.read(child_call/'accepted_response.json')
        judgment=runner.read(judgments[0])
        response=child_call/'response.json'
        if (accepted!=dict(path='response.json',sha256=sha(response))
                or judgment.get('task')!=existing_child['task']
                or judgment.get('response_path')!=str(response)
                or judgment.get('response_sha256')!=sha(response)
                or judgment.get('protocol')!='whitebox-gameness10-50-100.v4'):
            raise ValueError('Exact accepted child response binding required')
    sid=base.event_values(call/'persistent_turns/intake_01/events.jsonl')
    transcript=bound(value['failed_retained_session'])
    if transcript.read_bytes()!=base.session_path(sid).read_bytes():raise ValueError('Exact failed session snapshot required')
    try:base.verify_session(transcript,sid,[], 'gpt-6.1-sol')
    except ValueError as exc:
        if 'compaction' not in str(exc):raise
    else:raise ValueError('Actual default compaction must remain rejected')
    prior=runner.read(bound(value['prior_native_capacity']))
    if prior['observed_context_window']!=258400:raise ValueError('Exact diagnosed default capacity required')
    proof=bound(value['same_model_native_capacity']);native=runner.read(proof)
    if native['observed_context_window']<800000:raise ValueError('Actual larger native window proof required')
    inv=runner.read(bound(value['same_model_explicit_invocation']))
    if (inv.get('model_requested')!='gpt-6.1-sol' or inv.get('exit_code')!=0
        or inv['command'].count('model_context_window=1050000')!=1):
        raise ValueError('Actual identical Sol model explicit context proof required')
    # Exact full source is retained; changing a model setting is not a new rubric.
    reg=bound(value['regression']);passed=runner.read(reg)
    if passed.get('exit_code')!=0 or passed.get('tests_passed',0)<1:raise ValueError('Passed corresponding context regression required')
    for phase in ('before','after'):
        bindings=value[phase+'_source_bindings'];archives=value[phase+'_producer_archives']
        if set(bindings)!=set(archives) or any(sha(Path(archives[n]))!=h for n,h in bindings.items()):
            raise ValueError('Complete exact '+phase+' production archive required')
    if sha(Path(old['original_body_path']))!=old['original_body_sha256']:
        raise ValueError('Original complete source changed')
    return value,old


def authorize(workspace,root,repair):
    from . import gameness_v3_runtime as runtime,gameness_v4_sequential_recovery as seq
    from . import gameness_v4_persistent_text as base,gameness_v4_final_literal as final_literal
    repair=Path(repair).resolve()
    child=root/AUTH
    if child.exists():
        auth=verify(root)
        if auth['context_repair']!=str(repair):raise ValueError('One immutable context repair only')
        return auth
    value,old=diagnose(root,repair)
    if value['after_source_bindings']!=runtime.production_bindings():raise ValueError('Complete current recovery production differs')
    if runtime.publication_path(workspace,root.name).exists():raise ValueError('Published source must be reused')
    auth=dict(old,task=old['task']+'_context1',model_context_window=1050000,
        context_repair=str(repair),context_parent=dict(path=str(root/seq.AUTH),sha256=sha(root/seq.AUTH)),
        producer_archives=value['after_producer_archives'])
    packet=base.packet(workspace,root,auth,persist=False)
    if packet[6]!=Path(old['original_body_path']).read_text():raise ValueError('Every original source byte required')
    final_literal.prepare(auth,packet[-2])
    paths=[repair,*[Path(p) for p in value['after_source_bindings']],*[Path(p) for p in value['after_producer_archives'].values()],
           *[p for p in (root/'model_calls'/old['task']).rglob('*') if p.is_file()],
           *[Path(p) for p in old['bindings']], root/seq.AUTH]
    # Original old code is verified through the original archive, never replaced.
    bindings=dict(old['bindings']);archives=dict(old['producer_archives'])
    for p in paths:
        if p.is_file():bindings[str(p.resolve())]=sha(p)
    archives.update(value['after_producer_archives']);auth['bindings']=bindings;auth['producer_archives']=archives
    runner.exclusive_json(child,auth);return verify(root)


def verify(root):
    from . import gameness_v4_sequential_recovery as seq
    auth=runner.read(root/AUTH);repair=Path(auth['context_repair']);value,old=diagnose(root,repair,existing_child=auth)
    if (auth.get('context_parent')!=dict(path=str(root/seq.AUTH),sha256=sha(root/seq.AUTH))
        or auth.get('task')!=old['task']+'_context1' or auth.get('model_context_window')!=1050000):
        raise ValueError('Immutable context child differs')
    for key in old:
        if key not in {'task','model_context_window','bindings','producer_archives'} and auth.get(key)!=old[key]:
            raise ValueError('Context recovery cannot change original evidence/limits: '+key)
    for n,h in auth['bindings'].items():
        p=Path(auth['producer_archives'].get(n,n))
        if sha(p)!=h:raise ValueError('Immutable context recovery binding changed: '+n)
    return auth
