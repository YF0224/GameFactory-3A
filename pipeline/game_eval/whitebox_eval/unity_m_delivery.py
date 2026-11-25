"""Exact inherited native context and bounded text intake for Unity M.

These are transport/metadata checks. The frozen scoring evaluator is unchanged.
"""
from pathlib import Path
import copy
import hashlib
import json
from . import batch, codex
from .protocol import sha


def rows(path):
    return [json.loads(s) for s in Path(path).read_text().split('\n') if s.strip()]


def text_inputs(values):
    return [i['text'] for v in values if v.get('type') == 'response_item'
            and v.get('payload', {}).get('role') == 'user'
            for i in v['payload'].get('content', []) if i.get('type') in {'text', 'input_text'}]


def exact_fork(parent_folder, fork_folder, snapshot):
    """Verify actual paginated RPC inheritance without concatenating fake logs."""
    parent_folder, fork_folder, snapshot = map(Path, (parent_folder, fork_folder, snapshot))
    from .unity_m_intake_recovery import parent as intake_parent
    parent_folder, parent_prompts, parent_turns = intake_parent(parent_folder)
    parent = batch.read(parent_folder/'invocation.json')
    invocation = batch.read(fork_folder/'invocation.json')
    child = rows(snapshot)
    metas = [v['payload'] for v in child if v.get('type') == 'session_meta']
    if len(metas) != 1:
        raise ValueError('One exact child history metadata required')
    meta = metas[0]; history = meta.get('history_base', {})
    raw = (parent_folder/'retained_session.jsonl').read_bytes(); cut = history.get('end_byte_offset')
    if (meta.get('id') != invocation['thread'] or meta.get('forked_from_id') != parent['thread']
            or history.get('thread_id') != parent['thread'] or type(cut) is not int
            or cut != len(raw) or raw[cut-1:cut] != b'\n'):
        raise ValueError('Exact completed parent snapshot boundary required')
    prefix = rows(parent_folder/'retained_session.jsonl')
    if (history.get('end_ordinal_exclusive') != meta.get('forked_from_ordinal_exclusive')
            or prefix[-1].get('ordinal') != history.get('end_ordinal_exclusive', 0)-1
            or prefix[-1].get('payload', {}).get('type') != 'task_complete'
            or prefix[-1]['payload'].get('turn_id') != parent['turn']):
        raise ValueError('Fork must end at exact successful intake turn')
    for v in prefix+child:
        p = v.get('payload', {})
        if 'compact' in (str(v.get('type'))+' '+str(p.get('type'))).lower():
            raise ValueError('Compacted inherited context forbidden')
        if v.get('type') == 'turn_context' and p.get('model') != 'gpt-6.1-sol':
            raise ValueError('Inherited model changed')
    requests = [v for v in rows(fork_folder/'rpc_requests.jsonl') if v.get('method') == 'thread/fork']
    if len(requests) != 1:
        raise ValueError('One actual exact fork required')
    request = requests[0]
    if request['params'].get('threadId') != parent['thread'] or request['params'].get('lastTurnId') != parent['turn']:
        raise ValueError('Fork request parent/turn changed')
    responses = [v for v in rows(fork_folder/'rpc_events.jsonl') if v.get('id') == request['id']]
    if len(responses) != 1:
        raise ValueError('One actual fork response required')
    thread = responses[0].get('result', {}).get('thread', {}); turns = thread.get('turns', [])
    prompts = [v['text'] for t in turns for i in t.get('items', []) if i.get('type') == 'userMessage'
               for v in i.get('content', []) if v.get('type') == 'text']
    # The source-only parent contains one completed intake, including every image.
    if (thread.get('id') != invocation['thread'] or thread.get('forkedFromId') != parent['thread']
            or [t.get('id') for t in turns] != parent_turns or prompts != parent_prompts
            or any(t.get('status') != 'completed' for t in turns)):
        raise ValueError('RPC must inherit exactly the complete successful original intake')
    return dict(parent_snapshot_sha256=sha(parent_folder/'retained_session.jsonl'),
                parent_prefix_bytes=cut, parent_turn=parent['turn'], parent_thread=parent['thread'],
                rpc_requests_sha256=sha(fork_folder/'rpc_requests.jsonl'),
                rpc_events_sha256=sha(fork_folder/'rpc_events.jsonl'))


