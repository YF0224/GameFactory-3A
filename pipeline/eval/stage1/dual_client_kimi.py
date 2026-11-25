"""Stage1 playable pairs: independent engine processes, native input, replicated state.

Kimi G043 only; no single-client fallback. ``run_playable(delivery_dir, out, *, models)``
is the runner interface; ``record_pair(project, out, *, profile)`` is the native probe.
An unqualified pair writes diagnostics/status, never playable_score.json.
"""
from __future__ import annotations

from ..model_config import PLANNER_MODEL

from contextlib import contextmanager, ExitStack
import fcntl
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

from .paths import read_profiles
from .paths import BENCH, FRAMEWORK, read_json, write_json, sha256
from .llm import HarnessError
from .prepare import IGNORE
from . import playable_rules

from .dual_client_kimi_plan import PROTOCOL as VERSION, DURATION_S, make_plan
OBSERVER = Path(__file__).with_name('dual_client_kimi_observer.gd')
ROLES = ('host', 'client')
LOADED_MODULE_SHA256 = sha256(Path(__file__))


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


def require_official():
    if Path(__file__).resolve() != FRAMEWORK/'pipeline/eval/stage1/dual_client_kimi.py':
        raise HarnessError('draft is offline review only; integrate official module before evaluation')
    if sha256(Path(__file__)) != LOADED_MODULE_SHA256:
        raise HarnessError('loaded Kimi module differs from current producer')


def review_target(target: dict, *, scope_path: Path | None = None) -> dict:
    profile = read_profiles(Path(__file__).with_name('dual_client_kimi_profiles.json'), reader=read_json)['kimi_g043']
    if target != profile['target']:
        raise HarnessError('unsupported or rebound Kimi target; no single-client fallback')
    scope = Path(scope_path or profile['scope_path'])
    if scope.resolve() != Path(profile['scope_path']).resolve() or sha256(scope) != profile['scope_sha256']:
        raise HarnessError('frozen Kimi60 scope changed')
    if target not in read_json(scope)['targets'] or sha256(Path(target['source'])) != profile['selection_sha256']:
        raise HarnessError('frozen selection mismatch')
    source = profile['source_manifest']
    if sha256(Path(source['path'])) != source['sha256']:
        raise HarnessError('original manifest changed')
    manifest = read_json(Path(source['path']))
    project = Path(target['project'])
    actual = {str(p.relative_to(project)):sha256(p) for p in project.rglob('*') if p.is_file() and not p.is_symlink()}
    if manifest['symlinks'] or any(p.is_symlink() for p in project.rglob('*')) or actual != manifest['files']:
        raise HarnessError('original differs from historical frozen admission, including delivered assets')
    if sha256(Path(profile['requirement']['path'])) != profile['requirement']['sha256']:
        raise HarnessError('original requirement changed')
    return profile


def profile_for(delivery: dict, project: Path) -> str:
    p = read_profiles(Path(__file__).with_name('dual_client_kimi_profiles.json'), reader=read_json)['kimi_g043']
    t = p['target']
    if (delivery.get('model', '').lower() != 'kimi' or delivery.get('game_id') != t['game_id']
        or delivery.get('engine') != 'godot' or delivery.get('required_real_clients') != 2
        or delivery.get('source_of_selection') != t['source'] or project.resolve() != Path(t['project']).resolve()):
        raise HarnessError('delivery is not frozen Kimi G043 Godot two-client identity')
    review_target(t)
    return 'kimi_g043'


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
    if profile != 'kimi_g043':
        raise HarnessError('unreviewed native entry')
    pair.wait(lambda: all((pair.out/r/'latest.json').exists() for r in ROLES))
    pair.pause(1)
    pair.send('host','click',text='创建厨房（生成房间码）')
    room = pair.wait(lambda: pair.states()['host']['room'])
    if len(room) != 4 or not room.isdigit():
        raise ProductLimitation('authored UI did not create a four-digit room')
    pair.send('client','text',text=room,placeholder='房间码（4 位）')
    pair.send('client','click',text='加入房间')
    pair.wait(lambda: all(pair.states()[r]['peers'] for r in ROLES))
    for role in ROLES:
        pair.send(role,'click',text='准备')
    # Let the original five-second opening CG/countdown complete naturally.
    pair.wait(lambda: all(pair.states()[r]['state']['phase'] == 'play' for r in ROLES), timeout=16)


