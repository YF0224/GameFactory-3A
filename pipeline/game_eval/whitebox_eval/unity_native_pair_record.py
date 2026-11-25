"""Real authored host plus two independently clocked internal-input recorders.

The caller owns the coordinator, five execution locks, publication lock and
cleanup marker. The accepted adapter is unchanged. No OS input, focus calls,
author automation or gameplay method invocation are used. No scores published.
"""
from pathlib import Path
import json
import os
import shutil
import signal
import shlex
import socket
import subprocess
import sys
import time
from . import batch, multiclient, unity_disk_guard as disk
from . import unity_native_pair_admission as admission
from .protocol import dump, sha

VERSION = 'unity-source-bound-native-pair-record.v1'


def validate_request(candidate, source, actions, schedule, duration, warmup, fps):
    admitted, binding = admission.validate_source(candidate)
    source = Path(source).resolve()
    if not source.is_dir() or any(sha(source/name) != digest for name,digest in binding.items()):
        raise ValueError('Frozen planning source differs from reviewed authored TCP delivery')
    if sha(source/admission.SCENE) != sha(admitted/admission.SCENE):
        raise ValueError('Frozen planning scene differs from native admission')
    if (not isinstance(duration,(int,float)) or isinstance(duration,bool) or not 0 < duration <= 1800
            or type(warmup) not in (int,float) or not 0 <= warmup <= 10
            or type(fps) is not int or not 1 <= fps <= 60):
        raise ValueError('Invalid native pair timing')
    if not actions or any(not isinstance(a,dict) or not a.get('action_id') for a in actions):
        raise ValueError('Native pair route requires preserved action identities')
    for role in multiclient.ROLES:
        if not any(a.get('action') != 'wait' and a.get('client_role') in (role,'BOTH') for a in actions):
            raise ValueError('Each real native client requires planned physical input')
    if any(a.get('client_role') not in ('A','B','BOTH') and not (
            a.get('action_id') == 'system/startup' and a.get('probe_id') == 'system'
            and a.get('action') == 'wait' and 'client_role' not in a) for a in actions):
        raise ValueError('Native pair action has unknown role')
    if schedule.get('warmup_ms') != warmup*1000:
        raise ValueError('Native pair warmup/schedule differs')
    multiclient.validate_schedule(schedule)
    return binding


def verified_host_reuse(candidate, receipt):
    """Reuse only the exact stopped observation-only host from real pair admission."""
    receipt=Path(receipt)
    saved=batch.read(receipt)
    binding=batch.read(receipt.parent/'source_binding.json')
    copy=batch.read(receipt.parent/'HOST/source_copy.json')
    if (saved.get('schema') != admission.VERSION or not saved.get('real_pair_connected')
            or saved.get('source_unchanged') is not True
            or not all(saved.get('cleanup',{}).get(k) is True for k in ('input_cleanup','view_cleanup','process_cleanup'))
            or binding.get('candidate') != candidate):
        raise ValueError('Native host reuse lacks matched source/connection/cleanup proof')
    project=Path(copy['project']).resolve()
    if project != (receipt.parent/'HOST/project').resolve() or copy['source'] != candidate['selected_project']:
        raise ValueError('Native host reuse points outside its owned admission')
    current=batch.hashes(project)
    metadata={'Packages/manifest.json','Packages/packages-lock.json','ProjectSettings/ProjectVersion.txt',
              'ProjectSettings/ShaderGraphSettings.asset','ProjectSettings/UnityConnectSettings.asset'}
    if any(current.get(n) != d for n,d in copy['files'].items() if n not in metadata):
        raise ValueError('Reused host authored source changed')
    helper='Assets/GameFactory3AEvaluation/Editor/WhiteboxNativePairOpen.cs'
    if current.get(helper) != sha(Path(__file__).with_name('resources')/'WhiteboxNativePairOpen.cs'):
        raise ValueError('Reused host helper changed')
    for name in current.keys()-copy['files'].keys():
        if (name == helper or name.endswith('.meta') or name in metadata
                or name.startswith('ProjectSettings/') or name.startswith('UserSettings/')):
            continue
        raise ValueError('Unexpected reused host source: '+name)
    return project, {'receipt':str(receipt),'receipt_sha256':sha(receipt),
                     'source_copy_sha256':sha(receipt.parent/'HOST/source_copy.json'),
                     'source_binding_sha256':sha(receipt.parent/'source_binding.json'),
                     'project':str(project),'files_sha256':current}


