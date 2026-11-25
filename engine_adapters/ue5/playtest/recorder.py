"""In-editor PIE playtest recorder for the UE5 adapter.

This script runs inside the Editor's embedded Python interpreter via
``-ExecutePythonScript`` (the Python Editor Script Plugin must be enabled in
the target project). It loads the play map, starts Play-In-Editor, captures
Game-view frames with the ``HighResShot`` console command at the requested
frame rate, writes the editor-side report, ends PIE, and quits the Editor.

The host client (``engine_adapters/ue5/playtest/client.py``) owns the
scenario timeline: it polls the ``play_started.json`` marker this script
writes and posts real keyboard events while PIE runs.

Only ``unreal`` and the standard library are used. Unreal Editor APIs move
between engine versions, so every call is resolved defensively and every
failure is recorded in the report instead of raising.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import unreal

_OPERATION = "playtest.record"


def _argv_map(argv: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    index = 0
    while index + 1 < len(argv):
        key = str(argv[index])
        if key.startswith("--"):
            result[key[2:]] = str(argv[index + 1])
        index += 2
    return result


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path), "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


class PendingScreenshot:
    """One request in flight; only durable, stable image files become evidence."""
    def __init__(self, output, fps):
        self.output = Path(output)
        self.fps = fps
        self.pending = None
        self.frames = 0
        self.errors = []
        self.intervals_ms = []
        self.last_ms = None
        self.capture_total_ms = 0.0

    def request(self, path, timestamp_ms, now):
        if self.pending is not None:
            raise RuntimeError("screenshot already pending")
        self.pending = {"path": Path(path), "timestamp_ms": timestamp_ms,
                        "requested": now, "size": -1, "changed": now}

    def poll(self, now):
        pending = self.pending
        if pending is None:
            return
        path = pending["path"]
        size = path.stat().st_size if path.is_file() else -1
        if size != pending["size"]:
            pending.update(size=size, changed=now)
        if size > 32 and now - pending["changed"] >= 0.1:
            # HighResShot writes PNG asynchronously. Require its header and
            # complete IEND trailer before publishing the index row.
            data = path.read_bytes()
            if data[:8] != b"\x89PNG\r\n\x1a\n" or data[-8:] != b"IEND\xaeB`\x82":
                if now-pending["requested"] >= 5:
                    self.errors.append("screenshot output is not a complete PNG")
                    self.pending = None
                return
            stamp = pending["timestamp_ms"]
            rel = path.relative_to(self.output).as_posix()
            row = {"frame_id": f"FRAME:{self.frames+1:05d}", "timestamp_ms": stamp,
                   "t_ms": stamp, "capture_end_t_ms": stamp + round((now-pending["requested"])*1000),
                   "path": rel, "raw_path": rel, "source_path": rel,
                   "delivered_path": None, "delivery_status": "pending_manifest",
                   "capture_status": "captured", "engine": "ue5", "window": "PIE",
                   "viewport": "game_view", "clock": "recorder_session_monotonic",
                   "timing": "request_to_file_completion; pixel time within this interval",
                   "video_t_ms": round(self.frames*1000/self.fps)}
            with (self.output / "frame_index.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row) + "\n")
                handle.flush()
            if self.last_ms is not None:
                self.intervals_ms.append(stamp-self.last_ms)
            self.last_ms = stamp
            self.frames += 1
            self.capture_total_ms += (now-pending["requested"])*1000
            self.pending = None
        elif now-pending["requested"] >= 5:
            self.errors.append("screenshot request produced no complete PNG within capture flush deadline")
            self.pending = None


def _level_editor():
    for factory in (
        lambda: unreal.get_editor_subsystem(unreal.LevelEditorSubsystem),
        lambda: unreal.LevelEditorSubsystem(),
        lambda: unreal.EditorLevelLibrary,
    ):
        try:
            candidate = factory()
            if candidate is not None:
                return candidate
        except Exception:  # noqa: BLE001 - probe defensively per engine version
            continue
    return None


def _game_world():
    editor = _level_editor()
    for name in ("get_game_world", "get_editor_world"):
        getter = getattr(editor, name, None)
        if getter is None:
            continue
        try:
            world = getter()
            if world is not None:
                return world
        except Exception:  # noqa: BLE001
            continue
    return None


def _console(world, command: str) -> None:
    unreal.SystemLibrary.execute_console_command(world, command, None)


def main() -> int:
    args = _argv_map(list(sys.argv[1:]))
    output = Path(args.get("a3-playtest-output", "")).expanduser()
    if not str(output):
        print("RECORDER_ERROR: --a3-playtest-output is required")
        return 2
    fps = max(int(float(args.get("a3-playtest-fps", "20"))), 1)
    duration = max(float(args.get("a3-playtest-duration", "12")), 0.1)
    warmup = max(float(args.get("a3-playtest-warmup", "0")), 0.0)
    map_path = args.get("a3-playtest-map", "")

    report: dict = {
        "schema_version": "gamefactory3a.ue5.playtest_editor_report.v1",
        "ok": False,
        "map": map_path,
        "fps": fps,
        "duration": duration,
        "frames": 0,
        "state_snapshots": 0,
        "warnings": [],
        "errors": [],
    }
    frames_dir = output / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    state = {"started": False, "start": 0.0, "last": 0.0, "frame": 0}
    state["audio_stopping"] = None
    state["audio_size"] = -1
    state["audio_changed"] = 0.0
    captures = PendingScreenshot(output, fps)
    state["next_slot"] = 0
    report["skipped_sample_slots"] = 0
    started_at = time.monotonic()
    boot_timeout = max(float(args.get("a3-playtest-start-timeout", "300")), 30.0)

    if map_path:
        try:
            unreal.EditorLoadingAndSavingUtils.load_map(map_path)
        except Exception as exc:  # noqa: BLE001
            report["errors"].append(f"load_map failed: {exc}")
            _write_json(output / "_editor_report.json", report)
            unreal.SystemLibrary.quit_editor()
            return 3

    editor = _level_editor()
    if editor is None or not hasattr(editor, "editor_play_simulation"):
        report["errors"].append(
            "no editor API to start PIE; enable the Python Editor Script Plugin"
        )
        _write_json(output / "_editor_report.json", report)
        unreal.SystemLibrary.quit_editor()
        return 3
    editor.editor_play_simulation()

    def tick(_delta: float) -> None:
        world = _game_world()
        if world is None:
            if not state["started"] and time.monotonic() - started_at > boot_timeout:
                report["errors"].append("PIE did not start in time")
                _write_json(output / "_editor_report.json", report)
                unreal.SystemLibrary.quit_editor()
                return
            return
        now = time.monotonic()
        if not state["started"]:
            state["started"] = True
            state["start"] = now
            state["last"] = now
            try:
                unreal.AudioMixerBlueprintLibrary.start_recording_output(world, warmup + duration + 1, None)
                state["audio_started"] = True
                _write_json(output / "audio_capture.json", {"status": "recording", "source": "game_output"})
            except Exception:
                state["audio_started"] = False
                _write_json(output / "audio_capture.json", {"status": "unavailable", "source": "game_output",
                                                          "error": "master_submix_recording_unavailable"})
            _write_json(output / "play_started.json", {
                "play_started_wall": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "editor_pid": os.getpid(),
            })
        elapsed = now - state["start"]
        captures.poll(now)
        report["frames"] = captures.frames
        if elapsed >= warmup + duration:
            # No new requests after the gameplay deadline. A single pending
            # screenshot may finish inside its own bounded flush deadline.
            if captures.pending is not None:
                return
            if state.get("audio_started"):
                if state["audio_stopping"] is None:
                    state["audio_stopping"] = now
                    state["audio_changed"] = now
                    try:
                        unreal.AudioMixerBlueprintLibrary.stop_recording_output(
                            world, unreal.AudioRecordingExportType.WAV_FILE, "audio", str(output) + "/", None, None)
                    except Exception:
                        state["audio_started"] = False
                        _write_json(output / "audio_capture.json", {"status": "capture_failed", "source": "game_output",
                                                                  "error": "wav_export_failed"})
                    return
                audio_path = output / "audio.wav"
                size = audio_path.stat().st_size if audio_path.is_file() else -1
                if size != state["audio_size"]:
                    state["audio_size"] = size
                    state["audio_changed"] = now
                stable = size > 44 and now - state["audio_changed"] >= 0.5
                if not stable and now - state["audio_stopping"] < 10:
                    return
                _write_json(output / "audio_capture.json", {
                    "status": "captured" if stable else "capture_failed", "source": "game_output",
                    "clock": "monotonic_session_ms", "start_t_ms": 0,
                    "synchronization_precision": "master submix buffer; not frame exact",
                    "error": None if stable else "wav_export_timeout_or_no_samples"})
            unreal.unregister_slate_post_tick_callback(handle)
            report["errors"].extend(captures.errors)
            report["ok"] = captures.frames >= 2 and not report["errors"]
            if captures.frames < 2:
                report["errors"].append("visual capture incomplete: fewer than two real frames")
            report.update(actual_runtime_seconds=min(elapsed, warmup+duration),
                          capture_finalize_seconds=max(0, elapsed-warmup-duration),
                          actual_fps=captures.frames/duration,
                          sampling_intervals_ms=captures.intervals_ms,
                          screenshot_total_ms=captures.capture_total_ms,
                          video_timing="fixed fps; frame_index maps request/completion interval to video position")
            _write_json(output / "execution.json", report)
            if not report["ok"]:
                _write_json(output / "harness_error.json", {"status": "HARNESS_ERROR", "phase": "capture", "errors": report["errors"]})
            _write_json(output / "_editor_report.json", report)
            try:
                stop = getattr(editor, "editor_request_end_play_map", None)
                if stop is not None:
                    stop()
            except Exception as exc:  # noqa: BLE001
                report["warnings"].append(f"end PIE failed: {exc}")
            unreal.SystemLibrary.quit_editor()
            return
        if elapsed < warmup:
            return
        slot = int((elapsed-warmup)*fps)
        if slot < state["next_slot"]:
            return
        if captures.pending is not None:
            report["skipped_sample_slots"] += slot-state["next_slot"]+1
            state["next_slot"] = slot+1
            return
        report["skipped_sample_slots"] += max(0, slot-state["next_slot"])
        state["next_slot"] = slot+1
        state["frame"] += 1
        path = frames_dir / f"f{state['frame']:05d}.png"
        try:
            captures.request(path, round(elapsed*1000), now)
            _console(world, f"HighResShot filename={path}")
        except Exception as exc:  # noqa: BLE001
            captures.pending = None
            captures.errors.append(f"capture failed: {exc}")

    handle = unreal.register_slate_post_tick_callback(tick)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
