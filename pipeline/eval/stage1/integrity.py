"""Read-only run audits. Only batch-level audit records are written.

Historical scores and model replies are never edited by this module.
"""
from __future__ import annotations
import copy
import json
import time
from pathlib import Path
from .protocol import dump, sha, validate_judgments

VERSION = 'capture-delivery-gate.targeted-recovery.v1'



def product_attribution(root):
    """Confirm native compiler diagnostics against unmodified delivered sources."""
    import re
    from .batch import read
    root = Path(root)
    meta = read(root/'input_manifest.json') if (root/'input_manifest.json').is_file() else {}
    original = Path(meta.get('entry', {}).get('project') or '/nonexistent')
    findings = []
    for log in (root/'runtime').glob('*.log'):
        for number, line in enumerate(log.read_text(errors='replace').splitlines(), 1):
            match = re.search(r'(Assets/[^\n]*?\.cs)\((\d+),(\d+)\): error (CS\d+):', line)
            if not match:
                continue
            rel = match.group(1)
            paths = [original/rel, root/'input/project'/rel, root/'runtime/project'/rel]
            if all(p.is_file() for p in paths):
                digests = [sha(p) for p in paths]
                if len(set(digests)) == 1:
                    findings.append({'kind':'delivered_source_compile_error', 'source':rel,
                        'source_line':int(match.group(2)), 'source_sha256':digests[0],
                        'original_path':str(paths[0]), 'snapshot_path':str(paths[1]),
                        'runtime_path':str(paths[2]), 'log':str(log.relative_to(root)),
                        'log_line':number, 'log_sha256':sha(log), 'diagnostic':line})
    return {'confirmed':bool(findings), 'findings':findings,
            'rule':'native error log plus identical original/snapshot/runtime source SHA256'}


def audit_bindings(root):
    root = Path(root)
    names = ['evidence_manifest.json','scores.json','rubric_verdicts.json','sol_plan.json',
             'trace_summary.json','input/pilot_rubric.json','input_manifest.json',
             'runtime/frame_index.jsonl','runtime/actions.jsonl','runtime/state_trace.jsonl',
             'runtime/event_trace.jsonl','runtime/engine_result.json','runtime/import_result.json',
             'status.json','harness_error.json','channel_transport_recovery.json','static_delivery_recovery.json','static_packet_policy.json','plan_budget_recovery.json','lean_plan_recovery.json']
    names += [str(p.relative_to(root)) for p in sorted((root/'scoring_protocols').glob('*.json'))]
    names += [str(p.relative_to(root)) for p in sorted((root/'judgments').glob('*.json'))]
    names += ['static_existence.json','static_items_transport.json','recorded_plan_derivation.json',
              'recorded_capture_provenance.json','recovery_source/recorded_sol_plan.original.json']
    names += ['runtime/capture_schedule.json', 'runtime/play_started.json', 'runtime/action_frame_links.json']
    names += [str(p.relative_to(root)) for p in sorted((root/'model_calls').glob('static_existence*/*')) if p.is_file()]
    for folder in (root/'model_calls').glob('*'):
        if folder.is_dir() and (folder.name in {'static','plan'} or folder.name.startswith(('evidence_', 'plan_', 'static_'))):
            names += [str(path.relative_to(root)) for path in folder.iterdir()
                      if path.is_file() and path.name in {'actual_delivery.json','prompt.txt','schema.json','response.json','invocation.json','accepted_response.json','retry_provenance.json','repair_feedback.json','applied_plan.json','patch_application.json','original_schema.json','schema_transform.json'}]
    names += [str(p.relative_to(root)) for p in sorted((root/'runtime').glob('*.log'))]
    if (root/'runtime/multisession_index.json').is_file():
        names += ['runtime/multisession_index.json','runtime/log_index.jsonl','runtime/multisession_sources.json']
        names += [str(p.relative_to(root)) for folder in ['runtime/sessions','runtime/session_projects']
                  for p in sorted((root/folder).rglob('*')) if p.is_file()]
    if (root/'lean_plan_recovery.json').is_file():
        receipt = json.loads((root/'lean_plan_recovery.json').read_text())
        source = Path(receipt['source_attempt'])
        names += [str(source/name) for name in receipt['source_bindings']]
    if (root/'plan_budget_recovery.json').is_file():
        receipt = json.loads((root/'plan_budget_recovery.json').read_text())
        source = Path(receipt['source_attempt'])
        for name in receipt['source_bindings']:
            names.append(str(source/name))
        if receipt.get('cleanup_reconciliation'):
            names.append(receipt['cleanup_reconciliation'])
    names += ['planning_prompt_policy.json','planning_prompt_template.py','planning_prompt_transform.json',
              'plan_normalization.json','recovery_source/plan_normalization.json','unsupported_input_policy.json','route_metadata_repair.json']
    if (root/'recovery_source/plan_normalization.json').is_file():
        recorded = Path(json.loads((root/'recorded_capture_provenance.json').read_text())['source_attempt'])
        normalization = json.loads((recorded/'plan_normalization.json').read_text())
        names += [str(recorded/'plan_normalization.json'), str(recorded/'sol_plan.json'),
                  str(recorded/'unsupported_input_policy.json'),str(recorded/'route_metadata_repair.json')]
        reply = recorded/normalization['response']
        names += [str(reply), str(reply.parent/'schema.json'), str(reply.parent/'invocation.json')]
    result = {name:sha(root/name) for name in names if (root/name).is_file()}
    from .native_slot_recovery import RECEIPT as slot_receipt, verify as verify_slots
    if (root/slot_receipt).is_file():result.update(verify_slots(root))
    from .unity_runtime_dependencies import audit_binding as dependency_bindings
    result.update(dependency_bindings(root))
    from .input_axis_provenance import audit_binding as axis_bindings
    result.update(axis_bindings(root))
    from .unity_capture_retry import audit_binding as retry_bindings
    result.update(retry_bindings(root))
    from .unity_capture_policy import audit_binding as foreground_bindings
    result.update(foreground_bindings(root))
    from .unity_observer_recovery import audit_binding as observer_bindings
    result.update(observer_bindings(root))
    from .unity_native_entry import audit_binding as native_entry_bindings
    result.update(native_entry_bindings(root))
    from .plan_invocation_identity import audit_binding as invocation_bindings
    result.update(invocation_bindings(root))
    from .static_judge_recovery import RECEIPT, verify as verify_static_recovery
    if (root/RECEIPT).is_file():result.update(verify_static_recovery(root))
    if (root/'channel_transport_recovery.json').is_file() or (root/'static_delivery_recovery.json').is_file():
        from .request_reuse import bindings
        result.update(bindings(root))
    from .unity_admission_metadata import audit_binding as admission_metadata_binding
    result.update(admission_metadata_binding(root))
    from .controller_import_source import audit_bindings as controller_import_bindings
    result.update(controller_import_bindings(root))
    from .native_gateway_timeout_recovery import RECEIPT as gateway_receipt, verify as verify_gateway
    if (root/gateway_receipt).is_file():result.update(verify_gateway(root))
    return result