def validation_manifest(root, task):
    """Restore the bound capture clock omitted by task construction, not timing."""
    root = Path(root); original = batch.read(root/'evidence_manifest.json')
    frame_rows=rows(root/'runtime/frame_index.jsonl')
    event_rows=rows(root/'runtime/event_trace.jsonl')
    clocks={r.get('clock') for r in frame_rows+event_rows}
    if not frame_rows or clocks!={'recorder_session_monotonic'}:
        raise ValueError('One original Unity recorder clock required')
    clock='recorder_session_monotonic'
    # Native Unity recorder and input driver use the same take-start origin.
    # Generic manifest session_monotonic was a transport default; raw traces
    # remain immutable and all explicit native clocks take precedence.
    if original.get('clock') not in {'session_monotonic',clock}:
        raise ValueError('Unqualified original native clock')
    selected = copy.deepcopy(task['selected'])
    if selected.get('clock', clock) != clock:
        raise ValueError('Task/native clock mismatch')
    by_id={r['frame_id']:r for r in frame_rows}
    for item in selected['items']:
        if item['type']=='frame':
            raw=by_id[item['id']]
            if item['t_ms']!=raw['t_ms'] or item['sha256']!=sha(root/'runtime'/raw['path']):
                raise ValueError('Original native frame clock/timestamp binding changed')
            item['clock']=raw['clock']
    selected['clock'] = clock
    return selected


def split_exact(text, maximum_bytes=190000):
    parts=[];current=[];size=0
    for char in text:
        width=len(char.encode())
        if size+width>maximum_bytes:
            parts.append(''.join(current));current=[];size=0
        current.append(char);size+=width
    if current:parts.append(''.join(current))
    if ''.join(parts)!=text:raise ValueError('Exact original request reconstruction failed')
    return parts


def delivery(root, folder, task, transport=None, correction=None, *, failed_output=False):
    from .unity_m_judge import retained, RESERVE, WINDOW
    from . import unity_m_runtime_reuse as reuse
    if transport and transport.get("version")==reuse.VERSION:
        return reuse.delivery(root,folder,task,transport,correction,failed_output=failed_output)
    from .gameness_v4_persistent_text import session_path
    from .gameness_v4_persistent_capacity import telemetry
    from .native_image_cli_probe import retained_images
    root, folder = Path(root), Path(folder)
    common=batch.read(root/'unity_m_common_request.json')
    parent=root/'model_calls/unity_m_original_intake'
    inv=batch.read(folder/'invocation.json');snapshot=folder/'retained_session.jsonl'
    if not snapshot.exists():snapshot.write_bytes(session_path(inv['thread']).read_bytes())
    fork_folder=Path(transport['chunk_folders'][0]) if transport else Path(correction['original_folder']) if correction else folder
    inheritance=exact_fork(parent,fork_folder,snapshot)
    pixels=retained_images(parent/'retained_session.jsonl',common['prompt'],[Path(p) for p in common['images']])
    expected=(runtime_prompts(transport)+[transport['final_prompt']]) if transport else [task['prompt']]
    if correction:
        from .unity_m_output_recovery import resolve
        resolved,qualified=resolve(root,task)
        if resolved!=folder or qualified!=correction:raise ValueError('Qualified exact correction required')
        original_inv=batch.read(Path(correction['original_folder'])/'invocation.json')
        if original_inv['thread']!=inv['thread']:raise ValueError('Correction must retain the same complete conversation')
        expected=expected+correction.get('prior_prompts',[])+[correction['prompt']]
    environment_proof=None
    if text_inputs(rows(snapshot))!=expected:
        if not correction or transport:
            raise ValueError('Every exact original runtime prompt must be retained once in order')
        from .unity_m_resume_context import verify_inputs
        environment_proof=verify_inputs(folder,Path(correction['original_folder']),expected)
    for prompt in expected:retained_images(snapshot,prompt,[])
    data=rows(snapshot)
    completed=[v['payload'].get('turn_id') for v in data if v.get('payload',{}).get('type')=='task_complete']
    if failed_output:
        from .unity_m_incomplete_recovery import validate_failed
        if validate_failed(folder)!=inv:raise ValueError('Exact failed output turn required')
    elif not completed or completed[-1]!=inv['turn']:raise ValueError('Final completed turn changed')
    if transport:
        if ''.join(transport['chunks'])!=task['prompt']:raise ValueError('Runtime exact inverse failed')
        for chunk_folder,chunk_prompt in zip(transport['chunk_folders'],transport['chunk_prompts']):
            original=Path(chunk_folder);f=qualified_ack(original);v=batch.read(f/'invocation.json')
            if (v['thread']!=inv['thread'] or v['turn'] not in completed
                    or (original/'prompt.txt').read_text()!=chunk_prompt
                    or batch.read(f/'response.json')!={'receipt':'EXACT_RUNTIME_CHUNK_RETAINED'}):
                raise ValueError('Complete ordered runtime intake acknowledgment required')
    usage=telemetry(snapshot)[-1]
    if usage['input_tokens']+usage['output_tokens']+RESERVE>min(WINDOW,usage['window']):
        raise ValueError('Actual retained final context exceeds bounded reserve')
    from .unity_m_numeric_recovery import verify_task
    numeric_proof=verify_task(root,task)
    return dict(**({'resume_environment':environment_proof} if environment_proof is not None else {}),
                **({'numeric_event_delivery':numeric_proof} if numeric_proof is not None else {}),
                session_sha256=sha(snapshot),pixels=pixels,usage=usage,no_compaction=True,
                inheritance=inheritance,validation_manifest_sha256=hashlib.sha256(
                    json.dumps(validation_manifest(root,task),sort_keys=True).encode()).hexdigest(),
                original_manifest_sha256=sha(root/'evidence_manifest.json'),
                exact_original_runtime_text=True)


