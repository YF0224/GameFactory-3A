"""Record a playtest of a Unity project through a dedicated GUI Editor.

This follows the ``record.md`` contract for Layer 3 (Play Session): the
adapter owns how to launch the game, send real input events, and capture
frames; the pipeline owns the session lifecycle and record placement; the
Agent may contribute a declarative action plan, which is hashed before
execution.

Recording is split across two cooperating processes:

1. **Editor side** — ``GameFactory3APlayTestRecorder`` (installed into the
   project by the transport's ``-executeMethod`` support) opens the play
   scene, focuses the Game view, enters Play Mode, captures
   ``frames/f00001.png`` at the requested frame rate, writes per-frame
   state snapshots from any ``GetStateSnapshot()`` runtime adapter into
   ``diagnostics.jsonl`` (privileged evidence, never shown to the Agent),
   and exits the Editor when the take ends.

2. **Host side** (this client) — launches that Editor, waits for the
   ``play_started.json`` marker, then drives the *player input surface*:
   on macOS it posts real keyboard events through System Events, exactly
   what a player pressing the keys would produce. The exact trace is
   written to ``actions.jsonl`` with monotonic timestamps.

The output follows the standard playtest layout::

    output_dir/
    ├── frames/f00001.png ...   — captured Game-view frames
    ├── video.mp4               — encoded from frames (if ffmpeg available)
    ├── report.json             — actions executed, evidence, warnings
    ├── actions.jsonl           — the exact input trace for replay
    └── diagnostics.jsonl       — engine-side state snapshots (privileged)

A live GUI Editor on the same project is refused: the recording needs a
dedicated Editor instance, and two Editors cannot share one ``Library``.
"""

from __future__ import annotations

import json
import signal
from contextlib import contextmanager
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any
from engine_adapters.action_provenance import action_metadata

from .._internal.transport import UnityEditorTransport
from .._internal.transport.unity_editor import has_injected_compilation_error
from ..config import UnityClientConfig
from ..contracts import UnityOperationResult

_OPERATION = "playtest.record"
_REPORT_SCHEMA = "gamefactory3a.unity3d.playtest_report.v1"
_RECORDER_METHOD = "GameFactory3APlayTestRecorder.Enter"


def _recorder_arguments(method: str, output: Path, scene: str, fps: int,
                        duration: float, warmup: float) -> list[str]:
    # Delivered initializers can react to legacy flags without their entry
    # being selected. Only explicitly selected project harnesses get them.
    prefix = "--gamefactory-evaluation-" if method in {_RECORDER_METHOD, "GameFactory3ARuntimeInitializerRecorder.Enter"} else "--a3-playtest-"
    arguments = ["-skipUpgradeDialogs", "-executeMethod", method,
            f"{prefix}output", str(output), f"{prefix}scene", scene,
            f"{prefix}fps", str(int(fps)), f"{prefix}duration", str(float(duration)),
            f"{prefix}warmup", str(float(warmup))]
    if os.environ.get("GAMEFACTORY_UNITY_CAPTURE_POLICY") == "graphics_batch_render_v2":
        arguments.insert(0, "-batchmode")
    return arguments

#: Allowlisted player-level action names (record.md contract), matching the
#: Godot adapter's allowlist so scenarios stay portable across engines.
ALLOWED_ACTIONS = frozenset({
    "move", "look", "jump", "attack", "interact",
    "dash", "pause", "restart", "wait", "key",
    "mouse_move", "mouse_down", "mouse_up", "mouse_click", "mouse_hold", "mouse_drag", "mouse_wheel",
})

#: input transports: ``system_events`` posts real keyboard events through
#: macOS System Events; ``harness`` delegates the whole input surface to the
#: project's own editor harness (synthetic-input session channel) — the
#: harness drives the plan through the game's declared input path, records
#: per-action delivery verdicts and writes ``actions.jsonl`` itself;
#: ``internal`` uses the bundled ``GameFactory3AInputDriver`` Editor driver
#: which queues keyboard/mouse state through the optional Input System.
#: Legacy/dual backends explicitly fall back to real host input after startup.
INPUT_TRANSPORT_SYSTEM_EVENTS = "system_events"
INPUT_TRANSPORT_HARNESS = "harness"
INPUT_TRANSPORT_INTERNAL = "internal"
_INPUT_TRANSPORTS = frozenset({INPUT_TRANSPORT_SYSTEM_EVENTS, INPUT_TRANSPORT_HARNESS, INPUT_TRANSPORT_INTERNAL})

#: Default player-key bindings. Unity games read the legacy Input class, so
#: the binding is the key character; non-printable keys use macOS key codes.
DEFAULT_KEY_BINDINGS = {
    "jump": "space",
    "attack": "j",
    "interact": "e",
    "dash": "leftshift",
    "pause": "escape",
    "restart": "enter",
}

_KEY_CODES = {
    "space": 49,
    "enter": 36,
    "return": 36,
    "escape": 53,
    "leftshift": 56,
    "left_arrow": 123,
    "right_arrow": 124,
    "down_arrow": 125,
    "up_arrow": 126,
}

_MOVE_KEYS = {"+x": "d", "-x": "a", "+y": "w", "-y": "s"}
_LOOK_KEYS = {"+yaw": "right_arrow", "-yaw": "left_arrow",
              "+pitch": "up_arrow", "-pitch": "down_arrow"}

#: A fighting-style default take: survive the round countdown, approach,
#: attack, trade with the AI opponent. AI P2 attacks by itself, so hits are
#: recorded even when P1 misses.
DEFAULT_ACTIONS: list[dict[str, Any]] = [
    {"action": "wait", "duration_ms": 3500},
    {"action": "move", "x": 1, "y": 0, "duration_ms": 900},
    {"action": "attack", "duration_ms": 200},
    {"action": "wait", "duration_ms": 700},
    {"action": "attack", "duration_ms": 200},
    {"action": "wait", "duration_ms": 700},
    {"action": "attack", "duration_ms": 200},
    {"action": "wait", "duration_ms": 900},
    {"action": "move", "x": -1, "y": 0, "duration_ms": 600},
    {"action": "attack", "duration_ms": 200},
    {"action": "wait", "duration_ms": 3800},
]

_EDITOR_BOOT_TIMEOUT = 300.0
_EDITOR_SHUTDOWN_TIMEOUT = 180.0


