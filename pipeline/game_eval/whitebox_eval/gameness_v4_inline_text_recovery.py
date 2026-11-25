"""Exact in-prompt child of a retained incomplete bounded text invocation.

This is a measured transport repair, not a repeated tool-reading request. Every
original context/source byte expands from readable literal definitions inside
the submitted prompt. Original frames, schema, criteria and caps are unchanged.
"""
import hashlib
from pathlib import Path
from . import mechanic_v3_runner as runner
from . import gameness_v4_literal_container as container
from .protocol import sha

VERSION = 'gameness-v4-diagnosed-inline-complete-text.v3'
AUTH = 'engineering/gameness_inline_text_recovery.json'
FAILURE = 'HARNESS_ERROR: model did not receive every complete source chunk in order'


def codec(value):
    version = value.get('literal_encoding', container.VERSION)
    if version == container.VERSION:
        return container
    from . import gameness_v4_raw_literal_container as raw
    if version == raw.VERSION:
        return raw
    raise ValueError('Unsupported complete inline literal encoding')


def _check_bindings(bindings, parent=None):
    if parent is not None:
        from . import gameness_v4_saved_inline_producers as saved
        if saved.matches(parent) and (Path(parent).parent/saved.RECEIPT).is_file():
            return saved.verified_bindings(parent, bindings)
        from . import gameness_v4_contract_service_producer as service
        if service._directory(Path(parent)).is_dir():
            return service.verified_bindings(parent, bindings)
        # The exact Godot-sidecar verifier repair has a separate immutable
        # producer lineage; existing narrow continuation receipts stay intact.
        from . import gameness_v4_sidecar_producer_continuation as sidecar
        if sidecar._directory(Path(parent)).is_dir():
            return sidecar.verified_bindings(parent, bindings)
        from .gameness_v4_inline_producer_continuation import verified_bindings
        return verified_bindings(parent, bindings)
    for file, digest in bindings.items():
        if sha(Path(file)) != digest:
            raise ValueError('Inline text recovery bound bytes changed: '+file)


def authorization(root):
    root = Path(root); path = root/AUTH
    if not path.exists():
        return None
    value = runner.read(path)
    if (value.get('version') != VERSION or value.get('identity') != root.name
            or value.get('maximum_prompt_bytes') != 1000000):
        raise ValueError('Invalid diagnosed inline text identity/cap')
    _check_bindings(value['bindings'], path)
    if (root/'model_calls'/value['parent_task']/'accepted_response.json').exists():
        raise ValueError('Accepted parent cannot be superseded')
    return value