def record_pair(project: Path, out: Path, *, profile: str, plan: dict) -> dict:
    """Run one new Godot pair; output must not exist. No scores or model calls."""
    require_official()
    from .record import godot_executable
    project, out = Path(project).resolve(), Path(out).resolve()
    validate_native_plan(project, out.parent, plan)
    binary = godot_executable()
    if not binary:
        raise HarnessError('Godot executable unavailable')
    if out.exists():
        raise HarnessError('pair attempt already exists; preserve evidence and use a new revision')
    out.mkdir(parents=True)
    baseline = source_hashes(project)
    import uuid
    session = uuid.uuid4().hex
    producer = producer_snapshot()
    write_json(out/'producer_start.json', producer)
    for name, digest in producer.items():
        blob = out/'producer_blobs'/digest
        blob.parent.mkdir(exist_ok=True)
        if not blob.exists(): shutil.copyfile(BENCH/name, blob)
        if sha256(blob) != digest: raise HarnessError('producer changed while archiving')
    if plan.get('protocol') != VERSION or plan.get('duration_s') != DURATION_S or plan.get('planner') != PLANNER_MODEL:
        raise HarnessError('record_pair requires a persisted Astra-reviewed 75-second plan')
    if read_json(out.parent/'plan.json') != plan:
        raise HarnessError('persisted plan differs from dispatched plan')
    write_json(out/'plan.json', plan)
    write_json(out/'source_binding.json', {'project':str(project),'files':baseline,'observer_sha256':sha256(OBSERVER), 'module_sha256':sha256(Path(__file__)), 'profile':profile,'session':session})
    copies = {}
    for role in ROLES:
        copies[role] = out/'projects'/role
        shutil.copytree(project,copies[role],ignore=IGNORE)
        (out/role).mkdir()
        if source_hashes(copies[role]) != baseline:
            raise HarnessError('runtime copy differs from original')
    processes, logs, commands, cleanup = {}, {}, {}, {}
    receipt = {'version':VERSION,'duration_s':DURATION_S,'required_real_clients':2,'qualified':False,'profile':profile,'session':session,
               'plan_sha256':sha256(out/'plan.json'),'source_binding_sha256':sha256(out/'source_binding.json')}
    try:
        with pair_slots(float(os.environ.get('A3GAME_GUI_WAIT_S','3600'))) as slots:
            receipt['gui_slots'] = slots
            validate_native_plan(project,out.parent,plan)
            if producer_snapshot() != producer:
                raise HarnessError('producer changed while waiting for GUI ownership; no native dispatch')
            if shutil.disk_usage(out).free < 8*(1<<30):
                raise HarnessError('8GiB native reserve exhausted while waiting for GUI ownership')
            for role in ROLES:
                home = out/'users'/role
                home.mkdir(parents=True,exist_ok=True)
                env = dict(os.environ, HOME=str(home), XDG_DATA_HOME=str(home/'data'), XDG_CONFIG_HOME=str(home/'config'), XDG_CACHE_HOME=str(home/'cache'))
                log = out/role/'import.log'
                cmd = [binary,'--headless','--path',str(copies[role]),'--editor','--import']
                with log.open('w') as stream:
                    try:
                        imported = subprocess.run(cmd,stdout=stream,stderr=subprocess.STDOUT,timeout=120,env=env)
                    except subprocess.TimeoutExpired:
                        write_json(out/role/'import_result.json', {'exit_code':None,'timeout':True,'command':cmd})
                        raise
                from .native_log import godot_product_errors
                product_errors = bool(godot_product_errors(log.read_text(errors='replace')))
                write_json(out/role/'import_result.json', {'exit_code':imported.returncode,'timeout':False,'product_errors':product_errors,'command':cmd})
                if imported.returncode or product_errors:
                    raise ProductLimitation(f'{role} original product import failed; inspect import.log; no qualified pair')
            for role in ROLES:
                commands[role] = [binary,'--path',str(copies[role]),'--resolution','1280x720',
                                  '-s',str(OBSERVER),'--',f'--pair-output={out/role}',
                                  f'--pair-profile={profile}',f'--pair-role={role}',f'--pair-session={session}']
                home = out/'users'/role
                home.mkdir(parents=True,exist_ok=True)
                env = dict(os.environ, HOME=str(home), XDG_DATA_HOME=str(home/'data'), XDG_CONFIG_HOME=str(home/'config'), XDG_CACHE_HOME=str(home/'cache'))
                logs[role] = (out/role/'engine.log').open('w')
                processes[role] = subprocess.Popen(commands[role],stdout=logs[role],stderr=subprocess.STDOUT,start_new_session=True,env=env)
            write_json(out/'launch.json', {r:{'pid':p.pid,'command':commands[r],'project':str(copies[r])} for r,p in processes.items()})
            pair = Pair(out,processes)
            try:
                pair.wait(lambda: all((out/r/'observer_ready.json').exists() for r in ROLES))
                for r in ROLES:
                    ready = read_json(out/r/'observer_ready.json')
                    if ready['pid'] != processes[r].pid or ready['session'] != session or not Path(ready['user_data']).resolve().is_relative_to((out/'users'/r).resolve()):
                        raise HarnessError('native user-data isolation not proven')
                write_json(out/'capture_start.json', {'session':session,'start_unix':time.time()+1.0})
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
        write_json(out/'producer_end.json', producer_snapshot())
        receipt['producer_unchanged'] = read_json(out/'producer_end.json') == producer
        receipt['cleanup'] = cleanup
        receipt['recording'] = {r:read_json(out/r/'recording_complete.json') if (out/r/'recording_complete.json').exists() else {} for r in ROLES}
        receipt['source_unchanged'] = source_hashes(project) == baseline
        receipt['runtime_authored_unchanged'] = all(all(sha256(copies[r]/name)==digest for name,digest in baseline.items()) for r in ROLES)
        for role in ROLES:
            path = out/role/'input_view_cleanup.json'
            cleanup.setdefault(role,{})['input_view'] = read_json(path) if path.exists() else None
        receipt['qualified'] = bool(receipt['qualified'] and receipt['producer_unchanged'] and all(75000 <= receipt['recording'][r].get('duration_ms',0) < 78000 for r in ROLES) and receipt['source_unchanged'] and receipt['runtime_authored_unchanged'] and all(cleanup[r].get('exit_code') == 0 and not cleanup[r].get('forced') and cleanup[r].get('input_view',{} ) and cleanup[r]['input_view'].get('input_cleanup') for r in ROLES))
        receipt['evidence_sha256'] = {str(p.relative_to(out)):sha256(p) for r in ROLES for p in (out/r).rglob('*') if p.is_file()}
        receipt['root_evidence_sha256'] = {n:sha256(out/n) for n in ('launch.json','capture_start.json','producer_start.json','producer_end.json') if (out/n).is_file()}
        write_json(out/'pair_receipt.json',receipt)
    return receipt


