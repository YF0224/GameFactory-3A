"""Continue never-invoked canonical shards after a partial raw admission.

The original raw authorization, accepted prefix and failed preflight remain
immutable. This admits no replacement invocation and changes no scoring data.
"""
from pathlib import Path
from . import mechanic_v3_runner as runner
from . import gameness_v4_raw_preflight as prior
from . import gameness_v4_raw_literal_container as codec
from . import exact_evidence_alias as alias
from .gameness_v4_raw_parent_correction import canonical_tasks
from .protocol import sha

VERSION = 'gameness-v4-raw-uninvoked-shard-continuation.v1'
AUTH = 'engineering/gameness_raw_shard_continuation.json'
ERROR = 'Invalid complete raw preflight identity'


def authorize(root, diagnosis, engineering_receipt):
    root = Path(root).resolve(); diagnosis = Path(diagnosis).resolve()
    engineering_receipt = Path(engineering_receipt).resolve()
    parent = root/prior.AUTH; original = runner.read(parent)
    from .gameness_v4_production_continuation import verified_bindings
    verified_bindings(parent, original['bindings'])
    tasks = canonical_tasks(root); names = [t['task'] for t in tasks]
    prefix = original['tasks']; pending = names[len(prefix):]
    if (original.get('version') != prior.VERSION or original.get('identity') != root.name
            or original.get('no_invocation_at_authorization') is not True
            or not prefix or not pending or names[:len(prefix)] != prefix
            or len({t['parent'] for t in tasks}) != 1):
        raise ValueError('A strict accepted canonical prefix and untouched suffix are required')
    diag = runner.read(diagnosis)
    log = Path(diag['failure_log']['path'])
    if (diag.get('exception') != ERROR or diag.get('model_called') is not False
            or diag.get('task') != pending[0] or sha(log) != diag['failure_log']['sha256']
            or ERROR not in log.read_text()):
        raise ValueError('Exact retained before-invocation shard-admission failure required')
    files = [parent, diagnosis, log, engineering_receipt, Path(original['original_body_path']),
        Path(original['template_path']), root/'input_manifest.json', root/'source_qualification.json',
        root/'evidence_manifest.json', root/'input/pilot_rubric.json', root/'gameness_source_review.json']
    for name in prefix:
        folder = root/'model_calls'/name; judgment = root/'judgments'/(name+'.json')
        accepted = runner.read(folder/'accepted_response.json'); verdict = runner.read(judgment)
        response = folder/accepted['path']; actual = root/'requests'/name/'actual_delivery.json'
        delivered = runner.read(actual)
        if (accepted['sha256'] != sha(response) or verdict['response_sha256'] != sha(response)
                or verdict['actual_delivery_sha256'] != sha(actual)
                or delivered.get('all_predeclared_frames_delivered') is not True):
            raise ValueError('Retain the complete accepted prefix before continuing')
        invocation = runner.read(folder/'invocation.json'); command = invocation.get('command', [])
        images = [str(Path(command[i+1]).resolve()) for i, arg in enumerate(command[:-1]) if arg == '--image']
        if (invocation.get('exit_code') != 0 or sha(folder/'prompt.txt') != delivered['prompt_sha256']
                or images != [str((root/i['path']).resolve()) for i in delivered['images']]
                or any(sha(root/i['path']) != i['sha256'] for i in delivered['images'] + delivered['complete_author_sources'])):
            raise ValueError('Accepted original complete native delivery changed')
        # The normal verifier refreshes this audit timestamp, never the request.
        files.extend([p for p in folder.rglob('*') if p.is_file() and p.name != 'v3_delivery_verified.json'])
        files.extend([p for p in (root/'requests'/name).rglob('*') if p.is_file()])
        files.extend([root/i['path'] for i in delivered['images'] + delivered['complete_author_sources']])
        files.append(judgment)
    for name in pending:
        if (root/'model_calls'/name).exists() or (root/'judgments'/(name+'.json')).exists():
            raise ValueError('Never replace an attempted or accepted suffix shard')
        claim = root/'engineering/gameness_inline_schema'/(name+'.json')
        if claim.exists():
            value = runner.read(claim)
            if value.get('first_delivery') is not True or value.get('task') != name:
                raise ValueError('Original first-delivery claim required')
            verified_bindings(claim, value['source_bindings']); files.append(claim)
    if not (root/'engineering/gameness_inline_schema'/(pending[0]+'.json')).is_file():
        raise ValueError('Preserve the failed sequential first-delivery claim')
    body = Path(original['original_body_path']).read_bytes().decode('utf-8')
    wire, proof = codec.encode(body, Path(original['template_path']).read_bytes().decode('utf-8'))
    if alias.digest(body) != original['original_body_sha256'] or proof != original['proof']:
        raise ValueError('Original complete body and exact raw transport must be unchanged')
    from .gameness_v3_runtime import production_bindings
    value = dict(version=VERSION, identity=root.name, tasks=tasks, pending_tasks=pending,
        accepted_prefix=prefix, parent=dict(path=str(parent), sha256=sha(parent)),
        maximum_prompt_bytes=1000000, no_suffix_invocation_at_authorization=True,
        original_claims_and_failures_preserved=True, classification='NON_SCORING_TOOL_TRANSPORT',
        original_body_sha256=alias.digest(body), body_path=original['original_body_path'],
        template_path=original['template_path'], proof=proof,
        bindings={**{str(p):sha(p) for p in files}, **production_bindings()})
    path = root/AUTH
    if path.exists():
        if runner.read(path) != value: raise ValueError('Immutable raw continuation differs')
    else: runner.exclusive_json(path, value)
    return value


