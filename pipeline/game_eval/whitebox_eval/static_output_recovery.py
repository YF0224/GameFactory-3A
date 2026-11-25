"""Source-bound output partition after a preserved max_output_tokens failure."""
import copy
import json
import time
import shutil
from pathlib import Path
from . import batch, codex, core12, static_existence as static
from .protocol import dump, sha

VERSION = 'whitebox-static-output-partition.v1'
RECEIPT = 'static_output_partition.json'
CLAIM = 'static_output_partition_claim'
REUSE = 'static_output_partition_reuse.json'
WIDTH = 4
REFINEMENT = "static_output_refinement/authorization.json"


def _max_output_event(event):
    # Qualified CLI versions add this exact transport prefix to the same failure.
    # Reconnection notices, service errors, timeout and arbitrary substrings do not qualify.
    message='Incomplete response returned, reason: max_output_tokens'
    accepted=(message,'stream disconnected before completion: '+message)
    if event.get('type')=='error':return event.get('message') in accepted
    if event.get('type')=='turn.failed':
        error=event.get('error')
        return isinstance(error,dict) and error.get('message') in accepted
    return False


def qualify(source, *, protect_score=True):
    source = Path(source).resolve()
    batch.verify_inputs(source)
    protocol = core12.verify_attempt(source, 'unity3d')
    if any((source/n).exists() for n in ('static_existence.json','sol_plan.json','background_record','scores.json')):
        raise ValueError('Output recovery requires the failed unfinished static review')
    folder = source/'model_calls/static_existence'
    inv = batch.read(folder/'invocation.json')
    command = inv.get('command', [])
    events = [json.loads(line) for line in (folder/'events.jsonl').read_text().splitlines() if line.strip()]
    truncated = any(_max_output_event(e) for e in events)
    if (inv.get('exit_code') == 0 or inv.get('status') == 'TIMEOUT'
            or inv.get('model_requested') != static.MODEL or '--model' not in command
            or command[command.index('--model')+1] != static.MODEL
            or not truncated or (folder/'response.json').exists()):
        raise ValueError('No proven max_output_tokens failure; do not repeat other failure types')
    expected = static.schema(protocol, static.identity(source,protocol),
                             batch.read(source/'input_manifest.json')['snapshot_hashes'])
    if batch.read(folder/'schema.json') != expected:
        raise ValueError('Preserved parent schema differs from the frozen static contract')
    if len(expected['properties']['checks']['properties']) <= WIDTH:
        raise ValueError('Already small output; partition would not substantively repair it')
    from .unity_recovery import attempts, saved_score
    from .unity_queue import published
    ident = batch.read(source/'input_manifest.json')['entry']['id']
    if protect_score and (saved_score(attempts(source.parents[1],ident)) or published(source.parents[1],ident)):
        raise ValueError('Saved score protected')
    names = ['input_manifest.json','input/pilot_rubric.json'] + ['model_calls/static_existence/'+n
        for n in ('prompt.txt','schema.json','events.jsonl','invocation.json','budget.json','stderr.log')
        if (folder/n).is_file()]
    return {n:sha(source/n) for n in names}


def partition_schema(parent, ids):
    result = copy.deepcopy(parent)
    checks = result['properties']['checks']
    expected = list(checks['properties'])
    if not ids or len(ids)>WIDTH or len(ids)!=len(set(ids)) or any(i not in expected for i in ids):
        raise ValueError('Invalid closed output partition')
    checks['properties'] = {i:checks['properties'][i] for i in ids}
    checks['required'] = list(ids)
    return result


def packet(parent_prompt, parent_schema, ids):
    suffix = '\n\nOUTPUT PARTITION (transport only): The complete parent task and frozen items above remain context. '
    suffix += 'For this invocation return exactly the following target IDs, each once, with the unchanged identity, '
    suffix += 'source existence definitions and full source reference requirements. Other targets remain parent context '
    suffix += 'and will be returned by disjoint sibling invocations; do not infer their judgments. RETURN_ONLY:\n'
    suffix += json.dumps(ids, ensure_ascii=False)
    prefix = codex.READ_ONLY_EVAL_INSTRUCTIONS
    # codex.call_codex adds this exact prefix. Store both the call argument and
    # actual wire text; keep the original parent text byte-for-byte as context.
    call_prompt = (parent_prompt[len(prefix):] if parent_prompt.startswith(prefix) else parent_prompt) + suffix
    return {'parent_prompt':parent_prompt, 'parent_schema':parent_schema,
        'return_only':ids, 'schema':partition_schema(parent_schema,ids),
        'call_prompt':call_prompt, 'prompt':prefix + call_prompt}


