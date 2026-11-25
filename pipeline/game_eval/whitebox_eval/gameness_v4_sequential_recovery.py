"""Parent-bound complete-source recovery after diagnosed pre-final capacity failure.

All original failed calls remain immutable. This capability measures the complete
new final plus all identical native images before any new source conversation.
It changes transport only; source review, scoring, schemas and limits are frozen.
"""
from pathlib import Path
import argparse,fcntl,json,time
from . import gameness_v4_persistent_text as base,gameness_v4_persistent_literal as literal
from . import gameness_v4_persistent_capacity as previous
from . import gameness_v4_sequential_lines as sequential,gameness_v4_final_literal as final_literal
from . import gameness_v3_runtime as runtime,gameness_v4 as policy
from . import gameness_v3_original as original,gameness_v3_static as static
from . import mechanic_v3_runner as runner,mechanic_v3_execution as execution
from . import evaluation_model_profile as models,batch,codex
from .protocol import dump,sha
from . import gameness_v4_sequential_preinvoke as preinvoke
VERSION='gameness-v4-sequential-complete-source-recovery.v1'
AUTH='engineering/gameness_sequential_complete_source.json'
CLASSIFICATION='NON_SCORING_SEQUENTIAL_COMPLETE_SOURCE'
PERMITTED_OLD_PRODUCERS={'gameness_v4_runtime.py','gameness_v4_bounded_text.py',
 'gameness_v4_persistent_text.py','gameness_v4_persistent_literal.py',
 'gameness_v4_persistent_capacity.py','gameness_v4_inline_text_recovery.py',
 'mechanic_v3_cli.py','mechanic_v3_delivery_audit_v4.py'}

EXACT_PARENT_PRODUCERS = {
 'c149046491ab7ff4c458f345b4cbcefce4afb636a1752a4d8effd75ae6098f8b': {
  'mechanic_v3_persistent_text.py': '8bd6a36049e3c1fc333f58d4ea10afd6164fe84212e8a90eace41146a50b048d'}
}

def auth_path(root):
 from .gameness_v4_context_continuation import path
 return path(root)

def authorization(root):
 path=auth_path(root);value=runner.read(path)
 if value.get('context_parent'):
  from .gameness_v4_context_continuation import verify
  return verify(root)
 if (value.get('version')!=VERSION or value.get('identity')!=root.name or value.get('maximum_attempts')!=1
     or value.get('maximum_prompt_bytes')!=base.MAX_PROMPT or value.get('maximum_images')!=100):
  raise ValueError('Exact sequential recovery identity and unchanged limits required')
 for name,digest in value['bindings'].items():
  archive=value['producer_archives'].get(name)
  actual=Path(archive) if archive else Path(name)
  if sha(actual)!=digest:raise ValueError('Immutable sequential parent/source/producer changed: '+name)
 return value

