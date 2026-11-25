"""Two independent UE clients for the three basic Playable checks.

Explicit user-authorized independent-client mode, not a network qualification.
Both isolated authored copies launch concurrently under the existing pair lease.
Each client uses the unchanged native recorder and stage1 Playable rules; a check
passes for the pair only when it passes for both clients. No multiplayer claim.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path
import subprocess
import time

from . import plan, prepare, record, playable_rules
from .dual_client import pair_slots
from .llm import HarnessError
from .paths import read_json, write_json, sha256

VERSION = 'stage1-independent-ue-pair.v1'
MODE = 'two_independent_clients'
CLIENTS = ('client_1', 'client_2')


def aggregate(client_checks):
    """Keep tool errors unscored; require both clients for each PASS."""
    if set(client_checks) != set(CLIENTS):
        raise HarnessError('two independent client results are required')
    result = {}
    for key in playable_rules.IDS:
        values = [client_checks[c].get(key) for c in CLIENTS]
        if any(v not in ('PASS', 'FAIL', 'UNVERIFIED') for v in values):
            raise HarnessError('client rule evidence incomplete: ' + key)
        result[key] = 'FAIL' if 'FAIL' in values else 'UNVERIFIED' if 'UNVERIFIED' in values else 'PASS'
    return result


def short_manifest(manifest):
    budget = dict(manifest['budget'])
    extra = 75000 - budget['gameplay_ms']
    for key in ('gameplay_ms', 'recording_ms', 'total_wall_clock_ms'):
        budget[key] += extra
    budget['engine_call_ms'] = max(budget['engine_call_ms'] + extra, budget['total_wall_clock_ms'])
    return {**manifest, 'budget': budget}


def validate_request(delivery, authorization):
    if delivery.get('engine') != 'ue5' or delivery.get('required_real_clients') != 2:
        raise HarnessError('this entry requires an authored UE two-client delivery')
    if authorization.get('mode') != MODE or authorization.get('user_instruction') != '双端可以启动两个独立的客户端':
        raise HarnessError('independent-client user authorization is required')
    if authorization.get('network_qualification') is not False:
        raise HarnessError('independent clients cannot qualify multiplayer synchronization')


def _client_record(out, manifest, executable, take, client, admitted):
    runtime = plan.take_dir(out, take) / 'record'
    native = runtime / 'native'
    native.mkdir(parents=True, exist_ok=False)
    actions = plan.native_actions(executable, 'ue5')
    write_json(runtime / 'action_schedule.json', {'version': record.VERSION, 'actions': actions})
    map_path = '' if executable['launch_source'].endswith('.uproject') else executable['launch_source']
    result = record._ue_record(client, actions, native, manifest['budget'],
                               time.monotonic() + manifest['budget']['engine_call_ms']/1000,
                               admitted, map_path)
    write_json(runtime / 'adapter_result.json', result)
    summary = record._collect(runtime, native / 'take')
    crash = record.record_game_crash(runtime, native / 'take')
    if crash:
        summary['game_crash'] = {k: crash[k] for k in ('signal', 't_ms', 'game_frames')}
    if summary['failed_actions'] or not summary['frames']:
        raise HarnessError('native client has missing frames or undelivered actions')
    summary.update(version=record.VERSION, engine='ue5', take=take,
                   plan_sha256=sha256(plan.take_dir(out, take)/'plan.json'),
                   pair_mode=MODE, native_verification=str(native/'take/verification.json'))
    write_json(runtime/'record_result.json', summary)
    return summary


def _overlap_sample(children, take):
    observed = {}
    for name, out in children.items():
        native = plan.take_dir(out, take)/'record/native/take'
        launch, ready = native/'launch.json', native/'play_started.json'
        if not launch.is_file() or not ready.is_file():
            return None
        launch, ready = read_json(launch), read_json(ready)
        pid = launch['pid']
        if ready.get('pid') != pid:
            raise HarnessError('native client PID mismatch')
        command = subprocess.run(['ps', '-p', str(pid), '-o', 'command='], capture_output=True, text=True).stdout.strip()
        manifest = read_json(out/'manifest.json')
        uproject = str((out/'runtime/project'/manifest['entry']).resolve())
        if uproject not in command:
            return None
        observed[name] = {'pid': pid, 'port': launch['port'], 'command': command,
                          'launch_sha256': sha256(native/'launch.json'),
                          'ready_sha256': sha256(native/'play_started.json')}
    if len({v['pid'] for v in observed.values()}) != 2 or len({v['port'] for v in observed.values()}) != 2:
        raise HarnessError('independent client PID/port collision')
    return {'observed_monotonic': time.monotonic(), 'clients': observed,
            'concurrent_independent_processes': True, 'network_qualified': False}


def run_playable(delivery_dir, out, *, models, authorization):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    validate_request(read_json(Path(delivery_dir)/'delivery.json'), authorization)
    if (out/'playable_score.json').exists():
        raise HarnessError('preserve the existing pair score; no duplicate execution')
    write_json(out/'authorization.json', authorization)
    children = {name: out/name for name in CLIENTS}
    manifests = {name: prepare.prepare(delivery_dir, child, models=models, suite='stage1', playable_only=True)
                 for name, child in children.items()}
    if len({m['project_digest'] for m in manifests.values()}) != 1:
        raise HarnessError('the two clients must have the same original source digest')
    write_json(out/'manifest.json', {'version': VERSION, 'mode': MODE, 'models': models,
               'client_manifests': {n: str(p/'manifest.json') for n,p in children.items()},
               'source_digest': next(iter(manifests.values()))['project_digest'],
               'network_qualification': False})
    feedback = {n: None for n in CLIENTS}
    history, verdicts = [], {}
    for take in range(1, 3):
        executable, short = {}, {}
        for name, child in children.items():
            prepare.verify(child)
            short[name] = short_manifest(manifests[name])
            write_json(out/'status.json', {'state':'PLANNING', 'client':name, 'take':take})
            executable[name] = plan.make_plan(child, short[name], take, ['play.launch','play.operate'], feedback[name])
            if executable[name].get('state_entry'):
                raise HarnessError('basic independent-client mode excludes direct state entry')
        # The formal pair lock excludes other GUI work throughout both admissions
        # and concurrent recordings; each child additionally retains its take lock.
        with pair_slots(), ExitStack() as stack:
            clients, admitted = {}, {}
            for name, child in children.items():
                stack.enter_context(record._record_lock(child, take))
                native = plan.take_dir(child, take)/'record/native'
                if native.exists():
                    raise HarnessError('preserve unfinished native take; explicit recovery required')
                project = (child/'runtime/project').resolve()
                clients[name] = record.make_client('ue5', project)
                admitted[name] = record._ue_admission(clients[name], project, child, time.monotonic()+1800)
            write_json(out/'status.json', {'state':'RECORDING_TWO_INDEPENDENT_CLIENTS', 'take':take})
            overlap = None
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = {n: pool.submit(_client_record, children[n], short[n], executable[n], take, clients[n], admitted[n]) for n in CLIENTS}
                while not all(f.done() for f in futures.values()):
                    if overlap is None:
                        overlap = _overlap_sample(children, take)
                        if overlap:
                            write_json(out/f'concurrency_take_{take}.json', overlap)
                    time.sleep(.2)
                results, errors = {}, {}
                for name, future in futures.items():
                    try:
                        results[name] = future.result()
                    except Exception as exc:
                        errors[name] = f'{type(exc).__name__}: {exc}'
                if errors:
                    write_json(out/f'pair_errors_take_{take}.json', errors)
                    raise HarnessError('independent native client recording failed: '+str(errors))
            if overlap is None:
                raise HarnessError('no evidence that both ready clients were alive concurrently')
        checks = {}
        for name, child in children.items():
            verdicts[name] = playable_rules.evaluate(child, manifests[name], take)
            checks[name] = {k:v['status'] for k,v in verdicts[name].items()}
            feedback[name] = {'earlier_plans':[read_json(plan.take_dir(child,k)/'plan.json')['summary'] for k in range(1,take+1)],
                              'judge_reasons':{'play.operate':verdicts[name].get('play.operate',{}).get('reason','')}}
        pair_checks = aggregate(checks)
        history.append({'take':take,'checks':pair_checks,'client_checks':checks})
        if pair_checks['play.operate']=='PASS' or pair_checks['play.launch']=='FAIL':
            break
    result = {'version':playable_rules.VERSION, 'pair_protocol':VERSION, 'client_mode':MODE,
              'game_id':next(iter(manifests.values()))['game_id'], 'engine':'ue5',
              'planner':models['planner'], 'judge':None, 'required_real_clients':2,
              'network_qualified':False, 'checks':pair_checks, 'client_verdicts':verdicts,
              'takes':history, 'complete':True,
              'playable':round(100*sum(v=='PASS' for v in pair_checks.values())/3,2)}
    write_json(out/'playable_score.json',result)
    write_json(out/'status.json',{'state':'COMPLETE','complete':True,'mode':MODE,'network_qualified':False})
    return result
