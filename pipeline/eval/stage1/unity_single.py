"""Explicit single Unity evaluation using preserved delivery and native receipts."""
from pathlib import Path
import argparse
import copy
import json
import os
import sys
import time

from . import batch, core12, endpoint_sparse, static_existence, tiered_core
from .protocol import dump, sha


def prepare_opened(output):
    candidate = batch.read(output/'opened_candidate.json')
    review = batch.read(Path(candidate['review_path']))
    selected = Path(candidate['selected_project'])
    receipt = batch.read(Path(candidate['native_open_receipt']))
    if (receipt['product_status'] != 'OPENED' or not receipt['source_unchanged']['ok']
            or sha(Path(candidate['native_open_receipt'])) != candidate['native_open_receipt_sha256']
            or batch.hashes(selected) != receipt['project_hashes']
            or not all(receipt['cleanup'].get(k) is True for k in ('input_cleanup','view_cleanup','process_cleanup'))):
        raise ValueError('Native scene-open receipt/source/cleanup changed')
    entry = copy.deepcopy(review['entry'])
    config = batch.read(output/'configuration.json')
    base = Path(config['batch'])
    from .effective import resolve_result
    if resolve_result(base,entry)['valid']:
        raise ValueError('Existing effective score protected')
    marker=selected/'ProjectSettings/ProjectVersion.txt'
    if not marker.is_file():
        marker=selected/(candidate['runtime_initializer_entry']['source'] if candidate.get('runtime_initializer_entry') else candidate['scenes'][0])
    entry.update(project=str(selected), project_marker=str(marker), marker_sha256=sha(marker),
                 planning_policy=tiered_core.VERSION,evaluation_policy=endpoint_sparse.VERSION)
    if 'asset_reservation_policy' in config:
        entry['asset_reservation_policy'] = config['asset_reservation_policy']
    entry['plan_timeout_override']={'version':'whitebox-explicit-plan-timeout.v1','seconds':1800,
        'authorization':'User instruction 2026-10-29: new Unity plan calls use an independent 1800-second budget.'}
    entry['stage_timeouts'] = {key: config.get(key+'_timeout_seconds', default) for key, default in
        [('static', 900), ('plan', 1800), ('judge', 900)]}
    entry['native_open_admission'] = {'version':candidate['admission_policy'],
        'receipt':candidate['native_open_receipt'],'sha256':candidate['native_open_receipt_sha256'],
        'original_project':receipt['source_project']}
    if candidate.get('runtime_initializer_entry'):
        entry['runtime_initializer_entry'] = candidate['runtime_initializer_entry']
    migration = Path(candidate['native_open_receipt']).parent/'input_migration.json'
    if migration.exists():
        entry['input_migration'] = {'manifest':str(migration),'sha256':sha(migration),
            'original_project':receipt['source_project'],'version':'unity-inputsystem-migration.v1',
            'user_authorized':True,'evaluation_version':'original_delivery_with_inputsystem_migration'}
    attempt = base/'recovery_runs'/(entry['id']+'__single_endpoint_v2_'+str(time.time_ns()))
    batch.prepare(base,entry,attempt)
    dump(attempt/'selection_provenance.json',candidate)
    from .route_first_capture import install_compact_policy
    install_compact_policy(attempt)
    return attempt


PHASE_OBSERVER = None

def phase(output,name,**values):
    pointer=output/'single_state.json'
    state=batch.read(pointer) if pointer.exists() else {'started_unix':time.time()}
    if name != 'HARNESS_ERROR':
        state.pop('reason', None)
    now=time.time()
    previous=state.get('phase')
    if previous and state.get('phase_started_unix'):
        durations=state.setdefault('stage_seconds',{})
        durations[previous]=durations.get(previous,0)+now-state['phase_started_unix']
    state.update(phase=name,phase_started_unix=now,updated_unix=now,pid=os.getpid(),**values)
    dump(pointer,state)
    print(json.dumps({'phase':name,**values},ensure_ascii=False),flush=True)
    if PHASE_OBSERVER is not None:PHASE_OBSERVER(name,**values)


