"""Sidecar observation of an external Codex session's rollout.

The agent (Codex CLI) is an unmodifiable black box working in the workspace;
this sidecar never starts, steers, or interrupts it. Codex keeps exactly one
append-only rollout per session under ``~/.codex/sessions/YYYY/MM/DD/``, so
— unlike the Codely autosave, which the agent rewrites as it works — there
is nothing to re-import and no snapshot bookkeeping: the
:class:`~pipeline.data_collection.adapters.codex_session.RolloutObserver`
consumes new complete lines incrementally and assembles the SAME verified
``token_usage_record`` request boundaries the companion recovery uses.

One run, one trajectory, one writer: the sidecar holds the only Collector.
Attribution is session-precise by the caller-supplied session id (the
rollout filename uuid); an external session's request boundary is never
fully observable from the outside, so the trajectory stays honestly
``partial`` (schema §5.1).
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from pipeline.data_collection.paths import make_trajectory_id, trajectory_path

from ..adapters.codex_session import (DEFAULT_SESSIONS_ROOT, RolloutObserver,
                                      find_rollout_for_thread)
from ..adapters.codely_autosave import (derive_tools_used, portable_uri,
                                        sanitize_trajectory_paths)
from ..core.artifact_store import ArtifactStore
from ..core.collector import Collector, content_block, add_identity_arguments
from ..core.collector_sink import CollectorSink
from ..core.errors import CaptureError
from .environment import capture_environment
from ..quality.validator import validate_trajectory
from ..core.workspace_tracker import WorkspaceObserver

#: How long finish() keeps draining the rollout's final flush before it
#: closes the trajectory with the facts already collected (audited, never
#: fatal) — rollouts append the last records at session end.
FINISH_DRAIN_SECONDS = 1.0


def _safe_print(message: str) -> None:
    """Best-effort console output (same policy as the codely sidecar)."""
    try:
        print(message, flush=True)
    except (OSError, ValueError):
        pass


class CodexRolloutCollector:
    """Observe one external Codex session into one open trajectory."""

    def __init__(
        self,
        *,
        game_id: str,
        run_id: str,
        workspace: str | Path,
        session_id: str,
        sessions_root: str | Path | None = None,
        engine: str | None = None,
        trajectory: str | Path | None = None,
        register: bool = True,
        skip_environment: bool = False,
        interval: float = 2.0,
        extra_metadata: dict | None = None,
        artifact_store: Any = None,
    ):
        self.game_id, self.run_id = game_id, run_id
        self.session_id = session_id
        self.engine = engine
        self.register = register
        self.skip_environment = skip_environment
        self.interval = interval
        self.extra_metadata = dict(extra_metadata or {})
        self.workspace = Path(workspace).expanduser().resolve(strict=False)
        self.sessions_root = (Path(sessions_root).expanduser()
                               if sessions_root else DEFAULT_SESSIONS_ROOT)
        self.trajectory_path = Path(trajectory) if trajectory else trajectory_path(
            make_trajectory_id(game_id, run_id))
        self.store = artifact_store or ArtifactStore()
        self.collector: Collector | None = None
        self.observer: RolloutObserver | None = None
        self._workspace_observer: WorkspaceObserver | None = None
        self._observer_failed = False
        self._missing_audited = False
        self._last_rollout: Path | None = None

    # ── lifecycle ─────────────────────────────────────────────────────────

    def start(self) -> "CodexRolloutCollector":
        for excluded in (self.trajectory_path.parent, self.store.root):
            if self.workspace == excluded or self.workspace.is_relative_to(excluded):
                raise ValueError(
                    f"workspace {self.workspace} must not live inside an excluded path "
                    f"({excluded}); move the trajectory or the blob store")
        metadata = {
            "game_id": self.game_id,
            "run_id": self.run_id,
            "run_kind": "project_run",
            "harness": "codex",
            "collector_version": "codex-rollout-sidecar.v1",
        }
        metadata.update(self.extra_metadata)
        environment_ref: dict = {}
        if not self.skip_environment:
            environment_ref = capture_environment(
                agent="codex", engine=self.engine,
                workspace=str(self.workspace), artifact_store=self.store)
        self.collector = Collector.start(
            metadata, environment_ref=environment_ref,
            path=self.trajectory_path, artifact_store=self.store,
            register=self.register, exclusive=True)
        self.observer = RolloutObserver(self.collector,
                                        session_id=self.session_id,
                                        assemble_requests=True)
        self._workspace_observer = WorkspaceObserver(
            CollectorSink(self.collector), self.workspace,
            excluded=(self.trajectory_path.parent, self.store.root))
        self._observe_workspace()  # baseline before the session's first change
        return self

    def _observe_workspace(self, *, final=False) -> None:
        """Poll the workspace observer; a broken observer degrades, never kills."""
        if self._workspace_observer is None or self._observer_failed:
            return
        try:
            self._workspace_observer.poll(final=final)
        except CaptureError:
            raise  # collector persistence failure is fatal to the whole run
        except Exception as exc:
            self._observer_failed = True
            assert self.collector is not None
            self.collector.record_event("system", "runtime",
                producer="codex_rollout_collector",
                audit_code="filesystem_observer_failed",
                content=[content_block("json", data={"error": str(exc)},
                                       visibility="collector_only")])

    def poll_once(self) -> dict[str, Any]:
        """One observation cycle: workspace poll + rollout incremental read."""
        assert self.collector is not None and self.observer is not None
        self._observe_workspace()
        rollout = find_rollout_for_thread(self.session_id,
                                          sessions_root=self.sessions_root)
        if rollout is None:
            # the rollout appears when the session starts; audit the wait once
            if not self._missing_audited:
                self._missing_audited = True
                self.collector.record_event("system", "runtime",
                    producer="codex_rollout_collector",
                    audit_code="rollout_not_found_yet",
                    content=[content_block("json",
                        data={"session_id": self.session_id,
                              "sessions_root": portable_uri(str(self.sessions_root))},
                        visibility="collector_only")])
            return {"rollout": None, "appended_events": 0, "new_requests": 0}
        self._last_rollout = rollout
        before_events = self.observer.report["appended_events"]
        before_requests = self.observer.report["new_requests"]
        report = self.observer.observe(rollout)
        return {"rollout": rollout.name,
                # per-poll deltas: the underlying observer report is cumulative
                "appended_events": report["appended_events"] - before_events,
                "new_requests": report["new_requests"] - before_requests,
                "usage_records": len(report["usage_records"])}

    def finish(self, status: str = "completed", reason: str | None = None) -> Path:
        """Final drain, tool layer, derived summary, raw rollout, close."""
        assert self.collector is not None and self.observer is not None
        self._observe_workspace(final=True)
        # bounded final drain: the rollout's last records land at session end
        deadline = time.monotonic() + FINISH_DRAIN_SECONDS
        last_lines = -1
        rollout = find_rollout_for_thread(self.session_id,
                                          sessions_root=self.sessions_root)
        while rollout is not None and time.monotonic() < deadline:
            report = self.observer.observe(rollout)
            if report["lines"] == last_lines:
                break
            last_lines = report["lines"]
            time.sleep(0.1)
        trajectory = self.collector.trajectory
        # tool layer: derived from the calls actually observed (the rollout
        # persists no registry) — same honest source as every codex view
        if self._last_rollout is not None:
            try:
                from scripts.convert_codex_rollout_to_trajectory import build_tools
                records = [json.loads(line) for line in self._last_rollout.read_text(
                    encoding="utf-8", errors="replace").splitlines() if line.strip()]
                tools = build_tools(records)
                if tools:
                    self.collector.record_tools(tools)
                    self.collector.record_tool_set("observed_codex_tools", tools)
                    self.collector.record_event("system", "runtime",
                        producer="codex_rollout_collector",
                        audit_code="tools_from_observed_calls",
                        content=[content_block("json",
                            data={"definitions": len(tools),
                                  "source": "function_call arguments in the rollout; "
                                            "the rollout persists no tool registry"},
                            visibility="collector_only")])
            except (OSError, ValueError):
                pass  # the tool layer is supplementary; facts stay recorded
        trajectory["derived_views"]["tools_used"] = derive_tools_used(trajectory["events"])
        sanitized = sanitize_trajectory_paths(trajectory, workspace=str(self.workspace))
        if sanitized:
            self.collector.record_event("system", "runtime",
                producer="codex_rollout_collector",
                audit_code="paths_sanitized_for_portability",
                content=[content_block("json", data={"fields": sanitized},
                                       visibility="collector_only")])
        if self._last_rollout is not None:
            try:
                stored = self.store.put_file(self._last_rollout,
                                             mime_type="application/x-ndjson")
                self.collector.record_attachment({
                    "type": "raw_session",
                    "uri": stored["uri"], "sha256": stored["sha256"],
                    "mime_type": stored["mime_type"],
                    "size_bytes": stored.get("size_bytes")})
            except OSError:
                pass  # audited by the run_meta report; never fatal
        result: dict[str, Any] = {"ok": status == "completed", "status": status}
        if reason:
            result["stop_reason"] = reason
        # an external session's request context is never fully observable:
        # the trajectory stays honestly partial
        return self.collector.finish(result, completeness="partial")

    def run(self) -> Path:
        """Observe until interrupted (Ctrl-C); finalize gracefully."""
        self.start()
        status, reason = "interrupted", "keyboard_interrupt"
        failure: BaseException | None = None
        try:
            while True:
                report = self.poll_once()
                if report.get("appended_events") or report.get("new_requests"):
                    _safe_print(f"[codex_sidecar] +{report['appended_events']} events, "
                               f"+{report['new_requests']} requests "
                               f"({report.get('rollout')})")
                time.sleep(self.interval)
        except KeyboardInterrupt:
            _safe_print("[codex_sidecar] interrupted; finalizing partial trajectory")
        except Exception as exc:
            _safe_print(f"[codex_sidecar] observation loop failed: {exc!r}; "
                        "finalizing partial trajectory")
            status, reason, failure = "error", "observation_loop_failed", exc
        try:
            return self.finish(status=status, reason=reason)
        finally:
            if self.collector is not None:
                self.collector.writer.close()
            if failure is not None:
                raise failure


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Observe an external codex session's rollout; one live "
                    "trajectory per run (session-precise attribution by id)")
    parser.add_argument("--game-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--workspace", type=Path, required=True,
                        help="The project directory the agent works in")
    parser.add_argument("--session-id", required=True,
                        help="The observed session's id — the rollout filename "
                             "carries it (thread-precise, never a guess)")
    parser.add_argument("--sessions-root", type=Path, default=None,
                        help="Codex sessions root (default ~/.codex/sessions)")
    parser.add_argument("--engine", default=None,
                        help="Engine name for the environment snapshot, e.g. unity3d")
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--trajectory", type=Path, default=None,
                        help="Default: train_data/trajectories/<game_id>__<run_id>.json")
    parser.add_argument("--register", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--no-environment", action="store_true")
    add_identity_arguments(parser)
    from ..core.collector import identity_metadata
    args = parser.parse_args(argv)
    collector = CodexRolloutCollector(
        game_id=args.game_id, run_id=args.run_id, workspace=args.workspace,
        session_id=args.session_id, sessions_root=args.sessions_root,
        engine=args.engine, trajectory=args.trajectory,
        register=args.register, skip_environment=args.no_environment,
        interval=args.interval, extra_metadata=identity_metadata(vars(args)))
    path = collector.run()
    trajectory = json.loads(Path(path).read_text(encoding="utf-8"))
    report = validate_trajectory(trajectory)
    print(f"trajectory: {path}")
    print(f"events={len(trajectory['events'])} requests={len(trajectory['requests'])} "
          f"tools_used={trajectory['derived_views'].get('tools_used')}")
    print(f"validator: ok={report['ok']} errors={len(report['errors'])} "
          f"warnings={len(report['warnings'])}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
