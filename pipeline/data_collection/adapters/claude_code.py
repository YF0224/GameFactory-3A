"""Claude Code adapter: headless stream-json + live session-file observation.

Verified against the installed CLI (2.1.238) and its real local sessions:

* Headless: ``claude -p <prompt> --output-format stream-json`` emits one JSON
  event per line — ``system/init`` (session_id + model + tools list),
  ``assistant`` (the COMPLETE Anthropic API message: thinking / text /
  tool_use blocks, per-response usage, ``msg_`` id), ``user`` (tool_result
  blocks), and a terminal ``result`` event (subtype success/error_*,
  aggregate usage + cost). Unlike codely's delta stream, every assistant
  event is a finished response — no delta merging.
* Session records: ``~/.claude/projects/<dir>/<session-id>.jsonl`` is
  append-only, one record per line. Assistant records ARE complete API
  responses: full content blocks, ``message.id`` (``msg_...`` — the
  response-scoped boundary key), per-response ``usage`` (input/cache/output
  tokens + thinking_tokens), ``parentUuid``/``uuid`` chain, ``isSidechain``
  flag. User records carry ``tool_result`` blocks paired by ``tool_use_id``.
  Bookkeeping record types (mode / permission-mode / atis-latch /
  file-history-snapshot / attachment / queue-operation / last-prompt) are
  counted, never re-recorded as facts.
* Thinking blocks arrive in PLAINTEXT (Anthropic returns them to the
  client, unlike codex's encrypted blobs): archived under the same
  restricted policy as codely reasoning — collector_only, never training
  input. Sidechain records (``isSidechain``) are kept as runtime
  observations with their provenance; they never enter the main
  conversation's request assembly.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from pipeline.data_collection.paths import make_trajectory_id, trajectory_path

from .base import AgentAdapter
from ..core.artifact_store import ArtifactStore
from ..core.collector import Collector, content_block, identity_metadata
from .codely_autosave import (INPUT_RECONSTRUCTION, derive_tools_used,
                              portable_uri)

DEFAULT_PROJECTS_ROOT = Path("~/.claude/projects").expanduser()

#: Session-record types that are client bookkeeping, not conversation facts.
_BOOKKEEPING_TYPES = {"mode", "permission-mode", "atis-latch",
                      "file-history-snapshot", "attachment",
                      "queue-operation", "last-prompt"}

#: How long the headless recovery waits for the session file's final flush.
SESSION_FLUSH_WAIT_SECONDS = 3.0

# ── stream-json normalizer (headless live view) ─────────────────────────────


def _blocks_payload(blocks: list, store: Any | None = None,
                     limit: int = 8192) -> list[dict]:
    """Render anthropic content blocks as collector content blocks."""
    from .codely_autosave import _content
    out = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text" and isinstance(block.get("text"), str):
            out.append(_content(block["text"], store, limit, "collector_only"))
    return out


class ClaudeCodeAdapter(AgentAdapter):
    provider = "claude"
    # the -p stream never echoes the launch prompt (same as codex exec):
    # the runner records the delivered task input itself
    echoes_prompt = False

    def __init__(self, executable="claude", extra_args=()):
        self.executable, self.extra_args = executable, list(extra_args)

    def start(self, prompt, *, cwd, env=None):
        return self._spawn(
            [self.executable, "-p", prompt, "--output-format", "stream-json",
             *self.extra_args], cwd, env)

    def normalizer(self):
        return ClaudeCodeNormalizer()


def _tool_result_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "\n".join(parts)
    return json.dumps(content, ensure_ascii=False, default=str)


class ClaudeCodeNormalizer:
    """One stream-json event in, collector events out. No delta merging:
    each assistant event is a complete API response."""

    provider = "claude"

    def __init__(self):
        self.session_id = None
        self.model = None

    def normalize(self, event: dict):
        if not isinstance(event, dict):
            return [self._unknown(event)]
        typ = event.get("type")
        common = {"producer": "claude", "provider_event": typ,
                  "session_id": self.session_id or event.get("session_id"),
                  "model": self.model}
        if event.get("timestamp"):
            common.update(ts=event["timestamp"], ts_source="provider")
        if typ == "system":
            if event.get("subtype") == "init":
                self.session_id = event.get("session_id") or self.session_id
                self.model = event.get("model") or self.model
                common.update(session_id=self.session_id, model=self.model)
            return [dict(source="system", kind="runtime",
                         content=[content_block("json", data=event,
                                                visibility="collector_only")],
                         **common)]
        if typ == "assistant":
            message = event.get("message") or {}
            self.session_id = event.get("session_id") or self.session_id
            self.model = message.get("model") or self.model
            common.update(session_id=self.session_id, model=self.model)
            out = []
            blocks = message.get("content") or []
            if not isinstance(blocks, list):
                blocks = []
            texts = [b.get("text") for b in blocks
                     if isinstance(b, dict) and b.get("type") == "text"
                     and isinstance(b.get("text"), str)]
            thinking = "".join(b.get("thinking") or "" for b in blocks
                               if isinstance(b, dict) and b.get("type") == "thinking")
            if texts or thinking:
                event_out = dict(source="assistant", kind="message",
                                 content=_blocks_payload(
                                     [{"type": "text", "text": t} for t in texts]),
                                 **common)
                if thinking:
                    from .codely_reasoning import reasoning_record
                    event_out["raw_reasoning"] = reasoning_record(thinking)
                out.append(event_out)
            for block in blocks:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    call_id = block.get("id")
                    if not call_id or not block.get("name"):
                        continue
                    out.append(dict(
                        source="assistant", kind="tool_call",
                        tool_calls=[{"tool_call_id": str(call_id),
                                     "raw_tool_call_id": call_id,
                                     "name": block.get("name"),
                                     "arguments": block.get("input") or {}}],
                        content=[],
                        **common))
            if not out:
                out.append(dict(source="system", kind="runtime",
                                content=[content_block("json", data=event,
                                                       visibility="collector_only")],
                                **common))
            return out
        if typ == "user":
            message = event.get("message") or {}
            content = message.get("content")
            out = []
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_result":
                        call_id = block.get("tool_use_id")
                        if not call_id:
                            continue
                        out.append(dict(
                            source="tool", kind="tool_result",
                            tool_call_id=str(call_id),
                            raw_tool_call_id=call_id,
                            status="error" if block.get("is_error") else "success",
                            content=[content_block("text",
                                                   data=_tool_result_text(block.get("content")),
                                                   visibility="collector_only")],
                            **common))
                return out or [self._unknown(event, common)]
            if isinstance(content, str) and content:
                return [dict(source="user", kind="message",
                             content=[content_block("text", data=content,
                                                    visibility="collector_only")],
                             **common)]
            return [self._unknown(event, common)]
        if typ == "result":
            return [dict(source="system", kind="runtime",
                         content=[content_block("json", data=event,
                                                visibility="collector_only")],
                         **common)]
        return [self._unknown(event, common)]

    def finish(self):
        return []

    @staticmethod
    def _unknown(event, common=None):
        return dict(source="system", kind="runtime", status="unknown",
                    audit_code="unknown_provider_event", normalized=False,
                    content=[content_block("json", data=event,
                                           visibility="collector_only")],
                    **(common or {"producer": "claude"}))


# ── session-file location / attribution ─────────────────────────────────────


def session_files(root: str | Path = DEFAULT_PROJECTS_ROOT) -> set:
    """All session record files under the Claude projects root."""
    root = Path(root).expanduser()
    return {p for p in root.glob("*/*.jsonl") if p.is_file()}


def session_matches_prompt(session_path: str | Path, prompt: str) -> bool:
    """Session attribution anchor: a user record contains the launch prompt
    (the same prompt-anchor rule as the codely journal / codex rollout)."""
    prompt = (prompt or "").strip()
    if not prompt:
        return False
    try:
        with open(session_path, encoding="utf-8", errors="replace") as source:
            for line in source:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if record.get("type") != "user":
                    continue
                content = (record.get("message") or {}).get("content")
                text = content if isinstance(content, str) else ""
                if not text and isinstance(content, list):
                    text = "\n".join(b.get("text", "") for b in content
                                     if isinstance(b, dict)
                                     and isinstance(b.get("text"), str))
                if prompt in text:
                    return True
    except OSError:
        return False
    return False


def find_session_file(session_id: str | None,
                      *, projects_root: str | Path | None = None) -> Path | None:
    """The one session file for this session id (filename == session id)."""
    if not session_id:
        return None
    root = Path(projects_root).expanduser() if projects_root else DEFAULT_PROJECTS_ROOT
    matches = sorted(p for p in session_files(root) if p.name == f"{session_id}.jsonl")
    return matches[0] if len(matches) == 1 else None


def session_id_from_raw_stream(raw_dir: str | Path,
                                provider: str = "claude") -> str | None:
    """Read the child's session id from the archived stream's init event."""
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
            if (isinstance(event, dict) and event.get("type") == "system"
                    and event.get("subtype") == "init" and event.get("session_id")):
                return str(event["session_id"])
    return None


# ── live session-file observation (interactive / sidecar / companion) ───────


class ClaudeSessionObserver:
    """Fact-delta observation of one Claude Code session file (append-only).

    ``assemble_requests=False`` (the live view) records facts only.
    ``assemble_requests=True`` closes ONE reconstructed request per assistant
    record: each record IS a complete API response (verified on real
    sessions), so the boundary key is the response's own ``message.id``
    (``msg_...``), the response end is proven by the record's
    ``stop_reason``, and the usage block rides the message verbatim. Inputs
    are the conversation events strictly before the record. Sidechain
    records are observed with provenance and never enter the main
    conversation's assembly.
    """

    def __init__(self, collector: Collector, session_id: str, *,
                 assemble_requests: bool = False):
        self.collector = collector
        self.session_id = session_id
        self.assemble_requests = assemble_requests
        self.report: dict[str, Any] = {
            "appended_events": 0, "new_calls": 0, "new_results": 0,
            "lines": 0, "skipped_bookkeeping": 0, "audits": [],
            "new_requests": 0, "usage_records": [], "model": None,
            "sidechain_records": 0}
        self._offset = 0
        self._session_uri: str | None = None
        self._model: str | None = None
        self._context: list[str] = []

    def observe(self, session_path: str | Path, *,
                source_uri: str | None = None) -> dict[str, Any]:
        """Consume newly completed lines; return the live report."""
        self._session_uri = source_uri or portable_uri(str(session_path))
        try:
            data = Path(session_path).read_bytes()
        except OSError as exc:
            self._audit("session_unreadable", error=str(exc))
            return self.report
        limit = data.rfind(b"\n") + 1
        if limit > self._offset:
            for raw in data[self._offset:limit].splitlines():
                self.report["lines"] += 1
                try:
                    record = json.loads(raw)
                except ValueError:
                    self._audit("session_invalid_line")
                    continue
                self._consume(record)
            self._offset = limit
        return self.report

    def _source_refs(self, record: dict[str, Any]) -> dict[str, Any]:
        return {"uri": self._session_uri, "format": "claude-session",
                "positions": [], "source_ids": [record["uuid"]]
                if record.get("uuid") else []}

    def _consume(self, record: dict[str, Any]) -> None:
        rtype = record.get("type")
        if rtype in _BOOKKEEPING_TYPES:
            self.report["skipped_bookkeeping"] += 1
            return
        if record.get("isSidechain"):
            # a subagent chain: observed with provenance, never part of the
            # main conversation's request assembly
            self.report["sidechain_records"] += 1
            self._runtime("sidechain", record)
            return
        if rtype == "system":
            self._runtime("system", record)
            return
        if rtype == "user":
            self._consume_user(record)
            return
        if rtype == "assistant":
            self._consume_assistant(record)
            return
        self._audit("session_unknown_record_type", record_type=str(rtype))

    def _common(self, record: dict[str, Any], provider_event: str) -> dict[str, Any]:
        common = {"producer": "claude", "provider_event": provider_event,
                  "session_id": self.session_id}
        if record.get("timestamp"):
            common.update(ts=record["timestamp"], ts_source="provider")
        return common

    def _runtime(self, provider_event: str, record: dict[str, Any]) -> None:
        payload = {"type": record.get("type"),
                   "content": record.get("message") or record.get("content") or {},
                   "uuid": record.get("uuid")}
        self.collector.record_event("system", "runtime",
            content=[content_block("json", data=payload, visibility="collector_only")],
            source_refs=self._source_refs(record),
            **self._common(record, provider_event))
        self.report["appended_events"] += 1

    def _consume_user(self, record: dict[str, Any]) -> None:
        message = record.get("message") or {}
        content = message.get("content")
        refs = self._source_refs(record)
        if isinstance(content, list):
            recorded = False
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_result":
                    call_id = block.get("tool_use_id")
                    if not call_id:
                        self._audit("session_result_without_call_id")
                        continue
                    event_id = self.collector.record_event(
                        "tool", "tool_result",
                        content=[content_block("text",
                                   data=_tool_result_text(block.get("content")),
                                   visibility="agent_received")],
                        tool_call_id=str(call_id), raw_tool_call_id=call_id,
                        status="error" if block.get("is_error") else "success",
                        source_refs=refs, **self._common(record, "user.tool_result"))
                    self.report["appended_events"] += 1
                    self.report["new_results"] += 1
                    self._note(event_id)
                    recorded = True
            if recorded:
                return
            texts = [b.get("text") for b in content
                     if isinstance(b, dict) and isinstance(b.get("text"), str)]
            if not texts:
                return  # a stub without visible text is not a fact
            content_text = "\n".join(texts)
        elif isinstance(content, str):
            content_text = content
        else:
            return
        if not content_text:
            return
        event_id = self.collector.record_event("user", "message",
            content=[content_block("text", data=content_text,
                                   visibility="agent_received")],
            source_refs=refs, **self._common(record, "user.message"))
        self.report["appended_events"] += 1
        self._note(event_id)

    def _note(self, event_id: str) -> None:
        if self.assemble_requests:
            self._context.append(event_id)

    def _consume_assistant(self, record: dict[str, Any]) -> None:
        message = record.get("message") or {}
        model = message.get("model")
        if model:
            self._model = str(model)
            self.report["model"] = self._model
            metadata = self.collector.trajectory["metadata"]
            if not metadata.get("model"):
                metadata["model"] = model
                self.collector.writer.checkpoint()
        blocks = message.get("content") or []
        if not isinstance(blocks, list):
            blocks = []
        refs = self._source_refs(record)
        common = self._common(record, "assistant")
        input_ids = list(self._context)  # snapshot BEFORE this response
        response_ids: list[str] = []
        texts = [b.get("text") for b in blocks
                 if isinstance(b, dict) and b.get("type") == "text"
                 and isinstance(b.get("text"), str)]
        thinking = "".join(b.get("thinking") or "" for b in blocks
                           if isinstance(b, dict) and b.get("type") == "thinking")
        if texts or thinking:
            kwargs: dict[str, Any] = dict(common)
            if thinking:
                from .codely_reasoning import reasoning_record
                kwargs["raw_reasoning"] = reasoning_record(thinking)
            event_id = self.collector.record_event(
                "assistant", "message",
                content=[content_block("text", data=text, visibility="agent_received")
                         for text in texts],
                source_refs=refs, **kwargs)
            self.report["appended_events"] += 1
            response_ids.append(event_id)
        for block in blocks:
            if not (isinstance(block, dict) and block.get("type") == "tool_use"):
                continue
            call_id = block.get("id")
            if not call_id or not block.get("name"):
                self._audit("session_call_without_identity", call_id=call_id)
                continue
            event_id = self.collector.record_event(
                "assistant", "tool_call", content=[],
                tool_calls=[{"tool_call_id": str(call_id),
                             "raw_tool_call_id": call_id,
                             "name": block.get("name"),
                             "arguments": block.get("input") or {}}],
                source_refs=refs, **common)
            self.report["appended_events"] += 1
            self.report["new_calls"] += 1
            response_ids.append(event_id)
        if not response_ids:
            return  # an empty response record is not a fact
        usage = message.get("usage") if isinstance(message.get("usage"), dict) else None
        response_id = message.get("id")
        self.report["usage_records"].append({
            "response_id": response_id, "usage": usage, "model": self._model,
            "ts": record.get("timestamp")})
        self._context.extend(response_ids)
        if not self.assemble_requests:
            return
        markers: dict[str, Any] = {
            "input_reconstruction": INPUT_RECONSTRUCTION,
            "boundary": "reconstructed",
            # each assistant record IS one complete API response; its own
            # message id is the response-scoped key (verified on real sessions)
            "boundary_basis": {"type": "assistant_record_message_id",
                               "response_id": response_id},
            "context": "partial",
            "context_basis": {"type": "session_history_reconstruction",
                              "system_prompt": False,
                              "history_verification": "complete_file_read"},
            "response_status": "complete" if message.get("stop_reason") else "unknown",
            "response_basis": {"type": "assistant_record_stop_reason",
                               "stop_reason": message.get("stop_reason")},
        }
        fields: dict[str, Any] = {"model": self._model, "provider": "claude",
                                  "session_id": self.session_id}
        if usage is not None:
            fields["usage"] = usage
        self.collector.record_request(input_ids, response_ids, **fields, **markers)
        self.report["new_requests"] += 1

    def _audit(self, code: str, **facts: Any) -> None:
        self.collector.record_event("system", "runtime",
            producer="session_observer", audit_code=code,
            content=[content_block("json", data=facts, visibility="collector_only")])
        self.report["audits"].append(code)
        self.report["appended_events"] += 1


# ── tool layer from observed calls (sessions persist no registry) ──────────


def derive_tool_definitions(records: list[dict[str, Any]]) -> list[dict]:
    """Tool definitions derived from the tool_use blocks actually observed —
    the session file persists no tool registry (same honest source as codex)."""
    observed: dict[str, dict[str, str]] = {}
    for record in records:
        message = record.get("message") or {}
        blocks = message.get("content") or []
        if record.get("type") != "assistant" or not isinstance(blocks, list):
            continue
        for block in blocks:
            if not (isinstance(block, dict) and block.get("type") == "tool_use"):
                continue
            name = block.get("name")
            if not name:
                continue
            props = observed.setdefault(name, {})
            args = block.get("input") or {}
            if isinstance(args, dict):
                for key, value in args.items():
                    if key not in props:
                        props[key] = {"type": {
                            bool: "boolean", int: "integer", float: "number",
                            str: "string", list: "array", dict: "object",
                        }.get(type(value), "string")}
    return [{"name": name, "input_schema": {"type": "object", "properties": props}
             if props else {"type": "object"}}
            for name, props in sorted(observed.items())]


# ── companion recovery (mirrors recover_codex_companion) ───────────────────


def recover_claude_companion(*, session_path: str | Path, game_id: str, run_id: str,
                             live_trajectory_id: str | None = None,
                             live_trajectory_path: str | Path | None = None,
                             register: bool = True, out_path: str | Path | None = None,
                             extra_metadata: dict | None = None,
                             artifact_store: Any = None) -> dict[str, Any]:
    """Build the export-view companion trajectory from a Claude session file.

    Requests close at the assistant records themselves (one complete API
    response each, keyed by its ``message.id``, usage verbatim). Thinking is
    archived plaintext under the restricted policy; the session file is
    archived into the content-addressed store. With ``live_trajectory_*``
    the views cross-link; without them this is a standalone post-hoc
    conversion. Returns an outcome dict; never raises.
    """
    session_path = Path(session_path)
    try:
        records = [json.loads(line) for line in session_path.read_text(
            encoding="utf-8", errors="replace").splitlines() if line.strip()]
        if not records:
            return {"attempted": True, "ok": False, "reason": "empty_session"}
        companion_run_id = f"{run_id}_export"
        companion_id = make_trajectory_id(game_id, companion_run_id)
        out = Path(out_path) if out_path else trajectory_path(companion_id)
        if out.exists():
            return {"attempted": True, "ok": False, "reason": "companion_already_exists",
                    "path": str(out)}

        live_doc: dict = {}
        if live_trajectory_path is not None:
            try:
                live_doc = json.loads(Path(live_trajectory_path).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                live_doc = {}

        store = artifact_store or ArtifactStore()
        archived = None
        try:
            archived = store.put_file(session_path, mime_type="application/x-ndjson")
        except OSError:
            archived = None
        session_uri = archived["uri"] if archived else portable_uri(str(session_path))

        start_metadata = {"game_id": game_id, "run_id": companion_run_id,
                          "harness": "claude"}
        if live_trajectory_id is not None:
            start_metadata["predecessor_trajectory_id"] = live_trajectory_id
        start_metadata.update(identity_metadata(extra_metadata or {}))
        collector = Collector.start(start_metadata,
            task_ref=live_doc.get("task_ref") or {},
            environment_ref=live_doc.get("environment_ref") or {},
            path=out, register=register)

        tools = derive_tool_definitions(records)
        if tools:
            collector.record_tools(tools)
            collector.record_tool_set("observed_claude_tools", tools)
            collector.record_event("system", "runtime", producer="recover_claude_companion",
                audit_code="tools_from_observed_calls",
                content=[content_block("json",
                    data={"definitions": len(tools),
                          "source": "tool_use blocks in the session file; "
                                    "the session persists no tool registry"},
                    visibility="collector_only")])

        observer = ClaudeSessionObserver(collector, session_id=session_path.stem,
                                         assemble_requests=True)
        observer.observe(session_path, source_uri=session_uri)

        live_versions = (live_doc.get("workspace") or {}).get("file_versions") or []
        if live_versions:
            collector.trajectory["workspace"]["file_versions"] = [dict(v) for v in live_versions]
            collector.record_event("system", "runtime", producer="recover_claude_companion",
                audit_code="workspace_inherited_from_live_view",
                content=[content_block("json",
                    data={"file_versions": len(live_versions),
                          "source": "live view of the same session (predecessor link)"},
                    visibility="collector_only")])
        live_verification = live_doc.get("verification_refs") or []
        if live_verification:
            collector.trajectory["verification_refs"] = [dict(v) for v in live_verification]
            collector.record_event("system", "runtime", producer="recover_claude_companion",
                audit_code="verification_inherited_from_live_view",
                content=[content_block("json",
                    data={"verification_refs": len(live_verification),
                          "source": "live view of the same session (predecessor link)"},
                    visibility="collector_only")])

        data = session_path.read_bytes()
        attachment = {"type": "recovered_session_records", "uri": session_uri,
                      "sha256": _sha256(data), "mime_type": "application/x-ndjson",
                      "size_bytes": len(data)}
        if archived:
            attachment["original_uri"] = portable_uri(str(session_path))
        collector.record_attachment(attachment)
        collector.trajectory["derived_views"]["tools_used"] = \
            derive_tools_used(collector.trajectory["events"])
        collector.finish({"ok": True, "status": "recovered_from_session_records",
                          "source": "claude code session file"}, completeness="partial")

        if live_trajectory_path is not None:
            link = Collector.resume(live_trajectory_path)
            if not any(a.get("trajectory_id") == companion_id
                       for a in link.trajectory.get("attachments", [])):
                link.record_attachment({
                    "type": "companion_export_trajectory", "trajectory_id": companion_id,
                    "uri": portable_uri(str(out)),
                    "recovered_from": "claude code session file"})
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
                "usage_records": [dict(r) for r in observer.report["usage_records"]],
                "appended_events": observer.report["appended_events"]}
    except Exception as exc:  # recovery must never break finalization
        return {"attempted": True, "ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _sha256(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()


def attempt_claude_run_recovery(state: dict, raw_dir: str | Path,
                                live_trajectory_path: str | Path,
                                *, projects_root: str | Path | None = None,
                                wait_seconds: float = SESSION_FLUSH_WAIT_SECONDS) -> dict:
    """Runner finalization hook: session-file harvest for the requests view.

    Runs on every claude finalize — clean exits included. Attribution is
    session-precise (the stream init's session_id is the session filename).
    Never raises; the outcome is recorded into run_meta.
    """
    try:
        game_id = str(state.get("game_id") or "")
        run_id = str(state.get("run_id") or "")
        if not game_id or not run_id:
            return {"attempted": True, "ok": False, "reason": "missing_game_or_run_id"}
        session_id = session_id_from_raw_stream(raw_dir)
        if not session_id:
            return {"attempted": True, "ok": False, "reason": "session_id_not_in_stream"}
        session_path = None
        if wait_seconds > 0:
            deadline = time.monotonic() + wait_seconds
            while True:
                session_path = find_session_file(session_id, projects_root=projects_root)
                if session_path is not None or time.monotonic() >= deadline:
                    break
                time.sleep(0.2)
        else:
            session_path = find_session_file(session_id, projects_root=projects_root)
        if session_path is None:
            return {"attempted": True, "ok": False, "reason": "session_file_not_found",
                    "session_id": session_id}
        return recover_claude_companion(
            session_path=session_path, game_id=game_id, run_id=run_id,
            live_trajectory_id=make_trajectory_id(game_id, run_id),
            live_trajectory_path=live_trajectory_path,
            register=bool(state.get("register", True)),
            extra_metadata=identity_metadata(state))
    except Exception as exc:
        return {"attempted": True, "ok": False, "error": f"{type(exc).__name__}: {exc}"}


def harvest_claude_session_layer(collector: Collector, raw_dir: str | Path, *,
                                 projects_root: str | Path | None = None,
                                 wait_seconds: float = SESSION_FLUSH_WAIT_SECONDS) -> dict:
    """Record the session's tool layer and model into an OPEN collector.

    The stream's init carries the model; the session file's observed
    tool_use blocks are the only honest tool-registry source (the session
    persists no definitions). Never raises.
    """
    try:
        session_id = session_id_from_raw_stream(raw_dir)
        if not session_id:
            return {"found": False, "reason": "session_id_not_in_stream"}
        session_path = None
        deadline = time.monotonic() + max(0.0, wait_seconds)
        while True:
            session_path = find_session_file(session_id, projects_root=projects_root)
            if session_path is not None or time.monotonic() >= deadline:
                break
            time.sleep(0.2)
        if session_path is None:
            return {"found": False, "reason": "session_file_not_found",
                    "session_id": session_id}
        records = [json.loads(line) for line in session_path.read_text(
            encoding="utf-8", errors="replace").splitlines() if line.strip()]
        for record in records:
            message = record.get("message") or {}
            if record.get("type") == "assistant" and message.get("model"):
                if not collector.trajectory["metadata"].get("model"):
                    collector.trajectory["metadata"]["model"] = message["model"]
                    collector.writer.checkpoint()
                break
        tools = derive_tool_definitions(records)
        if not tools:
            return {"found": True, "definitions": 0}
        collector.record_tools(tools)
        collector.record_tool_set("observed_claude_tools", tools)
        collector.record_event("system", "runtime", producer="session_harvest",
            audit_code="tools_from_observed_calls",
            content=[content_block("json",
                data={"definitions": len(tools),
                      "source": "tool_use blocks in the session file; "
                                "the session persists no tool registry"},
                visibility="collector_only")])
        return {"found": True, "definitions": len(tools)}
    except Exception as exc:  # never break the runner's finalization
        return {"found": False, "error": f"{type(exc).__name__}: {exc}"}