def _verify_pair_base(pair_dir: Path, project: Path) -> dict:
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


def _rules(out, pairs, *, write_reports=True):
    verdicts = {}
    for role in ROLES:
        takes = [(i+1,p/role) for i,p in enumerate(pairs)]
        imp = playable_rules._import(out,'godot',[p for _,p in takes])
        launch, launch_stats = playable_rules._launch(takes)
        operate, operate_stats = playable_rules._operate(takes)
        verdicts[role] = dict(zip(playable_rules.IDS,(imp,launch,operate)))
        if write_reports: write_json(pairs[-1]/role/'playable_rules.json', {'verdicts':verdicts[role],'launch':launch_stats,'operate':operate_stats})
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
    if (out/'qualification_hold.json').exists() and read_json(out/'qualification_hold.json').get('cache_policy') == 'KEEP_PROJECTS':
        raise HarnessError('KEEP_PROJECTS prohibits cache deletion; parent cleanup requires separate authorization')
    score_path = out/'playable_score.json'
    score = read_json(score_path)
    if not score.get('complete') or score.get('required_real_clients') != 2:
        raise HarnessError('runtime copy cleanup requires a qualified score')
    path = out/'pair_projects_cleanup.json'
    receipt = read_json(path) if path.exists() else {'score_sha256':sha256(score_path),'paths':{},'complete':False}
    if receipt['score_sha256'] != sha256(score_path):
        raise HarnessError('cleanup score binding changed')
    for pair in pair_dirs:
        proof = verify_pair(pair, Path(read_json(pair/'source_binding.json')['project']))
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


def _write_pair_score(out, delivery, models, pairs, qualified, checks, verdicts):
    """Shared score construction for normal execution and verified offline closure."""
    selected = qualified[-1]/'pair_receipt.json'
    result = {'version':VERSION,'game_id':delivery['game_id'],'engine':'godot','planner':models['planner'],
              'plan_origin':'accepted Astra source review before each native take','duration_s':75,
              'required_real_clients':2,'complete':True,'checks':checks,'client_checks':verdicts,
              'playable':round(100*sum(v=='PASS' for v in checks.values())/3,2),
              'takes':[str(p.relative_to(out)) for p in pairs],
              'pair_evidence_receipt':str(selected.relative_to(out)),'pair_evidence_sha256':sha256(selected)}
    write_json(out/'playable_score.json',result)
    return result


def _run_playable(delivery_dir: Path, out: Path, *, models: dict) -> dict:
    """Runner API: actual Astra review, up to two 75s native pairs, existing rules."""
    require_official()
    delivery = read_json(Path(delivery_dir)/'delivery.json')
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
                write_json(out/'status.json',{'step':'pair_finalize','state':'QUALIFICATION_PENDING','complete':False,'required_real_clients':2})
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
            result = _write_pair_score(out, delivery, models, pairs, qualified, checks, verdicts)
            write_json(out/'status.json',{'step':'pair_finalize','state':'QUALIFICATION_PENDING','complete':False,'required_real_clients':2})
            return result
        except Exception as exc:
            write_json(out/'status.json',{'step':'dual_client','state':'PRODUCT_LIMITATION' if isinstance(exc,ProductLimitation) else 'HARNESS_ERROR','complete':False,'required_real_clients':2,'error':str(exc)})
            raise



# Only this new module's closure is checked here. The Kimi runner additionally
# archives/checks its full producer; historical completions use archived bytes.
PRODUCER_NAMES = (
    'dual_client_kimi.py', 'dual_client_kimi_plan.py',
    'dual_client_kimi_profiles.json', 'dual_client_kimi_observer.gd',
    'paths.py', 'llm.py', 'prepare.py', 'delivery.py', 'playable_rules.py',
    'native_log.py', 'record.py',
)


def producer_snapshot():
    root = FRAMEWORK/'pipeline/eval/stage1'
    return {str((root/n).relative_to(BENCH)):sha256(root/n) for n in PRODUCER_NAMES}


def _contained(root, relative):
    path = root/relative
    if Path(relative).is_absolute() or '..' in Path(relative).parts or path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise HarnessError('evidence path escapes its owner')
    return path


def _same_capture_epoch(actual, expected):
    """Exact clock identity, allowing only the observed Godot JSON decimal form.

    No relative epsilon: at Unix epoch scale it would admit seconds of drift.
    Both fields must be finite numbers; the only alternate value is the exact
    15-significant-digit serialization, capped to five microseconds.
    """
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in (actual, expected)):
        return False
    return actual == expected or (
        actual == float(format(expected, '.15g')) and abs(actual - expected) <= .000005
    )


