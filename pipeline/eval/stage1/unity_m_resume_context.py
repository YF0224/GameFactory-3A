"""Verify a server-injected AGENTS update without dropping any submitted input.

The G018 successor reuses the already returned correction. It grants no new
correction, intake, native record or batch dispatch until the real column closes.
"""
from pathlib import Path
from . import batch, unity_m_admission as admission
from .protocol import sha

VERSION = 'unity-m-g018-resume-context-recovery.v1'
POINTER = 'engineering/unity_m_g018_resume_path_repair.json'
FAILURE = '1794152362043475000.json'
FILES = {'unity_m_resume_context.py', 'unity_m_delivery.py', 'unity_m_admission.py',
         'unity_m_direct_bug_recovery.py', 'unity_m_output_recovery.py'}
ERROR = 'Every exact original runtime prompt must be retained once in order'


def verify_inputs(folder, original, expected):
    """Bind one environment update to server provenance, world state and RPC.

    A text prefix never qualifies an input. Every original byte remains in the
    snapshot, and exactly one submitted correction must match its actual RPC.
    """
    from .unity_m_delivery import rows, text_inputs
    folder, original = Path(folder), Path(original)
    prior = (original/'retained_session.jsonl').read_bytes()
    current = (folder/'retained_session.jsonl').read_bytes()
    if not prior.endswith(b'\n') or not current.startswith(prior):
        raise ValueError('Complete original judge snapshot must remain an exact prefix')
    inv = batch.read(folder/'invocation.json'); old = batch.read(original/'invocation.json')
    if inv['thread'] != old['thread'] or inv['turn'] == old['turn']:
        raise ValueError('One resumed original thread and a distinct correction turn required')
    requests = rows(folder/'rpc_requests.jsonl'); events = rows(folder/'rpc_events.jsonl')
    resumes = [v for v in requests if v.get('method') == 'thread/resume']
    starts = [v for v in requests if v.get('method') == 'turn/start']
    if (len(resumes) != 1 or len(starts) != 1
            or any(v.get('method') not in {'initialize','initialized','thread/resume','turn/start'} for v in requests)):
        raise ValueError('Exactly one actual resume and correction submission required')
    resume, start = resumes[0], starts[0]
    if (resume['params'].get('threadId') != inv['thread']
            or start['params'].get('threadId') != inv['thread']
            or resume['params'].get('model') != 'gpt-6.1-sol'
            or start['params'].get('model') != 'gpt-6.1-sol'):
        raise ValueError('Resumed RPC thread/model changed')
    correction = (folder/'prompt.txt').read_text()
    if (start['params'].get('input') != [dict(type='text',text=correction)]
            or start['params'].get('outputSchema') != batch.read(folder/'schema.json')
            or not expected or expected[-1] != correction):
        raise ValueError('Exact actual correction RPC text and schema required')
    responses = [v.get('result',{}) for v in events if v.get('id') == resume['id']]
    started = [v.get('result',{}) for v in events if v.get('id') == start['id']]
    if (len(responses) != 1 or len(started) != 1
            or responses[0].get('thread',{}).get('id') != inv['thread']
            or started[0].get('turn',{}).get('id') != inv['turn']):
        raise ValueError('Actual RPC resume/start results required')
    sources = responses[0].get('instructionSources',[])
    if not sources or any(not isinstance(p,str) or not Path(p).is_absolute() or Path(p).name != 'AGENTS.md' for p in sources):
        raise ValueError('Actual server AGENTS instruction sources required')
    before = rows(original/'retained_session.jsonl')
    after = rows(folder/'retained_session.jsonl')
    if text_inputs(before) != expected[:-1]:
        raise ValueError('Every exact original runtime prompt must be retained once in order')
    suffix = after[len(before):]
    users = [(n,v) for n,v in enumerate(suffix) if v.get('type') == 'response_item' and v.get('payload',{}).get('role') == 'user']
    if len(users) != 2:
        raise ValueError('Exactly one environment update and submitted correction required')
    (at, update), (last, submitted) = users
    payload = update['payload']; metadata = payload.get('internal_chat_message_metadata_passthrough',{})
    content = payload.get('content',[])
    if (metadata.get('turn_id') != inv['turn']
            or metadata.get('content_item_kinds') != ['agents_md.instructions']
            or metadata.get('content_item_metadata') != [dict(provenance=dict(type='agents_md'))]
            or len(content) != 1 or content[0].get('type') != 'input_text'):
        raise ValueError('Server AGENTS provenance is required; text resemblance is insufficient')
    state = suffix[at+1] if at+1 < len(suffix) else {}
    instructions = state.get('payload',{}).get('state',{}).get('agents_md',{}).get('text')
    cwd = resume['params'].get('cwd')
    wrapper = (f'# AGENTS.md instructions for {cwd}\n\n<INSTRUCTIONS>\n'
               'These AGENTS.md instructions replace all previously provided AGENTS.md instructions.\n\n'
               f'{instructions}\n</INSTRUCTIONS>')
    if state.get('type') != 'world_state' or not isinstance(instructions,str) or content[0].get('text') != wrapper:
        raise ValueError('Environment update must exactly match adjacent server world state')
    sub = submitted['payload']; meta = sub.get('internal_chat_message_metadata_passthrough',{})
    contexts = [v['payload'] for v in suffix[at+2:last] if v.get('type') == 'turn_context']
    if (sub.get('content') != [dict(type='input_text',text=correction)]
            or meta.get('turn_id') != inv['turn']
            or meta.get('content_item_kinds') != ['user.text']
            or meta.get('content_item_metadata') != [dict(provenance=dict(type='user'))]
            or len(contexts) != 1 or contexts[0].get('turn_id') != inv['turn']
            or contexts[0].get('cwd') != cwd or contexts[0].get('model') != 'gpt-6.1-sol'):
        raise ValueError('Exact actual submitted correction and turn context required')
    actual = [v['params']['item'] for v in events if v.get('method') == 'item/completed'
              and v.get('params',{}).get('turnId') == inv['turn']
              and v.get('params',{}).get('item',{}).get('type') == 'userMessage']
    if len(actual) != 1 or actual[0].get('content') != [dict(type='text',text=correction,text_elements=[])]:
        raise ValueError('RPC userMessage must confirm the exact submitted correction')
    return dict(version=VERSION,environment_ordinal=update.get('ordinal'),
                environment_text_sha256=__import__('hashlib').sha256(content[0]['text'].encode()).hexdigest(),
                instruction_sources=sources,original_session_sha256=sha(original/'retained_session.jsonl'),
                actual_session_sha256=sha(folder/'retained_session.jsonl'),
                rpc_requests_sha256=sha(folder/'rpc_requests.jsonl'),rpc_events_sha256=sha(folder/'rpc_events.jsonl'),
                all_original_submitted_inputs_exact=True,environment_retained=True)