def runtime_request(root, task, parent_thread, parent_turn, intake_proof):
    """Only never-submitted oversized tasks enter this bounded retained route."""
    from .unity_m_judge import exact_json, WINDOW, RESERVE, MARGIN
    from .native_image_cli_probe import rpc_invoke
    from .gameness_v4_persistent_text import session_path
    from .gameness_v4_persistent_capacity import telemetry
    from .unity_m_runtime_reuse import prepare as reuse_runtime
    reused=reuse_runtime(root,task)
    if reused:return reused,reused['source_runtime']['thread']
    root=Path(root);path=root/'unity_m_runtime_transport'/(task['name']+'.json')
    parts=split_exact(task['prompt']);digest=hashlib.sha256(task['prompt'].encode()).hexdigest()
    literal_receipt=not path.exists() or batch.read(path).get('receipt_instruction_version')=='literal-v1'
    receipt_instruction=('Return exactly {"receipt":"EXACT_RUNTIME_CHUNK_RETAINED"}.' if literal_receipt else 'Return only the specified receipt.')
    prompts=[f'Non-scoring exact runtime intake, chunk {n+1}/{len(parts)}, complete original request SHA256 {digest}. '
             'Retain every character in order, do not summarize, compact, judge or call tools. '
             'After all chunks the complete original request and original output schema govern judgment. '
             +receipt_instruction+'\nBEGIN EXACT CHUNK\n'+part+'\nEND EXACT CHUNK'
             for n,part in enumerate(parts)]
    folders=[str(root/'model_calls'/('unity_m_'+task['name']+f'_runtime_{n+1:02d}')) for n in range(len(parts))]
    final=('All runtime chunks now form the complete original judgment request SHA256 '+digest+
           '. Execute that complete request, using all retained original author sources and original native frames. '
           'The unchanged structured output schema is supplied now. Do not call tools or omit evidence. '
           'Evaluate only the criteria named by the output schema; the full frozen contract remains context.')
    transport=dict(original_request_sha256=sha(root/'unity_m_requests'/task['column']/(task['name']+'.json')),
                   chunks=parts,chunk_prompts=prompts,chunk_folders=folders,final_prompt=final,
                   maximum_chunk_bytes=190000,maximum_new_calls=len(parts)+1)
    if literal_receipt:transport['receipt_instruction_version']='literal-v1'
    exact_json(path,transport)
    thread=parent_thread;usage=intake_proof['usage']
    schema=codex.obj({'receipt':{'type':'string','enum':['EXACT_RUNTIME_CHUNK_RETAINED']}})
    for n,(f,prompt) in enumerate(zip(folders,prompts)):
        f=Path(f)
        required=usage['input_tokens']+usage['output_tokens']+len(prompt.encode())+len(json.dumps(schema).encode())+RESERVE+MARGIN
        if required>min(WINDOW,usage['window']):raise ValueError('Bounded runtime intake capacity exceeded')
        if f.exists():
            if not (f/'response.json').exists():raise ValueError('Preserved runtime failure requires substantive repair')
            inv=batch.read(f/'invocation.json');response=batch.read(f/'response.json')
            if (f/'prompt.txt').read_text()!=prompt or batch.read(f/'schema.json')!=schema:raise ValueError('Runtime request drift')
            thread=inv['thread']
        else:
            response,thread=rpc_invoke(f,root,prompt,schema,[],model='gpt-6.1-sol',session=thread,
                                      fork_through=parent_turn if n==0 else None,context_window=WINDOW)
        try:codex.validate_schema(response,schema)
        except ValueError:
            if any((Path(other)/'receipt_correction.json').exists() for other in folders if Path(other)!=f):
                raise ValueError('At most one receipt correction per runtime group')
            f=recover_final_ack(root,Path(folders[0]),f,prompts[:n+1],schema)
            response=batch.read(f/'response.json');thread=batch.read(f/'invocation.json')['thread']
            codex.validate_schema(response,schema)
        snapshot=f/'retained_session.jsonl'
        if not snapshot.exists():snapshot.write_bytes(session_path(thread).read_bytes())
        exact_fork(root/'model_calls/unity_m_original_intake',Path(folders[0]),snapshot)
        if text_inputs(rows(snapshot))!=runtime_prompts(transport,limit=n+1):raise ValueError('Exact ordered runtime chunks required')
        usage=telemetry(snapshot)[-1]
        exact_json(f/'accepted_intake.json',dict(response=response,session_sha256=sha(snapshot),usage=usage))
    from .unity_m_schema_recovery import initial_schema
    submitted=initial_schema(root,task)
    required=usage['input_tokens']+usage['output_tokens']+len(final.encode())+len(json.dumps(submitted).encode())+RESERVE+MARGIN
    if required>min(WINDOW,usage['window']):raise ValueError('Measured complete runtime plus final schema exceeds window')
    return transport,thread


