"""Real native recording through the engine adapters (adapters used as-is).

One take per run, serialized by the same global GUI lock file the historical
evaluator uses (``$TMPDIR/gamefactory-sol-whitebox-gui.lock``), so a new run
waits for — never competes with — any other GUI recording on this machine.
No OS keyboard/mouse fallback, no replay, no synthetic frames: if the adapter
cannot deliver an input or frames, the take is a ``HarnessError``.

Output (``<run>/takes/<k>/record/``): ``native/`` (adapter output, untouched) plus
canonical copies ``actions.jsonl``, ``state_trace.jsonl``, ``event_trace.jsonl``,
``frame_index.jsonl``, ``frames/``, and ``record_result.json``.

Frames are action-anchored where the recorder allows it (capture.py); Unity
projects of any version open in an editor chosen by unity_editor.py.
"""
from __future__ import annotations

import fcntl
from contextlib import contextmanager, nullcontext
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from ..core.llm import HarnessError
from ..core.paths import FRAMEWORK, read_json, sha256, write_json
from . import capture
from engine_adapters.unity3d.playtest import unity_editor, unity_input
from ..plan.plan import native_actions, take_dir

VERSION = 'stage1-record.v1'
GUI_LOCK = Path(tempfile.gettempdir()) / 'gamefactory-sol-whitebox-gui.lock'
# Parallel recording slots: slot 0 is the historical global lock (default = fully
# serial, shared with the historical evaluator); A3GAME_GUI_SLOTS=N adds N-1 more.
GUI_SLOTS = max(1, int(os.environ.get('A3GAME_GUI_SLOTS', '1')))
LOCK_WAIT_S = float(os.environ.get('A3GAME_GUI_WAIT_S', '3600'))
UE_ROOT = os.environ.get('A3GAME_UE_ROOT') or '/Users/Shared/Epic Games/UE_5.4'


# A3GAME_EXCLUSIVE_ENGINE=1: engine builds / imports / batch renders take the same slot as recordings, so (with
# A3GAME_GUI_SLOTS=1) only one engine process runs on the machine; the other lanes only plan / judge meanwhile.
EXCLUSIVE_ENGINE = os.environ.get('A3GAME_EXCLUSIVE_ENGINE') == '1'
LOCK_WAITED_S = 0.0          # time this process spent waiting for a slot; excluded from the project budgets
_HELD = {'depth': 0, 'path': None}


def busy_clock() -> float:
    """time.monotonic() minus the time spent waiting for an engine slot (for budgets)."""
    return time.monotonic() - LOCK_WAITED_S


@contextmanager
def gui_slot():
    """Hold one free recording slot; wait up to LOCK_WAIT_S, then HarnessError. Re-entrant in one process."""
    global LOCK_WAITED_S
    if _HELD['depth']:
        _HELD['depth'] += 1
        try:
            yield _HELD['path']
        finally:
            _HELD['depth'] -= 1
        return
    paths = [GUI_LOCK] + [GUI_LOCK.with_name(f'gamefactory-sol-whitebox-gui.slot{k}.lock')
                          for k in range(1, GUI_SLOTS)]
    handles = [p.open('a') for p in paths]
    try:
        t0 = time.monotonic()
        deadline = t0 + LOCK_WAIT_S
        while True:
            for path, fh in zip(paths, handles):
                try:
                    fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    continue
                LOCK_WAITED_S += time.monotonic() - t0
                _HELD.update(depth=1, path=path)
                try:
                    yield path
                finally:
                    _HELD.update(depth=0, path=None)
                return
            if time.monotonic() >= deadline:
                LOCK_WAITED_S += time.monotonic() - t0
                raise HarnessError(f'all {GUI_SLOTS} GUI recording slot(s) busy for {LOCK_WAIT_S:.0f}s')
            time.sleep(1)
    finally:
        for fh in handles:
            fh.close()


def engine_lock():
    """Slot for engine work that needs no screen (build / import / batch render) when EXCLUSIVE_ENGINE."""
    return gui_slot() if EXCLUSIVE_ENGINE else nullcontext()
FPS = 10
# UE's native recorder never skips a late capture slot and fails the take if it falls behind;
# 10 fps screenshots measured ~6/s under load, so UE captures at 4 fps (250 ms slots).
FPS_BY_ENGINE = {'ue5': 4}
# Idle engine pre-roll before UE actions and capture start: absorbs the first-frame startup
# hitch (measured up to ~430 ms) that would push the first slots past the 350 ms tolerance.
UE_WARMUP_S = 3.0
# User decision B: accept frames up to 3 s late (real timestamps kept, lateness recorded).
UE_LATE_TOLERANCE_MS = 30000  # was 6000 (3000 before); the whole engine can stall for 5-9 s while another lane builds /
                              # launches UE (Sol G003 run d: 9 s without an engine frame, slots up to 15.6 s late).
                              # Every frame keeps its real timestamp and lateness (capture_lateness.json); the judge sees it.
CHANNELS = ('actions.jsonl', 'state_trace.jsonl', 'event_trace.jsonl', 'frame_index.jsonl')
EXTRA_FILES = ('video.mp4', 'play_started.json', 'input_view_cleanup.json', 'browser_cleanup.json',
               'process_cleanup.json', 'editor_cleanup.json', 'engine.log', 'execution.json',
               'launch_diagnostics.json', 'capture_schedule.json')
from .native_log import godot_product_errors
from ..evidence import asset_views
from ..core import prepare


# --- engine clients ----------------------------------------------------------
def godot_executable() -> str | None:
    """Same resolution order as the framework: env vars, godot4 on PATH, managed install."""
    for name in ('A3GAME_GODOT_EXECUTABLE', 'A3GAME_GODOT', 'AAAGF_GODOT'):
        if os.environ.get(name, '').strip():
            return os.environ[name].strip()
    found = shutil.which('godot4')
    if found:
        return found
    managed = sorted(Path.home().glob('.local/share/a3game/godot/*/*/Godot.app/Contents/MacOS/Godot'))
    return str(managed[-1]) if managed else None


def _free_ports(n: int) -> list:
    """Distinct localhost ports free for both UDP and TCP right now."""
    import socket
    ports = []
    while len(ports) < n:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        try:
            for kind in (socket.SOCK_DGRAM, socket.SOCK_STREAM):
                with socket.socket(socket.AF_INET, kind) as check:
                    check.bind(('127.0.0.1', port))
        except OSError:
            continue
        if port not in ports:
            ports.append(port)
    return ports


def make_client(engine: str, project: Path, unity_binary: str | None = None):
    if engine == 'godot':
        from engine_adapters.godot import GodotClient
        exe = godot_executable()
        return GodotClient(project_path=project, godot_executable=Path(exe) if exe else None)
    if engine == 'three_js':
        from engine_adapters.three_js import ThreeClient
        return ThreeClient(project_path=project)
    if engine == 'unity3d':
        from engine_adapters.unity3d import UnityClient
        return UnityClient(project_path=project, unity_root=unity_binary)
    if engine == 'ue5':
        from engine_adapters.ue5 import UEClient
        # Other sessions' UE playtests use the default ports; take free private ones per take.
        rc_port, runtime_port = _free_ports(2)
        return UEClient(project_path=project, ue_root=UE_ROOT, port=rc_port, runtime_port=runtime_port)
    raise ValueError(f'unsupported engine {engine}')


def _run(cmd, log: Path, timeout: float) -> dict:
    with log.open('w') as fh:
        try:
            # one-off imports / builds run at low CPU priority so parallel recordings keep the CPU
            proc = subprocess.run(['nice', '-n', '19', *[str(c) for c in cmd]], stdout=fh, stderr=subprocess.STDOUT,
                                  timeout=timeout)
            return {'cmd': [str(c) for c in cmd], 'exit_code': proc.returncode, 'timeout': False}
        except subprocess.TimeoutExpired:
            return {'cmd': [str(c) for c in cmd], 'exit_code': None, 'timeout': True}


