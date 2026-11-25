"""Bounded Stage1 Unity G014 pairs; no scoring models or old scoring entrypoints.

API: run_playable(delivery_dir, out, models={'planner': 'gpt-6-astra'}).
The caller selects a retest_dual_client_v1 output. All attempts are immutable;
only two 75-second takes are allowed. An unqualified pair produces diagnostics,
never playable_score.json. Original projects are never opened or edited.
"""
from __future__ import annotations

from ..model_config import PLANNER_MODEL

from contextlib import contextmanager, ExitStack
import ast
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import uuid

from . import llm, playable_rules, unity_editor, unity_input
from ..repair import dual_client_unity_recovery as recovery
from .paths import read_profiles
from .paths import BENCH, FRAMEWORK, read_json, write_json, sha256

VERSION = 'stage1-dual-client-unity.v1'
DURATION, WARMUP, FPS, MAX_TAKES = 75, 1, 4, 2
TARGETS = BENCH / 'test_data/outputs/eval/whitebox/_playable_retest/targets.json'
PROFILES = Path(__file__).with_name('dual_client_unity_profiles.json')
OBSERVER = Path(__file__).with_name('dual_client_unity_observer.cs')
WORKER = Path(__file__).with_name('dual_client_unity_worker.py')
ROLES = ('HOST', 'A', 'B')
RESERVE = 8 * (1 << 30)


class ProductLimitation(llm.HarnessError):
    """Use only for source/native-observed product limitations, never absent tooling."""


def source_hashes(project):
    from engine_adapters.unity3d.playtest.project_snapshot import snapshot_files, EXCLUDED
    # Unity imports only these three authored roots. Prior author validation/build
    # artifacts are evidence, not project inputs, and are never executed or copied.
    hashes = {}
    for name in ('Assets', 'Packages', 'ProjectSettings'):
        base = Path(project) / name
        if not base.is_dir() or base.is_symlink():
            raise llm.HarnessError('Missing or symlinked Unity source root: ' + name)
        for root, dirs, _ in os.walk(base, followlinks=False):
            dirs[:] = [d for d in dirs if d not in EXCLUDED]
            if any(Path(root, d).is_symlink() for d in dirs):
                raise llm.HarnessError('Source contains a directory symlink requiring provenance')
        hashes.update({str(p.relative_to(project)): sha256(p) for p in snapshot_files(base, [])})
    return hashes


def profile_for(delivery_dir):
    delivery_dir = Path(delivery_dir).resolve()
    delivery = read_json(delivery_dir / 'delivery.json')
    project = (delivery_dir / delivery['project_root']).resolve()
    matches = [t for t in read_json(TARGETS)['targets'] if t.get('model') in ('Sol', 'Astra')
               and t.get('case') == 'G014' and t.get('engine') == 'unity3d'
               and Path(t['project']).resolve() == project]
    if len(matches) != 1 or delivery.get('engine') != 'unity3d' or delivery.get('game_id') != 'G014_dual_zone_waterworks':
        raise llm.HarnessError('Unity pair backend only accepts the two original G014 targets')
    target = matches[0]
    if delivery.get('model', '').lower() != target['model'].lower() or target.get('required_real_clients') != 2:
        raise llm.HarnessError('Delivery model/client count differs from frozen target')
    profile = read_profiles(PROFILES, reader=read_json)[target['model']]
    if project != Path(profile['project']).resolve():
        raise llm.HarnessError('Target no longer matches source-reviewed original')
    for name, digest in profile['reviewed_sha256'].items():
        if not (project / name).is_file() or sha256(project / name) != digest:
            raise llm.HarnessError('Reviewed source changed: ' + name)
    return delivery, project, target, profile


def select_editor(project):
    selection = unity_editor.choose(project)
    pick = selection['editor']
    return {**pick, 'binary_sha256': sha256(Path(pick['binary'])),
            'requested_version': selection['delivery']['project_version'],
            'actual_version': pick['version'], 'version_gap': selection['version_gap'],
            'rule': selection['rule'], 'selection': selection}


def control_root():
    from engine_adapters.unity3d.playtest import background_record as backend
    try:
        return backend.migration_root()
    except FileNotFoundError:
        if os.environ.get('GAMEFACTORY_UNITY_CONTROL_ROOT'):
            raise
        # Read only the current production configuration; never execute workspace code.
        config = FRAMEWORK / 'workspaces/unity_m_original_two_columns_20261106/native_configuration.json'
        root = Path(read_json(config)['control_root']).resolve()
        if not root.is_dir() or not all((root / f'serial_{i}.lock').is_file() for i in range(3)):
            raise llm.HarnessError('Existing Unity control directory/locks unavailable')
        return root


