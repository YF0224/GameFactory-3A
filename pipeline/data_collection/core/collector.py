"""
pipeline/data_collection/collector.py

Trajectory lifecycle + raw-fact recording (collection plan §3–§4).

Format authority: ``benchmark/gamefactory3a_agent_trajectory_schema_unity.md``
(v5). This module only records facts:

* ``events[]`` is a canonical immutable log — once written, never rewritten;
* the collector never decides "this step is a repair" and never fabricates
  results from the agent's final prose;
* requests / workspace / verification_refs reference events by ID and never
  keep a second, competing copy of the facts.

Interface (collection plan §3)::

    collector = Collector.start(metadata, task_ref, environment_ref)
    collector.record_event(...)
    collector.record_request(...)
    collector.record_workspace_change(...)
    collector.record_verification(...)
    collector.record_asset_generation(...)
    collector.finish(result)

Stdlib only.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Iterable, Sequence

from pipeline.data_collection.paths import (
    collect_json_path,
    make_trajectory_id,
    rel_to_repo,
    trajectory_path,
)

from .event_writer import (
    TRAJECTORY_INDEX_SCHEMA_VERSION,
    TRAJECTORY_SCHEMA_VERSION,
    TrajectoryWriter,
    atomic_write_json,
    load_json,
    now_iso,
)

COLLECTOR_VERSION = "0.1.0"

SOURCES = ("system", "developer", "user", "assistant", "tool")
EVENT_KINDS = (
    "message",
    "tool_call",
    "tool_result",
    "verification",
    "file_change",
    "playtest",
    "runtime",
)
CONTENT_TYPES = ("text", "json", "image", "audio", "video", "file")
VISIBILITY = ("agent_visible", "agent_received", "collector_only")
OPERATIONS = ("create", "modify", "delete", "rename")
COMPLETENESS = ("complete", "partial", "interrupted")
TRAINING_STATUS = ("pending", "ready", "excluded")

#: Training-control policies (schema §10.2). ``assistant_complete_v1`` learns
#: only observed, complete-context model calls. ``assistant_reconstructed_v1``
#: explicitly also admits history-rebuilt request views (reconstructed
#: boundary, partial context) whose response provably finished — consumed
#: only by the loader's reconstruction mode, never the precise SFT set.
TRAINING_POLICIES = ("assistant_complete_v1", "assistant_reconstructed_v1")

#: Run-identity metadata (envelope requirements): optional, passed through
#: verbatim when the harness knows them; absence stays absence — identity is
#: never invented from filesystem state or guesses.
IDENTITY_KEYS = (
    "case_id",
    "task_kind",
    "task_id",
    "episode_id",
    "attempt_id",
    "parent_attempt_id",
    "repair_attempt",
    "phase",
)


def identity_metadata(source: dict) -> dict:
    """Pick the identity keys that actually carry values from ``source``.

    Idempotent over already-lifted metadata: the runner passes the lifted
    dict through ``state`` into the companion recovery, so both the CLI form
    (``trigger_evidence``) and the metadata form
    (``trigger_evidence_ids``) survive the round trip.
    """
    metadata = {key: source[key] for key in IDENTITY_KEYS if source.get(key) is not None}
    trigger = source.get("trigger_evidence") or source.get("trigger_evidence_ids")
    # Repair provenance (huibao §3.4): an improve/repair attempt names the
    # verification evidence that triggered it; a source-less regeneration is
    # a new write, never a disguised repair.
    if trigger:
        metadata["trigger_evidence_ids"] = list(trigger)
    return metadata


def add_identity_arguments(parser: Any) -> None:
    """Standard run-identity flags shared by every collection CLI.

    Values are optional; ``identity_metadata(vars(args))`` lifts the ones that
    were actually provided into trajectory metadata.
    """
    parser.add_argument("--case-id")
    parser.add_argument("--task-kind")
    parser.add_argument("--task-id")
    parser.add_argument("--episode-id")
    parser.add_argument("--attempt-id")
    parser.add_argument("--parent-attempt-id")
    parser.add_argument("--repair-attempt", type=int)
    parser.add_argument("--phase")
    parser.add_argument("--trigger-evidence", action="append", default=[],
                        metavar="TRAJECTORY_ID#EVENT_ID",
                        help="Verification evidence that triggered this repair "
                             "attempt (repeatable); required for improve/repair "
                             "phases, must stay absent for source-less writes")

_ID_RE = re.compile(r"_(\d+)$")


def content_block(
    type_: str,
    *,
    data: Any = None,
    uri: str | None = None,
    mime_type: str | None = None,
    sha256: str | None = None,
    visibility: str = "collector_only",
) -> dict:
    """Six-key content block; unused keys are null, never omitted (schema §6).

    The conservative default is ``collector_only``: recording an observation
    does not prove that a later provider request delivered it to the model.
    Harness/request-boundary code must explicitly mark ``agent_received`` (or
    ``agent_visible``) when it has that evidence.
    """
    if type_ not in CONTENT_TYPES:
        raise ValueError(f"unknown content type {type_!r}; expected one of {CONTENT_TYPES}")
    if visibility not in VISIBILITY:
        raise ValueError(f"unknown visibility {visibility!r}; expected one of {VISIBILITY}")
    return {
        "type": type_,
        "data": data,
        "uri": uri,
        "mime_type": mime_type,
        "sha256": sha256,
        "visibility": visibility,
    }


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _as_bytes(content: Any) -> bytes:
    if content is None:
        return b""
    if isinstance(content, bytes):
        return content
    if isinstance(content, str):
        return content.encode("utf-8")
    return str(content).encode("utf-8")


def _check_blocks(blocks: Sequence[dict]) -> None:
    for block in blocks or ():
        if not isinstance(block, dict) or block.get("type") not in CONTENT_TYPES:
            raise ValueError(f"content block must be a dict with a valid 'type': {block!r}")
        if block.get("visibility") not in VISIBILITY:
            raise ValueError(f"content block missing valid 'visibility': {block!r}")


def _max_numeric_id(items: Iterable[dict], key: str) -> int:
    best = 0
    for item in items or ():
        match = _ID_RE.search(str((item or {}).get(key) or ""))
        if match:
            best = max(best, int(match.group(1)))
    return best


class Collector:
    """Records one run's trajectory: append-only events plus referencing views."""

    def __init__(
        self,
        trajectory: dict,
        writer: TrajectoryWriter,
        *,
        artifact_store: Any = None,
        telemetry: Any = None,
        register: bool = False,
    ):
        self.trajectory = trajectory
        self.writer = writer
        self.artifact_store = artifact_store
        self.telemetry = telemetry
        self._finished = False
        self._counters = {
            "event": _max_numeric_id(trajectory.get("events") or [], "event_id"),
            "request": _max_numeric_id(trajectory.get("requests") or [], "request_id"),
            "file": _max_numeric_id(
                (trajectory.get("workspace") or {}).get("file_versions") or [], "version_id"
            ),
            "call": 0,
        }
        # Rebuild tool_call counters from existing assistant events.
        for event in trajectory.get("events") or []:
            for call in (event or {}).get("tool_calls") or []:
                match = _ID_RE.search(str(call.get("tool_call_id") or ""))
                if match:
                    self._counters["call"] = max(
                        self._counters["call"], int(match.group(1))
                    )

    # ── construction ─────────────────────────────────────────────────────

    @staticmethod
    def _normalize_metadata(metadata: dict) -> dict:
        md = dict(metadata or {})
        if not md.get("trajectory_id"):
            if md.get("game_id") and md.get("run_id"):
                md["trajectory_id"] = make_trajectory_id(md["game_id"], md["run_id"])
            else:
                raise ValueError(
                    "metadata needs a trajectory_id, or game_id+run_id for a project run"
                )
        game_id, run_id = md.get("game_id"), md.get("run_id")
        run_kind = md.get("run_kind") or (
            "project_run" if game_id and run_id else "standalone_training_task"
        )
        if run_kind == "project_run" and not (game_id and run_id):
            raise ValueError("run_kind=project_run requires both game_id and run_id")
        if run_kind == "standalone_training_task":
            md["game_id"] = None
            md["run_id"] = None
        md["run_kind"] = run_kind
        md.setdefault("predecessor_trajectory_id", None)
        md.setdefault("collector_version", COLLECTOR_VERSION)
        md.setdefault("completeness", "partial")
        md.setdefault("revision", 0)
        md.setdefault("created_at", now_iso())
        return md

    @classmethod
    def _skeleton(
        cls,
        metadata: dict,
        task_ref: dict | None,
        environment_ref: dict | None,
    ) -> dict:
        return {
            "schema_version": TRAJECTORY_SCHEMA_VERSION,
            "metadata": cls._normalize_metadata(metadata),
            "task_ref": task_ref or {},
            "environment_ref": environment_ref or {},
            "task_bindings": [],
            "tools": [],
            "tool_sets": {},
            "events": [],
            "requests": [],
            "asset_generations": [],
            "workspace": {"file_versions": []},
            "verification_refs": [],
            "attachments": [],
            "telemetry_refs": [],
            "training": {
                "status": "pending",
                "policy": "assistant_complete_v1",
                "group_id": None,
                "split": None,
            },
            "result": None,
            "derived_views": {},
        }

    @classmethod
    def start(
        cls,
        metadata: dict,
        task_ref: dict | None = None,
        environment_ref: dict | None = None,
        *,
        path: str | Path | None = None,
        artifact_store: Any = None,
        telemetry: Any = None,
        register: bool = True,
        exclusive: bool = False,
    ) -> "Collector":
        """Open a new trajectory for one run (schema §2.1: write file, then index)."""
        trajectory = cls._skeleton(metadata, task_ref, environment_ref)
        path = Path(path) if path else trajectory_path(trajectory["metadata"]["trajectory_id"])
        writer = TrajectoryWriter.create(path, trajectory)
        if exclusive:
            writer.acquire_exclusive()
        collector = cls(trajectory, writer, artifact_store=artifact_store, telemetry=telemetry)
        try:
            writer.checkpoint()  # revision 1: valid JSON exists before indexing
            if register:
                collector.register_index()
        except Exception:
            writer.close()
            raise
        return collector

    @classmethod
    def resume(
        cls,
        path: str | Path,
        *,
        artifact_store: Any = None,
        telemetry: Any = None,
    ) -> "Collector":
        """Continue an interrupted trajectory; already-written events stay."""
        writer = TrajectoryWriter.open_existing(path)
        return cls(
            writer.trajectory,
            writer,
            artifact_store=artifact_store,
            telemetry=telemetry,
            register=False,
        )

    # ── id allocation ─────────────────────────────────────────────────────

    def _next_id(self, kind: str, prefix: str) -> str:
        self._counters[kind] += 1
        return f"{prefix}_{self._counters[kind]:06d}"

    # ── events (canonical immutable log) ──────────────────────────────────

    def record_event(
        self,
        source: str,
        kind: str,
        *,
        content: Sequence[dict] | None = None,
        tool_calls: Sequence[dict] | None = None,
        tool_call_id: str | None = None,
        status: str | None = None,
        producer: str | None = None,
        ts: str | None = None,
        ts_source: str = "collector",
        **extra: Any,
    ) -> str:
        """Append one event and checkpoint. Never called on written events."""
        if self._finished:
            raise RuntimeError("trajectory already finished; start a new run")
        if source not in SOURCES:
            raise ValueError(f"unknown source {source!r}; expected one of {SOURCES}")
        if kind not in EVENT_KINDS:
            raise ValueError(f"unknown event kind {kind!r}; expected one of {EVENT_KINDS}")
        _check_blocks(content)
        if kind == "tool_result" and not tool_call_id:
            raise ValueError("tool_result events must carry the paired tool_call_id")
        if kind == "verification" and not tool_call_id and not producer:
            raise ValueError(
                "runner-produced verification events need a 'producer' (schema §6.1)"
            )
        event: dict[str, Any] = {
            "event_id": self._next_id("event", "evt"),
            "source": source,
            "kind": kind,
            "content": list(content or []),
        }
        if tool_calls is not None:
            event["tool_calls"] = list(tool_calls)
        if tool_call_id:
            event["tool_call_id"] = tool_call_id
        if status:
            event["status"] = status
        if producer:
            event["producer"] = producer
        event["ts"] = ts or now_iso()
        event["ts_source"] = ts_source
        event.update(extra)
        self.trajectory["events"].append(event)
        self.writer.checkpoint()
        return event["event_id"]

    def record_missing_event(self, source: str, reason: str, **extra: Any) -> str:
        """Mark an event that happened but was not fully captured (never fake it)."""
        return self.record_event(
            source,
            "runtime",
            status="unknown",
            missing_reason=reason,
            **extra,
        )

    def record_message(
        self,
        source: str,
        *,
        text: str | None = None,
        blocks: Sequence[dict] | None = None,
        visibility: str = "collector_only",
        **extra: Any,
    ) -> str:
        """Record a message; visibility is conservative unless the harness proves delivery."""
        if blocks is None:
            blocks = [content_block("text", data=text, visibility=visibility)]
        return self.record_event(source, "message", content=blocks, **extra)

    def record_tool_call(
        self,
        name: str,
        arguments: Any,
        *,
        tool_call_id: str | None = None,
        blocks: Sequence[dict] | None = None,
        visibility: str = "collector_only",
    ) -> tuple[str, str]:
        """Record an assistant tool-call event; returns (event_id, tool_call_id)."""
        if tool_call_id is None:
            tool_call_id = self._next_id("call", "call")
        event_id = self.record_event(
            "assistant",
            "tool_call",
            content=list(blocks or [content_block("json", data={"name": name, "arguments": arguments}, visibility=visibility)]),
            tool_calls=[{"tool_call_id": tool_call_id, "name": name, "arguments": arguments}],
        )
        return event_id, tool_call_id

    def record_tool_result(
        self,
        tool_call_id: str,
        status: str,
        *,
        text: str | None = None,
        data: Any = None,
        blocks: Sequence[dict] | None = None,
        visibility: str = "collector_only",
        **extra: Any,
    ) -> str:
        """Record the transport/process result of a tool call (not Unity's verdict)."""
        if blocks is None:
            if text is not None:
                blocks = [content_block("text", data=text, visibility=visibility)]
            else:
                blocks = [content_block("json", data=data, visibility=visibility)]
        return self.record_event(
            "tool",
            "tool_result",
            content=list(blocks),
            tool_call_id=tool_call_id,
            status=status,
            **extra,
        )

    # ── verification (runner conclusions, referencing events) ─────────────

    def record_verification(
        self,
        verification_kind: str,
        results: dict | None = None,
        *,
        producer: str = "runner",
        state_ref: str | None = None,
        suite_ref: str | None = None,
        environment_ref: str | None = None,
        origin: str | None = None,
        visible_event_ids: Sequence[str] | None = None,
        integrity: dict | None = None,
        tool_call_id: str | None = None,
        visibility: str = "collector_only",
        command: str | None = None,
        exit_code: int | None = None,
        workspace_version_ids: Sequence[str] | None = None,
        output_ref: str | None = None,
    ) -> tuple[str, dict]:
        """Record a verification observation plus its referencing ref.

        The event carries the raw conclusion (transport status vs business
        outcome stay separate, schema §6.1); the ``verification_ref`` binds the
        tested state, suite, origin and what the agent actually saw
        (schema §9.2). Runner verification is collector-only by default;
        callers must explicitly provide the event IDs actually delivered to
        the agent. ``command``/``exit_code``/``workspace_version_ids``/
        ``output_ref`` are the explicit observation entry for captured
        command executions: they record WHAT ran and its observed exit code
        against WHICH file versions — they never claim business success,
        and nothing infers a verification from a tool name.
        """
        results = dict(results or {})
        if command is not None:
            results.setdefault("command", command)
        if exit_code is not None:
            results.setdefault("exit_code", exit_code)
        payload = dict(results)
        payload["verification_kind"] = verification_kind
        event_id = self.record_event(
            "tool",
            "verification",
            content=[content_block(
                "json", data=payload, mime_type="application/json", visibility=visibility
            )],
            producer=producer,
            tool_call_id=tool_call_id,
        )
        ref: dict[str, Any] = {"verification_event_id": event_id, "results": results}
        if state_ref is not None:
            ref["state_ref"] = state_ref
        if suite_ref is not None:
            ref["suite_ref"] = suite_ref
        if environment_ref is not None:
            ref["environment_ref"] = environment_ref
        if origin is not None:
            ref["origin"] = origin
        if integrity is not None:
            ref["integrity"] = integrity
        # Visibility is an observation claim, not an inference. In particular,
        # a runner-produced verification must not become agent-visible merely
        # because it was recorded. The caller supplies the exact event IDs
        # that were actually returned to the model.
        ref["visible_event_ids"] = list(visible_event_ids or [])
        # explicit observation entry: what ran, its observed exit code, the
        # file versions it applies to, and where the raw output lives — never
        # an inferred success claim
        if command is not None:
            ref["command"] = command
        if exit_code is not None:
            ref["exit_code"] = exit_code
        if workspace_version_ids is not None:
            ref["workspace_version_ids"] = list(workspace_version_ids)
        if output_ref is not None:
            ref["output_ref"] = output_ref
        self.trajectory["verification_refs"].append(ref)
        self.writer.checkpoint()
        return event_id, ref

    # ── requests (model-call boundaries) ──────────────────────────────────

    def _find_request(self, request_id: str) -> dict:
        for request in self.trajectory["requests"]:
            if request.get("request_id") == request_id:
                return request
        raise KeyError(f"no such request_id {request_id!r}")

    def record_request(
        self,
        input_event_ids: Sequence[str],
        response_event_ids: Sequence[str] | None = None,
        *,
        model: str,
        provider: str | None = None,
        sampling: dict | None = None,
        tool_set_id: str | None = None,
        telemetry_ref: str | None = None,
        attempt_id: str | None = None,
        ts: str | None = None,
        completed_at: str | None = None,
        training: dict | None = None,
        **extra: Any,
    ) -> str:
        """Record one real model call by its event-id input/output boundary."""
        request: dict[str, Any] = {
            "request_id": self._next_id("request", "req"),
            "input_event_ids": list(input_event_ids),
            "response_event_ids": list(response_event_ids or []),
            "model": model,
        }
        if provider is not None:
            request["provider"] = provider
        if sampling is not None:
            request["sampling"] = sampling
        if tool_set_id is not None:
            request["tool_set_id"] = tool_set_id
        if telemetry_ref is not None:
            request["telemetry_ref"] = telemetry_ref
        if attempt_id is not None:
            request["attempt_id"] = attempt_id
        request["ts"] = ts or now_iso()
        if completed_at is not None:
            request["completed_at"] = completed_at
        if training is not None:
            request["training"] = dict(training)
        request.update(extra)
        self.trajectory["requests"].append(request)
        self.writer.checkpoint()
        return request["request_id"]

    def open_request(self, input_event_ids: Sequence[str], **fields: Any) -> str:
        """Record a request at dispatch time; close it with ``close_request``."""
        return self.record_request(input_event_ids, None, **fields)

    def close_request(
        self,
        request_id: str,
        response_event_ids: Sequence[str],
        *,
        completed_at: str | None = None,
        finish_reason: str | None = None,
    ) -> dict:
        """Attach the real response events to an already-recorded request."""
        request = self._find_request(request_id)
        request["response_event_ids"] = list(response_event_ids)
        request["completed_at"] = completed_at or now_iso()
        if finish_reason is not None:
            request["finish_reason"] = finish_reason
        self.writer.checkpoint()
        return request

    def attach_raw(
        self,
        request_id: str,
        *,
        raw_request_ref: dict | None = None,
        raw_response_ref: dict | None = None,
        raw_stream_ref: dict | None = None,
        capture_status: str = "complete",
        missing_reason: str | None = None,
    ) -> dict:
        """Attach redacted raw provider payload refs (schema §5.1.1) to a request."""
        request = self._find_request(request_id)
        refs = {"raw_request_ref": raw_request_ref, "raw_response_ref": raw_response_ref,
                "raw_stream_ref": raw_stream_ref}
        # A stream archive is optional; request and response are the required
        # pair for a complete boundary capture.
        required_present = sum(refs[key] is not None for key in ("raw_request_ref", "raw_response_ref"))
        if required_present == 0 and capture_status == "complete":
            capture_status = "unavailable"
            missing_reason = missing_reason or "no_raw_payloads"
        elif required_present < 2 and capture_status == "complete":
            capture_status = "partial"
            missing_reason = missing_reason or "one_or_more_required_raw_payloads_missing"
        for key, value in (
            ("raw_request_ref", raw_request_ref),
            ("raw_response_ref", raw_response_ref),
            ("raw_stream_ref", raw_stream_ref),
        ):
            if value is not None:
                request[key] = value
        request["capture_status"] = capture_status
        if missing_reason is not None:
            request["missing_reason"] = missing_reason
        self.writer.checkpoint()
        return request

    def set_request_training(
        self, request_id: str, *, learn: bool, reason: str | None = None
    ) -> dict:
        """Set the in-file training control for one request (schema §10.2)."""
        request = self._find_request(request_id)
        control: dict[str, Any] = {"learn": bool(learn)}
        if reason is not None:
            control["reason"] = reason
        request["training"] = control
        self.writer.checkpoint()
        return request

    # ── workspace / assets / tools / bindings ─────────────────────────────

    def record_workspace_change(
        self,
        path: str,
        operation: str = "modify",
        *,
        trigger_event_id: str | None = None,
        tool_call_id: str | None = None,
        content: Any = None,
        content_path: str | Path | None = None,
        renamed_from: str | None = None,
        mime_type: str | None = None,
        store: Any = None,
    ) -> str:
        """Append one immutable file version (schema §4.2 / collection plan §6.1).

        ``content`` (bytes/str) or ``content_path`` supplies the new bytes;
        with an artifact store the bytes are stored and referenced by URI +
        sha256, otherwise only the hash is recorded (delete keeps the previous
        version's content — no new bytes are needed).
        """
        if operation not in OPERATIONS:
            raise ValueError(f"unknown operation {operation!r}; expected one of {OPERATIONS}")
        store = store or self.artifact_store
        data: bytes | None = None
        if content is not None:
            data = _as_bytes(content)
        elif content_path is not None:
            data = Path(content_path).read_bytes()
        elif operation != "delete":
            raise ValueError(
                "create/modify/rename need content or content_path "
                "(hash-only manifests are not content backups, schema §4.3)"
            )

        logical_path = renamed_from or path
        parent = self._latest_version_for(logical_path)
        entry: dict[str, Any] = {
            "version_id": self._next_id("file", "file"),
            "path": str(path),
            "operation": operation,
        }
        if renamed_from is not None:
            entry["renamed_from"] = str(renamed_from)
        if parent is not None:
            entry["parent_version_id"] = parent
        if trigger_event_id is not None:
            entry["event_id"] = trigger_event_id
        if tool_call_id is not None:
            entry["tool_call_id"] = tool_call_id
        if data is not None:
            entry["sha256"] = sha256_bytes(data)
            if store is not None:
                stored = store.put(data, mime_type=mime_type)
                entry["uri"] = stored["uri"]
                entry.setdefault("sha256", stored["sha256"])
        self.trajectory["workspace"]["file_versions"].append(entry)
        self.writer.checkpoint()
        return entry["version_id"]

    def _latest_version_for(self, path: str) -> str | None:
        latest = None
        for entry in self.trajectory["workspace"]["file_versions"]:
            if entry.get("path") == path or entry.get("renamed_from") == path:
                latest = entry["version_id"]
        return latest

    def record_initial_state(self, ref: dict) -> None:
        """Reference the recoverable initial workspace state (schema §4.2).

        The referenced manifest is a hash manifest, not a content backup —
        the caller keeps the actual baseline (template, commit, snapshot).
        """
        self.trajectory["workspace"]["initial_state_ref"] = dict(ref)
        self.writer.checkpoint()

    def record_asset_generation(self, generation_ref: dict) -> dict:
        """Reference an authoritative generation in task meta (plan §0.1)."""
        entry = {"generation_ref": dict(generation_ref)}
        self.trajectory["asset_generations"].append(entry)
        self.writer.checkpoint()
        return entry

    def record_tools(self, definitions: Sequence[dict]) -> None:
        """Record/refresh the default tool definitions visible to the model."""
        known = {tool.get("name"): tool for tool in self.trajectory["tools"]}
        for definition in definitions:
            known[definition.get("name")] = dict(definition)
        self.trajectory["tools"] = list(known.values())
        self.writer.checkpoint()

    def record_tool_set(self, tool_set_id: str, definitions: Sequence[dict]) -> None:
        """Record a named tool set (schema §6: only when the active set changes)."""
        self.trajectory["tool_sets"][tool_set_id] = list(definitions)
        self.writer.checkpoint()

    def record_task_binding(self, binding: dict) -> dict:
        self.trajectory["task_bindings"].append(dict(binding))
        self.writer.checkpoint()
        return binding

    def record_attachment(self, attachment: dict) -> dict:
        self.trajectory["attachments"].append(dict(attachment))
        self.writer.checkpoint()
        return attachment

    def add_telemetry_ref(self, ref: Any) -> None:
        self.trajectory["telemetry_refs"].append(ref)
        self.writer.checkpoint()

    # ── training control (non-message fields, schema §10.2) ───────────────

    def set_training(
        self,
        *,
        status: str | None = None,
        policy: str | None = None,
        group_id: str | None = None,
        split: str | None = None,
    ) -> dict:
        """Update the in-file training control; never touches recorded messages."""
        training = self.trajectory["training"]
        if status is not None:
            if status not in TRAINING_STATUS:
                raise ValueError(f"unknown training status {status!r}")
            training["status"] = status
        if policy is not None:
            training["policy"] = policy
        if group_id is not None:
            training["group_id"] = group_id
        if split is not None:
            training["split"] = split
        self.writer.checkpoint()
        return training

    # ── lifecycle ─────────────────────────────────────────────────────────

    def register_index(self) -> Path:
        """Add this trajectory to ``collect.json`` (id unique; atomic replace)."""
        metadata = self.trajectory["metadata"]
        index_path = collect_json_path()
        index_path.parent.mkdir(parents=True, exist_ok=True)
        import fcntl
        with open(str(index_path) + ".lock", "a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if index_path.exists():
                index = load_json(index_path)
            else:
                index = {
                    "schema_version": TRAJECTORY_INDEX_SCHEMA_VERSION,
                    "trajectories": [],
                }
            if index.get("schema_version") != TRAJECTORY_INDEX_SCHEMA_VERSION:
                raise ValueError(f"{index_path}: unexpected index schema_version")
            ids = {item.get("trajectory_id") for item in index["trajectories"]}
            if metadata["trajectory_id"] in ids:
                raise ValueError(
                    f"trajectory_id {metadata['trajectory_id']!r} already indexed"
                )
            index["trajectories"].append(
                {
                    "trajectory_id": metadata["trajectory_id"],
                    "game_id": metadata.get("game_id"),
                    "run_id": metadata.get("run_id"),
                    "trajectory_path": rel_to_repo(self.writer.path),
                }
            )
            atomic_write_json(index_path, index)
            fcntl.flock(lock, fcntl.LOCK_UN)
            return index_path

    def mark_interrupted(self, reason: str) -> None:
        """Record an honest interruption; keep every already-written event."""
        self.trajectory["metadata"]["completeness"] = "interrupted"
        self.trajectory["result"] = {
            "ok": None,
            "status": "interrupted",
            "stop_reason": reason,
        }
        self.writer.checkpoint()
        self._finished = True
        self.writer.close()

    def finish(
        self,
        result: dict | None = None,
        *,
        completeness: str = "complete",
    ) -> Path:
        """Write the final result/state and close the trajectory."""
        if completeness not in COMPLETENESS:
            raise ValueError(f"unknown completeness {completeness!r}")
        final = dict(result or {})
        final.setdefault("ok", None)
        final.setdefault("status", "completed")
        self.trajectory["result"] = final
        self.trajectory["metadata"]["completeness"] = completeness
        self.writer.checkpoint()
        self._finished = True
        # A finished trajectory releases the process-wide writer lease. This is
        # important for a later explicit resume and for graceful shutdown.
        self.writer.close()
        return self.writer.path

    # ── context manager ───────────────────────────────────────────────────

    def __enter__(self) -> "Collector":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if not self._finished:
            reason = "collector_exception" if exc_type else "collector_exit_without_finish"
            self.mark_interrupted(reason)
        return False
