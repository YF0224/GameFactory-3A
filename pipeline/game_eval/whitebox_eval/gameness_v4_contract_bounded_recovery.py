"""One bounded child after proved shell-output omission in a source contract.

Every immutable chunk must be delivered in its own complete tool output. The
source, schema, original failed response, scoring policy and limits are retained.
"""
import json
import re
from pathlib import Path
from . import mechanic_v3_runner as runner
from . import gameness_v4_contract_chunks as chunks
from . import gameness_v4_contract_service_recovery as service
from . import gameness_v4 as policy
from .protocol import sha
from .codex import READ_ONLY_EVAL_INSTRUCTIONS, call_codex, saved_model_response

VERSION='gameness-v4-proved-output-omission-bounded-child.v1'
AUTH='engineering/source_contract_bounded_recovery/authorization.json'
TASK=service.PARENT+'_bounded_source_reads_v1'
ERROR='HARNESS_ERROR: model did not receive every complete source chunk in order'
NOTICE=('\nPROVED OUTPUT TRANSPORT FAILURE AND ONE BOUNDED CORRECTION: The earlier shell loop '
    'concatenated all source chunks and its output omitted source bytes. That response is invalid '
    'and is not supplied as a contract. Read ALL ordered chunk files again. Each command/tool call '
    'must cat EXACTLY ONE chunk file; use max_output_tokens at least 16000. Do not use shell loops, '
    'glob cats, multiple cat commands, multi-file cats, range summaries, rg, hashes or compressed text '
    'as substitutes for complete chunk output. There are 103 files in the original ordered manifest. '
    'Track each original chunk ID; deliver every chunk 0000 through 0102 once, each in a separate '
    'completed command output. Each is <= 16112 characters, avoiding the proved 1MiB aggregated-output '
    'ceiling. Only after all complete source chunks have actually appeared may you return the original '
    'complete source-only contract schema. Preserve original check IDs/requirements/groups verbatim. '
    'Cite original AUTHOR model/path and numbered physical source lines, never chunk wrapper lines. '
    'Retain all original source bytes, context, trigger alternatives, basic bug conditions and requirements. '
    'No runtime observations, verdicts or scores are supplied.\n')


def omitted_output(folder):
    folder=Path(folder);call=folder/'model_calls'/service.TASK
    if (call/'accepted_response.json').exists() or (folder/'frozen.json').exists():
        raise ValueError('Never replace accepted/frozen source contract')
    inv=runner.read(call/'invocation.json');error=runner.read(call/'validation_error.json')
    if (inv.get('exit_code')!=0 or inv.get('response_present') is not True or inv.get('attempt')!=1
            or inv.get('model_requested')!=policy.MODEL or error.get('exception')!=ERROR
            or error.get('response_sha256')!=sha(call/'response.json')):
        raise ValueError('Exact completed omission failure required')
    ref=runner.read(folder/service.AUTH)['source_authorization'];chunks.verify(ref)
    values=[p.read_text() for p in sorted((Path(ref['path']).parent/'chunks').glob('*.txt'))]
    complete=''.join(values);proof=[]
    for line in (call/'events.jsonl').read_text().splitlines():
        event=json.loads(line);item=event.get('item',{});text=item.get('aggregated_output','')
        if event.get('type')!='item.completed' or item.get('type')!='command_execution' or item.get('exit_code')!=0:continue
        for match in re.finditer(r'\n\.\.\. (\d+) bytes omitted \.\.\.\n',text):
            head=text[:match.start()];tail=text[match.end():]
            if complete.startswith(head) and complete.endswith(tail):
                absent=complete[len(head):len(complete)-len(tail)]
                if len(absent.encode())!=int(match.group(1)):continue
                proof.append(dict(item_id=item.get('id'),omitted_bytes=len(absent.encode()),original_bytes=len(complete.encode()),output_bytes=len(text.encode())))
    if len(proof)!=1:raise ValueError('Exact shell omission not proved')
    events=[json.loads(s) for s in (call/'events.jsonl').read_text().splitlines() if s.strip()]
    if events[-1].get('type')!='turn.completed':raise ValueError('Original model turn incomplete')
    return proof[0]


