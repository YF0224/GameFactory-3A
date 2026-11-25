"""One internal-input client under its parent's exclusive native-pair lease.

Bootstrap the accepted adapter before importing the current evaluator. This
worker never takes execution locks independently or drives OS input/focus.
"""
from pathlib import Path
import contextlib
import importlib
import json
import os
import signal
import subprocess
import sys
import threading
import time
import traceback


class RecordingPaths:
    """Keep physical raw data at sessions/<role>; do not relocate bound evidence."""
    def __init__(self, receipts, take):
        self.receipts, self.take = Path(receipts), Path(take)

    def __truediv__(self, name):
        return self.take if name == 'take' else self.receipts / name


def main(request):
    spec = json.loads(Path(request).read_text())
    adapter = Path(spec['adapter_root']).resolve()
    sys.path.insert(0, str(adapter))
    from engine_adapters.unity3d.playtest import client, background_record as backend
    from engine_adapters.unity3d._internal.transport import unity_editor as transport
    from engine_adapters.unity3d.config import UnityClientConfig
    for module in (client, backend, transport):
        if not Path(module.__file__).resolve().is_relative_to(adapter):
            raise ValueError('Native worker loaded an unaccepted adapter')
    backend.verify_pin(adapter, json.loads(Path(spec['adapter_pin']).read_text()))
    # Resolve evaluator imports from production, without replacing cached adapter.
    sys.path.insert(0, spec['evaluator_root'])
    from pipeline.game_eval.whitebox_eval import multiclient
    from pipeline.game_eval.whitebox_eval.action_links import write_links
    from pipeline.game_eval.whitebox_eval.protocol import dump, sha
    role = spec['role']
    if role not in multiclient.ROLES:
        raise ValueError('Native worker has no accepted client role')
    project, take, receipts = map(Path, (spec['project'], spec['take'], spec['receipts']))
    receipts.mkdir(parents=True, exist_ok=False)
    paths = RecordingPaths(receipts, take)
    actions = multiclient.split_actions(spec['actions'], role)
    schedule = multiclient.split_schedule(spec['schedule'], role)
    duration, warmup, fps = spec['duration'], spec['warmup'], spec['fps']
    backend.recording_duration(actions, duration)
    _, error = client.UnityPlaytestClient._load_actions(None, None, actions)
    if error:
        raise ValueError(error)
    expected = client.UnityPlaytestClient._timeline(actions)
    if any(e['t_ms'] > duration*1000 for e in expected):
        raise ValueError('Expanded role input exceeds recording duration')
    dump(take/'action_schedule.json', {'version':'whitebox-action-provenance.v1','actions':actions})
    dump(take/'capture_schedule.json', schedule)
    if schedule['version'] == 'whitebox-endpoint-gameness-sparse.v2':
        from engine_adapters.unity3d.playtest.endpoint_settle import guards
        dump(take/'endpoint_settle_guards.json', guards(take/'capture_schedule.json', actions))
    from engine_adapters.unity3d.playtest.functional_observer import load_contract
    dump(take/'functional_observer_contract.json', load_contract(Path(spec['observer_contract'])))
    snapshot = json.loads(Path(spec['snapshot']).read_text())
    stop = threading.Event()
    launches, samples, violations = [], [], []
    result, verified, error = {'ok':False}, None, None
    old_term = signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt('owned pair stop')))
    cursor = backend.CursorReader()
    def monitor():
        with (receipts/'foreground.jsonl').open('a', buffering=1) as stream:
            while not stop.is_set():
                try:
                    row = {'unix':time.time(), 'pid':client._native_frontmost_pid(), 'os_cursor':cursor.read()}
                except Exception as exc:
                    row = {'unix':time.time(), 'error':str(exc)}
                samples.append(row)
                stream.write(json.dumps(row)+'\n')
                stop.wait(.2)
    thread = threading.Thread(target=monitor, daemon=True)
    thread.start()
    os.environ['GAMEFACTORY_UNITY_CAPTURE_POLICY'] = backend.POLICY
    os.environ['GAMEFACTORY_UNITY_IMGUI_FORWARD'] = '1'
    original_launch = transport.UnityEditorTransport.launch_editor
    def launch(self, scene_path='', extra_args=None):
        # This list comes only from the source-bound reviewed normal TCP contract.
        args = ['--ww-client',role,'--ww-port',str(spec['port']),
                '--ww-address','127.0.0.1','--ww-session',spec['session'],
                '--ww-evidence',str(take/'author_evidence')]
        proc = original_launch(self, scene_path=scene_path, extra_args=[*(extra_args or []), *args])
        started=subprocess.run(['ps','-p',str(proc.pid),'-o','lstart='],capture_output=True,text=True,check=True).stdout.strip()
        dump(receipts/'owned_editor.json', {'pid':proc.pid, 'pgid':os.getpgid(proc.pid),
            'started':' '.join(started.split()),'editor':str(spec['editor']),'project':str(project),
            'args':args, 'worker_pid':os.getpid(), 'adapter_root':str(adapter)})
        return proc
    try:
        with contextlib.ExitStack() as stack:
            transport.UnityEditorTransport.launch_editor = launch
            stack.callback(setattr, transport.UnityEditorTransport, 'launch_editor', original_launch)
            stack.enter_context(backend.no_foreground_guards(client, transport, launches, violations))
            config = UnityClientConfig.resolve(project_path=project, unity_root=Path(spec['editor']))
            result = client.UnityPlaytestClient(config).record(output_dir=take,
                scene=spec['scene'], action_plan=actions, duration=duration, fps=fps,
                warmup=warmup, timeout=duration+warmup+30, input_transport='internal')
        dump(receipts/'result.json', result)
        write_links(take)
    except BaseException as exc:
        error = {'type':type(exc).__name__, 'error':str(exc), 'traceback':traceback.format_exc()}
        dump(receipts/'error.json', error)
    finally:
        stop.set()
        thread.join(timeout=2)
        try:
            verified = backend.verify_capture(paths, result, launches, samples, violations,
                snapshot, duration, warmup, fps, False, expected)
            if error:
                verified.update(ok=False, status='HARNESS_ERROR', error=error)
            dump(receipts/'verification.json', verified)
        except Exception as exc:
            error = error or {'type':type(exc).__name__, 'error':str(exc), 'traceback':traceback.format_exc()}
            dump(receipts/'verification_error.json', error)
        cleanup = bool(verified and all(verified['checks'].get(k) is True
            for k in ('input_cleanup','view_cleanup','process_cleanup')))
        dump(receipts/'runner_exit.json', {'cleanup_verified':cleanup,
            'no_editor_launched':not launches,'launches':launches,
            'policy_violations':violations,'error':error,'finished':time.time()})
        signal.signal(signal.SIGTERM, old_term)
    return 0 if verified and verified['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1]))
