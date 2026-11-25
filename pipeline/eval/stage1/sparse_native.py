"""Accepted Godot/Three.js sparse capture, using the unchanged endpoint schedule.

No score selection or evidence validation lives here. The existing plan, native
frame, channel, source and bundle validators remain authoritative.
"""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import shutil
import time

from .protocol import dump, sha

VERSION = 'whitebox-godot-threejs-native-sparse.v1'
RESERVE = 8 * 1024**3


def adapter_sources(engine):
    framework = Path(__file__).resolve().parents[3]
    paths = ['pipeline/eval/stage1/sparse_native.py']
    if engine == 'godot':
        paths += ['engine_adapters/godot/playtest/'+name for name in
                  ('bounded_recorder.gd', 'client.py', 'scene_entry.py')]
    elif engine == 'three_js':
        paths += ['engine_adapters/three_js/playtest/'+name for name in
                  ('record.mjs', 'client.py', 'browser_runtime.mjs', 'action_provenance.mjs', 'event_snapshots.mjs')]
        paths += ['engine_adapters/three_js/_internal/transport/node.py',
                  'engine_adapters/three_js/playtest/dependencies.py']
    else:
        raise ValueError('Sparse native backend supports Godot/Three.js only')
    return {str(framework/path): sha(framework/path) for path in paths}


def space(root, phase, *, estimated_bytes):
    root = Path(root)
    free = shutil.disk_usage(root).free
    receipt = {'phase':phase, 'available_bytes':free, 'estimated_next_stage_bytes':estimated_bytes,
               'reserve_bytes':RESERVE, 'required_bytes':estimated_bytes+RESERVE,
               'shortfall_bytes':max(0, estimated_bytes+RESERVE-free), 'checked_unix':time.time()}
    dump(root/'disk_checks'/f'{time.time_ns()}_{phase}.json', receipt)
    if receipt['shortfall_bytes']:
        raise OSError('Insufficient disk space: '+json.dumps(receipt))
    return receipt


def verify_acceptance(batch, engine):
    path = Path(batch)/'engineering/native_acceptance'/(engine+'.json')
    value = json.loads(path.read_text())
    if (value.get('version') != VERSION or value.get('accepted') is not True
            or value.get('adapter_sources') != adapter_sources(engine)
            or not value.get('real_input_verified') or not value.get('native_frame_verified')
            or not value.get('cleanup_verified')):
        raise ValueError('Native sparse acceptance missing or changed: '+str(path))
    for file, digest in value['evidence_bindings'].items():
        if sha(Path(file)) != digest:
            raise ValueError('Native sparse acceptance evidence changed: '+file)
    return {'path':str(path), 'sha256':sha(path), 'adapter_sources':value['adapter_sources']}


@contextmanager
def shared_execution(batch):
    """Cooperate with existing production leases; runtime owns the final GUI lock."""
    from . import runtime
    config = json.loads((Path(batch)/'native_capture_configuration.json').read_text())
    control = Path(config['control_root'])
    if (control/'background_record_cleanup_block.json').exists():
        raise BlockingIOError('Existing cleanup stop marker requires its owning session')
    active = runtime.active_gui_engines()
    if active:
        raise BlockingIOError('Other native engine active: '+json.dumps(active))
    handles = []
    try:
        for name in config['outer_execution_locks']:
            path = Path(name)
            path.parent.mkdir(parents=True, exist_ok=True)
            handle = path.open('a+')
            handles.append(handle)
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # A producer that has not yet acquired these locks must still be protected.
        active = runtime.active_gui_engines()
        if active:
            raise BlockingIOError('Native engine appeared during lease acquisition: '+json.dumps(active))
        yield config
    finally:
        for handle in reversed(handles):
            handle.close()


