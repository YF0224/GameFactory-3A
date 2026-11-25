"""Bounded corrections of diagnosed output failures; scoring remains unchanged."""
from pathlib import Path
import json
from . import batch, codex
from .protocol import sha

ERROR = 'Invalid physical line range'
BASIC_ERROR = 'NORMAL lacks actual correct functioning/processing proof'
BASIC_VERSION = 'unity-m-basic-runtime-reference-correction.v1'
DIRECT_BUG_VERSION = 'unity-m-direct-observed-counterexample-correction.v1'


def reversed_ranges(response):
    found=[]
    checks=response.get('checks',{}) if isinstance(response,dict) else {}
    if not isinstance(checks,dict):return found
    for ident,row in checks.items():
        for stage in ('source_existence','basic_function','result_outcome'):
            for index,ref in enumerate(row.get(stage,{}).get('evidence',[])):
                a,b=ref.get('line_start'),ref.get('line_end')
                if type(a) is int and type(b) is int and a>b:
                    found.append(dict(check=ident,stage=stage,index=index,id=ref['id'],line_start=a,line_end=b))
    return found


def resolve(root,task):
    from .unity_m_incomplete_recovery import resolve as resolve_incomplete
    incomplete=resolve_incomplete(root,task)
    if incomplete:return incomplete
    from .unity_m_observed_bug_recovery import resolve as resolve_bug
    observed = resolve_bug(root,task)
    if observed:return observed
    from .unity_m_schema_recovery import resolve_compact
    direct = resolve_direct_bug(root, task)
    if direct:return direct
    compact=resolve_compact(root,task)
    if compact:return compact
    root=Path(root);path=root/'unity_m_output_corrections'/(task['name']+'.json')
    original=root/'model_calls'/('unity_m_'+task['name'])
    if not path.exists():return original,None
    value=batch.read(path)
    if (value['maximum_new_calls']!=1 or value['original_folder']!=str(original)
            or value['request_sha256']!=sha(root/'unity_m_requests'/task['column']/(task['name']+'.json'))):
        raise ValueError('Exact bounded output correction task required')
    for p,d in value['bindings'].items():
        if sha(Path(p))!=d:raise ValueError('Original failed response or delivery changed')
    if value.get('version')==BASIC_VERSION:
        from .unity_m_schema_recovery import schema_for_task
        if (value['parent_error']!=BASIC_ERROR or task['column']!='Gameness'
                or value['reference_gaps']!=basic_reference_gaps(root,task,batch.read(original/'response.json'))
                or not value['reference_gaps']):
            raise ValueError('Exact original basic runtime-reference gap required')
        folder=root/'model_calls'/('unity_m_'+task['name']+'_basic_reference_correction_01')
        if value['correction_folder']!=str(folder):raise ValueError('Fixed runtime-reference correction destination required')
        if not (folder/'response.json').exists():raise ValueError('Preserved runtime-reference correction failed; no unchanged retry')
        schema=schema_for_task(root,task,None)
        if ((folder/'prompt.txt').read_text()!=value['prompt'] or value['transport_schema']!=schema
                or batch.read(original/'schema.json')!=schema or batch.read(folder/'schema.json')!=schema
                or batch.read(folder/'invocation.json')['thread']!=batch.read(original/'invocation.json')['thread']):
            raise ValueError('Runtime-reference correction must preserve original schema and conversation')
        codex.validate_schema(batch.read(folder/'response.json'),task['schema'])
        return folder,value
    if value.get('version')=='unity-m-schema-shape-correction.v1':
        raw=batch.read(original/'response.json')
        try:codex.validate_schema(raw,batch.read(original/'schema.json'))
        except ValueError as error:
            if str(error)!=value['parent_error']:raise ValueError('Original schema-shape failure changed') from error
        else:raise ValueError('Original response already satisfies its schema')
        folder=root/'model_calls'/('unity_m_'+task['name']+'_schema_shape_correction_01')
        if value['correction_folder']!=str(folder):raise ValueError('Fixed schema correction destination required')
        if not (folder/'response.json').exists():raise ValueError('Preserved schema correction failed; no unchanged retry')
        inv=batch.read(original/'invocation.json')
        if ((folder/'prompt.txt').read_text()!=value['prompt']
                or batch.read(folder/'schema.json')!=batch.read(original/'schema.json')
                or batch.read(folder/'invocation.json')['thread']!=inv['thread']):
            raise ValueError('Schema correction must preserve original schema and conversation')
        codex.validate_schema(batch.read(folder/'response.json'),batch.read(original/'schema.json'))
        return folder,value
    if value.get('version')=='unity-m-truncated-output-schema-recovery.v1':
        validate_truncation(original)
        folder=root/'model_calls'/('unity_m_'+task['name']+'_schema_recovery_01')
        if value['correction_folder']!=str(folder):raise ValueError('Fixed schema recovery destination required')
        return folder,value
    if value['invalid_ranges']!=reversed_ranges(batch.read(original/'response.json')) or not value['invalid_ranges']:
        raise ValueError('Exact reversed physical citation failure required')
    folder=root/'model_calls'/('unity_m_'+task['name']+'_citation_correction_01')
    if value['correction_folder']!=str(folder):raise ValueError('Fixed correction destination required')
    return folder,value


