"""Record a playtest of a three.js project in a headless browser.

This is a **fixed-timestep capture**, not screen recording: there is no display
and no GPU render node here, so WebGL runs on SwiftShader at a fraction of real
time. `record.mjs` documents why each part is shaped the way it is.

Three environment inputs have no default on a machine like this and are
therefore explicit parameters rather than assumptions:

- ``playwright_root`` - a project with ``node_modules/playwright``. A generated
  game does not depend on Playwright, and it should not have to: recording is
  the harness's concern, not the game's. When the parameter is not given,
  ``playtest.dependencies.resolve_playwright`` locates one (environment, the
  recorded project's own install, the repository, then a harness tools
  install) so a recording never fails with a bare "Cannot find module
  'playwright'".
- ``browser_executable`` / ``browsers_path`` - the browser is not in the default
  ``~/.cache`` location. ``dependencies.find_cached_browser_binary`` resolves a
  usable Chromium from the ms-playwright cache when the parameters are absent
  (an explicit executablePath bypasses Playwright's revision pinning).
- ``library_path`` - Chromium needs ``libatk-bridge-2.0``, ``libgbm`` and
  ``libatspi``, which are absent from this image and cannot be installed. They
  are supplied by prepending a directory to ``LD_LIBRARY_PATH``. Omitting this is
  the single most likely reason a recording fails to start, and the failure looks
  like a browser launch error rather than a missing library.

Serving: with no ``url`` given, the client installs the project's own
dependencies when missing and starts a dev server for **this project copy**
on a private port — the recorded page provably comes from the project being
evaluated, never from whatever happens to listen on the default port. Pass
``url`` to record an externally managed server, or
``serve_project=False`` to fall back to the configured dev-server URL.
"""

from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path
from typing import Any

from .._internal.transport import NodeToolchain
from ..config import ThreeClientConfig
from ..contracts import ThreeOperationResult
from . import dependencies as deps

_RECORDER = Path(__file__).with_name("record.mjs")
_OPERATION = "playtest.record"


def _last_line_is_object(stdout: str) -> bool:
    """Whether the recorder's final stdout line is a JSON object."""
    lines = [line for line in (stdout or "").strip().splitlines() if line.strip()]
    if not lines:
        return False
    try:
        return isinstance(json.loads(lines[-1]), dict)
    except ValueError:
        return False


def _frame_index(name: str) -> int | None:
    """The capture index encoded in a frame file name (``f000123.jpg``)."""
    digits = "".join(char for char in str(name) if char.isdigit())
    return int(digits) if digits else None


