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
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from .._internal.transport import UnityEditorTransport
from ..config import UnityClientConfig
from ..contracts import UnityOperationResult

_OPERATION = "playtest.record"
_REPORT_SCHEMA = "gamefactory3a.unity3d.playtest_report.v1"
_RECORDER_METHOD = "GameFactory3APlayTestRecorder.Enter"

#: Allowlisted player-level action names (record.md contract), matching the
#: Godot adapter's allowlist so scenarios stay portable across engines.
ALLOWED_ACTIONS = frozenset({
    "move", "look", "jump", "attack", "interact",
    "dash", "pause", "restart", "wait",
})

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
            timeout: Maximum seconds for the whole take after Play Mode.
            ffmpeg: Optional ffmpeg binary for encoding ``video.mp4``.
            dry_run: Validate and print the plan without running.
        """
        project = self._config.project_path
        if project is None or not (project / "Assets").is_dir():
            return self._fail("project_path must resolve to a Unity project")
        if duration <= 0 or fps <= 0:
            return self._fail("duration and fps must be positive")

        resolved_scene, scene_error = self._resolve_scene(scene)
        if scene_error:
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
            "actions": actions,
            "events": [
                {"t_ms": event[0], "phase": event[1], "key": event[2]}
                for event in events
            ],
            "unity_binary": str(unity_binary),
            "ffmpeg": str(encoder) if encoder else None,
            "input_transport": "macos_system_events",
        }
        if dry_run:
            return UnityOperationResult.success(
                _OPERATION,
                payload=payload,
            ).to_dict()

        input_error = self._check_input_driver()
        if input_error:
            return self._fail(input_error, payload)

        out.mkdir(parents=True, exist_ok=True)
        # A take directory is single-use evidence: when the caller reuses one,
        # stale frames and reports from the previous take must not mix into
        # the new video. Fresh timestamped directories (the CLI default) are
        # untouched by this.
        stale_frames = out / "frames"
        if stale_frames.is_dir():
            shutil.rmtree(stale_frames)
        for stale_name in (
            "report.json", "video.mp4", "actions.jsonl", "diagnostics.jsonl",
            "play_started.json", "_editor_report.json", "_scenario.json",
        ):
            (out / stale_name).unlink(missing_ok=True)
        (out / "_scenario.json").write_text(
            json.dumps(
                {"actions": actions, "fps": fps, "duration": duration},
                indent=2,
            ),
            encoding="utf-8",
        )

        process = transport.launch_editor(
            scene_path=str(resolved_scene),
            extra_args=[
                "-executeMethod", _RECORDER_METHOD,
                "--a3-playtest-output", str(out),
                "--a3-playtest-scene", str(resolved_scene),
                "--a3-playtest-fps", str(int(fps)),
                "--a3-playtest-duration", str(float(duration)),
                "--a3-playtest-warmup", str(float(warmup)),
            ],
        )
        payload["process_id"] = process.pid

        marker = out / "play_started.json"
        if not self._wait_for_marker(marker, process, payload, _EDITOR_BOOT_TIMEOUT):
            self._stop_process(process)
            return self._fail(
                payload.get("error") or "Unity Editor did not enter Play Mode",
                payload,
            )

        started = time.monotonic()
        payload["play_started_at"] = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
        )
        warnings = self._drive_events(process.pid, events, started, out, warmup)

        if not self._wait_for_exit(process, started + duration + _EDITOR_SHUTDOWN_TIMEOUT):
            warnings.append("Editor did not exit on time; terminating")
            self._stop_process(process)

        editor_report = self._read_editor_report(out, payload)
        frames = sorted((out / "frames").glob("f*.png")) if (out / "frames").is_dir() else []
        video_path = self._encode_video(out, frames, fps, encoder)
        report = {
            "schema_version": _REPORT_SCHEMA,
            "engine": "unity3d",
            "status": "passed" if frames else "failed",
            "url": str(project),
            "output_dir": str(out),
            "scene": str(resolved_scene),
            "fps": fps,
            "requested_seconds": duration,
            # The Editor throttles play mode when idle; the real wall time of
            # the last capture is the honest length, not frames/fps.
            "recorded_seconds": (
                (editor_report or {}).get("recorded_seconds")
                or (len(frames) / fps if fps > 0 else 0)
            ),
            "viewport": (editor_report or {}).get("viewport") or [],
            "warmup": warmup,
            "action_count": len(actions),
            "executed_actions": [item["action"] for item in actions],
            "frames": len(frames),
            "video": str(video_path) if video_path else None,
            "game_state": None,
            "warnings": warnings,
            "errors": [],
            "editor_report": editor_report,
        }
        report_path = out / "report.json"
        report_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        payload["report"] = report

        if not frames:
            return self._fail(
                (editor_report or {}).get("errors") or ["no frames were captured"],
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
        if not actions:
            return None, "action plan must not be empty"
        return actions, None

    @staticmethod
    def _timeline(actions: list[dict[str, Any]]) -> list[tuple[int, str, str]]:
        """Expand actions into ``(t_ms, phase, key)`` key events."""
        events: list[tuple[int, str, str]] = []
        t_ms = 0
        for action in actions:
            name = str(action.get("action", ""))
            duration_ms = int(action.get("duration_ms", 100))
            if name == "wait":
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
                    events.append((t_ms, "down", key))
                for key in keys:
                    events.append((t_ms + max(duration_ms, 100), "up", key))
                t_ms += max(duration_ms, 100)
                continue
            if name == "look":
                yaw = int(action.get("yaw_delta", 0) or 0)
                pitch = int(action.get("pitch_delta", 0) or 0)
                if yaw:
                    events.append((t_ms, "tap", _LOOK_KEYS["+yaw" if yaw > 0 else "-yaw"]))
                if pitch:
                    events.append((t_ms, "tap", _LOOK_KEYS["+pitch" if pitch > 0 else "-pitch"]))
                t_ms += max(duration_ms, 100)
                continue
            key = str(DEFAULT_KEY_BINDINGS.get(name, ""))
            if key:
                events.append((t_ms, "tap", key))
            t_ms += max(duration_ms, 100)
        events.sort(key=lambda item: item[0])
        return events

    # ── Editor lifecycle ───────────────────────────────────────────────────

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
    ) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if marker.is_file():
                return True
            if process.poll() is not None:
                payload["editor_exit_code"] = process.returncode
                payload["editor_log_tail"] = _log_tail(payload.get("project_dir", ""))
                payload["error"] = (
                    "Unity Editor exited before entering Play Mode; "
                    "see editor_log_tail (compilation errors or a startup "
                    "dialog are the usual causes)"
                )
                return False
            time.sleep(0.5)
        payload["error"] = (
            f"Unity Editor did not enter Play Mode within {timeout:.0f}s"
        )
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
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()

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
        events: list[tuple[int, str, str]],
        started: float,
        out: Path,
        warmup: float,
    ) -> list[str]:
        """Post key events on schedule; return non-fatal warnings."""
        warnings: list[str] = []
        actions_path = out / "actions.jsonl"
        held: set[str] = set()
        seq = 0
        with actions_path.open("w", encoding="utf-8") as handle:
            try:
                for t_ms, phase, key in events:
                    target = started + warmup + t_ms / 1000.0
                    remaining = target - time.monotonic()
                    if remaining > 0:
                        time.sleep(remaining)
                    ok, error = _key_event(process_id, key, phase)
                    seq += 1
                    if not ok:
                        warnings.append(f"key event failed: {error}")
                    handle.write(json.dumps({
                        "seq": seq,
                        "t_monotonic_ms": int((time.monotonic() - started) * 1000),
                        "phase": phase,
                        "key": key,
                    }) + "\n")
                    if phase == "down":
                        held.add(key)
                    elif phase == "up":
                        held.discard(key)
            finally:
                # Never leave a key pressed in the Editor session.
                for key in sorted(held):
                    _key_event(process_id, key, "up")
        return warnings

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _fail(message: str | list[str], payload: dict[str, Any] | None = None):
        errors = [str(item) for item in (message if isinstance(message, list) else [message])]
        return UnityOperationResult.failure(
            _OPERATION,
            *errors,
            payload=payload,
        ).to_dict()


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


def _key_event(process_id: int, key: str, phase: str) -> tuple[bool, str]:
    """Post one real keyboard event to the Editor process via System Events."""
    lines = ['tell application "System Events"']
    lines.append(
        "set frontmost of (first application process whose unix id is "
        f"{int(process_id)}) to true"
    )
    if key in _KEY_CODES:
        # Synthetic key codes post a full press; System Events has no
        # separate down/up for non-character keys, so held directions use
        # letters only and every non-letter verb is edge-triggered.
        lines.append(f"key code {int(_KEY_CODES[key])}")
    elif phase == "down":
        lines.append(f'key down "{key}"')
    elif phase == "up":
        lines.append(f'key up "{key}"')
    else:
        lines.append(f'keystroke "{key}"')
    lines.append("end tell")
    return _osascript("\n".join(lines))


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
