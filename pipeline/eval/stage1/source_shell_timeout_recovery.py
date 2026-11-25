"""Source-bound continuation after proven read-only shell incompatibility.

Only shell execution guidance changes. Original task/schema/context and source
validators remain intact; old failed calls and counters are never rewritten.
"""
from pathlib import Path
import json
import math
import os
import re
from . import batch, codex, static_existence
from .protocol import dump, sha

VERSION = 'whitebox-source-shell-timeout-recovery.v1'
DIRECTORY = 'source_shell_timeout_recovery'


def _path(root, name):
    if not re.fullmatch(r'source_column_\d{2}', name):
        raise ValueError('Exact source-column identity required')
    return Path(root)/DIRECTORY/(name+'.json')


def registered(root, name):
    return bool(re.fullmatch(r'source_column_\d{2}', name)) and _path(root, name).is_file()


def qualify(root, name, interpreter):
    root = Path(root).resolve()
    folder = root/'model_calls'/name
    invocation = batch.read(folder/'invocation.json')
    budget = batch.read(folder/'budget.json')
    duration = budget.get('effective_timeout_seconds')
    elapsed = invocation.get('seconds')
    interpreter = Path(interpreter).resolve()
    if (invocation.get('status') != 'TIMEOUT'
            or invocation.get('model_requested') != static_existence.MODEL
            or any(type(x) not in (int,float) or not math.isfinite(x) for x in (duration,elapsed))
            or duration < 300 or elapsed < duration-1 or elapsed > duration+30
            or not interpreter.is_absolute() or not interpreter.is_file()
            or not os.access(interpreter,os.X_OK)
            or any((folder/x).exists() for x in ('response.json','accepted_response.json'))):
        raise ValueError('Preserved source timeout and pinned interpreter required')
    proofs=[]
    for line_number, line in enumerate((folder/'events.jsonl').read_text().splitlines(),1):
        event=json.loads(line);item=event.get('item',{})
        if event.get('type')!='item.completed' or item.get('type')!='command_execution':continue
        output=item.get('aggregated_output',''); command=item.get('command','')
        if ('here document: operation not permitted' in output and '<<' in command):
            proofs.append({'line':line_number,'kind':'READ_ONLY_HEREDOC_TEMP_DENIED'})
        if ("couldn't create cache file '/tmp/xcrun_db-" in output
                and 'Operation not permitted' in output and 'python3' in command):
            proofs.append({'line':line_number,'kind':'SYSTEM_PYTHON_XCRUN_TEMP_DENIED'})
    if {x['kind'] for x in proofs}!={'READ_ONLY_HEREDOC_TEMP_DENIED','SYSTEM_PYTHON_XCRUN_TEMP_DENIED'}:
        raise ValueError('Both original shell incompatibilities must be proven')
    names=[p for p in folder.iterdir() if p.is_file()]
    names += [root/'input_manifest.json',root/'input/pilot_rubric.json',root/'static_existence.json',
              root/'source_column_delivery'/(name+'.json')]
    return {'failure_classification':'TIMEOUT_WITH_READ_ONLY_SHELL_ERRORS',
            'tool_errors_observed':proofs,
            'timeout_seconds':int(duration),
            'interpreter':str(interpreter),'interpreter_sha256':sha(interpreter),
            'original_bindings':{str(p.relative_to(root)):sha(p) for p in names}}


def suffix(value):
    # A JSON string is a safe Python literal for this constrained absolute path.
    interpreter=value['interpreter']
    return ('\n\nREAD-ONLY SHELL EXECUTION COMPATIBILITY (tool transport only):\n'
        'The preserved attempt encountered denied temporary-file creation in shell here-documents '
        'and the system Python/xcrun launcher. Use the pinned standalone Python executable '
        +json.dumps(interpreter)+' with -B -c and a quoted inline program for JSON parsing and hashing. '
        'Use direct read-only commands such as rg, sed, nl and wc. Avoid here-documents, '
        'temporary files and the system python3 launcher. All original project/rubric files remain available. '
        'This changes shell invocation syntax only; retain every original column binding, complete '
        'rubric context, source evidence path/SHA/physical-line requirement, score/null rule and '
        'runtime/visual uncertainty. Return exactly the original schema.\n')


def prepare(root, name, interpreter):
    root=Path(root).resolve();path=_path(root,name)
    if path.exists():raise ValueError('Existing recovery identity protected')
    qualification=qualify(root,name,interpreter)
    from .source_score_output_recovery import _lineage,RECEIPT
    _lineage(root,batch.read(root/RECEIPT))
    from .unity_recovery import attempts,saved_score
    from .unity_queue import published
    ident=batch.read(root/'input_manifest.json')['entry']['id']
    if saved_score(attempts(root.parents[1],ident)) or published(root.parents[1],ident):
        raise ValueError('Existing score protected')
    value={'version':VERSION,'source_attempt':str(root),'source_name':name,
           'request_name':name+'_shell_compat_v1','qualification':qualification,
           'old_failures_claims_counters_preserved':True,'scoring_semantics_changed':False}
    value['prompt_suffix']=suffix(qualification)
    path.parent.mkdir(exist_ok=True)
    # Exclusive creation binds a single continuation; never reset a failed call.
    with path.open('x') as stream:stream.write(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    return verify(root,name)


def verify(root,name):
    root=Path(root).resolve();value=batch.read(_path(root,name))
    if (value.get('version')!=VERSION or value.get('source_attempt')!=str(root)
            or value.get('source_name')!=name or value.get('request_name')!=name+'_shell_compat_v1'
            or value.get('scoring_semantics_changed') is not False
            or value.get('old_failures_claims_counters_preserved') is not True
            or value['qualification']!=qualify(root,name,value['qualification']['interpreter'])
            or value.get('prompt_suffix')!=suffix(value['qualification'])):
        raise ValueError('Original failure/interpreter/shell recovery changed')
    return value


def response(root,name):
    value=verify(root,name)
    from .source_score_output_recovery import _response
    return _response(Path(root),value['request_name'])


def validate_delivery(root,name,path,delivery):
    value=verify(root,name)
    original=batch.read(Path(root)/'source_column_delivery'/(name+'.json'))
    if delivery!=original:raise ValueError('Parent source task/schema changed')
    return ((path.parent/'prompt.txt').read_text()==delivery['prompt']+value['prompt_suffix']
            and batch.read(path.parent/'schema.json')==delivery['schema']
            and path.parent==Path(root)/'model_calls'/value['request_name'])


def ensure(root,name,delivery,remaining):
    root=Path(root);value=verify(root,name);new_name=value['request_name']
    folder=root/'model_calls'/new_name
    if not folder.exists():
        from .source_score_output_recovery import validate_shard
        codex.call_codex(root,name=new_name,prompt=delivery['call_prompt']+value['prompt_suffix'],
            schema=delivery['schema'],model=static_existence.MODEL,max_attempts=1,
            timeout=min(remaining,value['qualification']['timeout_seconds']),
            response_validator=lambda v:validate_shard(root,v,delivery))
    result=response(root,name)
    if not validate_delivery(root,name,result,delivery):raise ValueError('Actual shell continuation delivery changed')
    return result