def validate_shard(root, protocol, value, delivery):
    codex.validate_schema(value,delivery['schema'])
    if value['identity'] != static.identity(root,protocol):
        raise ValueError('Static output shard identity changed')
    sources = batch.read(Path(root)/'input_manifest.json')['snapshot_hashes']
    static.validate_check_rows(root,sources,value['checks'])
    return value


def merge(root, protocol, deliveries, responses):
    parent = static.schema(protocol,static.identity(root,protocol),
                           batch.read(Path(root)/'input_manifest.json')['snapshot_hashes'])
    expected = list(parent['properties']['checks']['properties'])
    if len(deliveries)!=len(responses) or not responses:
        raise ValueError('Incomplete static output shards')
    checks = {}
    for delivery,value in zip(deliveries,responses):
        if delivery['parent_schema'] != parent or delivery['schema'] != partition_schema(parent,delivery['return_only']):
            raise ValueError('Output shard changed parent schema or source reference definitions')
        validate_shard(root,protocol,value,delivery)
        if set(checks) & set(value['checks']):
            raise ValueError('Duplicate or conflicting static output targets')
        checks.update(copy.deepcopy(value['checks']))
    if set(checks)!=set(expected):
        raise ValueError('Static output union omitted or invented targets')
    return static.validate_result(root,protocol,{'identity':static.identity(root,protocol),
                                               'checks':{i:checks[i] for i in expected}})


def prepare(source):
    source=Path(source).resolve(); bindings=qualify(source)
    claim=source/CLAIM; claim.mkdir(exist_ok=False)
    entry=batch.read(source/'input_manifest.json')['entry']
    root=source.parent/(entry['id']+'__static_output_partition_v1_'+str(time.time_ns()))
    dump(claim/'claim.json',{'version':VERSION,'source_attempt':str(source),'attempt':str(root),
        'source_bindings':bindings,'created_unix':time.time(),'maximum_recoveries':1,
        'reason':'Preserved max_output_tokens; disjoint outputs with full parent prompt/schema and frozen source context',
        'old_attempts_and_counts_preserved':True,'scoring_semantics_changed':False})
    batch.prepare(source.parents[1],entry,root,previous_attempt=source)
    protocol=core12.verify_attempt(root,'unity3d')
    if static.identity(source,core12.verify_attempt(source,'unity3d')) != static.identity(root,protocol):
        raise ValueError('Static output recovery changed frozen identity')
    dump(root/RECEIPT,{'version':VERSION,'source_attempt':str(source),'source_bindings':bindings,
        'claim':str(claim/'claim.json'),'claim_sha256':sha(claim/'claim.json'),
        'width':WIDTH,'outputs':[],'complete':False,'model':static.MODEL})
    return root


def _unaccepted_max_output(folder):
    inv=batch.read(folder/'invocation.json');cmd=inv.get('command',[])
    events=[json.loads(line) for line in (folder/'events.jsonl').read_text().splitlines() if line.strip()]
    if (inv.get('exit_code')==0 or inv.get('status')=='TIMEOUT'
            or inv.get('model_requested')!=static.MODEL or '--model' not in cmd
            or cmd[cmd.index('--model')+1]!=static.MODEL
            or any((folder/n).exists() for n in ('response.json','accepted_response.json'))
            or not any(_max_output_event(e) for e in events)):
        raise ValueError('Only an actual unaccepted max_output_tokens failure qualifies for single-output refinement')