def verify_pair(pair_dir: Path, project: Path) -> dict:
    pair_dir, project = Path(pair_dir).resolve(), Path(project).resolve()
    receipt = _verify_pair_base(pair_dir, project)
    # Qualification is not inferred from a receipt flag; bind the original
    # selection, producer archive, complete native traces and both clocks.
    profile = read_profiles(Path(__file__).with_name('dual_client_kimi_profiles.json'), reader=read_json)['kimi_g043']
    review_target(profile['target'])
    if project != Path(profile['project']).resolve() or receipt.get('profile') != 'kimi_g043':
        raise HarnessError('pair is not the frozen Kimi G043 original')
    if not receipt['qualified']:
        return receipt
    required_roots = {'launch.json','capture_start.json','producer_start.json','producer_end.json'}
    if set(receipt.get('root_evidence_sha256',{})) != required_roots:
        raise HarnessError('missing root provenance')
    for name, digest in receipt['root_evidence_sha256'].items():
        if sha256(_contained(pair_dir,name)) != digest:
            raise HarnessError('native root provenance changed')
    start = read_json(pair_dir/'producer_start.json')
    if start != read_json(pair_dir/'producer_end.json') or not receipt.get('producer_unchanged'):
        raise HarnessError('actual producer drift retained; qualification held')
    expected_names = {str((FRAMEWORK/'pipeline/eval/stage1'/n).relative_to(BENCH)) for n in PRODUCER_NAMES}
    if set(start) != expected_names:
        raise HarnessError('producer dependency closure incomplete')
    for digest in start.values():
        if sha256(_contained(pair_dir,'producer_blobs/'+digest)) != digest:
            raise HarnessError('recorded producer archive changed')
    binding = read_json(pair_dir/'source_binding.json')
    plan = read_json(pair_dir/'plan.json')
    if plan.get('profile') != 'kimi_g043' or not plan['review']['entry_supported'] or plan.get('required_real_clients') != 2:
        raise HarnessError('accepted plan is not a supported two-client entry')
    if plan['source_sha256'] != profile['reviewed_sha256'] or plan['requirement_sha256'] != profile['requirement']['sha256']:
        raise HarnessError('plan source/requirement differs from reviewed original')
    module_key = 'pipeline/eval/stage1/dual_client_kimi.py'
    observer_key = 'pipeline/eval/stage1/dual_client_kimi_observer.gd'
    if binding['module_sha256'] != start[module_key] or binding['observer_sha256'] != start[observer_key] or plan['observer_sha256'] != start[observer_key]:
        raise HarnessError('dispatched observer/module differs from archived producer')
    if not receipt.get('source_unchanged') or not receipt.get('runtime_authored_unchanged'):
        raise HarnessError('authored source mutated')
    launch = read_json(pair_dir/'launch.json')
    barrier = read_json(pair_dir/'capture_start.json')
    session = receipt['session']
    if not session or binding['session'] != session or barrier['session'] != session:
        raise HarnessError('capture session mismatch')
    traces, actions = {}, {}
    for role in ROLES:
        root = pair_dir/role
        required = {'process.json','observer_ready.json','recording_complete.json','input_view_cleanup.json',
                    'frame_index.jsonl','state_trace.jsonl','actions.jsonl','engine.log','import.log','import_result.json'}
        if not {role+'/'+n for n in required} <= receipt['evidence_sha256'].keys():
            raise HarnessError('missing native evidence hash coverage')
        native = read_json(root/'process.json')
        recording = read_json(root/'recording_complete.json')
        ready = read_json(root/'observer_ready.json')
        clean = read_json(root/'input_view_cleanup.json')
        for row in (native,recording,ready,clean):
            if row['role'] != role or row['pid'] != launch[role]['pid'] or row['session'] != session:
                raise HarnessError('native observer identity/session mismatch')
        if clean != receipt['cleanup'][role]['input_view']:
            raise HarnessError('cleanup receipt does not match native exit acknowledgement')
        if not _same_capture_epoch(native['capture_epoch'], barrier['start_unix']) or not _same_capture_epoch(recording['capture_epoch'], barrier['start_unix']) or native['capture_epoch'] != recording['capture_epoch'] or not 0 <= native['origin_unix']-barrier['start_unix'] <= .25:
            raise HarnessError('clients did not start the shared capture window')
        if Path(launch[role]['project']).resolve() != (pair_dir/'projects'/role).resolve():
            raise HarnessError('runtime copy is not the role-owned path')
        if native['user_data'] != ready['user_data'] or not Path(native['user_data']).resolve().is_relative_to((pair_dir/'users'/role).resolve()):
            raise HarnessError('native user-data directories are not isolated')
        command = launch[role]['command']
        expected_tail = ['--',f'--pair-output={root}', '--pair-profile=kimi_g043',f'--pair-role={role}',f'--pair-session={session}']
        if command[command.index('--'):] != expected_tail or command[command.index('-s')+1] != str(FRAMEWORK/'pipeline/eval/stage1/dual_client_kimi_observer.gd'):
            raise HarnessError('unreviewed product arguments or observer dispatch')
        frames = _rows(root/'frame_index.jsonl')
        times = [f['t_ms'] for f in frames]
        if len(times) < 100 or times[0] > 1000 or times[-1] < 75000 or times != sorted(set(times)) or max(b-a for a,b in zip(times,times[1:])) > 2000:
            raise HarnessError('raw native frames do not cover the full 75s capture')
        for f in frames:
            key = role+'/'+f['path']
            if f['pid'] != native['pid'] or f['session'] != session or key not in receipt['evidence_sha256']:
                raise HarnessError('frame missing native identity/hash binding')
            _contained(pair_dir,key)
        traces[role], actions[role] = _rows(root/'state_trace.jsonl'), _rows(root/'actions.jsonl')
        for row in traces[role]+actions[role]:
            if row['pid'] != native['pid'] or row['session'] != session or not 0 <= row['t_ms'] <= recording['duration_ms']:
                raise HarnessError('trace/input is outside native identity or duration')
    proofs = receipt['interactions']
    planned = plan['review']['actions']
    if len(proofs) != len(planned):
        raise HarnessError('not all accepted native inputs have peer-visible evidence')
    for proof, expected in zip(proofs,planned):
        role, action = proof['actor'], proof['action']
        cmd = action['command']
        if role != expected['role'] or cmd.get('kind') != 'key' or cmd.get('key') != expected['key'] or cmd.get('duration') != expected['duration_s']:
            raise HarnessError('input differs from accepted bounded plan')
        if action.get('route') != 'Input.parse_input_event' or not action['ok'] or action['end_t_ms']-action['t_ms'] < expected['duration_s']*1000-50:
            raise HarnessError('no native held-key transport proof')
        if any(proof['before'][r]['unix'] >= action['unix'] or proof['after'][r]['unix'] <= action['unix'] for r in ROLES):
            raise HarnessError('replication observations do not bracket actual input')
        for r in ROLES:
            if proof['before'][r]['state']['phase'] != 'play' or proof['after'][r]['state']['phase'] != 'play' or proof['after'][r]['state']['authored_role'] != r:
                raise HarnessError('replication proof not from authored multiplayer play')
        other = 'client' if role == 'host' else 'host'
        if any(proof['before'][other]['unix'] < a['unix'] < proof['after'][other]['unix'] for a in actions[other]):
            raise HarnessError('peer was not idle during isolated input')
    return receipt


