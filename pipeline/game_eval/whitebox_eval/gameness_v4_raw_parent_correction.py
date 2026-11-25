"""Correct an uninvoked raw preflight diagnosed against the wrong native parent.

The first authorization remains immutable. The new envelope must bind the actual
canonical scoring tasks and their complete body, not the first capture subset.
"""
from pathlib import Path
from . import mechanic_v3_runner as runner
from . import gameness_v4_raw_preflight as prior
from . import gameness_v4_raw_literal_container as codec
from . import gameness_v4_literal_container as literal
from . import exact_evidence_alias as alias
from .protocol import sha

VERSION = 'gameness-v4-raw-parent-correction.v1'
AUTH = 'engineering/gameness_raw_parent_correction.json'


def canonical_tasks(root):
    from . import gameness_v3_rubric as rubric, gameness_v4 as policy
    root = Path(root)
    protocol = rubric.protocol_for_run(root)
    manifest = runner.read(root/'evidence_manifest.json')
    native = runner.read(root/'input/pilot_rubric.json')
    tasks = rubric.runtime_tasks(protocol, manifest, native)
    if tasks is None:
        tasks = []
        for parent, subset in manifest['evidence_sets'].items():
            specs = [s for s in policy.criteria(protocol) if s['id'] in subset['criterion_ids']]
            for start in range(0, len(specs), 5):
                tasks.append((f'gameness_v4_of1_{len(tasks)+1:02d}', parent, specs[start:start+5]))
    return [dict(task=name, parent=parent, criteria=[s['id'] for s in specs])
            for name, parent, specs in tasks]


def authorize(root, diagnosis, template_path, engineering_receipt):
    root = Path(root).resolve(); diagnosis = Path(diagnosis).resolve()
    template_path = Path(template_path).resolve(); engineering_receipt = Path(engineering_receipt).resolve()
    parent = root/prior.AUTH
    original = runner.read(parent)
    from .gameness_v4_production_continuation import verified_bindings
    verified_bindings(parent, original['bindings'])
    if (original.get('version') != prior.VERSION or original.get('identity') != root.name
            or original.get('no_invocation_at_authorization') is not True):
        raise ValueError('Exact original uninvoked raw authorization required')
    tasks = canonical_tasks(root); names = [t['task'] for t in tasks]
    measure_path = diagnosis/'measurement.json'; prompt_path = diagnosis/'prompt.txt'; body_path = diagnosis/'body.txt'
    measure = runner.read(measure_path); body = body_path.read_bytes().decode('utf-8')
    if (not tasks or names != original['tasks'] or len({t['parent'] for t in tasks}) != 1
            or measure.get('canonical_tasks') != tasks or measure.get('task') != names[0]
            or measure.get('parent') != tasks[0]['parent']):
        raise ValueError('Correction must bind the canonical native parent and all original tasks')
    if (measure.get('model_called') is not False or measure['prompt_sha256'] != sha(prompt_path)
            or measure['prompt_bytes'] != prompt_path.stat().st_size
            or measure['transport']['maximum_prompt_bytes'] != 1000000
            or measure['prompt_bytes'] <= 1000000 or not body
            or prompt_path.read_bytes().decode('utf-8').count(body) != 1
            or alias.digest(body) == original['original_body_sha256']):
        raise ValueError('Preserved corrected uninvoked overflow required')
    if (any((root/'model_calls'/name).exists() for name in names)
            or list((root/'judgments').glob('gameness_v4_*.json'))):
        raise ValueError('A parent correction cannot replace any runtime invocation')
    manifest = runner.read(root/'evidence_manifest.json')
    if (manifest.get('channel_transport', {}).get('event_wire_transport')
            or (root/literal.AUTH).exists() or (root/'engineering/gameness_runtime_chunks.json').exists()):
        raise ValueError('Competing complete-text transport requires its own recovery')
    wire, proof = codec.encode(body, template_path.read_bytes().decode('utf-8'))
    estimate = measure['prompt_bytes']-len(body.encode())+len(wire.encode())
    if estimate > 1000000 or len(wire.encode()) >= len(body.encode()):
        raise ValueError('Complete corrected transport exceeds unchanged cap')
    files = [parent, measure_path, prompt_path, body_path, template_path, engineering_receipt,
             root/'input_manifest.json', root/'source_qualification.json', root/'evidence_manifest.json',
             root/'input/pilot_rubric.json', root/'gameness_source_review.json']
    for name in names:
        claim = root/'engineering/gameness_inline_schema'/(name+'.json'); value = runner.read(claim)
        if value.get('first_delivery') is not True or value.get('task') != name:
            raise ValueError('Original untouched inline claim required')
        verified_bindings(claim, value['source_bindings']); files.append(claim)
    code = Path(__file__).resolve().parent
    files += [code/name for name in ['gameness_v4_raw_parent_correction.py',
        'gameness_v4_raw_literal_container.py', 'gameness_v4_literal_container.py',
        'gameness_v4_preflight_recovery.py', 'gameness_v3_runtime.py', 'gameness_v3_rubric.py',
        'gameness_v4.py', 'exact_evidence_alias.py', 'shared_document_wire.py']]
    value = dict(version=VERSION, identity=root.name, tasks=tasks, parent_path=str(parent),
        parent_sha256=sha(parent), no_runtime_invocation_at_authorization=True,
        classification='NON_SCORING_TOOL_TRANSPORT', original_claims_and_failures_preserved=True,
        original_body_sha256=alias.digest(body), body_path=str(body_path), template_path=str(template_path),
        estimated_prompt_bytes=estimate, maximum_prompt_bytes=1000000,
        bindings={str(p):sha(p) for p in files}, proof=proof)
    path = root/AUTH
    if path.exists():
        if runner.read(path) != value: raise ValueError('Immutable parent correction differs')
    else: runner.exclusive_json(path, value)
    return value


def apply(root, name, body):
    root = Path(root); path = root/AUTH
    if not path.exists(): return body, None
    value = runner.read(path)
    if (value.get('version') != VERSION or value.get('identity') != root.name
            or value.get('no_runtime_invocation_at_authorization') is not True
            or value.get('maximum_prompt_bytes') != 1000000
            or name not in [t['task'] for t in value['tasks']]):
        raise ValueError('Invalid exact raw parent correction')
    for file, digest in value['bindings'].items():
        if sha(Path(file)) != digest: raise ValueError('Raw parent correction binding changed: '+file)
    if (value['tasks'] != canonical_tasks(root) or sha(Path(value['parent_path'])) != value['parent_sha256']
            or alias.digest(body) != value['original_body_sha256']):
        raise ValueError('Corrected parent or complete original body changed')
    wire, proof = codec.encode(body, Path(value['template_path']).read_bytes().decode('utf-8'))
    if proof != value['proof'] or codec.decode(wire) != body:
        raise ValueError('Corrected literal body differs')
    proof = dict(proof, authorization_path=str(path), authorization_sha256=sha(path))
    folder = root/'requests'/name/'exact_evidence_transport'
    for filename, text in [('original_body.txt', body), ('submitted_body.txt', wire)]:
        dest = folder/filename
        if dest.exists() and dest.read_bytes() != text.encode(): raise ValueError('Retained corrected request differs')
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes(text.encode())
    dest = folder/'equivalence.json'
    if dest.exists():
        if runner.read(dest) != proof: raise ValueError('Retained corrected equivalence differs')
    else: runner.exclusive_json(dest, proof)
    return wire, dict(path=str(dest.relative_to(root)), sha256=sha(dest),
                     original_body_sha256=value['original_body_sha256'], exact_expansion=True)
