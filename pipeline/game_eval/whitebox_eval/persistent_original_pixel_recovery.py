"""Bounded source-preserving fork recovery for an actual native-pixel defect.

Each independent judge forks only through the final successful non-scoring
intake. The failed final turn remains in the parent. No source, image, schema,
criterion, old claim, accepted result or old publication is overwritten.
"""
from pathlib import Path
import argparse
import copy
import contextvars
import os
import fcntl
import hashlib
import json
import time
from . import mechanic_v3_runner as runner, mechanic_v3_execution as execution
from . import mechanic_v3_persistent_text as mechanic
from . import gameness_v4_persistent_text as transport
from . import native_image_cli_probe as native
from . import evaluation_model_profile as models, codex
from .protocol import dump, sha

VERSION = 'whitebox-persistent-original-pixel-recovery.v1'
AUTH = 'engineering/persistent_original_pixel_recovery.json'
FORK_AUDIT = 'engineering/original_pixel_fork_audit_continuation.json'
FINAL_CAPACITY = 'engineering/original_pixel_final_capacity_continuation.json'
CAPACITY_SCHEMA = 'engineering/original_pixel_capacity_schema_continuation.json'
TOKEN_CAPACITY = 'engineering/original_pixel_token_capacity_continuation.json'
ACCEPTED_AUDIT = 'engineering/original_pixel_accepted_audit_continuation.json'
ACCEPTED_HISTORY = 'engineering/original_pixel_accepted_producer_history.json'
MARKER = 'persistent_original_pixel_recovery'
COMPLETED_HISTORY = 'engineering/original_pixel_completed_producer_history.json'
PUBLISHED_FINAL = 'engineering/original_pixel_published_final_capacity.json'
OUTPUT_CONSISTENCY = 'engineering/original_pixel_frozen_output_continuation.json'
NESTED_ROOT = 'engineering/original_pixel_nested_root_continuation.json'
SOURCE_REPACK = 'engineering/original_pixel_source_repack_continuation.json'
SOURCE_INTAKE = 'engineering/original_pixel_source_repack_intake.json'
_READONLY_PRODUCTION = contextvars.ContextVar('original_pixel_readonly_production', default=None)
_READONLY_ARCHIVES = contextvars.ContextVar('original_pixel_readonly_archives', default={})


def production():
    from .gameness_v3_runtime import production_bindings
    return _READONLY_PRODUCTION.get() or production_bindings()


def bound(path):
    return {'path':str(Path(path).resolve()),'sha256':sha(Path(path))}


def verify_binding(value):
    path=Path(value['path'])
    if sha(path)!=value['sha256']:raise ValueError('Immutable recovery binding changed: '+str(path))
    return path


def rows(path):
    for line in Path(path).read_text().split('\n'):
        if line.strip():yield json.loads(line)


def intake_boundary(path, prompts, model):
    """Find the completed turn containing the last literal source intake."""
    turns=[];current=None;messages=[];complete=set()
    for value in rows(path):
        p=value.get('payload',{});kind=value.get('type')
        if 'compact' in (str(kind)+' '+str(p.get('type',''))).lower():
            raise ValueError('A compacted parent cannot supply original source context')
        if kind=='turn_context':
            current=p['turn_id'];turns.append((current,p.get('model')))
        if kind=='response_item' and p.get('type')=='message' and p.get('role')=='user':
            for v in p.get('content',[]):
                if v.get('type') in {'text','input_text'} and v.get('text') in prompts:
                    messages.append((v['text'],current))
        if kind=='event_msg' and p.get('type')=='task_complete':complete.add(p['turn_id'])
    if [x[0] for x in messages]!=prompts or any(m!=model for _,m in turns):
        raise ValueError('Every original intake must occur exactly once in order with the frozen model')
    turn=messages[-1][1]
    if turn not in complete:raise ValueError('Fork boundary is not a completed original intake')
    return turn


def original(root, column, repair=None):
    path=root/(transport.AUTH if column=='Gameness' else mechanic.AUTH)
    if repair is None and (root/AUTH).exists():
        repair=runner.read(verify_binding(runner.read(root/AUTH)['repair']))
    if repair and repair.get('published_descendant'):
        if column!='Gameness':raise ValueError('Accepted descendant locator is Gameness-only')
        path=verify_published_descendant(root,repair)
    return path,runner.read(path)


def verify_published_descendant(root, repair):
    """Locate only the actual accepted published child, preserving its full source.

    No old authorization is edited or reissued. The original publication must
    bind the child's judgment and accepted bytes; all ordinary pixel-recovery
    checks, intake ACKs, retained-history and capacity gates remain mandatory.
    """
    value=repair['published_descendant'];history=repair['published_history']
    base_path=verify_binding(value['base_authorization'])
    path=verify_binding(value['authorization'])
    allowed={'gameness_persistent_capacity_continuation.json',
        'gameness_sequential_complete_source.json','gameness_sequential_context_continuation.json'}
    if (value.get('version')!='original-pixel-accepted-gameness-descendant.v1'
            or base_path!=root/transport.AUTH or path.parent!=root/'engineering'
            or path.name not in allowed or value.get('parent_publication')!=history['parent_publication']
            or value.get('maximum_attempts_unchanged') is not True):
        raise ValueError('Exact published descendant authorization and original parent required')
    base=runner.read(base_path);auth=runner.read(path)
    parent=runner.read(verify_binding(history['parent_publication']))
    for field in ['identity','original_body_sha256','evidence_set','criterion_ids']:
        if auth.get(field)!=base.get(field):raise ValueError('Descendant changed frozen source or criteria')
    if auth.get('identity')!=root.name or not auth.get('task') or auth['task']==base['task']:
        raise ValueError('A distinct same-identity accepted descendant required')
    # Sequential children pin their original parent explicitly; capacity children
    # pin the original authorization in bindings and identify its exact task.
    parent_auth=auth.get('parent_authorization')
    if parent_auth:
        previous=runner.read(verify_binding(parent_auth))
        if previous['task']!=auth['parent_task'] or previous['identity']!=root.name:
            raise ValueError('Exact sequential parent authorization required')
        if previous!=base:
            if (previous.get('parent_task')!=base['task']
                    or previous.get('bindings',{}).get(str(base_path))!=sha(base_path)):
                raise ValueError('Descendant must lead to the pinned original authorization')
    elif (auth.get('parent_task')!=base['task']
            or auth.get('bindings',{}).get(str(base_path))!=sha(base_path)):
        raise ValueError('Exact capacity parent authorization required')
    name=auth['task'];call=root/'model_calls'/name
    judgment=root/'judgments'/(name+'.json');accepted=call/'accepted_response.json'
    required=[judgment,accepted,call/'response.json',call/'actual_delivery.json',
        call/'prompt.txt',call/'schema.json']
    if any(parent.get('bindings',{}).get(str(p))!=sha(p) for p in required):
        raise ValueError('Published parent must bind every actual accepted child artifact')
    artifact=runner.read(judgment);result=runner.read(verify_binding(history['parent_score']))
    marker=runner.read(accepted)
    if (artifact.get('task')!=name or artifact.get('checks')!=result.get('checks')
            or marker.get('path')!='response.json' or marker.get('sha256')!=sha(call/'response.json')):
        raise ValueError('Exact complete published accepted descendant judgment required')
    return path


def verify_old_auth(root, auth_path, auth, repair):
    """No global drift exemption: every old byte has an exact pinned archive."""
    code=Path(__file__).resolve().parent
    for name,expected in auth['bindings'].items():
        p=Path(name)
        if sha(p)==expected:continue
        archive=repair.get('original_producer_archives',{}).get(name) or _READONLY_ARCHIVES.get().get(name,{}).get('path')
        if p.parent!=code or not archive or sha(Path(archive))!=expected:
            raise ValueError('Exact original producer or original evidence required: '+name)
    if models.model_for(root,'judge')!='gpt-6.1-sol':
        raise ValueError('This bounded capability only qualifies the frozen Sol judge')


def verify_nested_root(root):
    """A pinned owner/score locator, never a copied scope or new delivery."""
    root=Path(root).resolve();value=runner.read(root/NESTED_ROOT)
    workspace=Path(value['workspace']).resolve()
    repair_path=verify_binding(value['repair']);repair=runner.read(repair_path)
    history=repair.get('published_history',{})
    parent=runner.read(verify_binding(history['parent_publication']))
    score=verify_binding(history['parent_score']).resolve()
    relative=root.relative_to(workspace) if root.is_relative_to(workspace) else Path('.')
    parts=relative.parts
    producer=str(Path(__file__).resolve());before=value['before_source_bindings'];after=production()
    changed={p for p in set(before)|set(after) if before.get(p)!=after.get(p)}
    if (value.get('version')!='original-pixel-nested-root-continuation.v1'
            or value.get('root')!=str(root) or value.get('identity')!=root.name
            or value.get('column')!='Mechanic' or repair.get('column')!='Mechanic'
            or repair.get('identity')!=root.name or parent.get('identity')!=root.name
            or parent.get('status')!='SCORED_PENDING_AUDIT'
            or Path(parent['score_file']).resolve()!=score or score.parent!=root
            or history.get('version')!='original-pixel-published-parent.v1'
            or history['prior_column']['workspace']!=str(workspace)
            or history['prior_column']['publication_sha256']!=history['parent_publication']['sha256']
            or len(parts)!=5 or parts[0]!='prerecord_recovery' or parts[1]!=root.name
            or len(parts[2])!=64 or any(c not in '0123456789abcdef' for c in parts[2])
            or parts[3:]!=('runs',root.name)
            or before!=repair['after_source_bindings'] or value.get('after_source_bindings')!=after
            or changed!={producer} or sha(verify_binding(value['old_producer']))!=before[producer]
            or value.get('maximum_attempts_unchanged') is not True or value.get('scope_copied') is not False):
        raise ValueError('Exact nested original score, owner and producer continuation required')
    for item in value['owner_bindings']:
        path=verify_binding(item)
        if not path.resolve().is_relative_to(workspace):raise ValueError('Owner binding escaped workspace')
    if not value['owner_bindings']:raise ValueError('Frozen owner bindings required')
    reg=runner.read(verify_binding(value['regression']))
    if reg.get('exit_code')!=0 or reg.get('tests_passed',0)<1:
        raise ValueError('Passed nested-root regressions required')
    return value


def context_workspace(workspace,root):
    if (Path(root)/NESTED_ROOT).exists():
        locator=runner.read(Path(root)/NESTED_ROOT)
        # A completed-only audit supplies precisely this locator's old producer.
        if _READONLY_PRODUCTION.get()==locator['after_source_bindings']:
            return Path(verify_nested_root(root)['workspace'])
        token=_READONLY_PRODUCTION.set(None)
        try:return Path(verify_nested_root(root)['workspace'])
        finally:_READONLY_PRODUCTION.reset(token)
    return Path(workspace)


def resolve_run_root(workspace,identity,column,repair_path):
    workspace=Path(workspace).resolve();repair=runner.read(repair_path)
    if not repair.get('published_history'):return workspace/'runs'/identity
    history=repair['published_history'];parent=runner.read(verify_binding(history['parent_publication']))
    if history['prior_column']['workspace']!=str(workspace) or parent.get('identity')!=identity:
        raise ValueError('Publication owner and requested identity must match')
    root=Path(parent['score_file']).resolve().parent
    if root==workspace/'runs'/identity:return root
    if column!='Mechanic':raise ValueError('Nested root route is independently Mechanic-only')
    value=verify_nested_root(root)
    if value['repair']!=bound(repair_path) or value['workspace']!=str(workspace):
        raise ValueError('Exact nested repair and owner required')
    return root


