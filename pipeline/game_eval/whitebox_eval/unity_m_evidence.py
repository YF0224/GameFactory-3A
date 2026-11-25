"""Source-bound Unity M materialization without invoking legacy score columns."""
from pathlib import Path
import argparse
import fcntl
import shutil
import time
import traceback
from . import batch, unity_m_capture, mechanic_v3_revision, mechanic_v3_outcome_evidence
from .protocol import dump, sha
from .mechanic_v3_runner import exclusive_json


def qualify_recorded(recorded):
    recorded = Path(recorded).resolve()
    workspace = recorded.parent.parent
    root, row, proto = unity_m_capture.qualify_source(workspace, recorded.name)
    if root != recorded:
        raise ValueError('Exact frozen Unity M recording required')
    receipt = batch.read(recorded/'unity_m_capture.json')
    if (receipt.get('stage') != 'NATIVE_CAPTURE_QUALIFIED_NOT_SCORED'
            or receipt.get('source_binding_sha256') != sha(recorded/'unity_m_source_binding.json')):
        raise ValueError('Qualified native capture/source binding required')
    from .unity_capture_policy import qualify
    qualify(recorded)
    native = batch.read(recorded/'recorder_acceptance_binding.json')
    if (native['acceptance_sha256'] != receipt['native_acceptance_sha256']
            or sha(Path(native['acceptance'])) != native['acceptance_sha256']
            or native['plan_sha256'] != sha(recorded/'sol_plan.json')
            or native['actions_sha256'] != sha(recorded/'native_actions.json')
            or native['schedule_sha256'] != sha(recorded/'capture_schedule.json')):
        raise ValueError('Native acceptance, plan or actual scheduled input changed')
    cleanup = batch.read(recorded/'background_record/runner_exit.json')
    if not cleanup.get('cleanup_verified') or cleanup.get('policy_violations'):
        raise ValueError('Actual input/view/process cleanup required')
    return workspace, row, proto