def correct(root,proto,contract,task,transport,error):
    from .unity_m_judge import exact_json, WINDOW, RESERVE, MARGIN
    from .unity_m_delivery import validation_manifest, delivery
    from . import mechanic_v3_outcome, gameness_v4
    from .native_image_cli_probe import rpc_invoke
    root=Path(root);original=root/'model_calls'/('unity_m_'+task['name'])
    raw=batch.read(original/'response.json');invalid=reversed_ranges(raw)
    from .unity_m_observed_bug_recovery import ERROR as observed_error
    if str(error)==observed_error and task['column']=='Mechanic':
        if (root/'unity_m_direct_observed_authorization.json').exists():
            return correct_direct_bug(root,proto,contract,task,transport,original)
        raise error
    if str(error)==BASIC_ERROR and task['column']=='Gameness':
        return correct_basic_reference(root,proto,contract,task,transport,original,raw)
    if str(error)!=ERROR or not invalid:
        schema=batch.read(original/'schema.json')
        try:codex.validate_schema(raw,schema)
        except ValueError as schema_error:
            parent_error=str(schema_error)
        else:raise error
        if (type(raw) is not dict or type(raw.get('checks')) is not list
                or set(raw)!={'checks'}
                or parent_error!="$: missing or unexpected keys; missing=['limitations', 'summary'], unexpected=[]"):
            raise error
        return _correct_schema_shape(root,task,transport,original,raw,schema,parent_error)
    policy=mechanic_v3_outcome if task['column']=='Mechanic' else gameness_v4
    try:policy.evaluate(root,proto,validation_manifest(root,task),task['rules'],contract,raw,task['specs'])
    except ValueError as reproduced:
        if str(reproduced)!=ERROR:raise ValueError('Original correction failure no longer reproduces') from reproduced
    else:raise ValueError('Valid judgment cannot be corrected')
    if (root/'judgments'/('unity_m_'+task['name']+'.json')).exists():raise ValueError('Accepted judgment cannot be corrected')
    proof=delivery(root,original,task,transport)
    prompt=('Your previous judgment failed the unchanged reference validator: Invalid physical line range. '
            'Every physical citation must have line_start <= line_end; STATE citations must use a single physical line. '
            'Reinspect the actual retained evidence and return one complete judgment under the identical schema and frozen criteria. '
            'Do not assume the previous conclusions or copy invalid citations. No score or status is prescribed. '
            'All original author source, native images and complete runtime request remain in this same conversation. '
            'Do not call tools or compact. Invalid reference locations (diagnostics only): '+json.dumps(invalid,ensure_ascii=False))
    usage=proof['usage'];required=usage['input_tokens']+usage['output_tokens']+len(prompt.encode())+len(json.dumps(task['schema']).encode())+RESERVE+MARGIN
    if required>min(WINDOW,usage['window']):raise ValueError('Bounded citation correction exceeds actual retained capacity')
    folder=root/'model_calls'/('unity_m_'+task['name']+'_citation_correction_01')
    files=[original/n for n in ('response.json','prompt.txt','schema.json','invocation.json','retained_session.jsonl')]
    descriptor=dict(version='unity-m-single-reversed-citation-correction.v1',maximum_new_calls=1,
        original_folder=str(original),correction_folder=str(folder),invalid_ranges=invalid,prompt=prompt,
        request_sha256=sha(root/'unity_m_requests'/task['column']/(task['name']+'.json')),
        bindings={str(p):sha(p) for p in files},parent_error=ERROR,required=required,window=usage['window'])
    exact_json(root/'unity_m_output_corrections'/(task['name']+'.json'),descriptor)
    inv=batch.read(original/'invocation.json')
    if folder.exists():
        if not (folder/'response.json').exists():raise ValueError('Preserve attempted correction; no unchanged retry')
        response=batch.read(folder/'response.json')
        if ((folder/'prompt.txt').read_text()!=prompt or batch.read(folder/'schema.json')!=task['schema']
                or batch.read(folder/'invocation.json')['thread']!=inv['thread']):
            raise ValueError('Correction context/schema changed')
    else:
        response,_=rpc_invoke(folder,root,prompt,task['schema'],[],model='gpt-6.1-sol',session=inv['thread'],context_window=WINDOW)
    return folder,descriptor,response


