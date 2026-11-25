"""Once-only preinput derivation for a real route with no observation windows."""
import shutil
import time
from pathlib import Path

from .protocol import dump, sha

RECEIPT = 'partial_observation_recovery.json'
VERSION = 'whitebox-preinput-partial-observation.v1'
CLAIM = 'partial_observation_recovery_claim.json'


def eligible(source):
    from . import batch, runtime, unity_plan_normalization
    source = Path(source)
    if ((source/RECEIPT).exists() or (source/CLAIM).exists() or (source/'background_record').exists()
            or (source/'scores.json').exists() or not (source/'plan_normalization.json').is_file()):
        return False
    try:
        unity_plan_normalization.verify(source)
        plan = batch.read(source/'sol_plan.json')
        return (not plan['capture_plan']['windows']
            and all(e['reachability']=='UNREACHABLE' for e in plan['capture_plan']['endpoints'].values())
            and any(a['action']!='wait' for a in runtime.native_actions(plan))
            and (source/'route_metadata_repair.json').is_file())
    except (OSError, ValueError, KeyError, TypeError):
        return False


def verify(root):
    from . import batch, unity_plan_normalization
    root = Path(root)
    receipt = batch.read(root/RECEIPT)
    source = Path(receipt['source_attempt'])
    if receipt.get('version') != VERSION or source.resolve()==root.resolve() or (source/RECEIPT).exists():
        raise ValueError('Invalid partial observation recovery lineage')
    claim = batch.read(source/CLAIM)
    if claim.get('child_attempt') != str(root.resolve()) or sha(source/CLAIM) != receipt.get('claim_sha256'):
        raise ValueError('Partial observation recovery claim changed')
    batch.verify_inputs(source)
    unity_plan_normalization.verify(source)
    for name,digest in receipt['source_bindings'].items():
        if Path(name).is_absolute() or '..' in Path(name).parts or sha(source/name)!=digest:
            raise ValueError('Partial observation recovery source changed: '+name)
    for name,digest in receipt['copied_bindings'].items():
        if Path(name).is_absolute() or '..' in Path(name).parts or sha(root/name)!=digest:
            raise ValueError('Partial observation copied input changed: '+name)
    return True


def resume_candidate(source):
    """Reuse the single completed derivation without deleting its original claim."""
    from . import batch, unity_plan_normalization
    source = Path(source).resolve()
    if not (source/CLAIM).is_file():
        return None
    if (source/RECEIPT).exists() or any((source/n).exists() for n in ('background_record','scores.json')):
        raise ValueError('Partial observation source has already advanced past preinput recovery')
    claim = batch.read(source/CLAIM)
    child = Path(claim['child_attempt']).resolve()
    if claim.get('policy') != VERSION or child.parent != source.parent or child == source:
        raise ValueError('Invalid partial observation recovery claim')
    receipt = batch.read(child/RECEIPT)
    if Path(receipt['source_attempt']).resolve() != source:
        raise ValueError('Partial observation claim references another source')
    if any((child/n).exists() for n in ('background_record','scores.json')):
        raise ValueError('Claimed partial observation child already recorded or scored')
    verify(child)
    unity_plan_normalization.verify(child)
    if not batch.read(child/'sol_plan.json')['capture_plan']['windows']:
        raise ValueError('Claimed partial observation child has no observation window')
    return child


def ready_for_bounded_resume(source):
    try:
        return eligible(source) or resume_candidate(source) is not None
    except (OSError, ValueError, KeyError, TypeError):
        return False


def prepare(source):
    from . import batch, unity_plan_normalization
    source = Path(source).resolve()
    if not eligible(source):
        raise ValueError('Only an unrecorded, verified partial route may gain observation windows')
    root = source.parent/(batch.read(source/'input_manifest.json')['entry']['id']+'__partial_observation_v1_'+str(time.time_ns()))
    import json
    with (source/CLAIM).open('x') as claim:
        json.dump({'child_attempt':str(root),'created_unix':time.time(),'policy':VERSION},claim)
    root.mkdir()
    copied = {}
    for item in source.iterdir():
        if item.name in {'sol_plan.json','plan_normalization.json','runtime','validation_history','background_record','recovery_source','endpoint_conditions_receipt.json','capture_route_contract.json','operation_report.md',CLAIM}:
            continue
        if item.is_dir() and item.name not in {'input','model_calls'}:
            continue
        if item.is_dir():
            shutil.copytree(item,root/item.name)
            paths = [p for p in item.rglob('*') if p.is_file()]
        else:
            shutil.copy2(item,root/item.name)
            paths = [item]
        copied.update({str(p.relative_to(source)):sha(p) for p in paths})
    dump(root/RECEIPT,{'version':VERSION,'source_attempt':str(source),
        'claim_sha256':sha(source/CLAIM),'source_bindings':{**copied,**{n:sha(source/n) for n in ('sol_plan.json','plan_normalization.json')}},
        'copied_bindings':copied,'created_unix':time.time(),'model_calls_added':0,
        'authorization':'User 2026-10-29: execute usable actual input routes despite incomplete plan; record real observation opportunities, no endpoint proof invented.',
        'scope':'Before first input only; immutable accepted source plan retained; schedule short samples within original route, no new physical actions.'})
    verify(root)
    plan=unity_plan_normalization.accept(root)
    assert plan['probes']==batch.read(source/'sol_plan.json')['probes']
    return root
