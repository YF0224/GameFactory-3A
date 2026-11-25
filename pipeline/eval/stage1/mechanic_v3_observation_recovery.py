"""Source-bound recovery of a real partial capture with no observation slots.

Keep the failed capture in place. A single derived attempt is justified by the
recorded empty schedule, not by a low score. New actions/windows come only from
a new source-only planner response with the complete mutable capture map.
"""
from . import evaluation_model_profile as eval_models
from pathlib import Path
import hashlib
import json
import shutil
from types import SimpleNamespace

from . import batch, core12, endpoint_sparse, sparse_native
from . import mechanic_v3 as v3, mechanic_v3_revision as revisions
from . import mechanic_v3_native as native
from .mechanic_v3_plan_transport import plan_frozen
from .mechanic_v3_runner import read, stamp, disk, exclusive_json, qualify_source, link_tree
from .protocol import dump, sha, write_operation_report

VERSION = 'whitebox-mechanic-empty-schedule-recovery.v1'
CLAIM = 'mechanic_observation_recovery_claim.json'


def failure_binding(source):
    """Only the precise real observer failure can authorize this derivation."""
    source = Path(source)
    if (source/'source_qualification.json').exists():
        raise ValueError('Do not re-record a qualified capture')
    batch.verify_inputs(source)
    error = read(source/'runtime/harness_error.json')
    schedule = read(source/'runtime/capture_schedule.json')
    cleanup = read(source/'runtime/native_cleanup.json')
    if (error.get('reason') != 'incomplete frame capture' or error.get('frames') != 1
            or schedule['points'] or schedule['plan']['windows']
            or not all(cleanup.get(k) is True for k in ('input_cleanup','view_cleanup','process_cleanup'))):
        raise ValueError('Recovery requires exact empty-schedule failure and actual complete cleanup')
    names = ['input_manifest.json', 'sol_plan.json', 'native_capture_admission.json',
             'runtime/harness_error.json', 'runtime/capture_schedule.json',
             'runtime/native_cleanup.json', 'runtime/frame_index.jsonl',
             'runtime/engine.log', 'runtime/actions.jsonl', 'runtime/state_trace.jsonl']
    names += [str(p.relative_to(source)) for p in (source/'model_calls').rglob('*') if p.is_file()]
    names += [str(p.relative_to(source)) for p in (source/'runtime/frames').glob('*') if p.is_file()]
    names += ['runtime/event_trace.jsonl','runtime/input_view_cleanup.json','runtime/process_cleanup.json']
    return {str((source/name).resolve()): sha(source/name) for name in names}


def prepare(workspace, row):
    workspace = Path(workspace).resolve()
    source = workspace/'runs'/row['entry']['id']
    bindings = failure_binding(source)
    fingerprint = hashlib.sha256(json.dumps(bindings, sort_keys=True).encode()).hexdigest()
    recovery_batch = workspace/'native_recovery'/source.name/fingerprint
    root = recovery_batch/'runs'/source.name
    claim = dict(version=VERSION, source=str(source), source_bindings=bindings,
                 recovery_root=str(root), source_fingerprint=fingerprint,
                 reason='Empty native schedule yields only readiness; original two-frame gate correctly rejects it.',
                 policy='One source-bound corrective source-only plan; no footage/scores; no original file/attempt moved or modified.')
    claim_path = source/CLAIM
    if claim_path.exists():
        if read(claim_path) != claim:raise ValueError('Existing recovery lineage differs')
    else:exclusive_json(claim_path, claim)
    recovery_batch.mkdir(parents=True,exist_ok=True)
    native.configuration(recovery_batch, workspace)
    disk(recovery_batch, 'source_bound_observation_recovery', 2*1024**3)
    if not root.exists():
        root.mkdir(parents=True)
        link_tree(source/'input', root/'input')
        shutil.copy2(source/'input_manifest.json', root/'input_manifest.json')
        if (source/'attempt_manifest.json').exists():
            shutil.copy2(source/'attempt_manifest.json', root/'attempt_manifest.json')
        exclusive_json(root/'mechanic_observation_recovery.json', dict(claim,
            time=stamp(), claim_sha256=sha(claim_path), production_source_sha256=sha(Path(__file__)),
            original_failures_preserved=True, tool_synthesized_actions=0,
            original_rubric_budget_capture_gates_unchanged=True))
    proof = read(root/'mechanic_observation_recovery.json')
    if proof['claim_sha256'] != sha(claim_path) or proof['source_bindings'] != bindings:
        raise ValueError('Derived native recovery provenance changed')
    batch.verify_inputs(root)
    engine = row['entry']['actual_engine'];proto = core12.verify_attempt(root,engine)
    case = row['entry']['case_id'];folder = revisions.contract_dir(workspace,case)
    frozen = read(folder/'frozen.json');contract = read(folder/'contract.json')
    if sha(folder/'contract.json') != frozen['contract_sha256']:raise ValueError('Frozen contract changed')
    if (root/'sol_plan.json').exists():
        return root, batch.validate_operation_plan(root,read(root/'sol_plan.json'),engine)
    operation = plan_frozen(workspace,root,proto,engine,core12.plan_identity(root,proto,engine),
                            contract,frozen,observation_recovery=True)
    dump(root/'sol_plan.json',operation)
    endpoint_sparse.freeze_conditions(root,proto,operation)
    write_operation_report(root,operation)
    dump(root/'stage.json',dict(time=stamp(),stage='EXECUTABLE_NATIVE_PLAN',recovery=VERSION,model=eval_models.model_for(root, "planner")))
    return root,operation


