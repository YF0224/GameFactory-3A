"""Verify an explicit, source-bound policy migration without rewriting frozen pins."""
from pathlib import Path
import os
from .common import read, sha


def verify_migration(output, current):
    output = Path(output).resolve()
    record = read(output / 'implementation_migration.json')
    if (record['from_code_identity'] != read(output / 'code_identity.json') or
            record['to_code_identity'] != current or record['output'] != str(output) or
            record['configuration_sha256'] != sha(output / 'configuration.json') or
            record['inventory_sha256'] != sha(output / 'inventory.json')):
        raise ValueError('Implementation migration does not bind frozen run and current code')
    for ref in [record['authorization'], record['boundary'], *record['before_sources']]:
        if sha(ref['path']) != ref['sha256']:
            raise ValueError('Implementation migration provenance changed')
    boundary = read(record['boundary']['path'])
    if record.get('schema') == 'refine.implementation-migration.v2':
        _verify_matrix_binding(output, record)
        old_script = record['from_prompt_script']
        previous_prompt = read(output / 'stage3_prompt_identity.json')
        if (sha(old_script['path']) != old_script['sha256']
                or old_script['sha256'] != previous_prompt['script_sha256']):
            raise ValueError('Missing original prompt script source binding')
    else:
        if boundary['status'] not in ('READY_FOR_POLICY_MIGRATION', 'OLD_WORKER_EXITED'):
            raise ValueError('Old worker has not reached a migration boundary')
        old_pid = read(record['authorization']['path'])['worker_pid']
        try:
            os.kill(old_pid, 0)
        except ProcessLookupError:
            pass
        else:
            raise ValueError('Cannot migrate while original worker is alive')
    before = {Path(r['path']).name: r['sha256'] for r in record['before_sources']}
    if any(before.get(name) != value for name, value in record['from_code_identity'].items()):
        raise ValueError('Migration lacks original implementation sources')
    return record


RUNTIME_KEYS = {'repair_execution_policy', 'repair_candidate_root',
                'repair_budget_policy', 'provider_runtime_policy'}


def _verify_matrix_binding(output, record):
    """Check the immutable matrix receipt without importing historical snapshots."""
    ref = record['matrix_migration']
    if sha(ref['path']) != ref['sha256']:
        raise ValueError('Matrix migration changed')
    # Use the same formal verifier as matrix admission, including boundary
    # identity, PREPARED/ACTIVE linkage and every additional source receipt.
    from refine.recovery import verify_migration as verify_matrix
    matrix_output = output.parents[2]
    matrix = verify_matrix(ref['path'], matrix_output)
    job = record['job_id']
    model, game = job.split('/')
    if (model not in matrix['models'] or job not in matrix['original_jobs']
            or job in matrix.get('fresh_jobs', [])
            or output != matrix_output / 'batches' / model / game
            or record['authorization'] != matrix['authorization']
            or record['boundary'] != matrix['boundary']
            or matrix.get('evaluation_started') is not False):
        raise ValueError('Implementation migration does not bind active repair identity')
    production = {str(Path(r['path']).resolve()): r['sha256'] for r in matrix['production_sources']}
    package = Path(__file__).resolve().parent
    if any(production.get(str(package / name)) != value for name, value in record['to_code_identity'].items()):
        raise ValueError('Matrix does not bind complete current repair implementation')
    return matrix


def verify_runtime_config(output, config, current):
    """Accept only the explicit additive overlay, preserving frozen configuration."""
    output = Path(output).resolve()
    record = verify_migration(output, current)
    if record.get('schema') != 'refine.implementation-migration.v2':
        raise ValueError('Runtime additions require an explicit v2 implementation migration')
    matrix = _verify_matrix_binding(output, record)
    frozen = read(output / 'configuration.json')
    from .batch import normalize
    base = normalize(matrix['original_configs'][record['job_id']])
    # Child frozen configuration is normalized by the same generation entry.
    if frozen != base:
        raise ValueError('Frozen child and matrix configuration differ')
    from refine.recovery import runtime_config
    expected = normalize(runtime_config(matrix, record['job_id']))
    if (config != expected or record['runtime_configuration'] != config
            or any(k not in frozen and k not in RUNTIME_KEYS for k in config)
            or any(config.get(k) != value for k, value in frozen.items() if k not in RUNTIME_KEYS)):
        raise ValueError('Runtime configuration differs from approved additive migration')
    from .providers import validate_runtime_policy
    validate_runtime_policy(config['agent'], config.get('provider_runtime_policy'))
    return record