def verified_project_reuse(source, project_root, receipt):
    """Reuse imported clients only after a fully verified prior real capture."""
    receipt=Path(receipt)
    saved=batch.read(receipt)
    previous=receipt.parent
    if (saved.get('schema') != VERSION or saved.get('ok') is not True
            or saved.get('status') != 'NATIVE_PAIR_CAPTURE_VERIFIED'
            or not all(batch.read(previous/'verification.json')['checks'].values())
            or not all(batch.read(previous/'cleanup.json').get(k) is True
                       for k in ('input_cleanup','view_cleanup','process_cleanup','source_unchanged'))):
        raise ValueError('Imported clients require verified capture and cleanup before reuse')
    if (sha(previous/'project_reuse.json') != saved.get('project_reuse_sha256')
            or sha(previous/'source_binding.json') != saved.get('source_binding_sha256')):
        raise ValueError('Imported native project receipt SHA changed')
    binding=batch.read(previous/'project_reuse.json')
    if (binding['source'] != str(Path(source).resolve())
            or binding['source_hashes'] != batch.hashes(Path(source))
            or binding['project_root'] != str(Path(project_root).resolve())):
        raise ValueError('Imported native client source identity changed')
    for role in multiclient.ROLES:
        project=Path(project_root)/('project_'+role)
        if project.is_symlink() or batch.hashes(project) != binding['projects'][role]:
            raise ValueError('Imported native project changed after verified capture: '+role)
    return {'receipt':str(receipt),'receipt_sha256':sha(receipt),
            'project_reuse_sha256':sha(previous/'project_reuse.json')}


def owned_group_members(pgid):
    return [row for row in process_identities().values() if row['pgid'] == pgid]


def process_identities():
    text=subprocess.run(['ps','-axo','pid=,ppid=,pgid=,lstart=,stat=,args='],
                        capture_output=True,text=True,check=True).stdout
    result={}
    for line in text.splitlines():
        parts=line.split(None,9)
        if len(parts)!=10:continue
        # Native ps replaces argv with <defunct> after exit and before wait().
        # Zombies have no executable state and must never be signalled or
        # mistaken for a live PID reuse. Live identities remain exact.
        if parts[8].startswith('Z'):continue
        result[int(parts[0])]={'pid':int(parts[0]),'ppid':int(parts[1]),'pgid':int(parts[2]),
                              'started':' '.join(parts[3:8]),'command':parts[9]}
    return result


def observe_editor_group(receipts, worker_pid, editor, project, observed):
    """Capture exact self-owned group identities while its verified leader lives."""
    path=Path(receipts)/'owned_editor.json'
    if not path.is_file():return None
    value=batch.read(path)
    if (value.get('worker_pid')!=worker_pid or value.get('project')!=str(project)
            or value.get('editor')!=str(editor) or value.get('pid')!=value.get('pgid')
            or value.get('pid') in (os.getpid(),os.getpgrp(),73299)):
        raise ValueError('Native client ownership receipt differs from its launched worker')
    table=process_identities();leader=table.get(value['pid'])
    if leader is not None:
        command=shlex.split(leader['command'])
        if (leader['started']!=value.get('started') or not command or command[0]!=str(editor)
                or '-projectPath' not in command
                or command[command.index('-projectPath')+1]!=str(project)
                or leader['pgid']!=value['pgid']):
            raise ValueError('Native Editor PID was reused or its project identity changed')
        for pid,row in table.items():
            if row['pgid']==value['pgid']:observed[pid]=row
    return value


def cleanup_editor_group(receipts, worker_pid, editor, project, observed, output):
    """Never signal an unrelated or unobserved process, even after leader exit."""
    value=observe_editor_group(receipts,worker_pid,editor,project,observed)
    events=[]
    if value is None:
        # The adapter records every attempted launch; uncertain launch stays blocked.
        exit_path=Path(receipts)/'runner_exit.json'
        no_launch=exit_path.is_file() and batch.read(exit_path).get('no_editor_launched') is True
        result={'ok':no_launch,'owned_editor_receipt':None,'signals':events,'remaining':[],
                'reason':'verified no launch' if no_launch else 'launch ownership not proved'}
        dump(output,result);return result
    for sig in (signal.SIGTERM,signal.SIGKILL):
        table=process_identities();members={pid:row for pid,row in table.items() if row['pgid']==value['pgid']}
        if not members:break
        unknown=[row for pid,row in members.items() if pid in (os.getpid(),os.getpgrp(),73299) or pid not in observed or
                 any(row[k]!=observed[pid][k] for k in ('pid','pgid','started','command'))]
        if unknown:
            dump(output,{'ok':False,'owned_editor_receipt':value,'signals':events,
                         'remaining':list(members.values()),'unverified_members':unknown})
            return {'ok':False,'remaining':list(members.values())}
        events.append({'signal':int(sig),'verified_members':list(members.values())})
        for pid in members:
            try:os.kill(pid,sig)
            except ProcessLookupError:pass
        deadline=time.monotonic()+3
        while time.monotonic()<deadline and owned_group_members(value['pgid']):time.sleep(.2)
    remaining=owned_group_members(value['pgid'])
    result={'ok':not remaining,'owned_editor_receipt':value,'signals':events,
            'remaining':remaining,'observed_members':list(observed.values())}
    dump(output,result);return result