def context(workspace, root, column, auth, task):
    workspace=context_workspace(workspace,root)
    if column=='Gameness':
        if (Path(root)/SOURCE_REPACK).exists():
            repack=verify_source_repack(root)
            auth=dict(auth,literal_transport=repack['literal_transport'])
        values=transport.packet(workspace,root,auth,persist=False)
        proto,specs,selected,rules,contract,review,body,images,schema,prompt,actual=values
        wire_parts=transport.delivery_parts(auth,body)
        expanded=prompt+'\nCOMPLETE ORIGINAL RETAINED CONTEXT:\n'+body
    else:
        values=mechanic.packet(workspace,root,auth,task,persist=False)
        proto,specs,selected,rules,contract,images,schema,prompt,body,wire,actual=values
        wire_parts=transport.parts(wire);review=None
        expanded=prompt.replace('PERSISTENT_COMPLETE_BODY_SHA256 '+mechanic.digest(body),body,1)
    return dict(proto=proto,specs=specs,selected=selected,rules=rules,contract=contract,
        review=review,body=body,images=images,schema=schema,prompt=prompt,actual=actual,
        wire_parts=wire_parts,
        intake_prompts=[transport.chunk_prompt(i,len(wire_parts),v) for i,v in enumerate(wire_parts,1)],expanded=expanded)


def verify_fork_audit_continuation(root, repair_path, repair, *, expected_production=None):
    """Only resume the exact successful capacity ACK after a local audit defect."""
    value=runner.read(root/FORK_AUDIT)
    if (value.get('version')!='original-pixel-fork-audit-continuation.v1'
            or value.get('authorization')!=bound(root/AUTH)
            or value.get('repair')!=bound(repair_path)
            or value.get('after_source_bindings')!=(expected_production or production())):
        raise ValueError('Exact fork-audit continuation required')
    before=repair['after_source_bindings'];after=value['after_source_bindings']
    changed={name for name in set(before)|set(after) if before.get(name)!=after.get(name)}
    current=str(Path(__file__).resolve())
    if changed!={current} or sha(verify_binding(value['old_producer']))!=before[current]:
        raise ValueError('Only the exact fork-audit producer may change')
    if runner.read(verify_binding(value['regression'])).get('exit_code')!=0:
        raise ValueError('Passed fork-audit regression required')
    failure=runner.read(verify_binding(value['parent_failure']))
    if failure.get('error')!="ValueError('Every complete original prompt must occur once in the same conversation in order')":
        raise ValueError('Exact local fork-audit failure required')
    for item in value['accepted_capacity_bindings']:verify_binding(item)
    return value


def verify_fork_session(root, task, folder, c, prompt):
    """Audit paginated retained history without manufacturing a session log.

    The child's history_base selects exact parent bytes. The RPC fork response
    must independently expose precisely the completed original intake turns.
    """
    snapshot=verify_binding(task['parent_snapshot']);raw=snapshot.read_bytes()
    inv=runner.read(folder/'invocation.json');session=folder/'persistent_session.jsonl'
    child=list(rows(session));metas=[v['payload'] for v in child if v.get('type')=='session_meta']
    if len(metas)!=1:raise ValueError('One exact child history metadata required')
    meta=metas[0];history=meta.get('history_base',{});cut=history.get('end_byte_offset')
    if (meta.get('forked_from_id')!=task['parent_session'] or history.get('thread_id')!=task['parent_session']
            or not isinstance(cut,int) or not 0<cut<=len(raw) or raw[cut-1:cut]!=b'\n'):
        raise ValueError('Exact parent byte boundary required')
    prefix=[json.loads(v) for v in raw[:cut].decode().split('\n') if v.strip()]
    if (history.get('end_ordinal_exclusive')!=meta.get('forked_from_ordinal_exclusive')
            or not prefix or prefix[-1].get('ordinal')!=history.get('end_ordinal_exclusive')-1
            or prefix[-1].get('payload',{}).get('type')!='task_complete'
            or prefix[-1]['payload'].get('turn_id')!=task['fork_through']):
        raise ValueError('Fork must end at the exact completed source intake')
    prompts=[];turns=[]
    for v in prefix:
        payload=v.get('payload',{});kind=v.get('type')
        if 'compact' in (str(kind)+' '+str(payload.get('type',''))).lower():
            raise ValueError('Compacted inherited history forbidden')
        if kind=='turn_context':
            if payload.get('model')!='gpt-6.1-sol':raise ValueError('Inherited model changed')
            turns.append(payload['turn_id'])
        if kind=='response_item' and payload.get('type')=='message' and payload.get('role')=='user' and turns:
            prompts.extend(v['text'] for v in payload['content'] if v.get('type') in {'text','input_text'})
    if prompts!=c['intake_prompts']:raise ValueError('Every inherited source prompt must occur once exactly')
    fork_requests=[v for v in rows(folder/'rpc_requests.jsonl') if v.get('method')=='thread/fork']
    if len(fork_requests)!=1:raise ValueError('One exact fork request required')
    responses=[v for v in rows(folder/'rpc_events.jsonl') if v.get('id')==fork_requests[0]['id']]
    if len(responses)!=1:raise ValueError('One actual fork response required')
    thread=responses[0].get('result',{}).get('thread',{});actual_turns=thread.get('turns',[])
    texts=[v['text'] for t in actual_turns for i in t.get('items',[]) if i.get('type')=='userMessage'
           for v in i.get('content',[]) if v.get('type')=='text']
    if (thread.get('id')!=inv['thread'] or thread.get('forkedFromId')!=task['parent_session']
            or [t.get('id') for t in actual_turns]!=turns or texts!=c['intake_prompts']
            or any(t.get('status')!='completed' for t in actual_turns)):
        raise ValueError('Actual RPC fork must retain exactly the original successful source turns')
    child_proof=transport.verify_session(session,inv['thread'],[prompt],'gpt-6.1-sol')
    return dict(parent_snapshot=task['parent_snapshot'],parent_prefix_bytes=cut,
        parent_prefix_sha256=hashlib.sha256(raw[:cut]).hexdigest(),inherited_turns=turns,
        original_user_prompt_sha256=task['intake_prompt_sha256'],child=child_proof,
        rpc_events=bound(folder/'rpc_events.jsonl'),no_compaction=True)


def encode_final_literal(text):
    """Readable nonrecursive dictionary; inverse retains every original character."""
    import re
    from collections import Counter
    from .gameness_v4_persistent_literal import _flat_inverse
    initial=next((v for v in ['¤','§','‖','※'] if v not in text),None)
    if initial is None:raise ValueError('No unambiguous reserved literal initial')
    words=re.findall(r'\w+|[^\w]',text);candidates=Counter()
    for width in [4,8,16,32,64]:
        for offset in range(len(words)-width+1):
            value=''.join(words[offset:offset+width])
            if 24<=len(value)<=4096:candidates[value]+=1
    ranked=sorted((v for v,n in candidates.items() if n>=3),
        key=lambda v:(candidates[v]-1)*len(v)-candidates[v]*5,reverse=True)
    template=text;dictionary={}
    for value in ranked:
        count=template.count(value)
        if count<3 or (count-1)*len(value)-count*5-30<=0:continue
        key=initial+format(len(dictionary),'03x');dictionary[key]=value
        template=template.replace(value,key)
        if len(dictionary)>=256:break
    wire=json.dumps(dict(dictionary=dictionary),ensure_ascii=False,separators=(',',':'))+'\nTEMPLATE\n'+template
    if _flat_inverse(wire,nested=True)!=text:raise ValueError('Every original final character must be recoverable')
    return wire



def optimize_final_literal(text):
    """Exact readable dictionary; local tokenizer estimates never grant capacity.

    Single-character keys cannot occur anywhere in the original. Token-aware
    selection avoids replacing cheap whitespace with more costly dictionary
    entries. The inverse, real native-pixel probe and frozen gate remain final.
    """
    import re
    import unicodedata
    from collections import Counter
    import tiktoken
    from .gameness_v4_persistent_literal import _flat_inverse
    enc=tiktoken.get_encoding('o200k_base')
    cost=lambda v:len(enc.encode(v,disallowed_special=()))
    symbols=[]
    for n in range(0xa1,0xa000):
        ch=chr(n)
        if ch not in text and unicodedata.category(ch)[0] in 'LNPS' and cost(ch)==1:
            symbols.append(ch)
            if len(symbols)==1024:break
    if len(symbols)<16:raise ValueError('Unambiguous readable literal keys required')
    words=re.findall(r'\w+|[^\w]',text);counts=Counter()
    for width in [2,3,4,6,8,12,16,24,32,48,64,96,128]:
        for offset in range(len(words)-width+1):
            phrase=''.join(words[offset:offset+width])
            if 8<=len(phrase)<=4096:counts[phrase]+=1
    ranked=sorted((v for v,n in counts.items() if n>=2),key=lambda v:(counts[v]-1)*len(v),reverse=True)[:20000]
    costs={v:cost(v) for v in ranked}
    ranked.sort(key=lambda v:(counts[v]-1)*costs[v]-counts[v]-5,reverse=True)
    template=text;dictionary={}
    for phrase in ranked:
        count=template.count(phrase)
        if count<2 or (count-1)*costs[phrase]-count-5<=0:continue
        key=symbols[len(dictionary)];dictionary[key]=phrase;template=template.replace(phrase,key)
        if len(dictionary)==len(symbols):break
    wire=json.dumps(dict(dictionary=dictionary),ensure_ascii=False,separators=(',',':'))+'\nTEMPLATE\n'+template
    if _flat_inverse(wire,nested=True)!=text:raise ValueError('Exact final literal inverse failed')
    return wire


def verify_final_capacity_continuation(root,repair_path,repair,*,expected_production=None):
    value=runner.read(root/FINAL_CAPACITY)
    if (value.get('version')!='original-pixel-exact-final-capacity.v1'
            or value.get('authorization')!=bound(root/AUTH) or value.get('repair')!=bound(repair_path)
            or value.get('after_source_bindings')!=(expected_production or production())
            or value.get('maximum_new_capacity_calls_per_task')!=1):
        raise ValueError('Exact substantive final-capacity continuation required')
    prior=runner.read(verify_binding(value['fork_audit_continuation']))
    verify_fork_audit_continuation(root,repair_path,repair,expected_production=prior['after_source_bindings'])
    before=prior['after_source_bindings'];after=value['after_source_bindings'];current=str(Path(__file__).resolve())
    if ({k for k in set(before)|set(after) if before.get(k)!=after.get(k)}!={current}
            or sha(verify_binding(value['old_producer']))!=before[current]):
        raise ValueError('Only exact final literal recovery producer may change')
    failure=runner.read(verify_binding(value['parent_failure']))
    gate=runner.read(verify_binding(value['parent_capacity_gate']))
    if ('Original-pixel complete final capacity insufficient' not in failure.get('error','')
            or gate.get('passed') is not False or gate['required_with_output_and_margin']<=gate['window']):
        raise ValueError('Measured real complete-original-pixel capacity failure required')
    if runner.read(verify_binding(value['regression'])).get('exit_code')!=0:
        raise ValueError('Passed exact-final capacity regression required')
    return value



