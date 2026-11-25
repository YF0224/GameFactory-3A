"""One source-bound validator-feedback correction of an invalid v4 judgment.

Preserve the complete failed call. Deliver the same full sources/native images,
unchanged output schema and frozen scoring checks, with concise validator feedback.
No product field is edited, and the original validators decide the new response.
"""
from pathlib import Path
import argparse
import copy
import fcntl
import json
from . import gameness_v3_runtime as runtime, gameness_v4 as policy
from . import mechanic_v3_runner as runner
from .codex import call_codex, saved_model_response, READ_ONLY_EVAL_INSTRUCTIONS, validate_schema
from .protocol import dump, sha

VERSION = 'gameness-v4-bounded-validator-feedback.v1'
SUPPORTED = {'NORMAL lacks actual correct functioning/processing proof', 'Invalid physical line range'}


def physical_range_errors(raw, path=''):
    errors = []
    if isinstance(raw, dict):
        if 'line_start' in raw and 'line_end' in raw:
            start, end = raw['line_start'], raw['line_end']
            if type(start) is not int or type(end) is not int or start > end:
                errors.append(dict(path=path, id=raw.get('id'), line_start=start, line_end=end))
        for key, value in raw.items():
            errors.extend(physical_range_errors(value, path+'/'+key))
    elif isinstance(raw, list):
        for index, value in enumerate(raw):
            errors.extend(physical_range_errors(value, path+'/'+str(index)))
    return errors


def qualify_parent(root, name, schema, prompt, actual, evaluate_response):
    root=Path(root);folder=root/'model_calls'/name
    if (folder/'accepted_response.json').exists():
        raise ValueError('Never correct an accepted response')
    error=runner.read(folder/'validation_error.json')
    if (error.get('phase')!='response_plan_validation' or error.get('exception') not in SUPPORTED
            or error.get('response_sha256')!=sha(folder/'response.json')):
        raise ValueError('Different failure needs a separate source-bound diagnosis')
    if (runner.read(folder/'schema.json')!=schema
            or (folder/'prompt.txt').read_text()!=READ_ONLY_EVAL_INSTRUCTIONS+prompt):
        raise ValueError('Original full request/schema changed')
    if (actual.get('all_predeclared_frames_delivered') is not True
            or actual.get('scoring_protocol')!=policy.VERSION):
        raise ValueError('Original full native delivery is required')
    for item in actual['images']+actual['complete_author_sources']:
        if sha(root/item['path'])!=item['sha256']:
            raise ValueError('Original source/native bytes changed')
    invocation=runner.read(folder/'invocation.json');command=invocation.get('command',[])
    if ('--model' not in command or command[command.index('--model')+1]!=policy.MODEL):
        raise ValueError('Original judge model differs')
    runtime.shared_execution.audit_invocation(root,name,actual)
    raw=runner.read(folder/'response.json');validate_schema(raw,schema)
    if error['exception']=='Invalid physical line range':
        diagnosis=physical_range_errors(raw)
        if not diagnosis:raise ValueError('No exact invalid physical range in the retained response')
        error=dict(error,citation_diagnosis=diagnosis)
    try:
        evaluate_response(raw)
    except ValueError as failure:
        if str(failure)!=error['exception']:
            raise ValueError('Current validator differs from the preserved failure') from failure
    else:
        raise ValueError('Response now validates; revalidate without recalling the model')
    files=[folder/p for p in ('response.json','schema.json','prompt.txt','validation_error.json','invocation.json')]
    files.append(root/'requests'/name/'actual_delivery.json')
    return error,{str(p.resolve()):sha(p) for p in files}


def correction_prompt(prompt, old_name, new_name, root, error, specs):
    # The old response stays fully preserved in lineage, not redundantly pasted
    # into the near-capacity request. Feedback cannot prescribe a credit/tier.
    old=str(Path(root)/'model_calls'/old_name/'schema.json')
    new=str(Path(root)/'model_calls'/new_name/'schema.json')
    text=prompt.replace(old,new)
    feedback=('\nVALIDATOR FEEDBACK FOR ONE BOUNDED CORRECTION: '+error['exception']+
        '. Re-evaluate only these same frozen checks from the attached actual native images and full sources. '
        'Every claimed NORMAL/BUG must have the required actual runtime proof and valid citations; '
        'source existence alone is not proof that runtime function worked. Where runtime is unproven, '
        'report the schema-defined unobserved/insufficient state. No requested score or tier. '
        'Retain original criterion identities and requirements. Checks: '+','.join(s['id'] for s in specs)+'.\n')
    if error['exception']=='Invalid physical line range':
        feedback=('\nVALIDATOR FEEDBACK FOR ONE BOUNDED CORRECTION: Invalid physical line range. '
            'The retained response used these invalid citation ranges: '+json.dumps(error.get('citation_diagnosis',[]),ensure_ascii=False)+
            '. Re-evaluate the same frozen checks from all attached original native images and complete sources. '
            'Citations require integer line_start <= line_end within the actually delivered original evidence lines; '
            'image citations require 0,0. Do not invent a line or silently reorder the old citation: '
            'choose supporting evidence after checking the complete original delivery. '
            'Return the unchanged schema and criterion identities. No requested score or tier. '
            'Checks: '+','.join(s['id'] for s in specs)+'.\n')
    return text+feedback


