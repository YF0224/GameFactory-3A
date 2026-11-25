"""Source-bound timeout continuation with the exact schema inline.

Failed attempts remain immutable. New requests retain all author source text,
requirements, capture rules and validators; only schema access is changed.
"""
from pathlib import Path
import hashlib
import json
from . import batch, core12, endpoint_sparse, mechanic_v3_revision as revisions
from . import mechanic_v3_outcome_native as native
from .mechanic_v3_plan_transport import plan_frozen
from .mechanic_v3_plan_recovery import recording_started
from .mechanic_v3_prerecord_recovery import CLAIM, verify
from .mechanic_v3_runner import read, stamp, exclusive_json, disk
from .protocol import dump, sha, write_operation_report

VERSION='mechanic-inline-schema-planner-timeout-recovery.v1'
PENDING='mechanic_inline_planner_recovery_claim.json'


def qualify_failure(source):
    source=Path(source)
    if recording_started(source) or (source/'sol_plan.json').exists() or (source/'source_qualification.json').exists():
        raise ValueError('Inline timeout continuation requires a never-recorded failed plan')
    candidates=[p for p in (source/'model_calls').iterdir() if p.is_dir() and (p/'invocation.json').exists()]
    candidates=[p for p in candidates if p.name in ('plan','plan_v3_outcome_frame_v1','plan_v3_fixed_context_recovery_v1')]
    if len(candidates)!=1:raise ValueError('One unambiguous original failed planner required')
    failed=candidates[0];invocation=read(failed/'invocation.json')
    if invocation.get('status')!='TIMEOUT':raise ValueError('Separate diagnosis required for a non-timeout planner failure')
    if any((failed/n).exists() for n in ('response.json','accepted_response.json')):
        raise ValueError('Preserve complete response; use narrow saved-response recovery')
    events=(failed/'events.jsonl').read_text()
    # The observed cause is repeated schema inspection within the same bounded
    # call, not a speculative retry of an unavailable external service.
    if 'schema.json' not in events or 'command_execution' not in events:
        raise ValueError('Original events must demonstrate schema tool inspection')
    return failed


def recover(workspace,row,*,source_attempt=None):
    workspace=Path(workspace).resolve();source=Path(source_attempt).resolve() if source_attempt else workspace/'runs'/row['entry']['id']
    primary=workspace/'runs'/row['entry']['id']
    if source.name!=row['entry']['id']:raise ValueError('Original planner identity differs from frozen scope')
    if (primary/CLAIM).exists():return verify(workspace,row)
    failed=qualify_failure(source);batch.verify_inputs(source)
    case=row['entry']['case_id'];folder=revisions.contract_dir(workspace,case)
    paths=[source/'input_manifest.json',folder/'contract.json',folder/'frozen.json',Path(__file__),Path(plan_frozen.__code__.co_filename)]
    paths += [p for p in (source/'input').rglob('*') if p.is_file()]
    paths += [p for p in failed.rglob('*') if p.is_file()]
    bindings={str(p.resolve()):sha(p) for p in paths}
    fingerprint=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    recovery=workspace/'planner_transport_recovery'/row['entry']['id']/fingerprint;root=recovery/'runs'/row['entry']['id']
    pending=dict(version=VERSION,time=stamp(),source=str(source),source_bindings=bindings,recovery_root=str(root),
        reason='Bounded planner expired after schema tool reads; complete schema is now inlined and tool discovery is disabled.',
        original_failure_preserved=True,scoring_contract_unchanged=True,full_author_source_preserved=True)
    # Persist a stable pre-call claim: interrupted/failed continuation cannot be
    # renamed or submitted again by calling this function a second time.
    if (primary/PENDING).exists():
        previous=read(primary/PENDING)
        if any(previous[k]!=pending[k] for k in pending if k!='time'):raise ValueError('Inline planner continuation lineage differs')
        pending=previous
    else:exclusive_json(primary/PENDING,pending)
    for name,digest in bindings.items():
        if sha(Path(name))!=digest:raise ValueError('Original timed-out planner drift')
    recovery.mkdir(parents=True,exist_ok=True);native.native.configuration(recovery,workspace)
    if not root.exists():
        disk(recovery,'inline_schema_planner_recovery',2*1024**3)
        batch.prepare(Path(row['source_batch']),native.prepared_entry(workspace,row),root,prefer_explicit_endpoint_conditions=True)
    batch.verify_inputs(root)
    if read(root/'input_manifest.json')['snapshot_hashes']!=read(source/'input_manifest.json')['snapshot_hashes']:
        raise ValueError('Inline transport changed original author snapshot')
    engine=row['entry']['actual_engine'];proto=core12.verify_attempt(root,engine)
    frozen=read(folder/'frozen.json');contract=read(folder/'contract.json')
    if sha(folder/'contract.json')!=frozen['contract_sha256']:raise ValueError('Frozen outcome contract drift')
    operation=plan_frozen(workspace,root,proto,engine,core12.plan_identity(root,proto,engine),contract,frozen,
        capture_map_complete=True,inline_schema=True)
    dump(root/'sol_plan.json',operation);endpoint_sparse.freeze_conditions(root,proto,operation);write_operation_report(root,operation)
    claim=dict(pending,claim_source_sha256=sha(primary/PENDING))
    exclusive_json(primary/CLAIM,claim)
    exclusive_json(root/'prerecord_recovery.json',dict(claim,claim_sha256=sha(primary/CLAIM),
        operation_sha256=sha(root/'sol_plan.json'),original_complete_validators_passed=True,new_native_recording=False))
    return root
