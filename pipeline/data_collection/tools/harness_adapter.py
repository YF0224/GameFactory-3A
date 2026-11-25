"""
pipeline/data_collection/harness_adapter.py

Wraps the model/tool call boundary and feeds the collector
(collection plan §4.1–§4.2, schema §5.1.1).

Responsibilities:

* record context messages (system / developer / user);
* record assistant responses including tool calls;
* pair ``tool_call`` ↔ ``tool_result`` and keep transport success separate
  from Unity's business verdict;
* archive redacted raw provider payloads (``capture_status``:
  complete | partial | unavailable | excluded | deferred).

Stdlib only.
"""
from __future__ import annotations

import json
import re
from typing import Any, Sequence

from ..core.collector_sink import as_sink
from ..core.collector import Collector, content_block

# Keys whose values must never be archived verbatim (schema §5.1.1 / §8.2).
_REDACT_KEYS = {
    "authorization",
    "cookie",
    "cookies",
    "set-cookie",
    "api_key",
    "apikey",
    "x-api-key",
    "x-goog-api-key",
    "token",
    "access_token",
    "refresh_token",
    "id_token",
    "session",
    "secret",
    "client_secret",
    "password",
    "passwd",
    "credentials",
    "private_key",
}
_URL_CREDENTIALS_RE = re.compile(r"([a-z]+://)[^/@:\s]+:[^/@\s]+@", re.IGNORECASE)


def redact(value: Any) -> Any:
    """Recursively mask secret-looking keys and URL credentials; keep shape."""
    if isinstance(value, dict):
        return {
            key: ("[REDACTED]" if str(key).lower() in _REDACT_KEYS else redact(item))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return _URL_CREDENTIALS_RE.sub(r"\1[REDACTED]@", value)
    return value


class HarnessAdapter:
    """Thin sugar over :class:`Collector` for the model/tool call boundary."""

    def __init__(
        self,
        collector: Collector,
        *,
        telemetry: Any = None,
        artifact_store: Any = None,
    ):
        self.collector = as_sink(collector)
        self.telemetry = telemetry
        self.artifact_store = artifact_store

    # ── context messages ──────────────────────────────────────────────────

    def record_context_message(
        self,
        source: str,
        *,
        text: str | None = None,
        blocks: Sequence[dict] | None = None,
        visibility: str = "agent_received",
        **extra: Any,
    ) -> str:
        """system / developer / user message that enters the model context."""
        if source not in ("system", "developer", "user"):
            raise ValueError(f"record_context_message: invalid source {source!r}")
        return self.collector.record_message(
            source, text=text, blocks=blocks, visibility=visibility, **extra
        )

    # ── requests ──────────────────────────────────────────────────────────

    def open_request(
        self, input_event_ids: Sequence[str], **fields: Any
    ) -> str:
        """Record a model request at dispatch time (close it after the response)."""
        return self.collector.open_request(list(input_event_ids), **fields)

    def record_response(
        self,
        request_id: str,
        *,
        text: str | None = None,
        blocks: Sequence[dict] | None = None,
        tool_calls: Sequence[dict] | None = None,
        finish_reason: str | None = None,
        visibility: str = "agent_received",
    ) -> str:
        """Record the assistant response for a request and close it.

        ``tool_calls`` items are ``{"tool_call_id", "name", "arguments"}``;
        the call ids come from the provider, or are runner-generated when the
        provider supplies none (schema §6.1).
        """
        if blocks is None and text is not None:
            blocks = [content_block("text", data=text, visibility=visibility)]
        event_id = self.collector.record_event(
            "assistant",
            "tool_call" if tool_calls else "message",
            content=list(blocks or []),
            tool_calls=list(tool_calls) if tool_calls else None,
        )
        self.collector.close_request(request_id, [event_id], finish_reason=finish_reason)
        return event_id

    # ── tools ─────────────────────────────────────────────────────────────

    def record_tool_call(
        self,
        name: str,
        arguments: Any,
        *,
        tool_call_id: str | None = None,
    ) -> tuple[str, str]:
        return self.collector.record_tool_call(name, arguments, tool_call_id=tool_call_id)

    def record_tool_result(
        self,
        tool_call_id: str,
        status: str,
        *,
        text: str | None = None,
        data: Any = None,
        blocks: Sequence[dict] | None = None,
        visibility: str = "agent_received",
        **extra: Any,
    ) -> str:
        """Transport/process result only — Unity's verdict is a verification."""
        return self.collector.record_tool_result(
            tool_call_id,
            status,
            text=text,
            data=data,
            blocks=blocks,
            visibility=visibility,
            **extra,
        )

    # ── raw provider payloads (schema §5.1.1) ─────────────────────────────

    def archive_raw(
        self,
        request_id: str,
        *,
        raw_request: Any = None,
        raw_response: Any = None,
        stream_chunks: Sequence[Any] | None = None,
        capture_status: str = "complete",
        missing_reason: str | None = None,
    ) -> dict:
        """Archive redacted raw request/response payloads as URI+hash refs.

        Payloads are redacted before hashing; the hash covers the redacted
        bytes actually archived (schema §5.1.1). Without an artifact store the
        refs stay null and ``capture_status`` must say why (never silently
        drop the fact that raw payloads were expected).
        """
        refs: dict[str, dict | None] = {
            "raw_request_ref": None,
            "raw_response_ref": None,
            "raw_stream_ref": None,
        }
        if self.artifact_store is not None:
            if raw_request is not None:
                refs["raw_request_ref"] = self._dump_raw(raw_request, "request")
            if raw_response is not None:
                refs["raw_response_ref"] = self._dump_raw(raw_response, "response")
            if stream_chunks:
                refs["raw_stream_ref"] = self._dump_raw(list(stream_chunks), "stream")
        elif raw_request is not None or raw_response is not None or stream_chunks:
            if capture_status == "complete":
                capture_status = "partial"
            missing_reason = missing_reason or "no_artifact_store"
        return self.collector.attach_raw(
            request_id,
            raw_request_ref=refs["raw_request_ref"],
            raw_response_ref=refs["raw_response_ref"],
            raw_stream_ref=refs["raw_stream_ref"],
            capture_status=capture_status,
            missing_reason=missing_reason,
        )

    def _dump_raw(self, payload: Any, label: str) -> dict:
        text = json.dumps(redact(payload), indent=2, ensure_ascii=False)
        stored = self.artifact_store.put(
            text.encode("utf-8"),
            ext=".json",
            mime_type="application/json",
        )
        return {
            "uri": stored["uri"],
            "sha256": stored["sha256"],
            "mime_type": stored["mime_type"],
        }
