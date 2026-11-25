"""One parent-bound continuation after a retained persistent-session compaction.

Every original source/context byte is recovered by the existing flat literal
inverse. Native pixels, criterion schema, validators and frozen limits do not
change. Old authorization, failed calls and counts remain immutable. The new
wire must materially shrink; actual retained telemetry gates the final call.
"""
from pathlib import Path
import argparse
import fcntl
import json
import time
from . import gameness_v4_persistent_text as base
from . import gameness_v4_persistent_literal as literal
from . import gameness_v3_runtime as runtime, gameness_v4 as policy
from . import gameness_v3_original as original, gameness_v3_static as static
from . import mechanic_v3_runner as runner, mechanic_v3_execution as execution
from . import evaluation_model_profile as models, batch, codex
from .protocol import dump, sha

VERSION = 'gameness-v4-persistent-capacity-continuation.v1'
AUTH = 'engineering/gameness_persistent_capacity_continuation.json'
OUTPUT_RESERVE = 16384
OVERHEAD_MARGIN = 4096


def telemetry(path):
    """Read real CLI usage; an invocation flag is never capacity evidence."""
    result=[]
    for line in Path(path).read_text().split('\n'):
        if not line.strip(): continue
        value=json.loads(line);p=value.get('payload',{})
        if value.get('type')=='event_msg' and p.get('type')=='token_count':
            info=p.get('info')
            if info and isinstance(info.get('model_context_window'),int):
                usage=info.get('last_token_usage',{})
                if isinstance(usage.get('input_tokens'),int):
                    result.append(dict(input_tokens=usage['input_tokens'],
                        output_tokens=usage.get('output_tokens',0),
                        total_tokens=info.get('total_token_usage',{}).get('total_tokens',0),
                        window=info['model_context_window']))
    if not result:raise ValueError('Actual retained capacity telemetry required')
    return result


def parent_capacity(path):
    """Measure final request overhead from the refused compacted parent only.

    A parent summary is diagnostic capacity data, NEVER scoring evidence. The
    continuation must deliver the full original again in an uncompacted thread.
    """
    rows=[json.loads(s) for s in Path(path).read_text().split('\n') if s.strip()]
    positions=[i for i,v in enumerate(rows) if 'compact' in str(v.get('type','')).lower()]
    if len(positions)!=1:raise ValueError('Exactly one retained parent compaction required')
    residual=None;final=None;window=None
    for value in rows[positions[0]+1:]:
        p=value.get('payload',{})
        if value.get('type')!='event_msg' or p.get('type')!='token_count':continue
        info=p.get('info') or {};usage=info.get('last_token_usage') or {}
        if usage.get('input_tokens')==0 and residual is None:
            residual=usage.get('total_tokens')
        elif residual is not None and usage.get('input_tokens',0)>0:
            final=usage['input_tokens'];window=info.get('model_context_window');break
    if (not isinstance(residual,int) or not isinstance(final,int) or not isinstance(window,int)
            or not 0<residual<final<window):
        raise ValueError('Complete post-compaction diagnostic usage required')
    return dict(parent_summary_tokens=residual,parent_final_input_tokens=final,
        final_increment_upper_bound=final-residual+OVERHEAD_MARGIN,
        observed_context_window=window,output_reserve=OUTPUT_RESERVE)


def capacity_gate(session,capacity,final_reduction=0):
    last=telemetry(session)[-1]
    # No configured context increase, no compaction relaxation, no estimated
    # tokenizer alone. Fail before final if the actual intake is still too big.
    window=min(last['window'],capacity['observed_context_window'])
    if (not isinstance(final_reduction,int) or isinstance(final_reduction,bool)
            or not 0<=final_reduction<capacity['final_increment_upper_bound']):
        raise ValueError('Invalid measured final capacity reduction')
    required=last['input_tokens']+last['output_tokens']+capacity['final_increment_upper_bound']-final_reduction+OUTPUT_RESERVE
    if last['input_tokens']<=0 or required>window:
        raise ValueError('Actual persistent intake leaves insufficient complete-final capacity: '+str((required,window)))
    result=dict(actual_intake=last,required_with_final_and_reserve=required,
        conservative_window=window,remaining_margin=window-required)
    if final_reduction:result['measured_final_reduction_after_margin']=final_reduction
    return result


