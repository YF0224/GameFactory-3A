"""
pipeline/data_collection/outer_agent_hook.py

Connects the outer-Agent code-generation workflows (mechanic / UI:
``prepare`` → external coding agent works in the workspace → ``finalize``)
and the playtest recorder to the trajectory collector
(collection plan §4/§11).

One trajectory per ``(game_id, run_id)``: the first prepared task creates
it; later tasks in the same run resume it and append their own binding and
prompts. The trajectory closes (honestly ``partial`` — the outer agent's
model session is never seen by this repo) only after every prepared task
has finalized. Facts recorded here:

* ``prepare``  → task binding, system + task prompts as the agent's real
  input events, snapshot reference, run_start / task_prepared telemetry,
  trajectory id written back into each task packet;
* ``finalize`` → real file versions from the manifest diff; one
  collector-side verification event per task (never claimed visible to the
  agent); an explicit missing-marker for the uncaptured outer-agent
  session; run_end telemetry at the final close;
* playtest take → a ``playtest`` event with the recorded artifacts,
  attached to the trajectory derived from the project path (or an explicit
  id), while the trajectory is still open.

Collection never breaks the pipeline: every failure degrades to a disabled
result plus a stderr warning. Disable with ``AAAGF_TRAJECTORY_COLLECT=0``.

Stdlib only.
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path
from typing import Any

from pipeline.common.artifacts import read_json, write_json
from pipeline.common.paths import OUTPUT_ROOT, run_meta_path
from pipeline.data_collection.paths import (
    make_trajectory_id,
    rel_to_repo,
    trajectory_path,
)

from ..core.artifact_store import ArtifactStore
from ..core.collector import Collector, content_block
from ..core.event_writer import now_iso
from ..core.telemetry import TelemetryWriter

_DISABLED_VALUES = {"0", "false", "off", "no"}


def collection_enabled() -> bool:
    value = os.environ.get("AAAGF_TRAJECTORY_COLLECT", "1")
    return value.strip().lower() not in _DISABLED_VALUES


def _warn(message: str) -> None:
    print(f"[data_collection] {message}", file=sys.stderr)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _repo_uri(path: str | Path) -> str:
    return rel_to_repo(Path(path).expanduser().resolve(strict=False))


def _record_prompts(collector: Collector, packet: dict) -> None:
    """The system + task prompts are what the outer agent actually receives."""
    instructions = packet.get("instructions") or {}
    system_prompt = str(instructions.get("system_prompt") or "")
    task_prompt = str(instructions.get("task_prompt") or "")
    repair_prompt = str(instructions.get("repair_prompt") or "")
    if system_prompt:
        collector.record_message("system", text=system_prompt)
    user_prompt = task_prompt
    if repair_prompt:
        user_prompt = f"{user_prompt}\n\n## Repair Guidance\n\n{repair_prompt}"
    if user_prompt:
        collector.record_message("user", text=user_prompt)


def start_code_gen_trajectory(packet: dict, *, collector=None) -> dict:
    """After ``prepare``: open (or resume) this run's trajectory and tag the packet."""
    if collector is not None or os.environ.get("AAAGF_OBSERVATION_SPOOL"):
        return _live_hook("prepare", packet, collector=collector)
    info: dict[str, Any] = {"enabled": False}
    if not collection_enabled():
        info["reason"] = "disabled_by_env"
        return info
    try:
        game_id = str(packet.get("game_id") or "")
        run_id = str(packet.get("run_id") or "")
        if not game_id or not run_id:
            info["reason"] = "packet_missing_game_or_run"
            return info
        artifacts = packet.get("artifacts") or {}
        task_packet_path = Path(
            str(artifacts.get("task_packet_path") or "")
        )
        if not task_packet_path.is_file():
            info["reason"] = "task_packet_not_written"
            return info
        trajectory_id = make_trajectory_id(game_id, run_id)
        task_kind = str(packet.get("task_kind") or "")
        task_id = str(packet.get("task_id") or "")
        binding = {
            "binding_id": f"{task_kind}_{task_id}",
            "game_id": game_id,
            "run_id": run_id,
            "task_kind": task_kind,
            "task_id": task_id,
            "task_packet_uri": _repo_uri(task_packet_path),
            "task_packet_sha256": _sha256_file(task_packet_path),
        }

        path = trajectory_path(trajectory_id)
        resumed = path.exists()
        reopened = False
        if resumed:
            collector = Collector.resume(path)
            already_bound = any(
                (item or {}).get("binding_id") == binding["binding_id"]
                for item in collector.trajectory.get("task_bindings") or []
            )
            # Interleaved flow (repo order: UI prepares only after the
            # mechanic finalize): the log may already carry a close result.
            # Continuing is a new fact, recorded as an event — history is
            # never rewritten.
            reopened = collector.trajectory.get("result") is not None
        else:
            collector = Collector.start(
                {
                    "game_id": game_id,
                    "run_id": run_id,
                    "case_id": task_id,
                    "engine": str(packet.get("engine") or ""),
                },
                task_ref={
                    "uri": _repo_uri(task_packet_path),
                    "sha256": _sha256_file(task_packet_path),
                    "note": "code-gen task packet (requirement/context/boundaries)",
                },
                environment_ref={
                    "uri": _repo_uri(task_packet_path),
                    "workspace": _repo_uri(packet.get("workspace")),
                    "engine": str(packet.get("engine") or ""),
                    "engine_context_root": str(
                        (packet.get("context") or {}).get("engine_context_root") or ""
                    ),
                    "allowed_write_root": str(
                        (packet.get("boundaries") or {}).get("allowed_write_root") or ""
                    ),
                },
                artifact_store=ArtifactStore(),
            )
            already_bound = False

        if not already_bound:
            collector.record_task_binding(binding)
            if reopened:
                collector.record_event(
                    "tool",
                    "runtime",
                    producer="outer_agent_hook",
                    note="run_continued_with_new_task_after_finalize",
                    task_kind=task_kind,
                    task_id=task_id,
                )
            _record_prompts(collector, packet)
            snapshot_path = artifacts.get("workspace_snapshot_path")
            if snapshot_path:
                snapshot_ref = {
                    "uri": _repo_uri(snapshot_path),
                    "sha256": _sha256_file(Path(snapshot_path)),
                    "mime_type": "application/json",
                    "source": "prepare_workspace_snapshot",
                    "task_kind": task_kind,
                    "task_id": task_id,
                }
                if resumed:
                    # The run-level initial_state_ref belongs to the first
                    # task; later tasks keep their snapshot as an attachment.
                    collector.record_attachment(dict(snapshot_ref))
                else:
                    collector.record_initial_state(
                        {
                            "uri": snapshot_ref["uri"],
                            "sha256": snapshot_ref["sha256"],
                            "note": "prepare workspace snapshot "
                            "(hash manifest, not a content backup)",
                        }
                    )

        telemetry = TelemetryWriter(run_meta_path(game_id, run_id))
        if resumed:
            if not already_bound:
                telemetry.record_event(
                    "task_prepared", task_kind=task_kind, task_id=task_id
                )
        else:
            telemetry.record_run_start(
                task_id=task_id,
                engine=str(packet.get("engine") or ""),
                mode=str(packet.get("mode") or ""),
            )
            collector.add_telemetry_ref(
                {
                    "uri": _repo_uri(run_meta_path(game_id, run_id)),
                    "container": "run_meta.json.telemetry",
                    "scope": "run",
                }
            )

        info.update(
            {
                "enabled": True,
                "trajectory_id": trajectory_id,
                "trajectory_path": rel_to_repo(collector.writer.path),
                "resumed": resumed,
            }
        )
        # Persist the link back into the packet so finalize can resume.
        on_disk = read_json(
            task_packet_path, "Prepared code-gen task packet"
        )
        on_disk["trajectory"] = dict(info)
        write_json(task_packet_path, on_disk)
    except Exception as exc:  # never break the pipeline for collection
        info = {"enabled": False, "reason": f"start_failed: {exc}"}
        _warn(f"trajectory collection skipped for this run: {exc}")
    return info