def _python_dependencies(seeds):
    """Bind the local static import closure without importing/executing snapshots."""
    found, pending = set(), list(seeds)
    def module_path(name):
        root = FRAMEWORK.joinpath(*name.split('.'))
        for path in (root.with_suffix('.py'), root / '__init__.py'):
            if path.is_file():
                return path
    while pending:
        path = pending.pop()
        if path in found or not path.is_file():
            continue
        found.add(path)
        if path.suffix != '.py':
            continue
        package = list(path.relative_to(FRAMEWORK).parts[:-1])
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8-sig'))):
            names = []
            if isinstance(node, ast.Import):
                names = [n.name for n in node.names]
            elif isinstance(node, ast.ImportFrom):
                prefix = package[:len(package) - node.level + 1] if node.level else []
                prefix += node.module.split('.') if node.module else []
                names = ['.'.join(prefix)] + ['.'.join([*prefix, n.name]) for n in node.names]
            for name in names:
                dependency = module_path(name)
                if dependency and dependency not in found:
                    pending.append(dependency)
    return found


def production_binding():
    files = set((FRAMEWORK / 'engine_adapters/unity3d').rglob('*.py'))
    files.update((FRAMEWORK / 'engine_adapters/unity3d').rglob('*.cs'))
    files.update((FRAMEWORK / 'engine_adapters/unity3d').rglob('*.json'))
    files.update((FRAMEWORK / 'engine_adapters').glob('_*.py'))
    formal = FRAMEWORK / 'pipeline/eval/stage1'
    files.update(formal / n for n in ('unity_native_pair_record.py', 'unity_native_pair_admission.py',
        'unity_native_pair_sources.py', 'unity_native_pair_worker.py', 'multiclient.py',
        'runtime.py', 'batch.py', 'sparse_evidence.py'))
    files.update(Path(__file__).parent / n for n in ('dual_client_unity.py', 'dual_client_unity_worker.py',
        'llm.py', 'plan.py', 'playable_rules.py', 'paths.py', 'unity_editor.py', 'unity_input.py'))
    files = _python_dependencies(files)
    files.update((OBSERVER, PROFILES))
    return {'framework': str(FRAMEWORK), 'files': {str(p.relative_to(FRAMEWORK)): sha256(p)
            for p in sorted(files) if '__pycache__' not in p.parts},
            'accepted': False, 'validation_scope': 'this source-bound native pair only'}


def verify_production(binding):
    if Path(binding['framework']).resolve() != FRAMEWORK.resolve():
        raise llm.HarnessError('Workspace or foreign evaluator execution is forbidden')
    for name, digest in binding['files'].items():
        p = (FRAMEWORK / name).resolve()
        if not p.is_relative_to(FRAMEWORK) or sha256(p) != digest:
            raise llm.HarnessError('Production changed during pair attempt: ' + name)


def arguments(model, role, port, session, output, stop):
    if model not in ('Sol', 'Astra') or role not in ROLES or not 1024 <= port <= 65535:
        raise ValueError('Unknown reviewed pair/role/port')
    if model == 'Sol':
        args = ['--ww-host'] if role == 'HOST' else ['--ww-client', role]
        args += ['--ww-port', str(port), '--ww-address', '127.0.0.1', '--ww-session', session,
                 '--ww-evidence', str(output / 'author_evidence')]
    else:
        args = ['--role', 'host' if role == 'HOST' else role, '--port', str(port),
                '--address', '127.0.0.1', '--evidence', str(output / 'author_evidence')]
        if role != 'HOST':
            args.append('--autoconnect')
    return args + ['--s1-pair-model', model, '--s1-pair-role', role, '--s1-pair-session', session,
                   '--s1-pair-output', str(output), '--s1-pair-stop', str(stop)]


@contextmanager
def native_locks():
    """All Stage1 slots AND formal Unity locks; never bypass another session."""
    from engine_adapters.unity3d.playtest import background_record as backend
    # NOTE: runtime module not migrated; dual-client unity requires bench environment
    from pipeline.game_eval.whitebox_eval import runtime
    control = control_root()
    base = Path(tempfile.gettempdir()) / 'gamefactory-sol-whitebox-gui.lock'
    count = max(1, int(os.environ.get('A3GAME_GUI_SLOTS', '1')))
    paths = set(backend.control_paths(control)) | {base}
    paths.update(base.with_name(f'gamefactory-sol-whitebox-gui.slot{k}.lock') for k in range(1, count))
    paths.update(base.parent.glob('gamefactory-sol-whitebox-gui.slot*.lock'))
    with ExitStack() as stack:
        for path in sorted(paths):
            handle = stack.enter_context(path.open('a'))
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise llm.HarnessError('BLOCKED_LOCK: ' + str(path)) from exc
        block = control / 'background_record_cleanup_block.json'
        if block.exists():
            raise llm.HarnessError('Unconfirmed earlier cleanup: ' + str(block))
        occupied = runtime.active_gui_engines()
        if occupied:
            raise llm.HarnessError('Native engine occupied: ' + json.dumps(occupied))
        yield {'paths': [str(p) for p in sorted(paths)], 'control': str(control)}


def plan_schema():
    return llm.obj({'summary': llm.S, 'steps': llm.arr(llm.obj({
        'client_role': llm.enum('A', 'B', 'BOTH'), 'key': llm.S,
        'duration_ms': {'type': 'integer', 'minimum': 100, 'maximum': 6000},
        'purpose': llm.S}), minItems=4, maxItems=48)})


