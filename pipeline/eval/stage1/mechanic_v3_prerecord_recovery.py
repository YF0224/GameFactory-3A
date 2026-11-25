"""Preserve native plans across evaluator repairs, before any game execution.

A changed observer snapshot gets a separate input/operation receipt. Original
model responses, failed attempts, source bytes and all actions remain untouched.
"""
from pathlib import Path
import copy
import hashlib
import shutil
from . import batch, core12, endpoint_sparse, mechanic_v3_revision as revisions
from .codex import validate_schema
from .mechanic_v3_plan_recovery import recording_started
from .mechanic_v3_plan_transport import expand
from .mechanic_v3_outcome_observer_binding import bind_rubrics
from .mechanic_v3_runner import read, stamp, exclusive_json, disk
from .protocol import dump, sha, write_operation_report

CLAIM='mechanic_prerecord_recovery_claim.json'


def verify(workspace,row, *, continue_identity=False):
    source=Path(workspace)/'runs'/row['entry']['id'];claim=read(source/CLAIM)
    for name,digest in claim['source_bindings'].items():
        if sha(Path(name))!=digest:raise ValueError('Prerecord recovery source changed: '+name)
    for name in claim.get('source_absent_paths',[]):
        if Path(name).exists():raise ValueError('Originally absent observer input was introduced: '+name)
    root=Path(claim['recovery_root']);proof=read(root/'prerecord_recovery.json')
    if proof['claim_sha256']!=sha(source/CLAIM) or proof['operation_sha256']!=sha(root/'sol_plan.json'):
        raise ValueError('Prerecord operation or claim changed')
    batch.verify_inputs(root)
    from . import mechanic_v3_prerecord_identity as identity_recovery
    if (root/identity_recovery.CLAIM).exists():
        return identity_recovery.recover(workspace,row,root) if continue_identity else identity_recovery.verify(root)
    return root