def source_integrity(root):
    """Recheck actual original/snapshot/runtime files, including added observers."""
    from . import batch as b
    issues=[]
    for check in (b.verify_inputs,b.verify_runtime_sources):
        try:check(Path(root))
        except (ValueError,KeyError,TypeError,OSError) as exc:issues.append(str(exc))
    return {'valid':not issues,'issues':issues}


def validator_bindings(root=None):
    result = {name:sha(Path(__file__).parent/name) for name in
            ('integrity.py','batch.py','protocol.py','codex.py','unity_metadata.py','partial_scoring.py','runtime_budgets.py','vite_cache.py','vite_cache_rebuild.mjs','judge_artifacts.py','npm_lock.py','tiered_core.py','static_existence.py','frame_budget.py','endpoint_sparse.py','sparse_evidence.py','endpoint_channels.py','request_reuse.py','asset_reservation.py','plan_budget_recovery.py','static_judge_shards.py','static_judge_recovery.py','native_static_partition_recovery.py','native_service_recovery.py','native_slot_recovery.py')}
    if root is not None:
        from .unity_runtime_dependencies import audit_binding as dependency_bindings
        if dependency_bindings(root):
            result['unity_runtime_dependencies.py'] = sha(Path(__file__).with_name('unity_runtime_dependencies.py'))
    if root is not None and (Path(root)/'static_items_transport.json').is_file():
        result['static_transport_recovery.py'] = sha(Path(__file__).with_name('static_transport_recovery.py'))
    if root is not None and any((Path(root)/name).is_file() for name in ('plan_normalization.json','recovery_source/plan_normalization.json')):
        result['unity_plan_normalization.py'] = sha(Path(__file__).with_name('unity_plan_normalization.py'))
        result['unsupported_inputs.py'] = sha(Path(__file__).with_name('unsupported_inputs.py'))
        result['plan_route_metadata.py'] = sha(Path(__file__).with_name('plan_route_metadata.py'))
        for receipt_name in ('plan_normalization.json','recovery_source/plan_normalization.json'):
            receipt_path = Path(root)/receipt_name
            if receipt_path.is_file() and json.loads(receipt_path.read_text()).get('partial_observation_recovery_sha256'):
                result['partial_observation_recovery.py'] = sha(Path(__file__).with_name('partial_observation_recovery.py'))
        for receipt_name in ('plan_normalization.json','recovery_source/plan_normalization.json'):
            receipt_path = Path(root)/receipt_name
            if receipt_path.is_file() and any(c.get('kind') == 'replay_saved_field_correction'
                    for c in json.loads(receipt_path.read_text()).get('changes', [])):
                result['saved_plan_field_patch.py'] = sha(Path(__file__).with_name('saved_plan_field_patch.py'))
                result['plan_patches.py'] = sha(Path(__file__).with_name('plan_patches.py'))
    if root is not None:
        from .input_axis_provenance import audit_binding as axis_bindings
        if axis_bindings(root):
            for name in ('input_axis_provenance.py','recorded_import_review.py','unity_axis_recovery.py'):
                result[name] = sha(Path(__file__).with_name(name))
            from engine_adapters.unity3d.playtest import input_axis_serialization
            result['input_axis_serialization.py'] = sha(Path(input_axis_serialization.__file__))
    if root is not None:
        from .unity_capture_retry import audit_binding as retry_bindings
        if retry_bindings(root):
            result['unity_capture_retry.py'] = sha(Path(__file__).with_name('unity_capture_retry.py'))
    if root is not None:
        from .unity_observer_recovery import audit_binding as observer_bindings
        if observer_bindings(root):
            result['unity_observer_recovery.py']=sha(Path(__file__).with_name('unity_observer_recovery.py'))
            from engine_adapters.unity3d.playtest import functional_observer
            result['functional_observer.py']=sha(Path(functional_observer.__file__))
    if root is not None:
        from .unity_native_entry import audit_binding as native_entry_bindings
        if native_entry_bindings(root):
            for name in ('unity_native_entry.py','unity_entry_recovery.py','unity_admission.py'):
                result[name]=sha(Path(__file__).with_name(name))
    if root is not None:
        from .plan_invocation_identity import audit_binding as invocation_bindings
        if invocation_bindings(root):
            result['plan_invocation_identity.py']=sha(Path(__file__).with_name('plan_invocation_identity.py'))
    if root is not None:
        from .unity_capture_policy import audit_binding as foreground_bindings
        if foreground_bindings(root):
            result['unity_capture_policy.py'] = sha(Path(__file__).with_name('unity_capture_policy.py'))
    if root is not None and (Path(root)/'recorded_capture_provenance.json').is_file():
        result['unity_ide_metadata.py'] = sha(Path(__file__).with_name('unity_ide_metadata.py'))
        result['unity_admission_metadata.py'] = sha(Path(__file__).with_name('unity_admission_metadata.py'))
    if root is not None and (Path(root)/'runtime/multisession_index.json').is_file():
        for name in ['multiclient.py','action_links.py','runtime.py','tiered_core.py','core12.py']:
            result[name]=sha(Path(__file__).parent/name)
    return result