def qualify_producer(root, current, repair_path):
    """Explicit, exact-parent continuation; immutable original producer survives."""
    from .unity_m_judge import exact_json
    root=Path(root);original=root/'unity_m_judge_producer.json'
    if not original.exists() or batch.read(original)==current:
        exact_json(original,current);return
    if repair_path is None:raise ValueError('Exact producer continuation required after substantive repair')
    repair=batch.read(repair_path)
    if (repair.get('parent_producer_sha256')!=sha(original) or repair.get('after_producer')!=current
            or repair.get('classification')!='NON_SCORING_TRANSPORT_AND_METADATA_REPAIR'):
        raise ValueError('Exact original/current producer repair required')
    before=batch.read(original)['production'];after=current['production']
    changed={p for p in set(before)|set(after) if before.get(p)!=after.get(p)}
    if changed!=set(repair['changed_files']):raise ValueError('Complete producer delta required')
    for p in changed:
        old=repair['changed_files'][p]
        if p in before and (not old or sha(Path(old['archive']))!=before[p]):raise ValueError('Exact old producer bytes required')
        if p not in before and old is not None:raise ValueError('New dependency must be explicit')
    for p,d in repair['parent_failure_bindings'].items():
        if sha(Path(p))!=d:raise ValueError('Parent failure changed')
    if not repair['parent_failure_bindings']:raise ValueError('Actual parent failure required')
    regression=Path(repair['regression']['path'])
    if sha(regression)!=repair['regression']['sha256'] or batch.read(regression).get('exit_code')!=0:
        raise ValueError('Passing targeted regression required')
    continuation=dict(repair_path=str(Path(repair_path).resolve()),repair_sha256=sha(Path(repair_path)),
                      parent_producer_sha256=sha(original),after_producer=current)
    first=root/'unity_m_judge_continuation.json'
    if first.exists() and batch.read(first)!=continuation:
        previous=repair.get('parent_continuation',{})
        if previous.get('path')!=str(first) or previous.get('sha256')!=sha(first):
            raise ValueError('Preserve and bind exact prior continuation')
        exact_json(root/'unity_m_judge_continuations'/(sha(Path(repair_path))+'.json'),continuation)
    else:exact_json(first,continuation)


