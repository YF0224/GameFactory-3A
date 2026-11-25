"""Source-pinned UE5 native sparse capture using an existing project input relay.

Public admission uses the formal native viewport hook; legacy Dock stays supported.
No foreground/OS input or gameplay patch is used. Only the formal recorder and
its AudioMixer build dependency are overlaid in an isolated runtime copy.
"""
from pathlib import Path
import bisect
import json
import math
import re
import os
import shutil
import socket
import subprocess
import time
import uuid
from pipeline.eval.refine.common import dump, read, sha, jsonl
from .isolation import OwnedProcessTree, native_take_lease

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT/'engine_adapters/ue5/plugin/A3GamePlayable/Source/A3GamePlayable'
RECORDER_FILES = ['Public/Playtest/A3GamePlaytestRecorderSubsystem.h',
                  'Private/Playtest/A3GamePlaytestRecorderSubsystem.cpp', 'A3GamePlayable.Build.cs']


READINESS_POLICY = 'post_core_ticker_frame.v1'
CAPTURE_SURFACE_POLICY = 'slate_window.v1'
SLATE_MOUSE_POLICY = 'viewport_button.v1'
VIEWPORT_POINTER_POLICY = 'viewport_pointer.v1'
POINTER_KINDS = {'mouse_move', 'mouse_click', 'mouse_down', 'mouse_up', 'mouse_hold', 'mouse_drag', 'mouse_wheel'}
EXTRA_KEYS = {'rightshift', 'rightcontrol', 'leftalt', 'rightalt', 'backspace', 'delete', 'insert', 'home', 'end',
              'pageup', 'pagedown', 'capslock', 'comma', 'period', 'slash', 'backslash', 'semicolon', 'apostrophe',
              'minus', 'equals', 'leftbracket', 'rightbracket', 'backquote', 'mmb', 'numpadenter',
              *{f'f{i}' for i in range(1, 13)}, *{f'numpad{i}' for i in range(10)}}
SLATE_MOUSE_SOURCE = 'FSlateApplication::RoutePointer_window_local.v1'


def _validate_startup_boundary(ready):
    """Require a native post-core-ticker frame, never infer it from wall time."""
    gate = ready.get('startup_boundary')
    if not isinstance(gate, dict) or gate.get('policy') != READINESS_POLICY:
        raise RuntimeError('Native recorder lacks required startup boundary proof')
    clocks = [gate.get('armed_native_seconds'), gate.get('completed_native_seconds'),
              ready.get('native_origin_seconds')]
    if (any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in clocks)
            or not clocks[0] <= clocks[1] <= clocks[2]):
        raise RuntimeError('Native startup boundary clock order is invalid')
    frames = [gate.get('armed_frame'), gate.get('completed_frame'), gate.get('ready_frame')]
    if (any(type(v) not in (int, float) or not math.isfinite(v) or v < 0
            or v >= 2**53 or int(v) != v for v in frames)
            or not frames[0] <= frames[1] < frames[2]):
        raise RuntimeError('Native ready must follow the completed startup frame')
    if ready.get('recorder_elapsed_ms') != 0:
        raise RuntimeError('Native startup boundary changed the take-clock origin')
    return dict(gate)


def _validate_capture_surface(ready):
    """Require the pinned recorder's game-window UI path before sending input."""
    surface = ready.get('capture_surface')
    if (not isinstance(surface, dict) or surface.get('policy') != CAPTURE_SURFACE_POLICY
            or any(surface.get(k) is not True for k in
                   ('show_ui', 'slate_initialized', 'game_window_valid'))):
        raise RuntimeError('Native recorder lacks owning Slate game-window UI capture proof')
    return dict(surface)


def _validate_ui_frame_sources(destination):
    """Bind every retained native frame to the engine-owned Slate surface."""
    index = Path(destination) / 'frame_index.jsonl'
    if not index.is_file():
        raise RuntimeError('Native UI capture produced no frame index')
    rows = [row for _, row in jsonl(index)]
    if not rows:
        raise RuntimeError('Native UI capture produced no frame index')
    for row in rows:
        if (not isinstance(row, dict) or
                row.get('source') != 'FScreenshotRequest_native_slate_window' or
                row.get('capture_policy') != CAPTURE_SURFACE_POLICY):
            raise RuntimeError('Native frame is not bound to the Slate window capture surface')
    return len(rows)


def append(path, value):
    with Path(path).open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(value, ensure_ascii=False)+'\n')


