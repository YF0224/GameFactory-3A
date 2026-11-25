"""Internal Stage1 A/B recorder; parent holds all native locks.

Reuse formal pair worker paths, routing, background guards and verification.
Only launch arguments differ by authored delivery. No workspace code is loaded.
"""
from __future__ import annotations
import contextlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import traceback


def main(request):
    # This file is launched directly from production, not from an output snapshot.
    framework = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(framework))
    from engine_adapters.unity3d.playtest import client, background_record as backend
    from engine_adapters.unity3d._internal.transport import unity_editor as transport
    from engine_adapters.unity3d.config import UnityClientConfig
    # NOTE: requires bench environment (not migrated to public repo)
    from pipeline.game_eval.whitebox_eval import multiclient
    # NOTE: requires bench environment (not migrated to public repo)
    from pipeline.game_eval.whitebox_eval.unity_native_pair_worker import RecordingPaths
    from pipeline.eval.whitebox import dual_client_unity as pair
    from pipeline.eval.whitebox.paths import read_json, write_json

    spec = read_json(Path(request))
    pair.verify_production(spec['production'])
    role = spec['role']
    if role not in ('A', 'B'):
        raise ValueError('Only independent A/B clients may record')
    project, take, receipts = map(Path, (spec['project'], spec['take'], spec['receipts']))
    receipts.mkdir(parents=True, exist_ok=False)
    take.mkdir(parents=True, exist_ok=False)
    paths = RecordingPaths(receipts, take)
    actions = multiclient.split_actions(spec['actions'], role)
    duration, warmup, fps = pair.DURATION, pair.WARMUP, pair.FPS
    backend.recording_duration(actions, duration)
    _, error = client.UnityPlaytestClient._load_actions(None, None, actions)
    if error:
        raise ValueError(error)
    expected = client.UnityPlaytestClient._timeline(actions)
    if any(e['t_ms'] > duration * 1000 for e in expected):
        raise ValueError('Input exceeds the 75 second budget')
    write_json(take / 'action_schedule.json', {'actions': actions})
    snapshot = read_json(Path(spec['snapshot']))
    stop = threading.Event()
    launches, samples, violations = [], [], []
    result, verified, error = {'ok': False}, None, None
    old_term = signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt('owned pair stop')))
    cursor = backend.CursorReader()

    def monitor():
        with (receipts / 'foreground.jsonl').open('a', buffering=1) as stream:
            while not stop.is_set():
                try:
                    row = {'unix': time.time(), 'pid': client._native_frontmost_pid(), 'os_cursor': cursor.read()}
                except Exception as exc:
                    row = {'unix': time.time(), 'error': str(exc)}
                samples.append(row)
                stream.write(json.dumps(row) + '\n')
                stop.wait(.2)

    thread = threading.Thread(target=monitor, daemon=True)
    thread.start()
    os.environ['GAMEFACTORY_UNITY_CAPTURE_POLICY'] = backend.POLICY
    os.environ['GAMEFACTORY_UNITY_IMGUI_FORWARD'] = '1'
    original_launch = transport.UnityEditorTransport.launch_editor

    def launch(self, scene_path='', extra_args=None):
        args = pair.arguments(spec['model'], role, spec['port'], spec['session'], take, Path(spec['stop']))
        proc = original_launch(self, scene_path=scene_path, extra_args=[*(extra_args or []), *args])
        started = subprocess.run(['ps', '-p', str(proc.pid), '-o', 'lstart='], capture_output=True,
                                 text=True, check=True).stdout.strip()
        write_json(receipts / 'owned_editor.json', {'pid': proc.pid, 'pgid': os.getpgid(proc.pid),
                   'started': ' '.join(started.split()), 'editor': spec['editor'], 'project': str(project),
                   'args': args, 'worker_pid': os.getpid(), 'adapter_root': str(framework)})
        return proc

    try:
        with contextlib.ExitStack() as stack:
            transport.UnityEditorTransport.launch_editor = launch
            stack.callback(setattr, transport.UnityEditorTransport, 'launch_editor', original_launch)
            stack.enter_context(backend.no_foreground_guards(client, transport, launches, violations))
            config = UnityClientConfig.resolve(project_path=project, unity_root=Path(spec['editor']))
            result = client.UnityPlaytestClient(config).record(output_dir=take, scene=spec['scene'],
                action_plan=actions, duration=duration, fps=fps, warmup=warmup,
                timeout=duration + warmup + 45, input_transport='internal')
        write_json(receipts / 'result.json', result)
    except BaseException as exc:
        error = {'type': type(exc).__name__, 'error': str(exc), 'traceback': traceback.format_exc()}
        write_json(receipts / 'error.json', error)
    finally:
        stop.set()
        thread.join(timeout=2)
        try:
            verified = backend.verify_capture(paths, result, launches, samples, violations,
                snapshot, duration, warmup, fps, False, expected)
            if error:
                verified.update(ok=False, status='HARNESS_ERROR', error=error)
            write_json(receipts / 'verification.json', verified)
        except Exception as exc:
            error = error or {'type': type(exc).__name__, 'error': str(exc)}
            write_json(receipts / 'verification_error.json', error)
        cleanup = bool(verified and all(verified['checks'].get(k) is True
                       for k in ('input_cleanup', 'view_cleanup', 'process_cleanup')))
        write_json(receipts / 'runner_exit.json', {'cleanup_verified': cleanup,
            'no_editor_launched': not launches, 'launches': launches,
            'policy_violations': violations, 'error': error, 'finished': time.time()})
        signal.signal(signal.SIGTERM, old_term)
    return 0 if verified and verified.get('ok') and not error else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1]))
