"""One source-bound pre-plan continuation for a proven 502 gateway TIMEOUT.

Separate from 503 recovery: never promotes a timeout or partial response to an
accepted result. Original call counters/errors remain immutable and auditable.
"""
from pathlib import Path
import json
import shutil
import time
from . import batch, core12, core12_planning, codex, static_existence
from . import native_service_recovery as service
from .protocol import dump, sha

VERSION = 'whitebox-native-gateway-timeout-recovery.v1'
RECEIPT = 'native_gateway_timeout_recovery.json'
CLAIM = 'native_gateway_timeout_recovery_claim.json'


def failure(source):
    source = Path(source).resolve()
    if batch.plan_engine(source) not in {'godot', 'three_js'}:
        raise ValueError('Original native engine required')
    if any((source/name).exists() for name in
           (RECEIPT, 'sol_plan.json', 'scores.json', 'runtime/frame_index.jsonl',
            'native_capture_admission.json', 'evidence_manifest.json')):
        raise ValueError('Existing stages or repeated gateway recovery protected')
    marker = batch.read(source/'harness_error.json')
    if marker.get('phase') not in {'plan', 'static_and_plan'}:
        raise ValueError('Only preserved pre-plan failure supported')
    calls = sorted(p for p in (source/'model_calls').glob('plan*') if p.is_dir())
    if [p.name for p in calls] != ['plan']:
        raise ValueError('Exactly one original incomplete planner call required')
    folder = calls[0]
    invocation = batch.read(folder/'invocation.json')
    budget = batch.read(folder/'budget.json')
    if (invocation.get('model_requested') != static_existence.MODEL
            or invocation.get('status') != 'TIMEOUT'
            or not 590 < invocation.get('seconds', 0) <= 601
            or budget.get('effective_timeout_seconds') != 600
            or any((folder/name).exists() for name in ('response.json', 'accepted_response.json'))):
        raise ValueError('Original bounded TIMEOUT without response required')
    events = (folder/'events.jsonl').read_text(errors='replace').splitlines()
    lines = [{'line':i, 'text':line} for i, line in enumerate(events, 1)
             if '502 Bad Gateway' in line]
    if not lines:
        raise ValueError('Actual original 502 gateway events required; generic timeout is ineligible')
    return {'classification':'TIMEOUT_WITH_502_GATEWAY', 'events':lines,
            'invocation_sha256':sha(folder/'invocation.json'),
            'events_sha256':sha(folder/'events.jsonl'), 'original_planner_calls':1}


def prepare(source, *, probe, engineering_repair, authorization):
    source = Path(source).resolve()
    proof = Path(engineering_repair).resolve()
    if not authorization.strip() or batch.read(proof).get('non_scoring_semantics') is not True:
        raise ValueError('Explicit authorization and engineering proof required')
    failed = failure(source)
    if (source/CLAIM).exists():
        raise ValueError('Gateway recovery already claimed')
    health = service.verify_probe(source.parents[1], probe)
    batch.verify_inputs(source)
    protocol = core12.verify_attempt(source, batch.plan_engine(source))
    static_existence.load(source, protocol)
    root = source.with_name(source.name+'__native_gateway_timeout_recovery_v1')
    if root.exists():
        raise ValueError('Existing gateway destination protected')
    claim = {'version':VERSION, 'source':str(source), 'destination':str(root),
             'maximum_recoveries':1, 'maximum_new_planner_calls':1,
             'original_call_counters_preserved':True, 'created_unix':time.time()}
    with (source/CLAIM).open('x') as stream:
        json.dump(claim, stream, indent=2)
    batch.prepare(source.parents[1], batch.read(source/'input_manifest.json')['entry'],
                  root, previous_attempt=source)
    if core12.verify_attempt(root, batch.plan_engine(root)) != protocol:
        raise ValueError('Gateway recovery changed frozen protocol')
    service._preserve_frozen_input_bytes(source, root)
    copied = []
    for name in ('static_existence.json', 'static_format_recovery.json'):
        if (source/name).exists():
            shutil.copy2(source/name, root/name)
            copied.append(name)
    for folder in (source/'model_calls').glob('static_existence*'):
        if folder.is_dir():
            shutil.copytree(folder, root/'model_calls'/folder.name)
            copied += [str(p.relative_to(source)) for p in folder.rglob('*') if p.is_file()]
    static_existence.load(root, protocol)
    bindings = {str(p.relative_to(source)):sha(p) for p in source.rglob('*') if p.is_file()}
    dump(root/RECEIPT, {'version':VERSION, 'source':str(source), 'destination':str(root),
         'maximum_recoveries':1, 'maximum_new_planner_calls':1,
         'original_call_counters_preserved':True, 'source_bindings':bindings,
         'copied_static_bindings':{name:sha(root/name) for name in copied},
         'failure':failed, 'probe':str(Path(probe).resolve()), 'probe_bindings':health,
         'health_checked_unix':time.time(), 'engineering_repair':str(proof),
         'engineering_repair_sha256':sha(proof), 'authorization':authorization})
    verify(root)
    return root


