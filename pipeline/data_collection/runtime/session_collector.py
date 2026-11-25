"""
pipeline/data_collection/session_collector.py

Sidecar collector for an external coding agent's game-generation session.

The agent (Codely / Codex / Claude Code) is an unmodifiable black box that
reads ``agent_skills/`` and works in the workspace; this sidecar never
starts, steers, or interrupts it. It observes the three facts the repo can
own (collection plan §4.3):

* the agent's own session export (autosave) — the canonical model-interaction
  source, imported incrementally as the agent rewrites it;
* the workspace filesystem — immutable file versions via WorkspaceObserver;
* the collector host environment — one scoped snapshot at start.

One run, one trajectory, one writer: the sidecar holds the only Collector;
nothing else opens the canonical trajectory file. Inputs reconstructed from
event order are labeled ``input_reconstruction`` and the trajectory stays
honestly ``partial`` — an external agent's request boundary is never fully
observable from the outside (schema §5.1, plan §4.3).

Observation limit: the autosave is re-imported as it changes, so polling may
miss intermediate snapshots — this is incremental observation of the agent's
session export, not a lossless real-time tool stream. Sidecar support is per
implemented session importer (:data:`SESSION_IMPORTERS`), not per headless
adapter registration.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from pipeline.data_collection.paths import make_trajectory_id, trajectory_path

from ..adapters.codely_autosave import (
    derive_tools_used,
    portable_uri,
    sanitize_trajectory_paths,
)
from ..core.artifact_store import ArtifactStore
from ..adapters.codely_autosave import AutosaveSessionImporter, _doc_model
from ..core.collector import Collector, add_identity_arguments, content_block, identity_metadata
from ..core.collector_sink import CollectorSink
from ..core.errors import CaptureError
from .environment import capture_environment
from ..quality.validator import validate_trajectory
from ..core.workspace_tracker import WorkspaceObserver

#: Sidecar support matrix: agent -> session importer actually implemented.
#: Registering a headless adapter does NOT imply sidecar support; a new
#: agent enters here only when its session export can be incrementally read.
SESSION_IMPORTERS = {"codely": AutosaveSessionImporter}

#: How long finish() keeps retrying a torn final export before it closes the
#: trajectory with the facts already collected (audited, never fatal).
FINISH_DRAIN_SECONDS = 1.0


def _safe_print(message: str) -> None:
    """Best-effort console output.

    Finalization must never depend on stdout health: an orphaned sidecar's
    stdout pipe can already be broken by the time SIGINT arrives, and letting
    that BrokenPipeError escape the KeyboardInterrupt handler would skip the
    entire finalize path (observed live: result never written).
    """
    try:
        print(message, flush=True)
    except (OSError, ValueError):
        pass


class SessionCollector:
    def __init__(
        self,
        *,
        game_id: str,
        run_id: str,
        workspace: str | Path,
        autosave_dir: str | Path,
        engine: str | None = None,
        agent: str = "codely",
        autosave_pattern: str = "chat-auto-save-*.json",
        trajectory: str | Path | None = None,
        artifact_store: Any = None,
        register: bool = True,
        skip_environment: bool = False,
        interval: float = 2.0,
        snapshot_store: Any = None,
        extra_metadata: dict | None = None,
    ):
        self.game_id, self.run_id = game_id, run_id
        self.agent = agent
        self.engine = engine
        self.autosave_pattern = autosave_pattern
        self.register = register
        self.skip_environment = skip_environment
        self.interval = interval
        self.snapshot_store = snapshot_store
        self.extra_metadata = dict(extra_metadata or {})
        self.workspace = Path(workspace).expanduser().resolve(strict=False)
        self.autosave_dir = Path(autosave_dir).expanduser().resolve(strict=False)
        self.trajectory_path = Path(trajectory) if trajectory else trajectory_path(
            make_trajectory_id(game_id, run_id)
        )
        self.store = artifact_store or ArtifactStore()
        self._last_signature: tuple | None = None
        self._last_autosave: Path | None = None
        self._last_system_prompt: str | None = None
        self._last_system_ref: dict | None = None
        self._unreadable_signature: tuple | None = None
        self._observer_failed = False
        self.collector: Collector | None = None
        self.importer: AutosaveSessionImporter | None = None
        self.observer: WorkspaceObserver | None = None

    # ── lifecycle ─────────────────────────────────────────────────────────

    def start(self) -> "SessionCollector":
        if self.agent not in SESSION_IMPORTERS:
            raise ValueError(
                f"sidecar collection for {self.agent!r} is not implemented yet; "
                f"implemented: {tuple(sorted(SESSION_IMPORTERS))}"
            )
        for excluded in (self.trajectory_path.parent, self.store.root):
            if self.workspace == excluded or self.workspace.is_relative_to(excluded):
                raise ValueError(
                    f"workspace {self.workspace} must not live inside an excluded path "
                    f"({excluded}); move the trajectory or the blob store"
                )
        metadata = {
            "game_id": self.game_id,
            "run_id": self.run_id,
            "run_kind": "project_run",
            "harness": self.agent,
            "collector_version": "session-collector.v1",
        }
        metadata.update(self.extra_metadata)
        environment_ref: dict = {}
        if not self.skip_environment:
            environment_ref = capture_environment(
                agent=self.agent,
                engine=self.engine,
                workspace=str(self.workspace),
                artifact_store=self.store,
            )
        self.collector = Collector.start(
            metadata,
            environment_ref=environment_ref,
            path=self.trajectory_path,
            artifact_store=self.store,
            register=self.register,
            exclusive=True,
        )
        self.importer = AutosaveSessionImporter(self.collector)
        self.observer = WorkspaceObserver(
            CollectorSink(self.collector),
            self.workspace,
            excluded=(self.trajectory_path.parent, self.store.root),
        )
        self._observe_workspace()  # baseline before the agent's first change
        return self

    def _observe_workspace(self, *, final=False) -> None:
        """Poll the workspace observer; a broken observer degrades, never kills.

        Filesystem observation is secondary to the session export: on the
        first failure the observer is disabled for the rest of the run (same
        policy as the live runner) and collection continues autosave-only.
        """
        if self.observer is None or self._observer_failed:
            return
        try:
            self.observer.poll(final=final)
        except CaptureError:
            raise  # collector persistence failure is fatal to the whole run
        except Exception as exc:
            self._observer_failed = True
            assert self.collector is not None
            self.collector.record_event("system", "runtime",
                producer="session_collector", audit_code="filesystem_observer_failed",
                content=[content_block("json", data={"error": str(exc)},
                                       visibility="collector_only")])

    def _latest_autosave(self) -> Path | None:
        latest, newest = None, None
        for path in self.autosave_dir.glob(self.autosave_pattern):
            try:
                if not path.is_file():
                    continue
                mtime = path.stat().st_mtime
            except OSError:
                continue  # vanished between listing and stat; next poll retries
            if newest is None or mtime > newest:
                latest, newest = path, mtime
        return latest

    def poll_once(self) -> dict:
        """One observation cycle: workspace poll + autosave import if changed."""
        assert self.observer is not None and self.importer is not None
        self._observe_workspace()
        return self._import_latest_autosave()

    def _import_latest_autosave(self, *, events: bool = True) -> dict[str, Any]:
        """Import the newest session export if it changed; never raise on a torn read.

        The agent rewrites the export while it works, so a poll can catch it
        mid-write: the unreadable state is audited (once per file state) and
        retried by the next cycle instead of killing the sidecar.
        """
        report: dict[str, Any] = {"autosave": None, "appended_events": 0,
                                  "new_requests": 0, "history_mutated": False,
                                  "session_changed": False, "autosave_unreadable": False}
        assert self.collector is not None and self.importer is not None
        latest = self._latest_autosave()
        if latest is None:
            return report
        try:
            stat = latest.stat()
        except OSError as exc:
            self._audit_unreadable(latest, (str(latest), "stat"), str(exc))
            report["autosave_unreadable"] = True
            return report
        signature = (str(latest), stat.st_mtime_ns, stat.st_size, stat.st_ino)
        if signature == self._last_signature:
            return report
        try:
            raw_snapshot = latest.read_bytes()
            doc = json.loads(raw_snapshot.decode("utf-8"))
            after = latest.stat()
        except (OSError, ValueError) as exc:
            # OSError: the export vanished/replaced mid-poll; ValueError:
            # torn JSON or torn UTF-8 (transient while it is rewritten).
            self._audit_unreadable(latest, signature, str(exc))
            report["autosave_unreadable"] = True
            return report
        if (after.st_mtime_ns, after.st_size, after.st_ino) != (
            stat.st_mtime_ns, stat.st_size, stat.st_ino
        ):
            # The export was replaced between stat and read: the parsed bytes
            # may be stale for this signature, and pinning the new signature to
            # old content would make every later poll skip the new version.
            # Audit, import nothing, and let the next cycle (or the finish
            # drain) retry the now-current file.
            self._audit_unreadable(latest, signature,
                "unstable autosave observation (rewritten mid-poll)",
                code="unstable_autosave_observation")
            report["autosave_unreadable"] = True
            return report
        system = (((doc.get("prefixContext") or {}).get("systemPrompt") or {})
                  .get("dynamic") or {}).get("joinedText")
        if system:
            # Stash the session's real system prompt for the companion build:
            # the journal carries none, and the interactive chain imports the
            # exit autosave's tool layer only.
            self._last_system_prompt = system
        else:
            # Verified CLI shape: no dynamic prompt text means the export
            # carries the static core prompt as a hash reference only — keep
            # the reference for the companion build; the text never exists
            # to import.
            static = ((doc.get("prefixContext") or {}).get("systemPrompt") or {}).get("static")
            if isinstance(static, dict) and static.get("hash"):
                self._last_system_ref = static
        if self.snapshot_store is not None:
            stored = self.snapshot_store.put(raw_snapshot, ext=".json", mime_type="application/json")
            self.collector.record_attachment({"type": "raw_session_snapshot", **stored})
        if events:
            applied = self.importer.update(
                doc, source_uri=portable_uri(str(latest), workspace=str(self.workspace)))
        else:
            # Journal-sourced interactive runs take only the tool layer from
            # the exit autosave: observed facts already came from the
            # live-session journal and must not be imported twice.
            self.importer.import_tools(doc)
            applied = {"appended_events": 0, "new_requests": 0}
        self._unreadable_signature = None
        # The model id is only known once the agent's export exists; keep it
        # in metadata for index/inspection, once, from the session record.
        metadata = self.collector.trajectory["metadata"]
        if "model" not in metadata:
            model = _doc_model(doc, doc.get("conversationRecord") or {})
            if model:
                metadata["model"] = model
        self._last_signature = signature
        self._last_autosave = latest
        report.update(autosave=latest.name, **applied)
        return report

    def import_tools_only(self) -> dict[str, Any]:
        """Observe the latest export's tool layer + raw snapshot, no events."""
        return self._import_latest_autosave(events=False)

    def _audit_unreadable(self, autosave: Path, key: tuple, error: str, *,
                          code: str = "autosave_unreadable") -> None:
        """Record an unreadable/unstable export once per file state, not per poll."""
        if key == self._unreadable_signature:
            return
        self._unreadable_signature = key
        assert self.collector is not None
        self.collector.record_event("system", "runtime",
            producer="autosave_importer", audit_code=code,
            content=[content_block("json",
                data={"autosave": autosave.name, "error": error},
                visibility="collector_only")])

    def finish(self, status: str = "completed", reason: str | None = None) -> Path:
        """Final observation pass, derived summary, raw session attachment, close."""
        assert self.collector is not None and self.importer is not None
        self._observe_workspace(final=True)
        # Bounded final drain: the export usually grows one last time after
        # the final periodic poll, so import that batch before closing — the
        # trajectory keeps every call. A still-torn export is retried briefly
        # and then left audited; collected facts are kept, and the writer
        # still releases (run() force-closes it in a finally).
        deadline = time.monotonic() + FINISH_DRAIN_SECONDS
        while True:
            report = self._import_latest_autosave()
            if not report["autosave_unreadable"] or time.monotonic() >= deadline:
                break
            time.sleep(0.05)
        trajectory = self.collector.trajectory
        # tools_used is derived from the canonical event log, not from any
        # importer-side counter: interactive runs record their calls through
        # the journal/rollout observer, which the importer never sees.
        trajectory["derived_views"]["tools_used"] = derive_tools_used(trajectory["events"])
        # structured portability pass (schema §8.2): whitelisted fields only;
        # raw artifacts keep the original bytes
        sanitized = sanitize_trajectory_paths(trajectory, workspace=str(self.workspace))
        if sanitized:
            self.collector.record_event("system", "runtime",
                producer="session_collector",
                audit_code="paths_sanitized_for_portability",
                content=[content_block("json", data={"fields": sanitized},
                                       visibility="collector_only")])
        if self._last_autosave is not None:
            stored = self.store.put_file(self._last_autosave, mime_type="application/json")
            self.collector.record_attachment({
                "type": "raw_session",
                "uri": stored["uri"],
                "sha256": stored["sha256"],
                "mime_type": stored["mime_type"],
                "size_bytes": stored.get("size_bytes"),
            })
        result: dict[str, Any] = {"ok": status == "completed", "status": status}
        if reason:
            result["stop_reason"] = reason
        # An external agent's request boundary is never fully observable:
        # the trajectory stays honestly partial (outer_agent_hook semantics).
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
                    print(f"[session_collector] +{report['appended_events']} events, "
                          f"+{report['new_requests']} requests ({report.get('autosave')})",
                          flush=True)
                time.sleep(self.interval)
        except KeyboardInterrupt:
            _safe_print("[session_collector] interrupted; finalizing partial trajectory")
        except Exception as exc:
            # Torn exports are absorbed inside poll_once; anything that still
            # escapes must not cost the run its trajectory or its writer lease.
            _safe_print(f"[session_collector] observation loop failed: {exc!r}; "
                        "finalizing partial trajectory")
            status, reason, failure = "error", "observation_loop_failed", exc
        try:
            return self.finish(status=status, reason=reason)
        finally:
            # The exclusive lease must not outlive the run even when
            # finalization itself fails; close() is idempotent.
            if self.collector is not None:
                self.collector.writer.close()
            if failure is not None:
                raise failure


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Observe an external agent's game-generation session; one live trajectory per run")
    parser.add_argument("--game-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--workspace", type=Path, required=True,
                        help="The project directory the agent works in")
    parser.add_argument("--agent", default="codely", choices=("codely", "codex"),
                        help="codely: incremental session-export import; codex: "
                             "incremental session-rollout observation")
    parser.add_argument("--autosave-dir", type=Path, default=None,
                        help="codely: directory the agent rewrites its session export into")
    parser.add_argument("--autosave-pattern", default="chat-auto-save-*.json")
    parser.add_argument("--session-id", default=None,
                        help="codex/claude: the observed session's id (the session "
                             "filename carries it — precise attribution, never a guess)")
    parser.add_argument("--sessions-root", type=Path, default=None,
                        help="codex: sessions root (default ~/.codex/sessions)")
    parser.add_argument("--projects-root", type=Path, default=None,
                        help="claude: projects root (default ~/.claude/projects)")
    parser.add_argument("--engine", default=None,
                        help="Engine name for the environment snapshot, e.g. unity3d")
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--trajectory", type=Path, default=None,
                        help="Default: train_data/trajectories/<game_id>__<run_id>.json")
    parser.add_argument("--register", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--no-environment", action="store_true")
    add_identity_arguments(parser)
    args = parser.parse_args(argv)
    if args.agent == "codex":
        if not args.session_id:
            parser.error("sidecar collection for codex needs --session-id "
                         "(the observed session's rollout id)")
        from .codex_sidecar import CodexRolloutCollector
        collector = CodexRolloutCollector(
            game_id=args.game_id, run_id=args.run_id, workspace=args.workspace,
            session_id=args.session_id, sessions_root=args.sessions_root,
            engine=args.engine, trajectory=args.trajectory,
            register=args.register, skip_environment=args.no_environment,
            interval=args.interval, extra_metadata=identity_metadata(vars(args)))
    elif args.agent == "claude":
        if not args.session_id:
            parser.error("sidecar collection for claude needs --session-id "
                         "(the observed session's file id)")
        from .claude_sidecar import ClaudeSessionCollector
        collector = ClaudeSessionCollector(
            game_id=args.game_id, run_id=args.run_id, workspace=args.workspace,
            session_id=args.session_id, projects_root=args.projects_root,
            engine=args.engine, trajectory=args.trajectory,
            register=args.register, skip_environment=args.no_environment,
            interval=args.interval, extra_metadata=identity_metadata(vars(args)))
    else:
        if not args.autosave_dir:
            parser.error("sidecar collection for codely needs --autosave-dir")
        collector = SessionCollector(
            game_id=args.game_id, run_id=args.run_id, workspace=args.workspace,
            autosave_dir=args.autosave_dir, engine=args.engine, agent=args.agent,
            autosave_pattern=args.autosave_pattern, trajectory=args.trajectory,
            register=args.register, skip_environment=args.no_environment,
            interval=args.interval, extra_metadata=identity_metadata(vars(args)),
        )
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