def recover_observer(workspace,row):
    from . import mechanic_v3_outcome_native as native
    workspace=Path(workspace).resolve();source=workspace/'runs'/row['entry']['id']
    if (source/CLAIM).exists():return verify(workspace,row)
    if recording_started(source) or (source/'source_qualification.json').exists():
        raise ValueError('Observer rebind allowed only before native recording')
    if not (source/'sol_plan.json').exists():raise ValueError('Preserved accepted operation required')
    batch.verify_inputs(source);engine=row['entry']['actual_engine']
    proto=core12.verify_attempt(source,engine);before=read(source/'sol_plan.json')
    shared_path=endpoint_sparse.shared_conditions_path(workspace,proto);shared=read(shared_path)
    observer_input=source/'input/endpoint_conditions.json'
    if observer_input.exists() and read(observer_input)==shared:
        raise ValueError('No different shared observer to repair')
    folder=revisions.contract_dir(workspace,row['entry']['case_id'])
    paths=[source/'input_manifest.json',source/'sol_plan.json',shared_path,folder/'contract.json',folder/'frozen.json']
    if observer_input.exists():paths.append(observer_input)
    frozen_receipt=source/'endpoint_conditions_receipt.json'
    if frozen_receipt.exists():
        if read(frozen_receipt)['sol_plan_sha256']!=sha(source/'sol_plan.json'):
            raise ValueError('Original observer freeze does not bind its accepted plan')
        paths.append(frozen_receipt)
    absent=[] if observer_input.exists() else [str(observer_input.resolve())]
    bindings={str(p.resolve()):sha(p) for p in paths}
    fingerprint=core12.fingerprint(bindings)
    recovery=workspace/'prerecord_recovery'/source.name/fingerprint;root=recovery/'runs'/source.name
    disk(workspace,'prerecord_observer_snapshot',2*1024**3)
    entry=native.prepared_entry(workspace,row)
    if not root.exists():
        batch.prepare(Path(row['source_batch']),entry,root,prefer_explicit_endpoint_conditions=True)
    current=core12.verify_attempt(root,engine)
    if (read(root/'input_manifest.json')['snapshot_hashes']!=read(source/'input_manifest.json')['snapshot_hashes']
            or read(root/'input/pilot_rubric.json')!=read(source/'input/pilot_rubric.json')):
        raise ValueError('Observer-only recovery changed original sources or protocol')
    # Capability dictionaries can serialize set-derived lists in a different
    # key order. Retain the exact original bytes for identical JSON values.
    for name in ('pilot_rubric.json','input_capabilities.json'):
        if read(root/'input'/name)!=read(source/'input'/name):
            raise ValueError('Recovery changed native protocol/capabilities')
        shutil.copyfile(source/'input'/name,root/'input'/name)
    manifest=read(root/'input_manifest.json')
    manifest['input_hashes']=batch.hashes(root/'input')
    manifest['protocol_sha256']=sha(root/'input/pilot_rubric.json')
    dump(root/'input_manifest.json',manifest)
    # The recovery batch must inherit the same native controls and accepted
    # adapter pins before the unchanged operation validator can inspect it.
    native.native.configuration(recovery,workspace)
    current=core12.verify_attempt(root,engine)
    operation,changes=bind_rubrics(before,shared,current)
    old_identity=copy.deepcopy(operation['planning_identity'])
    operation['planning_identity']=core12.plan_identity(root,current,engine)
    if any(old_identity[k]!=operation['planning_identity'][k] for k in old_identity if k!='constraints_sha256'):
        raise ValueError('Recovery changed non-tool planning identity')
    operation=batch.validate_operation_plan(root,operation,engine)
    for field in ('probes','coverage'):
        if operation[field]!=before[field]:raise ValueError('Observer rebind changed '+field)
    if operation['capture_plan']['windows']!=before['capture_plan']['windows']:
        raise ValueError('Observer rebind changed native windows')
    dump(root/'sol_plan.json',operation)
    endpoint_sparse.freeze_conditions(root,current,operation);write_operation_report(root,operation)
    claim=dict(version='mechanic-prerecord-observer-recovery.v1',time=stamp(),source=str(source),
        source_bindings=bindings,source_absent_paths=absent,recovery_root=str(root),
        root_cause='Generic batch preparation overrode the explicit independent-batch observer with source-batch metadata.',
        original_attempt_preserved=True,actions_windows_coverage_unchanged=True,scoring_contract_unchanged=True)
    exclusive_json(source/CLAIM,claim)
    exclusive_json(root/'prerecord_recovery.json',dict(claim,claim_sha256=sha(source/CLAIM),
        operation_sha256=sha(root/'sol_plan.json'),rubric_metadata_changes=changes,
        derived_tool_identity_before=old_identity,derived_tool_identity_after=operation['planning_identity'],
        model_call_repeated=False,new_native_recording=False))
    dump(root/'stage.json',dict(time=stamp(),stage='EXECUTABLE_NATIVE_PLAN',recovery='shared_observer_snapshot'))
    return root


