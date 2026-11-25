"""Opt-in lossless image encoding after a preserved HTTP 413 rejection.

The original PNGs and raw frame bytes remain immutable. Every delivered sheet
has identical decoded RGB pixels, size, labels, native tiles and frame IDs.
"""
from pathlib import Path
import copy
from PIL import Image
from .protocol import sha
from .mechanic_v3_runner import read, exclusive_json

VERSION='mechanic-native-pixels-lossless-webp.v1'
NATIVE_VERSION='mechanic-original-native-frames.v1'
SHEET_VERSION='mechanic-retained-native-sheets-source-recovery.v1'


def encode(source, destination):
    source=Path(source);destination=Path(destination)
    destination.parent.mkdir(parents=True,exist_ok=True)
    with Image.open(source) as original:
        rgb=original.convert('RGB')
        if not destination.exists():
            temporary=destination.with_suffix('.partial')
            rgb.save(temporary,format='WEBP',lossless=True,quality=100,method=6)
            with Image.open(temporary) as check:
                if check.size!=rgb.size or check.convert('RGB').tobytes()!=rgb.tobytes():
                    raise ValueError('Lossless encoder changed native pixels')
            temporary.replace(destination)
        with Image.open(destination) as check:
            if check.size!=rgb.size or check.convert('RGB').tobytes()!=rgb.tobytes():
                raise ValueError('Preserved lossless transport changed native pixels')
    return dict(source=str(source),source_sha256=sha(source),destination=str(destination),
        destination_sha256=sha(destination),source_bytes=source.stat().st_size,
        destination_bytes=destination.stat().st_size,native_rgb_pixels_identical=True)


def apply(root, manifest, parent, name):
    root=Path(root);authorization=root/'engineering/judge_image_transport'/(name+'.json')
    if not authorization.exists():return manifest
    value=read(authorization)
    if value['version'] not in {VERSION,NATIVE_VERSION,SHEET_VERSION}:raise ValueError('Unknown image transport')
    for path,digest in value['source_bindings'].items():
        if sha(Path(path))!=digest:raise ValueError('Lossless image transport source changed: '+path)
    if value['version']==SHEET_VERSION:
        from .mechanic_v3_source_delivery import _retained_sheet_bindings
        if (value.get('parent_evidence_set') != parent or
                value.get('complete_source_recovery') is not True):
            raise ValueError('Retained sheets require diagnosed source recovery')
        def checked(path):
            path=Path(path).resolve()
            if value['source_bindings'].get(str(path)) != sha(path):
                raise ValueError('Retained sheet recovery binding missing: '+str(path))
        proof=_retained_sheet_bindings(root,value['original_request'],parent,checked)
        if proof != value.get('retained_sheet_qualification'):
            raise ValueError('Retained native sheet qualification changed')
        from . import mechanic_v3_outcome_evidence as evidence
        from .protocol import load_lines
        from .action_links import frame_id
        indexed={frame_id(row,n):row for n,row in enumerate(
            load_lines(root/'runtime/frame_index.jsonl'),1)}
        evidence.validate_pixels(root,manifest['evidence_sets'][parent],indexed,set(proof['frame_ids']))
        return manifest
    if value['version']==NATIVE_VERSION:
        return native_frames(root,manifest,parent,name,value,authorization)
    result=copy.deepcopy(manifest);subset=result['evidence_sets'][parent];mappings={};proofs=[]
    for sheet in subset['delivery_sheets']:
        source=root/sheet['path']
        if sha(source)!=sheet['sha256']:raise ValueError('Original native sheet SHA changed')
        relative=Path('delivery/lossless_native_webp_v1')/(sha(source)+'.webp')
        proof=encode(source,root/relative);proofs.append(proof)
        mappings[sheet['path']]=str(relative)
        sheet.update(path=str(relative),sha256=proof['destination_sha256'])
    for item in subset['frames'].values():item['delivery_sheet']=mappings[item['delivery_sheet']]
    for item in result['items']:
        if item.get('delivery_sheet') in mappings:item['delivery_sheet']=mappings[item['delivery_sheet']]
    proof=dict(version=VERSION,authorization_sha256=sha(authorization),images=proofs,
        image_count=len(proofs),all_original_images_delivered=True,frame_ids_unchanged=True,
        original_image_bytes=sum(p['source_bytes'] for p in proofs),
        delivered_image_bytes=sum(p['destination_bytes'] for p in proofs))
    path=root/'requests'/name/'lossless_image_transport.json'
    if path.exists():
        if read(path)!=proof:raise ValueError('Lossless delivery proof changed')
    else:exclusive_json(path,proof)
    from . import mechanic_v3_outcome_evidence as evidence
    from .protocol import load_lines
    from .action_links import frame_id
    indexed={frame_id(row,index):row for index,row in enumerate(load_lines(root/'runtime/frame_index.jsonl'),1)}
    evidence.validate_pixels(root,subset,indexed,set(subset['frames']))
    return result


