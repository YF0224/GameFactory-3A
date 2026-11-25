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

VERSION = 'mechanic-outcome-frozen-output-consistency.v1'
NOTES = {
    'Non-frozen trigger mode': """OUTPUT CONSISTENCY VALIDATION: use only a trigger mode explicitly allowed
for that exact check in the unchanged frozen paired contract and schema. A mode
is required to obey that enum even when the effect was UNOBSERVED. Never infer
an allowed mode from another check or change the contract. Preserve truthful
observation flags and all original citations; a frozen mode is not evidence of
an observed effect. If not actually established, report UNOBSERVED truthfully.
""",
    'Basic BUG needs real observed counterexample': """OUTPUT CONSISTENCY VALIDATION: BUG requires an actually delivered runtime
FRAME/STATE/EVENT counterexample of this check's basic function. Missing coverage,
source-only suspicion or lack of success is not such a counterexample. Use
UNOBSERVED when the supplied evidence does not establish a runtime bug or normal
function. Never invent actions, observations, counterexamples or citations.
""",
}
SUFFIX = """Judge every original check independently using the entire unchanged source and
all supplied original images. No previous score or verdict is supplied. All frozen
10/50/100 rules, criterion identities and validators remain authoritative.
"""


def note(error):
    if error not in NOTES:
        raise ValueError('Only exact frozen-output validation failures can recover')
    return '\n'+NOTES[error]+SUFFIX


def parent_bindings(bindings, repair):
    """Archive exact old producers while keeping all evidence bindings current."""
    result = {}
    code = Path(__file__).resolve().parent
    for name, digest in bindings.items():
        path = Path(name)
        current = sha(path)
        if current != digest:
            archive = repair.get('before_producer_archives', {}).get(name)
            if (path.parent != code or path.name != 'mechanic_v3_execution.py'
                    or not archive or sha(Path(archive)) != digest):
                raise ValueError('Parent evidence or unarchived producer changed: '+name)
            result[str(Path(archive).resolve())] = digest
        result[name] = current
    return result



def _path(root, task):
    return Path(root)/'engineering/judge_frozen_output_recovery'/(task+'.json')


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
    if repair.get('classification') != 'NON_SCORING_FROZEN_OUTPUT_CONSISTENCY':
        raise ValueError('Documented invalid-response diagnosis required')
    required = {str(Path(__file__).resolve()), str(Path(__file__).resolve().with_name('mechanic_v3_execution.py'))}
    if not required <= repair['after_source_bindings'].keys():
        raise ValueError('Exact current recovery and execution producers required')
    for name, digest in repair['after_source_bindings'].items():
        if sha(Path(name)) != digest:raise ValueError('Recovery implementation drift')
    folder=root/'model_calls'/task
    failure=read(folder/'validation_error.json')
    error = failure.get('exception')
    guidance = note(error)
    if (folder/'accepted_response.json').exists():
        raise ValueError('Accepted verdict cannot be corrected')
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
    source_path=source._path(root,task)
    complete_source=read(source_path) if source_path.exists() else None
    if complete_source is not None and (complete_source.get('version') != source.VERSION or complete_source.get('recovery_task') != task):
        raise ValueError('Exact original complete-source authorization required')
    image_path=root/'engineering/judge_image_transport'/(task+'.json')
    image=read(image_path) if image_path.exists() else None
    if complete_source is not None:
        bindings.update(parent_bindings(complete_source['bindings'],repair))
        bindings[str(source._path(root,task).resolve())]=sha(source._path(root,task))
    if image is not None:
        if image.get('version') not in {images.VERSION,images.NATIVE_VERSION}:
            raise ValueError('Unknown parent image transport')
        verified_image_bindings=parent_bindings(image['source_bindings'],repair)
        if (complete_source is not None and
                image.get('parent_evidence_set')!=complete_source['parent']):
            raise ValueError('Parent image/source evidence set differs')
        bindings.update(verified_image_bindings)
        bindings[str(image_path.resolve())]=sha(image_path)
    bindings.update(repair['after_source_bindings'])
    bindings[str(Path(__file__).resolve())]=sha(Path(__file__))
    fingerprint=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    receipt=dict(version=VERSION,time=stamp(),original_task=task,
        recovery_task=task+'_consistency_'+fingerprint[:12],bindings=bindings,
        guidance_sha256=hashlib.sha256(guidance.encode()).hexdigest(),
        validation_error=error,original_failure_preserved=True,original_response_modified=False,
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
    guidance=note(receipt['validation_error'])
    if receipt['guidance_sha256']!=hashlib.sha256(guidance.encode()).hexdigest():
        raise ValueError('Recovery guidance changed')
    return guidance