def recover_tool_identity(workspace,row):
    """Accept the exact saved response after only tool-fingerprint drift."""
    workspace=Path(workspace).resolve();root=workspace/'runs'/row['entry']['id']
    if recording_started(root) or (root/'sol_plan.json').exists():
        raise ValueError('Only never-recorded rejected plans can recover tool identity')
    failed=root/'model_calls/plan_v3_outcome_frame_v1';error=read(failed/'validation_error.json')
    if error['exception']!='$.planning_identity.constraints_sha256: invalid enum value':
        raise ValueError('Different planner rejection needs its specific diagnosis')
    if sha(failed/'response.json')!=error['response_sha256']:
        raise ValueError('Original rejected planner changed')
    raw=read(failed/'response.json');validate_schema(raw,read(failed/'schema.json'))
    proof=root/'engineering/outcome_frame_v1_plan_transport'
    operation=expand(raw,read(proof/'fixed_context.json'))
    validate_schema(operation,read(proof/'original_schema.json'))
    from .mechanic_v3_plan_recovery import normalize_schedule
    operation,schedule_changes=normalize_schedule(read(root/'input/pilot_rubric.json'),operation)
    operation=batch.validate_operation_plan(root,operation,row['entry']['actual_engine'])
    dest=root/'engineering/tool_identity_recovery.json'
    exclusive_json(dest,dict(time=stamp(),classification='NON_SCORING_TOOL_FINGERPRINT_RECOVERY',
        original_failure_sha256=sha(failed/'validation_error.json'),original_response_sha256=sha(failed/'response.json'),
        schema_sha256=sha(failed/'schema.json'),raw_response_unchanged=True,full_original_validators=True,
        schedule_metadata_changes=schedule_changes,actions_windows_coverage_unchanged=True,
        compatibility_receipt_sha256=sha(root/'validation_history/plan_invocation_identity.json'),model_call_repeated=False))
    exclusive_json(failed/'accepted_response.json',dict(path='response.json',sha256=sha(failed/'response.json'),attempt=1,
        recovery_receipt_sha256=sha(dest),prerecord_metadata_derivation=True))
    dump(root/'sol_plan.json',operation)
    proto=core12.verify_attempt(root,row['entry']['actual_engine'])
    endpoint_sparse.freeze_conditions(root,proto,operation);write_operation_report(root,operation)
    return root


