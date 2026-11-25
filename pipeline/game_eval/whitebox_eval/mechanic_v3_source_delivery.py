"""Explicit source-completeness recovery; preserve runtime context and old calls.

Only a demonstrated truncated source channel can supersede a retained request.
All source bytes, physical lines and original frame files reach a fresh judge;
no score, contract, image limit or prompt-size limit is changed.
"""
from pathlib import Path
import hashlib
import json
import re
from .protocol import sha, dump
from .mechanic_v3_runner import read, stamp, exclusive_json

VERSION = 'mechanic-complete-source-delivery.v1'
NOTE = ('\nCOMPLETE SOURCE TRANSPORT: Every SRC is delivered in full. Exact document '
        'grammar is a reversible representation of original UTF-8 bytes and physical '
        'line numbers; cite the original SRC ID and physical lines. It proves source '
        'existence only, never runtime success. All runtime channels and native frames '
        'are unchanged. Do not inspect other files.\n')


def _path(root, name):
    return Path(root)/'engineering/complete_source_delivery'/(name+'.json')


def verify(value):
    if value.get('version') != VERSION:
        raise ValueError('Unknown complete-source recovery')
    for path, digest in value['bindings'].items():
        if sha(Path(path)) != digest:
            raise ValueError('Complete-source recovery binding changed: '+path)


def selected_task(root, task):
    """Follow preserved preflight generations; validate the final current binding.

    Earlier code SHAs can differ only when the final explicit repair binds their
    immutable receipts and before snapshots. Historical mappings remain read-only.
    """
    name, parent, specs = task
    seen = set(); chain = []
    while True:
        if name in seen:
            raise ValueError('Cyclic complete-source task recovery')
        seen.add(name)
        mapping = Path(root)/'engineering/complete_source_preflight'/(name+'.json')
        path = mapping if mapping.exists() else _path(root, name)
        if not path.exists():
            if not chain:
                return task
            raise ValueError('Complete-source recovery claim missing')
        value = read(path)
        if (value.get('parent') != parent or
                (value.get('canonical_task') != name and
                 (mapping.exists() or value.get('recovery_task') != name))):
            raise ValueError('Complete-source task identity changed')
        chain.append((path, value))
        selected = value['recovery_task']
        if selected == name:
            if mapping.exists():
                raise ValueError('Cyclic complete-source task recovery')
            break
        name = selected
    verify(value)
    for path, previous in chain:
        if previous != value and value['bindings'].get(str(path.resolve())) != sha(path):
            raise ValueError('Complete-source retained lineage binding changed: '+str(path))
    return name, parent, specs


def authorization(root, name):
    p = _path(root, name)
    if not p.exists():return None
    value = read(p);verify(value)
    if value['recovery_task'] != name:
        raise ValueError('Source delivery requires recovery request identity')
    return value


def _section_end(body, offset):
    """Keep the original separator and unprefixed runtime footer outside SRC.

    Source physical lines are numbered, so these exact unprefixed metadata
    headings cannot be confused with author source containing the same words.
    """
    from .state_packet import DESCRIPTION
    tail=body[offset:];ends=[]
    following=re.search(r'\nEVIDENCE [^\n]+\n',tail)
    if following:ends.append(offset+following.start())
    for heading in (DESCRIPTION,
            'EVENT OBSERVATION PROTOCOL CONTEXT (metadata, not a gameplay evidence ID):',
            'STATE CITATION WHITELIST (original raw line numbers, exhaustive):'):
        position=tail.find('\n'+heading+'\n')
        if position>=0:ends.append(offset+position+1)
    return min(ends) if ends else len(body)


def _section(body, ident):
    marker = '\nEVIDENCE '+ident+'\n'
    if body.count(marker) != 1:
        raise ValueError('Source section absent or duplicated: '+ident)
    start=body.index(marker)
    end=_section_end(body,start+len(marker))
    return start,end,body[start:end]


