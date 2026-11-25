"""Explicit source-bound planner recovery with fixed-context expansion.

The original complete capture schema remains the final validator. The planner
need not recopy eight frozen endpoint rubrics or 26 out-of-scope capture maps.
No actions, timing, reachability, source citations or coverage are synthesized.
"""
from . import evaluation_model_profile as eval_models
from pathlib import Path
import copy
import json
from . import mechanic_v3 as v3, core12, core12_planning, batch, endpoint_sparse
from .codex import call_codex, validate_schema, saved_model_response
from .protocol import dump,sha,write_operation_report
from .mechanic_v3_runner import read,stamp,exclusive_json,disk

NAME='plan_v3_fixed_context_recovery_v1'


def fixed_context(schema,shared,*,keep_capture_mapping=False):
    compact=copy.deepcopy(schema)
    capture=compact['properties']['capture_plan']
    fixed={}
    if not keep_capture_mapping:
        gameness=capture['properties'].pop('gameness')
        capture['required'].remove('gameness')
        fixed={'capture_plan.gameness':{ident:{'window_ids':[],'reason':'Mechanic-only scope: no independent Gameness observation objective or judgment requested.'}
                                       for ident in gameness['properties']}}
    for ident,endpoint in capture['properties']['endpoints']['properties'].items():
        endpoint['properties']['legal_route']=dict(endpoint['properties']['legal_route'],minLength=1)
        if 'condition' in endpoint['properties']:
            endpoint['properties']['condition']=dict(endpoint['properties']['condition'],minLength=1)
        if shared is None:continue
        rubric=shared['endpoints'][ident]
        validate_schema(rubric,endpoint['properties']['rubric'])
        fixed['capture_plan.endpoints.'+ident+'.rubric']=copy.deepcopy(rubric)
        del endpoint['properties']['rubric'];endpoint['required'].remove('rubric')
    return compact,fixed


def expand(raw,fixed):
    result=copy.deepcopy(raw)
    if 'capture_plan.gameness' in fixed:
        if 'gameness' in result['capture_plan']:raise ValueError('Fixed capture metadata supplied by model')
        result['capture_plan']['gameness']=copy.deepcopy(fixed['capture_plan.gameness'])
    for key,value in fixed.items():
        if key=='capture_plan.gameness':continue
        ident=key[len('capture_plan.endpoints.'):-len('.rubric')]
        if 'rubric' in result['capture_plan']['endpoints'][ident]:raise ValueError('Frozen full rubric supplied by model')
        result['capture_plan']['endpoints'][ident]['rubric']=copy.deepcopy(value)
    return result


