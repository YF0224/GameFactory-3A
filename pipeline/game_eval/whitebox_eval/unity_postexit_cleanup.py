"""Supplemental post-exit resource release; failed recording remains invalid.

Never changes original cleanup booleans, sends host input, or signals a process.
EPERM is not treated as absence. A complete independent census and ESRCH probes
are required while holding every native resource lock.
"""
from pathlib import Path
from contextlib import ExitStack
import fcntl
import os
import re
import time
from . import batch
from .protocol import sha, dump

VERSION = 'unity-failed-record-postexit-resource-release.v1'


def assert_absent(pids, pgids, project, snapshot):
    binding = re.compile(r'(?:^| )-projectPath '+re.escape(str(Path(project).resolve()))+r'(?= -|$)')
    if any(row['pid'] in pids or row['pgid'] in pgids or binding.search(row['command']) for row in snapshot.values()):
        raise ValueError('Owned PID/group/project remains in complete process census')
    probes=[]
    for kind, identifiers, probe in [('pid', pids, os.kill), ('pgid', pgids, os.killpg)]:
        for ident in sorted(set(identifiers)):
            if type(ident) is not int or ident <= 1:
                raise ValueError('Explicit isolated positive process identity required')
            try:
                probe(ident, 0)
            except ProcessLookupError:
                probes.append(dict(kind=kind, identity=ident, result='ESRCH'))
            else:
                raise ValueError('Owned process or group still exists')
    return probes


def release(workspace, identity, configuration, repair):
    from engine_adapters.unity3d.playtest.background_record import control_paths, check_original
    from engine_adapters.unity3d.playtest.client import _process_snapshot
    from . import unity_m_admission as admission
    workspace=Path(workspace).resolve();root=workspace/'runs'/identity
    if root.resolve().parent != workspace/'runs':
        raise ValueError('Exact workspace run required')
    config=batch.read(Path(configuration))
    if config != batch.read(root/'unity_m_native_dispatch/configuration.json'):
        raise ValueError('Exact failed dispatch configuration required')
    descriptor=Path(repair).resolve();value=batch.read(descriptor)
    if (value.get('version') != VERSION or value.get('identity') != identity
            or value.get('production') != admission.production()):
        raise ValueError('Exact post-exit release producer descriptor required')
    admission._check_regression(value['regression'])
    capture=root/'background_record';control=Path(config['control_root']);marker=control/'background_record_cleanup_block.json'
    files=['runner_exit.json','background_session.json','source_snapshot.json','verification.json',
           'take/editor_cleanup.json','take/background_input_settings.json']
    if set(value['bindings']) != {str(capture/n) for n in files}|{str(marker)}:
        raise ValueError('Complete original failed cleanup bindings required')
    for p,d in value['bindings'].items():
        if sha(Path(p)) != d:
            raise ValueError('Original failed cleanup evidence changed')
    with ExitStack() as stack:
        for path in [workspace/'.unity_m_native.lock',control/'whitebox_production_queue.lock',*control_paths(control)]:
            handle=stack.enter_context(path.open('a+'));fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        block=batch.read(marker);session=batch.read(capture/'background_session.json')
        exited=batch.read(capture/'runner_exit.json');cleanup=batch.read(capture/'take/editor_cleanup.json')
        verify=batch.read(capture/'verification.json');settings=batch.read(capture/'take/background_input_settings.json')
        if (block.get('output') != str(capture) or block.get('runner_pid') != session['pid']
                or block.get('launches') != exited['launches'] or len(exited['launches']) != 1
                or exited['launches'][0]['pid'] != cleanup['pid']
                or exited['launches'][0]['pgid'] != cleanup['owned_pgid']):
            raise ValueError('Stop marker and original isolated ownership must agree')
        if (session['capture_policy'] != 'graphics_batch_render_v2' or session['activation'] != 'forbidden'
                or session['os_input'] != 'forbidden' or exited['policy_violations']
                or settings['scope'] != 'owned Editor process only; no settings asset saved'):
            raise ValueError('Enforced zero host input and process-local settings required')
        if (cleanup.get('process_exit_verified') is not True or cleanup.get('returncode') != 0
                or cleanup.get('errors') != ['[Errno 1] Operation not permitted']
                or cleanup.get('detached_groups') != [] or cleanup.get('ok') is not False):
            raise ValueError('Exact diagnosed post-exit partial cleanup failure required')
        checks=verify['checks']
        if (verify['status'] != 'HARNESS_ERROR' or set(k for k,v in checks.items() if v is not True)
                != {'adapter_success','process_cleanup'} or verify['input_cleanup'].get('ok') is not True):
            raise ValueError('Original input/view teardown and all non-process checks required')
        if not check_original(batch.read(capture/'source_snapshot.json'))['ok']:
            raise ValueError('Original author source changed')
        pids={session['pid'],cleanup['pid']};pgids={cleanup['owned_pgid']}
        project=Path(session['project']);snapshots=[];probes=[]
        for _ in range(2):
            snapshot=_process_snapshot()
            if not snapshot:raise ValueError('Complete process census unavailable')
            probes.append(assert_absent(pids,pgids,project,snapshot));snapshots.append(snapshot)
        preferences={}
        prefs=Path.home()/'Library/Preferences/Unity'
        if not prefs.is_dir():raise ValueError('Unity preference root unavailable')
        for p in sorted(prefs.rglob('*')):
            if p.is_file():
                if b'GameFactory owned capture' in p.read_bytes():
                    raise ValueError('Owned capture view persisted')
                preferences[str(p)]=sha(p)
        if not preferences:raise ValueError('Unity preference census empty')
        result=dict(version=VERSION,identity=identity,failed_capture=str(capture),checked_unix=time.time(),
            descriptor=dict(path=str(descriptor),sha256=sha(descriptor)),original_bindings=value['bindings'],
            seven_resource_locks_held=True,process_snapshots=snapshots,absence_probes=probes,
            original_input_view_teardown_verified=True,persisted_preferences_sha256=preferences,
            resource_release_verified=True,capture_accepted=False,original_cleanup_receipts_rewritten=False,
            scoring_authorized=False,signals_sent=0,host_input_sent=0,
            resolution='Isolated Editor and group independently absent; process-local input/view resources are gone. Original failed capture remains invalid.')
        dest=root/'unity_m_native_dispatch/cleanup_recovery'/str(time.time_ns());dest.mkdir(parents=True)
        (dest/marker.name).write_bytes(marker.read_bytes());dump(dest/'resource_release.json',result)
        if sha(marker) != value['bindings'][str(marker)]:
            raise ValueError('Stop marker changed concurrently')
        # This is formal reconciled release under all locks, not deletion of a lease/claim.
        marker.unlink()
        return dest/'resource_release.json',result