def _correct_schema_shape(root,task,transport,original,raw,schema,parent_error):
    """One same-thread correction for the specifically diagnosed list/object mismatch."""
    from .unity_m_judge import exact_json, WINDOW, RESERVE, MARGIN
    from .unity_m_delivery import delivery
    from .native_image_cli_probe import rpc_invoke
    from .unity_m_schema_recovery import compact_schema
    reduced,equivalence=compact_schema(task['schema'])
    if schema!=reduced:raise ValueError('Schema-shape correction requires exact original equivalent schema')
    root=Path(root)
    if (root/'judgments'/('unity_m_'+task['name']+'.json')).exists():
        raise ValueError('Accepted judgment cannot be schema-corrected')
    proof=delivery(root,original,task,transport)
    prompt=('Your previous response failed the unchanged output schema: the top-level checks value was an array, '
        'but checks must be an object keyed by the exact criterion IDs; required top-level summary and limitations '
        'were also omitted. Re-evaluate the retained evidence and return one complete response conforming to the '
        'exact unchanged schema below. Preserve every required field and original criterion identity. Do not invent '
        'evidence, infer a score from the prior response, call tools, repeat sources/images or compact context. '
        'No score or status is prescribed. The original request, complete author sources and all native frames '
        'remain in this same conversation.\nEXACT UNCHANGED OUTPUT SCHEMA:\n'+json.dumps(schema,ensure_ascii=False))
    usage=proof['usage'];required=usage['input_tokens']+usage['output_tokens']+len(prompt.encode())+len(json.dumps(schema).encode())+RESERVE+MARGIN
    if required>min(WINDOW,usage['window']) or len(prompt.encode())>1000000:
        raise ValueError('Bounded schema-shape correction exceeds actual retained capacity')
    folder=root/'model_calls'/('unity_m_'+task['name']+'_schema_shape_correction_01')
    descriptor=dict(version='unity-m-schema-shape-correction.v1',maximum_new_calls=1,
        original_folder=str(original),correction_folder=str(folder),request_sha256=sha(root/'unity_m_requests'/task['column']/(task['name']+'.json')),
        parent_error=parent_error,prompt=prompt,required=required,window=usage['window'],
        transport_schema=schema,schema_equivalence=equivalence,
        response_sha256=sha(original/'response.json'),schema_sha256=sha(original/'schema.json'),
        bindings={str(original/n):sha(original/n) for n in ('response.json','prompt.txt','schema.json','invocation.json','retained_session.jsonl')})
    exact_json(root/'unity_m_output_corrections'/(task['name']+'.json'),descriptor)
    if folder.exists():raise ValueError('Existing unqualified schema-shape attempt must be preserved')
    invocation=batch.read(original/'invocation.json')
    response,_=rpc_invoke(folder,root,prompt,schema,[],model='gpt-6.1-sol',session=invocation['thread'],context_window=WINDOW)
    codex.validate_schema(response,schema)
    return folder,descriptor,response