def authorization(root):
    value=runner.read(root/AUTH)
    if (value.get('version')!=VERSION or value.get('identity')!=root.name
            or value.get('maximum_attempts')!=1 or value.get('maximum_prompt_bytes')!=base.MAX_PROMPT
            or value.get('maximum_images')!=100):
        raise ValueError('Capacity continuation identity or frozen limits changed')
    from . import gameness_v4_saved_capacity_producers as saved
    from . import gameness_v4_saved_capacity_producers_v2 as saved_v2
    retained = saved if saved.matches(root/AUTH) else saved_v2
    preserved = retained.matches(root/AUTH)
    if preserved: retained.verified_bindings(root/AUTH,value['bindings'])
    for p,d in (() if preserved else value['bindings'].items()):
        if sha(Path(p))!=d:
            from .gameness_v4_producer_history import verify
            from . import gameness_v4_capacity_probe_resume as resume
            if (root/resume.RECEIPT).exists():
                resume.verify_producer(root,root/AUTH,Path(p),d)
            else:
                verify(root, root/AUTH, Path(p), d)
    parent=base.authorization(root)
    if value['parent_task']!=parent['task'] or value['original_body_sha256']!=parent['original_body_sha256']:
        raise ValueError('Capacity continuation is not the exact retained parent')
    return value


def authorize(workspace,root,repair):
    dest=root/AUTH
    if dest.exists():
        value=authorization(root)
        if value['repair']!=str(repair):raise ValueError('One immutable capacity continuation per parent')
        return value
    d=runner.read(repair);code=Path(__file__).resolve().parent
    required={str(code/n) for n in ['gameness_v4_persistent_capacity.py','gameness_v4_runtime.py','gameness_v4_bounded_text.py']}
    if (d.get('classification')!='NON_SCORING_PERSISTENT_CAPACITY_CONTINUATION'
            or not d.get('root_cause') or not required<=d.get('after_source_bindings',{}).keys()):
        raise ValueError('Substantive capacity repair and complete production bindings required')
    for p,h in d['after_source_bindings'].items():
        if sha(Path(p))!=h:raise ValueError('Capacity repair producer changed')
    parent=base.authorization(root)
    if not parent.get('literal_transport') or d.get('parent_task')!=parent['task']:
        raise ValueError('Only this retained failed flat-literal parent is supported')
    call=root/'model_calls'/parent['task'];failure=Path(d['parent_failure']).resolve()
    if (failure.parent!=(root/'failures').resolve()
            or 'Retained conversation contains compaction' not in runner.read(failure).get('error','')
            or (call/'accepted_response.json').exists()
            or list((root/'judgments').glob('gameness_v4_*.json'))
            or runtime.publication_path(workspace,root.name).exists()):
        raise ValueError('A retained compaction failure with no complete accepted result is required')
    first=call/'persistent_turns/intake_01/events.jsonl';sid=base.event_values(first)
    session=base.session_path(sid);capacity=parent_capacity(session)
    # Check every old intake and final really belong to the same parent session.
    oldbody=Path(parent['original_body_path']).read_bytes().decode()
    oldwire=literal.complete_wire(parent,oldbody)
    for i,_ in enumerate(base.parts(oldwire),1):
        if base.event_values(call/'persistent_turns'/f'intake_{i:02d}'/'events.jsonl')!=sid:
            raise ValueError('Parent intake session lineage changed')
    if base.event_values(call/'persistent_turns/final/events.jsonl')!=sid:
        raise ValueError('Parent final session lineage changed')
    wire_path=Path(d['wire_path']).resolve();wire=wire_path.read_bytes().decode()
    wire_version=d.get('literal_version',literal.VERSION)
    if literal.decode_wire(wire,wire_version)!=oldbody or len(wire.encode())>len(oldwire.encode())*0.97:
        raise ValueError('Materially smaller exact inverse of ALL original text required')
    files=[repair,root/base.AUTH,failure,first,session,wire_path,Path(parent['original_body_path'])]
    files.extend(call.rglob('*'));files.extend(Path(p) for p in d['after_source_bindings'])
    for old in d.get('before_source_bindings',{}).values():
        p=Path(old['archive'])
        if sha(p)!=old['sha256']:raise ValueError('Retained before producer differs')
        files.append(p)
    name=parent['task']+'_capacity1'
    auth=dict(parent,version=VERSION,identity=root.name,parent_task=parent['task'],task=name,
        repair=str(repair),repair_sha256=sha(repair),maximum_attempts=1,maximum_images=100,
        literal_transport=dict(version=wire_version,wire_path=str(wire_path),wire_sha256=sha(wire_path)),
        capacity=capacity,original_failures_claims_and_counts_preserved=True)
    if d.get('final_literal_transport'):
        from . import gameness_v4_final_literal as final_literal
        supplied=d['final_literal_transport'];path=Path(supplied['wire_path']).resolve()
        if supplied.get('version')!=final_literal.VERSION:
            raise ValueError('Explicit exact final literal version required')
        auth['final_literal_transport']=dict(version=final_literal.VERSION,
            wire_path=str(path),wire_sha256=sha(path),parent_prompt=str(call/'prompt.txt'),
            parent_prompt_sha256=sha(call/'prompt.txt'))
        files.append(path)
    # Packet construction is read-only until all parent and full-image checks pass.
    packet=base.packet(workspace,root,auth,persist=False)
    if packet[6]!=oldbody:raise ValueError('Continuation changed complete original body')
    if auth.get('final_literal_transport'):
        from .gameness_v4_final_literal import prepare
        prepare(auth,packet[-2])
    files.extend(packet[7]);files.extend(root/s['path'] for s in packet[-1]['complete_author_sources'])
    for text in base.parts(wire):
        if len(base.chunk_prompt(1,99,text).encode())>base.MAX_PROMPT:
            raise ValueError('Frozen per-turn prompt limit exceeded')
    auth['bindings']={str(p.resolve()):sha(p) for p in files if p.is_file()}
    runner.exclusive_json(dest,auth)
    return auth


