"""One source-column continuation after proven 503 and a bounded healthy probe."""
import json
import math
import re
import time
from pathlib import Path
from . import batch, codex, static_existence, unity_service_recovery as service
from .protocol import sha

VERSION = 'whitebox-source-column-service-recovery.v1'


def _path(root, name):
    if not re.fullmatch(r'source_column_\d{2,}', name):
        raise ValueError('Only original source-column names may recover')
    return Path(root)/'source_column_service_recovery'/(name+'.json')


def registered(root, name):
    return bool(re.fullmatch(r'source_column_\d{2,}', name) and _path(root, name).exists())


def qualify(root, name):
    from . import source_score_output_recovery as columns
    root = Path(root).resolve()
    _path(root, name)
    source = columns._lineage(root, batch.read(root/columns.RECEIPT))
    index = int(name.removeprefix('source_column_'))-1
    deliveries = columns._inputs(source)
    if not 0 <= index < len(deliveries) or name != f'source_column_{index+1:02d}':
        raise ValueError('Unknown original source column')
    delivery = deliveries[index]
    path = root/'source_column_delivery'/(name+'.json')
    if batch.read(path) != delivery:
        raise ValueError('Frozen source column delivery changed')
    folder = root/'model_calls'/name
    if any((folder/n).exists() for n in ('response.json','accepted_response.json','schema_error.json')):
        raise ValueError('Only a response-free provider failure may recover')
    inv = batch.read(folder/'invocation.json')
    command = inv.get('command', [])
    budget = batch.read(folder/'budget.json').get('effective_timeout_seconds')
    if (inv.get('status') == 'TIMEOUT' or '--model' not in command
            or command[command.index('--model')+1] != static_existence.MODEL
            or type(budget) not in (int, float) or not math.isfinite(budget) or budget <= 0
            or (folder/'prompt.txt').read_text() != delivery['prompt']
            or batch.read(folder/'schema.json') != delivery['schema']):
        raise ValueError('Original model, budget or source task changed')
    failures = [v for v in service.service_failures(root) if v['stage'] == name]
    if len(failures) != 1:
        raise ValueError('Actual provider 503 required; other failures do not qualify')
    names = ['input_manifest.json','input/pilot_rubric.json','static_existence.json',
             str(path.relative_to(root))]
    return {'classification':'PROVIDER_503','failure':failures[0],
            'original_timeout_seconds':budget,
            'frozen_bindings':{n:sha(root/n) for n in names}}


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
    bindings = service.verify_probe(queue, probe)
    value = {'version':VERSION,'source_attempt':str(root),'source_name':name,
             'request_name':name+'_service_recovery_v1','qualification':qualification,
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
            or value.get('request_name') != name+'_service_recovery_v1'
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
    if remaining <= 0:
        raise TimeoutError('Shared source-column phase deadline exhausted')
    new_name = value['request_name']
    if not (root/'model_calls'/new_name).exists():
        codex.call_codex(root,name=new_name,prompt=delivery['call_prompt'],schema=delivery['schema'],
            model=static_existence.MODEL,max_attempts=1,
            timeout=min(remaining,value['qualification']['original_timeout_seconds']),
            response_validator=lambda v:validate_shard(root,v,delivery))
    path = response(root,name)
    if not validate_delivery(root,name,path,delivery):
        raise ValueError('Actual service continuation delivery changed')
    return path