def actions_for(plan):
    from .plan import native_chord
    llm.validate_schema(plan, plan_schema())
    total = 8000
    actions = [{'action': 'wait', 'duration_ms': total, 'action_id': 'system/startup', 'probe_id': 'system'}]
    for index, step in enumerate(plan['steps'], 1):
        total += step['duration_ms']
        key = native_chord(step['key'], 'unity3d') if step['key'] else ''
        if key and any(k not in {'a', 'd', 'w', 's', 'e', 'q', 'enter', 'space', 'escape'} for k in key.split('+')):
            raise ValueError('Only source-reviewed G014 gameplay keys are allowed')
        actions.append({'action': 'key' if key else 'wait', 'key': key, 'duration_ms': step['duration_ms'],
                        'action_id': f'pair:{index}', 'probe_id': 'playable', 'client_role': step['client_role'],
                        'purpose': step['purpose']})
    if total > DURATION * 1000:
        raise ValueError('Pair plan exceeds 75 seconds including connection slack')
    if any(not any(a['action'] != 'wait' and a.get('client_role') in (r, 'BOTH') for a in actions) for r in ('A', 'B')):
        raise ValueError('Both real clients need physical input')
    if total < DURATION * 1000:
        actions.append({'action': 'wait', 'duration_ms': DURATION * 1000 - total,
                        'action_id': 'system/tail', 'probe_id': 'system'})
    return actions


def make_plan(out, project, profile, model, take, feedback=None):
    folder = out / 'plans' / str(take)
    path = folder / 'plan.json'
    if path.exists():
        plan = read_json(path)
        binding = read_json(folder / 'source_review.json')
        if binding['reviewed_sha256'] != profile['reviewed_sha256'] or binding['planner'] != PLANNER_MODEL:
            raise llm.HarnessError('Saved pair plan source/model differs')
        actions_for(plan)
        return plan
    folder.mkdir(parents=True, exist_ok=True)
    source = '\n\n'.join('FILE ' + n + '\n' + (project / n).read_text() for n in profile['reviewed_sha256'] if n.endswith('.cs'))
    review = {'model': model, 'project': str(project), 'reviewed_sha256': profile['reviewed_sha256'],
              'planner': PLANNER_MODEL, 'judge': None, 'take': take, 'gameplay_ms': 75000,
              'networking': profile['networking'], 'scene': profile['scene'],
              'authored_gameplay_changes': [], 'input_policy': 'isolated native device-read shim only'}
    write_json(folder / 'source_review.json', review)
    prompt = ('Plan a source-informed playable test of TWO independent native Unity clients A and B '
              'in the SAME authored TCP session, with a separate real host. No bots, replay, test mode, '
              'direct gameplay calls, OS input, source changes, or judge. Read the following complete '
              'reviewed gameplay files. Host/connection arguments are already supplied. Each step is '
              'sequential on a shared nominal route; non-target clients wait; clocks/startup are independent. '
              'There is an automatic initial 8s connection wait. Steps must total <=67000ms; each 100..6000ms. '
              'Use only actual a/d/w/s/e/q/enter/space/escape controls; key="" means wait. '
              'Ready BOTH, allow cinematic to finish, and demonstrate each client input reaching the host '
              'and producing visible player motion. Release keys via waits between presses. Include '
              'separate A and B motion probes; do not require winning. '
              'Return summary and steps(client_role,key,duration_ms,purpose).\n'
              + 'Earlier take feedback: ' + json.dumps(feedback) + '\n' + source)
    plan = llm.call_model(folder / 'calls', name='pair_plan', prompt=prompt, schema=plan_schema(),
                          cwd=project, model=PLANNER_MODEL, timeout=240, max_attempts=2,
                          validator=actions_for, read_dirs=[project])
    write_json(path, plan)
    return plan


def _rows(path):
    from pipeline.game_eval.whitebox_eval.unity_native_pair_admission import read_rows
    return read_rows(path)