def finalize_code_gen_trajectory(
    packet_path: str | Path,
    finalize_result: dict,
    collector=None,
) -> dict:
    """After ``finalize``: record this task's facts; close when the run is done."""
    if collector is not None or os.environ.get("AAAGF_OBSERVATION_SPOOL"):
        return _live_hook("finalize", finalize_result, collector=collector)
    info: dict[str, Any] = {"enabled": False}
    if not collection_enabled():
        info["reason"] = "disabled_by_env"
        return info
    try:
        packet = read_json(
            Path(packet_path), "Prepared code-gen task packet"
        )
        link = packet.get("trajectory") or {}
        trajectory_id = str(link.get("trajectory_id") or "")
        if not link.get("enabled") or not trajectory_id:
            info["reason"] = "trajectory_not_started_at_prepare"
            return info
        path = trajectory_path(trajectory_id)
        if not path.exists():
            info["reason"] = "trajectory_file_missing"
            return info

        collector = Collector.resume(path)
        store = ArtifactStore()
        workspace = Path(str(finalize_result.get("workspace") or ""))

        for relative in finalize_result.get("generated_files") or []:
            collector.record_workspace_change(
                str(relative),
                "create",
                content_path=workspace / str(relative),
                store=store,
            )
        for relative in finalize_result.get("modified_files") or []:
            collector.record_workspace_change(
                str(relative),
                "modify",
                content_path=workspace / str(relative),
                store=store,
            )
        for relative in finalize_result.get("deleted_files") or []:
            collector.record_workspace_change(str(relative), "delete")

        checks = dict(finalize_result.get("required_artifact_checks") or {})
        results = {
            "checks": checks,
            "generated": len(finalize_result.get("generated_files") or []),
            "modified": len(finalize_result.get("modified_files") or []),
            "deleted": len(finalize_result.get("deleted_files") or []),
            "errors": list(finalize_result.get("errors") or []),
        }
        evidence = finalize_result.get("finalize_result_path")
        if evidence:
            results["evidence_uri"] = _repo_uri(evidence)
        collector.record_verification(
            f"{str(packet.get('task_kind') or 'code_gen')}_finalize_checks",
            results,
            producer="finalize_runner",
            origin="finalize",
            visibility="collector_only",  # agent session over; never shown
        )

        # This task's outer-agent session happened outside this process:
        # record the gap honestly instead of fabricating requests.
        collector.record_missing_event(
            "tool",
            reason="outer_agent_model_session_not_captured",
            producer="outer_agent_harness",
        )

        # Mark this task's binding finalized; the run closes only when every
        # prepared task is done (mechanic and UI may finish in any order).
        binding_id = (
            f"{packet.get('task_kind')}_{packet.get('task_id')}"
        )
        bindings = collector.trajectory.get("task_bindings") or []
        marked = False
        for item in bindings:
            if item.get("binding_id") == binding_id:
                item["finalized"] = {
                    "ok": bool(finalize_result.get("ok")),
                    "status": str(finalize_result.get("status") or ""),
                    "at": now_iso(),
                }
                marked = True
        run_complete = bool(bindings) and all(
            item.get("finalized") for item in bindings
        )
        if not marked:
            # Trajectory predates task bindings (legacy single-task flow).
            run_complete = True
        collector.writer.checkpoint()

        game_id = str(packet.get("game_id") or "")
        run_id = str(packet.get("run_id") or "")
        if run_complete:
            if game_id and run_id:
                TelemetryWriter(run_meta_path(game_id, run_id)).record_run_end(
                    status=str(finalize_result.get("status") or "")
                )
            collector.finish(
                {
                    "ok": bool(finalize_result.get("ok")),
                    "status": str(finalize_result.get("status") or "completed"),
                    "stop_reason": "code_gen_finalize",
                },
                completeness="partial",  # model interactions were never captured
            )
            info = {
                "enabled": True,
                "trajectory_id": trajectory_id,
                "closed": "partial",
            }
        else:
            info = {
                "enabled": True,
                "trajectory_id": trajectory_id,
                "closed": None,
                "pending_tasks": [
                    str(item.get("binding_id"))
                    for item in bindings
                    if not item.get("finalized")
                ],
            }
    except Exception as exc:  # never break the pipeline for collection
        info = {"enabled": False, "reason": f"finalize_failed: {exc}"}
        _warn(f"trajectory finalize hook failed: {exc}")
    return info


