"""Shared Unity serial admission and cleanup, with explicitly configured lock roots."""
from contextlib import contextmanager
from pathlib import Path
import fcntl
import json
import os
import subprocess
import time

from . import batch, runtime
from .protocol import sha

CLEANUP_KEYS = ('input_cleanup', 'view_cleanup', 'process_cleanup')


class SafetyStop(RuntimeError):
    pass


def lock_paths(config):
    from engine_adapters.unity3d.playtest.background_record import control_paths
    return list(dict.fromkeys(control_paths(Path(config['control_root'])) +
                              [Path(p) for p in config.get('additional_locks', [])]))


def external_processes(config=None):
    result = subprocess.run(['ps', '-axo', 'pid=,args='], text=True, capture_output=True, check=True)
    active = []
    tokens = ('pipeline.game_eval.whitebox_eval.unity_single', 'run_tiered_unity_serial.py',
              'run_endpoint_night.py', 'run_editor_g014.py', 'run_formal_g014.py')
    for line in result.stdout.splitlines():
        pid, _, command = line.strip().partition(' ')
        if not pid.isdigit() or int(pid) == os.getpid():
            continue
        # Ignore shell wrappers and ps/rg invocations; track the actual interpreters.
        executable = command.split(' ', 1)[0].lower()
        if ('python' in executable or executable.endswith('/python.app/contents/macos/python')) and any(t in command for t in tokens):
            if config is not None and 'pipeline.game_eval.whitebox_eval.unity_single' in command:
                waiter = Path(config['control_root'])/'production_lease_waiters'/(pid+'.json')
                if waiter.is_file():
                    value = batch.read(waiter)
                    if (value.get('version') == 'whitebox-production-lease-waiter.v1'
                            and value.get('pid') == int(pid) and value.get('status') == 'WAITING'
                            and '--output '+str(value.get('output')) in command):
                        continue
            active.append({'pid': int(pid), 'command': command})
    return active


def locks_clear(config, *, check_external=False):
    # Scoped repair is opt-in and already holds legacy gates SH plus its engine
    # and mutable-resource locks. Never reacquire those gates EX in this scope.
    from . import repair_execution
    project_scope = repair_execution.active_scope()
    if project_scope is not None:
        if Path(config['control_root']).resolve() != Path(project_scope['control_root']):
            raise SafetyStop('Repair execution scope/control root mismatch')
        repair_execution.check_idle(project_scope)
        return list(project_scope['locks'])
    from .engine_execution import active_scope, check_idle
    scope = active_scope()
    if scope is not None:
        if Path(config['control_root']).resolve() != Path(scope['control_root']):
            raise SafetyStop('Execution scope/control root mismatch')
        check_idle(scope)
        if check_external:
            active = external_processes(config)
            if active:
                raise BlockingIOError('External serial evaluation outside engine scope: '+json.dumps(active))
        return list(scope['locks'])
    control = Path(config['control_root'])
    if (control/'background_record_cleanup_block.json').exists():
        from .unity_cleanup_policy import report_only, archive_marker
        if report_only(config):
            archive_marker(config)
        else:
            raise SafetyStop('Unresolved input/view/process cleanup stop marker: '+str(control))
    occupied = runtime.active_gui_engines()
    if occupied:
        raise BlockingIOError('Active GUI engine: '+json.dumps(occupied, ensure_ascii=False))
    if check_external:
        active = external_processes(config)
        if active:
            raise BlockingIOError('External serial Unity evaluation: '+json.dumps(active))
    handles = []
    try:
        for path in lock_paths(config):
            path.parent.mkdir(parents=True, exist_ok=True)
            stream = path.open('a+')
            handles.append(stream)
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        for handle in reversed(handles):
            handle.close()
    return [str(p) for p in lock_paths(config)]


@contextmanager
def held_locks(config):
    from .engine_execution import active_scope
    if active_scope() is not None:
        raise SafetyStop('Legacy exclusive held_locks cannot nest inside an engine scope')
    locks_clear(config)
    handles = []
    try:
        for path in lock_paths(config):
            stream = path.open('a+')
            handles.append(stream)
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        for stream in reversed(handles):
            stream.close()


def capture_cleanup(capture):
    capture = Path(capture)
    if (capture/'preinput_cleanup_qualification.json').is_file():
        from .unity_preinput_cleanup import qualify
        qualified = qualify(capture)
        saved = batch.read(capture/'preinput_cleanup_qualification.json')
        if any(saved.get(k) != v for k, v in qualified.items()):
            raise SafetyStop('Pre-input cleanup qualification changed: '+str(capture))
        return {k: True for k in CLEANUP_KEYS} | {'preinput_cleanup_sha256':sha(capture/'preinput_cleanup_qualification.json')}
    verification = batch.read(capture/'verification.json')
    receipt = batch.read(capture/'runner_exit.json')
    if (receipt.get('cleanup_verified') is not True or receipt.get('policy_violations')
            or any(verification.get('checks', {}).get(k) is not True for k in CLEANUP_KEYS)):
        raise SafetyStop('Input/view/process cleanup uncertain: '+str(capture))
    return {**{k: True for k in CLEANUP_KEYS}, 'verification_sha256': sha(capture/'verification.json'),
            'runner_exit_sha256': sha(capture/'runner_exit.json')}


def check(config, capture=None):
    result = {'locks': locks_clear(config), 'stop_marker_absent': True, 'checked_unix': time.time()}
    if capture is not None:
        from .unity_cleanup_policy import report_only, capture_report
        if report_only(config):
            result.update(capture_report(config, capture))
        else:
            result.update(capture_cleanup(capture))
    return result