def record(workspace,row,*,godot):
    root,operation = prepare(workspace,row)
    if (root/'source_qualification.json').exists():return root
    ensure_runtime_snapshot(root)
    exclusive_json(root/'mechanic_native_capture_claim.json',dict(time=stamp(),plan_sha256=sha(root/'sol_plan.json')))
    sparse_native.capture(root,operation,SimpleNamespace(godot=godot),row['entry'])
    qualification = qualify_source(root)
    qualification.update(recording='NEW_REAL_NATIVE_RECORD',new_recording=True,
        raw_record_reused=False,notice='来源绑定的空采样修复后，按新冻结契约新增真实原生录制',
        view_manifest_sha256=sha(root/'evidence_manifest.json'),
        recovery_provenance_sha256=sha(root/'mechanic_observation_recovery.json'))
    exclusive_json(root/'source_qualification.json',qualification)
    print(json.dumps(dict(identity=root.name,stage='NEW_NATIVE_RECORD_COMPLETE',recovery=VERSION)),flush=True)
    return root


def ensure_runtime_snapshot(root):
    """Match batch.prepare's byte-identical runtime copy, before any real take.

    A proven missing-copy prelaunch error may continue once. Preserve every
    failed file and SHA; remove only empty adapter output placeholders.
    """
    root=Path(root);runtime=root/'runtime';project=runtime/'project'
    if (root/'mechanic_native_capture_claim.json').exists():
        raise ValueError('Derived recording already attempted; inspect saved failure without resetting it')
    batch.verify_inputs(root)
    if project.exists():
        raise ValueError('Existing derived runtime project requires ownership/attempt review')
    if runtime.exists():
        expected='Invalid project path specified: "'+str(project)+'", aborting.'
        for name in ('observer_check.log','import.log'):
            if (runtime/name).read_text().strip()!=expected:
                raise ValueError('Not the exact proven missing-copy prelaunch failure')
        result=read(runtime/'import_result.json')
        if result.get('exit_code')!=1 or result.get('timeout') is not False:
            raise ValueError('Unexpected prelaunch import failure')
        for name in ('actions.jsonl','state_trace.jsonl','event_trace.jsonl','frame_index.jsonl'):
            path=runtime/name
            if path.exists() and path.stat().st_size:raise ValueError('Real native channel exists; no prelaunch continuation')
        if any((runtime/'frames').glob('*')) or (runtime/'dispatch_result.json').exists() or (runtime/'engine.log').exists():
            raise ValueError('Native take exists; no prelaunch continuation')
        cleanup=read(runtime/'native_cleanup_error.json')
        if cleanup.get('active_engines')!=[]:raise ValueError('Prelaunch process absence not proven')
        archive=root/'validation_history/v3_missing_runtime_snapshot_failure'
        shutil.copytree(runtime,archive)
        bindings={str(p.relative_to(root)):sha(p) for p in archive.rglob('*') if p.is_file()}
        exclusive_json(root/'mechanic_prelaunch_snapshot_repair.json',dict(time=stamp(),
            classification='NON_SCORING_RECOVERY_RUNTIME_SNAPSHOT_OMISSION',preserved_failure=bindings,
            actual_inputs_before_repair=0,actual_frames_before_repair=0,model_calls_unchanged=True))
        for name in ('actions.jsonl','state_trace.jsonl','frame_index.jsonl'):
            path=runtime/name
            if path.exists():path.unlink()
    shutil.copytree(root/'input/project',project,ignore=batch.IGNORE)
    if batch.hashes(project)!=read(root/'input_manifest.json')['snapshot_hashes']:
        raise ValueError('Runtime snapshot differs from bound author original')
    exclusive_json(root/'mechanic_runtime_snapshot.json',dict(time=stamp(),
        source=str(root/'input/project'),source_manifest_sha256=sha(root/'input_manifest.json'),
        snapshot_hashes=batch.hashes(project),author_bytes_unchanged=True))
