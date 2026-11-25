#!/usr/bin/env python3
"""Stage3 refine matrix with serial defaults and opt-in isolated model lanes."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import signal
from pathlib import Path
import subprocess
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from pipeline.eval.refinement.common import dump, read, resolve, sha
from pipeline.eval.refinement.batch import exclusive
from pipeline.eval.refinement.providers import POLICY, preflight, validate
import scripts.eval.run_stage3_refine_eval as single

DEFAULT_MANIFEST = Path(__file__).with_name('matrix.json')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def freeze(path, value):
    if path.exists():
        if read(path) != value:
            raise ValueError('Frozen identity changed; preserve existing state: ' + str(path))
    else:
        dump(path, value)


def load_manifest(path):
    manifest = read(path)
    root = resolve(path.parent, manifest.get('bench_root', '..'))
    models, games = manifest['models'], manifest['games']
    if not models or not games or len(games) != len(set(games)):
        raise ValueError('Nonempty models and unique games required')
    import re
    for name in [*models, *games]:
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', name):
            raise ValueError('Unsafe model/game name')
    if len({s['model'] for s in models.values()}) != len(models):
        raise ValueError('Duplicate actual model routes are forbidden')
    base_path = resolve(root, manifest['base_config'])
    inventory_path = resolve(root, manifest['source_inventory'])
    for name, source in [('base_config', base_path), ('source_inventory', inventory_path)]:
        if sha(source) != manifest[name + '_sha256']:
            raise ValueError('Frozen input changed: ' + name)
    base = read(base_path)
    inventory = read(inventory_path)
    by_game = {g['game_id']: g for g in inventory['games']}
    if set(games) != set(by_game):
        raise ValueError('Manifest must include every frozen source game exactly once')
    base['bench_root'] = str(root)
    base['repair_rounds'] = 10
    base['interaction_policy'] = POLICY
    base['include_vfx'] = True
    frozen_sources = manifest['collect_sources']
    if not frozen_sources:
        raise ValueError('Frozen collect sources required')
    base['frozen_collect_sources'] = {
        key: {'path': str(resolve(root, ref['path'])), 'sha256': ref['sha256']}
        for key, ref in frozen_sources.items()}
    if manifest.get('motion_sources'):
        base['motion_sources'] = {
            key: {'path': str(resolve(root, ref['path'])), 'sha256': ref['sha256']}
            for key, ref in manifest['motion_sources'].items()}
    if manifest.get('case_inputs'):
        if set(manifest['case_inputs']) != set(games):
            raise ValueError('Every game requires its own case input index')
        base['case_inputs'] = {
            gid: {'path': str(resolve(root, ref['path'])), 'sha256': ref['sha256']}
            for gid, ref in manifest['case_inputs'].items()}
    verify_inputs(base)
    for key in ('post_repair_evaluation', 'repair_sources', 'explicit_restart', 'preparation_parent'):
        base.pop(key, None)
    base['project_overrides'] = {gid: by_game[gid]['project'] for gid in games if by_game[gid]['project']}
    base['frozen_project_sources'] = manifest['project_sources']
    if set(base['frozen_project_sources']) != {gid for gid in games if by_game[gid]['project']}:
        raise ValueError('Every located source project requires a frozen content digest')
    base['consecutive_error_limit'] = 1  # Each child contains one game; parent isolates failures.
    for name, settings in models.items():
        settings['executable'] = (sys.executable if settings['executable'] == '{python}' else
                                  settings['executable'].replace('{bench}', str(root)))
        settings['args'] = [a.replace('{bench}', str(root)).replace('{home}', str(Path.home()))
                            for a in settings.get('args', [])]
        settings['timeout_seconds'] = 1800
        validate(settings)
    return manifest, single.normalize(base), by_game, root


def verify_inputs(base):
    if base.get('case_inputs'):
        from pipeline.eval.refinement.case_inputs import load as load_cases
        load_cases(base, list(base['case_inputs']))
    if base.get('motion_sources'):
        from pipeline.eval.refinement.motion_delivery import load_sources
        load_sources(base)
    for ref in base['frozen_collect_sources'].values():
        if sha(ref['path']) != ref['sha256']:
            raise ValueError('Frozen matrix collect changed: ' + ref['path'])


def history_roots(root, extra):
    return [root / 'test_data/outputs/game_refine', root / 'test_data/outputs/playtest',
            *[resolve(root, p) for p in extra]]


def find_history(root, roots, model, gid, current):
    """Known legacy batches plus candidate metadata; never infer zero from a ledger."""
    found = set()
    for parent in roots:
        for config_path in parent.glob('*/configuration.json'):
            config = read(config_path)
            output = config_path.parent.resolve()
            if output == current.resolve() or config.get('agent', {}).get('model') != model:
                continue
            folder = output / 'games' / gid
            # Partial work/raw/claims count even when ledger or summary says zero.
            if any(folder.glob('repair_rounds/round_*/claim.json')) or any(
                    (folder / name).exists() for name in ('agent_report.json', 'agent_identity.json',
                        'agent_session/raw/zcode.jsonl', 'timeout_recovery/summary.json')):
                found.add(str(output))
    game_root = root / 'test_data/outputs/initial_game_gen/gpt_sol6p1' / gid
    for path in game_root.glob('*/run_meta.json'):
        meta = read(path)
        if meta.get('agent_model') == model and meta.get('control_folder'):
            output = Path(meta['control_folder']).parents[1].resolve()
            if output != current.resolve():
                found.add(str(output))
    return sorted(found)


def make_jobs(manifest, base, output, selected):
    jobs = []
    for model in selected:
        for gid in manifest['games']:
            config = copy.deepcopy(base)
            config['agent'] = copy.deepcopy(manifest['models'][model])
            config['games'] = [gid]
            if base.get('case_inputs'):
                config['case_inputs'] = {gid: copy.deepcopy(base['case_inputs'][gid])}
            config = single._generation_config(config)
            child = output / 'batches' / model / gid
            if config.get('repair_execution_policy'):
                from stage3_run_layout import candidate_location
                game = {'game_id': gid, 'project': config['project_overrides'][gid]}
                _, candidate = candidate_location(game, child/'games'/gid, config)
                config['repair_candidate_root'] = str(candidate)
            jobs.append({'id': model + '/' + gid, 'model': model, 'game': gid,
                         'config': config, 'output': child,
                         'config_path': output / 'configs' / model / (gid + '.json')})
    return jobs


def registry_path(base, job, *, original=False):
    identity = {'model': job['config']['agent']['model'], 'game': job['game']}
    if base.get('authorized_new_experiment') and not original:
        identity['experiment'] = base['authorized_new_experiment']['sha256']
    return Path(base['unity']['control_root']) / 'stage3_refine_identities' / (digest(identity) + '.json')


def job_command(job, mode):
    command = [sys.executable, str(BENCH / 'scripts/run_stage3_refine.py'),
            '--config', str(job['config_path']), '--output', str(job['output']),
            '--interaction-policy', POLICY, '--mode', mode]
    if job.get('migration'):
        command.extend(['--matrix-migration', str(job['migration'])])
    return command


def run_child(command, **kwargs):
    """Let the owned runner finalize its provider group before leaving a claim."""
    kwargs.pop('check', None)
    stop_event = kwargs.pop('stop_event', None)
    child = subprocess.Popen(command, start_new_session=True, **kwargs)
    try:
        while True:
            try:
                return subprocess.CompletedProcess(command, child.wait(timeout=1))
            except subprocess.TimeoutExpired:
                if stop_event is not None and stop_event.is_set():
                    raise KeyboardInterrupt
    except KeyboardInterrupt:
        try:
            child.send_signal(signal.SIGINT)
            child.wait(timeout=30)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            pass  # Keep RUNNING claim; never kill an unknown descendant or retry.
        raise


def status(job, state, root, roots, base):
    previous = state.get(job['id'], {})
    registry = registry_path(base, job)
    if registry.exists() and read(registry).get('output') != str(job['output']):
        return {'status': 'BLOCKED_EXISTING_IDENTITY', 'identity': str(registry)}
    history = find_history(root, roots, job['config']['agent']['model'], job['game'], job['output'])
    authorization = base.get('authorized_new_experiment')
    if authorization:
        receipt = read(authorization['path'])
        if sha(authorization['path']) != authorization['sha256']:
            raise ValueError('Restart authorization changed')
        prior = receipt['prior_jobs'][job['id']]
        for ref in prior['sources']:
            if sha(ref['path']) != ref['sha256']:
                raise ValueError('Prior experiment evidence changed: ' + ref['path'])
        legacy_registry = registry_path(base, job, original=True)
        if legacy_registry.exists() and str(legacy_registry) not in {r['path'] for r in prior['sources']}:
            raise ValueError('Unacknowledged original experiment identity')
        history = sorted(set(history) - set(prior['existing_batches']))
    if history:
        return {'status': 'BLOCKED_HISTORY', 'existing_batches': history,
                'reason': 'Reuse/migrate existing attempts; never allocate another ten rounds'}
    if job['game'] not in base['project_overrides']:
        return {'status': 'BLOCKED_NO_PROJECT', 'reason': 'Frozen source has no project; no substitute selection'}
    folder = job['output'] / 'games' / job['game']
    summary = folder / 'repair_rounds/summary.json'
    if summary.exists() and read(summary).get('status') == 'REPAIRED':
        from pipeline.eval.refinement.fresh_sessions import validate as validate_closed
        result = validate_closed(folder, job['config'])
        return {'status': 'REPAIRED', 'summary': str(summary),
                'rounds_attempted': result['rounds_attempted'],
                'stop_reason': result['stop_reason'], 'evaluation_started': False}
    if job.get('migration') and not job.get('fresh_migration'):
        from pipeline.eval.refinement.repair_budget import verify_recovery
        try:
            budget = verify_recovery(folder, job['config'])
        except (ValueError, OSError, RuntimeError) as exc:
            return {**previous, 'status': 'BLOCKED_RECOVERY', 'reason': str(exc)}
        if budget.get('ready') is True:
            return {'status': 'READY', 'recovery': budget}
        return {**previous, 'status': 'BLOCKED_RECOVERY', 'reason': 'Source-bound recovery is not ready', 'budget': budget}
    if previous.get('status') in ('RUNNING', 'ERROR', 'BLOCKED_RECOVERY'):
        return {**previous, 'status': 'BLOCKED_RECOVERY',
                'reason': 'Preserved interrupted/failed dispatch; diagnose before retry'}
    for claim in folder.glob('repair_rounds/round_*/claim.json'):
        if not claim.with_name('closed.json').exists():
            return {'status': 'BLOCKED_RECOVERY', 'claim': str(claim)}
    return {'status': 'READY'}


def historical_attempts(output, model):
    """Use dispatch timestamps across games, never per-game physical round order."""
    paths = list((Path(output) / 'batches' / model).glob('*/games/*/repair_rounds/round_*/claim.json'))
    def order(path):
        claim = read(path)
        return (claim.get('started_unix', claim.get('unix', path.stat().st_mtime)), str(path))
    return [path.parent for path in sorted(paths, key=order)]


def attempts_after_probe(attempts, probe):
    if not probe:
        return attempts
    from pipeline.eval.refinement.repair_budget import diagnose
    # A pre-probe claim whose failure arrived later must still trip the circuit.
    return [path for path in attempts if any(Path(ref['path']).stat().st_mtime > probe['completed_unix']
                for ref in diagnose(path)['sources'])]


def execute(manifest_path, output, selected=None, *, mode='check', runner=run_child, restart_authorization=None, workers=1, project_isolation=False, migration=None):
    if workers not in (1, 2, 3) or (workers > 1 and not project_isolation):
        raise ValueError('Workers must be 1..3; parallel repair requires --project-isolation')
    manifest_path, output = Path(manifest_path).resolve(), Path(output).resolve()
    manifest, base, _, root = load_manifest(manifest_path)
    migration_record = None
    if migration:
        from refine.recovery import verify_migration
        migration = Path(migration).resolve()
        migration_record = verify_migration(migration, output)
        if mode == 'prepare':
            raise ValueError('Migrated batches are already prepared; do not overwrite frozen pins')
        base = copy.deepcopy(read(output / 'matrix_identity.json')['base_config'])
        if restart_authorization and str(Path(restart_authorization).resolve()) != migration_record['authorization']['path']:
            raise ValueError('Migration must retain the original authorization')
        restart_authorization = migration_record['authorization']['path']
        selected = selected or migration_record['models']
        if set(selected) - set(migration_record['models']):
            raise ValueError('Requested model is paused or outside migrated scope')
    selected = selected or list(manifest['models'])
    if len(selected) != len(set(selected)) or set(selected) - set(manifest['models']):
        raise ValueError('Unknown/duplicate model selection')
    if restart_authorization:
        receipt_path = Path(restart_authorization).resolve()
        receipt = read(receipt_path)
        expected_jobs = (set(migration_record['original_jobs']) if migration_record else
                         {m + '/' + g for m in selected for g in manifest['games']})
        if (receipt.get('schema') != 'refine.authorized-new-experiment.v1'
                or receipt.get('user_authorized_fresh_budget') is not True
                or not receipt.get('user_request')
                or receipt.get('output') != str(output)
                or receipt.get('manifest_sha256') != sha(manifest_path)
                or set(receipt.get('prior_jobs', {})) != expected_jobs):
            raise ValueError('Restart authorization must bind exact output, manifest and selected jobs')
        base['authorized_new_experiment'] = {'path': str(receipt_path), 'sha256': sha(receipt_path)}
    if project_isolation and not migration_record:
        from pipeline.eval.repair import VERSION
        base['repair_execution_policy'] = {'version': VERSION, 'input': 'native_client', 'capture': 'native_viewport'}
    jobs = make_jobs(manifest, base, output, selected)
    if migration_record:
        from refine.recovery import runtime_config
        for job in jobs:
            job['config'] = runtime_config(migration_record, job['id'])
            job['migration'] = migration
            job['fresh_migration'] = job['id'] in migration_record.get('fresh_jobs', [])
    roots = history_roots(root, manifest.get('history_roots', []))
    state_path = output / 'matrix_status.json'
    state = read(state_path) if state_path.exists() else {}
    results = {}
    checked_sources = set()
    # Check is read-only, including lock files. Running/prepare locks all selected
    # jobs through this matrix; production engine leases remain in the child.
    from contextlib import nullcontext
    lock = nullcontext() if mode == 'check' else exclusive(output.parent / (output.name + '.matrix.lock'))
    with lock:
        state = read(state_path) if state_path.exists() else {}
        binding = {'manifest': manifest, 'base_config': base, 'source': str(manifest_path)}
        frozen = output / 'matrix_identity.json'
        if migration_record:
            from refine.recovery import verify_migration
            verify_migration(migration, output)  # Recheck after acquiring matrix ownership.
            binding = read(frozen)
        if frozen.exists() and read(frozen) != binding:
            raise ValueError('Matrix configuration changed; existing jobs cannot reset')
        if mode != 'check':
            freeze(frozen, binding)
        state_mutex = threading.Lock()
        cancelled, blocked = threading.Event(), threading.Event()
        circuits_path = output / 'matrix_provider_lanes.json'
        lane_faults = read(circuits_path) if circuits_path.exists() else {}
        lane_attempts = {}
        from pipeline.eval.refinement.repair_budget import provider_circuit_state
        for model in selected:
            probe = None
            if migration_record and model in migration_record.get('provider_probes', {}):
                from refine.recovery import verify_provider_probe
                cfg = next(job['config'] for job in jobs if job['model'] == model)
                probe = verify_provider_probe(migration_record['provider_probes'][model], model,
                                              cfg['agent'], cfg.get('provider_runtime_policy'))
            attempts = attempts_after_probe(historical_attempts(output, model), probe)
            lane_attempts[model] = attempts
            circuit = provider_circuit_state(attempts)
            prior = lane_faults.get(model)
            if circuit['pause_dispatch']:
                lane_faults[model] = {'status': 'PROVIDER_CIRCUIT_OPEN', **circuit,
                                     'retry_requires_connection_verification': True}
            elif probe and (not prior or all(Path(ref['path']).stat().st_mtime <= probe['completed_unix']
                                            for ref in prior.get('sources', []))):
                lane_faults.pop(model, None)
            elif attempts and prior and prior.get('status') == 'PROVIDER_CIRCUIT_OPEN':
                # A later, formally verified repair success also resets the circuit.
                lane_faults.pop(model, None)
        if mode != 'check' and (lane_faults or circuits_path.exists()):
            dump(circuits_path, lane_faults)

        def saved_fault(job, previous_rounds):
            from pipeline.eval.refinement.repair_budget import provider_circuit_state
            folder = job['output'] / 'games' / job['game'] / 'repair_rounds'
            new_rounds = sorted(path for path in folder.glob('round_*')
                                if path not in previous_rounds and (path / 'claim.json').is_file())
            with state_mutex:
                lane_attempts[job['model']].extend(new_rounds)
                attempts = list(lane_attempts[job['model']])
            if not attempts:
                return None
            circuit = provider_circuit_state(attempts)
            if circuit['pause_dispatch']:
                return {'status': 'PROVIDER_CIRCUIT_OPEN', 'job': job['id'], **circuit,
                        'retry_requires_connection_verification': True}
            return None

        def pause_lane(model, fault):
            with state_mutex:
                lane_faults[model] = fault
                if mode != 'check':
                    dump(circuits_path, lane_faults)

        def process_job(job):
            try:
                verify_inputs(base)
                with state_mutex:
                    snapshot = copy.deepcopy(state)
                    fault = lane_faults.get(job['model'])
                row = status(job, snapshot, root, roots, base)
                if fault and row['status'] != 'REPAIRED':
                    row = {**snapshot.get(job['id'], {}), 'provider_fault': fault, 'status': 'BLOCKED_PROVIDER_LANE'}
                if row['status'] == 'READY':
                    if mode != 'check' or job['game'] not in checked_sources:
                        from pipeline.eval.refinement.session import inventory, inventory_digest
                        source = base['project_overrides'][job['game']]['project_root']
                        if inventory_digest(inventory(source)) != base['frozen_project_sources'][job['game']]:
                            raise ValueError('Frozen source project changed: ' + source)
                        with state_mutex:
                            checked_sources.add(job['game'])
                    try:
                        preflight(job['config']['agent'])
                    except (ValueError, OSError) as exc:
                        row = {'status': 'BLOCKED_PROVIDER', 'error': str(exc)}
                        pause_lane(job['model'], {'status': 'PROVIDER_PREFLIGHT_BLOCKED', 'reason': str(exc)})
                if row['status'] == 'READY' and mode != 'check':
                    registry = registry_path(base, job)
                    with exclusive(registry_path(base, job, original=True).with_suffix('.lock')):
                        if job.get('migration'):
                            old_config = migration_record['original_configs'][job['id']]
                            expected = {'model': old_config['agent']['model'], 'game': job['game'],
                                        'output': str(job['output']), 'config_sha256': digest(old_config)}
                            freeze(registry, expected)
                            freeze(job['config_path'], old_config)
                            from refine.recovery import verify_migration
                            verify_migration(migration, output)
                            from pipeline.eval.refinement.repair_budget import verify_recovery
                            if not job.get('fresh_migration') and verify_recovery(job['output'] / 'games' / job['game'], job['config']).get('ready') is not True:
                                raise ValueError('Recovery authorization already consumed or no longer ready')
                        else:
                            freeze(registry, {'model': job['config']['agent']['model'], 'game': job['game'],
                                              'output': str(job['output']), 'config_sha256': digest(job['config'])})
                            freeze(job['config_path'], job['config'])
                        command = job_command(job, mode)
                        attempt = output / 'dispatches' / job['id'] / str(time.time_ns())
                        attempt.mkdir(parents=True, exist_ok=False)
                        recovery_admission = row.get('recovery')
                        row = {'status': 'RUNNING', 'mode': mode, 'command': command,
                               'dispatch': str(attempt), 'evaluation_started': False}
                        if job.get('migration'):
                            row.update(migration={'path': str(migration), 'sha256': sha(migration)},
                                       runtime_config_sha256=digest(job['config']),
                                       recovery=recovery_admission, previous_dispatch=snapshot.get(job['id']))
                        with state_mutex:
                            state[job['id']] = row
                            dump(state_path, state)  # Durable before child/model creation.
                        dump(attempt / 'claim.json', row)
                        previous_rounds = set((job['output'] / 'games' / job['game'] / 'repair_rounds').glob('round_*'))
                        with (attempt / 'stdout.log').open('w') as stdout, (attempt / 'stderr.log').open('w') as stderr:
                            extra = {'stop_event': cancelled} if runner is run_child else {}
                            result = runner(command, cwd=root, stdout=stdout, stderr=stderr, check=False, **extra)
                        ledger = job['output'] / 'ledger.json'
                        child_status = read(ledger).get(job['game'], {}) if ledger.exists() else {}
                        if result.returncode == 75 or child_status.get('status') == 'SAFETY_STOP':
                            row = {**row, 'status': 'SAFETY_STOP', 'child': child_status}
                        elif result.returncode != 0:
                            row = {**row, 'status': 'ERROR', 'exit_code': result.returncode, 'child': child_status}
                        elif mode == 'prepare':
                            row = {**row, 'status': 'PREPARED', 'exit_code': 0}
                        else:
                            row = {**row, **status(job, {}, root, roots, base), 'exit_code': 0}
                            if row['status'] != 'REPAIRED':
                                row.update(status='ERROR', error='Child exited without a verified closed repair pass')
                        fault = saved_fault(job, previous_rounds)
                        if fault:
                            row['provider_fault'] = fault
                            pause_lane(job['model'], fault)
                        if row['status'] == 'SAFETY_STOP' and project_isolation:
                            row['status'] = 'WAITING_RESOURCE'
                            with state_mutex:
                                lane_faults[job['model']] = {'status': 'WAITING_RESOURCE', 'reason': 'Shared execution resource busy; no new repair round authorized'}
                        dump(attempt / 'result.json', row)
            except BlockingIOError:
                row = {'status': 'SAFETY_STOP', 'reason': 'An existing identity/production lock is held'}
            except (ValueError, OSError, RuntimeError) as exc:
                row = {'status': 'ERROR', 'error': f'{type(exc).__name__}: {exc}'}
            with state_mutex:
                results[job['id']] = row
            if mode != 'check':
                with state_mutex:
                    state[job['id']] = row
                    dump(state_path, state)
                print(job['id'] + ': ' + row['status'], flush=True)
            if row['status'] == 'SAFETY_STOP' and not project_isolation:
                # Do not dispatch another 64 children into the same shared lock.
                blocked.set()

        if workers == 1 or mode != 'repair':
            for job in jobs:
                if blocked.is_set():
                    break
                process_job(job)
        else:
            # One lane per model, serial rounds/projects inside that lane.
            # Unity waits until other lanes leave native execution; UE copies coexist.
            condition = threading.Condition()
            running = []

            def lane(model):
                for job in (j for j in jobs if j['model'] == model):
                    engine = job['config']['project_overrides'][job['game']].get('engine', 'unknown')
                    with condition:
                        while running and (engine == 'unity3d' or 'unity3d' in running):
                            if cancelled.is_set() or blocked.is_set():
                                return
                            condition.wait(timeout=1)
                        if cancelled.is_set() or blocked.is_set():
                            return
                        running.append(engine)
                    try:
                        process_job(job)
                    finally:
                        with condition:
                            running.remove(engine)
                            condition.notify_all()

            pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix='refine-model')
            try:
                futures = [pool.submit(lane, model) for model in selected]
                for future in as_completed(futures):
                    future.result()
            except BaseException:
                cancelled.set()
                raise
            finally:
                pool.shutdown(wait=True, cancel_futures=True)
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument('--output', type=Path, default=BENCH / 'test_data/outputs/game_refine/stage3_five_models_v1')
    parser.add_argument('--models', nargs='+', help='Default: every model in manifest; e.g. astra sol glm opus kimi')
    parser.add_argument('--mode', choices=('check', 'prepare', 'repair'), default='check')
    parser.add_argument('--restart-authorization', type=Path,
                        help='Explicit user-authorized new experiment receipt; never inferred from a new output')
    parser.add_argument('--workers', type=int, choices=(1, 2, 3), default=1, help='Concurrent model lanes; each model remains serial')
    parser.add_argument('--project-isolation', action='store_true', help='Opt in at a new or formally migrated boundary; UE candidate leases and separate ports, Unity serial')
    parser.add_argument('--matrix-migration', type=Path, help='ACTIVE source-bound migration; preserve original scope/config/pins')
    args = parser.parse_args(argv)
    try:
        result = execute(args.manifest, args.output, args.models, mode=args.mode,
                         restart_authorization=args.restart_authorization, workers=args.workers,
                         project_isolation=args.project_isolation, migration=args.matrix_migration)
    except (ValueError, OSError, RuntimeError) as exc:
        print(f'{type(exc).__name__}: {exc}', file=sys.stderr)
        return 2
    counts = {}
    for row in result.values():
        counts[row['status']] = counts.get(row['status'], 0) + 1
    print(json.dumps({'jobs': result, 'counts': counts, 'evaluation_started': False}, ensure_ascii=False, indent=2))
    return 0 if all(r['status'] in ('READY', 'PREPARED', 'REPAIRED') for r in result.values()) else 2


if __name__ == '__main__':
    def stop(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('Interrupted: dispatch claim and round counts preserved; inspect cleanup before recovery.', file=sys.stderr)
        raise SystemExit(130)
