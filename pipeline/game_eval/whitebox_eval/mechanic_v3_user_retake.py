"""One explicitly authorized replacement take; preserve the parent and its plan."""
from pathlib import Path
from types import SimpleNamespace
import copy
import hashlib
import json
import shutil

from . import batch, core12, endpoint_sparse, engine_scoped_capture, sparse_native
from . import mechanic_v3_native as native, mechanic_v3_revision as revisions
from .mechanic_v3_runner import read, exclusive_json, disk, stamp, qualify_source
from .protocol import sha, dump, write_operation_report

VERSION = 'mechanic-user-authorized-native-retake.v1'
CLAIM = 'mechanic_user_retake_claim.json'


def check_authorization(authorization, identity, source):
    value = read(authorization)
    if (value.get('identity') != identity or value.get('reason') != 'user_reported_focus_loss'
            or value.get('confirmed_native_input_failure') is not False
            or value.get('unchanged_plan') is not True or not value.get('user_request', '').strip()):
        raise ValueError('Explicit identity-bound user retake authorization required')
    if value.get('parent_take') != str(source.resolve()):
        raise ValueError('Authorization must identify the exact affected take')
    return value


def cleaned(source):
    value = read(Path(source)/'runtime/native_cleanup.json')
    if not all(value.get(k) is True for k in ('input_cleanup', 'view_cleanup', 'process_cleanup')):
        raise ValueError('Actual parent input/view/process cleanup required')


def verify(canonical):
    canonical = Path(canonical)
    claim = read(canonical/CLAIM)
    if claim.get('version') != VERSION:
        raise ValueError('Unknown user retake claim')
    for path, digest in claim['source_bindings'].items():
        if sha(Path(path)) != digest:
            raise ValueError('Retake parent or authorization changed: '+path)
    root = Path(claim['recovery_root'])
    proof = read(root/'user_retake.json')
    if proof['claim_sha256'] != sha(canonical/CLAIM) or proof['operation_sha256'] != sha(root/'sol_plan.json'):
        raise ValueError('Retake proof or plan changed')
    batch.verify_inputs(root)
    before = read(Path(claim['source'])/'sol_plan.json')
    after = read(root/'sol_plan.json')
    before['planning_identity'] = after['planning_identity']
    if before != after:
        raise ValueError('Retake must retain exact actions and observation windows')
    return root


def prepare(workspace, row, authorization):
    workspace = Path(workspace).resolve()
    identity = row['entry']['id']; canonical = workspace/'runs'/identity
    if (revisions.publication_dir(workspace)/(identity+'.json')).exists():
        raise ValueError('Cannot replace a published product judgment')
    if (canonical/CLAIM).exists():
        root = verify(canonical)
        return root, batch.validate_operation_plan(root, read(root/'sol_plan.json'), row['entry']['actual_engine'])
    from .mechanic_v3_outcome_runner import locate_qualified
    source = locate_qualified(workspace, identity).resolve()
    authorization = Path(authorization).resolve()
    request = check_authorization(authorization, identity, source)
    cleaned(source); batch.verify_inputs(source)
    if any((source/'model_calls').glob('mechanic_v3_*')):
        raise ValueError('Parent has runtime judgment attempts; explicit separate reassessment required')
    engine = row['entry']['actual_engine']
    batch.validate_operation_plan(source, read(source/'sol_plan.json'), engine)
    paths = [authorization, source/'sol_plan.json', source/'input_manifest.json',
             source/'attempt_manifest.json', source/'source_qualification.json']
    for folder in ('input', 'runtime', 'model_calls'):
        paths.extend(p for p in (source/folder).rglob('*') if p.is_file()
                     and not (folder == 'runtime' and 'project' in p.relative_to(source/'runtime').parts))
    contract = revisions.contract_dir(workspace, row['entry']['case_id'])
    paths.extend((contract/'contract.json', contract/'frozen.json'))
    bindings = {str(p.resolve()): sha(p) for p in paths}
    fingerprint = hashlib.sha256(json.dumps(bindings, sort_keys=True).encode()).hexdigest()
    recovery = workspace/'user_retakes'/identity/fingerprint
    root = recovery/'runs'/identity
    disk(workspace, 'user_retake_prepare', 2*1024**3)
    exclusive_json(canonical/CLAIM, dict(version=VERSION, time=stamp(), source=str(source),
        source_bindings=bindings, recovery_root=str(root), authorization=request,
        parent_preserved=True, parent_excluded_from_new_judgment=True, product_score=None))
    root.mkdir(parents=True, exist_ok=False); native.configuration(recovery, workspace)
    shutil.copytree(source/'input', root/'input', symlinks=True)
    for name in ('input_manifest.json', 'attempt_manifest.json'):
        shutil.copyfile(source/name, root/name)
    proto = core12.verify_attempt(root, engine)
    before = read(source/'sol_plan.json'); operation = copy.deepcopy(before)
    operation['planning_identity'] = core12.plan_identity(root, proto, engine)
    operation = batch.validate_operation_plan(root, operation, engine)
    expected = copy.deepcopy(before); expected['planning_identity'] = operation['planning_identity']
    if operation != expected:
        raise ValueError('Retake changed plan semantics')
    dump(root/'sol_plan.json', operation); endpoint_sparse.freeze_conditions(root, proto, operation)
    write_operation_report(root, operation)
    exclusive_json(root/'user_retake.json', dict(version=VERSION,
        claim_sha256=sha(canonical/CLAIM), operation_sha256=sha(root/'sol_plan.json'),
        unchanged_source_actions_windows=True, reason='user_reported_focus_loss',
        confirmed_native_input_failure=False))
    return root, operation


def record(workspace, row, authorization):
    root, operation = prepare(workspace, row, authorization)
    if (root/'source_qualification.json').exists():
        return root
    from . import mechanic_v3_outcome_native as outcome_native, mechanic_v3_record_completion as completion
    completion.freeze(root, operation); outcome_native.prepare_runtime_snapshot(root)
    if (root/'native_capture_admission.json').exists():
        raise ValueError('Retake already attempted; preserve it and diagnose before continuation')
    disk(root, 'user_retake_native_record', 2*1024**3)
    options = SimpleNamespace(godot=Path.home()/'.local/bin/godot4')
    if engine_scoped_capture.enabled(workspace):
        engine_scoped_capture.capture(workspace, root, operation, options, row['entry'])
    else:
        sparse_native.capture(root, operation, options, row['entry'])
    qualification = qualify_source(root, workspace=workspace)
    qualification.update(new_recording=True, raw_record_reused=False,
        notice='用户报告焦点丢失后授权按同一计划重新原生录制；原录制保留',
        user_retake_sha256=sha(root/'user_retake.json'),
        view_manifest_sha256=sha(root/'evidence_manifest.json'))
    exclusive_json(root/'source_qualification.json', qualification)
    return root
