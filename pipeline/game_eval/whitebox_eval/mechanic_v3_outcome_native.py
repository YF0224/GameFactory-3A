"""Outcome-revision source-bound native planning and real recording.

A previous never-recorded planner is preserved and bound, rather than retried.
A fresh result contract is a user-authorized semantic change, not score chasing.
"""
from pathlib import Path
import hashlib
import json
import shutil
from types import SimpleNamespace
from . import mechanic_v3_outcome as outcome, mechanic_v3_revision as revisions
from . import mechanic_v3_native as native, mechanic_v3_runner as runner
from . import batch, core12, endpoint_sparse, sparse_native
from .mechanic_v3_plan_transport import plan_frozen
from .mechanic_v3_observation_recovery import ensure_runtime_snapshot
from .protocol import dump, sha, write_operation_report



def prepared_entry(workspace, row):
    """Freeze the existing native sampler explicitly, independent of scoring.

    Inventories built before a runtime policy is selected omit evaluation_policy.
    The outcome judge remains the separate v3 calculator; this flag only selects
    the already accepted sparse native planning/recording format.
    """
    import copy
    if revisions.revision(Path(workspace)) != outcome.REVISION:
        raise ValueError('Explicit outcome preparation required')
    if (Path(workspace)/'full_s_scope.json').exists():
        from .mechanic_v3_full_scope import bind_observation_conditions
        bind_observation_conditions(workspace)
    entry = copy.deepcopy(row['entry'])
    if entry.get('evaluation_policy') not in (None, endpoint_sparse.VERSION):
        raise ValueError('Unknown explicit native preparation policy')
    entry['evaluation_policy'] = endpoint_sparse.VERSION
    from .mechanic_v3_scope import load_inventory
    conditions = native.paired_endpoint_conditions(load_inventory(workspace), entry['case_id'])
    # The active workspace may already contain the paired outcome observer,
    # even when neither identity has a preferred historical recording.
    shared = Path(workspace)/'endpoint_conditions'/(entry['case_id']+'.'+endpoint_sparse.CAPTURE_VERSION+'.json')
    if shared.is_file():
        conditions = {'path':str(shared.resolve()),'sha256':sha(shared)}
    if conditions is not None:entry['endpoint_conditions'] = conditions
    return entry


def preparation_policy_recovery(workspace, row, source):
    """Preserve a pre-model preparation which used a non-native default policy."""
    proto_path = source/'input/pilot_rubric.json'
    claimpath = source/'mechanic_preparation_policy_recovery_claim.json'
    if claimpath.exists():
        claim = runner.read(claimpath)
        for name, digest in claim['source_bindings'].items():
            if sha(Path(name)) != digest:raise ValueError('Preserved preparation changed')
        return Path(claim['recovery_root'])
    if not proto_path.exists() or endpoint_sparse.closed_endpoints(runner.read(proto_path)):
        return None
    # This repair applies only before any model or native execution. A recorded
    # or judged source needs a distinct evidence-bound continuation.
    if any((source/name).exists() for name in ('sol_plan.json','native_capture_admission.json',
            'runtime/frame_index.jsonl','source_qualification.json')) or any(
            p.is_file() for p in (source/'model_calls').rglob('*')):
        raise ValueError('Preparation policy recovery cannot replace model/native work')
    batch.verify_inputs(source)
    paths = [source/'input_manifest.json', source/'attempt_manifest.json']
    paths += [p for p in (source/'input').rglob('*') if p.is_file()]
    folder = revisions.contract_dir(workspace, row['entry']['case_id'])
    paths += [folder/'contract.json',folder/'frozen.json']
    bindings = {str(p.resolve()):sha(p) for p in paths}
    fingerprint = hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    recovery = workspace/'preparation_policy_recovery'/row['entry']['id']/fingerprint
    root = recovery/'runs'/row['entry']['id']
    claim = dict(version='mechanic-native-preparation-policy-recovery.v1',
        revision=outcome.REVISION, source=str(source), source_bindings=bindings,
        recovery_root=str(root), original_attempt_unchanged=True,
        reason='Missing native evaluation_policy selected static runtime schema without capture_plan; no model or native execution occurred.',
        previous_policy=runner.read(proto_path).get('scoring_policy'),
        native_capture_policy=endpoint_sparse.VERSION, scoring_semantics_unchanged=True)
    runner.exclusive_json(claimpath,claim)
    recovery.mkdir(parents=True,exist_ok=True);native.configuration(recovery,workspace)
    runner.disk(recovery,'native_preparation_policy_recovery',2*1024**3)
    batch.prepare(Path(row['source_batch']),prepared_entry(workspace,row),root,prefer_explicit_endpoint_conditions=True)
    runner.exclusive_json(root/'preparation_policy_provenance.json',dict(claim,claim_sha256=sha(claimpath)))
    return root


