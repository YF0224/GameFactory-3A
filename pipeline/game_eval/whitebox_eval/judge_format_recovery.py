"""One source-bound correction of a retained native judge schema failure.

No original response becomes a verdict. The same model returns the complete
unchanged closed schema under the original remaining 600-second call budget.
"""
from pathlib import Path
import hashlib,json,math,re,time
from .protocol import dump,sha
VERSION='whitebox-judge-format-recovery.v1'
PROMPT_RECEIPT='judge_format_prompt.json'
MODEL='gpt-6.1-sol'


def original_failure(folder):
    from . import codex
    folder=Path(folder).resolve()
    if not re.fullmatch(r'(?:evidence|static)_\d{2,}',folder.name):
        raise ValueError('Original named native judge shard required')
    inv=codex.load_plan_json(folder/'invocation.json');err=codex.load_plan_json(folder/'schema_error.json')
    command=inv.get('command',[])
    if (inv.get('exit_code')!=0 or inv.get('model_requested')!=MODEL
            or '--model' not in command or command[command.index('--model')+1]!=MODEL
            or err.get('response_sha256')!=sha(folder/'response.json')
            or err.get('phase')!='response_schema_validation'
            or (folder/'accepted_response.json').exists()):
        raise ValueError('Successful retained Sol call with exact unaccepted schema error required')
    expected=codex.load_plan_json(folder/'schema.json')
    try:codex.validate_schema(codex.load_plan_json(folder/'response.json'),expected)
    except (KeyError,TypeError) as error:
        raise ValueError('Invalid original closed schema') from error
    except ValueError as error:
        if str(error)!=err.get('exception'):raise ValueError('Original schema diagnosis changed')
    else:raise ValueError('Original response conforms; correction forbidden')
    budget=codex.load_plan_json(folder/'budget.json');spent=inv.get('seconds')
    if (budget.get('effective_timeout_seconds')!=600 or type(spent) not in (int,float)
            or not math.isfinite(spent) or not 0<spent<600):
        raise ValueError('Original bounded judge budget has no correction remainder')
    if any((folder/n).exists() for n in ('prompt_transform.json','source_reference_transport.json','citation_line_codebook.json')):
        raise ValueError('Combined prompt/line transports need separate qualification')
    return {'remaining_seconds':math.floor(600-spent),'diagnosis':err['exception']}


def suffix(folder):
    from . import codex
    folder=Path(folder)
    error=codex.load_plan_json(folder/'schema_error.json')['exception']
    return ('\nBOUNDED OUTPUT FORMAT CORRECTION. The preceding complete task, evidence, '
        'criterion IDs, references and scoring rules remain unchanged. The previous response '
        'was rejected by the exact original closed JSON Schema: '+error+
        '\nReturn a complete replacement matching the supplied ORIGINAL schema, including '
        'every required nested key and exact value type. Preserve valid prior fields; '
        'correct schema-invalid fields and supply missing fields only from the evidence '
        'already delivered above. Do not invent observations, convert HARNESS_ERROR to '
        'product failure, or change valid verdicts. Mechanism endpoint_verification requires '
        'last_action_completed (boolean), stable_result (boolean), visible_conditions '
        '(boolean array), state_event_conditions (boolean array), reason (string); '
        'execution.observable_change is a boolean. The original validators and '
        'evidence sufficiency rules remain authoritative. No new game execution or source analysis. '
        '\nPREVIOUS_RESPONSE_BEGIN\n'+(folder/'response.json').read_text()+
        '\nPREVIOUS_RESPONSE_END\nReturn only the complete conforming JSON object.')