def _retained_files(out):
    """Exact evidence set; runner metadata and live status are outside this seal."""
    result = {}
    roots = [out/'takes',out/'input']
    if (out/EPOCH_RECOVERY).exists(): roots.append(out/EPOCH_RECOVERY)
    for root in roots:
        for directory, dirs, names in os.walk(root, followlinks=False):
            dirs[:] = [d for d in dirs if d not in ('projects','users','__pycache__')]
            for name in names:
                p = Path(directory,name)
                if p.is_symlink(): raise HarnessError('symlink in retained pair evidence')
                result[str(p.relative_to(out))] = sha256(p)
    for name in ('manifest.json','playable_score.json','qualification_hold.json','pair_projects_cleanup.json'):
        result[name] = sha256(out/name)
    return result


def _preserved_cache_receipt(out: Path, pairs: list[Path], *, check_live: bool = False):
    """Verify retained owned caches; native input/view/process cleanup stays mandatory."""
    receipt = {'schema':'stage1-kimi-pair-cache-policy.v1', 'cache_policy':'KEEP_PROJECTS',
               'score_sha256':sha256(out/'playable_score.json'), 'complete':True,
               'disposition':'PRESERVED', 'deleted_bytes':0, 'paths':{}, 'user_paths':{}}
    for pair in pairs:
        binding = read_json(pair/'source_binding.json')
        proof = verify_pair(pair, Path(binding['project']))
        if not proof['qualified']: continue
        launch = read_json(pair/'launch.json')
        for role in ROLES:
            if not proof['cleanup'][role].get('process_cleanup'):
                raise HarnessError('native process cleanup unproven; retain caches')
            if check_live:
                try: os.kill(launch[role]['pid'], 0)
                except ProcessLookupError: pass
                else: raise HarnessError('recorded PID still exists; cannot finalize retained caches')
            for kind, field in (('projects','paths'), ('users','user_paths')):
                target = pair/kind/role
                if target.is_symlink() or not target.is_dir() or target.resolve() != target.absolute() or not target.resolve().is_relative_to(out.resolve()):
                    raise HarnessError('retained cache absent or unsafe owned path')
                if kind == 'projects':
                    if target.resolve() == Path(binding['project']).resolve() or Path(launch[role]['project']).resolve() != target.resolve():
                        raise HarnessError('retained project ownership mismatch')
                    for name, digest in binding['files'].items():
                        source = target/name
                        if source.is_symlink() or not source.resolve().is_relative_to(target.resolve()) or not source.is_file() or sha256(source) != digest:
                            raise HarnessError('retained authored source changed or absent')
                receipt[field][str(target)] = {'disposition':'PRESERVED', 'deleted_bytes':0}
    return receipt


def _qualified_score(out, *, cleaned):
    if (out/EPOCH_RECOVERY).exists(): _verify_epoch_recovery(out)
    score = read_json(out/'playable_score.json')
    if not score.get('complete') or score.get('required_real_clients') != 2 or score.get('version') != VERSION or score.get('engine') != 'godot' or score.get('game_id') != 'G043_airship_kitchen':
        raise HarnessError('not a complete Kimi paired score')
    manifest = read_json(out/'manifest.json')
    project = Path(manifest['delivery']['project_root']).resolve()
    profile_for(manifest['delivery'],project)
    qualified, pairs = [], []
    for name in score['takes']:
        if name not in ('takes/take_01/pair','takes/take_02/pair'):
            raise HarnessError('attempt exceeds two-pair bound')
        pair = _contained(out,name)
        proof = verify_pair(pair, project)
        pairs.append(pair)
        if proof['qualified']: qualified.append(pair)
    if not qualified or len(set(score['takes'])) != len(pairs):
        raise HarnessError('no unique qualified pair')
    selected = qualified[-1]/'pair_receipt.json'
    if out/score['pair_evidence_receipt'] != selected or sha256(selected) != score['pair_evidence_sha256']:
        raise HarnessError('selected pair changed')
    checks, verdicts = _rules(out,qualified,write_reports=False)
    if 'HARNESS_ERROR' in checks.values() or checks != score['checks'] or verdicts != score['client_checks'] or score['playable'] != round(100*sum(v=='PASS' for v in checks.values())/3,2):
        raise HarnessError('score does not equal formal rules on native evidence')
    if cleaned:
        clean = read_json(out/'pair_projects_cleanup.json')
        policy = read_json(out/'qualification_hold.json').get('cache_policy', 'DELETE_QUALIFIED_COPIES')
        if policy == 'KEEP_PROJECTS':
            if clean != _preserved_cache_receipt(out, qualified):
                raise HarnessError('KEEP_PROJECTS cache receipt invalid or retained copies changed')
            return score
        if policy != 'DELETE_QUALIFIED_COPIES' or clean.get('cache_policy', 'DELETE_QUALIFIED_COPIES') != policy:
            raise HarnessError('unknown or mismatched cache policy')
        expected = {str(p/'projects'/r) for p in qualified for r in ROLES}
        if clean['score_sha256'] != sha256(out/'playable_score.json') or not clean['complete'] or set(clean['paths']) != expected:
            raise HarnessError('runtime copy cleanup binding incomplete')
        for name, row in clean['paths'].items():
            if not row.get('complete') or Path(name).exists() or row['deleted_bytes'] != sum(row['files'].values()):
                raise HarnessError('runtime cleanup has not completed')
        expected_users = {str(p/'users'/r) for p in qualified for r in ROLES}
        if set(clean.get('user_paths',{})) != expected_users or any(Path(n).exists() or not row['complete'] for n,row in clean['user_paths'].items()):
            raise HarnessError('isolated native user-data cleanup incomplete')
    return score