def refine_output(root):
    """One bound output-size correction; never resend a failed model-call name."""
    root=Path(root).resolve();receipt=batch.read(root/RECEIPT);_verify_lineage(root,receipt)
    if receipt.get('complete') or (root/REFINEMENT).exists() or (root/'static_existence.json').exists():
        raise ValueError('Completed or previously refined static output is protected')
    source=Path(receipt['source_attempt']);parent=batch.read(source/'model_calls/static_existence/schema.json')
    ids=list(parent['properties']['checks']['properties']);index=len(receipt['outputs'])
    name=f'static_existence_output_{index+1:02d}';folder=root/'model_calls'/name
    selected=ids[index*WIDTH:(index+1)*WIDTH]
    if len(selected)<=1:raise ValueError('A single output cannot be partitioned further')
    _unaccepted_max_output(folder)
    prompt=(source/'model_calls/static_existence/prompt.txt').read_text()
    delivery=packet(prompt,parent,selected)
    if (batch.read(root/'static_output_delivery'/f'{name}.json')!=delivery
            or (folder/'prompt.txt').read_text()!=delivery['prompt']
            or batch.read(folder/'schema.json')!=delivery['schema']):
        raise ValueError('Failed output actual delivery changed')
    history=root/'static_output_refinement';history.mkdir(exist_ok=False)
    shutil.copy2(root/RECEIPT,history/'partition.before.json')
    bindings={str(p.relative_to(root)):sha(p) for p in folder.iterdir() if p.is_file()}
    bindings['static_output_delivery/'+name+'.json']=sha(root/'static_output_delivery'/f'{name}.json')
    dump(root/REFINEMENT,{'version':VERSION,'root':str(root),'failed_name':name,
        'failure_classification':'OUTPUT_MAX_OUTPUT_TOKENS','failure_bindings':bindings,
        'prior_partition_sha256':sha(history/'partition.before.json'),
        'accepted_prefix':receipt['outputs'],'first_refined_group':index+1,
        'remaining_output_width':1,'created_unix':time.time(),'maximum_refinements':1,
        'reason':'Four-check output still exceeds response limit; return each remaining target separately with full original parent context/schema and unchanged source/line checks',
        'original_calls_and_counters_preserved':True})
    return batch.read(root/REFINEMENT)


def _delivery_specs(root,receipt,prompt,parent):
    ids=list(parent['properties']['checks']['properties']);ref=None
    if (root/REFINEMENT).exists():
        ref=batch.read(root/REFINEMENT);history=root/'static_output_refinement/partition.before.json'
        old=batch.read(history)
        if (ref.get('version')!=VERSION or ref.get('root')!=str(root)
                or ref.get('maximum_refinements')!=1 or ref.get('remaining_output_width')!=1
                or sha(history)!=ref['prior_partition_sha256']
                or ref['accepted_prefix']!=old['outputs'] or old.get('complete')
                or ref['first_refined_group']!=len(old['outputs'])+1
                or receipt['outputs'][:len(old['outputs'])]!=old['outputs']):
            raise ValueError('Single-output refinement lineage changed')
        for name,digest in ref['failure_bindings'].items():
            rel=Path(name)
            if rel.is_absolute() or '..' in rel.parts or sha(root/rel)!=digest:
                raise ValueError('Original output failure changed')
        _unaccepted_max_output(root/'model_calls'/ref['failed_name'])
    result=[]
    for n,start in enumerate(range(0,len(ids),WIDTH),1):
        name=f'static_existence_output_{n:02d}';selected=ids[start:start+WIDTH]
        if ref and n>=ref['first_refined_group']:
            result.extend((f'{name}_single_{i+1:02d}',packet(prompt,parent,[ident])) for i,ident in enumerate(selected))
        else:result.append((name,packet(prompt,parent,selected)))
    from .source_reference_recovery import deliveries
    return deliveries(root,result)


