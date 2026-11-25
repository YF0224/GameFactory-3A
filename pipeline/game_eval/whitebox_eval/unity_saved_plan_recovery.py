"""One explicit resume of a saved plan after deterministic wire/tool compatibility repair."""
import os
import time
from pathlib import Path

from . import batch, unity_plan_normalization as normalization, unity_queue, unity_safety, unity_single
from .protocol import dump, sha

VERSION = 'whitebox-saved-plan-resume.v1'


def qualify_pre_capture_resume(source, output):
    """Allow one continuation of the same claim after the first-capture gate repair."""
    previous = batch.read(output/'recovery_state.json')
    if (previous.get('phase') != 'FAILED'
            or previous.get('source_attempt') != str(source)
            or 'independent_publication_audit.json' not in previous.get('reason', '')
            or (source/'background_record').exists()
            or not (source/'sol_plan.json').is_file()
            or (output/'pre_capture_resume.json').exists()):
        raise ValueError('Saved-plan recovery output already exists; inspect saved worker')
    try:
        os.kill(previous['pid'], 0)
    except ProcessLookupError:
        pass
    else:
        raise ValueError('Previous saved-plan recovery process is still alive')
    claim = batch.read(source/'saved_plan_resume.json')
    if (claim.get('version') != VERSION or claim.get('output') != str(output)
            or claim.get('source_manifest_sha256') != sha(source/'input_manifest.json')
            or claim.get('plan_response_sha256') != sha(source/'model_calls/plan/response.json')
            or claim.get('new_plan_calls') != 0):
        raise ValueError('Pre-capture continuation changed its original recovery claim')
    normalization.verify(source)
    gate = batch.validate_capture_plan(source, plan=batch.read(source/'sol_plan.json'))
    if not gate['valid']:
        raise ValueError('Pre-capture continuation still fails validation: '+str(gate))
    return previous


def run(source, config, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    state_path = output/'recovery_state.json'
    resuming = state_path.exists()
    previous = qualify_pre_capture_resume(source, output) if resuming else None
    def state(phase, **extra):
        dump(state_path, {'version':VERSION,'phase':phase,'pid':os.getpid(),
             'updated_unix':time.time(),'source_attempt':str(source),**extra})
    ident = batch.read(source/'input_manifest.json')['entry']['id']
    if (source/'background_record').exists() or ((source/'sol_plan.json').exists() and not resuming):
        raise ValueError('Saved-plan resume requires preserved failed planning without capture')
    if unity_queue.published(config['batch'],ident):
        state('SKIP_SCORED'); return
    qualification = ({'recoverable':True, 'accepted_plan_sha256':sha(source/'sol_plan.json'),
                      'mode':'same_claim_pre_capture_continuation', 'model_calls_added':0}
                     if resuming else normalization.assessment(source))
    if not qualification['recoverable']:
        raise ValueError('Saved response fails actual operation validation: '+str(qualification))
    if resuming:
        dump(output/'state_history/pre_capture_failure.json',previous)
        dump(output/'pre_capture_resume.json',{'previous_state':previous,
            'plan_sha256':sha(source/'sol_plan.json'),'model_calls_added':0,
            'original_claim_unchanged':True,'maximum_continuations':1,'created_unix':time.time()})
    else:
        dump(output/'qualification.json',qualification)
    state('WAITING_SERIAL_LEASE')
    with unity_queue.coordinator(config, lambda:state('WAITING_SERIAL_LEASE')):
        try:
            unity_safety.check(config)
            queue_state=Path(config['queue_output'])/'queue_state.json'
            if queue_state.is_file() and batch.read(queue_state).get('status') in {
                    'STOPPED_ENVIRONMENT_FAILURES','STOPPED_CLEANUP_UNCERTAIN','STOPPED_ACCEPTANCE'}:
                state('BLOCKED_QUEUE_STOP',reason='Preserve queue safety/environment stop');return
            if unity_queue.published(config['batch'],ident):
                state('SKIP_SCORED');return
            unity_queue.verify_acceptance(config)
            claim=source/'saved_plan_resume.json'
            if resuming:
                normalization.verify(source)
                gate = batch.validate_capture_plan(source, plan=batch.read(source/'sol_plan.json'))
                if (source/'background_record').exists() or not gate['valid']:
                    raise ValueError('Pre-capture continuation changed while waiting')
            else:
                if claim.exists():
                    raise ValueError('One saved-plan recovery already claimed; inspect its existing output')
                # Qualification is repeated after acquiring the full-flow lease.
                if not normalization.recoverable(source):
                    raise ValueError('Saved plan qualification changed while waiting')
                dump(claim,{'version':VERSION,'output':str(output),'authorization':
                    'User 2026-10-29: 能忽略这个sha256么，直接跑么',
                    'source_manifest_sha256':sha(source/'input_manifest.json'),
                    'plan_response_sha256':sha(source/'model_calls/plan/response.json'),
                    'new_plan_calls':0,'actions_and_frozen_identity_unchanged':True})
            dump(output/'configuration.json',config)
            state('EVALUATING',attempt=str(source))
            unity_single.continue_stages(output,source)
            state('COMPLETE',attempt=str(source),result=batch.read(output/'single_state.json'))
        except BaseException as exc:
            state('FAILED',attempt=str(source),reason=str(exc));raise
        finally:
            if (source/'background_record').exists():
                unity_safety.capture_cleanup(source/'background_record')
            dump(output/'cleanup_check.json',unity_safety.check(config))
