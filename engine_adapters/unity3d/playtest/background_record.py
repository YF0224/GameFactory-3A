#!/usr/bin/env python3
"""Pinned, zero-activation Unity recording. Does not judge or publish scores.

selftest uses the accepted fixture. record always snapshots its input project.
Both commands use internal Unity input and graphics batch mode, never OS input.
"""
from __future__ import annotations
import argparse
from collections import Counter
import contextlib
import ctypes
import fcntl
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import signal
import sys
import threading
import time
import traceback

ROOT = Path(__file__).resolve().parents[4]
READINESS = ROOT / 'workspaces/native_harness_20261024/validation/unity_serial_readiness_20261025_225743'
POLICY = 'graphics_batch_render_v2'
# Native acceptance may bind this to its verified editor for the current run.
KNOWN_EDITOR = None


def control_paths(control_root):
    control_root = Path(control_root)
    return [control_root/('serial_'+str(i)+'.lock') for i in range(3)] + [
        Path('/tmp/gamefactory-sol-whitebox-gui.lock'), Path('/tmp/gamefactory-native-playtest-gui.lock')]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def rows(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8-sig').splitlines() if line.strip()]


def migration_root():
    configured = os.environ.get('GAMEFACTORY_UNITY_CONTROL_ROOT')
    if configured:
        path = Path(configured).resolve()
        if not path.is_dir(): raise ValueError('Explicit Unity control root is absent')
        return path
    path = Path((READINESS / 'active_unity_migration_path.txt').read_text().strip()).resolve()
    if not path.is_dir() or not path.is_relative_to(READINESS):
        raise ValueError('Invalid migration pointer; inspect active_unity_migration_path.txt')
    return path


def verify_pin(candidate, pin):
    if pin.get('schema') != 'unity-background-adapter-pin.v1' or pin.get('policy') != POLICY:
        raise ValueError('Unsupported background adapter pin')
    for relative, expected in pin['files'].items():
        path = (candidate / relative).resolve()
        if not path.is_relative_to(candidate.resolve()) or not path.is_file() or sha(path) != expected:
            raise ValueError('Adapter differs from accepted version; revalidate before updating pin: ' + relative)


def load_actions(path, duration):
    obj = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    actions = obj.get('actions') if isinstance(obj, dict) else obj
    if not isinstance(actions, list) or not actions or not all(isinstance(a, dict) for a in actions):
        raise ValueError('Actions must be a nonempty list or {"actions": [...]} in native recorder format')
    elapsed = 0
    for action in actions:
        value = action.get('duration_ms', 100)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0 or int(value) != value:
            raise ValueError('duration_ms must be a positive integer')
        elapsed += action_duration_ms(action)
    if elapsed > duration * 1000:
        raise ValueError(f'Action timeline {elapsed}ms exceeds real recording budget {duration * 1000}ms')
    return actions


def action_duration_ms(action):
    value = action.get('duration_ms', 100)
    return value if action.get('action') in {'wait', 'mouse_move', 'mouse_down', 'mouse_up', 'mouse_click'} else max(value, 100)


def recording_duration(actions, budget):
    duration = sum(action_duration_ms(action) for action in actions) / 1000
    if not 0 < duration <= budget:
        raise ValueError('Action timeline must be positive and within recording budget')
    return duration


def snapshot_project(source, destination, migration, *, fixture=False):
    # Reuse the tested source walker and its documented generated-artifact policy.
    from engine_adapters.unity3d.playtest import project_snapshot as module
    excluded = []
    paths = list(module.snapshot_files(source, excluded))
    manifest = {}
    import shutil
    for path in paths:
        relative = path.relative_to(source)
        if fixture and relative.parts[:2] == ('Assets', 'GameFactory3AEvaluation'):
            continue
        if fixture and str(relative) == 'Assets/GameFactory3AEvaluation.meta':
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        before = sha(path)
        shutil.copy2(path, target)
        if sha(target) != before:
            raise ValueError('Source changed while copying: ' + str(path))
        manifest[str(relative)] = before
    from .input_axis_serialization import normalize_snapshot
    normalization = normalize_snapshot(source, destination)
    package_relocation = module.relocate_missing_input_package(destination)
    return {'policy': module.SNAPSHOT_POLICY, 'source': str(source), 'files_sha256': manifest, 'excluded_artifacts': excluded, 'fixture_injection_excluded': fixture, 'input_axis_normalization': normalization, 'package_path_relocation': package_relocation}


def check_original(snapshot):
    source = Path(snapshot['source'])
    changed = [name for name, expected in snapshot['files_sha256'].items() if not (source / name).is_file() or sha(source / name) != expected]
    return {'ok': not changed, 'changed_or_missing_files': changed}


class CursorReader:
    """Read-only; deliberately contains no cursor-post/warp/activation API."""
    class Point(ctypes.Structure):
        _fields_ = [('x', ctypes.c_double), ('y', ctypes.c_double)]

    def __init__(self):
        self.q = ctypes.CDLL('/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics')
        self.cf = ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
        self.q.CGEventCreate.argtypes = [ctypes.c_void_p]
        self.q.CGEventCreate.restype = ctypes.c_void_p
        self.q.CGEventGetLocation.argtypes = [ctypes.c_void_p]
        self.q.CGEventGetLocation.restype = self.Point
        self.cf.CFRelease.argtypes = [ctypes.c_void_p]

    def read(self):
        event = self.q.CGEventCreate(None)
        if not event:
            raise RuntimeError('Cannot read OS cursor')
        try:
            point = self.q.CGEventGetLocation(event)
            return [point.x, point.y]
        finally:
            self.cf.CFRelease(event)


@contextlib.contextmanager
def no_foreground_guards(client, transport, launches, violations):
    saved = []
    def patch(owner, name, replacement):
        saved.append((owner, name, owner.__dict__[name]))
        setattr(owner, name, replacement)
    def forbidden(*args, **kwargs):
        violations.append({'kind': 'forbidden_os_input_or_activation', 'at': time.time()})
        raise RuntimeError('NO_FOREGROUND_POLICY: OS input and activation are forbidden')
    for name in ['_focus_process', '_recover_gameview_focus', '_key_event', '_mouse_event', '_osascript']:
        patch(client, name, forbidden)
    patch(client.UnityPlaytestClient, '_drive_events', forbidden)
    patch(client.UnityPlaytestClient, '_check_input_driver', forbidden)
    original_launch = transport.UnityEditorTransport.launch_editor
    def launch(self, scene_path='', extra_args=None):
        args = [str(value) for value in (extra_args or [])]
        if '-nographics' in args:
            raise RuntimeError('Graphics device is required for real recording')
        launch_record = {'pid': None, 'pgid': None, 'launch_attempted': True}
        launches.append(launch_record)
        process = original_launch(self, scene_path=scene_path, extra_args=['-batchmode', *[value for value in args if value != '-batchmode']])
        launch_record['pid'] = process.pid
        try:
            launch_record['pgid'] = os.getpgid(process.pid)
        except ProcessLookupError:
            pass
        return process
    patch(transport.UnityEditorTransport, 'launch_editor', launch)
    # Fail promptly on an explicit recorder failure before readiness. Never focus.
    def wait_marker(marker, process, payload, timeout, *, require_os_focus=False):
        if require_os_focus:
            forbidden()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if marker.is_file():
                return True
            report = marker.parent / '_editor_report.json'
            if report.is_file():
                try:
                    obj = json.loads(report.read_text())
                    if obj.get('ok') is False:
                        payload['error'] = {'phase': 'before_input_ready', 'recorder_report': obj}
                        return False
                except (OSError, ValueError):
                    pass
            if process.poll() is not None:
                payload['editor_exit_code'] = process.returncode
                payload['error'] = client._editor_failure_context(marker, payload, process.returncode)
                return False
            time.sleep(.1)
        payload['error'] = client._editor_failure_context(marker, payload, None)
        return False
    patch(client.UnityPlaytestClient, '_wait_for_marker', staticmethod(wait_marker))
    try:
        yield
    finally:
        for owner, name, value in reversed(saved):
            setattr(owner, name, value)


def delivery_check(expected, actual):
    def identity(row):
        return (row.get('index'), row.get('action'), row.get('phase'), row.get('key') or '', row.get('button') or '')
    requested = Counter(identity(row) for row in expected)
    delivered = Counter(identity(row) for row in actual if row.get('sent') is True and not row.get('cleanup_release'))
    return requested == delivered and all(row.get('sent') is True for row in actual)


def verify_capture(output, result, launches, samples, violations, snapshot, duration, warmup, fps, fixture, expected_events):
    take = output / 'take'
    cleanup_path, inputs_path = take / 'editor_cleanup.json', take / 'background_input_cleanup.json'
    cleanup = json.loads(cleanup_path.read_text()) if cleanup_path.exists() else {}
    inputs = json.loads(inputs_path.read_text()) if inputs_path.exists() else {}
    view_path = take / 'background_view_cleanup.json'
    view = json.loads(view_path.read_text()) if view_path.exists() else {}
    frames = rows(take / 'frame_index.jsonl') if (take / 'frame_index.jsonl').exists() else []
    events = rows(take / 'actions.jsonl') if (take / 'actions.jsonl').exists() else []
    times = [row['t_ms'] for row in frames]
    max_gap = max((b-a for a,b in zip(times,times[1:])), default=None)
    owned_pids = {row['pid'] for row in launches}
    for row in cleanup.get('detached_groups', []):
        for key in ('pid', 'pgid'):
            if isinstance(row.get(key), int):
                owned_pids.add(row[key])
    original = check_original(snapshot)
    checks = {
        'adapter_success': result.get('ok') is True,
        'no_forbidden_host_calls': not violations,
        'foreground_samples_available': bool(samples) and all(isinstance(row.get('pid'), int) and row['pid'] > 0 for row in samples),
        'no_owned_foreground_sample': bool(samples) and all(row.get('pid') not in owned_pids for row in samples),
        'continuous_frames': bool(times) and times[0] <= (warmup + 2) * 1000 and times[-1] >= duration * 1000 and len(frames) >= duration * fps * .9 and max_gap is not None and max_gap <= 1000 and all(b > a for a,b in zip(times, times[1:])),
        'real_frames_present': bool(frames) and all((take / row['path']).is_file() for row in frames),
        'video_present': (take / 'video.mp4').is_file() and (take / 'video.mp4').stat().st_size > 0,
        'all_events_delivered': delivery_check(expected_events, events),
        'input_cleanup': all(inputs.get(key) is True for key in ['ok', 'keys_and_buttons_released', 'virtual_devices_removed', 'settings_restored', 'muted_devices_restored', 'input_filter_removed']),
        'view_cleanup': all(view.get(key) is True for key in ['ok', 'custom_size_removed', 'selected_size_restored', 'target_size_restored', 'render_target_released']),
        'process_cleanup': all(cleanup.get(key) is True for key in ['ok', 'process_exit_verified', 'group_exit_verified', 'detached_exit_verified']),
        'original_unchanged': original['ok'],
        'launches_in_verified_group': bool(launches) and all(row['pid'] == cleanup.get('pid') for row in launches),
    }
    if (take / 'capture_schedule.json').is_file():
        from pipeline.eval.stage1.sparse_evidence import audit_capture
        sparse_audit = audit_capture(take)
        checks.pop('continuous_frames')
        checks.pop('video_present')
        checks['sparse_slots_and_sequences'] = not sparse_audit['missing_slots_ms'] and all(
            row['complete'] and row['continuous'] for row in sparse_audit['windows'].values())
        dump(output / 'sparse_capture_audit.json', sparse_audit)
    if (take / 'functional_observer_contract.json').is_file():
        from .functional_observer import verify
        observer = verify(take)
        dump(output / 'functional_observer_verification.json', observer)
        checks['functional_observer_available'] = observer['ok']
    if (take/'runtime_initializer_entry.json').is_file():
        from . import runtime_initializer
        try:
            runtime_initializer.verify_recording(take)
            checks['natural_runtime_entry'] = True
        except (OSError,ValueError,KeyError,TypeError):
            checks['natural_runtime_entry'] = False
    fixture_state = None
    if fixture:
        checks['fixture_trace_present'] = (take / 'state_trace.jsonl').is_file() and bool(rows(take / 'state_trace.jsonl'))
    if fixture and (take / 'state_trace.jsonl').exists():
        state_rows = rows(take / 'state_trace.jsonl')
        fixture_state = state_rows[-1]['state']
        m, c, n = (fixture_state[key] for key in ['MigrationProbe', 'InputProbe', 'NoiseProbe'])
        cycles = 6 if duration == 180 else 1
        segments = []; previous = None
        for row in state_rows:
            combat = row['state'].get('InputProbe')
            if not combat: continue
            if previous is None or combat['shots'] < previous['shots'] or combat['scene'] != previous['scene']:
                segments.append({'shots': 0, 'hits': 0})
            for key in ['shots','hits']: segments[-1][key] = max(segments[-1][key], combat[key])
            previous = combat
        checks.update({
            'fixture_gui': m['imguiClicks'] == cycles*2 and m['uguiClicks'] == cycles*2,
            'fixture_keyboard': m['keyDown'] == cycles and m['keyUp'] == cycles and not m['currentD'],
            'fixture_current_devices': m['mouseCurrent'] == 'GameFactoryBackgroundMouse' and m['keyboardCurrent'] == 'GameFactoryBackgroundKeyboard',
            'fixture_combat': sum(s['shots'] for s in segments) == cycles*4 and sum(s['hits'] for s in segments) == cycles*4 and not c['fireHeld'],
            'fixture_scene_resets': len(segments) == (3 if cycles == 6 else 1),
            'fixture_noise_filtered': n['queuedFrames'] >= 1000 and inputs.get('filtered_keyboard_events',0) >= n['queuedFrames'] and inputs.get('filtered_pointer_events',0) >= n['queuedFrames'],
        })
    return {'schema': 'unity-background-record-verification.v1', 'status': 'CAPTURE_VERIFIED' if all(checks.values()) else 'HARNESS_ERROR', 'ok': all(checks.values()), 'checks': checks, 'fixture_only': fixture, 'benchmark_score': None, 'frames': len(frames), 'first_ms': times[0] if times else None, 'last_ms': times[-1] if times else None, 'max_gap_ms': max_gap, 'foreground_sample_count': len(samples), 'foreground_pids': sorted({row.get('pid') for row in samples if row.get('pid') is not None}), 'input_cleanup': inputs, 'process_cleanup': cleanup, 'original_check': original, 'fixture_state': fixture_state, 'limits': ['Foreground sampled every 200ms; no continuous OS activation trace.', 'Real-project action delivery is not proof of gameplay consumption or success; inspect video/state and run evidence/judge separately.', 'No formal score or COMPLETE status is published by this tool.']}


def parser():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='command', required=True)
    for name in ['selftest', 'record']:
        cmd = sub.add_parser(name)
        cmd.add_argument('--output', type=Path, required=True, help='New directory; existing paths are refused')
        cmd.add_argument('--adapter-root', type=Path, help='Defaults to the pinned migration candidate')
        cmd.add_argument('--unity', type=Path, help='Editor executable; defaults to environment configuration, then discovery')
        cmd.add_argument('--duration', type=float, default=20 if name == 'selftest' else None, required=name == 'record', choices=[20,180] if name == 'selftest' else None, help='Selftest length; record budget ceiling (record ends when all action durations finish)')
        cmd.add_argument('--actions', type=Path, required=name == 'record', help='Native recorder actions JSON, not sol_plan.json')
        if name == 'record':
            cmd.add_argument('--project', type=Path, required=True)
            cmd.add_argument('--scene', required=True, help='Explicit Assets/... scene from this project')
        cmd.add_argument('--warmup', type=float, default=1)
        cmd.add_argument('--fps', type=int, default=10)
        cmd.add_argument('--capture-schedule', type=Path)
        cmd.add_argument('--observer-contract', type=Path, help='Source-backed functional observer availability, not gameplay success')
        cmd.add_argument('--runtime-entry', type=Path, help='Strict frozen native admission for an authored AfterSceneLoad initializer')
        cmd.add_argument('--adapter-pin', type=Path)
        cmd.add_argument('--control-root', type=Path)
        cmd.add_argument('--fixture-project', type=Path)
    return p


