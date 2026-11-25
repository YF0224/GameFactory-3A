"""Bound terminal-quota recovery before any valid complete-source judgment.

The failed request and never-invoked siblings retain all bytes and claims. A
newer verified success must prove restoration of the identical Sol CLI service.
Only explicit full-source preflight mappings are added; normal judges, native
sheets, frozen contracts and transport caps remain unchanged.
"""
from datetime import datetime
from pathlib import Path
import difflib
import hashlib
import json
from .protocol import sha
from .mechanic_v3_runner import read, stamp, exclusive_json
from . import mechanic_v3_source_delivery as sources

VERSION = 'mechanic-empty-terminal-quota-continuation.v1'
POINTER = 'engineering/empty_service_continuation.json'
ALLOWED = {'mechanic_v3_source_delivery.py', 'mechanic_v3_image_transport.py',
           'mechanic_v3_execution.py'}


def _events(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _producer_bindings(value, repair, bind):
    """Only reviewed historical producer drift; author material never rebased."""
    changed = set()
    directory = Path(__file__).resolve().parent
    for text, digest in value['bindings'].items():
        path = Path(text).resolve()
        if sha(path) == digest:
            bind(path)
            continue
        if path.parent != directory or path.name not in ALLOWED:
            raise ValueError('Unrelated first-delivery binding drift: '+str(path))
        review = repair['reviewed_producer_changes'].get(str(path))
        if not review:
            raise ValueError('Missing exact reviewed producer continuation')
        before = Path(review['before_snapshot'])
        patch = Path(review['patch'])
        if sha(before) != digest or review['before_sha256'] != digest:
            raise ValueError('Historical producer snapshot differs')
        difference = ''.join(difflib.unified_diff(before.read_text().splitlines(True),
            path.read_text().splitlines(True), fromfile=str(before), tofile=str(path)))
        if (review['after_sha256'] != sha(path) or sha(patch) != review['patch_sha256']
                or patch.read_text() != difference):
            raise ValueError('Reviewed producer patch differs')
        for item in (before, patch, path): bind(item)
        changed.add(str(path))
    if not changed or changed != set(repair['reviewed_producer_changes']):
        raise ValueError('Exact producer drift set differs from review')


def _restored_service(root, task, success, bind):
    from . import evaluation_model_profile as models
    folder = root/'model_calls'/task
    inv = read(folder/'invocation.json')
    if (models.profile_for(root) is not None or inv.get('model_requested') != models.DEFAULT
            or inv.get('exit_code') != 1 or inv.get('response_present') is not False
            or inv.get('attempt') != 1):
        raise ValueError('Original first Sol terminal invocation required')
    if any((folder/name).exists() for name in ('response.json','accepted_response.json')):
        raise ValueError('Product response cannot be superseded')
    events = _events(folder/'events.jsonl')
    terminal = [e for e in events if e.get('type') == 'turn.failed']
    message = terminal[-1].get('error',{}).get('message','') if terminal else ''
    if ('403 Forbidden' not in message or 'token quota is not enough' not in message
            or any(e.get('type') == 'turn.completed' for e in events)):
        raise ValueError('Terminal 403 quota exhaustion required')
    failure = root/'failures'/(task+'.json')
    failed = read(failure)
    ok = read(success/'invocation.json')
    accepted = read(success/'accepted_response.json')
    proof = read(success/'v3_delivery_verified.json')
    response = success/accepted['path']
    if (response.resolve().parent != success or sha(response) != accepted['sha256']
            or ok.get('exit_code') != 0 or ok.get('response_present') is not True
            or ok.get('model_requested') != inv['model_requested'] or not inv.get('cli_runtime')
            or ok.get('cli_runtime') != inv['cli_runtime']):
        raise ValueError('Verified same-model same-CLI successful service required')
    if (proof.get('valid') is not True
            or proof.get('invocation_sha256') != sha(success/'invocation.json')
            or proof.get('prompt_sha256') != sha(success/'prompt.txt')
            or datetime.fromisoformat(proof['time']) <= datetime.fromisoformat(failed['time'])
            or not any(e.get('type') == 'turn.completed' for e in _events(success/'events.jsonl'))):
        raise ValueError('Verified service success must postdate terminal failure')
    for directory in (folder, success):
        for path in directory.iterdir():
            if path.is_file(): bind(path)
    bind(failure)


def prepare(workspace, identity, success, repair_path):
    """Called under the official per-identity CLI lock, never launches a model."""
    from . import mechanic_v3_source_correction as correction
    from . import mechanic_v3_execution as execution
    from . import mechanic_v3_cli as cli
    workspace = Path(workspace).resolve(); success = Path(success).resolve()
    repair_path = Path(repair_path).resolve()
    target, root = correction.prepare(workspace, identity)
    pointer = root/POINTER
    if pointer.exists():
        receipt = read(pointer)
        if (receipt.get('version') != VERSION or receipt.get('identity') != identity
                or receipt.get('success_evidence') != str(success)
                or receipt.get('repair_path') != str(repair_path)):
            raise ValueError('Retained empty-service continuation differs')
        for text, digest in receipt['bindings'].items():
            if sha(Path(text)) != digest:
                raise ValueError('Retained empty-service continuation drift: '+text)
        return receipt
    repair = read(repair_path)
    if (repair.get('classification') != 'NON_SCORING_EMPTY_SERVICE_CONTINUATION'
            or repair.get('root') != str(root) or repair.get('identity') != identity):
        raise ValueError('Explicit same-root empty-service repair required')
    production = cli.production_source_bindings()
    if repair.get('after_source_bindings') != production:
        raise ValueError('Complete reviewed production bindings differ')
    bindings = dict(production)
    def bind(path):
        path = Path(path).resolve(); bindings[str(path)] = sha(path)
    bind(repair_path);bind(correction.pointer(workspace,identity))
    prior_preflight = root/'engineering/source_correction_complete_preflight.json'
    if prior_preflight.exists(): bind(prior_preflight)
    protocol = read(root/'input/pilot_rubric.json')
    manifest = read(root/'evidence_manifest.json')
    tasks = execution.partitions(protocol, manifest, prefix='mechanic_v3_of1_')
    if len(tasks) != 2 or tasks[0][1] != tasks[1][1]:
        raise ValueError('Only two first-delivery shards on one retained evidence set are qualified')
    first = tasks[0][0]
    calls = sorted(p.name for p in (root/'model_calls').iterdir() if p.name.startswith('mechanic_v3'))
    if calls != [first]:
        raise ValueError('Only the failed first shard may have been invoked')
    _restored_service(root, first, success, bind)
    old = []
    original_images = None
    for task, parent, _ in tasks:
        prior = sources._path(root,task); claim = read(prior)
        if (claim.get('first_delivery') is not True or claim.get('canonical_task') != task
                or claim.get('recovery_task') != task or claim.get('parent') != parent):
            raise ValueError('Unchanged original first-delivery claim required')
        if (root/'engineering/complete_source_preflight'/(task+'.json')).exists():
            raise ValueError('Existing preflight recovery must be preserved')
        _producer_bindings(claim, repair, bind); bind(prior)
        request = root/'requests'/task
        delivered = read(request/'complete_source_delivery.json')
        actual = read(request/'actual_delivery.json')
        if delivered.get('all_source_bytes_delivered') is not True:
            raise ValueError('Retained request lacks full original-source proof')
        if original_images is None: original_images = actual['images']
        if actual['images'] != original_images or actual['parent_evidence_set'] != parent:
            raise ValueError('Retained sibling native images differ')
        for path in request.rglob('*'):
            if path.is_file(): bind(path)
        old.append((task,parent,claim))
    pixels = sources._retained_sheet_bindings(root, first, tasks[0][1], bind)
    fingerprint = hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()[:12]
    routes = []
    for task, parent, claim in old:
        child = task+'_empty_service_'+fingerprint
        if (root/'model_calls'/child).exists() or sources._path(root,child).exists():
            raise ValueError('Retained service child cannot be repeated')
        mapping = root/'engineering/complete_source_preflight'/(task+'.json')
        routes.append((mapping, sources._path(root,child), dict(claim,
            recovery_task=child, bindings=dict(bindings), service_continuation=VERSION,
            prior_failed_task=first, prior_claim_preserved=True,
            retained_sheet_qualification=pixels, max_new_calls=1)))
    # Immutable mappings use the existing source resolver; no validator bypass.
    for mapping, childpath, value in routes:
        exclusive_json(mapping,value)
        final = dict(value,bindings={**value['bindings'],str(mapping.resolve()):sha(mapping)})
        exclusive_json(childpath,final)
        bind(mapping);bind(childpath)
    receipt = dict(version=VERSION,time=stamp(),identity=identity,root=str(root),
        correction_workspace=str(target),success_evidence=str(success),repair_path=str(repair_path),
        failed_task=first,never_invoked_siblings=[tasks[1][0]],max_new_calls=2,
        failed_shard_retry_budget=1,never_invoked_sibling_initial_calls=1,
        task_mapping={read(p)['canonical_task']:read(p)['recovery_task'] for p,_,_ in routes},
        original_claims_and_failure_preserved=True,scoring_semantics_unchanged=True,
        all_original_sources_and_native_frames_preserved=True,bindings=bindings)
    exclusive_json(pointer,receipt)
    return receipt


def continuation_preflight(root, current, prior_path):
    """Store changed task names separately after full original packet validation."""
    root = Path(root).resolve(); prior_path = Path(prior_path).resolve()
    receipt = read(root/POINTER)
    if receipt.get('version') != VERSION or receipt.get('root') != str(root):
        raise ValueError('Explicit empty-service preflight continuation required')
    for text, digest in receipt['bindings'].items():
        if sha(Path(text)) != digest:
            raise ValueError('Empty-service preflight evidence drift: '+text)
    if receipt['bindings'].get(str(prior_path)) != sha(prior_path):
        raise ValueError('Original complete preflight was not preserved')
    old = read(prior_path)
    mapping = receipt['task_mapping']
    if ([t['task'] for t in old['tasks']] != list(mapping)
            or [t['task'] for t in current['tasks']] != list(mapping.values())
            or current.get('root') != str(root) or current.get('identity') != receipt['identity']
            or current.get('complete_sources') is not True
            or current.get('complete_native_frames') is not True):
        raise ValueError('Complete preflight continuation task identity differs')
    return root/'engineering/empty_service_complete_preflight.json'