def qualify_network(folder, model, session):
    """Require native connections AND exact authored host events received by each client."""
    observed, states, events, pids = {}, {}, {}, {}
    transport = read_json(folder / 'session.json')
    if transport['model'] != model or transport['session'] != session:
        raise llm.HarnessError('Transport/session binding differs')
    projects = set()
    for role in ROLES:
        native = folder / 'sessions' / role
        rows = _rows(native / 'observations.jsonl')
        if (native / 'observer_error.txt').exists():
            raise llm.HarnessError('Read-only observer failed for ' + role)
        good = [r for r in rows if r.get('schema') == 'stage1-unity-pair-observation.v1'
                and r.get('role') == role and r.get('model') == model and r.get('session') == session
                and (role == 'HOST' or r.get('actual_role') == role)
                and r.get('is_host') is (role == 'HOST') and r.get('test_mode') is False
                and r.get('ignore_focus') is False and not r.get('error')
                and (role == 'HOST' or r.get('connected') is True)]
        if len(good) < 3 or len({r['pid'] for r in good}) != 1:
            raise llm.HarnessError('Missing native connected observations: ' + role)
        pids[role] = good[0]['pid']
        owner = read_json(native / 'owned_process.json' if role == 'HOST' else folder / 'workers' / role / 'owned_editor.json')
        if owner['pid'] != pids[role]:
            raise llm.HarnessError('Observed process is not the launched native client')
        expected_project = str(recovery.verify(folder) if role == 'HOST' else folder / ('project_' + role))
        command = owner['command'] if role == 'HOST' else owner['args']
        expected = arguments(model, role, transport['port'], session, native, folder / 'STOP_OWNED_PAIR')
        if role == 'HOST':
            if '-projectPath' not in command or command[command.index('-projectPath') + 1] != expected_project:
                raise llm.HarnessError('Host project ownership differs')
        elif owner.get('project') != expected_project:
            raise llm.HarnessError('Client project ownership differs')
        if command[-len(expected):] != expected:
            raise llm.HarnessError('Authored transport/role launch arguments differ')
        projects.add(expected_project)
        observed[role] = good
        values = [json.loads(r['state_json']) for r in good if r.get('state_json')]
        if model == 'Sol':
            states[role] = [v for v in values if v.get('session') == session and
                len(v.get('players', [])) == 2 and {p.get('role') for p in v['players']} == {'A', 'B'}
                and all(p.get('connected') is True for p in v['players'])]
            name = 'host_events.jsonl' if role == 'HOST' else f'client_{role}.jsonl'
        else:
            if role == 'HOST':
                values = _rows(native / 'author_evidence/states.jsonl')
            states[role] = [v for v in values if v.get('connectedA') is True and v.get('connectedB') is True
                            and (role == 'HOST' or v.get('role') == role)]
            name = 'events.jsonl'
        # Overlap uses only observations whose authored state contains BOTH clients.
        if model == 'Sol' or role != 'HOST':
            valid_states = {json.dumps(v, sort_keys=True) for v in states[role]}
            observed[role] = [r for r in good if r.get('state_json') and
                             json.dumps(json.loads(r['state_json']), sort_keys=True) in valid_states]
        events[role] = _rows(native / 'author_evidence' / name)
        seq = 'stateSeq' if model == 'Sol' else 'state_seq'
        if len(states[role]) < 3 or max(v[seq] for v in states[role]) <= min(v[seq] for v in states[role]):
            raise llm.HarnessError('No advancing authored shared state: ' + role)
    if len(set(pids.values())) != 3:
        raise llm.HarnessError('Host and clients are not three independent native processes')
    begin = max(min(r['unix_ms'] for r in observed[role]) for role in ROLES)
    end = min(max(r['unix_ms'] for r in observed[role]) for role in ROLES)
    if len(projects) != 3:
        raise llm.HarnessError('Native projects are not independent')
    if end - begin < 1000:
        raise llm.HarnessError('Native pair connection intervals do not overlap')
    # Match whole author-produced event records, including sequence/time/input identity.
    kind, actor = ('type', 'role') if model == 'Sol' else ('key', 'owner')
    host = {json.dumps(e, sort_keys=True): e for e in events['HOST'] if e.get(kind) == 'input_accepted'}
    received = {}
    for role in ('A', 'B'):
        matches = [e for e in events[role] if e.get(actor) == role and e.get(kind) == 'input_accepted'
                   and json.dumps(e, sort_keys=True) in host]
        if model == 'Sol':
            matches = [e for e in matches if not e.get('detail', '').startswith(('move#', 'focus_lost#'))]
        else:
            inputs = _rows(folder / 'sessions/HOST/author_evidence/inputs.jsonl')
            active = {c['seq'] for c in inputs if c.get('role') == role and
                      (c.get('command') or c.get('move') or any(c.get(k) for k in
                       ('jump', 'crouch', 'interact', 'ping')))}
            matches = [e for e in matches if e.get('input_seq') in active]
        if not matches:
            raise llm.HarnessError('No exact host-accepted input transferred back to client ' + role)
        received[role] = matches[:3]
    if any(not observed[r] for r in ROLES):
        raise llm.HarnessError('No overlapping connected state observations')
    return {'native_pids': pids, 'session': session, 'overlap_ms': end - begin,
            'host_accepted_input_received': received,
            'connected_state_counts': {r: len(states[r]) for r in ROLES},
            'evidence_kind': 'authored TCP state and identical host input acceptance events'}


def _copy_project(source, target, hashes):
    target.mkdir(parents=True, exist_ok=False)
    for name, digest in hashes.items():
        dest = target / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / name, dest)
        if sha256(dest) != digest:
            raise llm.HarnessError('Original changed while copying: ' + name)
    helper = target / 'Assets/Stage1DualUnityObserver/Editor/Stage1DualUnityObserver.cs'
    if helper.exists():
        raise llm.HarnessError('Observer would overwrite authored code')
    helper.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(OBSERVER, helper)