def _main(argv=None):
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--resume', action='store_true', help='Continue saved validated stages without repeating model calls or recording')
    parser.add_argument('--editor-acceptance',type=Path)
    parser.add_argument('--retry-plan', action='store_true', help='Explicit new attempt after a preserved planner timeout')
    parser.add_argument('--plan-timeout-seconds', type=int, choices=[1800])
    parser.add_argument('--stop-after',choices=['static','plan','complete'],default='complete')
    args=parser.parse_args(argv)
    output=args.output.resolve()
    state=output/'single_state.json'
    if args.editor_acceptance:
        config=batch.read(output/'configuration.json')
        config['editor_acceptance']=str(args.editor_acceptance.resolve())
        dump(output/'configuration.json',config)
    if args.retry_plan != (args.plan_timeout_seconds is not None):
        parser.error('--retry-plan requires --plan-timeout-seconds 1800')
    if args.retry_plan and not args.resume:
        parser.error('--retry-plan requires --resume to select the preserved failed run')
    if state.exists() and not args.resume:
        raise ValueError('Preserve existing run; use --resume for saved stages')
    if args.resume and not state.exists():
        raise ValueError('No saved run to resume')
    attempt=None
    try:
        if args.resume:
            saved=batch.read(state)
            previous_pid=saved.get('pid')
            if previous_pid and previous_pid!=os.getpid():
                try: os.kill(previous_pid,0)
                except ProcessLookupError: pass
                else: raise ValueError('Saved stage process is still running')
            attempt=Path(saved['attempt'])
            batch.verify_inputs(attempt)
            config = batch.read(output/'configuration.json')
            if config.get('save_source_code_scores', False):
                from .unity_source_score_recovery import eligible, prepare as recover_source_scores
                if eligible(attempt):
                    dump(output/'state_history'/('before_source_scores_v2_'+str(time.time_ns())+'.json'), saved)
                    previous_attempt = attempt
                    attempt = recover_source_scores(attempt)
                    phase(output, 'static_recovery', attempt=str(attempt), previous_attempt=str(previous_attempt))
            from .partial_observation_recovery import ready_for_bounded_resume as partial_ready, resume_candidate, prepare as partial_prepare
            if partial_ready(attempt):
                dump(output/'state_history'/('before_partial_observation_'+str(time.time_ns())+'.json'), saved)
                previous_attempt = attempt
                attempt = resume_candidate(attempt) or partial_prepare(attempt)
                phase(output,'partial_observation_recovery',attempt=str(attempt),previous_attempt=str(previous_attempt),model_calls_added=0)
            if args.retry_plan:
                from .plan_budget_recovery import prepare
                from .route_first_capture import planning_feedback, plan_with_route_policy
                history = output/'state_history'/('before_plan1800_'+str(time.time_ns())+'.json')
                dump(history, saved)
                attempt = prepare(attempt, args.plan_timeout_seconds,
                    'User 2026-10-29: allow half an hour for Sol G005 plan; preserve failed 900-second attempt')
                phase(output,'static_reused',attempt=str(attempt),previous_attempt=saved['attempt'])
                proto = core12.verify_attempt(attempt,'unity3d')
                planning_feedback(attempt)
                phase(output,'plan',attempt=str(attempt),plan_timeout_seconds=args.plan_timeout_seconds)
                plan_with_route_policy(attempt,static_existence.MODEL,args.plan_timeout_seconds,'unity3d')
                phase(output,'plan_complete',attempt=str(attempt))
                if args.stop_after == 'plan':
                    return
            continue_stages(output,attempt,args.stop_after)
            return
        attempt=prepare_opened(output)
        continue_stages(output,attempt,args.stop_after)
    except BaseException as exc:
        phase(output,'HARNESS_ERROR',attempt=str(attempt) if attempt else None,reason=str(exc))
        raise