def prompt_identity(folder):
    from . import codex,judge_schema_transport
    folder=Path(folder).resolve();receipt=codex.load_plan_json(folder/PROMPT_RECEIPT)
    root=folder.parent.parent;name=receipt.get('original_name','')
    if not re.fullmatch(r'(?:evidence|static)_\d{2,}',name):raise ValueError('Invalid original judge shard name')
    original=root/'model_calls'/name
    if (receipt.get('version')!=VERSION or folder.name!=name+'_002'
            or receipt.get('maximum_new_calls')!=1):
        raise ValueError('Invalid judge format correction lineage')
    original_failure(original)
    if (root/HANDOFF).exists():verify_handoff(root)
    if set(receipt['original_call_files'])!={str(p.relative_to(root)) for p in original.rglob('*') if p.is_file()}:
        raise ValueError('Incomplete original judge failure bindings')
    for relative,digest in receipt['original_call_files'].items():
        p=(root/relative).resolve()
        if not p.is_relative_to(original) or sha(p)!=digest:raise ValueError('Original judge failure changed: '+relative)
    claim=root/'judge_format_recovery'/name/'authorization.json'
    if sha(claim)!=receipt['claim_sha256']:raise ValueError('Judge format claim changed')
    actual=(original/'prompt.txt').read_text()+suffix(original)
    if ((folder/'prompt.txt').read_text()!=actual or sha(folder/'prompt.txt')!=receipt['submitted_prompt_sha256']
            or sha(original/'prompt.txt')!=receipt['original_prompt_sha256']
            or hashlib.sha256(suffix(original).encode()).hexdigest()!=receipt['suffix_sha256']):
        raise ValueError('Judge format correction prompt changed')
    try:judge_schema_transport.same_retry_schema(original,folder)
    except (ValueError,OSError,KeyError) as error:raise ValueError('Judge format correction schema changed') from error
    preserve_valid(codex.load_plan_json(original/'response.json'),codex.load_plan_json(folder/'response.json'),
        judge_schema_transport.expand(codex.load_plan_json(original/'schema.json')))
    return receipt['original_prompt_sha256']



def preserve_valid(previous,current,schema,_root=None,path='$'):
    """Permit corrections only inside schema-invalid subtrees; no verdict rewrite."""
    from .codex import validate_schema
    _root=schema if _root is None else _root
    if '$ref' in schema:
        ref=schema['$ref']
        if not ref.startswith('#/$defs/'):raise ValueError('Unsupported correction schema reference')
        return preserve_valid(previous,current,_root['$defs'][ref[len('#/$defs/'):]],_root,path)
    try:validate_schema(previous,schema,path,_root)
    except ValueError:pass
    else:
        if previous!=current:raise ValueError('Format correction changed a valid prior field: '+path)
        return
    if isinstance(previous,dict) and isinstance(current,dict):
        for key,value in previous.items():
            if key in schema.get('properties',{}):
                if key not in current:raise ValueError('Format correction removed a prior field: '+path+'.'+key)
                preserve_valid(value,current[key],schema['properties'][key],_root,path+'.'+key)
    elif isinstance(previous,list) and isinstance(current,list) and 'items' in schema:
        if len(previous)!=len(current):raise ValueError('Format correction changed prior list length: '+path)
        for i,(a,b) in enumerate(zip(previous,current)):
            preserve_valid(a,b,schema['items'],_root,path+'['+str(i)+']')


