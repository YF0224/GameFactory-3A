"""Opt-in resource-scoped native execution leases; legacy defaults stay intact.

This protocol never reinterprets a live legacy global lease. Rollout must happen
at a normal run boundary. No lock is unlinked and no foreign process is killed.
Engine input must be native/client-local, never desktop keyboard or screenshots.
"""
from contextlib import contextmanager, ExitStack
from contextvars import ContextVar
import fcntl
import hashlib
import json
import os
from pathlib import Path
import time

from .protocol import dump, sha

VERSION = 'whitebox-engine-resource-leases.v1'
ENGINES = frozenset(('godot', 'three_js', 'ue5'))
_ACTIVE = ContextVar('whitebox_engine_execution', default=None)


def active_scope():
    return _ACTIVE.get()


def validate_policy(policy):
    if (not isinstance(policy, dict) or set(policy) != {'version', 'input', 'capture'}
            or policy['version'] != VERSION or policy['input'] != 'native_client'
            or policy['capture'] != 'native_viewport'):
        raise ValueError('Explicit native-client/native-viewport engine lease policy required')
    return policy


def engine_of_process(row):
    """Only classify positively identified executable paths, never project labels."""
    command = row['command']
    executable = command.partition(' -')[0]
    if executable.endswith('.app/Contents/MacOS/UnrealEditor'):
        return 'ue5'
    if executable.endswith(('.app/Contents/MacOS/Unity', '.app/Contents/MacOS/Tuanjie')):
        return 'unity3d'
    if Path(executable).name in ('godot', 'godot4'):
        return 'godot'
    return None


def relevant_processes(engine, processes):
    # Unclassified GUI processes remain blockers. Three.js browser instances are
    # private to each adapter; their same-engine exclusion is the engine lease.
    return [p for p in processes if engine_of_process(p) in (None, engine)]


def canonical(path):
    path = Path(path).absolute()
    if path.resolve() != path:
        raise ValueError('Linked/noncanonical execution resource: '+str(path))
    return path


def lock_file(stack, path, *, shared=False):
    path = canonical(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(path, flags, 0o600)
    stream = stack.enter_context(os.fdopen(fd, 'a+'))
    fcntl.flock(stream, (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | fcntl.LOCK_NB)
    return stream


def legacy_gate_paths(control):
    # Hold old gates SH throughout execution. Resolve only the system /tmp
    # alias (macOS /private/tmp), never a linked lock file itself.
    system_tmp = Path('/tmp').resolve()
    return [control/'whitebox_production_queue.lock',
            *[control/f'serial_{i}.lock' for i in range(3)],
            system_tmp/'gamefactory-native-playtest-gui.lock',
            system_tmp/'gamefactory-sol-whitebox-gui.lock']


def check_idle(scope, *, processes=None):
    from . import runtime
    control = Path(scope['control_root'])
    # Unknown cleanup markers cannot safely be assigned to another engine.
    for marker in (control/'background_record_cleanup_block.json',
                   control/'engine_execution'/scope['engine']/'cleanup_block.json'):
        if marker.exists():
            raise BlockingIOError('Unresolved cleanup marker; owner must resolve: '+str(marker))
    occupied = relevant_processes(scope['engine'], runtime.active_gui_engines() if processes is None else processes)
    if occupied:
        raise BlockingIOError('Same-engine or unclassified native process: '+json.dumps(occupied))
    return occupied


@contextmanager
def lease(control, engine, resource, receipt, *, policy):
    """Different engines coexist; same engine or mutable resource conflicts.

    Hold every old gate SH for the whole lease. New participants can share it;
    any old recorder/cache cleaner taking EX conflicts in either start order.
    This avoids the check-then-start race and preserves live old workers.
    """
    validate_policy(policy)
    if engine not in ENGINES:
        raise ValueError('Engine has no accepted native-client scope: '+str(engine))
    control, resource, receipt = map(canonical, (control, resource, receipt))
    token = None
    value = dict(version=VERSION, engine=engine, pid=os.getpid(),
                 control_root=str(control), resource=str(resource),
                 started_unix=time.time(), input='native_client', capture='native_viewport',
                 status='ADMISSION_PENDING', policy=policy, implementation_sha256=sha(Path(__file__)))
    # Each admission owns a fresh receipt, including failures. A losing process
    # must never replace the active owner's receipt for the same project.
    receipt.parent.mkdir(parents=True, exist_ok=True)
    with receipt.open('x') as stream:
        json.dump(value, stream, indent=2)
    base = control/'engine_execution'
    # Shared ancestors + exclusive leaf also protect nested write roots. Exact
    # hashes alone would allow one run to edit a child of another run's root.
    resources = [*reversed(resource.parents), resource]
    resource_paths = [(base/'resources'/(hashlib.sha256(str(p).encode()).hexdigest()+'.lock'),
                       p != resource) for p in resources]
    paths = [base/engine/'execution.lock', *[p for p, _ in resource_paths]]
    try:
        with ExitStack() as stack:
            for gate in legacy_gate_paths(control):
                lock_file(stack, gate, shared=True)
            lock_file(stack, paths[0])
            for path, shared in resource_paths:
                lock_file(stack, path, shared=shared)
            check_idle(value)
            value.update(status='ACTIVE', locks=list(map(str, paths)),
                         legacy_shared_gates=list(map(str, legacy_gate_paths(control))),
                         implementation_sha256=sha(Path(__file__)))
            dump(receipt, value)
            token = _ACTIVE.set(value)
            try:
                yield value
            finally:
                _ACTIVE.reset(token)
                value.update(status='RELEASED', released_unix=time.time())
                dump(receipt, value)
    except BaseException as exc:
        if value['status'] == 'ADMISSION_PENDING':
            value.update(status='ADMISSION_BLOCKED', error=repr(exc), checked_unix=time.time())
            dump(receipt, value)
        raise


def repair_scope(config, inventory, mode):
    policy = config.get('engine_execution_policy')
    if policy is None:
        return None
    validate_policy(policy)
    if config.get('unity', {}).get('additional_locks'):
        raise ValueError('Additional legacy locks need explicit resource classification before engine rollout')
    native_eval = (mode == 'evaluate' and config.get('ue_native_backend') == 'dock_native_sparse.v1'
                   and all(g.get('project', {}).get('engine') == 'ue5' for g in inventory['games']))
    if mode != 'repair' and not native_eval:
        raise ValueError('Engine-scoped refine defaults to pure repair; evaluation requires an explicit admitted UE native backend')
    engines = {g['project']['engine'] for g in inventory['games'] if g.get('project')}
    if len(engines) != 1 or not engines <= ENGINES:
        raise ValueError('Freeze exactly one supported repair engine per scoped run')
    return next(iter(engines))