def qualified_completion_score(out: Path) -> dict | None:
    """Read-only, fail-closed runner gate. No recursion, model/native or writes."""
    try:
        out = Path(out).resolve()
        seal = read_json(out/'kimi_pair_completion.json')
        if seal.get('schema') != 'stage1-kimi-pair-completion.v1' or seal.get('evidence_files') != _retained_files(out):
            return None
        if seal['releases_hold_sha256'] != sha256(out/'qualification_hold.json'):
            return None
        score = _qualified_score(out,cleaned=True)
        return score if seal['score'] == score else None
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, IndexError):
        return None


def run_playable(delivery_dir: Path, out: Path, *, models: dict, scope_path: Path | None = None, keep_projects: bool = True) -> dict:
    """Official API; at most two accepted Astra plans and two real 75s pairs.

    The parent runner must route Kimi G043 completion here BEFORE its generic
    canonical-score/hold checks. Hold remains as provenance after the seal.
    """
    require_official()
    if type(keep_projects) is not bool:
        raise HarnessError('keep_projects must be an explicit boolean')
    cache_policy = 'KEEP_PROJECTS' if keep_projects else 'DELETE_QUALIFIED_COPIES'
    out = Path(out).resolve()
    p = read_profiles(Path(__file__).with_name('dual_client_kimi_profiles.json'), reader=read_json)['kimi_g043']
    review_target(p['target'],scope_path=scope_path)
    out.mkdir(parents=True,exist_ok=True)
    # Covers plan, pair, offline finalization and cleanup, not only native launch.
    with (out/'.kimi_pair.lock').open('a') as lock:
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as exc: raise HarnessError('Kimi pair identity already owned') from exc
        old = qualified_completion_score(out)
        if old is not None: return old
        if (out/'kimi_pair_completion.json').exists():
            raise HarnessError('sealed evidence failed revalidation; no replay')
        hold = out/'qualification_hold.json'
        if not hold.exists():
            write_json(hold,{'schema':'stage1-kimi-pair-hold.v1','reason':'requires sealed paired evidence, native cleanup and cache policy receipt','target':p['target'],'cache_policy':cache_policy})
        if read_json(hold).get('cache_policy', 'DELETE_QUALIFIED_COPIES') != cache_policy:
            raise HarnessError('existing hold cache policy differs; no implicit policy switch')
        result = _run_playable(delivery_dir,out,models=models)
        _qualified_score(out,cleaned=False)
        if keep_projects:
            write_json(out/'pair_projects_cleanup.json', _preserved_cache_receipt(out, [out/n for n in result['takes']], check_live=True))
        else:
            cleanup_projects(out,[out/n for n in result['takes']])
            clean = read_json(out/'pair_projects_cleanup.json')
            clean.setdefault('user_paths',{})
            for name in result['takes']:
                pair = out/name
                if not read_json(pair/'pair_receipt.json')['qualified']: continue
                for role in ROLES:
                    target = pair/'users'/role
                    key = str(target)
                    if target.is_symlink() or not target.resolve().is_relative_to(out):
                        raise HarnessError('unsafe user-data cleanup path')
                    if key not in clean['user_paths']:
                        if not target.is_dir(): raise HarnessError('user-data absent without deletion intent')
                        clean['user_paths'][key] = {'complete':False,'bytes':sum(p.stat().st_size for p in target.rglob('*') if p.is_file() and not p.is_symlink())}
                        write_json(out/'pair_projects_cleanup.json',clean)
                    if target.exists(): shutil.rmtree(target)
                    clean['user_paths'][key]['complete'] = True
                    write_json(out/'pair_projects_cleanup.json',clean)
        _qualified_score(out,cleaned=True)
        write_json(out/'kimi_pair_completion.json',{'schema':'stage1-kimi-pair-completion.v1',
                   'score':result,'releases_hold_sha256':sha256(hold),'evidence_files':_retained_files(out)})
        accepted = qualified_completion_score(out)
        if accepted is None: raise HarnessError('final completion verification failed; hold retained')
        write_json(out/'status.json',{'step':'playable','state':'done','complete':True,'required_real_clients':2})
        return accepted