def qualify(workspace, identity, operation, column, descriptor):
    from . import unity_m_direct_bug_recovery as parent
    workspace=Path(workspace).resolve(); path=Path(descriptor).resolve(); value=batch.read(path)
    if (identity != parent.IDENTITY or operation != 'judge' or column != 'Mechanic'
            or value.get('version') != VERSION or value.get('identity') != identity
            or value.get('new_native_calls') != 0 or value.get('maximum_new_correction_calls') != 0
            or value.get('batch_admitted') is not False or value.get('scoring_changed') is not False):
        raise ValueError('Only the exact recorded G018 saved correction may resume')
    prior_path=parent.reference(value['parent_repair']); prior=batch.read(prior_path)
    before=prior['after_production']; current=admission.production()
    parent.qualify(workspace,identity,operation,column,prior_path,expected_production=before)
    changed={p for p in before.keys()|current.keys() if before.get(p)!=current.get(p)}
    expected={str(Path(__file__).resolve().parent/n) for n in FILES}
    if (value.get('before_production') != before or value.get('after_production') != current
            or changed != expected or set(value.get('changed_files',{})) != changed):
        raise ValueError('Exact complete resume-context production delta required')
    for name, archive in value['changed_files'].items():
        if name in before:
            if not archive or sha(Path(archive)) != before[name]:
                raise ValueError('Exact archived parent producer required')
        elif archive is not None or Path(name).name != 'unity_m_resume_context.py':
            raise ValueError('Only the explicit resume-context dependency may be new')
    verify_path_type_recovery(workspace,value,current)
    admission._check_regression(value['regression'])
    if batch.read(parent.reference(value['regression'])).get('production') != current:
        raise ValueError('Regression must bind the complete current producer')
    root=workspace/'recovery_runs'/parent.ROOT
    failure=root/'unity_m_judge_failures'/FAILURE
    required={failure,root/'unity_m_direct_observed_authorization.json',
              root/'unity_m_direct_observed_corrections/mechanic_singleton_10.json',
              root/'unity_m_judge_continuation.json'}
    correction=root/'model_calls/unity_m_mechanic_singleton_10_direct_observed_bug_correction_01'
    required.update(correction/n for n in ('prompt.txt','schema.json','invocation.json','response.json',
                                         'rpc_requests.jsonl','rpc_events.jsonl','retained_session.jsonl'))
    required.update(root/'judgments'/f'unity_m_mechanic_singleton_{n:02d}.json' for n in range(1,10))
    bindings=value.get('bindings',{})
    if (value.get('root') != str(root) or value.get('parent_failure') != str(failure)
            or not {str(p) for p in required} <= set(bindings)
            or batch.read(failure).get('error') != repr(ValueError(ERROR))):
        raise ValueError('Exact actual failed delivery, correction and accepted shards required')
    for name,digest in bindings.items():
        if Path(name).is_symlink() or sha(Path(name)) != digest:
            raise ValueError('Preserved resume-context lineage changed: '+name)
    original=root/'model_calls/unity_m_mechanic_singleton_10'
    task=batch.read(root/'unity_m_requests/Mechanic/mechanic_singleton_10.json')
    verify_inputs(correction,original,[task['prompt'],(correction/'prompt.txt').read_text()])
    # Existing response is reused and independently checked by the frozen policy.
    from . import codex, unity_m_judge as judge, mechanic_v3_outcome as policy
    from .unity_m_delivery import validation_manifest
    raw=batch.read(correction/'response.json');codex.validate_schema(raw,task['schema'])
    _,contract,_=judge.contract(workspace,'G018_portal_freight','Mechanic')
    policy.evaluate(root,batch.read(root/'input/pilot_rubric.json'),validation_manifest(root,task),
                    task['rules'],contract,raw,task['specs'])
    repair=parent.reference(value['judge_repair']); rv=batch.read(repair)
    producer=batch.read(root/'unity_m_judge_producer.json')
    original_production=producer['production']
    delta={p for p in original_production.keys()|current.keys() if original_production.get(p)!=current.get(p)}
    if (rv.get('after_producer') != dict(producer,production=current)
            or rv.get('parent_producer_sha256') != sha(root/'unity_m_judge_producer.json')
            or rv.get('classification') != 'NON_SCORING_TRANSPORT_AND_METADATA_REPAIR'
            or rv.get('parent_failure_bindings',{}).get(str(failure)) != sha(failure)
            or rv.get('parent_continuation') != dict(path=str(root/'unity_m_judge_continuation.json'),sha256=sha(root/'unity_m_judge_continuation.json'))
            or set(rv.get('changed_files',{})) != delta
            or rv.get('regression') != value['regression']):
        raise ValueError('Exact current formal judge continuation required')
    for name,archive in rv['changed_files'].items():
        if name in original_production:
            if not archive or sha(Path(archive['archive'])) != original_production[name]:
                raise ValueError('Exact original judge producer archive required')
        elif archive is not None:
            raise ValueError('New judge dependency must be explicit')
    for name,digest in rv['parent_failure_bindings'].items():
        if sha(Path(name)) != digest:raise ValueError('Actual parent failure changed')
    return value


