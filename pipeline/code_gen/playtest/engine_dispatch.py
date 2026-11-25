"""
Cross-engine playtest + build dispatch for the benchmark layer (AGENTS.md §4).

The benchmark layer never re-implements engine work: launch, input
injection, frame capture, video encoding, in-engine state collection and
build/export pipelines all stay owned by the existing ``xxClient`` surface
(``playtest.record()`` / ``build.project()``). This module only

* resolves engine aliases (``unity`` / ``unity3d`` / ``ue5`` / ``unreal`` /
  ``three_js`` / ``threejs`` …) onto the canonical engine ids the adapters
  register (``godot``, ``unity3d``, ``ue5``, ``three_js``, ``blender``);
* constructs the right ``xxClient`` for a located project (actual class
  names from the adapters: ``GodotClient``, ``UnityClient``, ``UEClient``,
  ``ThreeClient``, ``BlenderClient`` — all take ``project_path`` first);
* exposes two uniform benchmark-side entry points::

      record_playtest(engine, project_path, output_dir, action_plan,
                      duration, fps, ...)
      record_build_trial(engine, evidence_dir, target_output_path, spec)

  ``record_playtest`` maps the common frozen parameters onto each engine's
  native ``playtest.record(...)`` signature. The shared action vocabulary
  (``wait`` / ``move`` / ``look`` / ``jump`` / ``attack`` / ``interact`` /
  ``dash`` / ``pause`` / ``restart``) is forwarded verbatim to the engines
  whose recorders accept verb plans (Godot, Unity, UE5). The three.js
  recorder takes a *plan file* carrying per-action ``event.code``
  keys/taps, so its frozen verb plan is converted through the contract's
  frozen ``input_bindings`` and written as a real plan file — the actions
  are executed as frozen, never dropped in favor of the game's free
  discovery, and verbs without a usable mapping are reported as
  ``unmapped_verbs`` instead of guessed. The Blender recorder discovers
  the game's own actions from the running game; the dispatch records that
  fact instead of re-implementing the adapter's input mapping.

  ``record_build_trial`` executes a frozen per-engine build spec (the case
  definition owns *which* build — e.g. GameG's Godot ``Web`` export preset)
  and appends one row per attempt to ``build_trace.jsonl``. The Godot
  executor runs the first attempt against a **clean copy** of the project
  (engine caches stripped) through the existing ``GodotBuildClient``
  (``client.build.project``) — the engine owns the build; the benchmark only
  stages, records and preserves the raw logs. ``attempt_index=1`` is what
  FIRST_ATTEMPT_BUILD_SUCCESS reads; later attempts are retry diagnostics
  and never overwrite the first result.

Honesty rules (the ``benchmark/evaluation`` contract):

* an engine that cannot start (missing binary, missing project, adapter
  exception) produces a ``ok=False`` envelope / trace row with the concrete
  error — never a fabricated PASS; the caller keeps the diagnostics and the
  dependent metrics honestly stay UNKNOWN;
* ``record_playtest`` / ``record_build_trial`` therefore convert
  construction / location / execution failures into failure records (with a
  ``failure_stage`` marker) instead of raising, so a report is always
  written;
* a successful build never implies the game is playable — the playtest
  evidence chain judges that separately.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[3]

# ── engine aliases ───────────────────────────────────────────────────────────

#: canonical engine id → the adapter package's client class.
ENGINE_ALIASES: dict[str, str] = {
    "godot": "godot",
    "unity": "unity3d",
    "unity3d": "unity3d",
    "ue5": "ue5",
    "unreal": "ue5",
    "unreal5": "ue5",
    "three_js": "three_js",
    "threejs": "three_js",
    "three": "three_js",
    "blender": "blender",
}

#: engines whose recorders accept the shared verb action plan as a list.
VERB_PLAN_ENGINES = frozenset({"godot", "unity3d", "ue5"})

#: engines whose recorders discover actions from the running game and take
#: a discovered-action plan *file*; the shared verb plan cannot be honored
#: there and is not forwarded (the adapter owns input injection).
DISCOVERY_PLAN_ENGINES = frozenset({"blender"})

#: engines whose recorder takes an explicit discovered-action plan *file*
#: built by converting the shared verb plan through the frozen per-game key
#: bindings — the frozen actions are forwarded, never silently dropped in
#: favor of free discovery.
PLAN_FILE_ENGINES = frozenset({"three_js"})

#: default shared verb → physical-key vocabulary (browser ``event.code``),
#: matching the Godot recorder's convention: WASD movement, Space jump,
#: J attack, U dash, H interact, Enter restart/start, Escape pause.
_DEFAULT_THREE_KEY_BINDINGS: dict[str, str] = {
    "move_up": "KeyW", "move_down": "KeyS",
    "move_left": "KeyA", "move_right": "KeyD",
    "jump": "Space", "attack": "KeyJ", "dash": "KeyU",
    "interact": "KeyH", "pause": "Escape", "restart": "Enter",
    "start": "Enter",
}

_THREE_KEY_ALIASES = {
    "space": "Space", "enter": "Enter", "return": "Enter",
    "escape": "Escape", "esc": "Escape", "tab": "Tab",
    "shift": "ShiftLeft", "leftshift": "ShiftLeft",
    "control": "ControlLeft", "ctrl": "ControlLeft", "leftctrl": "ControlLeft",
    "alt": "AltLeft", "leftalt": "AltLeft",
    "left_arrow": "ArrowLeft", "right_arrow": "ArrowRight",
    "up_arrow": "ArrowUp", "down_arrow": "ArrowDown",
    "up": "ArrowUp", "down": "ArrowDown", "left": "ArrowLeft", "right": "ArrowRight",
}


def _normalize_key_code(name: str) -> str:
    """Normalize a frozen binding spelling to a browser ``event.code``."""
    key = str(name or "").strip()
    if not key:
        return ""
    lowered = key.lower().replace(" ", "")
    if lowered in _THREE_KEY_ALIASES:
        return _THREE_KEY_ALIASES[lowered]
    if len(key) == 1:
        if key.isalpha():
            return f"Key{key.upper()}"
        if key.isdigit():
            return f"Digit{key}"
    if key.startswith(("Key", "Digit", "Arrow", "Numpad")):
        return key
    return key


def build_three_js_plan(steps: list | None,
                        input_bindings: Any = None) -> tuple[dict[str, Any], float]:
    """Convert the frozen shared verb plan into a three.js plan-file dict.

    The recorder's plan-file schema carries per-action ``keys``/``taps``
    (browser ``event.code`` values), not verbs, so the shared vocabulary is
    translated through the frozen ``input_bindings`` (per-game key names as
    frozen in the execution contract) with the shared default vocabulary as
    the fallback. Verbs with no usable mapping are **not** silently turned
    into free discovery: they are dropped from the action list and reported
    under ``unmapped_verbs`` so downstream coverage treats them as never
    sent (UNKNOWN), never as executed.

    Returns ``(plan_dict, plan_seconds)``.
    """
    bindings = dict(_DEFAULT_THREE_KEY_BINDINGS)
    binding_notes: list[str] = []
    for verb, key in (dict(input_bindings or {})).items():
        name = str(verb or "").strip().lower()
        code = _normalize_key_code(str(key))
        if not name or not code:
            binding_notes.append(f"input binding {verb!r}={key!r} is not usable")
            continue
        bindings[name] = code
        binding_notes.append(f"{name}→{code}")

    actions: list[dict[str, Any]] = []
    unmapped: list[str] = []
    seconds_total = 0.0
    for index, step in enumerate(steps or []):
        if not isinstance(step, dict):
            continue
        verb = str(step.get("verb") or step.get("action") or "").strip().lower()
        seconds = step.get("seconds")
        if seconds is None and step.get("duration_ms") is not None:
            seconds = float(step.get("duration_ms")) / 1000.0
        try:
            seconds = float(seconds) if seconds is not None else 0.1
        except (TypeError, ValueError):
            seconds = 0.1
        seconds = max(0.05, seconds)
        action: dict[str, Any] = {
            "id": str(step.get("id") or f"{verb or 'wait'}_{index + 1}"),
            "label": verb or "wait",
            "keys": [], "taps": [],
            "seconds": seconds,
        }
        from engine_adapters.action_provenance import action_metadata
        action.update(action_metadata(step))
        if not verb or verb == "wait":
            pass  # a scheduled pause: nothing to inject
        elif verb in {"mouse_move", "mouse_click", "mouse_drag", "mouse_down", "mouse_up", "mouse_hold", "mouse_wheel"}:
            from engine_adapters._mouse_plan import validate_mouse_step
            gesture = {k: step[k] for k in ("x", "y", "to_x", "to_y", "button", "delta_x", "delta_y") if k in step}
            gesture["kind"] = verb
            gesture["duration_ms"] = round(seconds * 1000)
            validate_mouse_step(gesture)
            gesture.pop("duration_ms")
            action["pointer"] = gesture
        elif verb == "key":
            from engine_adapters._input_capabilities import canonical_chord, browser_code
            physical = [browser_code(key) for key in canonical_chord(str(step.get("key") or ""))]
            action["keys"] = physical
        elif verb == "move":
            x = int(step.get("x") or 0)
            y = int(step.get("y") or 0)
            keys = []
            if x:
                keys.append(bindings.get("move_right" if x > 0 else "move_left"))
            if y:
                keys.append(bindings.get("move_down" if y > 0 else "move_up"))
            keys = [code for code in keys if code]
            if not keys:
                unmapped.append(verb)
                continue  # no usable direction key: never fabricate input
            action["keys"] = sorted(set(keys))
        else:
            code = bindings.get(verb)
            if code:
                action["taps"] = [code]
            else:
                unmapped.append(verb)
                continue  # never fabricate a different input for a frozen verb
        actions.append(action)
        seconds_total += seconds
    plan = {
        "schema": "gamefactory3a.three_js_action_plan.v1",
        "actions": actions,
        "sustained": [],
        "bindings": binding_notes,
        "unmapped_verbs": sorted(set(unmapped)),
    }
    return plan, round(seconds_total, 3)


def resolve_engine(name: str) -> str:
    """Canonical engine id for a task-record / CLI engine name."""
    engine = str(name or "").strip().lower()
    if engine not in ENGINE_ALIASES:
        raise ValueError(
            f"unknown engine {name!r} (supported: {sorted(set(ENGINE_ALIASES.values()))})"
        )
    return ENGINE_ALIASES[engine]


# ── engine client factories (lazy imports keep this module engine-free) ─────


def locate_godot_executable() -> Path | None:
    """The Godot binary, mirroring the task launch scripts' fallback chain.

    ``GodotClientConfig.resolve`` already honours ``$A3GAME_GODOT_EXECUTABLE``
    / ``$A3GAME_GODOT`` / ``$AAAGF_GODOT`` when the argument is ``None`` —
    return ``None`` so those keep priority, then fall back to ``godot4`` on
    PATH and the a3game managed install. Nothing found → ``None`` → the
    playtest fails honestly with "godot_executable is not configured".
    """
    for name in ("A3GAME_GODOT_EXECUTABLE", "A3GAME_GODOT", "AAAGF_GODOT"):
        if os.environ.get(name, "").strip():
            return None
    on_path = shutil.which("godot4")
    if on_path:
        return Path(on_path)
    managed = sorted(
        Path.home().glob(
            ".local/share/a3game/godot/*/*/Godot.app/Contents/MacOS/Godot"
        )
    )
    return managed[-1] if managed else None


def _make_godot_client(project_path: Path) -> Any:
    from engine_adapters.godot import GodotClient

    return GodotClient(
        project_path=project_path,
        godot_executable=locate_godot_executable(),
    )


def _make_unity_client(project_path: Path) -> Any:
    from engine_adapters.unity3d import UnityClient

    return UnityClient(project_path=project_path)


def _make_ue5_client(project_path: Path) -> Any:
    from engine_adapters.ue5 import UEClient

    return UEClient(project_path=project_path)


def _make_three_client(project_path: Path) -> Any:
    from engine_adapters.three_js import ThreeClient

    return ThreeClient(project_path=project_path)


def _make_blender_client(project_path: Path) -> Any:
    from engine_adapters.blender import BlenderClient

    return BlenderClient(project_path=project_path)


#: canonical engine → client factory (``factory(project_path)``). The client
#: owns launch, input injection and recording through
#: ``client.playtest.record(...)`` — nothing here re-implements engine
#: behavior. ``pipeline.game_eval.run`` re-exports this same dict object as its
#: ``ENGINE_CLIENTS``, so monkeypatching either name affects both.
ENGINE_CLIENTS: dict[str, Callable[[Path], Any]] = {
    "godot": _make_godot_client,
    "unity3d": _make_unity_client,
    "ue5": _make_ue5_client,
    "three_js": _make_three_client,
    "blender": _make_blender_client,
}


# ── engine-aware project location ────────────────────────────────────────────

#: engine → the project marker inside a task's output dir (or its
#: ``project/`` subdir, the layout the generated task outputs use).
_PROJECT_MARKERS: dict[str, tuple[str, str]] = {
    "godot": ("file", "project.godot"),
    "unity3d": ("dir", "Assets"),
    "ue5": ("glob", "*.uproject"),
    "three_js": ("file", "package.json"),
    "blender": ("file", "game.py"),
}


def locate_engine_project(engine: str, target_output_path: str | Path) -> Path:
    """The engine project inside a pipeline task's output directory.

    Raises ``ValueError`` when no project marker is found — the caller
    records it as an environment / adapter problem, never a game FAIL.
    """
    from pipeline.common import paths

    canonical = resolve_engine(engine)
    kind, marker = _PROJECT_MARKERS[canonical]
    base = paths.resolve_input_path(target_output_path)
    for candidate in (base / "project", base):
        if kind == "file" and (candidate / marker).is_file():
            return candidate
        if kind == "dir" and (candidate / marker).is_dir():
            return candidate
        if kind == "glob":
            if candidate.is_file() and candidate.suffix.lower() == ".uproject":
                return candidate.parent
            matches = sorted(candidate.glob(marker))
            if matches:
                return matches[0].parent
    raise ValueError(
        f"no {canonical} project ({marker}) found under {paths.rel_to_repo(base)}"
    )


# ── the uniform benchmark-side entry point ───────────────────────────────────


def _failure_envelope(
    engine: str, output_dir: Path, stage: str, message: str
) -> dict[str, Any]:
    """An ``ok=False`` record() envelope for a dispatch-side failure.

    Environment / adapter failures (missing binary, missing project, an
    adapter exception) are recorded verbatim — the caller keeps the
    diagnostics and the dependent metrics honestly stay UNKNOWN; nothing is
    ever fabricated into a PASS.
    """
    return {
        "ok": False,
        "operation": "playtest.record",
        "engine": engine,
        "artifacts": [],
        "diagnostics": [],
        "warnings": [],
        "errors": [message],
        "payload": {
            "engine": engine,
            "output_dir": str(output_dir),
            "failure_stage": stage,
        },
    }


def _record_accepts(client: Any, parameter: str) -> bool:
    """Whether the client's ``playtest.record()`` declares ``parameter``.

    Adapters with ``**kwargs`` accept anything; the dispatch only forwards
    the evidence channel request when the adapter explicitly declares it
    so no engine record() ever breaks on an unknown keyword.
    """
    import inspect

    try:
        record = client.playtest.record
    except AttributeError:
        return False
    try:
        signature = inspect.signature(record)
    except (TypeError, ValueError):
        return False
    if any(
        str(p.kind) == "VAR_KEYWORD"
        for p in signature.parameters.values()
    ):
        return True
    return parameter in signature.parameters


def record_playtest(
    *,
    engine: str,
    output_dir: str | Path,
    action_plan: list | None = None,
    project_path: str | Path | None = None,
    target_output_path: str | Path | None = None,
    duration: float = 12.0,
    fps: int | None = None,
    timeout: float | None = None,
    ffmpeg: str | Path | None = None,
    extra_engine_kwargs: dict | None = None,
    dry_run: bool = False,
    evidence_channels: list | None = None,
    input_bindings: dict | None = None,
) -> dict[str, Any]:
    """Record one playtest through the engine's own ``xxClient``.

    Returns ``{"engine", "project_path", "action_plan_forwarded",
    "plan_dispatch_note", "evidence_channels_forwarded",
    "evidence_channels_note", "envelope"}`` where ``envelope`` is the
    adapter's native ``playtest.record()`` result (or an honest failure
    envelope when the dispatch / adapter could not run). Construction,
    location and record failures are converted into failure envelopes
    with a ``failure_stage`` so the caller still writes a report — an
    engine that cannot start never becomes a fabricated PASS or a raised
    exception.

    ``action_plan`` is the frozen shared verb plan (``{verb, seconds}``).
    Verb-plan engines receive it translated to their native rows; the
    three.js recorder receives it converted into its real plan-file
    interface (written under ``output_dir``) through ``input_bindings``
    (the frozen per-game key bindings from the execution contract) — the
    frozen actions are forwarded, never dropped in favor of free
    discovery, and unmapped verbs are reported instead of guessed.

    ``evidence_channels`` (optional) is a benchmark-level *request* for
    the runtime evidence channels a profile needs (actions / states /
    events / timing / frames / video). Adapters whose ``record()`` accepts
    the parameter receive it (the Godot client records it into its native
    report); adapters that do not keep recording their full native
    evidence set and the request rides along in the dispatch result —
    the canonical evidence bundle later derives every channel's real
    status from the artifacts the run actually captured, never from the
    request.
    """
    canonical = resolve_engine(engine)
    out = Path(output_dir).expanduser().resolve(strict=False)
    plan_note = ""
    forwarded: list | None = None
    plan_file: Path | None = None
    plan_seconds: float | None = None
    try:
        if project_path is None:
            if target_output_path is None:
                raise ValueError(
                    "record_playtest needs project_path or target_output_path"
                )
            project_path = locate_engine_project(canonical, target_output_path)
        project = Path(project_path)
    except Exception as exc:  # location failure — environment/adapter problem
        return {
            "engine": canonical,
            "project_path": None,
            "action_plan_forwarded": False,
            "plan_dispatch_note": "",
            "envelope": _failure_envelope(
                canonical, out, "project_location", f"{type(exc).__name__}: {exc}"
            ),
        }

    if canonical in VERB_PLAN_ENGINES:
        forwarded = [dict(step) for step in (action_plan or [])]
    elif canonical in PLAN_FILE_ENGINES and action_plan:
        plan_dict, plan_seconds = build_three_js_plan(action_plan, input_bindings)
        if not plan_dict["actions"] and not plan_dict["unmapped_verbs"]:
            plan_note = "no action plan given: the three.js recorder will run its own discovery"
        else:
            plan_file = out / "action_plan.json"
            out.mkdir(parents=True, exist_ok=True)
            plan_file.write_text(
                json.dumps(plan_dict, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8")
            forwarded = [dict(step) for step in action_plan]
            plan_note = (
                "frozen verb plan converted into the three.js plan-file "
                f"interface ({len(plan_dict['actions'])} action(s), "
                f"{plan_seconds}s; bindings: {', '.join(plan_dict['bindings']) or 'shared defaults'})"
            )
            if plan_dict["unmapped_verbs"]:
                plan_note += (
                    f"; UNMAPPED verbs omitted (never sent, never guessed): "
                    f"{plan_dict['unmapped_verbs']}")
            # the recorder refuses a plan longer than the take unless partial
            # probing is explicitly allowed — give the full frozen plan room
            duration = max(float(duration), plan_seconds + 0.5)
    else:
        # Blender recorders take a discovered-action plan file and resolve
        # input through the running game — the shared verb plan cannot be
        # honored, so the adapter's own discovery owns injection.
        plan_note = (
            "action plan not forwarded: the {engine} recorder discovers the "
            "game's own actions and resolves their bindings from the running "
            "game (its plan-file schema carries per-action keys/taps, not "
            "the shared verb vocabulary)"
        ).format(engine=canonical)

    try:
        client = ENGINE_CLIENTS[canonical](project)
        # For Godot: inject rubric input_bindings into the config so the
        # recorder uses the game's actual key bindings rather than the
        # shared default vocabulary (e.g. interact=Enter instead of H).
        if canonical == "godot" and input_bindings:
            import dataclasses
            from engine_adapters.godot.playtest import GodotPlaytestClient
            new_config = dataclasses.replace(client._config,
                                             input_bindings=dict(input_bindings))
            client.playtest = GodotPlaytestClient(new_config)
    except Exception as exc:  # construction failure — environment problem
        return {
            "engine": canonical,
            "project_path": str(project),
            "action_plan_forwarded": False,
            "plan_dispatch_note": plan_note,
            "envelope": _failure_envelope(
                canonical, out, "client_construction",
                f"engine client construction failed: {type(exc).__name__}: {exc}",
            ),
        }

    kwargs: dict[str, Any] = {
        "output_dir": out,
        "duration": duration,
        "dry_run": dry_run,
    }
    # Unity: use the bundled internal input driver (GameFactory3AInputDriver)
    # which dispatches keys via InputSystem or EditorWindow.SendEvent without
    # requiring OS window focus, eliminating physical input delivery failures.
    if canonical == "unity3d" and _record_accepts(client, "input_transport"):
        kwargs["input_transport"] = "internal"
    # an explicit per-trial capture fps is forwarded to every adapter whose
    # record() accepts it; None keeps the adapter's own default (20) —
    # lowering the capture cadence never changes the simulated duration,
    # the action plan's seconds or any judged time window
    if fps is not None:
        if _record_accepts(client, "fps"):
            kwargs["fps"] = int(fps)
        else:
            plan_note += (f"; requested capture fps {int(fps)} not forwarded "
                          f"({canonical} adapter record() takes no fps parameter)")
    if canonical in PLAN_FILE_ENGINES and plan_file is not None:
        kwargs["action_plan"] = plan_file
    elif forwarded is not None:
        kwargs["action_plan"] = forwarded
    if timeout is not None:
        kwargs["timeout"] = timeout
    if ffmpeg is not None:
        kwargs["ffmpeg"] = ffmpeg
    kwargs.update(dict(extra_engine_kwargs or {}))

    # the evidence channel request forwards only to adapters that accept
    # it — an adapter that does not keeps recording its full native set and
    # the request is reported honestly instead of silently dropped
    channels_forwarded = False
    channels_note = ""
    if evidence_channels:
        if _record_accepts(client, "evidence_channels"):
            kwargs["evidence_channels"] = list(evidence_channels)
            channels_forwarded = True
            channels_note = (
                "evidence channel request forwarded to the adapter "
                f"({', '.join(str(c) for c in evidence_channels)})"
            )
        else:
            channels_note = (
                "evidence channel request recorded (not forwarded): the "
                f"{canonical} adapter's record() takes no evidence_channels "
                "parameter and records its full native evidence set — every "
                "channel's real status is derived from the artifacts the run "
                "actually captured"
            )

    try:
        envelope = client.playtest.record(**kwargs)
    except Exception as exc:  # adapter failure — recorded, never raised
        return {
            "engine": canonical,
            "project_path": str(project),
            "action_plan_forwarded": forwarded is not None,
            "plan_dispatch_note": plan_note,
            "action_plan_file": str(plan_file) if plan_file else None,
            "evidence_channels_forwarded": channels_forwarded,
            "evidence_channels_note": channels_note,
            "envelope": _failure_envelope(
                canonical, out, "record_call",
                f"engine adapter raised {type(exc).__name__}: {exc}",
            ),
        }
    return {
        "engine": canonical,
        "project_path": str(project),
        "action_plan_forwarded": forwarded is not None,
        "plan_dispatch_note": plan_note,
        "action_plan_file": str(plan_file) if plan_file else None,
        "plan_seconds": plan_seconds,
        "evidence_channels_forwarded": channels_forwarded,
        "evidence_channels_note": channels_note,
        "envelope": envelope,
    }


# ── the build-trial dispatch (FIRST_ATTEMPT_BUILD_SUCCESS evidence) ─────────

BUILD_TRACE_SCHEMA = "gamefactory3a.build_trace.v1"
BUILD_TRACE_FILENAME = "build_trace.jsonl"

#: engine caches that a clean-environment copy strips — a first-attempt
#: build must not inherit a warm import cache from earlier runs.
_CLEAN_COPY_IGNORE = shutil.ignore_patterns(".godot", "Library", "Build")


def _patch_godot_export_presets_etc2(project_path: Path) -> None:
    """Enable ETC2/ASTC texture formats in export_presets.cfg.

    On macOS, Godot requires ETC2/ASTC for arm64 export.  Projects that ship
    with ``texture_format/etc2=false`` abort the export with a config error.
    This patches the copy in the temp build dir — the source is never touched.
    """
    cfg = project_path / "export_presets.cfg"
    if not cfg.is_file():
        return
    text = cfg.read_text(encoding="utf-8", errors="replace")
    patched = text.replace("texture_format/etc2=false", "texture_format/etc2=true")
    patched = patched.replace("texture_format/etc2_astc=false", "texture_format/etc2_astc=true")
    if patched != text:
        cfg.write_text(patched, encoding="utf-8")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _append_trace_row(trace_path: Path, row: dict[str, Any]) -> int:
    """Append one attempt row; returns its 1-based ``attempt_index``."""
    rows: list[dict[str, Any]] = []
    if trace_path.is_file():
        for line in trace_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except ValueError:
                continue
            if isinstance(parsed, dict):
                rows.append(parsed)
    index = len(rows) + 1
    row = {"attempt_index": index, **row}
    with trace_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row) + "\n")
    return index


def _execute_godot_export(
    *,
    project_path: Path,
    evidence_dir: Path,
    spec: dict[str, Any],
    clean_environment: bool,
) -> dict[str, Any]:
    """One first-attempt Godot export through the existing build client.

    The engine owns the build (``GodotBuildClient.project`` → the adapter's
    staged ``--export-release`` pipeline); this executor only stages the
    clean copy, calls the client built from the shared registry, and
    preserves the adapter's captured stdout/stderr next to the trace. The
    export lands under ``evidence_dir/build_export/`` — the generated
    project itself is never written to.
    """
    preset = str(spec.get("preset") or "").strip()
    timeout = float(spec.get("timeout_s") or 600.0)
    build_project = project_path
    copy_root: Path | None = None
    if clean_environment:
        copy_root = Path(tempfile.mkdtemp(prefix="a3game-build-godot-"))
        build_project = copy_root / project_path.name
        shutil.copytree(project_path, build_project, ignore=_CLEAN_COPY_IGNORE)
        # Patch export_presets.cfg: macOS arm64 export requires ETC2/ASTC
        # texture formats; projects shipping with etc2=false abort the export.
        _patch_godot_export_presets_etc2(build_project)
    try:
        client = ENGINE_CLIENTS["godot"](build_project)
        output_path = evidence_dir / "build_export" / str(spec.get("output_name") or "export")
        started_at = _now_iso()
        started = time.monotonic()
        try:
            envelope = client.build.project(
                preset=preset,
                output_path=output_path,
                allow_external_output=True,
                timeout=timeout,
            )
        except Exception as exc:  # adapter failure — recorded, never raised
            envelope = {
                "ok": False,
                "errors": [f"godot export raised {type(exc).__name__}: {exc}"],
                "payload": {"engine": "godot"},
            }
        duration = round(time.monotonic() - started, 3)
        payload = envelope.get("payload") or {}
        # preserve the adapter's captured logs next to the trace — the row
        # carries their paths, the raw text stays in the evidence bundle
        stdout_path = stderr_path = None
        stdout_text = str(payload.get("stdout_tail") or payload.get("stdout") or "")
        stderr_text = str(payload.get("stderr_tail") or payload.get("stderr") or "")
        if stdout_text or stderr_text:
            (evidence_dir / "build_logs").mkdir(parents=True, exist_ok=True)
        if stdout_text:
            stdout_path = evidence_dir / "build_logs" / "stdout.log"
            stdout_path.write_text(stdout_text, encoding="utf-8")
        if stderr_text:
            stderr_path = evidence_dir / "build_logs" / "stderr.log"
            stderr_path.write_text(stderr_text, encoding="utf-8")
        exit_code = payload.get("returncode")
        return {
            "kind": "godot_export",
            "preset": preset,
            "project_path": str(project_path),
            "build_project_path": str(build_project),
            "clean_environment": clean_environment,
            "command": payload.get("command") or "",
            "started_at": started_at,
            "finished_at": _now_iso(),
            "duration_seconds": duration,
            "exit_code": exit_code if isinstance(exit_code, int) else None,
            "succeeded": bool(envelope.get("ok")),
            "produced_paths": list(payload.get("produced_paths") or []),
            "stdout_path": str(stdout_path) if stdout_path else None,
            "stderr_path": str(stderr_path) if stderr_path else None,
            "errors": [str(item) for item in envelope.get("errors") or []],
            "warnings": [str(item) for item in envelope.get("warnings") or []],
            # the adapter's full diagnostic classification (severity/code/
            # message), so the trace keeps *why* each line was judged an
            # error vs a benign headless-renderer note — verdicts stay
            # auditable from build_trace.jsonl alone
            "diagnostics": list(envelope.get("diagnostics") or []),
            "failure_stage": None if envelope.get("ok") else "build_call",
        }
    finally:
        if copy_root is not None:
            shutil.rmtree(copy_root, ignore_errors=True)


def _execute_unity_export(
    *,
    project_path: Path,
    evidence_dir: Path,
    spec: dict[str, Any],
    clean_environment: bool = True,
) -> dict[str, Any]:
    """One first-attempt Unity/Tuanjie player build through the editor CLI.

    The engine owns the build (``BuildPipeline.BuildPlayer`` invoked by the
    project's own static editor method via ``-executeMethod``); this
    executor only stages the clean copy, launches the editor in batch mode,
    and preserves the editor log plus the build script's JSON report next to
    the trace. The build lands under ``evidence_dir/build_export/`` — the
    generated project itself is never written to.

    Frozen spec fields (engine-keyed ``build_trials``):

    * ``execute_method`` — the project's static build entry (required);
    * ``unity_binary`` — editor binary override (else ``A3GAME_UNITY_ROOT``);
    * ``timeout_s`` — editor batch timeout (default 1800);
    * ``output_name`` — artifact subdirectory under ``build_export/``;
    * ``clean_environment`` — build on a cache-stripped copy (default true;
      the dispatch passes it explicitly from the frozen spec).
    """
    method = str(spec.get("execute_method") or "").strip()
    if not method:
        return {
            "kind": "unity_export",
            "skipped": True,
            "skip_reason": "unity_export spec carries no execute_method",
            "started_at": _now_iso(),
            "succeeded": None,
            "exit_code": None,
            "errors": ["no execute_method frozen in the build spec"],
        }
    timeout = float(spec.get("timeout_s") or 1800.0)
    binary_value = str(spec.get("unity_binary") or "").strip() or (
        os.environ.get("A3GAME_UNITY_ROOT") or os.environ.get("AAAGF_UNITY") or ""
    )
    unity_binary = Path(binary_value).expanduser() if binary_value else None
    if unity_binary is None or not unity_binary.is_file():
        return {
            "kind": "unity_export",
            "skipped": True,
            "skip_reason": "no Unity/Tuanjie editor binary configured (A3GAME_UNITY_ROOT)",
            "started_at": _now_iso(),
            "succeeded": None,
            "exit_code": None,
            "errors": ["Unity/Tuanjie editor binary not found"],
        }
    build_project = project_path
    copy_root: Path | None = None
    if clean_environment:
        copy_root = Path(tempfile.mkdtemp(prefix="a3game-build-unity-"))
        build_project = copy_root / project_path.name
        shutil.copytree(project_path, build_project, ignore=_CLEAN_COPY_IGNORE)
    output_dir = evidence_dir / "build_export" / str(spec.get("output_name") or "export")
    output_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "build_logs").mkdir(parents=True, exist_ok=True)
    log_path = evidence_dir / "build_logs" / "editor.log"
    report_path = output_dir / "_build_report.json"
    command = [
        str(unity_binary),
        "-batchmode",
        "-quit",
        "-projectPath", str(build_project),
        "-executeMethod", method,
        "--a3-build-output", str(output_dir),
        "--a3-build-report", str(report_path),
        "-logFile", str(log_path),
    ]
    started_at = _now_iso()
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(build_project),
        )
        exit_code: int | None = completed.returncode
    except subprocess.TimeoutExpired:
        exit_code = None
    except OSError as exc:
        exit_code = None
        (evidence_dir / "build_logs" / "stderr.log").write_text(
            f"editor launch failed: {type(exc).__name__}: {exc}", encoding="utf-8"
        )
    duration = round(time.monotonic() - started, 3)

    build_report: dict[str, Any] = {}
    if report_path.is_file():
        try:
            build_report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            build_report = {"_unreadable": True}
    build_succeeded = bool(
        exit_code == 0
        and build_report
        and build_report.get("result") == "Succeeded"
    )
    errors = [
        str(item) for item in (build_report.get("errors") or [])
    ] or (
        [] if exit_code == 0 else [f"editor exited with code {exit_code}"]
    )
    if exit_code is None:
        errors = [f"editor build timed out after {timeout:.0f}s"]
    if log_path.is_file():
        try:
            log_text = log_path.read_text(encoding="utf-8", errors="replace")
            (evidence_dir / "build_logs" / "editor_tail.log").write_text(
                log_text[-4000:], encoding="utf-8"
            )
        except OSError:
            pass
    row = {
        "kind": "unity_export",
        "execute_method": method,
        "project_path": str(project_path),
        "build_project_path": str(build_project),
        "clean_environment": bool(clean_environment),
        "command": " ".join(command),
        "started_at": started_at,
        "finished_at": _now_iso(),
        "duration_seconds": duration,
        "exit_code": exit_code,
        "succeeded": build_succeeded,
        "produced_paths": [
            str(path) for path in sorted(output_dir.rglob("*")) if path.is_file()
        ][:40],
        "stdout_path": None,
        "stderr_path": None,
        "errors": errors,
        "warnings": [str(item) for item in (build_report.get("warnings") or [])],
        "build_report": build_report,
        "failure_stage": None if build_succeeded else "build_call",
    }
    if copy_root is not None:
        shutil.rmtree(copy_root, ignore_errors=True)
    return row


def _execute_three_build(
    *,
    project_path: Path,
    evidence_dir: Path,
    spec: dict[str, Any],
    clean_environment: bool,
) -> dict[str, Any]:
    """One first-attempt three.js web-bundle build via ThreeBuildClient.

    The build runs inside the evaluation workspace copy (the caller always
    points ``project_path`` at the workspace, never at the generated
    original), so ``clean_environment`` has nothing extra to stage — the
    parameter exists to mirror the other executors' signature.
    """
    started_at = _now_iso()
    timeout = float(spec.get("timeout_s") or 600.0)
    client = ENGINE_CLIENTS["three_js"](project_path)
    result = client.build.project(
        target=str(spec.get("target") or "build"),
        configuration=str(spec.get("configuration") or "production"),
        clean=bool(spec.get("clean") or clean_environment),
        timeout=timeout,
    )
    if not isinstance(result, dict):
        result = {}
    ok = bool(result.get("ok"))
    errors = [str(item) for item in (result.get("errors") or [])]
    diagnostics = [str(getattr(d, "message", d)) for d in (result.get("diagnostics") or [])]
    payload = result.get("payload") if isinstance(result.get("payload"), dict) else {}
    return {
        "kind": "three_build",
        "project_path": str(project_path),
        "target": str(spec.get("target") or "build"),
        "started_at": started_at,
        "finished_at": _now_iso(),
        "exit_code": 0 if ok else 1,
        "succeeded": ok,
        "produced_paths": [str(a.get("path")) for a in (result.get("artifacts") or [])
                           if isinstance(a, dict) and a.get("path")],
        "errors": errors or ([] if ok else ["vite build failed (see diagnostics)"]),
        "warnings": [str(item) for item in (result.get("warnings") or [])],
        "diagnostics": diagnostics[:20],
        "build_report": payload,
        "failure_stage": None if ok else "build_call",
    }


def ensure_unity_startup_scene(
    *,
    engine: str,
    evidence_dir: str | Path,
    project_path: str | Path,
    bootstrap: dict[str, Any],
    timeout_s: float = 1200.0,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Follow a project's declared startup flow to materialize its launch scene.

    Some generated Unity projects ship no ``.unity`` asset but declare their
    startup scene at editor load (a static constructor on an Editor class
    that creates the scene and registers it in EditorBuildSettings). This
    executor runs *that declared bootstrap entry* — never a repair method —
    once in batch mode on the evaluation workspace copy, preserves the
    editor log under the evidence bundle, and reports whether the declared
    scene path actually materialized. A failure here is an environment/
    flow problem and is reported as such, never as a game FAIL.
    """
    canonical = resolve_engine(engine)
    if canonical != "unity3d":
        return {"executed": False, "scene_path": None,
                "error": f"startup-scene bootstrap is unity3d-only, got {engine!r}"}
    out_dir = Path(evidence_dir)
    log_dir = out_dir / "startup_bootstrap"
    log_dir.mkdir(parents=True, exist_ok=True)
    method = str((bootstrap or {}).get("execute_method") or "").strip()
    scene_path = str((bootstrap or {}).get("scene_path") or "").strip()
    summary = {
        "declared": True,
        "execute_method": method,
        "scene_path": scene_path or None,
        "source": bootstrap.get("source"),
        "log_path": str(log_dir / "editor.log"),
    }
    if not method:
        return {**summary, "executed": False,
                "error": "the declared bootstrap carries no executable method"}
    if dry_run:
        return {**summary, "executed": False, "dry_run": True}
    binary_value = (os.environ.get("A3GAME_UNITY_ROOT")
                    or os.environ.get("AAAGF_UNITY") or "").strip()
    unity_binary = Path(binary_value).expanduser() if binary_value else None
    if unity_binary is None or not unity_binary.is_file():
        return {**summary, "executed": False,
                "error": "no Unity/Tuanjie editor binary configured "
                         "(A3GAME_UNITY_ROOT) — the declared startup flow "
                         "cannot be followed in this environment"}
    project = Path(project_path)
    command = [
        str(unity_binary), "-batchmode", "-quit",
        "-projectPath", str(project),
        "-executeMethod", method,
        "-logFile", str(log_dir / "editor.log"),
    ]
    started_at = _now_iso()
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True,
            timeout=float(timeout_s), cwd=str(project))
        exit_code: int | None = completed.returncode
    except subprocess.TimeoutExpired:
        exit_code = None
    except OSError as exc:
        (log_dir / "stderr.log").write_text(
            f"editor launch failed: {type(exc).__name__}: {exc}", encoding="utf-8")
        exit_code = None
    duration = round(time.monotonic() - started, 3)
    scene_exists = bool(scene_path and (project / scene_path).is_file())
    return {
        **summary,
        "executed": True,
        "command": " ".join(command),
        "started_at": started_at,
        "finished_at": _now_iso(),
        "duration_seconds": duration,
        "exit_code": exit_code,
        "scene_path": scene_path if scene_exists else None,
        "ok": bool(exit_code == 0 and scene_exists),
        "error": None if scene_exists else (
            f"the declared startup bootstrap ran (exit {exit_code}) but the "
            f"declared scene {scene_path!r} did not materialize"),
    }


