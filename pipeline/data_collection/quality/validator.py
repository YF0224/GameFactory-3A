"""
pipeline/data_collection/validator.py

Read-only integrity checks (collection plan §9.1).

The validator only adds findings — it never modifies a trajectory. Errors
mean the file must not be consumed by the loader; warnings mean human review.
Implemented against schema v5 §6/§9/§10 and plan.md §0.2.

Stdlib only.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from pipeline.data_collection.paths import REPO_ROOT, collect_json_path, rel_to_repo

from ..core.collector import (
    COMPLETENESS,
    EVENT_KINDS,
    OPERATIONS,
    SOURCES,
    TRAINING_POLICIES,
    TRAINING_STATUS,
    VISIBILITY,
)
from ..core.event_writer import (
    TRAJECTORY_INDEX_SCHEMA_VERSION,
    TRAJECTORY_SCHEMA_VERSION,
    load_json,
)

_CONTENT_KEYS = ("type", "data", "uri", "mime_type", "sha256", "visibility")

# High-confidence secret *values* (error) vs secret-looking keys (warning).
# The optional quote after the key covers JSON-embedded payloads like
# {"api_key": "..."} — the shape redacted raw provider bodies are stored in.
_SECRET_VALUE_RE = re.compile(
    r"(?i)\b(authorization|api[_-]?key)\b[\"']?\s*[:=]\s*[\"'][A-Za-z0-9_\-.]{16,}"
)
_SECRET_KEY_RE = re.compile(r"(?i)\b(password|secret|access_token|credentials)\s*[:=]")
# Machine-private absolute paths (schema §8.2: paths get stable substitute prefixes).
_ABS_PATH_RE = re.compile(r"/Users/|/home/[a-z]|/var/folders/|[A-Za-z]:\\")
# Formal benchmark evaluation must never be packaged into a trajectory (§8.1).
_EVAL_URI_RE = re.compile(r"/eval/")

# Request quality markers (additive v5 request keys): boundary and context are
# marked separately — a reliable boundary never implies a complete context.
# context=complete may only be claimed on the basis of a real request snapshot;
# a session-history reconstruction is at best partial.
_REQUEST_BOUNDARIES = ("observed", "reconstructed", "unknown")
_REQUEST_CONTEXTS = ("complete", "partial", "unknown")
# Response-end status is separate from tool execution: a tool result proves
# the tool ran, never that the streamed response finished (schema §7.2).
_REQUEST_RESPONSES = ("complete", "partial", "unknown")


@dataclass
class Finding:
    code: str
    message: str
    severity: str = "error"  # "error" | "warning"

    def as_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "severity": self.severity}


def _iter_strings(value: Any, path: str = "$") -> Iterator[tuple[str, str]]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _iter_strings(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            yield from _iter_strings(item, f"{path}[{index}]")
    elif isinstance(value, str):
        yield path, value


def _scan_text(report: list[Finding], location: str, text: str) -> None:
    if _SECRET_VALUE_RE.search(text):
        report.append(Finding("leak.secret", f"{location}: looks like a secret value", "error"))
    elif _SECRET_KEY_RE.search(text):
        report.append(
            Finding("leak.secret_key", f"{location}: secret-looking key mention", "warning")
        )
    if _ABS_PATH_RE.search(text):
        report.append(
            Finding("leak.abs_path", f"{location}: machine-absolute path", "warning")
        )
    if _EVAL_URI_RE.search(text):
        report.append(
            Finding("leak.eval", f"{location}: reference into a formal eval/ directory", "warning")
        )


def _resolve_uri(uri: str) -> Path:
    path = Path(uri)
    return path if path.is_absolute() else REPO_ROOT / path


def validate_trajectory(
    data: dict,
    *,
    index: dict | None = None,
    verify_hashes: bool = False,
) -> dict:
    """Validate one in-memory trajectory; returns ``{ok, errors, warnings}``."""
    findings: list[Finding] = []

    def error(code: str, message: str) -> None:
        findings.append(Finding(code, message, "error"))

    def warning(code: str, message: str) -> None:
        findings.append(Finding(code, message, "warning"))

    # ── top level / metadata ───────────────────────────────────────────────
    if data.get("schema_version") != TRAJECTORY_SCHEMA_VERSION:
        error("schema.version", f"schema_version must be {TRAJECTORY_SCHEMA_VERSION!r}")
    metadata = data.get("metadata") or {}
    trajectory_id = metadata.get("trajectory_id")
    if not trajectory_id:
        error("metadata.trajectory_id", "metadata.trajectory_id is required")
    run_kind = metadata.get("run_kind")
    game_id, run_id = metadata.get("game_id"), metadata.get("run_id")
    if run_kind == "project_run" and not (game_id and run_id):
        error("metadata.run_kind", "project_run requires game_id and run_id")
    if run_kind == "standalone_training_task" and (game_id or run_id):
        warning("metadata.run_kind", "standalone task should keep game_id/run_id null")
    # Repair provenance (huibao §3.4): an improve/repair attempt names the
    # verification evidence that triggered it; a source-less regeneration is
    # a new write. Advisory — phase naming stays caller-owned.
    trigger_evidence = metadata.get("trigger_evidence_ids")
    phase = metadata.get("phase")
    if phase in ("improve", "repair") and not trigger_evidence:
        warning("metadata.trigger_evidence",
                f"phase={phase} attempt without trigger_evidence_ids "
                f"(the verification evidence that triggered the repair)")
    if phase == "write" and trigger_evidence:
        warning("metadata.trigger_evidence",
                "phase=write with trigger_evidence_ids: a source-less "
                "regeneration is a new write; record an improve/repair phase "
                "instead of carrying repair evidence on a write")
    if metadata.get("completeness") not in COMPLETENESS:
        error("metadata.completeness", f"completeness must be one of {COMPLETENESS}")
    revision = metadata.get("revision")
    if not isinstance(revision, int) or revision < 1:
        error("metadata.revision", "revision must be a positive integer")

    # ── events ─────────────────────────────────────────────────────────────
    events = data.get("events") or []
    order: dict[str, int] = {}
    known_calls: set[str] = set()
    results_by_call: dict[str, list[str]] = {}
    for position, event in enumerate(events):
        event_id = event.get("event_id")
        if not event_id:
            error("event.id", f"event at position {position} has no event_id")
            continue
        if event_id in order:
            error("event.duplicate_id", f"duplicate event_id {event_id}")
            continue
        order[event_id] = position
        if event.get("source") not in SOURCES:
            error("event.source", f"{event_id}: unknown source {event.get('source')!r}")
        if event.get("kind") not in EVENT_KINDS:
            error("event.kind", f"{event_id}: unknown kind {event.get('kind')!r}")
        for block in event.get("content") or []:
            if not isinstance(block, dict):
                error("event.content", f"{event_id}: content block must be a dict")
                continue
            if block.get("visibility") not in VISIBILITY:
                error("event.visibility", f"{event_id}: missing valid visibility")
            missing = [key for key in _CONTENT_KEYS if key not in block]
            if missing:
                warning("event.content_keys", f"{event_id}: content block missing {missing}")
        if event.get("kind") == "tool_result":
            call_id = event.get("tool_call_id")
            if not call_id:
                error("event.unpaired_result", f"{event_id}: tool_result without tool_call_id")
            else:
                results_by_call.setdefault(call_id, []).append(event_id)
        if event.get("kind") == "verification" and not event.get("tool_call_id"):
            if not event.get("producer"):
                error("event.producer", f"{event_id}: runner verification needs a producer")
        for call in event.get("tool_calls") or []:
            call_id = call.get("tool_call_id")
            if not call_id:
                error("event.tool_call_id", f"{event_id}: tool_call without tool_call_id")
            else:
                known_calls.add(call_id)

    for call_id, result_ids in results_by_call.items():
        if call_id not in known_calls:
            error("tool.orphan_result", f"tool_call_id {call_id} has no assistant call")
        if len(result_ids) > 1:
            error(
                "tool.duplicate_result",
                f"tool_call_id {call_id} has multiple results: {result_ids}",
            )
    for call_id in known_calls:
        if call_id not in results_by_call:
            warning(
                "tool.pending_result",
                f"tool_call_id {call_id} has no result (pending/interrupted is allowed)",
            )

    # ── requests ───────────────────────────────────────────────────────────
    requests = data.get("requests") or []
    request_ids: set[str] = set()
    referenced_events: set[str] = set()
    for request in requests:
        request_id = request.get("request_id")
        if not request_id:
            error("request.id", "request without request_id")
            continue
        if request_id in request_ids:
            error("request.duplicate_id", f"duplicate request_id {request_id}")
        request_ids.add(request_id)
        input_ids = request.get("input_event_ids") or []
        response_ids = request.get("response_event_ids") or []
        for event_id in input_ids + response_ids:
            referenced_events.add(event_id)
            if event_id not in order:
                error("request.unknown_event", f"{request_id} references unknown {event_id}")
        if response_ids and set(response_ids) & set(input_ids):
            error(
                "request.self_input",
                f"{request_id}: its own response events are referenced as input",
            )
        if response_ids and input_ids:
            if any(order[i] >= min(order[r] for r in response_ids) for i in input_ids if i in order):
                error(
                    "request.ordering",
                    f"{request_id}: an input event happens after its response events",
                )
        for event_id in response_ids:
            if event_id in order and events[order[event_id]].get("source") != "assistant":
                error(
                    "request.response_source",
                    f"{request_id}: response event {event_id} is not assistant-sourced",
                )
        if request.get("tool_set_id") and request["tool_set_id"] not in (data.get("tool_sets") or {}):
            warning(
                "request.tool_set",
                f"{request_id}: tool_set_id {request['tool_set_id']} not in tool_sets",
            )
        # ── request quality markers ──────────────────────────────────────────
        boundary = request.get("boundary")
        context = request.get("context")
        if boundary is not None and boundary not in _REQUEST_BOUNDARIES:
            error("request.boundary_value", f"{request_id}: unknown boundary marker {boundary!r}")
        if context is not None and context not in _REQUEST_CONTEXTS:
            error("request.context_value", f"{request_id}: unknown context marker {context!r}")
        response_status = request.get("response_status")
        if response_status is not None and response_status not in _REQUEST_RESPONSES:
            error("request.response_status_value",
                  f"{request_id}: unknown response_status marker {response_status!r}")
        if request.get("provider_request_id") and request.get("session_id") is None:
            warning(
                "request.session_missing",
                f"{request_id}: provider_request_id without session_id; "
                f"id attribution across sessions/resume is incomplete",
            )
        boundary_basis = request.get("boundary_basis")
        if boundary == "observed" and not isinstance(boundary_basis, dict):
            error(
                "request.boundary_basis",
                f"{request_id}: boundary=observed without an evidence basis",
            )
        elif boundary == "reconstructed" and not isinstance(boundary_basis, dict):
            warning(
                "request.boundary_basis",
                f"{request_id}: reconstructed boundary without a basis record",
            )
        context_basis = request.get("context_basis")
        if context == "complete" and (
            not isinstance(context_basis, dict) or context_basis.get("type") != "request_snapshot"
        ):
            error(
                "request.context_basis",
                f"{request_id}: context=complete requires a request_snapshot basis; "
                f"a session-history reconstruction is at best partial",
            )
        if request.get("provider_request_id") and boundary != "observed":
            warning(
                "request.provider_id_boundary",
                f"{request_id}: provider_request_id is set but boundary is {boundary!r}; "
                f"provider ids anchor observed boundaries, importer-local numbers "
                f"must never be written there",
            )
        control = request.get("training")
        if control is not None and not isinstance(control.get("learn"), bool):
            error("request.learn", f"{request_id}: training.learn must be a boolean")

    # Visibility invariant (schema §5 rule 3 / §6.1): request-referenced
    # content that actually entered the request must be agent_received.
    for event_id in sorted(referenced_events):
        if event_id not in order:
            continue
        for block in events[order[event_id]].get("content") or []:
            if isinstance(block, dict) and block.get("visibility") == "agent_visible":
                error(
                    "visibility.request_input",
                    f"{event_id}: referenced as request input but marked agent_visible; must be agent_received",
                )

    # ── workspace ──────────────────────────────────────────────────────────
    versions = (data.get("workspace") or {}).get("file_versions") or []
    version_ids = {entry.get("version_id") for entry in versions}
    for entry in versions:
        version_id = entry.get("version_id")
        if not version_id:
            error("workspace.version_id", "file version without version_id")
        if entry.get("operation") not in OPERATIONS:
            error("workspace.operation", f"{version_id}: unknown operation")
        parent = entry.get("parent_version_id")
        if parent is not None and parent not in version_ids:
            error("workspace.parent", f"{version_id}: unknown parent_version_id {parent}")
        if entry.get("operation") != "delete" and not entry.get("uri"):
            warning(
                "workspace.content",
                f"{version_id}: no stored content uri (hash-only is not a backup)",
            )
        if entry.get("event_id") and entry["event_id"] not in order:
            warning("workspace.event", f"{version_id}: trigger event not found")
        if verify_hashes and entry.get("uri") and entry.get("sha256"):
            import hashlib

            path = _resolve_uri(entry["uri"])
            if path.exists():
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                if digest != entry["sha256"]:
                    error("workspace.hash", f"{version_id}: content hash mismatch")
            else:
                warning("workspace.missing_uri", f"{version_id}: uri not resolvable ({entry['uri']})")

    # parent chains must be acyclic
    for entry in versions:
        seen: set[str] = set()
        current = entry.get("version_id")
        while current in version_ids:
            if current in seen:
                error("workspace.cycle", f"version chain cycle at {current}")
                break
            seen.add(current)
            current = next(
                (e.get("parent_version_id") for e in versions if e.get("version_id") == current),
                None,
            )

    # ── verification refs ──────────────────────────────────────────────────
    for ref in data.get("verification_refs") or []:
        event_id = ref.get("verification_event_id")
        if event_id not in order:
            error("verification.event", f"verification_ref references unknown {event_id}")
        elif events[order[event_id]].get("kind") != "verification":
            error("verification.kind", f"{event_id} is not a verification event")
        for visible in ref.get("visible_event_ids") or []:
            if visible not in order:
                warning("verification.visible", f"unknown visible_event_id {visible}")
        state = ref.get("state_ref")
        if state is not None and state not in version_ids:
            warning("verification.state", f"state_ref {state} is not a recorded file version")

    # ── asset generations / attachments ────────────────────────────────────
    for entry in data.get("asset_generations") or []:
        if not isinstance(entry.get("generation_ref"), dict):
            warning("asset.ref", "asset_generations entry without generation_ref")
    for attachment in data.get("attachments") or []:
        if not (attachment.get("uri") or attachment.get("data") is not None):
            warning("attachment.empty", f"attachment {attachment!r} has neither uri nor data")

    # ── training control ───────────────────────────────────────────────────
    training = data.get("training") or {}
    if training.get("status") not in TRAINING_STATUS:
        error("training.status", f"training.status must be one of {TRAINING_STATUS}")
    if metadata.get("completeness") == "complete" and not data.get("result"):
        warning("result.missing", "completeness=complete but result is empty")

    # Request quality gate (schema §10.2/§10.3): learn=true claims the request
    # is trainable UNDER THE DECLARED POLICY. The default (and missing-policy)
    # policy assistant_complete_v1 keeps the strict gate — learn=true must be
    # an observed, complete-context model call, so ready+learn cannot bypass
    # the boundary/context markers. assistant_reconstructed_v1 explicitly
    # admits history-rebuilt views (reconstructed boundary with recorded
    # basis, partial context) for the loader's reconstruction mode; unknown
    # markers still refuse. "requests non-empty" is never a quality bar —
    # a trajectory with zero grounded requests is valid and simply untrainable.
    if training.get("status") == "ready":
        policy = training.get("policy", "assistant_complete_v1")
        if policy not in TRAINING_POLICIES:
            error("training.policy",
                  f"training.policy must be one of {TRAINING_POLICIES} when status=ready")
        for request in requests:
            request_id = request.get("request_id")
            learn = (request.get("training") or {}).get("learn") is True
            if not learn:
                continue
            boundary = request.get("boundary", "unknown")
            context = request.get("context", "unknown")
            if policy == "assistant_reconstructed_v1":
                if boundary not in ("observed", "reconstructed") or context not in (
                    "complete", "partial"
                ):
                    error(
                        "request.learn_quality",
                        f"{request_id}: learn=true on a request the {policy} policy "
                        f"cannot ground (boundary={boundary}, context={context})",
                    )
            elif not (boundary == "observed" and context == "complete"):
                error(
                    "request.learn_quality",
                    f"{request_id}: learn=true on a request that is not an observed, "
                    f"complete-context model call",
                )
            # A truncated/interrupted response is never a loss target
            # (schema §10.2: 截断输出 learn=false) under ANY policy — response
            # end and tool execution stay separate facts.
            if request.get("response_status") == "partial":
                error(
                    "request.response_partial_learn",
                    f"{request_id}: learn=true on a partial (interrupted/truncated) response",
                )

    # ── index ──────────────────────────────────────────────────────────────
    if index is not None:
        entries = [e for e in index.get("trajectories") or [] if e.get("trajectory_id") == trajectory_id]
        if len(entries) == 0:
            warning("index.missing", f"trajectory_id {trajectory_id} not in collect.json")
        elif len(entries) > 1:
            error("index.duplicate", f"trajectory_id {trajectory_id} indexed {len(entries)} times")

    # ── secrets / private paths / eval leakage over all strings ────────────
    for location, text in _iter_strings(data):
        _scan_text(findings, location, text)

    return {
        "ok": not any(f.severity == "error" for f in findings),
        "errors": [f.as_dict() for f in findings if f.severity == "error"],
        "warnings": [f.as_dict() for f in findings if f.severity == "warning"],
    }


def validate_file(
    path: str | Path,
    *,
    data_root: str | Path | None = None,
    verify_hashes: bool = False,
) -> dict:
    """Validate a trajectory file, cross-checking it against collect.json."""
    path = Path(path)
    data = load_json(path)
    index_path = Path(data_root) / "collect.json" if data_root else collect_json_path()
    index = load_json(index_path) if index_path.exists() else None
    if index is not None and index.get("schema_version") != TRAJECTORY_INDEX_SCHEMA_VERSION:
        index = None
    report = validate_trajectory(data, index=index, verify_hashes=verify_hashes)
    if index is not None:
        trajectory_id = (data.get("metadata") or {}).get("trajectory_id")
        for entry in index.get("trajectories") or []:
            if entry.get("trajectory_id") == trajectory_id:
                expected = rel_to_repo(path)
                if entry.get("trajectory_path") not in (expected, str(path)):
                    report["warnings"].append(
                        {
                            "code": "index.path",
                            "message": f"index trajectory_path {entry.get('trajectory_path')!r} "
                            f"does not match {expected!r}",
                            "severity": "warning",
                        }
                    )
    return report