def exact_runtime_bridge(parent, bindings, reference):
    """Verify one explicitly selected immutable receipt; retain ambiguity guards elsewhere."""
    from . import gameness_v4_production_continuation as continuation
    parent=Path(parent).resolve();path=Path(reference['path']).resolve()
    if (path.parent!=continuation._directory(parent).resolve() or sha(path)!=reference['sha256']):
        raise ValueError('Exact runtime bridge reference changed')
    value=runner.read(path)
    if (path.stem!=continuation._digest(value) or value.get('version')!=continuation.VERSION
            or value.get('parent')!=dict(path=str(parent),sha256=sha(parent))
            or value.get('original_bindings')!=bindings):
        raise ValueError('Exact runtime bridge parent changed')
    code=Path(__file__).parent.resolve()
    drift={str(Path(p).resolve()):d for p,d in bindings.items() if sha(Path(p))!=d}
    changes=value.get('changes',{})
    if set(drift)!={str(code/'gameness_v3_runtime.py')} or set(changes)!=set(drift):
        raise ValueError('Only exact runtime dispatcher drift may continue')
    for name,old in drift.items():
        change=changes[name];archive=Path(change['archive'])
        if (change['before_sha256']!=old or sha(archive)!=old
                or change['after_sha256']!=sha(Path(name))
                or value['bindings'].get(str(archive))!=old
                or value['bindings'].get(name)!=change['after_sha256']):
            raise ValueError('Exact runtime bridge lacks before/after archive')
    for name,digest in value['bindings'].items():
        if sha(Path(name))!=digest:raise ValueError('Exact runtime bridge binding changed: '+name)
    return {**{p:d for p,d in bindings.items() if str(Path(p).resolve()) not in drift},
        **value['bindings'],str(path):sha(path)}


def authorize(folder,repair,before_directory):
    folder=Path(folder).resolve();repair=Path(repair).resolve();before=Path(before_directory).resolve()
    if (folder/'model_calls'/TASK).exists():raise ValueError('Bounded child already attempted')
    proof=omitted_output(folder);parent=folder/'model_calls'/service.TASK
    service_path=folder/service.AUTH;service_value=runner.read(service_path)
    # An explicit exact archive bridges only the runtime dispatcher edit.
    from .gameness_v4_production_continuation import authorize as bridge
    reference=bridge(service_path,service_value['bindings'],before,repair)
    resolved=exact_runtime_bridge(service_path,service_value['bindings'],reference)
    original=(parent/'prompt.txt').read_text()
    if not original.startswith(READ_ONLY_EVAL_INSTRUCTIONS):raise ValueError('Original read-only instructions missing')
    prompt=original[len(READ_ONLY_EVAL_INSTRUCTIONS):]+NOTICE
    if len((READ_ONLY_EVAL_INSTRUCTIONS+prompt).encode())>1000000:raise ValueError('Bounded full packet exceeds unchanged cap')
    source_auth=service_value['source_authorization'];chunk_folder=Path(source_auth['path']).parent/'chunks'
    chunks_text=[p.read_text() for p in sorted(chunk_folder.glob('*.txt'))]
    if len(chunks_text)!=103 or max(map(len,chunks_text))>16112:
        raise ValueError('Bounded correction only for measured 103-chunk original source')
    paths=[service_path,*[p for p in parent.iterdir() if p.is_file()],repair,Path(__file__).resolve()]
    value=dict(version=VERSION,classification='NON_SCORING_PROVED_OUTPUT_OMISSION_RECOVERY',
        source_authorization=source_auth,parent_task=service.TASK,recovery_task=TASK,diagnosis=proof,
        maximum_prompt_bytes=1000000,maximum_additional_attempts=1,source_schema_validator_unchanged=True,
        prompt_sha256=chunks.digest(prompt.encode()),bindings={**resolved,**{str(p):sha(p) for p in paths}})
    path=folder/AUTH
    if path.exists():
        if runner.read(path)!=value:raise ValueError('Immutable bounded child authorization differs')
    else:runner.exclusive_json(path,value)
    return dict(path=str(path),sha256=sha(path))


def authorization(folder):
    value=runner.read(Path(folder)/AUTH)
    if value.get('version')!=VERSION or value.get('recovery_task')!=TASK:raise ValueError('Unknown bounded source continuation')
    for p,d in value['bindings'].items():
        if sha(Path(p))!=d:raise ValueError('Bounded source binding changed: '+p)
    return value