def complete(root, manifest, name, body, omitted):
    value=authorization(root,name)
    if value is None:return body,omitted
    from . import document_wire
    original=body;ids=set();sources=[]
    for entry in manifest['items']:
        if entry['type']!='source':continue
        ident=entry['id'];path=Path(root)/entry['path']
        if ident in ids or sha(path)!=entry['sha256']:
            raise ValueError('Source identity or frozen bytes changed')
        ids.add(ident)
        start,end,old=_section(body,ident)
        full='\nEVIDENCE '+ident+'\n'+''.join(
            f'{n}: {line}\n' for n,line in enumerate(path.read_text(errors='strict').splitlines(),1))+'\n'
        gap=any(row['id']==ident for row in omitted)
        if not gap and old != full:
            raise ValueError('Unaccounted source channel omission: '+ident)
        text=full
        if gap:
            encoded=document_wire.section(path,ident)
            if len(encoded.encode()) < len(full.encode()):text=encoded+'\n'
        if text!=full and not document_wire.verify_section(text,path,ident):
            raise ValueError('Source wire does not reproduce original bytes')
        body=body[:start]+text+body[end:]
        if text!=full:document_wire.persist(root,entry,text)
        sources.append(dict(id=ident,path=entry['path'],sha256=sha(path),
            physical_lines=len(path.read_text().splitlines()),source_bytes=path.stat().st_size,
            delivered_section_sha256=hashlib.sha256(text.encode()).hexdigest(),
            representation='exact_document_wire' if text!=full else 'exact_physical_lines',
            recovered_omission=gap))
    # Erasing SRC sections must reproduce all non-source context byte-for-byte.
    def without_sources(text):
        for ident in ids:
            # Wire and plain headers differ; match either exact section header.
            marker=re.search(r'\nEVIDENCE '+re.escape(ident)+r'(?: \(exact document physical lines\):)?\n',text)
            if marker is None:raise ValueError('Missing delivered source')
            end=_section_end(text,marker.end())
            text=text[:marker.start()]+text[end:]
        return text
    if without_sources(original)!=without_sources(body):
        raise ValueError('Non-source parent context changed')
    remaining=[row for row in omitted if row['id'] not in ids]
    proof=dict(version=VERSION,all_source_bytes_delivered=True,source_count=len(sources),
        sources=sources,prior_source_omissions=[row for row in omitted if row['id'] in ids],
        remaining_non_source_omissions=remaining,non_source_context_byte_identical=True,
        original_body_sha256=hashlib.sha256(original.encode()).hexdigest(),
        delivered_body_sha256=hashlib.sha256(body.encode()).hexdigest(),
        prior_invocation=value['prior_invocation'],authorization_sha256=sha(_path(root,name)))
    dump(Path(root)/'requests'/name/'complete_source_delivery.json',proof)
    return body,remaining


def request_note(root,name):
    return NOTE if authorization(root,name) is not None else ''


def _retained_sheet_bindings(root, prior, parent, bind):
    """Qualify the complete retained sheet pixels without inventing old admission.

    This branch is only called after an independently demonstrated source gap.
    It keeps the original image representation and the fixed transport limits.
    """
    from . import mechanic_v3_outcome_evidence as evidence
    from .protocol import load_lines
    from .action_links import frame_id
    root = Path(root)
    request = root/'requests'/prior
    selected = read(request/'selected_manifest.json')
    actual = read(request/'actual_delivery.json')
    prompt = root/'model_calls'/prior/'prompt.txt'
    if sha(prompt) != actual['prompt_sha256']:
        raise ValueError('Retained source-gap prompt changed')
    manifest = read(root/'evidence_manifest.json')
    subset = selected['evidence_sets'][parent]
    wanted = evidence.selected_ids(manifest, parent)
    indexed = {frame_id(row, n): row for n, row in enumerate(
        load_lines(root/'runtime/frame_index.jsonl'), 1)}
    evidence.validate_pixels(root, subset, indexed, wanted)
    references = [e for e in selected['items'] if e['type'] == 'reference']
    expected = references + subset['delivery_sheets']
    if [(i['path'], i['sha256']) for i in actual['images']] != [
            (i['path'], i['sha256']) for i in expected]:
        raise ValueError('Retained complete native sheet image list differs')
    if set(actual['actual_frame_ids']) != wanted:
        raise ValueError('Retained native frame delivery differs')
    for image in expected:
        path = root/image['path']
        if sha(path) != image['sha256']:
            raise ValueError('Retained native image changed')
        bind(path)
    bind(root/'runtime/frame_index.jsonl')
    for item in subset['frames'].values():
        bind(root/item['path'])
    return dict(prior_authorization_present=False, retained_sheets_verified=True,
                frame_ids=sorted(wanted), image_count=len(expected),
                original_image_representation_preserved=True)


