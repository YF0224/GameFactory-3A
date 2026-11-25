"""Recover Codely live-session journals into export-view companion trajectories.

The CLI keeps a rolling per-session journal under
``~/.codely-cli/tmp/<project>/chats/<session-id>.jsonl`` (put/ckpt records whose
``msg`` payloads carry the full UI-level session: canonicalParts, segmented
``thoughts``, and ``toolCalls`` entries that include each call's result).

A live-runner child killed without a clean exit (SIGTERM on interrupt/timeout,
network death) never writes its session export. The journal is then the only
source of the model interactions, so the runner finalization path harvests it
automatically and builds the companion "export view" trajectory (requests with
boundaries, calls, results, thinking) that the live stream alone cannot
provide.

The recovery functions never raise: they report outcomes so a failure can
never break the runner's finalization.
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from pipeline.data_collection.paths import make_trajectory_id, trajectory_path

from ..core.artifact_store import ArtifactStore
from ..core.collector import Collector, content_block, identity_metadata
from .codely_autosave import (AutosaveSessionImporter, _content, _doc_model, _tools,
                              derive_tools_used, portable_uri,
                              sanitize_trajectory_paths)
from .codely_reasoning import reasoning_record

DEFAULT_JOURNAL_ROOT = Path("~/.codely-cli/tmp").expanduser()


def find_session_journal(session_id: str, *, root: Path | None = None) -> Path | None:
    """Locate the CLI journal for a session id (unique across projects)."""
    base = (root or DEFAULT_JOURNAL_ROOT).expanduser()
    matches = sorted(glob.glob(str(base / "*" / "chats" / f"{session_id}.jsonl")))
    return Path(matches[0]) if matches else None


def session_id_from_raw_stream(raw_dir: str | Path, provider: str) -> str | None:
    """Read the child's session id from the archived stream's init event."""
    stream = Path(raw_dir) / f"{provider}.jsonl"
    if not stream.exists():
        return None
    with open(stream, encoding="utf-8", errors="replace") as f:
        for _ in range(20):
            line = f.readline()
            if not line:
                break
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and event.get("type") == "init" and event.get("session_id"):
                return str(event["session_id"])
    return None


def _autosave_system_prompt(doc: dict) -> str | None:
    system = (((doc.get("prefixContext") or {}).get("systemPrompt") or {})
              .get("dynamic") or {}).get("joinedText")
    return system or None


def _autosave_system_ref(doc: dict) -> dict | None:
    """Static core-prompt reference when the export carries no prompt text.

    Verified against the installed CLI (1.0.0-release.57): with empty dynamic
    sections, ``prefixContext.systemPrompt.static`` is a ``core_static_ref``
    (sectionName + hash + placeholderText) — the actual core prompt text
    lives in the CLI binary, so the export can only ever give a
    content-addressed reference, never the text. The reference is recorded,
    the prompt is never fabricated.
    """
    static = ((doc.get("prefixContext") or {}).get("systemPrompt") or {}).get("static")
    if isinstance(static, dict) and static.get("hash"):
        return dict(static)
    return None


def harvest_exit_autosave(session_id: str | None, workspace: str | Path | None,
                          *, autosave_dir: str | Path | None = None,
                          autosave_pattern: str = "chat-auto-save-*.json"
                          ) -> tuple[Path, dict] | None:
    """Newest session export of THIS session under the workspace's auto-saves.

    Attribution is session-precise (``conversationRecord.sessionId``), never
    newest-by-mtime alone: a copied-in workspace can carry another session's
    exports, and a torn mid-rewrite file is skipped for the next candidate.
    The journal carries neither tool definitions nor the system prompt, so a
    matching export is the only honest source for both.
    """
    if not session_id:
        return None
    directory = Path(autosave_dir).expanduser() if autosave_dir else (
        Path(workspace).expanduser() / ".codely-cli" / "auto-saves")
    if not directory.is_dir():
        return None
    candidates = []
    for path in directory.glob(autosave_pattern):
        try:
            if path.is_file():
                candidates.append((path.stat().st_mtime_ns, path))
        except OSError:
            continue
    for _, path in sorted(candidates, reverse=True):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        session = (doc.get("conversationRecord") or {}).get("sessionId")
        if session is not None and str(session) == str(session_id):
            return path, doc
    return None


def _message_texts(message: dict[str, Any]) -> list[str]:
    """Visible (non-thought) canonical text parts, with content fallbacks."""
    parts = []
    for cp in message.get("canonicalParts") or []:
        if isinstance(cp, dict) and cp.get("text") and not cp.get("thought"):
            parts.append(cp["text"])
    if parts:
        return parts
    content = message.get("content")
    if isinstance(content, str) and content:
        return [content]
    if isinstance(content, list):
        return [p.get("text", "") for p in content
                if isinstance(p, dict) and p.get("text")]
    return []


def _call_facts(message: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalized toolCall facts of one message revision.

    Mirrors journal_to_client_history's exact normalization: a dict result
    needs a non-empty functionResponse object; a string result becomes
    ``{"output": text}`` keyed by the call id. ``response is None`` means the
    revision does not carry this call's result yet.
    """
    facts = []
    for tc in message.get("toolCalls") or []:
        if not isinstance(tc, dict):
            continue
        res = tc.get("result")
        if isinstance(res, dict):
            fr = res.get("functionResponse") or {}
            if fr:
                result_id, response = fr.get("id"), fr.get("response", {})
            else:
                result_id, response = None, None
        elif isinstance(res, str):
            result_id, response = tc.get("id"), {"output": res}
        else:
            result_id, response = None, None
        facts.append({"call_id": tc.get("id"), "name": tc.get("name"),
                      "arguments": tc.get("args", {}),
                      "result_id": result_id, "response": response})
    return facts