def observe_owned(ownership, proc, observed):
    """Keep strict live identity checks; tolerate only a Popen-confirmed exit race."""
    try:
        ownership.observe_owned_group(proc, observed)
    except ValueError:
        if proc.poll() is None:
            raise


def record_pair(project, folder, *, model, profile, plan, editor, production, hashes, lineage=None, plan_folder=None):
    from pipeline.game_eval.whitebox_eval import unity_native_pair_record as ownership
    processes, observed, streams, editor_observed = {}, {}, {}, {'A': {}, 'B': {}}
    stop = folder / 'STOP_OWNED_PAIR'
    session = 'stage1-' + uuid.uuid4().hex
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
    actions = actions_for(plan)
    with native_locks() as locks:
        folder.mkdir(parents=True, exist_ok=False)
        write_json(folder / 'locks.json', locks)
        write_json(folder / 'source_snapshot.json', {'source': str(project), 'files_sha256': hashes})
        write_json(folder / 'production.json', production)
        write_json(folder / 'plan.json', plan)
        if plan_folder is not None:
            shutil.copytree(plan_folder, folder / 'planner_provenance')
        if lineage is not None:
            write_json(folder / 'import_recovery.json', lineage)
            recovery.verify(folder)
        write_json(folder / 'session.json', {'session': session, 'port': port, 'model': model,
                   'editor': editor, 'required_real_clients': 2, 'seconds': DURATION})
        error, cleanup = None, {}
        old_term = signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt('owned pair stop')))
        deadline = time.monotonic() + 1050  # bounded imports + host admission + one 75s take

        def check():
            if time.monotonic() > deadline:
                raise llm.HarnessError('Native import/startup/record deadline exceeded')
            if shutil.disk_usage(folder).free < RESERVE:
                raise llm.HarnessError('8GiB reserve reached')
            for key, proc in processes.items():
                observe_owned(ownership, proc, observed[key])
            for role in ('A', 'B'):
                if role in processes:
                    ownership.observe_editor_group(folder / 'workers' / role, processes[role].pid,
                        editor['binary'], folder / ('project_' + role), editor_observed[role])

        def launch(key, command, log):
            log.parent.mkdir(parents=True, exist_ok=True)
            streams[key] = log.open('w')
            processes[key] = subprocess.Popen(command, stdout=streams[key], stderr=subprocess.STDOUT,
                                               start_new_session=True)
            observed[key] = {}
            observe_owned(ownership, processes[key], observed[key])
            return processes[key]

        try:
            for role in ROLES:
                check()
                copy = folder / ('project_' + role)
                if role == 'HOST' and lineage is not None:
                    (folder / 'sessions/HOST').mkdir(parents=True)
                    shutil.copytree(Path(lineage['parent']) / 'imports/HOST', folder / 'imports/HOST')
                    if 'recovered_import_result' in lineage:
                        write_json(folder / 'imports/HOST/import_result.json', lineage['recovered_import_result'])
                    continue
                _copy_project(project, copy, hashes)
                if role != 'HOST':
                    unity_input.migrate(copy, folder / ('input_migration_' + role + '.json'))
                native = folder / 'sessions' / role
                native.mkdir(parents=True)
                # Clients' take directory is created by their worker, so import logs live separately.
                if role != 'HOST':
                    native.rmdir()
                imp = folder / 'imports' / role
                imp.mkdir(parents=True)
                command = [editor['binary'], '-batchmode', '-nographics', '-quit', '-projectPath', str(copy),
                           '-skipUpgradeDialogs', '-logFile', str(imp / 'import.log')]
                proc = launch('import_' + role, command, imp / 'process.log')
                end = min(deadline, time.monotonic() + 240)
                while proc.poll() is None:
                    check()
                    if time.monotonic() > end:
                        raise llm.HarnessError('Native import timeout for ' + role)
                    time.sleep(.25)
                write_json(imp / 'import_result.json', {'exit_code': proc.returncode, 'timeout': False, 'editor': editor})
                if proc.returncode:
                    raise llm.HarnessError('Native import failed; inspect original engine diagnostics: ' + str(imp))
            verify_production(production)
            host = folder / 'sessions/HOST'
            command = [editor['binary'], '-batchmode', '-projectPath', str(recovery.verify(folder)),
                       '-skipUpgradeDialogs', '-executeMethod', 'Stage1DualUnityObserver.Enter',
                       '-logFile', str(host / 'Editor.log'), '--s1-pair-scene', profile['scene'],
                       *arguments(model, 'HOST', port, session, host, stop)]
            proc = launch('HOST', command, host / 'process.log')
            write_json(host / 'owned_process.json', {'pid': proc.pid, 'command': command})
            end = min(deadline, time.monotonic() + 180)
            while True:
                check()
                rows = _rows(host / 'observations.jsonl')
                if any(r.get('is_host') is True and not r.get('error') for r in rows):
                    break
                if proc.poll() is not None or time.monotonic() > end:
                    raise llm.HarnessError('Authored native host did not start; preserve diagnostics')
                time.sleep(.25)
            for role in ('A', 'B'):
                spec = dict(model=model, role=role, project=str(folder / ('project_' + role)),
                            take=str(folder / 'sessions' / role), receipts=str(folder / 'workers' / role),
                            editor=editor['binary'], scene=profile['scene'], port=port, session=session,
                            stop=str(stop), actions=actions, production=production,
                            snapshot=str(folder / 'source_snapshot.json'))
                request = folder / ('request_' + role + '.json')
                write_json(request, spec)
                launch(role, [sys.executable, str(WORKER), str(request)], folder / ('worker_' + role + '.log'))
            end = min(deadline, time.monotonic() + DURATION + WARMUP + 240)
            while any(processes[r].poll() is None for r in ('A', 'B')):
                check()
                if processes['HOST'].poll() is not None or any(processes[r].poll() not in (None, 0) for r in ('A', 'B')):
                    raise llm.HarnessError('Native host/client failed; no pair score')
                if time.monotonic() > end:
                    raise llm.HarnessError('Pair record exceeded bounded startup allowance')
                time.sleep(.25)
        except BaseException as exc:
            error = {'type': type(exc).__name__, 'error': str(exc)}
            raise
        finally:
            stop.write_text('Stop this owned native pair only.\n')
            for key, proc in processes.items():
                try:
                    cleanup[key] = ownership.stop_owned(proc, folder / ('cleanup_' + key + '.json'), observed[key])
                except Exception as exc:
                    cleanup[key] = {'ok': False, 'error': str(exc)}
            for role in ('A', 'B'):
                if role in processes:
                    try:
                        cleanup['editor_' + role] = ownership.cleanup_editor_group(folder / 'workers' / role,
                            processes[role].pid, editor['binary'], folder / ('project_' + role),
                            editor_observed[role], folder / ('cleanup_editor_' + role + '.json'))
                    except Exception as exc:
                        cleanup['editor_' + role] = {'ok': False, 'error': str(exc)}
            for stream in streams.values():
                stream.close()
            unchanged = source_hashes(project) == hashes
            clean = all(c.get('ok') is True for c in cleanup.values())
            write_json(folder / 'cleanup.json', {'ok': clean and unchanged, 'owned_processes': cleanup,
                       'source_unchanged': unchanged, 'error': error, 'deleted_bytes': 0})
            if not clean:
                # Own precise marker blocks later runs; never overwrite another session's marker.
                block = Path(locks['control']) / 'background_record_cleanup_block.json'
                if not block.exists():
                    write_json(block, {'owner': VERSION, 'attempt': str(folder), 'cleanup': str(folder / 'cleanup.json')})
            signal.signal(signal.SIGTERM, old_term)
        if not clean or not unchanged:
            raise llm.HarnessError('Owned cleanup/source verification failed')
        verify_production(production)
        for role in ('A', 'B'):
            verification = read_json(folder / 'workers' / role / 'verification.json')
            if verification.get('ok') is not True or not verification.get('checks') or not all(
                    value is True for value in verification['checks'].values()):
                raise llm.HarnessError('Formal native client verification failed: ' + role)
        try:
            network = qualify_network(folder, model, session)
            network_error = None
        except llm.HarnessError as exc:
            network, network_error = {'session': session}, str(exc)
        bindings = evidence_bindings(folder)
        receipt = {'version': VERSION, 'qualified': network_error is None, 'error': network_error, 'required_real_clients': 2,
                   'network': network, 'editor': editor, 'source': str(project),
                   'source_hashes': hashes, 'production': production, 'evidence_sha256': bindings,
                   'authored_gameplay_changes': [], 'input_transport': 'internal', 'os_input': False,
                   'automation': False, 'replay': False, 'cleanup_verified': True}
        write_json(folder / 'pair_receipt.json', receipt)
        return receipt


