"""Opt-in sparse recording under engine/resource leases, with unchanged gates.

Legacy sparse_native and runtime pins remain byte-for-byte unchanged. This
orchestrator invokes the same native backends and all original plan, schedule,
source, pixels, cleanup and evidence validators. No OS input fallback exists.
"""
from pathlib import Path
import os
import time

from . import batch, core12, endpoint_sparse, runtime, sparse_native, sparse_evidence
from . import engine_execution
from .protocol import dump, sha, write_operation_report

POLICY_FILE = 'engine_execution_policy.json'


def enabled(workspace):
    path = Path(workspace)/POLICY_FILE
    if not path.exists():
        return False
    engine_execution.validate_policy(batch.read(path))
    return True


def sources(engine):
    paths = dict(sparse_native.adapter_sources(engine))
    folder = Path(__file__).parent
    for name in ('engine_execution.py', 'engine_scoped_capture.py', 'runtime.py',
                 'batch.py', 'budgets.py', 'mechanic_v3_record_completion.py',
                 'mechanic_v3_outcome_native.py', 'mechanic_v3_runner.py', 'unity_safety.py', 'protocol.py'):
        paths[str(folder/name)] = sha(folder/name)
    if engine == 'three_js':
        root = Path(__file__).resolve().parents[3]
        for path in (root/'engine_adapters/three_js').rglob('*'):
            if path.suffix in ('.py', '.mjs'):
                paths[str(path)] = sha(path)
    return paths


def run_native(root, operation, godot, engine, scope):
    """The old runtime budget/normalization, using the already-held engine lease."""
    from .budgets import resolve_recording_budget
    root = Path(root)
    proto_path = root/'input/pilot_rubric.json'
    proto = batch.read(proto_path)
    operation = batch.validate_operation_plan(root, operation, engine)
    budget = resolve_recording_budget(root, proto.get('runtime_budget', {}))
    if (root/'native_record_completion_policy.json').exists():
        from .mechanic_v3_record_completion import effective_budget
        budget = effective_budget(root, proto, operation, budget)
    start = time.monotonic()
    deadline = start + budget['engine_call_ms']*.001
    dump(root/'runtime/budget_resolution.json', dict(effective_budget=budget,
        plan_max_duration_ms=operation.get('max_duration_ms'),
        passive_observation_extension_ms=max(0, budget['recording_ms']-operation.get('max_duration_ms', budget['recording_ms'])),
        source_protocol_sha256=sha(proto_path)))
    dump(root/'runtime/preflight.json', dict(checked_unix=time.time(), pid=os.getpid(),
        engine=engine, target=str(root/'runtime/project'), engine_execution=scope,
        policy='native client input and viewport; same-engine/resource serialization'))
    if engine == 'godot':
        console = runtime.console_gui_status(capture_backend='client_viewport')
        if not console['available']:
            dump(root/'gui_session_blocker.json', console)
            raise RuntimeError('HARNESS_ERROR: native viewport console unavailable')
    engine_execution.check_idle(scope)
    try:
        if engine == 'godot':
            return runtime._run_engine_unlocked(root, operation, Path(godot).resolve(), deadline=deadline, budget=budget)
        from pipeline.code_gen.playtest.engine_dispatch import resolve_engine
        return runtime._native_run(root, operation, resolve_engine(engine), Path(godot).resolve(), deadline=deadline, budget=budget)
    except Exception as exc:
        if not (root/'runtime/engine_result.json').exists():
            dump(root/'runtime/engine_result.json', dict(engine=engine, status='HARNESS_ERROR', error=str(exc), product_errors=False))
        raise
    finally:
        import sys
        primary = sys.exc_info()[1]
        dump(root/'runtime/timing.json', dict(engine=engine, elapsed_ms=round((time.monotonic()-start)*1000),
            budget=budget, timeout=time.monotonic()>deadline,
            timeout_reason='engine_call deadline exceeded' if time.monotonic()>deadline else None))
        try:
            runtime.normalize_channels(root, engine)
        except Exception as normalization:
            if primary is None:
                raise
            dump(root/'runtime/channel_normalization_error.json', dict(status='HARNESS_ERROR',
                error=str(normalization), primary_error=str(primary), raw_evidence_preserved=True))