def verify_capacity_schema_continuation(root,repair_path,repair,*,expected_production=None):
    """One changed inert schema, exact failed calls; original judge is unchanged."""
    value=runner.read(root/CAPACITY_SCHEMA)
    if (value.get('version')!='original-pixel-capacity-schema-defs.v1'
            or value.get('authorization')!=bound(root/AUTH) or value.get('repair')!=bound(repair_path)
            or value.get('after_source_bindings')!=(expected_production or production())
            or value.get('maximum_new_capacity_calls_per_task')!=1
            or value.get('maximum_scoring_calls_per_task')!=1):
        raise ValueError('Exact bounded capacity-schema continuation required')
    before=value['before_source_bindings'];after=value['after_source_bindings'];current=str(Path(__file__).resolve())
    if ({k for k in set(before)|set(after) if before.get(k)!=after.get(k)}!={current}
            or sha(verify_binding(value['old_producer']))!=before[current]):
        raise ValueError('Only exact inert-capacity producer may change')
    if (root/FINAL_CAPACITY).exists():
        if value.get('prior_capacity_continuation')!=bound(root/FINAL_CAPACITY):
            raise ValueError('Exact previous final-capacity continuation required')
        verify_final_capacity_continuation(root,repair_path,repair,expected_production=before)
    elif before!=repair.get('after_source_bindings'):
        raise ValueError('Exact original pixel repair production required')
    if runner.read(verify_binding(value['regression'])).get('exit_code')!=0:
        raise ValueError('Passed strict probe schema regression required')
    auth=runner.read(root/AUTH);entries=value['tasks']
    if set(entries)!={t['task'] for t in auth['tasks']}:
        raise ValueError('Every independent task must retain its original bound identity')
    failures=0
    for name,info in entries.items():
        folder=root/'capacity_calls'/(name+'_exact_final')
        if info['state']=='FAILED_OPTIONAL_SCHEMA':
            if (info['invocation']!=bound(folder/'invocation.json')
                    or info['schema']!=bound(folder/'schema.json')
                    or info['request']!=bound(folder/'rpc_requests.jsonl')
                    or info['events']!=bound(folder/'rpc_events.jsonl')
                    or info['prompt']!=bound(folder/'prompt.txt')):
                raise ValueError('Every actual failed capacity artifact must remain exact')
            inv=runner.read(folder/'invocation.json');schema=runner.read(folder/'schema.json')
            if (inv.get('attempt')!=1 or inv.get('status')!='HARNESS_ERROR'
                    or inv.get('model_requested')!='gpt-6.1-sol'
                    or not any(s in inv.get('error','') for s in ['upstream_error','stream disconnected before completion'])
                    or (folder/'response.json').exists()
                    or schema.get('required')!=['transport_probe']
                    or set(schema.get('properties',{}))=={'transport_probe'}):
                raise ValueError('Real failed optional-schema probe without accepted response required')
            failures+=1
        elif info['state']=='NOT_SUBMITTED_SIBLING':
            if folder.exists():raise ValueError('Unsubmitted sibling capacity must never have been dispatched')
        else:raise ValueError('Unknown capacity task qualification')
    if failures<1:raise ValueError('At least one exact actual probe failure is required')
    return value


def accepted_audit_expected_production(root):
    """Keep completed accepted-only audit recoveries bound to their exact producer."""
    if not (root/ACCEPTED_HISTORY).exists():return production()
    value=runner.read(root/ACCEPTED_HISTORY)
    if (value.get('version')!='original-pixel-accepted-producer-history.v1'
            or value.get('authorization')!=bound(root/ACCEPTED_AUDIT)
            or value.get('after_source_bindings')!=production()
            or value.get('maximum_new_model_calls')!=0):
        raise ValueError('Exact completed audit producer history required')
    before=value['before_source_bindings'];after=value['after_source_bindings']
    current=str(Path(__file__).resolve())
    if (runner.read(root/ACCEPTED_AUDIT)['after_source_bindings']!=before
            or {n for n in set(before)|set(after) if before.get(n)!=after.get(n)}!={current}
            or sha(verify_binding(value['old_producer']))!=before[current]):
        raise ValueError('Only exact recovery-producer history may evolve')
    proof=runner.read(verify_binding(value['regression']))
    if proof.get('exit_code')!=0 or proof.get('tests_passed',0)<1:
        raise ValueError('Passed completed audit history regression required')
    acceptance=runner.read(verify_binding(value['real_acceptance']))
    if (acceptance.get('status')!='MECHANIC_ORIGINAL_PIXELS_REAL_E2E_ACCEPTED'
            or acceptance.get('production_bindings')!=before
            or acceptance.get('complete_original_sources_and_pixels') is not True):
        raise ValueError('Completed exact original-pixel Mechanic E2E required')
    return before


def accepted_audit_production(root):
    """Exact post-acceptance local audit repair; no new model calls are granted."""
    if not (root/ACCEPTED_AUDIT).exists():return production()
    value=runner.read(root/ACCEPTED_AUDIT)
    if (value.get('version')!='original-pixel-accepted-audit-continuation.v1'
            or value.get('authorization')!=bound(root/AUTH)
            or value.get('prior_token_continuation')!=bound(root/TOKEN_CAPACITY)
            or value.get('after_source_bindings')!=accepted_audit_expected_production(root)
            or value.get('maximum_new_model_calls')!=0):
        raise ValueError('Exact accepted-only audit continuation required')
    before=value['before_source_bindings'];after=value['after_source_bindings']
    prior=runner.read(root/TOKEN_CAPACITY)
    allowed={str(Path(__file__).resolve()),str(Path(__file__).with_name('mechanic_v3_delivery_audit_v3.py').resolve())}
    if (prior['after_source_bindings']!=before
            or {p for p in set(before)|set(after) if before.get(p)!=after.get(p)}!=allowed
            or set(value['old_producers'])!=allowed):
        raise ValueError('Only the exact accepted-prompt audit producers may change')
    for name,archive in value['old_producers'].items():
        if sha(verify_binding(archive))!=before[name]:raise ValueError('Exact pre-audit producer bytes required')
    failure=runner.read(verify_binding(value['parent_failure']))
    if failure.get('error')!="ValueError('Actual submitted prompt SHA differs')":
        raise ValueError('Exact post-acceptance prompt audit failure required')
    regression=runner.read(verify_binding(value['regression']))
    if regression.get('exit_code')!=0 or regression.get('tests_passed',0)<1:
        raise ValueError('Passed accepted-audit regressions required')
    auth=runner.read(root/AUTH)
    if set(value['accepted_tasks'])!={t['task'] for t in auth['tasks']}:
        raise ValueError('Every accepted independent task must be retained')
    for name,files in value['accepted_tasks'].items():
        call=root/'model_calls'/name;req=root/'requests'/name
        required={str(call/f) for f in ['prompt.txt','schema.json','response.json','invocation.json',
            'rpc_requests.jsonl','rpc_events.jsonl','persistent_session.jsonl','actual_delivery.json',
            'accepted_response.json','original_pixel_delivery_verified.json']}
        required|={str(req/f) for f in ['actual_delivery.json','complete_body.txt','expanded_prompt.txt',
            'intake_prompts.json','context_binding.json','selected_manifest.json']}
        required.add(str(root/'judgments'/(name+'.json')))
        if set(files)!=required:raise ValueError('Complete immutable accepted task proof required')
        for path,digest in files.items():
            if sha(Path(path))!=digest:raise ValueError('Accepted task artifact changed: '+path)
        artifact=runner.read(root/'judgments'/(name+'.json'))
        proof=runner.read(call/'original_pixel_delivery_verified.json')
        if (artifact.get('task')!=name or not artifact.get('checks')
                or proof.get('all_original_text_actually_delivered') is not True
                or proof.get('all_original_pixels_actually_delivered') is not True):
            raise ValueError('Only fully accepted original-text/native-pixel tasks may resume')
    return before


def verify_token_capacity_continuation(root,repair_path,repair):
    """One exact smaller wire after a measured complete-native-pixel overflow.

    This is a new transport representation, never an unchanged capacity retry.
    Every prior accepted ACK, failed gate and never-submitted sibling is pinned.
    Actual capacity must still pass before any one bounded scoring call.
    """
    from .gameness_v4_final_literal import ACK, NOTICE
    from .gameness_v4_persistent_capacity import OUTPUT_RESERVE, OVERHEAD_MARGIN
    value=runner.read(root/TOKEN_CAPACITY)
    if (value.get('version')!='original-pixel-token-final-capacity.v1'
            or value.get('authorization')!=bound(root/AUTH) or value.get('repair')!=bound(repair_path)
            or value.get('after_source_bindings')!=accepted_audit_production(root)
            or value.get('maximum_new_capacity_calls_per_task')!=1
            or value.get('maximum_scoring_calls_per_task')!=1
            or value.get('prior_schema_continuation')!=bound(root/CAPACITY_SCHEMA)):
        raise ValueError('Exact single smaller-wire capacity continuation required')
    before=value['before_source_bindings'];after=value['after_source_bindings'];current=str(Path(__file__).resolve())
    prior=verify_capacity_schema_continuation(root,repair_path,repair,expected_production=before)
    changed={k for k in set(before)|set(after) if before.get(k)!=after.get(k)}
    audit=str(Path(__file__).with_name('mechanic_v3_delivery_audit_v3.py').resolve())
    additional=value.get('old_additional_producers',{})
    if (prior['after_source_bindings']!=before or current not in changed
            or changed-{current}!=set(additional) or not set(additional)<={audit}
            or sha(verify_binding(value['old_producer']))!=before[current]):
        raise ValueError('Only the exact final-wire recovery producer may change')
    for name,archive in additional.items():
        if sha(verify_binding(archive))!=before[name]:
            raise ValueError('Exact logical-prompt audit producer archive required')
    if runner.read(verify_binding(value['regression'])).get('exit_code')!=0:
        raise ValueError('Passed smaller-wire capacity regression required')
    failure=runner.read(verify_binding(value['parent_failure']))
    if 'Original-pixel complete final capacity insufficient' not in failure.get('error',''):
        raise ValueError('Measured original-pixel parent failure required')
    auth=runner.read(root/AUTH);entries=value['tasks']
    if set(entries)!={t['task'] for t in auth['tasks']}:
        raise ValueError('Every exact independent task must be retained')
    failures=0
    for name,info in entries.items():
        folder=root/'capacity_calls'/(name+'_schema_defs')
        wire=Path(info['transport']['wire_path'])
        if sha(wire)!=info['transport']['wire_sha256']:
            raise ValueError('Exact smaller complete-final wire required')
        original=verify_binding(info['original_prompt']).read_bytes().decode('utf-8')
        from .gameness_v4_final_literal import prepare
        encoded=prepare(dict(final_literal_transport=info['transport']),original)
        from .gameness_v4_persistent_literal import _flat_inverse
        old_wire=verify_binding(info['previous_wire']).read_bytes().decode('utf-8')
        if _flat_inverse(old_wire,nested=True)!=original:
            raise ValueError('Old and new wires must reconstruct the identical complete final')
        import tiktoken
        enc=tiktoken.get_encoding('o200k_base')
        tokens=lambda t:len(enc.encode(t,disallowed_special=()))
        if tokens(NOTICE+old_wire)-tokens(encoded)<256:
            raise ValueError('Substantive smaller token representation required before a new bounded probe')
        if info['state']=='MEASURED_INSUFFICIENT':
            for file in ['invocation.json','schema.json','rpc_requests.jsonl','rpc_events.jsonl','prompt.txt',
                         'response.json','persistent_session.jsonl','capacity_gate.json']:
                if info['artifacts'].get(file)!=bound(folder/file):
                    raise ValueError('Every accepted prior capacity artifact must remain exact')
            inv=runner.read(folder/'invocation.json');gate=runner.read(folder/'capacity_gate.json')
            if (inv.get('attempt')!=1 or inv.get('exit_code')!=0 or inv.get('model_requested')!='gpt-6.1-sol'
                    or runner.read(folder/'response.json')!=ACK or gate.get('passed') is not False
                    or gate.get('output_reserve')!=OUTPUT_RESERVE or gate.get('margin')!=OVERHEAD_MARGIN
                    or gate.get('scoring_calls')!=0 or gate.get('original_pixel_count',0)<1
                    or gate['required_with_output_and_margin']!=gate['actual']['input_tokens']+OUTPUT_RESERVE+OVERHEAD_MARGIN
                    or gate['required_with_output_and_margin']<=gate['window']):
                raise ValueError('Actual complete-original-pixel capacity overflow with retained ACK required')
            failures+=1
        elif info['state']=='NOT_SUBMITTED_SIBLING':
            if folder.exists():raise ValueError('An unsubmitted sibling cannot hide a prior actual call')
        else:raise ValueError('Unknown smaller-wire task qualification')
    if failures<1:raise ValueError('At least one exact measured capacity overflow required')
    return value


def final_prompt(root,task,c):
    text=_final_prompt(root,task,c)
    if task.get('frozen_output_consistency'):
        return text+OUTPUT_FEEDBACK
    return text


def _final_prompt(root,task,c):
    path=root/FINAL_CAPACITY
    if task.get('source_repack'):
        info=verify_source_repack(root)['final_literal_transport']
    elif (root/PUBLISHED_FINAL).exists():info=runner.read(root/PUBLISHED_FINAL)['tasks'][task['task']]['transport']
    elif (root/TOKEN_CAPACITY).exists():info=runner.read(root/TOKEN_CAPACITY)['tasks'][task['task']]['transport']
    elif path.exists():info=runner.read(path)['tasks'][task['task']]
    elif task.get('final_literal_transport'):info=task['final_literal_transport']
    else:return c['prompt']
    from .gameness_v4_final_literal import prepare
    return prepare(dict(final_literal_transport=info),c['prompt'])


