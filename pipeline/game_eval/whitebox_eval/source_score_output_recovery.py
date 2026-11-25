"""Preserve a full-budget timeout and partition only the returned source columns."""
import copy
import math
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from . import batch, codex, core12, static_existence, unity_source_review as review
from .protocol import dump, sha

VERSION='whitebox-source-score-output-partition.v1'
RECEIPT='source_score_output_partition.json'
CLAIM='source_score_output_partition_claim'


def qualify(source, *, protect_score=True):
    source=Path(source).resolve()
    batch.verify_inputs(source)
    protocol=core12.verify_attempt(source,'unity3d')
    static_existence.load(source,protocol)
    if any((source/n).exists() for n in ('sol_plan.json','background_record','static_source_scores.json','scores.json')):
        raise ValueError('Only an unfinished source review may be partitioned')
    folder=source/'model_calls/source_code_scores'
    inv=batch.read(folder/'invocation.json');budget=batch.read(folder/'budget.json')
    seconds=budget.get('effective_timeout_seconds');elapsed=inv.get('seconds')
    if (inv.get('status')!='TIMEOUT' or inv.get('model_requested')!=static_existence.MODEL
            or any(type(v) not in (int,float) or not math.isfinite(v) for v in (seconds,elapsed))
            or seconds<300 or (folder/'response.json').exists() or (folder/'accepted_response.json').exists()):
        raise ValueError('No preserved full-budget source-score timeout')
    clock_proof=False
    if elapsed<seconds:
        from .source_timeout_provenance import verify as verify_clock_proof
        clock_proof=verify_clock_proof(source)
        if not clock_proof:raise ValueError('No preserved full-budget source-score timeout')
    parent=batch.read(folder/'schema.json')
    if parent!=review.schema(protocol,grouped=True) or len(parent['properties']['checks']['properties'])<2:
        raise ValueError('Only the unchanged grouped-column schema may be partitioned')
    ident=batch.read(source/'input_manifest.json')['entry']['id']
    if protect_score:
        from .unity_recovery import attempts,saved_score
        from .unity_queue import published
        if saved_score(attempts(source.parents[1],ident)) or published(source.parents[1],ident):
            raise ValueError('Saved score protected')
    names=['input_manifest.json','input/pilot_rubric.json','static_existence.json']
    names += ['model_calls/source_code_scores/'+n for n in ('prompt.txt','schema.json','invocation.json','budget.json','events.jsonl','stderr.log') if (folder/n).is_file()]
    if clock_proof:
        from .source_timeout_provenance import RECEIPT as clock_receipt
        names.append(clock_receipt)
    return {n:sha(source/n) for n in names}


def packet(parent_prompt,parent_schema,ident):
    result=copy.deepcopy(parent_schema);checks=result['properties']['checks']
    if ident not in checks['properties']:raise ValueError('Unknown source column')
    checks['properties']={ident:checks['properties'][ident]};checks['required']=[ident]
    suffix='\n\nOUTPUT PARTITION (transport only): Retain the entire parent task, rubric and all frozen column bindings above as context. Return exactly '+ident+' in this invocation, using the unchanged source evidence, score, basis and runtime/visual-limit requirements. Disjoint sibling invocations return the other columns; do not infer their judgments. No criteria, weights or source requirements change.'
    prefix=codex.READ_ONLY_EVAL_INSTRUCTIONS
    call_prompt=(parent_prompt[len(prefix):] if parent_prompt.startswith(prefix) else parent_prompt)+suffix
    return {'parent_prompt':parent_prompt,'parent_schema':parent_schema,'return_only':[ident],'schema':result,
        'call_prompt':call_prompt,'prompt':prefix+call_prompt}



def validate_shard(root,value,delivery):
    codex.validate_schema(value,delivery['schema'])
    return review.validate_check_rows(Path(root),value,persist_normalizations=False)


def merge(root,protocol,deliveries,responses):
    parent=review.schema(protocol,grouped=True);checks={}
    if len(deliveries)!=len(responses) or not responses:raise ValueError('Incomplete source columns')
    for delivery,value in zip(deliveries,responses):
        ids=delivery['return_only']
        if len(ids)!=1 or delivery!=packet(delivery['parent_prompt'],parent,ids[0]):
            raise ValueError('Source partition changed parent schema or delivery')
        validate_shard(root,value,delivery)
        for ident,row in value['checks'].items():
            if ident in checks:raise ValueError('Duplicate source column')
            checks[ident]=row
    return review.validate(Path(root),protocol,{'checks':checks})


