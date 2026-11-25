"""Source-bound native TCP host/A/B admission. No inputs, frames, or scores.

The caller owns the coordinator lease, execution and publication locks. This
observes actual authored public state; it does not invoke gameplay or networking
methods, change focus handling, or use author automation/control/replay paths.
"""
from pathlib import Path
import json
import os
import shutil
import signal
import socket
import subprocess
import time
from . import batch, unity_disk_guard as disk
from .protocol import dump, sha
from engine_adapters.unity3d.playtest.project_snapshot import snapshot_files

VERSION = 'unity-source-bound-native-pair-admission.v1'
ROLES = ('HOST', 'A', 'B')
SCENE = 'Assets/Scenes/Waterworks.unity'
SOURCES = ('Assets/G014/Presentation/NetworkSession.cs',
           'Assets/G014/Presentation/WaterworksRuntime.cs',
           'Assets/G014/Mechanic/WaterworksSimulation.cs')


def arguments(role, port, session, output, stop):
    if role not in ROLES or type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError('Invalid real native pair role/port')
    if not session or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in session):
        raise ValueError('Unsafe native session identifier')
    args = ['--ww-host'] if role == 'HOST' else ['--ww-client', role]
    return args + ['--ww-port',str(port),'--ww-address','127.0.0.1','--ww-session',session,
                   '--ww-evidence',str(Path(output)/'author_evidence'),
                   '--whitebox-pair-role',role,'--whitebox-pair-output',str(output),
                   '--whitebox-pair-stop',str(stop),'--whitebox-pair-scene',SCENE]


def connected_sample(row, role, session):
    """Only actual configured, normal-mode, connected shared state qualifies."""
    if (row.get('schema') != 'whitebox-native-pair-observation.v1'
            or row.get('role') != role or row.get('session') != session
            or row.get('test_mode') is not False or row.get('ignore_focus') is not False
            or row.get('error') or row.get('is_host') is not (role == 'HOST')
            or (role != 'HOST' and row.get('connected') is not True)):
        return False
    try:
        state = json.loads(row['state_json'])
        players = state['players']
        return (state['session'] == session and state['stateSeq'] > 0
                and len(players) == 2 and {p['role'] for p in players} == {'A','B'}
                and all(p['connected'] is True for p in players))
    except (KeyError, ValueError, TypeError):
        return False


def read_rows(path):
    if not path.is_file(): return []
    lines = path.read_text().splitlines()
    result = []
    for index,line in enumerate(lines):
        try: result.append(json.loads(line))
        except ValueError:
            # A concurrent final write may be incomplete. Never accept it.
            if index != len(lines)-1: raise
    return result


def validate_source(candidate):
    if candidate.get('id') != 'Sol__G014_dual_zone_waterworks':
        raise ValueError('No reviewed native pair contract for this delivery')
    receipt_path = Path(candidate['native_open_receipt'])
    if sha(receipt_path) != candidate['native_open_receipt_sha256']:
        raise ValueError('Native admission source SHA changed')
    receipt = batch.read(receipt_path); source = Path(candidate['selected_project'])
    if (receipt['product_status'] != 'OPENED' or not receipt['source_unchanged']['ok']
            or not all(receipt['cleanup'].get(k) is True for k in ('input_cleanup','view_cleanup','process_cleanup'))
            or receipt['project'] != str(source) or batch.hashes(source) != receipt['project_hashes']):
        raise ValueError('Native opened source/cleanup binding changed')
    if not (source/SCENE).is_file() or any(not (source/name).is_file() for name in SOURCES):
        raise ValueError('Reviewed authored TCP delivery is incomplete')
    return source, {name:sha(source/name) for name in SOURCES}