ACK_PROMPT = ('Non-scoring receipt-format correction only. Your previous response used an invalid '
              'receipt enum. Keep all previously received original source, native images and exact '
              'runtime chunks unchanged in this same conversation. Do not repeat, summarize, judge '
              'or call tools. Acknowledge the last retained chunk by returning exactly '
              '{"receipt":"EXACT_RUNTIME_CHUNK_RETAINED"}. No score is requested.')


def qualified_ack(original):
    """Resolve a single preserved correction; never rewrite the failed response."""
    original=Path(original);descriptor=original/'receipt_correction.json'
    if not descriptor.exists():return original
    value=batch.read(descriptor);folder=original.parent/(original.name+'_receipt_01')
    if (value.get('maximum_new_calls')!=1 or value.get('prompt')!=ACK_PROMPT
            or value.get('folder')!=str(folder)):
        raise ValueError('Bounded receipt correction descriptor changed')
    for p,d in value['bindings'].items():
        if sha(Path(p))!=d:raise ValueError('Original receipt failure binding changed')
    if not (folder/'response.json').exists():raise ValueError('Preserved receipt correction failed; no unchanged retry')
    if ((folder/'prompt.txt').read_text()!=ACK_PROMPT
            or batch.read(folder/'schema.json')!=batch.read(original/'schema.json')
            or batch.read(folder/'invocation.json')['thread']!=batch.read(original/'invocation.json')['thread']):
        raise ValueError('Receipt correction must preserve original schema and conversation')
    codex.validate_schema(batch.read(folder/'response.json'),batch.read(original/'schema.json'))
    return folder


def runtime_prompts(transport,limit=None):
    expected=[]
    for folder,prompt in list(zip(transport['chunk_folders'],transport['chunk_prompts']))[:limit]:
        expected.append(prompt)
        if (Path(folder)/'receipt_correction.json').exists():
            qualified_ack(folder);expected.append(ACK_PROMPT)
    return expected


def recover_final_ack(root, first, failed, prompts, schema):
    from .unity_m_judge import exact_json, WINDOW, RESERVE, MARGIN
    from .native_image_cli_probe import rpc_invoke, retained_images
    from .gameness_v4_persistent_text import session_path
    from .gameness_v4_persistent_capacity import telemetry
    descriptor=failed/'receipt_correction.json'
    if descriptor.exists():return qualified_ack(failed)
    response=batch.read(failed/'response.json');inv=batch.read(failed/'invocation.json')
    if (set(response)!={'receipt'} or type(response['receipt']) is not str
            or response['receipt']=='EXACT_RUNTIME_CHUNK_RETAINED'):
        raise ValueError('Only non-scoring receipt enum failure is recoverable')
    snapshot=failed/'retained_session.jsonl'
    if not snapshot.exists():snapshot.write_bytes(session_path(inv['thread']).read_bytes())
    exact_fork(root/'model_calls/unity_m_original_intake',first,snapshot)
    data=rows(snapshot)
    if text_inputs(data)!=prompts:raise ValueError('Complete exact chunks required before receipt correction')
    completed=[r['payload'].get('turn_id') for r in data if r.get('payload',{}).get('type')=='task_complete']
    if not completed or completed[-1]!=inv['turn']:raise ValueError('Receipt failure must be a completed transport turn')
    for prompt in prompts:retained_images(snapshot,prompt,[])
    usage=telemetry(snapshot)[-1]
    required=usage['input_tokens']+usage['output_tokens']+len(ACK_PROMPT.encode())+len(json.dumps(schema).encode())+RESERVE+MARGIN
    if required>min(WINDOW,usage['window']):raise ValueError('Receipt correction exceeds retained capacity')
    folder=failed.parent/(failed.name+'_receipt_01')
    if folder.exists():raise ValueError('Unqualified receipt correction already exists')
    bindings={str(failed/n):sha(failed/n) for n in ('response.json','prompt.txt','schema.json','invocation.json','rpc_requests.jsonl','rpc_events.jsonl','retained_session.jsonl')}
    exact_json(descriptor,dict(maximum_new_calls=1,prompt=ACK_PROMPT,folder=str(folder),bindings=bindings,required=required))
    rpc_invoke(folder,root,ACK_PROMPT,schema,[],model='gpt-6.1-sol',session=inv['thread'],context_window=WINDOW)
    return qualified_ack(failed)