def verify_path_type_recovery(workspace,value,current):
    from . import unity_m_direct_bug_recovery as parent
    # A failed real continuation exposed a Path/string handoff. Preserve the
    # prior executed descriptor and producer rather than replacing its binding.
    recovery=value.get('path_type_recovery',{})
    previous_path=parent.reference(recovery['previous_repair'])
    previous=batch.read(previous_path)
    old_module=parent.reference(recovery['previous_module'])
    module=str(Path(__file__).resolve())
    old_production=previous['after_production']
    if (old_production.get(module)!=sha(old_module)
            or {p for p in old_production.keys()|current.keys() if old_production.get(p)!=current.get(p)}!={module}
            or previous.get('before_production')!=value['before_production']
            or previous.get('parent_repair')!=value['parent_repair']
            or any(value['bindings'].get(p)!=digest for p,digest in previous['bindings'].items())):
        raise ValueError('Exact previous executed resume-context producer required')
    old_pointer=Path(workspace)/'engineering/unity_m_g018_resume_context_repair.json'
    if batch.read(old_pointer)!=recovery['previous_repair']:
        raise ValueError('Immutable previous restricted registration required')
    failed_path=parent.reference(recovery['failure'])
    failed=batch.read(failed_path)
    if (failed.get('column')!='Mechanic'
            or failed.get('error')!=repr(AttributeError("'str' object has no attribute 'read_text'"))
            or 'qualify_authorization' not in failed.get('traceback','')
            or "value=batch.read(result['descriptor'])" not in failed.get('traceback','')
            or value['bindings'].get(str(failed_path))!=sha(failed_path)):
        raise ValueError('Actual saved-response Path handoff failure required')
    executed=parent.reference(recovery['executed_continuation'])
    receipt=batch.read(executed)
    if (receipt.get('repair_sha256')!=previous['judge_repair']['sha256']
            or receipt.get('after_producer',{}).get('production')!=old_production
            or value['bindings'].get(str(executed))!=sha(executed)):
        raise ValueError('Actual previous failed producer continuation required')