#: build-spec kind → executor. Each executor receives the located project
#: and the frozen spec and returns the trace-row facts; kinds without an
#: executor record a skipped row (the metric honestly stays UNKNOWN and the
#: extension point stays explicit).
_BUILD_EXECUTORS: dict[str, Callable[..., dict[str, Any]]] = {
    "godot_export": _execute_godot_export,
    "unity_export": _execute_unity_export,
    "three_build": _execute_three_build,
}


def record_build_trial(
    *,
    engine: str,
    evidence_dir: str | Path,
    target_output_path: str | Path,
    spec: dict[str, Any] | None,
) -> dict[str, Any]:
    """Run one frozen build attempt and append it to ``build_trace.jsonl``.

    ``spec`` is the case's frozen per-engine build trial (or ``None`` when
    the case freezes no build for this engine — the row records the skip so
    FIRST_ATTEMPT_BUILD_SUCCESS stays honestly UNKNOWN with the reason
    preserved). The first attempt (``attempt_index=1``) is authoritative;
    later rows are retry diagnostics and never overwrite it. Returns
    ``{"trace_path", "attempt_index", "row", "summary"}``; never raises —
    execution failures become trace rows with ``failure_stage`` set.
    """
    canonical = resolve_engine(engine)
    out_dir = Path(evidence_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    trace_path = out_dir / BUILD_TRACE_FILENAME

    if not spec:
        index = _append_trace_row(
            trace_path,
            {
                "schema_version": BUILD_TRACE_SCHEMA,
                "engine": canonical,
                "kind": "none",
                "skipped": True,
                "skip_reason": (
                    "no frozen build trial for this engine in the case "
                    "definition — build evidence not collected"
                ),
                "started_at": _now_iso(),
                "succeeded": None,
                "exit_code": None,
                "errors": [],
            },
        )
        return {
            "trace_path": str(trace_path),
            "attempt_index": index,
            "row": None,
            "summary": {
                "executed": False,
                "skipped": True,
                "reason": "no frozen build trial for this engine",
            },
        }

    kind = str(spec.get("kind") or "").strip()
    executor = _BUILD_EXECUTORS.get(kind)
    if executor is None:
        index = _append_trace_row(
            trace_path,
            {
                "schema_version": BUILD_TRACE_SCHEMA,
                "engine": canonical,
                "kind": kind,
                "skipped": True,
                "skip_reason": (
                    f"build kind {kind!r} has no executor in the dispatch "
                    "yet (extension point) — build evidence not collected"
                ),
                "started_at": _now_iso(),
                "succeeded": None,
                "exit_code": None,
                "errors": [],
            },
        )
        return {
            "trace_path": str(trace_path),
            "attempt_index": index,
            "row": None,
            "summary": {
                "executed": False,
                "skipped": True,
                "reason": f"build kind {kind!r} not implemented",
            },
        }

    try:
        project_path = locate_engine_project(canonical, target_output_path)
    except Exception as exc:
        index = _append_trace_row(
            trace_path,
            {
                "schema_version": BUILD_TRACE_SCHEMA,
                "engine": canonical,
                "kind": kind,
                "skipped": False,
                "failure_stage": "project_location",
                "started_at": _now_iso(),
                "succeeded": None,
                "exit_code": None,
                "errors": [f"{type(exc).__name__}: {exc}"],
            },
        )
        return {
            "trace_path": str(trace_path),
            "attempt_index": index,
            "row": None,
            "summary": {
                "executed": False,
                "skipped": False,
                "reason": f"project location failed: {exc}",
            },
        }

    clean = bool(spec.get("clean_environment", True))
    row = executor(
        project_path=project_path,
        evidence_dir=out_dir,
        spec=spec,
        clean_environment=clean,
    )
    row["schema_version"] = BUILD_TRACE_SCHEMA
    row["engine"] = canonical
    row["skipped"] = False
    index = _append_trace_row(trace_path, row)
    return {
        "trace_path": str(trace_path),
        "attempt_index": index,
        "row": dict(row),
        "summary": {
            "executed": True,
            "skipped": False,
            "kind": kind,
            "succeeded": row.get("succeeded"),
            "exit_code": row.get("exit_code"),
            "attempt_index": index,
            "errors": list(row.get("errors") or []),
        },
    }


__all__ = [
    "ENGINE_ALIASES",
    "ENGINE_CLIENTS",
    "VERB_PLAN_ENGINES",
    "DISCOVERY_PLAN_ENGINES",
    "PLAN_FILE_ENGINES",
    "BUILD_TRACE_FILENAME",
    "BUILD_TRACE_SCHEMA",
    "resolve_engine",
    "locate_engine_project",
    "locate_godot_executable",
    "record_playtest",
    "record_build_trial",
    "build_three_js_plan",
    "ensure_unity_startup_scene",
]
