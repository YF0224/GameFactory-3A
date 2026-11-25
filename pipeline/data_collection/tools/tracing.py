"""Small, opt-in tracing adapters for agent tools, commands, and engine clients.

This module deliberately does not own any game logic.  It wraps existing
entrypoints and emits facts to the existing :class:`Collector`.
"""
from __future__ import annotations

import functools
import asyncio
import inspect
import os
import subprocess
import time
from typing import Any, Callable, Mapping, Sequence

from ..core.collector_sink import as_sink
from ..core.collector import Collector, content_block
from .dispatch_context import CaptureError, current_dispatch, causal_fields, operation_scope


def safe_jsonable(value: Any) -> Any:
    """Make common command/client values JSON serialisable without leaking secrets."""
    if isinstance(value, Mapping):
        return {str(k): safe_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


# Backward-compatible private alias for older adapters. New integrations should
# import ``safe_jsonable``.
_safe = safe_jsonable


def _redact_env(env: Mapping[str, str] | None) -> dict[str, str] | None:
    if env is None:
        return None
    secret_words = ("key", "token", "secret", "password", "credential", "auth")
    return {
        str(k): ("[REDACTED]" if any(w in str(k).lower() for w in secret_words) else str(v))
        for k, v in env.items()
    }


def content_for_payload(
    type_: str,
    value: Any,
    *,
    mime_type: str | None = None,
    visibility: str = "collector_only",
    artifact_store: Any = None,
    ext: str = ".json",
) -> dict[str, Any]:
    """Encode short values inline and archive long values as a schema content block."""
    import json

    encoded = json.dumps(value, ensure_ascii=False, default=repr).encode("utf-8")
    limit = 8 * 1024
    if len(encoded) <= limit:
        return content_block(type_, data=value, mime_type=mime_type, visibility=visibility)
    if artifact_store is not None:
        ref = artifact_store.put(encoded, ext=ext, mime_type=mime_type)
        return content_block(
            type_, uri=ref["uri"], mime_type=mime_type, sha256=ref["sha256"],
            visibility=visibility,
        )
    # No store must not silently destroy feedback. Live mode always supplies one.
    return content_block(type_, data=value, mime_type=mime_type, visibility=visibility)


# Backward-compatible private alias; integrations should use content_for_payload.
_content_for_payload = content_for_payload


def record_engine_operation(
    collector: Collector,
    client: str,
    method: str,
    *,
    arguments: Mapping[str, Any] | None = None,
    result: Any = None,
    status: str = "success",
    parent_event_id: str | None = None,
    error: str | None = None,
    visibility: str = "collector_only",
    artifact_store: Any = None,
) -> str:
    """Record one completed client operation as an environment event."""
    collector = as_sink(collector)
    payload = {
        "client": client,
        "method": method,
        "arguments": safe_jsonable(arguments or {}),
        "result": safe_jsonable(result),
    }
    if error:
        payload["error"] = error
    return collector.record_event(
        "tool",
        "runtime",
        content=[_content_for_payload(
            "json", payload, mime_type="application/json",
            visibility=visibility, artifact_store=artifact_store,
        )],
        status=status,
        producer="engine_client",
        operation="engine_operation",
        **{**causal_fields(collector), "parent_event_id": parent_event_id},
    )


def traced_client(client: Any, collector: Collector, *, client_name: str | None = None, visibility: str = "collector_only") -> Any:
    """Return a recursive proxy recording public client methods.

    Nested client namespaces (for example ``client.playtest.record``) are
    proxied too. The original client is not modified. ``visibility`` controls
    whether returned operation facts are exposed to the agent.
    """
    collector = as_sink(collector)
    name = client_name or type(client).__name__
    cache: dict[str, Any] = {}

    class _Proxy:
        def __getattr__(self, attr: str) -> Any:
            value = getattr(client, attr)
            if attr.startswith("_") or not callable(value):
                if not attr.startswith("_") and not isinstance(value, (str, bytes, int, float, bool, type(None))):
                    if attr not in cache:
                        cache[attr] = traced_client(value, collector, client_name=f"{name}.{attr}", visibility=visibility)
                    return cache[attr]
                return value

            if inspect.iscoroutinefunction(value):
                @functools.wraps(value)
                async def wrapped_async(*args: Any, **kwargs: Any) -> Any:
                    event_id = collector.record_event(
                        "tool", "runtime", content=[content_for_payload("json", {
                            "client": name, "method": attr,
                            "arguments": safe_jsonable({"args": args, "kwargs": kwargs}),
                        }, mime_type="application/json", visibility=visibility, artifact_store=collector.artifact_store)],
                        status="started", producer="engine_client",
                        operation="engine_operation_start", **causal_fields(collector),
                    )
                    try:
                        with operation_scope(event_id):
                            result = await value(*args, **kwargs)
                    except CaptureError:
                        raise
                    except (Exception, asyncio.CancelledError) as exc:
                        record_engine_operation(collector, name, attr,
                            arguments={"args": args, "kwargs": kwargs}, status="error",
                            parent_event_id=event_id, error=f"{type(exc).__name__}: {exc}", visibility=visibility, artifact_store=collector.artifact_store)
                        raise
                    record_engine_operation(collector, name, attr,
                        arguments={"args": args, "kwargs": kwargs}, result=result,
                        parent_event_id=event_id, visibility=visibility, artifact_store=collector.artifact_store)
                    return result
                return wrapped_async

            @functools.wraps(value)
            def wrapped(*args: Any, **kwargs: Any) -> Any:
                event_id = collector.record_event(
                    "tool", "runtime",
                    content=[content_for_payload("json", {
                        "client": name, "method": attr,
                        "arguments": safe_jsonable({"args": args, "kwargs": kwargs}),
                    }, mime_type="application/json", visibility=visibility, artifact_store=collector.artifact_store)],
                    status="started", producer="engine_client",
                    operation="engine_operation_start", **causal_fields(collector),
                )
                try:
                    with operation_scope(event_id):
                        result = value(*args, **kwargs)
                except CaptureError:
                    raise
                except (Exception, asyncio.CancelledError) as exc:
                    record_engine_operation(collector, name, attr,
                        arguments={"args": args, "kwargs": kwargs}, status="error",
                        parent_event_id=event_id, error=f"{type(exc).__name__}: {exc}", visibility=visibility, artifact_store=collector.artifact_store)
                    raise
                record_engine_operation(collector, name, attr,
                    arguments={"args": args, "kwargs": kwargs}, result=result,
                    parent_event_id=event_id, visibility=visibility, artifact_store=collector.artifact_store)
                return result
            return wrapped

    return _Proxy()


def run_command(
    collector: Collector,
    args: Sequence[str] | str,
    *,
    cwd: str | os.PathLike[str] | None = None,
    timeout: float | None = None,
    env: Mapping[str, str] | None = None,
    shell: bool = False,
    check: bool = False,
    artifact_store: Any = None,
) -> subprocess.CompletedProcess[str]:
    """Execute a system command and record call, process output, and result.

    This is the supported cross-platform command boundary.  Callers should
    use it instead of direct ``subprocess.run`` when the action is agent-driven.
    """
    collector = as_sink(collector)
    ctx = current_dispatch(collector)
    arguments = {"args": safe_jsonable(args), "cwd": str(cwd) if cwd else None,
                 "shell": shell, "env": _redact_env(env)}
    if ctx:
        call_event_id, call_id = ctx.call_event_id, ctx.tool_call_id
    else:
        call_event_id, call_id = collector.record_tool_call("run_command", arguments)
    started = time.monotonic()
    start_id = collector.record_event("tool", "runtime", producer="system_command", status="started",
        operation="process_start", tool_call_id=call_id,
        parent_event_id=ctx.operation_parent if ctx else call_event_id,
        content=[content_for_payload("json", arguments, artifact_store=artifact_store)])
    try:
        completed = subprocess.run(args, cwd=cwd, env=dict(env) if env is not None else None,
            shell=shell, timeout=timeout, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    except (Exception, asyncio.CancelledError) as exc:
        collector.record_event("tool", "runtime", producer="system_command", status="error",
            operation="process_error", tool_call_id=call_id, parent_event_id=start_id,
            error=f"{type(exc).__name__}: {exc}")
        if not ctx:
            collector.record_tool_result(call_id, "error", visibility="collector_only",
                data={"error": f"{type(exc).__name__}: {exc}"})
        raise
    status = "success" if completed.returncode == 0 else "error"
    blocks = [content_for_payload("json", {"command": safe_jsonable(args), "exit_code": completed.returncode,
        "duration_ms": round((time.monotonic() - started) * 1000, 2)}, artifact_store=artifact_store),
        content_for_payload("text", completed.stdout, artifact_store=artifact_store, ext=".stdout.log"),
        content_for_payload("text", completed.stderr, artifact_store=artifact_store, ext=".stderr.log")]
    collector.record_event("tool", "runtime", content=blocks, status=status, producer="system_command",
        parent_event_id=start_id, tool_call_id=call_id, operation="process_result")
    if not ctx:
        collector.record_tool_result(call_id, status, blocks=blocks)
    if check and completed.returncode:
        raise subprocess.CalledProcessError(completed.returncode, args, completed.stdout, completed.stderr)
    return completed


def _bound_arguments(function: Callable, args: tuple[Any, ...], kwargs: Mapping[str, Any]) -> dict[str, Any]:
    """Prefer schema-like named arguments, falling back safely for variadics."""
    try:
        bound = inspect.signature(function).bind(*args, **dict(kwargs))
        bound.apply_defaults()
        return {str(k): safe_jsonable(v) for k, v in bound.arguments.items()}
    except (TypeError, ValueError):
        return {"args": safe_jsonable(args), "kwargs": safe_jsonable(kwargs)}


def traced_tool(collector: Collector, name: str | None = None) -> Callable:
    """Standalone tool boundary; nested dispatches emit internal operations only."""
    collector = as_sink(collector)
    def decorate(function: Callable) -> Callable:
        tool_name = name or function.__name__
        def begin(args, kwargs):
            ctx = current_dispatch(collector)
            arguments = _bound_arguments(function, args, kwargs)
            if ctx:
                event_id = collector.record_event("tool", "runtime", producer="traced_tool", status="started",
                    operation="internal_tool_start", **causal_fields(collector),
                    content=[content_for_payload("json", {"name": tool_name, "arguments": arguments})])
                return ctx, event_id, ctx.tool_call_id
            event_id, call_id = collector.record_tool_call(tool_name, arguments)
            return None, event_id, call_id
        def end(state, result=None, error=None):
            ctx, event_id, call_id = state
            payload = {"error": f"{type(error).__name__}: {error}"} if error else safe_jsonable(result)
            blocks = [content_for_payload("json", payload, artifact_store=collector.artifact_store)]
            if ctx:
                collector.record_event("tool", "runtime", producer="traced_tool", operation="internal_tool_result",
                    status="error" if error else "success", tool_call_id=call_id, parent_event_id=event_id, content=blocks)
            else:
                collector.record_tool_result(call_id, "error" if error else "success", blocks=blocks)
        if inspect.iscoroutinefunction(function):
            @functools.wraps(function)
            async def wrapped_async(*args, **kwargs):
                state = begin(args, kwargs)
                try:
                    with operation_scope(state[1]):
                        result = await function(*args, **kwargs)
                except CaptureError:
                    raise
                except (Exception, asyncio.CancelledError) as exc:
                    end(state, error=exc)
                    raise
                end(state, result=result)
                return result
            return wrapped_async
        @functools.wraps(function)
        def wrapped(*args, **kwargs):
            state = begin(args, kwargs)
            try:
                with operation_scope(state[1]):
                    result = function(*args, **kwargs)
            except CaptureError:
                raise
            except (Exception, asyncio.CancelledError) as exc:
                end(state, error=exc)
                raise
            end(state, result=result)
            return result
        return wrapped
    return decorate
