"""One in-place static transport repair; retain native capture and all failed calls.

Only the output task is partitioned. Full parent checks remain prompt context,
all original evidence/citation/image policies remain intact, and successful
runtime responses are reused. An exclusive receipt prevents recovery chains.
"""
from pathlib import Path
import json
import time

from . import batch, core12, frame_budget, static_judge_shards, static_existence
from .protocol import dump, sha

VERSION = 'whitebox-native-static-partition-recovery.v1'
RECEIPT = 'native_static_partition_recovery.json'
ORIGINAL = 'native_static_partition_original_manifest.json'


def timeout_qualified(folder):
    folder = Path(folder)
    inv = batch.read(folder/'invocation.json')
    budget = batch.read(folder/'budget.json')
    seconds = budget.get('allocated_seconds', 0)
    if (inv.get('status') != 'TIMEOUT' or inv.get('model_requested') != static_existence.MODEL
            or budget.get('phase') != 'judge' or seconds < 599
            or inv.get('seconds', 0) < seconds - 2
            or any((folder/n).exists() for n in ('response.json', 'accepted_response.json'))):
        raise ValueError('No exhausted native static timeout without response')
    return True


def transformed(protocol, original):
    if static_judge_shards.FIELD in original:
        raise ValueError('Native static parent is already partitioned')
    result = dict(original)
    result[static_judge_shards.FIELD] = static_judge_shards.partition(protocol)
    return result


def register(root, *, authorization):
    root = Path(root).resolve()
    if not isinstance(authorization, str) or not authorization.strip():
        raise ValueError('Explicit native transport repair authorization required')
    if any((root/n).exists() for n in (RECEIPT, ORIGINAL, 'scores.json', 'harness_error.json',
            'channel_transport_recovery.json', 'explicit_judge_retry_claim')):
        raise ValueError('Existing score, failure or recovery protected')
    engine = batch.plan_engine(root)
    if engine not in {'godot', 'three_js'}:
        raise ValueError('Native static recovery supports Godot/Three.js only')
    batch.verify_inputs(root)
    batch.verify_runtime_sources(root)
    protocol = core12.verify_attempt(root, engine)
    static_existence.load(root, protocol)
    manifest = batch.read(root/'evidence_manifest.json')
    updated = transformed(protocol, manifest)
    if len(updated[static_judge_shards.FIELD]['shards']) <= 1:
        raise ValueError('Static partition would not substantively repair oversized task')
    timeout_qualified(root/'model_calls/static')
    if (root/'judgments/static.json').exists():
        raise ValueError('Completed static judgment protected')
    if not batch.validate_capture_bundle(root, manifest, protocol)['valid']:
        raise ValueError('Native capture is not qualified')
    from .pending_publication import cleanup_source
    cleanup_source(root)
    from .codex import saved_model_response, decode_keyed_judgment
    from .request_reuse import audit_one
    dynamic = {}
    for name, specs, is_static in frame_budget.tasks(protocol, manifest):
        if is_static:
            continue
        audit_one(root, name, protocol, manifest)
        artifact = batch.read(root/'judgments'/f'{name}.json')
        response = batch.read(saved_model_response(root, name))
        if artifact['raw'] != decode_keyed_judgment(response, specs):
            raise ValueError('Native dynamic response differs from saved judgment')
        dynamic[name] = artifact['raw']
    # Bind preserved artifacts, including real channels/frames and every failed
    # invocation. Mutable status/validation and derived judgment rows are excluded;
    # their accepted raw checks are independently bound above.
    bindings = {str(p.relative_to(root)):sha(p) for p in root.rglob('*')
        if p.is_file() and p.relative_to(root).parts[0] not in {'validation_history', 'judgments'}
        and not any(p.is_relative_to(root/c) for c in ('runtime/project/.godot/imported',
            'runtime/project/.godot/shader_cache', 'runtime/project/node_modules'))
        and p.name != 'status.json' and p != root/'evidence_manifest.json'}
    with (root/ORIGINAL).open('x') as stream:
        stream.write((root/'evidence_manifest.json').read_text())
    receipt = {'version':VERSION, 'attempt':str(root), 'authorization':authorization,
        'original_manifest_sha256':sha(root/ORIGINAL), 'bindings':bindings,
        'preserved_dynamic_raw':dynamic,
        'new_model_calls_allowed':list(updated[static_judge_shards.FIELD]['shards']),
        'maximum_recoveries':1, 'execution_allowed':False, 'created_unix':time.time()}
    with (root/RECEIPT).open('x') as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2)
    dump(root/'evidence_manifest.json', updated)
    verify(root)
    return receipt


def verify(root):
    root = Path(root).resolve()
    value = batch.read(root/RECEIPT)
    if (value.get('version') != VERSION or value.get('attempt') != str(root)
            or value.get('maximum_recoveries') != 1 or value.get('execution_allowed') is not False
            or not value.get('authorization')):
        raise ValueError('Invalid native static recovery identity')
    if sha(root/ORIGINAL) != value['original_manifest_sha256']:
        raise ValueError('Native static original manifest changed')
    for name, digest in value['bindings'].items():
        path = (root/name).resolve()
        if not path.is_relative_to(root) or sha(path) != digest:
            raise ValueError('Native static preserved source changed: '+name)
    protocol = batch.read(root/'input/pilot_rubric.json')
    updated = transformed(protocol, batch.read(root/ORIGINAL))
    if batch.read(root/'evidence_manifest.json') != updated:
        raise ValueError('Native static recovery changed evidence beyond partition')
    if value['new_model_calls_allowed'] != list(updated[static_judge_shards.FIELD]['shards']):
        raise ValueError('Native static recovery task set changed')
    for name, raw in value['preserved_dynamic_raw'].items():
        if batch.read(root/'judgments'/f'{name}.json')['raw'] != raw:
            raise ValueError('Native static accepted dynamic checks changed')
    return {str(root/RECEIPT):sha(root/RECEIPT), str(root/ORIGINAL):sha(root/ORIGINAL),
            **{str(root/name):digest for name,digest in value['bindings'].items()}}
