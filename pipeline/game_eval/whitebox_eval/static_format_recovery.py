"""One explicit source-bound correction after a preserved static schema failure.

No result is translated or fabricated here. The same frozen Sol reviewer must
return the full original schema and every source reference passes old validators.
"""
import json
from pathlib import Path
from . import codex, static_existence as static
from .protocol import dump, sha
VERSION='whitebox-static-format-recovery.v1'
RECEIPT='static_format_recovery.json'
NAME='static_existence_format_v1'


def qualify(root, folder):
    from . import batch
    root=Path(root).resolve();folder=Path(folder).resolve()
    batch.verify_inputs(root)
    if not folder.is_relative_to(root/'model_calls') or not folder.name.startswith('static_existence'):
        raise ValueError('Static format recovery needs a preserved local static call')
    inv=codex.load_plan_json(folder/'invocation.json');cmd=inv.get('command',[])
    if (inv.get('exit_code')!=0 or inv.get('model_requested')!=static.MODEL
            or '--model' not in cmd or cmd[cmd.index('--model')+1]!=static.MODEL):
        raise ValueError('Static format failure must follow a successful real Sol invocation')
    protocol=codex.load_plan_json(root/'input/pilot_rubric.json')
    expected=static.schema(protocol,static.identity(root,protocol),
                           codex.load_plan_json(root/'input_manifest.json')['snapshot_hashes'])
    if codex.load_plan_json(folder/'schema.json')!=expected:
        raise ValueError('Original static schema differs from frozen source identity')
    err=codex.load_plan_json(folder/'schema_error.json')
    if err.get('response_sha256')!=sha(folder/'response.json'):
        raise ValueError('Original schema failure response SHA mismatch')
    try:codex.validate_schema(codex.load_plan_json(folder/'response.json'),expected)
    except ValueError:pass
    else:raise ValueError('Original response is not a static schema failure')
    return protocol,expected


def register(root, folder, *, authorization):
    root=Path(root).resolve();folder=Path(folder).resolve()
    if not authorization or any((root/n).exists() for n in (RECEIPT,'static_existence.json','scores.json','sol_plan.json')):
        raise ValueError('Static format recovery cannot replace existing acceptance or identity')
    protocol,expected=qualify(root,folder)
    names=('prompt.txt','schema.json','response.json','schema_error.json','invocation.json')
    value={'version':VERSION,'authorization':authorization,'original_call':str(folder.relative_to(root)),
           'original_bindings':{str((folder/n).relative_to(root)):sha(folder/n) for n in names},
           'identity':static.identity(root,protocol),'request_name':NAME,'maximum_new_calls':1,
           'root_cause':'The preserved response used an alternate structure. Exact submitted schema was not named in task text; correction explicitly reads it.',
           'semantics':'Full original task, source, identity, schema and all validators unchanged. No verdict conversion or reference relaxation.'}
    with (root/RECEIPT).open('x') as stream:json.dump(value,stream,ensure_ascii=False,indent=2)
    return value


def lineage(root):
    root=Path(root).resolve();value=codex.load_plan_json(root/RECEIPT)
    if value.get('version')!=VERSION or value.get('request_name')!=NAME or value.get('maximum_new_calls')!=1:
        raise ValueError('Unsupported static format recovery identity')
    for name,digest in value['original_bindings'].items():
        p=Path(name)
        if p.is_absolute() or '..' in p.parts or sha(root/p)!=digest:
            raise ValueError('Preserved static failure changed: '+name)
    protocol,expected=qualify(root,root/value['original_call'])
    if value['identity']!=static.identity(root,protocol):raise ValueError('Recovered static source identity changed')
    return value,protocol,expected


def run(root, timeout=600):
    root=Path(root).resolve();value,protocol,expected=lineage(root)
    if (root/'static_existence.json').exists():return verify(root,protocol)
    old=root/value['original_call'];folder=root/'model_calls'/NAME
    if not folder.exists():
        prompt=(old/'prompt.txt').read_text()+('\nFORMAT CORRECTION, original schema failure retained: '
            +codex.load_plan_json(old/'schema_error.json')['exception']
            +'\nRead your preserved raw response at '+str(old/'response.json')
            +'. Preserve valid source analysis. Return the complete ORIGINAL closed schema with root identity and checks; '
            'each check needs static_existence, connected_to_entry, reason and evidence. '
            'Each evidence reference needs path, actual sha256, physical line_start/line_end, role and reason. '
            'Never infer connection from a missing field or reuse unverified hashes. Use targeted source reads if necessary. '
            'The same strict source SHA and inclusive line checks still apply.')
        codex.call_codex(root,name=NAME,prompt=prompt,schema=expected,model=static.MODEL,
            timeout=timeout,max_attempts=1,response_validator=lambda result:static.validate_result(root,protocol,result))
    response=codex.saved_model_response(root,NAME)
    result=codex.load_plan_json(response)
    static.validate_result(root,protocol,result)
    dump(root/'static_existence.json',{'version':static.SCHEMA,'model':static.MODEL,
        'policy':static.policy(protocol)['version'],'result':result,'response_sha256':sha(response),
        'static_format_recovery_sha256':sha(root/RECEIPT)})
    return verify(root,protocol)


def verify(root,protocol):
    root=Path(root).resolve();value,bound,expected=lineage(root)
    if protocol!=bound:raise ValueError('Recovered static protocol changed')
    response=codex.saved_model_response(root,NAME);folder=response.parent
    inv=codex.load_plan_json(folder/'invocation.json');cmd=inv.get('command',[])
    if (inv.get('exit_code')!=0 or inv.get('model_requested')!=static.MODEL or '--model' not in cmd
            or cmd[cmd.index('--model')+1]!=static.MODEL or codex.load_plan_json(folder/'schema.json')!=expected):
        raise ValueError('Recovered static call lacks frozen model/schema provenance')
    artifact=codex.load_plan_json(root/'static_existence.json');result=codex.load_plan_json(response)
    if (artifact.get('version')!=static.SCHEMA or artifact.get('model')!=static.MODEL
            or artifact.get('policy')!=static.policy(protocol)['version']
            or artifact.get('static_format_recovery_sha256')!=sha(root/RECEIPT)
            or artifact.get('response_sha256')!=sha(response) or artifact.get('result')!=result):
        raise ValueError('Recovered static artifact differs from accepted raw response')
    return static.validate_result(root,protocol,result)
