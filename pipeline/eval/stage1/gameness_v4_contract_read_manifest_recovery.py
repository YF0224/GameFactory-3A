"""Failure-bound complete source reads without redundant compressed context.

Only an observed zero-read bounded contract failure may opt in. All immutable
source chunks must appear in real ordered outputs before the original validator
can accept a contract. Old calls, claims, schema and caps remain unchanged.
"""
import json
import shlex
from pathlib import Path
from . import mechanic_v3_runner as runner
from . import gameness_v4_contract_bounded_recovery as bounded
from . import gameness_v4_contract_chunks as chunks
from . import gameness_v4 as policy
from .protocol import sha
from .codex import READ_ONLY_EVAL_INSTRUCTIONS, call_codex, saved_model_response

VERSION='gameness-v4-zero-read-complete-source-manifest.v1'
AUTH='engineering/source_contract_read_manifest/authorization.json'
TASK='gameness_v4_source_contract_complete_manifest_v1'
MAX_GROUP_BYTES=150000


def failed_parent(folder):
    folder=Path(folder);call=folder/'model_calls'/bounded.TASK
    if (folder/'frozen.json').exists() or (call/'accepted_response.json').exists():
        raise ValueError('Never replace a valid source contract')
    inv=runner.read(call/'invocation.json');error=runner.read(call/'validation_error.json')
    events=[json.loads(s) for s in (call/'events.jsonl').read_text().splitlines() if s.strip()]
    if (inv.get('exit_code')!=0 or inv.get('response_present') is not True or inv.get('attempt')!=1
            or inv.get('model_requested')!=policy.MODEL or error.get('exception')!=bounded.ERROR
            or error.get('response_sha256')!=sha(call/'response.json')
            or not events or events[-1].get('type')!='turn.completed'
            or any(e.get('item',{}).get('type')=='command_execution' for e in events)):
        raise ValueError('Exact completed zero-source-read failure required')
    return call


def packet(folder,reference):
    """Retain original checks/instructions verbatim; move only source transport."""
    chunks.verify(reference);directory=Path(reference['path']).parent
    original=(directory/'original_prompt.txt').read_text()
    source=Path(runner.read(Path(reference['path']))['source_path']).read_text()
    marker='\nAUTHOR SOURCES\n'+source+'\nEXACT SCHEMA FILE '
    if original.count(marker)!=1:raise ValueError('Complete original source boundary changed')
    paths=sorted((directory/'chunks').glob('*.txt'))
    commands=[];groups=[];group=[];size=0
    for path in paths:
        count=path.stat().st_size
        if count>MAX_GROUP_BYTES:raise ValueError('Original source chunk exceeds bounded output size')
        if group and (size+count>MAX_GROUP_BYTES or len(group)==8):
            groups.append(group);group=[];size=0
        group.append(path);size+=count
    if group:groups.append(group)
    for group in groups:
        commands.append('cat '+' '.join(shlex.quote(str(p.resolve())) for p in group))
    notice=('COMPLETE ORIGINAL SOURCE FILE DELIVERY, MANDATORY BEFORE JSON. '
        'The earlier response executed zero source reads and is INVALID. The original compressed '
        'envelope remains preserved on disk; it is deliberately not repeated in context. '
        'Every byte of ALL original author sources is supplied through the immutable ordered '
        'chunk files below. Execute EVERY numbered read-only shell command in order, each in '
        'a separate tool output, with max_output_tokens=60000. Each command emits at most '
        '150000 UTF-8 bytes, below the proved aggregate-output ceiling. Do not merge these '
        'commands into a loop or one tool output. Never summarize, skip files, inspect only '
        'SHAs or compressed data, or return JSON before reading every command output in full. '
        'If a tool output is clipped, read the affected original chunks separately. The formal '
        'validator independently checks all original chunk bytes and order in actual completed '
        'outputs. Cite original AUTHOR model/path and numbered physical source lines, never '
        'chunk wrappers. This source-only transport grants no runtime credit and supplies no '
        'runtime evidence, old scores or verdicts. Preserve ALL original check identities, '
        'requirements, groups, trigger alternatives and basic bugs.\n'
        +'\n'.join(str(i+1)+'. '+command for i,command in enumerate(commands))+'\n')
    wire=original.replace(marker,'\nAUTHOR SOURCES\n'+notice+'\nEXACT SCHEMA FILE ',1)
    if len((READ_ONLY_EVAL_INSTRUCTIONS+wire).encode())>chunks.MAX_BYTES:
        raise ValueError('Complete source manifest exceeds unchanged request cap')
    return wire