def journal_to_client_history(path: str | Path) -> list[dict[str, Any]]:
    """Materialize message revisions by explicit ID, preserving first-seen order.

    ``put`` replaces a message, it is not a new model turn. Thinking-only
    messages remain independent observations; never guess their next owner.
    A torn final line is ignored; malformed complete records fail recovery.
    Every emitted entry carries its raw provenance: the journal uri, the seqs
    of ALL revisions of that message id (merged deltas keep the whole source
    range), the source message id, and the ``committed`` response-end flag.
    """
    messages: dict[Any, dict[str, Any]] = {}
    with open(path, encoding="utf-8") as source:
        for line_no, line in enumerate(source, 1):
            try:
                record = json.loads(line)
            except ValueError:
                if not line.endswith("\n"):
                    break
                raise ValueError(f"invalid journal record at line {line_no}")
            if record.get("t") != "put":
                continue
            m = record.get("msg") or {}
            key = ("id", m["id"]) if m.get("id") else ("line", line_no)
            entry = messages.setdefault(key, {"msg": m, "seqs": []})
            entry["msg"] = m  # latest revision wins
            if record.get("seq") is not None:
                entry["seqs"].append(record["seq"])
    events: list[dict[str, Any]] = []
    uri = portable_uri(str(path))
    for entry in messages.values():
        m = entry["msg"]
        ts = m.get("timestamp")
        parts = [{"text": text} for text in _message_texts(m)]
        source_ref = {"uri": uri, "format": "codely-journal",
                      "positions": list(entry["seqs"]),
                      "source_ids": [m["id"]] if m.get("id") else []}
        if m.get("type") == "user":
            events.append({"role": "user", "id": m.get("id"), "timestamp": ts,
                           "parts": parts, "thoughts": [],
                           "committed": m.get("committed"), "source": source_ref})
            continue
        calls, responses = [], []
        for fact in _call_facts(m):
            calls.append({"functionCall": {"id": fact["call_id"], "name": fact["name"],
                                            "args": fact["arguments"]}})
            if fact["response"] is not None:
                responses.append({"functionResponse": {"id": fact["result_id"],
                                                      "response": fact["response"]}})
        thoughts = m.get("thoughts") or []
        # The journal message id rides along as the response-grouping key
        # (one journal message revision = one recorded model response); it is
        # never a provider request id.
        if calls:
            events.append({"role": "model", "id": m.get("id"), "model": m.get("model"),
                           "timestamp": ts, "parts": parts + calls,
                           "thoughts": thoughts,
                           "committed": m.get("committed"), "source": source_ref})
            if responses:
                events.append({"role": "user", "timestamp": ts, "parts": responses,
                               "thoughts": [], "source": source_ref})
        elif parts or thoughts:
            events.append({"role": "model", "id": m.get("id"), "model": m.get("model"),
                           "timestamp": ts, "parts": parts,
                           "thoughts": thoughts,
                           "committed": m.get("committed"), "source": source_ref})
    return events