def native_frames(root, manifest, parent, name, value, authorization):
    """Deliver byte-identical raw images without the contact-sheet expansion.

    Validate the original complete sheets first; retain their immutable proof.
    The existing 100-image and prompt byte gates still run on the final request.
    """
    from . import mechanic_v3_outcome_evidence as evidence
    from .protocol import load_lines, checked_path
    from .action_links import frame_id
    from . import frame_budget
    root=Path(root)
    if value.get('parent_evidence_set')!=parent:
        raise ValueError('Native image authorization parent mismatch')
    indexed={frame_id(row,index):row for index,row in enumerate(load_lines(root/'runtime/frame_index.jsonl'),1)}
    original=manifest['evidence_sets'][parent]
    wanted=set(original['frames'])
    evidence.validate_pixels(root,original,indexed,wanted)
    protocol=read(root/'input/pilot_rubric.json')
    references=([item for item in manifest['items'] if item['type']=='reference']
                if original.get('include_references') is not False else [])
    if len(wanted)+len(references)>frame_budget.request_transport(protocol)['maximum_images']:
        raise ValueError('Original native frames exceed unchanged request image limit')
    result=copy.deepcopy(manifest);subset=result['evidence_sets'][parent]
    sheets=[];proofs=[]
    for ident,item in subset['frames'].items():
        raw=checked_path(root,item['path'])
        with Image.open(raw) as image:
            image.load(); width,height=image.size
            if image.format!='JPEG':raise ValueError('Native JPEG recovery requires original JPEG frames')
        sheets.append(dict(path=item['path'],sha256=item['sha256'],frame_id=ident,t_ms=item['t_ms']))
        proofs.append(dict(frame_id=ident,source_path=item['path'],source_sha256=item['sha256'],
            delivered_path=item['path'],delivered_sha256=sha(raw),bytes=raw.stat().st_size,
            original_sheet=item['delivery_sheet'],original_tile_rect=item['tile_rect']))
        item.update(delivery_sheet=item['path'],tile=0,tile_rect=[0,0,width,height])
    subset['delivery_sheets']=sheets
    # for_task replaces frame items with this subset; update any shared view too.
    for i,item in enumerate(result['items']):
        if item.get('id') in subset['frames']:result['items'][i]=copy.deepcopy(subset['frames'][item['id']])
    proof=dict(version=NATIVE_VERSION,authorization_sha256=sha(authorization),
        parent_evidence_set=parent,images=proofs,image_count=len(proofs),
        all_original_images_delivered=True,frame_ids_unchanged=True,
        native_file_bytes_unchanged=True,original_sheets_pixel_validation_passed=True,
        delivered_image_bytes=sum(p['bytes'] for p in proofs),
        original_sheet_bytes=sum((root/p['path']).stat().st_size for p in original['delivery_sheets']))
    destination=root/'requests'/name/'native_frame_transport.json'
    if destination.exists():
        if read(destination)!=proof:raise ValueError('Native frame delivery proof changed')
    else:exclusive_json(destination,proof)
    # The IMAGE ID MAP already carries each frame ID, timestamp and filename.
    # State its new representation explicitly, without changing judge semantics.
    subset['native_frame_transport']=dict(version=NATIVE_VERSION,
        note='Each attached image is one complete original native JPEG frame, without a sheet or label overlay. '
             'IMAGE ID MAP and IMAGE MAP bind image order/path to FRAME ID and timestamp. '
             'All original frames and all parent source/channel context are retained; cite FRAME IDs as usual.')
    return result


