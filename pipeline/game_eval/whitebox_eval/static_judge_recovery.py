"""One linked static-transport repair; reuse successful runtime judgments verbatim."""
from pathlib import Path
import shutil
import time

from . import batch, frame_budget, static_judge_shards, unity_safety
from .protocol import dump, sha

RECEIPT = 'static_partition_recovery.json'
CLAIM = 'static_partition_retry_claim'
VERSION = 'whitebox-static-partition-recovery.v1'


def prior_static_retry(source):
    """Recognize a preserved exhausted exact static retry, without resetting it."""
    source = Path(source).resolve()
    claim = source/'explicit_judge_retry_claim'
    if not claim.exists():
        return {}
    value = batch.read(claim/'authorization.json')
    if (Path(value['attempt']).resolve() != source or value.get('shards') != ['static']
            or value.get('maximum_calls_per_shard') != 1
            or value.get('timeout_seconds') != 900):
        raise ValueError('Foreign or non-static exhausted retry claim')
    for relative,digest in {**value['preserved_judgments'],
                            **value['original_model_call_files']}.items():
        path = (source/relative).resolve()
        if not path.is_relative_to(source):
            raise ValueError('Preserved pre-retry artifact escapes source: '+relative)
        if sha(path) != digest:
            original = source/'validation_history'/(path.stem+'.original.json')
            if (not relative.startswith('judgments/') or not original.is_file()
                    or sha(original) != digest
                    or batch.read(original).get('raw') != batch.read(path).get('raw')):
                raise ValueError('Preserved pre-retry artifact changed: '+relative)
    retry = source/'model_calls/static_002'
    invocation = batch.read(retry/'invocation.json')
    if (invocation.get('status') != 'TIMEOUT' or invocation.get('seconds',0) < 899
            or any((retry/n).exists() for n in ('response.json','accepted_response.json'))):
        raise ValueError('Explicit static retry is not an exhausted timeout')
    for name in ('prompt.txt','schema.json'):
        if sha(source/'model_calls/static'/name) != sha(retry/name):
            raise ValueError('Explicit static retry changed delivery: '+name)
    return {'previous_calls':2,'previous_retry_claim_preserved':True,
            'bindings':{str(f.relative_to(source)):sha(f) for folder in (claim,retry)
                        for f in folder.rglob('*') if f.is_file()}}


def qualify(source):
    source = Path(source).resolve()
    if any((source/n).exists() for n in (RECEIPT, CLAIM, 'scores.json', 'harness_error.json',
                                        'channel_transport_recovery.json')):
        raise ValueError('Static partition recovery already used or saved score protected')
    static_judge_shards.validate_policy(source.parents[1]/static_judge_shards.POLICY)
    proto=batch.read(source/'input/pilot_rubric.json')
    manifest=batch.read(source/'evidence_manifest.json')
    if static_judge_shards.FIELD in manifest:
        raise ValueError('Only the original oversized static transport can be repaired')
    static=[s for s in proto['criteria'] if s['mode']=='static']
    failed=source/'model_calls/static'
    invocation=batch.read(failed/'invocation.json')
    if (len(static)<=static_judge_shards.SIZE or invocation.get('status')!='TIMEOUT'
            or invocation.get('seconds',0)<899 or (failed/'response.json').exists()
            or (source/'judgments/static.json').exists()):
        raise ValueError('No full-budget oversized static timeout')
    prior_static_retry(source)
    batch.verify_inputs(source)
    batch.verify_runtime_sources(source)
    gate=batch.validate_capture_bundle(source,manifest,proto)
    if not gate['valid']:raise ValueError('Original capture bundle is not qualified')
    capture=Path(batch.read(source/'recorded_capture_provenance.json')['source_attempt'])
    unity_safety.capture_cleanup(capture/'background_record')
    dynamic=[]
    from .codex import saved_model_response, decode_keyed_judgment
    from .request_reuse import audit_one
    for name,specs,is_static in frame_budget.tasks(proto,manifest):
        if is_static:continue
        folder=audit_one(source,name,proto,manifest)
        response=batch.read(saved_model_response(source,name))
        artifact=batch.read(source/'judgments'/f'{name}.json')
        if artifact['raw']!=decode_keyed_judgment(response,specs):
            raise ValueError('Successful runtime judgment changed: '+name)
        dynamic.append(name)
    return proto,manifest,capture,dynamic


