"""One source-bound correction for a proven rejected source citation response.

Never edits a response or repairs a citation locally. The model must return a new
complete, schema-valid shard and pass the unchanged frozen-source validator.
"""
from pathlib import Path
import copy
import json
import re
from . import batch, codex, source_reference_transport as transport, static_existence
from .protocol import checked_path, dump, sha

VERSION = 'whitebox-source-invalid-reference-recovery.v1'
DIRECTORY = 'source_invalid_reference_recovery'


def _receipt(root, name):
    if not re.fullmatch(r'(?:static_existence_output_\d+(?:_single_\d+)?(?:_reference_transport)?|source_column_\d+)', name):
        raise ValueError('Invalid correction task name')
    return Path(root)/DIRECTORY/(name+'.json')


def registered(root, name):
    return bool(re.fullmatch(r"(?:static_existence_output_\d+(?:_single_\d+)?(?:_reference_transport)?|source_column_\d+)", name)) and _receipt(root, name).is_file()


def _response_value(folder):
    raw = folder/'response.json'
    if (folder/transport.DECODE).exists():
        decoded = folder/'source_reference_decoded_response.json'
        transport.verify_decoded(decoded, {'source_reference_receipt_sha256':sha(folder/transport.DECODE)})
        return batch.read(decoded)
    return batch.read(raw)


def _validate(root, value, delivery, kind):
    codex.validate_schema(value, delivery['schema'])
    if kind == 'static':
        from .static_output_recovery import validate_shard
        return validate_shard(root, batch.read(Path(root)/'input/pilot_rubric.json'), value, delivery)
    if kind == 'source':
        from .source_score_output_recovery import validate_shard
        return validate_shard(root, value, delivery)
    raise ValueError('Invalid correction kind')


def diagnose(root, failed_name, delivery, kind):
    root = Path(root).resolve(); folder = root/'model_calls'/failed_name
    if (folder/'accepted_response.json').exists():
        raise ValueError('Accepted source judgment protected')
    invocation = batch.read(folder/'invocation.json'); command = invocation.get('command', [])
    if (invocation.get('exit_code') != 0 or invocation.get('status') == 'TIMEOUT'
            or invocation.get('model_requested') != static_existence.MODEL
            or '--model' not in command or command[command.index('--model')+1] != static_existence.MODEL):
        raise ValueError('Requires a completed real model response, not a transport failure')
    value = _response_value(folder)
    codex.validate_schema(value, delivery['schema'])
    expected = batch.read(folder/'validation_error.json')['exception']
    allowed = ('invalid static source line range: ', 'static source SHA/path mismatch: ') if kind == 'static' else ('Source code-score evidence SHA mismatch', 'Source code-score physical lines are invalid')
    if not any(expected.startswith(p) for p in allowed):
        raise ValueError('Requires a proven strict source-reference validation failure')
    try:
        _validate(root, value, delivery, kind)
    except ValueError as error:
        if str(error) != expected:
            raise ValueError('Preserved source failure changed') from error
    else:
        raise ValueError('No current strict source-reference failure')
    hashes = batch.read(root/'input_manifest.json')['snapshot_hashes']; refs = []
    for ident, check in value['checks'].items():
        for index, ref in enumerate(check['evidence']):
            relative = ref['path']
            for prefix in ('input/project/', 'project/'):
                if relative.startswith(prefix) and relative[len(prefix):] in hashes:
                    relative = relative[len(prefix):]; break
            path = checked_path(root/'input/project', relative)
            if path.is_symlink() or hashes.get(relative) != sha(path):
                raise ValueError('Actual frozen source drift; not a model citation recovery')
            count = len(path.read_text(errors='replace').splitlines())
            refs.append({'check': ident, 'reference_index': index, 'original_reference': copy.deepcopy(ref),
                         'actual_path': relative, 'actual_sha256': hashes[relative], 'physical_line_count': count})
    bindings = {str(p.relative_to(root)): sha(p) for p in folder.iterdir() if p.is_file()}
    for name in ('input_manifest.json', 'input/pilot_rubric.json'):
        bindings[name] = sha(root/name)
    return {'failure': expected, 'references': refs, 'preserved_bindings': bindings}


def _suffix(value):
    return ('\n\nSOURCE REFERENCE VALIDATION FEEDBACK (non-scoring transport recovery):\n'
        'A preserved completed response was rejected by the unchanged strict source validator. '
        'Return a new complete response for exactly the original shard and schema. All original '
        'rubric, source, score, uncertainty and citation requirements remain in force. Read the '
        'actual frozen source and independently verify every SHA and physical 1-based inclusive '
        'line range. Never copy a guessed SHA or swap endpoints automatically. Metadata below is '
        'exact file identity/line-count information, not source interpretation or a judgment. '
        'It does not replace inspecting cited implementation. No original response is accepted '
        'or changed by this recovery. All siblings and failure counters remain preserved.\n'
        + json.dumps(value['diagnosis'], ensure_ascii=False, separators=(',', ':')) + '\n')


