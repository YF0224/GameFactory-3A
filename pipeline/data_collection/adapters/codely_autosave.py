"""Codely autosave importer for benchmark trajectory collection plan."""
from __future__ import annotations
from .codely_reasoning import reasoning_record
import hashlib, json
from pathlib import Path
from typing import Any
from pipeline.common.paths import REPO_ROOT
from ..core.artifact_store import ArtifactStore
from ..core.collector import Collector, content_block
from ..runtime.environment import capture_environment

SCHEMA_VERSION = "gamefactory3a.unity-trajectory.v5"


def portable_uri(uri: str | None, *, workspace: str | None = None) -> str | None:
    """Stable substitute prefixes for collector-side references (schema §8.2):
    $WORKSPACE for the session workspace, $HOME for the user home, $REPO_ROOT
    for the repository, so trajectory URIs stay machine-portable. Raw file
    CONTENT keeps whatever it contains — only the references are substituted,
    and the archived originals still resolve on the collecting machine."""
    if not uri:
        return uri
    if workspace:
        base = str(workspace).rstrip("/")
        if uri == base or uri.startswith(base + "/"):
            return "$WORKSPACE" + uri[len(base):]
    home = str(Path.home())
    if uri == home or uri.startswith(home + "/"):
        return "$HOME" + uri[len(home):]
    repo = str(REPO_ROOT)
    if uri == repo or uri.startswith(repo + "/"):
        return "$REPO_ROOT" + uri[len(repo):]
    return uri


def derive_tools_used(events: list) -> list[dict]:
    """The names the agent actually CALLED, with counts, derived from the
    canonical event log — not from any importer-side counter (observer-recorded
    calls bypass those). ``tools`` stays the set of available definitions;
    ``derived_views.tools_used`` is this, the actually-invoked subset."""
    used: dict[str, int] = {}
    for event in events or []:
        for call in event.get("tool_calls") or []:
            name = str(call.get("name") or "?")
            used[name] = used.get(name, 0) + 1
    return [{"name": name, "calls": count} for name, count in
            sorted(used.items(), key=lambda item: (-item[1], item[0]))]


def _substitute_leaves(value, substitute):
    """Apply the substitution to STRING LEAVES only, preserving structure:
    dict keys, JSON shape and non-string values are never touched."""
    if isinstance(value, str):
        return substitute(value)
    if isinstance(value, dict):
        return {key: _substitute_leaves(item, substitute) for key, item in value.items()}
    if isinstance(value, list):
        return [_substitute_leaves(item, substitute) for item in value]
    return value


def sanitize_trajectory_paths(trajectory: dict, *, workspace: str | None = None) -> int:
    """Structured portability pass (schema §8.2) over the CANONICAL trajectory.

    Whitelisted CONTENT fields only — string leaves inside tool_call arguments
    and content block data (covers tool-result payloads and message texts).
    URI reference fields are deliberately NOT rewritten here: they are made
    portable at creation (portable_uri) or point at the content-addressed
    store (repo-relative or the store's own $EXTERNAL convention), and
    rewriting store URIs would break artifact resolution. Substitution is
    prefix-ordered by specificity ($WORKSPACE, then $HOME, then $REPO_ROOT)
    and is deterministic; the raw artifacts keep their original bytes in the
    run archive, so nothing is lost. A global string replace is deliberately
    NOT used — it would break serialized shell commands, JSON and file
    content. Returns the number of substituted fields."""
    def substitute(text: str) -> str:
        out = text
        if workspace:
            out = out.replace(str(workspace).rstrip("/"), "$WORKSPACE")
        out = out.replace(str(Path.home()), "$HOME")
        out = out.replace(str(REPO_ROOT), "$REPO_ROOT")
        return out

    count = 0
    for event in trajectory.get("events") or []:
        for call in event.get("tool_calls") or []:
            if isinstance(call, dict) and call.get("arguments") is not None:
                call["arguments"] = _substitute_leaves(call["arguments"], substitute)
                count += 1
        for block in event.get("content") or []:
            if isinstance(block, dict) and block.get("data") is not None:
                block["data"] = _substitute_leaves(block["data"], substitute)
                count += 1
    return count

#: How a request's inputs were rebuilt. The legacy value
#: ``event_order_inference_v1`` (earlier importers, sliding local window)
#: stays readable on old files; new writes use the cumulative session-history
#: reconstruction below, which is explicitly quality-marked.
INPUT_RECONSTRUCTION = "session_history_reconstruction_v1"