def prepare(folder, config):
    from pipeline.eval.refine.session import snapshot
    folder = Path(folder)
    original = folder/'input/project'
    project = folder/'background_record/project'
    free = shutil.disk_usage(folder).free
    estimate = sum(p.stat().st_size for p in original.rglob('*') if p.is_file())
    dump(folder/'ue_disk_before_admission.json', {'free_bytes': free, 'estimate_bytes': estimate,
                                               'reserve_bytes': 8*1024**3})
    if free < estimate + 8*1024**3: raise RuntimeError('UE runtime copy needs 8GiB reserve')
    files = snapshot(original, project)
    markers = list(project.glob('*.uproject'))
    relays = list(project.glob('Source/**/DockNativeInput.cpp'))
    if len(markers) != 1 or len(relays) != 1:
        raise ValueError('No matching delivered native key relay; backend not accepted for this project')
    relay = relays[0].read_text()
    if any(s not in relay for s in ('DockInputPort=', 'UGameViewportClient', 'VC->InputKey(Args)', 'native_input.jsonl')):
        raise ValueError('Delivered input relay does not match native transport contract')
    overlays = []
    for relative in RECORDER_FILES:
        source = PLUGIN/relative
        target = project/'Plugins/A3GamePlayable/Source/A3GamePlayable'/relative
        overlays.append({'path': str(target.relative_to(project)), 'before_sha256': sha(target),
                         'formal_source': str(source), 'after_sha256': sha(source)})
        shutil.copy2(source, target)
    dump(folder/'ue_adapter_overlay.json', {'frozen_source_manifest': files, 'overlays': overlays,
         'semantic_change': 'Recorder timing/indexing only; gameplay and original delivery unchanged'})
    ue = Path(config['ue_root'])
    editor = ue/'Engine/Binaries/Mac/UnrealEditor.app/Contents/MacOS/UnrealEditor'
    # low CPU priority: a build must not starve recordings running in parallel (frames fell 26-39 s behind)
    command = ['nice', '-n', '19', str(ue/'Engine/Build/BatchFiles/Mac/Build.sh'), markers[0].stem+'Editor', 'Mac',
               'Development', str(markers[0]), '-WaitMutex', '-NoHotReload']
    from ..build.client import _serialized_build
    with _serialized_build(time.monotonic()+1200), (folder/'ue_build.log').open('w') as log:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=1200)
    dump(folder/'ue_build.json', {'command': command, 'returncode': result.returncode,
                                 'log_sha256': sha(folder/'ue_build.log')})
    if result.returncode: raise RuntimeError('HARNESS_ERROR: adapter overlay build failed; inspect ue_build.log')
    pin = {'editor': str(editor), 'editor_sha256': sha(editor),
           'recorder_sources': {str(PLUGIN/p): sha(PLUGIN/p) for p in RECORDER_FILES},
           'relay': str(relays[0]), 'relay_sha256': sha(relays[0]),
           'build_receipt_sha256': sha(folder/'ue_build.json'),
           'host_sha256': sha(__file__),
           'ownership_source': str(Path(__file__).with_name('isolation.py')),
           'ownership_sha256': sha(Path(__file__).with_name('isolation.py')),
           'runtime_sources': {str(project/rel): sha(project/rel) for rel in files
                if Path(rel).suffix.lower() in {'.cpp','.h','.cs','.ini','.uproject','.uplugin'}},
           'runtime_binaries': {str(path):sha(path) for pattern in
                ('Binaries/Mac/*.dylib','Plugins/*/Binaries/Mac/*.dylib') for path in project.glob(pattern)}}
    dump(folder/'ue_adapter_pin.json', pin)
    return {'status': 'OPENED', 'project': str(project), 'uproject': str(markers[0]),
            'scene': '', 'editor': str(editor), 'pin': str(folder/'ue_adapter_pin.json')}


def admit_existing(config, output_dir, *, timeout=1200, dry_run=False,
                   install_recorder=False, validation_source=None):
    """Build/pin a native recorder, optionally installing in an exact source copy.

    No editor is started. Installation needs an explicit independent validation
    copy; only the adapter recorder and missing module dependencies are overlaid.
    """
    from ..build.client import UEBuildClient
    from .client import _editor_binary
    from .native_admission import MODULE, DEPENDENCIES, install
    project_file = config.project_file
    if project_file is None or not project_file.is_file() or config.ue_root is None:
        raise ValueError('Existing candidate .uproject and UE root are required')
    project = project_file.parent.resolve()
    out = Path(output_dir).expanduser().resolve()
    editor = _editor_binary(config.ue_root)
    if not editor.is_file():
        raise ValueError('Configured Unreal Editor is missing')
    if install_recorder and validation_source is None:
        raise ValueError('install_recorder requires validation_source')
    if dry_run:
        return {'project': str(project), 'uproject': str(project_file), 'editor': str(editor),
                'dry_run': True, 'install_recorder': install_recorder,
                'next_action': 'source-bound adapter overlay, serialized build and source/binary pin'}
    out.mkdir(parents=True, exist_ok=False)
    free = shutil.disk_usage(project).free
    dump(out/'disk_admission.json', {'free_bytes': free, 'reserve_bytes': 8*1024**3,
         'note': 'Coordinator must also budget the candidate-specific build estimate'})
    if free < 8*1024**3:
        raise RuntimeError('Native admission requires at least 8GiB free plus the coordinator build estimate')
    binding = install(project, validation_source, out, PLUGIN, RECORDER_FILES) if install_recorder else {}
    for relative in RECORDER_FILES[:2]:
        target = project/MODULE/relative
        if not target.is_file() or sha(target) != sha(PLUGIN/relative):
            raise ValueError('Formal native recorder must be installed in the validation copy: '+str(target))
    build_text = (project/MODULE/'A3GamePlayable.Build.cs').read_text()
    if any('"'+name+'"' not in build_text for name in DEPENDENCIES):
        raise ValueError('Recorder module dependencies missing')
    relay = project/MODULE/RECORDER_FILES[1]
    result = UEBuildClient(config).project(timeout=timeout)
    dump(out/'build.json', result)
    if not result['ok']:
        raise RuntimeError('Candidate build failed; original failure preserved in '+str(out/'build.json'))
    files = [p for pattern in ('Source/**/*', 'Config/**/*', 'Plugins/*/Source/**/*', '*.uproject',
                              'Plugins/*/*.uplugin') for p in project.glob(pattern)
             if p.is_file() and p.suffix.lower() in {'.cpp','.h','.cs','.ini','.uproject','.uplugin'}]
    binaries = [p for pattern in ('Binaries/Mac/*.dylib','Plugins/*/Binaries/Mac/*.dylib')
                for p in project.glob(pattern) if p.is_file()]
    if not binaries:
        raise ValueError('No rebuilt Mac candidate/plugin binaries were found')
    ownership = Path(__file__).with_name('isolation.py')
    pin = {'editor': str(editor), 'editor_sha256': sha(editor),
           'recorder_sources': {str(PLUGIN/p): sha(PLUGIN/p) for p in RECORDER_FILES},
           'relay': str(relay), 'relay_sha256': sha(relay),
           'build_receipt_sha256': sha(out/'build.json'), 'host_sha256': sha(__file__),
           'ownership_source': str(ownership), 'ownership_sha256': sha(ownership),
           'host_sources': {str(p): sha(p) for p in Path(__file__).parent.glob('native_*.py')},
           'runtime_sources': {str(p): sha(p) for p in files},
           'runtime_binaries': {str(p): sha(p) for p in binaries}}
    dump(out/'pin.json', pin)
    admitted = {'status': 'BUILT_PENDING_NATIVE_ACCEPTANCE', 'project': str(project),
                'uproject': str(project_file), 'editor': str(editor), 'pin': str(out/'pin.json'),
                'relay_kind': 'formal_native_viewport.v1', **binding}
    dump(out/'admission.json', admitted)
    return admitted