def three_js_plan(actions: list[dict]) -> dict:
    """Adapter plan-file format: browser key codes per action, pointer gestures as-is."""
    from engine_adapters._input_capabilities import browser_code, canonical_chord
    out = []
    for a in actions:
        row = {'id': a['action_id'], 'label': a['action'], 'keys': [], 'taps': [],
               'seconds': max(0.05, a.get('duration_ms', 100) / 1000.0),
               **{k: a[k] for k in ('action_id', 'probe_id', 'step_id', 'criterion_ids', 'purpose',
                                    'expected_observation', 'planned_t_ms', 'planned_end_t_ms') if k in a}}
        if a['action'] == 'key':
            row['keys'] = [browser_code(k) for k in canonical_chord(a['key'])]
        elif a['action'].startswith('mouse_'):
            row['pointer'] = {'kind': a['action'], **{k: a[k] for k in ('x', 'y', 'to_x', 'to_y', 'button',
                                                                        'delta_x', 'delta_y') if k in a}}
        out.append(row)
    return {'schema': 'gamefactory3a.three_js_action_plan.v1', 'actions': out, 'sustained': [],
            'bindings': [], 'unmapped_verbs': []}


# --- engine-specific takes -------------------------------------------------------
def _schedule(actions, budget, runtime: Path):
    """Action-anchored capture schedule, or None when the take must stay dense."""
    try:
        sched, guards = capture.schedule(actions, budget['recording_ms'])
    except ValueError as exc:
        write_json(runtime / 'capture_mode.json', {'mode': 'dense', 'reason': str(exc)})
        return None, None
    write_json(runtime / 'capture_mode.json', {'mode': 'action_anchored', 'points': len(sched['points'])})
    return sched, guards


def _godot_window_size(project: Path) -> tuple[int, int]:
    """Use the author's viewport so fixed-position UI is not cropped by capture."""
    config = Path(project) / 'project.godot'
    dimensions = {'viewport_width': 960, 'viewport_height': 540}
    section = ''
    for raw in config.read_text(encoding='utf-8-sig').splitlines():
        line = raw.split(';', 1)[0].strip()
        if line.startswith('[') and line.endswith(']'):
            section = line[1:-1]
        elif section == 'display' and '=' in line:
            key, value = (part.strip() for part in line.split('=', 1))
            for dimension in dimensions:
                if key == 'window/size/' + dimension:
                    if not value.isdecimal() or int(value) <= 0:
                        raise HarnessError(f'Invalid authored Godot {dimension}: {value}')
                    dimensions[dimension] = int(value)
    return dimensions['viewport_width'], dimensions['viewport_height']


def _godot(client, project: Path, plan_path: Path, native: Path, budget: dict, deadline: float) -> dict:
    width, height = _godot_window_size(project)
    write_json(native.parent / 'window_size.json', {
        'width': width, 'height': height, 'basis': 'authored_viewport_with_legacy_defaults',
        'project_config_sha256': sha256(project / 'project.godot')})
    exe = godot_executable()
    if not exe:
        raise HarnessError('Godot executable not configured')
    imp = _run([exe, '--headless', '--path', project, '--editor', '--import'], native.parent / 'import.log',
               timeout=min(budget['engine_startup_ms'] / 1000, max(0.1, deadline - time.monotonic())))
    imp['product_errors'] = godot_product_errors((native.parent / 'import.log').read_text(errors='replace'))
    write_json(native.parent / 'import_result.json', imp)
    if imp['timeout']:
        raise HarnessError('Godot import timed out')
    if imp['exit_code'] and not imp['product_errors']:
        raise HarnessError('Godot import failed without a diagnosed product error')
    plan = read_json(plan_path)
    # The bounded Godot adapter finishes after the input plan unless recording_ms
    # is explicit. Dense/conditional plans need the same full observation window
    # as sparse plans; the duration keyword alone is ignored by that adapter path.
    observation = native.parent / 'recording_plan.json'
    recording_plan = {**plan, 'recording_ms': budget['recording_ms']}
    if capture.supported('godot', plan):
        sched, _ = _schedule(capture.godot_actions(plan), budget, native.parent)
        if sched:
            recording_plan['native_capture_schedule'] = sched
    else:
        write_json(native.parent / 'capture_mode.json', {'mode': 'dense', 'reason': 'condition waits'})
    write_json(observation, recording_plan)
    return client.playtest.record(output_dir=native, duration=budget['recording_ms'] / 1000, fps=FPS,
                                  timeout=max(0.1, deadline - time.monotonic()),
                                  observation_plan=observation, width=width, height=height)


def _unity_import(binary: str, project: Path, runtime: Path, budget: dict, deadline: float) -> None:
    """Open + compile the working copy once in batch mode (version upgrade happens here, on the copy)."""
    log = runtime / 'import.log'
    result = _run([binary, '-batchmode', '-nographics', '-quit', '-projectPath', project, '-logFile', log],
                  runtime / 'import_console.log',
                  timeout=min(budget['engine_startup_ms'] / 1000 * 2, max(0.1, deadline - time.monotonic())))
    text = log.read_text(errors='replace') if log.is_file() else ''
    result['product_errors'] = bool(re.search(r'error CS\d+|Scripts have compiler errors', text))
    write_json(runtime / 'import_result.json', result)
    if result['timeout']:
        raise HarnessError('Unity import timed out')
    if result['exit_code'] and not result['product_errors']:
        raise HarnessError('Unity import failed without a diagnosed compile error; see runtime/import.log')