#: Request quality markers (additive v5 request keys). ``boundary`` answers
#: "is this record really ONE model call?", ``context`` answers "are
#: input_event_ids the complete prompt?". A reliable boundary never implies a
#: complete context — both are marked separately, each with its evidence:
#: boundary_basis (client round id / journal message grouping / client-history
#: entry — all reconstructed; ``observed`` is reserved for provider-side
#: evidence such as a real provider request id or request snapshot, which no
#: importer fabricates) and context_basis (session-history reconstruction or
#: a real request snapshot; no importer produces snapshots today).
BOUNDARY_VALUES = ("observed", "reconstructed", "unknown")
CONTEXT_VALUES = ("complete", "partial", "unknown")

#: Response-end status: distinct from tool execution. A tool result only
#: proves the tool ran; it never proves the streamed response finished. The
#: only response-end evidence used is the journal's per-message ``committed``
#: flag — an interrupted stream keeps its received content and is marked
#: partial; without evidence the status stays unknown, never guessed.
RESPONSE_STATUSES = ("complete", "partial", "unknown")

def _content(value: Any, store: ArtifactStore | None, limit: int, visibility: str = "agent_received") -> dict[str, Any]:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    is_json = not isinstance(value, str)
    base = {"type":"json" if is_json else "text", "data":value if is_json and len(text) <= limit else text, "uri":None, "mime_type":"application/json" if is_json else "text/plain", "sha256":None, "visibility":visibility}
    if len(text) <= limit or store is None: return base
    saved = store.put(text, ext=".txt", mime_type="text/plain")
    base.update(data=None, uri=saved["uri"], sha256=saved["sha256"])
    return base

def _texts(parts): return [p["text"] for p in parts if isinstance(p, dict) and isinstance(p.get("text"), str) and not p.get("thought")]
def _tools(raw):
    out=[]
    for group in raw or []:
        for x in group.get("functionDeclarations", []) if isinstance(group,dict) else []:
            if isinstance(x,dict) and x.get("name"):
                out.append({"name":x["name"],"description":x.get("description", ""),"input_schema":x.get("parameters", {"type":"object"})})
    return out

def _snapshot_versions(doc, workspace_root=None):
    versions=[]
    for i,s in enumerate(doc.get("conversationRecord",{}).get("fileHistorySnapshots",[]) or [],1):
        backups=s.get("trackedFileBackups") or {}
        for path, value in backups.items():
            if isinstance(value,dict):
                content=value.get("content", value.get("text"))
                if content is None:
                    content = None
            else: content=value
            if content is None:
                versions.append({"version_id":f"file_{i:06d}","path":str(path),"operation":"modify","parent_version_id":versions[-1]["version_id"] if versions else None,"snapshot_id":s.get("id"),"capture_status":"partial","capture_reason":"Codely autosave contains backupName/backupTime only; backup content is not embedded"})
                continue
            raw=str(content).encode(); versions.append({"version_id":f"file_{i:06d}","path":str(path),"operation":"modify","parent_version_id":versions[-1]["version_id"] if versions else None,"sha256":hashlib.sha256(raw).hexdigest(),"size_bytes":len(raw),"snapshot_id":s.get("id"),"capture_status":"complete"})
    return versions

# ── shared turn parsing (one-shot convert and live importer use the same facts) ──

def _turn(msg: dict, ui_msg: dict) -> dict[str, Any]:
    """Normalize one clientHistory (API-level) entry into turn facts."""
    ts = msg.get("timestamp") or ui_msg.get("timestamp")
    parts = msg.get("parts", msg.get("content", []))
    parts = parts if isinstance(parts, list) else [{"text": parts}]
    role = msg.get("role", msg.get("type"))
    source = {"gemini":"assistant","model":"assistant","user":"user","developer":"developer"}.get(role, role)
    calls, tool_results = [], []
    for p in parts:
        fc = p.get("functionCall")
        if isinstance(fc, dict):
            # the raw id is preserved separately: the namespaced tool_call_id
            # keeps cross-session ids from colliding, the raw id keeps the
            # provider-issued value recoverable.
            calls.append({"tool_call_id":fc.get("id"), "raw_tool_call_id":fc.get("id"),
                          "name":fc.get("name"), "arguments":fc.get("args", {})})
        fr = p.get("functionResponse")
        if isinstance(fr, dict):
            output = fr.get("response", fr)
            tool_results.append({"tool_call_id":fr.get("id"), "raw_tool_call_id":fr.get("id"),
                "status":"error" if isinstance(output,dict) and output.get("error") else "success",
                "output":output})
    return {"source":source, "ts":ts, "texts":_texts(parts), "calls":calls,
            "tool_results":tool_results, "model":msg.get("model"),
            # apiRoundId is the export's client-side round id (verified in a
            # real session: 47/47 equal the client journal's model-message
            # ids). It groups one round's events and never impersonates a
            # provider request id, so it is never written into
            # provider_request_id.
            "api_round_id":msg.get("apiRoundId"),
            "message_id":msg.get("id"),
            # response-end evidence (journal `committed`): True = the streamed
            # response finished, False = interrupted mid-stream. Absent on
            # clientHistory rounds -> unknown; tool results never imply it.
            "committed":msg.get("committed"),
            # raw provenance carried by journal-derived entries
            "source_ref":msg.get("source"),
            "thoughts":msg.get("thoughts") or ui_msg.get("thoughts") or []}