def authorize(folder,repair,before_directory):
    folder=Path(folder).resolve();repair=Path(repair).resolve()
    if (folder/'model_calls'/TASK).exists():raise ValueError('Manifest recovery already attempted')
    call=failed_parent(folder);parent=folder/bounded.AUTH;value=runner.read(parent)
    from .gameness_v4_production_continuation import authorize as bridge
    ref=bridge(parent,value['bindings'],before_directory,repair)
    resolved=bounded.exact_runtime_bridge(parent,value['bindings'],ref)
    source=value['source_authorization'];wire=packet(folder,source)
    files=[parent,repair,Path(__file__).resolve(),*[p for p in call.iterdir() if p.is_file()]]
    receipt=dict(version=VERSION,classification='NON_SCORING_PROVED_ZERO_READ_TRANSPORT_REPAIR',
        parent_task=bounded.TASK,recovery_task=TASK,source_authorization=source,
        maximum_additional_attempts=1,maximum_prompt_bytes=chunks.MAX_BYTES,
        source_schema_validator_checks_and_weights_unchanged=True,
        prompt_sha256=chunks.digest(wire.encode()),
        bindings={**resolved,**{str(p):sha(p) for p in files}})
    path=folder/AUTH
    if path.exists():
        if runner.read(path)!=receipt:raise ValueError('Immutable manifest recovery differs')
    else:runner.exclusive_json(path,receipt)
    return dict(path=str(path),sha256=sha(path))


def authorization(folder):
    value=runner.read(Path(folder)/AUTH)
    if value.get('version')!=VERSION or value.get('recovery_task')!=TASK:
        raise ValueError('Unknown manifest source recovery')
    for p,d in value['bindings'].items():
        if sha(Path(p))!=d:raise ValueError('Manifest source binding changed: '+p)
    return value


def apply(folder,original,text):
    folder=Path(folder)
    if not (folder/AUTH).is_file():return bounded.apply(folder,original,text)
    value=authorization(folder);ref=value['source_authorization'];chunks.verify(ref)
    directory=Path(ref['path']).parent
    if ((directory/'original_prompt.txt').read_bytes()!=original.encode()
            or Path(runner.read(Path(ref['path']))['source_path']).read_bytes()!=text.encode()):
        raise ValueError('Original source contract packet changed')
    wire=packet(folder,ref)
    if chunks.digest(wire.encode())!=value['prompt_sha256']:raise ValueError('Manifest prompt changed')
    return wire,ref


def verify_delivery(folder,reference):
    folder=Path(folder);value=authorization(folder)
    if reference!=value['source_authorization']:raise ValueError('Manifest source reference differs')
    source=chunks.verify(reference);call=folder/'model_calls'/TASK
    texts=[p.read_text() for p in sorted((Path(reference['path']).parent/'chunks').glob('*.txt'))]
    events=call/'events.jsonl';proof=chunks.ordered_source_outputs(events.read_text(),texts)
    expected=READ_ONLY_EVAL_INSTRUCTIONS+packet(folder,reference)
    if (call/'prompt.txt').read_bytes()!=expected.encode():raise ValueError('Actual manifest request differs')
    receipt=dict(version=VERSION,authorization=dict(path=str(folder/AUTH),sha256=sha(folder/AUTH)),
        source_sha256=source['source_sha256'],all_original_author_bytes_actually_delivered=True,
        original_physical_lines=True,chunk_count=len(texts),ordered_output_proof=proof,
        prompt_sha256=sha(call/'prompt.txt'),events_sha256=sha(events))
    path=call/'actual_delivery.json'
    if path.exists():
        if runner.read(path)!=receipt:raise ValueError('Retained manifest delivery differs')
    else:runner.exclusive_json(path,receipt)
    return receipt


def verify_frozen_delivery(folder,reference):
    if (Path(folder)/AUTH).is_file():return verify_delivery(folder,reference)
    return bounded.verify_frozen_delivery(folder,reference)


def recover(folder,protocol,prompt,schema):
    folder=Path(folder)
    if not (folder/AUTH).is_file():return bounded.recover(folder,protocol,prompt,schema)
    value=authorization(folder);ref=value['source_authorization'];call=folder/'model_calls'/TASK
    if prompt!=packet(folder,ref):raise ValueError('Manifest runtime prompt differs')
    def validate(raw):
        verify_delivery(folder,ref);policy.validate_contract(protocol,raw)
    if call.exists():
        if not (call/'accepted_response.json').exists():raise ValueError('Manifest child failed/incomplete; no unchanged retry')
        if runner.read(call/'schema.json')!=schema:raise ValueError('Retained schema differs')
        result=runner.read(saved_model_response(folder,TASK));validate(result)
    else:
        result=call_codex(folder,name=TASK,prompt=prompt,schema=schema,model=policy.MODEL,
            timeout=900,max_attempts=1,response_validator=validate)
    inv=runner.read(call/'invocation.json')
    if inv.get('exit_code')!=0 or inv.get('model_requested')!=policy.MODEL:
        raise ValueError('Manifest invocation differs')
    files=[folder/AUTH,*[p for p in call.iterdir() if p.is_file()]]
    receipt=dict(version=VERSION,bindings={**value['bindings'],**{str(p):sha(p) for p in files}},
        original_failures_claims_and_attempts_preserved=True,model_recalled=True,
        full_original_validator_passed=True,all_original_source_actually_delivered=True,
        scoring_policy_changed=False)
    path=(folder/AUTH).parent/'receipt.json'
    if path.exists():
        if runner.read(path)!=receipt:raise ValueError('Retained manifest result differs')
    else:runner.exclusive_json(path,receipt)
    return result,dict(path=str(path),sha256=sha(path),bindings=receipt['bindings'])
