"""Opt-in complete evidence literal transport after a measured v4 preflight failure.

The synthetic document is a transport container, never citation evidence. Every
UTF-8 byte, original evidence identity and physical source line is reconstructed.
"""
import json
import re
from pathlib import Path
from . import exact_evidence_alias as alias
from . import shared_document_wire as shared
from . import mechanic_v3_runner as runner
from .protocol import sha

VERSION = 'gameness-v4-complete-literal-container.v1'
AUTH = 'engineering/gameness_literal_container.json'
IDENT = 'GAMENESS_COMPLETE_EVIDENCE_BODY'
NOTICE = ('COMPLETE EVIDENCE TRANSPORT CONTAINER: reconstruct its entire literal document, '
          'then expand EXACT_EVIDENCE_BODY_ALIAS using the included rules. '
          'The synthetic ID GAMENESS_COMPLETE_EVIDENCE_BODY is NOT evidence and MUST NOT be cited. '
          'Cite only original evidence IDs and original physical line numbers inside the reconstructed body. '
          'Every repeated occurrence and every character is retained. This packaging asserts no product success.\n')


def parse(packet):
    marker = '\nEVIDENCE '+IDENT+' (exact document shared text):\n'
    if not packet.startswith(shared.TABLE_MARKER) or packet.count(shared.TABLE_MARKER) != 1 or packet.count(marker) != 1:
        raise ValueError('Expected one complete evidence transport container')
    table_text, doc_text = packet[len(shared.TABLE_MARKER):].split(marker)
    table, doc = json.loads(table_text), json.loads(doc_text)
    if doc.get('evidence_id') != IDENT:
        raise ValueError('Unexpected synthetic document identity')
    raw = shared.decode(table, doc)
    if shared._render(table['dictionary'], [doc])[0] != packet:
        raise ValueError('Noncanonical complete literal container')
    return table, doc, raw


def encode(body, template_packet):
    table, _, _ = parse(template_packet)
    aliased, alias_proof = alias.encode(body)
    dictionary = table['dictionary']
    # Exact longest-first matches; unknown characters remain literal strings.
    order = sorted(range(len(dictionary)), key=lambda i: (-len(dictionary[i]), dictionary[i]))
    matcher = re.compile('|'.join(re.escape(dictionary[i]) for i in order)) if dictionary else None
    lookup = {value:i for i,value in enumerate(dictionary)}
    pieces = []; start = 0
    for match in matcher.finditer(aliased) if matcher else []:
        if match.start() > start: pieces.append(aliased[start:match.start()])
        pieces.append(lookup[match.group()]); start = match.end()
    if start < len(aliased): pieces.append(aliased[start:])
    doc = dict(evidence_id=IDENT, source_sha256=alias.digest(aliased),
               byte_count=len(aliased.encode()), physical_line_count=len(aliased.splitlines()), pieces=pieces)
    packet, _, _ = shared._render(dictionary, [doc])
    wire = NOTICE+packet
    if decode(wire) != body:
        raise ValueError('Complete evidence UTF-8 expansion differs')
    return wire, dict(version=VERSION, original_sha256=alias.digest(body), submitted_sha256=alias.digest(wire),
                     original_bytes=len(body.encode()), submitted_bytes=len(wire.encode()), alias_proof=alias_proof,
                     exact_expansion=True, physical_lines_unchanged=True, synthetic_id_is_citable=False)


def decode(wire):
    if not wire.startswith(NOTICE): raise ValueError('Missing complete-container citation rules')
    _, _, raw = parse(wire[len(NOTICE):])
    return alias.decode(raw.decode('utf-8'))