def _turn_list(doc: dict) -> list[dict[str, Any]]:
    """Ordered turns from the API-level clientHistory, UI messages as fallback.

    The API-level history is the canonical interaction record, but it never
    carries what the UI layer has: ``thoughts`` (reasoning segments) and
    message timestamps. Pair each API message with its UI counterpart by turn
    kind and order — model rounds match gemini UI messages 1:1 and real user
    messages match user UI messages 1:1 (verified on a real export: 182/182
    model pairs, 170/170 tool-call-id matches, 21/21 user pairs). Tool-result
    rounds have no UI counterpart. The previous single cumulative index walked
    both layers at different densities (373 API vs 203 UI messages in one
    real export), misfiling or silently dropping thinking.
    """
    api_history = doc.get("clientHistory") or []
    ui_history = (doc.get("conversationRecord") or {}).get("messages") or []
    if not api_history:
        # UI-only export: the UI message is both the turn and its own
        # counterpart; thoughts/timestamps live on it directly.
        return [_turn(msg, msg) | {"position": index}
                for index, msg in enumerate(ui_history)]
    ui_user = [m for m in ui_history if (m.get("type") or m.get("role")) == "user"]
    ui_model = [m for m in ui_history if (m.get("type") or m.get("role")) in ("gemini", "model")]
    turns = []
    user_i = model_i = 0
    for position, msg in enumerate(api_history):
        role = msg.get("role") or msg.get("type")
        ui_msg = {}
        if role in ("model", "gemini"):
            ui_msg = ui_model[model_i] if model_i < len(ui_model) else {}
            model_i += 1
        elif role == "user":
            parts = msg.get("parts", msg.get("content", []))
            parts = parts if isinstance(parts, list) else [{"text": parts}]
            is_tool_round = any(isinstance(p, dict) and p.get("functionResponse") for p in parts)
            if not is_tool_round:
                ui_msg = ui_user[user_i] if user_i < len(ui_user) else {}
                user_i += 1
        turns.append(_turn(msg, ui_msg) | {"position": position})
    return turns

def _doc_model(doc: dict, cr: dict) -> str:
    # clientHistory is the API-level record; prefixContext.model is the session
    # record; conversationRecord.messages is the UI-level fallback.
    return next((m.get("model") for m in (doc.get("clientHistory") or []) if m.get("model")), None) \
        or (doc.get("prefixContext") or {}).get("model") \
        or next((m.get("model") for m in cr.get("messages", []) if m.get("model")), None) or "codely"

def _digest(turns: list) -> str:
    return hashlib.sha256(json.dumps(turns, ensure_ascii=False, default=str, sort_keys=True).encode("utf-8")).hexdigest()


# ── request boundary & input semantics (collection plan §4.3) ──────────────

def request_markers(turn: dict, *, system_prompt: bool, history_verification: str,
                    response_committed: bool | None = None) -> dict:
    """Boundary/context/response markers plus evidence for one model round.

    ``apiRoundId`` is the export's client-side round id — verified against a
    real session's journal: 47/47 apiRoundIds are exactly the client journal's
    model-message ids, so they anchor response grouping but are NOT provider
    request ids and never enter provider_request_id. The round id therefore
    supports a *reconstructed* boundary (a client-recorded round), while
    ``observed`` is reserved for provider-side evidence (a real provider
    request id or request snapshot) that no importer fabricates.
    ``response_committed`` is response-end evidence (journal ``committed``):
    it is the ONLY source for response_status — a later tool result never
    retroactively completes a response.
    """
    api_round_id = turn.get("api_round_id")
    message_id = turn.get("message_id")
    if api_round_id:
        boundary, basis = "reconstructed", {"type": "client_round_id", "round_id": api_round_id}
    elif message_id:
        boundary, basis = "reconstructed", {"type": "journal_message", "message_id": message_id}
    else:
        boundary, basis = "reconstructed", {"type": "client_history_entry"}
    markers: dict[str, Any] = {
        "input_reconstruction": INPUT_RECONSTRUCTION,
        "boundary": boundary,
        "context": "partial",
        "boundary_basis": basis,
        "context_basis": {"type": "session_history_reconstruction",
                          "system_prompt": bool(system_prompt),
                          "history_verification": history_verification},
        "response_status": "unknown",
    }
    if response_committed is not None:
        markers["response_status"] = "complete" if response_committed else "partial"
        markers["response_basis"] = {"type": "journal_committed", "committed": bool(response_committed)}
    return markers