def verify_parent(root,repair):
 item=repair['parent_authorization'];path=Path(item['path']).resolve();code=Path(__file__).resolve().parent
 if path not in {(root/base.AUTH).resolve(),(root/previous.AUTH).resolve()} or sha(path)!=item['sha256']:
  raise ValueError('Exact retained parent authorization required')
 parent=runner.read(path);files=[path]
 if parent['identity']!=root.name:raise ValueError('Parent identity differs')
 for name,digest in parent['bindings'].items():
  p=Path(name)
  if sha(p)==digest:files.append(p);continue
  old=repair['parent_producer_archives'].get(name,{}).get(digest)
  explicitly_pinned = EXACT_PARENT_PRODUCERS.get(sha(path), {}).get(p.name) == digest
  if p.parent!=code or (p.name not in PERMITTED_OLD_PRODUCERS and not explicitly_pinned) or not old or sha(Path(old))!=digest:
   raise ValueError('Exact parent transport producer archive required: '+name)
  files.append(Path(old))
 failure=Path(repair['parent_failure']['path']).resolve()
 if not failure.is_relative_to((root/'failures').resolve()) or sha(failure)!=repair['parent_failure']['sha256']:
  raise ValueError('Exact retained parent failure required')
 error=runner.read(failure).get('error','');call=root/'model_calls'/parent['task']
 if (call/'accepted_response.json').exists() or list((root/'judgments').glob('gameness_v4_*.json')):
  raise ValueError('Accepted original judgments cannot be retried')
 if 'Actual persistent intake leaves insufficient complete-final capacity:' in error:
  if (call/'persistent_turns/final').exists():raise ValueError('Capacity route requires a never-invoked final')
  try:
   previous.capacity_gate(call/'pre_final_session.jsonl',parent['capacity'],
    runner.read(call/'final_capacity_calibration.json')['conservative_reduction'])
  except ValueError as exc:
   if 'Actual persistent intake leaves insufficient complete-final capacity:' not in str(exc):raise
  else:raise ValueError('Parent capacity failure no longer reproduced')
  return parent,[*files,failure,*[p for p in call.rglob('*') if p.is_file()]]
 if error!="ValueError('Retained conversation contains compaction')":raise ValueError('Diagnosed pre-final compaction or capacity failure required')
 if (call/'persistent_turns/final').exists():raise ValueError('This compaction route is pre-final only')
 sid=base.event_values(call/'persistent_turns/intake_01/events.jsonl');session=base.session_path(sid)
 if not any('compact' in str(json.loads(line).get('type','')).lower() for line in session.read_text().splitlines()):
  raise ValueError('Actual parent compaction proof required')
 return parent,[*files,failure,session,*[p for p in call.rglob('*') if p.is_file()]]

def authorize(workspace,root,repair):
 from .gameness_v4_context_continuation import VERSION as context_version,authorize as context_authorize
 if runner.read(repair).get('version')==context_version:return context_authorize(workspace,root,repair)
 if (root/AUTH).exists():
  value=authorization(root)
  if value['repair']!=str(repair):raise ValueError('One immutable sequential recovery per diagnosed parent')
  return value
 d=runner.read(repair)
 if (d.get('classification')!=CLASSIFICATION or not d.get('root_cause') or d.get('scoring_unchanged') is not True
     or d.get('all_original_bytes_and_pixels_required') is not True):raise ValueError('Substantive transport-only sequential recovery required')
 reg=Path(d['regression']['path'])
 if sha(reg)!=d['regression']['sha256'] or runner.read(reg).get('exit_code')!=0 or runner.read(reg).get('tests_passed',0)<1:
  raise ValueError('Passed corresponding transport regression required')
 production=runtime.production_bindings()
 if production!=d['after_source_bindings']:raise ValueError('Entire current formal production must match repair')
 archives=d['after_producer_archives']
 if set(archives)!=set(production) or any(sha(Path(archives[n]))!=h for n,h in production.items()):
  raise ValueError('Exact full after producer snapshots required')
 parent,files=verify_parent(root,d);body=Path(parent['original_body_path']).read_text();wirepath=Path(d['wire_path']);wire=wirepath.read_text()
 oldwire=base.delivery_parts(parent,body)
 if (sha(Path(parent['original_body_path']))!=parent['original_body_sha256'] or literal.decode_wire(wire,sequential.VERSION)!=body
     or len(wire.encode())>=sum(len(x.encode()) for x in oldwire)*0.97):raise ValueError('Materially smaller exact complete-source inverse required')
 if runtime.publication_path(workspace,root.name).exists():raise ValueError('Published source cannot be rerun')
 auth=dict(parent,version=VERSION,identity=root.name,repair=str(repair),parent_authorization=d['parent_authorization'],
  parent_task=parent['task'],task=parent['task']+'_sequential1',maximum_attempts=1,maximum_images=100,
  literal_transport=dict(version=sequential.VERSION,wire_path=str(wirepath),wire_sha256=sha(wirepath)),
  final_literal_transport=d['final_literal_transport'],producer_archives=archives,
  original_failures_claims_and_counts_preserved=True)
 data=base.packet(workspace,root,auth,persist=False)
 if data[6]!=body:raise ValueError('All original source and runtime context required')
 final_literal.prepare(auth,data[-2])
 files += [repair,reg,wirepath,Path(parent['original_body_path']),Path(auth['final_literal_transport']['wire_path'])]
 files += [Path(p) for p in production]+[Path(p) for p in archives.values()]+data[7]
 files += [root/s['path'] for s in data[-1]['complete_author_sources']]
 auth['bindings']={str(p.resolve()):sha(p) for p in files if p.is_file()}
 runner.exclusive_json(root/AUTH,auth);return auth

