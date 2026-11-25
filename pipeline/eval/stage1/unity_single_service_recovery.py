"""One source-bound single-case continuation after a proven provider 503."""
from pathlib import Path
import copy
import json
import math
import time

from . import batch, core12, endpoint_sparse, static_existence, unity_service_recovery as service
from .protocol import dump, sha

VERSION = 'whitebox-unity-single-source-service-recovery.v1'
RECEIPT = 'single_source_service_recovery.json'
CLAIM = 'single_source_service_recovery_claim.json'
DESTINATION = 'single_source_service_recovery_destination.json'


def qualify(source, *, protect_score=True):
    source = Path(source).resolve()
    if batch.plan_engine(source) != 'unity3d':
        raise ValueError('Only original Unity source work may continue')
    batch.verify_inputs(source)
    protocol = core12.verify_attempt(source, 'unity3d')
    static_existence.load(source, protocol)
    if any((source/name).exists() for name in (
            RECEIPT, 'service_recovery.json', 'source_score_output_partition.json',
            'sol_plan.json', 'background_record', 'static_source_scores.json', 'scores.json')):
        raise ValueError('Only unfinished original pre-plan source review may recover once')
    folder = source/'model_calls/source_code_scores'
    if any((folder/name).exists() for name in ('response.json', 'accepted_response.json', 'schema_error.json')):
        raise ValueError('A saved response must be recovered instead of called again')
    failures = service.service_failures(source)
    if len(failures) != 1 or failures[0]['stage'] != 'source_code_scores':
        raise ValueError('Actual response-free source-score provider 503 required')
    invocation = batch.read(folder/'invocation.json')
    command = invocation.get('command', [])
    budget = batch.read(folder/'budget.json').get('effective_timeout_seconds')
    from .unity_source_review import schema
    if (invocation.get('status') == 'TIMEOUT'
            or '--model' not in command
            or command[command.index('--model')+1] != static_existence.MODEL
            or type(budget) not in (int, float) or not math.isfinite(budget) or budget <= 0
            or batch.read(folder/'schema.json') != schema(protocol, grouped=True)):
        raise ValueError('Original grouped source task or failure classification changed')
    ident = batch.read(source/'input_manifest.json')['entry']['id']
    if protect_score:
        from .unity_recovery import attempts, saved_score
        from .unity_queue import published
        if saved_score(attempts(source.parents[1], ident)) or published(source.parents[1], ident):
            raise ValueError('Saved score protected')
    names = ['input_manifest.json', 'input/pilot_rubric.json', 'static_existence.json']
    names += [str(path.relative_to(source)) for path in folder.iterdir() if path.is_file()]
    return {'case_id': ident, 'classification': 'PROVIDER_503', 'failures': failures,
            'original_timeout_seconds': budget,
            'source_bindings': {name: sha(source/name) for name in sorted(names)}}


def prepare(source, *, queue, probe):
    """Caller holds the production coordinator and performs the usual preflight."""
    source = Path(source).resolve()
    qualification = qualify(source)
    health = service.verify_probe(queue, probe)
    checked = time.time()
    # An exclusive source claim prevents a renamed output from resetting retries.
    with (source/CLAIM).open('x') as stream:
        json.dump({'version': VERSION, 'source_attempt': str(source),
                   'qualification': qualification, 'maximum_service_recoveries': 1,
                   'authorized_unix': checked}, stream, indent=2)
        stream.write('\n')
    root = service.prepare_attempt(source, qualification['failures'])
    with (source/DESTINATION).open('x') as stream:
        json.dump({'version': VERSION, 'destination': str(root.resolve()),
                   'claim_sha256': sha(source/CLAIM)}, stream, indent=2)
        stream.write('\n')
    dump(root/RECEIPT, {'version': VERSION, 'source_attempt': str(source),
        'qualification': qualification, 'claim_sha256': sha(source/CLAIM),
        'destination_sha256': sha(source/DESTINATION),
        'service_recovery_sha256': sha(root/'service_recovery.json'),
        'queue': str(Path(queue).resolve()), 'probe': str(Path(probe).resolve()),
        'probe_bindings': health, 'authorized_unix': checked,
        'maximum_service_recoveries': 1, 'old_failures_claims_counters_preserved': True,
        'scoring_semantics_changed': False})
    verify(root)
    return root



def _expected_entry(source_entry, root, protocol):
    """Return source metadata plus only batch.prepare's deterministic binding.

    Older unfinished attempts can predate the shared endpoint-conditions file.
    ``batch.prepare`` then records that canonical binding in the recovery
    manifest. This is evaluator-derived metadata, not a source/rubric change;
    every other entry field remains an exact frozen comparison.
    """
    expected = copy.deepcopy(source_entry)
    if 'endpoint_conditions' not in expected:
        shared = endpoint_sparse.shared_conditions_path(root.parents[1], protocol)
        if endpoint_sparse.closed_endpoints(protocol) and shared.is_file():
            expected['endpoint_conditions'] = {
                'path': str(shared.resolve()), 'sha256': sha(shared)}
    return expected


def verify(root):
    root = Path(root).resolve()
    value = batch.read(root/RECEIPT)
    source = Path(value['source_attempt']).resolve()
    claim = batch.read(source/CLAIM)
    destination = batch.read(source/DESTINATION)
    if (value.get('version') != VERSION
            or value.get('qualification') != qualify(source, protect_score=False)
            or value.get('claim_sha256') != sha(source/CLAIM)
            or value.get('destination_sha256') != sha(source/DESTINATION)
            or value.get('service_recovery_sha256') != sha(root/'service_recovery.json')
            or destination != {'version': VERSION, 'destination': str(root),
                               'claim_sha256': value['claim_sha256']}
            or claim != {'version': VERSION, 'source_attempt': str(source),
                         'qualification': value['qualification'],
                         'maximum_service_recoveries': 1,
                         'authorized_unix': value['authorized_unix']}
            or value.get('maximum_service_recoveries') != 1
            or value.get('old_failures_claims_counters_preserved') is not True
            or value.get('scoring_semantics_changed') is not False
            or type(value.get('authorized_unix')) not in (int, float)
            or not math.isfinite(value['authorized_unix'])
            or value['authorized_unix'] > time.time()
            or service._verify_probe_at(value['queue'], value['probe'], value['authorized_unix'])
                != value['probe_bindings']):
        raise ValueError('Original provider failure or recovery authorization changed')
    entry = batch.read(root/'input_manifest.json')['entry']
    parent = batch.read(source/'input_manifest.json')['entry']
    batch.verify_inputs(root)
    protocol = core12.verify_attempt(root, 'unity3d')
    static_existence.load(root, protocol)
    lineage = batch.read(root/'service_recovery.json')
    for name, digest in lineage['copied_bindings'].items():
        relative = Path(name)
        if (relative.is_absolute() or '..' in relative.parts
                or sha(source/relative) != digest or sha(root/relative) != digest):
            raise ValueError('Accepted static recovery copy changed')
    if (entry != _expected_entry(parent, root, protocol)
            or static_existence.identity(root, protocol)
                != static_existence.identity(source, batch.read(source/'input/pilot_rubric.json'))
            or lineage.get('version') != service.VERSION
            or lineage.get('source_attempt') != str(source)
            or lineage.get('failures') != value['qualification']['failures']
            or lineage.get('maximum_service_recoveries') != 1):
        raise ValueError('Frozen source or accepted static identity changed')
    return value