def authorize(root, task, parent, repair_path):
    """Preserve even valid-looking outputs when actual source delivery was deficient."""
    root=Path(root).resolve();repair_path=Path(repair_path).resolve();repair=read(repair_path)
    if repair.get('classification')!='NON_SCORING_SOURCE_DELIVERY_GAP':
        raise ValueError('A demonstrated source-delivery defect is required')
    for path,digest in repair['after_source_bindings'].items():
        if sha(Path(path))!=digest:raise ValueError('Source repair implementation drift')
    bindings=dict(repair['after_source_bindings']);bindings[str(repair_path)]=sha(repair_path)
    def bind(path):
        path=Path(path).resolve();bindings[str(path)]=sha(path)
    name=task;seen=set()
    while (root/'engineering/judge_transport_recovery'/(name+'.json')).exists():
        if name in seen:raise ValueError('Cyclic original recovery')
        seen.add(name);p=root/'engineering/judge_transport_recovery'/(name+'.json');v=read(p);bind(p)
        for path,digest in v['bindings'].items():
            if sha(Path(path))!=digest:
                snapshot=repair.get('before_snapshots',{}).get(path)
                if repair['before_source_bindings'].get(path)!=digest or not snapshot or sha(Path(snapshot))!=digest:
                    raise ValueError('Historical recovery binding changed without preserved repair: '+path)
                bind(snapshot)
            else:bind(path)
        name=v['recovery_task']
    prior=name;folder=root/'model_calls'/prior
    if not (folder/'invocation.json').exists():raise ValueError('Retained model invocation required')
    context=read(root/'requests'/prior/'context_binding.json')
    manifest=read(root/'requests'/prior/'selected_manifest.json')
    source_ids={e['id'] for e in manifest['items'] if e['type']=='source'}
    gaps=[row for row in context['omitted_source_ranges'] if row['id'] in source_ids]
    if not gaps:raise ValueError('No demonstrated author-source omission; score retries prohibited')
    for directory in (folder,root/'requests'/prior):
        for p in directory.rglob('*'):
            if p.is_file():bind(p)
    for filename in ('input_manifest.json','source_qualification.json','evidence_manifest.json'):
        bind(root/filename)
    for e in manifest['items']:
        if e['type']=='source':
            if sha(root/e['path'])!=e['sha256']:raise ValueError('Frozen source changed')
            bind(root/e['path'])
    # The prior native image authorization is retained, but the new claim binds
    # current code and the immutable old receipts instead of silently rebasing.
    image_path=root/'engineering/judge_image_transport'/(prior+'.json')
    from .mechanic_v3_image_transport import NATIVE_VERSION, SHEET_VERSION
    sheet_proof = None
    if image_path.exists():
        image=read(image_path);bind(image_path)
        if image.get('version')!=NATIVE_VERSION:
            raise ValueError('Expected retained native-file transport')
        image_version=NATIVE_VERSION
    else:
        sheet_proof=_retained_sheet_bindings(root,prior,parent,bind)
        image_version=SHEET_VERSION
    fingerprint=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    recovery=task+'_source_'+fingerprint[:12]
    receipt=dict(version=VERSION,time=stamp(),canonical_task=task,parent=parent,
        prior_invocation=prior,recovery_task=recovery,bindings=bindings,source_gaps=gaps,
        classification='HARNESS_ERROR',product_score=None,old_response_preserved=True,
        scoring_semantics_unchanged=True,reason=repair['root_cause'],
        **({'retained_sheet_qualification':sheet_proof} if sheet_proof else {}))
    exclusive_json(_path(root,task),receipt);exclusive_json(_path(root,recovery),receipt)
    exclusive_json(root/'engineering/judge_image_transport'/(recovery+'.json'),
        dict(version=image_version,parent_evidence_set=parent,source_bindings=bindings,
             original_request=prior,complete_source_recovery=True,
             **({'retained_sheet_qualification':sheet_proof} if sheet_proof else {})))
    return receipt