def authorize(root, repair_path):
    from . import gameness_v4_bounded_text as bounded
    root = Path(root).resolve(); repair_path = Path(repair_path).resolve()
    repair = runner.read(repair_path)
    if repair.get('classification') != 'NON_SCORING_DIAGNOSED_INLINE_TEXT':
        raise ValueError('Measured substantive inline text repair required')
    old_path = root/bounded.AUTH; old = runner.read(old_path)
    parent = old['recovery_task']; call = root/'model_calls'/parent
    if (call/'accepted_response.json').exists():
        raise ValueError('Accepted parent cannot be superseded')
    error = runner.read(call/'validation_error.json'); response = runner.read(call/'response.json')
    if (error.get('exception') != FAILURE or error.get('response_sha256') != sha(call/'response.json')
            or not response.get('checks') or any(
                c.get(k, {}).get('status') != 'HARNESS_ERROR'
                for c in response['checks'].values() for k in ('basic_function', 'result_outcome'))):
        raise ValueError('Only a preserved incomplete-text tool failure may continue')
    bindings = {}
    changes = repair.get('producer_changes', {})
    for file, digest in old['bindings'].items():
        if sha(Path(file)) == digest:
            bindings[file] = digest
        else:
            proof = changes.get(file, {}); before = Path(proof.get('archive', ''))
            if (not before.is_file() or sha(before) != digest
                    or proof.get('before_sha256') != digest
                    or sha(Path(file)) != proof.get('after_sha256')):
                raise ValueError('Missing exact archived producer continuation: '+file)
            bindings[str(before.resolve())] = digest
    _check_bindings(repair['after_source_bindings'])
    bindings.update(repair['after_source_bindings'])
    actual_path = root/'requests'/parent/'actual_delivery.json'; actual = runner.read(actual_path)
    if (actual.get('scoring_protocol') != 'whitebox-gameness10-50-100.v4'
            or actual.get('all_predeclared_frames_delivered') is not True):
        raise ValueError('Complete unchanged native frames required')
    for item in actual['images']+actual['complete_author_sources']:
        p = root/item['path']
        if sha(p) != item['sha256']:
            raise ValueError('Original source/native bytes changed')
        bindings[str(p.resolve())] = item['sha256']
    body_path = Path(old['original_body']); body = body_path.read_bytes().decode('utf-8')
    if sha(body_path) != old['original_body_sha256']:
        raise ValueError('Complete original body changed')
    # The repair must diagnose an actually incomplete output, not just an error label.
    proof_path = root/actual['runtime_text_chunks']['path']; proof = runner.read(proof_path)
    texts = bounded.payloads(body)
    from .gameness_v4_contract_chunks import ordered_source_outputs
    try:
        ordered_source_outputs((call/'events.jsonl').read_text(), texts)
    except ValueError as failure:
        if str(failure) != FAILURE:
            raise
    else:
        raise ValueError('Fully delivered text must use its own validation recovery')
    template_path = Path(repair['template_path']).resolve()
    _, _, template_raw = container.parse(template_path.read_bytes().decode('utf-8'))
    from .exact_evidence_alias import decode
    if decode(template_raw.decode('utf-8')) != body:
        raise ValueError('Template must contain every original body byte')
    wire, equivalence = codec(repair).encode(body, template_path.read_bytes().decode('utf-8'))
    old_prompt = (call/'prompt.txt').read_bytes().decode('utf-8')
    old_wire = (proof_path.parent/'submitted_body.txt').read_bytes().decode('utf-8')
    if old_prompt.count(old_wire) != 1:
        raise ValueError('Retained submitted body boundary differs')
    estimate = len(old_prompt.replace(old_wire, wire, 1).encode('utf-8'))+4096
    if estimate > 1000000 or len(wire.encode()) >= len(body.encode()):
        raise ValueError('Measured inline repair does not fit unchanged cap')
    # Only the failed primary task and its untouched, explicitly admitted siblings.
    mappings = old['recovery_tasks']
    for canonical, prior_name in mappings.items():
        if prior_name != parent and (root/'model_calls'/prior_name).exists():
            raise ValueError('Attempted sibling requires its own diagnosis')
        if canonical != old['parent_task'] and (root/'model_calls'/canonical).exists():
            raise ValueError('Attempted original sibling cannot be replaced')
    generation = sha(repair_path)[:12]
    tasks = {canonical:canonical+'_inline_text_'+generation for canonical in mappings}
    if any((root/'model_calls'/name).exists() for name in tasks.values()):
        raise ValueError('New child must be admitted before invocation')
    files = [old_path, actual_path, proof_path, repair_path, template_path, body_path]
    files += [call/name for name in ('prompt.txt','schema.json','response.json','validation_error.json','invocation.json','events.jsonl')]
    bindings.update({str(p.resolve()):sha(p) for p in files})
    value = dict(version=VERSION, identity=root.name, parent_task=parent,
        parent_authorization=dict(path=str(old_path),sha256=sha(old_path)),
        recovery_tasks=tasks, original_body=str(body_path), original_body_sha256=sha(body_path),
        template_path=str(template_path), literal_encoding=codec(repair).VERSION, maximum_prompt_bytes=1000000,
        estimated_prompt_bytes=estimate, no_invocation_at_authorization=True,
        original_failures_claims_counts_preserved=True, native_images_unchanged=True,
        scoring_semantics_unchanged=True, equivalence=equivalence, bindings=bindings)
    path = root/AUTH
    if path.exists():
        if runner.read(path) != value:
            raise ValueError('Retained inline continuation differs')
    else:
        runner.exclusive_json(path,value)
    return value