def _unity_input_metadata(out: Path, manifest: dict, choice: dict, deadline: float) -> dict | None:
    """Once per runtime copy, let the selected Editor create a missing InputManager.

    This is preparation, never gameplay or a retry/recovery entry point. Compiler
    diagnostics retain _unity_import's existing product-error policy.
    """
    out = Path(out)
    project = (out / 'runtime/project').resolve()
    axes = project / 'ProjectSettings/InputManager.asset'
    receipt_dir = out / 'runtime/unity_input_metadata'
    if receipt_dir.exists():
        receipt_path = receipt_dir / 'receipt.json'
        receipt = read_json(receipt_path) if receipt_path.is_file() else {}
        if (receipt.get('status') != 'metadata_ready' or not axes.is_file()
                or receipt.get('editor', {}).get('editor') != choice['editor']
                or receipt.get('after', {}).get('ProjectSettings/InputManager.asset', {}).get('sha256') != sha256(axes)):
            raise HarnessError('Unity metadata initialization already attempted; inspect its receipt before recovery')
        return receipt
    if axes.is_file():
        return None                         # Existing axes: no new native operation.
    if axes.exists() or axes.is_symlink():
        raise HarnessError('InputManager path is not an absent regular file')
    source = Path(manifest['project_source']).resolve()
    frozen = (out / 'input/project').resolve()
    if project in (source, frozen):
        raise HarnessError('Unity metadata initialization requires an isolated runtime copy')

    def metadata(root):
        return {name: {'exists': (root / name).is_file(),
                       'sha256': sha256(root / name) if (root / name).is_file() else None}
                for name in ('ProjectSettings/ProjectSettings.asset', 'ProjectSettings/InputManager.asset',
                             'ProjectSettings/ProjectVersion.txt')}

    original, snapshot, before = metadata(source), metadata(frozen), metadata(project)
    if original != snapshot or snapshot != before:
        raise HarnessError('Unity missing-axes metadata differs from the original/frozen snapshot')
    if not before['ProjectSettings/ProjectVersion.txt']['exists']:
        raise HarnessError('Unity missing-axes initialization requires authored ProjectVersion.txt')
    # Do not use this narrowly scoped step to repair absent/malformed PlayerSettings.
    unity_input._handler_update((project / 'ProjectSettings/ProjectSettings.asset').read_bytes().decode('utf-8'))
    if (out / 'runtime/unity_input_migration.json').exists():
        raise HarnessError('Unity metadata initialization cannot repair a previously migrated copy')
    if time.monotonic() >= deadline:
        raise HarnessError('Unity metadata preparation deadline exhausted')
    try:
        receipt_dir.mkdir()                  # Exclusive claim; failures never get an automatic second import.
    except FileExistsError as exc:
        raise HarnessError('Unity metadata initialization already claimed') from exc
    receipt = {'version': 'stage1-unity-input-metadata.v1', 'status': 'started',
               'project': str(project), 'source': str(source), 'snapshot': str(frozen),
               'editor': choice, 'original_before': original, 'snapshot_before': snapshot,
               'before': before, 'budget': manifest['budget'], 'max_import_calls': 1,
               'receipt_dir': str(receipt_dir.resolve()),
               'producer': {'record.py': sha256(Path(__file__)),
                            'unity_input.py': sha256(Path(unity_input.__file__))}}
    write_json(receipt_dir / 'claim.json', receipt)
    try:
        _unity_import(choice['editor']['binary'], project, receipt_dir, manifest['budget'], deadline)
        unity_input._input_axes(project)      # Generated bytes must be usable before any migration writes.
        receipt['status'] = 'metadata_ready'
    except Exception as exc:
        receipt['status'] = 'failed'
        receipt['error'] = {'type': type(exc).__name__, 'message': str(exc)}
        raise
    finally:
        receipt['after'] = metadata(project)
        receipt['original_after'], receipt['snapshot_after'] = metadata(source), metadata(frozen)
        receipt['original_metadata_unchanged'] = receipt['original_after'] == original
        receipt['snapshot_metadata_unchanged'] = receipt['snapshot_after'] == snapshot
        result = receipt_dir / 'import_result.json'
        receipt['import_result'] = read_json(result) if result.is_file() else None
        receipt['evidence_sha256'] = {name: sha256(receipt_dir / name)
                                    for name in ('import.log', 'import_console.log', 'import_result.json')
                                    if (receipt_dir / name).is_file()}
        if not receipt['original_metadata_unchanged'] or not receipt['snapshot_metadata_unchanged']:
            receipt['status'] = 'failed'
        write_json(receipt_dir / 'receipt.json', receipt)
    if receipt['status'] != 'metadata_ready':
        raise HarnessError('Unity metadata source changed during import; inspect receipt')
    return receipt


def _native(client, engine: str, project: Path, plan: dict, native: Path, budget: dict, deadline: float,
            admitted: dict | None = None) -> dict:
    actions = native_actions(plan, engine)
    legacy_zero = [a for a in actions if a.get('action_id') != 'system/startup'
                   and any(s.get('id') == a.get('step_id') and s.get('duration_ms') == 0
                           for probe in plan['probes'] if probe['id'] == a.get('probe_id')
                           for s in probe['steps'])]
    if legacy_zero:
        write_json(native.parent / 'duration_compat.json', {
            'policy': 'legacy_zero_to_budgeted_100ms.v1',
            'reason': 'native adapter requires positive duration; original plan preserved',
            'original_plan_sha256': sha256(native.parent.parent / 'plan.json'),
            'actions': [{'action_id': a['action_id'], 'original_duration_ms': 0,
                         'effective_duration_ms': a['duration_ms']} for a in legacy_zero]})
    write_json(native.parent / 'action_schedule.json', {'version': VERSION, 'actions': actions})
    common = {'output_dir': native, 'duration': budget['recording_ms'] / 1000, 'fps': FPS_BY_ENGINE.get(engine, FPS),
              'timeout': max(0.1, deadline - time.monotonic())}
    sched, guards = _schedule(actions, budget, native.parent) if capture.supported(engine, plan) else (None, None)
    if engine == 'three_js':
        plan_file = native.parent / 'three_js_action_plan.json'
        write_json(plan_file, three_js_plan(actions))
        extra = {}
        if sched:
            sched['audit_protocol'] = capture.AUDIT_PROTOCOL
            write_json(native.parent / 'capture_schedule.json', sched)
            extra['capture_schedule'] = native.parent / 'capture_schedule.json'
        return client.playtest.record(**common, action_plan=plan_file, clock='realtime', warmup=0, look='off',
                                      import_build_timeout=budget['engine_startup_ms'] / 1000,
                                      launch_timeout=45.0, evidence_log_dir=native.parent, **extra)
    if engine == 'unity3d':
        from engine_adapters.unity3d._internal.transport.unity_editor import playtest_recorder_files
        added = []
        # An older adapter install left in the delivery (listed with its exact SHA in the adapter's own
        # installation.json) is harness-owned, not authored: refresh it in this eval working copy only.
        inst = project / 'Assets' / 'GameFactory3AEvaluation' / 'installation.json'
        owned = read_json(inst).get('files', {}) if inst.is_file() else {}
        for source, relative in playtest_recorder_files():      # adapter's own recorder scripts
            dest = project / relative
            if dest.exists() and sha256(dest) != sha256(source):
                if owned.get(relative.as_posix()) != sha256(dest):
                    raise HarnessError(f'adapter recorder file collides with delivered source: {relative}')
                added.append({'path': relative.as_posix(), 'replaced_stale_adapter_install': sha256(dest)})
                shutil.copyfile(source, dest)
            added.append({'path': relative.as_posix(), 'sha256': sha256(source)})
        write_json(native.parent / 'instrumentation_manifest.json', {'added_files': added})
        if sched:      # the Unity recorder picks these up from its output directory
            write_json(native / 'capture_schedule.json', sched)
            write_json(native / 'endpoint_settle_guards.json', guards)
        # Background (offscreen batch-render) capture policy, as used by the historical Unity
        # evaluator: the adapter must use its in-engine Input System driver
        # and fail rather than fall back to physical / OS keyboard input.
        previous = os.environ.get('GAMEFACTORY_UNITY_CAPTURE_POLICY')
        os.environ['GAMEFACTORY_UNITY_CAPTURE_POLICY'] = 'graphics_batch_render_v2'
        shots = _unity_asset_shot_plan(native.parents[3], native.parent)     # stage3 in-game asset photos
        if shots:
            os.environ['GAMEFACTORY_UNITY_ASSET_SHOTS_PLAN'] = str(shots)
        previous_events = os.environ.get('GAMEFACTORY_UNITY_ASSET_EVENTS')
        if _stage3(native.parents[3]):            # imported-asset events for the stage3 import checks
            os.environ['GAMEFACTORY_UNITY_ASSET_EVENTS'] = '1'
        elif os.environ.get('A3GAME_ASSET_EVENTS_OFF') == '1':
            os.environ.pop('GAMEFACTORY_UNITY_ASSET_EVENTS', None)
        from . import state_entry                     # state-conditioned take only (plan carries state_entry)
        entry_env = state_entry.prepare(plan, 'unity3d', native.parent) or {}
        os.environ.update(entry_env)
        try:
            from .unity_authored_builder import record_scene
            from engine_adapters.unity3d.playtest import unity_natural_entry
            if unity_natural_entry.context(project.parent.parent) is not None:
                entry_args = unity_natural_entry.record_binding(project, plan, native.parent)
            else:
                entry_args = {'scene': record_scene(project, plan, native.parent)}
            return client.playtest.record(**common, action_plan=actions, **entry_args,
                                          input_transport='internal')
        finally:
            if previous is None:
                os.environ.pop('GAMEFACTORY_UNITY_CAPTURE_POLICY', None)
            else:
                os.environ['GAMEFACTORY_UNITY_CAPTURE_POLICY'] = previous
            os.environ.pop('GAMEFACTORY_UNITY_ASSET_SHOTS_PLAN', None)
            if previous_events is None:
                os.environ.pop('GAMEFACTORY_UNITY_ASSET_EVENTS', None)
            else:
                os.environ['GAMEFACTORY_UNITY_ASSET_EVENTS'] = previous_events
            for k in entry_env:
                os.environ.pop(k, None)
    if engine == 'ue5':
        # Formal native path: input injected inside the engine by the pinned recorder
        # (never macOS system events). Admission (recorder overlay + build + pin) is
        # done once per run on runtime/project and reused by every take.
        admitted = admitted or _ue_admission(client, project, native.parents[3], deadline)
        map_path = '' if plan['launch_source'].endswith('.uproject') else plan['launch_source']
        shots = _ue_asset_shot_plan(native.parents[3], native.parent)
        previous = os.environ.get('A3GAME_UE_ASSET_SHOTS_PLAN')
        previous_events = os.environ.get('A3GAME_ASSET_EVENTS')
        if shots:
            os.environ['A3GAME_UE_ASSET_SHOTS_PLAN'] = str(shots)
        if _stage3(native.parents[3]):            # imported-asset events for the stage3 import checks
            os.environ['A3GAME_ASSET_EVENTS'] = '1'
        elif os.environ.get('A3GAME_ASSET_EVENTS_OFF') == '1':
            os.environ.pop('A3GAME_ASSET_EVENTS', None)
        from . import state_entry                     # state-conditioned take only (plan carries state_entry)
        entry_env = state_entry.prepare(plan, 'ue5', native.parent, project) or {}
        os.environ.update(entry_env)
        try:
            return _ue_record(client, actions, native, budget, deadline, admitted, map_path)
        finally:
            for k in entry_env:
                os.environ.pop(k, None)
            if previous is None:
                os.environ.pop('A3GAME_UE_ASSET_SHOTS_PLAN', None)
            else:
                os.environ['A3GAME_UE_ASSET_SHOTS_PLAN'] = previous
            if previous_events is None:
                os.environ.pop('A3GAME_ASSET_EVENTS', None)
            else:
                os.environ['A3GAME_ASSET_EVENTS'] = previous_events
    raise ValueError(engine)