def prepare(root, name, failed_name, delivery, kind):
    root = Path(root).resolve(); path = _receipt(root, name)
    if path.exists() or (root/'model_calls'/(name+'_reference_validation_v1')).exists():
        raise ValueError('Source citation recovery already exists; no reset/retry')
    if not transport.delivery_matches(root/'model_calls'/failed_name, delivery['prompt'], delivery['schema']):
        # Shell compatibility has a source-bound, exact additional suffix.
        if kind != 'source': raise ValueError('Rejected delivery differs from original task')
        from .source_shell_timeout_recovery import verify as shell_verify
        shell = shell_verify(root, name)
        if failed_name != shell['request_name'] or (root/'model_calls'/failed_name/'prompt.txt').read_text() != delivery['prompt']+shell['prompt_suffix'] or batch.read(root/'model_calls'/failed_name/'schema.json') != delivery['schema']:
            raise ValueError('Rejected shell delivery differs from bound parent')
    from .unity_recovery import saved_score, attempts
    from .unity_queue import published
    ident = batch.read(root/'input_manifest.json')['entry']['id']
    if saved_score(attempts(root.parents[1],ident)) or published(root.parents[1],ident):
        raise ValueError('Existing complete score protected')
    diagnosis = diagnose(root, failed_name, delivery, kind)
    value = {'version': VERSION, 'attempt': str(root), 'name': name, 'failed_name': failed_name,
             'kind': kind, 'request_name': name+'_reference_validation_v1', 'delivery': delivery,
             'diagnosis': diagnosis, 'semantics_changed': False, 'max_attempts': 1}
    value['prompt_suffix'] = _suffix(value)
    # Preserve original shell compatibility when it was needed to inspect files.
    if kind == 'source':
        from .source_shell_timeout_recovery import registered as shell_registered, verify as shell_verify
        if shell_registered(root, name): value['prompt_suffix'] = shell_verify(root,name)['prompt_suffix']+value['prompt_suffix']
    path.parent.mkdir(exist_ok=True)
    with path.open('x') as stream: stream.write(json.dumps(value, ensure_ascii=False, indent=2)+'\n')
    return verify(root, name)


def verify(root, name):
    root = Path(root).resolve(); value = batch.read(_receipt(root,name))
    if (value.get('version') != VERSION or value.get('attempt') != str(root)
            or value.get('name') != name or value.get('request_name') != name+'_reference_validation_v1'
            or value.get('semantics_changed') is not False or value.get('max_attempts') != 1
            or value['diagnosis'] != diagnose(root,value['failed_name'],value['delivery'],value['kind'])):
        raise ValueError('Source citation recovery lineage changed')
    expected = _suffix(value)
    if value['kind'] == 'source':
        from .source_shell_timeout_recovery import registered as reg, verify as shell_verify
        if reg(root,name): expected = shell_verify(root,name)['prompt_suffix']+expected
    if value.get('prompt_suffix') != expected:
        raise ValueError('Source correction feedback changed')
    return value


def delivery_matches(root,name,path,delivery):
    value=verify(root,name)
    return (value['delivery']==delivery and Path(path).parent == Path(root)/'model_calls'/value['request_name']
            and transport.delivery_matches(Path(path).parent, delivery['prompt']+value['prompt_suffix'],delivery['schema']))


def response(root,name):
    value=verify(root,name);folder=Path(root)/'model_calls'/value['request_name']
    if not (folder/'accepted_response.json').exists():
        raise ValueError('Citation correction not accepted; preserve failed correction')
    path=codex.saved_model_response(Path(root),value['request_name'])
    from .static_output_recovery import _successful
    _successful(path)
    if not delivery_matches(root,name,path,value['delivery']):
        raise ValueError('Actual source correction delivery changed')
    _validate(root,batch.read(path),value['delivery'],value['kind'])
    return path


def ensure(root,name,delivery,timeout):
    root=Path(root);value=verify(root,name)
    if value['delivery'] != delivery: raise ValueError('Correction parent task changed')
    if not (root/'model_calls'/value['request_name']).exists():
        codex.call_codex(root,name=value['request_name'],prompt=delivery['call_prompt']+value['prompt_suffix'],
            schema=delivery['schema'],model=static_existence.MODEL,timeout=timeout,max_attempts=1,
            response_validator=lambda result:_validate(root,result,delivery,value['kind']))
    return response(root,name)