def selected_task(root, task):
    value = authorization(root)
    if value is None:
        return None
    name, parent, specs = task
    if name not in value['recovery_tasks']:
        return task
    return value['recovery_tasks'][name], parent, specs


def apply(root, name, body):
    root = Path(root); value = authorization(root)
    if value is None or name not in value['recovery_tasks'].values():
        return None
    if hashlib.sha256(body.encode()).hexdigest() != value['original_body_sha256']:
        raise ValueError('Inline child original body differs')
    wire, equivalence = codec(value).encode(body, Path(value['template_path']).read_bytes().decode())
    folder = root/'requests'/name/'complete_inline_text_v3'
    from .gameness_v4_runtime_chunks import save_bytes
    for filename, text in [('original_body.txt',body),('submitted_body.txt',wire)]:
        save_bytes(folder/filename, text.encode())
    proof = dict(version=VERSION, authorization=dict(path=str(root/AUTH),sha256=sha(root/AUTH)),
        original_body_sha256=value['original_body_sha256'], equivalence=equivalence,
        all_original_text_in_submitted_prompt=True,
        bindings={str(p.resolve()):sha(p) for p in (folder/'original_body.txt',folder/'submitted_body.txt')})
    path = folder/'equivalence.json'
    if path.exists():
        if runner.read(path) != proof:
            raise ValueError('Retained inline text proof differs')
    else:
        runner.exclusive_json(path,proof)
    return wire, dict(version=VERSION,path=str(path.relative_to(root)),sha256=sha(path))


def verify_delivery(root, name, actual):
    root = Path(root); value = authorization(root)
    if value is None or name not in value['recovery_tasks'].values():
        raise ValueError('Missing exact inline child authorization')
    reference = actual['runtime_text_chunks']; path = root/reference['path']
    if (not path.resolve().is_relative_to((root/'requests'/name).resolve())
            or sha(path) != reference['sha256']):
        raise ValueError('Inline child proof reference changed')
    proof = runner.read(path); _check_bindings(proof['bindings'], path)
    if proof['authorization'] != dict(path=str(root/AUTH),sha256=sha(root/AUTH)):
        raise ValueError('Inline child authorization reference changed')
    body = (path.parent/'original_body.txt').read_bytes().decode()
    wire = (path.parent/'submitted_body.txt').read_bytes().decode()
    expected, equivalence = codec(value).encode(body,Path(value['template_path']).read_bytes().decode())
    if (wire != expected or proof['equivalence'] != equivalence or codec(value).decode(wire) != body
            or sha(path.parent/'original_body.txt') != value['original_body_sha256']):
        raise ValueError('Inline delivery does not reconstruct every original byte')
    call = root/'model_calls'/name; prompt = (call/'prompt.txt').read_bytes().decode()
    if sha(call/'prompt.txt') != actual['prompt_sha256'] or prompt.count(wire) != 1:
        raise ValueError('Complete inline body absent from actual submitted prompt')
    receipt = dict(version=VERSION, task=name, all_original_text_actually_delivered=True,
        original_body_sha256=value['original_body_sha256'], prompt_sha256=sha(call/'prompt.txt'),
        equivalence_sha256=sha(path), native_images_attached_unchanged=True)
    dest = path.parent/'actual_text_delivery.json'
    if dest.exists():
        if runner.read(dest) != receipt:
            raise ValueError('Retained inline actual delivery differs')
    else:
        runner.exclusive_json(dest, receipt)
    return receipt
