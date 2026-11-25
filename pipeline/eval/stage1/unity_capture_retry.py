"""Explicit, once-only capture retry after user-reported foreground interference."""
from pathlib import Path
import shutil
import time

from . import batch, core12, static_existence, unity_safety, unity_source_review
from .protocol import dump, sha

RECEIPT = 'foreground_capture_retry.json'
AUTHORIZATION = 'User 2026-10-29: 那个glm39录制有问题，我之前不小心切换后台了，可以冲跑录制开始judge'
AUTHORIZED_CASE = 'GLM__G039_sky_ring_flight'


def qualify(source, root):
    from .unity_queue import published
    source = Path(source).resolve()
    batch.verify_inputs(source)
    ident = batch.read(source/'input_manifest.json')['entry']['id']
    if ident != AUTHORIZED_CASE or published(root, ident):
        raise ValueError('Foreground retry requires explicit unscored G039 authorization')
    checks = batch.read(source/'background_record/verification.json')['checks']
    if {k for k,v in checks.items() if v is not True} != {'no_owned_foreground_sample'}:
        raise ValueError('Only the foreground-interference failure is authorized')
    unity_safety.capture_cleanup(source/'background_record')
    protocol = core12.verify_attempt(source, 'unity3d')
    static_existence.load(source, protocol)
    unity_source_review.load(source)
    batch.validate_operation_plan(source, batch.read(source/'sol_plan.json'), 'unity3d', record_validation=False)
    if (source/RECEIPT).exists():
        raise ValueError('One foreground capture retry already used')
    return ident


def prepare(source, root):
    source = Path(source).resolve()
    ident = qualify(source, root)
    for path in source.parent.glob(ident+'__foreground_retry_v1_*/'+RECEIPT):
        if batch.read(path)['source_attempt'] == str(source):
            verify(path.parent)
            return path.parent
    dest = source.parent/(ident+'__foreground_retry_v1_'+str(time.time_ns()))
    dest.mkdir()
    shutil.copytree(source/'input', dest/'input')
    copied = []
    # All frozen planning transformations and original calls remain byte-for-byte;
    # no capture/runtime files, old frame links or model-generated replacement plan.
    excluded = {'status.json','attempt_manifest.json','capture_schedule.json',
        'native_actions.json','recorder_acceptance_binding.json'}
    for p in source.iterdir():
        if p.is_file() and p.name not in excluded:
            shutil.copy2(p, dest/p.name)
            copied.append(p.name)
    shutil.copytree(source/'model_calls', dest/'model_calls')
    copied.extend(str(p.relative_to(source)) for p in (source/'model_calls').rglob('*') if p.is_file())
    manifest = batch.read(source/'attempt_manifest.json')
    manifest.update(attempt_id=dest.name, previous_attempt=str(source))
    dump(dest/'attempt_manifest.json', manifest)
    dump(dest/RECEIPT, {'version':'whitebox-foreground-capture-retry.v1',
        'source_attempt':str(source), 'authorization':AUTHORIZATION, 'maximum_retries':1,
        'model_calls_added_before_capture':0, 'copied_bindings':{n:sha(source/n) for n in copied},
        'failed_capture_bindings':{n:sha(source/'background_record'/n) for n in ('verification.json','runner_exit.json')},
        'created_unix':time.time()})
    verify(dest)
    return dest


def verify(dest):
    dest = Path(dest)
    receipt = batch.read(dest/RECEIPT)
    source = Path(receipt['source_attempt'])
    if (receipt.get('version') != 'whitebox-foreground-capture-retry.v1'
            or receipt['authorization'] != AUTHORIZATION or receipt['maximum_retries'] != 1
            or receipt.get('model_calls_added_before_capture') != 0
            or source == dest or source.parent != dest.parent
            or (source/RECEIPT).exists()):
        raise ValueError('Invalid foreground retry lineage')
    for folder in (source,dest):
        batch.verify_inputs(folder)
    if core12.verify_attempt(source,'unity3d') != core12.verify_attempt(dest,'unity3d'):
        raise ValueError('Foreground retry changed frozen protocol')
    for name,digest in receipt['copied_bindings'].items():
        if Path(name).is_absolute() or '..' in Path(name).parts:
            raise ValueError('Unsafe retry binding')
        if sha(source/name) != digest or sha(dest/name) != digest:
            raise ValueError('Foreground retry changed saved static/plan evidence: '+name)
    for name,digest in receipt['failed_capture_bindings'].items():
        if sha(source/'background_record'/name) != digest:
            raise ValueError('Original failed capture receipt changed')
    static_existence.load(dest,core12.verify_attempt(dest,'unity3d'))
    unity_source_review.load(dest)
    batch.validate_operation_plan(dest,batch.read(dest/'sol_plan.json'),'unity3d',record_validation=False)
    return True


def audit_binding(root):
    """Audit the saved retry lineage, also from a derived judge package.

    Publication must remain auditable after a score exists, so this verifies
    the immutable lineage rather than re-running admission's unscored check.
    """
    root = Path(root).resolve()
    provenance = root/'recorded_capture_provenance.json'
    recorded = Path(batch.read(provenance)['source_attempt']).resolve() if provenance.is_file() else root
    receipt_path = recorded/RECEIPT
    if not receipt_path.is_file():
        return {}
    verify(recorded)
    receipt = batch.read(receipt_path)
    source = Path(receipt['source_attempt']).resolve()
    if batch.read(recorded/'input_manifest.json')['entry']['id'] != AUTHORIZED_CASE:
        raise ValueError('Foreground retry case changed')
    checks = batch.read(source/'background_record/verification.json')['checks']
    if {key for key, value in checks.items() if value is not True} != {'no_owned_foreground_sample'}:
        raise ValueError('Original retry capture failed beyond foreground presence')
    unity_safety.capture_cleanup(source/'background_record')
    files = [receipt_path]
    files.extend(source/name for name in receipt['copied_bindings'])
    files.extend(recorded/name for name in receipt['copied_bindings'])
    files.extend(source/'background_record'/name for name in receipt['failed_capture_bindings'])
    return {str(path):sha(path) for path in files}


def authorize(output, config, state, ident):
    """Run while holding the production coordinator; idempotent before recording."""
    output = Path(output)
    if ident != AUTHORIZED_CASE:
        raise ValueError('Only explicitly authorized G039 foreground retry is allowed')
    case = state['cases'][ident]
    if case.get('foreground_retry_count'):
        raise ValueError('Foreground retry already scheduled; use ordinary resume')
    if case.get('status') != 'BOUNDED_FAILURE':
        raise ValueError('Foreground retry requires the preserved failed case')
    unity_safety.check(config)
    single = output/'cases'/ident/'single_state.json'
    saved = batch.read(single)
    if saved['attempt'] != case['recorded_attempt']:
        raise ValueError('Capture retry pointer changed')
    source = Path(saved['attempt'])
    dest = prepare(source, Path(config['batch']))
    dump(single.parent/'state_history'/('before_foreground_retry_'+str(time.time_ns())+'.json'),saved)
    dump(single, {'attempt':str(dest),'phase':'foreground_retry_prepared','previous_attempt':str(source),
        'started_unix':time.time()})
    case.setdefault('failure_history',[]).append({k:v for k,v in case.items() if k not in ('entry','failure_history')})
    case.update(status='PENDING',foreground_retry_count=1,recorded_attempt=str(dest),
        recovery_reason=AUTHORIZATION)