def validate_truncation(folder):
    """A real failed final turn, never a valid or accepted response, is required."""
    folder=Path(folder)
    if (folder/'response.json').exists():raise ValueError('Completed response cannot enter truncation recovery')
    inv=batch.read(folder/'invocation.json')
    events=[json.loads(s) for s in (folder/'rpc_events.jsonl').read_text().splitlines() if s.strip()]
    ends=[v['params'] for v in events if v.get('method')=='turn/completed'
          and v.get('params',{}).get('turn',{}).get('id')==inv.get('turn')]
    if (inv.get('status')!='HARNESS_ERROR' or len(ends)!=1 or ends[0].get('threadId')!=inv.get('thread')
            or ends[0]['turn'].get('status')!='failed'
            or ends[0]['turn'].get('error',{}).get('message')!='Incomplete response returned, reason: max_output_tokens'):
        raise ValueError('Exact actual output truncation required')
    return inv


def recover_truncation(root,task,transport):
    from .unity_m_judge import exact_json, WINDOW, RESERVE, MARGIN
    from .unity_m_delivery import delivery
    from .native_image_cli_probe import rpc_invoke
    root=Path(root);original=root/'model_calls'/('unity_m_'+task['name'])
    inv=validate_truncation(original)
    if (root/'judgments'/('unity_m_'+task['name']+'.json')).exists():
        raise ValueError('Accepted judgment cannot be corrected')
    proof=delivery(root,original,task,transport,failed_output=True)
    prompt=('The previous final turn returned no complete judgment: max_output_tokens. '
            'This is one bounded output-format recovery, with the complete unchanged JSON schema now explicit in the text. '
            'All original author source, native frames and runtime evidence remain in this same conversation. '
            'Evaluate precisely the criterion keys in this schema under the retained original request and frozen contract. '
            'Return the entire schema-valid JSON with concise reasons and sufficient actual evidence citations. '
            'No status or score is prescribed; do not drop required fields, invent evidence, call tools or compact. '
            'EXACT UNCHANGED OUTPUT SCHEMA:\n'+json.dumps(task['schema'],ensure_ascii=False))
    usage=proof['usage'];required=usage['input_tokens']+usage['output_tokens']+len(prompt.encode())+len(json.dumps(task['schema']).encode())+RESERVE+MARGIN
    if required>min(WINDOW,usage['window']) or len(prompt.encode())>1000000:
        raise ValueError('Bounded schema recovery exceeds actual retained capacity')
    folder=root/'model_calls'/('unity_m_'+task['name']+'_schema_recovery_01')
    files=[original/n for n in ('prompt.txt','schema.json','invocation.json','rpc_requests.jsonl','rpc_events.jsonl','retained_session.jsonl')]
    descriptor=dict(version='unity-m-truncated-output-schema-recovery.v1',maximum_new_calls=1,
        original_folder=str(original),correction_folder=str(folder),prompt=prompt,
        request_sha256=sha(root/'unity_m_requests'/task['column']/(task['name']+'.json')),
        bindings={str(p):sha(p) for p in files},parent_error='max_output_tokens',required=required,window=usage['window'])
    exact_json(root/'unity_m_output_corrections'/(task['name']+'.json'),descriptor)
    if folder.exists():
        if not (folder/'response.json').exists():raise ValueError('Preserve failed bounded schema recovery; no unchanged retry')
        response=batch.read(folder/'response.json')
        if ((folder/'prompt.txt').read_text()!=prompt or batch.read(folder/'schema.json')!=task['schema']
                or batch.read(folder/'invocation.json')['thread']!=inv['thread']):
            raise ValueError('Schema recovery context/schema changed')
    else:
        response,_=rpc_invoke(folder,root,prompt,task['schema'],[],model='gpt-6.1-sol',session=inv['thread'],context_window=WINDOW)
    return folder,descriptor,response


