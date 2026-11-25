"""Real-time observation of Codex CLI session rollouts, plus their companions.

Codex appends one JSONL record per event to
``~/.codex/sessions/YYYY/MM/DD/rollout-<ts>-<thread-id>.jsonl``: records are
ordinal-ordered and append-only (a ``put`` never revises an earlier message,
unlike the Codely journal), so observation consumes new complete lines and
records each fact exactly once:

* ``session_meta`` / ``turn_context`` and lifecycle ``event_msg`` records
  (task started/completed, turn aborted) → runtime observations;
* ``response_item`` ``message`` → user/assistant message events (the rollout
  is what the runtime actually sent the model → ``agent_received``);
* ``response_item`` ``function_call`` → an assistant tool_call event;
* ``response_item`` ``function_call_output`` → the paired tool_result, by
  ``call_id``;
* ``response_item`` ``reasoning`` → Codex stores thinking as
  ``encrypted_content`` with an empty summary: no text is reconstructable, so
  the item is kept as a collector_only observation with the blob replaced by
  a redaction marker — never a fabricated ``raw_reasoning``;
* ``token_usage_record`` (verified against real 0.155/0.156 sessions) → kept
  out of the fact event stream but stashed with its provider ``response_id``
  and verbatim usage: with ``assemble_requests=True`` it is the response-end
  boundary that closes ONE reconstructed request per model call (items since
  the previous usage record). A response whose turn was aborted (no usage
  record) stays unclaimed — never invented;
* provider bookkeeping (token counters, ``item_completed`` echo, world
  state) is skipped, counted, and never re-recorded.

Session attribution mirrors the Codely journal anchor: the child's first
user message wraps the launch prompt (inside an ``environment_context``
block), so the prompt text is matched against the full user message text.
Headless attribution is thread-precise: the exec stream's
``thread.started`` id equals the rollout's session id (verified on real
exec rollouts: the filename uuid == ``session_meta.session_id``).
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

from pipeline.data_collection.paths import make_trajectory_id, trajectory_path

from ..core.artifact_store import ArtifactStore
from ..core.collector import Collector, content_block, identity_metadata
from .codely_autosave import (INPUT_RECONSTRUCTION, derive_tools_used,
                              portable_uri)

DEFAULT_SESSIONS_ROOT = Path("~/.codex/sessions").expanduser()
EXIT_CODE_RE = re.compile(r"Process exited with code (\d+)")
_LIFECYCLE_EVENT_MSG = {"task_started", "task_complete", "turn_aborted"}
_BOOKKEEPING = {"token_usage_record", "world_state", "compacted"}

#: How long the headless recovery waits for the exec child's final rollout
#: flush (rollouts land at session end; verified on real sessions).
ROLLOUT_FLUSH_WAIT_SECONDS = 3.0


def rollout_files(root: str | Path = DEFAULT_SESSIONS_ROOT) -> set:
    """All session rollout files under the Codex sessions root."""
    root = Path(root).expanduser()
    return {p for p in root.glob("*/*/*/*.jsonl") if p.is_file()}


def _message_texts(payload: dict[str, Any]) -> list[str]:
    return [c.get("text", "") for c in (payload.get("content") or [])
            if isinstance(c, dict) and isinstance(c.get("text"), str)]


def rollout_matches_prompt(rollout_path: str | Path, prompt: str) -> bool:
    """Session attribution anchor: the child's user messages contain the
    launch prompt (wrapped in an ``environment_context`` block by the CLI,
    so match against the full message text, not its head)."""
    prompt = (prompt or "").strip()
    if not prompt:
        return False
    try:
        with open(rollout_path, encoding="utf-8", errors="replace") as source:
            for line in source:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                payload = record.get("payload") or {}
                if (record.get("type") == "response_item"
                        and payload.get("type") == "message"
                        and payload.get("role") == "user"):
                    if prompt in "\n".join(_message_texts(payload)):
                        return True
    except OSError:
        return False
    return False


class RolloutObserver:
    """Fact-delta observation of one Codex session rollout (append-only).

    ``assemble_requests=False`` (the live view) records facts only — the
    interactive main trajectory never invents request boundaries.
    ``assemble_requests=True`` (the companion rebuild) additionally closes
    ONE reconstructed request per model call at its ``token_usage_record``
    boundary: response items (reasoning / assistant message / function_call)
    since the previous usage record, marked with the provider ``response_id``,
    a provably complete response end, and the session-history-rebuilt inputs.
    A response without a usage record (aborted turn) stays unclaimed.
    """

    def __init__(self, collector: Collector, session_id: str, *,
                 assemble_requests: bool = False):
        self.collector = collector
        self.session_id = session_id
        self.assemble_requests = assemble_requests
        self.report: dict[str, Any] = {"appended_events": 0, "new_calls": 0,
                                       "new_results": 0, "lines": 0,
                                       "skipped_bookkeeping": 0, "audits": [],
                                       "new_requests": 0, "usage_records": [],
                                       "model": None}
        self._offset = 0
        self._unknown_types: set[str] = set()
        self._rollout_uri: str | None = None
        self._model: str | None = None
        self._has_system = False
        # request assembly bookkeeping: the context is the session history the
        # NEXT response saw; an open response's input is snapshotted when its
        # FIRST item appears (everything the model saw strictly before it —
        # this guarantees input events never follow response events), and it
        # closes at its token_usage_record boundary. Aborted responses drop
        # their buffer: no usage record, no proven end, no invented request.
        self._context: list[str] = []
        self._open_response: list[str] = []
        self._open_input: list[str] | None = None

    def observe(self, rollout_path: str | Path, *,
                source_uri: str | None = None) -> dict[str, Any]:
        """Consume the rollout's newly completed lines; return the live report.

        ``source_uri`` optionally names the ARCHIVED copy (content-addressed
        store) so per-event provenance points at the recoverable artifact
        instead of the machine-local session file."""
        self._rollout_uri = source_uri or portable_uri(str(rollout_path))
        try:
            data = Path(rollout_path).read_bytes()
        except OSError as exc:
            self._audit("rollout_unreadable", error=str(exc))
            return self.report
        limit = data.rfind(b"\n") + 1
        if limit > self._offset:
            for raw in data[self._offset:limit].splitlines():
                self.report["lines"] += 1
                try:
                    record = json.loads(raw)
                except ValueError:
                    self._audit("rollout_invalid_line")
                    continue
                self._consume(record)
            self._offset = limit
        return self.report

    def _source_refs(self, record: dict[str, Any]) -> dict[str, Any]:
        """Per-event raw provenance: the rollout file and the record ordinal —
        a later conversion fix can regenerate from here (schema §8.2 for the
        machine-local prefix)."""
        ordinal = record.get("ordinal")
        return {"uri": self._rollout_uri, "format": "codex-rollout",
                "positions": [ordinal] if ordinal is not None else []}

    def _consume(self, record: dict[str, Any]) -> None:
        rtype = record.get("type")
        if rtype == "token_usage_record":
            # Provider bookkeeping for the fact stream, but the boundary fact
            # itself: stash the usage record and, in assembly mode, close the
            # open response as ONE reconstructed request.
            self.report["skipped_bookkeeping"] += 1
            self._consume_usage_record(record)
            return
        if rtype in _BOOKKEEPING:
            self.report["skipped_bookkeeping"] += 1
            return
        if rtype == "response_item":
            self._consume_item(record, record.get("payload") or {})
            return
        if rtype in ("session_meta", "turn_context"):
            if rtype == "turn_context" and (record.get("payload") or {}).get("model"):
                self._lift_model((record.get("payload") or {}).get("model"))
            self._runtime(rtype, record, record.get("payload") or {})
            return
        if rtype == "event_msg":
            inner = (record.get("payload") or {}).get("type")
            if inner in _LIFECYCLE_EVENT_MSG:
                if inner == "turn_aborted":
                    self._abandon_open_response()
                self._runtime(f"event_msg.{inner}", record, record.get("payload") or {})
            else:
                self.report["skipped_bookkeeping"] += 1
            return
        if rtype not in self._unknown_types:
            self._unknown_types.add(rtype)
            self._audit("rollout_unknown_record_type", record_type=str(rtype))

    def _lift_model(self, model: Any) -> None:
        """turn_context carries the model actually serving the turn (verified
        on real sessions); record it once at the metadata level."""
        self._model = str(model) if model else self._model
        self.report["model"] = self._model
        metadata = self.collector.trajectory["metadata"]
        if model and not metadata.get("model"):
            metadata["model"] = model
            self.collector.writer.checkpoint()

    def _consume_usage_record(self, record: dict[str, Any]) -> None:
        payload = record.get("payload") or {}
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else None
        self.report["usage_records"].append({
            "response_id": payload.get("response_id"),
            "turn_id": payload.get("turn_id"),
            "usage": usage,
            "model": self._model,
            "ts": record.get("timestamp"),
        })
        if not self.assemble_requests or not self._open_response:
            return
        response_ids = list(self._open_response)
        input_ids = list(self._open_input or [])
        self._open_response = []
        self._open_input = None
        response_id = payload.get("response_id")
        markers: dict[str, Any] = {
            "input_reconstruction": INPUT_RECONSTRUCTION,
            "boundary": "reconstructed",
            # the usage record terminates exactly one provider response and
            # carries its provider-issued id (verified on real sessions)
            "boundary_basis": {"type": "usage_record_end", "response_id": response_id},
            "context": "partial",
            "context_basis": {"type": "session_history_reconstruction",
                              "system_prompt": self._has_system,
                              "history_verification": "complete_file_read"},
            "response_status": "complete",
            "response_basis": {"type": "usage_record_end", "response_id": response_id},
        }
        fields: dict[str, Any] = {"model": self._model,
                                  "provider": "codex",
                                  "session_id": self.session_id}
        if usage is not None:
            fields["usage"] = usage
        self.collector.record_request(input_ids, response_ids, **fields, **markers)
        self.report["new_requests"] += 1
        # the closed response enters the history the next response sees
        self._context.extend(response_ids)

    def _abandon_open_response(self) -> None:
        """A turn aborted mid-stream leaves no usage record: its items stay
        conversation facts but no request claims them — response end is
        never proven, so nothing is invented (the dropped buffer also never
        enters the context of later requests)."""
        self._open_response = []
        self._open_input = None

    def _common(self, record: dict[str, Any], provider_event: str) -> dict[str, Any]:
        common = {"producer": "codex", "provider_event": provider_event,
                  "session_id": self.session_id}
        if record.get("timestamp"):
            common.update(ts=record["timestamp"], ts_source="provider")
        return common

    def _runtime(self, provider_event: str, record: dict[str, Any],
                 payload: dict[str, Any]) -> None:
        self.collector.record_event("system", "runtime",
            content=[content_block("json", data=payload, visibility="collector_only")],
            source_refs=self._source_refs(record),
            **self._common(record, provider_event))
        self.report["appended_events"] += 1

    def _note(self, event_id: str) -> None:
        """An input-side fact (developer/user message, tool output): part of
        the session history the next response saw."""
        if self.assemble_requests:
            self._context.append(event_id)

    def _consume_item(self, record: dict[str, Any], payload: dict[str, Any]) -> None:
        itype = payload.get("type")
        if itype == "message":
            role = payload.get("role")
            if role == "developer":
                # Codex ships skills/instructions as developer-role items; they
                # are model input, so they land as system messages, not user.
                source, kind = "system", "message"
                self._has_system = True
            elif role == "assistant":
                source, kind = "assistant", "message"
            else:
                source, kind = "user", "message"
            texts = _message_texts(payload)
            if not texts:
                return  # a message without visible text is not a fact
            event_id = self.collector.record_event(source, kind,
                content=[content_block("text", data=text, visibility="agent_received")
                         for text in texts],
                source_refs=self._source_refs(record),
                **self._common(record, "response_item.message"))
            self.report["appended_events"] += 1
            if role == "assistant":
                # a message the model produced: part of the open response
                self._claim_response_item(event_id)
            else:
                self._note(event_id)
            return
        if itype == "function_call":
            call_id = payload.get("call_id") or payload.get("id")
            if not call_id or not payload.get("name"):
                self._audit("rollout_call_without_identity", call_id=call_id)
                return
            arguments = payload.get("arguments")
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except ValueError:
                    pass  # keep the raw string; never guess a structure
            event_id = self.collector.record_event("assistant", "tool_call", content=[],
                tool_calls=[{"tool_call_id": str(call_id),
                             "name": payload.get("name"),
                             "arguments": arguments}],
                source_refs=self._source_refs(record),
                **self._common(record, "response_item.function_call"))
            self.report["appended_events"] += 1
            self.report["new_calls"] += 1
            self._claim_response_item(event_id)
            return
        if itype == "function_call_output":
            call_id = payload.get("call_id")
            if not call_id:
                self._audit("rollout_result_without_call_id")
                return
            output = payload.get("output")
            if not isinstance(output, str):
                output = json.dumps(output, ensure_ascii=False, default=str)
            status = "unknown"
            match = EXIT_CODE_RE.search(output)
            if match:
                status = "success" if match.group(1) == "0" else "error"
            event_id = self.collector.record_event("tool", "tool_result",
                content=[content_block("text", data=output, visibility="agent_received")],
                tool_call_id=str(call_id), status=status,
                source_refs=self._source_refs(record),
                **self._common(record, "response_item.function_call_output"))
            self.report["appended_events"] += 1
            self.report["new_results"] += 1
            # the tool output is INPUT for the next response, never part of
            # the response that issued the call
            self._note(event_id)
            return
        if itype == "reasoning":
            encrypted = payload.get("encrypted_content")
            data = {"type": "reasoning", "id": payload.get("id"),
                    "summary": payload.get("summary") or [],
                    "encrypted_content": {"redacted": True,
                                          "length": len(encrypted) if isinstance(encrypted, str) else None},
                    "reasoning_text": "not_available_encrypted_by_provider"}
            event_id = self.collector.record_event("system", "runtime",
                content=[content_block("json", data=data, visibility="collector_only")],
                source_refs=self._source_refs(record),
                **self._common(record, "response_item.reasoning"))
            self.report["appended_events"] += 1
            # Reasoning is a system-sourced, collector_only observation: it is
            # neither model input nor an assistant-sourced response member, so
            # no request view claims it (its policy already forbids training
            # input; the rollout archive keeps the bytes).
            return
        # web_search_call and future item kinds: keep the raw observation.
        self._runtime(f"response_item.{itype}", record, payload)

    def _claim_response_item(self, event_id: str) -> None:
        """An assistant-sourced item the model produced: open-response member
        in assembly mode, plain fact otherwise. The input snapshot is taken at
        the FIRST item — everything the model saw strictly before its
        response, so request inputs can never follow response events."""
        if not self.assemble_requests:
            return
        if not self._open_response:
            self._open_input = list(self._context)
        self._open_response.append(event_id)

    def _audit(self, code: str, **facts: Any) -> None:
        self.collector.record_event("system", "runtime",
            producer="rollout_observer", audit_code=code,
            content=[content_block("json", data=facts, visibility="collector_only")])
        self.report["audits"].append(code)
        self.report["appended_events"] += 1


def thread_id_from_raw_stream(raw_dir: str | Path, provider: str = "codex") -> str | None:
    """Read the exec child's thread id from the archived stream's first
    ``thread.started`` event."""
    stream = Path(raw_dir) / f"{provider}.jsonl"
    if not stream.exists():
        return None
    with open(stream, encoding="utf-8", errors="replace") as f:
        for _ in range(50):
            line = f.readline()
            if not line:
                break
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if (isinstance(event, dict) and event.get("type") == "thread.started"
                    and event.get("thread_id")):
                return str(event["thread_id"])
    return None


def find_rollout_for_thread(thread_id: str | None,
                             *, sessions_root: str | Path | None = None) -> Path | None:
    """The one rollout file whose name carries this thread id.

    Precise attribution (the filename uuid equals ``session_meta.session_id``
    on real rollouts); missing or ambiguous matches return None — never a
    timestamp guess."""
    if not thread_id:
        return None
    root = Path(sessions_root).expanduser() if sessions_root else DEFAULT_SESSIONS_ROOT
    matches = sorted(p for p in rollout_files(root)
                     if p.name.endswith(f"-{thread_id}.jsonl"))
    return matches[0] if len(matches) == 1 else None


def recover_codex_companion(*, rollout_path: str | Path, game_id: str, run_id: str,
                            live_trajectory_id: str | None = None,
                            live_trajectory_path: str | Path | None = None,
                            register: bool = True, out_path: str | Path | None = None,
                            extra_metadata: dict | None = None,
                            artifact_store: Any = None) -> dict[str, Any]:
    """Build the export-view companion trajectory from a Codex rollout.

    Requests are reconstructed at the ``token_usage_record`` boundaries
    (verified on real 0.155/0.156 sessions): each record terminates exactly
    one provider response, carries its provider-issued ``response_id`` and the
    usage block, and closes the open response as ONE reconstructed request
    with a provably complete response end. Inputs are the explicitly marked
    session-history reconstruction. A response whose turn was aborted leaves
    no usage record and stays unclaimed — never invented. The tool layer is
    derived from the calls actually observed (the rollout persists no
    registry). With ``live_trajectory_*`` the workspace/verification facts
    are inherited from the live view of the SAME session and the views are
    cross-linked; without them this is a standalone post-hoc conversion.
    The rollout is archived so the companion never depends on a
    machine-local session file. Returns an outcome dict and never raises so
    the runner's finalization can call it unconditionally.
    """
    rollout_path = Path(rollout_path)
    try:
        records = [json.loads(line) for line in rollout_path.read_text(
            encoding="utf-8", errors="replace").splitlines() if line.strip()]
        if not records:
            return {"attempted": True, "ok": False, "reason": "empty_rollout"}
        companion_run_id = f"{run_id}_export"
        companion_id = make_trajectory_id(game_id, companion_run_id)
        out = Path(out_path) if out_path else trajectory_path(companion_id)
        if out.exists():
            return {"attempted": True, "ok": False, "reason": "companion_already_exists",
                    "path": str(out)}

        # the live view of the same session: its captured task/environment
        # and workspace/verification facts are the truth the export view keeps
        live_doc: dict = {}
        if live_trajectory_path is not None:
            try:
                live_doc = json.loads(Path(live_trajectory_path).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                live_doc = {}

        session_id = None
        for record in records:
            if record.get("type") == "session_meta":
                session_id = (record.get("payload") or {}).get("session_id")
                break

        # archive the rollout: references must point at the content-addressed
        # copy, never at a machine-local session file
        store = artifact_store or ArtifactStore()
        archived = None
        try:
            archived = store.put_file(rollout_path, mime_type="application/x-ndjson")
        except OSError:
            archived = None
        rollout_uri = archived["uri"] if archived else portable_uri(str(rollout_path))

        start_metadata = {"game_id": game_id, "run_id": companion_run_id,
                          "harness": "codex"}
        if live_trajectory_id is not None:
            start_metadata["predecessor_trajectory_id"] = live_trajectory_id
        start_metadata.update(identity_metadata(extra_metadata or {}))
        collector = Collector.start(start_metadata,
            task_ref=live_doc.get("task_ref") or {},
            environment_ref=live_doc.get("environment_ref") or {},
            path=out, register=register)

        # tool layer: derived from the calls the model actually made — the
        # rollout persists no tool registry (same honest source as the v1 chain)
        from scripts.convert_codex_rollout_to_trajectory import build_tools
        tools = build_tools(records)
        if tools:
            collector.record_tools(tools)
            collector.record_tool_set("observed_codex_tools", tools)
            collector.record_event("system", "runtime", producer="recover_codex_companion",
                audit_code="tools_derived_from_observed_calls",
                content=[content_block("json",
                    data={"definitions": len(tools),
                          "source": "function_call arguments in the rollout; the "
                                    "rollout persists no tool registry"},
                    visibility="collector_only")])

        observer = RolloutObserver(collector,
                                   session_id=str(session_id) if session_id else rollout_path.stem,
                                   assemble_requests=True)
        observer.observe(rollout_path, source_uri=rollout_uri)

        # the journal carries no file-change facts: inherit the SAME
        # session's recorded workspace history from the live view
        live_versions = (live_doc.get("workspace") or {}).get("file_versions") or []
        if live_versions:
            collector.trajectory["workspace"]["file_versions"] = [dict(v) for v in live_versions]
            collector.record_event("system", "runtime", producer="recover_codex_companion",
                audit_code="workspace_inherited_from_live_view",
                content=[content_block("json",
                    data={"file_versions": len(live_versions),
                          "source": "live view of the same session (predecessor link)"},
                    visibility="collector_only")])
        live_verification = live_doc.get("verification_refs") or []
        if live_verification:
            collector.trajectory["verification_refs"] = [dict(v) for v in live_verification]
            collector.record_event("system", "runtime", producer="recover_codex_companion",
                audit_code="verification_inherited_from_live_view",
                content=[content_block("json",
                    data={"verification_refs": len(live_verification),
                          "source": "live view of the same session (predecessor link)"},
                    visibility="collector_only")])

        data = rollout_path.read_bytes()
        attachment = {"type": "recovered_session_rollout", "uri": rollout_uri,
                      "sha256": hashlib.sha256(data).hexdigest(),
                      "mime_type": "application/x-ndjson", "size_bytes": len(data)}
        if archived:
            attachment["original_uri"] = portable_uri(str(rollout_path))
        collector.record_attachment(attachment)
        if not archived:
            collector.record_event("system", "runtime", producer="recover_codex_companion",
                audit_code="raw_rollout_not_portable",
                content=[content_block("json", data={"status": "missing",
                          "uri": rollout_uri}, visibility="collector_only")])
        collector.trajectory["derived_views"]["tools_used"] = \
            derive_tools_used(collector.trajectory["events"])
        collector.finish({"ok": True, "status": "recovered_from_session_rollout",
                          "source": "codex session rollout"}, completeness="partial")

        # cross-link the live view; its recorded result and completeness stay
        # exactly as finalized
        if live_trajectory_path is not None:
            link = Collector.resume(live_trajectory_path)
            if not any(a.get("trajectory_id") == companion_id
                       for a in link.trajectory.get("attachments", [])):
                link.record_attachment({
                    "type": "companion_export_trajectory", "trajectory_id": companion_id,
                    "uri": portable_uri(str(out)),
                    "recovered_from": "codex session rollout"})
                link.finish(link.trajectory.get("result") or {"ok": None, "status": "relinked"},
                            completeness=link.trajectory["metadata"].get("completeness")
                            or "partial")

        trajectory = json.loads(out.read_text(encoding="utf-8"))
        return {"attempted": True, "ok": True, "path": str(out),
                "trajectory_id": companion_id,
                "events": len(trajectory["events"]),
                "requests": len(trajectory["requests"]),
                "tools": len(tools),
                "model": observer.report.get("model"),
                "usage_records": [dict(record) for record in observer.report["usage_records"]],
                "appended_events": observer.report["appended_events"]}
    except Exception as exc:  # recovery must never break finalization
        return {"attempted": True, "ok": False, "error": f"{type(exc).__name__}: {exc}"}


def harvest_rollout_layer(collector: Collector, raw_dir: str | Path, *,
                          sessions_root: str | Path | None = None,
                          wait_seconds: float = ROLLOUT_FLUSH_WAIT_SECONDS) -> dict:
    """Record the session's tool layer and model into an OPEN collector.

    The exec stream carries neither tool definitions nor the model name; the
    session rollout is the only honest source: tools are derived from the
    calls the model actually made (the rollout persists no registry) and the
    model comes from ``turn_context``. Attribution is thread-precise (the
    stream's ``thread.started`` id equals the rollout's session id, verified
    on real exec rollouts). ``wait_seconds`` polls briefly because the final
    flush lands at process exit. Never raises — a harvest failure must not
    break the runner's finalization.
    """
    try:
        thread_id = thread_id_from_raw_stream(raw_dir)
        if not thread_id:
            return {"found": False, "reason": "thread_id_not_in_stream"}
        rollout = None
        deadline = time.monotonic() + max(0.0, wait_seconds)
        while True:
            rollout = find_rollout_for_thread(thread_id, sessions_root=sessions_root)
            if rollout is not None or time.monotonic() >= deadline:
                break
            time.sleep(0.2)
        if rollout is None:
            return {"found": False, "reason": "rollout_not_found",
                    "thread_id": thread_id}
        records = [json.loads(line) for line in rollout.read_text(
            encoding="utf-8", errors="replace").splitlines() if line.strip()]
        # model lift: turn_context carries the model actually serving the run
        for record in records:
            if record.get("type") == "turn_context" and (record.get("payload") or {}).get("model"):
                model = record["payload"]["model"]
                if not collector.trajectory["metadata"].get("model"):
                    collector.trajectory["metadata"]["model"] = model
                    collector.writer.checkpoint()
                break
        from scripts.convert_codex_rollout_to_trajectory import build_tools
        tools = build_tools(records)
        if not tools:
            return {"found": True, "definitions": 0}
        collector.record_tools(tools)
        collector.record_tool_set("observed_codex_tools", tools)
        collector.record_event("system", "runtime", producer="rollout_harvest",
            audit_code="tools_from_observed_calls",
            content=[content_block("json",
                data={"definitions": len(tools),
                      "source": "function_call arguments in the session rollout; "
                                "the exec stream and the rollout persist no registry"},
                visibility="collector_only")])
        return {"found": True, "definitions": len(tools)}
    except Exception as exc:  # never break the runner's finalization
        return {"found": False, "error": f"{type(exc).__name__}: {exc}"}


def attempt_codex_run_recovery(state: dict, raw_dir: str | Path,
                                live_trajectory_path: str | Path,
                                *, sessions_root: str | Path | None = None,
                                wait_seconds: float = ROLLOUT_FLUSH_WAIT_SECONDS) -> dict:
    """Runner finalization hook: rollout harvest for the requests-view companion.

    Runs on every codex finalize — the exec stream never carries request
    boundaries, so the session rollout is the only source, on clean exits
    just as much as interrupted ones. Attribution is thread-precise (the
    stream's ``thread.started`` id equals the rollout's session id, verified
    on real exec rollouts); the rollout's final flush lands at process exit,
    so the harvest briefly waits for the file. Never raises; the outcome is
    recorded into run_meta so the recovery is auditable from the run
    artifacts alone.
    """
    try:
        game_id = str(state.get("game_id") or "")
        run_id = str(state.get("run_id") or "")
        if not game_id or not run_id:
            return {"attempted": True, "ok": False, "reason": "missing_game_or_run_id"}
        thread_id = thread_id_from_raw_stream(raw_dir)
        if not thread_id:
            return {"attempted": True, "ok": False, "reason": "thread_id_not_in_stream"}
        rollout = None
        if wait_seconds > 0:
            deadline = time.monotonic() + wait_seconds
            while True:
                rollout = find_rollout_for_thread(thread_id, sessions_root=sessions_root)
                if rollout is not None or time.monotonic() >= deadline:
                    break
                time.sleep(0.2)
        else:
            rollout = find_rollout_for_thread(thread_id, sessions_root=sessions_root)
        if rollout is None:
            return {"attempted": True, "ok": False, "reason": "rollout_not_found",
                    "thread_id": thread_id}
        return recover_codex_companion(
            rollout_path=rollout, game_id=game_id, run_id=run_id,
            live_trajectory_id=make_trajectory_id(game_id, run_id),
            live_trajectory_path=live_trajectory_path,
            register=bool(state.get("register", True)),
            extra_metadata=identity_metadata(state))
    except Exception as exc:
        return {"attempted": True, "ok": False, "error": f"{type(exc).__name__}: {exc}"}