def journal_matches_prompt(journal_path: str | Path, prompt: str) -> bool:
    """Session attribution anchor: the child's journal contains the launch
    prompt among its user messages. A concurrently-created journal from an
    unrelated session does not match, so attribution never merges sessions
    by timestamp guesses."""
    prompt = (prompt or "").strip()
    if not prompt:
        return False
    try:
        with open(journal_path, encoding="utf-8", errors="replace") as source:
            for line in source:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                message = record.get("msg") or {}
                if record.get("t") == "put" and message.get("type") == "user":
                    if prompt in "\n".join(_message_texts(message)):
                        return True
    except OSError:
        return False
    return False


class JournalObserver:
    """Real-time fact-delta observation of one codely live-session journal.

    A journal ``put`` is a REVISION of a message, not a new model turn: a
    model message often first appears thinking-only and is later revised to
    carry its toolCalls, and later again their results. Observation is
    therefore fact-based, exactly once per fact:

    * a message's first appearance emits its visible text (+ reasoning);
    * a revision that first shows a call emits that call;
    * a later revision that first shows the call's result emits the result;
    * already-recorded facts are never re-recorded;
    * a conflicting revision is kept as an audited observation;
    * only complete lines are consumed — a torn tail is retried next poll.

    Events are stream-shaped; no request boundaries are invented here (the
    request-view companion comes from ``recover_companion``/rebuild).
    """

    def __init__(self, importer: AutosaveSessionImporter, session_id: str):
        self.importer = importer
        self.collector = importer.collector
        self.session_id = session_id
        self.report: dict[str, Any] = {"appended_events": 0, "new_calls": 0,
                                       "new_results": 0, "lines": 0, "audits": []}
        self._offset = 0
        self._journal_uri: str | None = None
        self._message_digests: dict[Any, str] = {}
        self._calls: dict[tuple[Any, Any], str] = {}
        self._emitted_results: set[tuple[Any, Any]] = set()

    def _source_refs(self, seq: Any) -> dict[str, Any]:
        """Per-event raw provenance: the journal file and the record seq that
        carried the fact — a later conversion fix can regenerate from here.
        The URI is machine-portable ($HOME/... per schema §8.2)."""
        return {"uri": portable_uri(self._journal_uri), "format": "codely-journal",
                "positions": [seq] if seq is not None else []}

    def observe(self, journal_path: str | Path) -> dict[str, Any]:
        """Consume the journal's newly completed lines; return the live report."""
        self._journal_uri = str(journal_path)
        try:
            data = Path(journal_path).read_bytes()
        except OSError as exc:
            self._audit("journal_unreadable", error=str(exc))
            return self.report
        limit = data.rfind(b"\n") + 1
        if limit > self._offset:
            for raw in data[self._offset:limit].splitlines():
                self.report["lines"] += 1
                try:
                    record = json.loads(raw)
                except ValueError:
                    self._audit("journal_invalid_line")
                    continue
                if record.get("t") == "put":
                    self._observe_put(record.get("msg") or {}, record.get("seq"))
                elif record.get("t") == "session":
                    self._observe_session(record)
            self._offset = limit
        return self.report

    def _observe_session(self, record: dict[str, Any]) -> None:
        session = record.get("session") if isinstance(record.get("session"), dict) else {}
        session_id = session.get("sessionId") or record.get("sessionId")
        if session_id and str(session_id) != str(self.session_id):
            self._audit("journal_session_conflict", expected=str(self.session_id),
                        observed=str(session_id))

    def _observe_put(self, message: dict[str, Any], seq: Any) -> None:
        mid = message.get("id")
        if not mid:
            self._audit("journal_put_without_id")
            return
        texts = _message_texts(message)
        thoughts = message.get("thoughts") or []
        ts = message.get("timestamp")
        digest = hashlib.sha256(json.dumps([texts, thoughts] if not message.get("type") == "user"
                                            else [texts], ensure_ascii=False, default=str
                                            ).encode("utf-8")).hexdigest()
        known = self._message_digests.get(mid)
        if message.get("type") == "user":
            if not texts:
                return  # a context stub without visible text is not a fact
            if known is None or digest != known:
                if known is not None:
                    self._audit("user_message_revised", message_id=mid)
                self._message_digests[mid] = digest
                self._emit_user(texts, ts, seq)
            return
        if known is None or digest != known:
            if known is not None:
                self._audit("model_message_revised", message_id=mid)
            self._message_digests[mid] = digest
            if texts or thoughts:
                self._emit_model(texts, thoughts, ts, seq)
        self._observe_calls(mid, message, ts, seq)

    def _emit_user(self, texts: list[str], ts: Any, seq: Any) -> None:
        extras = {"ts": ts} if ts else {}
        self.collector.record_event("user", "message",
            content=self.importer._blocks(texts), source_refs=self._source_refs(seq), **extras)
        self.report["appended_events"] += 1

    def _emit_model(self, texts: list[str], thoughts: list[Any], ts: Any, seq: Any) -> None:
        kwargs: dict[str, Any] = {}
        if ts:
            kwargs["ts"] = ts
        if thoughts:
            kwargs["raw_reasoning"] = reasoning_record(thoughts)
        self.collector.record_event("assistant", "message",
            content=self.importer._blocks(texts), source_refs=self._source_refs(seq), **kwargs)
        self.report["appended_events"] += 1

    def _observe_calls(self, mid: Any, message: dict[str, Any], ts: Any, seq: Any) -> None:
        for fact in _call_facts(message):
            call_id = fact["call_id"]
            if not call_id:
                self._audit("journal_call_without_id", message_id=mid)
                continue
            key = (mid, call_id)
            fingerprint = json.dumps([fact["name"], fact["arguments"]],
                                     sort_keys=True, default=str)
            known = self._calls.get(key)
            if known is None or known != fingerprint:
                if known is not None:
                    self._audit("call_conflict", message_id=mid, call_id=call_id)
                self._calls[key] = fingerprint
                self._emit_call(fact, ts, seq)
            if fact["response"] is not None and key not in self._emitted_results:
                self._emitted_results.add(key)
                self._emit_result(fact, ts, seq)

    def _emit_call(self, fact: dict[str, Any], ts: Any, seq: Any) -> None:
        kwargs: dict[str, Any] = {"tool_calls": [{
            "tool_call_id": self.importer._cid(self.session_id, fact["call_id"]),
            "raw_tool_call_id": fact["call_id"],
            "name": fact["name"], "arguments": fact["arguments"]}],
            "source_refs": self._source_refs(seq)}
        if ts:
            kwargs["ts"] = ts
        self.collector.record_event("assistant", "tool_call", content=[], **kwargs)
        self.report["appended_events"] += 1
        self.report["new_calls"] += 1

    def _emit_result(self, fact: dict[str, Any], ts: Any, seq: Any) -> None:
        raw_id = fact["result_id"] or fact["call_id"]
        extras = {"ts": ts} if ts else {}
        self.collector.record_event("tool", "tool_result",
            content=[_content(fact["response"], self.importer.store,
                              self.importer.max_inline_chars, "agent_received")],
            tool_call_id=self.importer._cid(self.session_id, raw_id),
            raw_tool_call_id=raw_id,
            source_refs=self._source_refs(seq),
            **extras)
        self.report["appended_events"] += 1
        self.report["new_results"] += 1

    def _audit(self, code: str, **facts: Any) -> None:
        self.collector.record_event("system", "runtime",
            producer="journal_observer", audit_code=code,
            content=[content_block("json", data=facts, visibility="collector_only")])
        self.report["audits"].append(code)
        self.report["appended_events"] += 1


