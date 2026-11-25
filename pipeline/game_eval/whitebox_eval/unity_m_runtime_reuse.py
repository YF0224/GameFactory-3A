"""Fork a fully acknowledged original runtime before any scoring turn.

Only identical original runtime envelopes may be reused. Every target retains
its complete original request, frozen contract, schema and independent judgment.
"""
from pathlib import Path
import hashlib
import json
from . import batch
from .protocol import sha

VERSION = 'unity-m-complete-unscored-runtime-fork.v1'


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def equivalent_runtime(source, target):
    from .unity_m_runtime_wire import INTRO, verify
    if (source['column'] != 'Gameness' or target['column'] != 'Gameness'
            or not source.get('numeric_event_packets') or not target.get('numeric_event_packets')
            or source['common_prompt_sha256'] != target['common_prompt_sha256']
            or source['contract_sha256'] != target['contract_sha256']):
        raise ValueError('Same complete original source and frozen runtime contract required')
    for task in (source, target):verify(task['prompt'], task['shared_runtime_packets'])
    source_prefix, source_wire = source['prompt'].split(INTRO, 1)
    target_prefix, target_wire = target['prompt'].split(INTRO, 1)
    if source_wire != target_wire or source['shared_runtime_packets'] != target['shared_runtime_packets']:
        raise ValueError('Only byte-identical complete original runtime may be reused')
    return target_prefix, INTRO+target_wire


def qualified_runtime(root, source):
    """Recheck the original source/image fork and every ordered acknowledged byte."""
    from .unity_m_delivery import rows, text_inputs, runtime_prompts, qualified_ack, exact_fork
    from .unity_m_numeric_recovery import verify_task
    from .gameness_v4_persistent_capacity import telemetry
    from .unity_m_intake_recovery import parent
    root=Path(root);path=root/'unity_m_runtime_transport'/(source['name']+'.json')
    transport=batch.read(path)
    request=root/'unity_m_requests'/source['column']/(source['name']+'.json')
    if (transport['original_request_sha256'] != sha(request)
            or ''.join(transport['chunks']) != source['prompt']):
        raise ValueError('Complete immutable parent runtime request required')
    bindings={str(path):sha(path),str(request):sha(request)}
    folders=[];turns=[]
    for name,prompt in zip(transport['chunk_folders'],transport['chunk_prompts']):
        original=Path(name);folder=qualified_ack(original);accepted=batch.read(folder/'accepted_intake.json')
        inv=batch.read(folder/'invocation.json');response=batch.read(folder/'response.json')
        if ((original/'prompt.txt').read_text()!=prompt or response!={'receipt':'EXACT_RUNTIME_CHUNK_RETAINED'}
                or accepted['response']!=response or accepted['session_sha256']!=sha(folder/'retained_session.jsonl')
                or accepted['usage']!=telemetry(folder/'retained_session.jsonl')[-1]):
            raise ValueError('Every original runtime chunk requires an exact accepted receipt')
        if folder!=original:turns.append(batch.read(original/'invocation.json')['turn'])
        turns.append(inv['turn']);folders.append(folder)
        for f in {folder,original}:
            for n in ('prompt.txt','schema.json','response.json','invocation.json','retained_session.jsonl','accepted_intake.json','receipt_correction.json','rpc_requests.jsonl','rpc_events.jsonl'):
                p=f/n
                if p.exists():bindings[str(p)]=sha(p)
    if len(folders)!=len(transport['chunks']) or not folders:
        raise ValueError('All declared runtime chunks required')
    last=folders[-1];data=rows(last/'retained_session.jsonl')
    completed=[r['payload']['turn_id'] for r in data if r.get('payload',{}).get('type')=='task_complete']
    if (text_inputs(data)!=runtime_prompts(transport) or completed!=turns
            or data[-1].get('payload',{}).get('type')!='task_complete'):
        raise ValueError('Parent must end at complete runtime intake, before any judgment')
    inheritance=exact_fork(root/'model_calls/unity_m_original_intake',Path(transport['chunk_folders'][0]),last/'retained_session.jsonl')
    source_folder,source_prompts,source_turns=parent(root/'model_calls/unity_m_original_intake')
    for n in ('prompt.txt','schema.json','response.json','invocation.json','retained_session.jsonl','accepted_response.json'):
        p=source_folder/n;bindings[str(p)]=sha(p)
    return dict(folder=str(last),thread=batch.read(last/'invocation.json')['thread'],turn=turns[-1],
        snapshot_sha256=sha(last/'retained_session.jsonl'),usage=telemetry(last/'retained_session.jsonl')[-1],
        inherited_prompts=source_prompts+runtime_prompts(transport),inherited_turns=source_turns+turns,
        source_inheritance=inheritance,numeric_delivery=verify_task(root,source),bindings=bindings)


def descriptor_path(root,task):
    return Path(root)/'unity_m_runtime_reuse'/(task['name']+'.json')