def authorize_native(root, task, parent, repair_path):
    """Bind changed raw-file delivery to the preserved terminal WebP 413."""
    from .mechanic_v3_judge_transport import VERSION as transport_version, key
    from .mechanic_v3_runner import stamp
    import hashlib
    root=Path(root);repair_path=Path(repair_path);repair=read(repair_path)
    if repair.get('classification')!='NON_SCORING_TOOL_TRANSPORT':
        raise ValueError('Native image recovery needs documented transport repair')
    for source,digest in repair['after_source_bindings'].items():
        if sha(Path(source))!=digest:raise ValueError('Native transport repair drift')
    folder=root/'model_calls'/task
    if (folder/'accepted_response.json').exists() or (folder/'response.json').exists():
        raise ValueError('Native transport recovery cannot repeat a product judgment')
    events=(folder/'events.jsonl').read_text()
    if '413' not in events or 'turn.failed' not in events:
        raise ValueError('Native transport recovery requires preserved HTTP413')
    bindings={str(p.resolve()):sha(p) for p in folder.iterdir() if p.is_file()}
    paths=[repair_path,root/'requests'/task/'actual_delivery.json',root/'input_manifest.json',
           root/'source_qualification.json',root/'evidence_manifest.json',root/'runtime/frame_index.jsonl']
    actual=read(root/'requests'/task/'actual_delivery.json')
    paths.extend(root/image['path'] for image in actual['images'])
    bindings.update({str(p.resolve()):sha(p) for p in paths})
    fingerprint=hashlib.sha256(key(bindings).encode()).hexdigest()
    name=task+'_native_'+fingerprint[:12]
    exclusive_json(root/'engineering/judge_image_transport'/(name+'.json'),
        dict(version=NATIVE_VERSION,source_bindings=bindings,original_request=task,parent_evidence_set=parent))
    receipt=dict(time=stamp(),transport_version=transport_version,original_task=task,
        recovery_task=name,bindings=bindings,reason=repair['root_cause'],
        original_failure_preserved=True,scoring_semantics_unchanged=True,
        all_frames_sources_and_channels_unchanged=True,native_files_byte_identical=True)
    exclusive_json(root/'engineering/judge_transport_recovery'/(task+'.json'),receipt)
    return receipt


def authorize_native_parent(root, task, parent, failure_recovery):
    """Apply the same validated parent transport to a never-attempted shard."""
    root=Path(root);failure_recovery=Path(failure_recovery);receipt=read(failure_recovery)
    if (root/'model_calls'/task).exists():raise ValueError('Parent transport may not overwrite an attempted shard')
    recovered=receipt['recovery_task']
    authorization=root/'engineering/judge_image_transport'/(recovered+'.json')
    value=read(authorization)
    if value.get('version')!=NATIVE_VERSION or value.get('parent_evidence_set')!=parent:
        raise ValueError('Parent must match the source-bound native recovery')
    for source,digest in receipt['bindings'].items():
        if sha(Path(source))!=digest:raise ValueError('Parent recovery source changed')
    bindings=dict(value['source_bindings'])
    bindings[str(failure_recovery.resolve())]=sha(failure_recovery)
    bindings[str(authorization.resolve())]=sha(authorization)
    exclusive_json(root/'engineering/judge_image_transport'/(task+'.json'),
        dict(version=NATIVE_VERSION,parent_evidence_set=parent,source_bindings=bindings,
             original_request=value['original_request'],unattempted_parent_shard=True))


def authorize_preflight_revision(root, task, parent, repair_path):
    """Preserve an unattempted claim when an evidence preflight fixes delivery."""
    from .mechanic_v3_judge_transport import VERSION as transport_version
    root=Path(root);repair_path=Path(repair_path);repair=read(repair_path)
    if (root/'model_calls'/task).exists():raise ValueError('Preflight revision requires no model invocation')
    if repair.get('classification')!='NON_SCORING_TOOL_TRANSPORT':raise ValueError('Documented preflight repair required')
    for path,digest in repair['after_source_bindings'].items():
        if sha(Path(path))!=digest:raise ValueError('Preflight revision code drift')
    prior=root/'engineering/judge_image_transport'/(task+'.json');value=read(prior)
    if value.get('version')!=NATIVE_VERSION or value.get('parent_evidence_set')!=parent:
        raise ValueError('Preflight native delivery parent changed')
    bindings=dict(value['source_bindings'])
    bindings.update({str(prior.resolve()):sha(prior),str(repair_path.resolve()):sha(repair_path),
                     **repair['after_source_bindings']})
    name=task+'_preflight_'+sha(repair_path)[:12]
    exclusive_json(root/'engineering/judge_image_transport'/(name+'.json'),
        dict(value,source_bindings=bindings,pending_claim_preserved=True))
    exclusive_json(root/'engineering/judge_transport_recovery'/(task+'.json'),
        dict(transport_version=transport_version,original_task=task,recovery_task=name,bindings=bindings,
             reason=repair['root_cause'],prior_model_calls=0,pending_claim_preserved=True))
    return name