def observe_owned_group(proc, observed):
    """Only observe descendants while the Popen-owned dedicated leader lives."""
    if proc.poll() is not None:
        return
    table = process_identities()
    leader = table.get(proc.pid)
    if leader is None and proc.poll() is not None:
        return  # exited between the initial poll and native ps snapshot
    if not leader or leader['pgid'] != proc.pid or proc.pid in (os.getpid(),os.getpgrp(),73299):
        raise ValueError('Owned worker group leader is not verified')
    if proc.pid in observed and any(leader[k] != observed[proc.pid][k]
                                   for k in ('pid','pgid','started','command')):
        raise ValueError('Owned worker PID identity changed')
    for pid,row in table.items():
        if row['pgid'] == proc.pid:
            observed[pid] = row


def stop_owned(proc, receipt, observed):
    """Signal only saved, unchanged identities in this launched dedicated group."""
    observe_owned_group(proc, observed)
    events = []
    if proc.poll() is None:
        proc.send_signal(signal.SIGTERM)
        events.append({'signal':int(signal.SIGTERM),'pid':proc.pid,'identity':observed[proc.pid]})
        try:
            proc.wait(timeout=25)  # allow adapter finally to clean its Editors
        except subprocess.TimeoutExpired:
            pass
    for sig in (signal.SIGTERM,signal.SIGKILL):
        table = process_identities()
        members = {pid:r for pid,r in table.items() if r['pgid'] == proc.pid}
        if not members:
            break
        unknown = [r for pid,r in members.items() if pid not in observed or
                   pid in (os.getpid(),os.getpgrp(),73299) or any(
                       r[k] != observed[pid][k] for k in ('pid','pgid','started','command'))]
        if unknown:
            result = {'ok':False,'pid':proc.pid,'signals':events,
                      'remaining':list(members.values()),'unverified_members':unknown}
            dump(receipt,result)
            return result
        events.append({'signal':int(sig),'verified_members':list(members.values())})
        for pid in members:
            try:os.kill(pid,sig)
            except ProcessLookupError:pass
        deadline = time.monotonic()+3
        while time.monotonic()<deadline and owned_group_members(proc.pid):time.sleep(.2)
    remaining = owned_group_members(proc.pid)
    proc.poll()
    result = {'ok':not remaining,'pid':proc.pid,'exit_code':proc.returncode,
              'signals':events,'remaining':remaining,'observed_members':list(observed.values())}
    dump(receipt,result)
    return result


def verify_prepared_output(source, output):
    """Admit only an exact, unused planning-source copy; never existing evidence."""
    source, output = Path(source).resolve(), Path(output).resolve()
    if set(p.name for p in output.iterdir()) != {'project'}:
        raise ValueError('Prepared output contains capture evidence or unknown files')
    project = output/'project'
    if project.is_symlink() or not project.is_dir():
        raise ValueError('Prepared project is not an isolated directory')
    def tree(root):
        result = {}
        for path in root.rglob('*'):
            if path.is_symlink():
                raise ValueError('Prepared source refuses symlinks')
            if path.is_file(): result[str(path.relative_to(root))] = sha(path)
        return result
    expected, actual = tree(source), tree(project)
    if not expected or actual != expected:
        raise ValueError('Prepared project differs from exact planning source')
    return {'schema':'unity-unused-planning-copy.v1', 'source':str(source),
            'prepared_project':str(project), 'files_sha256':actual,
            'no_existing_capture':True, 'copy_not_executed':True}


