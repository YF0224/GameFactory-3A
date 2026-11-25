"""Deliver omitted original observer metadata after a qualified native take."""
from pathlib import Path
import time
from . import batch, unity_judge_transport_recovery as transport
from .protocol import dump,sha

CLAIM='observer_metadata_delivery_repair_claim'
RECEIPT='observer_metadata_delivery_recovery.json'
VERSION='unity-original-observer-metadata-delivery.v1'
from .prepare_unity_recorded_judge import NATIVE_OBSERVER_METADATA as NATIVE


def qualify(source):
    source=Path(source).resolve()
    if any((source/n).exists() for n in ('scores.json',CLAIM,RECEIPT)):
        raise ValueError('Saved result or previous observer delivery repair protected')
    manifest=batch.read(source/'evidence_manifest.json')
    if any(row['id'] in NATIVE for row in manifest['items']):
        raise ValueError('Observer metadata already delivered; no new packaging root cause')
    receipt=batch.read(source/'judge_transport_recovery.json')
    recorded=Path(batch.read(source/'recorded_capture_provenance.json')['source_attempt'])
    from .unity_public_field_recovery import audit_binding
    if not audit_binding(recorded):
        raise ValueError('Missing qualified source-bound public field take')
    from .unity_recovery import qualify_capture
    qualify_capture(recorded)
    from engine_adapters.unity3d.playtest.functional_observer import verify
    if not verify(recorded/'background_record/take')['ok']:
        raise ValueError('Native functional observer unavailable')
    failed=[]
    response_bindings={}
    from .judge_invocation import response_for_judgment, _same_judgment
    for judgment in sorted((source/'judgments').glob('evidence_*.json')):
        value=batch.read(judgment)
        if any(row.get('execution',{}).get('status')=='HARNESS_ERROR' for row in value['raw']['checks']):
            response=response_for_judgment(source,judgment.stem)
            if not _same_judgment(batch.read(response),value['raw']):
                raise ValueError('Execution failure differs from accepted original model response')
            call=source/'model_calls'/judgment.stem
            for artifact in (response,call/'accepted_response.json',call/'invocation.json',
                             call/'prompt.txt',call/'schema.json'):
                response_bindings[str(artifact)]=sha(artifact)
            failed.append(judgment)
    if not failed:
        raise ValueError('No accepted execution harness failure supports observer delivery repair')
    bindings={str(p):sha(p) for p in [source/'evidence_manifest.json',
        source/'judge_transport_recovery.json',source/'recorded_capture_provenance.json',*failed]}
    bindings.update(response_bindings)
    for name in NATIVE.values():
        raw=recorded/'background_record/take'/name
        if sha(source/'runtime'/name)!=sha(raw):
            raise ValueError('Omitted observer metadata differs from original native source')
        bindings[str(raw)]=sha(raw)
    return recorded,Path(receipt['parent_attempt']),bindings


def prepare(source,output):
    source=Path(source).resolve()
    recorded,static_source,bindings=qualify(source)
    claim=source/CLAIM
    claim.mkdir(exist_ok=False)
    dump(claim/'authorization.json',{'source_attempt':str(source),'source_bindings':bindings,
        'new_root_cause':'Qualified raw observer contract/readiness/bindings copied but not delivered',
        'previous_attempts_and_counts_preserved':True,'maximum_recoveries':1,'created_unix':time.time()})
    root=transport.prepare(static_source,Path(output),recorded_override=recorded)
    inherit_output_refinements(source,root)
    manifest=batch.read(root/'evidence_manifest.json')
    by_id={row['id']:row for row in manifest['items']}
    for ident,name in NATIVE.items():
        row=by_id[ident]
        if row['path']!='runtime/'+name or row['type']!='log' or row['sha256']!=sha(recorded/'background_record/take'/name):
            raise ValueError('Original observer metadata was not delivered verbatim')
    delivery=verify_delivery(root)
    dump(root/RECEIPT,{'version':VERSION,'source_attempt':str(source),'source_bindings':bindings,
        'native_metadata':NATIVE,'delivery':delivery,'claim_sha256':sha(claim/'authorization.json'),
        'recordings_added':0,'static_calls_added':0,'gameplay_changes':[],
        'failed_runtime_responses_preserved':True,'created_unix':time.time()})
    verify(root)
    return root