def prepare(source):
    source=Path(source).resolve();bindings=qualify(source)
    entry=batch.read(source/'input_manifest.json')['entry'];ident=entry['id']
    root=source.parent/(ident+'__source_column_partition_v1_'+str(time.time_ns()))
    claim=source/CLAIM;claim.mkdir(exist_ok=False)
    dump(claim/'claim.json',{'source_attempt':str(source),'attempt':str(root),'source_bindings':bindings,'at':time.time()})
    batch.prepare(source.parents[1],entry,root,previous_attempt=source)
    if static_existence.identity(root,batch.read(root/'input/pilot_rubric.json'))!=static_existence.identity(source,batch.read(source/'input/pilot_rubric.json')):
        raise ValueError('Source partition changed frozen identity')
    return _finish_preparation(source,root,bindings,claim)


def _static_path(root,name):
    relative=Path(name)
    if relative.is_absolute() or '..' in relative.parts:raise ValueError('Invalid static artifact path')
    path=Path(root)
    for part in relative.parts:
        path=path/part
        if path.is_symlink():raise ValueError('Static artifact symlink rejected: '+name)
    return path


def _static_files(source):
    from .static_transport_recovery import RECEIPT as transport_receipt
    files=['static_existence.json']
    for name in ('static_existence_normalization.json',transport_receipt):
        path=_static_path(source,name)
        if path.exists():files.append(name)
    _static_path(source,'model_calls')
    for folder in (source/'model_calls').glob('static_existence*'):
        _static_path(source,str(folder.relative_to(source)))
        if folder.is_dir():
            for path in folder.rglob('*'):
                name=str(path.relative_to(source));_static_path(source,name)
                if path.is_file():files.append(name)
    return sorted(files)


def _finish_preparation(source,root,bindings,claim):
    files=_static_files(source)
    # Check every existing byte before adding any missing provenance. Never overwrite.
    for name in files:
        old,new=_static_path(source,name),_static_path(root,name)
        if new.exists() and (not new.is_file() or sha(new)!=sha(old)):
            raise ValueError('Existing accepted static artifact changed: '+name)
    for name in files:
        old,new=source/name,root/name;new.parent.mkdir(parents=True,exist_ok=True)
        if not new.exists():shutil.copy2(old,new)
    static_existence.load(root,batch.read(root/'input/pilot_rubric.json'))
    from .route_first_capture import install_compact_policy
    install_compact_policy(root)
    dump(root/RECEIPT,{'version':VERSION,'source_attempt':str(source),'source_bindings':bindings,
        'copied_static_sha256':{n:sha(source/n) for n in files},'claim':str(claim/'claim.json'),
        'claim_sha256':sha(claim/'claim.json'),'complete':False,'outputs':[],
        'mechanic_calls_added':0,'old_failure_and_budget_preserved':True,
        'reason':'Full-budget grouped source request timed out. Return one existing column per call with full unchanged parent context; no budget increase or identical retry.',
        'created_unix':time.time()})
    return root



def resume_preparation(root):
    """Complete the same claimed identity after a missing legacy receipt handoff.

    Only an exact partial copy missing static_items_transport.json qualifies.
    Existing model calls, claim, original timeout and recovery identity are preserved.
    """
    from .static_transport_recovery import RECEIPT as transport_receipt
    root=Path(root).resolve()
    manifest=batch.read(_static_path(root,'attempt_manifest.json'));source=Path(manifest['previous_attempt']).resolve()
    claim=source/CLAIM;value=batch.read(_static_path(source,CLAIM+'/claim.json'))
    if (Path(value['source_attempt']).resolve()!=source or Path(value['attempt']).resolve()!=root
            or source.parent!=root.parent or value['source_bindings']!=qualify(source)
            or manifest['attempt_id']!=root.name
            or manifest['entry_id']!=batch.read(source/'input_manifest.json')['entry']['id']):
        raise ValueError('Partial source-column claim/source binding changed')
    if any((root/n).exists() for n in (RECEIPT,'sol_plan.json','background_record','static_source_scores.json','scores.json','source_column_delivery')):
        raise ValueError('Only incomplete source-column preparation may resume')
    if _static_path(root,transport_receipt).exists() or not _static_path(source,transport_receipt).is_file():
        raise ValueError('Missing legacy transport handoff is not demonstrated')
    batch.verify_inputs(root)
    protocol=core12.verify_attempt(root,'unity3d')
    if static_existence.identity(root,protocol)!=static_existence.identity(source,batch.read(source/'input/pilot_rubric.json')):
        raise ValueError('Partial source-column frozen identity changed')
    expected=set(_static_files(source))
    actual=set()
    _static_path(root,'model_calls')
    for path in (root/'model_calls').rglob('*'):
        name=str(path.relative_to(root));_static_path(root,name)
        if path.is_file():actual.add(name)
    if actual!={n for n in expected if n.startswith('model_calls/')}:
        raise ValueError('Partial source-column model calls changed')
    for name in expected-{transport_receipt}:
        path=_static_path(root,name)
        if not path.is_file() or sha(path)!=sha(source/name):
            raise ValueError('Partial accepted static artifact changed: '+name)
    original=static_existence.load(source,batch.read(source/'input/pilot_rubric.json'))
    artifact=batch.read(root/'static_existence.json')
    if artifact['result']!=original or artifact.get('transport_normalization_sha256')!=sha(source/transport_receipt):
        raise ValueError('Missing handoff is not the sole accepted-static discrepancy')
    return _finish_preparation(source,root,value['source_bindings'],claim)


