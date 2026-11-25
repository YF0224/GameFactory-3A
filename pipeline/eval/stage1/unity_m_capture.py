"""First Unity M native capture through the current formal two-column entry.

This explicit acceptance case records only. No legacy eight-column scorer runs.
"""
from pathlib import Path
import argparse
import fcntl
import time
import os
from contextlib import contextmanager
from . import batch, unity_m_scope, unity_safety, unity_single, unity_disk_guard
from . import mechanic_v3_revision, mechanic_v3_outcome, gameness_v4, core12
from .protocol import dump, sha
from engine_adapters.unity3d.playtest import native_acceptance



@contextmanager
def native_queue_lease(control, root, identity, *, timeout=1200.0, poll=5.0):
    """One admitted worker waits for the real EX lease; no native work before it.

    Preserve every wait receipt and never alter another process's lock/claim.
    Source, editor, safety and disk gates remain in capture after acquisition.
    """
    started = time.monotonic()
    path = root/'native_lease_waits'/(str(time.time_ns())+'_'+str(os.getpid())+'.json')
    state = dict(version='unity-m-native-queue-wait.v1', identity=identity,
        pid=os.getpid(), lock=str(control/'whitebox_production_queue.lock'),
        started_unix=time.time(), timeout_seconds=timeout, status='WAITING',
        contention_observations=0, native_work_before_acquisition=False)
    dump(path, state)
    with (control/'whitebox_production_queue.lock').open('a+') as lease:
        try:
            while True:
                if (control/'background_record_cleanup_block.json').exists():
                    raise unity_safety.SafetyStop('Cleanup stop marker appeared while waiting for native lease')
                try:
                    fcntl.flock(lease, fcntl.LOCK_EX|fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    state['contention_observations'] += 1
                    state['last_observed_unix'] = time.time()
                    dump(path, state)
                    remaining = timeout-(time.monotonic()-started)
                    if remaining <= 0:
                        raise TimeoutError('Unity M native queue lease wait exhausted before dispatch')
                    if state['contention_observations'] == 1:
                        print('UNITY_M_WAITING_NATIVE_QUEUE_LEASE', identity, str(path), flush=True)
                    time.sleep(min(poll, remaining))
            state.update(status='ACQUIRED', acquired_unix=time.time(),
                         waited_seconds=time.monotonic()-started)
            dump(path, state)
            print('UNITY_M_NATIVE_QUEUE_LEASE_ACQUIRED', identity, flush=True)
            yield lease
        except BaseException as exc:
            state.update(status='FAILED', error_type=type(exc).__name__, error=str(exc),
                         finished_unix=time.time())
            dump(path, state)
            raise
        else:
            state.update(status='RELEASED', finished_unix=time.time())
            dump(path, state)


def qualify_source(workspace, identity):
    inventory = unity_m_scope.load(workspace)
    rows = {r['entry']['id']:r for r in inventory['entries'] if r['in_scope']}
    row = rows[identity]
    if row['source_blocker'] or unity_m_scope.source_files(Path(row['entry']['project'])) != row['source_hashes']:
        raise ValueError('Original source missing or changed')
    root = workspace/'runs'/identity
    batch.verify_inputs(root)
    binding = batch.read(root/'unity_m_source_binding.json')
    if (binding['scope_sha256'] != sha(workspace/'scopes/unity_m_original/scope.json')
            or binding['source_hashes'] != row['source_hashes']):
        raise ValueError('Unity M frozen source/scope binding changed')
    folder = mechanic_v3_revision.contract_dir(workspace,row['entry']['case_id'])
    gf = workspace/'gameness_contracts/outcome_frame_v1'/row['entry']['case_id']
    for directory, key in [(folder,'mechanic_frozen_sha256'),(gf,'gameness_frozen_sha256')]:
        frozen = batch.read(directory/'frozen.json')
        if sha(directory/'frozen.json') != binding[key] or sha(directory/'contract.json') != frozen['contract_sha256']:
            raise ValueError('Unity M frozen outcome contract changed')
    proto = core12.verify_attempt(root,'unity3d')
    mechanic_v3_outcome.validate_contract(proto,batch.read(folder/'contract.json'))
    gameness_v4.validate_contract(proto,batch.read(gf/'contract.json'))
    batch.validate_operation_plan(root,batch.read(root/'sol_plan.json'),'unity3d')
    gate = batch.validate_capture_plan(root)
    if not gate['valid']: raise ValueError(gate)
    return root, row, proto


def capture(workspace, identity, configuration, acceptance_case=False):
    from . import unity_m_admission
    unity_m_admission.require(workspace,identity,acceptance_case=acceptance_case)
    root, row, proto = qualify_source(workspace,identity)
    if (root/'unity_m_capture.json').exists():
        from .unity_m_evidence import qualify_recorded
        qualify_recorded(root)
        print('UNITY_M_QUALIFIED_CAPTURE_REUSED',identity,flush=True)
        return batch.read(root/'unity_m_capture.json')
    admission = None if acceptance_case else unity_m_admission.admission_path(workspace,unity_m_admission.production())
    config = batch.read(configuration)
    adapter = Path(__file__).resolve().parents[3]
    if Path(config['adapter_root']).resolve() != adapter:
        raise ValueError('Formal adapter only')
    accepted = Path(config['editor_acceptance'])
    native = batch.read(accepted)
    native_acceptance.verify(accepted,adapter,Path(native['editor']))
    control = Path(config['control_root'])
    with native_queue_lease(control, root, identity):
        unity_safety.locks_clear(config,check_external=True)
        from . import runtime
        from engine_adapters.unity3d.playtest.background_record import recording_duration
        actions = runtime.native_actions(batch.read(root/'sol_plan.json'))
        duration = recording_duration(actions,proto['runtime_budget']['recording_ms']/1000)
        unity_disk_guard.check(workspace,'capture',Path(row['entry']['project']),
                              duration=duration,frames=int(duration*10),width=960,height=540)
        output = root/'unity_m_native_dispatch'
        recovery = output/'input_migration_recovery.json'
        process_receipts = None
        if output.exists():
            if batch.read(output/'configuration.json') != config:
                raise ValueError('Preserved native dispatch configuration differs')
            if not (root/'background_record/verification.json').is_file():
                failure = root/'native_record_process/failure.json'
                exact_error = 'Requires reviewed InputSystem-only project; migrate legacy input in an isolated version first'
                if (not failure.is_file() or batch.read(failure).get('error') != exact_error
                        or (root/'background_record').exists()):
                    raise ValueError('Only exact prelaunch input-handler failure qualifies for this recovery')
                process_receipts = root/'native_record_process__input_migration_v1'
                if process_receipts.exists():
                    raise ValueError('Preserved migration continuation requires diagnosis; no unchanged retry')
                from .mechanic_v3_runner import exclusive_json
                exclusive_json(recovery,{'version':'unity-m-prelaunch-input-recovery.v1',
                    'parent_failure':str(failure),'parent_failure_sha256':sha(failure),
                    'original_request_sha256':sha(failure.parent/'request.json'),
                    'old_dispatch_sha256':sha(output/'dispatch.json'),
                    'production':{str(p):sha(p) for p in Path(__file__).parent.glob('*.py')},
                    'maximum_continuation_calls':1,'native_editor_launched':False})
                # Keep exact old binding bytes even though actions and plan stay identical.
                old_binding=root/'recorder_acceptance_binding.json'
                (output/'recorder_acceptance_binding.before.json').write_bytes(old_binding.read_bytes())
        else:
            output.mkdir();dump(output/'configuration.json',config)
            dump(output/'dispatch.json',{'configuration':str(configuration),'sha256':sha(configuration),
                 'created':time.time(),'first_two_column_acceptance_case':acceptance_case,
                 'two_column_admission':None if admission is None else {'path':str(admission),'sha256':sha(admission)},
                 'source_binding_sha256':sha(root/'unity_m_source_binding.json'),
                 'native_acceptance_sha256':sha(accepted),'recording_seconds':duration})
        from .unity_m_input_adapter import prepare as prepare_input
        prepare_input(root, output, accepted)
        value = unity_single.complete_capture(output,root,capture_only=True,
                                             process_receipt_directory=process_receipts)
        if unity_m_scope.source_files(Path(row['entry']['project'])) != row['source_hashes']:
            raise ValueError('Original source changed during recording')
        dump(root/'unity_m_capture.json',{'stage':'NATIVE_CAPTURE_QUALIFIED_NOT_SCORED',
            'source_binding_sha256':sha(root/'unity_m_source_binding.json'),
            'native_acceptance_sha256':sha(accepted),'cleanup':value['cleanup'],
            'capture':str(root/'background_record'),'two_column_e2e_accepted':not acceptance_case,
            'two_column_admission':None if admission is None else {'path':str(admission),'sha256':sha(admission)}})
        return value


def main(argv):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workspace',type=Path,required=True)
    p.add_argument('--phase',choices=['unity-m-capture'],required=True)
    p.add_argument('--ids',nargs='+',required=True)
    p.add_argument('--native-configuration',type=Path,required=True)
    p.add_argument('--acceptance-case',action='store_true')
    a=p.parse_args(argv)
    if len(a.ids)!=1:raise ValueError('One identity per owned native dispatch')
    w=a.workspace.resolve()
    with (w/'.unity_m_native.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        capture(w,a.ids[0],a.native_configuration.resolve(),a.acceptance_case)
    return 0
