"""
pipeline/data_collection/telemetry.py

Single metering-source writer: ``run_meta.json.telemetry`` (plan.md §0.2).

One run has exactly one writer; wrappers report invocations/events here and
nobody keeps a second ledger. Trajectories only reference these records via
``telemetry_refs`` / invocation ids. Usage/cost/quota keep provider-reported
keys verbatim; missing values stay ``null`` — never zero, never guessed.

This module is for project runs. Standalone training tasks without a project
run inline their telemetry in the trajectory top level (schema §7 / plan §0.2).

Stdlib only.
"""
from __future__ import annotations

from pathlib import Path
import fcntl
from contextlib import contextmanager
from typing import Any

from .event_writer import atomic_write_json, load_json, now_iso


class TelemetryWriter:
    """Merges invocations/events into ``run_meta.json`` under ``telemetry``."""

    def __init__(self, run_meta_path: str | Path):
        self.path = Path(run_meta_path)

    # ── container access ──────────────────────────────────────────────────

    @contextmanager
    def _transaction(self):
        """Serialize read-modify-write updates across processes."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(str(self.path) + ".lock", "a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield
            fcntl.flock(lock, fcntl.LOCK_UN)


    def _load_run_meta(self) -> dict:
        if self.path.exists():
            meta = load_json(self.path)
            if not isinstance(meta, dict):
                raise ValueError(f"{self.path}: run_meta.json must be a JSON object")
            return meta
        return {}

    def _container(self, meta: dict) -> dict:
        telemetry = meta.setdefault("telemetry", {})
        telemetry.setdefault("invocations", [])
        telemetry.setdefault("events", [])
        return telemetry

    def _save(self, meta: dict) -> None:
        atomic_write_json(self.path, meta)

    # ── run-level events (non-conversation, plan §0.2 events[]) ───────────

    def record_event(
        self,
        kind: str,
        *,
        ts: str | None = None,
        ts_source: str = "collector",
        **refs: Any,
    ) -> str:
        """run_start / run_end / interrupt / resume / verification_completed ..."""
        meta = self._load_run_meta()
        container = self._container(meta)
        event: dict[str, Any] = {
            "event_id": f"tevt_{len(container['events']) + 1:06d}",
            "kind": kind,
            "ts": ts or now_iso(),
            "ts_source": ts_source,
        }
        event.update(refs)
        container["events"].append(event)
        self._save(meta)
        return event["event_id"]

    def record_run_start(self, **refs: Any) -> str:
        return self.record_event("run_start", **refs)

    def record_run_end(self, status: str = "completed", **refs: Any) -> str:
        return self.record_event("run_end", status=status, **refs)

    # ── invocations (one physical call, plan §0.2 invocations[]) ──────────

    def record_invocation(
        self,
        *,
        kind: str,
        status: str,
        parent_invocation_id: str | None = None,
        retry_of: str | None = None,
        request_id: str | None = None,
        tool_call_id: str | None = None,
        provider_request_id: str | None = None,
        provider_response_id: str | None = None,
        correlation_id: str | None = None,
        job_id: str | None = None,
        session_id: str | None = None,
        model: str | None = None,
        provider: str | None = None,
        finish_reason: str | None = None,
        started_at: str | None = None,
        first_token_at: str | None = None,
        completed_at: str | None = None,
        ts_source: str = "collector",
        clock_id: str | None = None,
        usage: dict | None = None,
        cost: dict | None = None,
        quota: dict | None = None,
        error: str | None = None,
    ) -> str:
        """Record one physical model/tool/asset-service call.

        ``usage``/``cost``/``quota`` keep the provider's original keys and units
        (credits, GPU-seconds, ...); do not fold cache/reasoning sub-counts
        into totals and do not zero-fill missing numbers.
        """
        meta = self._load_run_meta()
        container = self._container(meta)
        invocation: dict[str, Any] = {
            "invocation_id": f"inv_{len(container['invocations']) + 1:06d}",
            "kind": kind,
            "status": status,
            "ts_source": ts_source,
        }
        for key, value in (
            ("parent_invocation_id", parent_invocation_id),
            ("retry_of", retry_of),
            ("request_id", request_id),
            ("tool_call_id", tool_call_id),
            ("provider_request_id", provider_request_id),
            ("provider_response_id", provider_response_id),
            ("correlation_id", correlation_id),
            ("job_id", job_id),
            ("session_id", session_id),
            ("model", model),
            ("provider", provider),
            ("finish_reason", finish_reason),
            ("started_at", started_at),
            ("first_token_at", first_token_at),
            ("completed_at", completed_at),
            ("clock_id", clock_id),
            ("usage", usage),
            ("cost", cost),
            ("quota", quota),
            ("error", error),
        ):
            if value is not None:
                invocation[key] = value
        container["invocations"].append(invocation)
        self._save(meta)
        return invocation["invocation_id"]


# Wrap the two read-modify-write entrypoints without changing their public API.
def _locked_mutator(method):
    def wrapped(self, *args, **kwargs):
        with self._transaction():
            return method(self, *args, **kwargs)
    wrapped.__name__ = method.__name__
    wrapped.__doc__ = method.__doc__
    return wrapped

TelemetryWriter.record_event = _locked_mutator(TelemetryWriter.record_event)
TelemetryWriter.record_invocation = _locked_mutator(TelemetryWriter.record_invocation)