def run(root, timeout=900):
    root=Path(root).resolve(); receipt=batch.read(root/RECEIPT)
    if receipt.get('complete'):
        return verify(root,batch.read(root/'input/pilot_rubric.json'))
    _verify_lineage(root,receipt)
    source=Path(receipt['source_attempt']);protocol=core12.verify_attempt(root,'unity3d')
    prompt=(source/'model_calls/static_existence/prompt.txt').read_text()
    parent=batch.read(source/'model_calls/static_existence/schema.json')
    deliveries=[]; responses=[]
    for n,(name,delivery) in enumerate(_delivery_specs(root,receipt,prompt,parent),1):
        path=root/'static_output_delivery'/f'{name}.json'
        if path.exists() and batch.read(path)!=delivery:
            raise ValueError('Saved output delivery changed')
        dump(path,delivery)
        folder=root/'model_calls'/name
        from . import source_invalid_reference_recovery as correction
        from . import static_inline_source_delivery as supplement
        if supplement.registered(root,name):
            response=supplement.ensure(root,name,delivery,timeout);_successful(response)
            value=batch.read(response);validate_shard(root,protocol,value,delivery)
        elif correction.registered(root,name):
            response=correction.ensure(root,name,delivery,timeout);_successful(response)
            value=batch.read(response);validate_shard(root,protocol,value,delivery)
        elif folder.exists():
            response=codex.saved_model_response(root,name); _successful(response)
            value=batch.read(response); validate_shard(root,protocol,value,delivery)
        else:
            value=codex.call_codex(root,name=name,prompt=delivery['call_prompt'],schema=delivery['schema'],
                model=static.MODEL,timeout=timeout,max_attempts=1,
                response_validator=lambda v:validate_shard(root,protocol,v,delivery))
            response=codex.saved_model_response(root,name);_successful(response)
        deliveries.append(delivery);responses.append(value)
        row={'name':name,'delivery':str(path.relative_to(root)),'delivery_sha256':sha(path),
             'response':str(response.relative_to(root)),'response_sha256':sha(response),
             'invocation_sha256':sha(response.parent/'invocation.json')}
        if n<=len(receipt['outputs']):
            if receipt['outputs'][n-1]!=row:raise ValueError('Accepted static shard changed')
        else:receipt['outputs'].append(row);dump(root/RECEIPT,receipt)
    result=merge(root,protocol,deliveries,responses)
    receipt['complete']=True;dump(root/RECEIPT,receipt)
    dump(root/'static_existence.json',{'version':static.SCHEMA,'result':result,
        'response_sha256':sha(root/RECEIPT),'model':static.MODEL,'policy':static.policy(protocol)['version'],
        'output_partition_sha256':sha(root/RECEIPT)})
    return verify(root,protocol)


def _successful(response):
    inv=batch.read(response.parent/'invocation.json');command=inv.get('command',[])
    if (inv.get('exit_code')!=0 or inv.get('model_requested')!=static.MODEL or '--model' not in command
            or command[command.index('--model')+1]!=static.MODEL):
        raise ValueError('Static shard lacks successful real Sol provenance')


def _verify_lineage(root,receipt):
    source=Path(receipt['source_attempt']).resolve();claim=source/CLAIM/'claim.json'
    if (receipt.get('version')!=VERSION or receipt.get('width')!=WIDTH or receipt.get('model')!=static.MODEL
            or source==root or source.parent!=root.parent or str(claim)!=receipt.get('claim')
            or sha(claim)!=receipt.get('claim_sha256') or Path(batch.read(claim)['attempt']).resolve()!=root
            or qualify(source,protect_score=False)!=receipt['source_bindings']):
        raise ValueError('Static output recovery lineage changed')
    batch.verify_inputs(root)
    if static.identity(source,core12.verify_attempt(source,'unity3d')) != static.identity(root,core12.verify_attempt(root,'unity3d')):
        raise ValueError('Static output recovery frozen source/contract changed')


def verify(root,protocol):
    root=Path(root).resolve();receipt=batch.read(root/RECEIPT);_verify_lineage(root,receipt)
    source=Path(receipt['source_attempt']);parent=batch.read(source/'model_calls/static_existence/schema.json')
    prompt=(source/'model_calls/static_existence/prompt.txt').read_text();specs=_delivery_specs(root,receipt,prompt,parent)
    if not receipt.get('complete') or len(receipt['outputs'])!=len(specs):
        raise ValueError('Incomplete static output partition cannot become a source judgment')
    deliveries=[];responses=[]
    for n,row in enumerate(receipt['outputs']):
        name,delivery=specs[n];path=root/'static_output_delivery'/f'{name}.json'
        from . import source_invalid_reference_recovery as correction
        from . import static_inline_source_delivery as supplement
        response=(supplement.response(root,name) if supplement.registered(root,name) else
            correction.response(root,name) if correction.registered(root,name) else codex.saved_model_response(root,name))
        _successful(response)
        expected={'name':name,'delivery':str(path.relative_to(root)),'delivery_sha256':sha(path),
            'response':str(response.relative_to(root)),'response_sha256':sha(response),
            'invocation_sha256':sha(response.parent/'invocation.json')}
        from .source_reference_transport import delivery_matches
        actual_delivery=(supplement.delivery_matches(root,name,response,delivery) if supplement.registered(root,name) else
            correction.delivery_matches(root,name,response,delivery) if correction.registered(root,name)
            else delivery_matches(response.parent,delivery['prompt'],delivery['schema']))
        if row!=expected or batch.read(path)!=delivery or not actual_delivery:
            raise ValueError('Static output actual delivery/provenance changed')
        deliveries.append(delivery);responses.append(batch.read(response))
    result=merge(root,protocol,deliveries,responses);artifact=batch.read(root/'static_existence.json')
    if (artifact.get('result')!=result or artifact.get('response_sha256')!=sha(root/RECEIPT)
            or artifact.get('output_partition_sha256')!=sha(root/RECEIPT)):
        raise ValueError('Merged static artifact differs from accepted raw shards')
    return result