class UnityPlaytestClient:
    """Launch a dedicated Unity Editor and record one playtest take."""

    def __init__(self, config: UnityClientConfig) -> None:
        self._config = config

    def record(
        self,
        *,
        output_dir: str | Path,
        scene: str = "",
        scenario: str | Path | None = None,
        action_plan: list[dict[str, Any]] | None = None,
        duration: float = 12.0,
        fps: int = 20,
        warmup: float = 0.0,
        timeout: float = 900.0,
        ffmpeg: str | Path | None = None,
        dry_run: bool = False,
        input_transport: str = INPUT_TRANSPORT_SYSTEM_EVENTS,
        missing_scene_diagnostic: bool = False,
        execute_method: str = _RECORDER_METHOD,
        runtime_entry: str | Path | None = None,
    ) -> dict[str, Any]:
        """Record one playtest into ``output_dir``.

        Args:
            scene: Play scene as an absolute path or a project-relative
                ``Assets/...`` path. Defaults to the first scene in
                EditorBuildSettings.
            scenario: Path to a scenario JSON file (``{"actions": [...]}``).
            action_plan: Inline action list, same format as a scenario's
                ``actions`` (overrides the default fighting take).
            duration: Take length in seconds.
            fps: Capture frame rate.
            warmup: Seconds the Editor captures but the scenario delays.
            timeout: Maximum seconds from input readiness through Editor exit.
                Import/startup and video encoding use separate bounded budgets.
            ffmpeg: Optional ffmpeg binary for encoding ``video.mp4``.
            dry_run: Validate and print the plan without running.
            input_transport: ``internal`` consumes the expanded JSON events
                in the bundled Editor input driver; ``system_events`` (real
                keyboard and mouse events via
                macOS System Events) or ``harness`` — the project's own
                editor harness owns the input surface (synthetic-input
                session channel declared by the game's mechanic contract),
                drives the plan, records delivery verdicts and writes
                ``actions.jsonl`` itself; this client never touches
                System Events in that mode.
            execute_method: the static editor entry the Editor runs via
                ``-executeMethod`` (default: the public
                ``GameFactory3APlayTestRecorder``); harness mode names the
                project's own harness entry instead.
        """
        if input_transport not in _INPUT_TRANSPORTS:
            return self._fail(
                f"unknown input_transport {input_transport!r} "
                f"(supported: {sorted(_INPUT_TRANSPORTS)})"
            )
        background = os.environ.get("GAMEFACTORY_UNITY_CAPTURE_POLICY") in {"background_inputsystem_v1", "graphics_batch_render_v2"}
        if background and input_transport != INPUT_TRANSPORT_INTERNAL:
            return self._fail("background capture requires verified native InputSystem internal transport")
        harness_input = input_transport == INPUT_TRANSPORT_HARNESS
        internal_input = input_transport == INPUT_TRANSPORT_INTERNAL
        recorder_method = str(execute_method or _RECORDER_METHOD).strip() or _RECORDER_METHOD
        if harness_input and recorder_method == _RECORDER_METHOD:
            return self._fail(
                "harness input_transport needs the project's own harness "
                "execute_method (e.g. 'WbPlayTestHarness.Enter')"
            )
        project = self._config.project_path
        if project is None or not (project / "Assets").is_dir():
            return self._fail("project_path must resolve to a Unity project")
        import math
        if not all(math.isfinite(float(v)) for v in (duration, fps, warmup, timeout)):
            return self._fail("duration, fps, warmup and timeout must be finite")
        if duration <= 0 or fps <= 0 or warmup < 0 or timeout <= 0:
            return self._fail("duration, fps and timeout must be positive; warmup must be nonnegative")
        if timeout < duration + warmup:
            return self._fail("timeout must cover the requested duration plus warmup")

        runtime_binding = None
        runtime_arguments = []
        if runtime_entry is not None:
            from . import runtime_initializer
            if (input_transport != INPUT_TRANSPORT_INTERNAL or not background
                    or recorder_method != _RECORDER_METHOD):
                return self._fail('Runtime initializer requires accepted native background recorder')
            runtime_binding = runtime_initializer.load(runtime_entry, project)
            if scene not in ('', runtime_binding['source']):
                return self._fail('Runtime scene identifier differs from source-bound initializer')
            resolved_scene, scene_error = '', None
            recorder_method = runtime_initializer.METHOD
            runtime_arguments = runtime_initializer.arguments(runtime_binding, Path(output_dir).expanduser().resolve())
        else:
            resolved_scene, scene_error = self._resolve_scene(scene)
        if scene_error:
            # An incomplete delivery still deserves a real import attempt. Do
            # not construct a scene or replace the delivered startup scene.
            if missing_scene_diagnostic and ((scene and not (project / scene).is_file()) or (not scene and not any((project / "Assets").rglob("*.unity")))):
                return self._diagnose_missing_scene(output_dir, scene_error, min(timeout or 180, 180))
            return self._fail(scene_error)

        actions, actions_error = self._load_actions(scenario, action_plan)
        if actions_error:
            return self._fail(actions_error)

        transport = UnityEditorTransport(self._config)
        unity_binary = transport.unity_binary
        if unity_binary is None or not unity_binary.is_file():
            return self._fail("Unity editor binary is not configured; set project or A3GAME_UNITY_ROOT")
        if transport.is_editor_live():
            return self._fail(
                "a GUI Editor is already open for this project; close it "
                "before recording (a dedicated Editor instance is required)"
            )

        out = Path(output_dir).expanduser().resolve(strict=False)
        encoder = Path(ffmpeg).expanduser() if ffmpeg else None
        events = self._timeline(actions)
        plan_seconds = sum(
            int(item.get("duration_ms", 100)) for item in actions
        ) / 1000.0
        if plan_seconds > duration:
            return self._fail(
                f"scenario needs {plan_seconds:.1f}s but duration is {duration:.1f}s"
            )

        payload: dict[str, Any] = {
            "engine": "unity3d",
            "project_dir": str(project),
            "scene": str(resolved_scene),
            "output_dir": str(out),
            "report_path": str(out / "report.json"),
            "duration": duration,
            "fps": fps,
            "warmup": warmup,
            "action_count": len(actions),
            "budgets": {"schema": "unity-record-stage-budgets.v1",
                        "startup_seconds": _EDITOR_BOOT_TIMEOUT,
                        "gameplay_seconds": duration, "warmup_seconds": warmup,
                        "ready_to_editor_exit_seconds": timeout,
                        "shutdown_seconds_max": _EDITOR_SHUTDOWN_TIMEOUT,
                        "encoding_seconds_max": 120},
            "timings": {},
            "actions": actions,
            "events": [
                {key: value for key, value in event.items() if key != "index"}
                for event in events
            ],
            "unity_binary": str(unity_binary),
            "ffmpeg": str(encoder) if encoder else None,
            "input_transport": input_transport,
        }
        if dry_run:
            return UnityOperationResult.success(
                _OPERATION,
                payload=payload,
            ).to_dict()

        if harness_input:
            # the project's own harness owns the input surface — no host
            # keyboard driver is involved, so no Accessibility permission
            # can be required
            pass
        elif internal_input:
            # Input System-only projects are driven inside Play Mode. The
            # backend marker may require physical input; check permissions then.
            pass
        else:
            input_error = self._check_input_driver()
            if input_error:
                return self._fail(input_error, payload)

        out.mkdir(parents=True, exist_ok=True)
        evidence_names = ("frames", "report.json", "video.mp4", "actions.jsonl", "diagnostics.jsonl",
                          "state_trace.jsonl", "event_trace.jsonl", "play_started.json", "input_focus.json",
                          "_editor_report.json", "_scenario.json", "frame_index.jsonl")
        if any((out / name).exists() for name in evidence_names):
            return self._fail("take directory already contains evidence; use a fresh recovery attempt", payload)
        (out / "_scenario.json").write_text(
            json.dumps(
                {"actions": actions, "events": events, "fps": fps, "duration": duration,
                 "use_internal_driver": internal_input},
                indent=2,
            ),
            encoding="utf-8",
        )

        baseline_processes = _process_snapshot()
        launch_started = time.monotonic()
        process = transport.launch_editor(
            scene_path=str(resolved_scene),
            extra_args=_recorder_arguments(recorder_method, out, str(resolved_scene),
                                           fps, duration, warmup) + runtime_arguments,
        )
        with self._owned_editor_session(process, out, payload, project=self._config.project_path, baseline_processes=baseline_processes):
            payload["process_id"] = process.pid
            payload["execute_method"] = recorder_method

            marker = out / "play_started.json"
            if not self._wait_for_marker(marker, process, payload, _EDITOR_BOOT_TIMEOUT,
                                         require_os_focus=not background and not harness_input and os.sys.platform == "darwin"):
                self._stop_process(process)
                return self._fail(
                    payload.get("error") or "Unity Editor did not become input-ready",
                    payload,
                )

            ready_observed = time.monotonic()
            ready_deadline = ready_observed + timeout
            payload["timings"]["startup_seconds"] = ready_observed - launch_started
            marker_data = json.loads(marker.read_text(encoding="utf-8"))
            if internal_input and marker_data.get("input_transport") == INPUT_TRANSPORT_SYSTEM_EVENTS:
                # The Editor knows the compiled backend. IMGUI events do not feed
                # legacy Input.GetKey/GetMouseButton; use real physical input.
                if background:
                    self._stop_process(process)
                    return self._fail("background InputSystem unavailable; physical/focus fallback forbidden", payload)
                internal_input = False
                payload["requested_input_transport"] = input_transport
                payload["input_transport"] = INPUT_TRANSPORT_SYSTEM_EVENTS
                payload["input_transport_reason"] = "legacy or dual backend requires physical input"
                input_error = self._check_input_driver()
                if input_error:
                    self._stop_process(process)
                    return self._fail("HARNESS_ERROR: " + input_error, payload)
            if background and not (marker_data.get("experimental_background") is True and marker_data.get("background_render_ready") is True):
                self._stop_process(process)
                return self._fail("background first usable frame readiness missing", payload)
            payload["capture_policy"] = os.environ["GAMEFACTORY_UNITY_CAPTURE_POLICY"] if background else "foreground"
            started = self._align_to_take_start(marker)
            ready_offset = float(marker_data.get("recorder_elapsed_ms", 0)) / 1000.0
            require_focus = marker_data.get("input_ready") is True
            payload["input_readiness"] = marker_data
            payload["play_started_at"] = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
            )
            warnings: list[str] = []
            deliveries: list[dict[str, Any]] = []
            if harness_input:
                # the in-project harness drives the plan through the game's
                # synthetic-input channel and writes actions.jsonl itself —
                # the host only observes the take; delivery verdicts are read
                # back from what the harness actually wrote
                payload["input_driver"] = "project_harness (synthetic-input session channel)"
            elif internal_input:
                # GameFactory3AInputDriver (bundled) drives input from inside Play Mode
                # via InputSystem.QueueStateEvent or the GameView input queue —
                # no OS focus needed; actions.jsonl written by the driver itself
                payload["input_driver"] = "internal_driver (GameFactory3AInputDriver)"
            else:
                warnings, deliveries = self._drive_events(
                    process.pid, events, started, out, warmup + ready_offset,
                    require_focus=require_focus, recover_focus=True, deadline=started + ready_offset + warmup + duration,
                    trace_name="host_input_actions.jsonl")
                payload["delivery_verdicts"] = deliveries

            capture_deadline = started + ready_offset + warmup + duration
            exit_deadline = min(capture_deadline + _EDITOR_SHUTDOWN_TIMEOUT, ready_deadline)
            payload["budgets"]["effective_shutdown_seconds"] = max(0, exit_deadline - capture_deadline)
            payload["timings"]["input_dispatch_finished_seconds_after_ready"] = time.monotonic() - ready_observed
            if not self._wait_for_exit(process, exit_deadline):
                warnings.append("Editor did not exit on time; terminating")
                self._stop_process(process)

            payload["timings"]["editor_exit_seconds_after_ready"] = time.monotonic() - ready_observed
            if not harness_input and not internal_input:
                self._combine_action_traces(out)

            editor_report = self._read_editor_report(out, payload)
            frames = sorted((out / "frames").glob("f*.png")) if (out / "frames").is_dir() else []
            encoding_started = time.monotonic()
            sparse_capture = (out / 'capture_schedule.json').is_file()
            video_path = None if sparse_capture else self._encode_video(out, frames, fps, encoder)
            if sparse_capture:
                payload['video_policy'] = 'Predeclared sparse stills and native temporal sequences; no full-route continuous video.'
            payload["timings"]["encoding_seconds"] = time.monotonic() - encoding_started
            # executed_actions summarize what the take actually delivered —
            # harness rows or the host's per-key-event verdicts, never the
            # requested plan
            delivered, action_rows = self._summarize_delivered_actions(out)
            editor_channels = (editor_report or {}).get("channels") or {}
            if events and action_rows == 0:
                warnings.append(
                    "actions.jsonl was not written: no input delivery was "
                    "recorded for this take (input send channel missing)")
            capture_errors = list((editor_report or {}).get("errors") or [])
            if background:
                for cleanup_name in ("background_input_cleanup.json", "background_view_cleanup.json"):
                    cleanup_path = out / cleanup_name
                    try:
                        cleanup_report = json.loads(cleanup_path.read_text(encoding="utf-8-sig"))
                    except (OSError, ValueError) as error:
                        cleanup_report = {"ok": False, "error": str(error)}
                    payload[cleanup_name.removesuffix(".json")] = cleanup_report
                    if cleanup_report.get("ok") is not True:
                        capture_errors.append("HARNESS_ERROR: cleanup unconfirmed: " + cleanup_name)
            if len(frames) < 2:
                capture_errors.append("HARNESS_ERROR: insufficient runtime frames (minimum two required)")
            if editor_report is None:
                capture_errors.append("HARNESS_ERROR: editor report missing")
            if events and action_rows == 0:
                capture_errors.append("HARNESS_ERROR: input trace missing for nonempty event plan")
            if any(item.get("sent") is False for item in delivered):
                capture_errors.append("HARNESS_ERROR: input delivery failed")
            if not harness_input and not internal_input and recorder_method == _RECORDER_METHOD and not require_focus:
                capture_errors.append("HARNESS_ERROR: recorder did not attest focused first-frame readiness")
            capture_ok = not capture_errors and (editor_report or {}).get("ok") is True
            report = {
                "schema_version": _REPORT_SCHEMA,
                "engine": "unity3d",
                "status": "passed" if capture_ok else "failed",
                "url": str(project),
                "output_dir": str(out),
                "scene": str(resolved_scene),
                "fps": fps,
                "requested_seconds": duration,
                # The Editor throttles play mode when idle; the real wall time of
                # the last capture is the honest length, not frames/fps.
                "recorded_seconds": (
                    (editor_report or {}).get("recorded_seconds")
                ),
                "viewport": (editor_report or {}).get("viewport") or [],
                "warmup": warmup,
                "action_count": len(actions),
                "executed_actions": delivered,
                "requested_actions": [item["action"] for item in actions],
                "channel_coverage": {
                    "actions": {"available": action_rows > 0, "rows": action_rows},
                    "states": {
                        "available": bool(editor_channels.get("states_available")),
                        "rows": int(editor_channels.get("state_rows") or 0),
                        "source": str(editor_channels.get("states_source") or ""),
                    },
                    "events": {
                        "available": bool(editor_channels.get("events_available")),
                        "rows": int(editor_channels.get("event_rows") or 0),
                        "subscriptions": int(editor_channels.get("event_subscriptions") or 0),
                    },
                    "frames": {"available": bool(frames), "rows": len(frames)},
                    "video": {"available": bool(video_path), "rows": None},
                },
                "frames": len(frames),
                "video": str(video_path) if video_path else None,
                "game_state": None,
                "warnings": warnings,
                "errors": capture_errors,
                "input_readiness": marker_data,
                "editor_report": editor_report,
            }
            report_path = out / "report.json"
            report_path.write_text(
                json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            payload["report"] = report

            if not capture_ok:
                return self._fail(
                    capture_errors or ["HARNESS_ERROR: recorder did not finish successfully"],
                    payload,
                )

            artifacts = [
                {"type": "playtest_report", "path": str(report_path)},
                {"type": "playtest_actions", "path": str(out / "actions.jsonl")},
                {"type": "playtest_frames", "path": str(out / "frames")},
            ]
            if (out / "diagnostics.jsonl").is_file():
                artifacts.append({
                    "type": "playtest_diagnostics",
                    "path": str(out / "diagnostics.jsonl"),
                })
            for name, kind in (
                ("state_trace.jsonl", "playtest_state_trace"),
                ("event_trace.jsonl", "playtest_event_trace"),
            ):
                trace = out / name
                if trace.is_file() and trace.stat().st_size > 0:
                    artifacts.append({"type": kind, "path": str(trace)})
            if video_path:
                artifacts.append({"type": "playtest_video", "path": str(video_path)})
            return UnityOperationResult.success(
                _OPERATION,
                artifacts=artifacts,
                warnings=[
                    str(item) for item in (editor_report or {}).get("warnings", [])
                ] + [str(item) for item in report["warnings"]],
                payload=payload,
            ).to_dict()

    # ── Scenario handling ─────────────────────────────────────────────────

    def _load_actions(
        self,
        scenario: str | Path | None,
        action_plan: list[dict[str, Any]] | None,
    ) -> tuple[list[dict[str, Any]] | None, str | None]:
        actions: list[dict[str, Any]]
        if scenario is not None:
            path = Path(scenario).expanduser()
            if not path.is_file():
                return None, f"scenario file does not exist: {path}"
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                return None, f"invalid scenario JSON: {exc}"
            actions = list(data.get("actions") or [])
        elif action_plan is not None:
            actions = list(action_plan)
        else:
            actions = [dict(item) for item in DEFAULT_ACTIONS]
        for action in actions:
            if not isinstance(action, dict) or action.get("action") not in ALLOWED_ACTIONS:
                return None, (
                    "invalid action plan: use allowlisted action names "
                    f"{sorted(ALLOWED_ACTIONS)}"
                )
            raw_duration = action.get("duration_ms", 100)
            try:
                duration_ms = int(raw_duration)
            except (TypeError, ValueError, OverflowError):
                return None, "duration_ms must be a positive integer"
            if (isinstance(raw_duration, bool) or duration_ms <= 0
                    or isinstance(raw_duration, float) and not raw_duration.is_integer()):
                return None, "duration_ms must be a positive integer"
            if action.get("action") == "key":
                import re
                if not re.fullmatch(r"(?:[a-z0-9]|space|enter|return|escape|leftshift|rightshift|leftcontrol|rightcontrol|leftalt|rightalt|left_arrow|right_arrow|up_arrow|down_arrow|tab|backspace|delete|insert|home|end|pageup|pagedown|capslock|comma|period|slash|backslash|semicolon|apostrophe|minus|equals|leftbracket|rightbracket|backquote|f[1-9]|f1[0-2]|numpad[0-9]|numpadenter|lmb|rmb)(?:\+(?:[a-z0-9]|space|enter|return|escape|leftshift|rightshift|leftcontrol|rightcontrol|leftalt|rightalt|left_arrow|right_arrow|up_arrow|down_arrow|tab|backspace|delete|insert|home|end|pageup|pagedown|capslock|comma|period|slash|backslash|semicolon|apostrophe|minus|equals|leftbracket|rightbracket|backquote|f[1-9]|f1[0-2]|numpad[0-9]|numpadenter)){0,2}", str(action.get("key", "")).lower()):
                    return None, "invalid physical key action"
            if action.get("action") in {"mouse_move", "mouse_down", "mouse_up", "mouse_click", "mouse_hold", "mouse_drag", "mouse_wheel"}:
                if str(action.get("button", "left")).lower() not in {"left", "right", "middle", "lmb", "rmb", "mmb"}:
                    return None, "invalid mouse button"
                for coordinate in ("x", "y"):
                    value = action.get(coordinate)
                    if isinstance(value, bool):
                        return None, f"mouse {coordinate} must be numeric"
                    try:
                        if not 0.0 <= float(value) <= 1.0:
                            return None, f"mouse {coordinate} must be in [0, 1]"
                    except (TypeError, ValueError):
                        return None, f"mouse {coordinate} must be numeric"
        if not actions:
            return None, "action plan must not be empty"
        return actions, None

    @staticmethod
    def _timeline(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Expand keyboard and normalized-coordinate mouse actions.

        Every key event carries the action it belongs to, so the written
        actions.jsonl can report per-action delivery verdicts instead of
        replaying the request plan.
        """
        events: list[dict[str, Any]] = []
        t_ms = 0
        last_xy = None
        for index, action in enumerate(actions):
            name = str(action.get("action", ""))
            duration_ms = int(action.get("duration_ms", 100))
            if name == "wait":
                t_ms += duration_ms
                continue
            if name == "key":
                for key in str(action.get("key", "")).lower().split("+"):
                    if not key:
                        raise ValueError("empty physical key")
                    if key.lower() in {"lmb", "rmb"}:
                        mouse = {"action": "mouse_click", "index": index,
                                 "button": "left" if key == "lmb" else "right", "x": 0.5, "y": 0.5}
                        events.append({**mouse, "t_ms": t_ms, "phase": "down"})
                        events.append({**mouse, "t_ms": t_ms + min(duration_ms, 80), "phase": "up"})
                    else:
                        events.append({"t_ms": t_ms, "phase": "down", "key": key, "action": name, "index": index})
                        events.append({"t_ms": t_ms + max(duration_ms, 100), "phase": "up", "key": key, "action": name, "index": index})
                t_ms += max(duration_ms, 100)
                continue
            if name in {"mouse_move", "mouse_down", "mouse_up", "mouse_click", "mouse_hold", "mouse_drag", "mouse_wheel"}:
                button = str(action.get("button", "left")).lower()
                button = {"lmb": "left", "rmb": "right", "mmb": "middle"}.get(button, button)
                mouse = {"action": name, "index": index, "button": button,
                         "x": float(action["x"]), "y": float(action["y"])}
                if name == "mouse_move":
                    fx, fy = last_xy or (0.5, 0.5)          # cursor starts at the viewport centre
                    steps = max(1, min(40, duration_ms // 50))
                    for i in range(1, steps + 1):
                        events.append({**mouse, "t_ms": t_ms + duration_ms * i / steps, "phase": "move",
                                       "x": fx + (mouse["x"] - fx) * i / steps, "y": fy + (mouse["y"] - fy) * i / steps})
                    last_xy = (mouse["x"], mouse["y"])
                    t_ms += duration_ms
                    continue
                last_xy = (mouse["x"], mouse["y"]) if name != "mouse_drag" else (float(action["to_x"]), float(action["to_y"]))
                if name == "mouse_click":
                    events.append({**mouse, "t_ms": t_ms, "phase": "move"})
                    events.append({**mouse, "t_ms": t_ms, "phase": "down"})
                    events.append({**mouse, "t_ms": t_ms + min(duration_ms, 80), "phase": "up"})
                elif name == "mouse_hold":
                    events.append({**mouse, "t_ms": t_ms, "phase": "move"})
                    events.append({**mouse, "t_ms": t_ms, "phase": "down"})
                    events.append({**mouse, "t_ms": t_ms + duration_ms, "phase": "up"})
                elif name == "mouse_drag":
                    tx, ty = float(action["to_x"]), float(action["to_y"])
                    events.append({**mouse, "t_ms": t_ms, "phase": "move"})
                    events.append({**mouse, "t_ms": t_ms, "phase": "down"})
                    steps = max(2, min(40, duration_ms // 50))
                    for i in range(1, steps + 1):
                        events.append({**mouse, "t_ms": t_ms + duration_ms * i / steps, "phase": "move",
                                       "x": mouse["x"] + (tx - mouse["x"]) * i / steps,
                                       "y": mouse["y"] + (ty - mouse["y"]) * i / steps})
                    events.append({**mouse, "t_ms": t_ms + duration_ms, "phase": "up", "x": tx, "y": ty})
                elif name == "mouse_wheel":
                    events.append({**mouse, "t_ms": t_ms, "phase": "move"})
                    events.append({**mouse, "t_ms": t_ms, "phase": "wheel",
                                   "wheel": -float(action.get("delta_y", 0) or 0) / 120.0})
                else:
                    phase = "move" if name == "mouse_move" else name.removeprefix("mouse_")
                    events.append({**mouse, "t_ms": t_ms, "phase": phase})
                t_ms += duration_ms
                continue
            if name == "move":
                x = int(action.get("x", 0) or 0)
                y = int(action.get("y", 0) or 0)
                keys = []
                if x:
                    keys.append(_MOVE_KEYS["+x" if x > 0 else "-x"])
                if y:
                    keys.append(_MOVE_KEYS["+y" if y > 0 else "-y"])
                for key in keys:
                    events.append({"t_ms": t_ms, "phase": "down", "key": key, "action": name, "index": index})
                for key in keys:
                    events.append({"t_ms": t_ms + max(duration_ms, 100), "phase": "up", "key": key, "action": name, "index": index})
                t_ms += max(duration_ms, 100)
                continue
            if name == "look":
                yaw = int(action.get("yaw_delta", 0) or 0)
                pitch = int(action.get("pitch_delta", 0) or 0)
                if yaw:
                    events.append({"t_ms": t_ms, "phase": "tap", "key": _LOOK_KEYS["+yaw" if yaw > 0 else "-yaw"], "action": name, "index": index})
                if pitch:
                    events.append({"t_ms": t_ms, "phase": "tap", "key": _LOOK_KEYS["+pitch" if pitch > 0 else "-pitch"], "action": name, "index": index})
                t_ms += max(duration_ms, 100)
                continue
            key = str(DEFAULT_KEY_BINDINGS.get(name, ""))
            if key:
                events.append({"t_ms": t_ms, "phase": "tap", "key": key, "action": name, "index": index})
            t_ms += max(duration_ms, 100)
        for event in events:
            event.update(action_metadata(actions[event['index']]))
        events.sort(key=lambda item: item["t_ms"])
        return events

    # ── Editor lifecycle ───────────────────────────────────────────────────

    def _diagnose_missing_scene(self, output_dir, scene_error, timeout):
        """Use the same GUI transport for import; never create playable content."""
        out = Path(output_dir).expanduser().resolve(strict=False)
        out.mkdir(parents=True, exist_ok=True)
        transport = UnityEditorTransport(self._config)
        if transport.is_editor_live():
            return self._fail("a GUI Editor is already open for this project")
        payload = {"engine": "unity3d", "missing_startup_diagnostic": True,
                   "inputs_sent": False, "scene_error": scene_error,
                   "confirmed_missing_startup": False}
        baseline_processes = _process_snapshot()
        launch_started = time.monotonic()
        process = transport.launch_editor(extra_args=["-skipUpgradeDialogs", "-quit"])
        with self._owned_editor_session(process, out, payload, project=self._config.project_path, baseline_processes=baseline_processes):
            payload["process_id"] = process.pid
            payload["command"] = process.args
            try:
                payload["editor_exit_code"] = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self._stop_process(process)
                payload["timeout"] = True
            log = self._config.project_path / "Library/GameFactory3A/Editor.log"
            if log.is_file():
                shutil.copyfile(log, out / "launch.log")
                text = log.read_text(errors="replace")
                # A license/SDK/environment abort cannot establish a product fault.
                compiler_error = __import__("re").search(r"error CS\d+", text)
                payload["confirmed_missing_startup"] = (payload.get("editor_exit_code") == 0 or bool(compiler_error))
            (out / "launch_result.json").write_text(json.dumps(payload, indent=2))
            return self._fail(scene_error, payload)

    def _resolve_scene(self, scene: str) -> tuple[Path | None, str | None]:
        project = self._config.project_path
        if not project:
            return None, "project_path is not configured"
        if scene:
            candidate = Path(scene).expanduser()
            if not candidate.is_absolute():
                candidate = project / scene
            if not candidate.is_file():
                return None, f"play scene was not found: {scene}"
            return candidate.resolve(strict=False), None
        built = self._first_build_settings_scene(project)
        if built:
            return built, None
        scenes = sorted((project / "Assets").rglob("*.unity")) if (project / "Assets").is_dir() else []
        listing = ", ".join(
            str(item.relative_to(project)) for item in scenes[:8]
        ) or "none"
        return None, (
            "no play scene given and EditorBuildSettings has none; "
            f"pass --scene with one of: {listing}"
        )

    @staticmethod
    def _first_build_settings_scene(project: Path) -> Path | None:
        settings = project / "ProjectSettings" / "EditorBuildSettings.asset"
        if not settings.is_file():
            return None
        for line in settings.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if stripped.startswith("path:") and "Assets/" in stripped:
                relative = stripped.split("path:", 1)[1].strip()
                candidate = project / relative
                if candidate.is_file():
                    return candidate
        return None

    @staticmethod
    def _wait_for_marker(
        marker: Path,
        process: subprocess.Popen[Any],
        payload: dict[str, Any],
        timeout: float,
        *, require_os_focus: bool = False,
    ) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            # App registration, import and window creation share the existing
            # boot deadline. Do not block initialization on a pre-window focus.
            focused = not require_os_focus
            if require_os_focus and process.poll() is None:
                focused, error = _focus_process(process.pid)
                payload["os_focus"] = {"target_pid": process.pid, "verified": focused,
                                       "error": error or None}
            if marker.is_file() and focused:
                return True
            if process.poll() is not None:
                payload["editor_exit_code"] = process.returncode
                log_tail = _log_tail(payload.get("project_dir", ""))
                payload["editor_log_tail"] = log_tail
                # Classify the early exit based on log content
                payload["error"] = _editor_failure_context(marker, payload, process.returncode)
                return False
            time.sleep(0.5)
        log_tail = _log_tail(payload.get("project_dir", ""))
        payload["editor_log_tail"] = log_tail
        payload["error"] = _editor_failure_context(marker, payload, None)
        return False

    @staticmethod
    def _wait_for_exit(process: subprocess.Popen[Any], deadline: float) -> bool:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                return True
            time.sleep(1.0)
        return False

    @staticmethod
    def _stop_process(process: subprocess.Popen[Any]) -> None:
        """Stop only the owned child and reap it even after escalation."""
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=15)

    @staticmethod
    @contextmanager
    def _owned_editor_session(process: subprocess.Popen[Any], out: Path, payload: dict[str, Any], *, project: Path | None = None, baseline_processes: dict | None = None):
        # launch_editor starts a dedicated POSIX session. Capture ownership
        # while the child still exists; never search/kill by application name.
        pgid = None
        if os.name != "nt":
            try:
                group = os.getpgid(process.pid)
                if group == process.pid:
                    pgid = group
            except ProcessLookupError:
                pass
        record = {"schema_version": "unity-owned-editor-cleanup.v1",
                  "pid": process.pid, "owned_pgid": pgid,
                  "command": process.args, "session_started_unix": time.time(),
                  "process_exit_verified": False, "group_exit_verified": pgid is None,
                  "detached_groups": [], "detached_exit_verified": project is None}
        # Results use shallow payload copies; fill this same nested object in
        # finally so success/failure callers both receive the exit attestation.
        payload["cleanup"] = record
        try:
            yield
        finally:
            record["started_unix"] = time.time()
            errors = []
            try:
                UnityPlaytestClient._stop_process(process)
                record["process_exit_verified"] = process.poll() is not None
                record["returncode"] = process.returncode
                if pgid is not None:
                    def group_live():
                        try:
                            os.killpg(pgid, 0)
                            return True
                        except ProcessLookupError:
                            return False
                    if group_live():
                        os.killpg(pgid, signal.SIGTERM)
                        end = time.monotonic() + 5
                        while group_live() and time.monotonic() < end:
                            time.sleep(.1)
                        if group_live():
                            os.killpg(pgid, signal.SIGKILL)
                            end = time.monotonic() + 5
                            while group_live() and time.monotonic() < end:
                                time.sleep(.1)
                    record["group_exit_verified"] = not group_live()
                if project is not None:
                    # Hub detaches via launch services into its own session.
                    # Only a NEW group leader carrying this exact isolated
                    # -projectPath is ours. Never touch pre-existing/shared Hub.
                    for row in _detached_project_groups(project, baseline_processes or {}):
                        attestation = dict(row)
                        record["detached_groups"].append(attestation)
                        _stop_owned_group(row["pgid"], expected=row)
                        attestation["exit_verified"] = not _group_live(row["pgid"])
                    record["detached_exit_verified"] = (
                        all(row.get("exit_verified") for row in record["detached_groups"])
                        and not _detached_project_groups(project, baseline_processes or {}))

            except BaseException as error:
                errors.append(str(error))
            record["errors"] = errors
            record["finished_unix"] = time.time()
            record["ok"] = bool(record["process_exit_verified"] and record["group_exit_verified"] and record["detached_exit_verified"] and not errors)
            payload["cleanup"] = record
            temporary = out / "editor_cleanup.json.tmp"
            temporary.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
            temporary.replace(out / "editor_cleanup.json")
            if not record["ok"]:
                raise RuntimeError("HARNESS_ERROR: owned Unity process cleanup unconfirmed; do not start next case")

    @staticmethod
    def _read_editor_report(out: Path, payload: dict[str, Any]) -> dict[str, Any] | None:
        path = out / "_editor_report.json"
        if not path.is_file():
            payload["editor_report_missing"] = True
            payload["editor_log_tail"] = _log_tail(payload.get("project_dir", ""))
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            payload["editor_report_invalid"] = f"{type(exc).__name__}: {exc}"
            return None

    @staticmethod
    def _encode_video(
        out: Path,
        frames: list[Path],
        fps: int,
        encoder: Path | None,
    ) -> Path | None:
        if not frames:
            return None
        binary = encoder or shutil.which("ffmpeg")
        if not binary:
            return None
        video_path = out / "video.mp4"
        try:
            subprocess.run(
                [
                    str(binary), "-y",
                    "-framerate", str(max(fps, 1)),
                    "-i", str(out / "frames" / "f%05d.png"),
                    # Editor captures can have odd heights (for example
                    # 2048x1207); yuv420p requires even dimensions.
                    "-vf", "crop=trunc(iw/2)*2:trunc(ih/2)*2",
                    "-c:v", "libx264",
                    "-pix_fmt", "yuv420p",
                    "-crf", "23",
                    str(video_path),
                ],
                capture_output=True,
                timeout=120,
            )
        except (subprocess.TimeoutExpired, OSError):
            return None
        return video_path if video_path.is_file() else None

    # ── Player input ──────────────────────────────────────────────────────

    def _check_input_driver(self) -> str | None:
        import platform

        if platform.system() != "Darwin":
            return (
                "Unity playtest input injection is currently implemented "
                "for macOS only (System Events); on this platform the take "
                "would record without player input"
            )
        # Preflight Quartz availability before attempting System Events
        try:
            import Quartz
            if not hasattr(Quartz, 'CGEventCreateKeyboardEvent'):
                return (
                    "Quartz module is available but CGEventCreateKeyboardEvent is not; "
                    "install pyobjc-framework-Quartz: pip install pyobjc-framework-Quartz"
                )
        except ImportError:
            return (
                "Quartz module is not available for keyboard injection; "
                "install pyobjc-framework-Quartz: pip install pyobjc-framework-Quartz"
            )
        ok, error = _osascript(
            'tell application "System Events" to get name of first application process'
        )
        if not ok:
            return (
                "System Events is not available for keyboard injection: "
                f"{error}. Grant the calling terminal Accessibility "
                "permission (System Settings → Privacy & Security → "
                "Accessibility) and retry."
            )
        return None

    @staticmethod
    def _drive_events(
        process_id: int,
        events: list[dict[str, Any]],
        started: float,
        out: Path,
        warmup: float,
        *, require_focus: bool = False, recover_focus: bool = False, deadline: float | None = None,
        trace_name: str = "actions.jsonl",
    ) -> tuple[list[str], list[dict[str, Any]]]:
        """Post key events on schedule; return warnings + per-action verdicts.

        Every row records the real delivery result of one key
        event (``sent`` from the System Events call), and the returned
        per-action verdicts aggregate them — a failed injection is an input
        delivery failure, never recorded as an executed action.
        """
        warnings: list[str] = []
        actions_path = out / trace_name
        held: set[tuple[str, str]] = set()
        last_mouse = (0.5, 0.5)
        seq = 0
        deliveries: dict[int, dict[str, Any]] = {}
        with actions_path.open("w", encoding="utf-8") as handle:
            try:
                for event in events:
                    t_ms = int(event["t_ms"])
                    phase = str(event["phase"])
                    action_name = str(event.get("action", "key"))
                    action_index = int(event.get("index", -1))
                    key = str(event.get("key", ""))
                    is_mouse = action_name.startswith("mouse_")
                    button = str(event.get("button", "left"))
                    held_buttons = sorted(value for kind, value in held if kind == "mouse")
                    if is_mouse and phase == "move" and held_buttons:
                        phase = "drag"
                        button = button if button in held_buttons else held_buttons[0]
                    target = started + warmup + t_ms / 1000.0
                    remaining = target - time.monotonic()
                    if remaining > 0:
                        time.sleep(remaining)
                    focus, focus_age = _read_input_focus(out / "input_focus.json") if require_focus else ({}, 0)
                    focus_recovery = None
                    if (require_focus and recover_focus and phase != 'up'
                            and not _usable_gameview_focus(focus, focus_age)
                            and (deadline is None or time.monotonic() < deadline)):
                        focus, focus_age, focus_recovery = _recover_gameview_focus(
                            process_id, out / 'input_focus.json', deadline)
                    send_start = time.monotonic()
                    focus_ok = (not require_focus or
                                (_usable_gameview_focus(focus, focus_age)
                                 and (focus_recovery is None or focus_recovery['verified'])))
                    if deadline is not None and send_start >= deadline:
                        ok, error = False, "input deadline exceeded"
                    elif not focus_ok and phase != "up":
                        ok, error = False, "GameView focus unavailable or stale; input withheld"
                    else:
                        if is_mouse:
                            ok, error = _mouse_event(process_id, event["x"], event["y"], button, phase, screen_rect=focus.get("screen_rect"))
                        else:
                            ok, error = _key_event(process_id, key, phase)
                    completed = time.monotonic()
                    os_foreground = None
                    if os.sys.platform == "darwin":
                        try:
                            os_foreground = _frontmost_process()
                        except (ImportError, AttributeError) as exc:
                            os_foreground = {"error": str(exc)}
                    seq += 1
                    if not ok:
                        warnings.append(f"mouse event failed: {error}" if is_mouse else f"key event failed: {error}")
                    row: dict[str, Any] = {
                        **action_metadata(event),
                        "seq": seq,
                        "t_monotonic_ms": int((time.monotonic() - started) * 1000),
                        "t_ms": int((time.monotonic() - started) * 1000),
                        "planned_t_ms": round((warmup + t_ms / 1000) * 1000, 3),
                        "action_planned_t_ms": event.get('planned_t_ms'),
                        "send_start_t_ms": round((send_start - started) * 1000, 3),
                        "completed_t_ms": round((completed - started) * 1000, 3),
                        "scheduling_delay_ms": round(max(0, send_start - target) * 1000, 3),
                        "index": action_index,
                        "target_pid": process_id,
                        "target_window": "GameView" if require_focus else "UNVERIFIED",
                        "focus_observation": focus or None,
                        "os_foreground_after_dispatch": os_foreground,
                        "focus_recovery": focus_recovery,
                        "phase": phase,
                        "key": key or None,
                        "action": action_name,
                        "button": button if is_mouse else None,
                        "x": event.get("x") if is_mouse else None,
                        "y": event.get("y") if is_mouse else None,
                        "sent": bool(ok),
                    }
                    if phase != "up":
                        # an input attempt row carries the verb it executes
                        # and its plan index; releases stay channel evidence
                        row["action"] = action_name
                        row["index"] = action_index
                    if not ok:
                        row["error"] = str(error)[:200]
                    handle.write(json.dumps(row) + "\n")
                    handle.flush()
                    verdict = deliveries.setdefault(
                        action_index, {**action_metadata(event), "action": action_name, "index": action_index,
                                       "sent": True, "events": 0, "errors": []})
                    verdict["events"] += 1
                    if not ok:
                        verdict["sent"] = False
                        verdict["errors"].append(str(error)[:200])
                    if is_mouse and ok:
                        last_mouse = (float(event["x"]), float(event["y"]))
                    if phase == "down" and ok:
                        held.add(("mouse" if is_mouse else "key", event.get("button", "left") if is_mouse else key))
                    elif phase == "up" and ok:
                        held.discard(("mouse" if is_mouse else "key", event.get("button", "left") if is_mouse else key))
            finally:
                # Never leave a key pressed in the Editor session.
                for kind, value in sorted(held):
                    if kind == "mouse":
                        ok, error = _mouse_event(process_id, *last_mouse, value, "up")
                    else:
                        ok, error = _key_event(process_id, value, "up")
                    if not ok:
                        warnings.append(f"{kind} event failed: cleanup {value} up: {error}")
                    handle.write(json.dumps({"phase": "up", "key": value if kind == "key" else None,
                        "button": value if kind == "mouse" else None, "action": "mouse_up" if kind == "mouse" else "key", "sent": bool(ok),
                        "t_ms": round((time.monotonic() - started) * 1000, 3),
                        "x": last_mouse[0] if kind == "mouse" else None,
                        "y": last_mouse[1] if kind == "mouse" else None,
                        "cleanup_release": True, "error": error or None}) + "\n")
                handle.flush()
        return warnings, [deliveries[index] for index in sorted(deliveries)]

    @staticmethod
    def _combine_action_traces(out: Path) -> None:
        """Keep the editor and host writers isolated, then merge immutable rows."""
        host = out / "host_input_actions.jsonl"
        native = out / "actions.jsonl"
        project = out / "project_actions.jsonl"
        if native.is_file():
            native.replace(project)
        combined: list[tuple[float, int, dict[str, Any]]] = []
        for priority, path, source in ((0, host, "host_input"), (1, project, "project_recorder")):
            if not path.is_file():
                continue
            for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid {source} action trace at line {line_no}: {exc}") from exc
                if not isinstance(row, dict):
                    raise ValueError(f"invalid {source} action trace row at line {line_no}: expected object")
                row = {**row, "trace_source": source}
                timestamp = row.get("t_ms", row.get("t", row.get("t_monotonic_ms", 0)))
                try:
                    timestamp = float(timestamp)
                except (TypeError, ValueError):
                    timestamp = 0.0
                combined.append((timestamp, priority, row))
        combined.sort(key=lambda item: (item[0], item[1]))
        with native.open("w", encoding="utf-8") as handle:
            for _, _, row in combined:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    @staticmethod
    def _align_to_take_start(marker: Path) -> float:
        """The monotonic clock anchored at the Editor's take start.

        The Editor recorder stamps its state/event rows from its own take
        clock; anchoring the host's monotonic clock to the marker file's
        write time minus the explicitly reported recorder elapsed time puts
        actions.jsonl on the recorder session timeline. This retains the
        first-frame readiness delay instead of treating marker time as take
        start. The cross-process alignment is approximate and independent
        screenshot/state completion times remain intact.
        """
        try:
            started_wall = marker.stat().st_mtime
            offset = time.time() - started_wall
            data = json.loads(marker.read_text(encoding="utf-8"))
            elapsed = max(0, float(data.get("recorder_elapsed_ms", 0))) / 1000
            return time.monotonic() - offset - elapsed
        except (OSError, ValueError, TypeError):
            return time.monotonic()

    @staticmethod
    def _summarize_delivered_actions(out: Path) -> tuple[list[dict[str, Any]], int]:
        """Actual deliveries from the actions.jsonl the take really wrote.

        ``executed_actions`` summarizes what was actually delivered during
        the take (harness verdicts or the project harness's own rows) —
        never a copy of the requested plan.
        """
        path = out / "actions.jsonl"
        if not path.is_file():
            return [], 0
        rows: list[dict[str, Any]] = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
        except OSError:
            return [], 0
        by_action: dict[Any, dict[str, Any]] = {}
        for row in rows:
            name = row.get("action") or row.get("verb") or ""
            if not name:
                continue
            index = row.get("index", name)
            verdict = by_action.setdefault(index, {
                "action": name, "sent": True, "ok": True, "events": 0, "errors": []})
            verdict["events"] += 1
            if row.get("sent") is False or (row.get("error") and row.get("sent") is None):
                verdict["sent"] = False
                verdict["ok"] = False
                verdict["errors"].append(str(row.get("error"))[:200])
        return [by_action[key] for key in sorted(by_action, key=repr)], len(rows)

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _fail(message: str | list[str], payload: dict[str, Any] | None = None):
        errors = [str(item) for item in (message if isinstance(message, list) else [message])]
        return UnityOperationResult.failure(
            _OPERATION,
            *errors,
            payload=payload,
        ).to_dict()


def _process_snapshot() -> dict[int, dict]:
    if os.name == "nt":
        return {}
    result = subprocess.run(["ps", "-axo", "pid=,pgid=,command="],
                            capture_output=True, text=True, check=True, timeout=10)
    rows = {}
    for line in result.stdout.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            rows[int(parts[0])] = {"pid": int(parts[0]), "pgid": int(parts[1]), "command": parts[2]}
    return rows


def _detached_project_groups(project: Path, baseline: dict) -> list[dict]:
    import re
    path = str(Path(project).resolve())
    # ps prints argv without quotes; match the known path plus argument boundary.
    binding = re.compile(r"(?:^| )-projectPath " + re.escape(path) + r"(?= -|$)")
    return [row for pid, row in _process_snapshot().items()
            if pid not in baseline and row["pgid"] == pid
            and row["command"].startswith("/Applications/Unity Hub.app/Contents/MacOS/Unity Hub ")
            and binding.search(row["command"])]


def _group_live(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False


def _stop_owned_group(pgid: int, *, expected: dict | None = None):
    for sig in (signal.SIGTERM, signal.SIGKILL):
        if not _group_live(pgid):
            return
        if expected is not None:
            current = _process_snapshot().get(expected["pid"])
            if current != expected:
                raise RuntimeError(f"owned detached group {pgid} identity changed before signal; cleanup refused")
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            return
        end = time.monotonic() + 5
        while _group_live(pgid) and time.monotonic() < end:
            time.sleep(.1)
    if _group_live(pgid):
        raise RuntimeError(f"owned detached process group {pgid} did not exit")


def _read_input_focus(path: Path) -> tuple[dict[str, Any], float]:
    """Read content and timestamp from one focus snapshot, then sample host time.

    Sampling time before stat races a concurrent Editor write and can produce
    a negative age for a perfectly fresh snapshot. An open descriptor keeps
    content/mtime paired across the recorder's atomic file replacements.
    """
    try:
        with path.open(encoding="utf-8") as stream:
            focus = json.load(stream)
            modified = os.fstat(stream.fileno()).st_mtime
        age_ms = (time.time() - modified) * 1000
        return (focus, age_ms) if isinstance(focus, dict) else ({}, float("inf"))
    except (OSError, ValueError):
        return {}, float("inf")


def _osascript(script: str) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"{type(exc).__name__}: {exc}"
    if result.returncode != 0:
        return False, (result.stderr or result.stdout or "osascript failed").strip()
    return True, result.stdout.strip()


def _usable_gameview_focus(focus: dict, age_ms: float) -> bool:
    return (focus.get("focused") is True and focus.get("target_window") == "GameView"
            and 0 <= age_ms <= 2000)


def _recover_gameview_focus(process_id: int, path: Path, deadline: float | None):
    """Bounded OS reactivation, followed by a fresh Editor attestation.

    No click or gameplay input is used to acquire focus. Recovery latency is
    real elapsed recording time and must never shift the scenario/deadline.
    """
    start = time.monotonic()
    stop = min(start + .75, deadline) if deadline is not None else start + .75
    ok, error = _focus_process(process_id)
    focus, age = _read_input_focus(path)
    while ok and not _usable_gameview_focus(focus, age) and time.monotonic() < stop:
        time.sleep(min(.05, max(0, stop - time.monotonic())))
        focus, age = _read_input_focus(path)
    return focus, age, {"attempted": True, "process_active": ok,
                        "verified": ok and _usable_gameview_focus(focus, age),
                        "elapsed_ms": round((time.monotonic() - start) * 1000, 3),
                        "error": error or None}


def _native_frontmost_pid() -> int:
    """Query the WindowServer process directly, without AppKit's cached app."""
    import ctypes
    class ProcessSerialNumber(ctypes.Structure):
        _fields_ = [("high", ctypes.c_uint32), ("low", ctypes.c_uint32)]
    services = ctypes.CDLL(
        "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
    services.GetFrontProcess.argtypes = [ctypes.POINTER(ProcessSerialNumber)]
    services.GetFrontProcess.restype = ctypes.c_int32
    services.GetProcessPID.argtypes = [ctypes.POINTER(ProcessSerialNumber), ctypes.POINTER(ctypes.c_int32)]
    services.GetProcessPID.restype = ctypes.c_int32
    serial = ProcessSerialNumber()
    pid = ctypes.c_int32()
    if services.GetFrontProcess(ctypes.byref(serial)) != 0:
        raise OSError("GetFrontProcess failed")
    if services.GetProcessPID(ctypes.byref(serial), ctypes.byref(pid)) != 0 or pid.value <= 0:
        raise OSError("GetProcessPID failed")
    return pid.value


def _frontmost_process() -> dict[str, Any]:
    """Read the current foreground PID even on a Python monitor thread.

    Pumping that thread's runloop alone can leave NSWorkspace stale when the
    main Cocoa thread is not pumping notifications. Never use its cached PID
    as an input authorization. System Events is a bounded fallback.
    """
    source = "GetFrontProcess/GetProcessPID"
    try:
        pid = _native_frontmost_pid()
    except (ImportError, OSError, AttributeError):
        ok, output = _osascript('tell application "System Events" to get unix id of first application process whose frontmost is true')
        if not ok or not output.strip().isdigit() or int(output.strip()) <= 0:
            return {"pid": None, "name": None, "source": "unavailable",
                    "error": output, "observed_unix": time.time()}
        pid = int(output.strip())
        source = "System Events foreground PID"
    name = None
    try:
        import AppKit
        app = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        if app is not None:
            name = str(app.localizedName())
    except (ImportError, AttributeError):
        pass
    return {"pid": pid, "name": name, "source": source,
            "observed_unix": time.time()}


def _focus_process(process_id: int) -> tuple[bool, str]:
    if os.environ.get("GAMEFACTORY_UNITY_CAPTURE_POLICY") in {"background_inputsystem_v1", "graphics_batch_render_v2"}:
        raise RuntimeError("background policy forbids OS focus activation")
    """Activate and verify the dedicated process using a fresh OS observation."""
    try:
        import AppKit
        if _frontmost_process()["pid"] == int(process_id):
            return True, ""
        app = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(int(process_id))
        if app is not None:
            app.activateWithOptions_(AppKit.NSApplicationActivateIgnoringOtherApps)
            end = time.monotonic() + .25
            while time.monotonic() < end:
                if _frontmost_process()["pid"] == int(process_id):
                    return True, ""
                time.sleep(.01)
    except (ImportError, AttributeError):
        pass
    script = ('tell application "System Events"\n'
              'set targetProcess to first application process whose unix id is ' + str(int(process_id)) + '\n'
              'set frontmost of targetProcess to true\n'
              'return unix id of first application process whose frontmost is true\nend tell')
    ok, output = _osascript(script)
    if not ok:
        return False, output
    return ((True, "") if output.strip() == str(int(process_id))
            else (False, "target process did not become frontmost; observed PID " + output.strip()))


def _key_event(process_id: int, key: str, phase: str) -> tuple[bool, str]:
    """Post a physical key edge only to the acknowledged foreground Editor."""
    focused, error = _focus_process(process_id)
    if not focused:
        return False, error
    from engine_adapters.macos_input import post_key_edge
    return post_key_edge(process_id, key, phase)


def _mouse_event(process_id: int, x: float, y: float, button: str, phase: str, *, screen_rect=None) -> tuple[bool, str]:
    """Post one normalized-coordinate mouse event to the target process."""
    focused, error = _focus_process(process_id)
    if not focused:
        return False, error
    from engine_adapters.macos_input import post_mouse_edge
    return post_mouse_edge(process_id, x, y, button, phase, screen_rect=screen_rect, foreground=True)


def _log_tail(project_dir: str, limit: int = 2000) -> str:
    if not project_dir:
        return ""
    log = Path(project_dir) / "Library" / "GameFactory3A" / "Editor.log"
    if not log.is_file():
        return ""
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text[-limit:]


def _editor_failure_context(marker: Path, payload: dict, exit_code: int | None) -> str:
    """Keep the recorder's actual error plus numbered log context, not allocator noise."""
    import hashlib
    import re
    log_path = Path(payload.get("project_dir", "")) / "Library/GameFactory3A/Editor.log"
    try:
        raw = log_path.read_bytes()
    except OSError:
        raw = b""
    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    pattern = re.compile(r"error CS\d+|Exception:|\[GameFactory3APlayTest\]|failed compilation|invalid dependencies|license.*(?:failed|error)|(?:failed|error).*licens", re.I)
    hits = [i for i, line in enumerate(lines) if pattern.search(line)]
    # Earliest errors and the latest take lifecycle both survive long shutdown logs.
    selected = sorted(set(hits[:8] + hits[-8:]))
    keep = sorted({j for i in selected for j in range(max(0, i-2), min(len(lines), i+9))})
    context = "\n".join(f"{i+1}: {lines[i]}" for i in keep)
    report_path = marker.parent / "_editor_report.json"
    try:
        report = json.loads(report_path.read_text(encoding="utf-8-sig"))
        if not isinstance(report, dict): report = {}
    except (OSError, ValueError):
        report = {}
    diagnostic = {"schema": "unity-editor-failure-context.v1", "log": str(log_path),
                  "log_sha256": hashlib.sha256(raw).hexdigest(), "log_lines": len(lines),
                  "exit_code": exit_code, "editor_report": report,
                  "critical_context": context, "tail": text[-2000:]}
    payload["editor_failure"] = diagnostic
    (marker.parent / "editor_failure.json").write_text(json.dumps(diagnostic, indent=2)+"\n")
    errors = report.get("errors", [])
    harness = [e for e in errors if isinstance(e, str) and e.startswith("HARNESS_ERROR:")]
    if harness:
        return "; ".join(harness) + "; see editor_failure.json (full Editor.log preserved)"
    relevant = context or text[-2000:]
    return (_classify_editor_exit(relevant, exit_code) if exit_code is not None
            else _classify_timeout(relevant, payload.get("os_focus")))


def _license_failure(log: str) -> bool:
    import re
    return any(re.search(r"licens(?:e|ing|ingclient|eclient)", line) and
               re.search(r"fail(?:ed|ure)?|error|timed out|unavailable|no valid|not activated", line)
               for line in log.splitlines())


def _classify_editor_exit(log_tail: str, exit_code: int | None) -> str:
    """Classify Unity Editor early exit as product error, environment error, or harness error."""
    import re
    if has_injected_compilation_error(log_tail):
        return (
            "HARNESS_ERROR: injected Unity evaluation driver/recorder failed compilation; "
            "see editor_log_tail; this is not a product compilation verdict"
        )
    log = log_tail.lower()

    # Product compilation errors
    if re.search(r"error cs\d+", log) or "script compilation error" in log:
        return (
            "PRODUCT_ERROR: Unity Editor exited due to C# compilation errors in the product code; "
            "see editor_log_tail for the error details"
        )

    # Product package/dependency issues
    if "invalid dependencies" in log or "package.*cannot be found" in log:
        return (
            "PRODUCT_ERROR: Unity Editor exited due to missing or invalid package dependencies; "
            "see editor_log_tail (check Packages/manifest.json)"
        )

    # Product YAML/asset corruption
    if "yaml error" in log and "projectsettings" in log:
        return (
            "PRODUCT_ERROR: Unity Editor exited due to corrupt ProjectSettings; "
            "see editor_log_tail"
        )

    # Environment/licensing issues
    if exit_code == 199 or _license_failure(log):
        return (
            "ENVIRONMENT_ERROR: Unity Editor exited due to licensing issues; "
            "see editor_log_tail (activate Unity Hub or keep a licensed Editor open)"
        )

    # Environment certificate issues
    if "cert verify failed" in log or "certificate could not be verified" in log:
        return (
            "ENVIRONMENT_ERROR: Unity Editor encountered certificate validation errors; "
            "see editor_log_tail (network/TLS configuration issue)"
        )

    # Generic early exit
    return (
        "Unity Editor exited before entering Play Mode; "
        "see editor_log_tail (compilation errors or a startup dialog are the usual causes)"
    )


def _classify_timeout(log_tail: str, os_focus: dict | None) -> str:
    """Classify readiness timeout as product issue, environment issue, or harness issue."""
    import re
    if has_injected_compilation_error(log_tail):
        return (
            "HARNESS_ERROR: injected Unity evaluation driver/recorder failed compilation; "
            "see editor_log_tail; this is not a product compilation verdict"
        )
    log = log_tail.lower()

    # Product issues that block startup
    if re.search(r"error cs\d+", log) or "script compilation error" in log:
        return (
            "PRODUCT_ERROR: Unity Editor did not enter Play Mode due to compilation errors; "
            "see editor_log_tail"
        )

    if "invalid dependencies" in log or "package.*cannot be found" in log:
        return (
            "PRODUCT_ERROR: Unity Editor did not enter Play Mode due to package dependency issues; "
            "see editor_log_tail"
        )

    # Environment issues
    if _license_failure(log):
        return (
            "ENVIRONMENT_ERROR: Unity Editor did not enter Play Mode due to licensing issues; "
            "see editor_log_tail"
        )

    # Harness timeout with no clear product cause
    return (
        f"HARNESS_ERROR: Unity Editor did not become render/input ready within timeout; "
        f"foreground={os_focus}; see editor_log_tail for diagnostic information"
    )
