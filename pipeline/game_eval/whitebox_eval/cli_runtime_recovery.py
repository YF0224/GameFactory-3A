"""One explicit source-call recovery after a proven CLI host failure.

The accepted runtime changes only the executable. The parent task, frozen bytes,
source ordinal bijection and original source validation remain authoritative.
"""
from pathlib import Path
import json
import os
import re
import shutil

from . import batch, codex, source_reference_transport as transport
from .protocol import dump, sha, checked_path

VERSION = 'whitebox-cli-runtime-recovery.v1'
SUFFIX = '_cli_runtime_v1'


def _path(root, name):
    if not re.fullmatch(r'static_existence(?:_output_\d+(?:_single_\d+)?_source_delivery_v1)?', name):
        raise ValueError('CLI recovery limited to explicit missing source tasks')
    return Path(root)/'cli_runtime_recovery'/(name+'.json')


def registered(root, name):
    return _path(root, name).is_file()


def qualified_runtime(spec):
    binary = Path(spec['path']).resolve()
    proof = Path(spec['real_read_qualification']).resolve()
    if (not binary.is_file() or not os.access(binary, os.X_OK)
            or sha(binary) != spec['sha256'] or sha(proof) != spec['real_read_qualification_sha256']):
        raise ValueError('Qualified CLI executable/proof SHA changed')
    result, command = batch.read(proof), batch.read(proof.parent/'command.json')
    def option(key):
        return command[command.index(key)+1] if key in command else None
    if (result.get('exact_read') is not True or result.get('exit_code') != 0
            or result.get('status') != 'EXITED' or Path(command[0]).resolve() != binary
            or option('--model') != 'gpt-6.1-sol' or option('--sandbox') != 'read-only'):
        raise ValueError('CLI requires actual same-model read-only tool qualification')
    fixture = Path(option('-C'))/'read_only_fixture.txt'
    text = fixture.read_text()
    events = [json.loads(line) for line in (proof.parent/'events.jsonl').read_text().splitlines() if line]
    if (batch.read(proof.parent/'response.json') != {'read_text':text}
            or not any(e.get('type') == 'item.completed' and
                e.get('item', {}).get('type') == 'command_execution' and
                e['item'].get('status') == 'completed' and e['item'].get('exit_code') == 0 and
                e['item'].get('aggregated_output') == text for e in events)
            or codex.tool_transport_failure(proof.parent)):
        raise ValueError('Qualified CLI lacks an actual successful exact source read')
    return {str(p):sha(p) for p in [binary, fixture, *sorted(p for p in proof.parent.iterdir() if p.is_file())]}


def task(root, name):
    folder = Path(root)/'model_calls'/name
    if (folder/transport.TRANSFORM).is_file():
        schema, _ = transport.verify(folder)
        prompt = transport.verify_prompt(folder)
    else:
        schema, prompt = batch.read(folder/'schema.json'), (folder/'prompt.txt').read_text()
    if not prompt.startswith(codex.READ_ONLY_EVAL_INSTRUCTIONS):
        raise ValueError('Original read-only task prefix missing')
    return {'prompt':prompt[len(codex.READ_ONLY_EVAL_INSTRUCTIONS):], 'schema':schema}


def _failure(root, name):
    folder = Path(root)/'model_calls'/name
    invocation = batch.read(folder/'invocation.json')
    command = invocation.get('command', [])
    error = codex.tool_transport_failure(folder)
    if ((folder/'accepted_response.json').exists() or not error
            or batch.read(folder/'tool_transport_error.json') != error
            or invocation.get('status') != 'HARNESS_ERROR'
            or invocation.get('failure_layer') != 'cli_tool_transport'
            or invocation.get('model_requested') != 'gpt-6.1-sol'
            or '--model' not in command or command[command.index('--model')+1] != 'gpt-6.1-sol'
            or '--sandbox' not in command or command[command.index('--sandbox')+1] != 'read-only'
            or '-C' not in command or Path(command[command.index('-C')+1]).resolve() != (Path(root)/'input').resolve()):
        raise ValueError('No exact failed source-tool invocation; accepted work protected')
    return {str(p.relative_to(root)):sha(p) for p in sorted(folder.iterdir()) if p.is_file()}