def run(root,name,*,authorization):
    from . import batch,codex,frame_budget,judge_schema_transport,sparse_native
    root=Path(root).resolve();original=root/'model_calls'/name
    if batch.plan_engine(root) not in {'godot','three_js'} or not authorization.strip():
        raise ValueError('Authorized native judge correction required')
    if (root/'scores.json').exists() or (root/'judgments'/(name+'.json')).exists():
        raise ValueError('Existing score/judgment protected')
    if list(original.parent.glob(name+'_*')):raise ValueError('A subsequent call already exists; never repeat')
    qualification=original_failure(original)
    if (root/'harness_error.json').exists():raise ValueError('Preserve failed attempt; prepare a bound judge handoff first')
    if not (root/HANDOFF).exists():raise ValueError('Source-bound judge format handoff required')
    verify_handoff(root)
    batch.verify_inputs(root);batch.verify_runtime_sources(root)
    proto=batch.read(root/'input/pilot_rubric.json');manifest=batch.read(root/'evidence_manifest.json')
    gate=batch.validate_capture_bundle(root,manifest,proto)
    if gate['valid'] is not True:raise ValueError('Original native capture gate failed')
    task=next((t for t in frame_budget.tasks(proto,manifest) if t[0]==name),None)
    if task is None:raise ValueError('Frozen judge shard not found')
    _,specs,is_static=task;selected=frame_budget.for_task(manifest,name)
    _,omitted=batch.packet(root,selected,is_static)
    images=[] if is_static else [root/e['path'] for e in selected['items'] if e['type']=='reference']+[root/e['path'] for e in selected['delivery_sheets']]
    permitted=[e['id'] for e in selected['items'] if not is_static or e['type'] not in {'frame','reference','action','state','event'}]
    rules=batch.judge_citation_rules(root,selected,omitted,is_static)
    expected=codex.keyed_judge_schema(specs,evidence_ids=permitted,citation_rules=rules)
    if judge_schema_transport.expand(expected)!=judge_schema_transport.expand(batch.read(original/'schema.json')):
        raise ValueError('Original schema differs from current exact frozen task')
    text=(original/'prompt.txt').read_text()
    if not text.startswith(codex.READ_ONLY_EVAL_INSTRUCTIONS):raise ValueError('Original read-only prompt prefix missing')
    submitted=text+suffix(original)
    old_delivery=batch.read(original/'actual_delivery.json')
    # This measured preflight retains every image, ID, channel row and cap.
    delivery=frame_budget.validate_request(root,name,proto,manifest,images,submitted)
    comparable=lambda v:{k:x for k,x in v.items() if k not in {'prompt_sha256','prompt_bytes'}}
    if comparable(delivery)!=comparable(old_delivery):raise ValueError('Original evidence delivery changed')
    sparse_native.space(root,'judge_format_correction',estimated_bytes=2*1024**3)
    calls={str(p.relative_to(root)):sha(p) for p in (root/'model_calls').rglob('*') if p.is_file()}
    claim=root/'judge_format_recovery'/name;claim.mkdir(parents=True,exist_ok=False)
    dump(claim/'authorization.json',{'version':VERSION,'authorization':authorization,'original_name':name,
        'maximum_new_calls':1,'original_total_seconds':600,'remaining_seconds':qualification['remaining_seconds'],
        'original_call_files':calls,'qualification':qualification,'capture_gate':gate,'at':time.time()})
    result=codex.call_codex(root,name=name,prompt=submitted[len(codex.READ_ONLY_EVAL_INSTRUCTIONS):],
        schema=expected,model=MODEL,images=images,timeout=qualification['remaining_seconds'],max_attempts=1)
    folder=root/'model_calls'/(name+'_002')
    dump(folder/PROMPT_RECEIPT,{'version':VERSION,'original_name':name,'maximum_new_calls':1,
        'original_call_files':{k:v for k,v in calls.items() if k.startswith('model_calls/'+name+'/')},
        'claim_sha256':sha(claim/'authorization.json'),'original_prompt_sha256':sha(original/'prompt.txt'),
        'submitted_prompt_sha256':sha(folder/'prompt.txt'),'suffix_sha256':hashlib.sha256(suffix(original).encode()).hexdigest()})
    prompt_identity(folder)
    preserve_valid(codex.load_plan_json(original/'response.json'),result,expected)
    for relative,digest in calls.items():
        if sha(root/relative)!=digest:raise ValueError('Prior model invocation changed: '+relative)
    decoded=codex.decode_keyed_judgment(result,specs,evidence_ids=permitted,citation_rules=rules)
    import copy
    visible=copy.deepcopy(selected)
    if is_static:visible['items']=[e for e in visible['items'] if e['type'] not in {'frame','reference','action','state','event'}]
    normalized=batch.canonical_evidence_ids(decoded,visible)
    rows=batch.validate_judgments(normalized,visible,root,specs=specs)
    batch.validate_delivery_claims(rows,visible,omitted,{s['line'] for s in batch.read(root/'trace_summary.json')['state_samples']})
    artifact={'rows':rows,'raw':decoded,'structured_raw':result,'normalized':normalized,
        'validation_version':'frozen-keyed-judgments.v1','omitted_source_ranges':omitted}
    dump(root/'judgments'/(name+'.json'),artifact)
    from .judge_invocation import response_for_judgment
    response_for_judgment(root,name)
    dump(claim/'completed.json',{'response':str(folder/'response.json'),'response_sha256':sha(folder/'response.json'),
        'judgment_sha256':sha(root/'judgments'/(name+'.json')),'complete_eight_columns':False,'at':time.time()})
    return artifact


HANDOFF='judge_format_handoff.json'
HANDOFF_CLAIM='judge_format_handoff_claim.json'


