"""Partition a Codex rollout into task-scoped JSONL sessions.

Codex may run several tasks in one session.  This module keeps the original
records intact and routes function calls/results by prepared task workspace.
It does not interpret hidden reasoning or invent task ownership.
"""
from __future__ import annotations
import argparse, json, os, sys
import hashlib
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:  # CLI: make `pipeline`/`scripts` importable
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.data_collection.adapters.codely_autosave import derive_tools_used  # noqa: E402


def _strings(value: Any):
    if isinstance(value, str): yield value
    elif isinstance(value, dict):
        for v in value.values(): yield from _strings(v)
    elif isinstance(value, (list, tuple)):
        for v in value: yield from _strings(v)


def _match(text: str, binding: dict[str, Any]) -> bool:
    root = binding.get("workspace")
    if not root: return False
    try:
        return os.path.commonpath([os.path.abspath(text), os.path.abspath(str(root))]) == os.path.abspath(str(root))
    except (ValueError, OSError):
        return False


def _owner(payload: dict[str, Any], bindings: list[dict[str, Any]]) -> str | None:
    raw = payload.get("arguments", payload.get("output", payload))
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            pass
    values = list(_strings(raw))
    # Prefer an explicit task id if a producer supplied one.
    for b in bindings:
        if b.get("task_id") and any(str(b["task_id"]) in v for v in values): return b["task_id"]
    for b in bindings:
        if any(_match(v, b) for v in values): return b.get("task_id")
    return None


def _load_json_file(path: Any) -> dict[str, Any] | None:
    if not path: return None
    p = Path(path)
    if not p.is_file(): return None
    try: return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print(f"warning: unreadable JSON at {p}")
        return None