def packet(workspace,root,auth):
    data=list(base.packet(workspace,root,auth,persist=False));actual=data[-1];name=auth['task']
    req=root/'requests'/name;ref=req/'persistent_capacity/equivalence.json'
    base.save(ref.parent/'original_body.txt',data[6].encode())
    proof=dict(version=VERSION,authorization=dict(path=str(root/AUTH),sha256=sha(root/AUTH)),
        original_body_sha256=auth['original_body_sha256'],parent_task=auth['parent_task'],
        all_original_text_retained=True,native_images_unchanged=True,
        bindings={str(ref.parent/'original_body.txt'):sha(ref.parent/'original_body.txt')})
    if auth.get('final_literal_transport'):
        from . import gameness_v4_final_literal as final_literal
        original_prompt=data[-2];data[-2]=final_literal.prepare(auth,original_prompt)
        base.save(ref.parent/'original_final_prompt.txt',original_prompt.encode())
        proof['bindings'].update({str(ref.parent/'original_final_prompt.txt'):sha(ref.parent/'original_final_prompt.txt'),
            auth['final_literal_transport']['wire_path']:auth['final_literal_transport']['wire_sha256']})
        proof['final_literal_transport']=auth['final_literal_transport']
        actual['prompt_sha256']=base.digest(data[-2].encode());actual['prompt_bytes']=len(data[-2].encode())
        dump(root/'validation_history'/(name+'.actual_delivery.json'),actual)
    base.save(ref,(json.dumps(proof,ensure_ascii=False,indent=2)+'\n').encode())
    actual['runtime_text_chunks']=dict(version=VERSION,path=str(ref.relative_to(root)),sha256=sha(ref))
    for filename,value in [('actual_delivery.json',actual),('selected_manifest.json',data[2]),
            ('citation_rules.json',data[3]),('original_schema.json',original.runtime_schema(data[1],data[3],data[2]))]:
        dump(req/filename,value)
    return data