def authorize_preflight(root, task, repair_path, *, native_files=True):
    """Keep the first pending claim after a source-wrapper-only preflight fix."""
    root=Path(root).resolve();repair_path=Path(repair_path).resolve();repair=read(repair_path)
    if repair.get('classification')!='NON_SCORING_SOURCE_PREFLIGHT':
        raise ValueError('Explicit source preflight repair required')
    prior=_path(root,task);old=read(prior);attempt=old['recovery_task']
    if (root/'model_calls'/attempt).exists():raise ValueError('Preflight repair cannot supersede a model call')
    bindings={}
    for path,digest in old['bindings'].items():
        if sha(Path(path))==digest:bindings[path]=digest
        else:
            snapshot=repair['before_snapshots'].get(path)
            if not snapshot or sha(Path(snapshot))!=digest:
                raise ValueError('Preflight changed unrelated binding')
            bindings[snapshot]=digest
    for path,digest in repair['after_source_bindings'].items():
        if sha(Path(path))!=digest:raise ValueError('Preflight implementation drift')
        bindings[path]=digest
    bindings[str(prior)]=sha(prior);bindings[str(repair_path)]=sha(repair_path)
    name=attempt+'_preflight_'+sha(repair_path)[:12]
    ancestor = root/'engineering/complete_source_preflight'/(old['canonical_task']+'.json')
    if ancestor.exists():
        if read(ancestor) != old:
            raise ValueError('Preflight ancestor identity changed')
        bindings[str(ancestor)] = sha(ancestor)
    receipt=dict(old,canonical_task=task,recovery_task=name,bindings=bindings,pending_claim_preserved=True,
                 prior_pending_claim=str(prior),preflight_parent=attempt)
    if repair.get('exact_evidence_body_transport') is True:
        diagnosis=repair['overflow_diagnoses'][task]
        prompt_path=Path(diagnosis['prompt']);measurement_path=Path(diagnosis['measurement'])
        measurement=read(measurement_path)
        from .frame_budget import request_transport
        limit=request_transport(read(root/'input/pilot_rubric.json'))['maximum_prompt_bytes']
        if (sha(prompt_path)!=measurement['prompt_sha256'] or
                prompt_path.stat().st_size!=measurement['prompt_bytes'] or
                measurement['maximum_prompt_bytes']!=limit or measurement['prompt_bytes']<=limit):
            raise ValueError('Exact evidence recovery requires saved full preflight overflow')
        bindings[str(prompt_path)]=sha(prompt_path);bindings[str(measurement_path)]=sha(measurement_path)
        receipt['exact_evidence_body_transport'] = True
    if repair.get('exact_shared_source_packets'):
        if receipt.get('exact_evidence_body_transport') is not True:
            raise ValueError('Shared source transport requires diagnosed exact preflight authorization')
        from .mechanic_v3_shared_source_transport import validate_packet
        packets = repair['exact_shared_source_packets']
        for ident, packet_path in packets.items():
            _, source_path, _ = validate_packet(root, ident, packet_path)
            bindings[str(Path(packet_path).resolve())] = sha(Path(packet_path))
            bindings[str(source_path.resolve())] = sha(source_path)
        receipt['exact_shared_source_packets'] = packets
    exclusive_json(root/'engineering/complete_source_preflight'/(task+'.json'),receipt)
    exclusive_json(_path(root,name),receipt)
    from .mechanic_v3_image_transport import NATIVE_VERSION
    if native_files:
        exclusive_json(root/'engineering/judge_image_transport'/(name+'.json'),
            dict(version=NATIVE_VERSION,parent_evidence_set=old['parent'],source_bindings=bindings,
                 original_request=old['prior_invocation'],complete_source_recovery=True))
    return receipt
