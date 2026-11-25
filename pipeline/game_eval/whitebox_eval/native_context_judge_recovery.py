"""Bounded native judge continuation with every parent's full delivered context.

An actual exhausted multi-check timeout authorizes one deterministic partition,
not a new playthrough, missing evidence, a retry of the same request, or a score.
"""
import copy
import hashlib
import json
from pathlib import Path
import re
import shutil
import time

from . import batch, frame_budget
from .protocol import checked_path, dump, sha

VERSION = 'whitebox-native-context-preserving-judge-recovery.v1'
RECEIPT = 'native_context_judge_recovery.json'
CLAIM = 'native_context_judge_recovery_claim.json'
MAXIMUM = 4


def partition(manifest, protocol, accepted):
    """Copy all parent fields, including all pictures/rows/omissions, verbatim."""
    if manifest.get('judge_transport_partition'):
        raise ValueError('Nested context partitions are not authorized')
    tasks = frame_budget.tasks(protocol, manifest)
    names = {name for name, _, _ in tasks}
    if len(set(accepted)) != len(accepted) or set(accepted) - names:
        raise ValueError('Unknown or duplicate accepted native shard')
    result = copy.deepcopy(manifest)
    result['evidence_sets'] = {}
    result['judge_transport_partition'] = {}
    counter = max(int(name.split('_')[1]) for name in manifest['evidence_sets'])
    for name, specs, static in tasks:
        if static:
            continue
        if name in accepted:
            result['evidence_sets'][name] = copy.deepcopy(manifest['evidence_sets'][name])
            continue
        for start in range(0, len(specs), MAXIMUM):
            counter += 1
            child = f'evidence_{counter:02d}'
            subset = copy.deepcopy(manifest['evidence_sets'][name])
            subset['criterion_ids'] = [row['id'] for row in specs[start:start+MAXIMUM]]
            result['evidence_sets'][child] = subset
            result['judge_transport_partition'][child] = {
                'version': VERSION, 'parent_name': name, 'parent_specs': copy.deepcopy(specs),
                'parent_criterion_ids': copy.deepcopy(manifest['evidence_sets'][name]['criterion_ids'])}
    frame_budget.tasks(protocol, result)
    return result


def exhausted_timeout(source, name, manifest, protocol):
    if not re.fullmatch(r'evidence_\d{2,}', name):
        raise ValueError('A native runtime judge shard is required')
    task = next((task for task in frame_budget.tasks(protocol, manifest) if task[0] == name), None)
    if task is None or task[2] or len(task[1]) <= MAXIMUM:
        raise ValueError('An exhausted multi-check native task is required')
    folder = source/'model_calls'/name
    invocation = batch.read(folder/'invocation.json')
    if (invocation.get('status') != 'TIMEOUT' or invocation.get('seconds', 0) < 599
            or invocation.get('model_requested') != 'gpt-6.1-sol'
            or any((folder/item).exists() for item in ('response.json', 'accepted_response.json'))
            or (source/'judgments'/(name+'.json')).exists()):
        raise ValueError('No unaccepted full-budget native judge timeout')
    if list(folder.parent.glob(name+'_*')):
        raise ValueError('A subsequent invocation already exists; retain its original recovery budget')
    return {'classification': 'TIMEOUT', 'name': name, 'seconds': invocation['seconds'],
            'files': {str(p.relative_to(source)): sha(p) for p in folder.rglob('*') if p.is_file()}}


def _digest_packet(value):
    body, omitted = value
    return {'body_sha256': hashlib.sha256(body.encode()).hexdigest(), 'omitted': omitted}