def evaluate_task(workspace,root,protocol,manifest,contract,frozen,task,review):
    name,parent,specs=runtime.selected_task(root,task)
    failed=root/'model_calls'/name
    if not (failed/'validation_error.json').is_file() or (failed/'accepted_response.json').is_file():
        return runtime.evaluate_task(workspace,root,protocol,manifest,contract,frozen,task,review=review,scoring_policy=policy)
    selected,rules,images,schema,prompt=runtime.request(root,protocol,manifest,contract,frozen,name,parent,specs,review=review,scoring_policy=policy)
    if runtime.independent.active(protocol) or review is None or 'gameness_rubric' in protocol:
        raise ValueError('This correction requires the independent original-check first-stage source review')
    evaluate=lambda raw:runtime.original_rubric.evaluate(root,protocol,selected,rules,contract,raw,specs,review,scoring_policy=policy)
    actual=runner.read(root/'requests'/name/'actual_delivery.json')
    error,bindings=qualify_parent(root,name,schema,prompt,actual,evaluate)
    recovered=name+'_validator_feedback_v1'
    claim_path=root/'engineering/gameness_validator_feedback'/(name+'.json')
    claim=dict(version=VERSION,parent_task=name,recovery_task=recovered,bindings=bindings,
        implementation_bindings={str(Path(__file__).resolve()):sha(Path(__file__))},
        root_cause=error['exception'],maximum_corrections=1,parent_failure_preserved=True,
        scoring_semantics_unchanged=True,all_sources_and_native_images_preserved=True)
    preflight=None
    if claim_path.exists():
        previous=runner.read(claim_path)
        if previous!=claim:
            preflight_path=root/'engineering/gameness_validator_feedback_preflight'/(name+'.json')
            preflight=runner.read(preflight_path)
            if (any(previous[k]!=claim[k] for k in claim if k!='implementation_bindings')
                    or preflight.get('parent_claim_sha256')!=sha(claim_path)
                    or preflight.get('before_implementation_bindings')!=previous['implementation_bindings']
                    or preflight.get('after_implementation_bindings')!=claim['implementation_bindings']
                    or preflight.get('model_invoked') is not False):
                raise ValueError('Existing bounded correction lineage changed')
            runtime.verify_bindings(preflight['retained_before_bindings'])
            claim=previous
    else:
        runner.exclusive_json(claim_path,claim)
    submitted=correction_prompt(prompt,name,recovered,root,error,specs)
    native_protocol=runner.read(root/'input/pilot_rubric.json')
    validation=runtime.frame_budget.validate_request(root,parent,native_protocol,selected,images,READ_ONLY_EVAL_INSTRUCTIONS+submitted)
    delivered=dict(actual,**validation,task=recovered,parent_task=name,
        validator_feedback_lineage=dict(path=str(claim_path),sha256=sha(claim_path)))
    if preflight is not None:
        delivered['validator_feedback_preflight_repair']=dict(path=str(preflight_path),sha256=sha(preflight_path))
    request_dir=root/'requests'/recovered
    for artifact in ('selected_manifest.json','citation_rules.json','original_schema.json','schema_transport.json'):
        dump(request_dir/artifact,runner.read(root/'requests'/name/artifact))
    dump(request_dir/'actual_delivery.json',delivered)
    call=root/'model_calls'/recovered
    if call.exists():
        if not (call/'accepted_response.json').is_file():
            raise ValueError('Bounded correction already attempted; preserve its failure, no unchanged retry')
        if (runner.read(call/'schema.json')!=schema or
                (call/'prompt.txt').read_text()!=READ_ONLY_EVAL_INSTRUCTIONS+submitted):
            raise ValueError('Accepted correction request changed')
        raw=runner.read(saved_model_response(root,recovered))
    else:
        try:
            raw=call_codex(root,name=recovered,prompt=submitted,schema=schema,images=images,
                model=policy.MODEL,timeout=900,max_attempts=1,explicit_stdin_separator=True,response_validator=evaluate)
        except Exception as failure:
            dump(root/'failures'/(recovered+'.json'),dict(time=runner.stamp(),category='HARNESS_ERROR',
                exception=repr(failure),product_score=None,parent_failure_preserved=True,
                next_action='Inspect distinct corrected-response failure; bounded correction cannot repeat unchanged'))
            raise
    runtime.shared_execution.audit_invocation(root,recovered,delivered)
    checks=evaluate(raw)
    dump(root/'judgments'/(recovered+'.json'),dict(protocol=policy.VERSION,task=recovered,raw=raw,checks=checks,
        actual_delivery_sha256=sha(request_dir/'actual_delivery.json'),response_path=str(saved_model_response(root,recovered)),
        response_sha256=sha(saved_model_response(root,recovered)),correction_lineage=claim))
    print(json.dumps(dict(identity=root.name,stage='GAMENESS_VALIDATOR_CORRECTION_COMPLETE',task=recovered)),flush=True)
    return checks