def _event_source_ref(turn: dict, fallback_uri: str | None,
                      fallback_format: str = "codely-autosave") -> dict[str, Any]:
    """Per-event raw provenance: source file, positions, source ids.

    Journal-derived turns carry their own ref (uri + every revision seq —
    merged deltas keep the whole source range). Turns without one fall back
    to the import source the caller named (autosave file + clientHistory
    position, or the journal when the doc itself is journal-derived), so a
    later conversion fix can regenerate the event without re-running.
    """
    ref = turn.get("source_ref")
    if isinstance(ref, dict):
        return dict(ref)
    position = turn.get("position")
    return {"uri": fallback_uri, "format": fallback_format,
            "positions": [position] if position is not None else []}


class RequestAssembler:
    """Assemble request records without conflating three distinct records.

    A model request, a tool call/result pair, and a session-history
    reconstruction are different facts: an assistant event alone never proves
    a model call. Assistant events confirmed to belong to one response (same
    round key: export apiRoundId or journal message id) merge into ONE
    request's response_event_ids — original events are never merged or
    rewritten. Inputs are the explicitly marked session-history reconstruction:
    the system prompt (when its source and scope are known) plus every
    conversation event recorded before the round — never a silently truncated
    local window, and never this round's own response.
    """

    def __init__(self, issue_request):
        # issue_request(input_ids, response_ids, fields, markers) -> request dict
        self._issue_request = issue_request
        self._context: list[str] = []   # conversation events later rounds saw
        self._pending: dict | None = None  # {"key", "request", "response_ids"}

    def note(self, event_id: str) -> None:
        """A non-assistant conversation event (system/user/developer/tool
        result): becomes part of later rounds' reconstructed input."""
        self._close_round()
        self._context.append(event_id)

    def response(self, event_ids: list[str], *, key, fields: dict, markers: dict) -> tuple[dict, bool]:
        """Assistant events of one turn. A same round key extends the open
        response instead of opening a second request; returns (request, created)."""
        if self._pending is not None and key is not None and self._pending["key"] == key:
            self._pending["response_ids"].extend(event_ids)
            request = self._pending["request"]
            request["response_event_ids"] = list(self._pending["response_ids"])
            return request, False
        self._close_round()
        request = self._issue_request(list(self._context), list(event_ids), dict(fields), dict(markers))
        self._pending = {"key": key, "request": request, "response_ids": list(event_ids)}
        return request, True

    def observation(self, event_id: str, *, key) -> None:
        """A reasoning-only assistant event: never a request boundary and never
        model input. When the round key proves it extends the open response it
        is appended to that response's references; otherwise it stays an
        independent observation no request claims."""
        if self._pending is not None and key is not None and self._pending["key"] == key:
            self._pending["response_ids"].append(event_id)
            self._pending["request"]["response_event_ids"] = list(self._pending["response_ids"])

    def _close_round(self) -> None:
        # The round's own response enters history for subsequent rounds only
        # after the round closes; it is never part of its own input.
        if self._pending is not None:
            self._context.extend(self._pending["response_ids"])
            self._pending = None

    def reset(self) -> None:
        """A different session is a different model context: nothing carries
        over, so a later round can never inherit another session's history."""
        self._close_round()
        self._context = []

# ── one-shot import (same boundary/input semantics as the live importer) ──