def validate_native_plan(project, take_dir, plan):
    """No native/import call may bypass the persisted accepted source review."""
    from . import llm
    from .dual_client_kimi_plan import SCHEMA
    profile = read_profiles(Path(__file__).with_name('dual_client_kimi_profiles.json'), reader=read_json)['kimi_g043']
    review_target(profile['target'])
    if Path(project).resolve() != Path(profile['project']).resolve():
        raise HarnessError('unreviewed original project')
    if plan.get('protocol') != VERSION or plan.get('duration_s') != 75 or plan.get('required_real_clients') != 2 or plan.get('planner') != PLANNER_MODEL or plan.get('profile') != 'kimi_g043':
        raise HarnessError('invalid native plan identity/budget')
    if read_json(take_dir/'plan.json') != plan or plan['source_sha256'] != profile['reviewed_sha256'] or plan['requirement_sha256'] != profile['requirement']['sha256']:
        raise HarnessError('persisted source review binding changed')
    calls = take_dir/'model_calls'
    if llm.accepted_response(calls,'source_review') != plan['review'] or sha256(calls/'source_review/accepted_response.json') != plan['accepted_response_sha256']:
        raise HarnessError('no matching accepted model response')
    if sha256(OBSERVER) != plan['observer_sha256']:
        raise HarnessError('observer changed after model source review')
    llm.validate_schema(plan['review'],SCHEMA)
    if not plan['review']['entry_supported']:
        raise HarnessError('accepted review rejected native entry')
    for ref in plan['review']['source_references']:
        if ref['path'] not in profile['reviewed_sha256'] or ref['line'] > len((project/ref['path']).read_text().splitlines()):
            raise HarnessError('invalid source reference')
    for role in ROLES:
        keys = {a['key'] for a in plan['review']['actions'] if a['role'] == role}
        if not ({'D','A'} <= keys or {'W','S'} <= keys):
            raise HarnessError('each independent client needs opposing native movement probes')


EPOCH_RECOVERY = 'recovery/epoch_serialization_v1'
EPOCH_FAILURE = 'clients did not start the shared capture window'


def _verify_epoch_recovery(out):
    """Read-only provenance check, included in the normal completion gate."""
    root = _contained(out, EPOCH_RECOVERY)
    receipt = read_json(root/'receipt.json')
    if (receipt.get('schema') != 'stage1-kimi-pair-epoch-recovery.v1'
            or receipt.get('state') != 'READY_FOR_FINAL_SEAL'
            or receipt.get('output') != str(out.resolve())
            or receipt.get('new_model_calls') != 0 or receipt.get('new_native_takes') != 0
            or receipt.get('consumed_native_takes') != 1 or receipt.get('total_take_limit') != 2
            or receipt.get('cache_policy') != 'KEEP_PROJECTS'):
        raise HarnessError('invalid offline recovery lineage/budget')
    for name, digest in receipt['archive_sha256'].items():
        if sha256(_contained(root, 'before/'+name)) != digest:
            raise HarnessError('offline recovery parent archive changed')
    for name in ('_kimi_batch/failure.json', '_kimi_batch/attempt.json', 'qualification_hold.json'):
        if sha256(out/name) != receipt['archive_sha256'][name]:
            raise HarnessError('offline recovery original failure/claim/hold changed')
    pair = out/'takes/take_01/pair'
    if sha256(pair/'pair_receipt.json') != receipt['parent_pair_sha256']:
        raise HarnessError('offline recovered native receipt changed')
    claim = read_json(root/'claim.json')
    if (claim.get('schema') != 'stage1-kimi-pair-offline-claim.v1'
            or claim.get('parent_failure_sha256') != receipt['archive_sha256']['_kimi_batch/failure.json']
            or claim.get('parent_pair_sha256') != receipt['parent_pair_sha256']
            or claim.get('new_native_takes') != 0 or claim.get('new_model_calls') != 0
            or claim.get('total_take_limit') != 2):
        raise HarnessError('offline recovery claim binding/budget changed')
    producer = receipt['producer']
    native_producer = read_json(pair/'producer_start.json')
    key = 'pipeline/eval/stage1/dual_client_kimi.py'
    if set(producer) != set(native_producer) or any(producer[n] != native_producer[n] for n in producer if n != key):
        raise HarnessError('offline recovery producer closure differs')
    for digest in producer.values():
        if sha256(_contained(root, 'producer_blobs/'+digest)) != digest:
            raise HarnessError('offline recovery producer archive changed')
    if sha256(out/'playable_score.json') != receipt['score_sha256']:
        raise HarnessError('offline recovery score binding changed')
    return receipt


