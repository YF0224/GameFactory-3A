"""Provider subprocess lifecycle. No engine/tool execution responsibilities."""
from __future__ import annotations
from dataclasses import dataclass, field
import os
import queue
import signal
import subprocess
import threading
import time


@dataclass
class AgentProcess:
    process: subprocess.Popen
    command: list[str]
    owns_process_group: bool = False
    queue: queue.Queue = field(default_factory=lambda: queue.Queue(maxsize=1024))
    readers: list = field(default_factory=list)
    eof: set = field(default_factory=set)


class AgentAdapter:
    provider = 'unknown'
    #: Whether the provider's stream-json echoes the launch prompt as a user
    #: message event. codely does; codex exec does not (verified against the
    #: installed CLIs) — the runner records the delivered task input itself
    #: for those, or the live view loses its first turn.
    echoes_prompt = True

    def capabilities(self):
        return {'runtime_stream': True, 'request_boundary': False, 'tool_definitions': False,
                'environment_facts': False, 'autosave': False}

    def start(self, prompt, *, cwd, env=None):
        raise NotImplementedError

    def _spawn(self, command, cwd, env):
        process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=os.name=='posix')
        return AgentProcess(process, command, owns_process_group=os.name=='posix')

    def start_readers(self, handle):
        if handle.readers: return
        def read(channel, stream):
            try:
                while True:
                    data = os.read(stream.fileno(), 65536)
                    if not data: break
                    handle.queue.put((channel, data))
            except (OSError, ValueError) as exc:
                handle.queue.put(('reader_error', str(exc).encode()))
            finally:
                handle.queue.put((channel, None))
        for channel in ('stdout', 'stderr'):
            stream = getattr(handle.process, channel)
            if stream is None:
                handle.eof.add(channel)
                continue
            thread = threading.Thread(target=read, args=(channel,stream), daemon=True, name=f'{self.provider}-{channel}')
            handle.readers.append(thread)
            thread.start()

    def poll_events(self, handle, *, timeout=0.02, limit=256):
        self.start_readers(handle)
        items=[]
        for i in range(limit):
            try: channel,data=handle.queue.get(timeout=timeout if i==0 else 0)
            except queue.Empty: break
            if data is None: handle.eof.add(channel)
            else: items.append((channel,data))
        return items

    def is_running(self, handle):
        return handle.process.poll() is None

    def terminate(self, handle, *, grace_seconds=0.25):
        def send(sig):
            try:
                if handle.owns_process_group: os.killpg(handle.process.pid, sig)
                elif handle.process.poll() is None: handle.process.send_signal(sig)
            except ProcessLookupError: pass
        send(signal.SIGTERM)
        try: handle.process.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired: pass
        # Even an exited parent can have surviving children holding its pipes.
        send(signal.SIGKILL)
        try: handle.process.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired: pass

    def normalizer(self):
        raise NotImplementedError