def final_prompt(task,prefix,wire):
    return (prefix+'\nCOMPLETE ORIGINAL RUNTIME REUSE: The exact runtime literal envelope SHA256 '+digest(wire)+
            ' is already retained in the inherited successful runtime intake. Read every original packet, occurrence and physical line from that envelope. '
            'Combining the exact target prefix above with that unchanged envelope reconstructs the complete original target request SHA256 '+digest(task['prompt'])+'. '
            'The full original author sources and all original native pixels are inherited unchanged. No scoring turn is inherited. '
            'Evaluate only the current CHECKS under the unchanged output schema. Do not call tools, compact, summarize or omit evidence.')


def capacity(root,task,parent,prompt):
    from .unity_m_judge import WINDOW,RESERVE,MARGIN
    from .unity_m_schema_recovery import initial_schema
    submitted=initial_schema(root,task)
    required=parent["usage"]["input_tokens"]+parent["usage"]["output_tokens"]+len(prompt.encode())+len(json.dumps(submitted).encode())+RESERVE+MARGIN
    if required>min(WINDOW,parent["usage"]["window"]):raise ValueError("Complete runtime reuse exceeds frozen capacity")
    return required


def prepare(root,task):
    """Only a new judge may fork a complete acknowledged sibling runtime."""
    from .unity_m_judge import exact_json, WINDOW, RESERVE, MARGIN
    from .unity_m_schema_recovery import initial_schema
    root=Path(root);path=descriptor_path(root,task)
    if path.exists():return resolve(root,task)
    if (not task.get('numeric_event_packets') or task['column']!='Gameness'
            or (root/'model_calls'/('unity_m_'+task['name'])).exists()):return None
    candidates=sorted((root/'unity_m_runtime_transport').glob('gameness_group_*.json'))
    for p in candidates:
        if p.stem==task['name']:continue
        source=batch.read(root/'unity_m_requests/Gameness'/(p.stem+'.json'))
        try:
            prefix,wire=equivalent_runtime(source,task)
            parent=qualified_runtime(root,source)
        except (ValueError,FileNotFoundError):continue
        prompt=final_prompt(task,prefix,wire)
        try:required=capacity(root,task,parent,prompt)
        except ValueError:continue
        preserved={}
        old=root/'unity_m_runtime_transport'/(task['name']+'.json')
        if old.exists():
            preserved[str(old)]=sha(old)
            for folder in batch.read(old)['chunk_folders']:
                for f in Path(folder).glob('*'):
                    if f.is_file():preserved[str(f)]=sha(f)
        value=dict(version=VERSION,source_task=source['name'],target_request_sha256=sha(root/'unity_m_requests'/task['column']/(task['name']+'.json')),
            source_runtime=parent,final_prompt=prompt,fork_through=parent['turn'],runtime_envelope_sha256=digest(wire),
            required=required,window=parent['usage']['window'],maximum_new_calls=1,
            preserved_incomplete_bindings=preserved,prior_judgments_inherited=False)
        exact_json(path,value)
        return value
    return None


def resolve(root,task):
    root=Path(root);value=batch.read(descriptor_path(root,task))
    if (value.get('version')!=VERSION or value.get('maximum_new_calls')!=1
            or value.get('prior_judgments_inherited') is not False
            or value['target_request_sha256']!=sha(root/'unity_m_requests'/task['column']/(task['name']+'.json'))):
        raise ValueError('Exact independent runtime reuse descriptor required')
    source=batch.read(root/'unity_m_requests/Gameness'/(value['source_task']+'.json'))
    prefix,wire=equivalent_runtime(source,task);parent=qualified_runtime(root,source)
    if (value['source_runtime']!=parent or value['fork_through']!=parent['turn']
            or value['runtime_envelope_sha256']!=digest(wire) or value['final_prompt']!=final_prompt(task,prefix,wire)
            or value['required']!=capacity(root,task,parent,value['final_prompt'])
            or value['window']!=parent['usage']['window']):
        raise ValueError('Complete original runtime reuse binding changed')
    for p,d in value['preserved_incomplete_bindings'].items():
        if sha(Path(p))!=d:raise ValueError('Preserved incomplete runtime attempt changed')
    return value


