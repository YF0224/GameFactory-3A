"""
pipeline/data_collection/workspace_tracker.py

Immutable file versions for the Unity project
(schema §4.2, collection plan §6.1).

Every real change (create/modify/delete/rename) appends one version entry
bound to the triggering event/call; the same path keeps every intermediate
version — an erroneous write and its repair are two versions, never one
overwritten file. Text may also be reconstructed from baseline+patch, but
this tracker always keeps the concrete bytes via the artifact store.

Stdlib only.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Iterable, Sequence

from .collector_sink import as_sink
from .collector import Collector

#: Directory/file patterns never worth recording as project content.
_DEFAULT_SKIP = {
    "__pycache__",
    ".git",
    ".godot",
    # The agent CLI's own state under the workspace (session auto-saves,
    # exports): session records are archived as attachments/snapshots, not
    # as project file versions.
    ".codely-cli",
    "Library",
    "Temp",
    "Logs",
    "obj",
    "Bin",
    "objDebug",
    "UserSettings",
    ".vs",
    ".idea",
    ".DS_Store",
}

_VOLATILE_SUFFIXES = {".log", ".avi", ".mp4", ".webm", ".mov", ".mkv"}


class WorkspaceTracker:
    """Feeds :meth:`Collector.record_workspace_change` with real bytes."""

    def __init__(
        self,
        collector: Collector,
        artifact_store: Any = None,
        project_root: str | Path | None = None,
    ):
        self.collector = as_sink(collector)
        self.artifact_store = artifact_store or collector.artifact_store
        if self.artifact_store is None:
            from .artifact_store import ArtifactStore
            # A run-local fallback is mandatory: hashes alone are not recoverable.
            root = getattr(getattr(collector, "writer", None), "path", None)
            fallback = (Path(root).parent / "workspace_blobs") if root else None
            self.artifact_store = ArtifactStore(fallback) if fallback else ArtifactStore()
        self.project_root = (
            Path(project_root).expanduser().resolve(strict=False)
            if project_root is not None
            else None
        )

    def _logical_path(self, path: str | Path) -> str:
        """Return a stable project-relative path, never a machine path."""
        candidate = Path(path).expanduser()
        if candidate.is_absolute() and self.project_root is not None:
            try:
                return candidate.resolve(strict=False).relative_to(self.project_root).as_posix()
            except ValueError as exc:
                raise ValueError(
                    f"workspace path {candidate} is outside project_root {self.project_root}"
                ) from exc
        if candidate.is_absolute():
            return "$WORKSPACE/" + candidate.name
        return candidate.as_posix()

    def record_change(
        self,
        path: str,
        operation: str = "modify",
        *,
        trigger_event_id: str | None = None,
        tool_call_id: str | None = None,
        content: Any = None,
        content_path: str | Path | None = None,
        renamed_from: str | None = None,
        mime_type: str | None = None,
    ) -> str:
        """Record one real file change; returns the new ``version_id``."""
        return self.collector.record_workspace_change(
            self._logical_path(path),
            operation,
            trigger_event_id=trigger_event_id,
            tool_call_id=tool_call_id,
            content=content,
            content_path=content_path,
            renamed_from=renamed_from,
            mime_type=mime_type,
            store=self.artifact_store,
        )

    def record_baseline(
        self,
        roots: Iterable[str | Path],
        *,
        skip: Sequence[str] = _DEFAULT_SKIP,
    ) -> list[str]:
        """Record the initial state of every file under ``roots`` (P1).

        Only files whose bytes can be read are recorded; unreadable paths are
        skipped rather than guessed at. Content is stored via the artifact
        store when available, otherwise only the hash is kept.
        """
        version_ids: list[str] = []
        root_paths = [Path(root).expanduser().resolve(strict=False) for root in roots]
        if self.project_root is None and root_paths:
            # Multiple roots (Assets + Packages, for example) share the
            # narrowest common parent so every recorded path is stable.
            self.project_root = Path(os.path.commonpath([str(p) for p in root_paths]))
        for root_path in root_paths:
            for file_path in sorted(root_path.rglob("*")):
                if not file_path.is_file():
                    continue
                if skip and any(part in skip for part in file_path.parts):
                    continue
                version_ids.append(
                    self.record_change(
                        str(file_path),
                        "create",
                        content_path=file_path,
                    )
                )
        return version_ids


class WorkspaceObserver:
    """Polling fallback; records observed versions, not every transient write.

    Controlled writes should still use WorkspaceTracker at their actual boundary.
    Logs and recordings are sampled after settling, at most once per interval;
    poll(final=True) archives pending bytes without a size limit at shutdown.
    No compile/build verdict or model visibility is inferred here.
    """
    def __init__(
        self,
        collector,
        root,
        *,
        excluded=(),
        max_files=10000,
        logical_prefix="",
        volatile_settle_seconds: float = 30,
        volatile_interval_seconds: float = 300,
    ):
        self.collector = as_sink(collector)
        self.tracker = WorkspaceTracker(self.collector, project_root=root)
        self.root = Path(root).resolve()
        self.excluded = [Path(p).resolve() for p in excluded]
        self.previous = {}
        self.captured = {}
        self.pending = {}
        self.last_capture = {}
        self.deferred = set()
        self.max_files = max_files
        self.logical_prefix = logical_prefix
        self.volatile_settle_seconds = max(0, float(volatile_settle_seconds))
        self.volatile_interval_seconds = max(0, float(volatile_interval_seconds))

    def poll(self, *, final=False):
        import mimetypes
        current = {}
        files = 0
        now = time.monotonic()
        for directory, dirs, names in os.walk(self.root, followlinks=False):
            base = Path(directory)
            dirs[:] = [d for d in dirs if d not in _DEFAULT_SKIP | {'node_modules'}
                and not (base/d).is_symlink() and not any((base/d).resolve().is_relative_to(p) for p in self.excluded)]
            for name in sorted(names):
                path = base/name
                if path.is_symlink() or name in _DEFAULT_SKIP: continue
                files += 1
                if files > self.max_files:
                    raise RuntimeError('filesystem observation file limit exceeded; scan incomplete')
                logical = self.logical_prefix + path.relative_to(self.root).as_posix()
                try:
                    stat = path.stat()
                    signature = (stat.st_mtime_ns, stat.st_size, stat.st_ino)
                    current[logical] = signature
                    if self.captured.get(logical) == signature: continue
                    volatile = path.suffix.lower() in _VOLATILE_SUFFIXES
                    if volatile:
                        if self.previous.get(logical) != signature or logical not in self.pending:
                            self.pending[logical] = now
                        if not final and (
                            now - self.pending[logical] < self.volatile_settle_seconds
                            or now - self.last_capture.get(logical, float('-inf')) < self.volatile_interval_seconds
                        ):
                            if logical not in self.deferred:
                                self.collector.record_event(
                                    'system', 'runtime', producer='filesystem_observer',
                                    audit_code='volatile_file_observation_deferred',
                                    path=logical, settle_seconds=self.volatile_settle_seconds,
                                    interval_seconds=self.volatile_interval_seconds,
                                    final_capture=True,
                                )
                                self.deferred.add(logical)
                            continue
                    data = path.read_bytes()
                    after = path.stat()
                    if (after.st_mtime_ns, after.st_size, after.st_ino) != signature:
                        self.pending[logical] = now
                        self.collector.record_event('system','runtime',producer='filesystem_observer',
                            audit_code='unstable_file_observation',path=logical)
                        continue
                    version = self.tracker.record_change(logical,
                        'modify' if logical in self.captured else 'create', content=data)
                    self.captured[logical] = signature
                    self.pending.pop(logical, None)
                    if volatile:
                        self.last_capture[logical] = now
                    mime = mimetypes.guess_type(logical)[0] or 'application/octet-stream'
                    if mime.startswith(('image/','video/')) or path.suffix.lower() == '.log':
                        ref = self.collector.artifact_store.put(data, ext=path.suffix, mime_type=mime)
                        from .collector import content_block
                        kind = 'image' if mime.startswith('image/') else 'video' if mime.startswith('video/') else 'file'
                        self.collector.record_event('tool','runtime',producer='artifact_observer',
                            operation='artifact_observed',version_id=version,
                            content=[content_block(kind, uri=ref['uri'],sha256=ref['sha256'],mime_type=mime,visibility='collector_only')])
                except OSError as exc:
                    current[logical] = self.previous.get(logical)
                    self.collector.record_event('system','runtime',producer='filesystem_observer',
                        audit_code='file_observation_failed',path=logical,error=str(exc))
        for logical in self.previous.keys()-current.keys():
            if logical in self.pending:
                self.collector.record_event('system', 'runtime', producer='filesystem_observer',
                    audit_code='volatile_file_removed_before_capture', path=logical)
            if logical in self.captured:
                self.tracker.record_change(logical,'delete')
                self.captured.pop(logical, None)
            self.pending.pop(logical, None)
            self.last_capture.pop(logical, None)
            self.deferred.discard(logical)
        self.previous = current
