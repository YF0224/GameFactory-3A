"""Exact continuation of the failed-before-input Unity M protocol lookup.

No native/model call, claim removal or new attempt identity. Every prior
failure byte is archived and bound before preparation can advance.
"""
from pathlib import Path
from . import batch
from .protocol import sha


def qualify(recorded, repair):
    recorded=Path(recorded)
    failure=Path(repair['parent_failure'])
    if sha(failure)!=repair['parent_failure_sha256']:
        raise ValueError('Protocol preparation parent failure changed')
    expected="[Errno 2] No such file or directory: '"+str(recorded.parent.parent/'protocol_lock.json')+"'"
    if batch.read(failure)['error']!=expected:
        raise ValueError('Exact pre-input protocol lookup failure required')
    attempt=Path(repair['partial_attempt']);stamp=attempt.name.removeprefix(recorded.name+'__recorded_judge_v1_')
    if (attempt.parent!=recorded.parent.parent/'recovery_runs' or not stamp.isdecimal()
            or (attempt/'input').exists() or (attempt/'runtime').exists()):
        raise ValueError('Continuation must be the unchanged pre-input attempt')
    prior=batch.read(attempt/'harness_error.json')
    if prior['reason']!=expected or prior['phase']!='prepare':
        raise ValueError('Wrong preparation failure')
    archive=Path(repair['attempt_archive'])
    if batch.hashes(attempt)!=batch.hashes(archive) or batch.hashes(attempt)!=repair['partial_hashes']:
        raise ValueError('Exact failed attempt archive required')
    derived=recorded/'derived_judge_sources'/(recorded.name+'__recorded_urp_'+stamp)
    if batch.hashes(derived)!=repair['derived_hashes']:
        raise ValueError('Preserved imported source differs')
    version=batch.read(derived.with_suffix('.json'))
    if version['version_project']!=str(derived):
        raise ValueError('Preserved imported source identity differs')
    return dict(stamp=stamp,partial_attempt=str(attempt),partial_hashes=repair['partial_hashes'],
                archive=str(archive),derived_hashes=repair['derived_hashes'])


def resume_prepare(recorded, attempt, source_base, entry, receipt):
    if str(attempt)!=receipt['partial_attempt'] or batch.hashes(attempt)!=receipt['partial_hashes']:
        raise ValueError('Failed preparation advanced during continuation')
    if batch.hashes(Path(entry['project']))!=receipt['derived_hashes']:
        raise ValueError('Preserved derived source changed during continuation')
    batch.verify_protocol(source_base,entry)
    # This is the existing formal preparation routine after its exact earlier
    # protocol-lookup failure. Original creation/budget/lineage stay retained.
    batch._prepare(source_base,entry,attempt,prefer_explicit_endpoint_conditions=True)
    batch.verify_inputs(attempt)


def repair_prepared_budget(recorded, repair):
    from .protocol import dump
    from .mechanic_v3_runner import exclusive_json
    recorded=Path(recorded);attempt=Path(repair['partial_attempt'])
    failure=Path(repair['parent_failure'])
    if (sha(failure)!=repair['parent_failure_sha256'] or batch.read(failure)['error']!=
            'Recorded core12 contract/budget changed while preparing judge: pilot_rubric.json'):
        raise ValueError('Exact prepared budget handoff failure required')
    if (attempt.parent!=recorded.parent.parent/'recovery_runs' or
            not attempt.name.startswith(recorded.name+'__recorded_judge_v1_')):
        raise ValueError('Exact original derived attempt required')
    batch.verify_inputs(attempt)
    for name in ('sol_plan.json','model_calls','judgments','evidence_manifest.json'):
        if (attempt/name).exists():raise ValueError('Prepared budget recovery must precede plan/model/evidence')
    original=batch.read(recorded/'input/pilot_rubric.json');prior=batch.read(attempt/'input/pilot_rubric.json')
    if {k:v for k,v in original.items() if k!='runtime_budget'}!={k:v for k,v in prior.items() if k!='runtime_budget'}:
        raise ValueError('Prepared protocol differs beyond inherited budget')
    archive=Path(repair['attempt_archive'])
    paths=('input/pilot_rubric.json','input_manifest.json','attempt_manifest.json')
    if any(sha(attempt/n)!=sha(archive/n) for n in paths):
        raise ValueError('Exact preparation archive differs')
    claim=attempt/'unity_m_prepared_budget_claim.json'
    exclusive_json(claim,dict(parent_failure=str(failure),parent_failure_sha256=sha(failure),
        before={n:sha(attempt/n) for n in paths},archive=str(archive),original_protocol_sha256=sha(recorded/'input/pilot_rubric.json')))
    # Preserve the precise original recording budget, never a newly enlarged one.
    (attempt/'input/pilot_rubric.json').write_bytes((recorded/'input/pilot_rubric.json').read_bytes())
    creation=batch.read(attempt/'attempt_manifest.json');creation['budget']=original['runtime_budget']
    dump(attempt/'attempt_manifest.json',creation)
    manifest=batch.read(attempt/'input_manifest.json');manifest['input_hashes']=batch.hashes(attempt/'input');manifest['protocol_sha256']=sha(attempt/'input/pilot_rubric.json')
    dump(attempt/'input_manifest.json',manifest)
    exclusive_json(attempt/'unity_m_prepared_budget_receipt.json',dict(recorded=str(recorded),
        before_claim_sha256=sha(claim),after={n:sha(attempt/n) for n in paths},
        original_protocol_sha256=sha(recorded/'input/pilot_rubric.json'),new_native_or_model_calls=0))
    verify_prepared_receipt(recorded,attempt)
    return attempt


def verify_prepared_receipt(recorded,attempt):
    receipt=batch.read(attempt/'unity_m_prepared_budget_receipt.json')
    if receipt['recorded']!=str(recorded) or receipt['original_protocol_sha256']!=sha(recorded/'input/pilot_rubric.json'):
        raise ValueError('Prepared original protocol changed')
    if sha(attempt/'unity_m_prepared_budget_claim.json')!=receipt['before_claim_sha256']:
        raise ValueError('Prepared budget recovery claim changed')
    for name,digest in receipt['after'].items():
        if sha(attempt/name)!=digest:raise ValueError('Prepared budget recovery output changed: '+name)