def _normalize_bindings(bindings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate bindings and fill v5-format gaps on fresh copies.

    Collector v5 ``task_bindings`` entries carry ``task_packet_uri`` and no
    ``workspace``: the uri is aliased to ``task_packet_path`` and the workspace
    is derived from ``meta_json`` → task packet → the standard
    ``<workspace>/demo_outputs/<stage>/task_packet.json`` layout. Duplicate or
    missing ``task_id`` values are rejected instead of silently merging slices.
    """
    normalized, seen = [], set()
    for binding in bindings:
        b = dict(binding)
        task_id = b.get("task_id")
        if not task_id:
            raise ValueError(f"binding without task_id: {sorted(b)}")
        if str(task_id) in seen:
            raise ValueError(f"duplicate task_id in bindings: {task_id!r}")
        seen.add(str(task_id))
        if not (b.get("task_packet") or b.get("task_packet_path")) and b.get("task_packet_uri"):
            b["task_packet_path"] = b["task_packet_uri"]
        if not b.get("workspace"):
            meta = _load_json_file(b.get("meta_json"))
            packet = _load_json_file(b.get("task_packet_path"))
            ws = (meta or {}).get("workspace") or (meta or {}).get("output_dir") \
                or (packet or {}).get("workspace") or (packet or {}).get("output_dir")
            if not ws and b.get("task_packet_path"):
                for parent in Path(b["task_packet_path"]).parents:
                    if parent.name == "demo_outputs":
                        ws = str(parent.parent); break
            if ws: b["workspace"] = ws
        normalized.append(b)
    return normalized


def _merge_unique(slices: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Merge task slices back into one session view, each record exactly once.

    Shared records are the same rollout line routed into every task slice, so
    they dedupe by ``ordinal`` (the rollout's sequence key) or by object
    identity when the rollout lacks ordinals; sorting restores the real
    chronology of parallel calls.
    """
    merged, seen = [], set()
    for records in slices:
        for record in records:
            key = record.get("ordinal")
            if key is None: key = ("object", id(record))
            if key in seen: continue
            seen.add(key)
            merged.append(record)
    merged.sort(key=lambda r: r.get("ordinal", 0))
    return merged


def _plan_trajectory(trajectory: dict[str, Any], raw_records: list[dict[str, Any]],
                     raw_path: Path, metadata: dict[str, Any]) -> dict[str, Any]:
    """Upgrade the small Codex message converter output to collection-plan v5.

    The script converter remains deliberately backward-compatible (and is also
    used by its v1 tests).  The collection boundary is the place where a run
    gets the plan's complete container and where raw rollout provenance is
    retained; no facts are inferred from assistant prose.
    """
    md = dict(trajectory.get("metadata") or {})
    md.update({k: v for k, v in metadata.items() if k not in {"metadata", "task_packet"}})
    game, run = md.get("game_id"), md.get("run_id")
    md.setdefault("trajectory_id", f"{game}__{run}" if game and run else raw_path.stem)
    md.setdefault("run_kind", "project_run" if game and run else "standalone_training_task")
    md.setdefault("collector_version", "codex-rollout-importer.v2")
    md.setdefault("revision", 1)  # first written revision; validator requires >= 1
    md.setdefault("harness", "codex")
    md.setdefault("completeness", "partial")

    raw_by_ordinal = {r.get("ordinal"): r for r in raw_records}
    from pipeline.data_collection.paths import rel_to_repo
    raw_uri = rel_to_repo(raw_path)
    for i, event in enumerate(trajectory.get("events", []), 1):
        event.setdefault("event_id", f"evt_{i:06d}")
        event.setdefault("kind", "tool_call" if event.get("tool_calls") else ("tool_result" if event.get("source") == "tool" else "message"))
        for block in event.get("content", []):
            # Rollout items are the codex runtime's conversation items: they
            # were visible to the model in some round, but the rollout never
            # records which request delivered them. agent_received is a
            # per-request delivery claim, so it is never blanket-assumed here;
            # agent_visible keeps the facts loadable for analysis without
            # feeding them into a fabricated prompt.
            block.setdefault("visibility", "agent_visible")
        # Preserve rollout time and raw provenance: the first contributing
        # ordinal aligns the timestamp; every contributing ordinal is kept as
        # per-event source_refs so a conversion fix can regenerate the
        # trajectory from the rollout without re-running the session.
        ordinals = event.get("ordinals") or []
        if event.get("ts") is None and ordinals and ordinals[0] in raw_by_ordinal:
            event["ts"] = raw_by_ordinal[ordinals[0]].get("timestamp")
        event["source_refs"] = {"uri": raw_uri, "format": "codex-rollout",
                                "positions": list(ordinals)}

    # The rollout format carries no model request boundaries: no round ids, no
    # per-request snapshots — turn_context only marks user submissions and one
    # turn spans several model calls, so an assistant event is NOT a request.
    # Requests are therefore left empty instead of being invented from event
    # order; the event-order grouping survives only as an explicitly derived
    # view (schema §6: derived_views are re-derivable, never model input).
    def _conversation_shaped(event: dict[str, Any]) -> bool:
        return bool(event.get("content") or event.get("tool_calls"))

    rounds: list[dict[str, Any]] = []
    context: list[str] = []
    for event in trajectory.get("events", []):
        if event.get("source") == "assistant":
            rounds.append({"round": len(rounds) + 1,
                           "input_event_ids": list(context),
                           "response_event_ids": [event["event_id"]]})
        if _conversation_shaped(event):
            context.append(event["event_id"])
    return {
        "schema_version": "gamefactory3a.unity-trajectory.v5",
        "metadata": md,
        "task_ref": metadata.get("task_ref"),
        "environment_ref": metadata.get("environment_ref"),
        "tools": trajectory.get("tools", []),
        "tool_sets": {"observed_codex_tools": list(trajectory.get("tools", []))},
        "events": trajectory.get("events", []), "requests": [],
        "workspace": {"file_versions": []}, "verification_refs": [],
        "asset_generations": [],
        "attachments": [{"type": "raw_session", "uri": rel_to_repo(raw_path), "mime_type": "application/json",
                         "sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest()}],
        "training": {"status": "pending", "policy_version": "codex-rollout-import.v2",
                      "group_id": md.get("trajectory_id")},
        "result": trajectory.get("result", {}),
        "derived_views": {
            "tools_used": derive_tools_used(trajectory.get("events", [])),
            "request_reconstruction": {
                "rule": "assistant_event_rounds_v1",
                "boundary": "unknown",
                "note": "derived from rollout event order; codex rollouts record no "
                        "model request boundaries — not request truth, never model input",
                "rounds": rounds,
            },
        },
    }


def partition_rollout(rollout: Path, bindings: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Return task_id -> records. Shared session metadata/messages are copied.

    Calls are assigned using their arguments (normally ``workdir``/paths).
    Results use the call-id map. Unassigned calls are not silently assigned:
    they are returned under ``__unassigned__`` for operator review.
    """
    bindings = _normalize_bindings(bindings)
    out = {str(b["task_id"]): [] for b in bindings}
    out["__unassigned__"] = []
    call_owner: dict[str, str] = {}
    records = [json.loads(x) for x in rollout.read_text(encoding="utf-8").splitlines() if x.strip()]
    for record in records:
        payload = record.get("payload") or {}
        typ = payload.get("type")
        if typ == "function_call":
            owner = _owner(payload, bindings) or "__unassigned__"
            call_id = payload.get("call_id")
            if call_id: call_owner[str(call_id)] = owner
            out[owner].append(record)
        elif typ == "function_call_output":
            owner = call_owner.get(str(payload.get("call_id")), "__unassigned__")
            out[owner].append(record)
        else:
            # Context is shared. Keep it in every task view; it is not a claim
            # that every task caused the message.
            for task_id in out:
                if task_id != "__unassigned__": out[task_id].append(record)
    return out


def write_partitioned(rollout: Path, bindings_path: Path, output_dir: Path) -> dict[str, Path]:
    manifest = json.loads(bindings_path.read_text(encoding="utf-8"))
    bindings = _normalize_bindings(manifest.get("bindings", manifest if isinstance(manifest, list) else []))
    parts = partition_rollout(rollout, bindings)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for task_id, records in parts.items():
        if task_id == "__unassigned__" and not records: continue
        b = next((x for x in bindings if str(x.get("task_id")) == task_id), {})
        stem = "__".join(str(b.get(k, "unknown")) for k in ("game_id", "run_id", "task_kind")) if b else "unassigned"
        path = output_dir / f"{stem}__{task_id}.jsonl"
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
        paths[task_id] = path
    return paths


def convert_partitioned_rollout(
    rollout: Path,
    bindings_path: Path,
    output_dir: Path,
    *,
    max_inline_chars: int = 8192,
    keep_partitioned_jsonl: bool = True,
) -> dict[str, Path]:
    """Partition and convert each task slice into a trajectory JSON.

    Each binding may provide ``meta_json`` and ``task_packet``. Otherwise the
    binding itself is used as metadata. The raw rollout remains the source of
    truth; task JSONL slices are retained by default for auditability.
    """
    from scripts.convert_codex_rollout_to_trajectory import convert
    from pipeline.data_collection.core.artifact_store import ArtifactStore

    manifest = json.loads(bindings_path.read_text(encoding="utf-8"))
    bindings = _normalize_bindings(manifest.get("bindings", manifest if isinstance(manifest, list) else []))
    parts = partition_rollout(rollout, bindings)
    output_dir.mkdir(parents=True, exist_ok=True)
    by_task = {str(b.get("task_id")): b for b in bindings}
    result: dict[str, Path] = {}
    for task_id, records in parts.items():
        if task_id == "__unassigned__":
            if records:
                p = output_dir / f"{rollout.stem}__unassigned.jsonl"
                p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
                result[task_id] = p
            continue
        binding = by_task[task_id]
        raw_path = output_dir / f"{rollout.stem}__{task_id}.jsonl"
        raw_path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
        if keep_partitioned_jsonl:
            result[f"{task_id}:raw"] = raw_path
        meta = dict(binding); meta.update(binding.get("metadata") or {})
        meta_path = binding.get("meta_json")
        if meta_path and Path(meta_path).is_file():
            meta.update(json.loads(Path(meta_path).read_text(encoding="utf-8")))
        packet = None
        packet_path = binding.get("task_packet") or binding.get("task_packet_path")
        if packet_path and Path(packet_path).is_file():
            packet = json.loads(Path(packet_path).read_text(encoding="utf-8"))
        trajectory = convert(raw_path, meta, packet, store=ArtifactStore(), max_inline_chars=max_inline_chars)
        trajectory = _plan_trajectory(trajectory, records, raw_path, meta)
        game = trajectory["metadata"].get("game_id", "unknown")
        run = trajectory["metadata"].get("run_id", "unknown")
        out = output_dir / f"{game}__{run}__{task_id}__trajectory_v1.json"
        out.write_text(json.dumps(trajectory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result[task_id] = out
    return result


def convert_run_rollout(
    rollout: Path,
    bindings_path: Path,
    output_dir: Path,
    *,
    max_inline_chars: int = 8192,
    index_path: Path | None = None,
) -> dict[str, Path]:
    """Create one trajectory JSON per ``(game_id, run_id)`` and update collect.json.

    Parallel tasks of the same run stay in one run trajectory; their task
    identity goes to a sidecar ``<trajectory_id>__task_bindings.json`` audit
    file, not into trajectory metadata (the v1 schema keeps metadata minimal).
    Shared session records are merged back exactly once. Calls that cannot be
    mapped to a task are always written to an unassigned audit JSONL; when the
    session has a single run they also stay in that run trajectory so it stays
    complete, otherwise they are kept out of every run view.
    """
    from scripts.convert_codex_rollout_to_trajectory import convert, validate
    from pipeline.data_collection.core.artifact_store import ArtifactStore
    from pipeline.data_collection.paths import make_trajectory_id, rel_to_repo, collect_json_path

    manifest = json.loads(bindings_path.read_text(encoding="utf-8"))
    bindings = _normalize_bindings(manifest.get("bindings", manifest if isinstance(manifest, list) else []))
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for b in bindings:
        groups.setdefault((str(b.get("game_id", "unknown")), str(b.get("run_id", "unknown"))), []).append(b)
    parts = partition_rollout(rollout, bindings)
    output_dir.mkdir(parents=True, exist_ok=True)

    unassigned = parts.get("__unassigned__", [])
    written: dict[str, Path] = {}
    if unassigned:
        audit = output_dir / f"{rollout.stem}__unassigned.jsonl"
        audit.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in unassigned), encoding="utf-8")
        written["unassigned"] = audit
    sole_run = len(groups) == 1

    index_entries: list[dict[str, Any]] = []
    for (game_id, run_id), group in groups.items():
        slices = [parts.get(str(b.get("task_id")), []) for b in group]
        if sole_run:
            slices.append(unassigned)  # single-run session: ownership is unambiguous
        records = _merge_unique(slices)
        raw = output_dir / f"{make_trajectory_id(game_id, run_id)}__run.jsonl"
        raw.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
        base = dict(group[0]); base.update(group[0].get("metadata") or {})
        meta_path = base.get("meta_json")
        if meta_path and Path(meta_path).is_file():
            base.update(json.loads(Path(meta_path).read_text(encoding="utf-8")))
        packet = None
        pp = base.get("task_packet") or base.get("task_packet_path")
        if pp and Path(pp).is_file(): packet = json.loads(Path(pp).read_text(encoding="utf-8"))
        traj_v1 = convert(raw, base, packet, store=ArtifactStore(), max_inline_chars=max_inline_chars)
        errors = validate(traj_v1)
        if errors:
            raise ValueError(f"trajectory {game_id}__{run_id} failed v1 validation: {errors}")
        traj = _plan_trajectory(traj_v1, records, raw, base)
        out = output_dir / f"{make_trajectory_id(game_id, run_id)}.json"
        out.write_text(json.dumps(traj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written[f"{game_id}::{run_id}"] = out
        bindings_out = output_dir / f"{make_trajectory_id(game_id, run_id)}__task_bindings.json"
        bindings_out.write_text(json.dumps([
            {k: b[k] for k in ("game_id", "run_id", "task_kind", "task_id", "workspace") if k in b}
            for b in group
        ], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written[f"{game_id}::{run_id}::task_bindings"] = bindings_out
        index_entries.append({"trajectory_id": make_trajectory_id(game_id, run_id), "game_id": game_id, "run_id": run_id, "trajectory_path": rel_to_repo(out)})
    if index_path is None: index_path = collect_json_path()
    index_path.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if index_path.exists():
        try: existing = json.loads(index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError: existing = {}
    merged = {str(x.get("trajectory_id")): x for x in existing.get("trajectories", [])}
    merged.update({str(x["trajectory_id"]): x for x in index_entries})
    index_path.write_text(json.dumps({"schema_version":"gamefactory3a.trajectory-index.v1", "trajectories":list(merged.values())}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return written


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Partition one Codex rollout by task workspace")
    p.add_argument("rollout", type=Path)
    p.add_argument("--bindings", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--convert", action="store_true", help="also convert each task slice to trajectory JSON")
    p.add_argument("--run", action="store_true", help="emit one trajectory JSON per game_id/run_id and update collect.json")
    a = p.parse_args(argv)
    paths = convert_run_rollout(a.rollout, a.bindings, a.output_dir) if a.run else (convert_partitioned_rollout(a.rollout, a.bindings, a.output_dir) if a.convert else write_partitioned(a.rollout, a.bindings, a.output_dir))
    for task, path in paths.items(): print(f"{task}: {path}")
    return 0

if __name__ == "__main__": raise SystemExit(main())