def prepare(workspace,row):
    workspace=Path(workspace).resolve();identity=row['entry']['id']
    if revisions.revision(workspace)!=outcome.REVISION:raise ValueError('Outcome authorization required')
    if not row['in_scope'] or not row['entry'].get('project'):raise ValueError('No original eligible delivery')
    if row.get('preferred_record'):raise ValueError('Reuse qualified historical recording first')
    source=workspace/'runs'/identity
    from . import mechanic_v3_prerecord_identity as identity_recovery
    if (source/identity_recovery.CLAIM).exists():
        root=identity_recovery.verify(source)
        return root,batch.validate_operation_plan(root,runner.read(root/'sol_plan.json'),row['entry']['actual_engine'])
    if (source/'source_qualification.json').exists():raise ValueError('Reuse already qualified real source')
    native.configuration(workspace,Path(row['source_batch']))
    repaired=source/'mechanic_prerecord_recovery_claim.json'
    if repaired.exists():
        from .mechanic_v3_prerecord_recovery import verify
        root=verify(workspace,row)
        return root,batch.validate_operation_plan(root,runner.read(root/'sol_plan.json'),row['entry']['actual_engine'])
    recovered=preparation_policy_recovery(workspace,row,source) if source.exists() else None
    if recovered is not None:
        root=recovered
    elif not source.exists():
        # Normal first preparation includes exact input/runtime snapshots.
        entry=prepared_entry(workspace,row)
        runner.disk(workspace,'outcome_native_first_prepare',2*1024**3)
        batch.prepare(Path(row['source_batch']),entry,source,prefer_explicit_endpoint_conditions=True)
        root=source
    elif (source/'model_calls/plan_v3_outcome_frame_v1').exists():
        root=source
    else:
        if (source/'native_capture_admission.json').exists() or (source/'sol_plan.json').exists():
            raise ValueError('Existing capture/accepted plan needs its specific continuation, not a new identity')
        batch.verify_inputs(source)
        paths=[source/'input_manifest.json']
        paths += [p for p in (source/'model_calls').rglob('*') if p.is_file()]
        bindings={str(p.resolve()):sha(p) for p in paths}
        folder=revisions.contract_dir(workspace,row['entry']['case_id'])
        bindings[str((folder/'frozen.json').resolve())]=sha(folder/'frozen.json')
        fingerprint=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
        recovery=workspace/'outcome_native_recovery'/identity/fingerprint
        root=recovery/'runs'/identity
        claim=dict(revision=outcome.REVISION,source=str(source),source_bindings=bindings,
            recovery_root=str(root),reason='Explicit user outcome semantic revision supersedes the preserved never-recorded strict-contract planner.',
            original_attempt_unchanged=True,no_runtime_or_old_verdict_in_planner=True)
        claimpath=source/'mechanic_outcome_native_claim.json'
        if claimpath.exists() and runner.read(claimpath)!=claim:raise ValueError('Outcome native lineage differs')
        if not claimpath.exists():runner.exclusive_json(claimpath,claim)
        recovery.mkdir(parents=True,exist_ok=True);native.configuration(recovery,workspace)
        runner.disk(recovery,'outcome_native_recovery_prepare',2*1024**3)
        if not root.exists():
            root.mkdir(parents=True)
            from .mechanic_v3_runner import link_tree
            link_tree(source/'input',root/'input')
            for name in ('input_manifest.json','attempt_manifest.json'):
                if (source/name).exists():shutil.copy2(source/name,root/name)
            runner.exclusive_json(root/'outcome_native_provenance.json',dict(claim,time=runner.stamp(),claim_sha256=sha(claimpath)))
    batch.verify_inputs(root);engine=row['entry']['actual_engine']
    proto=core12.verify_attempt(root,engine)
    if not endpoint_sparse.closed_endpoints(proto):raise ValueError('Native plan requires the explicit sparse preparation policy')
    folder=revisions.contract_dir(workspace,row['entry']['case_id'])
    frozen=runner.read(folder/'frozen.json');contract=runner.read(folder/'contract.json')
    if sha(folder/'contract.json')!=frozen['contract_sha256']:raise ValueError('Outcome contract changed')
    if (root/'sol_plan.json').exists():return root,batch.validate_operation_plan(root,runner.read(root/'sol_plan.json'),engine)
    operation=plan_frozen(workspace,root,proto,engine,core12.plan_identity(root,proto,engine),contract,frozen,capture_map_complete=True)
    dump(root/'sol_plan.json',operation);endpoint_sparse.freeze_conditions(root,proto,operation)
    write_operation_report(root,operation)
    dump(root/'stage.json',dict(time=runner.stamp(),stage='OUTCOME_EXECUTABLE_NATIVE_PLAN',revision=outcome.REVISION))
    return root,operation


