"""Explicit Stage3 dispatcher boundaries and immutable migration receipts.

No operation runs a worker. Signal helpers are opt-in calls by the coordinator;
all verification functions and prepare_migration are read-only to the live run.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import sys
import time
import uuid

BENCH = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(BENCH))
from pipeline.eval.refine.common import read, sha


def write_receipt(path, value):
    """Publish once without replacing an existing receipt, even across threads."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('x') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)  # Atomic, fails rather than resetting old evidence.
    finally:
        temporary.unlink(missing_ok=True)
    return value


def reference(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': sha(path)}


def verify_ref(ref):
    if sha(ref['path']) != ref['sha256']:
        raise ValueError('Migration source changed: ' + ref['path'])
    return Path(ref['path'])


def parse_process(line):
    fields = line.strip().split(None, 8)
    if len(fields) != 9:
        raise ValueError('Expected ps pid,ppid,lstart,stat,command')
    return {'pid': int(fields[0]), 'ppid': int(fields[1]),
            'lstart': ' '.join(fields[2:7]), 'stat': fields[7], 'cmd': fields[8]}


def process_table():
    result = subprocess.run(['ps', '-axo', 'pid=,ppid=,lstart=,stat=,command='],
                            capture_output=True, text=True, check=True)
    return {item['pid']: item for item in map(parse_process, result.stdout.splitlines())}


def process_identity(pid):
    return process_table().get(int(pid))


def same_process(expected, actual):
    return actual is not None and all(actual[k] == expected[k] for k in ('pid', 'lstart', 'cmd'))


def descendants(table, pid):
    found = set()
    pending = [pid]
    while pending:
        parent = pending.pop()
        children = {p for p, row in table.items() if row['ppid'] == parent} - found
        found.update(children)
        pending.extend(children)
    return found


def boundary_identities(record):
    """Normalize supported external receipt versions without losing their source."""
    parent = record.get('parent')
    if parent is None:
        parent_line = (record.get('parent_after') or record.get('parent_after_boundary')
                       or record.get('parent_before_boundary') or record.get('parent_before'))
        if not parent_line:
            raise ValueError('Boundary receipt has no parent process identity')
        parent = parse_process(parent_line) if isinstance(parent_line, str) else parent_line
    children = record.get('children')
    if children is None:
        children = record.get('children_before', record.get('children_before_boundary', []))
    children = [parse_process(child) if isinstance(child, str) else child for child in children]
    return parent, children


def _owned_parent(parent, output):
    args = shlex.split(parent['cmd'])
    if (not any(Path(arg).name == 'refine_game.py' for arg in args)
            or '--output' not in args
            or Path(args[args.index('--output') + 1]).resolve() != Path(output).resolve()
            or '--mode' not in args or args[args.index('--mode') + 1] != 'repair'):
        raise ValueError('Parent command does not bind this repair matrix output')


def suspend_dispatch(expected_parent, expected_child, receipt_path, *, probe=process_table,
                     send_signal=os.kill):
    """Strictly recheck identity and signal the parent only; never signal its child."""
    if Path(receipt_path).exists():
        raise ValueError('Suspension receipt already exists')
    before = probe()
    parent = before.get(expected_parent['pid'])
    child = before.get(expected_child['pid'])
    if not same_process(expected_parent, parent) or not same_process(expected_child, child):
        raise ValueError('Parent/child identity changed before suspension')
    if child['ppid'] != parent['pid']:
        raise ValueError('Protected child is no longer owned by parent')
    direct = {p for p, row in before.items() if row['ppid'] == parent['pid']}
    if direct != {child['pid']}:
        raise ValueError('Expected exactly one protected child')
    record = {'schema': 'refine.dispatch-suspension.v1', 'parent': parent, 'children': [child],
              'descendants': [before[p] for p in sorted(descendants(before, parent['pid']))],
              'signal': 'SIGSTOP_PARENT_ONLY', 'unix': time.time(), 'evaluation_started': False}
    intent = Path(receipt_path).with_name(Path(receipt_path).name + '.intent.json')
    write_receipt(intent, {**record, 'status': 'SUSPEND_REQUESTED'})
    # A second observation immediately before sending prevents stale inspected PIDs.
    if not same_process(parent, probe().get(parent['pid'])):
        raise ValueError('Parent identity changed at signal boundary')
    send_signal(parent['pid'], signal.SIGSTOP)
    after = probe()
    if not same_process(parent, after.get(parent['pid'])) or 'T' not in after[parent['pid']]['stat']:
        raise ValueError('Parent suspension not confirmed; preserve intent and inspect')
    direct_after = [row for row in after.values() if row['ppid'] == parent['pid']]
    if any(not same_process(child, row) for row in direct_after):
        raise ValueError('Child changed during suspension; preserve intent and inspect')
    return write_receipt(receipt_path, {**record, 'parent': after[parent['pid']],
        'status': 'DISPATCH_SUSPENDED_CHILD_PRESERVED', 'intent': reference(intent)})


def validate_boundary(boundary, output, *, require_exit=False, probe=process_table):
    record = read(boundary)
    if record.get('status') not in ('DISPATCH_SUSPENDED_CHILD_PRESERVED', 'OLD_SCHEDULER_EXIT_CONFIRMED'):
        raise ValueError('Expected explicit external dispatch suspension')
    parent, children = boundary_identities(record)
    _owned_parent(parent, output)
    if len(children) > 1:
        raise ValueError('Expected at most one protected child')
    for child in children:
        args = shlex.split(child['cmd'])
        if (child['ppid'] != parent['pid'] or '--output' not in args
                or not Path(args[args.index('--output') + 1]).resolve().is_relative_to(Path(output).resolve() / 'batches')):
            raise ValueError('Protected child does not bind the frozen matrix')
    table = probe()
    live_parent = table.get(parent['pid'])
    if live_parent:
        if not same_process(parent, live_parent):
            raise ValueError('Parent PID reused; inspect identity before migration')
        if require_exit or 'T' not in live_parent['stat']:
            raise ValueError('Old parent must be STOPPED for prepare, exited for activation')
        direct = [row for row in table.values() if row['ppid'] == parent['pid']]
        if any(not any(same_process(c, row) for c in children) for row in direct):
            raise ValueError('Unexpected child; parent crossed the declared boundary')
    for expected in [*children, *record.get('descendants', [])]:
        actual = table.get(expected['pid'])
        if actual and not same_process(expected, actual):
            raise ValueError('Protected descendant PID reused; inspect before migration')
        if require_exit and actual:
            raise ValueError('Protected child/descendant still exists; cannot dispatch')
    if require_exit and descendants(table, parent['pid']):
        raise ValueError('Old descendants have not exited')
    return record


def terminate_stopped_parent(boundary, completion, receipt_path, *, probe=process_table,
                             send_signal=os.kill):
    """Coordinator only: after verified child completion, terminate only stopped parent.

    SIGTERM is queued before SIGCONT; the legacy parent's SIGTERM handler exits
    through KeyboardInterrupt. Activation separately verifies the resulting exit.
    """
    record = read(boundary)
    parent, children = boundary_identities(record)
    done = read(completion)
    if (done.get('status') != 'CHILD_EXIT_CONFIRMED' or not done.get('sources')
            or done.get('boundary') != reference(boundary) or done.get('cleanup_verified') is not True):
        raise ValueError('Require source-bound child completion and cleanup receipt')
    for ref in done['sources']:
        verify_ref(ref)
    table = probe()
    if any(c['pid'] in table for c in [*children, *record.get('descendants', [])]) or descendants(table, parent['pid']):
        raise ValueError('Protected child/descendants still exist')
    actual = table.get(parent['pid'])
    if not same_process(parent, actual) or 'T' not in actual['stat']:
        raise ValueError('Expected exact stopped parent')
    intent = Path(receipt_path).with_name(Path(receipt_path).name + '.intent.json')
    payload = {'schema': 'refine.old-parent-exit.v1', 'boundary': reference(boundary),
               'completion': reference(completion), 'parent': actual, 'unix': time.time()}
    write_receipt(intent, {**payload, 'status': 'PARENT_EXIT_REQUESTED'})
    if not same_process(parent, probe().get(parent['pid'])):
        raise ValueError('Parent identity changed at signal boundary')
    send_signal(parent['pid'], signal.SIGTERM)
    if same_process(parent, probe().get(parent['pid'])):
        send_signal(parent['pid'], signal.SIGCONT)
    return write_receipt(receipt_path, {**payload, 'status': 'PARENT_EXIT_SIGNALLED', 'intent': reference(intent)})


def production_sources():
    """Bind current implementation, including helpers outside the refine package."""
    paths = set((BENCH / 'scripts/refine').glob('*.py'))
    paths.update((BENCH / 'GameFactory-3A/pipeline/eval/refine').glob('*.py'))
    for suffix in ('*.py', '*.cpp', '*.h', '*.cs', '*.uplugin'):
        paths.update((BENCH / 'GameFactory-3A/engine_adapters/ue5').rglob(suffix))
    paths.update(BENCH / 'scripts' / name for name in
                 ('refine_game.py', 'run_stage3_refine.py', 'resume_stage3_refine.py', 'stage3_run_layout.py'))
    paths.update(BENCH / 'GameFactory-3A/pipeline/eval/stage1' / name
                 for name in ('repair_execution.py', 'unity_safety.py'))
    return sorted(p for p in paths if p.is_file())


def frozen_sources(output):
    output = Path(output)
    paths = {output / 'matrix_identity.json'}
    paths.update((output / 'configs').rglob('*.json'))
    for pattern in ('batches/*/*/configuration.json', 'batches/*/*/code_identity.json',
                    'batches/*/*/stage3_prompt_identity.json', 'batches/*/*/inventory.json'):
        paths.update(output.glob(pattern))
    return sorted(paths)


def verify_provider_probe(ref, lane, agent, runtime_policy=None):
    """Validate immutable route identity and an actual successful CLI completion."""
    value = read(verify_ref(ref))
    if (value.get('schema') != 'refine.provider-probe.v1'
            or value.get('status') != 'CONNECTION_VERIFIED' or value.get('lane') != lane
            or value.get('provider') != agent['provider'] or value.get('model') != agent['model']
            or value.get('provider_runtime_policy', {}) != (runtime_policy or {})
            or not value.get('sources') or type(value.get('completed_unix')) not in (int, float)):
        raise ValueError('Provider probe must bind the exact lane, route and runtime policy')
    completed = []
    import math
    if not math.isfinite(value['completed_unix']) or value['completed_unix'] > time.time():
        raise ValueError('Invalid probe completion time')
    for source in value['sources']:
        path = verify_ref(source)
        if path.suffix != '.jsonl':
            continue
        terminal = None
        for line in path.read_text(errors='replace').splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get('type') in ('turn.completed', 'turn.failed'):
                terminal = event
        if (terminal and terminal['type'] == 'turn.completed' and not terminal.get('error')
                and terminal.get('payload', {}).get('resultType', 'success') == 'success'):
            completed.append(path.stat().st_mtime)
    if not any(abs(t - value['completed_unix']) < .001 for t in completed):
        raise ValueError('Provider probe needs a successful raw CLI event and its completion mtime')
    return value


def verify_qualification(ref):
    """Bind coordinator-provided native acceptance; fixtures are never acceptance."""
    value = read(verify_ref(ref))
    if value.get('status') != 'QUALIFIED' or not value.get('sources'):
        raise ValueError('Native qualification must be QUALIFIED with full source references')
    for source in [*value['sources'], *value.get('production_sources', [])]:
        verify_ref(source)
    return value


def _fresh_job(output, model, game):
    """Only proven prepare-only dispatches may precede an unstarted job."""
    output = Path(output)
    child = output / 'batches' / model / game
    folder = child / 'games' / game
    if (any(p.exists() or p.is_symlink() for p in
            (child / 'configuration.json', folder / 'original_project.json'))
            or any(folder.glob('repair_rounds/round_*'))):
        return False
    dispatches = output / 'dispatches' / model / game
    for attempt in dispatches.iterdir() if dispatches.exists() else ():
        try:
            path = attempt / 'claim.json'
            claim, result = read(path), read(path.with_name('result.json'))
            if (claim.get('mode') != 'prepare' or result.get('mode') != 'prepare'
                    or result.get('status') != 'PREPARED'
                    or type(result.get('exit_code')) is not int or result['exit_code'] != 0
                    or not isinstance(claim.get('command'), list) or not claim['command']
                    or not all(isinstance(arg, str) for arg in claim['command'])
                    or claim['command'] != result.get('command')):
                return False
            command = claim['command']
            modes = [command[i + 1] if arg == '--mode' and i + 1 < len(command) else
                     arg.split('=', 1)[1] if arg.startswith('--mode=') else None
                     for i, arg in enumerate(command) if arg == '--mode' or arg.startswith('--mode=')]
            if modes != ['prepare']:
                return False
        except (OSError, ValueError, TypeError, AttributeError):
            return False  # Unknown, unfinished or corrupt claims never reset a job.
    return True


def prepare_migration(output, authorization, boundary, production_files=None, *, models=('sol', 'glm'),
                      job_recoveries=None, runtime_overrides=None, provider_probes=None, qualifications=None,
                      probe=process_table, destination=None):
    """Create PREPARED only. A stopped parent and its live child may still exist."""
    output = Path(output).resolve()
    validate_boundary(boundary, output, probe=probe)
    identity = read(output / 'matrix_identity.json')
    authorization = Path(authorization).resolve()
    auth = read(authorization)
    frozen_auth = identity['base_config'].get('authorized_new_experiment')
    jobs = set(auth.get('prior_jobs', {}))
    if (frozen_auth != reference(authorization) or auth.get('output') != str(output)
            or auth.get('schema') != 'refine.authorized-new-experiment.v1'
            or sha(identity['source']) != auth.get('manifest_sha256')
            or not models or set(models) - {'sol', 'glm'} or len(models) != len(set(models))
            or set(models) - {key.split('/')[0] for key in jobs}
            or jobs != {key for key in jobs if key.split('/')[0] in identity['manifest']['models']}):
        raise ValueError('Migration must retain original authorization and model scope')
    expected = {m + '/' + g for m in {j.split('/')[0] for j in jobs} for g in identity['manifest']['games']}
    if jobs != expected:
        raise ValueError('Original authorized identities are incomplete')
    from refine.matrix import make_jobs
    original_models = list(dict.fromkeys(j.split('/')[0] for j in sorted(jobs)))
    original_configs = {}
    for job in make_jobs(identity['manifest'], identity['base_config'], output, original_models):
        cfg = read(job['config_path']) if job['config_path'].exists() else job['config']
        if cfg != job['config']:
            raise ValueError('Original per-job configuration differs from frozen matrix: ' + job['id'])
        original_configs[job['id']] = cfg
    files = production_sources() if production_files is None else production_files
    refs = [reference(p) for p in files]
    if not refs:
        raise ValueError('Current production SHA binding required')
    overrides = runtime_overrides or {}
    if set(overrides) - set(models) or any(set(v) - {'provider_runtime_policy'} for v in overrides.values()):
        raise ValueError('Only explicit provider runtime settings may supplement frozen config')
    recoveries = job_recoveries or {}
    if set(recoveries) - jobs:
        raise ValueError('Recovery mapping contains an unknown identity')
    for ref in recoveries.values():
        verify_ref(ref)
    probes = provider_probes or {}
    if set(probes) - set(models):
        raise ValueError('Probe mapping contains an inactive model lane')
    for model, ref in probes.items():
        cfg = next(v for k, v in original_configs.items() if k.split('/')[0] == model)
        verify_provider_probe(ref, model, cfg['agent'], overrides.get(model, {}).get('provider_runtime_policy'))
    qualifications = qualifications or []
    for ref in qualifications:
        verify_qualification(ref)
    fresh = sorted(job_id for job_id in jobs if _fresh_job(output, *job_id.split('/')))
    record = {'schema': 'refine.matrix-migration.v1', 'status': 'PREPARED', 'output': str(output),
        'authorization': reference(authorization), 'boundary': reference(boundary),
        'original_identity': reference(output / 'matrix_identity.json'), 'original_jobs': sorted(jobs),
        'original_configs': original_configs,
        'models': list(models), 'paused_models': sorted({j.split('/')[0] for j in jobs} - set(models)),
        'frozen_sources': [reference(p) for p in frozen_sources(output)],
        'production_sources': refs, 'job_recoveries': recoveries, 'runtime_overrides': overrides,
        'fresh_jobs': fresh, 'provider_probes': probes, 'qualifications': qualifications,
        'execution_policy': {'version': 'refine-project-execution.v1', 'input': 'native_client', 'capture': 'native_viewport'},
        'budget_policies': {'sol': 'sol_effective_success_10.v1', 'glm': 'physical_attempt_10_recovery.v1'},
        'unix': time.time(), 'evaluation_started': False}
    target = Path(destination) if destination else output / 'matrix_migrations' / str(time.time_ns()) / 'prepared.json'
    write_receipt(target, record)
    return target


def verify_migration(path, output, *, require_active=True, probe=process_table):
    record = read(path)
    if (record.get('schema') != 'refine.matrix-migration.v1' or record.get('output') != str(Path(output).resolve())
            or record.get('status') not in (('ACTIVE',) if require_active else ('PREPARED', 'ACTIVE'))):
        raise ValueError('Migration must bind this output and be ACTIVE before dispatch')
    for ref in [record['authorization'], record['boundary'], record['original_identity'],
                *record['frozen_sources'], *record['production_sources'], *record['job_recoveries'].values()]:
        verify_ref(ref)
    if record.get('status') == 'ACTIVE' and not record.get('prepared'):
        raise ValueError('Active migration requires immutable prepared binding')
    if record.get('prepared'):
        prepared = read(verify_ref(record['prepared']))
        if prepared.get('status') != 'PREPARED' or any(record.get(k) != v for k, v in prepared.items() if k != 'status'):
            raise ValueError('Active migration differs from prepared binding')
    validate_boundary(record['boundary']['path'], output, require_exit=require_active, probe=probe)
    identity = read(record['original_identity']['path'])
    auth = read(record['authorization']['path'])
    if (identity['base_config'].get('authorized_new_experiment') != record['authorization']
            or record['original_jobs'] != sorted(auth['prior_jobs'])
            or not record['models'] or set(record['models']) - {'sol', 'glm'}
            or len(record['models']) != len(set(record['models']))
            or record['execution_policy'] != {'version': 'refine-project-execution.v1', 'input': 'native_client', 'capture': 'native_viewport'}
            or record['budget_policies'] != {'sol': 'sol_effective_success_10.v1', 'glm': 'physical_attempt_10_recovery.v1'}):
        raise ValueError('Migration identity, scope or runtime policy changed')
    overrides = record.get('runtime_overrides', {})
    if (set(overrides) - set(record['models'])
            or any(set(v) - {'provider_runtime_policy'} for v in overrides.values())):
        raise ValueError('Only explicit provider runtime settings may supplement frozen config')
    from pipeline.eval.refine.providers import validate_runtime_policy
    for model, overlay in overrides.items():
        cfg = next(v for k, v in record['original_configs'].items() if k.split('/')[0] == model)
        validate_runtime_policy(cfg['agent'], overlay.get('provider_runtime_policy'))
    if (set(record.get('fresh_jobs', [])) - set(record['original_jobs'])
            or set(record.get('provider_probes', {})) - set(record['models'])):
        raise ValueError('Fresh jobs/probes exceed frozen scope')
    for model, ref in record.get('provider_probes', {}).items():
        cfg = next(v for k, v in record['original_configs'].items() if k.split('/')[0] == model)
        value = verify_provider_probe(ref, model, cfg['agent'],
                    record.get('runtime_overrides', {}).get(model, {}).get('provider_runtime_policy'))
        if value['completed_unix'] > record['unix']:
            raise ValueError('Probe completed after this migration was prepared')
    for ref in record.get('qualifications', []):
        verify_qualification(ref)
    return record


def runtime_config(record, job_id):
    """Derive a runtime overlay; never change the historical config or source pins."""
    import copy
    if job_id not in record['original_jobs'] or job_id.split('/')[0] not in record['models']:
        raise ValueError('Job outside migrated active model lanes')
    model, game = job_id.split('/')
    output = Path(record['output'])
    path = output / 'configs' / model / (game + '.json')
    config = copy.deepcopy(record['original_configs'][job_id])
    if path.exists() and read(path) != config:
        raise ValueError('Original job configuration changed')
    config['repair_execution_policy'] = copy.deepcopy(record['execution_policy'])
    if job_id not in record.get('fresh_jobs', []):
        config['repair_budget_policy'] = record['budget_policies'][model]
    from stage3_run_layout import candidate_location
    _, candidate = candidate_location({'game_id': game, 'project': config['project_overrides'][game]},
                                      output / 'batches' / model / game / 'games' / game, config)
    config['repair_candidate_root'] = str(candidate)
    config.update(copy.deepcopy(record.get('runtime_overrides', {}).get(model, {})))
    return config


def activate_migration(prepared_path, *, probe=process_table):
    record = read(prepared_path)
    if record.get('status') != 'PREPARED':
        raise ValueError('Expected PREPARED migration')
    verify_migration(prepared_path, record['output'], require_active=False, probe=probe)
    validate_boundary(record['boundary']['path'], record['output'], require_exit=True, probe=probe)
    target = Path(prepared_path).with_name('active.json')
    write_receipt(target, {**record, 'status': 'ACTIVE', 'prepared': reference(prepared_path), 'activated_unix': time.time()})
    return target


def reconcile_child_exit(output, job_id, boundary, completion_path, *, cleanup_receipt=None,
                         candidate_location=None, probe=process_table):
    """Bind real terminal child artifacts without editing old claims or guessing success."""
    output = Path(output).resolve()
    record = validate_boundary(boundary, output, probe=probe)
    parent, children = boundary_identities(record)
    table = probe()
    if any(c['pid'] in table for c in [*children, *record.get('descendants', [])]):
        raise ValueError('Protected child has not exited')
    if descendants(table, parent['pid']):
        raise ValueError('Old descendants have not exited')
    parts = job_id.split('/')
    if len(parts) != 2 or any(not re.fullmatch(r'[A-Za-z0-9_.-]+', p) for p in parts):
        raise ValueError('Unsafe job identity')
    model, game = parts
    child_output = output / 'batches' / model / game
    if not children or not all('--output ' + str(child_output) in c['cmd'] for c in children):
        raise ValueError('Completion does not match the protected child output')
    ledger = child_output / 'ledger.json'
    row = read(ledger).get(game, {})
    if row.get('status') not in ('ERROR', 'REPAIRED', 'SAFETY_STOP'):
        raise ValueError('No durable terminal child ledger; do not infer an exit result')
    state = read(output / 'matrix_status.json').get(job_id, {})
    dispatch = Path(state['dispatch']).resolve()
    if not dispatch.is_relative_to(output / 'dispatches' / model / game):
        raise ValueError('Dispatch escapes the protected identity')
    refs = [reference(ledger), reference(dispatch / 'claim.json')]
    folder = child_output / 'games' / game
    cleanups = list(folder.rglob('cleanup.json'))
    historical_verified = bool(cleanups)
    for cleanup in cleanups:
        value = read(cleanup)
        historical_verified &= (value.get('locks_clear') is True
                               or value.get('status') in ('CLEAN', 'COMPLETE', 'CLEANED'))
        refs.append(reference(cleanup))
    basis = 'HISTORICAL_CLEANUP'
    if cleanup_receipt is not None:
        current = read(verify_ref(cleanup_receipt))
        checked = current.get('checked_unix')
        import math
        if (current.get('schema') != 'refine.boundary-cleanup.v1'
                or current.get('status') != 'CLEANUP_VERIFIED' or current.get('job') != job_id
                or current.get('output') != str(output)
                or not all(current.get(k) is True for k in ('process_clear', 'locks_clear', 'ownership_verified'))
                or not current.get('sources') or type(checked) not in (int, float)
                or not math.isfinite(checked) or checked < record.get('boundary_unix', record.get('unix', 0))
                or checked > time.time()):
            raise ValueError('Require current source-bound ownership/idle/lease cleanup verification')
        for ref in current['sources']:
            verify_ref(ref)
        config = read(output / 'configs' / model / (game + '.json'))
        from stage3_run_layout import candidate_location as derive_candidate_location
        _, candidate = derive_candidate_location(
            {'game_id': game, 'project': config['project_overrides'][game]}, folder, config)
        expected_candidate = candidate.resolve()
        if candidate_location is not None and Path(candidate_location).resolve() != expected_candidate:
            raise ValueError('Explicit candidate location differs from the frozen source')
        supplied_candidate = current.get('candidate_location', current.get('candidate_root'))
        if supplied_candidate != str(expected_candidate):
            raise ValueError('Cleanup receipt candidate ownership differs from the frozen source')
        # Probe again after checking the external evidence, including detached
        # native processes whose command still names this exact candidate.
        live = probe()
        if (any(c['pid'] in live for c in [*children, *record.get('descendants', [])])
                or descendants(live, parent['pid'])
                or any(str(expected_candidate) in process['cmd'] or str(folder) in process['cmd']
                       for process in live.values())):
            raise ValueError('Owned candidate process still exists at cleanup boundary')
        refs.append(cleanup_receipt)
        basis = 'CURRENT_BOUNDARY_CHECK'
    elif not historical_verified:
        raise ValueError('Missing real cleanup evidence; supply an explicit current boundary cleanup receipt')
    return write_receipt(completion_path, {'schema': 'refine.child-exit.v1', 'status': 'CHILD_EXIT_CONFIRMED',
        'job': job_id, 'boundary': reference(boundary), 'sources': refs, 'child_result': row,
        'old_matrix_row': state, 'cleanup_verified': True, 'cleanup_basis': basis,
        'historical_cleanup_missing': not cleanups, 'historical_cleanup_verified': historical_verified,
        'unix': time.time(), 'evaluation_started': False})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    prepare = commands.add_parser('prepare')
    prepare.add_argument('--output', type=Path, required=True)
    prepare.add_argument('--authorization', type=Path, required=True)
    prepare.add_argument('--boundary', type=Path, required=True)
    activate = commands.add_parser('activate')
    activate.add_argument('--prepared', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.action == 'prepare':
        print(prepare_migration(args.output, args.authorization, args.boundary))
    else:
        print(activate_migration(args.prepared))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
