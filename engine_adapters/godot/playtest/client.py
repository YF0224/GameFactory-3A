"""Record a playtest of a Godot project through the running game.

This follows the ``record.md`` contract for Layer 3 (Play Session):

- The adapter owns how to launch the game, send real input events, and
  capture frames.
- The pipeline owns the session lifecycle and record placement.
- The Agent may produce a declarative action plan, which is hashed before
  execution.

The adapter's own ``observe_recorder.gd`` (shipped next to this module) is
the recorder: a game-agnostic SceneTree script that loads the project's
real main scene, binds runtime observation through the game's runtime
adapter (``event_emitted`` + ``get_state_snapshot()``) when the game has
one, executes the action plan with real input events, and writes what
actually happened this session:

```
output_dir/
├── frames/f00001.png ...        — captured viewport frames
├── video.mp4                    — encoded from frames (if ffmpeg available)
├── report.json                  — actions, traces, coverage, warnings
├── actions.jsonl                — per-step real sends: sent verdicts + t_monotonic_ms
├── state_trace.jsonl            — {t_ms, state} rows from get_state_snapshot()
└── event_trace.jsonl            — {t_ms, event, payload} rows from event_emitted
```

Honesty rules kept here: ``actions.jsonl`` is *never* rewritten from the
requested plan — only the recorder's own rows count as executed input; a
crashed recorder leaves the channel absent (the report records the
missing channel, and downstream metrics stay UNKNOWN).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ..config import GodotClientConfig
from .._internal.transport import GodotTransport

_OPERATION = "playtest.record"
_REPORT_SCHEMA = "gamefactory3a.godot.playtest_report.v1"
_RECORDER_SCRIPT = Path(__file__).with_name("observe_recorder.gd")

# Allowlisted player-level action names (record.md contract)
ALLOWED_ACTIONS = frozenset({
    "move", "look", "jump", "attack", "interact",
    "dash", "pause", "restart", "wait",
})


class GodotPlaytestClient:
    """Drive a running Godot game and record a playtest session."""

    def __init__(self, config: GodotClientConfig) -> None:
        self._config = config

    def record(
        self,
        *,
        output_dir: str | Path,
        scenario: str | Path | None = None,
        action_plan: list[dict[str, Any]] | None = None,
        duration: float = 12.0,
        fps: int = 20,
        width: int = 640,
        height: int = 360,
        timeout: float = 120.0,
        headless: bool = False,
        ffmpeg: str | Path | None = None,
        dry_run: bool = False,
        observation_plan: str | Path | None = None,
    ) -> dict[str, Any]:
        """Record one playtest into ``output_dir``.

        Args:
            scenario: Path to a scenario JSON file with ``actions`` list.
            action_plan: Inline action list (same format as scenario).
            duration: Total recording time in seconds.
            fps: Frames per second to capture.
            width/height: Frame resolution.
            timeout: Maximum time to wait for the game.
            headless: Must be False for frame capture (headless Godot has
                no rendering server). Kept as parameter for API compat.
            ffmpeg: Path to ffmpeg for video encoding.
            dry_run: Validate and print the plan without running.
        """
        if observation_plan is not None:
            return self._record_bounded_plan(output_dir, Path(observation_plan), timeout, width, height, dry_run)
        project_dir = self._config.project_dir
        if project_dir is None or not (project_dir / "project.godot").is_file():
            return self._fail("project_path must resolve to a Godot project")

        out = Path(output_dir).expanduser().resolve(strict=False)
        actions = self._load_actions(scenario, action_plan, duration)
        if actions is None:
            return self._fail("invalid action plan: use allowlisted action names")

        payload: dict[str, Any] = {
            "engine": "godot",
            "project_dir": str(project_dir),
            "output_dir": str(out),
            "duration": duration,
            "fps": fps,
            "viewport": {"width": width, "height": height},
            "headless": headless,
            "action_count": len(actions),
            "actions": actions,
        }
        if dry_run:
            return self._ok(payload, [])

        out.mkdir(parents=True, exist_ok=True)
        frames_dir = out / "frames"
        frames_dir.mkdir(exist_ok=True)
        # stale traces from a reused take dir must never mix into this take
        for stale_name in ("actions.jsonl", "state_trace.jsonl", "event_trace.jsonl",
                           "report.json", "video.mp4"):
            (out / stale_name).unlink(missing_ok=True)

        # Write the scenario the recorder executes (the frozen plan).
        # input_bindings from the rubric are forwarded so the recorder can
        # map each verb to the game's actual key rather than the default.
        scenario: dict[str, Any] = {"actions": actions, "fps": fps, "duration": duration}
        if self._config.input_bindings:
            scenario["input_bindings"] = self._config.input_bindings
        scenario_path = out / "_scenario.json"
        scenario_path.write_text(
            json.dumps(scenario, indent=2),
            encoding="utf-8",
        )

        # Launch the game with the recording scene (normal mode, not SceneTree script)
        exec_path = self._config.godot_executable
        if exec_path is None:
            return self._fail("godot_executable is not configured")
        record_scene = project_dir / "scenes" / "main_record.tscn"
        if record_scene.is_file():
            # project-shipped recorder scene: the in-game recorder consumes
            # the --a3-record argument family.
            command = [
                str(exec_path),
                "--log-file", str(out / "godot.log"),
                "--path", str(project_dir),
                "--resolution", f"{width}x{height}",
                str(record_scene),
                "--", "--a3-record", str(frames_dir),
                "--a3-record-fps", str(fps),
                "--a3-record-duration", str(duration),
            ]
        else:
            # the adapter's own observation recorder: runs the project's real
            # main scene under a SceneTree that injects only the allowlisted
            # verbs and records every channel it can actually observe
            if not _RECORDER_SCRIPT.is_file():
                return self._fail(f"playtest recorder script is missing: {_RECORDER_SCRIPT}")
            main_scene_result = self._resolve_main_scene_checked(project_dir)
            if main_scene_result["classification"] == "PRODUCT_MISSING_MAIN_SCENE":
                return self._fail(
                    f"PRODUCT_MISSING_MAIN_SCENE: configured main scene does not exist. "
                    f"Config: {main_scene_result['configured']}, "
                    f"Expected path: {main_scene_result['expected_path']}, "
                    f"Exists: False",
                    payload={**payload, "launch_diagnostics": main_scene_result})
            main_scene = main_scene_result.get("resolved")
            if main_scene is None:
                return self._fail(
                    "project has no scenes/main_record.tscn and no resolvable "
                    "main scene (project.godot run/main_scene, res://main.tscn, "
                    "res://scenes/main.tscn)",
                    payload={**payload, "launch_diagnostics": main_scene_result})
            command = [
                str(exec_path),
                "--log-file", str(out / "godot.log"),
                "--path", str(project_dir),
                "--resolution", f"{width}x{height}",
                "-s", str(_RECORDER_SCRIPT),
                "--", "--a3-scenario", str(scenario_path),
                "--a3-output", str(out),
            ]

        payload["command"] = " ".join(command)
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(project_dir),
            )
        except subprocess.TimeoutExpired:
            return self._fail(f"playtest timed out after {timeout}s", payload)
        except OSError as exc:
            return self._fail(f"failed to launch: {exc}", payload)

        payload["exit_code"] = result.returncode
        payload["stdout_tail"] = result.stdout[-2000:] if result.stdout else ""
        payload["stderr_tail"] = result.stderr[-2000:] if result.stderr else ""

        # Collect the channels the recorder actually wrote — the client never
        # fabricates any of them from the requested plan
        frames = sorted(frames_dir.glob("f*.png"))
        payload["frame_count"] = len(frames)
        action_rows, actions_available = self._read_trace_rows(out / "actions.jsonl")
        state_rows, states_available = self._read_trace_rows(out / "state_trace.jsonl")
        event_rows, events_available = self._read_trace_rows(out / "event_trace.jsonl")
        delivered = self._delivered_actions(action_rows)
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        capture_error = ""
        if result.returncode != 0:
            capture_error = (f"recorder exited with code {result.returncode}: "
                             f"{(stdout + stderr)[-300:]}")
        elif "A3PLAYTEST_ERROR" in stdout:
            capture_error = stdout[-500:]

        # Encode video if ffmpeg is available
        video_path = None
        if frames and (ffmpeg or shutil.which("ffmpeg")):
            video_path = out / "video.mp4"
            ffmpeg_cmd = str(ffmpeg) if ffmpeg else "ffmpeg"
            try:
                subprocess.run(
                    [
                        ffmpeg_cmd, "-y",
                        "-framerate", str(fps),
                        "-i", str(frames_dir / "f%05d.png"),
                        "-c:v", "libx264",
                        "-pix_fmt", "yuv420p",
                        "-crf", "23",
                        str(video_path),
                    ],
                    capture_output=True,
                    timeout=60,
                )
            except (subprocess.TimeoutExpired, OSError):
                video_path = None

        # Write report
        report = {
            "schema_version": _REPORT_SCHEMA,
            "engine": "godot",
            "status": "passed" if frames else "failed",
            "url": str(project_dir),
            "output_dir": str(out),
            "fps": fps,
            "requested_seconds": duration,
            "recorded_seconds": len(frames) / fps if fps > 0 else 0,
            "viewport": {"width": width, "height": height},
            "headless": headless,
            "action_count": len(actions),
            "requested_actions": [a["action"] for a in actions],
            # only what the recorder actually sent this session
            "executed_actions": delivered,
            "channel_coverage": {
                "actions": {"available": actions_available,
                            "rows": len(action_rows)},
                "states": {"available": states_available,
                           "rows": len(state_rows)},
                "events": {"available": events_available,
                           "rows": len(event_rows)},
                "frames": {"available": bool(frames), "rows": len(frames)},
                "video": {"available": bool(video_path), "rows": None},
            },
            "frames": len(frames),
            "video": str(video_path) if video_path else None,
            "game_state": state_rows[-1].get("state") if state_rows else None,
            "capture_error": capture_error,
            "warnings": ([] if actions_available else
                         ["recorder wrote no actions.jsonl — the input "
                          "delivery channel is missing for this take"]),
            "page_errors": [],
        }
        report_path = out / "report.json"
        report_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        artifacts = [
            {"type": "playtest_report", "path": str(report_path)},
            {"type": "playtest_frames", "path": str(frames_dir)},
        ]
        for name, kind in (("actions.jsonl", "playtest_actions"),
                           ("state_trace.jsonl", "playtest_state_trace"),
                           ("event_trace.jsonl", "playtest_event_trace")):
            trace = out / name
            if trace.is_file() and trace.stat().st_size > 0:
                artifacts.append({"type": kind, "path": str(trace)})
        if video_path:
            artifacts.append({"type": "playtest_video", "path": str(video_path)})

        if not frames:
            return self._fail(
                "recorder captured no frames; "
                f"capture_error: {capture_error[:200]}; "
                f"stdout: {payload['stdout_tail'][:200]}; "
                f"stderr: {payload['stderr_tail'][:200]}",
                payload,
            )
        return self._ok(payload, artifacts)

    def _record_bounded_plan(self, output_dir, plan_path, timeout, width, height, dry_run):
        """Run the existing whitebox read-only field observer via this adapter.

        The trusted host validates the closed, bounded declarative plan. No
        in-game methods are called and no gameplay state is written.
        """
        project=self._config.project_dir
        binary=self._config.godot_executable
        version = json.loads(Path(plan_path).read_text()).get('protocol_version')
        recorder=Path(__file__).with_name('vnext_recorder.gd' if version in {'generic-whitebox.vnext.1', 'generic-whitebox.vnext.2', 'generic-whitebox.vnext.3', 'generic-whitebox.vnext.4', 'generic-whitebox.vnext.5'} else 'bounded_recorder.gd')
        out=Path(output_dir).resolve(); out.mkdir(parents=True,exist_ok=True)
        if not binary or not project or not recorder.is_file():
            return self._fail('bounded observer binary/project/recorder missing')
        protected=['engine.log','actions.jsonl','state_trace.jsonl','execution.json','frame_index.jsonl']
        if any((out/n).exists() for n in protected):
            return self._fail('bounded observer output is single-use; preserve previous take')
        command=[str(binary),'--path',str(project),'--resolution',f'{width}x{height}',
                 '--position','40,70','--script',str(recorder.resolve()),'--',str(plan_path.resolve()),str(out)]
        from .scene_entry import resolve_scene
        scene_entry = resolve_scene(project)
        payload={'command':command,'observer_path':str(recorder),'observation_plan':str(plan_path),'launch_diagnostics':scene_entry}
        (out/'launch_diagnostics.json').write_text(json.dumps(scene_entry,indent=2))
        if recorder.name == 'bounded_recorder.gd':
            if not scene_entry['resolved']:
                return self._fail('Godot delivered entry unresolved: '+scene_entry['classification'],payload)
            command.append(scene_entry['resolved'])
        if dry_run:return self._ok(payload,[])
        import signal
        with (out/'engine.log').open('w') as log:
            process=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            try:code=process.wait(timeout=timeout);timed_out=False
            except subprocess.TimeoutExpired:
                os.killpg(process.pid,signal.SIGTERM)
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait()
                code=process.returncode;timed_out=True
        # The process group was created exclusively for this adapter launch.
        try:
            os.killpg(process.pid, 0)
            group_alive = True
        except ProcessLookupError:
            group_alive = False
        cleanup = {"pid":process.pid, "process_group":process.pid, "returncode":code,
                   "process_cleanup":process.poll() is not None and not group_alive,
                   "view_cleanup":process.poll() is not None and not group_alive,
                   "group_alive_after_wait":group_alive, "timeout":timed_out}
        (out/'process_cleanup.json').write_text(json.dumps(cleanup, indent=2))
        payload.update(exit_code=code,timeout=timed_out,process_cleanup=cleanup)
        if group_alive:return self._fail('bounded observer descendants remain; cleanup unresolved',payload)
        if code or timed_out:return self._fail('bounded observer process did not complete',payload)
        return self._ok(payload,[])

    @staticmethod
    def _read_trace_rows(path: Path) -> tuple[list[dict[str, Any]], bool]:
        """Rows a recorder trace actually wrote; ``(rows, available)``.

        ``available`` is False only when the file is absent — the recorder
        leaves a channel unwritten when it observed nothing, and the client
        never fabricates rows for a missing channel.
        """
        if not path.is_file():
            return [], False
        rows: list[dict[str, Any]] = []
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return [], True
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                rows.append(row)
        return rows, True

    @staticmethod
    def _delivered_actions(action_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Per-step delivery verdicts from the recorder's own actions rows.

        The recorder writes one row per executed step with a ``sent`` flag
        (false for unmapped verbs that were never injected); the report's
        executed_actions summarize those rows — never the request.
        """
        delivered: list[dict[str, Any]] = []
        for row in action_rows:
            if not row.get("action"):
                continue
            verdict = {
                "action": str(row.get("action")),
                "seq": row.get("seq"),
                "t_monotonic_ms": row.get("t_monotonic_ms"),
                "duration_ms": row.get("duration_ms"),
                "sent": bool(row.get("sent")),
                "ok": bool(row.get("sent")),
                "source": str(row.get("source") or "runtime"),
            }
            if not verdict["sent"]:
                verdict["error"] = "recorder did not inject this verb (no mapping)"
            delivered.append(verdict)
        return delivered

    def _load_actions(
        self,
        scenario: str | Path | None,
        action_plan: list[dict[str, Any]] | None,
        duration: float,
    ) -> list[dict[str, Any]] | None:
        if scenario is not None:
            path = Path(scenario)
            if not path.is_file():
                return None
            data = json.loads(path.read_text(encoding="utf-8"))
            actions = data.get("actions", [])
        elif action_plan is not None:
            actions = action_plan
        else:
            # Default: idle + move right + attack + wait
            actions = [
                {"action": "wait", "duration_ms": 1000},
                {"action": "move", "x": 1, "y": 0, "duration_ms": 2000},
                {"action": "attack", "duration_ms": 200},
                {"action": "wait", "duration_ms": 500},
                {"action": "move", "x": -1, "y": 0, "duration_ms": 1500},
                {"action": "jump", "duration_ms": 300},
                {"action": "wait", "duration_ms": 2000},
            ]
        for action in actions:
            if action.get("action") not in ALLOWED_ACTIONS:
                return None
        return actions

    @staticmethod
    def _resolve_main_scene(project_dir) -> "str | None":
        from .scene_entry import resolve_scene
        return resolve_scene(project_dir)['resolved']

    @staticmethod
    def _resolve_main_scene_checked(project_dir) -> dict:
        from .scene_entry import resolve_scene
        return resolve_scene(project_dir)

    @staticmethod
    def _ok(payload: dict[str, Any], artifacts: list[dict[str, str]]) -> dict[str, Any]:
        return {
            "ok": True,
            "operation": _OPERATION,
            "engine": "godot",
            "artifacts": artifacts,
            "diagnostics": [],
            "warnings": [],
            "errors": [],
            "payload": payload,
        }

    @staticmethod
    def _fail(message: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "ok": False,
            "operation": _OPERATION,
            "engine": "godot",
            "artifacts": [],
            "diagnostics": [],
            "warnings": [],
            "errors": [message],
            "payload": payload or {},
        }