def cleanup(root, engine):
    root = Path(root)
    folder = root/'runtime'
    if engine == 'godot':
        inputs = json.loads((folder/'input_view_cleanup.json').read_text())
        processes = json.loads((folder/'process_cleanup.json').read_text())
        checks = {'input_cleanup':inputs.get('input_cleanup') is True,
                  'view_cleanup':processes.get('view_cleanup') is True,
                  'process_cleanup':processes.get('process_cleanup') is True}
        paths = [folder/'input_view_cleanup.json', folder/'process_cleanup.json']
    else:
        native = Path(json.loads((folder/'dispatch_result.json').read_text())['envelope']['payload']['take_dir'])
        browser = json.loads((native/'browser_cleanup.json').read_text())
        process = json.loads((native/'host_process_cleanup.json').read_text())
        checks = {'input_cleanup':browser.get('input_cleanup') is True,
                  'view_cleanup':browser.get('view_cleanup') is True,
                  'process_cleanup':browser.get('browser_cleanup') is True and process.get('process_cleanup') is True}
        paths = [native/'browser_cleanup.json', native/'host_process_cleanup.json']
    receipt = {'version':VERSION, 'engine':engine, **checks, 'checks':checks,
               'sources':{str(p):sha(p) for p in paths}, 'checked_unix':time.time()}
    dump(folder/'native_cleanup.json', receipt)
    if not all(checks.values()):
        raise RuntimeError('Native cleanup unresolved; preserve engine stop: '+json.dumps(receipt))
    return receipt


def capture(root, operation, args, entry):
    from . import batch, runtime, endpoint_sparse, sparse_evidence
    from .protocol import write_operation_report
    root = Path(root)
    batch_dir = root.parent.parent
    engine = entry['actual_engine']
    acceptance = verify_acceptance(batch_dir, engine)
    operation = batch.validate_operation_plan(root, operation, engine)
    proto = batch.read(root/'input/pilot_rubric.json')
    endpoint_sparse.validate_policy(proto)
    dump(root/'sol_plan.json', operation)
    write_operation_report(root, operation)
    gate = batch.validate_capture_plan(root, proto, operation)
    dump(root/'validation_history/capture_plan_validation.json', gate)
    if not gate['valid']:
        raise ValueError('capture plan gate failed: '+json.dumps(gate))
    # At most 361 original 960x540/1280x720 frames plus continuous traces.
    space(root, 'native_record', estimated_bytes=2*1024**3)
    with shared_execution(batch_dir) as config:
        dump(root/'native_capture_admission.json', {'version':VERSION, 'pid':os.getpid(),
             'acceptance':acceptance, 'plan_sha256':sha(root/'sol_plan.json'),
             'configuration_sha256':sha(batch_dir/'native_capture_configuration.json'),
             'outer_execution_locks':config['outer_execution_locks'], 'time':time.time()})
        if engine == 'godot':
            runtime.assert_gui_available(root, capture_backend='client_viewport')
        batch.status(root, 'RECORDING', pid=os.getpid(), engine=engine)
        try:
            runtime.run_engine(root, operation, Path(args.godot).resolve(), engine=engine)
        except BaseException:
            try:cleanup(root, engine)
            except Exception as error:
                # A pre-launch failure has no cleanup receipt. Keep a local
                # diagnostic; only real owned live engines justify quarantine.
                active = runtime.active_gui_engines()
                dump(root/'runtime/native_cleanup_error.json',
                     {'owner':'opus_s_native_sparse','root':str(root),'pid':os.getpid(),
                      'reason':repr(error),'active_engines':active,'created_unix':time.time()})
                owned = [row for row in active if str(root) in json.dumps(row)]
                if owned:
                    marker=Path(config['control_root'])/'background_record_cleanup_block.json'
                    if not marker.exists():
                        with marker.open('x') as stream:
                            json.dump({'owner':'opus_s_native_sparse','root':str(root),
                                'pid':os.getpid(),'live_owned_engines':owned,
                                'reason':repr(error),'created_unix':time.time()},stream,indent=2)
            raise
        cleanup(root, engine)
        audit = sparse_evidence.audit_capture(root/'runtime')
        dump(root/'validation_history/native_sparse_capture_audit.json', audit)
    # Native processes have exited before preparing judge artifacts.
    space(root, 'evidence', estimated_bytes=2*1024**3)
    manifest = batch.deliver(root)
    validation = batch.validate_capture_bundle(root, manifest)
    dump(root/'validation_history/capture_bundle_validation.json', validation)
    if not validation['valid']:
        raise ValueError('capture evidence gate failed: '+json.dumps(validation))
    batch.status(root, 'RECORDED', native_cleanup_verified=True)
    return manifest