def verify_pin(admitted):
    pin = read(admitted['pin'])
    if (sha(pin['editor']) != pin['editor_sha256'] or sha(pin['relay']) != pin['relay_sha256']
            or sha(__file__) != pin['host_sha256']):
        raise ValueError('UE native source/editor identity changed')
    if pin.get('ownership_source') and sha(pin['ownership_source']) != pin['ownership_sha256']:
        raise ValueError('UE native ownership implementation changed')
    for path, digest in {**pin['recorder_sources'], **pin.get('host_sources', {}), **pin.get('runtime_sources', {}),
                         **pin.get('runtime_binaries', {})}.items():
        if sha(path) != digest: raise ValueError('UE native recorder source changed')


def mouse_action(action):
    """Only a complete left click; no implicit pointer state or OS fallback."""
    if action.get('action') != 'mouse_click' or action.get('button') != 'left':
        raise ValueError('Native Slate supports left mouse_click only')
    for key in ('x', 'y'):
        value = action.get(key)
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError('Native Slate coordinates must be finite viewport fractions')
    duration = action.get('duration_ms')
    if type(duration) is not int or not 100 <= duration <= 6000:
        raise ValueError('Native Slate click duration must be 100..6000ms')
    if not isinstance(action.get('action_id'), str) or not action['action_id']:
        raise ValueError('Native Slate click requires action identity')


_LAST_POINTER = {'xy': None}


