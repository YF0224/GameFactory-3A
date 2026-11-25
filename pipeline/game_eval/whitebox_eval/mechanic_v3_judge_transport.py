"""Lossless Mechanic-only schema grouping and source-bound transport recovery.

Every native frame, source line and citation restriction remains in the request.
The grouping replaces identical citation alternatives with a union of their IDs.
"""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
from .protocol import dump, sha
from .mechanic_v3_runner import read, stamp, exclusive_json
from .judge_schema_transport import compact, expand

VERSION = 'mechanic-judge-exact-citation-groups.v1'


def key(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def group(schema):
    original = copy.deepcopy(schema)
    grouped = copy.deepcopy(schema)
    variants = grouped.get('$defs', {}).get('Citation', {}).get('anyOf', [])
    groups = []; order = []; known = {}
    for variant in variants:
        props = variant.get('properties', {})
        ids = props.get('id', {}).get('enum', [])
        if len(ids) != 1 or not isinstance(ids[0], str):
            raise ValueError('Citation grouping requires exact singleton identity alternatives')
        shape = copy.deepcopy(variant); del shape['properties']['id']['enum']
        signature = key(shape)
        if signature not in known:
            known[signature] = len(groups); groups.append(copy.deepcopy(variant))
        else:
            groups[known[signature]]['properties']['id']['enum'].extend(ids)
        order.append(dict(group=known[signature], id=ids[0]))
    if variants:
        grouped['$defs']['Citation']['anyOf'] = groups
    # Prove the exact inverse, including original alternative order and bounds.
    restored = copy.deepcopy(grouped)
    if variants:
        ungrouped = []
        for entry in order:
            variant = copy.deepcopy(groups[entry['group']])
            variant['properties']['id']['enum'] = [entry['id']]
            ungrouped.append(variant)
        restored['$defs']['Citation']['anyOf'] = ungrouped
    if restored != original:
        raise ValueError('Citation grouping failed exact inverse proof')
    wire = compact(grouped)
    if expand(wire) != expand(grouped):
        raise ValueError('Shared schema differs from grouped schema')
    proof = dict(version=VERSION, original_alternatives=len(variants), grouped_alternatives=len(groups),
        inverse_order=order, exact_inverse_verified=True, scoring_semantics_unchanged=True,
        original_canonical_sha256=hashlib.sha256(key(original).encode()).hexdigest(),
        restored_canonical_sha256=hashlib.sha256(key(restored).encode()).hexdigest(),
        submitted_canonical_sha256=hashlib.sha256(key(wire).encode()).hexdigest())
    return wire, proof


def selected_task(root, task):
    name, parent, specs = task
    seen=set()
    while True:
        if name in seen:raise ValueError('Cyclic judge transport recovery')
        seen.add(name)
        path=root/'engineering/judge_transport_recovery'/(name+'.json')
        if not path.exists():return name,parent,specs
        receipt=read(path)
        for source,digest in receipt['bindings'].items():
            if sha(Path(source))!=digest:raise ValueError('Judge transport recovery source changed: '+source)
        if receipt['transport_version']!=VERSION or receipt['original_task']!=name:
            raise ValueError('Invalid judge transport recovery identity')
        name=receipt['recovery_task']


def authorize(root, task, repair_path):
    """Bind one substantive transport repair to a preserved failed invocation."""
    root=Path(root);repair_path=Path(repair_path)
    repair=read(repair_path)
    if repair.get('classification') != 'NON_SCORING_TOOL_TRANSPORT':
        raise ValueError('Documented transport root cause required')
    for source,digest in repair['after_source_bindings'].items():
        if sha(Path(source)) != digest:raise ValueError('Transport repair code drift')
    folder=root/'model_calls'/task
    if not (folder/'validation_error.json').exists() or (folder/'accepted_response.json').exists():
        raise ValueError('Only preserved validator-rejected transport errors can recover')
    raw=read(folder/'response.json')
    errors=[part for check in raw.get('checks',{}).values() for part in check.values()
            if isinstance(part,dict) and part.get('status')=='HARNESS_ERROR']
    if not errors:raise ValueError('Product judgment is not a transport recovery')
    bindings={str(p.resolve()):sha(p) for p in folder.iterdir() if p.is_file()}
    bindings.update({str(repair_path.resolve()):sha(repair_path)})
    for name in ('input_manifest.json','source_qualification.json','evidence_manifest.json'):
        bindings[str((root/name).resolve())]=sha(root/name)
    fingerprint=hashlib.sha256(key(bindings).encode()).hexdigest()
    receipt=dict(time=stamp(),transport_version=VERSION,original_task=task,
        recovery_task=task+'_transport_'+fingerprint[:12],bindings=bindings,
        reason=repair['root_cause'],original_failure_preserved=True,scoring_semantics_unchanged=True,
        images_and_parent_context_unchanged=True)
    path=root/'engineering/judge_transport_recovery'/(task+'.json')
    exclusive_json(path,receipt)
    return receipt


def authorize_payload_recovery(root, task, repair_path):
    """One changed lossless request after a demonstrated transport-size error."""
    from .mechanic_v3_image_transport import VERSION as image_version
    root=Path(root);repair_path=Path(repair_path);repair=read(repair_path)
    if repair.get('classification')!='NON_SCORING_TOOL_TRANSPORT':
        raise ValueError('Documented transport root cause required')
    for path,digest in repair['after_source_bindings'].items():
        if sha(Path(path))!=digest:raise ValueError('Payload repair implementation drift')
    folder=root/'model_calls'/task
    if (folder/'response.json').exists() or (folder/'accepted_response.json').exists():
        raise ValueError('Payload recovery requires a failed request without a response')
    events=(folder/'events.jsonl').read_text()
    if '413' not in events or 'turn.failed' not in events:
        raise ValueError('Original events do not prove failed HTTP 413')
    bindings={str(p.resolve()):sha(p) for p in folder.iterdir() if p.is_file()}
    for path in [repair_path,root/'requests'/task/'actual_delivery.json',
                 root/'input_manifest.json',root/'source_qualification.json',root/'evidence_manifest.json']:
        bindings[str(path.resolve())]=sha(path)
    actual=read(root/'requests'/task/'actual_delivery.json')
    for image in actual['images']:
        path=root/image['path']
        if sha(path)!=image['sha256']:raise ValueError('Original image drift')
        bindings[str(path.resolve())]=sha(path)
    fingerprint=hashlib.sha256(key(bindings).encode()).hexdigest()
    receipt=dict(time=stamp(),transport_version=VERSION,original_task=task,
        recovery_task=task+'_payload_'+fingerprint[:12],bindings=bindings,
        reason=repair['root_cause'],original_failure_preserved=True,scoring_semantics_unchanged=True,
        images_and_parent_context_unchanged=True,decoded_native_pixels_unchanged=True)
    exclusive_json(root/'engineering/judge_image_transport'/(receipt['recovery_task']+'.json'),
        dict(version=image_version,source_bindings=bindings,original_request=task))
    exclusive_json(root/'engineering/judge_transport_recovery'/(task+'.json'),receipt)
    return receipt