def recover_companion(*, journal_path: str | Path, game_id: str, run_id: str,
                      live_trajectory_id: str, live_trajectory_path: str | Path,
                      register: bool = True, out_path: str | Path | None = None,
                      visible_tools: list | None = None,
                      system_prompt: str | None = None,
                      system_ref: dict | None = None,
                      extra_metadata: dict | None = None,
                      workspace: str | None = None,
                      artifact_store: Any = None) -> dict[str, Any]:
    """Build the export-view companion trajectory from a session journal.

    Returns an outcome dict; never raises so the runner's finalization path
    can call it unconditionally. ``out_path`` overrides the default
    train_data location (tests). ``visible_tools`` and ``system_prompt``
    optionally carry the tool definitions and system prompt the caller
    harvested from the session's exit autosave: the journal records neither,
    and the companion's training view must keep both. The tool defs are
    re-serialized into the export shape and flow through the importer's
    normal paths; the system prompt rides the export's prefixContext so the
    importer records it once as the session's real system input. When the
    export carries no prompt text but only the static core-prompt hash
    reference (verified CLI shape), ``system_ref`` records that reference as
    an audit — the prompt text is never fabricated. Without them the gaps
    stay honestly empty. ``extra_metadata`` carries run identity fields
    (episode/attempt/task) through to the companion. The task statement,
    environment capture, workspace file-change history and verification
    refs are inherited from the live view of the SAME session
    (predecessor_trajectory_id documents the source view). ``workspace``
    enables the structured portability pass over the canonical fields.

    The journal itself is archived into the content-addressed store so the
    companion is self-contained: attachments and per-event source_refs point
    at the archived copy, never at a machine-local session file. When
    archiving fails the external path is still recorded but an
    ``raw_journal_not_portable`` audit marks it honestly as not recoverable.
    """
    journal_path = Path(journal_path)
    try:
        client_history = journal_to_client_history(journal_path)
        if not client_history:
            return {"attempted": True, "ok": False, "reason": "empty_journal"}

        companion_run_id = f"{run_id}_export"
        companion_id = make_trajectory_id(game_id, companion_run_id)
        out_path = Path(out_path) if out_path else trajectory_path(companion_id)
        if out_path.exists():
            return {"attempted": True, "ok": False, "reason": "companion_already_exists",
                    "path": str(out_path)}

        # the live view of the same session: its task_ref/environment_ref and
        # workspace/verification facts are the captured truth the export view
        # must not lose
        try:
            live_doc = json.loads(Path(live_trajectory_path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            live_doc = {}
        live_task_ref = live_doc.get("task_ref") or {}
        live_environment_ref = live_doc.get("environment_ref") or {}
        live_versions = (live_doc.get("workspace") or {}).get("file_versions") or []
        live_verification = live_doc.get("verification_refs") or []

        # archive the journal: the companion must not depend on a
        # machine-local session file to stay recoverable
        archived = None
        try:
            archived = (artifact_store or ArtifactStore()).put_file(
                journal_path, mime_type="application/x-ndjson")
        except OSError:
            archived = None
        journal_uri = archived["uri"] if archived else portable_uri(str(journal_path))
        for entry in client_history:
            if isinstance(entry.get("source"), dict):
                entry["source"]["uri"] = journal_uri

        doc = {
            "codelyVersion": "journal-recovery",
            "tag": journal_path.stem,
            "conversationRecord": {"sessionId": journal_path.stem, "messages": [],
                                   "fileHistorySnapshots": []},
            "prefixContext": {"model": "codely-core", "systemPrompt": {}},
            "visibleTools": [],
            "clientHistory": client_history,
        }
        if system_prompt:
            doc["prefixContext"]["systemPrompt"] = {"dynamic": {"joinedText": system_prompt}}
        if visible_tools:
            # caller-side source: the session's exit autosave (journal has no
            # tool definitions). Re-serialize the normalized defs into the
            # export shape so the importer's single tool path records them.
            doc["visibleTools"] = [{"functionDeclarations": [
                {"name": tool.get("name"), "description": tool.get("description", ""),
                 "parameters": tool.get("input_schema") or {"type": "object"}}
                for tool in visible_tools
                if isinstance(tool, dict) and tool.get("name")]}]
        start_metadata = {"game_id": game_id, "run_id": companion_run_id,
                          "predecessor_trajectory_id": live_trajectory_id}
        start_metadata.update(identity_metadata(extra_metadata or {}))
        collector = Collector.start(
            start_metadata,
            task_ref=live_task_ref, environment_ref=live_environment_ref,
            path=out_path, register=register)
        # the model that produced the journal's turns, recorded at the metadata
        # level the training side expects (schema: metadata.model)
        collector.trajectory["metadata"]["model"] = _doc_model(
            doc, doc.get("conversationRecord") or {})
        if visible_tools:
            collector.record_event("system", "runtime", producer="recover_companion",
                audit_code="tools_from_exit_autosave",
                content=[content_block(
                    "json",
                    data={"definitions": len(doc["visibleTools"][0]["functionDeclarations"]),
                          "source": "exit autosave harvested by the caller; the journal carries none"},
                    visibility="collector_only")])
        if system_prompt:
            collector.record_event("system", "runtime", producer="recover_companion",
                audit_code="system_prompt_from_exit_autosave",
                content=[content_block(
                    "json",
                    data={"source": "exit autosave harvested by the caller; the journal carries none"},
                    visibility="collector_only")])
        elif system_ref:
            collector.record_event("system", "runtime", producer="recover_companion",
                audit_code="system_prompt_static_ref_only",
                content=[content_block(
                    "json",
                    data={"ref": system_ref,
                          "note": "exit autosave carries the static core prompt as a hash "
                                  "reference only; the text lives in the CLI binary"},
                    visibility="collector_only")])
        # The journal carries no file-change facts: the export view inherits
        # the SAME session's recorded workspace history from the live view, so
        # training on *_export.json never loses the code-change process.
        if live_versions:
            collector.trajectory["workspace"]["file_versions"] = [dict(v) for v in live_versions]
            collector.record_event("system", "runtime", producer="recover_companion",
                audit_code="workspace_inherited_from_live_view",
                content=[content_block("json",
                    data={"file_versions": len(live_versions),
                          "source": "live view of the same session (predecessor link)"},
                    visibility="collector_only")])
            collector.writer.checkpoint()
        data = journal_path.read_bytes()
        journal_attachment = {
            "type": "recovered_session_journal",
            "uri": journal_uri,
            "sha256": hashlib.sha256(data).hexdigest(),
            "mime_type": "application/x-ndjson",
            "size_bytes": len(data),
        }
        if archived:
            journal_attachment["original_uri"] = portable_uri(str(journal_path))
        collector.record_attachment(journal_attachment)
        if not archived:
            # an unarchivable external path is recorded but never presented
            # as recoverable
            collector.record_event("system", "runtime", producer="recover_companion",
                audit_code="raw_journal_not_portable",
                content=[content_block("json", data={"status": "missing",
                          "uri": journal_uri}, visibility="collector_only")])
        report = AutosaveSessionImporter(collector).update(
            doc, source_uri=journal_uri, source_format="codely-journal")
        if live_verification:
            # The live view's verification refs point at ITS event ids; this
            # trajectory's events are journal-derived and numbered
            # independently, so a copied ref is a dangling pointer. Each
            # verification observation is therefore RE-RECORDED here — a new
            # verification event in this view's id space, bound to the same
            # tool call — and the ref is rebuilt from the live ref's own
            # facts. A ref whose live event is missing or not a verification
            # observation is dropped with its facts kept in the audit, never
            # re-pointed at an unrelated event.
            live_events = {e.get("event_id"): e for e in live_doc.get("events") or []}
            # live visible_event_ids are live-view ids: they survive only when
            # they resolve through the stable tool_call_id into THIS view's
            # events; the rest are dropped rather than guessed.
            companion_by_call: dict[Any, str] = {}
            for event in collector.trajectory["events"]:
                call_id = event.get("tool_call_id")
                if call_id and call_id not in companion_by_call:
                    companion_by_call[call_id] = event["event_id"]
            re_recorded = 0
            dropped: list[dict] = []
            for ref in live_verification:
                live_event = live_events.get(ref.get("verification_event_id")) or {}
                blocks = live_event.get("content") or [{}]
                payload = blocks[0].get("data") if isinstance(blocks[0], dict) else None
                kind = payload.get("verification_kind") if isinstance(payload, dict) else None
                if not kind:
                    dropped.append(ref)
                    continue
                results = ref.get("results") if isinstance(ref.get("results"), dict) \
                    else {k: v for k, v in payload.items() if k != "verification_kind"}
                visible = [companion_by_call[(live_events.get(vid) or {}).get("tool_call_id")]
                           for vid in ref.get("visible_event_ids") or []
                           if (live_events.get(vid) or {}).get("tool_call_id")
                           in companion_by_call]
                collector.record_verification(
                    kind, results,
                    producer=live_event.get("producer") or "runner",
                    state_ref=ref.get("state_ref"), suite_ref=ref.get("suite_ref"),
                    environment_ref=ref.get("environment_ref"), origin=ref.get("origin"),
                    integrity=ref.get("integrity"), visible_event_ids=visible,
                    tool_call_id=live_event.get("tool_call_id"),
                    command=ref.get("command"), exit_code=ref.get("exit_code"),
                    workspace_version_ids=ref.get("workspace_version_ids"),
                    output_ref=ref.get("output_ref"))
                re_recorded += 1
            collector.record_event("system", "runtime", producer="recover_companion",
                audit_code="verification_inherited_from_live_view",
                content=[content_block("json",
                    data={"re_recorded": re_recorded, "dropped": dropped,
                          "source": "live view of the same session (predecessor link)"},
                    visibility="collector_only")])
            collector.writer.checkpoint()
        collector.trajectory["derived_views"]["tools_used"] = \
            derive_tools_used(collector.trajectory["events"])
        sanitized = sanitize_trajectory_paths(collector.trajectory, workspace=workspace)
        if sanitized:
            collector.record_event("system", "runtime", producer="recover_companion",
                audit_code="paths_sanitized_for_portability",
                content=[content_block("json", data={"fields": sanitized},
                                       visibility="collector_only")])
        collector.finish({"ok": True, "status": "recovered_from_session_journal",
                          "source": "cli live-session journal (unclean exit recovery)"},
                         completeness="partial")
        trajectory = json.loads(out_path.read_text(encoding="utf-8"))
        counts = {
            "events": len(trajectory["events"]),
            "requests": len(trajectory["requests"]),
            "tool_calls": sum(len(e.get("tool_calls", []) or []) for e in trajectory["events"]),
            "thinking": sum(1 for e in trajectory["events"] if e.get("raw_reasoning")),
        }

        link = Collector.resume(live_trajectory_path)
        already_linked = any(a.get("trajectory_id") == companion_id
                             for a in link.trajectory.get("attachments", []))
        if not already_linked:
            link.record_attachment({
                "type": "companion_export_trajectory",
                "trajectory_id": companion_id,
                "uri": portable_uri(str(out_path)),
                "recovered_from": "cli live-session journal (export never written)",
            })
            # The cross-link must not rewrite the live view's own facts: keep
            # its recorded result and completeness exactly as finalized.
            link.finish(link.trajectory.get("result") or {"ok": None, "status": "relinked"},
                        completeness=link.trajectory["metadata"].get("completeness") or "partial")

        return {"attempted": True, "ok": True, "path": str(out_path),
                "trajectory_id": companion_id, "appended_events": report["appended_events"],
                "new_requests": report["new_requests"], **counts}
    except Exception as exc:  # recovery must never break finalization
        return {"attempted": True, "ok": False, "error": f"{type(exc).__name__}: {exc}"}


def harvest_exit_tools(collector, session_id, workspace, *, autosave_dir=None,
                       autosave_pattern: str = "chat-auto-save-*.json",
                       wait_seconds: float = 0.0) -> dict[str, Any]:
    """Record the session's tool definitions into an OPEN collector.

    The live stream carries neither tool definitions nor a system prompt; the
    session's exit/periodic autosave is the only honest source for the tool
    layer the stream's calls actually used. Attribution is session-precise
    (same rule as ``harvest_exit_autosave``); a missing or foreign export
    records nothing. ``wait_seconds`` polls briefly because the exit autosave
    appears shortly after the child exits. Never raises — a tool-harvest
    failure must not break the runner's finalization.
    """
    try:
        harvested = None
        deadline = time.monotonic() + max(0.0, wait_seconds)
        while True:
            harvested = harvest_exit_autosave(session_id, workspace,
                                              autosave_dir=autosave_dir,
                                              autosave_pattern=autosave_pattern)
            if harvested is not None or time.monotonic() >= deadline:
                break
            time.sleep(0.2)
        if harvested is None:
            return {"found": False}
        definitions = _tools(harvested[1].get("visibleTools"))
        if not definitions:
            return {"found": True, "definitions": 0}
        collector.record_tools(definitions)
        collector.record_tool_set("codely_visible_tools", definitions)
        collector.record_event("system", "runtime", producer="exit_autosave_harvest",
            audit_code="tools_from_exit_autosave",
            content=[content_block("json",
                data={"definitions": len(definitions),
                      "source": "exit autosave; the live stream carries none"},
                visibility="collector_only")])
        return {"found": True, "definitions": len(definitions)}
    except Exception as exc:  # never break the runner's finalization
        return {"found": False, "error": f"{type(exc).__name__}: {exc}"}


def attempt_run_recovery(state: dict, raw_dir: str | Path, provider: str,
                         live_trajectory_path: str | Path,
                         *, journal_root: Path | None = None) -> dict[str, Any]:
    """Runner finalization hook: journal harvest for the requests-view companion.

    Runs on every codely finalize — a clean exit needs the request-boundary
    export view just as much as an interrupted one (the stream alone never
    carries request boundaries). The child's exit/periodic autosave, when it
    carries THIS session's export, contributes the tool definitions and the
    system prompt the journal lacks. Never raises; the outcome is recorded
    into run_meta so the recovery is auditable from the run artifacts alone.
    """
    try:
        game_id = str(state.get("game_id") or "")
        run_id = str(state.get("run_id") or "")
        if not game_id or not run_id:
            return {"attempted": True, "ok": False, "reason": "missing_game_or_run_id"}
        session_id = session_id_from_raw_stream(raw_dir, provider)
        if not session_id:
            return {"attempted": True, "ok": False, "reason": "session_id_not_in_stream"}
        journal = find_session_journal(session_id, root=journal_root)
        if journal is None:
            return {"attempted": True, "ok": False, "reason": "journal_not_found",
                    "session_id": session_id}
        visible_tools = None
        system_prompt = None
        system_ref = None
        harvested = harvest_exit_autosave(
            session_id, state.get("workspace"),
            autosave_dir=state.get("autosave_dir"),
            autosave_pattern=state.get("autosave_pattern") or "chat-auto-save-*.json")
        if harvested is not None:
            _, autosave_doc = harvested
            definitions = _tools(autosave_doc.get("visibleTools"))
            if definitions:
                visible_tools = definitions
            system_prompt = _autosave_system_prompt(autosave_doc)
            if not system_prompt:
                # verified CLI shape: empty dynamic sections mean the export
                # carries the core prompt as a hash reference only
                system_ref = _autosave_system_ref(autosave_doc)
        outcome = recover_companion(
            journal_path=journal, game_id=game_id, run_id=run_id,
            live_trajectory_id=make_trajectory_id(game_id, run_id),
            live_trajectory_path=live_trajectory_path,
            visible_tools=visible_tools, system_prompt=system_prompt,
            system_ref=system_ref,
            extra_metadata=identity_metadata(state),
            register=bool(state.get("register", True)),
            workspace=state.get("workspace"))
        if visible_tools or system_prompt or system_ref:
            outcome["autosave_harvested"] = {
                "tools": len(visible_tools or []),
                "system_prompt": bool(system_prompt),
                "system_static_ref": bool(system_ref)}
        return outcome
    except Exception as exc:
        return {"attempted": True, "ok": False, "error": f"{type(exc).__name__}: {exc}"}