def verify(root):
    """Reject source, capture, grouping, accepted-response and call-budget drift."""
    from . import integrity
    from .judge_format_recovery import repair_proof
    root = Path(root).resolve()
    value = batch.read(root/RECEIPT)
    source = Path(value['source_attempt']).resolve()
    if (value.get('version') != VERSION or value.get('destination') != str(root)
            or source == root or source.parent != root.parent
            or value.get('execution_allowed') is not False or value.get('new_recordings') != 0
            or value.get('maximum_recoveries') != 1 or not value.get('authorization')):
        raise ValueError('Invalid native context judge recovery identity')
    if (sha(source/CLAIM) != value['claim_sha256'] or sha(root/CLAIM) != value['claim_sha256']):
        raise ValueError('Native context judge claim changed')
    claim = batch.read(source/CLAIM)
    if (claim.get('source_attempt') != str(source) or claim.get('destination') != str(root)
            or claim.get('maximum_recoveries') != 1 or claim.get('version') != VERSION):
        raise ValueError('Native context judge claim identity changed')
    if repair_proof(value['engineering_repair']['path']) != value['engineering_repair']:
        raise ValueError('Native context judge engineering pin changed')
    if integrity.audit_bindings(source) != value['source_audit_bindings']:
        raise ValueError('Native context judge source provenance graph changed')
    for name, digest in value['source_bindings'].items():
        if sha(checked_path(source, name)) != digest:
            raise ValueError('Native context judge source changed: '+name)
    for name, digest in value['immutable_copy_bindings'].items():
        if sha(checked_path(root, name)) != digest:
            raise ValueError('Native context judge immutable copy changed: '+name)
    for name, raw in value['preserved_raw'].items():
        if batch.read(root/'judgments'/(name+'.json'))['raw'] != raw:
            raise ValueError('Native context judge accepted raw changed: '+name)
    baseline = root/'evidence_manifest.before_partition.json'
    protocol = batch.read(root/'input/pilot_rubric.json')
    original = batch.read(baseline)
    if (sha(baseline) != value['original_manifest_sha256']
            or sha(root/'evidence_manifest.json') != value['manifest_sha256']
            or batch.read(root/'evidence_manifest.json') != partition(original, protocol, value['accepted_shards'])):
        raise ValueError('Native context judge partition changed full original evidence')
    if exhausted_timeout(source, value['failure']['name'], original, protocol) != value['failure']:
        raise ValueError('Native context judge timeout qualification changed')
    calls = {p.name for p in (root/'model_calls').iterdir() if p.is_dir()}
    if calls - set(value['allowed_model_calls']):
        raise ValueError('Unauthorized native context judge model call')
    return {str(root/RECEIPT): sha(root/RECEIPT), str(source/CLAIM): sha(source/CLAIM),
            **{str(source/name): digest for name, digest in value['source_bindings'].items()}}


def validate_partition(root, protocol, manifest):
    verify(root)
    original = batch.read(Path(root)/'evidence_manifest.before_partition.json')
    if manifest != batch.read(Path(root)/'evidence_manifest.json'):
        raise ValueError('Native context judge gate must validate the bound manifest')
    if protocol != batch.read(Path(root)/'input/pilot_rubric.json'):
        raise ValueError('Native context judge frozen protocol changed')
    return original