def verify(root):
    root = Path(root).resolve()
    value = batch.read(root/RECEIPT)
    source = Path(value['source']).resolve()
    if (value.get('version') != VERSION or value.get('destination') != str(root)
            or root.parent != source.parent or root == source
            or value.get('maximum_recoveries') != 1
            or value.get('maximum_new_planner_calls') != 1
            or value.get('original_call_counters_preserved') is not True
            or not value.get('authorization')):
        raise ValueError('Invalid gateway continuation lineage')
    claim = batch.read(source/CLAIM)
    if (claim.get('source') != str(source) or claim.get('destination') != str(root)
            or claim.get('maximum_recoveries') != 1 or claim.get('maximum_new_planner_calls') != 1):
        raise ValueError('Gateway claim changed')
    if failure(source) != value['failure']:
        raise ValueError('Original gateway failure changed')
    for name, digest in value['source_bindings'].items():
        path = (source/name).resolve()
        if not path.is_relative_to(source) or sha(path) != digest:
            raise ValueError('Original gateway inputs, errors or call counters changed: '+name)
    for name, digest in value['copied_static_bindings'].items():
        path = (root/name).resolve()
        if not path.is_relative_to(root) or sha(path) != digest:
            raise ValueError('Reused accepted static changed: '+name)
    proof = Path(value['engineering_repair'])
    if sha(proof) != value['engineering_repair_sha256'] or batch.read(proof).get('non_scoring_semantics') is not True:
        raise ValueError('Gateway engineering proof changed')
    if service.verify_probe(root.parents[1], value['probe'], checked_unix=value['health_checked_unix']) != value['probe_bindings']:
        raise ValueError('Gateway health qualification changed')
    if any(sha(Path(name)) != digest for name, digest in value['probe_bindings'].items()):
        raise ValueError('Gateway health artifacts changed')
    batch.verify_inputs(root)
    if (batch.read(source/'input_manifest.json') != batch.read(root/'input_manifest.json')
            or core12.verify_attempt(source,batch.plan_engine(source)) != core12.verify_attempt(root,batch.plan_engine(root))):
        raise ValueError('Gateway recovery changed source identity or frozen protocol')
    parent = service.verify(source) if (source/service.RECEIPT).is_file() else {}
    return {str(root/RECEIPT):sha(root/RECEIPT), str(proof):sha(proof),
            **{str(source/n):d for n,d in value['source_bindings'].items()}, **value['probe_bindings'], **parent}


def plan(root, *, timeout=600):
    root = Path(root).resolve()
    verify(root)
    if (root/'model_calls/plan').exists() or (root/'sol_plan.json').exists():
        raise ValueError('Gateway planner was already dispatched; never retry')
    proto = core12.verify_attempt(root,batch.plan_engine(root))
    engine = batch.plan_engine(root)
    static_existence.load(root,proto)
    identity = core12.plan_identity(root,proto,engine)
    prompt = core12_planning.prompt(proto,engine,identity)
    if (root/'input/endpoint_conditions.json').is_file():
        prompt += '\nSHARED FROZEN ENDPOINT RUBRIC CONDITIONS (reuse verbatim):\n'+json.dumps(batch.read(root/'input/endpoint_conditions.json'),ensure_ascii=False)
    schema = core12_planning.schema(proto,engine,identity)
    if timeout != 600 or batch.plan_timeout_root(root,timeout) != timeout:
        raise ValueError('Original bounded planner timeout must be preserved')
    batch.status(root,'PLANNING')
    result = codex.call_codex(root,name='plan',prompt=prompt,schema=schema,
             model=static_existence.MODEL,timeout=timeout,max_attempts=1,
             response_validator=lambda response:batch.validate_operation_plan(root,response,engine))
    result = batch.validate_operation_plan(root,result,engine)
    dump(root/'sol_plan.json',result)
    from . import endpoint_sparse
    from .protocol import write_operation_report
    endpoint_sparse.freeze_conditions(root,proto,result)
    write_operation_report(root,result)
    return result
