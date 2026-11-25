"""Independent cleanup qualification for the exact native pre-input refusal.

Never changes a failed capture into recording evidence. Original failed cleanup
and stop marker are preserved; only process-isolated, never-started input/view
resources are qualified for proceeding to another case.
"""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import time

ERROR = 'background experiment requires native InputSystem internal transport; no physical fallback'
RECORDER_SHA = '74f8f981cd0740e4d0d48e02dfababc2b287d0d07adbb948e28ebc50243e8f5a'
DRIVER_SHA = '2ed89bf1b1a2ae433c9c537d83a5f64befb0a05cf506c76c1f41e650e0e89e99'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def qualify(capture):
    capture = Path(capture).resolve()
    take, project = capture/'take', capture/'project'
    read = lambda p:json.loads(p.read_text())
    if not (take/'_editor_report.json').exists():
        log=project/'Library/GameFactory3A/Editor.log'
        if log.is_file() and 'An error occurred while resolving packages:' in log.read_text(errors='replace'):
            return qualify_package_failure(capture)
        return qualify_compile_failure(capture)
    report = read(take/'_editor_report.json')
    session = read(capture/'background_session.json')
    process = read(take/'editor_cleanup.json')
    runner = read(capture/'runner_exit.json')
    log = project/'Library/GameFactory3A/Editor.log'
    recorder = project/'Assets/GameFactory3AEvaluation/Editor/GameFactory3APlayTestRecorder.cs'
    driver = recorder.with_name('GameFactory3AInputDriver.cs')
    if (report.get('ok') is not False or report.get('errors') != [ERROR]
            or report.get('frames') != 0 or report.get('state_snapshots') != 0
            or report.get('actual_runtime_seconds') != 0 or report.get('recorded_seconds') != 0
            or session.get('capture_policy') != 'graphics_batch_render_v2'
            or session.get('input_transport') != 'internal' or session.get('activation') != 'forbidden'
            or session.get('os_input') != 'forbidden' or runner.get('policy_violations') != []
            or sha(recorder) != RECORDER_SHA or sha(driver) != DRIVER_SHA):
        raise ValueError('Pre-input cleanup qualification does not match reviewed native refusal')
    text = log.read_text(errors='replace')
    if ERROR not in text or 'internal input driver activated (' in text or 'internal driver init failed:' in text:
        raise ValueError('Input initialization may have started')
    for name in ['play_started.json', 'actions.jsonl', 'frame_index.jsonl',
                 'background_input_settings.json', 'background_input_cleanup.json', 'background_view_cleanup.json']:
        if (take/name).exists():
            raise ValueError('Unexpected input/view/readiness artifact: '+name)
    if any((take/'frames').iterdir()):
        raise ValueError('Capture has real frames; ordinary cleanup is required')
    if (not all(process.get(k) is True for k in ['ok','process_exit_verified','group_exit_verified','detached_exit_verified'])
            or process.get('errors') or process.get('detached_groups')
            or runner.get('launches') != [{'pid':process['pid'],'pgid':process['owned_pgid'],'launch_attempted':True}]
            or '-projectPath' not in process.get('command', [])
            or str(project) not in process['command']):
        raise ValueError('Owned native process exit is not proven')
    for number in {process['pid'], process['owned_pgid']}:
        try:os.kill(number, 0)
        except ProcessLookupError:pass
        else:raise ValueError('Owned Editor PID still exists')
    try:os.killpg(process['owned_pgid'], 0)
    except ProcessLookupError:pass
    else:raise ValueError('Owned Editor process group still exists')
    active = subprocess.check_output(['ps','-axo','pid=,args='], text=True)
    if any(str(project) in line and ('/MacOS/Tuanjie' in line or '/MacOS/Unity' in line) for line in active.splitlines()):
        raise ValueError('Owned project Editor remains active')
    paths = [take/'_editor_report.json', capture/'background_session.json', take/'editor_cleanup.json',
             capture/'runner_exit.json', recorder, driver, log]
    return {'version':'whitebox-preinput-cleanup.v1','capture':str(capture),'qualified':True,
            'input_cleanup':True,'view_cleanup':True,'process_cleanup':True,
            'reason':'Reviewed exact refusal precedes InputDriver.Begin and first graphics-batch render; no host input/activation; owned process/group exited.',
            'capture_qualified':False,'bindings':{str(p.relative_to(capture)):sha(p) for p in paths}}