def basic_reference_gaps(root,task,raw):
    """Diagnose missing actual runtime references without changing any judgment."""
    from .unity_m_delivery import validation_manifest
    from .gameness_v3 import inspect_references
    manifest=validation_manifest(root,task);gaps=[]
    for ident,row in raw['checks'].items():
        basic=row['basic_function']
        if basic['status']!='NORMAL':continue
        facts=inspect_references(root,manifest,task['rules'],basic['evidence'])
        if (all(basic[k] for k in ('correct_target','correct_core_information','functional_effect_proven','no_basic_bug'))
                and basic['reason'].strip() and not facts['outcome_times']
                and basic['processing_basis'] not in {'unchanged_state_only','none'}
                and (basic['trigger_mode']!='rejection' or basic['processing_proven'])):
            gaps.append(ident)
    return gaps


def correct_basic_reference(root,proto,contract,task,transport,original,raw):
    from .unity_m_judge import exact_json,WINDOW,RESERVE,MARGIN
    from .unity_m_delivery import delivery,validation_manifest
    from .unity_m_schema_recovery import schema_for_task
    from .native_image_cli_probe import rpc_invoke
    from . import gameness_v4
    if task['column']!='Gameness':raise ValueError('Diagnosed Gameness reference failure required')
    if (root/'judgments'/('unity_m_'+task['name']+'.json')).exists():raise ValueError('Accepted judgment cannot be corrected')
    try:gameness_v4.evaluate(root,proto,validation_manifest(root,task),task['rules'],contract,raw,task['specs'])
    except ValueError as observed:
        if str(observed)!=BASIC_ERROR:raise ValueError('Original runtime-reference failure changed') from observed
    else:raise ValueError('Valid judgment cannot be corrected')
    gaps=basic_reference_gaps(root,task,raw)
    if not gaps:raise ValueError('Exact actual missing runtime-reference diagnosis required')
    schema=schema_for_task(root,task,None)
    if batch.read(original/'schema.json')!=schema:raise ValueError('Original submitted equivalent schema required')
    proof=delivery(root,original,task,transport)
    prompt=('The previous response was rejected by the unchanged frozen Gameness validator: '+BASIC_ERROR+'. '
        'The basic_function fields listed below claim NORMAL but their own evidence references do not establish any actual runtime observation. '
        'Source implementation alone cannot prove runtime functioning. Evidence cited in another field does not automatically prove this field. '
        'Reinspect the complete retained original evidence and return a complete independent judgment in the same exact schema. '
        'For any claimed NORMAL status, its own evidence must establish the actual observed function; if the actual evidence does not support it, '
        'use the appropriate unchanged status. Do not assume the previous conclusions, copy unsupported claims, invent evidence or change the standard. '
        'No score, status or reference is prescribed. All original source, all native pixels and the complete runtime remain in this same conversation. '
        'Do not call tools, summarize or compact. Diagnostic criterion IDs: '+json.dumps(gaps,ensure_ascii=False))
    usage=proof['usage'];required=usage['input_tokens']+usage['output_tokens']+len(prompt.encode())+len(json.dumps(schema).encode())+RESERVE+MARGIN
    if required>min(WINDOW,usage['window']):raise ValueError('Bounded runtime-reference correction exceeds actual retained capacity')
    folder=root/'model_calls'/('unity_m_'+task['name']+'_basic_reference_correction_01')
    descriptor=dict(version=BASIC_VERSION,maximum_new_calls=1,original_folder=str(original),correction_folder=str(folder),
        request_sha256=sha(root/'unity_m_requests'/task['column']/(task['name']+'.json')),parent_error=BASIC_ERROR,
        reference_gaps=gaps,prompt=prompt,required=required,window=usage['window'],transport_schema=schema,
        bindings={str(original/n):sha(original/n) for n in ('response.json','prompt.txt','schema.json','invocation.json','retained_session.jsonl')})
    exact_json(root/'unity_m_output_corrections'/(task['name']+'.json'),descriptor)
    if folder.exists():raise ValueError('Existing runtime-reference attempt must be preserved; no unchanged retry')
    invocation=batch.read(original/'invocation.json')
    response,_=rpc_invoke(folder,root,prompt,schema,[],model='gpt-6.1-sol',session=invocation['thread'],context_window=WINDOW)
    codex.validate_schema(response,task['schema'])
    return folder,descriptor,response


