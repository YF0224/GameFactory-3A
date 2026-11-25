"""Failure-bound source review when original invocation metadata was lost.

Terminal events prove only a retained response, never its model or OS exit.
Preserve it and admit one independently audited Sol call with full inline schema.
No original response is promoted to accepted, and no invocation is fabricated.
"""
import copy
import hashlib
import json
import re
from pathlib import Path
from . import mechanic_v3_runner as runner
from .codex import READ_ONLY_EVAL_INSTRUCTIONS, call_codex, saved_model_response, validate_schema
from .protocol import sha

VERSION = 'gameness-v4-orphan-source-invocation-recovery.v1'


def qualify(folder, scoring_policy, schema, prompt, actual, validator):
    folder = Path(folder); root = folder.parent.parent
    if (scoring_policy.VERSION != 'whitebox-gameness10-50-100.v4'
            or not re.fullmatch(r'gameness_source_v1_[0-9]+', folder.name)
            or any((folder/n).exists() for n in ['invocation.json', 'accepted_response.json',
                'validation_error.json', 'parse_error.json'])):
        raise ValueError('Only an unaccepted orphan source invocation qualifies')
    if (runner.read(folder/'schema.json') != schema
            or (folder/'prompt.txt').read_text() != READ_ONLY_EVAL_INSTRUCTIONS+prompt
            or sha(folder/'prompt.txt') != actual.get('prompt_sha256')
            or actual.get('model') != scoring_policy.MODEL or actual.get('images') != []
            or actual.get('all_author_sources_delivered') is not True
            or actual.get('runtime_evidence_supplied') is not False
            or actual.get('old_scores_supplied') is not False):
        raise ValueError('Original complete orphan source request differs')
    failure = root/'engineering/orphan_source_invocation'/folder.name/'original_failure.json'
    if not failure.exists(): failure = root/'failures'/(folder.name+'.json')
    error = runner.read(failure)
    if (error.get('category') != 'HARNESS_ERROR' or error.get('product_score') is not None
            or 'Retained failed source request needs substantive bound recovery' not in error.get('error', '')):
        raise ValueError('Retained orphan dispatcher failure required')
    events = [json.loads(s) for s in (folder/'events.jsonl').read_text().splitlines() if s.strip()]
    messages = [e['item']['text'] for e in events
        if e.get('type') == 'item.completed' and e.get('item', {}).get('type') == 'agent_message']
    if (not events or events[-1].get('type') != 'turn.completed' or not messages
            or messages[-1].strip() != (folder/'response.json').read_text().strip()
            or sum(e.get('type') == 'turn.started' for e in events) != 1
            or sum(e.get('type') == 'turn.completed' for e in events) != 1):
        raise ValueError('One complete original terminal response required; no exit status inferred')
    raw = runner.read(folder/'response.json'); validate_schema(raw, schema); validator(raw)
    binding = runner.read(root/'source_binding.json')
    if (binding.get('identity') != actual.get('identity')
            or binding.get('scoring_protocol') != scoring_policy.VERSION
            or binding.get('contract_sha256') != actual.get('contract_sha256')
            or sha(root/'source_binding.json') != actual.get('source_binding_sha256')):
        raise ValueError('Orphan original source identity/contract differs')
    for p, digest in binding['author_sources'].items():
        if sha(Path(p)) != digest: raise ValueError('Original author source changed')
    manifest = runner.read(root/'source_manifest.json')
    expected = {i['id']:(i['path'], i['sha256']) for i in manifest['items'] if i['type'] == 'source'}
    supplied = actual['complete_author_sources']
    if (len(supplied) != len(expected) or {i['id']:(i['path'],i['sha256']) for i in supplied} != expected
            or binding['source_sha256_by_id'] != {k:v[1] for k,v in expected.items()}):
        raise ValueError('Orphan source packet incomplete')
    for item in supplied:
        file = root/item['path']
        if sha(file) != item['sha256'] or len(file.read_text(errors='replace').splitlines()) != item['line_count']:
            raise ValueError('Orphan delivered bytes/physical lines changed')
    files = [folder/n for n in ['response.json','schema.json','prompt.txt','events.jsonl','budget.json','cli_runtime.json','stderr.log']]
    files += [failure, root/'source_binding.json',root/'source_manifest.json',root/'citation_rules.json',
              root/'requests'/folder.name/'actual_delivery.json']
    if runner.read(files[-1]) != actual: raise ValueError('Orphan actual delivery changed')
    return {str(p.resolve()):sha(p) for p in files}