def authorize(workspace,root,column,repair_path):
    if (root/SOURCE_REPACK).exists():
        receipt=verify_source_repack(root)
        token=_READONLY_PRODUCTION.set(receipt['before_source_bindings'])
        try:return _authorize(workspace,root,column,repair_path)
        finally:_READONLY_PRODUCTION.reset(token)
    if (root/NESTED_ROOT).exists():
        receipt=verify_nested_root(root)
        token=_READONLY_PRODUCTION.set(receipt['before_source_bindings'])
        try:return _authorize(workspace,root,column,repair_path)
        finally:_READONLY_PRODUCTION.reset(token)
    if (root/OUTPUT_CONSISTENCY).exists():
        receipt=verify_output_consistency(root)
        token=_READONLY_PRODUCTION.set(receipt['before_source_bindings'])
        try:return _authorize(workspace,root,column,repair_path)
        finally:_READONLY_PRODUCTION.reset(token)
    return _authorize(workspace,root,column,repair_path)


def _authorize(workspace,root,column,repair_path):
    repair=runner.read(repair_path)
    if (repair.get('version')!=VERSION or repair.get('column')!=column or repair.get('identity')!=root.name
            or repair.get('maximum_attempts')!=1
            or repair.get('cause')!='ACTUAL_RETAINED_NATIVE_IMAGES_RESIZED'):
        raise ValueError('One substantive exact-production original-pixel repair required')
    if repair.get('after_source_bindings')!=production():
        if (root/PUBLISHED_FINAL).exists():verify_published_final_capacity(root,repair_path,repair)
        elif (root/TOKEN_CAPACITY).exists():verify_token_capacity_continuation(root,repair_path,repair)
        elif (root/CAPACITY_SCHEMA).exists():verify_capacity_schema_continuation(root,repair_path,repair)
        elif (root/FINAL_CAPACITY).exists():verify_final_capacity_continuation(root,repair_path,repair)
        else:verify_fork_audit_continuation(root,repair_path,repair)
    for item in repair['evidence']:
        verify_binding(item)
    if runner.read(verify_binding(repair['regression'])).get('exit_code')!=0:
        raise ValueError('Passed targeted recovery regression required')
    auth_path,auth=original(root,column,repair);verify_old_auth(root,auth_path,auth,repair)
    path=root/AUTH
    if path.exists():
        value=runner.read(path)
        if value['repair']!=bound(repair_path) or value['original_authorization']!=bound(auth_path):
            raise ValueError('A prior bounded pixel repair already exists')
        return value
    # No published result is replaced by this initial missing-column capability.
    from . import mechanic_v3_revision as revision
    from . import gameness_v3_runtime as runtime
    publication=(runtime.publication_path(workspace,root.name) if column=='Gameness'
        else revision.publication_dir(workspace)/(root.name+'.json'))
    published = repair.get('published_history')
    if publication.exists():
        if not published:raise ValueError('Published-result qualification repair needs a separate explicit history route')
        verify_published_parent(root, repair)
        if sha(publication) != published['parent_publication']['sha256']:
            raise ValueError('Published repair must start from its exact still-current parent')
    elif published:
        raise ValueError('Published-result repair cannot hide a missing parent publication')
    tasks=auth['tasks'] if column=='Mechanic' else [{'task':auth['task']}]
    planned=[]
    for task in tasks:
        source=repair['source_tasks'][task['task']]
        call=root/'model_calls'/source
        final=call/'persistent_turns/final/invocation.json'
        if published:
            inv=runner.read(final)
            accepted=runner.read(call/'accepted_response.json')
            if (inv.get('exit_code')!=0 or accepted.get('sha256')!=sha(call/accepted['path'])
                    or source!=task['task']):
                raise ValueError('Published pixel repair requires the exact accepted parent task')
        elif runner.read(final).get('status')!='TIMEOUT':
            raise ValueError('This recovery requires the retained final TIMEOUT plus the proven pixel defect')
        c=context(workspace,root,column,auth,task)
        original_prompt=c['prompt']
        if auth.get('final_literal_transport') and column=='Gameness':
            from .gameness_v4_final_literal import prepare
            original_prompt=prepare(auth,original_prompt)
        if (call/'prompt.txt').read_text()!=original_prompt and task['task']==source:
            raise ValueError('Original final prompt changed')
        if task['task']==source and runner.read(call/'schema.json')!=c['schema']:
            raise ValueError('Original final schema changed')
        for index,(prompt,wire_part) in enumerate(zip(c['intake_prompts'],c['wire_parts']),1):
            folder=call/'persistent_turns'/f'intake_{index:02d}'
            inv=runner.read(folder/'invocation.json');response=runner.read(folder/'response.json')
            expected=runner.read(folder/'schema.json')['properties']
            if ((folder/'prompt.txt').read_text()!=prompt or inv.get('exit_code')!=0
                    or inv.get('model_requested')!='gpt-6.1-sol' or response!={
                        'chunk':index,'sha256':expected['sha256']['enum'][0]}
                    or expected['chunk']['enum']!=[index]
                    or expected['sha256']['enum']!=[hashlib.sha256(wire_part.encode()).hexdigest()]):
                raise ValueError('Original complete intake ACK changed')
        sid=transport.event_values(call/'persistent_turns/intake_01/events.jsonl')
        parent=transport.session_path(sid)
        boundary=intake_boundary(parent,c['intake_prompts'],'gpt-6.1-sol')
        # Keep a complete immutable parent snapshot, including the failed final.
        snapshot=root/'engineering/original_pixel_parent_sessions'/(sid+'.jsonl')
        snapshot.parent.mkdir(parents=True,exist_ok=True)
        transport.save(snapshot,parent.read_bytes())
        previous=runner.read(root/'requests'/source/'actual_delivery.json')
        try:native.retained_images(snapshot,(call/'prompt.txt').read_text(),[root/v['path'] for v in previous['images']])
        except ValueError as error:
            if 'changed original native pixels' not in str(error):raise
        else:raise ValueError('A real actual native-pixel defect must be proven')
        planned.append(dict(original_task=task['task'],task=task['task']+'_original_pixels_'+sha(repair_path)[:12],
            source_task=source,parent_session=sid,fork_through=boundary,parent_snapshot=bound(snapshot),
            body_sha256=hashlib.sha256(c['body'].encode()).hexdigest(),intake_prompt_sha256=[hashlib.sha256(p.encode()).hexdigest() for p in c['intake_prompts']],
            parent_failure=bound(final),criterion_ids=[s['id'] for s in c['specs']],
            **({'final_literal_transport':repair['final_literal_transports'][task['task']]} if repair.get('final_literal_transports') else {})))
    value=dict(version=VERSION,identity=root.name,column=column,repair=bound(repair_path),
        original_authorization=bound(auth_path),maximum_attempts_per_independent_task=1,
        maximum_prompt_bytes=1000000,maximum_images=100,maximum_capacity_calls_per_independent_task=1,
        original_claims_failures_and_counts_preserved=True,
        all_original_bytes_and_pixels_required=True,tasks=planned)
    runner.exclusive_json(path,value);return value


def verify_delivery(root, name, actual):
    """Read a completed exact producer without granting new runtime admission."""
    path=Path(root)/COMPLETED_HISTORY
    if not path.exists():return _verify_delivery(root,name,actual)
    value=runner.read(path)
    from .gameness_v3_runtime import production_bindings
    current=production_bindings();before=value['before_source_bindings']
    if (value.get('version')!='original-pixel-completed-producer-history.v1'
            or value.get('authorization')!=bound(Path(root)/AUTH)
            or value.get('after_source_bindings')!=current
            or value.get('maximum_new_model_calls')!=0):
        raise ValueError('Exact completed-only producer history required')
    changed={p for p in set(before)|set(current) if before.get(p)!=current.get(p)}
    allowed={str(Path(__file__).with_name(n).resolve()) for n in (
        'persistent_original_pixel_recovery.py','two_column_sync.py','gameness_v4_producer_history.py')}
    if not changed or not changed<=allowed or set(value['old_producers'])!=changed:
        raise ValueError('Only exact published-pixel transport producers may evolve')
    for p in changed:
        if sha(verify_binding(value['old_producers'][p]))!=before[p]:
            raise ValueError('Exact old completed producer bytes required')
    proof=runner.read(verify_binding(value['regression']))
    accepted=runner.read(verify_binding(value['acceptance']))
    if (proof.get('exit_code')!=0 or proof.get('tests_passed',0)<1
            or not accepted.get('complete_original_sources_and_pixels')
            or accepted.get('new_recording') is not False):
        raise ValueError('Completed real original-pixel E2E and regression required')
    for p,d in value['immutable_materials'].items():
        if sha(Path(p))!=d:raise ValueError('Completed original-pixel evidence changed: '+p)
    if name not in value['completed_tasks']:
        raise ValueError('Completed history never authorizes a new independent task')
    token=_READONLY_PRODUCTION.set(before)
    archive_token=_READONLY_ARCHIVES.set(value['old_producers'])
    try:return _verify_delivery(root,name,actual)
    finally:
        _READONLY_ARCHIVES.reset(archive_token)
        _READONLY_PRODUCTION.reset(token)


def _verify_delivery(root,name,actual):
    value=runner.read(root/AUTH);marker=actual.get(MARKER,{})
    if marker.get('authorization')!=bound(root/AUTH):raise ValueError('Exact original-pixel authorization required')
    repair_path=verify_binding(value['repair']);repair=runner.read(repair_path)
    auth_path=verify_binding(value['original_authorization']);auth=runner.read(auth_path)
    verify_old_auth(root,auth_path,auth,repair)
    task=next(t for t in delivery_tasks(root,value) if t['task']==name)
    if task.get('frozen_output_consistency'):verify_output_consistency(root)
    if task.get('source_repack'):verify_source_repack(root)
    original_task=next(t for t in auth.get('tasks',[]) if t['task']==task['original_task']) if value['column']=='Mechanic' else {'task':auth['task']}
    expected_context=context(root.parent.parent,root,value['column'],auth,original_task)
    calibrate_capacity(root,task,expected_context,allow_call=False)
    verify_binding(task['parent_snapshot']);verify_binding(task['parent_failure'])
    expected_actual=copy.deepcopy(expected_context['actual'])
    expected_actual.pop('mechanic_persistent_complete_source',None);expected_actual.pop('runtime_text_chunks',None)
    expected_actual[MARKER]=dict(version=VERSION,authorization=bound(root/AUTH))
    expected_actual['v3_task']=name;expected_actual['task']=name
    if actual!=expected_actual:raise ValueError('Every original source, native image and frozen delivery field must remain identical')
    for item in actual['images']:
        if sha(root/item['path'])!=item['sha256']:raise ValueError('Original image SHA changed')
    if value['column']=='Gameness':
        if not actual.get('all_predeclared_frames_delivered') or not actual.get('complete_author_sources'):
            raise ValueError('Complete original author sources and every declared frame required')
        for item in actual['complete_author_sources']:
            source=root/item['path']
            if sha(source)!=item['sha256'] or len(source.read_text(errors='replace').splitlines())!=item['line_count']:
                raise ValueError('Original author source identity changed')
    call=root/'model_calls'/name;req=root/'requests'/name
    prompt=(call/'prompt.txt').read_text();body=(req/'complete_body.txt').read_text()
    if prompt!=final_prompt(root,task,expected_context) or body!=expected_context['body'] or runner.read(call/'schema.json')!=expected_context['schema']:
        raise ValueError('Complete frozen prompt, body and output schema must remain identical')
    if hashlib.sha256(expected_context['prompt'].encode()).hexdigest()!=actual['prompt_sha256'] or hashlib.sha256(body.encode()).hexdigest()!=task['body_sha256']:
        raise ValueError('Complete original body or final prompt changed')
    intake=runner.read(req/'intake_prompts.json')
    if [hashlib.sha256(p.encode()).hexdigest() for p in intake]!=task['intake_prompt_sha256']:
        raise ValueError('Original literal source inputs changed')
    inv=runner.read(call/'invocation.json')
    if (inv.get('exit_code')!=0 or inv.get('attempt')!=1 or inv.get('transport')!='app-server-original-detail'
            or inv.get('model_requested')!='gpt-6.1-sol'):
        raise ValueError('Original-detail actual invocation required')
    rpc=list(rows(call/'rpc_requests.jsonl'))
    forks=[v['params'] for v in rpc if v.get('method')=='thread/fork']
    starts=[v['params'] for v in rpc if v.get('method')=='turn/start']
    if len(forks)!=1 or forks[0]['threadId']!=task['parent_session'] or forks[0]['lastTurnId']!=task['fork_through']:
        raise ValueError('Exact source-only fork boundary required')
    expected=[dict(type='text',text=prompt)]+[dict(type='localImage',path=str((root/i['path']).resolve()),detail='original') for i in actual['images']]
    if len(starts)!=1 or starts[0]['input']!=expected or starts[0]['outputSchema']!=runner.read(call/'schema.json'):
        raise ValueError('Exact complete original image input and schema required')
    session=call/'persistent_session.jsonl'
    proof=verify_fork_session(root,task,call,expected_context,prompt)
    pixels=native.retained_images(session,prompt,[root/i['path'] for i in actual['images']])
    expanded=(req/'expanded_prompt.txt').read_text()
    if body not in expanded or expanded!=expected_context['expanded']:raise ValueError('Exact full original context must be available to source audit')
    return dict(version=VERSION,all_original_text_actually_delivered=True,ordered_session_proof=proof,
        all_original_pixels_actually_delivered=True,images=pixels,expanded_prompt=expanded)