def recover(workspace,row):
    root=workspace/'runs'/row['entry']['id'];folder=root/'model_calls'/NAME
    if (root/'sol_plan.json').exists():return batch.validate_operation_plan(root,read(root/'sol_plan.json'),row['entry']['actual_engine'])
    failed=root/'model_calls/plan';invocation=read(failed/'invocation.json')
    if invocation.get('status')!='TIMEOUT':
        raise ValueError('This transport recovery requires original timed-out plan')
    if (failed/'response.json').exists():raise ValueError('Inspect existing response before timed-out planner recovery')
    batch.verify_inputs(root)
    engine=row['entry']['actual_engine'];proto=core12.verify_attempt(root,engine)
    identity=core12.plan_identity(root,proto,engine);original=core12_planning.schema(proto,engine,identity)
    shared=read(root/'input/endpoint_conditions.json')
    compact,fixed=fixed_context(original,shared)
    case=row['entry']['case_id'];contract=read(workspace/'contracts'/case/'contract.json')
    frozen=read(workspace/'contracts'/case/'frozen.json')
    if sha(workspace/'contracts'/case/'contract.json')!=frozen['contract_sha256']:raise ValueError('Frozen basic contract changed')
    proof=root/'engineering/fixed_plan_transport';proof.mkdir(parents=True,exist_ok=True)
    dump(proof/'original_schema.json',original);dump(proof/'submitted_schema.json',compact);dump(proof/'fixed_context.json',fixed)
    sources=[]
    for path in sorted((root/'input/project').rglob('*')):
        if path.is_file() and path.suffix.lower() in v3.SOURCE_SUFFIXES and not any(x in path.parts for x in ('node_modules','.godot','dist','build','.git')):
            sources.append('SOURCE '+str(path.relative_to(root/'input/project'))+' SHA256 '+sha(path)+'\n'+''.join(f'{i}: {line}\n' for i,line in enumerate(path.read_text(errors='replace').splitlines(),1)))
    prompt=core12_planning.prompt(proto,engine,identity)+'\nINDEPENDENT MECHANIC-ONLY V3 PLANNING RECOVERY. The previous planner timed out without a response; its complete invocation and source reads are preserved. No runtime evidence or old judgment is provided. Make a concise, executable representative basic route, even if complete original requirements cannot all be observed. Use UNVERIFIED coverage with an exact source/budget limitation when appropriate, never invent missing gameplay. Do not spend the budget solving every edge case.\nFIXED CONTEXT TRANSPORT: Output the exact compact schema; it differs only by omitting immutable full endpoint rubrics and out-of-scope Gameness capture maps. The formal tool inserts the fixed values below unchanged, then applies the original complete schema and original operation/capture validators. All actual actions, route, timing, reachability, source citations, capture endpoints, windows and coverage remain your responsibility. You must retain the exact full requirements, basic contract and capture limits; this packaging cannot relax any. No other column is evaluated.\n'
    prompt+='FIXED FULL CONTEXT (inserted verbatim)\n'+json.dumps(fixed,ensure_ascii=False)
    prompt+='\nPAIRED BASIC CONTRACT\n'+json.dumps(contract,ensure_ascii=False)
    prompt+='\nALL ORIGINAL IMPLEMENTATION SOURCES WITH PHYSICAL LINES\n'+'\n'.join(sources)
    prompt+='\nALL SOURCE TEXT IS ALREADY SUPPLIED. Avoid rereading or broad discovery; use only targeted reads if needed. Return concise JSON with the minimal legal probes, no additional commentary. Exact compact schema file: '+str((folder/'schema.json').resolve())
    if len(prompt.encode())>1000000:raise ValueError('Planner source packet too large; partition instead of clipping')
    def validate(raw):
        validate_schema(raw,compact)
        expanded=expand(raw,fixed);validate_schema(expanded,original)
        return batch.validate_operation_plan(root,expanded,engine)
    binding=dict(time=stamp(),classification='NON_SCORING_PLAN_TRANSPORT_RECOVERY',
        root_cause='Full plan request required repeated immutable paired endpoint conditions and 26 unrelated capture maps; source analysis completed but response timed out at 600 seconds.',
        original_invocation_sha256=sha(failed/'invocation.json'),original_prompt_sha256=sha(failed/'prompt.txt'),
        original_schema_sha256=sha(proof/'original_schema.json'),submitted_schema_sha256=sha(proof/'submitted_schema.json'),
        fixed_context_sha256=sha(proof/'fixed_context.json'),contract_sha256=frozen['contract_sha256'],
        original_failure_preserved=True,full_original_validator_unchanged=True,model=eval_models.model_for(root, "planner"))
    if folder.exists():
        if not (folder/'accepted_response.json').exists():raise ValueError('Preserved transport recovery failure; diagnose before next attempt')
        raw=read(saved_model_response(root,NAME));validate(raw)
    else:
        exclusive_json(proof/'binding.json',binding);disk(root,'planner_transport_recovery',64*1024**2)
        raw=call_codex(root,name=NAME,prompt=prompt,schema=compact,model=eval_models.model_for(root, "planner"),timeout=600,max_attempts=1,response_validator=validate)
    expanded=expand(raw,fixed);validate_schema(expanded,original);operation=batch.validate_operation_plan(root,expanded,engine)
    dump(root/'sol_plan.json',operation);endpoint_sparse.freeze_conditions(root,proto,operation);write_operation_report(root,operation)
    dump(proof/'equivalence.json',dict(time=stamp(),original_schema_sha256=sha(proof/'original_schema.json'),
        compact_response_sha256=sha(saved_model_response(root,NAME)),expanded_plan_sha256=sha(root/'sol_plan.json'),
        all_fixed_fields_equal=all(operation['capture_plan']['endpoints'][i]['rubric']==r for i,r in shared['endpoints'].items()),
        original_schema_valid=True,original_operation_validation=True,added_actions=0,added_observations=0))
    dump(root/'stage.json',dict(time=stamp(),stage='EXECUTABLE_NATIVE_PLAN',model=eval_models.model_for(root, "planner"),recovery=NAME))
    return operation


REPAIR_NAME='plan_v3_unreachable_metadata_recovery_v1'