def copy_judgment(source,target):
    source,target=Path(source).resolve(),Path(target).resolve()
    protocol=batch.read(source/'input/pilot_rubric.json')
    result=static.load(source,protocol)
    if result['identity']!=static.identity(target,batch.read(target/'input/pilot_rubric.json')):
        raise ValueError('Partition reuse requires exactly equal source/contract identity')
    files=['static_existence.json']
    for name in (RECEIPT,REUSE,'static_output_delivery','static_output_refinement'):
        path=source/name
        if path.is_dir():
            shutil.copytree(path,target/name)
            files.extend(str(p.relative_to(source)) for p in path.rglob('*') if p.is_file())
        elif path.is_file() and name!=REUSE:
            files.append(name)
    # Keep original partition receipt in a bound subdirectory. A copied result
    # uses its own explicit source pointer rather than impersonating the claim.
    original=target/'static_output_reuse_source'
    original.mkdir(exist_ok=False)
    for name in (RECEIPT,REUSE):
        if (source/name).is_file():shutil.copy2(source/name,original/name)
    for folder in sorted((source/'model_calls').glob('static_existence_output_*')):
        shutil.copytree(folder,target/'model_calls'/folder.name)
        files.extend(str(p.relative_to(source)) for p in folder.rglob('*') if p.is_file())
    files=[n for n in files if n!=RECEIPT]
    shutil.copy2(source/'static_existence.json',target/'static_existence.json')
    dump(target/REUSE,{'version':VERSION,'source_attempt':str(source),
        'source_artifact_sha256':sha(source/'static_existence.json'),
        'source_receipt_sha256':sha(source/(RECEIPT if (source/RECEIPT).is_file() else REUSE)),
        'copied_files_sha256':{n:sha(source/n) for n in files},'model_calls_added':0})
    return verify_reuse(target,batch.read(target/'input/pilot_rubric.json'))


def verify_reuse(root,protocol):
    root=Path(root).resolve();receipt=batch.read(root/REUSE)
    source=Path(receipt['source_attempt']).resolve()
    if source==root or receipt.get('version')!=VERSION or receipt.get('model_calls_added')!=0:
        raise ValueError('Invalid static output reuse identity')
    name=RECEIPT if (source/RECEIPT).is_file() else REUSE
    if (sha(source/'static_existence.json')!=receipt['source_artifact_sha256']
            or sha(source/name)!=receipt['source_receipt_sha256']
            or sha(root/'static_output_reuse_source'/name)!=receipt['source_receipt_sha256']):
        raise ValueError('Static partition source receipt/artifact changed')
    result=static.load(source,batch.read(source/'input/pilot_rubric.json'))
    if result['identity']!=static.identity(root,protocol):
        raise ValueError('Static output reuse changed source/contract')
    for name,digest in receipt['copied_files_sha256'].items():
        rel=Path(name)
        if rel.is_absolute() or '..' in rel.parts or sha(source/rel)!=digest or sha(root/rel)!=digest:
            raise ValueError('Static output reuse changed accepted response/delivery')
    if batch.read(root/'static_existence.json')!=batch.read(source/'static_existence.json'):
        raise ValueError('Static output reuse altered verdicts')
    return static.validate_result(root,protocol,result)
