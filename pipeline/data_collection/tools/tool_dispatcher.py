"""Controlled execution boundary for agent-facing tools."""
from __future__ import annotations

import inspect
import asyncio
from typing import Any, Callable, Mapping

from ..core.collector_sink import as_sink
from ..core.collector import Collector
from .dispatch_context import CaptureError, dispatch_scope
from .tracing import content_for_payload, safe_jsonable


class ToolDispatcher:
    """Register every agent tool and record its real execution."""

    def __init__(self, collector: Collector, *, artifact_store: Any = None):
        self.collector = as_sink(collector)
        self.artifact_store = artifact_store or collector.artifact_store
        self._tools: dict[str, Callable[..., Any]] = {}
        self._descriptions: dict[str, str] = {}

    def register(self, name: str, function: Callable[..., Any], *, description: str | None = None) -> None:
        if not name or name in self._tools:
            raise ValueError(f"tool name must be unique: {name!r}")
        self._tools[name] = function
        self._descriptions[name] = description or (inspect.getdoc(function) or f"Execute {name}").split("\n", 1)[0]
        self.collector.record_tools(self.tool_definitions())

    def tool_definitions(self) -> list[dict]:
        """Return model-facing OpenAI-style tool definitions and persist them."""
        definitions = []
        for name in self.names():
            fn = self._tools[name]
            properties, required = {}, []
            try:
                signature = inspect.signature(fn)
                for param_name, param in signature.parameters.items():
                    if param_name.startswith("_") or param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
                        continue
                    annotation = param.annotation
                    annotation_name = str(annotation).replace("<class \'", "").replace("\'>", "")
                    typ = ("string" if annotation in (str, inspect.Parameter.empty) or "str" in annotation_name
                           else "integer" if annotation is int or "int" in annotation_name
                           else "number" if annotation is float or "float" in annotation_name
                           else "boolean" if annotation is bool or "bool" in annotation_name
                           else "array" if annotation is list or "Sequence" in annotation_name
                           else "object")
                    properties[param_name] = {"type": typ}
                    if param.default is param.empty:
                        required.append(param_name)
            except (TypeError, ValueError):
                pass
            definitions.append({"name": name, "description": self._descriptions[name], "input_schema": {"type": "object", "properties": properties, "required": required}})
        return definitions

    def names(self) -> list[str]:
        return sorted(self._tools)

    def _begin(self, name, arguments, tool_call_id):
        # A provider ID is identity, NOT evidence that its call was recorded.
        args = safe_jsonable(arguments if arguments is not None else {})
        matches = [(e, c) for e in self.collector.trajectory["events"]
                   for c in e.get("tool_calls", []) if c.get("tool_call_id") == tool_call_id] if tool_call_id is not None else []
        if matches and (len(matches) != 1 or matches[0][1].get("name") != name or matches[0][1].get("arguments") != args):
            error = ValueError(f"conflicting tool_call_id: {tool_call_id!r}")
            self.collector.record_event("system", "runtime", producer="dispatcher", status="error",
                operation="dispatch_rejected", audit_code="conflicting_call_id", tool_call_id=tool_call_id,
                attempted_name=name, attempted_arguments=args, error=str(error))
            raise error
        if matches:
            event_id, call_id = matches[0][0]["event_id"], tool_call_id
        else:
            event_id, call_id = self.collector.record_tool_call(name, args, tool_call_id=tool_call_id)
        attempt = self.collector.record_event("tool", "runtime", producer="dispatcher", status="started",
            operation="dispatch_attempt", tool_call_id=call_id, parent_event_id=event_id,
            observation_view="dispatcher_execution")
        return event_id, call_id, attempt

    def _error(self, call_id, attempt, exc):
        self.collector.record_tool_result(call_id, "error", visibility="collector_only",
            producer="dispatcher", parent_event_id=attempt, observation_view="dispatcher_result",
            data={"error": f"{type(exc).__name__}: {exc}", "cancelled": isinstance(exc, asyncio.CancelledError)})

    def _result(self, call_id, attempt, result):
        self.collector.record_tool_result(call_id, "success", producer="dispatcher",
            parent_event_id=attempt, observation_view="dispatcher_result",
            blocks=[content_for_payload("json", safe_jsonable(result), mime_type="application/json",
                visibility="collector_only", artifact_store=self.artifact_store)])

    def call(self, name: str, arguments: Mapping[str, Any] | None = None, *, tool_call_id: str | None = None) -> Any:
        event_id, call_id, attempt = self._begin(name, arguments, tool_call_id)
        with dispatch_scope(self.collector, call_id, event_id, attempt):
            try:
                function = self._get(name)
                if inspect.iscoroutinefunction(function):
                    raise TypeError(f"tool {name!r} is async; use await dispatcher.call_async(...)")
                result = self._call_function(function, self._arguments(arguments), call_id)
                if inspect.isawaitable(result):
                    if inspect.iscoroutine(result):
                        result.close()
                    raise TypeError(f"tool {name!r} returned an awaitable; use call_async")
            except CaptureError:
                raise  # Lost observation, never invent a tool result.
            except (Exception, asyncio.CancelledError) as exc:
                self._error(call_id, attempt, exc)
                raise
            self._result(call_id, attempt, result)
            return result

    async def call_async(self, name: str, arguments: Mapping[str, Any] | None = None, *, tool_call_id: str | None = None) -> Any:
        event_id, call_id, attempt = self._begin(name, arguments, tool_call_id)
        with dispatch_scope(self.collector, call_id, event_id, attempt):
            try:
                function = self._get(name)
                result = self._call_function(function, self._arguments(arguments), call_id)
                if inspect.isawaitable(result):
                    result = await result
            except CaptureError:
                raise
            except (Exception, asyncio.CancelledError) as exc:
                self._error(call_id, attempt, exc)
                raise
            self._result(call_id, attempt, result)
            return result

    @staticmethod
    def _arguments(arguments):
        if arguments is not None and not isinstance(arguments, Mapping):
            raise TypeError("tool arguments must be a mapping")
        return dict(arguments) if arguments is not None else {}

    @staticmethod
    def _call_function(function: Callable[..., Any], arguments: dict[str, Any], call_id: str) -> Any:
        try:
            signature = inspect.signature(function)
        except (TypeError, ValueError):
            signature = None
        if signature:
            if "_tool_call_id" in signature.parameters:
                arguments["_tool_call_id"] = call_id
            signature.bind(**arguments)
        return function(**arguments)

    def _get(self, name: str) -> Callable[..., Any]:
        if name not in self._tools:
            raise KeyError(f"unregistered tool: {name}")
        return self._tools[name]