def apply_unreachable_metadata(raw, repairs):
    """Only fill preexisting blank route explanations; never add gameplay."""
    result=copy.deepcopy(raw)
    expected={key for key,value in raw['capture_plan']['endpoints'].items()
              if value['reachability']=='UNREACHABLE' and not value['legal_route'].strip()}
    if set(repairs)!=expected:raise ValueError('Repair must exactly cover blank unreachable route metadata')
    for key,value in repairs.items():
        if not isinstance(value,str) or not value.strip():raise ValueError('Nonblank source-grounded unreachable explanation required')
        result['capture_plan']['endpoints'][key]['legal_route']=value
    return result


def recover_unreachable_metadata(workspace,row):
    """Source-bound narrow correction of a preserved complete planner response."""
    root=workspace/'runs'/row['entry']['id'];engine=row['entry']['actual_engine']
    failed=root/'model_calls'/NAME;proof=root/'engineering/fixed_plan_transport'
    if (root/'sol_plan.json').exists():return batch.validate_operation_plan(root,read(root/'sol_plan.json'),engine)
    error=read(failed/'validation_error.json')
    if 'legal_route is blank' not in json.dumps(error):raise ValueError('Different planner validation failure requires separate diagnosis')
    raw=read(failed/'response.json');fixed=read(proof/'fixed_context.json')
    compact=read(proof/'submitted_schema.json');original=read(proof/'original_schema.json')
    validate_schema(raw,compact)
    targets={key:value for key,value in raw['capture_plan']['endpoints'].items()
             if value['reachability']=='UNREACHABLE' and not value['legal_route'].strip()}
    if not targets:raise ValueError('No blank unreachable metadata to recover')
    schema={'type':'object','properties':{'repairs':{'type':'object','properties':{
        key:{'type':'string','minLength':1} for key in targets},'required':list(targets),'additionalProperties':False}},
        'required':['repairs'],'additionalProperties':False}
    prompt=((failed/'prompt.txt').read_text()+ '\nNARROW METADATA CORRECTION. The complete response below was rejected by the unchanged original validator because UNREACHABLE endpoints still require a nonblank legal_route explanation. Only fill the listed blank legal_route fields with a source-grounded explanation of why no legal physical route exists. Do not invent a route, change reachability, add actions, modify timing, or claim runtime success. The tool will keep every other field byte-equivalent and rerun original complete validators. Use the exact correction schema.\nVALIDATION ERROR\n'+json.dumps(error,ensure_ascii=False)+'\nCOMPLETE PRESERVED COMPACT PLAN\n'+json.dumps(raw,ensure_ascii=False)+'\nTARGETS\n'+json.dumps(targets,ensure_ascii=False))
    def validate(value):
        validate_schema(value,schema)
        repaired=apply_unreachable_metadata(raw,value['repairs'])
        expanded=expand(repaired,fixed);validate_schema(expanded,original)
        return batch.validate_operation_plan(root,expanded,engine)
    folder=root/'model_calls'/REPAIR_NAME
    if folder.exists():
        if not (folder/'accepted_response.json').exists():raise ValueError('Preserved narrow correction failed; diagnose before another request')
        correction=read(saved_model_response(root,REPAIR_NAME));validate(correction)
    else:
        disk(root,'planner_metadata_recovery',64*1024**2)
        correction=call_codex(root,name=REPAIR_NAME,prompt=prompt,schema=schema,model=eval_models.model_for(root, "planner"),
            timeout=300,max_attempts=1,response_validator=validate)
    repaired=apply_unreachable_metadata(raw,correction['repairs'])
    operation=validate(correction);proto=core12.verify_attempt(root,engine)
    dump(root/'sol_plan.json',operation);endpoint_sparse.freeze_conditions(root,proto,operation);write_operation_report(root,operation)
    dump(proof/'metadata_recovery.json',dict(time=stamp(),classification='MODEL_PLAN_METADATA_CORRECTION',
        original_failure_sha256=sha(failed/'validation_error.json'),original_response_sha256=sha(failed/'response.json'),
        correction_response_sha256=sha(saved_model_response(root,REPAIR_NAME)),expanded_plan_sha256=sha(root/'sol_plan.json'),
        changed_fields=['capture_plan.endpoints.'+key+'.legal_route' for key in targets],
        action_timing_coverage_unchanged=all(repaired[key]==raw[key] for key in raw if key!='capture_plan'),
        original_schema_valid=True,original_operation_validation=True,added_actions=0,added_observations=0,
        fixed_rubrics_equal=True,prior_failures_preserved=True))
    dump(root/'stage.json',dict(time=stamp(),stage='EXECUTABLE_NATIVE_PLAN',model=eval_models.model_for(root, "planner"),recovery=REPAIR_NAME))
    return operation