def audit_run(root):
    from . import batch as b
    root=Path(root)
    capture=b.validate_capture_bundle(root)
    sources=source_integrity(root)
    proto=b.read(root/'input/pilot_rubric.json')
    plan_issues=[]
    try:
        from .unity_plan_normalization import audit_binding
        audit_binding(root)
        from .input_axis_provenance import audit_binding as axis_bindings
        axis_bindings(root)
        from .unity_capture_retry import audit_binding as retry_bindings
        retry_bindings(root)
        from .unity_capture_policy import audit_binding as foreground_bindings
        foreground_bindings(root)
        from .unity_observer_recovery import audit_binding as observer_bindings
        observer_bindings(root)
        from .unity_native_entry import audit_binding as native_entry_bindings
        native_entry_bindings(root)
    except (ValueError,KeyError,TypeError,OSError) as exc:
        plan_issues.append('plan normalization provenance: '+str(exc))
    from . import core12
    if (not core12.enabled(proto) and proto.get('case_id')=='G057_rhythm_machine_hall'
            and (root.parents[1]/'recording_protocols/root-relative-recovery.v3.json').is_file()):
        from .legacy_g057 import validate_g057_chart_plan
        try:validate_g057_chart_plan(b.read(root/'sol_plan.json'))
        except (ValueError,KeyError,TypeError,OSError) as exc:plan_issues.append(str(exc))
    manifest=b.read(root/'evidence_manifest.json')
    samples={s['line'] for s in b.read(root/'trace_summary.json').get('state_samples',[])}
    from . import frame_budget
    tasks=frame_budget.tasks(proto,manifest)
    failures=[];rows=[];invalid_shards=[]
    for name,specs,static in tasks:
        source=root/'judgments'/f'{name}.json'
        try:
            artifact=b.read(source)
            from .judge_artifacts import validate_saved_shard
            validate_saved_shard(artifact,specs)
            if {c.get('id') for c in artifact['raw']['checks']}!={s['id'] for s in specs} or len(artifact['raw']['checks'])!=len(specs):
                raise ValueError('saved judge omitted or invented check IDs')
            task_manifest=frame_budget.for_task(manifest,name)
            visible=copy.deepcopy(task_manifest)
            if static:visible['items']=[e for e in visible['items'] if e['type'] not in {'frame','reference','action','state','event'}]
            normalized=b.canonical_evidence_ids(artifact['raw'],visible)
            checked=validate_judgments(normalized,visible,root,specs=specs)
            _,omitted=b.packet(root,task_manifest,static)
            b.validate_delivery_claims(checked,visible,omitted,{row['line'] for row in frame_budget.state_samples(root,task_manifest)})
            bad=b.validate_verdict_structure(checked)
            if bad:invalid_shards.append(name)
            failures.extend(bad);rows.extend(checked)
        except (ValueError,KeyError,TypeError,OSError) as exc:
            failures.append({'shard':name,'issues':[str(exc)]});invalid_shards.append(name)
    old=b.read(root/'scores.json') if (root/'scores.json').exists() else {}
    old_rows={r['id']:r for r in old.get('checks',[])}
    # Match the controller verdict used by judge() before comparing history.
    # Every changed verdict requires review, including a downgrade to zero.
    b.apply_controller_import_verdict(root, rows)
    downgraded=[{'id':r['id'],'old_status':old_rows[r['id']]['status'],'validated_status':r['status'],
                 'issues':r.get('validation_issues',[])} for r in rows if r['id'] in old_rows
                and old_rows[r['id']]['status']!=r['status']]
    changed_ids={r['id'] for r in downgraded}
    for name,specs,_ in tasks:
        if changed_ids & {spec['id'] for spec in specs}:invalid_shards.append(name)
    from .protocol import aggregate, COLUMNS
    from .judge_artifacts import run_fallback_issues
    provenance_issues=run_fallback_issues(root)
    current=b.read(root/'status.json') if (root/'status.json').is_file() else {}
    error=b.read(root/'harness_error.json') if (root/'harness_error.json').is_file() else {}
    if current.get('status') in {'HARNESS_ERROR','BLOCKED_ENGINE_COLLECTOR'} or current.get('score_status')=='JUDGE_PENDING_RECOVERY':
        provenance_issues.append('current attempt has an unresolved harness error')
    if error.get('is_score_allowed') is False or error.get('scores_valid') is False:
        provenance_issues.append('harness_error.json forbids publishing a score')
    scoring_issues=[]
    recalculated={}
    try:
        from . import asset_reservation
        asset_reservation.validate(proto)
        if asset_reservation.enabled(proto):
            from .core12 import verify_attempt
            verify_attempt(root,b.read(root/'input_manifest.json')['entry']['actual_engine'])
        if frame_budget.enabled(proto):
            if (root/'channel_transport_recovery.json').is_file() or (root/'static_delivery_recovery.json').is_file():
                from .request_reuse import audit_requests
                audit_requests(root,proto,manifest)
            else:
                frame_budget.audit_requests(root,proto,manifest)
        recalculated=aggregate(rows,valid=True,method='audit',protocol='audit',scope='audit') if rows else {}
        version=old.get('scoring_protocol')
        from .partial_scoring import apply_to_report, make_rubric, SUPPORTED_VERSIONS, VERSION as scoring_version
        if version in SUPPORTED_VERSIONS and rows:
            apply_to_report(recalculated,proto,version=version,root=root)
            if version in {scoring_version,'whitebox-static10-runtime90.v1','whitebox-mechanic10-50-100.v1','whitebox-mechanic10-50-100.v2'}:
                relative=old.get('scoring_protocol_path')
                if relative!=f"scoring_protocols/{proto['case_id']}.{version}.json":
                    raise ValueError('missing or unexpected per-attempt scoring protocol path')
                artifact=root/relative
                if b.read(artifact)!=make_rubric(proto,version=version):
                    raise ValueError('scoring artifact differs from frozen protocol')
                if old.get('scoring_protocol_sha256')!=sha(artifact) or old.get('source_protocol_sha256')!=sha(root/'input/pilot_rubric.json'):
                    raise ValueError('scoring artifact or frozen protocol SHA256 mismatch')
                if version in {'whitebox-static10-runtime90.v1','whitebox-mechanic10-50-100.v1','whitebox-mechanic10-50-100.v2'} and old.get('static_existence_sha256')!=sha(root/'static_existence.json'):
                    raise ValueError('static source judgment SHA256 mismatch')
        elif version is not None:
            raise ValueError(f'unsupported scoring protocol: {version}')
        elif proto.get('version')==b.V4_VERSION:
            raise ValueError('v4 frozen protocol requires explicit partial scoring version')
    except (ValueError,KeyError,TypeError,OSError) as exc:
        scoring_issues.append(str(exc))
    score_consistent=(not scoring_issues and old.get('valid') is True and old.get('overall_score')==recalculated.get('overall_score')
        and all(old.get('columns',{}).get(c,{}).get('score')==recalculated.get('columns',{}).get(c,{}).get('score') for c in COLUMNS))
    valid=capture['valid'] and sources['valid'] and not plan_issues and not failures and not downgraded and not provenance_issues and score_consistent
    engine=b.read(root/'runtime/engine_result.json') if (root/'runtime/engine_result.json').is_file() else {}
    attribution=product_attribution(root)
    product_error=attribution['confirmed']
    state=('COMPLETE' if valid else 'HARNESS_ERROR' if not sources['valid'] or plan_issues or provenance_issues or scoring_issues else 'DELIVERY_REVIEW_REQUIRED' if product_error
           else 'HARNESS_ERROR' if not capture['valid'] or failures else 'DELIVERY_REVIEW_REQUIRED')
    if valid and old.get('scoring_protocol') in {'whitebox-static10-runtime90.v1','whitebox-mechanic10-50-100.v1','whitebox-mechanic10-50-100.v2'}:
        state='JUDGED'
    return {'version':VERSION,'source_run':str(root.resolve()),'created_unix':time.time(),
        'valid':valid,'effective_status':state,'confirmed_product_error':product_error, 'product_attribution':attribution,
        'capture':capture,'source_integrity':sources,'plan_issues':plan_issues,'citation_failures':failures,'score_consistent':score_consistent,
        'reason':'; '.join(plan_issues+provenance_issues+scoring_issues) or None,
        'provenance_issues':provenance_issues,'scoring_issues':scoring_issues,
        'invalidated_judge_shards':sorted(set(invalid_shards)), 'verdicts_requiring_review':downgraded,
        'historical_score':old.get('overall_score'), 'historical_score_is_formal':valid,
        'bindings':audit_bindings(root), 'validator_bindings':validator_bindings(root)}