def prepare_runtime_snapshot(root):
    """Accept batch.prepare's untouched first copy; recover missing copies only.

    The legacy recovery helper deliberately rejects existing runtime projects.
    First preparation already creates one, so verify its exact original bytes
    and absence of native output instead of treating it as a previous take.
    """
    root=Path(root);runtime=root/'runtime';project=runtime/'project'
    if (root/'native_capture_admission.json').exists() or (root/'mechanic_native_capture_claim.json').exists():
        raise ValueError('Preserve attempted native capture; no snapshot reset')
    if not project.exists():
        return ensure_runtime_snapshot(root)
    batch.verify_inputs(root)
    if {p.name for p in runtime.iterdir()} != {'project'}:
        raise ValueError('Runtime output exists; inspect ownership and preserved take')
    expected=runner.read(root/'input_manifest.json')['snapshot_hashes']
    if batch.hashes(project)!=expected:
        raise ValueError('Existing first runtime snapshot differs from original author bytes')
    proof=root/'mechanic_first_runtime_snapshot.json'
    value=dict(source_manifest_sha256=sha(root/'input_manifest.json'),snapshot_hashes=expected,
        author_bytes_unchanged=True,previous_native_outputs=False,copy_created_by='batch.prepare')
    if proof.exists() and runner.read(proof)!=value:
        raise ValueError('First runtime snapshot provenance changed')
    if not proof.exists():runner.exclusive_json(proof,value)


def record(workspace,row):
    root,operation=prepare(workspace,row)
    if (root/'source_qualification.json').exists():return root
    from . import mechanic_v3_record_completion as completion
    completion.freeze(root,operation)
    prepare_runtime_snapshot(root)
    if (root/'native_capture_admission.json').exists():raise ValueError('Preserve attempted native capture; diagnose exact failure before another take')
    runner.disk(root,'outcome_native_record',2*1024**3)
    from . import engine_scoped_capture
    if engine_scoped_capture.enabled(workspace):
        engine_scoped_capture.capture(workspace,root,operation,
            SimpleNamespace(godot=Path.home()/'.local/bin/godot4'),row['entry'])
    else:
        sparse_native.capture(root,operation,SimpleNamespace(godot=Path.home()/'.local/bin/godot4'),row['entry'])
    qualification=runner.qualify_source(root,workspace=workspace)
    qualification.update(new_recording=True,raw_record_reused=False,
        notice='outcome_frame_v1共同契约冻结后新增真实原生录制',view_manifest_sha256=sha(root/'evidence_manifest.json'))
    runner.exclusive_json(root/'source_qualification.json',qualification)
    return root