def release(config, capture):
    """Preserve the stop marker before releasing only this qualified dead capture."""
    from .protocol import dump
    receipt = qualify(capture)
    control = Path(config['control_root'])
    marker = control/'background_record_cleanup_block.json'
    if marker.exists():
        value = json.loads(marker.read_text())
        if Path(value['output']).resolve() != Path(capture).resolve():
            raise ValueError('Cleanup marker belongs to another capture')
        archive = control/'cleanup_recovery_history'/f'{time.time_ns()}.json'
        dump(archive, {'original_marker':value,'original_marker_sha256':sha(marker),'qualification':receipt})
        marker.unlink()
        receipt['marker_archive'] = str(archive)
    dump(Path(capture)/'preinput_cleanup_qualification.json', receipt)
    return receipt


def qualify_compile_failure(capture):
    """Exact compiler-abort proof: no executeMethod, input, view or frames began."""
    import re
    capture=Path(capture).resolve();take=capture/'take';project=capture/'project'
    read=lambda p:json.loads(p.read_text())
    session=read(capture/'background_session.json');process=read(take/'editor_cleanup.json')
    runner=read(capture/'runner_exit.json')
    log=project/'Library/GameFactory3A/Editor.log'
    recorder=project/'Assets/GameFactory3AEvaluation/Editor/GameFactory3APlayTestRecorder.cs'
    driver=recorder.with_name('GameFactory3AInputDriver.cs')
    if (session.get('capture_policy')!='graphics_batch_render_v2' or session.get('input_transport')!='internal'
            or session.get('activation')!='forbidden' or session.get('os_input')!='forbidden'
            or runner.get('policy_violations')!=[] or sha(recorder)!=RECORDER_SHA or sha(driver)!=DRIVER_SHA):
        raise ValueError('Compiler cleanup does not match accepted isolated recorder')
    text=log.read_text(errors='replace')
    if ('Scripts have compiler errors.' not in text or not re.search(r'Assets/[^\n]+\.cs\(\d+,\d+\): error CS\d+:',text)
            or 'internal input driver activated (' in text or 'internal driver init failed:' in text):
        raise ValueError('No proven pre-execution compiler abort')
    for name in ['_editor_report.json','play_started.json','actions.jsonl','frame_index.jsonl','state_trace.jsonl','event_trace.jsonl',
                 'background_input_settings.json','background_input_cleanup.json','background_view_cleanup.json']:
        if (take/name).exists():raise ValueError('Unexpected execution artifact: '+name)
    if (take/'frames').exists() and any((take/'frames').iterdir()):raise ValueError('Real frames require ordinary cleanup')
    if (not all(process.get(k) is True for k in ['ok','process_exit_verified','group_exit_verified','detached_exit_verified'])
            or process.get('errors') or process.get('detached_groups') or process.get('returncode')!=1
            or runner.get('launches')!=[{'pid':process['pid'],'pgid':process['owned_pgid'],'launch_attempted':True}]
            or '-projectPath' not in process.get('command',[]) or str(project) not in process['command']
            or '-executeMethod' not in process['command'] or 'GameFactory3APlayTestRecorder.Enter' not in process['command']):
        raise ValueError('Compiler-aborted owned process exit is not proven')
    for number in {process['pid'],process['owned_pgid']}:
        try:os.kill(number,0)
        except ProcessLookupError:pass
        else:raise ValueError('Owned compiler-aborted Editor PID exists')
    try:os.killpg(process['owned_pgid'],0)
    except ProcessLookupError:pass
    else:raise ValueError('Owned compiler-aborted Editor group exists')
    active=subprocess.check_output(['ps','-axo','pid=,args='],text=True)
    if any(str(project) in line and ('/MacOS/Tuanjie' in line or '/MacOS/Unity' in line) for line in active.splitlines()):
        raise ValueError('Owned compiler-aborted project Editor active')
    paths=[capture/'background_session.json',take/'editor_cleanup.json',capture/'runner_exit.json',recorder,driver,log]
    return {'version':'whitebox-precompile-cleanup.v1','capture':str(capture),'qualified':True,
        'input_cleanup':True,'view_cleanup':True,'process_cleanup':True,'capture_qualified':False,
        'reason':'Native compiler abort before recorder executeMethod; no input/view/readiness artifacts; accepted observer SHA; owned process and group verified exited.',
        'bindings':{str(p.relative_to(capture)):sha(p) for p in paths}}


