"""Minimal agent-facing boundary for mechanic task collection.

An agent runner should use this object instead of direct file/subprocess calls.
It deliberately contains no model code: the model loop remains responsible for
producing tool calls, while every execution is routed through one dispatcher.
"""
from __future__ import annotations

from pathlib import Path
import fnmatch
from typing import Any, Mapping

from ..core.artifact_store import ArtifactStore
from ..core.collector_sink import as_sink
from ..core.collector import Collector
from .tool_dispatcher import ToolDispatcher
from .tracing import run_command, traced_client
from ..core.workspace_tracker import WorkspaceTracker


class MechanicAgentBoundary:
    """Register the standard file, command, and engine-client boundaries."""

    def __init__(self, collector: Collector, workspace: str | Path, *, artifact_store: Any = None):
        self.collector = as_sink(collector)
        self.workspace = Path(workspace).expanduser().resolve(strict=False)
        self.store = artifact_store or collector.artifact_store or ArtifactStore()
        self.workspace_tracker = WorkspaceTracker(self.collector, self.store, project_root=self.workspace)
        self._clients: dict[str, Any] = {}
        self.dispatcher = ToolDispatcher(self.collector, artifact_store=self.store)
        self.dispatcher.register("read_file", self.read_file)
        self.dispatcher.register("list_files", self.list_files)
        self.dispatcher.register("search_text", self.search_text)
        self.dispatcher.register("inspect_client", self.inspect_client)
        self.dispatcher.register("write_file", self.write_file)
        self.dispatcher.register("run_command", self.run_command)

    def read_file(self, path: str) -> dict[str, Any]:
        """Read a project file through the same recorded agent boundary."""
        target = (self.workspace / path).resolve(strict=False)
        if self.workspace not in target.parents and target != self.workspace:
            raise ValueError(f"read path escapes task workspace: {path}")
        if not target.is_file():
            raise FileNotFoundError(str(path))
        content = target.read_text(encoding="utf-8")
        return {"path": target.relative_to(self.workspace).as_posix(), "content": content}

    def inspect_client(self, client: str, attribute: str = "") -> dict[str, Any]:
        """Read-only diagnostic view of client/config/transport/cache objects."""
        if client not in self._clients:
            raise KeyError(f"unregistered client: {client}")
        obj = self._clients[client]
        if attribute:
            for part in attribute.split("."):
                if part.startswith("__"):
                    raise ValueError("dunder attributes are not inspectable")
                obj = getattr(obj, part)
        attrs = {}
        for name in sorted(dir(obj)):
            if name.startswith("__"):
                continue
            try:
                value = getattr(obj, name)
                attrs[name] = {"callable": callable(value), "type": type(value).__name__}
            except Exception as exc:
                attrs[name] = {"error": f"{type(exc).__name__}: {exc}"}
        return {"client": client, "attribute": attribute, "type": type(obj).__name__, "attributes": attrs}

    def list_files(self, path: str = ".", pattern: str = "*") -> dict[str, Any]:
        """List project files without exposing paths outside the task workspace."""
        root = (self.workspace / path).resolve(strict=False)
        if self.workspace not in root.parents and root != self.workspace:
            raise ValueError(f"list path escapes task workspace: {path}")
        if not root.exists():
            raise FileNotFoundError(str(path))
        files = [
            item.relative_to(self.workspace).as_posix()
            for item in sorted(root.rglob("*"))
            if item.is_file() and fnmatch.fnmatch(item.name, pattern)
        ]
        return {"path": root.relative_to(self.workspace).as_posix() if root != self.workspace else ".", "pattern": pattern, "files": files}

    def search_text(self, query: str, path: str = ".", pattern: str = "*") -> dict[str, Any]:
        """Search text in project files; results remain project-relative."""
        root = (self.workspace / path).resolve(strict=False)
        if self.workspace not in root.parents and root != self.workspace:
            raise ValueError(f"search path escapes task workspace: {path}")
        matches = []
        for item in sorted(root.rglob(pattern)) if root.is_dir() else [root]:
            if not item.is_file():
                continue
            try:
                for line_no, line in enumerate(item.read_text(encoding="utf-8").splitlines(), 1):
                    if query in line:
                        matches.append({"path": item.relative_to(self.workspace).as_posix(), "line": line_no, "text": line})
            except (UnicodeDecodeError, OSError):
                continue
        return {"query": query, "matches": matches}

    def write_file(self, path: str, content: str, *, _tool_call_id: str | None = None) -> dict[str, Any]:
        target = (self.workspace / path).resolve(strict=False)
        if self.workspace not in target.parents and target != self.workspace:
            raise ValueError(f"write path escapes task workspace: {path}")
        existed = target.exists()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        logical = target.relative_to(self.workspace).as_posix()
        self.workspace_tracker.record_change(logical, "modify" if existed else "create", content=content, tool_call_id=_tool_call_id)
        return {"path": logical, "bytes": len(content.encode("utf-8")), "operation": "modify" if existed else "create"}

    def run_command(self, args: Any, *, cwd: str | None = None, timeout: float | None = None) -> dict[str, Any]:
        command_cwd = (self.workspace / cwd).resolve(strict=False) if cwd else self.workspace
        if self.workspace not in command_cwd.parents and command_cwd != self.workspace:
            raise ValueError(f"command cwd escapes task workspace: {cwd}")
        result = run_command(self.collector, args, cwd=command_cwd, timeout=timeout, artifact_store=self.store)
        return {"args": args, "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}

    def register_client(self, name: str, client: Any, *, visibility: str = "collector_only", include_internal: bool = False) -> Any:
        """Expose a recursively traced *_client object and register leaf methods.

        ``dir`` must inspect the real client, not the dynamic proxy: the proxy
        intentionally exposes attributes through ``__getattr__``.
        """
        self._clients[name] = client
        proxy = traced_client(client, self.collector, client_name=name, visibility=visibility)

        def visit(prefix: str, obj: Any, obj_proxy: Any, seen: set[int]) -> None:
            if id(obj) in seen:
                return
            seen.add(id(obj))
            for method_name in dir(obj):
                if method_name.startswith("_") and not include_internal:
                    continue
                try:
                    raw = getattr(obj, method_name)
                    wrapped = getattr(obj_proxy, method_name)
                except Exception:
                    continue
                if callable(raw):
                    self.dispatcher.register(f"{prefix}.{method_name}", wrapped)
                elif not isinstance(raw, (str, bytes, int, float, bool, type(None), list, tuple, dict, set)):
                    visit(f"{prefix}.{method_name}", raw, wrapped, seen)

        visit(name, client, proxy, set())
        return proxy