def evidence_bindings(folder):
    files = [folder / 'plan.json', folder / 'input_migration_A.json', folder / 'input_migration_B.json',
             folder / 'request_A.json', folder / 'request_B.json', folder / 'source_snapshot.json', folder / 'session.json', folder / 'cleanup.json',
             folder / 'production.json', folder / 'sessions/HOST/owned_process.json']
    files += [p for p in (folder / 'planner_provenance').rglob('*') if p.is_file()]
    if (folder / 'import_recovery.json').exists():
        files.append(folder / 'import_recovery.json')
    for role in ROLES:
        native = folder / 'sessions' / role
        files += [native / 'observations.jsonl'] + sorted((native / 'author_evidence').glob('*.jsonl'))
        files += sorted((folder / 'imports' / role).glob('*'))
        if role != 'HOST':
            files += sorted((folder / 'workers' / role).glob('*.json'))
            files += [p for p in native.rglob('*') if p.is_file() and p.suffix in ('.json', '.jsonl', '.png', '.mp4')]
    return {str(p.relative_to(folder)): sha256(p) for p in sorted(set(files))}


def verify_receipt(out, score, *, require_qualified=True):
    from pipeline.game_eval.whitebox_eval.unity_native_pair_sources import bound_path
    if Path(score['pair_evidence_receipt']).is_absolute():
        raise llm.HarnessError('Pair receipt must be relative to output')
    path = bound_path(out, score['pair_evidence_receipt'])
    if sha256(path) != score['pair_evidence_sha256']:
        raise llm.HarnessError('Published pair receipt changed')
    receipt = read_json(path)
    recovery.verify(path.parent)
    if (require_qualified and receipt.get('qualified') is not True) or receipt.get('required_real_clients') != 2:
        raise llm.HarnessError('No qualified two-client receipt')
    for name, digest in receipt['evidence_sha256'].items():
        if sha256(bound_path(path.parent, name)) != digest:
            raise llm.HarnessError('Pair raw evidence changed: ' + name)
    if receipt['evidence_sha256'] != evidence_bindings(path.parent):
        raise llm.HarnessError('Incomplete native evidence binding')
    snapshot = read_json(path.parent / 'source_snapshot.json')
    if receipt['source'] != snapshot['source'] or receipt['source_hashes'] != snapshot['files_sha256']:
        raise llm.HarnessError('Receipt original binding differs')
    cleanup = read_json(path.parent / 'cleanup.json')
    if cleanup.get('ok') is not True or cleanup.get('source_unchanged') is not True:
        raise llm.HarnessError('Native pair cleanup not verified')
    for role in ('A', 'B'):
        verified = read_json(path.parent / 'workers' / role / 'verification.json')
        if verified.get('ok') is not True or not verified.get('checks') or not all(
                value is True for value in verified['checks'].values()):
            raise llm.HarnessError('Client capture verification incomplete')
    if receipt['qualified']:
        qualify_network(path.parent, read_json(path.parent / 'session.json')['model'], receipt['network']['session'])
    return receipt