def recover(folder, *, scoring_policy, schema, prompt, actual, validator):
    folder = Path(folder); root = folder.parent.parent
    qualify(folder, scoring_policy, schema, prompt, actual, validator)
    original_failure = root/'engineering/orphan_source_invocation'/folder.name/'original_failure.json'
    if not original_failure.exists():
        original_failure.parent.mkdir(parents=True, exist_ok=True)
        with original_failure.open('xb') as handle:
            handle.write((root/'failures'/(folder.name+'.json')).read_bytes())
    parents = qualify(folder, scoring_policy, schema, prompt, actual, validator)
    name = folder.name+'_audited_invocation_v1'
    submitted = (prompt+'\nRECOVERY OF LOST INVOCATION METADATA. The earlier response is preserved '
        'but cannot qualify because its model command and process exit status were not saved. '
        'Perform a fresh independent source-only review of ALL sources and checks above. '
        'Do not read earlier findings. This invocation must complete with the original validator. '
        'Use the complete inline schema below; do not repeatedly read schema paths.\nCOMPLETE SCHEMA:\n'
        +json.dumps(schema,ensure_ascii=False,separators=(',',':')))
    if len((READ_ONLY_EVAL_INSTRUCTIONS+submitted).encode()) > 1000000:
        raise ValueError('Complete orphan recovery exceeds unchanged request cap')
    path = root/'engineering/orphan_source_invocation'/folder.name/'claim.json'
    code = Path(__file__).resolve()
    value = dict(version=VERSION,parent_bindings=parents,task=name,
        production_bindings={str(p):sha(p) for p in [code,code.with_name('gameness_v3_static.py'),code.with_name('gameness_v4.py')]},
        submitted_prompt_sha256=hashlib.sha256((READ_ONLY_EVAL_INSTRUCTIONS+submitted).encode()).hexdigest(),
        original_model_proven=False,original_exit_status_proven=False,
        original_response_promoted=False,original_failure_preserved=True,max_new_calls=1,
        original_validator_required=True,scoring_semantics_changed=False)
    if path.exists():
        if runner.read(path) != value: raise ValueError('Orphan invocation recovery claim changed')
    else: runner.exclusive_json(path,value)
    call = root/'model_calls'/name
    if call.exists():
        if not (call/'accepted_response.json').is_file():
            raise ValueError('Bounded orphan recovery already attempted; preserve failure')
        if (runner.read(call/'schema.json') != schema
                or (call/'prompt.txt').read_text() != READ_ONLY_EVAL_INSTRUCTIONS+submitted):
            raise ValueError('Retained independent source request differs')
        raw = runner.read(saved_model_response(root,name)); validate_schema(raw,schema); validator(raw)
    else:
        raw = call_codex(root,name=name,prompt=submitted,schema=schema,model=scoring_policy.MODEL,
            timeout=900,max_attempts=1,response_validator=validator)
    invocation = runner.read(call/'invocation.json'); command = invocation.get('command',[])
    if ('--model' not in command or command[command.index('--model')+1] != scoring_policy.MODEL):
        raise ValueError('Independent source invocation model differs')
    delivered = copy.deepcopy(actual); delivered['prompt_sha256'] = sha(call/'prompt.txt')
    delivered['orphan_parent'] = dict(path=str(folder),original_model_proven=False,original_exit_status_proven=False)
    from .mechanic_v3_execution import audit_invocation
    audit_invocation(root,name,delivered)
    files = [path]+[call/n for n in ['response.json','accepted_response.json','prompt.txt','schema.json',
                                   'invocation.json','events.jsonl','actual_delivery.json','v3_delivery_verified.json']]
    receipt = dict(version=VERSION,parent_bindings=parents,bindings={str(p):sha(p) for p in files},
        task=name,model_recalled=True,original_invocation_fabricated=False,
        original_response_promoted=False,full_original_validator_passed=True)
    dest = path.parent/'receipt.json'
    # The per-call audit includes a timestamp. Bind stable audit facts, not time.
    receipt['bindings'].pop(str(call/'v3_delivery_verified.json'))
    if dest.exists():
        if runner.read(dest) != receipt: raise ValueError('Orphan invocation receipt changed')
    else: runner.exclusive_json(dest,receipt)
    return raw,dict(path=str(dest),sha256=sha(dest))
