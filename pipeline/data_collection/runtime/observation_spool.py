"""Producer-local append-only transport of existing Collector API observations.

No tool execution, no canonical writer. One unique file per producer instance.
Collector's in-memory methods validate/allocate local references; only Runner
replays those methods into the canonical document.
"""
from __future__ import annotations
import copy
import json
import os
import uuid
from pathlib import Path
from ..core.collector import Collector
from ..core.artifact_store import ArtifactStore
from ..core.event_writer import now_iso, atomic_write_json
from ..tools.harness_adapter import redact
from ..tools.dispatch_context import CaptureError

ENV_SPOOL = "AAAGF_OBSERVATION_SPOOL"
ENV_TRAJECTORY = "AAAGF_LIVE_TRAJECTORY"
ENV_BLOBS = "AAAGF_LIVE_BLOBS"
METHODS = {"record_event", "record_message", "record_tool_call", "record_tool_result", "record_tools",
           "record_tool_set", "record_workspace_change", "record_verification", "record_attachment",
           "record_initial_state", "record_asset_generation", "record_task_binding", "record_missing_event",
           "record_request", "open_request", "close_request", "add_telemetry_ref"}


class _MemoryWriter:
    def __init__(self, path): self.path = Path(path)
    def checkpoint(self): pass


class SpoolSink:
    is_observation_sink = True

    def __init__(self, directory, metadata, *, artifact_store=None, snapshot=None, canonical_path=""):
        self.producer_id = uuid.uuid4().hex
        self.sequence = 0
        self.path = Path(directory) / (self.producer_id + ".jsonl")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation: never append to another process's producer file.
        self._stream = self.path.open("xb")
        self.artifact_store = artifact_store or ArtifactStore()
        trajectory = copy.deepcopy(snapshot) if snapshot else Collector._skeleton(metadata, None, None)
        self._local = Collector(trajectory, _MemoryWriter(canonical_path), artifact_store=self.artifact_store)
        self._local._next_id = lambda kind, prefix: f"{prefix}_{self.producer_id}_{uuid.uuid4().hex}"
        self.context_identity = self

    @classmethod
    def from_environment(cls):
        path = Path(os.environ[ENV_TRAJECTORY])
        snapshot = json.loads(path.read_text())  # atomic read only, NEVER resume a Writer
        return cls(os.environ[ENV_SPOOL], snapshot['metadata'], snapshot=snapshot,
                   canonical_path=path, artifact_store=ArtifactStore(os.environ[ENV_BLOBS]))

    @property
    def trajectory(self): return self._local.trajectory
    @property
    def writer(self): return self._local.writer

    def _append(self, kind, payload):
        self.sequence += 1
        envelope = {"producer_id": self.producer_id, "producer_sequence": self.sequence,
                    "timestamp": now_iso(), "kind": kind, "payload": redact(payload)}
        try:
            data = (json.dumps(envelope, ensure_ascii=False) + "\n").encode()
            self._stream.write(data)
            self._stream.flush()
            os.fsync(self._stream.fileno())
        except (OSError, TypeError) as exc:
            raise CaptureError(f"observation spool failed: {exc}") from exc

    def __getattr__(self, name):
        if name not in METHODS:
            raise AttributeError(name)
        def record(*args, **kwargs):
            wire = dict(kwargs)
            wire.pop('store', None)
            if name == 'record_workspace_change':
                content = wire.pop('content', None)
                content_path = wire.pop('content_path', None)
                if content is not None or content_path is not None:
                    data = content if content is not None else Path(content_path).read_bytes()
                    ref = self.artifact_store.put(data)
                    # Transport the immutable blob reference, never the mutable source path.
                    wire['content_path'] = ref['uri']
                    # Keep the local validation copy backed by the bytes, not a
                    # redacted external URI. The canonical replay still uses the
                    # immutable blob reference.
                    wire['_local_content_bytes'] = data
            local_bytes = wire.pop('_local_content_bytes', None)
            wire = redact(wire)
            local_kwargs = dict(wire)
            if name == 'record_workspace_change' and local_bytes is not None:
                local_kwargs['content'] = local_bytes
                local_kwargs.pop('content_path', None)
            result = getattr(self._local, name)(*redact(list(args)), **local_kwargs)
            self._append(name, {"args": list(args), "kwargs": wire, "local_result": result})
            return result
        return record

    def finish(self, result, **kwargs):
        # A subprocess hook ending is not the episode ending.
        return self.record_event('tool', 'runtime', producer='external_hook', operation='producer_finalize',
                                 status='success', producer_result=result)

    def close(self):
        if not self._stream.closed:
            self._append('producer.closed', {})
            self._stream.close()


class SpoolReader:
    """Read complete lines only; persisted byte position is only an optimization.

    Durable replay identity resides in the canonical ingest marker, so a crash
    after canonical checkpoint but before cursor save cannot duplicate facts.
    """
    def __init__(self, directory, assembler, cursor_path):
        self.directory, self.assembler = Path(directory), assembler
        self.cursor_path = Path(cursor_path)
        self.positions = json.loads(self.cursor_path.read_text()) if self.cursor_path.exists() else {}
        self.partial = set()

    def poll(self):
        count = 0
        for path in sorted(self.directory.glob('*.jsonl')):
            offset = self.positions.get(path.name, 0)
            if path.stat().st_size < offset:
                self.assembler.audit('spool_replaced', file=path.name)
                offset = 0
            with path.open('rb') as stream:
                stream.seek(offset)
                while True:
                    start = stream.tell()
                    line = stream.readline()
                    if not line:
                        self.partial.discard(path.name)
                        break
                    if not line.endswith(b'\n'):
                        self.partial.add(path.name)
                        break
                    try:
                        envelope = json.loads(line)
                    except (ValueError, UnicodeError) as exc:
                        self.assembler.audit('damaged_spool_record', file=path.name, byte_offset=start, error=str(exc))
                    else:
                        self.assembler.ingest(envelope)
                    offset = stream.tell()
                    count += 1
            self.positions[path.name] = offset
        atomic_write_json(self.cursor_path, self.positions)
        return count
