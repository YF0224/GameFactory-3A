"""Run the accepted native recorder with a fresh, explicitly bound adapter import."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
import traceback


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')


def run(config, arguments, output, *, framework_root):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    acceptance = Path(config['editor_acceptance']).resolve()
    adapter = Path(config['adapter_root']).resolve()
    request = output/'request.json'
    dump(request, {'version':'unity-native-record-process.v1',
        'adapter_root':str(adapter), 'editor_acceptance':str(acceptance),
        'editor_acceptance_sha256':sha(acceptance), 'arguments':list(arguments),
        'control_root':str(Path(config['control_root']).resolve()),
        'framework_root':str(Path(framework_root).resolve()),
        'worker':str(Path(__file__).resolve()), 'worker_sha256':sha(__file__)})
    command = [sys.executable, str(Path(__file__).resolve()),
               '--request',str(request), '--request-sha256',sha(request)]
    dump(output/'launch.json', {'at':time.time(), 'parent_pid':os.getpid(),
        'command':command, 'request_sha256':sha(request),
        'reason':'Fresh interpreter prevents stale parent engine_adapters package selection'})
    with (output/'stdout.log').open('w') as stdout, (output/'stderr.log').open('w') as stderr:
        process = subprocess.Popen(command, stdout=stdout, stderr=stderr)
        dump(output/'child.json', {'pid':process.pid,'parent_pid':os.getpid(),'at':time.time()})
        previous_term = signal.getsignal(signal.SIGTERM)
        def interrupted(signum, frame):
            raise KeyboardInterrupt('Native recorder parent interrupted: '+str(signum))
        signal.signal(signal.SIGTERM, interrupted)
        try:
            code = process.wait()
        except BaseException as error:
            if process.poll() is None:
                process.terminate()
            # The native recorder handles SIGTERM and owns its input/view/Unity
            # cleanup. Retain the receipt and wait for that finally block.
            process.wait()
            dump(output/'interrupted.json', {'pid':process.pid, 'at':time.time(),
                'error':str(error), 'native_cleanup_signal':'SIGTERM',
                'returncode':process.returncode})
            raise
        finally:
            signal.signal(signal.SIGTERM, previous_term)
            dump(output/'exit.json', {'pid':process.pid, 'returncode':process.returncode,'at':time.time(),
                'stdout_sha256':sha(output/'stdout.log'), 'stderr_sha256':sha(output/'stderr.log')})
    return code


def worker(request, expected_sha):
    request = Path(request).resolve()
    if sha(request) != expected_sha:
        raise ValueError('Native recorder process request changed')
    value = json.loads(request.read_text())
    if (value['version'] != 'unity-native-record-process.v1'
            or Path(value['worker']).resolve() != Path(__file__).resolve()
            or value['worker_sha256'] != sha(__file__)):
        raise ValueError('Native recorder process worker binding changed')
    adapter = Path(value['adapter_root']).resolve()
    acceptance_path = Path(value['editor_acceptance']).resolve()
    if sha(acceptance_path) != value['editor_acceptance_sha256']:
        raise ValueError('Native recorder acceptance changed before launch')
    acceptance = json.loads(acceptance_path.read_text())
    editor = Path(acceptance['editor']).resolve()
    # Nothing from engine_adapters is imported before this selection. The
    # recorder's original client-origin guard and pin verification still apply.
    sys.path[:0] = [str(adapter), value['framework_root']]
    from engine_adapters.unity3d.playtest import background_record, native_acceptance
    for module in (background_record, native_acceptance):
        if not Path(module.__file__).resolve().is_relative_to(adapter):
            raise ValueError('Recorder process imported outside the accepted adapter: '+str(module.__file__))
    native_acceptance.verify(acceptance_path, adapter, editor)
    background_record.KNOWN_EDITOR = editor
    os.environ['GAMEFACTORY_UNITY_CONTROL_ROOT'] = value['control_root']
    dump(request.parent/'adapter_import.json', {'at':time.time(), 'pid':os.getpid(),
        'adapter_root':str(adapter), 'editor':str(editor),
        'request_sha256':sha(request),
        'modules':{module.__name__:{'path':str(Path(module.__file__).resolve()),
            'sha256':sha(module.__file__)} for module in (background_record,native_acceptance)},
        'acceptance_verified':True, 'original_recorder_guards_retained':True})
    return background_record.main(value['arguments'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request',type=Path,required=True)
    parser.add_argument('--request-sha256',required=True)
    args = parser.parse_args()
    try:
        return worker(args.request,args.request_sha256)
    except BaseException as error:
        dump(args.request.parent/'failure.json', {'at':time.time(),'error':str(error),
            'traceback':traceback.format_exc(),'classification':'HARNESS_ERROR'})
        raise


if __name__ == '__main__':
    raise SystemExit(main())