def pointer_events(action, seq):
    """viewport_pointer.v1 events for one mouse step (viewport fractions, in-engine only).
    An explicit mouse_move is interpolated over its duration (smooth camera turn, no single-frame jump); the
    positioning move before a click / hold / wheel is 'implicit': the recorder applies it only when the game
    shows a cursor, so it never swings a mouse-look camera."""
    kind, start, end = action['action'], action['planned_t_ms'], action['planned_end_t_ms']
    x, y = action['x'], action['y']
    button = action.get('button') or 'left'
    key = {'left': 'lmb', 'right': 'rmb', 'middle': 'mmb'}.get(button, 'lmb')
    def ev(at, phase, px, py, **extra):
        return {'at_ms': at, 'type': 'viewport_pointer', 'phase': phase, 'x': px, 'y': py,
                'button': button if phase in ('down', 'up') else '', 'wheel': extra.get('wheel', 0),
                'implicit': bool(extra.get('implicit')),
                'key': key if phase in ('down', 'up') else phase, 'action': action}
    if kind == 'mouse_move':
        fx, fy = _LAST_POINTER['xy'] or (0.5, 0.5)          # cursor starts at the viewport centre
        steps = max(1, min(40, int((end - start) // 50)))
        out = [ev(start + (end - start) * i / steps, 'move', fx + (x - fx) * i / steps, fy + (y - fy) * i / steps)
               for i in range(1, steps + 1)]
        _LAST_POINTER['xy'] = (x, y)
        for e in out:
            e['seq'] = seq; seq += 1
        return out, seq
    out = [ev(start, 'move', x, y, implicit=True)]
    if kind in ('mouse_click', 'mouse_hold'):
        out += [ev(start, 'down', x, y), ev(end, 'up', x, y)]
    elif kind == 'mouse_down':
        out.append(ev(start, 'down', x, y))
    elif kind == 'mouse_up':
        out.append(ev(start, 'up', x, y))
    elif kind == 'mouse_drag':
        tx, ty = action['to_x'], action['to_y']
        out.append(ev(start, 'down', x, y))
        steps = max(2, min(40, int((end - start) // 50)))
        for i in range(1, steps + 1):
            out.append(ev(start + (end - start) * i / steps, 'move', x + (tx - x) * i / steps, y + (ty - y) * i / steps))
        out.append(ev(end, 'up', tx, ty))
    elif kind == 'mouse_wheel':
        notches = (action.get('delta_y') or 0) / 120.0
        out.append(ev(start, 'wheel', x, y, wheel=-notches))      # plan: positive delta_y = scroll down
    _LAST_POINTER['xy'] = (out[-1]['x'], out[-1]['y'])
    for e in out:
        e['seq'] = seq; seq += 1
    return out, seq


def expand(actions):
    """Legacy key events unchanged; window-local clicks have an explicit wire type."""
    events = []
    seq = 0
    _LAST_POINTER['xy'] = None
    allowed = set('abcdefghijklmnopqrstuvwxyz0123456789') | {
        'space','enter','return','escape','leftshift','leftcontrol','tab','lmb','rmb',
        'left_arrow','right_arrow','up_arrow','down_arrow'} | EXTRA_KEYS
    for action in actions:
        if action['action'] == 'wait': continue
        start, end = action['planned_t_ms'], action['planned_end_t_ms']
        if action['action'] in POINTER_KINDS and action.get('pointer_policy') == VIEWPORT_POINTER_POLICY:
            more, seq = pointer_events(action, seq)
            events += more
            continue
        if action['action'] == 'mouse_click':
            mouse_action(action)
            if (type(start) not in (int, float) or type(end) not in (int, float)
                    or not math.isfinite(start) or not math.isfinite(end) or start < 0
                    or end - start != action['duration_ms']):
                raise ValueError('Invalid native Slate click timing')
            for phase, at in [('down', start), ('up', end)]:
                events.append({'at_ms': at, 'key': 'lmb', 'phase': phase, 'seq': seq,
                               'type': 'slate_mouse', 'x': action['x'], 'y': action['y'],
                               'button': 'left', 'action': action})
                seq += 1
            continue
        if action['action'] != 'key': raise ValueError('Unsupported native action; no desktop fallback')
        keys = action['key'].lower().split('+')
        if not keys or any(k not in allowed for k in keys):
            raise ValueError('Unsupported native key in '+str(keys))
        for phase, at in [('down', start), ('up', end)]:
            for key in keys:
                events.append({'at_ms': at, 'key': key, 'phase': phase, 'seq': seq,
                               'action': action})
                seq += 1
    return sorted(events, key=lambda e: (e['at_ms'], e['seq']))


def wire_message(event, token):
    message = {'type': event.get('type', 'key'), **{k: event[k] for k in ('key', 'phase', 'seq')}}
    if token is not None:
        message['token'] = token
    if message['type'] == 'viewport_pointer':
        if not token:
            raise ValueError('viewport pointer requires the formal token-bound relay')
        message.update({k: event[k] for k in ('x', 'y', 'button', 'wheel')})
        message.update(policy=VIEWPORT_POINTER_POLICY, action_id=event['action']['action_id'],
                       implicit=bool(event.get('implicit')))
        return message
    if message['type'] == 'slate_mouse':
        if not token:
            raise ValueError('Slate mouse requires the formal token-bound relay')
        message.update({k: event[k] for k in ('x', 'y', 'button')})
        message.update(policy=SLATE_MOUSE_POLICY, action_id=event['action']['action_id'])
    return message


def verify_mouse_receipt(receipt, event, ready, pid, token):
    expected = wire_message(event, token)
    if any(receipt.get(k) != v for k, v in expected.items()):
        raise RuntimeError('Native Slate input receipt differs from scheduled event')
    if (receipt.get('pid') != pid or receipt.get('routed') is not True
            or receipt.get('handled') is not True or receipt.get('owning_window') is not True
            or receipt.get('virtual_user') is not True or type(receipt.get('user_index')) is not int
            or receipt['user_index'] <= 0 or receipt.get('fresh_virtual_user') is not True
            or type(receipt.get('virtual_slot')) is not int or not 64 <= receipt['virtual_slot'] < 128
            or type(receipt.get('pointer_index')) is not int
            or receipt.get('pointer_index') != 0
            or receipt.get('source') != SLATE_MOUSE_SOURCE or receipt.get('hit_widget') != 'SButton'
            or receipt.get('window_id') != ready.get('slate_mouse_window_id')
            or not ready.get('slate_mouse_window_id') or ready.get('slate_mouse_policy') != SLATE_MOUSE_POLICY):
        raise RuntimeError('Native Slate input lacks owning-window/virtual-user/handled proof')
    geometry = receipt.get('geometry', {})
    for key in ('origin_x','origin_y','width','height','screen_x','screen_y'):
        value = geometry.get(key)
        if type(value) not in (int, float) or not math.isfinite(value):
            raise RuntimeError('Native Slate input geometry missing/nonfinite')
    if geometry['width'] <= 0 or geometry['height'] <= 0:
        raise RuntimeError('Native Slate input geometry empty')
    for axis, size in [('x','width'),('y','height')]:
        # Coordinates are mapped through the actual Slate viewport geometry,
        # with one physical pixel inset so fraction 1 remains inside the widget.
        pos = geometry['origin_'+axis] + event[axis] * max(0, geometry[size] - 1)
        if abs(pos - geometry['screen_'+axis]) > 0.01:
            raise RuntimeError('Native Slate input coordinate mapping differs')


_LOG_TIME = re.compile(r'^\[(\d{4})\.(\d\d)\.(\d\d)-(\d\d)\.(\d\d)\.(\d\d):(\d{3})\]')


def game_crash(destination, ready):
    """The game's own crash, from UE's crash report in unreal.log: signal, time on the take clock and the
    stack frames. None when there is no crash report, or when the crashing frames are in the evaluation
    recorder (A3GamePlayable) - those stay harness errors."""
    from datetime import datetime, timezone
    log = Path(destination) / 'unreal.log'
    if not log.exists():
        return None
    lines = log.read_text(errors='replace').splitlines()
    at = next((i for i, l in enumerate(lines) if '=== Critical error: ===' in l), None)
    if at is None:
        return None
    m = _LOG_TIME.match(lines[at])
    wall = None
    if m:
        y, mo, d, h, mi, se, ms = map(int, m.groups())
        wall = datetime(y, mo, d, h, mi, se, ms * 1000, tzinfo=timezone.utc).timestamp()
    signal = next((l.strip() for l in lines[at + 1:at + 4] if l.strip()), 'unknown')
    frames = [l.strip() for l in lines[at + 1:at + 40] if '!' in l and '0x' in l][:24]
    def fn(l):
        return l.split('!', 1)[1].split('   ')[0].strip() if '!' in l else l
    engine_mods = ('UnrealEditor-Core.', 'UnrealEditor-Engine.', 'UnrealEditor-CoreUObject.', 'UnrealEditor.',
                   'UnrealEditor!', 'UEAppDelegate', 'FCocoaGameThread',
                   'UnrealEditor-Slate', 'UnrealEditor-Renderer', 'UnrealEditor-RenderCore', 'UnrealEditor-RHI',
                   'libsystem', 'Foundation!', 'UnrealEditor-ApplicationCore', 'UnrealEditor-Launch')
    own = [fn(l) for l in frames if 'A3GamePlayable' in l]
    game = [fn(l) for l in frames if not any(e in l for e in engine_mods) and 'A3GamePlayable' not in l]
    if own and (not game or frames.index(next(l for l in frames if 'A3GamePlayable' in l)) <
                frames.index(next((l for l in frames if fn(l) in game), frames[-1]))):
        return None                                   # recorder code on top of the stack: our fault
    t_ms = (wall - ready['wall_origin_seconds']) * 1000 if (wall and 'wall_origin_seconds' in ready) else None
    return {'kind': 'game_crash', 'signal': signal, 't_ms': t_ms, 'log_line': at + 1,
            'game_frames': game[:12], 'stack': [fn(l) for l in frames[:12]],
            'note': 'the delivered game crashed during the take; frames / inputs before it are kept as evidence'}


def travel_gaps(destination, ready):
    """Wall-clock windows in which the game was loading a map during the take: from each 'LogLoad: LoadMap:'
    after recording started to the recorder's re-arm in the new world (+0.5 s)."""
    from datetime import datetime, timezone
    log = Path(destination) / 'unreal.log'
    if not log.exists():
        return []
    started, gaps, open_at = False, [], None
    for line in log.read_text(errors='replace').splitlines():
        m = _LOG_TIME.match(line)
        if not m:
            continue
        y, mo, d, h, mi, se, ms = map(int, m.groups())
        wall = datetime(y, mo, d, h, mi, se, ms * 1000, tzinfo=timezone.utc).timestamp()
        if 'A3 playtest recorder started' in line:
            started = True
        elif started and 'LogLoad: LoadMap:' in line and open_at is None:
            open_at = wall
        elif open_at is not None and ('A3 playtest recorder armed' in line or 'A3 playtest recorder continued' in line):
            gaps.append([open_at, wall + 0.5]); open_at = None
    if open_at is not None:
        gaps.append([open_at, open_at + 10.0])
    return gaps


def in_gap(ready, host_t_ms, gaps):
    if host_t_ms is None or not gaps or 'wall_origin_seconds' not in ready:
        return False
    wall = ready['wall_origin_seconds'] + host_t_ms / 1000.0
    return any(a - 0.3 <= wall <= b for a, b in gaps)


def verify_pointer_receipt(receipt, event, pid, token):
    """viewport_pointer.v1: routed in this process, same message, cursor / geometry mapping consistent."""
    expected = wire_message(event, token)
    if any(receipt.get(k) != v for k, v in expected.items() if k not in ('x', 'y', 'wheel', 'implicit')):
        raise RuntimeError('Native viewport pointer receipt differs from scheduled event')
    for k in ('x', 'y', 'wheel'):
        if abs(float(receipt.get(k, 0)) - float(expected[k])) > 1e-6:
            raise RuntimeError('Native viewport pointer receipt coordinates differ')
    if receipt.get('pid') != pid or receipt.get('routed') is not True or receipt.get('route') not in (
            'viewport_move', 'viewport_wheel', 'viewport_input_key', 'slate_button'):
        raise RuntimeError('Native viewport pointer was not routed in-engine')
    g = receipt.get('geometry') or {}
    for axis, size in (('x', 'width'), ('y', 'height')):
        pos = g.get('origin_' + axis, 0) + event[axis] * max(0, g.get(size, 0) - 1)
        if abs(pos - g.get('screen_' + axis, -1e9)) > 0.01:
            raise RuntimeError('Native viewport pointer coordinate mapping differs')


def verify_mouse_cleanup(destination, ready, pid, token):
    value = read(Path(destination) / 'native_pointer_cleanup.json')
    if (value.get('policy') != SLATE_MOUSE_POLICY or value.get('pid') != pid
            or value.get('token') != token or value.get('window_id') != ready['slate_mouse_window_id']
            or value.get('pending_before_cleanup') is not False
            or value.get('virtual_user_released') is not True):
        raise RuntimeError('Native Slate pointer cleanup incomplete or click interrupted')
    return value


def record(admitted, actions, schedule, destination, duration_ms, *, runtime_port=None,
           remote_control_port=None, map_path="", ready_timeout=240):
    verify_pin(admitted)
    project_file = Path(admitted['uproject'])
    project = Path(admitted['project'])
    if not project_file.is_absolute() or project_file.parent.resolve() != project.resolve():
        raise ValueError('Native admission project/uproject identity mismatch')
    leased_root = os.environ.get('A3GAME_REPAIR_PROJECT_ROOT')
    if leased_root:
        if project.resolve() != Path(leased_root).resolve():
            raise ValueError('Native admission must target the leased repair candidate')
        expected_port = int(os.environ['A3GAME_UE_RUNTIME_PORT'])
        if runtime_port not in (None, expected_port):
            raise ValueError('Native runtime cannot override the repair port lease')
        runtime_port = expected_port
        expected_rc = int(os.environ['A3GAME_UE_PORT'])
        if remote_control_port not in (None, expected_rc):
            raise ValueError('Native recorder cannot override the Remote Control lease')
        remote_control_port = expected_rc
    with native_take_lease(project_file, runtime_port) as port:
        return _record(admitted, actions, schedule, destination, duration_ms, port,
                       remote_control_port, map_path, ready_timeout)


def _startup_diagnostics(destination, process, owned):
    """Bounded, read-only inspection of our still identity-matched launch only."""
    from .isolation import process_table
    expected = owned.identities.get(process.pid) if owned is not None else None
    receipt = {'pid': process.pid, 'expected_identity': expected,
               'returncode': process.poll(), 'tools': {}}
    tools = {
        'sample': ['/usr/bin/sample', str(process.pid), '1', '10',
                   '-file', str(destination/'startup.sample.txt')],
        'lsof': ['/usr/sbin/lsof', '-nP', '-p', str(process.pid)],
    }
    for name, command in tools.items():
        result = {'command': command, 'timeout_seconds': 5}
        receipt['tools'][name] = result
        try:
            # Recheck launch time and full command immediately before each tool.
            # Never inspect a recycled PID or a same-name sibling candidate.
            current = process_table().get(process.pid) if expected is not None else None
            if (process.poll() is not None or current is None or
                    tuple(current[1:]) != tuple(expected)):
                result['skipped'] = 'launched process exited or identity unavailable/mismatched'
                continue
            output = destination/f'startup.{name}.log'
            result['output'] = str(output)
            with output.open('w') as handle:
                completed = subprocess.run(command, stdout=handle, stderr=subprocess.STDOUT,
                                           timeout=5, check=False)
            result['returncode'] = completed.returncode
        except (OSError, subprocess.SubprocessError) as exc:
            result['error'] = str(exc)
    dump(destination/'startup_diagnostics.json', receipt)


def _record(admitted, actions, schedule, destination, duration_ms, port,
            remote_control_port, map_path, ready_timeout):
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    dump(destination/'capture_schedule.json', schedule)
    dump(destination/'action_schedule.json', {'actions': actions})
    events = expand(actions)
    project = Path(admitted['project'])
    formal_relay = admitted.get('relay_kind') == 'formal_native_viewport.v1'
    mouse_events = [e for e in events if e.get('type') == 'slate_mouse']
    if mouse_events and not formal_relay:
        raise ValueError('Legacy delivered relay does not support Slate input')
    if any(e.get('type') == 'viewport_pointer' for e in events) and not formal_relay:
        raise ValueError('Legacy delivered relay does not support viewport pointer input')
    token = uuid.uuid4().hex if formal_relay else None
    evidence = destination if formal_relay else project/'Saved/DockEvidence'
    offsets = {name: (evidence/name).stat().st_size if (evidence/name).exists() else 0
               for name in ('native_input.jsonl', 'events.jsonl')}
    command = [admitted['editor'], admitted['uproject'], *([map_path] if map_path else []), '-game','-windowed','-ResX=1280','-ResY=720',
               '-NoSplash','-log',
               f'-A3PlaytestOutput={destination}', '-A3PlaytestFps=15',
               f'-A3PlaytestDuration={(duration_ms+schedule["warmup_ms"]+1000)/1000}',
               f'-A3CaptureSchedule={destination/"capture_schedule.json"}']
    if mouse_events:
        command += [f'-A3NativeSlateMouse={SLATE_MOUSE_POLICY}']
    if remote_control_port is not None:
        command += [f'-RemoteControlHttpServerPort={remote_control_port}',
                    f'-ExecCmds=WebControl.StartServer {remote_control_port}']
    if formal_relay:
        # UE's default Mac log directory is keyed by project *name*, so two GG
        # candidates otherwise write GG.log/GG_2.log outside their take receipts.
        # ABSLOG is parsed by GenericPlatformOutputDevices; FORCELOGFLUSH keeps
        # the startup wait point visible even when the game thread is blocked.
        # No -FORCELOGFLUSH: flushing the file after every line cost ~12 ms per line, so a game that floods its
        # own log (G008: 22k lines) stalled for minutes. UE still flushes periodically and on a crash.
        command += [f'-ABSLOG={destination/"unreal.log"}', '-unattended',
                    f'-A3NativeInputPort={port}', f'-A3NativeInputToken={token}',
                    f'-A3ReadinessGate={READINESS_POLICY}',
                    f'-A3CaptureSurface={CAPTURE_SURFACE_POLICY}']
        # Opt-in (default unchanged): background recording like Unity's runInBackground; the recorder
        # makes FApp::HasFocus() true in-process so focus-gated games do not auto-pause.
        if os.environ.get('A3GAME_UE_BACKGROUND_FOCUS') == '1':
            command += ['-A3BackgroundFocus']
        # Opt-in end-of-take asset photos (plan written by the evaluator).
        if os.environ.get('A3GAME_UE_ASSET_SHOTS_PLAN'):
            command += [f"-A3AssetShots={os.environ['A3GAME_UE_ASSET_SHOTS_PLAN']}"]
        # Opt-in state entry (state-conditioned take only).
        if '1' in (os.environ.get('A3GAME_UE_EVENT_FRAMES'), os.environ.get('A3GAME_EVENT_FRAMES')):  # opt-in event frames
            command += ['-A3EventFrames']
        # Opt-in imported-asset events (motion / audio / video / level + player trace), stage3 import checks.
        if os.environ.get('A3GAME_ASSET_EVENTS') == '1':
            command += ['-A3AssetEvents']
        if os.environ.get('A3GAME_UE_STATE_ENTRY'):
            command += [f"-A3StateEntry={os.environ['A3GAME_UE_STATE_ENTRY']}"]
    else:
        command += ['-RenderOffscreen', f'-DockInputPort={port}', f'-A3GameRuntimeInputPort={port}']
    process = None; sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    pressed, sent = set(), []
    owned = None
    def observe_children():
        if owned is not None:
            owned.observe()

    try:
        with (destination/'engine.log').open('w') as log:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
            owned = OwnedProcessTree(process, admitted['uproject'])
            dump(destination/'launch.json', {'command': command, 'pid': process.pid,
                 'port': port, 'native_input_token': token,
                 'stdout_log': str(destination/'engine.log'),
                 'native_log': str(destination/'unreal.log') if formal_relay else None})
            dump(destination/'process_ownership.json', {'identities': owned.identities})
            deadline = time.monotonic()+ready_timeout
            while not (destination/'play_started.json').exists():
                observe_children()
                if process.poll() is not None or time.monotonic()>deadline:
                    try:
                        _startup_diagnostics(destination, process, owned)
                    except Exception as exc:
                        # Diagnostics cannot prevent the ownership-checked finally cleanup.
                        dump(destination/'startup_diagnostics.json', {'error': str(exc)})
                    raise RuntimeError('UE native ready marker unavailable; inspect launch.json, '
                                       'unreal.log, engine.log and startup_diagnostics.json')
                time.sleep(.05)
            ready = json.loads((destination/'play_started.json').read_text(encoding='utf-8-sig'))
            if ready.get('pid') != process.pid or not ready.get('native_recorder'):
                raise RuntimeError('Native ready marker does not belong to the launched process')
            if formal_relay and (ready.get('native_input_token') != token or
                    ready.get('native_input_port') != port or
                    ready.get('native_input_source') != 'A3GamePlayable_native_viewport'):
                raise RuntimeError('Native ready marker input token/port/source mismatch')
            if formal_relay:
                gate = _validate_startup_boundary(ready)
                surface = _validate_capture_surface(ready)
                dump(destination/'startup_readiness.json', {
                    'policy': READINESS_POLICY, 'pid': process.pid,
                    'marker_sha256': sha(destination/'play_started.json'),
                    'startup_boundary': gate, 'capture_surface': surface,
                    'ready_timeout_seconds': ready_timeout,
                    'native_origin_seconds': ready['native_origin_seconds'],
                    'recording_ms': duration_ms, 'warmup_ms': schedule['warmup_ms'],
                    'capture_schedule_sha256': sha(destination/'capture_schedule.json')})
            if mouse_events and (ready.get('slate_mouse_policy') != SLATE_MOUSE_POLICY
                    or not ready.get('slate_mouse_window_id')):
                raise RuntimeError('Native ready marker lacks window-local Slate input capability')
            origin = time.monotonic()-(time.time()-ready['wall_origin_seconds'])
            crash = None
            for event in events:
                target = origin+(schedule['warmup_ms']+event['at_ms'])/1000
                while time.monotonic()<target:
                    observe_children()
                    if process.poll() is not None:
                        crash = game_crash(destination, ready)
                        if crash is None: raise RuntimeError('UE exited during native input')
                        break
                    time.sleep(min(.02,max(0,target-time.monotonic())))
                if crash is not None: break                 # the game crashed: nothing more can be sent
                message = wire_message(event, token)
                sock.sendto(json.dumps(message).encode(), ('127.0.0.1',port))
                if event.get('type') not in ('slate_mouse', 'viewport_pointer') or event['phase'] in ('down', 'up'):
                    if event['phase']=='down': pressed.add(event['key'])
                    elif event['phase']=='up': pressed.discard(event['key'])
                sent.append(event)
                append(destination/'host_input_requests.jsonl', {**message,
                       'host_t_ms': (time.monotonic()-origin)*1000, 'action_id': event['action']['action_id']})
            # asset shots are capped in-engine at 75 s; allow for the engine's own slow exit on top
            deadline = origin+(duration_ms+schedule['warmup_ms'])/1000+40+(180 if os.environ.get('A3GAME_UE_ASSET_SHOTS_PLAN') else 0)
            while process.poll() is None:
                observe_children()
                if time.monotonic()>deadline: raise RuntimeError('UE native exit timeout')
                time.sleep(.1)
            if crash is None and process.returncode != 0:
                crash = game_crash(destination, ready)        # crashed after the last input
            dump(destination/'runner_exit.json', {'returncode': process.returncode, 'game_crash': crash is not None})
    finally:
        # Native release is sent only to this task's port, never OS input.
        release_errors = []
        for n,key in enumerate(sorted(pressed)):
            try:
                release = {'type':'key','key':key,'phase':'up','seq':-1-n}
                if formal_relay:
                    release['token'] = token
                sock.sendto(json.dumps(release).encode(), ('127.0.0.1',port))
            except OSError as exc:
                release_errors.append(str(exc))
        sock.close()
        remaining = owned.stop() if owned is not None else []
        stopped = (process is not None and process.poll() is not None and not remaining)
        descendants = owned.identities if owned is not None else {}
        dump(destination/'cleanup.json', {'input_release_requests': sorted(pressed),
             'input_release_errors': release_errors,
             'transport':'private UDP socket closed; engine viewport/input owner exited',
             'descendants': descendants, 'remaining_descendants': remaining,
             'process_cleanup_ok': stopped,
             'view_cleanup_ok': stopped,
             'input_cleanup_ok': stopped,
             'pid': process.pid if process else None,
             'ownership_verified': owned is not None})
    if not stopped: raise RuntimeError('HARNESS_ERROR: UE native descendants remain')
    if process.returncode != 0 and crash is None: raise RuntimeError('HARNESS_ERROR: native engine nonzero exit')
    if crash is not None:
        dump(destination/'game_crash.json', crash)
    for name, offset in offsets.items():
        path = evidence/name
        if path.exists():
            with path.open('rb') as src: src.seek(offset); data = src.read()
        else: data = b''
        (destination/('raw_'+name)).write_bytes(data)
    log_text = (destination/'engine.log').read_text(errors='replace')
    if formal_relay and (destination/'unreal.log').exists():
        log_text += (destination/'unreal.log').read_text(errors='replace')
    if 'DOCK_INPUT no game viewport' in log_text or 'DOCK_INPUT unknown key' in log_text:
        raise RuntimeError('HARNESS_ERROR: native receiver did not route a valid viewport key')
    ready = json.loads((destination/'play_started.json').read_text(encoding='utf-8-sig'))
    receipt_rows = [row for _,row in jsonl(destination/'raw_native_input.jsonl')]
    if mouse_events and len({r['seq'] for r in receipt_rows}) != len(receipt_rows):
        raise RuntimeError('Duplicate native input receipt')
    receipts = {row['seq']: row for row in receipt_rows}
    gaps = travel_gaps(destination, ready)
    requests = destination/'host_input_requests.jsonl'      # absent when the take sends no input (wait-only plan)
    host_t = {row['seq']: row.get('host_t_ms') for _, row in jsonl(requests)} if requests.exists() else {}
    lost = []
    for event in sent:
        r = receipts.get(event['seq'])
        crash_lost = (not r and crash is not None and host_t.get(event['seq']) is not None
                      and host_t[event['seq']] >= crash['t_ms'] - 2000)
        if crash_lost or (not r and in_gap(ready, host_t.get(event['seq']), gaps)):
            # Sent while the game was loading a map (its own travel): the recorder's input socket is re-bound
            # by the new world, so nothing could receive it - same for a player. Recorded, not a harness fault.
            lost.append({'seq': event['seq'], 'key': event['key'], 'phase': event['phase'],
                         'action_id': event['action']['action_id'], 'host_t_ms': host_t.get(event['seq'])})
            append(destination/'actions.jsonl', {**event['action'], 'phase': event['phase'], 'key': event['key'],
                   'seq': event['seq'], 'sent': False, 'source': 'native_receiver',
                   ('lost_at_game_crash' if crash_lost else 'lost_during_map_travel'): True})
            continue
        if not r or r['key']!=event['key'] or r['phase']!=event['phase'] or r['pid']!=process.pid:
            raise RuntimeError('HARNESS_ERROR: missing/mismatched native input receipt')
        if event.get('type') == 'slate_mouse':
            verify_mouse_receipt(r, event, ready, process.pid, token)
        elif event.get('type') == 'viewport_pointer':
            verify_pointer_receipt(r, event, process.pid, token)
        elif formal_relay and (r.get('token') != token or r.get('routed') is not True or
                r.get('source') != 'UGameViewportClient::InputKey'):
            raise RuntimeError('HARNESS_ERROR: native viewport receipt token/routing/source mismatch')
        at = r['t_ms']-ready['native_origin_seconds']*1000
        append(destination/'actions.jsonl', {**event['action'], 'phase': r['phase'], 'key':r['key'],
               'seq':r['seq'], 'sent':True, 't_ms':at, 'end_t_ms':at,
               'source': 'native_receiver', 'source_t_ms':r['t_ms']})
    if lost:
        dump(destination/'input_lost_during_travel.json', {'gaps': gaps, 'lost': lost})
    pointer_cleanup = verify_mouse_cleanup(destination, ready, process.pid, token) if mouse_events else None
    (destination/'state_trace.jsonl').touch()
    (destination/'event_trace.jsonl').touch()
    clocks = [r for _,r in jsonl(destination/'clock_trace.jsonl')]
    world_times = [r['world_t_ms'] for r in clocks]
    for line, event in jsonl(destination/'raw_events.jsonl'):
        if 't_ms' not in event: continue
        n = bisect.bisect_left(world_times,event['t_ms'])
        choices = [clocks[i] for i in (n-1,n) if 0<=i<len(clocks)]
        if not choices: continue
        closest = min(choices,key=lambda c:abs(c['world_t_ms']-event['t_ms']))
        uncertainty = abs(closest['world_t_ms']-event['t_ms'])
        if uncertainty>100: continue  # Unsynchronized events remain in immutable raw channel.
        append(destination/'event_trace.jsonl', {**event,'source_t_ms':event['t_ms'],
               'source_clock':'world_time_ms','source_physical_line':line,
               't_ms':closest['t_ms'],'clock_mapping_uncertainty_ms':uncertainty})
    from pipeline.eval.stage1.sparse_evidence import audit_capture
    from pipeline.eval.stage1.action_links import build_links
    ui_frame_count = _validate_ui_frame_sources(destination) if formal_relay else None
    audit = audit_capture(destination,schedule)
    missing = audit['missing_slots_ms']
    # Context-only slots (no criterion) the recorder skipped because capture was > 1 s behind (slow game):
    # recorded in capture_skipped.jsonl, tolerated. Action / criterion slots must all be present.
    skipped = {r['at_ms'] for _, r in jsonl(destination/'capture_skipped.jsonl')} if (destination/'capture_skipped.jsonl').exists() else set()
    context_only = {p['at_ms'] for p in schedule['points'] if not p.get('criterion_ids') or (
        p.get('capture_ids') and all(c.startswith(('pre/', 'post300/', 'baseline/')) for c in p['capture_ids']))}
    audit['skipped_context_slots'] = sorted(m for m in missing if m in skipped and m in context_only)
    missing = [m for m in missing if not (m in skipped and m in context_only)]
    if crash is not None:
        # The game stalls / crashes: slots after the last frame it rendered cannot exist when the crash follows
        # within 5 s. Every slot before that last rendered frame must still be present.
        last = max((r['t_ms'] for _, r in jsonl(destination/'frame_index.jsonl')), default=0)
        if crash['t_ms'] is not None and crash['t_ms'] - last <= 5000:
            missing = [m for m in missing if m + schedule['warmup_ms'] < last]
        else:
            missing = [m for m in missing if m + schedule['warmup_ms'] < crash['t_ms'] - 500]
        audit['missing_after_game_crash'] = [m for m in audit['missing_slots_ms'] if m not in missing]
    if missing: raise RuntimeError('HARNESS_ERROR: native sparse capture slots missing')

    dump(destination/'action_frame_links.json',build_links(destination))
    dump(destination/'verification.json', {'ok': True, 'capture_audit':audit,
        'native_receipts':len(sent), 'slate_mouse_receipts': len(mouse_events),
        'native_pointer_cleanup_sha256': sha(destination/'native_pointer_cleanup.json') if mouse_events else None, 'pin_sha256':sha(admitted['pin']),
        'capture_surface_policy': CAPTURE_SURFACE_POLICY if formal_relay else None,
        'ui_surface_frame_count': ui_frame_count,
        'limitations':['Input receipt attests processing, not product success. Clock mapping uncertainty is explicit.']})
    return {'capture':str(destination),'ok':True, **({'game_crash': crash} if crash is not None else {})}