def convert(autosave: Path, metadata: dict[str,Any]|None=None, *, store=None, max_inline_chars=8192, workspace=None, engine=None, skip_environment=False):
    doc=json.loads(autosave.read_text(encoding="utf-8")); cr=doc.get("conversationRecord",{})
    md=dict(metadata or {})
    explicit_env = md.pop("environment_ref", None)
    workspace = workspace or md.pop("workspace", None)  # detection only; never stored (§8.2)
    engine = engine or md.get("engine") or None
    md.setdefault("game_id",None); md.setdefault("run_id",None)
    md.setdefault("run_kind","project_run" if (md["game_id"] and md["run_id"]) else "standalone_training_task")
    if md["game_id"] and md["run_id"]: md.setdefault("trajectory_id",f"{md['game_id']}__{md['run_id']}")
    else: md.setdefault("trajectory_id",doc.get("tag",autosave.stem))
    model = _doc_model(doc, cr)
    md.update({"collector_version":"codely-autosave-importer.v3","revision":1,"session_id":cr.get("sessionId"),"harness":"codely","codely_version":doc.get("codelyVersion"),"project_hash":cr.get("projectHash"),"completeness":"partial","model":model})
    events: list[dict[str, Any]] = []
    requests: list[dict[str, Any]] = []
    system = doc.get("prefixContext", {}).get("systemPrompt", {}).get("dynamic", {}).get("joinedText")
    system_present = bool(system)

    def _issue_request(input_ids: list[str], response_ids: list[str],
                       fields: dict, markers: dict) -> dict[str, Any]:
        request: dict[str, Any] = {
            "request_id": f"req_{len(requests) + 1:06d}",
            "input_event_ids": input_ids,
            "response_event_ids": response_ids,
            "tool_set_id": "codely_visible_tools",
        }
        request.update(fields)
        request.update(markers)
        requests.append(request)
        return request

    assembler = RequestAssembler(_issue_request)
    if system:
        eid = f"evt_{len(events) + 1:06d}"
        events.append({"event_id": eid, "source": "system", "kind": "message",
                       "content": [_content(system, store, max_inline_chars, "agent_received")],
                       "source_refs": {"uri": str(autosave), "format": "codely-autosave",
                                       "positions": [], "source_ids": ["prefixContext.systemPrompt"]}})
        # The session system prompt has a clear source and scope (schema §5.1):
        # it enters the reconstructed input of every round that follows.
        assembler.note(eid)
    for turn in _turn_list(doc):
        source_refs = _event_source_ref(turn, str(autosave))
        if turn["source"] == "user" and turn["tool_results"]:
            for tr in turn["tool_results"]:
                eid = f"evt_{len(events) + 1:06d}"
                e = {"event_id": eid, "source": "tool", "kind": "tool_result",
                     "tool_call_id": tr["tool_call_id"], "raw_tool_call_id": tr["raw_tool_call_id"],
                     "status": tr["status"],
                     "content": [_content(tr["output"], store, max_inline_chars)],
                     "source_refs": source_refs}
                if turn["ts"]: e["ts"] = turn["ts"]
                events.append(e)
                assembler.note(eid)
            # A Codely function-response turn can also carry ordinary user
            # text; retain it after the tool results in the same turn.
            if not turn["texts"]: continue
        texts = turn["texts"]; calls = turn["calls"]
        if not texts and not calls and not turn["thoughts"]: continue
        eid = f"evt_{len(events) + 1:06d}"
        if turn["source"] == "assistant":
            eids: list[str] = []
            if texts or turn["thoughts"]:
                e = {"event_id": eid, "source": "assistant", "kind": "message",
                     "content": [_content(x, store, max_inline_chars) for x in texts],
                     "source_refs": source_refs}
                if turn["thoughts"]:
                    e["raw_reasoning"] = reasoning_record(turn["thoughts"])
                if turn["ts"]: e["ts"] = turn["ts"]
                events.append(e)
                eids.append(e["event_id"])
            # Each tool call stays its own event (facts are never merged into
            # one synthetic event); one confirmed response references them all.
            for call in calls:
                cid = f"evt_{len(events) + 1:06d}"
                e = {"event_id": cid, "source": "assistant", "kind": "tool_call",
                     "content": [], "tool_calls": [call], "source_refs": source_refs}
                if turn["ts"]: e["ts"] = turn["ts"]
                events.append(e)
                eids.append(cid)
            key = turn.get("api_round_id") or turn.get("message_id")
            if texts or calls:
                assembler.response(eids, key=key,
                    fields={"model": turn["model"] if turn["model"] is not None else md.get("model", "codely"),
                            "provider": "codely", "session_id": md.get("session_id")},
                    markers=request_markers(turn, system_prompt=system_present,
                                            history_verification="none",
                                            response_committed=turn.get("committed")))
            else:
                # reasoning is neither a request boundary nor model input
                assembler.observation(eids[0], key=key)
            continue
        e = {"event_id": eid, "source": turn["source"], "kind": "message",
             "content": [_content(x, store, max_inline_chars) for x in texts],
             "source_refs": source_refs}
        if turn["thoughts"]:
            e["raw_reasoning"] = reasoning_record(turn["thoughts"])
        if turn["ts"]: e["ts"] = turn["ts"]
        events.append(e)
        assembler.note(e["event_id"])
    environment_ref = explicit_env if explicit_env is not None else (
        {} if skip_environment else capture_environment(agent="codely", agent_version=doc.get("codelyVersion"),
            model=model, engine=engine, workspace=workspace, artifact_store=store))
    used: dict[str,int] = {}
    for e in events:
        for c in e.get("tool_calls",[]) or []:
            name=str(c.get("name") or "?"); used[name]=used.get(name,0)+1
    tools_used=[{"name":n,"calls":c} for n,c in sorted(used.items(), key=lambda kv:(-kv[1],kv[0]))]
    # Store the raw session once, content-addressed, so the attachment resolves
    # without a machine-absolute path (schema §8.2); without a store the
    # original path is kept as the only available reference.
    if store is not None:
        stored_session = store.put_file(autosave, mime_type="application/json")
        raw_session = {"type":"raw_session","uri":stored_session["uri"],"sha256":stored_session["sha256"],"mime_type":stored_session["mime_type"],"size_bytes":stored_session.get("size_bytes")}
    else:
        raw_session = {"type":"raw_session","uri":str(autosave),"sha256":hashlib.sha256(autosave.read_bytes()).hexdigest(),"mime_type":"application/json"}
    return {"schema_version":SCHEMA_VERSION,"metadata":md,"task_ref":metadata.get("task_ref") if metadata else None,"environment_ref":environment_ref,"tools":_tools(doc.get("visibleTools")),"tool_sets":{"codely_visible_tools":_tools(doc.get("visibleTools"))},"events":events,"requests":requests,"workspace":{"file_versions":_snapshot_versions(doc)},"verification_refs":[],"asset_generations":[],"attachments":[raw_session],"training":{"status":"pending","policy_version":"codely-import.v1","group_id":md.get("trajectory_id")},"result":{},"derived_views":{"tools_used":tools_used}}