def continue_stages(output,attempt,stop_after='complete'):
    """Resume only unfinished stages; attempted model calls remain immutable."""
    from .unity_single_service_recovery import RECEIPT as service_receipt, verify as verify_service
    if (attempt/service_receipt).exists():
        verify_service(attempt)
    config=batch.read(output/'configuration.json')
    phase(output,'static',attempt=str(attempt))
    if config.get('save_source_code_scores',False):
        from .unity_source_review import run as source_review
        source_review(attempt,timeout=config.get('static_timeout_seconds',900))
    else:
        static_existence.run(attempt,timeout=config.get('static_timeout_seconds',900))
        from .unity_code_scores import save
        save(attempt)
    phase(output,'static_complete',attempt=str(attempt))
    if stop_after=='static':return
    return continue_plan_capture(output,attempt,stop_after)


def continue_plan_capture(output,attempt,stop_after='complete', *, capture_only=False):
    """Run the unchanged native plan/capture path after mandatory static validation."""
    config=batch.read(output/'configuration.json')
    proto=core12.verify_attempt(attempt,'unity3d')
    static_existence.load(attempt,proto)
    from .unity_execution_policy import authorize_route_metadata
    authorize_route_metadata(attempt, config)
    from .route_first_capture import planning_feedback,plan_with_route_policy
    if not (attempt/'sol_plan.json').is_file():
        from . import unity_plan_normalization
        if (attempt/'model_calls/plan').exists():
            if not unity_plan_normalization.recoverable(attempt):
                raise ValueError('Plan invocation already attempted; preserve failure and use an explicit bounded recovery identity')
            phase(output,'plan_normalization',attempt=str(attempt),model_calls_added=0)
            unity_plan_normalization.accept(attempt)
        else:
            planning_feedback(attempt)
            phase(output,'plan',attempt=str(attempt),plan_timeout_seconds=proto['runtime_budget']['plan_timeout_seconds'])
            try:
                plan_with_route_policy(attempt,static_existence.MODEL,proto['runtime_budget']['plan_timeout_seconds'],'unity3d')
            except Exception as exc:
                if not unity_plan_normalization.recoverable(attempt):
                    # Preserve transport timeouts unless a complete saved response
                    # independently proves a substantive planning-output defect.
                    review = unity_plan_normalization.assessment(attempt)
                    if review.get('substantively_invalid'):
                        raise unity_plan_normalization.InvalidSavedPlan(
                            'Saved plan cannot be deterministically normalized: '+
                            '; '.join(r['error'] for r in review['responses'])) from exc
                    raise
                phase(output,'plan_normalization',attempt=str(attempt),model_calls_added=0)
                unity_plan_normalization.accept(attempt)
    if (attempt/'plan_normalization.json').is_file():
        from .unity_plan_normalization import verify
        verify(attempt)
    batch.validate_operation_plan(attempt,batch.read(attempt/'sol_plan.json'),'unity3d')
    phase(output,'plan_complete',attempt=str(attempt))
    if stop_after=='plan':return
    return complete_capture(output,attempt,capture_only=True) if capture_only else complete_capture(output,attempt)


def _native_record_entry(attempt, plan):
    """Map an admitted natural entry to the recorder source identifier."""
    entry = batch.read(attempt/'input_manifest.json')['entry']
    if not entry.get('runtime_initializer_entry'):
        return plan['launch_scene'], [], {}
    if plan['launch_scene'] != '':
        raise ValueError('Natural runtime entry plan must retain its empty launch scene')
    from engine_adapters.unity3d.playtest import runtime_initializer
    path = attempt/'runtime_initializer_record_entry.json'
    binding = runtime_initializer.write(attempt, path)
    runtime_initializer.load(path, Path(entry['project']))
    return binding['source'], ['--runtime-entry', str(path)], {
        'runtime_initializer_entry_sha256':sha(path)}