def run(candidate, output, *, timeout=300, poll=None):
    output = Path(output); output.mkdir(exist_ok=False,parents=True)
    source, bindings = validate_source(candidate)
    files = list(snapshot_files(source, [])); source_bytes = sum(p.stat().st_size for p in files)
    # Three independent source copies and three conservative import allowances.
    required = 3 * disk.estimate('admission',source,source_bytes=source_bytes)['estimated_next_stage_bytes']
    gate = disk.check(output,'native_pair_admission',source)
    free = shutil.disk_usage(output).free
    gate.update(estimated_next_stage_bytes=required,required_bytes=required+8*disk.GIB,
                shortfall_bytes=max(0,required+8*disk.GIB-free),free_bytes=free,
                admitted=free>=required+8*disk.GIB,copy_count=3)
    dump(output/'pair_disk_gate.json',gate)
    if not gate['admitted']:
        dump(output/'disk_checkpoint.json',gate)
        raise disk.DiskSpaceRequired('Real host+A/B needs '+str(gate['required_bytes'])+' bytes, shortfall '+str(gate['shortfall_bytes']))
    helper = Path(__file__).with_name('resources')/'WhiteboxNativePairOpen.cs'
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1',0)); port = reservation.getsockname()[1]
    session = 'whitebox-'+str(time.time_ns()); stop = output/'STOP_NATIVE_PAIR'
    started = time.monotonic(); processes = {}; streams = {}; commands = {}; snapshots = {}; error = None; complete = False
    dump(output/'source_binding.json',{'schema':VERSION,'candidate':candidate,
        'authored_source_sha256':bindings,'helper_sha256':sha(helper),'module_sha256':sha(Path(__file__)),
        'normal_authored_tcp':True,'author_automation':False,'os_input':False,'recordings':0,'scores':0})
    def check_time():
        if time.monotonic()-started >= timeout: raise TimeoutError('Native pair admission 300-second deadline')
        if shutil.disk_usage(output).free < 8*disk.GIB: raise disk.DiskSpaceRequired('Native pair import reached 8GiB reserve')
        if poll: poll()
    def launch(role):
        check_time(); root = output/role; project = root/'project'; project.mkdir(parents=True)
        hashes = {}
        for src in files:
            check_time(); rel=src.relative_to(source); dst=project/rel
            dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst)
            digest=sha(src)
            if sha(dst)!=digest: raise ValueError('Pair copied source differs: '+str(rel))
            hashes[str(rel)]=digest
        snapshots[role]=hashes; dump(root/'source_copy.json',{'source':str(source),'project':str(project),'files':hashes})
        target = project/'Assets/GameFactory3AEvaluation/Editor/WhiteboxNativePairOpen.cs'
        if target.exists(): raise ValueError('Refuse to overwrite delivered pair helper')
        target.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(helper,target)
        args = [candidate['selected_editor'],'-batchmode','-projectPath',str(project),
                '-skipUpgradeDialogs','-executeMethod','WhiteboxNativePairOpen.Enter',
                '-logFile',str(root/'Editor.log'),*arguments(role,port,session,root,stop)]
        stream = (root/'process.log').open('w'); streams[role] = stream
        proc = subprocess.Popen(args,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
        processes[role]=proc; commands[role]={'pid':proc.pid,'command':args,'started_unix':time.time()}
        dump(output/'owned_processes.json',commands)
    try:
        launch('HOST')
        while True:
            check_time()
            if processes['HOST'].poll() is not None: raise RuntimeError('Authored native host exited before ready')
            observations=read_rows(output/'HOST/observations.jsonl')
            if observations and observations[-1].get('is_host') is True and observations[-1].get('state_json'):
                if observations[-1].get('error'): raise RuntimeError('Authored native host error: '+observations[-1]['error'])
                break
            time.sleep(.5)
        launch('A'); launch('B')
        while True:
            check_time()
            if any(p.poll() is not None for p in processes.values()): raise RuntimeError('Real native pair process exited before shared state')
            matched={role:[row for row in read_rows(output/role/'observations.jsonl') if connected_sample(row,role,session)] for role in ROLES}
            if all(len(rows)>=3 and rows[-1]['editor_time']-rows[0]['editor_time']>=1 for rows in matched.values()):
                # Independent clocks; do not require equal sequence or frame times.
                if any(json.loads(rows[-1]['state_json'])['stateSeq']<=json.loads(rows[0]['state_json'])['stateSeq'] for rows in matched.values()):
                    raise ValueError('Native host state failed to advance')
                dump(output/'shared_state_verified.json',{'session':session,'port':port,
                    'independent_native_clocks':True,'sources':bindings,
                    'samples':{role:rows for role,rows in matched.items()},
                    'both_authored_players_connected_in_all_sessions':True,'gameplay_inputs_sent':0,
                    'recordings':0,'not_gameplay_capture_acceptance':True})
                complete=True; break
            time.sleep(.5)
    except BaseException as exc:
        error={'type':type(exc).__name__,'error':str(exc)}
        raise
    finally:
        stop.write_text('Owned native pair observation complete; close all three Editors.\n')
        cutoff=time.monotonic()+15
        while time.monotonic()<cutoff and any(p.poll() is None for p in processes.values()): time.sleep(.2)
        for role,proc in processes.items():
            if proc.poll() is None:
                try: os.killpg(proc.pid,signal.SIGTERM)
                except ProcessLookupError: pass
                try: proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    try: os.killpg(proc.pid,signal.SIGKILL)
                    except ProcessLookupError: pass
                    proc.wait(timeout=10)
            streams[role].close()
        group_cleanup=[]
        for role,proc in processes.items():
            # Every group was created by this invocation with start_new_session.
            # Reap verified group members even after its Editor has exited.
            for sig in (signal.SIGTERM,signal.SIGKILL):
                ps_group=subprocess.run(['ps','-axo','pid=,ppid=,pgid=,args='],capture_output=True,text=True,check=True).stdout.splitlines()
                live=[line for line in ps_group if len(line.split(None,3))>=4 and int(line.split(None,3)[2])==proc.pid]
                if not live: break
                group_cleanup.append({'role':role,'pgid':proc.pid,'signal':int(sig),'verified_members':live})
                try: os.killpg(proc.pid,sig)
                except ProcessLookupError: pass
                time.sleep(.5)
        dump(output/'owned_group_cleanup.json',group_cleanup)
        source_unchanged=batch.hashes(source)==batch.read(Path(candidate['native_open_receipt']))['project_hashes']
        # A process group can outlive its Editor; preserve and report any survivors.
        ps=subprocess.run(['ps','-axo','pid=,ppid=,pgid=,args='],capture_output=True,text=True,check=True).stdout.splitlines()
        groups={p.pid for p in processes.values()}
        descendants=[line for line in ps if len(line.split(None,3))>=4 and int(line.split(None,3)[2]) in groups]
        cleanup={'input_cleanup':True,'view_cleanup':True,
                 'process_cleanup':all(p.poll() is not None for p in processes.values()) and not descendants,
                 'input_cleanup_reason':'Observation-only admission; no input or view activation performed',
                 'owned_processes':{role:{**commands[role],'exit_code':p.returncode} for role,p in processes.items()},
                 'remaining_owned_groups':descendants}
        dump(output/'result.json',{'schema':VERSION,'at':time.time(),'real_pair_connected':complete,
            'source_unchanged':source_unchanged,'cleanup':cleanup,'error':error,
            'seconds':time.monotonic()-started,'required_real_clients':2,'recordings':0,'scores':0,
            'status':'REAL_PAIR_CONNECTED_INPUT_CAPTURE_STILL_REQUIRED' if complete else 'HARNESS_ERROR'})
        if not source_unchanged or not cleanup['process_cleanup']:
            raise RuntimeError('Native pair source/owned process cleanup incomplete; inspect result.json')
    return batch.read(output/'result.json')
