"""One source-only continuation after a proved terminal 401 and restored service.

The old invocation and every source chunk remain immutable. A newer accepted
same-model/same-CLI invocation is required; all chunks must be delivered anew.
"""
from datetime import datetime
from pathlib import Path
import json
from . import mechanic_v3_runner as runner
from . import gameness_v4_contract_chunks as chunks
from . import gameness_v4 as policy
from .protocol import sha
from .codex import READ_ONLY_EVAL_INSTRUCTIONS, call_codex, saved_model_response

VERSION = 'gameness-v4-terminal-401-source-contract-continuation.v1'
AUTH = 'engineering/source_contract_service_recovery/authorization.json'
PARENT = 'gameness_v4_source_contract'
TASK = PARENT + '_restored_service_v1'


def terminal_failure(call):
    call=Path(call)
    if any((call/n).exists() for n in ('response.json','accepted_response.json')):
        raise ValueError('Never replace any contract response')
    inv=runner.read(call/'invocation.json')
    if (inv.get('exit_code')!=1 or inv.get('response_present') is not False
            or inv.get('attempt')!=1 or inv.get('model_requested')!=policy.MODEL):
        raise ValueError('Original terminal Sol invocation required')
    events=[json.loads(s) for s in (call/'events.jsonl').read_text().splitlines() if s.strip()]
    if (not events or events[-1].get('type')!='turn.failed'
            or any(e.get('type')=='turn.completed' for e in events)):
        raise ValueError('Original invocation is not a terminal failure')
    message=events[-1].get('error',{}).get('message','')
    if '401 Unauthorized' not in message or 'Invalid token' not in message:
        raise ValueError('Only exact terminal invalid-token failure may continue')
    return inv


def restored_success(parent, success):
    parent=Path(parent);success=Path(success)
    old=terminal_failure(parent);inv=runner.read(success/'invocation.json')
    accepted=runner.read(success/'accepted_response.json');response=success/accepted['path']
    if (response.resolve().parent!=success.resolve() or sha(response)!=accepted['sha256']
            or inv.get('exit_code')!=0 or inv.get('response_present') is not True
            or inv.get('model_requested')!=old['model_requested']
            or not old.get('cli_runtime') or inv.get('cli_runtime')!=old['cli_runtime']):
        raise ValueError('Restored service requires accepted same-model/same-CLI success')
    events=[json.loads(s) for s in (success/'events.jsonl').read_text().splitlines() if s.strip()]
    if not events or events[-1].get('type')!='turn.completed':
        raise ValueError('Restored service lacks completed event')
    if (success/'invocation.json').stat().st_mtime_ns <= (parent/'invocation.json').stat().st_mtime_ns:
        raise ValueError('Service success must postdate original terminal failure')
    return response


def _bindings(value):
    for name,digest in value['bindings'].items():
        if sha(Path(name))!=digest:raise ValueError('Contract service bound bytes changed: '+name)


def authorize(folder, success, before_directory, repair):
    folder=Path(folder).resolve();success=Path(success).resolve();before=Path(before_directory).resolve();repair=Path(repair).resolve()
    if (folder/'frozen.json').exists() or (folder/'model_calls'/TASK).exists():
        raise ValueError('Never reset accepted or already attempted continuation')
    parent=folder/'model_calls'/PARENT;response=restored_success(parent,success)
    ref=dict(path=str(folder/chunks.AUTH),sha256=sha(folder/chunks.AUTH));value=chunks.verify(ref)
    if (parent/'prompt.txt').read_bytes()!=(READ_ONLY_EVAL_INSTRUCTIONS+(Path(ref['path']).parent/'submitted_prompt.txt').read_text()).encode():
        raise ValueError('Original exact source request changed')
    if runner.read(parent/'schema.json')!=runner.read(folder/'planned_schema.json'):
        raise ValueError('Original contract schema changed')
    code=Path(__file__).parent.resolve();bindings={**value['bindings'],**value['original_source_bindings']}
    for name,digest in value['production_bindings'].items():
        p=Path(name)
        if sha(p)!=digest:
            archive=before/p.name
            if p!=code/'gameness_v3_runtime.py' or sha(archive)!=digest:
                raise ValueError('Unqualified source producer drift')
            bindings[str(archive)]=digest
        bindings[name]=sha(p)
    files=[*parent.iterdir(),*(success/n for n in ('invocation.json','accepted_response.json','events.jsonl','prompt.txt')),response,
        folder/'source_binding.json',folder/'author_sources.txt',folder/'frozen_protocol.json',folder/'planned_schema.json',
        Path(ref['path']),repair,Path(__file__).resolve(),code/'codex.py',code/'gameness_v4.py']
    bindings.update({str(p):sha(p) for p in files if p.is_file()})
    auth=dict(version=VERSION,classification='NON_SCORING_RESTORED_SERVICE_CONTINUATION',
        source_authorization=ref,parent_task=PARENT,recovery_task=TASK,bindings=bindings,
        newer_service_success=str(success),original_failure_claim_and_attempt_preserved=True,
        source_schema_prompt_and_validator_unchanged=True,maximum_prompt_bytes=1000000,
        maximum_additional_attempts=1)
    path=folder/AUTH
    if path.exists():
        if runner.read(path)!=auth:raise ValueError('Retained service authorization differs')
    else:runner.exclusive_json(path,auth)
    return dict(path=str(path),sha256=sha(path))