def verify_direct_bug_authorization(root, task, *, expected_production=None):
    """Only a registered, exact original direct-response validator failure."""
    from . import unity_m_admission as admission
    from .unity_m_observed_bug_recovery import ERROR as observed_error, diagnose
    from .unity_m_schema_recovery import resolve_compact
    from .unity_m_judge import contract
    root=Path(root).resolve()
    authorization=root/'unity_m_direct_observed_authorization.json'
    value=batch.read(authorization)
    workspace=Path(value['workspace'])
    original=root/'model_calls'/('unity_m_'+task['name'])
    current=admission.production() if expected_production is None else expected_production
    if expected_production is None and value.get('production')!=current:
        from .unity_m_resume_context import qualify_authorization
        qualify_authorization(workspace, root, task, value)
        current=value['production']  # immutable parent authorization, explicitly requalified
    if (value.get('version')!=DIRECT_BUG_VERSION or value.get('identity')!='Kimi__G018_portal_freight'
            or value.get('column')!='Mechanic' or task['column']!='Mechanic'
            or task.get('name')!='mechanic_singleton_10'
            or value.get('case_id')!='G018_portal_freight'
            or value.get('task')!=str(root/'unity_m_requests/Mechanic'/ (task['name']+'.json'))
            or value.get('root')!=str(root) or value.get('original_folder')!=str(original)
            or value.get('maximum_new_calls')!=1 or value.get('new_native_calls')!=0
            or value.get('production')!=current or resolve_compact(root,task)
            or (root/'unity_m_output_corrections'/(task['name']+'.json')).exists()):
        raise ValueError('Exact registered direct observed-counterexample authorization required')
    for name,digest in value['bindings'].items():
        if sha(Path(name))!=digest:raise ValueError('Direct counterexample original failure changed')
    failure=Path(value['parent_failure'])
    from .unity_m_direct_bug_recovery import FAILURE, FAILURE_SHA, ROOT
    if (root.name!=ROOT or failure!=root/'unity_m_judge_failures'/FAILURE
            or sha(failure)!=FAILURE_SHA):
        raise ValueError('Actual exact original G018 judge failure required')
    failed=batch.read(failure)
    if failed.get('column')!='Mechanic' or failed.get('error')!=repr(ValueError(observed_error)):
        raise ValueError('Exact original observed-counterexample validator failure required')
    _,cv,_=contract(workspace,value['case_id'],'Mechanic')
    proto=batch.read(root/'input/pilot_rubric.json')
    if diagnose(root,proto,cv,task,original)!=value['reference_gaps']:
        raise ValueError('Original direct observed-counterexample diagnosis changed')
    return value