def audit_batch(batch):
    from . import batch as b
    batch=Path(batch).resolve();results=[]
    for entry in b.read(batch/'inventory.json')['entries']:
        root=b.run_root(batch,entry)
        if not (root/'scores.json').exists():continue
        from .effective import audit_effective
        try:result=audit_effective(batch,entry)
        except (ValueError,KeyError,TypeError,OSError) as exc:
            result={'version':VERSION,'source_run':str(root.resolve()),'valid':False,'effective_status':'HARNESS_ERROR','reason':str(exc)}
        result['id']=entry['id']
        folder=batch/'validation_audits'/entry['id'];folder.mkdir(parents=True,exist_ok=True)
        dump(folder/f'{time.time_ns()}.json',result)
        dump(batch/'validation_audits'/f"{entry['id']}.json",result)
        results.append(result)
        print(json.dumps({'audited':entry['id'],'valid':result['valid'],'capture':result.get('capture',{}).get('counts'),
            'citation_failures':len(result.get('citation_failures',[])),'review_verdicts':len(result.get('verdicts_requiring_review',[]))}),flush=True)
    b.summary(batch)
    return results


def audit_for(batch,entry,root):
    path=Path(batch)/'validation_audits'/f"{entry['id']}.json"
    if not path.is_file():return None
    from .batch import read
    audit=read(path)
    if audit.get('source_run')!=str(Path(root).resolve()):return None
    if audit.get('version') != VERSION or audit.get('validator_bindings') != validator_bindings(root):return None
    if audit.get('bindings') != audit_bindings(root):return None
    # File removal/corruption must invalidate an old success even when the
    # manifest itself did not change. Never cache the raw/delivery gate.
    from .batch import validate_capture_bundle
    if validate_capture_bundle(root) != audit.get('capture'):return None
    if source_integrity(root) != audit.get('source_integrity'):return None
    for name,digest in audit.get('bindings',{}).items():
        if not (root/name).is_file() or sha(root/name)!=digest:return None
    return audit