def native_capacity(root,auth,prompt,images,*,invoke=False):
 call=root/'capacity_calls'/('gameness_sequential_complete_native_images'+('_context1' if auth.get('context_parent') else ''));schema=final_literal.SCHEMA
 text=final_literal.probe_prompt(prompt);model=models.model_for(root,'judge')
 if invoke:
  if call.exists():raise ValueError('Native capacity probe already attempted; preserve its exact result')
  value,sid=base.invoke(root,call,text,schema,model,time.monotonic()+900,images=images,context_tokens=preinvoke.context_configuration(auth))
  if value!=final_literal.ACK:raise ValueError('Non-scoring native capacity ACK differs')
  base.save(call/'retained_session.jsonl',base.session_path(sid).read_bytes())
  dump(call/'native_images.json',[dict(path=str(p.resolve()),sha256=sha(p)) for p in images])
 inv=runner.read(call/'invocation.json');preinvoke.verify_command(inv,auth);cmd=inv['command'];sid=base.event_values(call/'events.jsonl')
 if (inv.get('model_requested')!=model or inv.get('exit_code')!=0 or inv.get('attempt')!=1 or 'resume' in cmd
     or (call/'prompt.txt').read_text()!=text or runner.read(call/'schema.json')!=schema or runner.read(call/'response.json')!=final_literal.ACK
     or runner.read(call/'native_images.json')!=[dict(path=str(p.resolve()),sha256=sha(p)) for p in images]):
  raise ValueError('Complete native-image non-scoring capacity proof differs')
 attached=[cmd[i+1] for i,x in enumerate(cmd) if x=='--image']
 if attached!=[str(p) for p in images]:raise ValueError('Every original native image must enter capacity probe')
 proof=base.verify_session(call/'retained_session.jsonl',sid,[text],model);usage=previous.telemetry(call/'retained_session.jsonl')[-1]
 if not 0<usage['input_tokens']<usage['window']:raise ValueError('Actual complete final input usage required')
 return dict(final_increment_upper_bound=usage['input_tokens']+previous.OVERHEAD_MARGIN,
  observed_context_window=usage['window'],output_reserve=previous.OUTPUT_RESERVE,
  native_image_count=len(images),native_capacity_session=proof,non_scoring=True)

capacity_gate=previous.capacity_gate

