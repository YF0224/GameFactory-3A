"""Local native take leases and launch-owned process identities.

These locks complement the parent repair lease; they never replace or unlock it.
No engine-name/global process cleanup is performed here.
"""
from contextlib import contextmanager, ExitStack
import hashlib
import os
from pathlib import Path
import signal
import socket
import subprocess
import tempfile
import time


def process_table():
    rows = subprocess.check_output(
        ['ps', '-axo', 'pid=,ppid=,lstart=,command='], text=True)
    result = {}
    for line in rows.splitlines():
        parts = line.split(None, 7)
        if len(parts) == 8:
            result[int(parts[0])] = (int(parts[1]), ' '.join(parts[2:7]), parts[7])
    return result


class OwnedProcessTree:
    """Track descendants only through parents whose launch identity still matches."""
    def __init__(self, process, project_file):
        self.process = process
        self.identities = {}
        table = process_table()
        root = table.get(process.pid)
        if root is None or process.poll() is not None:
            raise RuntimeError('Native launch exited before process ownership could be verified')
        project = str(Path(project_file).resolve())
        if project not in root[2]:
            raise RuntimeError('Native launch command does not identify the candidate project')
        self.identities[process.pid] = root[1:]
        self.observe()

    def observe(self):
        table = process_table()
        parents = {pid for pid, identity in self.identities.items()
                   if pid in table and table[pid][1:] == identity}
        while True:
            added = {pid for pid, row in table.items() if row[0] in parents and pid not in parents}
            # A remembered PID with a different start/command is foreign, even
            # if its recycled parent PID happens to be part of this tree.
            added = {pid for pid in added if pid not in self.identities
                     or table[pid][1:] == self.identities[pid]}
            if not added:
                break
            for pid in added:
                self.identities[pid] = table[pid][1:]
            parents |= added

    def remaining(self):
        table = process_table()
        return [pid for pid, identity in self.identities.items()
                if pid in table and table[pid][1:] == identity
                and (pid != self.process.pid or self.process.poll() is None)]

    def stop(self):
        self.observe()
        # Verify again immediately before each signal, including escalation.
        for signum, grace in ((signal.SIGTERM, 5), (signal.SIGKILL, 3)):
            for pid in self.remaining():
                table = process_table()
                if pid in table and table[pid][1:] == self.identities[pid]:
                    try:
                        os.kill(pid, signum)
                    except ProcessLookupError:
                        pass
            deadline = time.monotonic() + grace
            while self.remaining() and time.monotonic() < deadline:
                self.process.poll()  # Reap our child so a zombie is not a survivor.
                time.sleep(.05)
            if not self.remaining():
                break
        self.process.poll()
        return self.remaining()


@contextmanager
def native_take_lease(project_file, runtime_port=None):
    """Hold a candidate take and UDP-port lease until input/view cleanup ends.

    The parent coordinator owns the RC and Python command port leases. An
    explicitly supplied runtime port is never replaced by another free port.
    """
    if os.name == 'nt':
        raise RuntimeError('Native take ownership currently requires POSIX process/lease support')
    import fcntl
    base = Path(tempfile.gettempdir()) / 'gamefactory-ue-native-takes'
    base.mkdir(exist_ok=True)
    candidate = hashlib.sha256(str(Path(project_file).resolve()).encode()).hexdigest()
    with ExitStack() as stack:
        candidate_lock = stack.enter_context((base / (candidate + '.lock')).open('a'))
        fcntl.flock(candidate_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # For legacy callers select a port while holding its advisory lease;
        # for repair callers use exactly the coordinator's leased runtime port.
        for _ in range(100):
            if runtime_port is None:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
                    probe.bind(('127.0.0.1', 0))
                    port = probe.getsockname()[1]
            else:
                port = int(runtime_port)
                if not 1 <= port <= 65535:
                    raise ValueError('Invalid native runtime port')
            handle = (base / f'port-{port}.lock').open('a')
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                for kind in (socket.SOCK_DGRAM, socket.SOCK_STREAM):
                    with socket.socket(socket.AF_INET, kind) as probe:
                        probe.bind(('127.0.0.1', port))
            except OSError:
                handle.close()
                if runtime_port is not None:
                    raise BlockingIOError(f'Leased native runtime port {port} is occupied')
                continue
            stack.enter_context(handle)
            yield port
            return
        raise BlockingIOError('No private native runtime port is available')