def require(workspace,identity,operation,column):
    from .unity_m_direct_bug_recovery import reference
    descriptor=reference(batch.read(Path(workspace)/POINTER))
    qualify(workspace,identity,operation,column,descriptor)
    return dict(restricted=True,identity=identity,operation=operation,column=column,
                new_native_calls=0,descriptor=str(descriptor),sha256=sha(descriptor))


def qualify_authorization(workspace,root,task,authorization):
    from . import unity_m_direct_bug_recovery as parent
    result=require(workspace,parent.IDENTITY,'judge','Mechanic')
    value=batch.read(Path(result['descriptor']))
    if (Path(root) != Path(value['root']) or task.get('name') != 'mechanic_singleton_10'
            or authorization.get('production') != value['before_production']):
        raise ValueError('Exact immutable parent authorization required')


def register(workspace,descriptor):
    from .unity_m_judge import exact_json
    value=qualify(workspace,'Kimi__G018_portal_freight','judge','Mechanic',descriptor)
    path=Path(workspace)/POINTER
    exact_json(path,dict(path=str(Path(descriptor).resolve()),sha256=sha(descriptor)))
    require(workspace,value['identity'],'judge','Mechanic')
    return path,value


def verify_complete(workspace,descriptor):
    from . import unity_m_direct_bug_recovery as parent, unity_m_judge as judge
    value=batch.read(descriptor);repair=parent.reference(value['repair'])
    qualification=qualify(workspace,parent.IDENTITY,'judge','Mechanic',repair)
    process=batch.read(parent.reference(value['completed_process']))
    parent.verify_process(process,workspace,parent.reference(qualification['judge_repair']))
    root,proof=admission.evidence(workspace,parent.IDENTITY)
    paths=[root/'unity_m_judge_continuation.json',*sorted((root/'unity_m_judge_continuations').glob('*.json'))]
    matches=[p for p in paths if p.exists() and batch.read(p)['after_producer']['production']==admission.production()
             and batch.read(p)['repair_sha256']==qualification['judge_repair']['sha256']]
    if len(matches)!=1:raise ValueError('Actual current producer continuation required')
    accepted=batch.read(root/'judgments/unity_m_mechanic_singleton_10.json')
    correction=root/'model_calls/unity_m_mechanic_singleton_10_direct_observed_bug_correction_01'
    if (accepted.get('response_sha256')!=sha(correction/'response.json')
            or not accepted.get('actual_delivery',{}).get('resume_environment',{}).get('all_original_submitted_inputs_exact')):
        raise ValueError('Saved correction must close with actual exact delivery proof')
    pub=batch.read(judge.publication_path(Path(workspace),parent.IDENTITY,'Mechanic'))
    required=[matches[0],parent.reference(qualification['judge_repair']),
              root/'unity_m_direct_observed_authorization.json',root/'unity_m_direct_observed_corrections/mechanic_singleton_10.json']
    if any(pub.get('bindings',{}).get(str(p))!=sha(p) for p in required):
        raise ValueError('Actual published column must bind recovery lineage')
    return proof,batch.read(matches[0])['after_producer']


def create(workspace,descriptor):
    proof,producer=verify_complete(workspace,descriptor)
    value=dict(version=admission.VERSION,capability='UNITY_M_MECHANIC_V3_GAMENESS_V4_ORIGINAL_PIXELS',
               verification_production=admission.production(),executed_producer=producer,e2e=proof,
               resume_context_recovery=dict(path=str(Path(descriptor).resolve()),sha256=sha(descriptor)),
               scoring_unchanged=True,model='gpt-6.1-sol')
    path=admission.admission_path(workspace,value['verification_production'])
    if path.exists():
        if batch.read(path)!=value:raise ValueError('Immutable completed resume-context admission changed')
    else:
        from .mechanic_v3_runner import exclusive_json
        exclusive_json(path,value)
    return path,value
