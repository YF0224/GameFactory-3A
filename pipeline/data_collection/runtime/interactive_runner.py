"""Native agent terminal supervised by a single Collector.

This is NOT stream-json over a terminal and NOT kill/resume steering. The
child inherits the terminal (input, approvals, launch-game requests, Ctrl-C).
Only this parent writes the trajectory.

Two providers, both verified against real sessions (never --help inference):

* codely — the CLI keeps a per-session journal that updates every turn; it is
  attributed by the launch prompt appearing as one of its user messages and
  observed in real time. The exit autosave contributes the visible tool
  definitions and raw snapshot attachments.
* codex — the CLI writes a per-session rollout (``~/.codex/sessions/...``)
  that is created early but whose conversation records flush coarsely and
  may only land at session end, so observation is snapshot-style: whatever is
  on disk is recorded, the final drain runs at exit, and the limitation is
  audited honestly. Reasoning stays provider-encrypted and is never
  reconstructed. No attributable record means the capture is reported
  missing, never papered over.

A request-view companion trajectory is rebuilt from the same session record
once the main trajectory's writer has closed.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time

from pipeline.data_collection.paths import make_trajectory_id, trajectory_path

from ..core.artifact_store import ArtifactStore
from ..core.collector import content_block
from ..core.event_writer import atomic_write_json, now_iso
from ..adapters.codely_autosave import portable_uri
from ..quality.capture_audit import summarize_capture
from .session_collector import SessionCollector
from .verification_observer import apply_declared_verification_rules


class FreshSessionCollector(SessionCollector):
    """Don't ingest an unrelated export left behind by a previous session."""
    def remember_existing(self):
        self._before = {p: p.stat().st_mtime_ns for p in
                        self.autosave_dir.glob(self.autosave_pattern) if p.is_file()}

    def _latest_autosave(self):
        candidates = []
        for p in self.autosave_dir.glob(self.autosave_pattern):
            try:
                if p.is_file() and p.stat().st_mtime_ns != self._before.get(p):
                    candidates.append(p)
            except OSError:
                continue
        return max(candidates, key=lambda p: p.stat().st_mtime_ns) if candidates else None


def _journals(journal_root: Path) -> set:
    return {p for p in journal_root.glob("*/chats/*.jsonl") if p.is_file()}


def _provider_records(provider, prompt, journal_root):
    """(files_fn, matches_fn, make_observer_fn, limitations) per provider."""
    if provider == "codely":
        from ..adapters.codely_journal import (DEFAULT_JOURNAL_ROOT, JournalObserver,
                                                journal_matches_prompt, recover_companion)

        root = Path(journal_root).expanduser() if journal_root else DEFAULT_JOURNAL_ROOT

        def files():
            return _journals(root)

        def matches(path):
            return journal_matches_prompt(path, prompt)

        def make(collector, importer, path):
            return JournalObserver(importer, session_id=Path(path).stem)

        def companion(**kwargs):
            return recover_companion(**kwargs)

        mime = "application/x-ndjson"
        attachment_type = "recovered_session_journal"
        limitations = ["exit_autosave_contributes_tools_and_snapshots_only",
                        "request_boundaries_not_invented_here",
                        "companion_export_view_rebuilt_from_journal",
                        "exclusive_codely_session_in_workspace_required"]
        return files, matches, make, companion, root, mime, attachment_type, limitations
    if provider == "codex":
        from ..adapters.codex_session import (DEFAULT_SESSIONS_ROOT, RolloutObserver,
                                              rollout_files, rollout_matches_prompt,
                                              recover_codex_companion)

        root = Path(journal_root).expanduser() if journal_root else DEFAULT_SESSIONS_ROOT

        def files():
            return rollout_files(root)

        def matches(path):
            return rollout_matches_prompt(path, prompt)

        def make(collector, importer, path):
            return RolloutObserver(collector, session_id=Path(path).stem)

        def companion(**kwargs):
            return recover_codex_companion(**kwargs)

        mime = "application/x-ndjson"
        attachment_type = "recovered_session_rollout"
        limitations = ["codex_rollout_flushes_coarsely_intermediate_states_may_be_missing",
                       "main_trajectory_has_no_request_boundaries_companion_infers_them",
                       "reasoning_is_encrypted_by_provider_text_not_reconstructed",
                       "companion_export_view_rebuilt_from_rollout"]
        return files, matches, make, companion, root, mime, attachment_type, limitations
    if provider == "claude":
        from ..adapters.claude_code import (DEFAULT_PROJECTS_ROOT,
                                            ClaudeSessionObserver,
                                            recover_claude_companion,
                                            session_files, session_matches_prompt)

        root = Path(journal_root).expanduser() if journal_root else DEFAULT_PROJECTS_ROOT

        def files():
            return session_files(root)

        def matches(path):
            return session_matches_prompt(path, prompt)

        def make(collector, importer, path):
            return ClaudeSessionObserver(collector, session_id=Path(path).stem)

        def companion(**kwargs):
            return recover_claude_companion(**kwargs)

        mime = "application/x-ndjson"
        attachment_type = "recovered_session_records"
        limitations = ["claude_session_file_appends_live_interactive_observation_is_incremental",
                       "main_trajectory_has_no_request_boundaries_companion_infers_them",
                       "thinking_is_archived_restricted_never_training_input",
                       "companion_export_view_rebuilt_from_session_file"]
        return files, matches, make, companion, root, mime, attachment_type, limitations
    raise ValueError(f"interactive collection for {provider!r} is not implemented")


