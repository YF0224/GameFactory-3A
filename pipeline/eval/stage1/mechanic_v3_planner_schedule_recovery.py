"""Validate a rejected bounded correction after deriving observer metadata only.

The original correction claim, response and invocation remain immutable. This
continuation performs no model calls, gameplay, score or requirement changes.
"""
from pathlib import Path
from . import mechanic_v3_planner_response_recovery as parent
from . import mechanic_v3_revision as revisions
from . import mechanic_v3_runner as runner
from . import batch, endpoint_sparse
from .mechanic_v3_plan_recovery import recording_started, normalize_schedule
from .mechanic_v3_plan_transport import expand
from .codex import validate_schema
from .protocol import sha, dump, write_operation_report

VERSION = 'mechanic-v3-rejected-correction-observer-metadata.v1'
PROOF = 'engineering/planner_response_schedule_metadata/repair.json'


def derive(root, engine):
    """Reproduce the exact saved failure before applying the existing normalizer."""
    root = Path(root).resolve()
    if (recording_started(root) or (root/'sol_plan.json').exists() or
            (root/'source_qualification.json').exists()):
        raise ValueError('Schedule correction requires a never-recorded rejected plan')
    proto, retained, fixed, original, _, _ = parent.qualify_parent(root, engine)
    claim_path = root/parent.CLAIM
    claim = runner.read(claim_path)
    if (claim.get('version') != parent.VERSION or claim.get('task') != parent.TASK or
            claim.get('identity') != root.name or claim.get('maximum_correction_invocations') != 1 or
            claim.get('parent_task') != parent.parent_task(root, engine)):
        raise ValueError('Unknown bounded correction claim')
    for name, digest in claim['bindings'].items():
        if sha(Path(name)) != digest:
            raise ValueError('Bounded correction lineage changed: '+name)
    folder = root/'model_calls'/parent.TASK
    if (folder/'accepted_response.json').exists():
        raise ValueError('Accepted correction cannot be replaced')
    error = runner.read(folder/'validation_error.json')
    if (error.get('phase') != 'response_plan_validation' or
            not error.get('exception','').startswith('endpoint must follow its actual last input and declared settling observation: ') or
            error.get('response_sha256') != sha(folder/'response.json')):
        raise ValueError('Different correction failure needs its own diagnosis')
    schema = runner.read(folder/'schema.json')
    if schema != parent.submission_schema(retained):
        raise ValueError('Correction schema changed')
    invocation = runner.read(folder/'invocation.json'); command = invocation.get('command', [])
    if '--model' not in command or command[command.index('--model')+1] != parent.eval_models.model_for(root, 'planner'):
        raise ValueError('Correction planner model differs')
    raw = runner.read(folder/'response.json')
    validate_schema(raw, schema); validate_schema(raw, retained)
    before = expand(raw, fixed); validate_schema(before, original)
    try:
        batch.validate_operation_plan(root, before, engine)
    except ValueError as failure:
        if str(failure) != error['exception']:
            raise ValueError('Saved correction diagnosis changed') from failure
    else:
        raise ValueError('Saved correction already validates')
    operation, changes = normalize_schedule(proto, before)
    if not changes:
        raise ValueError('No actual observer metadata correction')
    if any(operation[k] != before[k] for k in ('probes','coverage')) or operation['capture_plan']['windows'] != before['capture_plan']['windows']:
        raise ValueError('Observer repair changed physical actions, coverage or windows')
    # Only the existing normalizer's endpoint clock and final-input reference
    # may differ. Stable waits, routes, source citations and rubrics stay exact.
    import copy
    stripped = copy.deepcopy(operation)
    for ident, old in before['capture_plan']['endpoints'].items():
        for key in ('at_ms','last_action_id'):
            stripped['capture_plan']['endpoints'][ident][key] = old[key]
    if stripped != before:
        raise ValueError('Observer repair changed non-observer plan fields')
    validate_schema(operation, original)
    operation = batch.validate_operation_plan(root, operation, engine)
    from . import mechanic_v3_plan_recovery as schedule
    files = [claim_path, Path(__file__).resolve(), Path(parent.__file__).resolve(), Path(schedule.__file__).resolve()]
    files += [folder/n for n in ('response.json','schema.json','prompt.txt','validation_error.json','invocation.json')]
    bindings = dict(claim['bindings'])
    bindings.update({str(p.resolve()):sha(p) for p in files})
    return proto, operation, dict(version=VERSION, time=runner.stamp(), source_bindings=bindings,
        changes=changes, original_failure_preserved=True, original_claim_unchanged=True,
        full_original_validators=True, physical_inputs_coverage_windows_unchanged=True,
        scoring_contract_unchanged=True, additional_model_invocations=0, new_native_recording=False)


def recover(workspace, row):
    workspace = Path(workspace).resolve(); root = workspace/'runs'/row['entry']['id']
    if revisions.revision(workspace) != 'outcome_frame_v1' or not row['in_scope']:
        raise ValueError('Frozen outcome-frame original required')
    if (root/'sol_plan.json').exists():
        proof = runner.read(root/PROOF)
        for name, digest in proof['source_bindings'].items():
            if sha(Path(name)) != digest:
                raise ValueError('Schedule recovery lineage changed: '+name)
        if sha(root/'sol_plan.json') != proof['operation_sha256']:
            raise ValueError('Recovered operation changed')
        batch.validate_operation_plan(root, runner.read(root/'sol_plan.json'), row['entry']['actual_engine'])
        return root
    proto, operation, proof = derive(root, row['entry']['actual_engine'])
    dest = root/Path(PROOF).parent
    runner.exclusive_json(dest/'validated_operation.json', operation)
    proof['operation_sha256'] = sha(dest/'validated_operation.json')
    runner.exclusive_json(root/PROOF, proof)
    dump(root/'sol_plan.json', operation)
    endpoint_sparse.freeze_conditions(root, proto, operation)
    write_operation_report(root, operation)
    runner.exclusive_json(root/'engineering/planner_response_correction/completion.json', dict(
        version=parent.VERSION, time=runner.stamp(), claim_sha256=sha(root/parent.CLAIM),
        response_path=str(root/'model_calls'/parent.TASK/'response.json'),
        response_sha256=sha(root/'model_calls'/parent.TASK/'response.json'),
        operation_sha256=sha(root/'sol_plan.json'), original_full_validation=True,
        observer_metadata_recovery=str(root/PROOF), observer_metadata_recovery_sha256=sha(root/PROOF),
        new_native_recording=False))
    dump(root/'stage.json', dict(time=runner.stamp(), stage='EXECUTABLE_NATIVE_PLAN', recovery=VERSION))
    return root