def complete_capture(output,attempt, *, capture_only=False, process_receipt_directory=None):
    from . import runtime, integrity
    from .route_first_capture import capture_route
    from engine_adapters.unity3d.playtest import native_acceptance
    from .unity_record_process import run as run_record_process
    config=batch.read(output/'configuration.json')
    acceptance_path=Path(config['editor_acceptance']).resolve()
    acceptance=batch.read(acceptance_path)
    adapter=Path(config['adapter_root']).resolve()
    editor=Path(acceptance['editor'])
    native_acceptance.verify(acceptance_path,adapter,editor)
    proto=core12.verify_attempt(attempt,'unity3d')
    plan=batch.read(attempt/'sol_plan.json')
    batch.validate_operation_plan(attempt,plan,'unity3d')
    actions=runtime.native_actions(plan)
    schedule,actual,diagnostic=capture_route(proto,plan,actions,root=attempt)
    if diagnostic or actual!=actions:
        raise ValueError('Diagnostic-only plan cannot be published as gameplay evaluation')
    gate=batch.validate_capture_plan(attempt,plan=plan)
    if not gate['valid']:raise ValueError(gate)
    capture=attempt/'background_record'
    if not capture.exists():
        phase(output,'capture',attempt=str(attempt))
        dump(attempt/'capture_schedule.json',schedule)
        dump(attempt/'native_actions.json',{'actions':actual})
        binding={'schema':'unity-single-recorder-binding.v1','acceptance':str(acceptance_path),
            'acceptance_sha256':sha(acceptance_path),'plan_sha256':sha(attempt/'sol_plan.json'),
            'actions_sha256':sha(attempt/'native_actions.json'),'schedule_sha256':sha(attempt/'capture_schedule.json'),
            'adapter_root':str(adapter),'editor':str(editor)}
        observer_args=[]
        if (attempt/'functional_observer_contract.json').is_file():
            from .unity_observer_recovery import audit_binding
            if not audit_binding(attempt):raise ValueError('Observer contract requires explicit source-bound recovery')
            observer_args=['--observer-contract',str(attempt/'functional_observer_contract.json')]
            binding['observer_contract_sha256']=sha(attempt/'functional_observer_contract.json')
        scene, entry_args, entry_binding = _native_record_entry(attempt, plan)
        observer_args += entry_args
        binding.update(entry_binding)
        process_output = attempt/'native_record_process'
        if process_receipt_directory is not None:
            process_output = Path(process_receipt_directory).resolve()
            if (process_output.parent != attempt.resolve()
                    or not process_output.name.startswith('native_record_process__')
                    or process_output.exists()):
                raise ValueError('Recovery process receipts require a new direct attempt child')
        dump(attempt/'recorder_acceptance_binding.json',binding)
        old_control=os.environ.get('GAMEFACTORY_UNITY_CONTROL_ROOT')
        os.environ['GAMEFACTORY_UNITY_CONTROL_ROOT']=str(Path(config['control_root']).resolve())
        try:
            source_project=Path(batch.read(attempt/'input_manifest.json')['entry']['project'])
            override=output/'native_project_override.json'
            if override.is_file():
                from .unity_m_input_adapter import verify as verify_input
                source_project=verify_input(attempt, output, acceptance_path)
            code=run_record_process(config,['record','--output',str(capture),
                '--adapter-root',str(adapter),'--adapter-pin',str(acceptance_path.parent/'candidate_pin.json'),
                '--control-root',config['control_root'],'--unity',str(editor),
                '--project',str(source_project),
                '--scene',scene,'--duration',str(proto['runtime_budget']['recording_ms']/1000),
                '--actions',str(attempt/'native_actions.json'),'--capture-schedule',str(attempt/'capture_schedule.json')]+observer_args,
                    process_output,framework_root=Path(batch.__file__).resolve().parents[3])
        finally:
            if old_control is None: os.environ.pop('GAMEFACTORY_UNITY_CONTROL_ROOT',None)
            else: os.environ['GAMEFACTORY_UNITY_CONTROL_ROOT']=old_control
        # A native nonzero exit caused solely by permitted foreground presence
        # is qualified below against unchanged raw verification and cleanup.
        if code not in (0, 1):
            raise RuntimeError('Native capture failed; preserve attempt and cleanup receipts')
    verification=batch.read(capture/'verification.json')
    cleanup=batch.read(capture/'runner_exit.json')
    from .unity_capture_policy import qualify
    qualify(attempt)
    safety=check_cleanup(config,capture)
    dump(output/'post_capture_cleanup.json',safety)
    if capture_only:
        phase(output,'CAPTURE_QUALIFIED',attempt=str(attempt),cleanup=safety)
        return {'attempt':str(attempt),'cleanup':safety}
    phase(output,'evidence',attempt=str(attempt))
    pointer=attempt/'active_background_judge_attempt.json'
    if pointer.exists():
        judged=Path(batch.read(pointer)['attempt'])
    else:
        from .recorded_import_review import create_import_review
        from .prepare_unity_recorded_judge import prepare
        create_import_review(attempt)
        judged=prepare(attempt)
    from . import static_judge_recovery
    if static_judge_recovery.eligible(judged):
        previous_judged = judged
        judged = static_judge_recovery.prepare(judged)
        dump(pointer, {'attempt':str(judged),'previous_attempt':str(previous_judged),
            'phase':'static_partition_recovery','at':time.time()})
    # Bind the independent acceptance and actual cleanup, alongside unchanged raw evidence.
    import shutil
    shutil.copy2(attempt/'recorder_acceptance_binding.json',judged/'recorder_acceptance_binding.json')
    dump(judged/'runtime/native_cleanup.json',{key:verification['checks'][key] for key in
        ('input_cleanup','view_cleanup','process_cleanup')})
    manifest=batch.read(judged/'evidence_manifest.json')
    for name in ('static_code_scores.json','static_source_scores.json'):
        source=attempt/name
        if source.is_file():
            destination=judged/'recovery_source'/name
            destination.parent.mkdir(parents=True,exist_ok=True)
            if not destination.exists():shutil.copy2(source,destination)
            if sha(destination)!=sha(source):raise ValueError('Saved source scores changed')
            ident='INITIAL_SOURCE_SCORES:'+name
            if not any(row['id']==ident for row in manifest['items']):
                manifest['items'].append({'id':ident,'path':str(destination.relative_to(judged)),
                    'type':'document','sha256':sha(destination)})
    for ident,relative in [('RECORDER_ACCEPTANCE_BINDING','recorder_acceptance_binding.json'),
                           ('NATIVE_CLEANUP','runtime/native_cleanup.json')]:
        if not any(row['id']==ident for row in manifest['items']):
            manifest['items'].append({'id':ident,'path':relative,'type':'document','sha256':sha(judged/relative)})
    dump(judged/'evidence_manifest.json',manifest)
    phase(output,'judge',attempt=str(attempt),judge_attempt=str(judged))
    if not (judged/'scores.json').exists():
        frozen_entry=batch.read(attempt/'input_manifest.json')['entry']
        from .unity_stage_timeouts import resolve
        judge_timeout=resolve(frozen_entry,proto,'judge',config)
        batch.judge(judged,static_existence.MODEL,judge_timeout)
    from .pending_publication import deferred, publish as publish_pending
    if deferred(config):
        phase(output,'pending_publication',attempt=str(attempt),judge_attempt=str(judged))
        result=publish_pending(judged)
        safety=check_cleanup(config,capture)
        dump(output/'final_cleanup.json',safety)
        phase(output,'SCORED_PENDING_AUDIT',attempt=str(attempt),judge_attempt=str(judged),
              score=result['score'],valid=False,provisional=True,audit_status='PENDING',cleanup=safety)
        return
    phase(output,'audit',attempt=str(attempt),judge_attempt=str(judged))
    native_acceptance.verify(acceptance_path,adapter,editor)
    audit=integrity.audit_run(judged)
    dump(judged/'independent_audit.json',audit)
    if not audit['valid']:raise ValueError('Independent audit failed; no publication')
    phase(output,'publication',attempt=str(attempt),judge_attempt=str(judged))
    receipt=judged/'formal_publication_receipt.json'
    if not receipt.exists():
        from .targeted_publication import main as publish
        publish(['--attempt',str(judged)])
    from .effective import resolve_result
    effective=resolve_result(Path(config['batch']),batch.read(judged/'input_manifest.json')['entry'])
    if not effective['valid'] or effective['root'].resolve()!=judged.resolve():
        raise ValueError('Effective source does not select audited published attempt')
    safety=check_cleanup(config,capture)
    dump(output/'final_cleanup.json',safety)
    score=batch.read(judged/'scores.json')
    phase(output,'COMPLETE',attempt=str(attempt),judge_attempt=str(judged),
          score=score['overall_score'],valid=score['valid'],cleanup=safety)