def launcher_acceptance(workspace):
    """Select a SHA-bound new acceptance without replacing historical evidence."""
    workspace=Path(workspace)
    binding=workspace/'engineering/three_js_launch_native_acceptance_binding.json'
    receipt=workspace/'engineering/three_js_launch_native_acceptance.json'
    if binding.is_file():
        pointer=batch.read(binding)
        receipt=Path(pointer['path'])
        if sha(receipt)!=pointer['sha256']:
            raise ValueError('Three.js launcher acceptance binding changed')
    accepted=batch.read(receipt)
    if accepted.get('accepted') is not True or accepted.get('production_sources')!=sources('three_js'):
        raise ValueError('Matching full Three.js launcher native acceptance required')
    for name,digest in accepted['evidence_bindings'].items():
        if sha(Path(name))!=digest:
            raise ValueError('Three.js launcher acceptance evidence changed: '+name)
    return dict(path=str(receipt.resolve()),sha256=sha(receipt),
        binding_path=str(binding.resolve()) if binding.is_file() else None,
        binding_sha256=sha(binding) if binding.is_file() else None)


def capture(workspace, root, operation, args, entry):
    workspace, root = Path(workspace).resolve(), Path(root).resolve()
    policy_path = workspace/POLICY_FILE
    policy = engine_execution.validate_policy(batch.read(policy_path))
    engine = entry['actual_engine']
    if engine not in ('godot', 'three_js'):
        raise ValueError('Scoped sparse recording supports Godot/Three.js only')
    # New Three.js launcher changes require their own native acceptance. An
    # old subset pin must never silently qualify the new launcher.
    launcher = launcher_acceptance(workspace) if engine == 'three_js' else None
    acceptance = sparse_native.verify_acceptance(root.parent.parent, engine)
    operation = batch.validate_operation_plan(root, operation, engine)
    proto = batch.read(root/'input/pilot_rubric.json')
    endpoint_sparse.validate_policy(proto)
    dump(root/'sol_plan.json', operation)
    write_operation_report(root, operation)
    gate = batch.validate_capture_plan(root, proto, operation)
    dump(root/'validation_history/capture_plan_validation.json', gate)
    if not gate['valid']:
        raise ValueError('capture plan gate failed: '+str(gate))
    sparse_native.space(root, 'native_record', estimated_bytes=2*1024**3)
    config = batch.read(workspace/'native_capture_configuration.json')
    expected_gates = set(engine_execution.legacy_gate_paths(Path(config['control_root'])))
    configured_gates = {Path(p).resolve() for p in config['outer_execution_locks']}
    configured_gates.add(Path(config['runtime_owned_gui_lock']).resolve())
    if configured_gates != expected_gates:
        raise ValueError('Explicit resource classification required for changed legacy gate configuration')
    lease_receipt = root/'execution_admissions'/(str(time.time_ns())+'.json')
    with engine_execution.lease(Path(config['control_root']), engine, root/'runtime/project',
            lease_receipt, policy=policy) as scope:
        dump(root/'native_capture_admission.json', dict(version=engine_execution.VERSION,
            pid=os.getpid(), acceptance=acceptance, launcher_acceptance=launcher, plan_sha256=sha(root/'sol_plan.json'),
            configuration_sha256=sha(workspace/'native_capture_configuration.json'),
            policy_path=str(policy_path), policy_sha256=sha(policy_path),
            production_sources=sources(engine), engine_execution=scope,
            lease_receipt=str(lease_receipt),
            validation_status='PENDING_NATIVE_VALIDATION', time=time.time()))
        batch.status(root, 'RECORDING', pid=os.getpid(), engine=engine)
        try:
            run_native(root, operation, args.godot, engine, scope)
        finally:
            import sys
            primary = sys.exc_info()[1]
            try:
                sparse_native.cleanup(root, engine)
            except Exception as error:
                active = runtime.active_gui_engines()
                owned = [p for p in active if str(root) in p['command']]
                diagnostic = dict(owner='engine_scoped_capture', root=str(root), pid=os.getpid(),
                                  reason=repr(error), primary_error=repr(primary) if primary else None,
                                  active_engines=active, live_owned_engines=owned)
                dump(root/'runtime/native_cleanup_error.json', diagnostic)
                if owned:
                    marker = Path(config['control_root'])/'engine_execution'/engine/'cleanup_block.json'
                    if not marker.exists():
                        with marker.open('x') as stream:
                            import json
                            json.dump(diagnostic, stream, indent=2)
                if primary is None:
                    raise
        audit = sparse_evidence.audit_capture(root/'runtime')
        dump(root/'validation_history/native_sparse_capture_audit.json', audit)
    sparse_native.space(root, 'evidence', estimated_bytes=2*1024**3)
    manifest = batch.deliver(root)
    validation = batch.validate_capture_bundle(root, manifest)
    dump(root/'validation_history/capture_bundle_validation.json', validation)
    if not validation['valid']:
        raise ValueError('capture evidence gate failed: '+str(validation))
    dump(root/'validation_history/engine_scoped_native_validation.json',
         dict(version=engine_execution.VERSION, native_record_verified=True,
              cleanup_verified=True, capture_bundle_verified=True, production_sources=sources(engine),
              evidence_bindings={str(root/name):sha(root/name) for name in (
                  'native_capture_admission.json', 'runtime/native_cleanup.json',
                  'validation_history/native_sparse_capture_audit.json',
                  'validation_history/capture_bundle_validation.json', 'evidence_manifest.json')},
              lease_receipt=str(lease_receipt), lease_sha256=sha(lease_receipt)))
    batch.status(root, 'RECORDED', native_cleanup_verified=True)
    return manifest


