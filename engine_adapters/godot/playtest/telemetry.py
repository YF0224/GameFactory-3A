"""Versioned native telemetry adapter; the existing bounded adapter stays pinned."""
from pathlib import Path
import json
import os
import signal
import subprocess

VERSION = 'godot-bounded-capture-telemetry.v1'
RECORDER = Path(__file__).with_name('bounded_telemetry_recorder.gd')


def record(project, output, plan, binary, timeout, *, fixture_early_exit=False):
    """Execute only the real delivered scene and allowlisted bounded player plan."""
    from .scene_entry import resolve_scene
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    scene = resolve_scene(Path(project))
    if not scene['resolved']:
        raise ValueError('Delivered Godot entry unresolved: '+scene['classification'])
    command = [str(binary), '--path', str(project), '--resolution', '960x540',
        '--position', '40,70', '--script', str(RECORDER.resolve()), '--',
        str(Path(plan).resolve()), str(output), scene['resolved']]
    # The parent observer accepts exactly config/output/scene. The fixture's
    # early-exit behavior is selected in its copied project setting instead.
    if fixture_early_exit:
        raise ValueError('Fixture mode must be author-declared in its project')
    (output/'invocation.json').write_text(json.dumps(dict(version=VERSION,
        command=command,timeout=timeout,launch_diagnostics=scene),indent=2))
    with (output/'engine.log').open('w') as log:
        process = subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        try:
            code = process.wait(timeout=timeout)
            timed_out = False
        except subprocess.TimeoutExpired:
            os.killpg(process.pid,signal.SIGTERM)
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid,signal.SIGKILL)
                process.wait()
            code = process.returncode
            timed_out = True
    try:
        os.killpg(process.pid,0)
        alive = True
    except ProcessLookupError:
        alive = False
    cleanup = dict(pid=process.pid,process_group=process.pid,returncode=code,
        process_cleanup=process.poll() is not None and not alive,
        view_cleanup=process.poll() is not None and not alive,
        group_alive_after_wait=alive,timeout=timed_out)
    (output/'process_cleanup.json').write_text(json.dumps(cleanup,indent=2))
    if alive: raise RuntimeError('Owned telemetry process group cleanup unresolved')
    return dict(exit_code=code,timeout=timed_out,cleanup=cleanup)