def recover_rejected(workspace, row, *, mapping_repair=None, source_attempt=None, observation_repair=None, reference_repair=None):
    """Derive only observation metadata from a preserved, rejected full plan.

    By default actions, coverage intervals and visual windows stay identical.
    Explicit source-bound observation repairs can extend passive waits or fix
    observer clocks, with truthful differences and all full validators retained.
    Missing window mappings require an explicit source-bound metadata receipt;
    this does not call a model or judge another column.
    """
    from . import mechanic_v3_outcome_native as native
    from .mechanic_v3_plan_recovery import normalize_schedule
    workspace=Path(workspace).resolve();claim_source=workspace/'runs'/row['entry']['id']
    if (claim_source/CLAIM).exists():return verify(workspace,row)
    source=Path(source_attempt).resolve() if source_attempt is not None else claim_source
    if source.name!=row['entry']['id']:raise ValueError('Recovery source identity differs from frozen scope')
    if (recording_started(source) or (source/'sol_plan.json').exists()
            or (source/'source_qualification.json').exists()):
        raise ValueError('Only a never-recorded rejected plan may derive metadata')
    failed=source/'model_calls/plan_v3_outcome_frame_v1'
    error=read(failed/'validation_error.json')
    allowed=('constraints_sha256: invalid enum value','endpoint must follow its actual last input',
             'visual window has no frozen Gameness purpose','endpoint rubric basis must quote',
             'visual window lies outside actual probes','core12 coverage extends past its referenced probes')
    if not (any(text in error.get('exception','') for text in allowed) or
            (reference_repair is not None and error.get('exception') in {
                'core12 coverage is unrelated to its referenced probe',
                'endpoint route/source evidence differs from frozen source'})):
        raise ValueError('Different planner rejection needs a separate diagnosis')
    if sha(failed/'response.json')!=error['response_sha256']:
        raise ValueError('Rejected response changed')
    if (failed/'accepted_response.json').exists():
        raise ValueError('Accepted plan requires accepted-operation recovery')
    batch.verify_inputs(source);engine=row['entry']['actual_engine']
    proto=core12.verify_attempt(source,engine)
    raw=read(failed/'response.json');validate_schema(raw,read(failed/'schema.json'))
    transport=source/'engineering/outcome_frame_v1_plan_transport'
    before=expand(raw,read(transport/'fixed_context.json'))
    validate_schema(before,read(transport/'original_schema.json'))
    original_before=copy.deepcopy(before)
    reference_changes=[]
    if reference_repair is not None:
        from .mechanic_v3_reference_recovery import apply as reference_metadata
        before,reference_changes=reference_metadata(before,Path(reference_repair),failed/'response.json',source/'input/project')
        validate_schema(before,read(transport/'original_schema.json'))
    shared_path=endpoint_sparse.shared_conditions_path(workspace,proto)
    shared=read(shared_path) if shared_path.exists() else observer_from_response(source,proto,before)
    folder=revisions.contract_dir(workspace,row['entry']['case_id'])
    paths=[failed/'response.json',failed/'schema.json',failed/'validation_error.json',
        transport/'fixed_context.json',transport/'original_schema.json',source/'input_manifest.json',
        folder/'contract.json',folder/'frozen.json']
    if shared_path.exists():paths.append(shared_path)
    if mapping_repair is not None:paths.append(Path(mapping_repair).resolve())
    if observation_repair is not None:paths.append(Path(observation_repair).resolve())
    if reference_repair is not None:paths.append(Path(reference_repair).resolve())
    bindings={str(p.resolve()):sha(p) for p in paths}
    fingerprint=core12.fingerprint(bindings)
    recovery=workspace/'prerecord_recovery'/source.name/fingerprint;root=recovery/'runs'/source.name
    disk(workspace,'prerecord_saved_response',2*1024**3)
    if not root.exists():
        batch.prepare(Path(row['source_batch']),native.prepared_entry(workspace,row),root,
                      prefer_explicit_endpoint_conditions=True)
    native.native.configuration(recovery,workspace)
    if read(root/'input_manifest.json')['snapshot_hashes']!=read(source/'input_manifest.json')['snapshot_hashes']:
        raise ValueError('Recovery changed original source/asset snapshot')
    for name in ('pilot_rubric.json','input_capabilities.json'):
        if read(root/'input'/name)!=read(source/'input'/name):
            raise ValueError('Recovery changed native protocol/capabilities')
        shutil.copyfile(source/'input'/name,root/'input'/name)
    manifest=read(root/'input_manifest.json');manifest['input_hashes']=batch.hashes(root/'input')
    manifest['protocol_sha256']=sha(root/'input/pilot_rubric.json');dump(root/'input_manifest.json',manifest)
    current=core12.verify_attempt(root,engine)
    baseline=batch.decode_plan_coverage(before)
    observation_changes=[]
    if observation_repair is not None:
        from .mechanic_v3_observation_repair import apply
        baseline,observation_changes=apply(baseline,Path(observation_repair),failed/'response.json')
    operation,rubric_changes=bind_rubrics(baseline,shared,current)
    operation,schedule_changes=normalize_schedule(current,operation)
    mapping_changes=[]
    if mapping_repair is not None:
        repair=read(Path(mapping_repair))
        if repair['response_sha256']!=sha(failed/'response.json'):
            raise ValueError('Mapping repair response binding differs')
        windows={w['id']:w for w in operation['capture_plan']['windows']}
        specifications={r['criterion_id']:r for r in endpoint_sparse.gameness_mapping(current)}
        used={w for m in operation['capture_plan']['gameness'].values() for w in m['window_ids']}
        for addition in repair['additions']:
            criterion=addition['criterion_id'];window=addition['window_id']
            if window not in windows or window in used or criterion not in specifications:
                raise ValueError('Mapping repair must bind an existing unmapped window and criterion')
            if (addition['window_reason']!=windows[window]['reason'] or
                    addition['frozen_criterion']!=specifications[criterion] or not addition['reason'].strip()):
                raise ValueError('Mapping repair lost frozen criterion/window context')
            mapping=operation['capture_plan']['gameness'][criterion]
            mapping['window_ids'].append(window);mapping['reason']+=' '+addition['reason']
            mapping_changes.append(addition);used.add(window)
    identity=core12.plan_identity(root,current,engine)
    if any(value!=identity[key] for key,value in before['planning_identity'].items() if key!='constraints_sha256'):
        raise ValueError('Recovery changed non-tool planning identity')
    operation['planning_identity']=identity
    operation=batch.validate_operation_plan(root,operation,engine)
    decoded=batch.decode_plan_coverage(original_before)
    if [[s for s in p['steps'] if s['kind']!='wait'] for p in operation['probes']]!=[[s for s in p['steps'] if s['kind']!='wait'] for p in decoded['probes']]:
        raise ValueError('Recovery changed original physical gameplay inputs')
    if operation['probes']!=baseline['probes'] or operation['coverage']!=baseline['coverage']:
        raise ValueError('Recovery changed physical actions or coverage')
    if operation['capture_plan']['windows']!=baseline['capture_plan']['windows']:
        raise ValueError('Recovery changed visual windows')
    dump(root/'sol_plan.json',operation)
    endpoint_sparse.freeze_conditions(root,current,operation);write_operation_report(root,operation)
    freeze_recovered_observer(workspace,current,operation)
    bindings[str(shared_path.resolve())]=sha(shared_path)
    claim=dict(version='mechanic-prerecord-saved-response-recovery.v1',time=stamp(),source=str(source),
        source_bindings=bindings,recovery_root=str(root),original_attempt_preserved=True,
        actions_windows_coverage_unchanged=all(operation[k]==decoded[k] for k in ('probes','coverage')) and operation['capture_plan']['windows']==original_before['capture_plan']['windows'],
        probe_assignments_unchanged=[p['criterion_ids'] for p in operation['probes']]==[p['criterion_ids'] for p in decoded['probes']],
        gameplay_input_values_unchanged=True,scoring_contract_unchanged=True,
        root_cause=error['exception'])
    exclusive_json(claim_source/CLAIM,claim)
    exclusive_json(root/'prerecord_recovery.json',dict(claim,claim_sha256=sha(claim_source/CLAIM),
        operation_sha256=sha(root/'sol_plan.json'),rubric_metadata_changes=rubric_changes,
        schedule_metadata_changes=schedule_changes,window_purpose_additions=mapping_changes,
        observation_schedule_changes=observation_changes,
        reference_metadata_changes=reference_changes,
        full_original_validators=True,model_call_repeated=False,new_native_recording=False))
    dump(root/'stage.json',dict(time=stamp(),stage='EXECUTABLE_NATIVE_PLAN',recovery='saved_response_metadata'))
    return root