def capacity_schema(original):
    """Strict inert ACK with the complete original schema retained once in $defs.

    Original references keep the same #/$defs scope. The unused definition
    supplies the complete actual judge-schema token load without requiring
    the probe to generate any scoring fields. The final judge uses original.
    """
    from .gameness_v4_final_literal import SCHEMA
    key='WhiteboxOriginalJudgment'
    if key in original.get('$defs',{}):raise ValueError('Reserved original-schema definition collision')
    value=copy.deepcopy(SCHEMA)
    value['$defs']=copy.deepcopy(original.get('$defs',{}))
    value['$defs'][key]={k:copy.deepcopy(v) for k,v in original.items() if k!='$defs'}
    return value


def calibrate_capacity(root, task, c, *, allow_call=True):
    """Measure the real complete source+original-image input in an inert fork.

    The original complete judgment schema is retained in the probe definitions;
    the strict root requires only the inert ACK property.
    The frozen 16K output reserve and 4096 margin are additional to real usage.
    No criterion answer from this calibration can enter a judgment.
    """
    from .gameness_v4_persistent_capacity import telemetry, OUTPUT_RESERVE, OVERHEAD_MARGIN
    from .gameness_v4_final_literal import probe_prompt, ACK, SCHEMA
    repacked=bool(task.get('source_repack'))
    if repacked:verify_source_repack(root)
    published_final=(root/PUBLISHED_FINAL).exists() and not repacked
    if published_final:
        auth=runner.read(root/AUTH);repair_path=verify_binding(auth['repair'])
        verify_published_final_capacity(root,repair_path,runner.read(repair_path))
    encoded=repacked or published_final or (root/FINAL_CAPACITY).exists() or bool(task.get('final_literal_transport'))
    strict_schema=(root/CAPACITY_SCHEMA).exists()
    token_wire=(root/TOKEN_CAPACITY).exists()
    if token_wire:
        auth=runner.read(root/AUTH);repair_path=verify_binding(auth['repair'])
        verify_token_capacity_continuation(root,repair_path,runner.read(repair_path))
    folder=root/'capacity_calls'/(task['task']+('_published_final_literal' if published_final else ('_token_final' if token_wire else ('_schema_defs' if strict_schema else ('_exact_final' if encoded else '')))))
    schema=capacity_schema(c['schema']) if encoded else SCHEMA
    prompt=probe_prompt(final_prompt(root,task,c)+(('\nINERT ORIGINAL OUTPUT SCHEMA:\n'+json.dumps(c['schema'],ensure_ascii=False)) if not encoded else ''))
    if not folder.exists():
        if not allow_call:raise ValueError('A successful bounded capacity calibration is required')
        value,sid=native.rpc_invoke(folder,root/'input',prompt,schema,c['images'],model='gpt-6.1-sol',
            session=task['parent_session'],fork_through=task['fork_through'])
        transport.save(folder/'persistent_session.jsonl',transport.session_path(sid).read_bytes())
        if value!=ACK:raise ValueError('Non-scoring original-pixel capacity ACK required')
    else:
        inv=runner.read(folder/'invocation.json');sid=inv.get('thread')
        if inv.get('exit_code')!=0 or not sid:
            raise ValueError('Prior bounded capacity failure retained; no unchanged retry')
        if not (folder/'persistent_session.jsonl').exists():
            transport.save(folder/'persistent_session.jsonl',transport.session_path(sid).read_bytes())
    inv=runner.read(folder/'invocation.json')
    if (runner.read(folder/'response.json')!=ACK or (folder/'prompt.txt').read_text()!=prompt
            or runner.read(folder/'schema.json')!=schema or inv.get('model_requested')!='gpt-6.1-sol'
            or inv.get('attempt')!=1 or inv.get('exit_code')!=0):
        raise ValueError('Exact successful original-pixel capacity call required')
    requests=list(rows(folder/'rpc_requests.jsonl'))
    forks=[v['params'] for v in requests if v.get('method')=='thread/fork']
    starts=[v['params'] for v in requests if v.get('method')=='turn/start']
    expected=[dict(type='text',text=prompt)]+[dict(type='localImage',path=str(Path(p).resolve()),detail='original') for p in c['images']]
    if (len(forks)!=1 or forks[0]['threadId']!=task['parent_session'] or forks[0]['lastTurnId']!=task['fork_through']
            or len(starts)!=1 or starts[0]['input']!=expected or starts[0]['outputSchema']!=schema):
        raise ValueError('Capacity must preserve the complete exact source-only prefix and all native pixels')
    session=folder/'persistent_session.jsonl'
    proof=verify_fork_session(root,task,folder,c,prompt)
    pixels=native.retained_images(session,prompt,c['images'])
    last=telemetry(session)[-1]
    required=last['input_tokens']+OUTPUT_RESERVE+OVERHEAD_MARGIN
    gate=dict(actual=last,required_with_output_and_margin=required,
        output_reserve=OUTPUT_RESERVE,margin=OVERHEAD_MARGIN,window=last['window'],
        passed=last['input_tokens']>0 and required<=last['window'],scoring_calls=0,
        complete_source_prefix=proof,original_pixel_count=len(pixels),parent_failure=task['parent_failure'])
    if allow_call:dump(folder/'capacity_gate.json',gate)
    elif runner.read(folder/'capacity_gate.json')!=gate:raise ValueError('Measured capacity gate changed')
    if not gate['passed']:raise ValueError('Original-pixel complete final capacity insufficient: '+str((required,last['window'])))
    return gate