def authorize(root, tasks, diagnosis, body_path, template_path):
    root=Path(root).resolve();diagnosis=Path(diagnosis).resolve()
    body_path=Path(body_path).resolve();template_path=Path(template_path).resolve()
    prompt_path=diagnosis/'prompt.txt';measurement_path=diagnosis/'measurement.json'
    measurement=runner.read(measurement_path);prompt=prompt_path.read_bytes().decode('utf-8');body=body_path.read_bytes().decode('utf-8')
    if (measurement.get('model_called') is not False or measurement['prompt_sha256']!=sha(prompt_path)
            or measurement['prompt_bytes']!=len(prompt_path.read_bytes())
            or measurement['transport']['maximum_prompt_bytes']!=1000000
            or measurement['prompt_bytes']<=1000000):
        raise ValueError('Measured unchanged pre-invocation overflow required')
    if prompt.count(body)!=1 or not body:
        raise ValueError('Complete original body must occur exactly once in retained prompt')
    if not tasks or len(set(tasks))!=len(tasks) or any((root/'model_calls'/name).exists() for name in tasks):
        raise ValueError('Cannot replace or repeat any actual invocation')
    manifest=runner.read(root/'evidence_manifest.json')
    if manifest.get('channel_transport',{}).get('event_wire_transport'):
        raise ValueError('Complete container is incompatible with required literal EVENT wire')
    from .gameness_v4_preflight_recovery import authorization, verify_previous_binding
    for name in tasks:
        previous=authorization(root,name)
        if previous and previous.get('exact_shared_source_packets'):
            raise ValueError('Existing source transport requires explicit independent continuation')
    _, _, template_raw=parse(template_path.read_bytes().decode('utf-8'))
    if alias.decode(template_raw.decode())!=body:
        raise ValueError('Template must reconstruct the retained complete original body')
    wire,proof=encode(body,template_path.read_bytes().decode('utf-8'))
    estimate=measurement['prompt_bytes']-len(body.encode())+len(wire.encode())
    if estimate>1000000 or len(wire.encode())>=len(body.encode()):
        raise ValueError('Complete transport still exceeds unchanged cap')
    code=Path(__file__).parent.resolve()
    files=[prompt_path,measurement_path,body_path,template_path,
           root/'input_manifest.json',root/'source_qualification.json',root/'evidence_manifest.json']
    previous_path=root/'engineering/gameness_exact_preflight_recovery.json'
    if previous_path.exists(): files.append(previous_path)
    files += [code/name for name in ['gameness_v4_literal_container.py','gameness_v4_preflight_recovery.py',
              'gameness_v4_inline_schema.py','gameness_v3_runtime.py','exact_evidence_alias.py','shared_document_wire.py']]
    for name in tasks:
        claim=root/'engineering/gameness_inline_schema'/(name+'.json')
        value=runner.read(claim)
        if value.get('first_delivery') is not True or value.get('task')!=name:
            raise ValueError('Preserved original first-delivery claim required')
        for file,digest in value['source_bindings'].items():
            if sha(Path(file))!=digest and not verify_previous_binding(root,name,file,digest):
                raise ValueError('Original inline claim changed')
            files.append(Path(file))
        files.append(claim)
    value=dict(version=VERSION,tasks=tasks,no_invocation_at_authorization=True,
        classification='NON_SCORING_TOOL_TRANSPORT',root_cause='Measured full evidence exceeds fixed cap; exact complete literal sharing only',
        template_path=str(template_path),retained_body_path=str(body_path),estimated_prompt_bytes=estimate,
        bindings={str(p):sha(p) for p in files},limits_unchanged=True,all_sources_and_native_frames_preserved=True,
        synthetic_id_is_citable=False,model_recalled=False,proof=proof)
    path=root/AUTH
    if path.exists():
        if runner.read(path)!=value:raise ValueError('Existing complete transport authorization differs')
    else:runner.exclusive_json(path,value)
    return value


def apply(root,name,body):
    root=Path(root);path=root/AUTH
    if not path.exists():return body,None
    receipt=runner.read(path)
    if (receipt.get('version')!=VERSION or receipt.get('no_invocation_at_authorization') is not True):
        raise ValueError('Invalid complete transport authorization')
    if name not in receipt.get('tasks',[]):
        from .gameness_v4_empty_evidence_recovery import permits_literal_task
        if not permits_literal_task(root,name,receipt.get('tasks',[])):
            raise ValueError('Invalid complete transport authorization')
    from .gameness_v4_production_continuation import verified_bindings
    verified_bindings(path,receipt['bindings'])
    wire,proof=encode(body,Path(receipt['template_path']).read_bytes().decode('utf-8'))
    if proof['submitted_bytes']>=proof['original_bytes']:
        raise ValueError('Complete transport must reduce bytes')
    folder=root/'requests'/name/'exact_evidence_transport'
    for filename,text in [('original_body.txt',body),('submitted_body.txt',wire)]:
        p=folder/filename
        if p.exists() and p.read_bytes()!=text.encode():raise ValueError('Retained complete request body differs')
        if not p.exists():
            p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(text.encode())
    proof.update(authorization_path=str(path),authorization_sha256=sha(path))
    p=folder/'equivalence.json'
    if p.exists():
        if runner.read(p)!=proof:raise ValueError('Retained complete request proof differs')
    else:runner.exclusive_json(p,proof)
    return wire,dict(path=str(p.relative_to(root)),sha256=sha(p),original_body_sha256=proof['original_sha256'],exact_expansion=True)