def repair_proof(path):
    from . import batch
    path=Path(path).resolve();proof=batch.read(path)
    if (proof.get('non_scoring_semantics') is not True or not proof.get('root_cause')
            or not proof.get('regressions') or not proof.get('changed_files')):
        raise ValueError('Substantive format repair and passing regressions required')
    for name,spec in proof['changed_files'].items():
        if spec['after_sha256']==spec['before_sha256']:
            raise ValueError('Judge format repair implementation changed')
        if sha(Path(name))!=spec['after_sha256']:
            from .native_slot_toolchain_compatibility import verify as verify_additive_native_toolchain
            if not verify_additive_native_toolchain(path, name, spec['after_sha256']):
                raise ValueError('Judge format repair implementation changed')
    for name,digest in proof['regressions'].items():
        if sha(Path(name))!=digest:raise ValueError('Judge format regression proof changed')
    return {'path':str(path),'sha256':sha(path)}


def prepare(source,name,*,engineering_repair,authorization):
    """Preserve the actual failed attempt and bind one missing-format correction."""
    from . import batch,core12,static_existence,recovery_publish,sparse_native,request_reuse
    from .pending_publication import cleanup_source
    source=Path(source).resolve()
    if not isinstance(authorization,str) or not authorization.strip():
        raise ValueError('Explicit format repair authorization required')
    repair=repair_proof(engineering_repair)
    qualification=original_failure(source/'model_calls'/name)
    if (any((source/n).exists() for n in ('scores.json',HANDOFF,HANDOFF_CLAIM,'judge_format_recovery'))
            or list((source/'model_calls').glob(name+'_*'))):
        raise ValueError('Existing result, recovery or retry protected')
    failure=batch.read(source/'harness_error.json')
    if failure.get('phase')!='judge' or failure.get('reason')!=qualification['diagnosis']:
        raise ValueError('Exact retained judge schema failure required')
    engine=batch.plan_engine(source)
    if engine not in {'godot','three_js'}:raise ValueError('Native format handoff only')
    batch.verify_inputs(source);batch.verify_runtime_sources(source)
    proto=core12.verify_attempt(source,engine);static_existence.load(source,proto)
    batch.validate_operation_plan(source,batch.read(source/'sol_plan.json'),engine)
    gate=batch.validate_capture_bundle(source)
    if gate.get('valid') is not True:raise ValueError('Original capture gate failed')
    cleanup_source(source)
    # Completed shards must originate in successful exact requests; do not clone
    # a saved verdict with unqualified source/image or schema bindings.
    from .codex import saved_model_response,decode_keyed_judgment
    from . import frame_budget
    preserved={}
    for shard,specs,_ in frame_budget.tasks(proto,batch.read(source/'evidence_manifest.json')):
        artifact=source/'judgments'/(shard+'.json')
        if not artifact.exists():continue
        request_reuse.audit_one(source,shard,proto,batch.read(source/'evidence_manifest.json'))
        raw=batch.read(artifact)['raw']
        if raw!=decode_keyed_judgment(batch.read(saved_model_response(source,shard)),specs):
            raise ValueError('Saved native shard differs from actual response')
        preserved[shard]=raw
    root=source.parent/(source.name+'__judge_format_handoff_v1')
    if root.exists():raise ValueError('Judge format handoff already exists')
    sparse_native.space(source,'judge_format_handoff',estimated_bytes=2*1024**3)
    # Full immutable source bindings include prior claims, failures, raw requests,
    # frames, channels and adapter pin; no invocation counter is reset.
    bindings={str(p.relative_to(source)):sha(p) for p in source.rglob('*') if p.is_file()}
    claim={'version':VERSION,'source_attempt':str(source),'target_attempt':str(root),
        'original_name':name,'engineering_repair':repair,'maximum_recoveries':1,
        'authorization':authorization,'created_unix':time.time(),
        'source_bindings_sha256':hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest(),
        'preserved_shards_sha256':hashlib.sha256(json.dumps(preserved,sort_keys=True).encode()).hexdigest()}
    with (source/HANDOFF_CLAIM).open('x') as stream:json.dump(claim,stream,ensure_ascii=False,indent=2)
    recovery_publish.clone_attempt(source,root)
    # clone_attempt archives inherited terminal state with original byte SHAs.
    archived=set(r['path'] for r in batch.read(root/'recovery_attempt.json')['inherited_files'])
    copied={k:v for k,v in bindings.items() if k not in archived}
    dump(root/HANDOFF,dict(claim,source_bindings=bindings,copied_bindings=copied,
        preserved_shards=preserved,claim_sha256=sha(source/HANDOFF_CLAIM),
        capture_gate=gate,execution_allowed=False,new_recordings=0,maximum_new_correction_calls=1))
    verify_handoff(root)
    return root