def qualify(root, name, runtime):
    root = Path(root).resolve()
    _path(root, name)
    batch.verify_inputs(root)
    frozen = {p:sha(root/p) for p in ('input_manifest.json','input/pilot_rubric.json')}
    failed = _failure(root, name)
    invocation = batch.read(root/'model_calls'/name/'invocation.json')
    executable = invocation['command'][0]
    failed_binary = Path(shutil.which(executable) or executable).resolve()
    if not failed_binary.is_file() or sha(failed_binary) == runtime['sha256']:
        raise ValueError('Runtime recovery requires a substantively different qualified executable')
    if (root/'scores.json').exists():
        raise ValueError('Existing complete static work protected')
    pending_artifact = None
    if (root/'static_existence.json').exists():
        # A stale artifact is not a judgment when its formal partition is incomplete.
        # Only the exact registered missing supplement may finish that partition.
        from . import static_output_recovery as partition, static_inline_source_delivery as supplement
        if name == 'static_existence' or not (root/partition.RECEIPT).is_file():
            raise ValueError('Existing complete static work protected')
        receipt = batch.read(root/partition.RECEIPT)
        partition._verify_lineage(root, receipt)
        parent_name = name.removesuffix('_source_delivery_v1')
        if (receipt.get('complete') is not False or not supplement.registered(root, parent_name)
                or supplement.verify(root, parent_name)['request_name'] != name):
            raise ValueError('Existing complete static work protected')
        try:
            partition.verify(root, batch.read(root/'input/pilot_rubric.json'))
        except ValueError as exc:
            if str(exc) != 'Incomplete static output partition cannot become a source judgment':
                raise
        else:
            raise ValueError('Existing complete static work protected')
        pending_artifact = {'sha256':sha(root/'static_existence.json'),
            'archive':'cli_runtime_recovery/'+name+'.preserved_static.json'}
    preserved = {str(p.relative_to(root)):sha(p) for p in sorted((root/'model_calls').glob('*/accepted_response.json'))}
    return {'version':VERSION, 'attempt':str(root), 'name':name, 'request_name':name+SUFFIX,
        'pending_artifact':pending_artifact, 'task':task(root,name), 'runtime':runtime, 'qualification_bindings':qualified_runtime(runtime),
        'failed_binary':str(failed_binary), 'failed_binary_sha256':sha(failed_binary),
        'failure_bindings':failed, 'frozen_bindings':frozen, 'accepted_bindings':preserved,
        'max_attempts':1, 'model':'gpt-6.1-sol', 'timeout_seconds':900,
        'semantics_changed':False, 'counter_reset':False}