def continue_judge(workspace,identity):
    inventory=runtime.load(workspace)
    rows=[r for r in inventory['entries'] if r['in_scope'] and r['entry']['id']==identity]
    if len(rows)!=1:raise ValueError('One selected frozen original identity required')
    if runtime.publication_path(workspace,identity).exists():return runtime.verify_publication(workspace,identity)
    row=rows[0];root=workspace/'runs'/identity
    runner.configure_cli(Path(row['source_batch']))
    runtime.batch.verify_inputs(root)
    qualification=runner.read(root/'source_qualification.json');runtime.verify_bindings(qualification['source_bindings'])
    if not runtime.scope.same_original(row['entry'],runner.read(root/'input_manifest.json')['entry']):
        raise ValueError('Original source identity changed')
    folder=runtime.contract_dir(workspace,row['entry']['case_id'])
    contract=runtime.freeze(workspace,row['entry']['case_id'],inventory);frozen=runner.read(folder/'frozen.json')
    review=runner.read(root/'gameness_source_review.json');source_binding=runner.read(root/'gameness_source_review_binding.json')
    runtime.verify_bindings(source_binding['bindings'])
    if sha(Path(source_binding['path']))!=source_binding['sha256']:raise ValueError('First-stage source review changed')
    protocol=runtime.authored_rubric.protocol_for_run(root);manifest=runner.read(root/'evidence_manifest.json')
    native=runner.read(root/'input/pilot_rubric.json');specs=policy.criteria(protocol)
    tasks=[];seen=set()
    for parent,subset in manifest['evidence_sets'].items():
        part=[s for s in specs if s['id'] in subset['criterion_ids']]
        for offset in range(0,len(part),5):
            chunk=part[offset:offset+5];ids={s['id'] for s in chunk}
            if ids & seen:raise ValueError('Duplicate original runtime checks')
            seen.update(ids);tasks.append((f'gameness_v4_of1_{len(tasks)+1:02d}',parent,chunk))
    tiered=runtime.authored_rubric.runtime_tasks(protocol,manifest,native)
    if tiered is not None:
        tasks=tiered;seen={s['id'] for _,_,part in tasks for s in part}
    if seen!={s['id'] for s in specs}:raise ValueError('Incomplete original runtime checks')
    runner.disk(root,'gameness_validator_correction',1024**3)
    checks={}
    for task in tasks:
        checks.update(evaluate_task(workspace,root,protocol,manifest,contract,frozen,task,review))
    result=policy.aggregate(protocol,checks);dump(root/'gameness_score.json',result)
    dump(root/'gameness_coverage.json',runtime.static_review.coverage_report(review,checks))
    with runner.held(workspace,Path(row['source_batch']),native=False) as guard:
        runtime.publish(workspace,root,result,guard)
    return runtime.verify_publication(workspace,identity)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace',type=Path,required=True);parser.add_argument('--identity',required=True)
    parser.add_argument('--acceptance-case',action='store_true');args=parser.parse_args(argv)
    workspace=args.workspace.resolve()
    if runtime.workspace_policy(workspace).VERSION!=policy.VERSION:raise ValueError('V4 workspace required')
    before=runtime.production_bindings() if args.acceptance_case else None
    if before is None:runtime.production_gate(workspace)
    lock=workspace/'locks'/('gameness_v4_'+args.identity+'.lock');lock.parent.mkdir(parents=True,exist_ok=True)
    with lock.open('a+') as handle:
        fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        value=continue_judge(workspace,args.identity)
        if before is not None:runtime.accept_real_case(workspace,args.identity,before)
    print(json.dumps(dict(identity=args.identity,stage=value['status'],score=value['gameness_score'])),flush=True)
    return 0

if __name__=='__main__':raise SystemExit(main())