def _checks(folder, take):
    clients = {}
    for role in ('A', 'B'):
        native = folder / 'sessions' / role
        imp = playable_rules._import(folder, 'unity3d', [folder / 'imports' / role])
        launch, launch_stats = playable_rules._launch([(take, native)])
        operate, operate_stats = playable_rules._operate([(take, native)])
        clients[role] = dict(zip(playable_rules.IDS, (imp, launch, operate)))
        rule_path = folder / ('playable_rules_' + role + '.json')
        value = {'verdicts': clients[role], 'launch': launch_stats, 'operate': operate_stats}
        if rule_path.exists():
            if read_json(rule_path) != json.loads(json.dumps(value)):
                raise llm.HarnessError('Rule diagnostic changed; preserve original attempt')
        else:
            write_json(rule_path, value)
    checks = {}
    for ident in playable_rules.IDS:
        statuses = [clients[r][ident]['status'] if clients[r][ident] else 'HARNESS_ERROR' for r in ('A', 'B')]
        checks[ident] = next((s for s in ('HARNESS_ERROR', 'FAIL', 'UNVERIFIED') if s in statuses), 'PASS')
    return checks, clients


def write_status(out, value):
    path = out / 'status.json'
    if path.exists():
        old = out / 'diagnostics' / ('status_before_' + str(time.time_ns()) + '.json')
        old.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, old)
    write_json(path, value)