def _trajectory_id_from_project(project_path: str | Path) -> str | None:
    """Derive ``<game_id>__<run_id>`` from a project path under the outputs root.

    Handles both the configured ``$AAAGF_OUTPUT_ROOT`` (whatever its name)
    and the default repo layout containing an ``outputs/`` component.
    """
    resolved = Path(project_path).expanduser().resolve(strict=False)
    try:
        relative = resolved.relative_to(
            Path(OUTPUT_ROOT).expanduser().resolve(strict=False)
        )
    except ValueError:
        relative = None
    if relative is not None and len(relative.parts) >= 2:
        game_id, run_id = relative.parts[0], relative.parts[1]
        if game_id and run_id:
            return make_trajectory_id(game_id, run_id)
    parts = resolved.parts
    if "outputs" in parts:
        index = len(parts) - 1 - parts[::-1].index("outputs")
        if index + 2 < len(parts):
            game_id, run_id = parts[index + 1], parts[index + 2]
            if game_id and run_id:
                return make_trajectory_id(game_id, run_id)
    return None


def record_playtest_take(
    project_path: str | Path,
    record_result: dict,
    *,
    trajectory_id: str | None = None,
    collector=None,
) -> dict:
    """After a playtest recording: attach the take to the matching trajectory.

    The trajectory is resolved from the explicit id or derived from an
    ``outputs/<game_id>/<run_id>/...`` project path; recordings of unrelated
    projects are skipped, never misfiled. The take is appended as a
    ``playtest`` event with agent-visible evidence blocks (recording files
    stay where the recorder wrote them). Takes land whenever the trajectory
    exists — including after the run closed, where they remain post-close
    facts and the run result is never rewritten.
    """
    if collector is not None or os.environ.get("AAAGF_OBSERVATION_SPOOL"):
        return _live_hook("playtest", record_result, collector=collector)
    info: dict[str, Any] = {"enabled": False}
    if not collection_enabled():
        info["reason"] = "disabled_by_env"
        return info
    try:
        resolved = trajectory_id or _trajectory_id_from_project(project_path)
        if not resolved:
            info["reason"] = "trajectory_unresolved"
            return info
        path = trajectory_path(resolved)
        if not path.exists():
            info["reason"] = "trajectory_file_missing"
            return info
        collector = Collector.resume(path)

        summary: dict[str, Any] = {}
        for key in (
            "ok",
            "operation",
            "engine",
            "output_dir",
            "duration",
            "fps",
            "width",
            "height",
            "warmup",
        ):
            value = record_result.get(key)
            if value is not None:
                summary[key] = value
        for key in ("errors", "warnings"):
            sequence = record_result.get(key)
            if isinstance(sequence, (list, tuple)):
                summary[key] = [str(item) for item in sequence]
        blocks = [
            content_block(
                "json",
                data=summary,
                mime_type="application/json",
                visibility="agent_visible",
            )
        ]
        output_dir = record_result.get("output_dir")
        if output_dir:
            out = Path(output_dir).expanduser().resolve(strict=False)
            for name, block_type, mime in (
                ("video.mp4", "video", "video/mp4"),
                ("report.json", "json", "application/json"),
            ):
                candidate = out / name
                if candidate.is_file():
                    reference = {
                        "uri": _repo_uri(candidate),
                        "sha256": _sha256_file(candidate),
                        "mime_type": mime,
                        "source": "playtest_take",
                    }
                    collector.record_attachment(dict(reference))
                    blocks.append(
                        content_block(
                            block_type,
                            uri=reference["uri"],
                            mime_type=mime,
                            sha256=reference["sha256"],
                            visibility="agent_visible",
                        )
                    )
        event_id = collector.record_event(
            "tool",
            "playtest",
            content=blocks,
            producer="playtest_recorder",
        )
        info = {
            "enabled": True,
            "trajectory_id": resolved,
            "event_id": event_id,
        }
    except Exception as exc:  # never break the recording pipeline
        info = {"enabled": False, "reason": f"record_failed: {exc}"}
        _warn(f"playtest take not attached to a trajectory: {exc}")
    return info


