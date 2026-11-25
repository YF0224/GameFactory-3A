"""Unified production entry for source-bound Mechanic outcome-frame evaluation.

python -m pipeline.game_eval.whitebox_eval.mechanic_v3_cli --help
Only explicit independent all-S batches can use the end-to-end run operation.
Legacy v2 entry points and their default behavior are unchanged.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import fcntl
import json
from pathlib import Path
import time
import traceback
from . import mechanic_v3_runner as runner, mechanic_v3_execution as execution
from . import mechanic_v3_outcome_runner as outcome_runner, mechanic_v3_outcome_native as native
from . import mechanic_v3_revision as revisions, mechanic_v3_outcome_evidence as evidence
from . import mechanic_v3_full_scope as full_scope
from .protocol import dump, sha
from . import evaluation_model_profile as eval_models


def production_source_bindings():
    """Bind Mechanic entry points and their production Python dependencies."""
    import ast
    directory=Path(__file__).resolve().parent
    pending=list(directory.glob('mechanic_v3*.py'));seen=set()
    while pending:
        path=pending.pop()
        if path in seen:continue
        seen.add(path)
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node,ast.ImportFrom) and node.level==1:
                names=[node.module.split('.')[0]] if node.module else [n.name for n in node.names]
                for name in names:
                    dependency=directory/(name+'.py')
                    if dependency.is_file() and dependency not in seen:pending.append(dependency)
    return {str(path):sha(path) for path in sorted(seen)}


def qualify_record(workspace, row):
    """Select the first qualified original take, recording each rejection."""
    root = workspace/'runs'/row['entry']['id']
    if (root/'source_qualification.json').exists():
        receipt=runner.read(root/'source_qualification.json')
        for name,digest in receipt['source_bindings'].items():
            if sha(Path(name)) != digest:
                raise ValueError('Existing qualified record source changed: '+name)
        return root
    selection = workspace/'record_selection'/(row['entry']['id']+'.json')
    if selection.exists():
        saved=runner.read(selection)
        if not saved.get('qualified_source'):
            from . import mechanic_v3_historical_qualification_recovery as historical
            return historical.recover(workspace,row,selection)
        chosen=dict(row, preferred_record=saved['qualified_source'])
        return runner.prepare_view(workspace, chosen)
    attempts=[]
    for candidate in row.get('record_candidates', []):
        try:
            value=runner.qualify_source(Path(candidate), workspace=workspace)
            attempts.append(dict(path=candidate,qualified=True,source_bindings=value['source_bindings']))
        except Exception as error:
            attempts.append(dict(path=candidate,qualified=False,error=repr(error),product_score=None))
            continue
        runner.exclusive_json(selection,dict(time=runner.stamp(),identity=row['entry']['id'],
            qualified_source=candidate,candidates=attempts,selection='First source-qualified record in frozen deterministic order; scores not inspected'))
        return runner.prepare_view(workspace,dict(row,preferred_record=candidate))
    runner.exclusive_json(selection,dict(time=runner.stamp(),identity=row['entry']['id'],
        qualified_source=None,candidates=attempts,product_score=None,
        next_action='Use original native adapter after formal execution locks and matching acceptance are available'))
    return None


def qualify_phase_record(workspace, row, phase):
    """Use the formal recovery verifier when judging an already-bound take."""
    from . import mechanic_v3_user_retake as retake
    from . import mechanic_v3_author_entry_recovery as author_entry
    canonical = Path(workspace)/'runs'/row['entry']['id']
    from . import godot_native_telemetry_reuse as telemetry_reuse
    if (canonical/telemetry_reuse.CLAIM).exists():
        return telemetry_reuse.verify(canonical)
    from . import mechanic_v3_original_material_recovery as material
    if any((canonical/claim).exists() for claim in (retake.CLAIM, author_entry.CLAIM, material.CLAIM)):
        return outcome_runner.locate_qualified(workspace,row['entry']['id'],recorded_only=phase in {'judge','migration-check','qualify'})
    root=qualify_record(workspace,row)
    if root is None and phase in {'qualify','judge','migration-check'}:
        return outcome_runner.locate_qualified(workspace,row['entry']['id'],recorded_only=phase in {'judge','migration-check','qualify'})
    return root



def parent_workspace(inventory):
    scope_path=inventory['full_scope_binding'].get('path')
    return Path(runner.read(Path(scope_path))['source_workspace']) if scope_path else None


def verify_parent_reuse(parent, row):
    """Reuse only a complete outcome publication for the same frozen original."""
    identity=row['entry']['id']
    publication=execution.verify_publication(parent,identity)
    if publication.get('contract_revision')!='outcome_frame_v1':
        raise ValueError('Parent publication has a different Mechanic revision')
    result=Path(publication['score_file'])
    manifest=result.parent/'input_manifest.json'
    if str(manifest.resolve()) not in publication['bindings']:
        qualification=result.parent/'source_qualification.json'
        if str(qualification.resolve()) not in publication['bindings']:
            raise ValueError('Parent publication does not bind its source qualification')
        qualified=runner.read(qualification)
        manifest=Path(qualified['source'])/'input_manifest.json'
        digest=qualified['source_bindings'].get(str(manifest.resolve()))
        if digest is None or sha(manifest)!=digest:
            raise ValueError('Parent qualification does not bind its original manifest')
        if qualified['entry_id']!=identity:
            raise ValueError('Parent qualified original has a different identity')
    original=runner.read(manifest)['entry']
    from .mechanic_v3_full_scope import FIELDS
    for field in FIELDS:
        if original.get(field)!=row['entry'].get(field):
            raise ValueError('Parent original differs from frozen scope: '+field)
    return publication


def complete_publication(workspace, row):
    """Return only source-bound, completely delivered publications for reuse."""
    from . import mechanic_v3_delivery_audit_v4 as delivery
    from . import mechanic_v3_source_correction as correction
    identity = row['entry']['id']
    candidates = []
    pointer = correction.pointer(workspace, identity)
    if pointer.exists():
        claim = correction.verify_claim(runner.read(pointer))
        candidates.append(Path(claim['correction_workspace']))
    candidates.append(workspace)
    for candidate in candidates:
        path = revisions.publication_dir(candidate)/(identity+'.json')
        if not path.exists():
            continue
        publication = verify_parent_reuse(candidate, row)
        checked = delivery.publication(candidate, identity)
        if checked['qualified']:
            return publication, path
    return None


def sync_corrected_publication(workspace, identity, publication_path):
    """Carry the exact authorized sync configuration into correction workspaces."""
    from . import two_column_sync
    target = Path(publication_path).parents[2]
    if revisions.publication_dir(target)/(identity+'.json') != Path(publication_path):
        raise ValueError('Correction publication layout differs')
    source_config = workspace/'two_column_sync.json'
    if not source_config.is_file():
        raise ValueError('Parent workspace lacks authorized two-column sync configuration')
    config = runner.read(source_config)
    destination = target/'two_column_sync.json'
    if destination.exists():
        if runner.read(destination) != config:
            raise ValueError('Correction sync configuration differs; preserve both bindings')
    else:
        runner.exclusive_json(destination, config)
    return two_column_sync.sync(target, identity, 'Mechanic')


def resume_delivery(workspace, row, phase):
    """Preserve incomplete publications and route diagnosed source corrections."""
    if phase not in {'judge', 'run', 'migration-check'}:
        raise ValueError('Retained publication has incomplete delivery; continue its diagnosed judge recovery')
    from . import mechanic_v3_source_correction_runtime as correction
    value = correction.run(workspace, row['entry']['id'])
    qualified = complete_publication(workspace, row)
    if qualified is None:
        raise ValueError('Correction did not produce a complete valid publication')
    publication, path = qualified
    sync_receipt = sync_corrected_publication(workspace, row['entry']['id'], path)
    return dict(identity=row['entry']['id'], stage='SCORED_PENDING_AUDIT',
        score=publication['mechanic_score'], publication=str(path),
        delivery_correction=True, recovery=value, sync_status=sync_receipt['status'])


def persistent_source_correction(workspace, row, inventory, repair):
    """Continue an existing diagnosed correction without replacing its scope or take."""
    from . import mechanic_v3_source_correction as correction
    from .mechanic_v3_persistent_text import run
    identity = row['entry']['id']
    parents = [workspace]
    original = parent_workspace(inventory)
    if original is not None and original != workspace:
        parents.append(original)
    if repair is not None:
        explicit = runner.read(repair).get('source_correction_parent_workspace')
        if explicit:
            previous = Path(explicit).resolve()
            previous_scope = full_scope.load(previous)
            if identity not in previous_scope['active_selection']:
                raise ValueError('Correction parent did not freeze this original identity')
            prior_row = next(r for r in previous_scope['entries'] if r['entry']['id'] == identity)
            if any(prior_row['entry'].get(f) != row['entry'].get(f) for f in full_scope.FIELDS):
                raise ValueError('Explicit correction parent froze another author run')
            if previous not in parents:
                parents.append(previous)
    for parent in parents:
        pointer = correction.pointer(parent, identity)
        if not pointer.is_file():
            continue
        claim = correction.verify_claim(runner.read(pointer))
        if claim['identity'] != identity or claim.get('no_new_recording') is not True:
            raise ValueError('Source correction identity or historical record differs')
        target, root = Path(claim['correction_workspace']), Path(claim['root'])
        if runner.read(root/'source_delivery_correction.json') != claim:
            raise ValueError('Correction root must retain its exact original claim')
        entry = runner.read(root/'input_manifest.json')['entry']
        for field in full_scope.FIELDS:
            if entry.get(field) != row['entry'].get(field):
                raise ValueError('Correction differs from frozen original: '+field)
        case = entry['case_id']
        for name in ('contract.json', 'frozen.json', 'source_binding.json'):
            path = revisions.contract_dir(target, case)/name
            if not path.is_file():
                raise ValueError('Correction lacks its original frozen contract')
        if repair is None:
            raise ValueError('Explicit substantive Mechanic --service-repair required')
        if (revisions.publication_dir(target)/(identity+'.json')).exists():
            # Reuse is handled before this route; never replace an attempted result.
            raise ValueError('Retained corrected publication requires qualification first')
        source_config = workspace/'two_column_sync.json'
        destination = target/'two_column_sync.json'
        config = runner.read(source_config)
        if destination.exists():
            if runner.read(destination) != config:
                raise ValueError('Correction sync config differs from authorized parent')
        else:
            runner.exclusive_json(destination, config)
        result = run(target, root, repair.resolve())
        return dict(identity=identity, stage='SCORED_PENDING_AUDIT', score=result['score'],
            publication=str(revisions.publication_dir(target)/(identity+'.json')),
            correction_claim=str(pointer), new_recording=False, delivery_correction=True)
    return None


def execute(workspace, row, inventory, phase, *, repair_source_workspace=None, retake_authorization=None, shared_web_environment=None, service_success=None, failed_task=None, material_diagnosis=None, material_repair=None, service_repair=None):
    identity=row['entry']['id']
    if not row['in_scope']:
        raise ValueError('Identity excluded by frozen uploader/source scope')
    from .mechanic_v3_kimi_scope import verify_sources as verify_kimi_source
    verify_kimi_source(workspace,row)
    root=workspace/'runs'/identity
    if phase == 'recover-empty-service':
        if service_success is None or service_repair is None:
            raise ValueError('Explicit --service-success and --service-repair required')
        from .mechanic_v3_empty_service_recovery import prepare
        receipt=prepare(workspace,identity,service_success,service_repair)
        return dict(identity=identity,stage='EMPTY_SERVICE_CONTINUATION_PREPARED',recovery=receipt)
    qualified = complete_publication(workspace, row)
    if qualified is not None:
        publication, path = qualified
        return dict(identity=identity, stage='SCORED_PENDING_AUDIT',
            score=publication['mechanic_score'], reused_same_batch=True, publication=str(path))
    if phase == 'persistent-judge':
        corrected = persistent_source_correction(workspace, row, inventory, service_repair)
        if corrected is not None:
            return corrected
    if (revisions.publication_dir(workspace)/(identity+'.json')).exists():
        return resume_delivery(workspace, row, phase)
    parent = parent_workspace(inventory)
    if parent is not None and eval_models.profile_for(workspace) is None:
        qualified = complete_publication(parent, row)
        if qualified is not None:
            publication, path = qualified
            return dict(identity=identity, stage='SKIP_SCORED', score=publication['mechanic_score'],
                reused_cross_batch=True, publication=str(path))
        if (revisions.publication_dir(parent)/(identity+'.json')).exists():
            return resume_delivery(workspace, row, phase)
    if phase == 'recover-service':
        if service_success is None or not failed_task:
            raise ValueError('Explicit --service-success and --failed-task required')
        from .mechanic_v3_service_recovery import prepare
        root=qualify_phase_record(workspace,row,'judge')
        if root is None: raise ValueError('Service continuation requires a qualified native record')
        receipt=prepare(root,failed_task,service_success,repair_path=service_repair)
        return dict(identity=identity,stage='SERVICE_CONTINUATION_PREPARED',root=str(root),recovery=receipt)
    if phase == 'repair-web-environment':
        if shared_web_environment is None:
            raise ValueError('Explicit --shared-web-environment required')
        from .mechanic_v3_web_env_recovery import record
        root=record(workspace,row,shared_web_environment)
        frozen=runner.read(revisions.contract_dir(workspace,row['entry']['case_id'])/'frozen.json')
        evidence.freeze(root,frozen['contract_sha256'])
        return dict(identity=identity,stage='QUALIFIED_RECORD',root=str(root),empty_prelaunch_continued=True)
    if phase == 'recover-original-material':
        if material_diagnosis is None or material_repair is None:
            raise ValueError('Explicit --material-diagnosis and --material-repair required')
        from .mechanic_v3_original_material_recovery import record
        root=record(workspace,row,material_diagnosis,material_repair)
        frozen=runner.read(revisions.contract_dir(workspace,row['entry']['case_id'])/'frozen.json')
        evidence.freeze(root,frozen['contract_sha256'])
        return dict(identity=identity,stage='QUALIFIED_RECORD',root=str(root),same_original_omitted_material=True)
    if phase == 'retake-record':
        if retake_authorization is None:
            raise ValueError('Explicit --retake-authorization required')
        from . import mechanic_v3_user_retake as retake
        root=retake.record(workspace,row,retake_authorization)
        frozen=runner.read(revisions.contract_dir(workspace,row['entry']['case_id'])/'frozen.json')
        evidence.freeze(root,frozen['contract_sha256'])
        return dict(identity=identity,stage='QUALIFIED_RECORD',root=str(root),user_authorized_retake=True)
    if phase == 'repair-planner-response':
        window_repair=workspace/'engineering/planner_infeasible_window_repairs'/(identity+'.json')
        if window_repair.is_file():
            from . import mechanic_v3_infeasible_window_recovery as window_recovery
            root=window_recovery.recover(workspace,row)
        else:
            from .mechanic_v3_planner_response_recovery import recover
            root=recover(workspace,identity)
        return dict(identity=identity,stage='EXECUTABLE_NATIVE_PLAN',root=str(root),diagnosed_model_correction=True)
    if phase == 'recover-planner':
        from .mechanic_v3_planner_recovery import recover
        root=recover(workspace,row,source_attempt=repair_source_workspace/'runs'/identity if repair_source_workspace else None)
        return dict(identity=identity,stage='EXECUTABLE_NATIVE_PLAN',root=str(root),source_bound_transport_recovery=True)
    if phase == 'repair-plan':
        from . import mechanic_v3_prerecord_recovery as recovery
        if (root/recovery.CLAIM).exists():
            root=recovery.verify(workspace,row,continue_identity=True)
            from . import mechanic_v3_prerecord_identity as identity_recovery
            from . import core12
            current=core12.plan_identity(root,runner.read(root/'input/pilot_rubric.json'),row['entry']['actual_engine'])
            if runner.read(root/'sol_plan.json')['planning_identity']!=current:
                root=identity_recovery.recover(workspace,row,root)
        elif (root/'sol_plan.json').exists():
            from . import mechanic_v3_prerecord_identity as identity_recovery
            from . import core12,endpoint_sparse
            proto=runner.read(root/'input/pilot_rubric.json')
            shared=endpoint_sparse.shared_conditions_path(workspace,proto)
            observer=root/'input/endpoint_conditions.json'
            if observer.exists() and runner.read(observer)==runner.read(shared):
                current=core12.plan_identity(root,proto,row['entry']['actual_engine'])
                if (root/identity_recovery.CLAIM).exists():root=identity_recovery.recover(workspace,row,root)
                elif runner.read(root/'sol_plan.json')['planning_identity']!=current:
                    root=identity_recovery.recover(workspace,row,root)
                else:
                    from . import batch
                    batch.validate_operation_plan(root,runner.read(root/'sol_plan.json'),row['entry']['actual_engine'])
            else:root=recovery.recover_observer(workspace,row)
        elif (root/'model_calls/plan_v3_diagnosed_response_correction_v1/validation_error.json').exists():
            from . import mechanic_v3_planner_schedule_recovery as schedule_recovery
            root=schedule_recovery.recover(workspace,row)
        else:
            mapping=workspace/'engineering/plan_metadata_repairs'/(identity+'.json')
            observation=workspace/'engineering/observation_schedule_repairs'/(identity+'.json')
            root=recovery.recover_rejected(workspace,row,mapping_repair=mapping if mapping.exists() else None,
                observation_repair=observation if observation.exists() else None,
                source_attempt=repair_source_workspace/'runs'/identity if repair_source_workspace else None)
        return dict(identity=identity,stage='EXECUTABLE_NATIVE_PLAN',root=str(root),model_call_repeated=False)
    if phase == 'freeze':
        outcome_runner.freeze(workspace, row['entry']['case_id'], inventory)
        return dict(identity=identity,stage='CONTRACT_FROZEN')
    # Continue the retained author-entry plan before historical take selection.
    # The recovery helper verifies its immutable claim and owns native admission.
    from . import mechanic_v3_author_entry_recovery as author_entry
    if phase in {'plan', 'record'} and (root/author_entry.CLAIM).exists():
        from . import mechanic_v3_author_entry_identity as author_identity
        if phase == 'plan':
            root, _ = author_identity.prepare(workspace, row)
            return dict(identity=identity, stage='EXECUTABLE_NATIVE_PLAN', root=str(root),
                author_entry_recovery=True, model_call_repeated=False)
        root = author_identity.record(workspace, row)
        frozen = runner.read(revisions.contract_dir(workspace,row['entry']['case_id'])/'frozen.json')
        evidence.freeze(root, frozen['contract_sha256'])
        return dict(identity=identity, stage='QUALIFIED_RECORD', root=str(root),
            author_entry_recovery=True)
    root=qualify_phase_record(workspace,row,'judge' if phase=='persistent-judge' else phase)
    if phase=='persistent-judge':
        if root is None or service_repair is None:
            raise ValueError('Persistent Mechanic requires qualified record and explicit --service-repair')
        from .mechanic_v3_persistent_text import run
        result=run(workspace,root,service_repair.resolve())
        return dict(identity=identity,stage='SCORED_PENDING_AUDIT',score=result['score'],new_recording=False)
    if phase == 'qualify':
        return dict(identity=identity,stage='QUALIFIED_HISTORICAL_RECORD' if root else 'NEEDS_NATIVE_RECORD',root=str(root) if root else None)
    if root is None:
        if phase in {'judge','migration-check'}:
            raise ValueError('No qualified historical record; native plan/record required')
        # record() preserves accepted plans and attempted captures. It takes the
        # official shared native execution locks, including other sessions.
        if phase == 'plan':
            root,_=native.prepare(workspace,row)
            return dict(identity=identity,stage='EXECUTABLE_NATIVE_PLAN',root=str(root))
        root=native.record(workspace,row)
    frozen=runner.read(revisions.contract_dir(workspace,row['entry']['case_id'])/'frozen.json')
    evidence.freeze(root,frozen['contract_sha256'])
    if phase == 'record':
        return dict(identity=identity,stage='QUALIFIED_RECORD',root=str(root))
    # First scores must qualify full source/native-frame delivery before any call.
    # Existing calls retain their exact requests and require diagnosed recovery.
    if not any((root/'model_calls').glob('mechanic_v3_*')):
        from . import mechanic_v3_first_score
        admitted=mechanic_v3_first_score.prepare(workspace,identity,inventory)
        if admitted.resolve()!=root.resolve():
            raise ValueError('First-score admission selected a different native record')
    result=execution.judge_and_publish(workspace,root,inventory)
    publication=execution.verify_publication(workspace,identity)
    return dict(identity=identity,stage='SCORED_PENDING_AUDIT',score=result['score'],
        reused_same_batch=False,publication=str(revisions.publication_dir(workspace)/(identity+'.json')),
        publication_sha256=sha(revisions.publication_dir(workspace)/(identity+'.json')),
        new_recording=publication['new_recording'])


def report(workspace, inventory):
    """Missing scores never enter a denominator as zero."""
    scores={}; rows=[]
    parent=parent_workspace(inventory)
    for row in inventory['entries']:
        entry=row['entry'];identity=entry['id']
        path=revisions.publication_dir(workspace)/(identity+'.json')
        qualified = complete_publication(workspace, row) if row['in_scope'] else None
        previous = None; previous_path = None
        parent_qualified = None
        if parent is not None:
            candidate = revisions.publication_dir(parent)/(identity+'.json')
            if candidate.exists():
                previous = execution.verify_publication(parent, identity)['mechanic_score']
                previous_path = candidate
            if row['in_scope'] and eval_models.profile_for(workspace) is None:
                parent_qualified = complete_publication(parent, row)
        reused_parent = qualified is None and parent_qualified is not None
        qualified = qualified or parent_qualified
        selected_path = None
        if qualified is not None:
            publication, selected_path = qualified
            scores[identity] = publication['mechanic_score']
        state_path=workspace/'progress'/(identity+'.json')
        state=runner.read(state_path) if state_path.exists() else {}
        unscored_stage = state.get('stage',row['initial_stage'])
        if identity not in scores and unscored_stage in {'SCORED_PENDING_AUDIT','SKIP_SCORED'}:
            unscored_stage = 'INCOMPLETE_DELIVERY'
        rows.append(dict(identity=identity,method=entry['method'],case_id=entry['case_id'],
            in_scope=row['in_scope'],engine=entry['actual_engine'],score=scores.get(identity),
            status='SCORED_PENDING_AUDIT' if identity in scores else unscored_stage,
            reused_cross_batch=reused_parent, score_source=str(selected_path) if selected_path else None,
            score_source_sha256=sha(selected_path) if selected_path else None,
            previous_outcome_score=previous,previous_outcome_source=str(previous_path) if previous_path else None,
            previous_outcome_sha256=sha(previous_path) if previous_path else None,
            change_from_previous_outcome=scores[identity]-previous if identity in scores and previous is not None else None,
            exclusion_reason=row.get('exclusion_reason'),error=state.get('error'),
            next_action=state.get('next_action')))
    models={}
    methods=sorted({row['entry']['method'] for row in inventory['entries']})
    for method in methods:
        selected=[r for r in rows if r['method']==method and r['in_scope']]
        actual=[r['score'] for r in selected if r['score'] is not None]
        models[method]=dict(frozen_count=len(selected),scored_count=len(actual),missing_count=len(selected)-len(actual),
            mean=sum(actual)/len(actual) if actual else None,denominator=len(actual),
            all_scope_mean=sum(actual)/len(actual) if actual and len(actual)==len(selected) else None)
    pairs={}
    from itertools import combinations
    for left,right in combinations(methods, 2):
        left_scores={r['case_id']:r['score'] for r in rows if r['method']==left and r['in_scope'] and r['score'] is not None}
        right_scores={r['case_id']:r['score'] for r in rows if r['method']==right and r['in_scope'] and r['score'] is not None}
        cases=sorted(left_scores.keys() & right_scores.keys())
        pairs[left+'/'+right]=dict(case_ids=cases,denominator=len(cases),
            means={left:sum(left_scores[c] for c in cases)/len(cases) if cases else None,
                   right:sum(right_scores[c] for c in cases)/len(cases) if cases else None})
    receipts=[runner.read(p) for p in (workspace/'native_cache_reclamation').glob('*/receipt.json')]
    value=dict(time=runner.stamp(),revision=revisions.revision(workspace),scope_binding=inventory['full_scope_binding'],
        authorized_columns=['Mechanic'],models=models,strict_pairs=pairs,rows=rows,
        actual_deleted_bytes=sum(r.get('actual_deleted_bytes',0) for r in receipts))
    dump(workspace/'reports/full_s_progress.json',value)
    text=['# 全 S 原始交付 Mechanic 独立重评','',
          '已发布结果均为 SCORED_PENDING_AUDIT（未审计）；旧成绩保留。缺分不填零，全范围未齐时不报告全范围均分。','',
          '| 模型 | 冻结数 | 已出分 | 缺分 | 已出分均分 | 分母 |','|---|---:|---:|---:|---:|---:|']
    for method,m in models.items():
        mean='—' if m['mean'] is None else f"{m['mean']:.2f}"
        text.append(f"| {method} | {m['frozen_count']} | {m['scored_count']} | {m['missing_count']} | {mean} | {m['denominator']} |")
    text+=['','| 身份 | 引擎 | 新 Mechanic | 前次 outcome | 差值 | 状态/排除原因 |','|---|---|---:|---:|---:|---|']
    for row in rows:
        score='—' if row['score'] is None else f"{row['score']:.2f}"
        previous='—' if row['previous_outcome_score'] is None else f"{row['previous_outcome_score']:.2f}"
        delta='—' if row['change_from_previous_outcome'] is None else f"{row['change_from_previous_outcome']:+.2f}"
        text.append(f"| {row['identity']} | {row['engine'] or '缺交付'} | {score} | {previous} | {delta} | {row['status'] if row['in_scope'] else row['exclusion_reason']} |")
    text+=['','严格同题配对（仅双方均有正式核验的有效新版分，包含跨批复用）：', '']
    for name,pair in pairs.items():
        text.append(f"- {name}：n={pair['denominator']}；均分 {pair['means']}；题目 {pair['case_ids']}")
    (workspace/'reports/full_s_progress.md').write_text('\n'.join(text)+'\n')
    return value


def main(argv=None):
    import sys
    arguments = list(sys.argv[1:] if argv is None else argv)
    if any(arguments[n] == '--phase' and arguments[n+1] in {'unity-m-judge','unity-m-judge-prepare'} for n in range(len(arguments)-1)):
        from .unity_m_judge import main as judge_main
        return judge_main(arguments)
    if any(arguments[n:n+2] == ['--phase', 'unity-m-evidence'] for n in range(len(arguments))):
        from .unity_m_evidence import main as evidence_main
        return evidence_main(arguments)
    if any(arguments[n:n+2] == ['--phase', 'unity-m-capture'] for n in range(len(arguments))):
        from .unity_m_capture import main as capture_main
        return capture_main(arguments)
    if any(arguments[n] == '--phase' and arguments[n+1].startswith('unity-m-') for n in range(len(arguments)-1)):
        from .unity_m_runtime import main as unity_m_main
        return unity_m_main(arguments, column='Mechanic')
    if any(arguments[n:n+2] == ['--phase', 'persistent-original-pixel-judge'] for n in range(len(arguments))):
        from .persistent_original_pixel_recovery import main as pixel_main
        return pixel_main(arguments)
    if any(arguments[n:n+2] == ["--phase", "native-image-delivery-acceptance"] for n in range(len(arguments))):
        from .native_image_cli_probe import main as probe_main
        return probe_main(arguments)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace',type=Path,required=True)
    parser.add_argument('--phase',required=True,choices=['freeze-kimi','native-draw-acceptance','recover-native-draw','qualify-native-telemetry','native-telemetry-acceptance','diagnose-native','freeze-reassessment','freeze-batch','qualify','freeze','plan','repair-plan','recover-planner','repair-planner-response','record','recover-original-material','retake-record','repair-web-environment','recover-service','recover-empty-service','persistent-judge','judge','migration-check','run','report','cache'])
    parser.add_argument('--native-source',type=Path)
    parser.add_argument('--native-repair',type=Path)
    parser.add_argument('--retake-authorization',type=Path)
    parser.add_argument('--material-diagnosis',type=Path)
    parser.add_argument('--material-repair',type=Path)
    parser.add_argument('--shared-web-environment',type=Path)
    parser.add_argument('--service-success',type=Path)
    parser.add_argument('--failed-task')
    parser.add_argument('--service-repair',type=Path)
    parser.add_argument('--source-workspace',type=Path)
    parser.add_argument('--kimi-source-manifest',type=Path)
    parser.add_argument('--repair-source-workspace',type=Path,help='Read preserved rejected plan data; never executes source workspace tools')
    parser.add_argument('--git-ref',default='origin/main')
    parser.add_argument('--models',nargs='+',choices=['Astra','Opus','Sol','GLM'])
    parser.add_argument('--engines',nargs='+',choices=['godot','three_js'])
    parser.add_argument('--parent-scope-workspace',type=Path)
    parser.add_argument('--identities',nargs='+')
    parser.add_argument('--workers',type=int,choices=[1,2],default=1)
    args=parser.parse_args(argv);workspace=args.workspace.resolve()
    if args.repair_source_workspace and args.phase not in {'repair-plan','recover-planner'}:
        parser.error('--repair-source-workspace requires repair-plan or recover-planner')
    if args.phase=='freeze-reassessment':
        if not args.source_workspace: parser.error('--source-workspace is required')
        from .mechanic_v3_reassessment import freeze
        inventory=freeze(workspace,args.source_workspace)
        print(json.dumps(dict(workspace=str(workspace),selected=inventory['active_selection'],roles=eval_models.profile_for(workspace)[1]['roles'])))
        return 0
    if args.phase=='freeze-kimi':
        if not args.source_workspace or not args.kimi_source_manifest:parser.error('Kimi requires original source manifest and shared frozen-contract workspace')
        from .mechanic_v3_kimi_scope import freeze
        frozen=freeze(workspace,args.source_workspace,args.kimi_source_manifest)
        print(json.dumps(dict(workspace=str(workspace),selected=len(frozen['active_selection']),unresolved=[r['entry']['id'] for r in frozen['entries'] if not r['in_scope']])))
        return 0
    if args.phase=='freeze-batch':
        if not args.source_workspace:parser.error('--source-workspace is required')
        inventory=full_scope.freeze(workspace,args.source_workspace,git_ref=args.git_ref,methods=args.models,engines=args.engines,parent_workspace=args.parent_scope_workspace)
        print(json.dumps(dict(workspace=str(workspace),selected=len(inventory['active_selection']),discovered=len(inventory['entries']))))
        return 0
    inventory=full_scope.load(workspace)
    if revisions.revision(workspace)!='outcome_frame_v1':raise ValueError('Explicit outcome revision required')
    if args.phase=='report':
        print(json.dumps(report(workspace,inventory)['models'],ensure_ascii=False));return 0
    if args.phase in {'record','recover-original-material','retake-record','repair-web-environment','run'} and args.workers!=1:
        parser.error('Native execution must be serialized')
    if args.phase=='run':
        acceptance=runner.read(workspace/'engineering/production_migration_acceptance.json')
        if acceptance['scope_binding']!=inventory['full_scope_binding']:
            raise ValueError('Migration acceptance scope differs')
        for name,digest in acceptance['production_source_bindings'].items():
            if sha(Path(name))!=digest:raise ValueError('Production source changed after migration acceptance: '+name)
        if sha(Path(acceptance['publication']))!=acceptance['publication_sha256']:
            raise ValueError('Migration acceptance publication changed')
    identities=args.identities or inventory['active_selection']
    if len(set(identities))!=len(identities) or set(identities)-set(inventory['active_selection']):
        raise ValueError('Duplicate or non-frozen identity')
    rows={row['entry']['id']:row for row in inventory['entries']}
    runner.configure_cli(Path(rows[identities[0]]['source_batch']))
    if args.phase in {'native-draw-acceptance','recover-native-draw'}:
        if len(identities)!=1 or args.workers!=1:
            parser.error('Native draw recovery requires one frozen identity and worker')
        from . import godot_native_draw_recovery as draw
        with (workspace/'locks'/('outcome_frame_v1_'+identities[0]+'.lock')).open('a+') as handle:
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            if args.phase=='native-draw-acceptance':
                value=draw.acceptance(workspace,rows[identities[0]])
            else:
                if not args.native_source or not args.native_repair:
                    parser.error('Native draw recovery requires the retained diagnostic and repair')
                value=draw.recover(workspace,rows[identities[0]],args.native_source,args.native_repair)
        print(json.dumps(dict(identity=identities[0],stage='NATIVE_DRAW_ACCEPTED' if args.phase=='native-draw-acceptance' else 'NATIVE_DRAW_RECORDED',result=value),ensure_ascii=False),flush=True)
        return 0
    if args.phase=='qualify-native-telemetry':
        if len(identities)!=1 or args.workers!=1 or not args.native_source or not args.native_repair:
            parser.error('Qualification requires one identity, diagnostic source and explicit repair')
        from . import godot_native_telemetry_reuse as telemetry_reuse
        with (workspace/'locks'/('outcome_frame_v1_'+identities[0]+'.lock')).open('a+') as handle:
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            root=telemetry_reuse.qualify(workspace,rows[identities[0]],args.native_source,args.native_repair)
        print(json.dumps(dict(identity=identities[0],stage='QUALIFIED_RECORD',root=str(root),new_recording=False)),flush=True)
        return 0
    if args.phase in {'native-telemetry-acceptance','diagnose-native'}:
        if len(identities)!=1 or args.workers!=1:
            parser.error('Native telemetry requires exactly one frozen identity and worker')
        from . import godot_native_telemetry as telemetry
        with (workspace/'locks'/('native_telemetry_'+identities[0]+'.lock')).open('a+') as handle:
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            if args.phase=='native-telemetry-acceptance':
                value=telemetry.acceptance(workspace,rows[identities[0]])
            else:
                if not args.native_source or not args.native_repair:
                    parser.error('Diagnostic requires --native-source and --native-repair')
                value=telemetry.diagnose(workspace,rows[identities[0]],args.native_source,args.native_repair)
        print(json.dumps(value,ensure_ascii=False),flush=True)
        return 0
    locks=workspace/'locks';locks.mkdir(exist_ok=True)
    def invoke(identity):
        with (locks/('outcome_frame_v1_'+identity+'.lock')).open('a+') as handle:
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            if args.phase=='cache':
                from . import mechanic_v3_cache
                return mechanic_v3_cache.run(workspace,outcome_runner.locate_qualified(workspace,identity))
            value=execute(workspace,rows[identity],inventory,args.phase,repair_source_workspace=args.repair_source_workspace,retake_authorization=args.retake_authorization,material_diagnosis=args.material_diagnosis,material_repair=args.material_repair,shared_web_environment=args.shared_web_environment,service_success=args.service_success,failed_task=args.failed_task,service_repair=args.service_repair)
            dump(workspace/'progress'/(identity+'.json'),dict(time=runner.stamp(),**value))
            if args.phase=='migration-check' and value['stage']=='SCORED_PENDING_AUDIT':
                if value.get('reused_same_batch'):
                    execution.verify_publication(workspace,identity)
                dump(workspace/'engineering/production_migration_acceptance.json',dict(time=runner.stamp(),
                    identity=identity,publication=value['publication'],publication_sha256=sha(Path(value['publication'])),
                    real_original_project=True,new_verdict_in_independent_batch=True,fixture_is_not_product_evaluation=True,
                    scoring_protocol='whitebox-mechanic10-50-100.v3',revision='outcome_frame_v1',
                    scope_binding=inventory['full_scope_binding'],
                    production_source_bindings=production_source_bindings()))
            return value
    failures=[]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        tasks={pool.submit(invoke,i):i for i in identities}
        for task in as_completed(tasks):
            identity=tasks[task]
            try:print(json.dumps(task.result(),ensure_ascii=False),flush=True)
            except Exception as error:
                state=dict(time=runner.stamp(),identity=identity,phase=args.phase,stage='HARNESS_ERROR',error=repr(error),
                    traceback=traceback.format_exc(),product_score=None,
                    next_action='Inspect this preserved error and source qualification; repair the specific root cause before another model/native attempt')
                dump(workspace/'failures'/(identity+'_'+str(time.time_ns())+'.json'),state)
                dump(workspace/'progress'/(identity+'.json'),state);failures.append(state)
                print(json.dumps({k:v for k,v in state.items() if k!='traceback'},ensure_ascii=False),flush=True)
    with (workspace/'.report.lock').open('a+') as handle:
        try:
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as error:
            pending=dict(time=runner.stamp(),stage='REPORT_PENDING',error=repr(error),
                publications_preserved=True,next_action='Refresh batch report under publication lock; do not rerun scoring')
            dump(workspace/'engineering/report_pending'/(str(time.time_ns())+'.json'),pending)
            print(json.dumps(pending),flush=True)
        else:
            report(workspace,inventory)
    return 1 if failures else 0


if __name__=='__main__':
    raise SystemExit(main())
