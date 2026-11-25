"""Stage1 playable pairs: independent engine processes, native input, replicated state.

No single-client fallback. ``run_playable(delivery_dir, out, *, models)`` is the
runner interface; ``record_pair(project, out, *, profile)`` is the native probe.
An unqualified pair writes diagnostics/status, never playable_score.json.
"""
from __future__ import annotations

from ..model_config import PLANNER_MODEL

from contextlib import contextmanager, ExitStack
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

from .paths import read_profiles
from .paths import read_json, write_json, sha256
from .llm import HarnessError
from .prepare import IGNORE
from . import playable_rules

from .dual_client_plan import PROTOCOL as VERSION, DURATION_S, make_plan
OBSERVER = Path(__file__).with_name('dual_client_observer.gd')
ROLES = ('host', 'client')


class ProductLimitation(HarnessError):
    """Native authored entry cannot reach user-controlled multiplayer play."""


def source_hashes(project: Path) -> dict:
    """Prune caches during traversal, including giant Unity import directories."""
    result = {}
    for root, dirs, names in os.walk(project, followlinks=False):
        dirs[:] = [d for d in dirs if d not in IGNORE(root, dirs) and not Path(root, d).is_symlink()]
        for name in names:
            path = Path(root, name)
            if name not in IGNORE(root, [name]) and not path.is_symlink():
                result[str(path.relative_to(project))] = sha256(path)
    return result


@contextmanager
def pair_slots(wait_s: float = 3600):
    """Reserve both lanes in a fixed order before either client launches.

    Retain earlier reservations while waiting for a busy lane, so cycling single
    jobs cannot starve a pair. Every pair uses the same order; timeout/error
    releases all reservations. No nested call to record.record is involved.
    """
    base = Path(tempfile.gettempdir()) / 'gamefactory-sol-whitebox-gui.lock'
    count = max(1, int(os.environ.get('A3GAME_GUI_SLOTS', '1')))
    paths = sorted(set([base] + [base.with_name(f'gamefactory-sol-whitebox-gui.slot{k}.lock') for k in range(1, count)] + list(base.parent.glob('gamefactory-sol-whitebox-gui.slot*.lock'))))
    end = time.monotonic() + wait_s
    with ExitStack() as stack:
        handles = [stack.enter_context(p.open('a')) for p in paths]
        acquired = []
        try:
            for handle in handles:
                while True:
                    try:
                        fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
                        acquired.append(handle)
                        break
                    except BlockingIOError:
                        if time.monotonic() >= end:
                            raise HarnessError('dual native GUI reservation busy; no client launched')
                        time.sleep(.25)
            yield [str(p) for p in paths]
        finally:
            for handle in reversed(acquired):
                fcntl.flock(handle,fcntl.LOCK_UN)


def profile_for(delivery: dict, project: Path) -> str:
    model = delivery.get('model', '').lower()
    if delivery.get('game_id') != 'G043_airship_kitchen' or model not in ('opus','sol','astra','glm'):
        raise HarnessError('no source-reviewed Godot pair profile for this identity')
    required = {'opus':'game/main.gd','sol':'scripts/kitchen_game.gd','astra':'network.gd','glm':'main.gd'}[model]
    if not (project / required).is_file():
        raise HarnessError(f'reviewed entry missing: {required}')
    profile = model + '_g043'
    reviewed = read_profiles(Path(__file__).with_name('dual_client_profiles.json'), reader=read_json)[profile]
    if project.resolve() != Path(reviewed['project']).resolve():
        raise HarnessError('delivery does not match the reviewed targets.json original project')
    if any(sha256(project/name) != digest for name,digest in reviewed['reviewed_sha256'].items()):
        raise HarnessError('reviewed native-entry source changed; re-review before input dispatch')
    return profile


def _rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _position(row: dict, player: int):
    players = row['state'].get('players', {})
    value = players[player - 1] if isinstance(players, list) else players.get(str(player), {})
    return value.get('pos')