def run_playable(delivery_dir, out, *, models=None):
    """Return only a complete, receipt-bound score; blockers raise HarnessError."""
    models = models or {'planner': PLANNER_MODEL}
    if models.get('planner') != PLANNER_MODEL:
        raise llm.HarnessError(f'Unity pair planner must match configured model {PLANNER_MODEL}; no judge is used')
    delivery, project, target, profile = profile_for(delivery_dir)
    out = Path(out).resolve()
    if out.is_relative_to(project) or project.is_relative_to(out):
        raise llm.HarnessError('Pair output must be isolated from the original')
    if 'retest_dual_client_v1' not in out.parts:
        raise llm.HarnessError('Use a separate retest_dual_client_v1 output; preserve old single-client diagnostics')
    out.mkdir(parents=True, exist_ok=True)
    with (out / '.dual_client_unity.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise llm.HarnessError('This Unity pair output already has an owner') from exc
        score_path = out / 'playable_score.json'
        if score_path.exists():
            score = read_json(score_path)
            if score.get('complete') is not True or score.get('required_real_clients') != 2:
                raise llm.HarnessError('Preserve unqualified previous score')
            receipt = verify_receipt(out, score)
            if receipt['source'] != str(project) or score.get('game_id') != delivery['game_id']:
                raise llm.HarnessError('Cached score identity differs')
            if source_hashes(project) != receipt['source_hashes']:
                raise llm.HarnessError('Original changed since qualified pair')
            return score
        step = 'source_review'
        try:
            hashes = source_hashes(project)
            manifest = {'version': VERSION, 'delivery': delivery, 'source': str(project), 'source_hashes': hashes,
                        'target': target, 'targets_sha256': sha256(TARGETS), 'required_real_clients': 2,
                        'models': {'planner': PLANNER_MODEL, 'judge': None}, 'profile': profile}
            if (out / 'manifest.json').exists():
                old = read_json(out / 'manifest.json')
                if old['source_hashes'] != hashes or old['delivery'] != delivery:
                    raise llm.HarnessError('Frozen original/delivery changed; preserve prior attempts')
            else:
                write_json(out / 'manifest.json', manifest)
            # Persist source/network provenance even when exact editor or lock admission is unavailable.
            review = out / 'source_review.json'
            if not review.exists():
                write_json(review, {'profile': profile, 'source_hashes': hashes, 'model': target['model'],
                           'planner': PLANNER_MODEL, 'plan_state': 'SOURCE_REVIEWED_NOT_MODEL_PLANNED',
                           'required_real_clients': 2, 'authored_multiplayer': True})
            step = 'editor_admission'
            editor = select_editor(project)
            write_json(out / 'editor_selection.json', editor)
            needed = 3 * sum((project / n).stat().st_size for n in hashes) + 10 * (1 << 30) + RESERVE
            if shutil.disk_usage(out).free < needed:
                raise llm.HarnessError('Insufficient disk for isolated imports, captures and 8GiB reserve')
            production = production_binding()
            history, feedback, qualified = [], None, []
            for take in range(1, MAX_TAKES + 1):
                folder = out / 'takes' / str(take)
                lineage = None
                if folder.exists() and not (folder / 'pair_receipt.json').exists():
                    child = folder / recovery.RECOVERY
                    if child.exists():
                        if not (child / 'pair_receipt.json').exists():
                            raise llm.HarnessError('Preserve partial recovery; bounded admission exhausted: ' + str(child))
                        recovery.verify(child)
                    else:
                        lineage = recovery.prepare(folder, project=project, hashes=hashes,
                                                   editor=editor, production=production, observer=OBSERVER)
                    folder = child
                if folder.exists():
                    stub = {'pair_evidence_receipt': str((folder / 'pair_receipt.json').relative_to(out)),
                            'pair_evidence_sha256': sha256(folder / 'pair_receipt.json')}
                    verify_receipt(out, stub, require_qualified=False)
                else:
                    step = 'plan_t' + str(take)
                    plan = make_plan(out, project, profile, target['model'], take, feedback)
                    step = 'record_t' + str(take)
                    write_status(out, {'step': step, 'state': 'RUNNING', 'complete': False,
                                      'required_real_clients': 2, 'take': take, 'editor': editor})
                    record_pair(project, folder, model=target['model'], profile=profile, plan=plan,
                                editor=editor, production=production, hashes=hashes, lineage=lineage,
                                plan_folder=out / 'plans' / str(take))
                receipt = read_json(folder / 'pair_receipt.json')
                checks, clients = _checks(folder, take)
                if receipt['qualified']:
                    qualified.append((folder, checks, clients))
                history.append({'take': take, 'checks': checks, 'pair_evidence_receipt':
                                str((folder / 'pair_receipt.json').relative_to(out))})
                if 'HARNESS_ERROR' in checks.values():
                    raise llm.HarnessError('Qualified pair has missing playable rule evidence')
                if checks['play.operate'] == 'PASS' and receipt['qualified']:
                    break
                feedback = {'checks': checks, 'client_checks': clients, 'pair_error': receipt.get('error')}
            if not qualified:
                raise llm.HarnessError('No qualified authored pair after two bounded takes: ' + str(receipt.get('error')))
            folder, checks, clients = qualified[-1]
            receipt_path = folder / 'pair_receipt.json'
            result = {'version': VERSION, 'game_id': delivery['game_id'], 'engine': 'unity3d',
                      'planner': PLANNER_MODEL, 'judge': None, 'required_real_clients': 2, 'complete': True,
                      'duration_s': 75, 'model': target['model'], 'editor': editor,
                      'plan_origin': 'accepted Astra source review before each native take',
                      'state': 'done', 'checks': checks, 'client_checks': clients, 'takes': history,
                      'playable': round(100 * sum(v == 'PASS' for v in checks.values()) / 3, 2),
                      'pair_evidence_receipt': str(receipt_path.relative_to(out)),
                      'pair_evidence_sha256': sha256(receipt_path), 'cache_deleted_bytes': 0}
            verify_receipt(out, result)
            write_json(score_path, result)
            write_status(out, {'step': 'playable', 'state': 'done', 'complete': True,
                       'required_real_clients': 2})
            return result
        except BaseException as exc:
            diagnostic = {'step': step,
                       'state': 'PRODUCT_LIMITATION' if isinstance(exc, ProductLimitation) else 'HARNESS_ERROR',
                       'complete': False, 'required_real_clients': 2, 'error': str(exc)}
            write_json(out / 'diagnostics' / (str(time.time_ns()) + '.json'), diagnostic)
            write_status(out, diagnostic)
            if isinstance(exc, (llm.HarnessError, KeyboardInterrupt, SystemExit)):
                raise
            raise llm.HarnessError(str(exc)) from exc