def packet(workspace,root,auth):
    data=list(base.packet(workspace,root,auth,persist=False));actual=data[-1];name=auth['task']
    req=root/'requests'/name;ref=req/'persistent_capacity/equivalence.json'
    base.save(ref.parent/'original_body.txt',data[6].encode())
    proof=dict(version=VERSION,authorization=dict(path=str(auth_path(root)),sha256=sha(auth_path(root))),
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
    if proof.get('authorization')!=dict(path=str(auth_path(root)),sha256=sha(auth_path(root))):
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
    if not auth.get('context_parent'):preinvoke.verify_saved(root,auth)
    for turn in [*(call/'persistent_turns'/f'intake_{i:02d}' for i in range(1,len(chunks)+1)),call/'persistent_turns/final']:
        preinvoke.verify_command(runner.read(turn/'invocation.json'),auth)
    original_prompt=(ref.parent/'original_final_prompt.txt').read_text()
    if base.packet(root.parent.parent,root,auth,persist=False)[-2]!=original_prompt or final_literal.prepare(auth,original_prompt)!=final:
        raise ValueError('Exact original frozen final prompt differs')
    rebuilt=base.packet(root.parent.parent,root,auth,persist=False)
    capacity=native_capacity(root,auth,final,rebuilt[7])
    if runner.read(call/'native_capacity.json')!=capacity:
        raise ValueError('Native-image capacity proof changed')
    gate=runner.read(call/'capacity_gate.json')
    if gate!=capacity_gate(call/'pre_final_session.jsonl',capacity):
        raise ValueError('Actual complete-source capacity gate changed')
    receipt=dict(version=VERSION,task=name,all_original_text_actually_delivered=True,
        original_body_sha256=auth['original_body_sha256'],chunk_count=len(chunks),ordered_session_proof=retained,
        prompt_sha256=actual['prompt_sha256'],native_images_attached_unchanged=True,
        parent_failure_retained=True,capacity_gate=gate)
    base.save(ref.parent/'actual_text_delivery.json',(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n').encode())
    return receipt


def evaluate(workspace,root,auth,resume=None):
    proto,specs,selected,rules,contract,review,body,images,schema,prompt,actual=packet(workspace,root,auth)
    name=auth['task'];call=root/'model_calls'/name
    if call.exists():
        if resume is None:raise ValueError('Sequential complete-source recovery already attempted; preserve every call')
        preinvoke.admit(root,auth,resume)
    else:
        if resume is not None:raise ValueError('Zero-invocation continuation requires the same prepared task')
        call.mkdir(parents=True)
    chunks=base.delivery_parts(auth,body);model=models.model_for(root,'judge')
    if model!='gpt-6.1-sol':raise ValueError('Frozen Sol judge required')
    deadline=time.monotonic()+2400;session=None;prompts=[]
    base.save(call/'prompt.txt',prompt.encode());dump(call/'schema.json',schema)
    capacity=native_capacity(root,auth,prompt,images,invoke=True);dump(call/'native_capacity.json',capacity)
    for index,text in enumerate(chunks,1):
        ingest=base.chunk_prompt(index,len(chunks),text)
        ack=codex.obj({'chunk':{'type':'integer','enum':[index]},'sha256':{'type':'string','enum':[base.digest(text.encode())]}})
        value,session=base.invoke(root,call/'persistent_turns'/f'intake_{index:02d}',ingest,ack,model,deadline,session,
            context_tokens=preinvoke.context_configuration(auth))
        if value!=dict(chunk=index,sha256=base.digest(text.encode())):raise ValueError('Incomplete intake receipt')
        prompts.append(ingest);source=base.session_path(session);base.verify_session(source,session,prompts,model)
        print(json.dumps(dict(identity=root.name,stage='CAPACITY_ORIGINAL_TEXT_PART',part=index,total=len(chunks))),flush=True)
    # Save the real pre-final session; final cannot be launched without this gate.
    base.save(call/'pre_final_session.jsonl',source.read_bytes())
    gate=capacity_gate(call/'pre_final_session.jsonl',capacity);dump(call/'capacity_gate.json',gate)
    final=call/'persistent_turns/final'
    raw,session=base.invoke(root,final,prompt,schema,model,deadline,session,images,context_tokens=preinvoke.context_configuration(auth))
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
            auth=authorize(workspace,root,args.capacity_repair.resolve());score=evaluate(workspace,root,auth,args.capacity_resume)
            with runner.held(workspace,Path(row['source_batch']),native=False) as guard:
                runtime.publish(workspace,root,score,guard)
            if args.acceptance_case:runtime.accept_real_case(workspace,identity,before)
        except Exception as error:
            dump(root/'failures'/('persistent_capacity_'+str(time.time_ns())+'.json'),dict(time=runner.stamp(),
                category='HARNESS_ERROR',error=repr(error),product_score=None,old_failures_claims_and_counts_preserved=True))
            raise
    return 0
