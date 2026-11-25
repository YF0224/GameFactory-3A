"""One evidence-bound correction of an invalid outcome response, never a score retry.

All original source/images and valid shards remain in place. Only a documented
cross-field output-validation failure may add explicit formatting guidance.
The scoring validator, contract and evidence are unchanged.
"""
from pathlib import Path
import hashlib
import json
from .protocol import sha
from .mechanic_v3_runner import read, stamp, exclusive_json

VERSION = 'mechanic-outcome-invalid-response-recovery.v1'
ERROR = 'NORMAL lacks genuine functional/processing proof'
NOTE = '''\nOUTPUT CONSISTENCY VALIDATION (existing outcome_frame_v1 requirements, no new scoring gate):
A previous invocation failed the cross-field validator: NORMAL lacks genuine functional/processing proof.
Before emitting NORMAL, verify basic_function.evidence itself contains an actually delivered runtime
FRAME/STATE/EVENT observation proving this check's functional effect and correct target. Source-only
citations cannot prove runtime. If functionality was not actually established, use UNOBSERVED and
truthful flags. The result_outcome judgment is independent. A visible failure screen does not by itself
prove a different action such as restart. Never invent citations, effects, processing or timestamps.
Use the entire unchanged supplied evidence; judge all requested checks independently. No prior score
or response is supplied. All frozen 10/50/100 criteria and the original validator remain authoritative.
'''


def _path(root, task):
    return Path(root)/'engineering/judge_validation_recovery'/(task+'.json')


def _verify(receipt):
    if receipt.get('version') != VERSION:
        raise ValueError('Unknown invalid-response recovery version')
    for name, digest in receipt['bindings'].items():
        if sha(Path(name)) != digest:
            raise ValueError('Invalid-response recovery binding changed: '+name)


def authorize(root, task, repair_path):
    """Reserve one changed request after diagnosing a specific invalid output."""
    root=Path(root).resolve();repair_path=Path(repair_path).resolve()
    existing=_path(root,task)
    if existing.exists():
        receipt=read(existing);_verify(receipt);return receipt
    repair=read(repair_path)
    if repair.get('classification') != 'NON_SCORING_INVALID_RESPONSE_RECOVERY':
        raise ValueError('Documented invalid-response diagnosis required')
    for name, digest in repair['after_source_bindings'].items():
        if sha(Path(name)) != digest:raise ValueError('Recovery implementation drift')
    folder=root/'model_calls'/task
    failure=read(folder/'validation_error.json')
    if (folder/'accepted_response.json').exists() or failure.get('exception') != ERROR:
        raise ValueError('Only exact preserved NORMAL validation failure can recover')
    if sha(folder/'response.json') != failure['response_sha256']:
        raise ValueError('Rejected response changed')
    original_prompt=(folder/'prompt.txt').read_text()
    if 'OUTPUT CONSISTENCY VALIDATION' in original_prompt:
        raise ValueError('No repeated invalid-response correction')
    bindings={str(p.resolve()):sha(p) for p in folder.iterdir() if p.is_file()}
    for p in [repair_path, root/'requests'/task/'actual_delivery.json',
              root/'input_manifest.json',root/'source_qualification.json',root/'evidence_manifest.json']:
        bindings[str(p.resolve())]=sha(p)
    actual=read(root/'requests'/task/'actual_delivery.json')
    for image in actual['images']:
        p=root/image['path']
        if sha(p)!=image['sha256']:raise ValueError('Original delivered image changed')
        bindings[str(p.resolve())]=sha(p)
    # Fresh output corrections must preserve the already qualified transport.
    # Existing mappings above remain immutable, including historical incomplete
    # corrections that require their own publication-level source recovery.
    from . import mechanic_v3_source_delivery as source
    from . import mechanic_v3_image_transport as images
    complete_source=source.authorization(root,task)
    image_path=root/'engineering/judge_image_transport'/(task+'.json')
    image=read(image_path) if image_path.exists() else None
    if complete_source is not None:
        bindings.update(complete_source['bindings'])
        bindings[str(source._path(root,task).resolve())]=sha(source._path(root,task))
    if image is not None:
        if image.get('version') not in {images.VERSION,images.NATIVE_VERSION}:
            raise ValueError('Unknown parent image transport')
        for name,digest in image['source_bindings'].items():
            if sha(Path(name))!=digest:
                raise ValueError('Parent image transport binding changed: '+name)
        if (complete_source is not None and
                image.get('parent_evidence_set')!=complete_source['parent']):
            raise ValueError('Parent image/source evidence set differs')
        bindings.update(image['source_bindings'])
        bindings[str(image_path.resolve())]=sha(image_path)
    bindings[str(Path(__file__).resolve())]=sha(Path(__file__))
    fingerprint=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    receipt=dict(version=VERSION,time=stamp(),original_task=task,
        recovery_task=task+'_validation_'+fingerprint[:12],bindings=bindings,
        guidance_sha256=hashlib.sha256(NOTE.encode()).hexdigest(),
        original_failure_preserved=True,original_response_modified=False,
        contract_evidence_validator_unchanged=True,reason=repair['root_cause'])
    name=receipt['recovery_task']
    if (root/'model_calls'/name).exists():
        raise ValueError('Validation correction cannot replace a retained invocation')
    if complete_source is not None:
        inherited=dict(complete_source,time=stamp(),canonical_task=name,
            recovery_task=name,prior_invocation=task,bindings=bindings,
            first_delivery=False,validation_recovery_parent=task)
        exclusive_json(source._path(root,name),inherited)
    if image is not None:
        exclusive_json(root/'engineering/judge_image_transport'/(name+'.json'),
            dict(image,source_bindings=bindings,original_request=task,
                 validation_recovery_parent=task))
    exclusive_json(existing,receipt)
    exclusive_json(_path(root,receipt['recovery_task']),dict(receipt,recovery_request=True))
    return receipt


def selected_task(root, task):
    name,parent,specs=task;p=_path(root,name)
    if not p.exists():return task
    receipt=read(p);_verify(receipt)
    if receipt.get('recovery_request'):return task
    return receipt['recovery_task'],parent,specs


def request_note(root, name):
    p=_path(root,name)
    if not p.exists():return ''
    receipt=read(p);_verify(receipt)
    if not receipt.get('recovery_request'):return ''
    if receipt['guidance_sha256']!=hashlib.sha256(NOTE.encode()).hexdigest():
        raise ValueError('Recovery guidance changed')
    return NOTE