def qualify_package_failure(capture):
    """Prove isolated Editor package abort occurred before recorder startup."""
    capture=Path(capture).resolve();take=capture/'take';project=capture/'project'
    read=lambda p:json.loads(p.read_text())
    session=read(capture/'background_session.json');process=read(take/'editor_cleanup.json')
    runner=read(capture/'runner_exit.json');log=project/'Library/GameFactory3A/Editor.log'
    text=log.read_text(errors='strict')
    import os
    cache = Path(os.environ.get('A3GAME_UNITY_PACKAGE_CACHE', Path.home() / 'Library/Unity/cache/packages'))
    expected = f'com.unity.inputsystem: The file [{cache}/packages.unity.cn/com.unity.inputsystem@1.14.0/package.json] cannot be found'
    if (expected not in text or 'An error occurred while resolving packages:' not in text
            or '[Package Manager] Server::Kill -- Server was shutdown' not in text
            or 'internal input driver activated (' in text or 'internal driver init failed:' in text
            or session.get('capture_policy')!='graphics_batch_render_v2' or session.get('input_transport')!='internal'
            or session.get('activation')!='forbidden' or session.get('os_input')!='forbidden' or runner.get('policy_violations')!=[]):
        raise ValueError('Not the isolated pre-execution missing-package abort')
    for name in ('_editor_report.json','play_started.json','actions.jsonl','frame_index.jsonl','state_trace.jsonl','event_trace.jsonl',
                 'background_input_settings.json','background_input_cleanup.json','background_view_cleanup.json'):
        if (take/name).exists():raise ValueError('Input/view may have started: '+name)
    if (take/'frames').exists() and any((take/'frames').iterdir()):raise ValueError('Real frames need ordinary cleanup')
    if (not all(process.get(k) is True for k in ('ok','process_exit_verified','group_exit_verified','detached_exit_verified'))
            or process.get('errors') or process.get('detached_groups') or process.get('returncode')!=1
            or runner.get('launches')!=[dict(pid=process['pid'],pgid=process['owned_pgid'],launch_attempted=True)]
            or str(project) not in process.get('command',[]) or '-batchmode' not in process['command']
            or '-executeMethod' not in process['command'] or 'GameFactory3APlayTestRecorder.Enter' not in process['command']):
        raise ValueError('Package-aborted owned process exit is not proven')
    for number in {process['pid'],process['owned_pgid']}:
        try:os.kill(number,0)
        except ProcessLookupError:pass
        else:raise ValueError('Owned Editor PID still exists')
    try:os.killpg(process['owned_pgid'],0)
    except ProcessLookupError:pass
    else:raise ValueError('Owned Editor group still exists')
    active=subprocess.check_output(['ps','-axo','pid=,args='],text=True)
    if any(str(project) in line and ('/MacOS/Tuanjie' in line or '/MacOS/Unity' in line) for line in active.splitlines()):
        raise ValueError('Owned project Editor remains active')
    paths=[capture/'background_session.json',take/'editor_cleanup.json',capture/'runner_exit.json',log]
    return dict(version='whitebox-prepackage-cleanup.v1',capture=str(capture),qualified=True,
        input_cleanup=True,view_cleanup=True,process_cleanup=True,capture_qualified=False,
        reason='Missing package abort before executeMethod; no input/view/readiness artifacts; owned Editor/group exited.',
        bindings={str(p.relative_to(capture)):sha(p) for p in paths})