def exact_runtime_fork(parent,folder,snapshot):
    from .unity_m_delivery import rows
    folder=Path(folder);data=rows(snapshot);inv=batch.read(folder/'invocation.json')
    parent_file=Path(parent['folder'])/'retained_session.jsonl';raw=parent_file.read_bytes();before=rows(parent_file)
    metas=[r['payload'] for r in data if r.get('type')=='session_meta']
    if len(metas)!=1:raise ValueError('One exact runtime fork metadata required')
    meta=metas[0];history=meta.get('history_base',{})
    if (meta.get('id')!=inv['thread'] or meta.get('forked_from_id')!=parent['thread']
            or history.get('thread_id')!=parent['thread'] or history.get('end_byte_offset')!=len(raw)
            or history.get('end_ordinal_exclusive')!=before[-1]['ordinal']+1
            or meta.get('forked_from_ordinal_exclusive')!=history.get('end_ordinal_exclusive')
            or before[-1].get('payload',{}).get('type')!='task_complete'
            or before[-1]['payload'].get('turn_id')!=parent['turn'] or sha(parent_file)!=parent['snapshot_sha256']):
        raise ValueError('Fork must end at exact complete unscored runtime snapshot')
    for row in before+data:
        payload=row.get('payload',{})
        if 'compact' in (str(row.get('type'))+' '+str(payload.get('type'))).lower():raise ValueError('Compacted runtime fork forbidden')
        if row.get('type')=='turn_context' and payload.get('model')!='gpt-6.1-sol':raise ValueError('Runtime fork model changed')
    requests=[r for r in rows(folder/'rpc_requests.jsonl') if r.get('method')=='thread/fork']
    if len(requests)!=1:raise ValueError('One actual runtime fork required')
    request=requests[0]
    if request['params'].get('threadId')!=parent['thread'] or request['params'].get('lastTurnId')!=parent['turn']:
        raise ValueError('Runtime fork parent/turn changed')
    responses=[r for r in rows(folder/'rpc_events.jsonl') if r.get('id')==request['id']]
    if len(responses)!=1:raise ValueError('One actual runtime fork response required')
    thread=responses[0].get('result',{}).get('thread',{});turns=thread.get('turns',[])
    prompts=[c['text'] for t in turns for i in t.get('items',[]) if i.get('type')=='userMessage'
             for c in i.get('content',[]) if c.get('type')=='text']
    if (thread.get('id')!=inv['thread'] or thread.get('forkedFromId')!=parent['thread']
            or [t.get('id') for t in turns]!=parent['inherited_turns'] or prompts!=parent['inherited_prompts']
            or any(t.get('status')!='completed' for t in turns)):
        raise ValueError('RPC must inherit every original source/runtime turn and no judgment')
    return dict(parent_snapshot_sha256=sha(parent_file),parent_prefix_bytes=len(raw),parent_turn=parent['turn'],
        parent_thread=parent['thread'],rpc_requests_sha256=sha(folder/'rpc_requests.jsonl'),rpc_events_sha256=sha(folder/'rpc_events.jsonl'))


def delivery(root,folder,task,transport,correction=None,*,failed_output=False):
    from .unity_m_delivery import rows,text_inputs,validation_manifest
    from .unity_m_judge import WINDOW,RESERVE
    from .gameness_v4_persistent_text import session_path
    from .gameness_v4_persistent_capacity import telemetry
    from .native_image_cli_probe import retained_images
    from .unity_m_numeric_recovery import verify_task
    root=Path(root);folder=Path(folder);value=resolve(root,task)
    if value!=transport:raise ValueError('Runtime reuse descriptor changed')
    invocation=batch.read(folder/'invocation.json');snapshot=folder/'retained_session.jsonl'
    if not snapshot.exists():snapshot.write_bytes(session_path(invocation['thread']).read_bytes())
    original=Path(correction['original_folder']) if correction else folder
    inherited=exact_runtime_fork(value['source_runtime'],original,snapshot)
    expected=[value['final_prompt']]
    if correction:
        from .unity_m_output_recovery import resolve as resolve_correction
        resolved,qualified=resolve_correction(root,task)
        if resolved!=folder or qualified!=correction or batch.read(original/'invocation.json')['thread']!=invocation['thread']:
            raise ValueError('Same-thread qualified correction required')
        expected+=correction.get('prior_prompts',[])+[correction['prompt']]
    data=rows(snapshot)
    if text_inputs(data)!=expected:raise ValueError('Exact independent task prefix and correction history required')
    completed=[r['payload'].get('turn_id') for r in data if r.get('payload',{}).get('type')=='task_complete']
    if failed_output:
        from .unity_m_output_recovery import validate_truncation
        if validate_truncation(folder)!=invocation:raise ValueError('Exact incomplete output required')
    elif not completed or completed[-1]!=invocation['turn']:raise ValueError('Completed independent judgment required')
    common=batch.read(root/'unity_m_common_request.json')
    pixels=retained_images(root/'model_calls/unity_m_original_intake/retained_session.jsonl',common['prompt'],[Path(p) for p in common['images']])
    usage=telemetry(snapshot)[-1]
    if usage['input_tokens']+usage['output_tokens']+RESERVE>min(WINDOW,usage['window']):raise ValueError('Retained runtime fork exceeds frozen reserve')
    return dict(runtime_reuse_version=VERSION,runtime_reuse_descriptor_sha256=sha(descriptor_path(root,task)),
        runtime_inheritance=inherited,source_inheritance=value['source_runtime']['source_inheritance'],
        numeric_event_delivery=verify_task(root,task),session_sha256=sha(snapshot),pixels=pixels,usage=usage,
        no_compaction=True,prior_judgments_inherited=False,exact_original_runtime_text=True,
        original_manifest_sha256=sha(root/'evidence_manifest.json'),validation_manifest_sha256=hashlib.sha256(json.dumps(validation_manifest(root,task),sort_keys=True).encode()).hexdigest())
