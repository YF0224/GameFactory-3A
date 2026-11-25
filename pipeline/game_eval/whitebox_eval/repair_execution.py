"""Opt-in candidate-local repair leases. No evaluation or process killing.

Legacy EX gates remain authoritative. UE candidates may coexist; Unity takes
an exclusive native lane until its parallel runtime has been qualified.
"""
from contextlib import contextmanager, ExitStack
from contextvars import ContextVar
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import time

from . import engine_execution as locks
from .protocol import dump, sha

VERSION = 'refine-project-execution.v1'
_ACTIVE = ContextVar('refine_project_execution', default=None)


def active_scope():
    return _ACTIVE.get()


def validate(config, inventory, mode):
    policy = config.get('repair_execution_policy')
    if policy is None:
        return None
    if (mode != 'repair' or policy != {'version': VERSION, 'input': 'native_client',
                                      'capture': 'native_viewport'}):
        raise ValueError('Project isolation requires explicit pure repair native policy')
    if config.get('engine_execution_policy') or config.get('unity', {}).get('additional_locks'):
        raise ValueError('Conflicting execution policies or unclassified additional locks')
    games = inventory['games']
    if len(games) != 1 or not games[0].get('project'):
        raise ValueError('Project isolation requires exactly one located candidate')
    engine = games[0]['project']['engine']
    if engine not in ('ue5', 'unity3d'):
        raise ValueError('Project isolation is not qualified for this engine: ' + engine)
    root = locks.canonical(config['repair_candidate_root'])
    source = Path(games[0]['project']['project_root']).resolve()
    if root == source or root.is_relative_to(source) or source.is_relative_to(root):
        raise ValueError('Candidate must be separate from original source')
    return engine, root


def process_rows():
    result = subprocess.run(['ps', '-axo', 'pid=,ppid=,command='], capture_output=True,
                            text=True, check=True, timeout=10)
    rows = []
    for line in result.stdout.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            rows.append(dict(pid=int(parts[0]), ppid=int(parts[1]), command=parts[2]))
    return rows


def native_process(row):
    # Executable must occur at the start; prompts containing engine paths do not count.
    return bool(re.match(r'^/[^\n]*?\.app/Contents/MacOS/(?:UnrealEditor|Unity|Tuanjie)(?: |$)',
                         row['command']))


def owned_processes(scope, rows):
    descendants = {scope['pid']}
    while True:
        more = {r['pid'] for r in rows if r['ppid'] in descendants}
        if more <= descendants:
            break
        descendants |= more
    root = str(Path(scope['resource']).resolve())
    # Match an exact path boundary, including unquoted macOS paths with spaces.
    project = re.compile(r'(?:^|[\s\"\'])' + re.escape(root) + r'(?:[/\s\"\']|$)')
    return [r for r in rows if native_process(r) and
            (r['pid'] in descendants or project.search(r['command']))]


def check_idle(scope, *, rows=None):
    control = Path(scope['control_root'])
    for marker in (control/'background_record_cleanup_block.json',
                   Path(scope['output'])/'repair_execution/cleanup_block.json'):
        if marker.exists():
            raise BlockingIOError('Unresolved cleanup marker: ' + str(marker))
    occupied = owned_processes(scope, process_rows() if rows is None else rows)
    if occupied:
        raise BlockingIOError('This repair still owns native processes: ' + json.dumps(occupied))
    return []


def resource_locks(stack, control, resource):
    result = []
    for path in [*reversed(resource.parents), resource]:
        target = control/'engine_execution/resources'/(hashlib.sha256(str(path).encode()).hexdigest()+'.lock')
        locks.lock_file(stack, target, shared=path != resource)
        result.append(str(target))
    return result


def allocate_ports(stack, control):
    # Each number is leased for the whole repair; probe TCP and UDP before use.
    # This coordinates participants, not arbitrary applications outside the protocol.
    chosen = []
    for number in range(31000, 32000):
        trial = ExitStack()
        try:
            locks.lock_file(trial, control/'repair_execution/ports'/f'{number}.lock')
            for kind in (socket.SOCK_STREAM, socket.SOCK_DGRAM):
                with socket.socket(socket.AF_INET, kind) as probe:
                    probe.bind(('127.0.0.1', number))
        except OSError:
            trial.close()
            continue
        stack.enter_context(trial)
        chosen.append(number)
        if len(chosen) == 3:
            return chosen
    raise BlockingIOError('No three isolated UE ports are available')


@contextmanager
def lease(config, inventory, output, *, mode='repair'):
    engine, resource = validate(config, inventory, mode)
    output = locks.canonical(output)
    control = locks.canonical(config['unity']['control_root'])
    receipt = output/'repair_execution'/f'{time.time_ns()}_{os.getpid()}.json'
    value = dict(version=VERSION, pid=os.getpid(), engine=engine, resource=str(resource),
                 output=str(output), control_root=str(control), status='ADMISSION_PENDING',
                 started_unix=time.time(), implementation_sha256=sha(Path(__file__)))
    receipt.parent.mkdir(parents=True, exist_ok=True)
    with receipt.open('x') as f:
        json.dump(value, f)
    try:
        with ExitStack() as stack:
            paths = []
            for gate in locks.legacy_gate_paths(control):
                locks.lock_file(stack, gate, shared=True)
                paths.append(str(gate))
            # Older engine-scoped participants hold EX here; do not bypass them.
            gate = control/'engine_execution'/engine/'execution.lock'
            locks.lock_file(stack, gate, shared=engine == 'ue5')
            paths.append(str(gate))
            gate = control/'repair_execution/native.lock'
            locks.lock_file(stack, gate, shared=engine == 'ue5')
            paths.append(str(gate))
            paths += resource_locks(stack, control, resource)
            paths += resource_locks(stack, control, output)
            env = {'A3GAME_REPAIR_PROJECT_ROOT': str(resource), 'A3GAME_NATIVE_INPUT_ONLY': '1'}
            if engine == 'ue5':
                rc, runtime, command = allocate_ports(stack, control)
                env.update(A3GAME_UE_PROJECT=str(resource), A3GAME_UE_HOST='127.0.0.1',
                           A3GAME_UE_RUNTIME_HOST='127.0.0.1', A3GAME_UE_PORT=str(rc),
                           A3GAME_UE_RUNTIME_PORT=str(runtime), A3GAME_UE_COMMAND_PORT=str(command),
                           A3GAME_UE_PYTHON_TRANSPORT='remote_execution')
                value['ports'] = dict(remote_control=rc, runtime=runtime, python_command=command)
            value.update(locks=paths, environment=env)
            check_idle(value)
            old = {k: os.environ.get(k) for k in env}
            os.environ.update(env)  # Runner is a dedicated process, never a scheduler thread.
            token = _ACTIVE.set(value)
            value['status'] = 'ACTIVE'
            dump(receipt, value)
            try:
                yield value
            finally:
                _ACTIVE.reset(token)
                for k, v in old.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
                try:
                    check_idle(value)
                    value['status'] = 'RELEASED'
                except BaseException as exc:
                    value.update(status='CLEANUP_BLOCKED', error=repr(exc))
                    dump(output/'repair_execution/cleanup_block.json', value)
                    raise
                finally:
                    value['released_unix'] = time.time()
                    dump(receipt, value)
    except BaseException as exc:
        if value['status'] == 'ADMISSION_PENDING':
            value.update(status='ADMISSION_BLOCKED', error=repr(exc))
            dump(receipt, value)
        raise