def apply(root, name, body):
    root = Path(root); path = root/AUTH
    if not path.exists(): return body, None
    value = runner.read(path)
    parent = root/prior.AUTH; original = runner.read(parent)
    names = [task['task'] for task in canonical_tasks(root)]
    if (value.get('parent') != dict(path=str(parent.resolve()),sha256=sha(parent))
            or value.get('accepted_prefix') != original['tasks']
            or value.get('pending_tasks') != names[len(original['tasks']):]
            or names[:len(original['tasks'])] != original['tasks']):
        raise ValueError('Raw continuation prefix or suffix differs from immutable original admission')
    # The accepted prefix always reconstructs its original request through prior.
    if name in value['accepted_prefix']: return body, None
    if (value.get('version') != VERSION or value.get('identity') != root.name
            or value.get('maximum_prompt_bytes') != 1000000
            or value.get('no_suffix_invocation_at_authorization') is not True
            or name not in value['pending_tasks']):
        raise ValueError('Invalid complete raw shard continuation')
    for file, digest in value['bindings'].items():
        if sha(Path(file)) != digest: raise ValueError('Raw continuation binding changed: '+file)
    if value['tasks'] != canonical_tasks(root) or alias.digest(body) != value['original_body_sha256']:
        raise ValueError('Canonical task mapping or complete original body changed')
    claim = root/'engineering/gameness_inline_schema'/(name+'.json')
    inline = runner.read(claim)
    if inline.get('task') != name or inline.get('first_delivery') is not True:
        raise ValueError('Formal sequential first-delivery claim required')
    from .gameness_v4_production_continuation import verified_bindings
    verified_bindings(claim, inline['source_bindings'])
    wire, proof = codec.encode(body, Path(value['template_path']).read_bytes().decode('utf-8'))
    if proof != value['proof'] or codec.decode(wire) != body:
        raise ValueError('Raw continuation changed a complete original byte')
    proof = dict(proof, authorization_path=str(path), authorization_sha256=sha(path))
    folder = root/'requests'/name/'exact_evidence_transport'
    for filename, text in [('original_body.txt',body), ('submitted_body.txt',wire)]:
        dest = folder/filename
        if dest.exists() and dest.read_bytes() != text.encode('utf-8'):
            raise ValueError('Retained raw continuation request differs')
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes(text.encode('utf-8'))
    dest = folder/'equivalence.json'
    if dest.exists():
        if runner.read(dest) != proof: raise ValueError('Retained raw continuation proof differs')
    else: runner.exclusive_json(dest, proof)
    return wire, dict(path=str(dest.relative_to(root)), sha256=sha(dest),
        original_body_sha256=value['original_body_sha256'], exact_expansion=True)
