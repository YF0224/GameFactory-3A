"""One immutable Gameness source continuation after a proved wrong native entry.

Reuse the newly qualified original author-entry take, retaining every failed
Gameness request and the original evidence view. No judgment is transplanted.
"""
from pathlib import Path
import hashlib
import json
from . import mechanic_v3_runner as runner
from . import mechanic_v3_author_entry_recovery as author_entry
from . import mechanic_v3_author_entry_identity as continuation
from . import mechanic_v3_full_scope as scope, qualified_history
from .protocol import sha

VERSION = 'gameness-v4-author-entry-source-continuation.v1'
CLAIM = 'engineering/gameness_author_entry_source_claim.json'
PROOF = 'gameness_native_source_recovery.json'


def qualify(workspace, row, source):
    workspace, source = Path(workspace).resolve(), Path(source).resolve()
    root = workspace/'runs'/row['entry']['id']
    from .gameness_v3_runtime import publication_path
    if publication_path(workspace, root.name).exists() or (root/'gameness_score.json').exists():
        raise ValueError('Existing Gameness score must be reused, never rebound')
    if row['entry']['actual_engine'] != 'three_js':
        raise ValueError('Exact Three.js author-entry source continuation only')
    if list((root/'model_calls').glob('*/accepted_response.json')):
        raise ValueError('Never replace an accepted runtime judgment')
    old = Path(runner.read(root/'source_qualification.json')['source']).resolve()
    if old == source:
        raise ValueError('Author-entry continuation requires a different qualified source')
    author_entry.diagnosed_loader_failure(old)
    if continuation.locate(old).resolve() != source:
        raise ValueError('New native source is outside the original author-entry continuation')
    q = qualified_history.prior(source)
    if not scope.same_original(row['entry'], runner.read(source/'input_manifest.json')['entry']):
        raise ValueError('New native source is not the frozen original identity')
    failed = []
    for path in (root/'model_calls').glob('*/validation_error.json'):
        error = runner.read(path)
        response = path.parent/'response.json'
        if ('HARNESS_ERROR remains unscored engineering task' in error.get('exception', '')
                and response.is_file() and any(
                    check.get('basic_function', {}).get('status') == 'HARNESS_ERROR'
                    for check in runner.read(response).get('checks', {}).values())):
            failed.append(str(path))
    if not failed:
        raise ValueError('Preserved failed Gameness loader judgment required')
    # All immutable parent requests/responses and physical take bindings survive.
    paths = [p for p in root.rglob('*') if p.is_file()
             and not any(part in {'project', 'frames'} for part in p.relative_to(root).parts)
             and p != root/CLAIM]
    paths += [old/author_entry.CLAIM, source/'source_qualification.json']
    bindings = {str(p.resolve()): sha(p) for p in paths}
    bindings.update(q.get('source_bindings', {}))
    return dict(old_source=str(old), failed_tasks=failed, source_bindings=bindings)


def verify(workspace, row, source):
    workspace, source = Path(workspace).resolve(), Path(source).resolve()
    canonical = workspace/'runs'/row['entry']['id']
    value = runner.read(canonical/CLAIM)
    if (value.get('version') != VERSION or value.get('identity') != canonical.name
            or value.get('new_source') != str(source)):
        raise ValueError('Gameness author-entry source identity changed')
    destination = Path(value['recovery_root']).resolve()
    if (not destination.is_relative_to(workspace/'author_entry_source_recovery')
            or destination.name != canonical.name or destination.parent.name != 'runs'):
        raise ValueError('Gameness source continuation destination changed')
    for name, digest in value['source_bindings'].items():
        if sha(Path(name)) != digest:
            raise ValueError('Gameness source continuation parent changed: '+name)
    return value


def prepare(workspace, row, source, repair_path=None):
    workspace, source = Path(workspace).resolve(), Path(source).resolve()
    root = workspace/'runs'/row['entry']['id']
    claim = root/CLAIM
    if claim.exists():
        value = verify(workspace, row, source)
    else:
        if repair_path is None:
            raise ValueError('Explicit source-bound native entry repair required')
        repair_path = Path(repair_path).resolve()
        repair = runner.read(repair_path)
        if (repair.get('classification') != 'NON_SCORING_AUTHOR_ENTRY_SOURCE_CONTINUATION'
                or not repair.get('root_cause')):
            raise ValueError('Substantive author-entry source repair diagnosis required')
        required = {str(Path(__file__).resolve()), str(Path(qualified_history.__file__).resolve())}
        producers = repair.get('after_source_bindings', {})
        if not required <= producers.keys():
            raise ValueError('Native source repair lacks exact production bindings')
        for name, digest in producers.items():
            if sha(Path(name)) != digest:
                raise ValueError('Native source repair producer changed: '+name)
        value = qualify(workspace, row, source)
        bindings = value['source_bindings']
        bindings.update(producers)
        bindings[str(repair_path)] = sha(repair_path)
        for module in (Path(__file__), Path(qualified_history.__file__)):
            bindings[str(module.resolve())] = sha(module)
        fingerprint = hashlib.sha256(json.dumps(bindings, sort_keys=True).encode()).hexdigest()
        destination = workspace/'author_entry_source_recovery'/root.name/fingerprint/'runs'/root.name
        value.update(version=VERSION, identity=root.name, new_source=str(source),
            recovery_root=str(destination), original_failure_and_claims_preserved=True,
            new_recording=False, old_judgments_supplied=False, scoring_semantics_unchanged=True,
            root_cause=repair['root_cause'])
        runner.exclusive_json(claim, value)
    destination = Path(value['recovery_root'])
    result = qualified_history.prepare_view(workspace, row, source, destination=destination)
    proof = dict(version=VERSION, claim_path=str(claim), claim_sha256=sha(claim),
                 source_bindings=value['source_bindings'])
    path = result/PROOF
    if path.exists():
        if runner.read(path) != proof:
            raise ValueError('Retained Gameness native source proof changed')
    else:
        runner.exclusive_json(path, proof)
    return result


def publication_bindings(root):
    path = Path(root)/PROOF
    if not path.exists():
        return {}
    proof = runner.read(path)
    if proof.get('version') != VERSION or sha(Path(proof['claim_path'])) != proof['claim_sha256']:
        raise ValueError('Gameness native source recovery proof changed')
    value = runner.read(Path(proof['claim_path']))
    if (value['recovery_root'] != str(Path(root).resolve())
            or value['source_bindings'] != proof['source_bindings']):
        raise ValueError('Gameness native source recovery lineage changed')
    bindings = {**proof['source_bindings'], proof['claim_path']: proof['claim_sha256'], str(path): sha(path)}
    for name, digest in bindings.items():
        if sha(Path(name)) != digest:
            raise ValueError('Gameness native source recovery binding changed: '+name)
    return bindings