# ── live incremental import into one open Collector ──

class AutosaveSessionImporter:
    """Incrementally apply a growing Codely autosave to one open Collector.

    Codely rewrites the autosave as the session grows; within one session the
    clientHistory is expected to be append-only. Applied turns are never
    re-applied: the importer advances by turn count and verifies the applied
    prefix digest, auditing honestly when the provider rewrites history
    (compaction). Canonical events already written stay immutable; a mutation
    is recorded, never patched. Requests share convert()'s boundary and input
    semantics via :class:`RequestAssembler` — one request per confirmed model
    round (marked, evidence attached), inputs as the explicitly marked
    session-history reconstruction; the system prompt enters every following
    round's inputs (schema §5.1) when the export carries one. The importer
    never opens or writes the trajectory file itself.
    """

    def __init__(self, collector: Collector, *, max_inline_chars: int = 8192):
        self.collector = collector
        self.store = collector.artifact_store
        self.max_inline_chars = max_inline_chars
        # Import cursors are per session: a new session starts at turn 0,
        # returning to a previously seen session resumes its cursor
        # (flip-flopping exports never re-import old turns), and a rewritten
        # history inside one session invalidates its cursor instead of
        # silently skipping the new calls after it.
        self._sessions: dict[Any, dict[str, Any]] = {}
        self._current_session: Any = None
        self._assembler = RequestAssembler(self._issue_request)
        self._has_system = False
        self._source_uri: str | None = None
        self._system_sessions: set = set()
        self._tool_set_id: str | None = None
        self._tools_hash: str | None = None
        self._tools_version = 0
        self._used: dict[str, int] = {}

    def _issue_request(self, input_ids: list[str], response_ids: list[str],
                       fields: dict, markers: dict) -> dict:
        self.collector.record_request(input_ids, response_ids, **fields, **markers)
        return self.collector.trajectory["requests"][-1]

    def _cid(self, session_id: Any, raw: Any):
        """Namespace call ids per session so ids cannot collide across sessions."""
        if raw is None:
            return None
        return f"{session_id}:{raw}" if session_id else str(raw)

    def _persist_snapshot(self, doc: dict) -> dict | None:
        """Keep a mutated export as an attachment; facts are never silently lost."""
        if self.store is None:
            return None
        payload = json.dumps(doc, ensure_ascii=False, indent=2, default=str)
        stored = self.store.put(payload, ext=".json", mime_type="application/json")
        attachment = {"type": "autosave_history_snapshot",
                      "uri": stored["uri"], "sha256": stored["sha256"],
                      "mime_type": stored["mime_type"],
                      "size_bytes": stored.get("size_bytes")}
        self.collector.record_attachment(attachment)
        return attachment

    def tools_used(self) -> list[dict]:
        return [{"name":n,"calls":c} for n,c in sorted(self._used.items(), key=lambda kv:(-kv[1],kv[0]))]

    def _blocks(self, values) -> list[dict]:
        return [_content(v, self.store, self.max_inline_chars, "agent_received") for v in values]

    def _audit(self, code: str, **facts) -> str:
        return self.collector.record_event("system", "runtime", producer="autosave_importer",
            audit_code=code,
            content=[content_block("json", data=dict(facts), visibility="collector_only")])

    def update(self, doc: dict, *, source_uri: str | None = None,
               source_format: str = "codely-autosave") -> dict:
        """Apply one export doc. ``source_uri`` names the raw file the doc
        was read from and ``source_format`` what that file is (autosave or
        journal), so every emitted event traces back to its true source."""
        self._source_uri = source_uri
        self._source_format = source_format
        cr = doc.get("conversationRecord") or {}
        report: dict[str, Any] = {"appended_events":0, "new_requests":0,
                                  "history_mutated":False, "session_changed":False, "audits":[]}
        session_id = cr.get("sessionId")
        if session_id != self._current_session and self._current_session is not None:
            report["session_changed"] = True
            report["audits"].append(self._audit("autosave_session_changed",
                previous=self._current_session, current=session_id))
            # A different session is a different model context: the
            # reconstructed input restarts with it and never accumulates the
            # previous session's history.
            self._assembler.reset()
            self._has_system = False
        state = self._sessions.get(session_id)
        if state is None:
            state = {"applied": 0, "prefix_digest": None,
                     "mutation_snapshotted": False, "mutation_audited": False}
            self._sessions[session_id] = state
        self._current_session = session_id
        # Tools: record the real definitions once; a change appends a new set version.
        self.import_tools(doc, report)
        # System prompt: once per session; its source (the export's
        # prefixContext) and scope (this session) are known, so it enters the
        # reconstructed input of every round that follows (schema §5.1). A
        # session without a recorded system prompt keeps the gap visible in
        # each request's context_basis instead of being fabricated.
        if session_id not in self._system_sessions:
            self._system_sessions.add(session_id)
            system = doc.get("prefixContext",{}).get("systemPrompt",{}).get("dynamic",{}).get("joinedText")
            if system:
                eid = self.collector.record_message("system", blocks=self._blocks([system]),
                                                    visibility="agent_received",
                                                    source_refs={
                                                        "uri": self._source_uri,
                                                        "format": self._source_format,
                                                        "positions": [],
                                                        "source_ids": ["prefixContext.systemPrompt"]})
                self._assembler.note(eid)
                self._has_system = True
                report["appended_events"] += 1
            else:
                # Verified CLI shape (1.0.0-release.57): with empty dynamic
                # sections the export carries the static core prompt as a
                # hash-only reference — the text lives in the CLI binary and
                # is NOT embedded, so record the reference, never fabricate
                # the prompt. _has_system stays False and every request's
                # context_basis keeps reporting no recorded system prompt.
                static_ref = doc.get("prefixContext",{}).get("systemPrompt",{}).get("static")
                if isinstance(static_ref, dict) and static_ref.get("hash"):
                    report["audits"].append(self._audit("system_prompt_static_ref_only",
                                                         session_id=session_id,
                                                         ref=static_ref))
        turns = _turn_list(doc)
        applied = state["applied"]
        if applied and _digest(turns[:applied]) != state["prefix_digest"]:
            # The provider rewrote already-applied history: the turn-count
            # cursor is no longer trustworthy. Persist the mutated export and
            # record the un-imported range explicitly — never skip silently.
            report["history_mutated"] = True
            facts = {"session_id": session_id, "applied_turns": applied,
                     "observed_turns": len(turns),
                     "unimported_turn_range": [applied, len(turns)] if len(turns) > applied else None}
            if not state["mutation_snapshotted"]:
                attachment = self._persist_snapshot(doc)
                if attachment:
                    facts["snapshot_sha256"] = attachment["sha256"]
                    state["mutation_snapshotted"] = True
                else:
                    facts["snapshot_missing_reason"] = "no_artifact_store"
            # Audit the surprise once, not once per poll: the compacted session
            # keeps failing the prefix check every cycle, and the canonical log
            # must not grow an event (and a full-file rewrite) every 2 seconds.
            # Every report still says history_mutated; the mutated content is
            # kept via the snapshot above and the final raw_session attachment.
            if not state["mutation_audited"]:
                state["mutation_audited"] = True
                report["audits"].append(self._audit("autosave_history_mutated", **facts))
            return report
        model = _doc_model(doc, cr)
        for turn in turns[applied:]:
            self._apply(turn, model, report, session_id)
            applied += 1
        state["applied"] = applied
        state["prefix_digest"] = _digest(turns[:applied]) if turns else _digest([])
        return report

    def import_tools(self, doc: dict, report: dict | None = None) -> None:
        """Record the visible tool definitions from an export doc, nothing else.

        Interactive collection sources its events from the live-session
        journal; the exit-time autosave still contributes the tool layer so
        the trajectory keeps tools/tool_sets without re-importing facts the
        journal observer has already recorded.
        """
        report = report if report is not None else {"audits": []}
        defs = _tools(doc.get("visibleTools"))
        dhash = hashlib.sha256(json.dumps(defs, sort_keys=True, default=str).encode("utf-8")).hexdigest()
        if self._tool_set_id is None:
            self._tool_set_id = "codely_visible_tools"; self._tools_hash = dhash
            self.collector.record_tools(defs)
            self.collector.record_tool_set(self._tool_set_id, defs)
        elif dhash != self._tools_hash:
            self._tools_version += 1
            self._tool_set_id = f"codely_visible_tools_v{self._tools_version}"; self._tools_hash = dhash
            self.collector.record_tool_set(self._tool_set_id, defs)
            report["audits"].append(self._audit("visible_tools_changed", tool_set_id=self._tool_set_id))

    def _apply(self, turn: dict, model: str, report: dict, session_id: Any) -> None:
        source_refs = _event_source_ref(turn, self._source_uri, self._source_format)
        if turn["source"] == "user" and turn["tool_results"]:
            for tr in turn["tool_results"]:
                extras = {"ts": turn["ts"]} if turn["ts"] else {}
                eid = self.collector.record_event("tool", "tool_result",
                    content=[_content(tr["output"], self.store, self.max_inline_chars, "agent_received")],
                    tool_call_id=self._cid(session_id, tr["tool_call_id"]),
                    raw_tool_call_id=tr["raw_tool_call_id"], status=tr["status"],
                    source_refs=source_refs, **extras)
                self._assembler.note(eid); report["appended_events"] += 1
            if not turn["texts"]:
                return
        texts, calls = turn["texts"], turn["calls"]
        if not texts and not calls and not turn["thoughts"]:
            return
        ts_kwargs: dict[str, Any] = {"ts": turn["ts"]} if turn["ts"] else {}
        if turn["source"] == "assistant":
            eids: list[str] = []
            if texts or turn["thoughts"]:
                kwargs: dict[str, Any] = dict(ts_kwargs)
                if turn["thoughts"]:
                    kwargs["raw_reasoning"] = reasoning_record(turn["thoughts"])
                eids.append(self.collector.record_event("assistant", "message",
                    content=self._blocks(texts), source_refs=source_refs, **kwargs))
                report["appended_events"] += 1
            # Each call keeps its own event; one confirmed response references
            # them all — grouping happens by reference, facts are never merged.
            for c in calls:
                eids.append(self.collector.record_event("assistant", "tool_call",
                    content=[],
                    tool_calls=[{"tool_call_id": self._cid(session_id, c.get("tool_call_id")),
                                 "raw_tool_call_id": c.get("raw_tool_call_id"),
                                 "name": c.get("name"), "arguments": c.get("arguments")}],
                    source_refs=source_refs, **ts_kwargs))
                report["appended_events"] += 1
            key = turn.get("api_round_id") or turn.get("message_id")
            if texts or calls:
                _, created = self._assembler.response(eids, key=key,
                    fields={"model": turn["model"] if turn["model"] is not None else model,
                            "tool_set_id": self._tool_set_id,
                            "provider": "codely", "session_id": session_id},
                    markers=request_markers(turn, system_prompt=self._has_system,
                                            history_verification="prefix_digest",
                                            response_committed=turn.get("committed")))
                if created:
                    report["new_requests"] += 1
            else:
                # reasoning-only observation: not a request boundary, not model
                # input; only a same-round-key response may claim it.
                self._assembler.observation(eids[0], key=key)
        else:
            kwargs: dict[str, Any] = {}
            if calls:
                kwargs["tool_calls"] = [{"tool_call_id": self._cid(session_id, c.get("tool_call_id")),
                                         "raw_tool_call_id": c.get("raw_tool_call_id"),
                                         "name": c.get("name"), "arguments": c.get("arguments")}
                                        for c in calls]
            kwargs.update(ts_kwargs)
            if turn["thoughts"]:
                kwargs["raw_reasoning"] = reasoning_record(turn["thoughts"])
            eid = self.collector.record_event(turn["source"],
                "tool_call" if calls and not texts else "message",
                content=self._blocks(texts), source_refs=source_refs, **kwargs)
            self._assembler.note(eid)
            report["appended_events"] += 1
        for c in calls:
            name = str(c.get("name") or "?")
            self._used[name] = self._used.get(name, 0) + 1


def validate(t):
    errors=[]; calls={c.get("tool_call_id") for e in t.get("events",[]) for c in e.get("tool_calls",[])}
    for i,e in enumerate(t.get("events",[])):
        if e.get("source") not in {"system","developer","user","assistant","tool"}: errors.append(f"events[{i}] invalid source")
        if e.get("kind")=="tool_result" and e.get("tool_call_id") not in calls: errors.append(f"events[{i}] unpaired tool result")
    return errors
