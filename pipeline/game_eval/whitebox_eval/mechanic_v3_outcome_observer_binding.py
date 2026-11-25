"""Bind a never-recorded outcome plan to existing shared observer metadata.

The paired outcome contract alone controls scoring. These rubrics describe the
native observer format; actions, windows and outcome goals are never changed.
"""
from pathlib import Path
import copy
from . import batch, core12, endpoint_sparse, mechanic_v3_revision as revisions
from .codex import validate_schema
from .mechanic_v3_plan_recovery import recording_started
from .mechanic_v3_runner import read, stamp, exclusive_json
from .protocol import dump, sha, write_operation_report


def bind_rubrics(operation, shared, protocol):
    value = copy.deepcopy(operation)
    endpoints = value['capture_plan']['endpoints']
    requirements = {s['id']:s['requirement'] for s in endpoint_sparse.mechanisms(protocol)}
    if set(endpoints) != set(shared['endpoints']) or set(endpoints) != set(requirements):
        raise ValueError('Shared observer mechanism identities differ')
    changes = []
    for ident, endpoint in endpoints.items():
        rubric = shared['endpoints'][ident]
        if endpoint['rubric']['requirement'] != requirements[ident] or rubric['requirement'] != requirements[ident]:
            raise ValueError('Shared observer changed the original mechanism requirement')
        if endpoint['rubric'] != rubric:
            changes.append(dict(endpoint=ident,before=endpoint['rubric'],after=rubric))
            endpoint['rubric'] = copy.deepcopy(rubric)
    return value, changes


def recover(workspace, row):
    workspace = Path(workspace).resolve(); root = workspace/'runs'/row['entry']['id']
    if revisions.revision(workspace) != 'outcome_frame_v1':
        raise ValueError('Explicit outcome observer binding required')
    if recording_started(root) or (root/'source_qualification.json').exists() or (root/'endpoint_conditions_receipt.json').exists():
        raise ValueError('Only a never-recorded unfinished observer freeze can be repaired')
    prior = root/'engineering/prerecord_schedule_metadata'
    receipt = read(prior/'repair.json')
    if (sha(prior/'validated_operation.json') != receipt['operation_sha256']
            or read(root/'sol_plan.json') != read(prior/'validated_operation.json')):
        raise ValueError('Pending schedule recovery binding changed')
    batch.verify_inputs(root); engine = row['entry']['actual_engine']
    proto = core12.verify_attempt(root, engine)
    shared_path = endpoint_sparse.shared_conditions_path(workspace, proto)
    shared = read(shared_path)
    if shared['case_id'] != row['entry']['case_id']:
        raise ValueError('Shared observer case differs')
    contract_folder = revisions.contract_dir(workspace, row['entry']['case_id'])
    contract_path = contract_folder/'contract.json'; frozen = read(contract_folder/'frozen.json')
    if sha(contract_path) != frozen['contract_sha256']:
        raise ValueError('Frozen outcome contract changed')
    before = read(root/'sol_plan.json'); operation, changes = bind_rubrics(before, shared, proto)
    if not changes:raise ValueError('No shared observer mismatch')
    proof = root/'engineering/outcome_frame_v1_plan_transport'
    wire = copy.deepcopy(operation)
    if isinstance(wire['coverage'], list):
        if len({c['atom_id'] for c in wire['coverage']}) != len(wire['coverage']):
            raise ValueError('Duplicate coverage identities')
        wire['coverage'] = {c['atom_id']:{k:v for k,v in c.items() if k != 'atom_id'} for c in wire['coverage']}
    validate_schema(wire, read(proof/'original_schema.json'))
    operation = batch.validate_operation_plan(root, wire, engine)
    dest = root/'engineering/shared_outcome_observer_binding'
    exclusive_json(dest/'original_pending_operation.json', before)
    exclusive_json(dest/'validated_operation.json', operation)
    exclusive_json(dest/'repair.json', dict(time=stamp(),
        classification='NON_SCORING_PRERECORD_SHARED_OBSERVER_BINDING',
        root_cause='Preparation searched only historical batches and missed the already frozen paired observer in the active Mechanic workspace.',
        original_operation_sha256=sha(prior/'validated_operation.json'),
        original_pending_file_sha256=sha(root/'sol_plan.json'),
        previous_repair_sha256=sha(prior/'repair.json'), shared_path=str(shared_path),shared_sha256=sha(shared_path),
        frozen_contract_sha256=sha(contract_path), changes=changes,
        actions_unchanged=operation['probes']==before['probes'],coverage_unchanged=operation['coverage']==before['coverage'],
        windows_unchanged=operation['capture_plan']['windows']==before['capture_plan']['windows'],
        scoring_contract_unchanged=True,full_original_validators=True,recording_not_started=True,
        operation_sha256=sha(dest/'validated_operation.json')))
    dump(root/'sol_plan.json', operation)
    endpoint_sparse.freeze_conditions(root, proto, operation)
    write_operation_report(root, operation)
    return root