def _glb_vertex_counts(path: Path) -> list[int]:
    """Vertex counts of the meshes (and primitives) of an original .glb, to recognise runtime-loaded copies."""
    import struct
    data = path.read_bytes()
    if data[:4] != b'glTF':
        return []
    n = struct.unpack('<I', data[12:16])[0]
    gltf = json.loads(data[20:20 + n])
    counts = set()
    for mesh in gltf.get('meshes', []):
        prims = [gltf['accessors'][p['attributes']['POSITION']]['count'] for p in mesh.get('primitives', [])
                 if 'POSITION' in p.get('attributes', {})]
        counts.update(prims)
        if prims:
            counts.add(sum(prims))
    return sorted(counts)


def _stage3(out: Path) -> bool:
    """Stage3 run (imported assets are evaluated); A3GAME_ASSET_EVENTS_OFF=1 turns the asset event watch off."""
    if os.environ.get('A3GAME_ASSET_EVENTS_OFF') == '1':
        return False
    try:
        return read_json(Path(out) / 'manifest.json').get('suite') == 'stage3'
    except (OSError, ValueError):
        return False


def _unity_asset_shot_plan(out: Path, runtime: Path) -> Path | None:
    """Unity: per imported 3D asset, its project files (editor imports) and the original glb's mesh
    vertex counts (runtime glTFast loads) for end-of-take in-game photos."""
    if os.environ.get('A3GAME_ASSET_SHOTS', '1') != '1' or read_json(out / 'manifest.json').get('suite') != 'stage3':
        return None
    from ..stage3 import import_presence
    from ..evidence import asset_views
    pres = import_presence.evaluate(out)
    assets = []
    for asset_id, a in pres['assets'].items():
        if a['kind'] not in ('3d_object', '3d_scene') or not a['present']:
            continue
        paths = [p for p in a.get('project_files', []) if p.startswith('Assets/')
                 and Path(p).suffix.lower() in ('.glb', '.gltf', '.fbx', '.obj', '.prefab', '.blend')]
        counts = sorted({c for f in asset_views.source_files(pres['game_id'], asset_id) if f.suffix.lower() == '.glb'
                         for c in _glb_vertex_counts(f)})
        if paths or counts:
            assets.append({'id': asset_id, 'kind': a['kind'], 'unity_paths': paths, 'vertex_counts': counts})
    motions = []
    for asset_id, a in pres['assets'].items():
        if a['kind'] != 'motion' or not a['present']:
            continue
        clips = [p for p in a.get('project_files', []) if p.startswith('Assets/')
                 and Path(p).suffix.lower() in ('.anim', '.fbx', '.gltf', '.glb', '.blend')]
        models = [p for p in a.get('project_files', []) if p.startswith('Assets/') and Path(p).suffix.lower()
                  in ('.prefab', '.fbx', '.gltf', '.glb', '.blend')]
        counts = sorted({c for f in asset_views.source_files(pres['game_id'], asset_id) if f.suffix.lower() == '.glb'
                         for c in _glb_vertex_counts(f)})
        if clips:
            motions.append({'id': asset_id, 'kind': 'motion', 'unity_paths': clips, 'model_paths': models,
                            'vertex_counts': counts})
    if not assets and not motions:
        return None
    path = runtime / 'asset_shots_plan.json'
    write_json(path, {'size': 640, 'assets': assets, 'motions': motions, 'motion_frames': 12})
    return path.resolve()


def _ue_asset_shot_plan(out: Path, runtime: Path) -> Path | None:
    """Packages of every imported 3D object / scene (from the import count) for end-of-take photos."""
    if os.environ.get('A3GAME_UE_ASSET_SHOTS', '1') != '1' or read_json(out / 'manifest.json').get('suite') != 'stage3':
        return None
    from ..stage3 import import_presence
    pres = import_presence.evaluate(out)
    assets = []
    for asset_id, a in pres['assets'].items():
        if a['kind'] not in ('3d_object', '3d_scene') or not a['present']:
            continue
        packages = sorted({'/Game/' + Path(p).relative_to('Content').with_suffix('').as_posix()
                           for p in a.get('engine_assets', []) if p.startswith('Content/')})
        if packages:
            assets.append({'id': asset_id, 'kind': a['kind'], 'packages': packages[:400]})
    motions = []
    for asset_id, a in pres['assets'].items():
        if a['kind'] != 'motion' or not a['present']:
            continue
        packages = sorted({'/Game/' + Path(p).relative_to('Content').with_suffix('').as_posix()
                           for p in a.get('engine_assets', []) if p.startswith('Content/')})
        if packages:
            motions.append({'id': asset_id, 'kind': 'motion', 'packages': packages[:400]})
    if not assets and not motions:
        return None
    path = runtime / 'asset_shots_plan.json'
    write_json(path, {'size': 640, 'assets': assets, 'motions': motions, 'motion_frames': 12,
                      'motion_max_seconds': 90})
    return path