def eligible(source):
    try:
        qualify(source)
        return True
    except (OSError,KeyError,ValueError,TypeError,RuntimeError):
        return False


def prepare(source):
    source=Path(source).resolve()
    proto,manifest,capture,dynamic=qualify(source)
    # Immutable, exclusive claim prevents an unlimited chain of transport retries.
    (source/CLAIM).mkdir(exist_ok=False)
    ident=batch.read(source/'input_manifest.json')['entry']['id']
    dest=source.parent/(ident+'__static_partition_recovery_v1_'+str(time.time_ns()))
    dump(source/CLAIM/'authorization.json',{'source_attempt':str(source),'destination':str(dest),
        'maximum_recoveries':1,'created_unix':time.time()})
    def ignore(folder,names):
        if Path(folder)==source:return [n for n in names if n in {CLAIM,'status.json','validation_history'}]
        if Path(folder)==source/'model_calls':return [n for n in names if n=='static']
        return []
    shutil.copytree(source,dest,ignore=ignore)
    partitioned=dict(manifest, **{static_judge_shards.FIELD:static_judge_shards.partition(proto)})
    dump(dest/'evidence_manifest.json',partitioned)
    bindings={str(p.relative_to(source)):sha(p) for p in source.rglob('*') if p.is_file()
              and CLAIM not in p.relative_to(source).parts}
    qualification=dest/RECEIPT
    dump(qualification,{'version':VERSION,'source_attempt':str(source),
        'source_plan_sha256':sha(source/'sol_plan.json'),'source_bindings':bindings,
        'capture_attempt':str(capture),'preserved_dynamic_shards':dynamic,
        'new_model_calls_allowed':list(partitioned[static_judge_shards.FIELD]['shards']),
        'maximum_recoveries':1,'execution_allowed':False,'created_unix':time.time(),
        'prior_exhausted_static_retry':prior_static_retry(source)})
    dump(dest/'channel_transport_recovery.json',{'schema':'whitebox-endpoint-channel-recovery.v1',
        'source_attempt':str(source),'qualification':str(qualification),
        'qualification_sha256':sha(qualification),'reused_judge_shards':dynamic})
    verify(dest)
    return dest


def verify(root):
    root=Path(root).resolve()
    value=batch.read(root/RECEIPT);source=Path(value['source_attempt']).resolve()
    if (value.get('version')!=VERSION or value.get('maximum_recoveries')!=1
            or value.get('execution_allowed') is not False or source==root or source.parent!=root.parent
            or (source/RECEIPT).exists()):
        raise ValueError('Invalid static partition recovery lineage')
    claim=batch.read(source/CLAIM/'authorization.json')
    if claim['destination']!=str(root) or claim['maximum_recoveries']!=1:
        raise ValueError('Static partition claim changed')
    for name,digest in value['source_bindings'].items():
        rel=Path(name)
        if rel.is_absolute() or '..' in rel.parts or sha(source/name)!=digest:
            raise ValueError('Original static recovery source changed: '+name)
    for name,digest in value['source_bindings'].items():
        if (name.startswith('input/') or name.startswith('model_calls/evidence_')
                or name.startswith('model_calls/static_existence')) and sha(root/name)!=digest:
            raise ValueError('Copied original request/input changed: '+name)
        if name.startswith('judgments/evidence_'):
            if batch.read(root/name)['raw']!=batch.read(source/name)['raw']:
                raise ValueError('Copied original judgment changed: '+name)
    for name in ('input_manifest.json','sol_plan.json','input/pilot_rubric.json'):
        if sha(source/name)!=sha(root/name):raise ValueError('Frozen static recovery input changed')
    proto=batch.read(root/'input/pilot_rubric.json')
    old=batch.read(source/'evidence_manifest.json');new=batch.read(root/'evidence_manifest.json')
    expected=dict(old,**{static_judge_shards.FIELD:static_judge_shards.partition(proto)})
    if new!=expected:raise ValueError('Recovery changed evidence beyond static partition')
    wanted=[name for name,_,static in frame_budget.tasks(proto,new) if static]
    if value['new_model_calls_allowed']!=wanted:raise ValueError('Recovery call set changed')
    return {str(root/RECEIPT):sha(root/RECEIPT),
            str(source/CLAIM/'authorization.json'):sha(source/CLAIM/'authorization.json'),
            **{str(source/name):digest for name,digest in value['source_bindings'].items()}}