def recover_completed_pair(out: Path, *, expected_failure_sha256: str,
                           expected_pair_sha256: str, reviewed_module_sha256: str) -> dict:
    """One offline continuation of the exact epoch failure; never plan or record.

    Requires the only existing take to qualify and operate under formal rules.
    Does not release batch attempts or delete caches. The original failure/hold
    remain; qualified_completion_score is the sole completion authority.
    """
    require_official()
    if sha256(Path(__file__)) != reviewed_module_sha256:
        raise HarnessError('offline recovery module differs from reviewed patch')
    out = Path(out).resolve()
    if not out.is_dir(): raise HarnessError('existing paired output required')
    with (out/'.kimi_pair.lock').open('a') as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as exc: raise HarnessError('Kimi pair identity already owned') from exc
        root = out/EPOCH_RECOVERY
        failure = out/'_kimi_batch/failure.json'
        pair = out/'takes/take_01/pair'
        if sha256(failure) != expected_failure_sha256 or sha256(pair/'pair_receipt.json') != expected_pair_sha256:
            raise HarnessError('offline recovery parent failure/native receipt mismatch')
        old = qualified_completion_score(out)
        if root.exists():
            if old is not None: return old
            raise HarnessError('offline recovery already claimed; retain partial failure, no replay')
        if any((out/n).exists() for n in ('playable_score.json','kimi_pair_completion.json','pair_projects_cleanup.json')):
            raise HarnessError('existing score/cleanup/seal requires separate review')
        if set(p.name for p in (out/'takes').iterdir()) != {'take_01'}:
            raise HarnessError('offline epoch recovery requires exactly original take1')
        if read_json(failure).get('type') != 'HarnessError' or read_json(failure).get('error') != EPOCH_FAILURE:
            raise HarnessError('not the bounded shared-epoch failure')
        status = read_json(out/'status.json')
        if status.get('state') != 'HARNESS_ERROR' or status.get('error') != EPOCH_FAILURE:
            raise HarnessError('parent status is not the preserved epoch failure')
        hold = read_json(out/'qualification_hold.json')
        if hold.get('schema') != 'stage1-kimi-pair-hold.v1' or hold.get('cache_policy') != 'KEEP_PROJECTS':
            raise HarnessError('offline epoch recovery must retain KEEP_PROJECTS hold')
        manifest = read_json(out/'manifest.json')
        delivery, models = manifest['delivery'], manifest['models']
        if models.get('planner') != PLANNER_MODEL:
            raise HarnessError('offline recovery planner identity changed')
        project = Path(delivery['project_root']).resolve()
        profile_for(delivery, project)
        profile = review_target(hold['target'])
        if read_json(out/'_kimi_batch/attempt.json')['target'] != profile['target']:
            raise HarnessError('batch claim identity differs from frozen target')
        pids = [read_json(out/'_kimi_batch/attempt.json')['pid']]
        pids += [r['pid'] for r in read_json(pair/'launch.json').values()]
        for pid in pids:
            try: os.kill(pid, 0)
            except ProcessLookupError: pass
            else: raise HarnessError('recorded runner/native PID still exists; no offline mutation')
        native_producer = read_json(pair/'producer_start.json')
        producer = producer_snapshot()
        key = 'pipeline/eval/stage1/dual_client_kimi.py'
        if set(producer) != set(native_producer) or any(producer[n] != native_producer[n] for n in producer if n != key):
            raise HarnessError('unreviewed producer drift outside epoch recovery module')
        proof = verify_pair(pair, project)
        if not proof['qualified']: raise HarnessError('existing pair not qualified; no new take allowed here')
        checks, verdicts = _rules(out, [pair], write_reports=False)
        if 'HARNESS_ERROR' in checks.values() or checks['play.operate'] != 'PASS':
            raise HarnessError('existing pair cannot close normal take loop; coordinate remaining budget')
        root.mkdir(parents=True, exist_ok=False)
        try:
            archive = {}
            parents = [out/n for n in ('status.json','manifest.json','qualification_hold.json')]
            parents += [p for p in (out/'_kimi_batch').rglob('*') if p.is_file()]
            for path in parents:
                name = str(path.relative_to(out)); source = _contained(out, name)
                target = root/'before'/name; target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                archive[name] = sha256(source)
                if sha256(target) != archive[name]: raise HarnessError('parent changed during archive')
            for name, digest in producer.items():
                target = root/'producer_blobs'/digest; target.parent.mkdir(exist_ok=True)
                shutil.copyfile(BENCH/name, target)
                if sha256(target) != digest: raise HarnessError('producer changed during archive')
            write_json(root/'claim.json', {'schema':'stage1-kimi-pair-offline-claim.v1',
                       'parent_failure_sha256':expected_failure_sha256,'parent_pair_sha256':expected_pair_sha256,
                       'pid':os.getpid(),'new_native_takes':0,'new_model_calls':0,'total_take_limit':2})
            checks, verdicts = _rules(out, [pair])
            result = _write_pair_score(out, delivery, models, [pair], [pair], checks, verdicts)
            write_json(root/'receipt.json', {'schema':'stage1-kimi-pair-epoch-recovery.v1',
                       'state':'READY_FOR_FINAL_SEAL','output':str(out),'archive_sha256':archive,
                       'parent_pair_sha256':expected_pair_sha256,'producer':producer,
                       'score_sha256':sha256(out/'playable_score.json'),'new_model_calls':0,
                       'new_native_takes':0,'consumed_native_takes':1,'total_take_limit':2,
                       'cache_policy':'KEEP_PROJECTS'})
            _qualified_score(out, cleaned=False)
            write_json(out/'pair_projects_cleanup.json', _preserved_cache_receipt(out, [pair], check_live=True))
            _qualified_score(out, cleaned=True)
            if producer_snapshot() != producer: raise HarnessError('offline finalizer producer drift; hold retained')
            write_json(out/'kimi_pair_completion.json', {'schema':'stage1-kimi-pair-completion.v1',
                       'score':result,'releases_hold_sha256':sha256(out/'qualification_hold.json'),
                       'evidence_files':_retained_files(out)})
            accepted = qualified_completion_score(out)
            if accepted is None: raise HarnessError('offline completion failed strict revalidation')
            write_json(out/'status.json', {'step':'playable','state':'done','complete':True,
                       'required_real_clients':2,'recovery':EPOCH_RECOVERY})
            return accepted
        except Exception as exc:
            write_json(root/'failure.json', {'type':type(exc).__name__,'error':str(exc),
                       'new_native_takes':0,'new_model_calls':0,'complete':False})
            raise


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Offline only: preserve and finalize completed G043 take1')
    parser.add_argument('--recover-completed-pair', required=True, type=Path)
    parser.add_argument('--failure-sha256', required=True)
    parser.add_argument('--pair-sha256', required=True)
    parser.add_argument('--reviewed-module-sha256', required=True)
    args = parser.parse_args()
    result = recover_completed_pair(args.recover_completed_pair,
        expected_failure_sha256=args.failure_sha256, expected_pair_sha256=args.pair_sha256,
        reviewed_module_sha256=args.reviewed_module_sha256)
    print(json.dumps(result, ensure_ascii=False, indent=2))