def verify(root):
    root=Path(root).resolve();receipt=batch.read(root/RECEIPT)
    if receipt.get('version')!=VERSION or receipt.get('recordings_added')!=0:
        raise ValueError('Invalid observer metadata delivery lineage')
    source=Path(receipt['source_attempt']).resolve()
    if source==root or source.parent!=root.parent:
        raise ValueError('Observer metadata source escapes recovery scope')
    if sha(source/CLAIM/'authorization.json')!=receipt['claim_sha256']:
        raise ValueError('Observer metadata claim changed')
    for path,digest in receipt['source_bindings'].items():
        if sha(Path(path))!=digest:
            raise ValueError('Observer metadata recovery source changed: '+path)
    manifest=batch.read(root/'evidence_manifest.json');items={r['id']:r for r in manifest['items']}
    recorded=Path(batch.read(root/'recorded_capture_provenance.json')['source_attempt'])
    for ident,name in NATIVE.items():
        row=items[ident]
        if (row['path']!='runtime/'+name or row['type']!='log'
                or row['sha256']!=sha(recorded/'background_record/take'/name)
                or row['sha256']!=sha(root/row['path'])):
            raise ValueError('Observer metadata delivery binding changed')
    if verify_delivery(root)!=receipt['delivery']:
        raise ValueError('Original observer metadata delivery changed')
    return receipt


def verify_delivery(root):
    """Check each original physical metadata line in every actual runtime packet."""
    root = Path(root).resolve()
    from .prepare_unity_recorded_judge import observer_metadata
    native_metadata = observer_metadata(root)
    manifest=batch.read(root/'evidence_manifest.json')
    protocol=batch.read(root/'input/pilot_rubric.json')
    delivered={}
    for name,specs,is_static in transport.frame_budget.tasks(protocol,manifest):
        if is_static:
            continue
        subset=transport.frame_budget.for_task(manifest,name)
        text,omitted=batch.packet(root,subset,False)
        if any(row['id'] in native_metadata for row in omitted):
            raise ValueError('Original observer metadata exceeds existing packet caps: '+name)
        for ident,filename in native_metadata.items():
            raw=(root/'runtime'/filename).read_text()
            section='\nEVIDENCE '+ident+'\n'+''.join(
                f'{number}: {line}\n' for number,line in enumerate(raw.splitlines(),1))
            if section not in text:
                from .observer_metadata_wire import IDS, verify_section
                if ident not in IDS or not verify_section(text,root/'runtime'/filename,ident):
                    raise ValueError('Original observer metadata missing from actual packet: '+name+'/'+ident)
        delivered[name]={ident:sha(root/'runtime'/filename) for ident,filename in native_metadata.items()}
    if not delivered:
        raise ValueError('No runtime requests verify observer metadata delivery')
    return delivered


def inherit_output_refinements(source,root):
    """Carry the proven output partition forward, binding the old failed calls."""
    import copy
    original=batch.read(source/'judge_transport_recovery.json')
    receipt=batch.read(root/'judge_transport_recovery.json')
    manifest=batch.read(root/'evidence_manifest.json')
    protocol=batch.read(root/'input/pilot_rubric.json')
    for failure in original.get('output_refinements',[]):
        if failure['failure_classification']!='OUTPUT_MAX_OUTPUT_TOKENS':
            raise ValueError('Unsupported prior output repair classification')
        inherited=copy.deepcopy(failure)
        inherited['failure_bindings']={str(source/path):digest
            for path,digest in failure['failure_bindings'].items()}
        inherited['origin_attempt']=str(source)
        inherited['origin_receipt_sha256']=sha(source/'judge_transport_recovery.json')
        for path,digest in inherited['failure_bindings'].items():
            if sha(Path(path))!=digest:
                raise ValueError('Prior output failure changed')
        manifest=transport.refine_manifest(manifest,protocol,
            failure['failed_name'],failure['child_names'])
        receipt.setdefault('output_refinements',[]).append(inherited)
    dump(root/'evidence_manifest.json',manifest)
    receipt['partition_manifest_sha256']=sha(root/'evidence_manifest.json')
    dump(root/'judge_transport_recovery.json',receipt)
    transport.validate_partition(root,protocol,manifest)