def _lineage(root,receipt):
    from . import single_service_source_partition as service_partition
    if (root/service_partition.RECEIPT).is_file():
        return service_partition.verify(root,receipt)
    if receipt.get('version')!=VERSION:raise ValueError('Unknown source partition version')
    source=Path(receipt['source_attempt']).resolve()
    if source==root or qualify(source,protect_score=False)!=receipt['source_bindings']:raise ValueError('Source timeout evidence changed')
    claim=source/CLAIM/'claim.json'
    if (str(claim)!=receipt['claim'] or sha(claim)!=receipt['claim_sha256']
            or Path(batch.read(claim)['attempt']).resolve()!=root):raise ValueError('Source partition claim changed')
    for name,digest in receipt['copied_static_sha256'].items():
        rel=Path(name)
        if rel.is_absolute() or '..' in rel.parts or sha(source/rel)!=digest or sha(root/rel)!=digest:
            raise ValueError('Accepted mechanic stage changed')
    if static_existence.identity(source,batch.read(source/'input/pilot_rubric.json'))!=static_existence.identity(root,batch.read(root/'input/pilot_rubric.json')):
        raise ValueError('Source partition identity changed')
    batch.verify_inputs(root)
    return source


def _response(root,name):
    from . import source_column_stream_transport_recovery as stream
    if stream.registered(root,name):return stream.response(root,name)
    from . import source_column_service_recovery as service
    if service.registered(root,name):return service.response(root,name)
    from . import source_invalid_reference_recovery as correction
    if correction.registered(root,name):return correction.response(root,name)
    from . import source_shell_timeout_recovery as shell
    if shell.registered(root,name):return shell.response(root,name)
    path=codex.saved_model_response(root,name);inv=batch.read(path.parent/'invocation.json');cmd=inv.get('command',[])
    if (inv.get('exit_code')!=0 or inv.get('status')=='TIMEOUT' or inv.get('model_requested')!=static_existence.MODEL
            or '--model' not in cmd or cmd[cmd.index('--model')+1]!=static_existence.MODEL):
        raise ValueError('Source column lacks a successful model invocation')
    if not (path.parent/'accepted_response.json').exists() and (path.parent/'schema_error.json').exists():
        from .source_response_envelope import recover
        path=recover(root,name)
    return path


def _actual_delivery(root,name,response,delivery):
    from . import source_column_stream_transport_recovery as stream
    if stream.registered(root,name):return stream.validate_delivery(root,name,response,delivery)
    from . import source_column_service_recovery as service
    if service.registered(root,name):return service.validate_delivery(root,name,response,delivery)
    from . import source_invalid_reference_recovery as correction
    if correction.registered(root,name):return correction.delivery_matches(root,name,response,delivery)
    from . import source_shell_timeout_recovery as shell
    if shell.registered(root,name):return shell.validate_delivery(root,name,response,delivery)
    return ((response.parent/'prompt.txt').read_text()==delivery['prompt']
        and batch.read(response.parent/'schema.json')==delivery['schema'])


def _inputs(source):
    folder=source/'model_calls/source_code_scores'
    parent=batch.read(folder/'schema.json');prompt=(folder/'prompt.txt').read_text()
    return [packet(prompt,parent,ident) for ident in parent['properties']['checks']['properties']]