def authorization(folder):
    path=Path(folder)/AUTH;value=runner.read(path)
    if value.get('version')!=VERSION or value.get('recovery_task')!=TASK:
        raise ValueError('Unknown contract service continuation')
    _bindings(value)
    terminal_failure(Path(folder)/'model_calls'/PARENT)
    return value


def apply(folder, original, text):
    folder=Path(folder)
    if not (folder/AUTH).is_file():return chunks.apply(folder,original,text)
    value=authorization(folder);ref=value['source_authorization'];chunks.verify(ref)
    parent=Path(ref['path']).parent
    if ((parent/'original_prompt.txt').read_bytes()!=original.encode()
            or Path(runner.read(Path(ref['path']))['source_path']).read_bytes()!=text.encode()):
        raise ValueError('Original full source packet changed')
    return (parent/'submitted_prompt.txt').read_text(),ref


def delivery_folder(folder):
    folder=Path(folder)
    return folder/'model_calls'/(TASK if (folder/AUTH).is_file() else PARENT)


def recover(folder, protocol, prompt, schema):
    folder=Path(folder);auth=authorization(folder);call=delivery_folder(folder)
    if (folder/'model_calls'/PARENT/'prompt.txt').read_bytes()!=(READ_ONLY_EVAL_INSTRUCTIONS+prompt).encode():
        raise ValueError('Restored source prompt must remain exact')
    def validate(raw):
        chunks.verify_delivery(auth['source_authorization'],call)
        policy.validate_contract(protocol,raw)
    if call.exists():
        if not (call/'accepted_response.json').exists():
            raise ValueError('Bounded restored-service attempt failed/incomplete; preserve without retry')
        if (call/'prompt.txt').read_bytes()!=(READ_ONLY_EVAL_INSTRUCTIONS+prompt).encode() or runner.read(call/'schema.json')!=schema:
            raise ValueError('Retained restored request changed')
        result=runner.read(saved_model_response(folder,TASK));validate(result)
    else:
        result=call_codex(folder,name=TASK,prompt=prompt,schema=schema,model=policy.MODEL,
            timeout=900,max_attempts=1,response_validator=validate)
    inv=runner.read(call/'invocation.json')
    if inv.get('exit_code')!=0 or inv.get('model_requested')!=policy.MODEL:
        raise ValueError('Restored source invocation differs')
    paths=[folder/AUTH,*[p for p in call.iterdir() if p.is_file()]]
    receipt=dict(version=VERSION,bindings={**auth['bindings'],**{str(p.resolve()):sha(p) for p in paths}},
        original_failure_preserved=True,model_recalled=True,all_original_source_actually_delivered=True,
        source_only_common_standard=True,full_original_validator_passed=True,scoring_policy_changed=False)
    path=(folder/AUTH).parent/'receipt.json'
    if path.exists():
        if runner.read(path)!=receipt:raise ValueError('Retained service result changed')
    else:runner.exclusive_json(path,receipt)
    return result,dict(path=str(path.resolve()),sha256=sha(path),bindings=receipt['bindings'])