def prepare(source, failed_name, *, engineering_repair, authorization):
    """Caller owns all seven execution/publication locks and has drained calls."""
    from . import integrity, recovery_publish, request_reuse, native_slot_recovery
    from . import static_existence, sparse_native
    from .judge_artifacts import validate_saved_shard
    from .judge_format_recovery import repair_proof
    source = Path(source).resolve()
    if (batch.plan_engine(source) not in {'godot', 'three_js'} or not authorization.strip()
            or (source/'scores.json').exists() or (source/CLAIM).exists() or (source/RECEIPT).exists()):
        raise ValueError('One authorized unscored native source is required; preserve prior claims')
    repair = repair_proof(engineering_repair)
    batch.verify_inputs(source); batch.verify_runtime_sources(source)
    protocol = batch.read(source/'input/pilot_rubric.json')
    if protocol.get('version') != 'whitebox-mechanic10-50-100.v2':
        raise ValueError('Only the frozen native v2 protocol is authorized')
    manifest = batch.read(source/'evidence_manifest.json')
    gate = batch.validate_capture_bundle(source, manifest, protocol)
    if gate.get('valid') is not True:
        raise ValueError('Native context judge requires a fully valid original capture')
    static_existence.load(source, protocol)
    failure = exhausted_timeout(source, failed_name, manifest, protocol)
    accepted = []
    preserved = {}
    for name, specs, _ in frame_budget.tasks(protocol, manifest):
        artifact = source/'judgments'/(name+'.json')
        if artifact.is_file():
            value = batch.read(artifact)
            validate_saved_shard(value, specs)
            request_reuse.audit_one(source, name, protocol, manifest)
            accepted.append(name); preserved[name] = value['raw']
    updated = partition(manifest, protocol, accepted)
    root = source.with_name(source.name+'__context_judge_partition_v1')
    if root.exists():
        raise ValueError('Native context judge destination already exists')
    sparse_native.space(source, 'native_context_judge_handoff', estimated_bytes=2*1024**3)
    # Packet generation is diagnostic and may persist exact transport proofs.
    # Freeze the source graph only after those proofs have been written.
    packets = {}
    for name, _, static in frame_budget.tasks(protocol, updated):
        parent = updated['judge_transport_partition'].get(name, {}).get('parent_name', name)
        if parent not in packets:
            packets[parent] = _digest_packet(batch.packet(source, frame_budget.for_task(manifest, parent), static))
    original_graph = integrity.audit_bindings(source)
    claim = {'version': VERSION, 'source_attempt': str(source), 'destination': str(root),
             'maximum_recoveries': 1, 'failure': failure, 'engineering_repair': repair, 'at': time.time()}
    with (source/CLAIM).open('x') as stream:
        json.dump(claim, stream, indent=2)
    recovery_publish.clone_attempt(source, root)
    archive = root/'inherited_attempt/context_judge'; archive.mkdir(parents=True)
    native_slot_recovery.archive_source_identities(root, archive)
    for name in (native_slot_recovery.RECEIPT, 'pending_publication_receipt.json',
                 'channel_transport_recovery.json', 'static_delivery_recovery.json'):
        if (root/name).exists():
            shutil.move(root/name, archive/name)
    for path in list((root/'model_calls').iterdir()):
        if path.is_dir() and path.name.startswith('evidence_') and path.name not in accepted:
            target = archive/'model_calls'/path.name; target.parent.mkdir(exist_ok=True)
            shutil.move(path, target)
    shutil.copy2(root/'evidence_manifest.json', root/'evidence_manifest.before_partition.json')
    dump(root/'evidence_manifest.json', updated)
    equivalence = {}
    for name, _, static in frame_budget.tasks(protocol, updated):
        parent = updated['judge_transport_partition'].get(name, {}).get('parent_name', name)
        actual = _digest_packet(batch.packet(root, frame_budget.for_task(updated, name), static))
        if actual != packets[parent]:
            raise ValueError('Native context judge changed the full parent packet: '+name)
        equivalence[name] = {'parent': parent, **actual, 'full_parent_context_equal': True}
    dump(root/'native_context_packet_equivalence.json', equivalence)
    allowed = [p.name for p in (root/'model_calls').iterdir() if p.is_dir()]
    new_calls = list(updated['judge_transport_partition'])
    immutable = {str(p.relative_to(root)): sha(p) for folder in ('input', 'runtime', 'delivery', 'model_calls', 'inherited_attempt')
                 for p in (root/folder).rglob('*') if p.is_file()}
    immutable.update({name: sha(root/name) for name in ('input_manifest.json', 'sol_plan.json', 'static_existence.json',
                     'trace_summary.json', 'native_context_packet_equivalence.json')})
    dump(root/RECEIPT, {'version': VERSION, 'source_attempt': str(source), 'destination': str(root),
        'authorization': authorization, 'execution_allowed': False, 'new_recordings': 0, 'maximum_recoveries': 1,
        'engineering_repair': repair, 'source_plan_sha256': sha(source/'sol_plan.json'),
        'claim_sha256': sha(source/CLAIM), 'source_audit_bindings': original_graph,
        'source_bindings': {str(p.relative_to(source)): sha(p) for p in source.rglob('*') if p.is_file()},
        'immutable_copy_bindings': immutable, 'preserved_raw': preserved, 'accepted_shards': accepted,
        'new_model_calls_allowed': new_calls, 'allowed_model_calls': allowed+new_calls,
        'original_manifest_sha256': sha(root/'evidence_manifest.before_partition.json'),
        'manifest_sha256': sha(root/'evidence_manifest.json'), 'failure': failure,
        'original_capture_gate': gate, 'maximum_questions_per_new_call': MAXIMUM})
    dump(root/'channel_transport_recovery.json', {'schema': 'whitebox-endpoint-channel-recovery.v1',
         'source_attempt': str(source), 'qualification': str(root/RECEIPT),
         'qualification_sha256': sha(root/RECEIPT), 'reused_judge_shards': accepted})
    verify(root)
    result = batch.validate_capture_bundle(root, updated, protocol)
    if result.get('valid') is not True:
        raise ValueError('Native context judge final capture gate failed: '+str(result))
    dump(root/'native_context_handoff_gate.json', result)
    return root