def verify_delivery(root,name,actual=None):
    root=Path(root);auth=authorization(root)
    if name!=auth['task']:raise ValueError('Exact capacity continuation task required')
    actual=actual if actual is not None else runner.read(root/'requests'/name/'actual_delivery.json')
    reference=actual.get('runtime_text_chunks',{});ref=root/reference.get('path','')
    if (reference.get('version')!=VERSION or not ref.resolve().is_relative_to((root/'requests'/name).resolve())
            or sha(ref)!=reference.get('sha256')):
        raise ValueError('Capacity complete-text reference changed')
    proof=runner.read(ref)
    if proof.get('authorization')!=dict(path=str(root/AUTH),sha256=sha(root/AUTH)):
        raise ValueError('Capacity authorization proof changed')
    for p,h in proof['bindings'].items():
        if sha(Path(p))!=h:raise ValueError('Original retained text changed')
    body=(ref.parent/'original_body.txt').read_bytes().decode();chunks=base.delivery_parts(auth,body)
    call=root/'model_calls'/name;prompts=[];session=None
    for index,text in enumerate(chunks,1):
        turn=call/'persistent_turns'/f'intake_{index:02d}';prompt=base.chunk_prompt(index,len(chunks),text)
        if ((turn/'prompt.txt').read_bytes().decode()!=prompt
                or runner.read(turn/'response.json')!=dict(chunk=index,sha256=base.digest(text.encode()))):
            raise ValueError('Every exact original intake acknowledgement required')
        sid=base.event_values(turn/'events.jsonl')
        if session is None:session=sid
        elif sid!=session:raise ValueError('Capacity original text split across threads')
        prompts.append(prompt)
    final=(call/'prompt.txt').read_bytes().decode()
    if sha(call/'prompt.txt')!=actual['prompt_sha256'] or base.event_values(call/'events.jsonl')!=session:
        raise ValueError('Capacity final is outside complete original conversation')
    prompts.append(final)
    retained=base.verify_session(call/'persistent_session.jsonl',session,prompts,models.model_for(root,'judge'))
    literal.verify_invocations(call,auth,len(chunks))
    reduction=0
    if auth.get('final_literal_transport'):
        from . import gameness_v4_final_literal as final_literal
        if proof.get('final_literal_transport')!=auth['final_literal_transport']:
            raise ValueError('Final literal proof is not bound to this continuation')
        original_prompt=(ref.parent/'original_final_prompt.txt').read_bytes().decode()
        if final_literal.prepare(auth,original_prompt)!=final:
            raise ValueError('Complete original final prompt was not delivered exactly')
        # Rebuild from the original contracts/review/schema, never trust a detached inverse.
        if base.packet(root.parent.parent,root,auth,persist=False)[-2]!=original_prompt:
            raise ValueError('Reconstructed final prompt differs from complete frozen packet')
        calibrated=final_literal.verify_calibration(root,call,auth,final,models.model_for(root,'judge'))
        if calibrated!=runner.read(call/'final_capacity_calibration.json'):
            raise ValueError('Measured final capacity calibration changed')
        reduction=calibrated['conservative_reduction']
    gate=runner.read(call/'capacity_gate.json')
    if (gate != capacity_gate(call/'pre_final_session.jsonl',auth['capacity'],reduction)
            or gate['remaining_margin']<0
            or gate['required_with_final_and_reserve']>gate['conservative_window']):
        raise ValueError('Capacity gate was not satisfied')
    receipt=dict(version=VERSION,task=name,all_original_text_actually_delivered=True,
        original_body_sha256=auth['original_body_sha256'],chunk_count=len(chunks),ordered_session_proof=retained,
        prompt_sha256=actual['prompt_sha256'],native_images_attached_unchanged=True,
        parent_failure_retained=True,capacity_gate=gate)
    base.save(ref.parent/'actual_text_delivery.json',(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n').encode())
    return receipt


def evaluate(workspace,root,auth,*,capacity_resume=None):
    proto,specs,selected,rules,contract,review,body,images,schema,prompt,actual=packet(workspace,root,auth)
    name=auth['task'];call=root/'model_calls'/name
    reuse_original=False
    if call.exists():
        if capacity_resume is None:raise ValueError('Capacity continuation already attempted; preserve all attempts')
        from .gameness_v4_capacity_probe_resume import begin
        reuse_original=begin(root,auth,capacity_resume)
    else:
        if capacity_resume is not None:raise ValueError('Accepted probe recovery requires the original attempted call')
        call.mkdir(parents=True)
    chunks=base.delivery_parts(auth,body);model=models.model_for(root,'judge')
    if model!='gpt-6.1-sol':raise ValueError('Frozen Sol judge required')
    deadline=time.monotonic()+2400;session=None;prompts=[]
    base.save(call/'prompt.txt',prompt.encode());dump(call/'schema.json',schema)
    reduction=0
    if auth.get('final_literal_transport'):
        from . import gameness_v4_final_literal as final_literal
        if reuse_original:
            from .gameness_v4_capacity_probe_resume import calibrate_missing_pair
            calibration=calibrate_missing_pair(root,call,auth,prompt,model,deadline)
        else:
            calibration=final_literal.calibrate(root,call,auth,prompt,model,deadline)
        reduction=calibration['conservative_reduction']
    for index,text in enumerate(chunks,1):
        ingest=base.chunk_prompt(index,len(chunks),text)
        ack=codex.obj({'chunk':{'type':'integer','enum':[index]},'sha256':{'type':'string','enum':[base.digest(text.encode())]}})
        value,session=base.invoke(root,call/'persistent_turns'/f'intake_{index:02d}',ingest,ack,model,deadline,session,
            context_tokens=auth['model_context_window'])
        if value!=dict(chunk=index,sha256=base.digest(text.encode())):raise ValueError('Incomplete intake receipt')
        prompts.append(ingest);source=base.session_path(session);base.verify_session(source,session,prompts,model)
        print(json.dumps(dict(identity=root.name,stage='CAPACITY_ORIGINAL_TEXT_PART',part=index,total=len(chunks))),flush=True)
    # Save the real pre-final session; final cannot be launched without this gate.
    base.save(call/'pre_final_session.jsonl',source.read_bytes())
    gate=capacity_gate(call/'pre_final_session.jsonl',auth['capacity'],reduction);dump(call/'capacity_gate.json',gate)
    final=call/'persistent_turns/final'
    raw,session=base.invoke(root,final,prompt,schema,model,deadline,session,images,context_tokens=auth['model_context_window'])
    prompts.append(prompt);source=base.session_path(session);base.verify_session(source,session,prompts,model)
    for filename in ['events.jsonl','stderr.log','response.json','invocation.json']:
        base.save(call/filename,(final/filename).read_bytes())
    if (final/'cli_runtime.json').is_file():base.save(call/'cli_runtime.json',(final/'cli_runtime.json').read_bytes())
    base.save(call/'persistent_session.jsonl',source.read_bytes());verify_delivery(root,name,actual)
    checks=original.evaluate(root,proto,selected,rules,contract,raw,specs,review,scoring_policy=policy)
    dump(call/'accepted_response.json',dict(path='response.json',sha256=sha(call/'response.json')))
    execution.audit_invocation(root,name,actual)
    dump(root/'judgments'/(name+'.json'),dict(protocol=policy.VERSION,task=name,raw=raw,checks=checks,
        actual_delivery_sha256=sha(root/'requests'/name/'actual_delivery.json'),
        response_path=str(call/'response.json'),response_sha256=sha(call/'response.json')))
    score=policy.aggregate(proto,checks);dump(root/'gameness_score.json',score)
    dump(root/'gameness_coverage.json',static.coverage_report(review,checks));return score


def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('--workspace',type=Path,required=True)
    parser.add_argument('--phase',choices=['persistent-capacity-judge'],required=True)
    parser.add_argument('--identities',nargs='+',required=True);parser.add_argument('--capacity-repair',type=Path,required=True)
    parser.add_argument('--acceptance-case',action='store_true');parser.add_argument('--capacity-resume',type=Path);args=parser.parse_args(argv)
    from . import gameness_v4_sequential_recovery as sequential
    if runner.read(args.capacity_repair.resolve()).get('classification') == sequential.CLASSIFICATION:
        return sequential.main(argv)
    workspace=args.workspace.resolve();inventory=runtime.load(workspace)
    if len(args.identities)!=1 or runtime.workspace_policy(workspace).VERSION!=policy.VERSION:
        raise ValueError('One explicit frozen original-check v4 identity required')
    identity=args.identities[0];row=next(r for r in inventory['entries'] if r['entry']['id']==identity and r['in_scope'])
    runner.configure_cli(Path(row['source_batch']));before=runtime.production_bindings()
    if not args.acceptance_case:runtime.production_gate(workspace)
    lock=workspace/'locks'/('gameness_v4_'+identity+'.lock');lock.parent.mkdir(parents=True,exist_ok=True)
    with lock.open('a+') as handle:
        fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB);root=workspace/'runs'/identity
        try:
            runner.disk(root,'gameness_persistent_capacity',256*1024**2);batch.verify_inputs(root)
            q=runner.read(root/'source_qualification.json');runtime.verify_bindings(q['source_bindings'])
            from .pending_publication import cleanup_source
            if not cleanup_source(Path(q['source']))[0]:raise ValueError('Real input/view/process cleanup required')
            from . import sparse_native
            sparse_native.verify_acceptance(workspace,row['entry']['actual_engine'])
            if not runtime.scope.same_original(runner.read(root/'input_manifest.json')['entry'],row['entry']):
                raise ValueError('Frozen original identity changed')
            auth=authorize(workspace,root,args.capacity_repair.resolve());score=evaluate(workspace,root,auth,capacity_resume=args.capacity_resume)
            with runner.held(workspace,Path(row['source_batch']),native=False) as guard:
                runtime.publish(workspace,root,score,guard)
            if args.acceptance_case:runtime.accept_real_case(workspace,identity,before)
        except Exception as error:
            dump(root/'failures'/('persistent_capacity_'+str(time.time_ns())+'.json'),dict(time=runner.stamp(),
                category='HARNESS_ERROR',error=repr(error),product_score=None,old_failures_claims_and_counts_preserved=True))
            raise
    return 0