def verify_handoff(root):
    from . import batch
    root=Path(root).resolve();value=batch.read(root/HANDOFF)
    source=Path(value['source_attempt']).resolve()
    if (value.get('version')!=VERSION or value.get('target_attempt')!=str(root)
            or source==root or source.parent!=root.parent
            or value.get('maximum_recoveries')!=1 or value.get('maximum_new_correction_calls')!=1
            or value.get('execution_allowed') is not False or value.get('new_recordings')!=0
            or not value.get('authorization')):
        raise ValueError('Invalid judge format source handoff')
    if sha(source/HANDOFF_CLAIM)!=value['claim_sha256'] or sha(root/HANDOFF_CLAIM)!=value['claim_sha256']:
        raise ValueError('Judge format source claim changed')
    if repair_proof(value['engineering_repair']['path'])!=value['engineering_repair']:
        raise ValueError('Judge format engineering proof changed')
    source_bindings=value['source_bindings']
    claim=batch.read(source/HANDOFF_CLAIM)
    expected_claim={k:v for k,v in value.items() if k not in {
        'source_bindings','copied_bindings','preserved_shards','claim_sha256','capture_gate',
        'execution_allowed','new_recordings','maximum_new_correction_calls'}}
    if claim!=expected_claim:raise ValueError('Judge format source claim identity changed')
    if (hashlib.sha256(json.dumps(source_bindings,sort_keys=True).encode()).hexdigest()!=claim['source_bindings_sha256']
            or hashlib.sha256(json.dumps(value['preserved_shards'],sort_keys=True).encode()).hexdigest()!=claim['preserved_shards_sha256']):
        raise ValueError('Judge format original source or raw shard inventory changed')
    inherited=batch.read(root/'recovery_attempt.json')
    if inherited.get('source_attempt')!=str(source):raise ValueError('Inherited failure source changed')
    archived={r['path'] for r in inherited['inherited_files']}
    if value['copied_bindings']!={k:v for k,v in source_bindings.items() if k not in archived}:
        raise ValueError('Judge format copied inventory changed')
    for row in inherited['inherited_files']:
        name=row['path'];p=(root/'inherited_attempt'/name).resolve()
        if (not p.is_relative_to(root/'inherited_attempt') or source_bindings.get(name)!=row['sha256']
                or sha(p)!=row['sha256']):raise ValueError('Archived original failure changed')
    if not source_bindings or any(not isinstance(k,str) for k in source_bindings):
        raise ValueError('Missing judge source bindings')
    # Validation history and saved judgment wrappers may be refreshed by normal
    # validators. Immutable model responses and raw verdicts remain exact.
    refreshable=lambda n:n.startswith(('validation_history/','judgments/')) or n=='status.json'
    for name,digest in source_bindings.items():
        p=(source/name).resolve()
        if not p.is_relative_to(source) or sha(p)!=digest:
            raise ValueError('Original judge source changed: '+name)
    for name,digest in value['copied_bindings'].items():
        p=(root/name).resolve()
        if not p.is_relative_to(root):raise ValueError('Judge handoff path escaped')
        if not refreshable(name) and sha(p)!=digest:
            raise ValueError('Reused native source changed: '+name)
    for name,raw in value['preserved_shards'].items():
        if batch.read(root/'judgments'/(name+'.json'))['raw']!=raw:
            raise ValueError('Reused accepted judgment changed')
    original_failure(source/'model_calls'/value['original_name'])
    from . import frame_budget
    task_names={t[0] for t in frame_budget.tasks(batch.read(root/'input/pilot_rubric.json'),batch.read(root/'evidence_manifest.json'))}
    allowed={p.name for p in (source/'model_calls').iterdir() if p.is_dir()}|task_names|{value['original_name']+'_002'}
    if {p.name for p in (root/'model_calls').iterdir() if p.is_dir()}-allowed:
        raise ValueError('Judge format recovery added an unauthorized invocation')
    return {str(root/HANDOFF):sha(root/HANDOFF),str(source/HANDOFF_CLAIM):sha(source/HANDOFF_CLAIM),
            **{str(source/n):v for n,v in source_bindings.items()}}