def run(root,timeout=900):
    root=Path(root).resolve();receipt=batch.read(root/RECEIPT);source=_lineage(root,receipt)
    if (root/'static_source_scores.json').exists():return load(root,batch.read(root/'static_source_scores.json'))
    from . import single_service_source_partition as service_partition
    inherited_cap = (service_partition.call_cap(root,timeout)
                     if (root/service_partition.RECEIPT).is_file() else None)
    deadline=time.monotonic()+timeout;deliveries=_inputs(source)
    protocol=batch.read(root/'input/pilot_rubric.json')
    def invoke(pair):
        index,delivery=pair;name=f'source_column_{index+1:02d}'
        path=root/'source_column_delivery'/f'{name}.json'
        if path.exists() and batch.read(path)!=delivery:raise ValueError('Source column delivery changed')
        if not path.exists():dump(path,delivery)
        folder=root/'model_calls'/name
        from . import source_shell_timeout_recovery as shell
        from . import source_invalid_reference_recovery as correction
        from . import source_column_service_recovery as service
        from . import source_column_stream_transport_recovery as stream
        if stream.registered(root,name):
            remaining=int(deadline-time.monotonic())
            response=stream.ensure(root,name,delivery,remaining)
        elif service.registered(root,name):
            remaining=int(deadline-time.monotonic())
            if remaining<=0:raise TimeoutError('Shared source-column phase deadline exhausted')
            response=service.ensure(root,name,delivery,remaining)
        elif correction.registered(root,name):
            remaining=int(deadline-time.monotonic())
            if remaining<=0:raise TimeoutError('Shared source-column phase deadline exhausted')
            response=correction.ensure(root,name,delivery,remaining)
        elif shell.registered(root,name):
            remaining=int(deadline-time.monotonic())
            if remaining<=0:raise TimeoutError('Shared source-column phase deadline exhausted')
            shell.ensure(root,name,delivery,remaining)
            response=_response(root,name)
        elif folder.exists():
            response=_response(root,name)
        else:
            remaining=int(deadline-time.monotonic())
            if remaining<=0:raise TimeoutError('Shared source-column phase deadline exhausted')
            call_timeout=min(remaining,inherited_cap) if inherited_cap is not None else remaining
            codex.call_codex(root,name=name,prompt=delivery['call_prompt'],schema=delivery['schema'],
                model=static_existence.MODEL,timeout=call_timeout,max_attempts=1,
                response_validator=lambda v:validate_shard(root,v,delivery))
            response=_response(root,name)
        if not _actual_delivery(root,name,response,delivery):
            raise ValueError('Actual source column delivery changed')
        return {'name':name,'delivery':str(path.relative_to(root)),'delivery_sha256':sha(path),
            'response':str(response.relative_to(root)),'response_sha256':sha(response),
            'invocation_sha256':sha(response.parent/'invocation.json')},batch.read(response)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(invoke,enumerate(deliveries)))
    result=merge(root,protocol,deliveries,[v for _,v in results]);receipt.update(complete=True,outputs=[r for r,_ in results],phase_timeout_seconds=timeout)
    dump(root/RECEIPT,receipt)
    artifact={'version':'whitebox-initial-source-scores.v2','column_bindings':review.column_targets(protocol),
        'identity':static_existence.identity(root,protocol),'model':static_existence.MODEL,
        'response':RECEIPT,'response_sha256':sha(root/RECEIPT),'output_partition':True,
        'result':result,'static_timeout_seconds':timeout,'existing_mechanic_artifact_sha256':sha(root/'static_existence.json'),
        'extra_weight':0,'formal_total':None,'reason':'Initial source implementation only; final judge uses existing rubric once'}
    dump(root/'static_source_scores.json',artifact)
    return load(root,artifact)


def load(root,artifact):
    root=Path(root).resolve();receipt=batch.read(root/RECEIPT);source=_lineage(root,receipt)
    protocol=batch.read(root/'input/pilot_rubric.json');deliveries=_inputs(source)
    if not receipt.get('complete') or len(receipt['outputs'])!=len(deliveries):raise ValueError('Incomplete source columns')
    responses=[]
    for index,(delivery,row) in enumerate(zip(deliveries,receipt['outputs'])):
        name=f'source_column_{index+1:02d}';path=root/'source_column_delivery'/f'{name}.json';response=_response(root,name)
        expected={'name':name,'delivery':str(path.relative_to(root)),'delivery_sha256':sha(path),
            'response':str(response.relative_to(root)),'response_sha256':sha(response),'invocation_sha256':sha(response.parent/'invocation.json')}
        if (row!=expected or batch.read(path)!=delivery or not _actual_delivery(root,name,response,delivery)):raise ValueError('Source partition actual delivery or accepted response changed')
        responses.append(batch.read(response))
    result=merge(root,protocol,deliveries,responses)
    if (artifact.get('identity')!=static_existence.identity(root,protocol) or artifact.get('response')!=RECEIPT
            or artifact.get('response_sha256')!=sha(root/RECEIPT) or artifact.get('result')!=result
            or artifact.get('model')!=static_existence.MODEL or artifact.get('extra_weight')!=0 or artifact.get('formal_total') is not None
            or artifact.get('column_bindings')!=review.column_targets(protocol)
            or artifact.get('existing_mechanic_artifact_sha256')!=sha(root/'static_existence.json')):
        raise ValueError('Source partition artifact changed original judgments or identity')
    return artifact
