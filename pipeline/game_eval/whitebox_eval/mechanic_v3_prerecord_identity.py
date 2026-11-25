"""Immutable continuation of a never-recorded plan after tool fingerprint drift.

No action, source, observer, window or rubric is changed. Old claims and failed
attempts remain bound; a newly derived root must pass the full current validator.
"""
from pathlib import Path
import copy
import hashlib
import shutil
from . import batch, core12, endpoint_sparse
from .protocol import sha, dump, write_operation_report
from .mechanic_v3_runner import read, exclusive_json, disk, stamp
from .mechanic_v3_plan_recovery import recording_started

CLAIM='mechanic_prerecord_identity_claim.json'


# This exact additive retrospective-verification branch never participates in
# planning or native execution. A different edit needs its own reviewed repair.
_HISTORY_BRANCH = """    if (root/'qualified_record_reuse.json').is_file():
        from .qualified_history import verify_recorded
        return verify_recorded(root, current, recorded)
"""
_HISTORY_PARENT_SHA = 'c7615af1d4c3ba797b9b34e1d3d551eb424ba1b87342750537dfb0a291e6244a'


def _parent(source):
    source=Path(source);claim=read(source/CLAIM);changes={}
    for name,digest in claim['source_bindings'].items():
        path=Path(name)
        if sha(path)==digest:continue
        if path.resolve()!=Path(core12.__file__).resolve() or digest!=_HISTORY_PARENT_SHA:
            raise ValueError('Prerecord identity parent changed: '+name)
        text=path.read_text()
        if text.count(_HISTORY_BRANCH)!=1 or hashlib.sha256(text.replace(_HISTORY_BRANCH,'',1).encode()).hexdigest()!=digest:
            raise ValueError('Prerecord identity parent changed beyond reviewed history branch: '+name)
        changes[name]=dict(before_sha256=digest,after_sha256=sha(path),
            exact_addition=_HISTORY_BRANCH,planning_and_native_semantics_unchanged=True)
    root=Path(claim['recovery_root']);proof=read(root/'prerecord_identity.json')
    if proof['claim_sha256']!=sha(source/CLAIM) or proof['operation_sha256']!=sha(root/'sol_plan.json'):
        raise ValueError('Prerecord identity continuation changed')
    batch.verify_inputs(root)
    return root,changes


def verify(source):
    root,changes=_parent(source)
    if changes:
        if not (root/CLAIM).is_file():
            raise ValueError('Reviewed tool drift requires explicit repair-plan continuation')
        claim=read(root/CLAIM)
        parent=claim.get('parent_tool_continuation',{})
        if (parent.get('path')!=str(Path(source)/CLAIM) or
                parent.get('sha256')!=sha(Path(source)/CLAIM) or parent.get('changes')!=changes):
            raise ValueError('Tool continuation lacks immutable parent lineage')
        return verify(root)
    return root


def recover(workspace,row,source, *, parent_tool_continuation=None):
    from .mechanic_v3_native import configuration
    source=Path(source).resolve();workspace=Path(workspace).resolve()
    if (source/CLAIM).exists():
        root,changes=_parent(source)
        if not changes:return verify(source)
        if (root/CLAIM).exists():return verify(source)
        if recording_started(root) or (root/'source_qualification.json').exists():
            raise ValueError('Tool identity continuation requires a never-recorded plan')
        parent=dict(path=str(source/CLAIM),sha256=sha(source/CLAIM),changes=changes,
            proof_path=str(root/'prerecord_identity.json'),proof_sha256=sha(root/'prerecord_identity.json'))
        return recover(workspace,row,root,parent_tool_continuation=parent)
    if recording_started(source) or (source/'source_qualification.json').exists():
        raise ValueError('Tool identity continuation requires a never-recorded plan')
    batch.verify_inputs(source);engine=row['entry']['actual_engine']
    proto=core12.verify_attempt(source,engine);before=read(source/'sol_plan.json')
    current=core12.plan_identity(source,proto,engine)
    if before['planning_identity']==current:raise ValueError('No tool fingerprint drift')
    if any(before['planning_identity'].get(k)!=v for k,v in current.items() if k!='constraints_sha256'):
        raise ValueError('Source or contract identity changed')
    paths=[source/'input_manifest.json',source/'sol_plan.json',source/'attempt_manifest.json']
    paths += [p for p in (source/'input').rglob('*') if p.is_file()]
    paths += [p for p in source.glob('*recovery.json') if p.is_file()]
    bindings={str(p.resolve()):sha(p) for p in paths}
    constraints={str(Path(core12.__file__).parent/n):sha(Path(core12.__file__).parent/n) for n in (
        'core12.py','core12_planning.py','unity_planning.py','codex.py','runtime.py','batch.py',
        'budgets.py','tiered_core.py','static_existence.py','frame_budget.py','endpoint_sparse.py','sparse_evidence.py')}
    bindings.update(constraints)
    if parent_tool_continuation:
        for path in (parent_tool_continuation['path'],parent_tool_continuation['proof_path'],str(Path(__file__).resolve())):
            bindings[path]=sha(Path(path))
    fingerprint=core12.fingerprint(bindings)
    recovery=workspace/'prerecord_identity_recovery'/source.name/fingerprint;root=recovery/'runs'/source.name
    disk(workspace,'prerecord_identity_continuation',2*1024**3)
    # Reserve before materialization; never erase an incomplete claim on failure.
    claim=dict(version='mechanic-prerecord-identity-continuation.v1',time=stamp(),source=str(source),
        source_bindings=bindings,recovery_root=str(root),old_identity=before['planning_identity'],
        current_identity=current,source_actions_windows_unchanged=True,model_request_repeated=False)
    if parent_tool_continuation:claim['parent_tool_continuation']=parent_tool_continuation
    exclusive_json(source/CLAIM,claim)
    root.mkdir(parents=True,exist_ok=False)
    configuration(recovery,workspace)
    shutil.copytree(source/'input',root/'input',symlinks=True)
    for name in ('input_manifest.json','attempt_manifest.json'):shutil.copy2(source/name,root/name)
    operation=copy.deepcopy(before);operation['planning_identity']=core12.plan_identity(root,proto,engine)
    operation=batch.validate_operation_plan(root,operation,engine)
    expected=copy.deepcopy(before);expected['planning_identity']=operation['planning_identity']
    if operation!=expected:raise ValueError('Tool continuation changed physical plan or observer')
    dump(root/'sol_plan.json',operation);endpoint_sparse.freeze_conditions(root,proto,operation)
    write_operation_report(root,operation)
    exclusive_json(root/'prerecord_identity.json',dict(claim,claim_sha256=sha(source/CLAIM),
        operation_sha256=sha(root/'sol_plan.json'),full_current_validator_passed=True))
    dump(root/'stage.json',dict(stage='EXECUTABLE_NATIVE_PLAN',time=stamp(),recovery='tool_fingerprint_only'))
    return root