def evaluate(workspace,root,column,auth,task,original_auth):
    old_task=next(t for t in original_auth.get('tasks',[]) if t['task']==task['original_task']) if column=='Mechanic' else {'task':original_auth['task']}
    c=context(workspace,root,column,original_auth,old_task);name=task['task'];call=root/'model_calls'/name
    req=root/'requests'/name;req.mkdir(parents=True,exist_ok=True)
    actual=copy.deepcopy(c['actual']);actual.pop('mechanic_persistent_complete_source',None);actual.pop('runtime_text_chunks',None)
    actual[MARKER]=dict(version=VERSION,authorization=bound(root/AUTH));actual['v3_task']=name;actual['task']=name
    for filename,text in [('complete_body.txt',c['body']),('expanded_prompt.txt',c['expanded'])]:transport.save(req/filename,text.encode())
    for filename,data in [('actual_delivery.json',actual),('selected_manifest.json',c['selected']),('citation_rules.json',c['rules']),
            ('intake_prompts.json',c['intake_prompts']),('context_binding.json',dict(omitted_source_ranges=[],body_sha256=task['body_sha256']))]:
        transport.save(req/filename,(json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode())
    dest=root/'judgments'/(name+'.json')
    if dest.exists():
        verify_delivery(root,name,actual);return runner.read(dest)['checks']
    if call.exists():raise ValueError('Original-pixel attempt already exists; preserve and diagnose; no automatic retry')
    runner.disk(root,'original_pixel_complete_judge',512*1024**2)
    calibrate_capacity(root,task,c)
    raw,sid=native.rpc_invoke(call,root/'input',final_prompt(root,task,c),c['schema'],c['images'],model='gpt-6.1-sol',
        session=task['parent_session'],fork_through=task['fork_through'])
    transport.save(call/'persistent_session.jsonl',transport.session_path(sid).read_bytes())
    delivery=verify_delivery(root,name,actual)
    try:
        checks=evaluate_response(root,column,c,raw)
    except ValueError as error:
        dump(call/'validation_error.json',dict(phase='original_pixel_response_validation',exception=str(error),
            response_sha256=sha(call/'response.json'),product_score=None))
        raise
    dump(call/'accepted_response.json',dict(path='response.json',sha256=sha(call/'response.json')))
    execution.audit_invocation(root,name,actual)
    dump(dest,dict(version=VERSION,task=name,parent=c['actual']['evidence_set'],raw=raw,checks=checks,
        actual_delivery_sha256=sha(call/'actual_delivery.json'),accepted_response_sha256=sha(call/'accepted_response.json'),
        response_path=str(call/'response.json'),response_sha256=sha(call/'response.json')))
    delivery.pop('expanded_prompt');dump(call/'original_pixel_delivery_verified.json',delivery)
    print(json.dumps(dict(stage='ORIGINAL_PIXEL_JUDGE_ACCEPTED',identity=root.name,column=column,task=name,images=len(c['images']))),flush=True)
    return checks


def recovery_inventory(workspace, root, column):
    """Use the original claim's scope owner without copying or replacing scope."""
    from . import gameness_v3_runtime as runtime
    workspace=Path(workspace).resolve();root=Path(root).resolve()
    if column=='Gameness':return runtime.load(workspace)
    claim_path=root/'source_delivery_correction.json'
    if not claim_path.exists():return runtime.scope.load(workspace)
    from . import mechanic_v3_source_correction as correction
    claim=correction.verify_claim(runner.read(claim_path))
    scope_path=verify_binding(claim['scope_binding']).resolve()
    owner=scope_path.parents[2]
    pointer=correction.pointer(owner,root.name)
    parent=Path(claim['original_publication']).resolve()
    fingerprint=claim['bindings'].get(str(parent),'')[:16]
    expected=owner/'source_delivery_corrections'/root.name/fingerprint
    if (scope_path!=owner/'scopes/all_s_original/scope.json'
            or workspace!=expected or root!=workspace/'runs'/root.name
            or claim.get('identity')!=root.name or claim.get('root')!=str(root)
            or claim.get('correction_workspace')!=str(workspace)
            or parent.name!=root.name+'.json'
            or parent.parent.name!='outcome_frame_v1' or parent.parent.parent.name!='publications'
            or len(fingerprint)!=16 or any(v not in '0123456789abcdef' for v in fingerprint)
            or runner.read(pointer)!=claim
            or claim.get('no_new_recording') is not True
            or claim.get('scoring_semantics_unchanged') is not True
            or runner.read(root/'source_qualification.json').get('source_delivery_correction')!=str(claim_path)):
        raise ValueError('Exact original source-correction claim, scope owner and pointer required')
    inventory=runtime.scope.load(owner)
    if (inventory['full_scope_binding']!=claim['scope_binding']
            or root.name not in inventory['active_selection']):
        raise ValueError('Source correction must retain its frozen selected original scope')
    return inventory


def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('--workspace',type=Path,required=True)
    parser.add_argument('--phase',choices=['persistent-original-pixel-judge'],required=True)
    parser.add_argument('--identities',nargs=1,required=True);parser.add_argument('--pixel-repair',type=Path,required=True)
    parser.add_argument('--column',choices=['Mechanic','Gameness'],required=True)
    parser.add_argument('--acceptance-case',action='store_true')
    args=parser.parse_args(argv);workspace=args.workspace.resolve();identity=args.identities[0]
    root=resolve_run_root(workspace,identity,args.column,args.pixel_repair.resolve())
    column=args.column
    if not args.acceptance_case:raise ValueError('This new native-pixel recovery requires an explicit real acceptance case')
    from . import gameness_v3_runtime as runtime, mechanic_v3_revision as revision
    lock=workspace/'locks'/((('gameness_v4_' if column=='Gameness' else 'outcome_frame_v1_')+identity)+'.lock')
    lock.parent.mkdir(parents=True,exist_ok=True)
    with lock.open('a+') as handle:
        fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:
            from . import batch, sparse_native
            from .pending_publication import cleanup_source
            batch.verify_inputs(root);q=runner.read(root/'source_qualification.json')
            runtime.verify_bindings(q['source_bindings'])
            if not cleanup_source(Path(q['source']))[0]:raise ValueError('Qualified original native cleanup required')
            entry=runner.read(root/'input_manifest.json')['entry']
            sparse_native.verify_acceptance(workspace,entry['actual_engine'])
            inventory=recovery_inventory(workspace,root,column)
            row=next(r for r in inventory['entries'] if r['entry']['id']==identity and r['in_scope'])
            runner.configure_cli(Path(row['source_batch']))
            before=production();auth=authorize(workspace,root,column,args.pixel_repair.resolve());_,old=original(root,column)
            auth=dict(auth,tasks=active_tasks(root,auth))
            checks={}
            for task in auth['tasks']:
                part=evaluate(workspace,root,column,auth,task,old)
                if set(checks)&set(part):raise ValueError('Independent criterion duplicated')
                checks.update(part)
            if runner.read(args.pixel_repair.resolve()).get('published_history'):
                publish_original_pixel_replacement(workspace,root,column,auth,checks,args.pixel_repair.resolve())
                return 0
            if column=='Mechanic':
                from . import mechanic_v3 as policy
                result=policy.aggregate(runner.read(root/'input/pilot_rubric.json'),checks)
                result['assessment_revision']='outcome_frame_v1';dump(revision.result_path(workspace,root),result)
                from . import mechanic_v3_delivery_audit_v3 as native_delivery, mechanic_v3_delivery_audit_v4 as full_delivery
                manifest=runner.read(root/'evidence_manifest.json')
                tasks=[native_delivery.task_delivery(root,runner.read(root/'judgments'/(t['task']+'.json')),manifest) for t in auth['tasks']]
                audited=full_delivery.upgrade(dict(version=native_delivery.VERSION,root=str(root),tasks=tasks))
                if not audited['qualified']:raise ValueError('Complete native Mechanic delivery must pass before publication')
                publication=execution.finalize_publication(workspace,root,result)
            else:
                from . import gameness_v4 as policy, gameness_v3_static as static
                result=policy.aggregate(runtime.authored_rubric.protocol_for_run(root),checks);dump(root/'gameness_score.json',result)
                dump(root/'gameness_coverage.json',static.coverage_report(runner.read(root/'gameness_source_review.json'),checks))
                source_batch=Path(next(r for r in runtime.load(workspace)['entries'] if r['entry']['id']==identity)['source_batch'])
                with runner.held(workspace,source_batch,native=False) as guard:runtime.publish(workspace,root,result,guard)
                publication=runtime.verify_publication(workspace,identity)
            from . import two_column_sync
            two_column_sync.sync(workspace,identity,column)
            dump(root/'engineering/original_pixel_real_acceptance.json',dict(version=VERSION,column=column,
                status=column.upper()+'_ORIGINAL_PIXELS_REAL_E2E_ACCEPTED',production_bindings=before,
                publication_status='SCORED_PENDING_AUDIT',new_recording=False,complete_original_sources_and_pixels=True,
                independent_tasks=len(auth['tasks']),score=result['score']))
            if column=='Mechanic':execution.cache_check(workspace,root,publication)

        except Exception as error:
            dump(root/'failures'/('original_pixel_'+str(time.time_ns())+'.json'),dict(category='HARNESS_ERROR',error=repr(error),
                old_claims_failures_and_counts_preserved=True,product_score=None));raise
    return 0


def verify_published_parent(root, repair):
    """Keep the exact published baseline and every original evidence byte."""
    history=repair['published_history'];parent=runner.read(verify_binding(history['parent_publication']))
    score=verify_binding(history['parent_score'])
    if (history.get('version')!='original-pixel-published-parent.v1'
            or parent.get('identity')!=root.name or Path(parent['score_file'])!=score
            or parent.get('status')!='SCORED_PENDING_AUDIT'
            or history['prior_column']['publication_sha256']!=history['parent_publication']['sha256']
            or history['prior_column']['workspace']!=str(context_workspace(root.parent.parent,root))):
        raise ValueError('Exact published original identity, score and registered baseline required')
    code=Path(__file__).resolve().parent
    for name,digest in parent['bindings'].items():
        if sha(Path(name))==digest:continue
        archived=repair.get('original_producer_archives',{}).get(name)
        if Path(name).parent!=code or not archived or sha(Path(archived))!=digest:
            raise ValueError('Published parent evidence or exact producer changed: '+name)
    return parent


def verify_published_replacement(root, publication):
    """A complete same-source, same-rubric qualification replaces scaled input."""
    meta=publication['qualification_recovery'];proof=runner.read(verify_binding(meta['proof']))
    auth=runner.read(root/AUTH);repair=runner.read(verify_binding(auth['repair']))
    parent=verify_published_parent(root,repair)
    if (meta.get('version')!='original-pixel-published-replacement.v1'
            or meta.get('prior_column')!=repair['published_history']['prior_column']
            or meta.get('parent_publication')!=repair['published_history']['parent_publication']
            or proof.get('authorization')!=bound(root/AUTH)
            or proof.get('repair')!=auth['repair']
            or proof.get('identity')!=root.name
            or proof.get('column')!=auth['column']
            or proof.get('new_recording') is not False
            or proof.get('complete_original_sources_and_pixels') is not True
            or proof.get('task_names')!=[t['task'] for t in active_tasks(root,auth)]
            or proof.get('score')!=bound(Path(publication['score_file']))
            or publication['identity']!=parent['identity']
            or publication['scoring_protocol']!=parent['scoring_protocol']
            or publication['contract_revision']!=parent['contract_revision']):
        raise ValueError('Exact complete original-pixel qualification proof required')
    checks={}
    for name in proof['task_names']:
        path=root/'judgments'/(name+'.json');artifact=runner.read(path)
        if (proof['judgments'].get(str(path))!=sha(path)
                or publication['bindings'].get(str(path))!=sha(path)
                or checks.keys() & artifact['checks'].keys()):
            raise ValueError('Every new independent judgment must be uniquely bound')
        verify_delivery(root,name,runner.read(root/'requests'/name/'actual_delivery.json'))
        checks.update(artifact['checks'])
    result=runner.read(Path(publication['score_file']))
    if checks!=result['checks']:raise ValueError('Replacement must include exactly every independently judged check')
    return proof


def merge_published_original_pixel(prior, incoming):
    meta=incoming['qualification_recovery'];proof=runner.read(verify_binding(meta['proof']))
    current=runner.read(Path(incoming['publication']))
    if current.get('qualification_recovery')!=meta or sha(Path(incoming['publication']))!=incoming['publication_sha256']:
        raise ValueError('Replacement must be the exact currently verified publication')
    clean={k:v for k,v in prior.items() if k!='previous_publications'}
    history=prior.get('previous_publications',[])
    if clean==incoming:return prior
    if meta['prior_column']!=prior:
        raise ValueError('Original-pixel replacement must retain its exact registered parent column')
    root=Path(current['score_file']).parent
    verify_published_replacement(root,current)
    return dict(incoming,previous_publications=[*history,clean])


def publish_original_pixel_replacement(workspace,root,column,auth,checks,repair_path):
    """Archive and atomically replace only the publication; old scored bytes stay."""
    repair=runner.read(repair_path);parent=verify_published_parent(root,repair)
    if column=='Mechanic':
        from . import mechanic_v3 as policy, mechanic_v3_revision as revisions
        result=policy.aggregate(runner.read(root/'input/pilot_rubric.json'),checks)
        result['assessment_revision']='outcome_frame_v1'
        target=revisions.publication_dir(workspace)/(root.name+'.json')
    else:
        from . import gameness_v4 as policy, gameness_v3_runtime as runtime
        result=policy.aggregate(runtime.authored_rubric.protocol_for_run(root),checks)
        target=runtime.publication_path(workspace,root.name)
    score=root/('original_pixel_score_'+sha(repair_path)[:12]+'.json')
    transport.save(score,(json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode())
    proof_path=root/'engineering/published_original_pixel_qualification.json'
    proof=dict(version='original-pixel-published-qualification.v1',identity=root.name,column=column,
        repair=bound(repair_path),authorization=bound(root/AUTH),score=bound(score),
        task_names=[t['task'] for t in auth['tasks']],
        judgments={str(root/'judgments'/(t['task']+'.json')):sha(root/'judgments'/(t['task']+'.json')) for t in auth['tasks']},
        complete_original_sources_and_pixels=True,new_recording=False)
    transport.save(proof_path,(json.dumps(proof,ensure_ascii=False,indent=2)+'\n').encode())
    value=copy.deepcopy(parent);value.update(score_file=str(score),published_at=runner.stamp(),new_recording=False,
        recording_notice='复用原合格实录；原像素送达故障后独立完整判词；保留旧发布及分数')
    value['mechanic_score' if column=='Mechanic' else 'gameness_score']=result['score']
    value['qualification_recovery']=dict(version='original-pixel-published-replacement.v1',proof=bound(proof_path),
        parent_publication=repair['published_history']['parent_publication'],prior_column=repair['published_history']['prior_column'])
    additions=[score,root/AUTH,repair_path,proof_path]
    if (root/NESTED_ROOT).exists():additions.append(root/NESTED_ROOT)
    if (root/SOURCE_REPACK).exists():
        additions.extend([root/SOURCE_REPACK,root/SOURCE_INTAKE])
        intake=runner.read(root/SOURCE_INTAKE)
        additions.extend(Path(p) for p in intake['immutable_materials'])
    for t in auth['tasks']:
        additions.append(root/'judgments'/(t['task']+'.json'))
        for directory in ['requests','model_calls']:
            additions.extend(p for p in (root/directory/t['task']).rglob('*') if p.is_file())
    value['bindings'].update({str(p):sha(p) for p in additions})
    verify_published_replacement(root,value)
    source_batch=Path(runner.read(root/'source_qualification.json')['source']).parent.parent
    with runner.held(workspace,source_batch,native=False):
        if sha(target)!=repair['published_history']['parent_publication']['sha256']:
            if runner.read(target)!=value:raise ValueError('Concurrent publication change; retain full judgment and sync later')
        else:
            temp=target.with_suffix('.original_pixels.tmp');dump(temp,value);os.replace(temp,target)
        if column=='Mechanic':execution.verify_publication(workspace,root.name);execution.rebuild_tables(workspace)
        else:runtime.verify_publication(workspace,root.name);runtime.rebuild_tables(workspace)
        from . import two_column_sync
        receipt=two_column_sync.sync(workspace,root.name,column,workspace_locked=True)
    dump(root/'engineering/original_pixel_real_acceptance.json',dict(version=VERSION,column=column,
        status=column.upper()+'_ORIGINAL_PIXELS_REAL_E2E_ACCEPTED',production_bindings=production(),
        publication_status='SCORED_PENDING_AUDIT',new_recording=False,complete_original_sources_and_pixels=True,
        independent_tasks=len(auth['tasks']),score=result['score'],qualified_published_replacement=True,
        synchronization_status=receipt['status']))
    print(json.dumps(dict(stage='ORIGINAL_PIXEL_PUBLISHED_REPLACEMENT',identity=root.name,column=column,
        score=result['score'],sync=receipt['status'])),flush=True)
    from . import mechanic_v3_cache, gameness_v3_cache
    (mechanic_v3_cache if column=='Mechanic' else gameness_v3_cache).run(workspace,root)
    return value


def verify_published_final_capacity(root, repair_path, repair):
    """One exact literal change after a measured published-parent capacity failure."""
    value=runner.read(root/PUBLISHED_FINAL);auth=runner.read(root/AUTH)
    if (value.get('version')!='original-pixel-published-final-capacity.v1'
            or value.get('authorization')!=bound(root/AUTH)
            or value.get('repair')!=bound(repair_path)
            or value.get('after_source_bindings')!=production()
            or value.get('maximum_new_capacity_calls_per_task')!=1
            or not repair.get('published_history')):
        raise ValueError('Exact bounded published final capacity continuation required')
    before=repair['after_source_bindings'];after=value['after_source_bindings']
    changed={n for n in set(before)|set(after) if before.get(n)!=after.get(n)}
    allowed={str(Path(__file__).with_name(n).resolve()) for n in ['persistent_original_pixel_recovery.py','two_column_sync.py']}
    if not changed or not changed<=allowed or set(value['old_producers'])!=changed:
        raise ValueError('Published final continuation only changes exact transport producers')
    for n in changed:
        if sha(verify_binding(value['old_producers'][n]))!=before[n]:
            raise ValueError('Exact pre-capacity producer archive required')
    reg=runner.read(verify_binding(value['regression']))
    if reg.get('exit_code')!=0 or reg.get('tests_passed',0)<1:
        raise ValueError('Passed published final capacity regression required')
    if set(value['tasks'])!={t['task'] for t in auth['tasks']}:
        raise ValueError('Every original independent capacity task required')
    from .gameness_v4_final_literal import prepare
    for task in auth['tasks']:
        item=value['tasks'][task['task']];gate_path=verify_binding(item['parent_capacity_gate'])
        if gate_path!=root/'capacity_calls'/task['task']/'capacity_gate.json':
            raise ValueError('Exact failed parent capacity path required')
        gate=runner.read(gate_path)
        if (gate.get('passed') is not False or gate.get('scoring_calls')!=0
                or gate['required_with_output_and_margin']<=gate['window']
                or gate.get('parent_failure')!=task['parent_failure']):
            raise ValueError('Measured full original-pixel overflow required')
        prompt=verify_binding(item['original_prompt']).read_text()
        prepare(dict(final_literal_transport=item['transport']),prompt)
    return value


OUTPUT_ERROR = 'Trigger outside common frozen Gameness alternatives'
OUTPUT_FEEDBACK = """
OUTPUT CONSISTENCY VALIDATION: for each unchanged Gameness check, basic_function.trigger_mode
must be one of that exact check's frozen permitted_trigger_modes, even when UNOBSERVED.
Do not borrow a mode from a different check or change the contract. An allowed mode
is not proof of an observed effect. Judge all original checks independently using
all original sources and images; where runtime is not established, truthfully report
UNOBSERVED. Do not invent actions, observations, counterexamples or citations. All
original validators and 10/50/100 rules remain unchanged; no score or tier is requested.
"""


def evaluate_response(root,column,c,raw):
    if column=='Mechanic':
        from . import mechanic_v3 as outcome
        return outcome.evaluate(root,c['proto'],c['selected'],c['rules'],c['contract'],raw,c['specs'])
    from . import gameness_v3_original as original_policy, gameness_v4 as policy
    return original_policy.evaluate(root,c['proto'],c['selected'],c['rules'],c['contract'],raw,c['specs'],c['review'],scoring_policy=policy)


def verify_output_consistency(root):
    """Qualify one failed native-pixel output, not a repeat of a valid score.

    The original authorization, source-only fork, response, measured capacity,
    rejected output and all request bytes stay immutable. Only this exact
    producer may evolve; no claim or attempt counter is reset.
    """
    root=Path(root);value=runner.read(root/OUTPUT_CONSISTENCY)
    auth=runner.read(root/AUTH);repair_path=verify_binding(auth['repair'])
    repair=runner.read(repair_path)
    from .gameness_v3_runtime import production_bindings
    after=production();before=value['before_source_bindings']
    producer=str(Path(__file__).resolve())
    changed={p for p in set(before)|set(after) if before.get(p)!=after.get(p)}
    if (value.get('version')!='original-pixel-frozen-output-continuation.v1'
            or auth.get('column')!='Gameness'
            or value.get('authorization')!=bound(root/AUTH)
            or value.get('repair')!=bound(repair_path)
            or value.get('after_source_bindings')!=after
            or before!=repair['after_source_bindings']
            or changed!={producer}
            or value.get('maximum_new_scoring_calls_per_task')!=1
            or value.get('maximum_new_capacity_calls_per_task')!=1
            or value.get('error')!=OUTPUT_ERROR
            or value.get('feedback_sha256')!=hashlib.sha256(OUTPUT_FEEDBACK.encode()).hexdigest()
            or sha(verify_binding(value['old_producer']))!=before[producer]):
        raise ValueError('Exact one-shot frozen-output producer and failed parent required')
    reg=runner.read(verify_binding(value['regression']))
    if reg.get('exit_code')!=0 or reg.get('tests_passed',0)<1:
        raise ValueError('Passed native-pixel frozen-output regressions required')
    if (root/PUBLISHED_FINAL).exists() or len(auth['tasks'])!=1:
        raise ValueError('This correction only covers the independently calibrated original final')
    task=auth['tasks'][0];name=task['task'];call=root/'model_calls'/name;req=root/'requests'/name
    expected={str(p.resolve()):sha(p) for folder in (call,req) for p in folder.rglob('*') if p.is_file()}
    if (value.get('parent_materials')!=expected or (call/'accepted_response.json').exists()
            or (root/'judgments'/(name+'.json')).exists()):
        raise ValueError('Never correct accepted output or changed failed request material')
    failure=runner.read(call/'validation_error.json')
    if (failure.get('phase')!='original_pixel_response_validation'
            or failure.get('exception')!=OUTPUT_ERROR
            or failure.get('response_sha256')!=sha(call/'response.json')):
        raise ValueError('Exact preserved trigger-mode output failure required')
    _,old=original(root,'Gameness');c=context(root.parent.parent,root,'Gameness',old,{'task':old['task']})
    token=_READONLY_PRODUCTION.set(before)
    try:
        _verify_delivery(root,name,runner.read(req/'actual_delivery.json'))
    finally:_READONLY_PRODUCTION.reset(token)
    try:evaluate_response(root,'Gameness',c,runner.read(call/'response.json'))
    except ValueError as error:
        if str(error)!=OUTPUT_ERROR:raise ValueError('Current validator differs from failed output') from error
    else:raise ValueError('Response now valid; reuse without a new model call')
    return value


def delivery_tasks(root,auth):
    """Derive a separately named one-shot task; the parent auth stays untouched."""
    if (Path(root)/SOURCE_REPACK).exists():
        return auth['tasks']+[source_repack_intake(root,allow_call=False)]
    if not (Path(root)/OUTPUT_CONSISTENCY).exists():return auth['tasks']
    # The old parent remains addressable while its delivery is being verified.
    value=runner.read(Path(root)/OUTPUT_CONSISTENCY)
    if value.get('authorization')!=bound(Path(root)/AUTH):
        raise ValueError('Exact original-pixel parent authorization required')
    task=copy.deepcopy(auth['tasks'][0])
    task['task']+='_frozen_output_'+sha(Path(root)/OUTPUT_CONSISTENCY)[:12]
    task['parent_failure']=bound(Path(root)/'model_calls'/auth['tasks'][0]['task']/'validation_error.json')
    task['frozen_output_consistency']=bound(Path(root)/OUTPUT_CONSISTENCY)
    return auth['tasks']+[task]


def active_tasks(root,auth):
    if (Path(root)/SOURCE_REPACK).exists():
        if (Path(root)/COMPLETED_HISTORY).exists():
            tasks=delivery_tasks(root,auth)[-1:]
            for task in tasks:
                verify_delivery(root,task['task'],runner.read(Path(root)/'requests'/task['task']/'actual_delivery.json'))
            return tasks
        return [source_repack_intake(root,allow_call=True)]
    if not (Path(root)/OUTPUT_CONSISTENCY).exists():return auth['tasks']
    tasks=delivery_tasks(root,auth)[-1:]
    if (Path(root)/COMPLETED_HISTORY).exists():
        for task in tasks:
            verify_delivery(root,task['task'],runner.read(Path(root)/'requests'/task['task']/'actual_delivery.json'))
    else:verify_output_consistency(root)
    return tasks



def verify_source_repack(root):
    """One exact complete-source representation change after two measured gates.

    This does not edit the old authorization, source, failed capacity calls or
    their budgets. New source ACKs carry no score; original-pixel final capacity
    and the unchanged scoring validator remain mandatory.
    """
    root=Path(root);value=runner.read(root/SOURCE_REPACK)
    if value.get('version')=='original-pixel-single-failure-source-repack.v2':
        return verify_single_failure_source_repack(root,value)
    pixel_auth=runner.read(root/AUTH);old_path=verify_binding(pixel_auth['original_authorization'])
    old=runner.read(old_path);prior_path=verify_binding(value['parent_final_continuation'])
    prior=runner.read(prior_path);before=value['before_source_bindings'];after=production()
    producer=str(Path(__file__).resolve())
    changed={p for p in set(before)|set(after) if before.get(p)!=after.get(p)}
    if (value.get('version')!='original-pixel-complete-source-repack.v1'
            or value.get('identity')!=root.name or value.get('column')!='Gameness'
            or pixel_auth.get('column')!='Gameness' or len(pixel_auth['tasks'])!=1
            or value.get('authorization')!=bound(root/AUTH)
            or prior_path!=root/PUBLISHED_FINAL or before!=prior['after_source_bindings']
            or value.get('after_source_bindings')!=after or changed!={producer}
            or sha(verify_binding(value['old_producer']))!=before[producer]
            or value.get('maximum_new_capacity_calls')!=1 or value.get('maximum_new_scoring_calls')!=1
            or value.get('maximum_prompt_bytes')!=1000000 or value.get('chunk_bytes')!=780000
            or value.get('original_claims_failures_and_counts_preserved') is not True):
        raise ValueError('Exact bounded complete-source repack continuation required')
    regression=runner.read(verify_binding(value['regression']))
    if regression.get('exit_code')!=0 or regression.get('tests_passed',0)<1:
        raise ValueError('Passed source-repack regressions required')
    repair_path=verify_binding(pixel_auth['repair']);repair=runner.read(repair_path)
    token=_READONLY_PRODUCTION.set(before)
    try:verify_published_final_capacity(root,repair_path,repair)
    finally:_READONLY_PRODUCTION.reset(token)
    # Bind both real failures, never merely a local tokenizer estimate.
    if len(value['failed_capacity_gates'])!=2:
        raise ValueError('Both exact measured original-pixel capacity failures required')
    original_task=pixel_auth['tasks'][0]['task']
    expected={root/'capacity_calls'/original_task/'capacity_gate.json',
              root/'capacity_calls'/(original_task+'_published_final_literal')/'capacity_gate.json'}
    paths={verify_binding(item) for item in value['failed_capacity_gates']}
    if paths!=expected:raise ValueError('Exact parent capacity lineage required')
    for path in paths:
        gate=runner.read(path)
        if (gate.get('passed') is not False or gate.get('scoring_calls')!=0
                or gate['required_with_output_and_margin']<=gate['window']):
            raise ValueError('Real non-scoring complete-original capacity overflow required')
    failures=[verify_binding(item) for item in value['parent_failures']]
    if len(failures)!=2 or any('Original-pixel complete final capacity insufficient' not in
            runner.read(p).get('error','') for p in failures):
        raise ValueError('Exact two retained original-pixel capacity failures required')
    if (root/'model_calls'/original_task/'accepted_response.json').exists():
        raise ValueError('Repack cannot rerun an accepted original-pixel judgment')
    from . import gameness_v4_persistent_literal as literal, gameness_v4_sequential_lines as sequential
    info=value['literal_transport'];wire_path=Path(info['wire_path']);wire=wire_path.read_text()
    body_path=Path(old['original_body_path']);body=body_path.read_text()
    if (info.get('version')!=sequential.VERSION or sha(wire_path)!=info.get('wire_sha256')
            or sha(body_path)!=old['original_body_sha256']
            or literal.decode_wire(wire,info['version'])!=body
            or value.get('maximum_new_intake_calls')!=len(transport.parts(wire))):
        raise ValueError('Every original source byte and exact physical line must round trip')
    if len(wire.encode())>=len(Path(old['literal_transport']['wire_path']).read_bytes()):
        raise ValueError('Substantively different smaller complete-source representation required')
    # Rebuild the final prompt solely with the explicit new decoding notice.
    workspace=Path(value['workspace']).resolve()
    if workspace/'runs'/root.name!=root.resolve():raise ValueError('Exact original Gameness owner required')
    derived=dict(old,literal_transport=info)
    packet=transport.packet(workspace,root,derived,persist=False)
    from .gameness_v4_final_literal import prepare
    prepare(dict(final_literal_transport=value['final_literal_transport']),packet[-2])
    return value


def verify_single_failure_source_repack(root, value):
    """A distinct complete-source representation after one exact real failed probe.

    Numeric overflow and pre-telemetry context rejection are separate causes.
    Neither grants an unchanged retry, scoring credit, larger limit or new record.
    """
    from . import gameness_v4_persistent_literal as literal
    from .gameness_v4_final_literal import prepare, probe_prompt, ACK, SCHEMA
    from .gameness_v4_persistent_capacity import OUTPUT_RESERVE, OVERHEAD_MARGIN
    root=Path(root).resolve();auth=runner.read(root/AUTH)
    repair_path=verify_binding(auth['repair']);repair=runner.read(repair_path)
    old_path=verify_binding(auth['original_authorization']);old=runner.read(old_path)
    before=value['before_source_bindings'];after=production();producer=str(Path(__file__).resolve())
    if (value.get('version')!='original-pixel-single-failure-source-repack.v2'
            or value.get('identity')!=root.name or value.get('column')!='Gameness'
            or auth.get('column')!='Gameness' or len(auth['tasks'])!=1
            or value.get('authorization')!=bound(root/AUTH)
            or before!=repair.get('after_source_bindings')
            or value.get('after_source_bindings')!=after
            or {p for p in set(before)|set(after) if before.get(p)!=after.get(p)}!={producer}
            or sha(verify_binding(value['old_producer']))!=before[producer]
            or value.get('maximum_new_capacity_calls')!=1 or value.get('maximum_new_scoring_calls')!=1
            or value.get('maximum_prompt_bytes')!=1000000 or value.get('chunk_bytes')!=780000
            or value.get('original_claims_failures_and_counts_preserved') is not True
            or value.get('parent_failures')!=[value.get('parent_failure')]):
        raise ValueError('Exact bounded single-failure complete-source continuation required')
    reg=runner.read(verify_binding(value['regression']))
    if reg.get('exit_code')!=0 or reg.get('tests_passed',0)<1:
        raise ValueError('Passed corresponding source continuation regression required')
    token=_READONLY_PRODUCTION.set(before)
    try:
        verify_old_auth(root,old_path,old,repair)
        verify_published_parent(root,repair)
    finally:_READONLY_PRODUCTION.reset(token)
    workspace=Path(value['workspace']).resolve()
    if root!=workspace/'runs'/root.name:
        raise ValueError('Exact original Gameness publication owner required')
    task=auth['tasks'][0];name=task['task']
    folder=root/'capacity_calls'/(name+('_exact_final' if task.get('final_literal_transport') else ''))
    if (root/'model_calls'/name).exists() or (root/'judgments'/(name+'.json')).exists():
        raise ValueError('New complete-source intake cannot repeat an original-pixel score')
    required={'invocation.json','prompt.txt','schema.json','rpc_requests.jsonl','rpc_events.jsonl'}
    artifacts=value['failed_call_artifacts']
    actual={str(p):sha(p) for p in folder.rglob('*') if p.is_file()}
    if (not required<={Path(p).name for p in artifacts} or artifacts!=actual):
        raise ValueError('Every real failed probe artifact must remain exact')
    values=transport.packet(workspace,root,old,persist=False)
    body,images,schema,logical=values[6],values[7],values[8],values[9]
    submitted=prepare(dict(final_literal_transport=task['final_literal_transport']),logical) if task.get('final_literal_transport') else logical
    expected_schema=capacity_schema(schema) if task.get('final_literal_transport') else SCHEMA
    expected_prompt=probe_prompt(submitted+(('\nINERT ORIGINAL OUTPUT SCHEMA:\n'+json.dumps(schema,ensure_ascii=False)) if not task.get('final_literal_transport') else ''))
    inv=runner.read(folder/'invocation.json')
    if (inv.get('model_requested')!='gpt-6.1-sol' or inv.get('attempt')!=1
            or (folder/'prompt.txt').read_text()!=expected_prompt
            or runner.read(folder/'schema.json')!=expected_schema):
        raise ValueError('Exact original full-context non-scoring probe required')
    requests=list(rows(folder/'rpc_requests.jsonl'));forks=[v['params'] for v in requests if v.get('method')=='thread/fork']
    starts=[v['params'] for v in requests if v.get('method')=='turn/start']
    expected=[dict(type='text',text=expected_prompt)]+[dict(type='localImage',path=str(Path(p).resolve()),detail='original') for p in images]
    if (len(forks)!=1 or forks[0].get('threadId')!=task['parent_session']
            or forks[0].get('lastTurnId')!=task['fork_through']
            or len(starts)!=1 or starts[0].get('input')!=expected
            or starts[0].get('outputSchema')!=expected_schema):
        raise ValueError('Failed probe must retain original source fork and every native image')
    failure_path=verify_binding(value['parent_failure']).resolve()
    if failure_path.parent!=root/'failures':
        raise ValueError('Exact retained failure in original run required')
    failure=runner.read(failure_path)
    if value.get('cause')=='MEASURED_COMPLETE_CONTEXT_OVERFLOW':
        gate=runner.read(folder/'capacity_gate.json')
        if (inv.get('exit_code')!=0 or runner.read(folder/'response.json')!=ACK
                or gate.get('passed') is not False or gate.get('scoring_calls')!=0
                or gate.get('output_reserve')!=OUTPUT_RESERVE or gate.get('margin')!=OVERHEAD_MARGIN
                or gate.get('parent_failure')!=task['parent_failure']
                or gate.get('original_pixel_count')!=len(images)
                or gate['required_with_output_and_margin']!=gate['actual']['input_tokens']+OUTPUT_RESERVE+OVERHEAD_MARGIN
                or gate['required_with_output_and_margin']<=gate['window']
                or 'Original-pixel complete final capacity insufficient' not in failure.get('error','')):
            raise ValueError('One exact measured non-scoring complete-context overflow required')
    elif value.get('cause')=='SERVER_CONTEXT_REJECTION_BEFORE_TELEMETRY':
        message='Your input exceeds the context window of this model'
        if (inv.get('status')!='HARNESS_ERROR' or message not in inv.get('error','')
                or message not in failure.get('error','')
                or any((folder/p).exists() for p in ['response.json','capacity_gate.json'])):
            raise ValueError('Exact pre-telemetry server context rejection required')
    else:raise ValueError('Unknown single-failure source-repack cause')
    info=value['literal_transport'];wire=Path(info['wire_path']).read_text();oldwire=Path(old['literal_transport']['wire_path']).read_text()
    if (sha(Path(info['wire_path']))!=info.get('wire_sha256')
            or sha(Path(old['original_body_path']))!=old['original_body_sha256']
            or literal.decode_wire(wire,info['version'])!=body
            or value.get('maximum_new_intake_calls')!=len(transport.parts(wire))
            or len(wire.encode())>=len(oldwire.encode())):
        raise ValueError('Substantively smaller source wire must recover every original byte')
    import tiktoken
    enc=tiktoken.get_encoding('o200k_base')
    if len(enc.encode(oldwire,disallowed_special=()))-len(enc.encode(wire,disallowed_special=()))<1024:
        raise ValueError('A substantive source token representation change is required')
    packet=transport.packet(workspace,root,dict(old,literal_transport=info),persist=False)
    prepare(dict(final_literal_transport=value['final_literal_transport']),packet[-2])
    return value


def source_repack_intake(root,*,allow_call):
    """Send every source byte in a new, bounded, fully retained ACK-only prefix."""
    root=Path(root);value=verify_source_repack(root)
    auth=runner.read(root/AUTH);old=runner.read(verify_binding(auth['original_authorization']))
    c=context(Path(value['workspace']),root,'Gameness',old,{'task':old['task']})
    prompts=c['intake_prompts'];prefix='source_repack_'+sha(root/SOURCE_REPACK)[:12]
    name=auth['tasks'][0]['task']+'_'+prefix;folders=[];session=None
    for index,(prompt,part) in enumerate(zip(prompts,c['wire_parts']),1):
        folder=root/'source_intakes'/prefix/f'intake_{index:02d}';folders.append(folder)
        digest=hashlib.sha256(part.encode()).hexdigest();ack=dict(chunk=index,sha256=digest)
        schema=codex.obj({'chunk':{'type':'integer','enum':[index]},'sha256':{'type':'string','enum':[digest]}})
        if not folder.exists():
            if not allow_call:raise ValueError('All complete-source intake ACKs must already be accepted')
            result,sid=native.rpc_invoke(folder,root/'input',prompt,schema,[],model='gpt-6.1-sol',session=session)
            if result!=ack:raise ValueError('Exact non-scoring source receipt required')
        inv=runner.read(folder/'invocation.json');sid=inv.get('thread')
        if (inv.get('exit_code')!=0 or inv.get('attempt')!=1 or inv.get('model_requested')!='gpt-6.1-sol'
                or not sid or (session is not None and session!=sid)
                or runner.read(folder/'response.json')!=ack or runner.read(folder/'schema.json')!=schema
                or (folder/'prompt.txt').read_text()!=prompt):
            raise ValueError('Exact one-shot complete-source intake changed or failed; no unchanged retry')
        rpc=list(rows(folder/'rpc_requests.jsonl'))
        starts=[v['params'] for v in rpc if v.get('method')=='turn/start']
        sessions=[v for v in rpc if v.get('method') in {'thread/start','thread/resume','thread/fork'}]
        if (len(starts)!=1 or starts[0]['input']!=[dict(type='text',text=prompt)]
                or starts[0]['outputSchema']!=schema or len(sessions)!=1
                or sessions[0]['method']!=('thread/resume' if session else 'thread/start')
                or (session and sessions[0]['params'].get('threadId')!=session)):
            raise ValueError('Actual source-only RPC sequence must retain every original text part')
        session=sid
    path=root/SOURCE_INTAKE
    snapshot=root/'engineering'/(prefix+'_source_session.jsonl')
    if not snapshot.exists():
        if not allow_call:raise ValueError('Immutable successful complete-source session snapshot required')
        transport.save(snapshot,transport.session_path(session).read_bytes())
    proof=transport.verify_session(snapshot,session,prompts,'gpt-6.1-sol')
    boundary=intake_boundary(snapshot,prompts,'gpt-6.1-sol')
    task=dict(auth['tasks'][0],task=name,parent_session=session,fork_through=boundary,
        parent_snapshot=bound(snapshot),intake_prompt_sha256=[hashlib.sha256(p.encode()).hexdigest() for p in prompts],
        parent_failure=value['parent_failures'][-1],source_repack=bound(root/SOURCE_REPACK))
    materials={str(p):sha(p) for folder in folders for p in folder.rglob('*') if p.is_file()}
    materials[str(snapshot)]=sha(snapshot)
    receipt=dict(version='original-pixel-complete-source-intake.v1',continuation=bound(root/SOURCE_REPACK),
        task=task,complete_original_roundtrip=True,ordered_session_proof=proof,immutable_materials=materials,
        scoring_calls=0,source_intake_calls=len(prompts))
    if path.exists():
        if runner.read(path)!=receipt:raise ValueError('Immutable complete-source ACK evidence changed')
    elif allow_call:runner.exclusive_json(path,receipt)
    else:raise ValueError('Complete-source intake receipt required')
    return task
