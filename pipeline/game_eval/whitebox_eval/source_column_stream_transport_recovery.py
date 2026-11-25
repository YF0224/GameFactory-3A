"""One bounded source-column continuation after a proven stream transport outage."""
import json
import math
import re
import time
from pathlib import Path
from . import batch, codex, static_existence, unity_service_recovery as service
from .protocol import sha

VERSION = 'whitebox-source-column-stream-transport-recovery.v1'


def _path(root, name):
    if not re.fullmatch(r'source_column_\d{2,}', name):
        raise ValueError('Only original source-column names may recover')
    return Path(root)/'source_column_stream_transport_recovery'/(name+'.json')


def registered(root, name):
    return bool(re.fullmatch(r'source_column_\d{2,}', name) and _path(root, name).exists())


def qualify(root, name):
    from . import source_score_output_recovery as columns, single_service_source_partition as partition
    root = Path(root).resolve()
    _path(root, name)
    parent = batch.read(root/partition.RECEIPT)
    source = columns._lineage(root, batch.read(root/columns.RECEIPT))
    index = int(name.removeprefix('source_column_'))-1
    deliveries = columns._inputs(source)
    if not 0 <= index < len(deliveries) or name != f'source_column_{index+1:02d}':
        raise ValueError('Unknown original column')
    delivery = deliveries[index]
    path = root/'source_column_delivery'/(name+'.json')
    folder = root/'model_calls'/name
    inv, budget = batch.read(folder/'invocation.json'), batch.read(folder/'budget.json')
    cap = partition.call_cap(root, parent['qualification']['phase_timeout_seconds'])
    elapsed = inv.get('seconds')
    if (inv.get('status') != 'TIMEOUT' or inv.get('model_requested') != static_existence.MODEL
            or type(elapsed) not in (int, float) or not math.isfinite(elapsed)
            or not cap <= elapsed <= cap+30 or budget.get('effective_timeout_seconds') != cap
            or budget.get('attempt') != 1 or budget.get('extension_seconds') != 0
            or any((folder/n).exists() for n in ('response.json','accepted_response.json','schema_error.json'))
            or batch.read(path) != delivery or (folder/'prompt.txt').read_text() != delivery['prompt']
            or batch.read(folder/'schema.json') != delivery['schema']):
        raise ValueError('Exact spent original call with no saved response required')
    pattern = r'Reconnecting\.\.\. [1-5]/5 \(stream disconnected before completion: Transport error: network error: error decoding response body\)'
    errors = []
    for number, line in enumerate((folder/'events.jsonl').read_text().splitlines(), 1):
        event = json.loads(line)
        if event.get('type') == 'error':
            message = event.get('message', '')
            if not re.fullmatch(pattern, message):
                raise ValueError('Different stream/error classification must be preserved separately')
            errors.append({'physical_line':number,'message':message})
    if not errors:
        raise ValueError('Actual stream transport reconnect diagnostic required')
    claim = batch.read(Path(parent['claim']))
    deadline = claim['created_unix']+parent['qualification']['phase_timeout_seconds']
    names = [p for p in folder.iterdir() if p.is_file()]
    names += [root/'input_manifest.json', root/'input/pilot_rubric.json',
              root/'static_existence.json', root/partition.RECEIPT, path]
    return {'classification':'TIMEOUT_WITH_STREAM_TRANSPORT_ERROR',
            'stream_errors':errors,'original_timeout_seconds':cap,'phase_deadline_unix':deadline,
            'frozen_bindings':{str(p.relative_to(root)):sha(p) for p in names}}


def prepare(root, name, queue, probe):
    from .unity_recovery import attempts, saved_score
    from .unity_queue import published
    root = Path(root).resolve()
    path = _path(root, name)
    if path.exists():
        raise ValueError('One service continuation already authorized')
    if any((root/n).exists() for n in ('static_source_scores.json','sol_plan.json','background_record','scores.json')):
        raise ValueError('Only unfinished pre-plan source work may recover')
    ident = batch.read(root/'input_manifest.json')['entry']['id']
    if saved_score(attempts(root.parents[1],ident)) or published(root.parents[1],ident):
        raise ValueError('Existing score protected')
    qualification = qualify(root, name)
    checked = time.time()
    if checked >= qualification['phase_deadline_unix']:
        raise TimeoutError('Original shared static-phase budget exhausted')
    bindings = service.verify_probe(queue, probe)
    if (Path(probe)/'model_calls/service_probe/invocation.json').stat().st_mtime < (root/'model_calls'/name/'invocation.json').stat().st_mtime:
        raise ValueError('Health probe must follow the actual transport failure')
    value = {'version':VERSION,'source_attempt':str(root),'source_name':name,
             'request_name':name+'_stream_transport_v1','qualification':qualification,
             'queue':str(Path(queue).resolve()),'probe':str(Path(probe).resolve()),
             'probe_bindings':bindings,'authorized_unix':checked,
             'maximum_service_recoveries':1,'old_failures_claims_counters_preserved':True,
             'scoring_semantics_changed':False}
    path.parent.mkdir(exist_ok=True)
    with path.open('x') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2)+'\n')
    return verify(root, name)


def verify(root, name):
    root = Path(root).resolve()
    value = batch.read(_path(root, name))
    if (value.get('version') != VERSION or value.get('source_attempt') != str(root)
            or value.get('source_name') != name
            or value.get('request_name') != name+'_stream_transport_v1'
            or value.get('qualification') != qualify(root, name)
            or value.get('maximum_service_recoveries') != 1
            or value.get('old_failures_claims_counters_preserved') is not True
            or value.get('scoring_semantics_changed') is not False
            or type(value.get('authorized_unix')) not in (int,float)
            or not math.isfinite(value['authorized_unix'])
            or value['authorized_unix'] > time.time()
            or service._verify_probe_at(value['queue'],value['probe'],value['authorized_unix']) != value['probe_bindings']):
        raise ValueError('Original source failure or service authorization changed')
    return value


def response(root, name):
    from .source_score_output_recovery import _response
    value = verify(root, name)
    return _response(Path(root), value['request_name'])


def validate_delivery(root, name, path, delivery):
    value = verify(root, name)
    root = Path(root).resolve()
    if delivery != batch.read(root/'source_column_delivery'/(name+'.json')):
        raise ValueError('Frozen source task changed')
    return (path.parent == root/'model_calls'/value['request_name']
            and (path.parent/'prompt.txt').read_text() == delivery['prompt']
            and batch.read(path.parent/'schema.json') == delivery['schema'])


def ensure(root, name, delivery, remaining):
    from .source_score_output_recovery import validate_shard
    root = Path(root).resolve()
    value = verify(root, name)
    if delivery != batch.read(root/'source_column_delivery'/(name+'.json')):
        raise ValueError('Frozen source task changed')
    call_timeout = min(remaining,value['qualification']['original_timeout_seconds'],
                       max(0,int(value['qualification']['phase_deadline_unix']-time.time())))
    if call_timeout <= 0:
        raise TimeoutError('Shared source-column phase deadline exhausted')
    new_name = value['request_name']
    if not (root/'model_calls'/new_name).exists():
        codex.call_codex(root,name=new_name,prompt=delivery['call_prompt'],schema=delivery['schema'],
            model=static_existence.MODEL,max_attempts=1,timeout=call_timeout,
            response_validator=lambda v:validate_shard(root,v,delivery))
    path = response(root,name)
    if not validate_delivery(root,name,path,delivery):
        raise ValueError('Actual service continuation delivery changed')
    return path