def qualify(root):
    """Bind scoped admission, released lease and full native validation to scores."""
    root = Path(root)
    admission_path = root/'native_capture_admission.json'
    admission = batch.read(admission_path)
    if admission.get('version') != engine_execution.VERSION:
        return {}
    validation_path = root/'validation_history/engine_scoped_native_validation.json'
    validation = batch.read(validation_path)
    receipt_path = Path(admission['lease_receipt'])
    receipt = batch.read(receipt_path)
    if (validation.get('version') != engine_execution.VERSION
            or any(validation.get(k) is not True for k in
                   ('native_record_verified', 'cleanup_verified', 'capture_bundle_verified'))
            or validation.get('production_sources') != admission['production_sources']
            or validation.get('lease_receipt') != str(receipt_path)
            or validation.get('lease_sha256') != sha(receipt_path)
            or receipt.get('status') != 'RELEASED'
            or receipt.get('engine') != admission['engine_execution']['engine']
            or receipt.get('pid') != admission['pid']
            or receipt.get('resource') != str(root/'runtime/project')):
        raise ValueError('Engine-scoped native validation/lease mismatch')
    bindings = dict(validation['evidence_bindings'])
    required = {str(root/name) for name in (
        'native_capture_admission.json', 'runtime/native_cleanup.json',
        'validation_history/native_sparse_capture_audit.json',
        'validation_history/capture_bundle_validation.json', 'evidence_manifest.json')}
    if set(bindings) != required:
        raise ValueError('Engine-scoped native validation omits required evidence bindings')
    if bindings.get(str(admission_path)) != sha(admission_path):
        raise ValueError('Engine-scoped admission is not bound to validation')
    for name, digest in bindings.items():
        if sha(Path(name)) != digest:
            raise ValueError('Engine-scoped native evidence changed: '+name)
    return dict(bindings, **{str(validation_path):sha(validation_path), str(receipt_path):sha(receipt_path)})