def validate_interaction(before: dict, after: dict, actor: str) -> dict:
    """Require real reciprocal peer IDs and remote replication of isolated input.

    Player 2 must move in HOST state, where prediction cannot fabricate it;
    player 1 must move in CLIENT state. Both ends must agree within tolerance.
    """
    if actor not in ROLES:
        raise ValueError('unknown native input role')
    for role in ROLES:
        if any(before[role][key] != after[role][key] for key in ('pid','peer_id','room','peers')):
            raise ValueError('participant/session changed during the input')
    host, client = after['host'], after['client']
    if host['pid'] == client['pid'] or host['peer_id'] != 1 or client['peer_id'] <= 1:
        raise ValueError('not two independent ENet participants')
    if client['peer_id'] not in host['peers'] or host['peer_id'] not in client['peers']:
        raise ValueError('participants are not reciprocal peers')
    if not host['room'] or host['room'] != client['room']:
        raise ValueError('room identifiers disagree')
    player = 1 if actor == 'host' else 2
    observer = 'client' if actor == 'host' else 'host'
    start, end = _position(before[observer], player), _position(after[observer], player)
    local = _position(after[actor], player)
    if not all(isinstance(p, list) and len(p) == 2 for p in (start, end, local)):
        raise ValueError('missing authored player positions')
    distance = sum((a-b)**2 for a,b in zip(start,end)) ** .5
    disagreement = sum((a-b)**2 for a,b in zip(local,end)) ** .5
    if distance < .15 or disagreement > .35:
        raise ValueError('remote native state did not replicate the isolated player input')
    if any(after[r]['unix'] <= before[r]['unix'] for r in ROLES):
        raise ValueError('stale state observations')
    return {'actor':actor, 'observer':observer, 'player':player, 'distance':distance,
            'replica_disagreement':disagreement, 'before':before, 'after':after}


class Pair:
    def __init__(self, out, processes):
        self.out, self.processes, self.serial = out, processes, dict.fromkeys(ROLES, 0)

    def wait(self, predicate, timeout=15):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            for role, process in self.processes.items():
                if process.poll() is not None:
                    raise HarnessError(f'{role} native process exited ({process.returncode}); inspect engine.log')
            value = predicate()
            if value:
                return value
            time.sleep(.1)
        raise HarnessError('native pair observation/input deadline; inspect per-client evidence')

    def send(self, role, kind, **values):
        self.serial[role] += 1
        command = dict(id=self.serial[role], kind=kind, **values)
        root = self.out / role
        write_json(root / 'command.json', command)
        def ack():
            path = root / 'ack.json'
            row = read_json(path) if path.exists() else {}
            return row if row.get('command', {}).get('id') == command['id'] else None
        result = self.wait(ack)
        if not result['ok']:
            raise HarnessError(f'{role} native input failed: {result["error"]}; {command}')
        return result

    def states(self):
        return {r:read_json(self.out/r/'latest.json') for r in ROLES}

    def pause(self, seconds):
        end = time.monotonic() + seconds
        self.wait(lambda: time.monotonic() >= end, timeout=seconds+2)


def _enter(pair: Pair, profile: str):
    pair.wait(lambda: all((pair.out/r/'latest.json').exists() for r in ROLES))
    pair.pause(2)
    if profile == 'opus_g043':
        pair.send('host','click',text='创建厨房')
        room = pair.wait(lambda: pair.states()['host']['room'])
        pair.send('client','click',text='加入房间')
        pair.send('client','text',text=room,placeholder='如 YUN-427')
        pair.send('client','click',text='加入')
    elif profile == 'sol_g043':
        # User-supplied address is entered through the authored LineEdit.
        from .record import _free_ports
        address = '127.0.0.1:' + str(_free_ports(1)[0])
        for role in ROLES:
            pair.send(role,'text',text=address)
        pair.send('host','click',text='创建厨房 / 主机')
        pair.pause(.8)
        pair.send('client','click',text='加入厨房 / 客户端')
    elif profile == 'astra_g043':
        pair.send('host','click',text='创建厨房')
        room = pair.wait(lambda: pair.states()['host']['room'])
        pair.send('client','text',text=room)
        pair.send('client','click',text='加入房间')
    elif profile == 'glm_g043':
        pair.wait(lambda: all(pair.states()[r]['peers'] for r in ROLES))
        for role in ROLES:
            pair.send(role,'key',key='Enter',duration=.15)
            pair.send(role,'key',key='D',duration=.8)
        pair.pause(3)
        write_json(pair.out/'product_limitation.json', {'classification':'PRODUCT_NO_MANUAL_READY_PATH', 'states':pair.states(), 'native_pair_attempted':True, 'evidence':'Both real peers connected; native Enter and movement sent; authored ready_state only changes inside bot branches and HUD has no ready Button. No bot enabled.'})
        raise ProductLimitation('GLM native peers connected but authored product has no manual ready path; no gameplay interaction qualified')
    pair.wait(lambda: all(pair.states()[r]['peers'] for r in ROLES))
    pair.pause(1)
    for role in ROLES:
        pair.send(role,'click',text='准备 · 等待另一位厨师' if profile == 'astra_g043' else '准备')
    pair.pause(2)
    for role in ROLES:
        pair.send(role,'key',key='Enter',duration=.15)
    pair.pause(5)


