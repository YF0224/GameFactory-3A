"""Bounded G005 capture recovery: native reacceptance and unchanged saved plan."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from . import batch, core12, unity_single, runtime
from .protocol import dump, sha


def reconcile_interrupted_cleanup(output, source, config):
    """Reconcile process-local resources after verified isolated Editor death.

    Original failed cleanup receipts remain unchanged and never certify capture.
    No persistent Unity setting or OS input is modified by this reconciliation.
    """
    from engine_adapters.unity3d.playtest.background_record import control_paths, check_original
    capture=source/'background_record';control=Path(config['control_root'])
    marker=control/'background_record_cleanup_block.json'
    if not marker.exists():
        return None
    block=batch.read(marker);exit=batch.read(capture/'runner_exit.json')
    cleanup=batch.read(capture/'take/editor_cleanup.json');session=batch.read(capture/'background_session.json')
    settings_path=capture/'take/background_input_settings.json'
    settings=batch.read(settings_path) if settings_path.exists() else None
    if settings is None:
        # A cancelled import may exit before the runtime creates any resources.
        # Refuse this path if readiness, real input or gameplay evidence exists.
        absent=('play_started.json','actions.jsonl','frame_index.jsonl','state_trace.jsonl','event_trace.jsonl')
        if any((capture/'take'/name).exists() for name in absent):
            raise ValueError('Missing input settings after runtime evidence appeared')
    if block.get('output')!=str(capture) or block.get('runner_pid')!=session['pid']:
        raise ValueError('Cleanup marker belongs to another capture')
    if session['capture_policy']!='graphics_batch_render_v2' or session['activation']!='forbidden' or session['os_input']!='forbidden' or exit['policy_violations']:
        raise ValueError('Process-local reconciliation requires enforced zero OS input')
    if settings is not None and settings['scope']!='owned Editor process only; no settings asset saved':
        raise ValueError('Input settings were not process local')
    if not all(cleanup.get(k) is True for k in ['ok','process_exit_verified','group_exit_verified','detached_exit_verified']) or cleanup['errors']:
        raise ValueError('Owned Editor termination is unconfirmed')
    for pid in [session['pid']]+[row['pid'] for row in exit['launches']]:
        try:os.kill(pid,0)
        except ProcessLookupError:pass
        else:raise ValueError('An owned process remains alive')
    if runtime.active_gui_engines():raise ValueError('A GUI engine remains alive')
    if not check_original(batch.read(capture/'source_snapshot.json'))['ok']:raise ValueError('Frozen source changed')
    # Recorder custom GameView sizes and RenderTextures are transient. Refuse
    # reconciliation if any persisted Unity preference contains our owned size.
    prefs=Path.home()/'Library/Preferences/Unity'
    pref_hashes={}
    for path in prefs.rglob('*'):
        if path.is_file():
            data=path.read_bytes()
            if b'GameFactory owned capture' in data:raise ValueError('Owned capture view persisted in Unity preferences')
            pref_hashes[str(path)]=sha(path)
    handles=[]
    try:
        for path in control_paths(control):
            handle=path.open('a+');handles.append(handle);fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        stamp=str(time.time_ns());dest=output/'cleanup_recovery'/stamp
        dest.mkdir(parents=True)
        shutil.copy2(marker,dest/marker.name)
        receipt={'version':'unity-isolated-process-cleanup-reconciliation.v1','failed_capture':str(capture),
            'checked_unix':time.time(),'editor_cleanup_sha256':sha(capture/'take/editor_cleanup.json'),
            'failed_runner_exit_sha256':sha(capture/'runner_exit.json'),'marker_sha256':sha(marker),
            'input_settings_sha256':sha(settings_path) if settings is not None else None,
            'cancelled_before_runtime_ready':settings is None,
            'five_locks_free':True,'owned_processes_absent':True,'original_source_unchanged':True,
            'persisted_unity_preferences_sha256':pref_hashes,'owned_view_preference_absent':True,
            'resolution':'All virtual input devices, filters, in-memory settings, views and render targets belonged to the terminated isolated Editor. No OS input was sent. No owned view persisted. Failed capture and missing teardown reports remain invalid.',
            'capture_accepted':False,'original_cleanup_receipts_rewritten':False}
        dump(dest/'reconciliation.json',receipt)
        if sha(marker)!=receipt['marker_sha256']:raise ValueError('Cleanup marker changed concurrently')
        marker.unlink()
        return dest/'reconciliation.json'
    finally:
        for handle in reversed(handles):handle.close()


def make_fixtures(output, config, old_acceptance):
    from engine_adapters.unity3d.playtest import background_record as rec
    from engine_adapters.unity3d.playtest import input_axis_serialization as axis
    import re,yaml
    target=output/('axis_native_fixtures_'+str(time.time_ns()))
    for duration in (20,180):
        original=old_acceptance.parent/f'fixture_{duration}s';dest=target/f'fixture_{duration}s'
        snap=rec.snapshot_project(original/'project',dest/'project',Path(config['control_root']),fixture=True)
        settings=dest/'project'/axis.SETTINGS
        text='\n'.join(line for line in settings.read_text().splitlines() if not line.startswith('%'))
        rows=yaml.safe_load(re.sub(r'--- !u!\d+ &\d+','---',text))['InputManager']['m_Axes']
        resource=dest/'project'/axis.RESOURCE
        resource.write_text(json.dumps({'axes':rows},ensure_ascii=False,indent=2)+'\n')
        shutil.copy2(original/'actions_input.json',dest/'actions_input.json')
        if (original/'take/capture_schedule.json').is_file():
            (dest/'take').mkdir();shutil.copy2(original/'take/capture_schedule.json',dest/'take/capture_schedule.json')
        dump(dest/'fixture_derivation.json',{'source_snapshot':snap,'generated_resource_test_input':axis.projection(dest/'project')[1],
            'purpose':'Exercise exact authored YAML m_Name to runtime name correction in real native fixture; gameplay and actions unchanged.'})
    return target


def recover_attempt(source, acceptance, reconciliation):
    from .unity_plan_normalization import verify
    verify(source);batch.verify_inputs(source);core12.verify_attempt(source,'unity3d')
    if not (source/'background_record/error.json').is_file() or (source/'scores.json').exists():raise ValueError('Only failed harness capture can be recovered')
    root=source.parent/('Sol__G005_broken_realm_echo__axis_snapshot_v1_'+str(time.time_ns()))
    preserved=['input','input_manifest.json','attempt_manifest.json','model_calls','sol_plan.json','plan_normalization.json',
        'static_existence.json','static_code_scores.json','lean_plan_recovery.json','capture_route_contract.json',
        'planning_prompt_policy.json','planning_prompt_template.py','planning_prompt_transform.json','planning_retry_feedback.json',
        'unsupported_input_policy.json','route_metadata_repair.json','endpoint_conditions_receipt.json']
    root.mkdir()
    for name in preserved:
        path=source/name
        if path.is_dir():shutil.copytree(path,root/name)
        elif path.is_file():shutil.copy2(path,root/name)
    bindings={str(p.relative_to(source)):sha(p) for name in preserved for p in
              ((source/name).rglob('*') if (source/name).is_dir() else [source/name]) if p.is_file()}
    dump(root/'input_axis_capture_recovery.json',{'version':'unity-axis-capture-recovery.v1','source_attempt':str(source),
        'reason':'Generated input axis resource used YAML m_Name but accepted runtime Axis declares name; failed harness capture invalidated.',
        'copied_files_sha256':bindings,'editor_acceptance':str(acceptance),'editor_acceptance_sha256':sha(acceptance),
        'cleanup_reconciliation':str(reconciliation) if reconciliation else None,
        'cleanup_reconciliation_sha256':sha(reconciliation) if reconciliation else None,
        'plan_model_calls_added':0,'physical_actions_changed':False,'frozen_source_changed':False,'created_unix':time.time()})
    verify(root);batch.verify_inputs(root);core12.verify_attempt(root,'unity3d')
    return root


def main():
    p=argparse.ArgumentParser(__doc__);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    output=args.output.resolve();config=batch.read(output/'configuration.json');control=Path(config['control_root'])
    with (control/'whitebox_production_queue.lock').open('a+') as lease:
        fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
        state=batch.read(output/'single_state.json');source=Path(state['attempt'])
        if batch.read(source/'input_manifest.json')['entry']['id']!='Sol__G005_broken_realm_echo':raise ValueError('G005 only')
        if source.name.startswith('Sol__G005_broken_realm_echo__axis_snapshot_v1_'):raise ValueError('Recovery already prepared; resume explicitly')
        from .effective import resolve_result
        if resolve_result(Path(config['batch']),batch.read(source/'input_manifest.json')['entry'])['valid']:raise ValueError('Effective result protected')
        reconciliation=reconcile_interrupted_cleanup(output,source,config)
        old_acceptance=Path(config['editor_acceptance']);old=batch.read(old_acceptance)
        fixtures=make_fixtures(output,config,old_acceptance)
        accepted=output/('recorder_acceptance_axis_'+str(time.time_ns()))
        unity_single.phase(output,'native_axis_acceptance',attempt=str(source),plan_model_calls_added=0)
        command=[sys.executable,'-m','engine_adapters.unity3d.playtest.native_acceptance','--output',str(accepted),
            '--adapter-root',config['adapter_root'],'--control-root',str(control),'--parent-pin',old['parent_pin'],
            '--fixture-root',str(fixtures),'--editor',old['editor']]
        subprocess.run(command,check=True)
        acceptance=accepted/'acceptance.json'
        from engine_adapters.unity3d.playtest.native_acceptance import verify
        verify(acceptance,Path(config['adapter_root']),Path(old['editor']))
        for duration in (20,180):
            snapshot=batch.read(accepted/f'fixture_{duration}s/source_snapshot.json')
            if not snapshot.get('input_axis_normalization'):raise ValueError('Native axis correction was not exercised')
        unity_single.check_cleanup(config,accepted/'fixture_180s')
        root=recover_attempt(source,acceptance,reconciliation)
        dump(output/'configuration_history'/('before_axis_'+str(time.time_ns())+'.json'),config)
        config['editor_acceptance']=str(acceptance);dump(output/'configuration.json',config)
        dump(output/'state_history'/('before_axis_'+str(time.time_ns())+'.json'),state)
        unity_single.phase(output,'axis_capture_recovery',attempt=str(root),previous_attempt=str(source),plan_model_calls_added=0)
        try:unity_single.continue_stages(output,root)
        except BaseException as exc:
            unity_single.phase(output,'HARNESS_ERROR',attempt=str(root),reason=str(exc));raise

if __name__=='__main__':main()
