"""First-invocation admission for complete source and original native frames.

Creates immutable claims before any model call; retained invocations must use
explicit diagnosed recovery instead. This is not a retry or a scoring policy.
"""
from pathlib import Path
from . import mechanic_v3_source_delivery as source, mechanic_v3_image_transport as images
from .mechanic_v3_runner import exclusive_json, stamp, read
from .protocol import sha

VERSION='mechanic-first-complete-source-admission.v1'


def authorize(root,task,parent,*,native_files=True):
    root=Path(root).resolve()
    if (root/'model_calls'/task).exists():
        raise ValueError('First delivery cannot replace a retained invocation')
    existing=source._path(root,task)
    if existing.exists():
        receipt=read(existing);source.verify(receipt)
        if receipt.get('first_delivery') is not True:raise ValueError('Retained recovery is not first delivery')
        return receipt
    if (root/'engineering/judge_transport_recovery'/(task+'.json')).exists():
        raise ValueError('Retained transport recovery requires its own lineage')
    from . import mechanic_v3_execution as execution
    bindings={str(Path(p).resolve()):sha(Path(p)) for p in (
        __file__,source.__file__,images.__file__,execution.__file__,
        root/'input_manifest.json',root/'source_qualification.json',root/'evidence_manifest.json')}
    manifest=read(root/'evidence_manifest.json')
    for e in manifest['items']:
        if e['type']=='source':
            path=root/e['path']
            if sha(path)!=e['sha256']:raise ValueError('Frozen author source changed')
            bindings[str(path)]=sha(path)
    receipt=dict(version=source.VERSION,time=stamp(),admission_version=VERSION,
        canonical_task=task,recovery_task=task,parent=parent,prior_invocation=None,
        first_delivery=True,bindings=bindings,source_gaps=[],product_score=None,
        scoring_semantics_unchanged=True,all_native_frames_preserved=True)
    if native_files:
        exclusive_json(root/'engineering/judge_image_transport'/(task+'.json'),
            dict(version=images.NATIVE_VERSION,parent_evidence_set=parent,
                 source_bindings=bindings,original_request=None,first_delivery=True))
    exclusive_json(existing,receipt)
    return receipt