def record_pair(project: Path, out: Path, *, profile: str, plan: dict) -> dict:
    """Run one new Godot pair; output must not exist. No scores or model calls."""
    from .record import godot_executable
    project, out = Path(project).resolve(), Path(out).resolve()
    binary = godot_executable()
    if not binary:
        raise HarnessError('Godot executable unavailable')
    if out.exists():
        raise HarnessError('pair attempt already exists; preserve evidence and use a new revision')
    out.mkdir(parents=True)
    baseline = source_hashes(project)
    if plan.get('protocol') != VERSION or plan.get('duration_s') != DURATION_S or plan.get('planner') != PLANNER_MODEL:
        raise HarnessError('record_pair requires a persisted Astra-reviewed 75-second plan')
    if read_json(out.parent/'plan.json') != plan:
        raise HarnessError('persisted plan differs from dispatched plan')
    write_json(out/'plan.json', plan)
    write_json(out/'source_binding.json', {'project':str(project),'files':baseline,'observer_sha256':sha256(OBSERVER), 'module_sha256':sha256(Path(__file__)), 'profile':profile})
    copies = {}
    for role in ROLES:
        copies[role] = out/'projects'/role
        shutil.copytree(project,copies[role],ignore=IGNORE)
        (out/role).mkdir()
        if source_hashes(copies[role]) != baseline:
            raise HarnessError('runtime copy differs from original')
    processes, logs, commands, cleanup = {}, {}, {}, {}
    receipt = {'version':VERSION,'duration_s':DURATION_S,'required_real_clients':2,'qualified':False,'profile':profile,
               'plan_sha256':sha256(out/'plan.json'),'source_binding_sha256':sha256(out/'source_binding.json')}
    try:
        with pair_slots(float(os.environ.get('A3GAME_GUI_WAIT_S','3600'))) as slots:
            receipt['gui_slots'] = slots
            for role in ROLES:
                log = out/role/'import.log'
                cmd = [binary,'--headless','--path',str(copies[role]),'--editor','--import']
                with log.open('w') as stream:
                    imported = subprocess.run(cmd,stdout=stream,stderr=subprocess.STDOUT,timeout=120)
                product_errors = bool(__import__('re').search(r'SCRIPT ERROR|Parse Error|Failed to load script',log.read_text(errors='replace')))
                write_json(out/role/'import_result.json', {'exit_code':imported.returncode,'timeout':False,'product_errors':product_errors,'command':cmd})
                if imported.returncode or product_errors:
                    raise ProductLimitation(f'{role} original product import failed; inspect import.log; no qualified pair')
            port = None
            if profile == 'glm_g043':
                from .record import _free_ports
                port = _free_ports(1)[0]
            for role in ROLES:
                commands[role] = [binary,'--path',str(copies[role]),'--resolution','1280x720',
                                  '-s',str(OBSERVER),'--',f'--pair-output={out/role}',
                                  f'--pair-profile={profile}',f'--pair-role={role}']
                if port is not None:
                    commands[role] += [f'--role={role}', f'--port={port}']
                logs[role] = (out/role/'engine.log').open('w')
                processes[role] = subprocess.Popen(commands[role],stdout=logs[role],stderr=subprocess.STDOUT,start_new_session=True)
            write_json(out/'launch.json', {r:{'pid':p.pid,'command':commands[r],'project':str(copies[r])} for r,p in processes.items()})
            pair = Pair(out,processes)
            try:
                _enter(pair, profile)
                interactions = []
                # Each isolated input is observed in the opposite engine's authored state.
                for command in plan['review']['actions']:
                    role, key = command['role'], command['key']
                    pair.pause(1.8)
                    before = pair.states()
                    action = pair.send(role,'key',key=key,duration=command['duration_s'])
                    pair.pause(command['wait_s'])
                    after = pair.states()
                    proof = validate_interaction(before,after,role)
                    proof['action'] = action
                    interactions.append(proof)
                receipt.update(qualified=True,interactions=interactions)
            except (ValueError, ProductLimitation, HarnessError) as exc:
                receipt.update(qualified=False,error=f'{type(exc).__name__}: {exc}',
                               failure_kind='PRODUCT_LIMITATION' if isinstance(exc,ProductLimitation) else 'UNQUALIFIED_PAIR')
            finally:
                # Each observer owns its 75-second capture clock. Do not shorten a
                # take after the first successful movement or a product limitation.
                for role,p in processes.items():
                    if p.poll() is None:
                        try: p.wait(timeout=85)
                        except subprocess.TimeoutExpired: pass
                for role,p in processes.items():
                    if p.poll() is None:
                        write_json(out/role/'command.json', {'id':pair.serial[role]+1,'kind':'stop'})
                for role,p in processes.items():
                    forced = False
                    try: p.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        forced = True; p.terminate()
                        try: p.wait(timeout=5)
                        except subprocess.TimeoutExpired: p.kill(); p.wait(timeout=5)
                    cleanup[role] = {'pid':p.pid,'exit_code':p.returncode,'forced':forced,'process_cleanup':p.poll() is not None}
    except Exception as exc:
        receipt.update(qualified=False,error=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        # Also cover exceptions between the two Popen calls.
        for role,p in processes.items():
            if p.poll() is None:
                p.terminate()
                try: p.wait(timeout=5)
                except subprocess.TimeoutExpired: p.kill(); p.wait(timeout=5)
                cleanup[role] = {'pid':p.pid,'exit_code':p.returncode,'forced':True,'process_cleanup':True}
        for log in logs.values(): log.close()
        receipt['cleanup'] = cleanup
        receipt['recording'] = {r:read_json(out/r/'recording_complete.json') if (out/r/'recording_complete.json').exists() else {} for r in ROLES}
        receipt['source_unchanged'] = source_hashes(project) == baseline
        receipt['runtime_authored_unchanged'] = all(all(sha256(copies[r]/name)==digest for name,digest in baseline.items()) for r in ROLES)
        for role in ROLES:
            path = out/role/'input_view_cleanup.json'
            cleanup.setdefault(role,{})['input_view'] = read_json(path) if path.exists() else None
        receipt['qualified'] = bool(receipt['qualified'] and all(75000 <= receipt['recording'][r].get('duration_ms',0) < 78000 for r in ROLES) and receipt['source_unchanged'] and receipt['runtime_authored_unchanged'] and all(cleanup[r].get('exit_code') == 0 and not cleanup[r].get('forced') and cleanup[r].get('input_view',{} ) and cleanup[r]['input_view'].get('input_cleanup') for r in ROLES))
        receipt['evidence_sha256'] = {str(p.relative_to(out)):sha256(p) for r in ROLES for p in (out/r).rglob('*') if p.is_file()}
        write_json(out/'pair_receipt.json',receipt)
    return receipt


def verify_pair(pair_dir: Path, project: Path) -> dict:
    """Verify a completed receipt and its raw evidence before reuse or scoring."""
    pair_dir = Path(pair_dir)
    receipt = read_json(pair_dir/'pair_receipt.json')
    if receipt.get('version') != VERSION or receipt.get('duration_s') != 75 or receipt.get('required_real_clients') != 2:
        raise HarnessError('receipt is not the reviewed 75-second dual protocol; preserve as diagnostic')
    for name, digest in receipt.get('evidence_sha256',{}).items():
        path = (pair_dir/name).resolve()
        if not path.is_relative_to(pair_dir.resolve()) or not path.is_file() or sha256(path) != digest:
            raise HarnessError(f'pair evidence changed or missing: {name}')
    if sha256(pair_dir/'plan.json') != receipt['plan_sha256'] or sha256(pair_dir/'source_binding.json') != receipt['source_binding_sha256']:
        raise HarnessError('pair source/plan receipt binding changed')
    binding = read_json(pair_dir/'source_binding.json')
    if binding['project'] != str(project.resolve()) or binding['files'] != source_hashes(project):
        raise HarnessError('original source differs from recorded pair')
    plan = read_json(pair_dir/'plan.json')
    requirement = pair_dir.parents[2]/'input'/'requirement.txt'
    if sha256(requirement) != plan['requirement_sha256']:
        raise HarnessError('original case requirement binding changed')
    from .llm import accepted_response
    calls = pair_dir.parent/'model_calls'
    if plan['planner'] != PLANNER_MODEL or accepted_response(calls,'source_review') != plan['review'] or sha256(calls/'source_review/accepted_response.json') != plan['accepted_response_sha256']:
        raise HarnessError('pair lacks matching accepted Astra source review')
    if not receipt.get('qualified'):
        return receipt
    launch = read_json(pair_dir/'launch.json')
    if launch['host']['pid'] == launch['client']['pid'] or launch['host']['project'] == launch['client']['project']:
        raise HarnessError('pair processes/runtime copies are not independent')
    for role in ROLES:
        native = read_json(pair_dir/role/'process.json')
        recording = read_json(pair_dir/role/'recording_complete.json')
        if native['pid'] != launch[role]['pid'] or recording['pid'] != native['pid'] or Path(native['project']).resolve() != Path(launch[role]['project']).resolve():
            raise HarnessError('native process identity mismatch')
        if not 75000 <= recording['duration_ms'] < 78000 or recording['requested_duration_ms'] != 75000:
            raise HarnessError('not a full 75-second native take')
        frames = _rows(pair_dir/role/'frame_index.jsonl')
        if len(frames) < 5 or frames[0]['t_ms'] > 2000 or frames[-1]['t_ms'] < 75000:
            raise HarnessError('native capture does not span the requested take')
        clean = receipt['cleanup'][role]
        if clean.get('forced') or clean.get('exit_code') != 0 or not clean.get('process_cleanup') or not all(clean.get('input_view',{}).get(k) for k in ('input_cleanup','view_cleanup')):
            raise HarnessError('native pair cleanup incomplete')
    origins = [read_json(pair_dir/r/'process.json')['origin_unix'] for r in ROLES]
    if abs(origins[0]-origins[1]) > 5:
        raise HarnessError('native clients did not capture concurrently')
    interactions = receipt.get('interactions',[])
    if {p['actor'] for p in interactions} != set(ROLES):
        raise HarnessError('both native clients must produce peer-visible input')
    traces = {r:_rows(pair_dir/r/'state_trace.jsonl') for r in ROLES}
    actions = {r:_rows(pair_dir/r/'actions.jsonl') for r in ROLES}
    for proof in interactions:
        validate_interaction(proof['before'],proof['after'],proof['actor'])
        action = proof['action']
        if not action.get('sent') or action not in actions[proof['actor']]:
            raise HarnessError('interaction lacks its native input receipt')
        for r in ROLES:
            if proof['before'][r] not in traces[r] or proof['after'][r] not in traces[r] or proof['after'][r]['pid'] != launch[r]['pid']:
                raise HarnessError('interaction is not bound to the native trace')
    return receipt


def _rules(out, pairs):
    verdicts = {}
    for role in ROLES:
        takes = [(i+1,p/role) for i,p in enumerate(pairs)]
        imp = playable_rules._import(out,'godot',[p for _,p in takes])
        launch, launch_stats = playable_rules._launch(takes)
        operate, operate_stats = playable_rules._operate(takes)
        verdicts[role] = dict(zip(playable_rules.IDS,(imp,launch,operate)))
        write_json(pairs[-1]/role/'playable_rules.json', {'verdicts':verdicts[role],'launch':launch_stats,'operate':operate_stats})
    checks = {}
    for ident in playable_rules.IDS:
        statuses = [verdicts[r][ident]['status'] if verdicts[r][ident] else 'HARNESS_ERROR' for r in ROLES]
        checks[ident] = next((s for s in ('HARNESS_ERROR','FAIL','UNVERIFIED') if s in statuses),'PASS')
    return checks, verdicts


def cleanup_projects(out: Path, pair_dirs: list[Path]):
    """Delete only the two bound runtime copies of qualified takes after score write.

    Failed-take copies, originals, model calls, captures and action/state traces
    are retained. A durable per-path intent makes interrupted deletion resumable.
    """
    score_path = out/'playable_score.json'
    score = read_json(score_path)
    if not score.get('complete') or score.get('required_real_clients') != 2:
        raise HarnessError('runtime copy cleanup requires a qualified score')
    path = out/'pair_projects_cleanup.json'
    receipt = read_json(path) if path.exists() else {'score_sha256':sha256(score_path),'paths':{},'complete':False}
    if receipt['score_sha256'] != sha256(score_path):
        raise HarnessError('cleanup score binding changed')
    for pair in pair_dirs:
        proof = read_json(pair/'pair_receipt.json')
        if not proof.get('qualified'):
            continue
        binding = read_json(pair/'source_binding.json')
        launch = read_json(pair/'launch.json')
        for role in ROLES:
            target = pair/'projects'/role
            key = str(target)
            if receipt['paths'].get(key,{}).get('complete'):
                continue
            if target.is_symlink() or not target.resolve().is_relative_to(out.resolve()) or target.resolve() == Path(binding['project']).resolve() or Path(launch[role]['project']).resolve() != target.resolve():
                raise HarnessError('unsafe runtime cleanup ownership/path')
            if not proof['cleanup'][role].get('process_cleanup'):
                raise HarnessError('runtime process cleanup unproven')
            try: os.kill(launch[role]['pid'],0)
            except ProcessLookupError: pass
            else: raise HarnessError('recorded PID still exists; retain runtime copy')
            if key not in receipt['paths']:
                if not target.is_dir() or any(not (target/name).is_file() or sha256(target/name) != digest for name,digest in binding['files'].items()):
                    raise HarnessError('runtime authored files changed or absent before cleanup')
                receipt['paths'][key] = {'complete':False,'files':{str(p.relative_to(target)):p.stat().st_size for p in target.rglob('*') if p.is_file() and not p.is_symlink()},'reason':'qualified pair; owned runtime copy only'}
                write_json(path,receipt)
            if target.exists():
                shutil.rmtree(target)
            receipt['paths'][key].update(complete=True,deleted_bytes=sum(receipt['paths'][key]['files'].values()))
            write_json(path,receipt)
    receipt['complete'] = True
    receipt['deleted_bytes'] = sum(row.get('deleted_bytes',0) for row in receipt['paths'].values())
    write_json(path,receipt)
    return receipt


def run_playable(delivery_dir: Path, out: Path, *, models: dict) -> dict:
    """Runner API: actual Astra review, up to two 75s native pairs, existing rules."""
    delivery = read_json(Path(delivery_dir)/'delivery.json')
    if delivery['engine'] == 'unity3d':
        from . import dual_client_unity
        return dual_client_unity.run_playable(delivery_dir,out,models=models)
    out = Path(out).resolve(); out.mkdir(parents=True,exist_ok=True)
    with (out/'.dual_client.lock').open('a') as lock:
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as exc: raise HarnessError('this dual-client output is already owned') from exc
        project = (Path(delivery_dir)/delivery['project_root']).resolve()
        score_path = out/'playable_score.json'
        try:
            profile = profile_for(delivery,project)
            if score_path.exists():
                old = read_json(score_path)
                if not old.get('complete') or old.get('required_real_clients') != 2 or old.get('version') != VERSION:
                    raise HarnessError('refuse to overwrite prior diagnostic/incomplete score')
                receipt_path = out/old['pair_evidence_receipt']
                if not receipt_path.resolve().is_relative_to(out) or sha256(receipt_path) != old['pair_evidence_sha256']:
                    raise HarnessError('published pair receipt changed')
                if not verify_pair(receipt_path.parent,project)['qualified']:
                    raise HarnessError('published pair is unqualified')
                cleanup_projects(out,[out/p for p in old['takes']])
                write_json(out/'status.json',{'step':'playable','state':'done','complete':True,'required_real_clients':2})
                return old
            from .prepare import SAMPLES
            original_requirement = SAMPLES/delivery['game_id']/'general_requirement.txt'
            requirement = out/'input'/'requirement.txt'
            requirement.parent.mkdir(parents=True,exist_ok=True)
            if requirement.exists() and sha256(requirement) != sha256(original_requirement):
                raise HarnessError('frozen original requirement changed')
            if not requirement.exists(): shutil.copyfile(original_requirement,requirement)
            write_json(out/'manifest.json',{'version':VERSION,'delivery':delivery,'models':models,'duration_s':75,'required_real_clients':2,'requirement_source':str(original_requirement),'requirement_sha256':sha256(requirement)})
            pairs, feedback, qualified = [], None, []
            for take in (1,2):
                take_dir = out/'takes'/f'take_{take:02d}'
                write_json(out/'status.json',{'step':'dual_plan','state':'RUNNING','take':take,'complete':False,'required_real_clients':2})
                plan = make_plan(project,take_dir,profile=profile,model=models.get('planner'),requirement=requirement,feedback=feedback)
                pair = take_dir/'pair'
                if (pair/'pair_receipt.json').exists():
                    receipt = verify_pair(pair,project)
                elif pair.exists():
                    raise HarnessError('interrupted native attempt preserved; no implicit replay or overwrite')
                else:
                    if shutil.disk_usage(out).free < 8*(1<<30) + 2*sum((project/p).stat().st_size for p in source_hashes(project)):
                        raise HarnessError('insufficient disk for two copies plus 8GiB reserve')
                    write_json(out/'status.json',{'step':'dual_record','state':'RUNNING','take':take,'complete':False,'required_real_clients':2})
                    receipt = record_pair(project,pair,profile=profile,plan=plan)
                    verify_pair(pair,project)
                pairs.append(pair)
                checks, verdicts = _rules(out,pairs)
                if receipt['qualified']: qualified.append(pair)
                feedback = {'checks':checks,'client_checks':verdicts,'pair_qualified':receipt['qualified'],'pair_error':receipt.get('error')}
                write_json(take_dir/'evaluation.json',feedback)
                if checks['play.operate'] == 'PASS' and receipt['qualified']:
                    break
            if not qualified:
                kind = receipt.get('failure_kind')
                raise (ProductLimitation if kind == 'PRODUCT_LIMITATION' else HarnessError)(receipt.get('error','no qualified native interaction pair'))
            checks, verdicts = _rules(out,qualified)
            if 'HARNESS_ERROR' in checks.values():
                raise HarnessError('paired playable evidence incomplete; no score')
            selected = qualified[-1]/'pair_receipt.json'
            result = {'version':VERSION,'game_id':delivery['game_id'],'engine':'godot','planner':models['planner'],
                      'plan_origin':'accepted Astra source review before each native take','duration_s':75,
                      'required_real_clients':2,'complete':True,'checks':checks,'client_checks':verdicts,
                      'playable':round(100*sum(v=='PASS' for v in checks.values())/3,2),
                      'takes':[str(p.relative_to(out)) for p in pairs],
                      'pair_evidence_receipt':str(selected.relative_to(out)),'pair_evidence_sha256':sha256(selected)}
            write_json(score_path,result)
            cleanup_projects(out,pairs)
            write_json(out/'status.json',{'step':'playable','state':'done','complete':True,'required_real_clients':2})
            return result
        except Exception as exc:
            write_json(out/'status.json',{'step':'dual_client','state':'PRODUCT_LIMITATION' if isinstance(exc,ProductLimitation) else 'HARNESS_ERROR','complete':False,'required_real_clients':2,'error':str(exc)})
            raise


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--delivery-dir',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--planner',default=PLANNER_MODEL)
    args = parser.parse_args()
    print(json.dumps(run_playable(args.delivery_dir,args.out,models={'planner':args.planner}),ensure_ascii=False,indent=2))
