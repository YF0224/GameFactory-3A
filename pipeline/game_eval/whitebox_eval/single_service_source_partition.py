"""Bounded disjoint output recovery for a fully spent single-service source call.

This is a separate qualification contract. The general full-budget source
partition gate remains unchanged. It only supports an authenticated one-time
provider continuation that reused accepted static and exhausted its original
supplemental-call cap without producing a response.
"""
from pathlib import Path
import math
import time

from . import batch, core12, static_existence, unity_single_service_recovery as service
from .protocol import dump, sha

VERSION = 'whitebox-single-service-source-output-partition.v1'
RECEIPT = 'single_service_source_partition.json'
CLAIM = 'single_service_source_partition_claim'


def qualify(source, *, protect_score=True):
    source = Path(source).resolve()
    authorization = service.verify(source)
    if any((source/n).exists() for n in ('sol_plan.json', 'background_record',
            'static_source_scores.json', 'scores.json', RECEIPT, 'source_score_output_partition.json')):
        raise ValueError('Only unfinished single-service supplemental source work may partition')
    folder = source/'model_calls/source_code_scores'
    original = Path(authorization['source_attempt'])/'model_calls/source_code_scores'
    inv, budget = batch.read(folder/'invocation.json'), batch.read(folder/'budget.json')
    seconds = authorization['qualification']['original_timeout_seconds']
    elapsed = inv.get('seconds')
    if (inv.get('status') != 'TIMEOUT' or inv.get('model_requested') != static_existence.MODEL
            or type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < seconds
            or budget.get('effective_timeout_seconds') != seconds or budget.get('attempt') != 1
            or budget.get('extension_seconds') != 0
            or any((folder/n).exists() for n in ('response.json', 'accepted_response.json', 'schema_error.json'))
            or sha(folder/'prompt.txt') != sha(original/'prompt.txt')
            or sha(folder/'schema.json') != sha(original/'schema.json')):
        raise ValueError('Exact original grouped request and exhausted inherited service budget required')
    protocol = core12.verify_attempt(source, 'unity3d')
    from .unity_source_review import schema
    if batch.read(folder/'schema.json') != schema(protocol, grouped=True):
        raise ValueError('Frozen grouped-column schema changed')
    entry = batch.read(source/'input_manifest.json')['entry']
    phase_cap = entry.get('stage_timeouts', {}).get('static')
    if type(phase_cap) not in (int, float) or not math.isfinite(phase_cap) or not 0 < seconds <= phase_cap:
        raise ValueError('Frozen static-phase cap required')
    if protect_score:
        from .unity_recovery import attempts, saved_score
        from .unity_queue import published
        if saved_score(attempts(source.parents[1], entry['id'])) or published(source.parents[1], entry['id']):
            raise ValueError('Saved score protected')
    names = ['input_manifest.json', 'input/pilot_rubric.json', 'static_existence.json',
             service.RECEIPT, 'service_recovery.json']
    names += [str(p.relative_to(source)) for p in folder.iterdir() if p.is_file()]
    return {'case_id': entry['id'], 'classification': 'FULL_INHERITED_SERVICE_CALL_TIMEOUT',
            'call_timeout_seconds': seconds, 'phase_timeout_seconds': phase_cap,
            'bindings': {n: sha(source/n) for n in sorted(names)}}


