"""
pipeline/data_collection/event_writer.py

Single-writer, atomic-replace persistence for one trajectory JSON.

The trajectory file is the canonical immutable fact log (schema v5 §4):
events are appended and never rewritten; missing facts are recorded as
new markers, not edits.  Every ``checkpoint()`` serialises the whole
in-memory document to a temp file and atomically replaces the target,
bumping ``metadata.revision`` (单写者、版本递增、临时文件完整写入后原子替换).

Stdlib only — safe to import from anywhere (same rule as paths.py).
"""
from __future__ import annotations

import json
import fcntl
from contextlib import contextmanager
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TRAJECTORY_SCHEMA_VERSION = "gamefactory3a.unity-trajectory.v5"
TRAJECTORY_INDEX_SCHEMA_VERSION = "gamefactory3a.trajectory-index.v1"


def now_iso() -> str:
    """Collector-observed UTC timestamp (schema §7.1 ``ts`` convention)."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def atomic_write_json(path: str | Path, payload: Any) -> None:
    """Write ``payload`` to ``path`` via temp file + ``os.replace``."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def load_json(path: str | Path) -> Any:
    """Load a UTF-8 JSON document."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class TrajectoryWriter:
    """Owns the on-disk trajectory file for one run.

    Single-writer contract (schema §2.3): exactly one collector process owns a
    trajectory at a time. The sidecar lock is held for the full collector
    lifetime, including resume, rather than only around individual writes.
    ``checkpoint()`` is cheap and is called after every recorded fact, so a
    crash loses at most the in-flight record and recovery keeps every
    already-written event (``open_existing``).
    """

    def __init__(self, path: str | Path, trajectory: dict):
        self.path = Path(path)
        self.trajectory = trajectory
        self._lease = None
        self.suspended = False
        self.revisions = int((trajectory.get("metadata") or {}).get("revision") or 0)
        # Re-read the on-disk revision before the first write after (re)opening;
        # while the exclusive lease is held no other writer can bump it, so
        # later checkpoints skip the full-file reload (it made per-event
        # checkpointing O(n²) and stalled long sessions).
        self._stale_check_pending = True
        self._closed = False
        self._batch_interval = None
        self._batch_last_write = 0.0
        self._batch_dirty = False

    @classmethod
    def create(cls, path: str | Path, trajectory: dict) -> "TrajectoryWriter":
        """Start a fresh trajectory file; refuses to clobber an existing one."""
        path = Path(path)
        if path.exists():
            raise FileExistsError(
                f"{path} already exists; use TrajectoryWriter.open_existing "
                f"(or Collector.resume) to continue an interrupted run"
            )
        return cls(path, trajectory)

    @classmethod
    def open_existing(cls, path: str | Path) -> "TrajectoryWriter":
        """Reopen after an interruption: keep every recorded event, continue."""
        path = Path(path)
        guard = cls(path, {})
        guard.acquire_exclusive()
        try:
            trajectory = load_json(path)
        except Exception:
            guard.close()
            raise
        if trajectory.get("schema_version") != TRAJECTORY_SCHEMA_VERSION:
            guard.close()
            raise ValueError(
                f"{path}: schema_version {trajectory.get('schema_version')!r} "
                f"is not {TRAJECTORY_SCHEMA_VERSION!r}"
            )
        guard.trajectory = trajectory
        guard.revisions = int((trajectory.get("metadata") or {}).get("revision") or 0)
        return guard
    def acquire_exclusive(self):
        """Live run lease. Other Collector instances fail rather than overwrite."""
        if self._lease is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            handle = open(str(self.path) + ".lock", "a+")
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                handle.close()
                raise RuntimeError(f"trajectory already has an active writer: {self.path}")
            self._lease = handle

    def _release_lease(self):
        """Drop the flock without ending the writer's life.

        The non-exclusive (per-write) lease must be released after every
        checkpoint while the writer stays usable for the next one — releasing
        it is not a close.
        """
        if self._lease is not None:
            fcntl.flock(self._lease, fcntl.LOCK_UN)
            self._lease.close()
            self._lease = None

    def close(self):
        self._release_lease()
        self._closed = True

    @contextmanager
    def coalesce_checkpoints(self, interval_seconds=1.0):
        """Bound observer write amplification; retain all facts, flush even on error.

        Only available under the lifetime exclusive lease. A crash can lose the
        current (at most interval_seconds between checkpoints) observation batch;
        this opt-in never changes the default per-event durability contract.
        """
        if self._lease is None or self._batch_interval is not None:
            raise RuntimeError('Coalescing requires one exclusive, non-nested writer')
        self._batch_interval = max(0, float(interval_seconds))
        self._batch_last_write = time.monotonic()
        try:
            yield
        finally:
            self._batch_interval = None
            if self._batch_dirty:
                self.checkpoint()

    def checkpoint(self) -> int:
        if self.suspended:
            return self.revisions
        if self._closed:
            raise RuntimeError(
                f"trajectory writer for {self.path} is closed; reopen via "
                f"TrajectoryWriter.open_existing (or Collector.resume) to continue"
            )
        if self._batch_interval is not None:
            self._batch_dirty = True
            if time.monotonic() - self._batch_last_write < self._batch_interval:
                return self.revisions
        temporary = self._lease is None
        if temporary:
            self.acquire_exclusive()
        try:
            # A resumed independent snapshot must never overwrite newer facts.
            # A non-exclusive checkpoint re-acquires the lock on every write,
            # so the on-disk revision must be re-read every time — the O(n²)
            # reload skip only applies while one writer holds the lease.
            if self._stale_check_pending or temporary:
                if self.path.exists():
                    revision = int(load_json(self.path).get("metadata", {}).get("revision", 0))
                    if revision != self.revisions:
                        raise RuntimeError("stale trajectory writer; resume only after the owner stops")
            self._stale_check_pending = False
            revision = self.revisions + 1
            self.trajectory.setdefault("metadata", {})["revision"] = revision
            atomic_write_json(self.path, self.trajectory)
            self.revisions = revision
            self._batch_last_write = time.monotonic()
            self._batch_dirty = False
            return revision
        finally:
            if temporary:
                self._release_lease()