class ThreePlaytestClient:
    """Drive a running game through discovered actions and record the result.

    Nothing here is written for a particular game. What the recorder needs to
    know is read from the running game — the input router publishes the very
    tables it dispatches on, so they cannot drift from what the game listens
    for. In order of preference: a ``__A3GAME_PLAYTEST__`` plan the game
    declares for itself; ``actionBindings`` and ``keyBindings``;
    ``[data-game-action]`` elements; a generic keyboard plan.

    Three things vary per game that a *list of verbs* cannot express, so they
    are separate inputs — inferred by default, overridable per recording:

    - ``hold`` - what stays pressed for the whole take. A racing game whose
      throttle is released between actions records a car twitching on the
      start line.
    - ``warmup`` - seconds to simulate before capturing. Games open on a
      countdown or a spawn, and a brawler drops attacks entirely until its
      round reaches FIGHT.
    - ``look`` - whether sweeping the camera is meaningful. Wrong in a
      side-scroller, actively harmful under drag-look.
    """

    def __init__(self, config: ThreeClientConfig) -> None:
        self._config = config
        self._toolchain = NodeToolchain(config)

    def record(
        self,
        *,
        output_dir: str | Path,
        url: str = "",
        action_plan: str | Path | None = None,
        hold: str | list[str] | None = None,
        warmup: float | None = None,
        look: str | bool | None = None,
        playwright_root: str | Path | None = None,
        browser_executable: str | Path | None = None,
        browsers_path: str | Path | None = None,
        library_path: str | Path | None = None,
        ffmpeg: str | Path | None = None,
        duration: float = 14.0,
        fps: int = 20,
        width: int = 1280,
        height: int = 720,
        timeout: float = 900.0,
        dry_run: bool = False,
        mode: str = "gameplay",
        clock: str = "fixed",
        preview: bool = False,
        allow_partial_plan: bool = False,
        source_hash: str | None = None,
        serve_project: bool | None = None,
        import_build_timeout: float = 180.0,
        launch_timeout: float = 45.0,
        evidence_log_dir: str | Path | None = None,
        software_renderer: bool = False,
        recorder_version: str = "legacy",
        capture_schedule: str | Path | None = None,
    ) -> dict[str, Any]:
        """Capture a unique take below ``output_dir`` without reusing old evidence.

        ``warmup=None`` and ``look=None`` preserve the game's declared plan.
        Explicit ``warmup=0`` disables pre-roll; ``look=False`` means ``off``.
        ``mode`` is gameplay or overview; ``preview`` captures one PNG instead
        of a video. ``allow_partial_plan`` explicitly permits a plan prefix.
        ``source_hash`` is an opaque build label passed through unchanged.
        Successful videos require completed status and verified video metadata;
        PNG previews require preview_completed. The current report path comes
        only from this invocation's final stdout JSON, never BASE/report.json.

        ``serve_project`` decides who serves the recorded page when no ``url``
        is given: ``None``/``True`` installs the project's dependencies when
        missing and starts a dev server for this exact project copy on a
        private port (torn down after the take); ``False`` keeps the legacy
        behavior of recording the configured dev-server URL.
        """
        project_dir = self._config.project_dir
        if recorder_version not in {"legacy", "generic-whitebox.vnext.1", "generic-whitebox.vnext.2", "generic-whitebox.vnext.3", "generic-whitebox.vnext.4", "generic-whitebox.vnext.5"}:
            return self._fail("unsupported recorder version")
        project_file = self._config.project_file
        if project_dir is None or project_file is None or not project_file.is_file():
            return self._fail("project_path must resolve to a project containing package.json")
        if not _RECORDER.is_file():
            return self._fail(f"Playtest recorder is missing: {_RECORDER}")
        if not all(isinstance(value, (int, float)) and not isinstance(value, bool)
                   and math.isfinite(value) and value > 0
                   for value in (duration, fps, width, height, timeout, import_build_timeout, launch_timeout)):
            return self._fail("duration, fps, width, height, and timeout must be finite and positive")
        if int(fps) != fps or any(int(value) != value or value % 2 for value in (width, height)):
            return self._fail("fps must be an integer; width and height must be even integers")
        if clock not in ("fixed", "realtime"):
            return self._fail("clock must be fixed or realtime")
        if not isinstance(software_renderer, bool):
            return self._fail("software_renderer must be boolean")
        if mode not in ("gameplay", "overview"):
            return self._fail("mode must be gameplay or overview")
        if not isinstance(preview, bool) or not isinstance(allow_partial_plan, bool):
            return self._fail("preview and allow_partial_plan must be boolean")
        if serve_project is not None and not isinstance(serve_project, bool):
            return self._fail("serve_project must be boolean or None")
        if source_hash is not None and (not isinstance(source_hash, str) or not source_hash):
            return self._fail("source_hash must be a non-empty string or None")

        out = Path(output_dir).expanduser().resolve(strict=False)
        plan = self._resolve(action_plan)
        root = self._resolve(playwright_root)
        browser = self._resolve(browser_executable)
        browsers = self._resolve(browsers_path)
        libraries = self._resolve(library_path)
        encoder = self._resolve(ffmpeg)

        if plan is not None and not plan.is_file():
            return self._fail(f"action_plan does not exist: {plan}")
        if root is not None and not (root / "node_modules" / "playwright").is_dir():
            return self._fail(f"playwright_root has no node_modules/playwright: {root}")
        if browser is not None and not browser.is_file():
            return self._fail(f"browser_executable does not exist: {browser}")
        if libraries is not None and not libraries.is_dir():
            return self._fail(f"library_path is not a directory: {libraries}")
        if look is False or look == "false":
            look = "off"
        if look not in (None, "auto", "pan", "off"):
            return self._fail(f"look must be auto, pan, off, False, or None; got {look!r}")
        if warmup is not None and (not isinstance(warmup, (int, float))
                                   or not math.isfinite(warmup) or warmup < 0):
            return self._fail("warmup must be finite and non-negative or None")

        held = [item.strip() for item in (hold.split(",") if isinstance(hold, str) else hold or [])]
        held = [item for item in held if item]
        url = str(url or "")
        serve = bool(serve_project) if serve_project is not None else (not url)
        if dry_run and not url:
            # nothing is launched: the configured URL stays the recorded hint
            url = str(self._config.dev_server_url)

        arguments = [
            "--url", url,
            "--output-dir", str(out),
            "--duration", str(float(duration)),
            "--fps", str(int(fps)),
            "--width", str(int(width)),
            "--height", str(int(height)),
            "--mode", mode, "--clock", clock,
        ]
        if capture_schedule is not None:
            if clock != "realtime" or recorder_version != "legacy" or preview:
                return self._fail("Sparse capture requires explicit realtime native recorder")
            schedule_path = Path(capture_schedule).resolve(strict=True)
            arguments.extend(["--capture-schedule", str(schedule_path)])
        if look is not None:
            arguments.extend(["--look", look])
        if warmup is not None:
            arguments.extend(["--warmup", str(float(warmup))])
        if preview:
            arguments.append("--preview")
        if software_renderer:
            arguments.append("--software-renderer")
        if allow_partial_plan:
            arguments.append("--allow-partial-plan")
        if source_hash is not None:
            arguments.extend(["--source-hash", source_hash])
        if held:
            arguments.extend(["--hold", ",".join(held)])
        for flag, value in (
            ("--action-plan", plan),
            ("--playwright-root", root),
            ("--browser-executable", browser),
        ):
            if value is not None:
                arguments.extend([flag, str(value)])

        environment: dict[str, str] = {}
        if browsers is not None:
            environment["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers)
        if libraries is not None:
            # Prepend: the image's own libraries must still win where they exist.
            existing = self._toolchain_environment().get("LD_LIBRARY_PATH", "")
            environment["LD_LIBRARY_PATH"] = (
                f"{libraries}:{existing}" if existing else str(libraries)
            )
        if encoder is not None:
            environment["A3GAME_PLAYTEST_FFMPEG"] = str(encoder)

        payload: dict[str, Any] = {
            "engine": "three_js",
            "url": url,
            "project_dir": str(project_dir),
            "output_dir": str(out),
            "report_path": None,
            "mode": mode,
            "renderer_policy": "swiftshader-explicit" if software_renderer else "native-gpu-preferred",
            "preview": preview,
            "allow_partial_plan": allow_partial_plan,
            "source_hash": source_hash,
            "serve_project": serve,
            "arguments": arguments,
            "action_plan": str(plan) if plan else None,
            "hold": held,
            "warmup": warmup,
            "look": look,
            "playwright_root": str(root) if root else None,
            "browser_executable": str(browser) if browser else None,
            "duration": duration,
            "fps": fps,
            "viewport": {"width": width, "height": height},
            "environment": environment,
            "dry_run": dry_run,
        }
        if dry_run:
            return ThreeOperationResult.success(_OPERATION, payload=payload).to_dict()

        # ── real run: resolve harness dependencies, then serve the project ──
        phase_started = time.monotonic()
        stage_timings = {}
        payload['phase_timings_ms'] = stage_timings
        dependency_notes: list[str] = []
        if root is None or browser is None:
            resolved = deps.resolve_playwright(project_dir, self._toolchain,
                                               explicit_root=root)
            if root is None and resolved.playwright_root is not None:
                root = resolved.playwright_root
                arguments.extend(["--playwright-root", str(root)])
                payload["playwright_root"] = str(root)
            if browser is None and resolved.browser_executable is not None:
                browser = resolved.browser_executable
                arguments.extend(["--browser-executable", str(browser)])
                payload["browser_executable"] = str(browser)
            dependency_notes.extend(resolved.notes)
            if resolved.errors and root is None:
                payload["dependency_resolution"] = resolved.to_dict()
                return self._fail(
                    f"recorder dependencies unavailable: {'; '.join(resolved.errors)}",
                    payload)
        payload["dependency_resolution"] = {
            "playwright_root": str(root) if root else None,
            "browser_executable": str(browser) if browser else None,
            "notes": dependency_notes,
        }
        stage_timings['harness_dependency_resolution'] = round((time.monotonic()-phase_started)*1000)

        payload["capture_schedule_path"] = str(Path(capture_schedule).resolve()) if capture_schedule is not None else None
        payload["recorder_version"] = recorder_version
        server = None
        if serve and not url:
            try:
                phase_started = time.monotonic()
                if deps.project_needs_install(project_dir):
                    dependency_notes.extend(
                        deps.install_project_dependencies(project_dir, self._toolchain,
                            timeout=import_build_timeout, log_dir=evidence_log_dir))
                    # keep the payload current so a serve failure still
                    # reports whether/how dependencies were installed
                    payload["dependency_resolution"]["notes"] = list(dependency_notes)
                from .launch import resolve_launch
                selected = resolve_launch(project_dir)
                payload['launch_selection'] = selected
                if selected['mode'] == 'build_preview':
                    remaining = import_build_timeout - (time.monotonic()-phase_started)
                    if remaining <= 0:raise RuntimeError('import/build budget exhausted before delivered build')
                    build = self._toolchain.run([str(self._toolchain.package_manager),'run','build'],cwd=project_dir,timeout=remaining)
                    if evidence_log_dir is not None:
                        Path(evidence_log_dir).mkdir(parents=True,exist_ok=True)
                        (Path(evidence_log_dir)/'delivered_build.log').write_text(build.stdout+'\n'+build.stderr)
                    if build.returncode:raise RuntimeError(f'delivered build failed: {build.returncode}')
                    payload['delivered_build_completed'] = True
                stage_timings['project_dependency_install'] = round((time.monotonic()-phase_started)*1000)
                server = deps.DevServerSession(project_dir, self._toolchain,
                    start_timeout=launch_timeout, log_dir=evidence_log_dir,
                    build_completed=bool(payload.get("delivered_build_completed")))
                phase_started = time.monotonic()
                url = server.start()
                stage_timings['dev_server_launch'] = round((time.monotonic()-phase_started)*1000)
                arguments[arguments.index("--url") + 1] = url
                payload["url"] = url
                payload["dev_server_started_by_recorder"] = True
                dependency_notes.extend(server.notes)
                payload["dependency_resolution"]["notes"] = dependency_notes
            except Exception as exc:  # noqa: BLE001
                if server is not None:server.stop()
                return self._fail(f"cannot serve the project for recording: "
                                  f"{type(exc).__name__}: {exc}", payload)
        try:
            phase_started = time.monotonic()
            result = self._record_take(
                out=out, url=url, project_dir=project_dir,
                environment=environment, arguments=arguments, payload=payload,
                duration=duration, fps=fps, width=width, height=height,
                timeout=timeout, mode=mode, preview=preview, clock=clock,
                allow_partial_plan=allow_partial_plan, source_hash=source_hash,
                dependency_notes=dependency_notes)
            stage_timings['browser_capture_and_encode'] = round((time.monotonic()-phase_started)*1000)
            result.setdefault('payload', {})['phase_timings_ms'] = stage_timings
            if not result.get('ok') and server is not None:
                diagnostic = server.failure_diagnostics()
                if diagnostic is not None:
                    result['payload']['server_failure'] = diagnostic
                    details = diagnostic['first_errors']
                    cause = details[0] if details else 'see dev_server.log'
                    result.setdefault('errors', []).append(
                        f"project server exited after HTTP readiness "
                        f"(exit {diagnostic['exit_code']}): {cause}")
                    if evidence_log_dir is not None:
                        (Path(evidence_log_dir)/'server_failure.json').write_text(
                            json.dumps(diagnostic, ensure_ascii=False, indent=2))
            return result
        finally:
            owned = server.process if capture_schedule is not None and server is not None else None
            if server is not None:
                server.stop()
            if capture_schedule is not None:
                alive = False
                if owned is not None:
                    try:os.killpg(owned.pid, 0);alive = True
                    except ProcessLookupError:pass
                receipt = {'owned_server_pid':owned.pid if owned is not None else None,
                    'server_returncode':owned.poll() if owned is not None else None,
                    'server_group_alive':alive,
                    'recorder':payload.get('command',{}).get('process_receipt',{})}
                receipt['process_cleanup'] = (not alive and
                    receipt['recorder'].get('process_cleanup') is True)
                take_path = payload.get('take_dir') or payload.get('partial_evidence',{}).get('take_dir')
                if take_path:
                    (Path(take_path)/'host_process_cleanup.json').write_text(
                        json.dumps(receipt,ensure_ascii=False,indent=2))
                payload['host_process_cleanup'] = receipt

    def _record_take(self, *, out: Path, url: str, project_dir: Path,
                     environment: dict[str, str], arguments: list[str],
                     payload: dict[str, Any], duration: float, fps: int,
                     width: int, height: int, timeout: float, mode: str,
                     preview: bool, allow_partial_plan: bool,
                     source_hash: str | None,
                     dependency_notes: list[str] | None = None, clock: str = "fixed") -> dict[str, Any]:
        try:
            out.mkdir(parents=True, exist_ok=True)
            previous_entries = {entry.name for entry in out.iterdir()}
            command = self._toolchain.run_node(
                (_RECORDER.with_name("record_vnext.mjs") if payload.get("recorder_version") in {"generic-whitebox.vnext.1", "generic-whitebox.vnext.2", "generic-whitebox.vnext.3", "generic-whitebox.vnext.4", "generic-whitebox.vnext.5"} else _RECORDER),
                cwd=project_dir,
                extra_args=arguments,
                timeout=timeout,
                environment=environment or None,
                **({"supervise_process":True} if payload.get("capture_schedule_path") else {}),
            )
        except Exception as exc:  # noqa: BLE001 - reported, never raised
            return self._fail(f"{type(exc).__name__}: {exc}", payload)
        payload["command"] = command.to_dict()

        # ── a killed recorder: recover the partial take from disk ─────────
        # The subprocess timeout SIGKILLs node, so no final stdout JSON can
        # exist by definition — this check runs BEFORE stdout parsing so the
        # recovered evidence never depends on a message the killed process
        # could not print. Frames persist per capture and the trace channels
        # append in bounded batches, so the interrupted take is still on
        # disk. Recovery is descriptive only: the envelope stays a failure
        # and downstream gating keeps treating the trial as interrupted —
        # this never relaxes the completed-take validation below.
        if command.timed_out or not _last_line_is_object(command.stdout):
            payload["failure_stage"] = ("record_timeout" if command.timed_out
                                        else "record_exited")
            if command.timed_out:
                cause = f"timed out after {timeout:g}s"
            elif command.returncode != 0:
                cause = f"exited with code {command.returncode}"
            else:
                cause = "produced no final stdout JSON"
            recovered = self._recover_partial_take(out, previous_entries)
            if recovered is not None:
                payload["partial_evidence"] = recovered
                return self._fail(
                    f"Recorder {cause} — partial evidence recovered from "
                    f"{recovered['take_dir']}: {recovered['frames']} frame(s) "
                    f"covering {recovered['recorded_seconds']}s of the requested "
                    f"{recovered['requested_seconds']}s, trace rows: "
                    f"{recovered['traces']}", payload)
            return self._fail(f"Recorder {cause} and left no recoverable take",
                              payload)

        try:
            lines = command.stdout.strip().splitlines()
            if not lines:
                raise ValueError("Recorder produced no final stdout JSON")
            current = json.loads(lines[-1])
            if not isinstance(current, dict):
                raise ValueError("Final stdout JSON must be an object")
            report_path = self._contained_path(current.get("report"), out)
            take = self._contained_path(current.get("output_dir"), out, directory=True)
            if take.parent != out or take.name in previous_entries:
                raise ValueError("Recorder did not return a new take within output_dir")
            if report_path != take / "report.json":
                raise ValueError("Report does not belong to the current take")
            report = json.loads(report_path.read_text(encoding="utf-8"))
            if not isinstance(report, dict):
                raise ValueError("Playtest report must be an object")
            payload.update(report_path=str(report_path), take_dir=str(take), report=report)
            if self._contained_path(report.get("output_dir"), out, directory=True) != take:
                raise ValueError("Report output_dir does not match the current take")
            if report.get("source_hash") != source_hash or current.get("source_hash") != source_hash:
                raise ValueError("Recorder source_hash does not match this invocation")
            if report.get("mode") != mode or report.get("url") != url:
                raise ValueError("Recorder mode or URL does not match this invocation")
            expected_status = "preview_completed" if preview else "completed"
            recorder_stderr = (command.stderr or "").strip()
            if recorder_stderr:
                # Preserve the recorder's own stderr verbatim: a bare exit code
                # alone never explains why the take failed.
                payload["recorder_stderr"] = recorder_stderr[-8000:]
            if command.timed_out or command.returncode != 0:
                # mark the take-level failure so downstream gating treats
                # this trial's evidence as truncated (UNKNOWN, never FAIL)
                payload["failure_stage"] = ("record_timeout" if command.timed_out
                                            else "record_exited")
                if command.timed_out:
                    raise ValueError("Recorder timed out")
                # The recorder always writes its report before exiting non-zero,
                # so prefer the recorder's own classified reason over the bare
                # exit code. The classification only describes the failure; the
                # envelope stays a failure and gating is unchanged.
                crashed = self._classify_recorder_failure(report, payload)
                raise ValueError(crashed or f"Recorder exited with code {command.returncode}")
            if report.get("status") != expected_status or current.get("status") != expected_status:
                crashed = self._classify_recorder_failure(report, payload)
                raise ValueError(crashed or f"Recorder status is not {expected_status}")
            if any(report.get(key) for key in ("crash", "page_errors")):
                crashed = self._classify_recorder_failure(report, payload)
                raise ValueError(crashed or "Recorder reported browser errors")
            if report.get("partial_plan") and not allow_partial_plan:
                raise ValueError("Recorder returned an unrequested partial plan")
            if not isinstance(report.get("warnings", []), list):
                raise ValueError("Report warnings must be an array")
            # console errors ride along as recorded evidence/warnings — the
            # metrics judge them, the capture does not die on them
            artifacts = [{"type": "playtest_report", "path": str(report_path)}]
            if payload.get("capture_schedule_path"):
                schedule = json.loads(Path(payload["capture_schedule_path"]).read_text())
                if schedule.get("audit_protocol") == "stage1-action-anchored.v1":
                    from pipeline.eval.stage1.capture import audit_capture
                else:
                    from pipeline.game_eval.whitebox_eval.sparse_evidence import audit_capture
                if report.get("sparse_capture") is not True or report.get("clock") != "realtime" or report.get("fixed_tick") is not False:
                    raise ValueError("Sparse capture lacks its native clock binding")
                if report.get("sampling_complete") is not True or report.get("wallclock_seconds", 0) < duration:
                    raise ValueError("Sparse capture did not finish its actual observation window")
                cleanup = json.loads((take/"browser_cleanup.json").read_text())
                if any(cleanup.get(key) is not True for key in ("input_cleanup", "view_cleanup", "browser_cleanup")):
                    raise ValueError("Sparse native input/view/browser cleanup incomplete")
                payload["sparse_capture_audit"] = audit_capture(take, schedule)
                artifacts.append({"type":"playtest_frames", "path":str(take/"frames")})
            elif preview:
                if report.get("preview") is not True or report.get("png_frames") != 1 or report.get("video"):
                    raise ValueError("Invalid PNG-only preview report")
                poster = self._contained_path(report.get("poster"), take)
                if poster.suffix.lower() != ".png":
                    raise ValueError("Preview poster must be a PNG")
                artifacts.append({"type": "playtest_poster", "path": str(poster)})
            else:
                metadata = report.get("video_metadata")
                if not isinstance(metadata, dict):
                    raise ValueError("Completed video has no video_metadata")
                frames = report.get("frames")
                if not isinstance(frames, int) or isinstance(frames, bool) or frames <= 0:
                    raise ValueError("Completed video has no frames")
                expected_frames = max(1, math.floor(duration * fps + 0.5))
                if clock == "realtime":
                    wallclock = report.get("wallclock_seconds")
                    if (report.get("clock") != "realtime" or report.get("fixed_tick") is not False
                            or report.get("sampling_complete") is not True
                            or not isinstance(wallclock, (int, float)) or not math.isfinite(wallclock)
                            or wallclock < duration or not 0 < frames <= expected_frames
                            or report.get("target_frames") != expected_frames
                            or report.get("dropped_sample_slots") != expected_frames - frames
                            or frames != metadata.get("frames")):
                        raise ValueError("Realtime sampling does not cover the requested clock window")
                elif frames != expected_frames or frames != report.get("target_frames") or frames != metadata.get("frames"):
                    raise ValueError("Video frame counts do not match the requested duration")
                if report.get("fps") != fps or metadata.get("fps") != fps:
                    raise ValueError("Video fps does not match the request")
                if report.get("viewport") != {"width": width, "height": height} or (
                    metadata.get("width"), metadata.get("height")
                ) != (width, height):
                    raise ValueError("Video dimensions do not match the request")
                if not all(isinstance(seconds, (int, float)) and math.isfinite(seconds)
                           and math.isclose(seconds, frames / fps, rel_tol=0, abs_tol=0.002)
                           for seconds in (metadata.get("seconds"), report.get("recorded_seconds"))):
                    raise ValueError("Video duration does not match frame count")
                video = self._contained_path(report.get("video"), take)
                if video.suffix.lower() != ".mp4":
                    raise ValueError("Completed video must be an MP4")
                artifacts.extend([
                    {"type": "playtest_frames", "path": str(self._contained_path(str(take / "frames"), take, directory=True))},
                    {"type": "playtest_video", "path": str(video)},
                ])
                for key in ("init", "poster"):
                    image = self._contained_path(report.get(key), take)
                    artifacts.append({"type": f"playtest_{key}", "path": str(image)})
            # runtime traces the recorder captured this take (absent file = the
            # channel was not captured — the loader reports that as UNKNOWN)
            for name, artifact_type in (
                ("actions.jsonl", "playtest_actions"),
                ("state_trace.jsonl", "playtest_state_trace"),
                ("event_trace.jsonl", "playtest_event_trace"),
            ):
                trace = take / name
                if trace.is_file() and trace.stat().st_size > 0:
                    artifacts.append({"type": artifact_type, "path": str(trace)})
        except (OSError, ValueError, TypeError, RuntimeError) as exc:
            return self._fail(f"Invalid current playtest evidence: {exc}", payload)
        return ThreeOperationResult.success(
            _OPERATION,
            artifacts=artifacts,
            warnings=[str(item) for item in report.get("warnings", [])]
            + [str(item) for item in dependency_notes],
            payload=payload,
        ).to_dict()

    @staticmethod
    def _classify_recorder_failure(report: dict[str, Any],
                                   payload: dict[str, Any]) -> str | None:
        """A specific, classified failure message for a failed take.

        ``record.mjs`` records ``crash`` alongside an optional
        ``error_classification``/``error_category``. A recorder error whose
        cause is the host environment (the page losing focus mid-take, a
        renderer crash) must never read as an anonymous ``exit 1``: the
        message names the class, the category and the recorder's own text.
        Returns ``None`` when the report carries no recognized failure, so
        the caller keeps its generic message.
        """
        crash = str(report.get("crash") or "").strip()
        classification = str(report.get("error_classification") or "").strip()
        category = str(report.get("error_category") or "").strip()
        if not classification and "lost focus" in crash.lower():
            # Older takes classify nothing; recognize the same condition.
            classification, category = "INPUT_FOCUS_LOST", "environment"
        if not classification:
            return None
        payload["crash_classification"] = classification
        payload["crash_category"] = category or "unknown"
        payload["crash_message"] = crash
        return (f"Recorder failed: {classification}"
                f" ({category or 'unknown'}) — "
                f"{crash or 'no recorder detail'}")

    def _recover_partial_take(self, out: Path,
                              previous_entries: set[str]) -> dict[str, Any] | None:
        """Best-effort recovery of a killed recorder's partial take from disk.

        Frames are written per capture and the trace channels append in
        bounded batches, so a take interrupted by a hard kill still holds
        every observation up to the last flush — readable even without the
        final stdout JSON or ``report.json``. The returned mapping is
        descriptive evidence only: the caller keeps the envelope a failure
        so downstream gating treats the trial as interrupted.
        """
        candidates: list[Path] = []
        try:
            for entry in out.iterdir():
                if not entry.is_dir() or entry.name in previous_entries:
                    continue
                if (entry / "frames").is_dir():
                    candidates.append(entry)
        except OSError:
            return None
        if not candidates:
            return None
        take = max(candidates, key=lambda p: len(list((p / "frames").iterdir())))
        frames = sorted(f.name for f in (take / "frames").iterdir() if f.is_file())
        rows = {key: self._count_jsonl_rows(take / name)
                for name, key in (("actions.jsonl", "actions"),
                                  ("state_trace.jsonl", "states"),
                                  ("event_trace.jsonl", "events"))}
        progress: dict[str, Any] | None = None
        progress_path = take / "recording_progress.json"
        if progress_path.is_file():
            try:
                loaded = json.loads(progress_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    progress = loaded
            except (OSError, ValueError):
                progress = None
        fps = progress.get("fps") if progress else None
        fps = int(fps) if isinstance(fps, (int, float)) and int(fps) > 0 else None
        target = progress.get("target_frames") if progress else None
        target = int(target) if isinstance(target, (int, float)) and int(target) > 0 else None
        requested = progress.get("requested_seconds") if progress else None
        recorded = progress.get("recorded_seconds") if progress else None
        index = _frame_index(frames[-1]) if frames else None
        if index is not None and fps:
            recorded = round((index + 1) / fps, 3)  # frame ↔ simulated-time map
        files: list[str] = []
        for name in ("actions.jsonl", "state_trace.jsonl", "event_trace.jsonl",
                     "recording_progress.json"):
            path = take / name
            if path.is_file() and path.stat().st_size > 0:
                files.append(path.name)
        return {
            "take_dir": str(take),
            "frames": len(frames),
            "frame_first": frames[0] if frames else None,
            "frame_last": frames[-1] if frames else None,
            "fps": fps,
            "target_frames": target,
            "requested_seconds": requested,
            "recorded_seconds": recorded,
            "traces": rows,
            "progress_status": (progress or {}).get("status"),
            "progress": progress,
            "files": files,
            "recovery_note": (
                "partial take recovered from disk after the recorder was "
                "killed; the envelope failure is kept so downstream gating "
                "treats the trial as interrupted"),
        }

    @staticmethod
    def _count_jsonl_rows(path: Path) -> int:
        """Count parseable object rows; a torn tail line does not count."""
        if not path.is_file():
            return 0
        count = 0
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return 0
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                if isinstance(json.loads(line), dict):
                    count += 1
            except ValueError:
                continue
        return count

    @staticmethod
    def _contained_path(value: Any, parent: Path, *, directory: bool = False) -> Path:
        if not isinstance(value, str) or not value or not Path(value).is_absolute():
            raise ValueError("Evidence paths must be absolute strings")
        candidate = Path(value).resolve(strict=True)
        if candidate == parent or not candidate.is_relative_to(parent):
            raise ValueError("Evidence path escapes the current output scope")
        if directory:
            if not candidate.is_dir():
                raise ValueError("Evidence directory is missing")
        elif not candidate.is_file() or candidate.stat().st_size == 0:
            raise ValueError("Evidence file is missing or empty")
        return candidate

    @staticmethod
    def _resolve(value: str | Path | None) -> Path | None:
        return Path(value).expanduser().resolve(strict=False) if value else None

    @staticmethod
    def _toolchain_environment() -> dict[str, str]:
        import os

        return dict(os.environ)

    @staticmethod
    def _fail(message: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return ThreeOperationResult.failure(_OPERATION, message, payload=payload).to_dict()