def check_cleanup(config,capture):
    from .unity_cleanup_policy import report_only
    if report_only(config):
        from .unity_safety import check
        return check(config, capture)
    import fcntl
    from engine_adapters.unity3d.playtest.background_record import control_paths
    from . import runtime
    control=Path(config['control_root'])
    if (control/'background_record_cleanup_block.json').exists():
        raise ValueError('Cleanup stop marker exists')
    if runtime.active_gui_engines():raise ValueError('Unity or another GUI engine remains active')
    handles=[]
    try:
        for path in control_paths(control):
            handle=path.open('a+')
            handles.append(handle)
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
    finally:
        for handle in handles:handle.close()
    verification=batch.read(capture/'verification.json')
    receipt=batch.read(capture/'runner_exit.json')
    keys=('input_cleanup','view_cleanup','process_cleanup')
    if (not receipt.get('cleanup_verified') or receipt.get('policy_violations')
            or not all(verification['checks'].get(k) is True for k in keys)):
        raise ValueError('Input/view/process cleanup is uncertain')
    return {'five_locks_free':True,'stop_marker_absent':True,'active_gui_engines':[],
        **{k:True for k in keys},'verification_sha256':sha(capture/'verification.json'),
        'runner_exit_sha256':sha(capture/'runner_exit.json'),'checked_unix':time.time()}


def main(argv=None):
    # The queue owns this lease through admission, model stages and recording.
    # Direct single-case resumes join the same lease before touching their state.
    if PHASE_OBSERVER is not None:
        return _main(argv)
    import fcntl
    arguments=list(sys.argv[1:] if argv is None else argv)
    if '--output' not in arguments:return _main(arguments)
    output=Path(arguments[arguments.index('--output')+1]).resolve()
    config=batch.read(output/'configuration.json')
    control=Path(config['control_root']);control.mkdir(parents=True,exist_ok=True)
    waiter = control/'production_lease_waiters'/(str(os.getpid())+'.json')
    dump(waiter, {'version': 'whitebox-production-lease-waiter.v1', 'pid': os.getpid(),
        'output': str(output), 'status': 'WAITING', 'started_unix': time.time()})
    with (control/'whitebox_production_queue.lock').open('a+') as handle:
        while True:
            try:
                fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
                break
            except BlockingIOError:
                print('Waiting for shared Unity production serial lease',flush=True)
                time.sleep(15)
        dump(waiter, {**batch.read(waiter), 'status': 'ACQUIRED', 'acquired_unix': time.time()})
        return _main(arguments)


if __name__=='__main__':main()