def prepare(workspace, identity, repair=None):
    recorded = workspace/'runs'/identity
    _, row, proto = qualify_recorded(recorded)
    pointer = recorded/'unity_m_evidence.json'
    if pointer.exists():
        value = batch.read(pointer)
        for path, digest in value['bindings'].items():
            if sha(Path(path)) != digest:
                raise ValueError('Preserved two-column native materialization changed: '+path)
        root = Path(value['root'])
        batch.verify_inputs(root);batch.verify_runtime_sources(root)
        return root
    continuation = None
    prepared = None
    materialized = None
    claim = recorded/'unity_m_evidence_claim.json'
    if claim.exists():
        if repair is None:raise ValueError('Preserved evidence claim requires exact pre-materialization repair')
        value=batch.read(repair)
        if value['parent_claim_sha256']!=sha(claim) or value['identity']!=identity:
            raise ValueError('Evidence repair parent identity changed')
        for path,digest in value['bindings'].items():
            if sha(Path(path))!=digest:raise ValueError('Evidence repair binding changed: '+path)
        if value.get('runtime_ide_followup'):
            from .unity_m_snapshot_recovery import verify_materialized_followup
            materialized = verify_materialized_followup(recorded,value)
        elif value.get('kind') in {'materialized_source_schedule','materialized_endpoint_partition','partial_delivery_checkpoint'}:
            failure=Path(value['parent_failure'])
            expected=('native sparse schedule differs from the validated plan' if value['kind']=='materialized_source_schedule' else 'Endpoint physical rows exceed bounded transport: EVENT (bytes=152193, rows=513, line=515)')
            if value['kind']=='partial_delivery_checkpoint':
                expected=str(batch.read(materialized/'validation_history/capture_bundle_validation.json')) if materialized else batch.read(failure)['error']
                if 'Invalid recorded judge plan derivation' not in expected:raise ValueError('Exact partial delivery validation failure required')
            if sha(failure)!=value['parent_failure_sha256'] or batch.read(failure)['error']!=expected:
                raise ValueError('Exact materialized evidence parent failure required')
            materialized=Path(value['partial_attempt'])
            if (materialized.parent!=workspace/'recovery_runs' or
                batch.read(materialized/'attempt_manifest.json')['previous_attempt']!=str(recorded)
                or (materialized/'model_calls').exists() or (materialized/'judgments').exists()):
                raise ValueError('Pre-judge exact materialized identity required')
            from .unity_m_materialization_resume import verify_prepared_receipt
            verify_prepared_receipt(recorded,materialized)
            batch.verify_inputs(materialized);batch.verify_runtime_sources(materialized)
            provenance=batch.read(materialized/'recorded_capture_provenance.json')
            if provenance['source_attempt']!=str(recorded):raise ValueError('Wrong native source')
            for item in provenance['raw_identical_copies']:
                target=materialized/(item.get('preserved_path') or 'runtime/'+item['path'])
                if sha(target)!=item['sha256'] or sha(Path(item['source']))!=item['sha256']:
                    raise ValueError('Raw materialized evidence changed')
        elif value.get('kind')=='endpoint_source_identity':
            from .unity_m_materialization_resume import verify_prepared_receipt
            failure=Path(value['parent_failure'])
            if (sha(failure)!=value['parent_failure_sha256'] or batch.read(failure)['error']!=
                    'endpoint route/source evidence differs from frozen source'):
                raise ValueError('Exact endpoint source handoff failure required')
            prepared=Path(value['partial_attempt'])
            verify_prepared_receipt(recorded,prepared)
        elif value.get('kind')=='prepared_budget':
            from .unity_m_materialization_resume import repair_prepared_budget
            prepared=repair_prepared_budget(recorded,value)
        elif value.get('kind')=='source_protocol_lock':
            from .unity_m_materialization_resume import qualify
            continuation=qualify(recorded,value)
        elif value.get('plan_import_followup'):
            from .unity_m_editor_local_recovery import verify_plan_followup
            _, prepared = verify_plan_followup(recorded, value)
        elif (recorded/'derived_judge_sources').exists() or any((workspace/'recovery_runs').glob(identity+'__recorded_judge_v1_*')):
            raise ValueError('Materialized partial requires a separate exact-stage continuation')
        if materialized:
            repair_claim=recorded/('unity_m_evidence_runtime_ide_repair_claim.json' if value.get('runtime_ide_followup') else 'unity_m_evidence_'+value['kind']+'_repair_claim.json')
        elif prepared and value.get('plan_import_followup'):
            repair_claim=recorded/'unity_m_evidence_plan_import_followup_claim.json'
        elif prepared:
            repair_claim=recorded/('unity_m_evidence_endpoint_source_repair_claim.json' if value.get('kind')=='endpoint_source_identity' else 'unity_m_evidence_prepared_budget_repair_claim.json')
        elif continuation:
            repair_claim=recorded/'unity_m_evidence_protocol_repair_claim.json'
            if value.get('continuation_failure'):
                failed=Path(value['continuation_failure'])
                if (sha(failed)!=value['continuation_failure_sha256'] or batch.read(failed)['error']!='Derived input copy changed: Assets/Generated/Rendering/FPSArenaRenderer.asset'):
                    raise ValueError('Exact derived-copy continuation failure required')
                repair_claim=recorded/'unity_m_evidence_derived_copy_repair_claim.json'
        elif value.get('kind')=='native_editor_recent_scene':
            from .unity_m_editor_local_recovery import verify_failure
            verify_failure(recorded,value)
            repair_claim=recorded/('unity_m_evidence_native_import_followup_claim.json' if value.get('native_import_followup') else 'unity_m_evidence_recent_scene_repair_claim.json')
        elif value.get('kind')=='build_snapshot_policy':
            from .unity_m_snapshot_recovery import verify_evidence_failure
            verify_evidence_failure(recorded,value)
            repair_claim=recorded/('unity_m_evidence_build_ide_repair_claim.json' if value.get('ide_followup') else 'unity_m_evidence_build_snapshot_repair_claim.json')
        elif value.get('kind')=='generated_input_ide':
            from .unity_m_materialization_repair import verify_ide_failure
            verify_ide_failure(recorded,value)
            repair_claim=recorded/'unity_m_evidence_input_ide_repair_claim.json'
        elif value.get('kind')=='native_input_baseline':
            from .unity_m_materialization_repair import verify_baseline_failure
            verify_baseline_failure(recorded,value)
            repair_claim=recorded/'unity_m_evidence_native_baseline_repair_claim.json'
        elif value.get('kind')=='native_settings_import':
            failure=Path(value['parent_failure'])
            if sha(failure)!=value['parent_failure_sha256'] or batch.read(failure)['error']!='Native capture changed input migration bytes: ProjectSettings/ProjectSettings.asset':
                raise ValueError('Exact native settings parent failure required')
            repair_claim=recorded/'unity_m_evidence_settings_repair_claim.json'
        elif value.get('kind')=='native_import_review':
            failure=Path(value['parent_failure'])
            failed=batch.read(failure)
            if (sha(failure)!=value['parent_failure_sha256']
                    or 'assert set(changed_authored)' not in failed['traceback']
                    or 'Assets/Generated/Rendering/FPSArenaRenderer.asset' not in failed['error']):
                raise ValueError('Exact missing native import review failure required')
            repair_claim=recorded/'unity_m_evidence_import_repair_claim.json'
        else:repair_claim=recorded/'unity_m_evidence_repair_claim.json'
        exclusive_json(repair_claim,{'repair':str(repair),'sha256':sha(repair),'new_native_or_model_calls':0})
    else:
        exclusive_json(claim, {'version':'unity-m-two-column-evidence-claim.v1',
        'recording':str(recorded), 'capture_sha256':sha(recorded/'unity_m_capture.json'),
        'no_legacy_static_or_runtime_scores':True})
    from .prepare_unity_recorded_judge import prepare as materialize
    from .recorded_import_review import create_import_review
    create_import_review(recorded)
    if materialized:
        from .prepare_unity_recorded_judge import finish_materialized
        root=finish_materialized(recorded,materialized,two_column_only=True,preserved_delivery=value['kind']=='partial_delivery_checkpoint')
    else:
        root = materialize(recorded, two_column_only=True, unprepared_resume=continuation,
                           existing_attempt=prepared,
                           exact_preplan_resume=value if repair and value.get('plan_import_followup') else None)
    # Preserve all original author sources alongside the exact imported identity.
    from .gameness_v3_runtime import source_files
    original=recorded/'input/project'
    manifest=batch.read(root/'evidence_manifest.json')
    author_bindings={}
    for file in source_files(original):
        relative=file.relative_to(original)
        destination=root/'original_author_source'/relative
        destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(file,destination)
        if sha(destination)!=sha(file):raise ValueError('Original author source copy differs')
        manifest['items'].append({'id':'ORIGINAL_SRC:'+str(relative),'path':str(destination.relative_to(root)),
            'type':'source','sha256':sha(destination)})
        author_bindings[str(relative)]=sha(file)
    dump(root/'evidence_manifest.json',manifest)
    dump(root/'unity_m_original_author_sources.json',{'recorded':str(recorded),
        'original_source_hashes':author_bindings,'implementation_credit':'original author implementation only; native shim is instrumentation'})
    contract_dir = mechanic_v3_revision.contract_dir(workspace,row['entry']['case_id'])
    frozen = batch.read(contract_dir/'frozen.json')
    mechanic_v3_outcome_evidence.freeze(root,frozen['contract_sha256'])
    bindings = {str(p):sha(p) for p in [recorded/'unity_m_capture.json',
        recorded/'unity_m_source_binding.json',recorded/'recorder_acceptance_binding.json',
        recorded/'background_record/verification.json',recorded/'background_record/runner_exit.json',
        root/'input_manifest.json',root/'evidence_manifest.json',
        root/'recorded_capture_provenance.json',root/'sol_plan.json',root/'unity_m_original_author_sources.json']}
    qualification = {'schema':'unity-m-two-column-source-qualification.v1',
        'source':str(recorded),'identity':identity,'new_recording':True,
        'no_new_recording_during_materialization':True,
        'source_bindings':bindings,'source_hashes':row['source_hashes'],
        'original_source_provenance':row['source_provenance'],
        'scope_sha256':sha(workspace/'scopes/unity_m_original/scope.json')}
    exclusive_json(root/'source_qualification.json',qualification)
    bindings[str(root/'source_qualification.json')] = sha(root/'source_qualification.json')
    exclusive_json(pointer,{'version':'unity-m-two-column-materialized.v1','root':str(root),
        'bindings':bindings,'legacy_scoring_called':False,'score':None})
    return root


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workspace',type=Path,required=True)
    p.add_argument('--phase',choices=['unity-m-evidence'],required=True)
    p.add_argument('--ids',nargs='+',required=True)
    p.add_argument('--acceptance-case',action='store_true')
    p.add_argument('--evidence-repair',type=Path)
    a=p.parse_args(argv);w=a.workspace.resolve()
    if len(a.ids)!=1:raise ValueError('One identity per evidence dispatch')
    from .unity_m_admission import require
    require(w,a.ids[0],acceptance_case=a.acceptance_case,operation='evidence')
    with (w/'.unity_m_evidence.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:
            root=prepare(w,a.ids[0],a.evidence_repair)
        except Exception as exc:
            dump(w/'runs'/a.ids[0]/'unity_m_evidence_failures'/f'{time.time_ns()}.json',
                {'error':str(exc),'traceback':traceback.format_exc(),'native_or_model_calls':0})
            raise
        print('UNITY_M_EVIDENCE_READY_NOT_SCORED',root,flush=True)
    return 0