def _live_hook(kind, payload, *, collector=None):
    """Live-only path: observe in the existing episode, never resume/finish its Writer.

    Standalone hooks retain their legacy lifecycle. Live observations do not
    claim request visibility or bind verification to a guessed workspace state.
    """
    from .observation_spool import SpoolSink
    from .collector_sink import as_sink
    own = collector is None
    sink = SpoolSink.from_environment() if own else as_sink(collector)
    try:
        md = sink.trajectory["metadata"]
        info = {"enabled": True, "trajectory_id": md["trajectory_id"],
                "trajectory_path": rel_to_repo(sink.writer.path), "live": True}
        if kind == "prepare":
            binding = {"binding_id": f"{payload.get('task_kind')}_{payload.get('task_id')}",
                       "task_kind": payload.get("task_kind"), "task_id": payload.get("task_id")}
            sink.record_task_binding(binding)
            sink.record_event("tool", "runtime", producer="outer_agent_hook", operation="task_prepared", **binding)
            packet_path = (payload.get("artifacts") or {}).get("task_packet_path")
            if packet_path and Path(packet_path).is_file():
                packet = read_json(Path(packet_path), "Prepared code-gen task packet")
                packet["trajectory"] = info
                write_json(Path(packet_path), packet)
        elif kind == "finalize":
            root = Path(payload.get("workspace") or ".").resolve()
            for key, operation in (("generated_files", "create"), ("modified_files", "modify"), ("deleted_files", "delete")):
                for relative in payload.get(key) or []:
                    path = (root / relative).resolve()
                    if not path.is_relative_to(root):
                        raise ValueError("finalize file escapes workspace")
                    sink.record_workspace_change(str(relative), operation,
                        **({"content_path": path} if operation != "delete" else {}))
            sink.record_verification("code_gen_finalize_checks",
                {"checks": payload.get("required_artifact_checks", {}), "errors": payload.get("errors", [])},
                producer="finalize_runner", visibility="collector_only", origin="finalize")
        elif kind == "playtest":
            summary = {k: payload[k] for k in ("ok", "operation", "engine", "duration", "fps", "errors", "warnings") if k in payload}
            blocks = [content_block("json", data=summary, visibility="collector_only")]
            output = payload.get("output_dir")
            if output:
                for name, typ, mime in (("video.mp4", "video", "video/mp4"), ("report.json", "json", "application/json")):
                    path = Path(output) / name
                    if path.is_file():
                        ref = sink.artifact_store.put_file(path, mime_type=mime)
                        sink.record_attachment(ref)
                        blocks.append(content_block(typ, uri=ref["uri"], sha256=ref["sha256"], mime_type=mime, visibility="collector_only"))
            info["event_id"] = sink.record_event("tool", "playtest", content=blocks, producer="playtest_recorder")
        return info
    except Exception as exc:
        # Hook failures stay non-fatal to the existing execution pipeline.
        try:
            sink.record_event("system", "runtime", producer="outer_agent_hook", audit_code="hook_observation_failed", error=str(exc))
        except Exception:
            _warn(f"live hook capture failed: {exc}")
        return {"enabled": False, "reason": str(exc)}
    finally:
        if own: sink.close()