def prepare(source):
    from . import source_score_output_recovery as columns
    source = Path(source).resolve()
    qualification = qualify(source)
    claim = source/CLAIM
    claim.mkdir(exist_ok=False)
    root = source.parent/(qualification['case_id']+'__service_source_partition_v1_'+str(time.time_ns()))
    dump(claim/'claim.json', {'version': VERSION, 'source_attempt': str(source), 'attempt': str(root),
        'qualification': qualification, 'maximum_output_partitions': 1, 'created_unix': time.time()})
    entry = batch.read(source/'input_manifest.json')['entry']
    batch.prepare(source.parents[1], entry, root, previous_attempt=source)
    if static_existence.identity(root, batch.read(root/'input/pilot_rubric.json')) != static_existence.identity(source, batch.read(source/'input/pilot_rubric.json')):
        raise ValueError('Source partition changed accepted static identity')
    columns._finish_preparation(source, root, qualification['bindings'], claim)
    dump(root/RECEIPT, {'version': VERSION, 'source_attempt': str(source), 'partition_attempt': str(root),
        'qualification': qualification, 'claim': str(claim/'claim.json'), 'claim_sha256': sha(claim/'claim.json'),
        'maximum_output_partitions': 1, 'old_failure_and_budget_preserved': True,
        'scoring_semantics_changed': False})
    verify(root, batch.read(root/columns.RECEIPT))
    return root


def verify(root, partition):
    from . import source_score_output_recovery as columns
    root = Path(root).resolve()
    value = batch.read(root/RECEIPT)
    source = Path(value['source_attempt']).resolve()
    qualification = qualify(source, protect_score=False)
    claim_path = source/CLAIM/'claim.json'
    claim = batch.read(claim_path)
    if (value.get('version') != VERSION or value.get('partition_attempt') != str(root)
            or value.get('qualification') != qualification
            or value.get('claim') != str(claim_path) or value.get('claim_sha256') != sha(claim_path)
            or value.get('maximum_output_partitions') != 1
            or value.get('old_failure_and_budget_preserved') is not True
            or value.get('scoring_semantics_changed') is not False
            or claim.get('version') != VERSION or claim.get('source_attempt') != str(source)
            or claim.get('attempt') != str(root) or claim.get('qualification') != qualification
            or claim.get('maximum_output_partitions') != 1
            or partition.get('version') != columns.VERSION
            or partition.get('source_attempt') != str(source)
            or partition.get('source_bindings') != qualification['bindings']
            or partition.get('claim') != str(claim_path) or partition.get('claim_sha256') != sha(claim_path)
            or partition.get('mechanic_calls_added') != 0
            or partition.get('old_failure_and_budget_preserved') is not True):
        raise ValueError('Single-service output-partition lineage changed')
    batch.verify_inputs(root)
    protocol = core12.verify_attempt(root, 'unity3d')
    if (batch.read(root/'input_manifest.json')['entry'] != batch.read(source/'input_manifest.json')['entry']
            or static_existence.identity(root, protocol) != static_existence.identity(source, batch.read(source/'input/pilot_rubric.json'))):
        raise ValueError('Frozen partition source identity changed')
    expected = {n: sha(source/n) for n in columns._static_files(source)}
    if partition.get('copied_static_sha256') != expected or any(sha(root/n) != h for n,h in expected.items()):
        raise ValueError('Accepted static partition copy changed')
    static_existence.load(root, protocol)
    cap = qualification['call_timeout_seconds']
    for folder in (root/'model_calls').glob('source_column_*'):
        if (folder/'budget.json').is_file():
            budget = batch.read(folder/'budget.json')
            seconds = budget.get('effective_timeout_seconds')
            if (type(seconds) not in (int, float) or not math.isfinite(seconds)
                    or not 0 < seconds <= cap or budget.get('extension_seconds') != 0
                    or budget.get('attempt') != 1):
                raise ValueError('Partition invocation exceeded inherited supplemental cap')
    if partition.get('complete') and not 0 < partition.get('phase_timeout_seconds', 0) <= qualification['phase_timeout_seconds']:
        raise ValueError('Partition phase exceeded frozen static cap')
    return source


def call_cap(root, phase_timeout):
    from . import source_score_output_recovery as columns
    root = Path(root)
    verify(root, batch.read(root/columns.RECEIPT))
    value = batch.read(root/RECEIPT)['qualification']
    if phase_timeout > value['phase_timeout_seconds']:
        raise ValueError('Output partition cannot increase frozen static-phase budget')
    return value['call_timeout_seconds']