def observer_from_response(source, protocol, operation):
    """Retain an original source-only observer; repair only nonliteral quotes."""
    context=(source/'input/requirement.txt').read_text()+'\n'+(source/'input/frozen_rubric.json').read_text()
    requirements={s['id']:s['requirement'] for s in endpoint_sparse.mechanisms(protocol)}
    endpoints={ident:copy.deepcopy(e['rubric']) for ident,e in operation['capture_plan']['endpoints'].items()}
    if set(endpoints)!=set(requirements):raise ValueError('Observer mechanisms differ')
    for ident,rubric in endpoints.items():
        if rubric['requirement']!=requirements[ident]:raise ValueError('Observer changed original requirement')
        if any(text not in context and text!=requirements[ident] for text in rubric['rubric_basis']):
            rubric['rubric_basis']=[requirements[ident]]
    return dict(version=endpoint_sparse.CAPTURE_VERSION,case_id=protocol['case_id'],endpoints=endpoints)


def freeze_recovered_observer(workspace, protocol, operation):
    """Freeze validated pre-record observer metadata under the standard lock."""
    import fcntl
    path=endpoint_sparse.shared_conditions_path(workspace,protocol);path.parent.mkdir(parents=True,exist_ok=True)
    value=dict(version=endpoint_sparse.CAPTURE_VERSION,case_id=protocol['case_id'],
        endpoints={ident:copy.deepcopy(e['rubric']) for ident,e in operation['capture_plan']['endpoints'].items()})
    with path.with_suffix('.lock').open('a') as handle:
        fcntl.flock(handle,fcntl.LOCK_EX)
        if path.exists():
            if read(path)!=value:raise ValueError('Recovered observer conflicts with active shared conditions')
        else:exclusive_json(path,value)