def _ue_record(client, actions, native: Path, budget: dict, deadline: float, admitted: dict, map_path: str) -> dict:
    """Formal UE native take through the adapter's lower-level recorder with our own schedule.

    Same pinned recorder, in-engine input injection, receipt / clock / mapping / file /
    cleanup verification as the public client. Policy difference (user decision B): a
    frame may arrive up to UE_LATE_TOLERANCE_MS after its slot (UE never skips a late
    slot, and shared-machine load produces multi-hundred-ms hitches); every frame's real
    lateness is recorded in capture_lateness.json and its real timestamp is what the judge sees."""
    from engine_adapters.ue5.playtest import native_client, native_record
    normalized, end_ms = native_client.plan_actions(actions, {})
    recording_ms = budget['recording_ms']
    if end_ms > recording_ms:
        raise HarnessError(f'plan needs {end_ms} ms, more than the {recording_ms} ms recording')
    try:
        schedule, _ = capture.schedule(normalized, recording_ms, engine='ue5')
        mode = 'action_anchored'
    except ValueError as exc:
        fps = FPS_BY_ENGINE['ue5']
        schedule = {'version': capture.VERSION, 'interval_ms': 1000 // fps,
                    'points': [{'at_ms': i * 1000 // fps, 'capture_ids': [f'playtest/frame/{i:05d}'],
                                'criterion_ids': []} for i in range(recording_ms * fps // 1000)]}
        mode = f'dense ({exc})'
    schedule.update(warmup_ms=round(UE_WARMUP_S * 1000), tolerance_ms=UE_LATE_TOLERANCE_MS,
                    plan={'windows': [], 'endpoints': []})
    write_json(native.parent / 'capture_mode.json', {'mode': mode, 'points': len(schedule['points']),
                                                     'tolerance_ms': UE_LATE_TOLERANCE_MS})
    config, take = client._config, native / 'take'
    native_record.record(admitted, normalized, schedule, take, recording_ms, runtime_port=config.runtime_port,
                         remote_control_port=config.port, map_path=map_path,
                         ready_timeout=max(60, min(240, deadline - time.monotonic())))
    _lateness(take, schedule, native.parent)
    return {'ok': True, 'payload': {'take_dir': str(take)}}


def _lateness(take: Path, schedule: dict, runtime: Path) -> None:
    ready = read_json(take / 'play_started.json')
    offset = ready['recorder_elapsed_ms'] + schedule['warmup_ms']
    rows = [json.loads(l) for l in (take / 'frame_index.jsonl').read_text().splitlines() if l.strip()]
    late = [{'frame_id': r.get('frame_id'), 'slot_ms': r['sample_at_ms'],
             'late_ms': round(r['t_ms'] - offset - r['sample_at_ms'], 1)}
            for r in rows if r.get('sample_at_ms', -1) >= 0]
    over = [x for x in late if abs(x['late_ms']) > 350]
    write_json(runtime / 'capture_lateness.json', {
        'tolerance_ms': schedule['tolerance_ms'], 'strict_tolerance_ms': 350, 'frames': len(late),
        'frames_over_350ms': len(over), 'max_late_ms': max((x['late_ms'] for x in late), default=0),
        'over_350ms': over})


def _ue_admission(client, project: Path, out: Path, deadline: float) -> dict:
    """Admit runtime/project once (recorder overlay + build + pin); reuse while the pin holds.

    A pin that no longer verifies (e.g. the adapter recorder source changed) is archived,
    runtime/project is rebuilt from the frozen input snapshot (admission requires an
    authored-identical copy), and the candidate is admitted again."""
    from engine_adapters.ue5.playtest.native_record import verify_pin
    from ..core.prepare import IGNORE
    from ..repair import ue_compile_compat
    compatibility = ue_compile_compat.selection(out)
    folder = out / 'runtime' / 'ue_admission'
    if (folder / 'admission.json').is_file():
        admitted = read_json(folder / 'admission.json')
        if admitted.get('compile_compatibility') is not None:
            # Authenticate the historical producer before considering a new explicit plan.
            # The SHA check below renews admission while preserving that producer.
            ue_compile_compat.validate_receipt(out, admitted['compile_compatibility'])
        try:
            if admitted.get('compile_compatibility', {}).get('plan_sha256') != (compatibility['sha256'] if compatibility else None):
                raise ValueError('Explicit source-bound compile compatibility plan changed')
            verify_pin(admitted)
            ue_compile_compat.mark_admitted(out, compatibility)
            return admitted
        except (ValueError, OSError) as exc:
            stale = str(exc)
    elif folder.exists():
        stale = 'unfinished admission'
    else:
        stale = None
    if stale is not None:
        n = 1
        while (folder.parent / f'ue_admission_stale_{n:03d}').exists():
            n += 1
        archive = folder.parent / f'ue_admission_stale_{n:03d}'
        if compatibility is not None:
            ue_compile_compat.begin_rebuild(out, compatibility, archive)
        folder.rename(archive)
        write_json(archive / 'stale_reason.json', {'reason': stale})
        # Keep the previous evaluator working copy intact for the failed-take audit.
        # Never delete a project directory while renewing a recorder pin.
        if project.exists():
            n = 1
            while (project.parent / f'project_stale_{n:03d}').exists():
                n += 1
            previous = project.parent / f'project_stale_{n:03d}'
            project.rename(previous)
            write_json(previous / 'stale_reason.json', {'reason': stale,
                                                        'previous_admission': str(archive)})
        shutil.copytree(out / 'input' / 'project', project, ignore=IGNORE)
        if compatibility is not None:
            ue_compile_compat.finish_rebuild(out)
    validation_source, compatibility_receipt = ue_compile_compat.prepare(out, project, compatibility)
    result = client.playtest.admit_native(output_dir=folder, timeout=max(60, min(1800, deadline - time.monotonic())),
                                          install_recorder=True, validation_source=validation_source)
    if not result.get('ok'):
        raise HarnessError(f'UE native admission failed: {result.get("errors") or result.get("message") or result}')
    admitted = result.get('payload') or read_json(folder / 'admission.json')
    if compatibility_receipt is not None:
        admitted['compile_compatibility'] = compatibility_receipt
        write_json(folder / 'admission.json', admitted)
        ue_compile_compat.validate_receipt(out, compatibility_receipt, compatibility)
        ue_compile_compat.mark_admitted(out, compatibility)
    return admitted


def record_game_crash(runtime: Path, take: Path) -> dict | None:
    """The delivered game crashed during the take (adapter wrote game_crash.json from the engine's crash
    report): keep it as product evidence - a copy in the take record and a GAME CRASH row in the event channel."""
    src = Path(take) / 'game_crash.json'
    if not src.is_file() or (runtime / 'game_crash.json').is_file():
        return read_json(runtime / 'game_crash.json') if (runtime / 'game_crash.json').is_file() else None
    crash = read_json(src)
    write_json(runtime / 'game_crash.json', crash)
    with (runtime / 'event_trace.jsonl').open('a', encoding='utf-8') as f:
        f.write(json.dumps({'t_ms': crash['t_ms'], 'source': 'engine_crash_report', 'level': 'Fatal',
                            'message': 'GAME CRASH: ' + crash['signal'] + ' in '
                            + ' <- '.join(crash['game_frames'][:4])}, ensure_ascii=False) + '\n')
    return crash


def _take_dir(native: Path, result: dict) -> Path:
    payload = (result or {}).get('payload') or {}
    take = (result or {}).get('take_dir') or payload.get('take_dir') or payload.get('capture') \
        or (result or {}).get('capture')
    if take and Path(take).is_dir():
        return Path(take)
    for p in [native, *sorted(native.rglob('*'))]:
        if p.is_dir() and (p / 'frame_index.jsonl').is_file():
            return p
    return native


def _collect(runtime: Path, take: Path) -> dict:
    for name in CHANNELS + EXTRA_FILES:
        if (take / name).is_file():
            shutil.copyfile(take / name, runtime / name)
    for name in CHANNELS:
        (runtime / name).touch()
    if (take / 'frames').is_dir():
        shutil.copytree(take / 'frames', runtime / 'frames', dirs_exist_ok=True)
    for name in ('audio_events.jsonl', 'audio.wav', 'audio_capture.json', 'audio_environment.json',
                 'asset_events.jsonl'):   # game sound starts / stops + output, imported-asset events
        if (take / name).is_file() and not (runtime / name).is_file():
            shutil.copyfile(take / name, runtime / name)
    if (take / 'event_frame_index.jsonl').is_file():          # opt-in event-triggered frames (own index)
        shutil.copyfile(take / 'event_frame_index.jsonl', runtime / 'event_frame_index.jsonl')
        if (take / 'event_frames').is_dir():
            shutil.copytree(take / 'event_frames', runtime / 'event_frames', dirs_exist_ok=True)
    actions = [json.loads(line) for line in (runtime / 'actions.jsonl').read_text().splitlines() if line.strip()]
    frames = [line for line in (runtime / 'frame_index.jsonl').read_text().splitlines() if line.strip()]
    # inputs the game could not receive because it was loading a map or had crashed are recorded with that
    # reason (not a delivery fault of the tool)
    failed = [a.get('action_id', a.get('id')) for a in actions if (a.get('sent') is False or a.get('ok') is False)
              and not (a.get('lost_at_game_crash') or a.get('lost_during_map_travel'))]
    cleanup = {n: read_json(runtime / n) for n in ('input_view_cleanup.json', 'process_cleanup.json',
                                                   'browser_cleanup.json', 'editor_cleanup.json')
               if (runtime / n).is_file()}
    return {'actions': len(actions), 'frames': len(frames), 'failed_actions': failed,
            'channels': {n: (runtime / n).stat().st_size > 0 for n in CHANNELS}, 'cleanup': cleanup}


def _recording_budget(manifest: dict, plan: dict, runtime: Path) -> dict:
    engine, budget = manifest['engine'], manifest['budget']
    # Stage3 uses the tier budget as a ceiling, not a mandatory idle recording.
    # Keep the complete action timeline (including observation waits) and a 3s tail.
    if manifest.get('suite') == 'stage3' and engine in ('unity3d', 'ue5'):
        actions = native_actions(plan, engine)
        action_end_ms = sum(int(a['duration_ms']) for a in actions)
        recording_ms = min(budget['recording_ms'], action_end_ms + 3000)
        if action_end_ms > recording_ms:
            raise HarnessError('Stage3 action timeline exceeds the recording budget')
        budget = {**budget, 'recording_ms': recording_ms}
        write_json(runtime / 'recording_window.json', {
            'policy': 'stage3-actions-complete-plus-3s.v1',
            'action_end_ms': action_end_ms, 'tail_ms': 3000,
            'budget_ceiling_ms': manifest['budget']['recording_ms'],
            'recording_ms': recording_ms,
            'tail_limited_by_budget': recording_ms < action_end_ms + 3000,
            'plan_sha256': sha256(runtime.parent / 'plan.json'),
        })
    return budget


def _record(out: Path, manifest: dict, plan: dict, take: int = 1) -> dict:
    """Execute one take's plan; reuse a finished take instead of recording again.

    Output: ``takes/<take>/record/``. All takes open the same working copy
    ``runtime/project`` (engine import caches are reused, the original is untouched)."""
    out = Path(out)
    runtime = take_dir(out, take) / 'record'
    if (runtime / 'record_result.json').is_file():
        result = read_json(runtime / 'record_result.json')
        from ..repair import ue_compile_compat
        ue_compile_compat.validate_record(out, runtime, result)
        return result
    engine = manifest['engine']
    budget = _recording_budget(manifest, plan, runtime)
    project, native = (out / 'runtime' / 'project').resolve(), runtime / 'native'
    if native.exists() and engine == 'three_js':
        return _recover_completed_threejs(out, manifest, plan, take)
    if native.exists() and engine == 'godot':
        from ..repair import godot_completed_record_recovery
        return godot_completed_record_recovery.recover(out, manifest, plan, take)
    if native.exists() and engine == 'ue5':
        from ..repair import ue_compile_compat
        ue_compile_compat.recover_unstarted_native(out, runtime)
    if native.exists():
        raise HarnessError(f'{native} exists from an unfinished take; inspect it before recording again')
    native.mkdir(parents=True)
    # Engine preparation needs no screen: do it before taking a GUI recording slot so a long
    # Unity import or UE build never blocks other recordings.
    with engine_lock():     # A3GAME_EXCLUSIVE_ENGINE: no build / import while another lane records
        prep_deadline = time.monotonic() + max(budget['engine_call_ms'] / 1000, 1800)
        binary, admitted = None, None
        if engine == 'unity3d':
            try:
                choice = unity_editor.choose(project)
            except unity_editor.EditorUnavailable as exc:
                raise HarnessError(str(exc)) from exc
            write_json(runtime / 'unity_editor.json', choice)
            binary = choice['editor']['binary']
            try:      # legacy-input projects: isolated Input System migration (never OS input)
                metadata = _unity_input_metadata(out, manifest, choice, prep_deadline)
                if metadata is not None:
                    write_json(runtime / 'unity_input_metadata.json', metadata)
                migration = unity_input.migrate(project, out / 'runtime' / 'unity_input_migration.json')
            except (ValueError, OSError) as exc:
                raise HarnessError(f'Unity input migration failed: {exc}') from exc
            write_json(runtime / 'unity_input_migration.json', migration)
            # Injected audio observers require the selected editor's built-in module,
            # even when the author's game does not use audio. Only the eval copy is changed.
            from pipeline.eval.whitebox.unity_runtime_dependencies import prepare as prepare_observer_dependencies
            try:
                prepare_observer_dependencies(project, binary, runtime / 'observer_runtime_dependencies.json')
            except (ValueError, OSError) as exc:
                raise HarnessError(f'Unity observer dependency preparation failed: {exc}') from exc
            first_import = out / 'takes' / '1' / 'record' / 'import_result.json'
            if take == 1 or not first_import.is_file():
                _unity_import(binary, project, runtime, budget, prep_deadline)
        if engine == 'ue5':
            from ..repair import ue_compile_compat
            ue_compile_compat.recover_before_client(out, project, ue_compile_compat.selection(out))
        client = make_client(engine, project, binary)
        if engine == 'ue5':
            admitted = _ue_admission(client, project, out, prep_deadline)
            from ..repair import ue_compile_compat
            compatibility_binding = ue_compile_compat.bind_record(out, runtime, admitted)
    with gui_slot() as slot:
        started = time.monotonic()
        deadline = started + budget['engine_call_ms'] / 1000
        try:
            if engine == 'godot':
                result = _godot(client, project, take_dir(out, take) / 'plan.json', native, budget, deadline)
            else:
                result = _native(client, engine, project, plan, native, budget, deadline, admitted)
        except HarnessError:
            raise
        except Exception as exc:
            write_json(runtime / 'record_error.json', {'type': type(exc).__name__, 'error': str(exc)})
            raise HarnessError(f'adapter record failed: {type(exc).__name__}: {exc}') from exc
        elapsed = round((time.monotonic() - started) * 1000)
    write_json(runtime / 'adapter_result.json', result if isinstance(result, dict) else {'result': repr(result)})
    if isinstance(result, dict) and result.get('ok') is False:
        raise HarnessError(f'adapter record failed: {result.get("errors") or result.get("message")}; '
                           f'see {runtime / "adapter_result.json"}')
    summary = _collect(runtime, _take_dir(native, result))
    try:
        summary['game_events'] = game_events(runtime, engine, project)
    except Exception as exc:          # diagnostic channel only; never fails the take
        summary['game_events'] = f'unavailable: {type(exc).__name__}: {exc}'
    crash = record_game_crash(runtime, _take_dir(native, result))
    if crash:
        summary['game_crash'] = {k: crash[k] for k in ('signal', 't_ms', 'game_frames')}
    summary.update(version=VERSION, engine=engine, elapsed_ms=elapsed, gui_slot=str(slot), take=take, plan_sha256=sha256(take_dir(out, take) / 'plan.json'),
                   recorder=str(FRAMEWORK / 'engine_adapters' / engine))
    if summary['failed_actions']:
        raise HarnessError(f'adapter did not deliver actions {summary["failed_actions"][:5]}')
    if not summary['frames']:
        raise HarnessError('take produced no frames')
    if engine == 'ue5' and compatibility_binding is not None:
        summary['compile_compatibility'] = compatibility_binding
    write_json(runtime / 'record_result.json', summary)
    return summary


@contextmanager
def _record_lock(out: Path, take: int):
    runtime = take_dir(Path(out), take) / 'record'
    runtime.mkdir(parents=True, exist_ok=True)
    with (runtime / '.postprocess.lock').open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise HarnessError('record/postprocessing already active for this take') from exc
        yield


_UE_LINE = re.compile(r'^\[(\d{4})\.(\d\d)\.(\d\d)-(\d\d)\.(\d\d)\.(\d\d):(\d{3})\]\[\s*\d+\](Log[A-Za-z0-9_]+): (?:(Display|Warning|Error): )?(.*)$')
_UE_GAME_CATEGORIES = {'LogTemp', 'LogBlueprintUserMessages', 'LogScript'}


def game_events(runtime: Path, engine: str, project: Path) -> int:
    """Copy what the game itself logged during the take into event_trace.jsonl (when the recorder left it
    empty): UE LogTemp / Blueprint messages with take-relative time; Unity Debug.Log lines whose call
    site is the delivered project's own script (Assets/, not the evaluation recorder). Evidence only."""
    events = runtime / 'event_trace.jsonl'
    if events.is_file() and events.stat().st_size:
        return -1
    rows = []
    if engine == 'ue5':
        log = next(runtime.glob('native/**/unreal.log'), None)
        ready = next(runtime.glob('native/**/play_started.json'), None)
        origin = read_json(ready).get('wall_origin_seconds') if ready else None
        from datetime import datetime, timezone
        for line in (log.read_text(errors='replace').splitlines() if log else []):
            m = _UE_LINE.match(line)
            if not m or m.group(8) not in _UE_GAME_CATEGORIES or 'A3 ' in m.group(10)[:4] or 'A3 playtest' in m.group(10):
                continue
            y, mo, d, h, mi, se, ms = map(int, m.groups()[:7])
            wall = datetime(y, mo, d, h, mi, se, ms * 1000, tzinfo=timezone.utc).timestamp()
            if origin is not None and wall < origin:
                continue                                     # before gameplay started
            rows.append({'t_ms': round((wall - origin) * 1000) if origin else None, 'source': m.group(8),
                         'level': m.group(9) or 'Log', 'message': m.group(10)[:600]})
    elif engine == 'unity3d' and next(runtime.glob('native/**/game_events.jsonl'), None):
        # recorder-captured Debug.Log lines with take-relative times (same clock as frames)
        for line in next(runtime.glob('native/**/game_events.jsonl')).read_text(errors='replace').splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
        engine = 'unity3d_timed'
    elif engine == 'unity3d':
        log = project / 'Library' / 'GameFactory3A' / 'Editor.log'
        lines = log.read_text(errors='replace').splitlines() if log.is_file() else []
        started = next((i for i, l in enumerate(lines) if 'entering Play Mode' in l or 'GameFactory3APlayTest] take started' in l), 0)
        i = started
        while i < len(lines):
            msg = lines[i]
            j = i + 1
            while j < len(lines) and j < i + 40 and not lines[j].startswith('(Filename:'):
                j += 1
            if j < len(lines) and lines[j].startswith('(Filename: Assets/') and 'GameFactory3A' not in lines[j] \
                    and msg.strip() and not msg.startswith(('UnityEngine.', ' ', '\t', '[')):
                rows.append({'t_ms': None, 'source': lines[j][len('(Filename: '):].split(' Line:')[0],
                             'level': 'Log', 'message': msg[:600], 'order': len(rows)})
                i = j + 1
                continue
            i += 1
        shutil.copyfile(log, runtime / 'editor_take.log') if log.is_file() else None
    if rows and engine == 'unity3d':
        rows.insert(0, {'note': 'Unity game log: lines are in the order the game logged them, but carry NO '
                                'timestamps (t_ms is null). Do not infer exact timing or align them to frames by time; '
                                'use them only as evidence that the logged event happened during this take.'})
    if rows:
        events.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows[:4000]))
    return len(rows) - (1 if rows and engine == 'unity3d' else 0)


def record(out: Path, manifest: dict, plan: dict, take: int = 1) -> dict:
    """Record once, or validate and finish a supported completed native take."""
    with _record_lock(out, take):
        return _record(out, manifest, plan, take)


def _recover_completed_threejs(out: Path, manifest: dict, plan: dict, take: int) -> dict:
    """Recover only the known post-native KeyError; never invoke an engine or score."""
    out = Path(out).resolve()
    runtime = take_dir(out, take) / 'record'
    native = runtime / 'native'
    try:
        if manifest['engine'] != 'three_js':
            raise ValueError('completed-take recovery is only for Three.js')
        if (runtime / 'record_result.json').is_file():
            return read_json(runtime / 'record_result.json')
        error = read_json(runtime / 'record_error.json')
        if error != {'type': 'KeyError', 'error': "'plan'"}:
            raise ValueError('not the known Stage1 postprocessing failure')
        frozen_manifest = prepare.verify(out)
        # The playable pipeline may shorten the budget, but cannot change source identity.
        if {k: v for k, v in manifest.items() if k != 'budget'} != {
                k: v for k, v in frozen_manifest.items() if k != 'budget'}:
            raise ValueError('recovery manifest identity changed')
        if plan != read_json(take_dir(out, take) / 'plan.json'):
            raise ValueError('recovery plan differs from saved plan')
        candidates = list(native.glob('*/report.json'))
        if len(candidates) != 1:
            raise ValueError('recovery requires exactly one native take')
        folder = candidates[0].parent.resolve()
        if folder.parent != native.resolve():
            raise ValueError('native take escapes this record directory')
        report = read_json(folder / 'report.json')
        native_manifest = read_json(folder / 'manifest.json')
        parent_manifest = read_json(native / 'manifest.json')
        if parent_manifest != native_manifest:
            raise ValueError('native take selection is ambiguous')
        for key in ('status', 'output_dir', 'source_hash', 'url', 'mode', 'frames', 'fps', 'viewport'):
            if report.get(key) != native_manifest.get(key):
                raise ValueError(f'native report/manifest mismatch: {key}')
        if (report.get('status') != 'completed' or report.get('engine') != 'three_js'
                or report.get('mode') != 'gameplay' or Path(report['output_dir']).resolve() != folder
                or Path(native_manifest['report']) != Path(folder.name) / 'report.json'):
            raise ValueError('native take is not completed or identity does not match')
        duration = manifest['budget']['recording_ms'] / 1000
        import math
        wallclock = report.get('wallclock_seconds')
        if (report.get('sparse_capture') is not True or report.get('clock') != 'realtime'
                or report.get('fixed_tick') is not False or report.get('sampling_complete') is not True
                or report.get('requested_seconds') != duration
                or not isinstance(wallclock, (int, float)) or not math.isfinite(wallclock)
                or wallclock < duration or report.get('crash') or report.get('page_errors')
                or report.get('partial_plan') or report.get('unexecuted_actions')
                or report.get('excluded_actions')):
            raise ValueError('native take did not complete the requested observation/actions')
        project = (out / 'runtime' / 'project').resolve()
        launch = read_json(runtime / 'launch_selection.json')
        if Path(launch['cwd']).resolve() != project or launch['url'] != report['url']:
            raise ValueError('native launch is not bound to this project')
        if Path(report['action_plan']).resolve() != runtime / 'three_js_action_plan.json':
            raise ValueError('native action plan belongs to another take')
        # Verify all frozen project files; adapter-generated dependencies may be additional.
        for rel, digest in prepare.tree_hashes(out / 'input' / 'project').items():
            if not (project / rel).is_file() or sha256(project / rel) != digest:
                raise ValueError(f'working project changed from frozen source: {rel}')
        actions = native_actions(plan, 'three_js')
        if read_json(runtime / 'action_schedule.json') != {'version': VERSION, 'actions': actions}:
            raise ValueError('saved actions differ from Stage1 plan')
        action_plan = three_js_plan(actions)
        if read_json(runtime / 'three_js_action_plan.json') != action_plan:
            raise ValueError('browser action plan differs from Stage1 plan')
        expected_actions = action_plan['actions']
        if len(report.get('actions', [])) != len(expected_actions) or any(
                any(actual.get(k) != value for k, value in expected.items())
                for expected, actual in zip(expected_actions, report['actions'])):
            raise ValueError('native report actions do not match saved plan')
        trace = [json.loads(line) for line in (folder / 'actions.jsonl').read_text().splitlines() if line.strip()]
        expected_ids = [a['action_id'] for a in actions]
        # Pointer release is an additional native trace row, not another planned action.
        action_trace = [a for a in trace if a.get('kind') != 'release']
        releases = [a for a in trace if a.get('kind') == 'release']
        if any(a.get('action_id') not in expected_ids or a.get('sent') is not True for a in releases):
            raise ValueError('invalid native pointer release')
        executed = report.get('executed_actions', [])
        if ([a.get('action_id') for a in action_trace] != expected_ids
                or [a.get('action_id') for a in executed] != expected_ids
                or any(a.get('sent') is not True or a.get('ok') is False for a in trace)
                or any(a.get('ok') is not True for a in executed)):
            raise ValueError('native actions incomplete or failed')
        for row, actual in zip(action_trace, executed):
            # record.mjs samples elapsed() separately for report and trace end times.
            # Start/input-completed clocks are shared; retain both actual end timestamps.
            if any(row.get(k) != actual.get(k) for k in ('t_ms', 'input_completed_t_ms')):
                raise ValueError('native action trace/report clock mismatch')
        sched, _ = capture.schedule(actions, manifest['budget']['recording_ms'])
        saved = read_json(runtime / 'capture_schedule.json')
        if saved.get('audit_protocol') == capture.AUDIT_PROTOCOL:
            sched['audit_protocol'] = capture.AUDIT_PROTOCOL
        if saved != sched:
            raise ValueError('saved capture schedule differs from Stage1 plan')
        audit = capture.audit_capture(folder, saved)
        if report.get('frames') != audit['actual_screenshots']:
            raise ValueError('native report/frame index count mismatch')
        browser = read_json(folder / 'browser_cleanup.json')
        inputs = read_json(folder / 'input_view_cleanup.json')
        host = read_json(folder / 'host_process_cleanup.json')
        if (any(browser.get(k) is not True for k in ('input_cleanup', 'view_cleanup', 'browser_cleanup'))
                or inputs.get('input_cleanup') is not True
                or inputs.get('held_keys_after_release') != 0 or inputs.get('held_buttons_after_release') != 0
                or host.get('process_cleanup') is not True or host.get('server_group_alive') is not False
                or host.get('recorder', {}).get('process_cleanup') is not True
                or host.get('recorder', {}).get('group_alive') is not False
                or host.get('recorder', {}).get('returncode') != 0):
            raise ValueError('native input/view/process cleanup incomplete')
        # Immutable lineage covers all native evidence, including original pixels.
        native_hashes = {str(p.relative_to(native)): sha256(p)
                         for p in native.rglob('*') if p.is_file()}
        parents = [out / 'manifest.json', take_dir(out, take) / 'plan.json',
                   runtime / 'record_error.json', runtime / 'action_schedule.json',
                   runtime / 'three_js_action_plan.json', runtime / 'capture_schedule.json',
                   runtime / 'launch_selection.json']
        if (out / 'status.json').is_file():
            parents.append(out / 'status.json')
        parent_hashes = {str(p.relative_to(out)): sha256(p) for p in parents}
        # First collect into a temporary canonical view; reject any conflicting prior output.
        # Native evidence is read only, and no GUI slot/adapter is acquired.
        with tempfile.TemporaryDirectory(prefix='stage1-postprocess-', dir=runtime) as tmp:
            staging = Path(tmp)
            summary = _collect(staging, folder)
            shutil.copyfile(folder / 'host_process_cleanup.json', staging / 'host_process_cleanup.json')
            summary['cleanup']['host_process_cleanup.json'] = host
            for src in staging.rglob('*'):
                if src.is_file():
                    dst = runtime / src.relative_to(staging)
                    if dst.exists() and (not dst.is_file() or sha256(src) != sha256(dst)):
                        if (src.name == 'capture_schedule.json' and dst.is_file()
                                and read_json(src) == read_json(dst)):
                            continue  # recorder serializes the same schedule with different whitespace
                        raise ValueError(f'canonical output conflicts with native evidence: {dst.name}')
            if native_hashes != {str(p.relative_to(native)): sha256(p)
                                 for p in native.rglob('*') if p.is_file()}:
                raise ValueError('native evidence changed during recovery')
            if any(sha256(out / rel) != digest for rel, digest in parent_hashes.items()):
                raise ValueError('parent evidence changed during recovery')
            archive = runtime / 'postprocess_recovery' / str(time.time_ns())
            for src in parents:
                dst = archive / 'before' / src.relative_to(out)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, dst)
            receipt = {'version': 'stage1-threejs-completed-recovery.v1',
                       'native_take': str(folder), 'native_sha256': native_hashes,
                       'parent_sha256': parent_hashes, 'audit': audit,
                       'production_sha256': {str(p): sha256(p) for p in (
                           Path(__file__), Path(capture.__file__),
                           FRAMEWORK / 'engine_adapters/three_js/playtest/client.py')},
                       'native_recording_reused': True, 'new_recording': False}
            write_json(archive / 'receipt.json', receipt)
            for src in staging.rglob('*'):
                if src.is_file():
                    dst = runtime / src.relative_to(staging)
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    if not dst.exists():
                        shutil.copyfile(src, dst)
            summary.update(version=VERSION, engine='three_js', elapsed_ms=None, gui_slot=None,
                           take=take, plan_sha256=sha256(take_dir(out, take) / 'plan.json'),
                           recorder=str(FRAMEWORK / 'engine_adapters' / 'three_js'),
                           recovery_receipt=str(archive / 'receipt.json'), sparse_capture_audit=audit)
            write_json(runtime / 'record_result.json', summary)
            return summary
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        raise HarnessError(f'completed Three.js take is not recoverable: {exc}') from exc


def recover_completed_threejs(out: Path, take: int = 1) -> dict:
    """Offline formal recovery: cannot launch, replan, rerecord, or score."""
    out = Path(out)
    with _record_lock(out, take):
        return _recover_completed_threejs(out, read_json(out / 'manifest.json'),
                                         read_json(take_dir(out, take) / 'plan.json'), take)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Recover completed Stage1 Three.js native takes only')
    parser.add_argument('--recover-completed-threejs', type=Path, required=True, metavar='RUN_DIR')
    parser.add_argument('--take', type=int, default=1)
    args = parser.parse_args()
    if args.take < 1:
        parser.error('--take must be positive')
    result = recover_completed_threejs(args.recover_completed_threejs, args.take)
    print(json.dumps(result, ensure_ascii=False, indent=2))