"""Opt-in complete runtime text delivery through ordered read-only tool outputs.

Native images remain original CLI attachments. Source, context, original line
numbers and schemas are unchanged. A model response cannot be accepted until
completed shell output proves every byte of the complete text container arrived.
"""
import hashlib
import json
from pathlib import Path
from . import mechanic_v3_runner as runner
from .protocol import sha
from .gameness_v4_contract_chunks import ordered_source_outputs

VERSION = 'gameness-v4-complete-runtime-chunks.v1'
AUTH = 'engineering/gameness_runtime_chunks.json'
CHARS = 16000
MAX_BYTES = 1000000


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def save_bytes(path, raw):
    path = Path(path)
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError('Retained runtime chunk artifact changed: '+str(path))
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as handle:
            handle.write(raw)


def payloads(body):
    if not body:
        raise ValueError('Empty runtime context cannot opt in')
    return [('RUNTIME_TEXT_CHUNK '+str(n)+' SHA256 '+digest(part)+'\n'+part
             +'\nEND_RUNTIME_TEXT_CHUNK '+str(n)+'\n')
            for n, start in enumerate(range(0, len(body), CHARS))
            for part in [body[start:start+CHARS]]]


def wire(folder, body):
    chunks = payloads(body)
    paths = [str((folder/'chunks'/('%04d.txt'%n)).resolve()) for n in range(len(chunks))]
    return ('COMPLETE RUNTIME TEXT DELIVERY: the immutable files listed below contain the entire '
        'original author source AND native textual context in original order, with original '
        'evidence IDs and physical source/log line numbers unchanged. Every byte is retained. '
        'Before judging, read EVERY chunk in this order using read-only shell cat. Read at most '
        'two adjacent chunks per command and request max_output_tokens=64000; check that output '
        'is not truncated. Every full chunk must appear in successful completed tool output. '
        'Hashes, manifests, compressed bytes, summaries and selected excerpts do not count as '
        'delivery. Do not read unrelated paths or execute source. Do not reread chunks already '
        'delivered. The chunk headers/footers are transport wrappers and are not evidence IDs. '
        'All native images are attached to THIS invocation; read them directly and retain their '
        'original image map/citations. A text chunk is never evidence of unseen image content. '
        'Apply exactly the supplied frozen criteria/schema; no scoring or coverage rule changes.\n'
        'COMPLETE_BODY_SHA256 '+digest(body)+' BYTES '+str(len(body.encode()))+'\n'
        'ORDERED_READ_ONLY_CHUNKS '+json.dumps(paths, ensure_ascii=False)+'\n')


def authorize(root, diagnosis, repair_path):
    """Only a measured, never-invoked v4 overflow can activate this transport."""
    root=Path(root).resolve(); diagnosis=Path(diagnosis).resolve(); repair_path=Path(repair_path).resolve()
    path=root/AUTH
    if path.exists():
        original=runner.read(path)
        if original['repair']!=str(repair_path):
            return continue_review(root,diagnosis,repair_path)
        return verify_authorization(root)
    m=runner.read(diagnosis/'measurement.json'); prompt=diagnosis/'prompt.txt'
    if (m.get('model_called') is not False or m['prompt_sha256']!=sha(prompt)
            or m['prompt_bytes']!=prompt.stat().st_size or m['prompt_bytes']<=MAX_BYTES
            or m['transport']['maximum_prompt_bytes']!=MAX_BYTES
            or m['image_count']>m['transport']['maximum_images']):
        raise ValueError('Preserved full-text preflight overflow required')
    if list((root/'model_calls').glob('*')) or list((root/'judgments').glob('gameness_v4_*.json')):
        raise ValueError('Runtime chunks cannot replace any attempted or accepted task')
    repair=runner.read(repair_path)
    if repair.get('classification')!='NON_SCORING_TOOL_TRANSPORT':
        raise ValueError('Documented substantive transport repair required')
    for file,h in repair['after_source_bindings'].items():
        if sha(Path(file))!=h:raise ValueError('Runtime chunk repair production drift')
    manifest=runner.read(root/'input_manifest.json')
    if manifest['entry']['id']!=root.name:raise ValueError('Runtime source identity differs')
    from . import gameness_v3_runtime as runtime, gameness_v4 as policy
    workspace=root.parent.parent
    if runtime.workspace_policy(workspace).VERSION!=policy.VERSION:
        raise ValueError('Runtime chunks are explicit original-check v4 only')
    protocol=runtime.authored_rubric.protocol_for_run(root); policy.criteria(protocol)
    files=[prompt,diagnosis/'measurement.json',repair_path,root/'input_manifest.json',
        root/'input/pilot_rubric.json',root/'source_qualification.json',root/'evidence_manifest.json',
        root/'gameness_source_review.json']
    # Existing claims remain immutable and are qualified via exact producer
    # continuations before this authorization is activated.
    from .gameness_v4_production_continuation import verified_bindings
    for claim in (root/'engineering/gameness_inline_schema').glob('*.json'):
        prior=runner.read(claim)
        if prior.get('first_delivery') is not True:
            raise ValueError('Original unattempted inline claim required')
        verified_bindings(claim,prior['source_bindings']); files.append(claim)
    value=dict(version=VERSION,identity=root.name,diagnosis=str(diagnosis),repair=str(repair_path),
        classification='NON_SCORING_TOOL_TRANSPORT',no_invocation_at_authorization=True,
        original_failure_preserved=True,maximum_prompt_bytes=MAX_BYTES,
        native_images_unchanged=True,source_context_and_physical_lines_unchanged=True,
        bindings={str(p):sha(p) for p in files},production_bindings=repair['after_source_bindings'])
    runner.exclusive_json(path,value)
    return value


