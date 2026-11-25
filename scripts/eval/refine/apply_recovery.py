"""Bounded offline preparation of the authorized 21-old/5-fresh Stage3 recovery.

Default CLI mode is read-only validation. --apply creates budget revisions,
PREPARED/ACTIVE matrix receipts and v2 implementation sidecars, never workers.
All candidates must already be quiescent under coordinator-owned leases.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

BENCH = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(BENCH / 'scripts'), str(BENCH / 'GameFactory-3A')]
from pipeline.eval.refinement.common import read, sha, resolve
from pipeline.eval.refinement.batch import normalize, code_identity
from pipeline.eval.refinement import selected as _stage3  # repair_budget not migrated
from refine import recovery


def _ref(value):
    if not isinstance(value, dict) or set(value) != {'path', 'sha256'}:
        raise ValueError('Expected an explicit path/SHA source reference')
    if not Path(value['path']).is_absolute():
        raise ValueError('Source references must use absolute paths')
    recovery.verify_ref(value)
    return value


def _timestamp(value, earliest=0):
    return (type(value) in (int, float) and math.isfinite(value)
            and earliest <= value <= time.time())


def _quiescence(ref, job, candidate, earliest):
    value = read(_ref(ref)['path'])
    if (value.get('schema') != 'refine.candidate-quiescence.v1'
            or value.get('status') != 'QUIESCENT' or value.get('job') != job
            or value.get('candidate_root') != str(candidate.resolve())
            or value.get('process_clear') is not True or value.get('lease_owned') is not True
            or not _timestamp(value.get('checked_unix'), earliest) or not value.get('sources')):
        raise ValueError('Candidate must have a current source-bound quiescence/lease receipt: ' + job)
    for source in value['sources']:
        _ref(source)
    return value


def _implementation_sidecar(output, matrix_record, active_ref, job, runtime, entry):
    """Construct a sidecar in memory, including during read-only preflight."""
    model, game = job.split('/')
    child = output / 'batches' / model / game
    frozen_path = child / 'configuration.json'
    frozen = read(frozen_path)
    if frozen != normalize(matrix_record['original_configs'][job]):
        raise ValueError('Frozen configuration differs from original matrix identity: ' + job)
    inventory = read(child / 'inventory.json')
    for ref in inventory.get('sources', {}).values():
        _ref(ref)
    prior_identity = read(child / 'code_identity.json')
    before = entry.get('before_sources', [])
    before_by_name = {}
    for ref in before:
        _ref(ref)
        name = Path(ref['path']).name
        if name in before_by_name:
            raise ValueError('Ambiguous original implementation source basename: ' + name)
        before_by_name[name] = ref['sha256']
    if not prior_identity or any(before_by_name.get(k) != v for k, v in prior_identity.items()):
        raise ValueError('Before-tree sources do not prove the old child code identity: ' + job)
    prompt_script = _ref(entry.get('from_prompt_script'))
    if read(child / 'stage3_prompt_identity.json').get('script_sha256') != prompt_script['sha256']:
        raise ValueError('Original prompt script pin is not proven: ' + job)
    return child / 'implementation_migration.json', {
        'schema': 'refine.implementation-migration.v2', 'output': str(child),
        'from_code_identity': prior_identity, 'to_code_identity': code_identity(),
        'configuration_sha256': sha(frozen_path), 'inventory_sha256': sha(child / 'inventory.json'),
        'authorization': matrix_record['authorization'], 'boundary': matrix_record['boundary'],
        'before_sources': before, 'from_prompt_script': prompt_script,
        'matrix_migration': active_ref, 'job_id': job, 'runtime_configuration': normalize(runtime),
    }


def _budget_preflight(folder, config, entry, authorization):
    """Mirror revision prerequisites without creating its checkpoint or journal."""
    from pipeline.eval.refinement.rounds import validate_budget, verify_original
    from pipeline.eval.refinement.session import inventory
    limit = validate_budget(config)
    verify_original(folder)
    # Also validates the candidate's actual bytes and rejects unsafe symlinks.
    candidate_files = inventory(folder / 'workspace/project')
    roots = budget._roots(folder)
    parent = Path(entry['parent_failure']).resolve()
    if not roots or parent != roots[-1].resolve():
        raise ValueError('Recovery parent must be the latest physical failure: ' + str(folder))
    if _ref(entry['parent_failure_ref']) != recovery.reference(parent / 'claim.json'):
        raise ValueError('Parent failure ref/path mismatch')
    history = [budget.diagnose(root) for root in roots]
    previous = None
    for root in roots:
        if read(root / 'claim.json').get('previous_manifest_sha256') != previous:
            raise ValueError('Historical claim source lineage changed')
        manifest = root / 'repaired_project.json'
        if manifest.exists():
            previous = sha(manifest)
    if history[-1]['outcome'] in ('SUCCESS', 'UNRESOLVED'):
        raise ValueError('Recovery requires diagnosed failure, not a success/unknown claim')
    if config['repair_budget_policy'] == budget.SOL_POLICY and any(
            row['outcome'] not in budget.EXCLUDED | {'SUCCESS'} for row in history):
        raise ValueError('Sol exclusion requires explicit timeout/network/auth failure evidence')
    # Reuse the formal session validator without constructing/writing a revision.
    check = object.__new__(budget.Budget)
    check.folder, check.config = folder, config
    check.records = {row['physical_attempt']: row for row in history}
    check.started = set(check.records)
    check._sessions()
    prior = config.get('explicit_restart', {}).get('prior_counted_attempts', 0)
    if type(prior) is not int or prior < 0:
        raise ValueError('Invalid prior cumulative budget')
    used = prior + (sum(row['outcome'] == 'SUCCESS' for row in history)
                    if config['repair_budget_policy'] == budget.SOL_POLICY else len(history))
    if used >= limit:
        raise ValueError('No remaining authorized repair budget')
    directory = folder / budget.DIRECTORY
    if directory.exists():
        if not (directory / 'revision.json').is_file():
            raise ValueError('Incomplete budget migration exists; preserve and inspect it')
        existing = budget.Budget(folder, config)
        if (existing.revision['authorization'] != authorization
                or existing.revision['parent_failure'] != entry['parent_failure_ref']):
            raise ValueError('Existing budget recovery identity cannot be replaced')
        budget.verify_recovery(folder, config)
    return candidate_files, history


def validate_plan(plan_path, *, probe=None):
    """Read-only preflight. probe injection is only needed by offline fixtures."""
    probe = recovery.process_table if probe is None else probe
    plan_path = Path(plan_path).resolve()
    plan = read(plan_path)
    if plan.get('schema') != 'refine.apply-recovery-plan.v1':
        raise ValueError('Unsupported recovery plan schema')
    output = Path(plan['output']).resolve()
    authorization, boundary, qualification = (_ref(plan[key]) for key in
                                             ('authorization', 'boundary', 'qualification'))
    qualified = recovery.verify_qualification(qualification)
    if (qualified.get('schema') != 'refine.native-parallel-qualification.v1'
            or qualified.get('simultaneous_native_processes') is not True
            or qualified.get('cleanup_independent') is not True
            or qualified.get('evaluation_started') is not False
            or not _timestamp(qualified.get('completed_unix'))):
        raise ValueError('Require completed native parallel qualification, not a mock acceptance')
    boundary_value = recovery.validate_boundary(boundary['path'], output, require_exit=True, probe=probe)
    if boundary_value.get('status') != 'OLD_SCHEDULER_EXIT_CONFIRMED':
        raise ValueError('Coordinator must confirm old scheduler exit before apply preparation')
    earliest = max(boundary_value.get('boundary_unix', boundary_value.get('unix', 0)),
                   qualified['completed_unix'])
    identity_path = output / 'matrix_identity.json'
    identity = read(identity_path)
    auth = read(authorization['path'])
    from refine.matrix import make_jobs, load_manifest, verify_inputs
    manifest, base, _, root = load_manifest(Path(identity['source']))
    if (manifest != identity['manifest'] or identity['base_config'] !=
            {**base, 'authorized_new_experiment': authorization}
            or auth.get('schema') != 'refine.authorized-new-experiment.v1'
            or auth.get('output') != str(output) or auth.get('user_authorized_fresh_budget') is not True
            or not auth.get('user_request') or auth.get('manifest_sha256') != sha(identity['source'])):
        raise ValueError('Plan does not bind the original frozen matrix authorization/configuration')
    verify_inputs(base)
    original_jobs = set(auth['prior_jobs'])
    original_models = sorted({job.split('/')[0] for job in original_jobs})
    expected_jobs = {m + '/' + g for m in original_models for g in manifest['games']}
    models = plan.get('models', ['sol', 'glm'])
    if (set(models) != {'sol', 'glm'} or len(models) != 2
            or set(original_models) != {'sol', 'astra', 'glm'}
            or set(original_models) - set(manifest['models'])
            or len(manifest['games']) != 13 or len(original_jobs) != 39 or original_jobs != expected_jobs):
        raise ValueError('Recovery must retain all 39 identities and activate only Sol/GLM')
    for row in auth['prior_jobs'].values():
        for ref in row.get('sources', []):
            _ref(ref)
    active_jobs = {job for job in original_jobs if job.split('/')[0] in models}
    fresh = {job for job in active_jobs if recovery._fresh_job(output, *job.split('/'))}
    configs = {}
    for job in make_jobs(manifest, identity['base_config'], output, original_models):
        path = job['config_path']
        if path.exists() or path.is_symlink():
            if not path.is_file() or read(path) != job['config']:
                raise ValueError('Original per-job configuration changed: ' + job['id'])
        elif job['id'] not in fresh:
            raise ValueError('Original per-job configuration missing for non-fresh identity: ' + job['id'])
        # Proven fresh jobs may never have had a matrix config dispatched.
        # Derive their config from the frozen identity without creating a file.
        configs[job['id']] = job['config']
    old_jobs = active_jobs - fresh
    entries = plan.get('jobs', {})
    if (set(entries) != old_jobs or len(old_jobs) != 21 or len(fresh) != 5
            or any(not job.startswith('glm/') for job in fresh)):
        raise ValueError('Plan must bind exactly 21 old attempted jobs and 5 fresh GLM identities')
    overrides = plan.get('runtime_overrides', {})
    if (set(overrides) - set(models) or any(set(v) - {'provider_runtime_policy'} for v in overrides.values())):
        raise ValueError('Only explicit provider runtime settings may supplement frozen config')
    from pipeline.eval.refinement.providers import validate_runtime_policy
    probes = plan.get('provider_probes', {})
    if set(probes) != set(models):
        raise ValueError('Both active lanes require source-bound successful provider probes')
    for lane, ref in probes.items():
        agent = configs[next(j for j in configs if j.startswith(lane + '/'))]['agent']
        policy = overrides.get(lane, {}).get('provider_runtime_policy')
        validate_runtime_policy(agent, policy)
        recovery.verify_provider_probe(_ref(ref), lane, agent, policy)
    record = {
        'output': str(output), 'original_jobs': sorted(original_jobs), 'models': models,
        'authorization': authorization, 'boundary': boundary, 'original_configs': configs,
        'execution_policy': {'version': 'refine-project-execution.v1', 'input': 'native_client', 'capture': 'native_viewport'},
        'budget_policies': {'sol': budget.SOL_POLICY, 'glm': budget.PHYSICAL_POLICY},
        'runtime_overrides': overrides, 'fresh_jobs': sorted(fresh),
    }
    candidate_roots = {job: Path(recovery.runtime_config(record, job)['repair_candidate_root']).resolve()
                       for job in active_jobs}
    qualified_roots = qualified.get('candidate_roots', [])
    if (len(qualified_roots) != 2 or len(set(qualified_roots)) != 2
            or any(sum(str(root) in qualified_roots for job, root in candidate_roots.items()
                       if job.startswith(lane + '/')) != 1 for lane in models)):
        raise ValueError('Native qualification must bind one actual candidate in each active lane')
    live = probe()
    for process in live.values():
        if any(str(root) in process['cmd'] for root in candidate_roots.values()) or str(output) in process['cmd']:
            raise ValueError('Owned candidate/dispatcher process still exists')
    validated = {}
    for job in sorted(old_jobs):
        entry = entries[job]
        model, game = job.split('/')
        folder = output / 'batches' / model / game / 'games' / game
        runtime = normalize(recovery.runtime_config(record, job))
        quiescence = _quiescence(entry.get('quiescence'), job, candidate_roots[job], earliest)
        sources = [_ref(ref)['path'] for ref in entry.get('budget_sources', [])]
        if not sources:
            raise ValueError('Budget revision requires nonempty source refs: ' + job)
        path, sidecar = _implementation_sidecar(output, record, None, job, runtime, entry)
        if path.exists() or path.is_symlink():
            raise FileExistsError('Never replace an implementation migration: ' + str(path))
        candidate_files, history = _budget_preflight(folder, runtime, entry, authorization)
        validated[job] = {'folder': folder, 'config': runtime, 'parent_failure': Path(entry['parent_failure']).resolve(),
                          'budget_sources': sources, 'sidecar_path': path, 'entry': entry,
                          'sidecar': sidecar, 'candidate_files': candidate_files, 'history': history,
                          'quiescence': quiescence}
    recoveries = plan.get('job_recoveries', {})
    if set(recoveries) - old_jobs:
        raise ValueError('Recovery mapping contains a non-attempted identity')
    for ref in recoveries.values():
        _ref(ref)
    # Keep a complete read-set for a final check before any writes.
    refs = [recovery.reference(plan_path), authorization, boundary, qualification,
            *probes.values(), *recoveries.values(),
            *[recovery.reference(p) for p in recovery.frozen_sources(output)],
            *[recovery.reference(p) for p in recovery.production_sources()]]
    for value in [qualified, *[read(ref['path']) for ref in probes.values()],
                  *auth['prior_jobs'].values(), *[read(ref['path']) for ref in recoveries.values()]]:
        refs.extend(_ref(ref) for ref in value.get('sources', []))
    for job, validated_job in validated.items():
        entry = validated_job['entry']
        refs.extend([entry['quiescence'], entry['from_prompt_script'], entry['parent_failure_ref'],
                     *entry['before_sources'], *entry['budget_sources'], *validated_job['quiescence']['sources']])
        refs.append(recovery.reference(validated_job['folder'] / 'original_project.json'))
        for row in validated_job['history']:
            refs.extend(row['sources'])
    refs.extend(base['frozen_collect_sources'].values())
    for key in ('motion_sources', 'case_inputs'):
        refs.extend(base.get(key, {}).values())
    paths = [Path(identity['source']), resolve(root, manifest['base_config']),
             resolve(root, manifest['source_inventory'])]
    paths.extend((output / 'dispatches').rglob('*.json'))
    if (output / 'matrix_status.json').exists():
        paths.append(output / 'matrix_status.json')
    refs.extend(recovery.reference(p) for p in paths)
    return {'plan': plan, 'plan_path': plan_path, 'output': output, 'authorization': authorization,
            'boundary': boundary, 'qualification': qualification, 'models': models,
            'fresh_jobs': sorted(fresh), 'jobs': validated, 'read_set': refs}


def apply_plan(plan_path, *, probe=None):
    """Explicit offline mutation only; all 21 jobs preflight before the first write."""
    probe = recovery.process_table if probe is None else probe
    ready = validate_plan(plan_path, probe=probe)
    output, plan = ready['output'], ready['plan']
    # Re-read references/candidate bytes after preflight and immediately before mutation.
    from pipeline.eval.refinement.session import inventory
    for ref in ready['read_set']:
        _ref(ref)
    for entry in ready['jobs'].values():
        if inventory(entry['folder'] / 'workspace/project') != entry['candidate_files']:
            raise ValueError('Candidate changed during recovery preflight')
    # New claims, physical roots, or sidecars appearing during preflight cannot
    # be hidden by the previously captured read-set. Revalidate before mutation.
    validate_plan(plan_path, probe=probe)
    recovery.validate_boundary(ready['boundary']['path'], output, require_exit=True, probe=probe)
    for job, entry in ready['jobs'].items():
        sources = [*entry['budget_sources'], str(ready['plan_path']), ready['qualification']['path'],
                   ready['boundary']['path'], plan['provider_probes'][job.split('/')[0]]['path'],
                   entry['entry']['quiescence']['path']]
        budget.create_revision(entry['folder'], entry['config'], authorization=ready['authorization']['path'],
                               sources=sources, parent_failure=entry['parent_failure'])
        budget.verify_recovery(entry['folder'], entry['config'])
    prepared = recovery.prepare_migration(output, ready['authorization']['path'], ready['boundary']['path'],
        models=ready['models'], runtime_overrides=plan.get('runtime_overrides', {}),
        provider_probes=plan['provider_probes'], qualifications=[ready['qualification']],
        job_recoveries=plan.get('job_recoveries', {}), probe=probe)
    active = recovery.activate_migration(prepared, probe=probe)
    active_ref = recovery.reference(active)
    record = recovery.verify_migration(active, output, probe=probe)
    sidecars = []
    for job, entry in ready['jobs'].items():
        path, sidecar = _implementation_sidecar(output, record, active_ref, job,
                                               recovery.runtime_config(record, job), entry['entry'])
        recovery.write_receipt(path, sidecar)
        sidecars.append(recovery.reference(path))
    result = {'schema': 'refine.apply-recovery-result.v1', 'status': 'ACTIVE_NO_WORKERS_STARTED',
              'plan': recovery.reference(plan_path), 'migration': active_ref,
              'old_jobs': len(ready['jobs']), 'fresh_jobs': ready['fresh_jobs'], 'sidecars': sidecars,
              'evaluation_started': False}
    recovery.write_receipt(Path(active).with_name('apply_receipt.json'), result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--apply', action='store_true', help='Write recovery receipts; default is read-only validation')
    args = parser.parse_args(argv)
    result = apply_plan(args.plan) if args.apply else validate_plan(args.plan)
    if not args.apply:
        result = {'status': 'DRY_VALIDATED_NO_WRITES', 'output': str(result['output']),
                  'old_jobs': len(result['jobs']), 'fresh_jobs': result['fresh_jobs']}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