def _claim_session(known_before: set, files, matches, state: dict, collector):
    """Attribute exactly one fresh session record by the launch-prompt anchor.

    Several matching candidates are an ambiguity: audit once and refuse to
    observe rather than merge sessions by timestamp guesses."""
    fresh = files() - known_before
    matching = sorted(p for p in fresh if matches(p))
    if len(matching) == 1:
        return matching[0]
    if len(matching) > 1 and not state.get("ambiguity_audited"):
        state["ambiguity_audited"] = True
        collector.record_event("system", "runtime",
            producer="interactive_runner", audit_code="session_attribution_ambiguous",
            content=[content_block("json",
                data={"candidates": [str(p) for p in matching]},
                visibility="collector_only")])
    return None


def run_interactive(prompt, *, workspace, run_dir, game_id, run_id,
                    provider="codely", executable=None, extra_args=(),
                    autosave_dir=None, autosave_pattern="chat-auto-save-*.json",
                    interval=1.0, trajectory=None, register=True,
                    skip_environment=False, timeout_seconds=None,
                    journal_root=None, companion_path=None,
                    verification_rules=None, extra_metadata=None, engine=None):
    """Run the native UI until exit, observing records without owning its tools.

    Use a dedicated workspace/session: multiple agent sessions rewriting the
    same export directory or records root cannot be attributed to this child
    from filenames alone.
    """
    provider = provider or "codely"
    executable = executable or provider
    workspace, run_dir = Path(workspace).resolve(), Path(run_dir).resolve()
    if not workspace.is_dir():
        raise ValueError("interactive workspace must already exist")
    forbidden = {"-p", "--prompt", "-i", "--prompt-interactive", "--output-format"}
    if any(arg.split("=", 1)[0] in forbidden for arg in extra_args):
        raise ValueError("interactive mode owns prompt/output mode; remove conflicting --agent-arg")
    run_dir.mkdir(parents=True, exist_ok=True)
    meta_path = run_dir / "run_meta.json"
    if meta_path.exists():
        raise FileExistsError("run directory already used")
    files, matches, make_observer, build_companion, records_root, mime, \
        attachment_type, limitations = _provider_records(provider, prompt, journal_root)
    target = Path(trajectory) if trajectory else trajectory_path(make_trajectory_id(game_id, run_id))
    sidecar = FreshSessionCollector(
        game_id=game_id, run_id=run_id, workspace=workspace,
        autosave_dir=autosave_dir or workspace / ".codely-cli" / "auto-saves",
        autosave_pattern=autosave_pattern, trajectory=target, register=register,
        skip_environment=skip_environment, interval=interval,
        snapshot_store=ArtifactStore(run_dir / "raw" / "autosaves"),
        extra_metadata=extra_metadata, engine=engine)
    sidecar.remember_existing()
    records_before = files()
    state = {"game_id": game_id, "run_id": run_id, "mode": "native_interactive",
             "provider": provider,
             "observation_source": ("live_session_journal" if provider == "codely"
                                    else "codex_session_rollout"),
             "started_at": now_iso(), "trajectory_path": str(target),
             "capture_complete": False, "runtime_stream": False}
    child = None
    old_interrupt = None
    failure = None
    observer = None
    claimed_record = None
    status, reason = "error", "startup_failed"
    try:
        atomic_write_json(meta_path, state)
        sidecar.start()
        # The launch prompt is the session's task statement (schema §6
        # task_ref): keep it as the immutable requirement reference next to
        # the user event that delivered it.
        sidecar.collector.trajectory["task_ref"] = {
            "source": "interactive_launch_prompt", "prompt": prompt}
        sidecar.collector.writer.checkpoint()
        sidecar.collector.record_event("system", "runtime", producer="interactive_runner",
            audit_code="interactive_observation_contract", limitations=limitations)
        # The agent owns terminal Ctrl-C. The parent must not close the
        # Collector when the user merely interrupts a generation to give
        # feedback; only a real child exit finalizes the trajectory.
        old_interrupt = signal.signal(signal.SIGINT, lambda signum, frame: None)
        if provider in ("codex", "claude"):
            # both CLIs take the launch prompt as a positional argument in
            # interactive mode (claude [prompt] / codex [prompt])
            argv = [executable, *extra_args, prompt]
        else:
            argv = [executable, *extra_args, "--prompt-interactive", prompt]
        child = subprocess.Popen(argv, cwd=workspace, env=os.environ.copy())
        state["pid"] = child.pid
        atomic_write_json(meta_path, state)
        deadline = time.monotonic() + timeout_seconds if timeout_seconds is not None else None
        status, reason = "completed", None
        while child.poll() is None:
            sidecar._observe_workspace()
            if observer is None:
                claimed_record = _claim_session(records_before, files, matches,
                                                 state, sidecar.collector)
                if claimed_record is not None:
                    observer = make_observer(sidecar.collector, sidecar.importer,
                                             claimed_record)
            if observer is not None:
                observer.observe(claimed_record)
            if deadline is not None and time.monotonic() >= deadline:
                status, reason = "timeout", "interactive_timeout"
                break
            time.sleep(max(0.01, interval))
        if status == "completed" and child.returncode != 0:
            status, reason = "crashed", "agent_exit_nonzero"
    except BaseException as exc:
        failure = exc
        status, reason = "error", "interactive_observation_failed"
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=2)
        if old_interrupt is not None:
            signal.signal(signal.SIGINT, old_interrupt)
        companion = None
        archived_record: dict | None = None
        try:
            if observer is not None:
                observer.observe(claimed_record)  # final records drain
            record_success = observer is not None and observer.report["appended_events"] > 0
            if record_success:
                if provider == "codely":
                    # The exit autosave appears after the child exits; take its
                    # tool layer + snapshot. Setting the import signature also
                    # pins the finish() drain to a no-op: every fact the
                    # autosave carries was already observed from the journal.
                    wait_end = time.monotonic() + 3.0
                    while time.monotonic() < wait_end:
                        if sidecar.import_tools_only()["autosave"] is not None:
                            break
                        time.sleep(0.2)
                # The session record must not stay a machine-local dependency:
                # copy it into the run's raw archive and the content-addressed
                # store, then reference only the archived copy. An
                # unarchivable record is honestly audited instead of being
                # presented as recoverable.
                raw_name = ("codely_session_journal.jsonl" if provider == "codely"
                            else "codex_session_rollout.jsonl" if provider == "codex"
                            else "claude_session_records.jsonl")
                try:
                    raw_copy = run_dir / "raw" / raw_name
                    raw_copy.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(claimed_record, raw_copy)
                    archived_record = sidecar.store.put_file(claimed_record, mime_type=mime)
                except OSError:
                    archived_record = None
                if archived_record:
                    for event in sidecar.collector.trajectory["events"]:
                        refs = event.get("source_refs")
                        if isinstance(refs, dict) and refs.get("format") == "codely-journal":
                            refs["uri"] = archived_record["uri"]
                data = Path(claimed_record).read_bytes()
                attachment = {
                    "type": attachment_type,
                    "uri": (archived_record["uri"] if archived_record
                            else portable_uri(str(claimed_record))),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "mime_type": mime, "size_bytes": len(data)}
                if archived_record:
                    attachment["original_uri"] = portable_uri(str(claimed_record))
                sidecar.collector.record_attachment(attachment)
                if not archived_record:
                    sidecar.collector.record_event("system", "runtime",
                        producer="interactive_runner",
                        audit_code="raw_journal_not_portable",
                        content=[content_block("json",
                                  data={"status": "missing",
                                        "uri": attachment["uri"]},
                                  visibility="collector_only")])
            else:
                # No attributable session record. Codely still has the
                # exit-time autosave snapshot as a fallback; codex has none.
                if provider == "codely":
                    sidecar.poll_once()
            # harness-declared verification rules observe real command
            # executions — never tool names, never exit-status guesses
            if verification_rules and record_success:
                recorded = apply_declared_verification_rules(
                    sidecar.collector, verification_rules)
                if recorded:
                    state["verification_observed"] = {
                        "kinds": sorted(set(recorded)), "count": len(recorded)}
            sidecar.finish(status=status, reason=reason)
            summary = summarize_capture(sidecar.collector.trajectory,
                                         raw_journal_archived=bool(archived_record))
            state["capture_audit"] = summary
            state["capture_completeness"] = {
                "provider_runtime_stream": False,
                "journal_observed": record_success,
                "raw_journal_archived": bool(archived_record),
                "tool_calls": "complete" if not summary["unpaired_calls"] else "incomplete",
                "tool_results": "complete" if not summary["orphan_results"] else "incomplete",
                "request_boundary": summary["request_boundary"],
                "reasoning": "observed" if summary["reasoning_events"] else "none",
            }
            if not record_success and sidecar._last_autosave is None:
                state["capture_missing_reason"] = (
                    "no_session_export_observed" if provider == "codely"
                    else "no_session_rollout_observed" if provider == "codex"
                    else "no_session_records_observed")
        finally:
            sidecar.collector.writer.close()
            state.update(status=status, stop_reason=reason, finished_at=now_iso(),
                         exit_code=child.returncode if child is not None else None,
                         # agent completion and capture completeness are
                         # different facts: a cleanly exited agent can still
                         # leave a partial capture (native interactive
                         # observation is journal-side, never a runtime
                         # stream), and a crashed agent can leave a complete one
                         agent_status=status,
                         capture_status=("missing"
                                         if state.get("capture_missing_reason")
                                         else "partial"),
                         capture_source=state.get("observation_source"),
                         # machine-local operational pointers also use the
                         # stable substitute prefixes (schema §8.2); the
                         # session record points at the ARCHIVED copy, with
                         # the original location kept separately
                         workspace=portable_uri(str(workspace)),
                         trajectory_path=portable_uri(str(target)),
                         session_record=(archived_record["uri"]
                                         if archived_record and claimed_record
                                         else (portable_uri(str(claimed_record))
                                               if claimed_record else None)),
                         session_record_original=(portable_uri(str(claimed_record))
                                                   if claimed_record else None))
            atomic_write_json(meta_path, state)
            # The request-view companion is rebuilt from the same session
            # record once this trajectory's writer has closed; it is
            # supplementary and must never cost the main trajectory.
            if claimed_record is not None:
                try:
                    companion_kwargs: dict = (
                        {"journal_path": claimed_record} if provider == "codely"
                        else {"rollout_path": claimed_record})
                    if provider == "codely":
                        # The journal carries no tool definitions; the tool
                        # layer the exit autosave already contributed to the
                        # main trajectory must reach the companion's training
                        # view too (facts still come from the journal only).
                        harvested = sidecar.collector.trajectory.get("tools") or []
                        if harvested:
                            companion_kwargs["visible_tools"] = harvested
                        # Same for the system prompt: the journal records
                        # none, and without it every reconstructed request
                        # input is missing its first real context block.
                        # When the export carries only the static core
                        # prompt's hash reference (verified CLI shape), that
                        # reference is recorded instead — never fabricated.
                        if sidecar._last_system_prompt:
                            companion_kwargs["system_prompt"] = sidecar._last_system_prompt
                        elif sidecar._last_system_ref:
                            companion_kwargs["system_ref"] = sidecar._last_system_ref
                        if extra_metadata:
                            companion_kwargs["extra_metadata"] = extra_metadata
                        companion_kwargs["workspace"] = str(workspace)
                        companion_kwargs["artifact_store"] = sidecar.store
                    else:
                        # codex / claude: identity fields and the run's blob
                        # store reach the requests-view companion the same way
                        if extra_metadata:
                            companion_kwargs["extra_metadata"] = extra_metadata
                        companion_kwargs["artifact_store"] = sidecar.store
                    companion = build_companion(
                        **companion_kwargs,
                        game_id=game_id, run_id=run_id,
                        live_trajectory_id=make_trajectory_id(game_id, run_id),
                        live_trajectory_path=target, register=register,
                        out_path=companion_path)
                except (Exception, SystemExit) as exc:  # companion is supplementary
                    companion = {"attempted": True, "ok": False, "error": str(exc)}
                state["companion_recovery"] = companion
                atomic_write_json(meta_path, state)
    if failure is not None:
        raise failure
    return target