def verify_authorization(root):
    root=Path(root); value=runner.read(root/AUTH)
    if (value.get('version')!=VERSION or value.get('identity')!=root.name
            or value.get('no_invocation_at_authorization') is not True
            or value.get('maximum_prompt_bytes')!=MAX_BYTES):
        raise ValueError('Invalid runtime chunk authorization')
    continuation=root/'engineering/gameness_runtime_chunks_review_continuation.json'
    if continuation.exists():
        child=runner.read(continuation)
        if child['parent']!=dict(path=str((root/AUTH).resolve()),sha256=sha(root/AUTH)):
            raise ValueError('Runtime review continuation parent changed')
        for file,h in child['bindings'].items():
            if sha(Path(file))!=h:raise ValueError('Runtime review continuation binding changed: '+file)
        old=runner.read(Path(child['original_review'])); current=runner.read(root/'gameness_source_review.json')
        equivalent_review(old,current)
        replacement=str((root/'gameness_source_review.json').resolve())
        if value['bindings'].get(replacement)!=sha(Path(child['original_review'])):
            raise ValueError('Original review bytes do not match retained authorization')
        value=dict(value,bindings={**value['bindings'],replacement:sha(root/'gameness_source_review.json')},
            production_bindings=child['production_bindings'])
    for file,h in value['bindings'].items():
        if sha(Path(file))!=h:raise ValueError('Runtime chunk source binding changed: '+file)
    return value


def apply(root, name, body):
    root=Path(root)
    if not (root/AUTH).exists():return body,None
    value=verify_authorization(root)
    if not name.startswith('gameness_v4_of1_') and not name.startswith('gameness_v4_tiered_'):
        raise ValueError('Unknown runtime chunk task')
    if not (root/'model_calls'/name).exists():
        for file,h in value['production_bindings'].items():
            if sha(Path(file))!=h:raise ValueError('Runtime chunk production changed before invocation')
    folder=root/'requests'/name/'complete_runtime_chunks'
    original=folder/'original_body.txt'; submitted=folder/'submitted_body.txt'
    save_bytes(original,body.encode()); text=wire(folder,body); save_bytes(submitted,text.encode())
    chunks=payloads(body)
    for n,chunk in enumerate(chunks):save_bytes(folder/'chunks'/('%04d.txt'%n),chunk.encode())
    files=[original,submitted]+sorted((folder/'chunks').glob('*.txt'))
    proof=dict(version=VERSION,authorization=dict(path=str(root/AUTH),sha256=sha(root/AUTH)),
        original_body_sha256=sha(original),original_body_bytes=original.stat().st_size,
        chunk_count=len(chunks),bindings={str(p):sha(p) for p in files},
        all_original_text_retained=True,actual_tool_output_required=True,native_images_unchanged=True)
    path=folder/'equivalence.json'
    if path.exists():
        if runner.read(path)!=proof:raise ValueError('Runtime chunk proof changed')
    else:runner.exclusive_json(path,proof)
    return text,dict(path=str(path.relative_to(root)),sha256=sha(path),version=VERSION)


def allow_reads(prompt):
    old='EXACT INLINE OUTPUT SCHEMA (no filesystem reads are needed or allowed; '
    if prompt.count(old)!=1:raise ValueError('Expected exact inline schema instruction')
    return prompt.replace(old,'EXACT INLINE OUTPUT SCHEMA (only the ordered runtime text chunk reads below are required and allowed; ',1)


