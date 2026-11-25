"""Single serial entry for preparation, one-session repair, evaluation and resume."""
from __future__ import annotations
import argparse
from contextlib import contextmanager, nullcontext
import fcntl
import copy
import json
from pathlib import Path
import sys
import time
from .common import dump, read, resolve, sha, once
from .collect import load


@contextmanager
def exclusive(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def normalize(raw):
    config = copy.deepcopy(raw)
    config['bench_root'] = str(Path(config['bench_root']).expanduser().resolve())
    root = config['bench_root']
    for key in ('adapter_root', 'editor_acceptance', 'control_root'):
        if config.get('unity', {}).get(key):
            config.setdefault('unity', {})[key] = str(resolve(root, config['unity'][key]))
    if config.get('unity', {}).get('editor_acceptances'):
        config['unity']['editor_acceptances'] = [str(resolve(root, p)) for p in config['unity']['editor_acceptances']]
    for key in ('playwright_root', 'browser'):
        if config.get('renderer', {}).get(key):
            config.setdefault('renderer', {})[key] = str(resolve(root, config['renderer'][key]))
    return config


def code_identity():
    package = Path(__file__).resolve().parent
    return {path.name: sha(path) for path in sorted(package.glob('*.py'))}


def prepare(config, output):
    from .rounds import validate_budget
    validate_budget(config)
    output = Path(output).resolve()
    if (output / 'configuration.json').exists():
        current = code_identity()
        migration_path = output / 'implementation_migration.json'
        if migration_path.is_file():
            from .common import read as read_json
            if read_json(migration_path).get('schema') == 'refine.implementation-migration.v2':
                from .migration import verify_runtime_config
                verify_runtime_config(output, config, current)
        if read(output / 'configuration.json') != config:
            if not (output / 'implementation_migration.json').is_file():
                raise ValueError('Configuration changed; explicit v2 implementation migration required')
            from .migration import verify_runtime_config
            verify_runtime_config(output, config, current)
        elif read(output / 'code_identity.json') != current:
            from .migration import verify_migration
            verify_migration(output, current)
        inventory = read(output / 'inventory.json')
        for ref in inventory['sources'].values():
            if sha(ref['path']) != ref['sha256']:
                raise ValueError('Frozen collect changed: ' + ref['path'])
        return inventory
    inventory = load(config)
    # Never place repair output inside an original project or collect input directory.
    for game in inventory['games']:
        project = game.get('project')
        if project:
            source = Path(project['project_root'])
            if output == source or output.is_relative_to(source):
                raise ValueError('Output must be outside original delivery')
    dump(output / 'configuration.json', config)
    dump(output / 'code_identity.json', code_identity())
    dump(output / 'inventory.json', inventory)
    summary = {'games': len(inventory['games']),
        'located_projects': sum(g['project'] is not None for g in inventory['games']),
        'repairs': sum(len(g['repairs']) for g in inventory['games']),
        'imports': sum(len(g['imports']) for g in inventory['games']),
        'repair_rounds_per_project': config.get('repair_rounds', 1),
        'vfx_repairs': sum(r['selection_kind'] == 'vfx' for g in inventory['games'] for r in g['repairs']),
        'ready_payloads': sum(i['payload']['status'] == 'READY' for g in inventory['games'] for i in g['imports']),
        'stale_project_indexes': [g['game_id'] for g in inventory['games'] if g['project_resolution']['stale_initial_index']],
        'mode': 'PREPARED_ONLY; no agents, model calls or engines started'}
    dump(output / 'preparation_summary.json', summary)
    return inventory



def require_completed_repairs(config, output, inventory):
    """The final-only evaluation barrier also applies to direct evaluation commands."""
    limit = config.get('repair_rounds', 1)
    if limit == 1 and config.get('interaction_policy') not in (
            'fresh_session_1500s_work_300s_handoff_10attempts.v2',
            'fresh_session_multi_provider_1500s_work_300s_handoff_10attempts.v3'):
        return
    sessions = set()
    for game in inventory['games']:
        folder = Path(output) / 'games' / game['game_id']
        if config.get('interaction_policy') in ('fresh_session_1500s_work_300s_handoff_10attempts.v2',
                'fresh_session_multi_provider_1500s_work_300s_handoff_10attempts.v3'):
            from .fresh_sessions import validate
            validate(folder, config)
            continue
        summary = folder / 'repair_rounds/summary.json'
        if not summary.is_file():
            raise ValueError('All project repairs must finish before evaluation: ' + game['game_id'])
        saved = read(summary)
        completed = saved.get('rounds_completed')
        attempted = saved.get('rounds_attempted', completed)
        if (saved.get('status') != 'REPAIRED' or type(completed) is not int or
                not 1 <= completed <= limit or type(attempted) is not int or
                not completed <= attempted <= limit or
                (attempted < limit and saved.get('stop_reason') not in
                 ('SOURCE_WORK_COMPLETE', 'EXTERNAL_BLOCKERS_ONLY'))):
            raise ValueError('All project repairs must finish before evaluation: ' + game['game_id'])
        if attempted < limit:
            from .rounds import turn_location, stop_decision
            _, final_root = turn_location(folder, attempted)
            decision = stop_decision(game, folder, final_root, attempted)
            if (not decision['stop'] or saved.get('source_completion') != decision or
                    saved.get('stop_reason') != decision['reason']):
                raise ValueError('Early repair stop has no valid source completion report')
        interruptions = []
        for number in range(1, attempted + 1):
            from .interruption import checkpoint
            if checkpoint(folder, number, config) is not None:
                interruptions.append(number)
                continue
            from .rounds import turn_location
            name, _ = turn_location(folder, number)
            marker = folder / 'stages' / (name + '.json')
            if not marker.is_file() or read(marker)['status'] != 'COMPLETE':
                raise ValueError('Repair turn is not complete: ' + str(marker))
        if (saved.get('interrupted_rounds', []) != interruptions or
                completed != attempted - len(interruptions)):
            raise ValueError('Repair attempt/completion counts changed')
        identity = read(folder / 'agent_identity.json')
        ids = identity.get('session_ids', [])
        if len(ids) != 1 or ids[0] in sessions or identity.get('model') != config['agent']['model']:
            raise ValueError('Each repaired project must have its own unique conversation/model')
        sessions.add(ids[0])


def run(config, output, mode):
    from .session import inventory as source_inventory
    from .rounds import repair_project
    from ..stage1 import unity_safety
    inventory = prepare(config, output)
    if mode == 'prepare':
        return read(Path(output) / 'preparation_summary.json')
    if mode in ('evaluate', 'run', 'static') and not config.get('sol', {}).get('model'):
        raise ValueError('sol.model must be configured before starting evaluation or any repair+evaluation run')
    if mode == 'run' and config.get('repair_rounds', 1) > 1:
        # Finish the pure repair pass for every project before any evaluation.
        run(config, output, 'repair')
        return run(config, output, 'evaluate')
    if mode in ('evaluate', 'static'):
        require_completed_repairs(config, output, inventory)
    unity = config.get('unity', {})
    if not unity.get('control_root'):
        raise ValueError('unity.control_root required for shared production serialization and safety gates')
    # This is the SAME production lease used by whitebox workflows, not a competing private lock.
    # Acquisition is nonblocking: do not wait forever on another conversation or take over its work.
    lease = Path(unity['control_root']) / 'whitebox_production_queue.lock'
    ledger = read(Path(output) / 'ledger.json') if (Path(output) / 'ledger.json').exists() else {}
    from ..stage1.engine_execution import repair_scope, lease as engine_lease
    scoped_engine = repair_scope(config, inventory, mode) if mode != 'static' else None
    execution = (nullcontext() if mode == 'static' else
                 engine_lease(Path(unity['control_root']), scoped_engine,
                     Path(output).resolve(), Path(output).resolve()/'engine_execution'/
                     (str(time.time_ns())+'_'+str(__import__('os').getpid())+'.json'),
                     policy=config['engine_execution_policy']) if scoped_engine else exclusive(lease))
    if config.get('repair_execution_policy') and mode != 'static':
        from ..stage1.repair_execution import lease as project_lease
        execution = project_lease(config, inventory, Path(output).resolve(), mode=mode)
    with execution:
        if mode != 'static':
            unity_safety.locks_clear(unity, check_external=True)
        failures = 0
        for game in inventory['games']:
            gid = game['game_id']
            folder = Path(output) / 'games' / gid
            folder.mkdir(parents=True, exist_ok=True)
            started = time.time()
            try:
                if mode != 'static':
                    unity_safety.locks_clear(unity, check_external=True)
                if not game['project']:
                    ledger[gid] = {'status': 'BLOCKED_NO_PROJECT'}
                    dump(Path(output) / 'ledger.json', ledger)
                    continue
                if mode in ('repair', 'run'):
                    repair_summary = repair_project(game, folder, config)
                if mode in ('evaluate', 'static') and gid in config.get('repair_sources', {}):
                    from .reuse import attach
                    once(folder, 'bind_repair_output', lambda g=game, f=folder: attach(g, f, config))
                if mode in ('evaluate', 'run', 'static'):
                    from .evaluation import evaluate
                    if not (folder / 'repaired_project.json').is_file():
                        raise ValueError('No completed repair session; run repair first in this same output')
                    if source_inventory(folder / 'workspace/project') != read(folder / 'repaired_project.json')['files']:
                        raise ValueError('Repaired source changed after saved session')
                    result = evaluate(game, folder, config, static_only=True) if mode == 'static' else evaluate(game, folder, config)
                    ledger[gid] = {'status': result['status'], 'result': str(folder / ('static_result.json' if mode == 'static' else 'result.json')),
                                   'product_status': result.get('product_status'),
                                   'pipeline_completed': result.get('pipeline_completed', result['status'] == 'EVALUATED')}
                else:
                    ledger[gid] = {'status': 'REPAIRED', 'session': str(folder / 'agent_session'),
                                   'rounds_completed': repair_summary['rounds_completed'],
                                   'rounds_limit': config.get('repair_rounds', 1),
                                   'rounds_attempted': repair_summary.get('rounds_attempted', repair_summary['rounds_completed']),
                                   'interrupted_rounds': repair_summary.get('interrupted_rounds', []),
                                   'stop_reason': repair_summary.get('stop_reason'),
                                   'evaluation_started': False}
                if mode != 'static':
                    unity_safety.locks_clear(unity, check_external=True)
                failures = 0
            except (unity_safety.SafetyStop, BlockingIOError) as exc:
                ledger[gid] = {'status': 'SAFETY_STOP', 'error': str(exc)}
                dump(Path(output) / 'ledger.json', ledger)
                raise
            except Exception as exc:
                # A harness/model/session failure is not a game BUG or a zero score.
                ledger[gid] = {'status': 'ERROR', 'error': f'{type(exc).__name__}: {exc}',
                               'formal_score': None}
                failures += 1
                if mode != 'static':
                    unity_safety.locks_clear(unity, check_external=True)
                if failures >= config.get('consecutive_error_limit', 2):
                    dump(Path(output) / 'ledger.json', ledger)
                    raise RuntimeError('Consecutive environment/session error limit reached') from exc
            finally:
                ledger.setdefault(gid, {})['elapsed_seconds'] = time.time() - started
                dump(Path(output) / 'ledger.json', ledger)
    return ledger


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mode', choices=('prepare', 'repair', 'evaluate', 'run', 'static', 'resume-repair'), default='prepare')
    parser.add_argument('--resume-game', help='one failed frozen game for explicit same-session continuation')
    parser.add_argument('--resume-session', help='exact persisted ZCode session from original provider events')
    args = parser.parse_args(argv)
    if args.mode == 'resume-repair' and not (args.resume_game and args.resume_session):
        parser.error('resume-repair requires --resume-game and --resume-session')
    if args.mode != 'resume-repair' and (args.resume_game or args.resume_session):
        parser.error('resume arguments only apply to resume-repair')
    config = normalize(read(args.config))
    output = args.output.expanduser().resolve()
    with exclusive(output.parent / (output.name + '.batch.lock')):
        if args.mode == 'resume-repair':
            from .repair_recovery import resume
            result = resume(config, output, args.resume_game, args.resume_session)
        else:
            result = run(config, output, args.mode)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.mode != 'prepare' and any(r.get('status') in ('ERROR', 'SAFETY_STOP', 'BLOCKED_NO_PROJECT', 'BLOCKED_RUNTIME')
                                     for r in result.values()):
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