def run(candidate, source, output, *, adapter_root, adapter_pin, editor,
        actions, schedule, observer_contract, duration, warmup=1, fps=10, poll=None,
        project_root=None, reuse_receipt=None, host_reuse_receipt=None, import_reuse_receipt=None, prepared_output=False):
    source, output = Path(source).resolve(), Path(output).resolve()
    bindings = validate_request(candidate,source,actions,schedule,duration,warmup,fps)
    project_root = Path(project_root).resolve() if project_root else output
    if reuse_receipt and import_reuse_receipt:
        raise ValueError("Capture reuse and import-only reuse must remain distinct")
    if import_reuse_receipt:
        from .unity_failed_import_reuse import verify
        reuse = verify(source,project_root,import_reuse_receipt)
    else:
        reuse = verified_project_reuse(source,project_root,reuse_receipt) if reuse_receipt else None
    host_project, host_reuse = verified_host_reuse(candidate,host_reuse_receipt) if host_reuse_receipt else (project_root/'project_HOST',None)
    prepared = verify_prepared_output(source,output) if prepared_output else None
    if output.exists() and not prepared:
        allowed={'project_A','project_B',Path(reuse_receipt).parent.name} if reuse and project_root==output else set()
        if not allowed or any(p.name not in allowed for p in output.iterdir()):
            raise ValueError('Preserve existing native pair capture; no repeat recording')
    from engine_adapters.unity3d.playtest.project_snapshot import snapshot_files
    files = list(snapshot_files(source, []))
    source_hashes = {str(p.relative_to(source)):sha(p) for p in files}
    source_bytes = sum(p.stat().st_size for p in files)
    # Import all three isolated source copies, plus a conservative PNG budget.
    import_count = (0 if reuse else 2) + (0 if host_reuse else 1)
    imports = import_count*disk.estimate('admission',source,source_bytes=source_bytes)['estimated_next_stage_bytes']
    points = len(schedule['points'])
    recording = max(256*1024**2, points*1920*1080*4*2)
    needed = imports+recording+8*disk.GIB
    free = shutil.disk_usage(output.parent).free
    output.mkdir(parents=True,exist_ok=bool(reuse))
    dump(output/'disk_gate.json',{'phase':'native_pair_record','free_bytes':free,
        'estimated_next_stage_bytes':imports+recording,'reserve_bytes':8*disk.GIB,
        'required_bytes':needed,'shortfall_bytes':max(0,needed-free),
        'admitted':free>=needed,'copy_count':import_count,'planned_role_screenshots':points,
        'verified_project_reuse':reuse,'verified_host_reuse':host_reuse})
    if free < needed:
        raise disk.DiskSpaceRequired(f'Native pair record needs {needed} bytes; shortfall {needed-free}')
    dump(output/'source_binding.json',{'schema':VERSION,'candidate':candidate,
        'authored_tcp_source_sha256':bindings,'planning_source':str(source),
        'planning_source_sha256':source_hashes,'adapter_root':str(adapter_root),
        'adapter_pin':str(adapter_pin),'adapter_pin_sha256':sha(adapter_pin),
        'observer_contract':str(observer_contract),'observer_contract_sha256':sha(observer_contract),
        'module_sha256':sha(Path(__file__)),'worker_sha256':sha(Path(__file__).with_name('unity_native_pair_worker.py')),
        'normal_authored_tcp':True,'automation':False,'replay':False,'ignore_focus':False,
        'clock':'independent recorder sessions; no cross-session synchronization',
        'prepared_output':prepared,'project_root':str(project_root),'verified_project_reuse':reuse,'verified_host_reuse':host_reuse})
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1',0));port=reservation.getsockname()[1]
    session = 'whitebox-record-'+str(time.time_ns())
    stop = output/'STOP_NATIVE_PAIR'
    helper = Path(__file__).with_name('resources')/'WhiteboxNativePairOpen.cs'
    snapshots, processes, streams = {}, {}, {}
    start = time.monotonic()
    error, verified, derivation = None, None, None
    observed_editors = {role:{} for role in multiclient.ROLES}
    observed_workers = {role:{} for role in admission.ROLES}
    def check():
        if time.monotonic()-start > duration+warmup+650:
            raise TimeoutError('Native pair startup plus recording deadline exceeded')
        if shutil.disk_usage(output).free < 8*disk.GIB:
            raise disk.DiskSpaceRequired('Native pair recording reached 8GiB reserve')
        try:
            for role in multiclient.ROLES:
                if role in processes:
                    observe_editor_group(output/'workers'/role,processes[role].pid,str(editor),
                                         project_root/('project_'+role),observed_editors[role])
            for role,proc in processes.items():
                observe_owned_group(proc,observed_workers[role])
        except Exception as exc:
            dump(output/('ownership_failure_'+str(time.time_ns())+'.json'),
                 {'at':time.time(),'error':str(exc),'live_processes':process_identities(),
                  'observed_workers':observed_workers,'observed_editors':observed_editors})
            raise
        if poll:poll()
    try:
        for role in admission.ROLES:
            project = host_project if role=='HOST' else project_root/('project_'+role)
            for src in ([] if (role=='HOST' and host_reuse) or (role!='HOST' and reuse) else files):
                check();rel=src.relative_to(source);dst=project/rel
                dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)
                if sha(dst)!=source_hashes[str(rel)]:
                    raise ValueError('Native pair source changed during copy')
            snapshot = {'source':str(source),'files_sha256':source_hashes}
            dump(output/('source_snapshot_'+role+'.json'),snapshot)
            snapshots[role]=snapshot
        dump(output/'client_snapshots.json',{role:snapshots[role] for role in multiclient.ROLES})
        host = output/'sessions/host';host.mkdir(parents=True)
        target = host_project/'Assets/GameFactory3AEvaluation/Editor/WhiteboxNativePairOpen.cs'
        if not host_reuse:
            if target.exists():raise ValueError('Do not overwrite author source with helper')
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(helper,target)
        host_command = [str(editor),'-batchmode','-projectPath',str(host_project),
            '-skipUpgradeDialogs','-executeMethod','WhiteboxNativePairOpen.Enter',
            '-logFile',str(host/'Editor.log'),*admission.arguments('HOST',port,session,host,stop)]
        streams['HOST']=(host/'process.log').open('w')
        processes['HOST']=subprocess.Popen(host_command,stdout=streams['HOST'],stderr=subprocess.STDOUT,start_new_session=True)
        observe_owned_group(processes['HOST'],observed_workers['HOST'])
        dump(host/'owned_process.json',{'pid':processes['HOST'].pid,'command':host_command,
             'helper_sha256':sha(helper),'at':time.time()})
        while True:
            check()
            if processes['HOST'].poll() is not None:raise RuntimeError('Real authored host exited before ready')
            rows=admission.read_rows(host/'observations.jsonl')
            if rows and rows[-1].get('is_host') is True and rows[-1].get('state_json'):
                if rows[-1].get('error'):raise RuntimeError('Authored host error: '+rows[-1]['error'])
                break
            time.sleep(.3)
        for role in multiclient.ROLES:
            spec={'role':role,'source':str(source),'project':str(project_root/('project_'+role)),
                'take':str(output/'sessions'/role),'receipts':str(output/'workers'/role),
                'snapshot':str(output/('source_snapshot_'+role+'.json')),
                'adapter_root':str(Path(adapter_root).resolve()),'adapter_pin':str(Path(adapter_pin).resolve()),
                'editor':str(editor),'scene':admission.SCENE,'port':port,'session':session,
                'evaluator_root':str(Path(__file__).resolve().parents[3]),
                'observer_contract':str(Path(observer_contract).resolve()),
                'actions':actions,'schedule':schedule,'duration':duration,'warmup':warmup,'fps':fps}
            request=output/('request_'+role+'.json');dump(request,spec)
            streams[role]=(output/('worker_'+role+'.log')).open('w')
            processes[role]=subprocess.Popen([sys.executable,str(Path(__file__).with_name('unity_native_pair_worker.py')),str(request)],
                stdout=streams[role],stderr=subprocess.STDOUT,start_new_session=True)
        for role in multiclient.ROLES:
            observe_owned_group(processes[role],observed_workers[role])
        dump(output/'owned_workers.json',{role:{'pid':p.pid} for role,p in processes.items()})
        while any(p.poll() is None for role,p in processes.items() if role in multiclient.ROLES):
            check()
            if processes['HOST'].poll() is not None:raise RuntimeError('Authored host exited during real pair record')
            if any(p.poll() not in (None,0) for role,p in processes.items() if role in multiclient.ROLES):
                raise RuntimeError('Native client failed; preserve raw diagnostics')
            time.sleep(.3)
        checks={role:batch.read(output/'workers'/role/'verification.json')['ok'] is True for role in multiclient.ROLES}
        samples=[r for r in admission.read_rows(host/'observations.jsonl') if admission.connected_sample(r,'HOST',session)]
        checks['real_authored_shared_state']=len(samples)>=3 and json.loads(samples[-1]['state_json'])['stateSeq']>json.loads(samples[0]['state_json'])['stateSeq']
        dump(output/'shared_state_verified.json',{'session':session,'port':port,'samples':samples,'checks':checks})
        if not all(checks.values()):raise RuntimeError('Real pair capture/input/shared state verification failed')
        verified={'checks':checks}
    except BaseException as exc:
        error={'type':type(exc).__name__,'error':str(exc)}
        raise
    finally:
        stop.write_text('Owned real pair recording complete; close authored host.\n')
        # Client recorders clean virtual input/view and their Editor groups before exit.
        if 'HOST' in processes:
            cutoff=time.monotonic()+12
            while processes['HOST'].poll() is None and time.monotonic()<cutoff:time.sleep(.2)
        worker_cleanup={}
        for role,proc in processes.items():
            try:
                worker_cleanup[role]=stop_owned(proc,output/('owned_cleanup_'+role+'.json'),observed_workers[role])
            except Exception as exc:
                worker_cleanup[role]={'ok':False,'error':str(exc)}
                dump(output/('owned_cleanup_'+role+'.json'),worker_cleanup[role])
        editor_cleanup={}
        for role in multiclient.ROLES:
            if role in processes:
                try:
                    editor_cleanup[role]=cleanup_editor_group(output/'workers'/role,processes[role].pid,str(editor),
                        project_root/('project_'+role),observed_editors[role],output/('owned_editor_cleanup_'+role+'.json'))
                except Exception as exc:
                    editor_cleanup[role]={'ok':False,'error':str(exc)}
                    dump(output/('owned_editor_cleanup_'+role+'.json'),editor_cleanup[role])
        for stream in streams.values():stream.close()
        source_unchanged=all(p.is_file() and sha(p)==source_hashes[str(p.relative_to(source))] for p in files)
        cleanup={name:True for name in ('input_cleanup','view_cleanup','process_cleanup')}
        for role in multiclient.ROLES:
            path=output/'workers'/role/'verification.json'
            role_checks=batch.read(path)['checks'] if path.is_file() else {}
            for name in cleanup:cleanup[name] &= role_checks.get(name) is True
        cleanup['process_cleanup'] &= all(not owned_group_members(p.pid) for p in processes.values())
        cleanup['process_cleanup'] &= all(row.get('ok') is True for row in editor_cleanup.values())
        cleanup['process_cleanup'] &= all(row.get('ok') is True for row in worker_cleanup.values())
        dump(output/'cleanup.json',dict(cleanup,source_unchanged=source_unchanged,
            roles=list(processes),owned_pids={r:p.pid for r,p in processes.items()},editor_cleanup=editor_cleanup))
        if verified:
            verified['checks'].update(cleanup,source_unchanged=source_unchanged)
        dump(output/'verification.json',verified or {'checks':dict(cleanup,source_unchanged=source_unchanged),'error':error})
        dump(output/'result.json',{'schema':VERSION,'ok':bool(verified and all(verified['checks'].values()) and not error),
            'error':error,'seconds':time.monotonic()-start,'scores_published':0,'status':'NATIVE_PAIR_CAPTURE_REQUIRES_DERIVATION' if verified and not error else 'HARNESS_ERROR'})
    if not all(cleanup.values()) or not source_unchanged:
        raise RuntimeError('Native pair cleanup incomplete; retain global cleanup marker')
    # Derive only after the host and both clients have stopped writing raw evidence.
    try:
        from .unity_native_pair_logs import preserve
        preserve(output,project_root)
        derivation=multiclient.derive_capture(output,schedule)
    except Exception as exc:
        dump(output/'derivation_failure.json',{'type':type(exc).__name__,'error':str(exc)})
        raise
    dump(output/'sparse_capture_audit.json',derivation)
    dump(output/'project_reuse.json',{'source':str(source),'source_hashes':batch.hashes(source),
        'project_root':str(project_root),
        'projects':{role:batch.hashes(project_root/('project_'+role)) for role in multiclient.ROLES}})
    result=batch.read(output/'result.json');result.update(ok=True,status='NATIVE_PAIR_CAPTURE_VERIFIED',
        project_reuse_sha256=sha(output/'project_reuse.json'),source_binding_sha256=sha(output/'source_binding.json'))
    dump(output/'result.json',result)
    return result
