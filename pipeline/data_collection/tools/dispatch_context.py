"""Task-local causal context; never propagated implicitly across processes."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from typing import Any

from ..core.errors import CaptureError


@dataclass(frozen=True)
class DispatchContext:
    collector: Any
    tool_call_id: str
    call_event_id: str
    operation_parent: str


_current: ContextVar[DispatchContext | None] = ContextVar("gf_dispatch", default=None)


def current_dispatch(collector=None):
    value = _current.get()
    identity = getattr(collector, "context_identity", collector)
    return value if value and (collector is None or value.collector is identity) else None


@contextmanager
def dispatch_scope(collector, call_id, event_id, operation_parent):
    token = _current.set(DispatchContext(getattr(collector, "context_identity", collector), call_id, event_id, operation_parent))
    try:
        yield
    finally:
        _current.reset(token)


@contextmanager
def operation_scope(event_id):
    value = _current.get()
    token = _current.set(replace(value, operation_parent=event_id)) if value else None
    try:
        yield
    finally:
        if token is not None:
            _current.reset(token)


def causal_fields(collector):
    ctx = current_dispatch(collector)
    return {"tool_call_id": ctx.tool_call_id, "call_event_id": ctx.call_event_id,
            "parent_event_id": ctx.operation_parent} if ctx else {}
