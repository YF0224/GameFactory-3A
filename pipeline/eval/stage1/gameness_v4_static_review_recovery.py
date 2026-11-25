"""One bounded model correction for a completed, incomplete source review.

All original source bytes, schema and validators are reused. Never fill inspected
IDs or source judgments locally, replace a failed reply or grant runtime credit.
"""
import copy
import hashlib
import json
from pathlib import Path
from . import mechanic_v3_runner as runner
from .codex import READ_ONLY_EVAL_INSTRUCTIONS,call_codex,saved_model_response,validate_schema
from .protocol import sha

VERSION='gameness-v4-complete-static-review-feedback.v1'
ERROR='HARNESS_ERROR: incomplete author source review'


def qualify(folder,policy,schema,prompt,actual,validator):
    folder=Path(folder);root=folder.parent.parent
    if policy.VERSION!='whitebox-gameness10-50-100.v4' or (folder/'accepted_response.json').exists():
        raise ValueError('Only failed original-check v4 source reviews qualify')
    error=runner.read(folder/'validation_error.json')
    if (error.get('phase')!='response_plan_validation' or error.get('exception')!=ERROR
            or error.get('response_sha256')!=sha(folder/'response.json')):
        raise ValueError('Not the exact SHA-bound incomplete source review')
    if runner.read(folder/'schema.json')!=schema or (folder/'prompt.txt').read_text()!=READ_ONLY_EVAL_INSTRUCTIONS+prompt:
        raise ValueError('Original complete source request/schema changed')
    invocation=runner.read(folder/'invocation.json');command=invocation.get('command',[])
    if (invocation.get('exit_code')!=0 or '--model' not in command
            or command[command.index('--model')+1]!=policy.MODEL or '--image' in command
            or actual.get('all_author_sources_delivered') is not True
            or actual.get('runtime_evidence_supplied') is not False
            or actual['prompt_sha256']!=sha(folder/'prompt.txt')):
        raise ValueError('Completed full-source-only original invocation required')
    events=[json.loads(line) for line in (folder/'events.jsonl').read_text().splitlines() if line.strip()]
    if not events or events[-1].get('type')!='turn.completed':
        raise ValueError('Original source review has not completed')
    for path,digest in runner.read(root/'source_binding.json')['author_sources'].items():
        if sha(Path(path))!=digest:raise ValueError('Original author source changed')
    if sha(root/'source_binding.json')!=actual['source_binding_sha256']:
        raise ValueError('Original source binding changed')
    for item in actual['complete_author_sources']:
        if sha(root/item['path'])!=item['sha256']:raise ValueError('Author source bytes changed')
    raw=runner.read(folder/'response.json');validate_schema(raw,schema)
    try:validator(raw)
    except ValueError as error:
        if str(error)!=ERROR:raise ValueError('Current source validator differs') from error
    else:raise ValueError('Valid response must be reused without correction')
    paths=[folder/n for n in ('response.json','schema.json','prompt.txt','validation_error.json','invocation.json','events.jsonl')]
    paths += [root/'source_binding.json',root/'source_manifest.json',root/'citation_rules.json']
    return {str(p):sha(p) for p in paths}


def recover(folder,*,scoring_policy,schema,prompt,actual,validator):
    folder=Path(folder);root=folder.parent.parent
    parents=qualify(folder,scoring_policy,schema,prompt,actual,validator)
    feedback=('\nONE BOUNDED VALIDATOR CORRECTION: '+ERROR+'. The complete original source packet above '
        'is unchanged. Review ALL delivered author source files and return the complete SAME schema '
        'for every check. inspected_source_ids must identify every source actually reviewed. '
        'Do not merely copy the list without reviewing each source. Preserve original check meanings; '
        'no runtime evidence or scores are supplied. No source findings are filled locally.\n')
    submitted=prompt+feedback
    if len(submitted.encode())>1000000:raise ValueError('Full corrected source review exceeds unchanged cap')
    name=folder.name+'_complete_review_feedback_v1'
    code=Path(__file__).resolve()
    claim=dict(version=VERSION,parent_bindings=parents,corrected_task=name,
        production_bindings={str(p):sha(p) for p in [code,code.with_name('gameness_v3_static.py'),code.with_name('gameness_v4.py')]},
        prompt_sha256=hashlib.sha256(submitted.encode()).hexdigest(),schema_unchanged=True,
        validator_unchanged=True,source_packet_unchanged=True,original_failure_preserved=True,local_fields_filled=False)
    path=root/'engineering/complete_static_review_feedback'/folder.name/'claim.json'
    if path.exists():
        if runner.read(path)!=claim:raise ValueError('Retained static correction claim changed')
    else:runner.exclusive_json(path,claim)
    call=root/'model_calls'/name
    if call.exists():
        if not (call/'accepted_response.json').exists():raise ValueError('Bounded correction already attempted; preserve failure')
        if runner.read(call/'schema.json')!=schema or (call/'prompt.txt').read_text()!=READ_ONLY_EVAL_INSTRUCTIONS+submitted:
            raise ValueError('Saved corrected source request changed')
        value=runner.read(saved_model_response(root,name));validator(value)
    else:
        value=call_codex(root,name=name,prompt=submitted,schema=schema,model=scoring_policy.MODEL,
            timeout=900,max_attempts=1,response_validator=validator)
    corrected_actual=copy.deepcopy(actual)
    corrected_actual['prompt_sha256']=sha(call/'prompt.txt')
    corrected_actual['parent_failure']=dict(path=str(folder/'validation_error.json'),sha256=sha(folder/'validation_error.json'))
    from .mechanic_v3_execution import audit_invocation
    audit_invocation(root,name,corrected_actual)
    paths=[path]+[call/n for n in ('response.json','accepted_response.json','prompt.txt','schema.json','invocation.json','events.jsonl','actual_delivery.json')]
    receipt=dict(version=VERSION,parent_bindings=parents,bindings={str(p):sha(p) for p in paths},
        model_recalled=True,original_failure_preserved=True,full_original_validator_passed=True,local_fields_filled=False)
    dest=path.parent/'receipt.json'
    if dest.exists():
        if runner.read(dest)!=receipt:raise ValueError('Retained source correction receipt changed')
    else:runner.exclusive_json(dest,receipt)
    return value,dict(path=str(dest),sha256=sha(dest))