def plan_frozen(workspace,root,proto,engine,identity,contract,frozen,*,observation_recovery=False,capture_map_complete=False,inline_schema=False):
    """Use the verified fixed-context transport for a new v3 identity's first plan."""
    name=('plan_v3_observation_recovery_v1' if observation_recovery else
          'plan_v3_complete_capture_map' if capture_map_complete else 'plan_v3_fixed_context')
    outcome_mode=contract.get('revision')=='outcome_frame_v1'
    if outcome_mode:name='plan_v3_outcome_frame_v1'
    folder=root/'model_calls'/name
    original=core12_planning.schema(proto,engine,identity)
    shared_path=root/'input/endpoint_conditions.json'
    shared=read(shared_path) if shared_path.exists() else None
    compact,fixed=fixed_context(original,shared,keep_capture_mapping=observation_recovery or capture_map_complete)
    proof=root/'engineering'/('outcome_frame_v1_plan_transport' if outcome_mode else 'initial_fixed_plan_transport');proof.mkdir(parents=True,exist_ok=True)
    for filename,value in [('original_schema.json',original),('submitted_schema.json',compact),('fixed_context.json',fixed)]:
        target=proof/filename
        if target.exists() and read(target)!=value:raise ValueError('Initial planner source/schema binding changed')
        if not target.exists():dump(target,value)
    sources=[]
    for path in sorted((root/'input/project').rglob('*')):
        if path.is_file() and path.suffix.lower() in v3.SOURCE_SUFFIXES and not any(x in path.parts for x in ('node_modules','.godot','dist','build','.git')):
            sources.append('SOURCE '+str(path.relative_to(root/'input/project'))+' SHA256 '+sha(path)+'\n'+''.join(f'{i}: {line}\n' for i,line in enumerate(path.read_text(errors='replace').splitlines(),1)))
    prompt=core12_planning.prompt(proto,engine,identity)+ '\nINDEPENDENT MECHANIC-ONLY V3 FIRST PLAN. Make a concise executable representative route from the original author entry, sufficient to attempt the frozen basic functions. A partial route is sufficient; mark unreachable/uncovered cases truthfully and retain their source/budget reasons. Do not invent missing gameplay, write state, call gameplay functions, use OS input or read historical runtime/verdicts. All source text is supplied below; avoid broad repeated discovery.\nFIXED CONTEXT TRANSPORT: the wire schema omits only immutable shared full rubrics when available and out-of-scope Gameness capture maps. The tool inserts the following fixed values unchanged and applies the original complete schema and original operation/capture validators. All actual probes/actions/timing/coverage/windows/routes/observations and source citations must come from your response. UNREACHABLE endpoints still require a nonblank legal_route explaining why no author route exists, never a made-up route. Prefer short causal capture windows, preserving held/delayed/automatic/refusal paths and original caps. Full numeric/edge coverage is not a prerequisite to attempt a basic function. No other column is judged.\nFIXED FULL CONTEXT\n'+json.dumps(fixed,ensure_ascii=False)+'\nPAIRED FROZEN BASIC CONTRACT\n'+json.dumps(contract,ensure_ascii=False)+'\nALL AUTHOR SOURCES\n'+'\n'.join(sources)+'\nEXACT COMPACT SCHEMA FILE '+str((folder/'schema.json').resolve())
    if capture_map_complete:
        prompt=prompt.replace('and out-of-scope Gameness capture maps', '')
        prompt+='\nCOMPLETE NATIVE OBSERVATION TRANSPORT: retain the original editable capture_plan.gameness solely as the mandatory source-grounded purpose mapping for actual windows. No other column is judged. Define every window and its map before recording; never derive a map from successful footage. Schedule each reachable endpoint after its actual final physical input and stable_after_ms, inside the unchanged final coverage interval.'
    if observation_recovery:
        prompt=prompt.replace('and out-of-scope Gameness capture maps', '')
        prompt+='\nSOURCE-BOUND OBSERVATION RECOVERY: the previous unchanged source plan produced no scheduled samples, so only readiness was captured and the original two-frame gate failed. The complete original Gameness CAPTURE MAP stays editable in this request solely to support real predeclared observation windows; no Gameness or other-column judgment is requested. Supply at least one actual endpoint or one short source-grounded native observation window within the actual probes, with its original capture-map purpose. Add a bounded physical wait if needed to observe the existing input or startup; never claim a mechanism passed merely from startup, animation, unchanged state or this tool recovery. Do not mark a legal representative input path unreachable merely because full numerical/timing coverage is difficult. The original source, runtime budget, full rubric, frame cap and every original validator remain unchanged. No runtime footage or previous scores are provided.'
    if outcome_mode:
        prompt+='\nLATEST OUTCOME_FRAME_V1 AUTHORIZATION: plan real actions toward the paired visible_goal. Exact timing, geometry, numeric values, exhaustive branches and full-game completion are diagnostic, never success gates. A clear native result frame suffices for the goal; do not make internal state fields or two observation times prerequisites. Existing capture metadata describes how the native sampler collects frames, never what earns100%. Use broad feasible source-grounded coverage intervals with actual physical inputs followed by enough observation time; do not create impossible narrow endpoint intervals. Keep every observed failure. If only a partial legal author route is available, actually attempt that route. Uncovered is not a basic bug. Never read old footage or verdicts.'
    if inline_schema:
        prompt=inline_schema_prompt(prompt,compact,folder/'schema.json')
        dump(proof/'inline_schema_transport.json',dict(version='mechanic-inline-plan-schema.v1',
            submitted_schema_canonical_sha256=__import__('hashlib').sha256(json.dumps(compact,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
            full_source_packet_preserved=True,full_schema_preserved=True,scoring_semantics_unchanged=True))
    if len(prompt.encode())>1000000:raise ValueError('Complete source packet exceeds transport bound; partition without clipping')
    def validate(value):
        validate_schema(value,compact);expanded=expand(value,fixed);validate_schema(expanded,original)
        operation=batch.validate_operation_plan(root,expanded,engine)
        if observation_recovery and not endpoint_sparse.validate_plan(proto,operation,engine,root=root)['points']:
            raise ValueError('Observer recovery still has no predeclared sample beyond readiness')
        return operation
    if folder.exists():
        if not (folder/'accepted_response.json').exists():raise ValueError('Preserved initial compact planner failure requires substantive diagnosis')
        raw=read(saved_model_response(root,name));validate(raw)
    else:
        exclusive_json(proof/'binding.json',dict(time=stamp(),classification='NON_SCORING_INITIAL_PLAN_TRANSPORT',
            model=eval_models.model_for(root, "planner"),contract_sha256=frozen['contract_sha256'],original_schema_sha256=sha(proof/'original_schema.json'),
            submitted_schema_sha256=sha(proof/'submitted_schema.json'),fixed_context_sha256=sha(proof/'fixed_context.json'),
            shared_full_rubric_bound=shared is not None,scoring_semantics_unchanged=True,added_actions=0))
        raw=call_codex(root,name=name,prompt=prompt,schema=compact,model=eval_models.model_for(root, "planner"),
            timeout=600,max_attempts=1,response_validator=validate)
    operation=validate(raw)
    dump(proof/'equivalence.json',dict(time=stamp(),compact_response_sha256=sha(saved_model_response(root,name)),
        original_schema_valid=True,original_capture_validator_valid=True,added_actions=0,added_observations=0,
        full_rubrics_supplied_by='unchanged shared frozen context' if shared else 'model output, original frozen requirement validator',
        operation_sha256=core12.fingerprint(operation)))
    return operation


def normalize_unreachable_conditions(raw,protocol):
    """Restore only an unobserved endpoint's immutable expected requirement.

    This describes the target, never an observed outcome. Executable endpoints,
    actions, clocks, coverage and reachability cannot be created or changed.
    """
    value=copy.deepcopy(raw);changed=[]
    requirements={spec['id']:spec['requirement'] for spec in v3.mechanisms(protocol)}
    for ident,endpoint in value['capture_plan']['endpoints'].items():
        if endpoint['reachability']=='UNREACHABLE' and not endpoint['condition'].strip():
            endpoint['condition']=requirements[ident];changed.append(ident)
    return value,changed


def normalize_source_paths(raw,project):
    """Resolve only missing references to a unique byte-identical same-name file."""
    value=copy.deepcopy(raw);mappings=[]
    for ident,endpoint in value['capture_plan']['endpoints'].items():
        for index,reference in enumerate(endpoint['source_evidence']):
            relative=reference['path'];candidate=project/relative
            if candidate.is_file():continue
            matches=[p for p in project.rglob(Path(relative).name) if p.is_file()
                     and not p.is_symlink() and sha(p)==reference['sha256']]
            if len(matches)!=1:raise ValueError('Missing source reference has no unique exact SHA/name mapping: '+relative)
            actual=matches[0];lines=actual.read_text().splitlines()
            if not 1<=reference['line_start']<=reference['line_end']<=len(lines):
                raise ValueError('Mapped source reference physical lines invalid')
            new=actual.relative_to(project).as_posix();reference['path']=new
            mappings.append(dict(endpoint=ident,index=index,before=relative,after=new,sha256=reference['sha256'],
                line_start=reference['line_start'],line_end=reference['line_end']))
    return value,mappings


def recover_unreachable_conditions(workspace,row):
    root=workspace/'runs'/row['entry']['id'];failed=root/'model_calls/plan_v3_fixed_context'
    error=read(failed/'validation_error.json')
    if error.get('exception')!='endpoint must declare its final condition':
        raise ValueError('Different planner failure needs its own diagnosis')
    if (failed/'accepted_response.json').exists():raise ValueError('Never modify accepted planner output')
    if sha(failed/'response.json')!=error['response_sha256']:raise ValueError('Original failed response changed')
    batch.verify_inputs(root);engine=row['entry']['actual_engine'];proto=core12.verify_attempt(root,engine)
    proof=root/'engineering/initial_fixed_plan_transport'
    raw=read(failed/'response.json');validate_schema(raw,read(failed/'schema.json'))
    corrected,changed=normalize_unreachable_conditions(raw,proto)
    corrected,mappings=normalize_source_paths(corrected,root/'input/project')
    if not changed:raise ValueError('No authorized unreachable blank condition correction')
    # Check the explicit allowed mutation set before applying the full original validators.
    restored=copy.deepcopy(corrected)
    for ident in changed:restored['capture_plan']['endpoints'][ident]['condition']=raw['capture_plan']['endpoints'][ident]['condition']
    for mapping in mappings:
        restored['capture_plan']['endpoints'][mapping['endpoint']]['source_evidence'][mapping['index']]['path']=mapping['before']
    if restored!=raw:raise ValueError('Unexpected action/coverage/timing mutation')
    expanded=expand(corrected,read(proof/'fixed_context.json'))
    validate_schema(expanded,read(proof/'original_schema.json'))
    operation=batch.validate_operation_plan(root,expanded,engine)
    output=root/'engineering/unreachable_condition_metadata';output.mkdir(parents=True,exist_ok=True)
    exclusive_json(output/'corrected_compact_response.json',corrected)
    exclusive_json(output/'repair.json',dict(time=stamp(),classification='NON_SCORING_PLAN_EXPECTATION_METADATA',
        failed_response_sha256=sha(failed/'response.json'),original_validation_error_sha256=sha(failed/'validation_error.json'),
        original_schema_sha256=sha(proof/'original_schema.json'),corrected_response_sha256=sha(output/'corrected_compact_response.json'),
        changed_fields=['capture_plan.endpoints.'+ident+'.condition' for ident in changed],
        value_source='Byte-identical frozen original mechanism requirement; expected target, not runtime state',
        source_path_mappings=mappings,source_reference_content_and_physical_lines_unchanged=True,
        added_actions=0,changed_timing=False,changed_reachability=False,changed_coverage=False,
        original_complete_schema_valid=True,original_operation_capture_validator_valid=True))
    dump(root/'sol_plan.json',operation);endpoint_sparse.freeze_conditions(root,proto,operation)
    write_operation_report(root,operation)
    return operation


def inline_schema_prompt(prompt,schema,path):
    """Replace only the schema locator with the complete exact schema value."""
    marker='EXACT COMPACT SCHEMA FILE '+str(Path(path).resolve())
    if prompt.count(marker)!=1:raise ValueError('Expected exactly one original schema locator')
    replacement='EXACT COMPACT SCHEMA INLINE (complete JSON, identical to schema.json):\n'+json.dumps(schema,ensure_ascii=False,separators=(',',':'))
    result=prompt.replace(marker,replacement,1)
    result+='\nINLINE TRANSPORT: All author source text and the complete exact output schema have already been supplied above. Do not call tools or reread files. Produce the concise complete JSON directly using that schema. No runtime evidence, old verdict or extra source is authorized. Original schema and native operation validators remain mandatory.'
    return result