def resolve_direct_bug(root,task):
    from .unity_m_schema_recovery import schema_for_task
    from .unity_m_observed_bug_recovery import ERROR as observed_error
    root=Path(root)
    path=root/'unity_m_direct_observed_corrections'/(task['name']+'.json')
    if not path.exists():return None
    value=batch.read(path);authorization=verify_direct_bug_authorization(root,task)
    original=root/'model_calls'/('unity_m_'+task['name'])
    folder=root/'model_calls'/('unity_m_'+task['name']+'_direct_observed_bug_correction_01')
    if (value.get('version')!=DIRECT_BUG_VERSION or value.get('maximum_new_calls')!=1
            or value.get('parent_error')!=observed_error or value.get('prior_prompts')!=[]
            or value.get('original_folder')!=str(original) or value.get('correction_folder')!=str(folder)
            or value.get('authorization_sha256')!=sha(root/'unity_m_direct_observed_authorization.json')
            or value.get('reference_gaps')!=authorization['reference_gaps']
            or value.get('request_sha256')!=sha(root/'unity_m_requests'/task['column']/(task['name']+'.json'))
            or value.get('transport_schema')!=schema_for_task(root,task,None)):
        raise ValueError('Exact bounded direct counterexample correction required')
    if not (folder/'response.json').exists():
        raise ValueError('Preserve the attempted direct correction; no unchanged retry')
    if ((folder/'prompt.txt').read_text()!=value['prompt']
            or batch.read(folder/'schema.json')!=value['transport_schema']
            or batch.read(folder/'invocation.json')['thread']!=batch.read(original/'invocation.json')['thread']):
        raise ValueError('Direct correction must preserve the original schema and conversation')
    codex.validate_schema(batch.read(folder/'response.json'),task['schema'])
    return folder,value


def correct_direct_bug(root,proto,contract,task,transport,original):
    from .unity_m_judge import exact_json, WINDOW, RESERVE, MARGIN
    from .unity_m_delivery import delivery
    from .unity_m_schema_recovery import schema_for_task
    from .unity_m_observed_bug_recovery import ERROR as observed_error
    from .native_image_cli_probe import rpc_invoke
    root=Path(root)
    if (root/'judgments'/('unity_m_'+task['name']+'.json')).exists():
        raise ValueError('Accepted judgments cannot be corrected')
    value=verify_direct_bug_authorization(root,task)
    path=root/'unity_m_direct_observed_corrections'/(task['name']+'.json')
    folder=root/'model_calls'/('unity_m_'+task['name']+'_direct_observed_bug_correction_01')
    if path.exists() or folder.exists():raise ValueError('Preserve existing direct correction; no unchanged retry')
    proof=delivery(root,original,task,transport)
    schema=schema_for_task(root,task,None)
    if batch.read(original/'schema.json')!=schema:raise ValueError('Original direct schema changed')
    prompt=('The previous complete response failed the unchanged Mechanic validator: '+observed_error+'. '
        'BUG and CONTRADICTED require actual observed runtime counterexamples in their own evidence. '
        'Source analysis can identify a possible defect but alone does not prove it occurred in this capture. '
        'Actions alone do not prove a gameplay response. Reinspect the complete retained original source and '
        'all original native pixels and runtime evidence. Return a complete independent judgment in the exact '
        'same schema. Choose only statuses and references supported by actual evidence; no status, score or '
        'reference is prescribed. Do not invent an observation or copy an unsupported previous conclusion. '
        'All frozen criteria, weights and 10/50/100 meanings remain unchanged. No tools, compaction or summary. '
        'Diagnostic fields: '+json.dumps(value['reference_gaps'],ensure_ascii=False))
    usage=proof['usage']
    required=usage['input_tokens']+usage['output_tokens']+len(prompt.encode())+len(json.dumps(schema).encode())+RESERVE+MARGIN
    if required>min(WINDOW,usage['window']):raise ValueError('Direct counterexample correction exceeds actual retained capacity')
    descriptor=dict(version=DIRECT_BUG_VERSION,maximum_new_calls=1,parent_error=observed_error,
        original_folder=str(original),correction_folder=str(folder),prior_prompts=[],prompt=prompt,
        transport_schema=schema,request_sha256=sha(root/'unity_m_requests'/task['column']/(task['name']+'.json')),
        authorization_sha256=sha(root/'unity_m_direct_observed_authorization.json'),
        reference_gaps=value['reference_gaps'],required=required)
    exact_json(path,descriptor)
    inv=batch.read(original/'invocation.json')
    raw,_=rpc_invoke(folder,root,prompt,schema,[],model='gpt-6.1-sol',session=inv['thread'],context_window=WINDOW)
    codex.validate_schema(raw,task['schema'])
    return folder,descriptor,raw