def submitted(folder):
    original=(Path(folder)/'model_calls'/service.TASK/'prompt.txt').read_text()
    if not original.startswith(READ_ONLY_EVAL_INSTRUCTIONS):raise ValueError('Original instructions changed')
    return original[len(READ_ONLY_EVAL_INSTRUCTIONS):]+NOTICE


def apply(folder,original,text):
    folder=Path(folder)
    if not (folder/AUTH).is_file():return service.apply(folder,original,text)
    value=authorization(folder);ref=value['source_authorization'];chunks.verify(ref);parent=Path(ref['path']).parent
    if ((parent/'original_prompt.txt').read_bytes()!=original.encode()
            or Path(runner.read(Path(ref['path']))['source_path']).read_bytes()!=text.encode()):
        raise ValueError('Original source contract packet changed')
    prompt=submitted(folder)
    if chunks.digest(prompt.encode())!=value['prompt_sha256']:raise ValueError('Bounded prompt differs')
    return prompt,ref


def verify_delivery(folder,ref):
    folder=Path(folder);value=authorization(folder);call=folder/'model_calls'/TASK
    if ref!=value['source_authorization']:raise ValueError('Bounded source authorization differs')
    source=chunks.verify(ref);text=[p.read_text() for p in sorted((Path(ref['path']).parent/'chunks').glob('*.txt'))]
    events=call/'events.jsonl';outputs=chunks.ordered_source_outputs(events.read_text(),text)
    # Single chunks only: a loop/multi-file full output still violates this repair.
    if len(outputs)!=len(text) or any(p['output_bytes']!=len(t.encode()) for p,t in zip(outputs,text)):
        raise ValueError('Bounded source must use exactly one chunk per complete output')
    if (call/'prompt.txt').read_bytes()!=(READ_ONLY_EVAL_INSTRUCTIONS+submitted(folder)).encode():raise ValueError('Bounded actual request changed')
    proof=dict(version=VERSION,all_original_author_bytes_actually_delivered=True,original_physical_lines=True,
        source_sha256=source['source_sha256'],chunk_count=len(text),ordered_output_proof=outputs,
        prompt_sha256=sha(call/'prompt.txt'),events_sha256=sha(events),authorization=dict(path=str(folder/AUTH),sha256=sha(folder/AUTH)))
    path=call/'actual_delivery.json'
    if path.exists():
        if runner.read(path)!=proof:raise ValueError('Retained bounded actual delivery differs')
    else:runner.exclusive_json(path,proof)
    return proof


def verify_frozen_delivery(folder,ref):
    if (Path(folder)/AUTH).is_file():return verify_delivery(folder,ref)
    return chunks.verify_delivery(ref,service.delivery_folder(folder))


def recover(folder,protocol,prompt,schema):
    folder=Path(folder)
    if not (folder/AUTH).is_file():return service.recover(folder,protocol,prompt,schema)
    value=authorization(folder);call=folder/'model_calls'/TASK
    if prompt!=submitted(folder):raise ValueError('Bounded runtime prompt differs')
    def validate(raw):
        verify_delivery(folder,value['source_authorization']);policy.validate_contract(protocol,raw)
    if call.exists():
        if not (call/'accepted_response.json').exists():raise ValueError('Bounded source child failed/incomplete; no unchanged retry')
        if runner.read(call/'schema.json')!=schema:raise ValueError('Retained schema differs')
        result=runner.read(saved_model_response(folder,TASK));validate(result)
    else:result=call_codex(folder,name=TASK,prompt=prompt,schema=schema,model=policy.MODEL,timeout=900,max_attempts=1,response_validator=validate)
    inv=runner.read(call/'invocation.json')
    if inv.get('exit_code')!=0 or inv.get('model_requested')!=policy.MODEL:raise ValueError('Bounded source invocation differs')
    paths=[folder/AUTH,*[p for p in call.iterdir() if p.is_file()]]
    receipt=dict(version=VERSION,bindings={**value['bindings'],**{str(p):sha(p) for p in paths}},
        original_failures_claims_and_attempts_preserved=True,model_recalled=True,
        full_original_validator_passed=True,all_original_source_actually_delivered=True,scoring_policy_changed=False)
    path=(folder/AUTH).parent/'receipt.json'
    if path.exists():
        if runner.read(path)!=receipt:raise ValueError('Retained bounded source result differs')
    else:runner.exclusive_json(path,receipt)
    return result,dict(path=str(path),sha256=sha(path),bindings=receipt['bindings'])