def prepare(root, name, runtime):
    root = Path(root).resolve()
    path = _path(root,name)
    if path.exists() or (root/'model_calls'/(name+SUFFIX)).exists():
        raise ValueError('CLI runtime recovery already prepared/attempted; no retry or reset')
    from .unity_queue import published
    from .unity_recovery import attempts, saved_score
    ident = batch.read(root/'input_manifest.json')['entry']['id']
    if published(root.parents[1],ident) or saved_score(attempts(root.parents[1],ident)):
        raise ValueError('Existing complete score protected')
    value = qualify(root,name,runtime)
    path.parent.mkdir(exist_ok=True)
    if value['pending_artifact']:
        archive = root/value['pending_artifact']['archive']
        with archive.open('xb') as stream:stream.write((root/'static_existence.json').read_bytes())
        if sha(archive) != value['pending_artifact']['sha256']:
            raise ValueError('Pending static preimage changed during registration')
    with path.open('x') as stream:
        stream.write(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    return verify(root,name)


def verify(root, name):
    root = Path(root).resolve()
    value = batch.read(_path(root,name))
    if (value.get('version') != VERSION or value.get('attempt') != str(root)
            or value.get('name') != name or value.get('request_name') != name+SUFFIX
            or value.get('max_attempts') != 1 or value.get('timeout_seconds') != 900
            or value.get('model') != 'gpt-6.1-sol' or value.get('semantics_changed') is not False
            or value.get('counter_reset') is not False or value.get('task') != task(root,name)
            or value.get('failure_bindings') != _failure(root,name)
            or value.get('qualification_bindings') != qualified_runtime(value['runtime'])):
        raise ValueError('CLI runtime recovery lineage/task/qualification changed')
    pending = value.get('pending_artifact')
    if pending and (pending.get('archive') != 'cli_runtime_recovery/'+name+'.preserved_static.json'
            or sha(checked_path(root,pending['archive'])) != pending['sha256']):
        raise ValueError('Incomplete static preimage archive changed')
    for key in ('frozen_bindings','accepted_bindings'):
        for rel,digest in value[key].items():
            if sha(checked_path(root,rel)) != digest:
                raise ValueError('CLI runtime recovery preserved binding changed: '+rel)
    if sha(Path(value['failed_binary'])) != value['failed_binary_sha256']:
        raise ValueError('Original CLI identity changed')
    batch.verify_inputs(root)
    return value


def response(root, name):
    root = Path(root).resolve()
    value = verify(root,name)
    folder = root/'model_calls'/value['request_name']
    result = codex.saved_model_response(root,value['request_name'])
    inv = batch.read(folder/'invocation.json')
    command = inv.get('command', [])
    if (inv.get('exit_code') != 0 or inv.get('model_requested') != value['model']
            or not command or Path(command[0]).resolve() != Path(value['runtime']['path']).resolve()
            or inv.get('cli_runtime',{}).get('sha256') != value['runtime']['sha256']
            or '--sandbox' not in command or command[command.index('--sandbox')+1] != 'read-only'
            or '--model' not in command or command[command.index('--model')+1] != value['model']
            or codex.tool_transport_failure(folder)
            or not transport.delivery_matches(folder,codex.READ_ONLY_EVAL_INSTRUCTIONS+value['task']['prompt'],value['task']['schema'])):
        raise ValueError('Accepted source recovery runtime/model/delivery changed')
    return result


def ensure(root, name, *, validator):
    root = Path(root).resolve()
    value = verify(root,name)
    folder = root/'model_calls'/value['request_name']
    if not folder.exists():
        # Persisted proof is mandatory; no global config mutation or implicit fallback.
        keys = ('A3GAME_CODEX_EXECUTABLE','A3GAME_CODEX_EXECUTABLE_SHA256')
        previous = {key:os.environ.get(key) for key in keys}
        try:
            os.environ[keys[0]],os.environ[keys[1]] = value['runtime']['path'],value['runtime']['sha256']
            codex.call_codex(root,name=value['request_name'],prompt=value['task']['prompt'],
                schema=value['task']['schema'],model=value['model'],timeout=value['timeout_seconds'],
                max_attempts=1,response_validator=validator)
        finally:
            for key,old in previous.items():
                if old is None:os.environ.pop(key,None)
                else:os.environ[key]=old
    path = response(root,name)
    validator(batch.read(path))
    return path


def run_static(root):
    from . import static_existence as static
    root = Path(root).resolve()
    protocol = batch.read(root/'input/pilot_rubric.json')
    value = verify(root,'static_existence')
    expected = static.schema(protocol,static.identity(root,protocol),batch.read(root/'input_manifest.json')['snapshot_hashes'])
    if value['task']['schema'] != expected:
        raise ValueError('Recovered static schema differs from original frozen contract')
    path = ensure(root,'static_existence',validator=lambda result:static.validate_result(root,protocol,result))
    dump(root/'static_existence.json',{'version':static.SCHEMA,'result':batch.read(path),
        'response_sha256':sha(path),'model':static.MODEL,'policy':static.policy(protocol)['version'],
        'cli_runtime_recovery_sha256':sha(_path(root,'static_existence'))})
    return static.load(root,protocol)


def verify_static(root, protocol):
    from . import static_existence as static
    root = Path(root).resolve()
    artifact = batch.read(root/'static_existence.json')
    path = response(root,'static_existence')
    if (artifact.get('version') != static.SCHEMA or artifact.get('model') != static.MODEL
            or artifact.get('policy') != static.policy(protocol)['version']
            or artifact.get('cli_runtime_recovery_sha256') != sha(_path(root,'static_existence'))
            or artifact.get('response_sha256') != sha(path) or artifact.get('result') != batch.read(path)):
        raise ValueError('Static recovery artifact differs from accepted source response')
    return static.validate_result(root,protocol,artifact['result'])