def verify_delivery(root, name, actual=None):
    root=Path(root)
    actual=actual if actual is not None else runner.read(root/'requests'/name/'actual_delivery.json')
    reference=actual.get('runtime_text_chunks')
    if reference is None:return None
    path=root/reference['path']
    if not path.resolve().is_relative_to((root/'requests'/name).resolve()) or sha(path)!=reference['sha256']:
        raise ValueError('Runtime chunk delivery reference changed')
    proof=runner.read(path); auth=proof['authorization']
    if Path(auth['path']).resolve()!=(root/AUTH).resolve() or sha(root/AUTH)!=auth['sha256']:
        raise ValueError('Runtime chunk authorization changed')
    verify_authorization(root)
    for file,h in proof['bindings'].items():
        if sha(Path(file))!=h:raise ValueError('Runtime chunk bytes changed: '+file)
    body=(path.parent/'original_body.txt').read_bytes().decode();chunks=payloads(body)
    if ([p.read_bytes().decode() for p in sorted((path.parent/'chunks').glob('*.txt'))]!=chunks
            or (path.parent/'submitted_body.txt').read_bytes().decode()!=wire(path.parent,body)
            or digest(body)!=proof['original_body_sha256'] or len(body.encode())!=proof['original_body_bytes']):
        raise ValueError('Runtime text chunks do not reconstruct the complete original body')
    call=root/'model_calls'/name; prompt=(call/'prompt.txt').read_bytes().decode()
    if sha(call/'prompt.txt')!=actual['prompt_sha256'] or prompt.count(wire(path.parent,body))!=1:
        raise ValueError('Actual runtime chunk prompt differs')
    # A model assertion or accepted marker is insufficient: check real successful
    # completed command outputs, without ignoring missing/reordered text bytes.
    events=call/'events.jsonl'; delivered=ordered_source_outputs(events.read_text(),chunks)
    value=dict(version=VERSION,task=name,all_original_text_actually_delivered=True,
        original_body_sha256=digest(body),chunk_count=len(chunks),
        ordered_output_proof=delivered,events_sha256=sha(events),prompt_sha256=sha(call/'prompt.txt'),
        equivalence_sha256=sha(path),native_images_attached_unchanged=True)
    receipt=path.parent/'actual_text_delivery.json'
    if receipt.exists():
        if runner.read(receipt)!=value:raise ValueError('Actual runtime text delivery changed')
    else:runner.exclusive_json(receipt,value)
    return value


def equivalent_review(before, after):
    """Only a proven revalidation metadata change; every check/source stays exact."""
    fields={'production_bindings','recovery_lineage'}
    if ({k:v for k,v in before.items() if k not in fields}
            !={k:v for k,v in after.items() if k not in fields}):
        raise ValueError('Revalidated source findings differ')
    lineage=after.get('recovery_lineage',{})
    parent=Path(lineage.get('parent_path',''))
    if (not parent.is_file() or sha(parent)!=lineage.get('parent_sha256')
            or runner.read(parent)!=before
            or lineage.get('previous_production_bindings')!=before.get('production_bindings')
            or not lineage.get('accepted_response_bindings')):
        raise ValueError('Missing exact static revalidation lineage')
    for file,h in {**lineage['accepted_response_bindings'],**after['production_bindings']}.items():
        if sha(Path(file))!=h:raise ValueError('Static revalidation bytes changed')


def continue_review(root, diagnosis, repair_path):
    root=Path(root).resolve(); parent=root/AUTH; original=runner.read(parent)
    repair=runner.read(repair_path)
    if (original['diagnosis']!=str(diagnosis) or repair.get('parent_authorization')
            !=dict(path=str(parent),sha256=sha(parent))
            or repair.get('classification')!='NON_SCORING_TOOL_TRANSPORT'
            or list((root/'model_calls').glob('*'))):
        raise ValueError('Only preserved pre-invocation review handoff can continue')
    original_review=Path(repair['original_review']); current=root/'gameness_source_review.json'
    if sha(original_review)!=original['bindings'][str(current)]:
        raise ValueError('Exact original review bytes required')
    equivalent_review(runner.read(original_review),runner.read(current))
    failure=Path(repair['parent_failure']['path'])
    if sha(failure)!=repair['parent_failure']['sha256']:
        raise ValueError('Review handoff failure changed')
    error=runner.read(failure)
    if 'Runtime chunk source binding changed: '+str(current) not in error.get('error',''):
        raise ValueError('Wrong retained handoff failure')
    for file,h in original['bindings'].items():
        if file!=str(current) and sha(Path(file))!=h:raise ValueError('Unrelated handoff drift')
    for file,h in repair['after_source_bindings'].items():
        if sha(Path(file))!=h:raise ValueError('Repaired production drift')
    value=dict(parent=dict(path=str(parent),sha256=sha(parent)),original_review=str(original_review),
        original_claim_preserved=True,no_model_invocation=True,
        source_checks_and_source_binding_unchanged=True,production_bindings=repair['after_source_bindings'],
        bindings={str(p):sha(p) for p in [parent,original_review,current,repair_path,failure]})
    path=root/'engineering/gameness_runtime_chunks_review_continuation.json'
    if path.exists():
        if runner.read(path)!=value:raise ValueError('Review continuation already differs')
    else:runner.exclusive_json(path,value)
    return verify_authorization(root)