def main(argv=None, *, validation_pin=None):
    args = parser().parse_args(argv)
    if sys.platform != 'darwin': raise ValueError('This pinned zero-activation backend is accepted only on macOS')
    if not math.isfinite(args.duration) or not 0 < args.duration <= 1800: raise ValueError('duration must be in (0,1800] seconds')
    if not math.isfinite(args.warmup) or not 0 <= args.warmup <= 10 or not 1 <= args.fps <= 60: raise ValueError('Invalid warmup/fps')
    if args.command == 'selftest' and (args.fps != 10 or args.warmup != 1): raise ValueError('Pinned fixture uses fps=10, warmup=1')
    if args.control_root:
        os.environ['GAMEFACTORY_UNITY_CONTROL_ROOT'] = str(args.control_root.resolve())
    migration = migration_root(); candidate = (args.adapter_root or migration / 'candidate/GameFactory-3A').resolve()
    pin = json.loads((args.adapter_pin or migration / 'background_adapter_pin.json').read_text()) if validation_pin is None else validation_pin
    if validation_pin is not None and (pin.get('accepted') is not False or not pin.get('validation_scope')):
        raise ValueError('Candidate acceptance requires an explicitly unaccepted manifest and validation scope')
    verify_pin(candidate, pin)
    sys.path.insert(0, str(ROOT / 'GameFactory-3A'))
    from engine_adapters.unity3d.editor_paths import resolve_editor
    args.unity = resolve_editor(explicit=args.unity or KNOWN_EDITOR)
    if KNOWN_EDITOR is not None and args.unity.resolve() != Path(KNOWN_EDITOR).resolve():
        raise ValueError('Editor differs from the one bound by native acceptance: ' + str(KNOWN_EDITOR))
    if KNOWN_EDITOR is None and validation_pin is None:
        acceptance = os.environ.get('A3GAME_UNITY_ACCEPTANCE')
        if acceptance:
            from engine_adapters.unity3d.playtest.native_acceptance import verify
            verify(Path(acceptance), candidate, args.unity)
        else:
            # Legacy pins were qualified only for this version. Discovery changes
            # installation paths, never the native-acceptance version boundary.
            from engine_adapters.unity3d.editor_paths import version_of
            if version_of(args.unity) != '2022.3.62f3c1':
                raise ValueError('Discovered editor lacks native acceptance for this pinned recorder; '
                                 'run explicit native acceptance and set A3GAME_UNITY_ACCEPTANCE')
    fixture = args.command == 'selftest'
    source = ((args.fixture_project or migration / 'long_fixture_graphics_batch_imgui_v15b_long') if fixture else args.project).resolve()
    scene = 'Assets/Fixture.unity' if fixture else args.scene
    if not (source / 'Assets').is_dir(): raise ValueError('Input project has no Assets directory')
    if args.runtime_entry:
        if fixture:
            raise ValueError('Runtime entry acceptance uses an explicit independently admitted runtime fixture')
        from . import runtime_initializer
        runtime_binding = runtime_initializer.load(args.runtime_entry, source)
        if scene != runtime_binding['source']:
            raise ValueError('Runtime entry must use its exact admitted source identifier')
    else:
        scene_path = (source / scene).resolve()
        if not scene_path.is_relative_to(source / 'Assets') or scene_path.suffix != '.unity' or not scene_path.is_file(): raise ValueError('Scene must be an existing project Assets/*.unity file')
    settings = source / 'ProjectSettings/ProjectSettings.asset'
    if not settings.is_file() or not re.search(r'(?m)^\s*(?:m_ActiveInputHandler|activeInputHandler):\s*1\s*$', settings.read_text()): raise ValueError('Requires reviewed InputSystem-only project; migrate legacy input in an isolated version first')
    action_file = (args.actions.resolve() if args.actions else migration / ('long_fixture_actions_graphics_batch_imgui_v15b_long.json' if args.duration == 180 else 'long_fixture_actions_graphics_batch_imgui_v14_filter.json')) if fixture else args.actions.resolve()
    actions = load_actions(action_file, args.duration)
    requested_budget = args.duration
    if not fixture:
        args.duration = recording_duration(actions, requested_budget)
    output = args.output.expanduser().resolve()
    if output.exists() or output.is_relative_to(source): raise ValueError('Output must be new and outside the source project')
    sys.path[:0] = [str(candidate), str(ROOT / 'GameFactory-3A')]
    from engine_adapters.unity3d.playtest import client
    from engine_adapters.unity3d.config import UnityClientConfig
    from engine_adapters.unity3d._internal.transport import unity_editor as transport
    from pipeline.eval.stage1 import runtime
    if not Path(client.__file__).resolve().is_relative_to(candidate): raise ValueError('Wrong adapter import path')
    _, action_error = client.UnityPlaytestClient._load_actions(None, None, actions)
    if action_error: raise ValueError(action_error)
    expected_events = client.UnityPlaytestClient._timeline(actions)
    if any(event['t_ms'] > args.duration * 1000 for event in expected_events): raise ValueError('Expanded input events exceed recording duration')
    block = migration / 'background_record_cleanup_block.json'
    stop = threading.Event(); samples = []; violations = []; launches = []; locks = []; thread = None
    result = {'ok': False}; snapshot = None; error = None; verified = None
    output.mkdir(parents=True)
    print('OUTPUT ' + str(output), flush=True)
    print('FRAMES ' + str(output / 'take/frames'), flush=True)
    def interrupted(signum, frame): raise KeyboardInterrupt('received signal ' + str(signum))
    original_term = signal.signal(signal.SIGTERM, interrupted)
    try:
        for path in control_paths(migration):
            h = path.open('a+')
            try: fcntl.flock(h, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BaseException: h.close(); raise
            locks.append(h)
        if block.exists(): raise RuntimeError('Previous cleanup unconfirmed; inspect ' + str(block))
        occupied = runtime.active_gui_engines()
        if occupied: raise RuntimeError('GUI capture occupied: ' + json.dumps(occupied))
        snapshot = snapshot_project(source, output / 'project', migration, fixture=fixture)
        dump(output / 'source_snapshot.json', snapshot)
        dump(output / 'actions_input.json', {'source': str(action_file), 'source_sha256': sha(action_file), 'actions': actions})
        dump(output / 'background_session.json', {'schema': 'unity-background-record-session.v1', 'started': time.time(), 'pid': os.getpid(), 'source': str(source), 'project': str(output / 'project'), 'adapter_root': str(candidate), 'adapter_pin': pin, 'capture_policy': POLICY, 'input_transport': 'internal', 'activation': 'forbidden', 'os_input': 'forbidden', 'duration': args.duration, 'recording_budget_seconds': requested_budget, 'stop_policy': 'fixture_duration' if fixture else 'action_timeline_complete', 'warmup': args.warmup, 'fps': args.fps, 'unity': str(args.unity), 'scene': scene})
        cursor = CursorReader()
        def monitor():
            with (output / 'foreground.jsonl').open('a', buffering=1) as h:
                while not stop.is_set():
                    try: row = {'unix': time.time(), 'pid': client._native_frontmost_pid(), 'os_cursor': cursor.read()}
                    except Exception as exc: row = {'unix': time.time(), 'error': str(exc)}
                    samples.append(row); h.write(json.dumps(row) + '\n'); stop.wait(.2)
        thread = threading.Thread(target=monitor, daemon=True); thread.start()
        # A hard interruption before finally leaves a persistent stop marker.
        dump(block, {'output': str(output), 'runner_pid': os.getpid(), 'status': 'CLEANUP_PENDING'})
        os.environ['GAMEFACTORY_UNITY_CAPTURE_POLICY'] = POLICY
        os.environ['GAMEFACTORY_UNITY_IMGUI_FORWARD'] = '1'
        with no_foreground_guards(client, transport, launches, violations):
            config = UnityClientConfig.resolve(project_path=output / 'project', unity_root=args.unity)
            if all(action.get('action_id') for action in actions):
                dump(output / 'take/action_schedule.json', {'version':'whitebox-action-provenance.v1','actions':actions})
            if args.capture_schedule:
                schedule = json.loads(args.capture_schedule.read_text())
                if schedule.get('version') not in {'whitebox-endpoint-gameness-sparse.v1','whitebox-endpoint-gameness-sparse.v2'} or schedule.get('warmup_ms') != args.warmup * 1000:
                    raise ValueError('sparse schedule version/warmup mismatch')
                dump(output / 'take/capture_schedule.json', schedule)
                if schedule['version'] == 'whitebox-endpoint-gameness-sparse.v2':
                    from .endpoint_settle import guards
                    dump(output / 'take/endpoint_settle_guards.json',guards(output/'take/capture_schedule.json',actions))
            if args.observer_contract:
                from .functional_observer import load_contract
                dump(output / 'take/functional_observer_contract.json', load_contract(args.observer_contract))
            runtime_kwargs = {}
            if args.runtime_entry:
                from . import runtime_initializer
                runtime_initializer.load(args.runtime_entry, output/'project')
                dump(output/'take/runtime_initializer_entry.json', runtime_binding)
                runtime_kwargs['runtime_entry'] = output/'take/runtime_initializer_entry.json'
            result = client.UnityPlaytestClient(config).record(output_dir=output / 'take', scene=scene, action_plan=actions, duration=args.duration, fps=args.fps, warmup=args.warmup, timeout=args.duration + args.warmup + 30, input_transport='internal', **runtime_kwargs)
        if all(action.get('action_id') for action in actions):
            from pipeline.eval.stage1.action_links import write_links
            links=write_links(output / 'take')
            dump(output / 'action_provenance_verification.json', {
                'version':links['version'], 'actions':len(links['links']),
                'recorded_actions':sum(link['timing_source']=='recorded_session_time' for link in links['links']),
                'gameplay_verified':False})
        dump(output / 'result.json', result)
    except BaseException as exc:
        error = {'type': type(exc).__name__, 'error': str(exc), 'traceback': traceback.format_exc()}
        dump(output / 'error.json', error)
    finally:
        stop.set()
        if thread: thread.join(timeout=2)
        if snapshot:
            try:
                verified = verify_capture(output, result, launches, samples, violations, snapshot, args.duration, args.warmup, args.fps, fixture, expected_events)
                if error: verified['ok'] = False; verified['status'] = 'HARNESS_ERROR'; verified['error'] = error
                dump(output / 'verification.json', verified)
            except Exception as exc:
                error = error or {'type': type(exc).__name__, 'error': str(exc)}
                dump(output / 'verification_error.json', error)
        cleanup_ok = bool(verified and all(verified['checks'].get(name) is True for name in ['process_cleanup', 'input_cleanup', 'view_cleanup']))
        if block.exists():
            block_record = json.loads(block.read_text())
            if block_record.get('output') == str(output):
                if cleanup_ok or not launches: block.unlink()
                else: dump(block, {'output': str(output), 'runner_pid': os.getpid(), 'launches': launches, 'status': 'CLEANUP_UNCONFIRMED', 'error': error})
        dump(output / 'runner_exit.json', {'cleanup_verified': cleanup_ok, 'no_editor_launched': not launches, 'launches': launches, 'policy_violations': violations, 'error': error, 'finished': time.time()})
        signal.signal(signal.SIGTERM, original_term)
        for h in reversed(locks): fcntl.flock(h, fcntl.LOCK_UN); h.close()
    ok = bool(verified and verified['ok'])
    print(('CAPTURE_VERIFIED ' if ok else 'HARNESS_ERROR ') + str(output / 'verification.json'), flush=True)
    if error: print(error['error'], file=sys.stderr)
    return 0 if ok else 1


if __name__ == '__main__':
    try: raise SystemExit(main())
    except (ValueError, OSError, RuntimeError) as exc:
        print('PREFLIGHT_ERROR: ' + str(exc), file=sys.stderr); raise SystemExit(2)
