"""One source-only correction for a retained frozen-trigger validator failure.

All source bytes, accepted siblings, original checks and the validator remain
unchanged. No recipe or finding is supplied locally.
"""
import copy
import hashlib
import json
from pathlib import Path
from . import mechanic_v3_runner as runner
from .codex import READ_ONLY_EVAL_INSTRUCTIONS, call_codex, saved_model_response, validate_schema
from .protocol import sha

VERSION = 'gameness-v4-static-trigger-recovery.v1'
ERROR = 'Trigger outside frozen common alternatives'


def contract_from_prompt(prompt):
    return json.loads(prompt.split('\nFROZEN CONTRACT:\n', 1)[1]
                      .split('\nCOMPLETE AUTHOR SOURCES:\n', 1)[0])


def strict_schema(schema, contract):
    """Expose the EXISTS-only constraint using the supported anyOf subset."""
    value = copy.deepcopy(schema)
    def resolved(node):
        while '$ref' in node:
            ref = node['$ref']
            if not ref.startswith('#/$defs/'):
                raise ValueError('Unsupported original schema reference')
            node = schema['$defs'][ref[len('#/$defs/'):]]
        return copy.deepcopy(node)
    for ident, original in schema['properties']['checks']['properties'].items():
        modes = contract['checks'][ident]['permitted_trigger_modes']
        if not modes or len(modes) != len(set(modes)):
            raise ValueError('Invalid frozen trigger alternatives')
        implemented = resolved(original)
        props = implemented['properties']
        props['source_existence'] = resolved(props['source_existence'])
        status = props['source_existence']['properties']['status']
        all_statuses = resolved(status)['enum']
        absent = copy.deepcopy(implemented)
        absent['properties']['source_existence']['properties']['status'] = dict(
            type='string', enum=[s for s in all_statuses if s != 'EXISTS'])
        props['source_existence']['properties']['status'] = dict(type='string',enum=['EXISTS'])
        props['trigger_recipe'] = resolved(props['trigger_recipe'])
        original_modes = resolved(props['trigger_recipe']['properties']['trigger_mode'])['enum']
        if not set(modes).issubset(original_modes):
            raise ValueError('Frozen mode outside original schema')
        props['trigger_recipe']['properties']['trigger_mode'] = dict(type='string',enum=modes)
        value['properties']['checks']['properties'][ident] = dict(anyOf=[implemented,absent])
    return value


def qualify(folder, policy, schema, prompt, actual, validator):
    folder = Path(folder); root = folder.parent.parent
    if policy.VERSION != 'whitebox-gameness10-50-100.v4' or (folder/'accepted_response.json').exists():
        raise ValueError('Only failed v4 source judgments qualify')
    error = runner.read(folder/'validation_error.json')
    if (error.get('phase') != 'response_plan_validation' or error.get('exception') != ERROR
            or error.get('response_sha256') != sha(folder/'response.json')):
        raise ValueError('Exact retained trigger failure required')
    if (runner.read(folder/'schema.json') != schema
            or (folder/'prompt.txt').read_text() != READ_ONLY_EVAL_INSTRUCTIONS+prompt
            or actual['prompt_sha256'] != sha(folder/'prompt.txt')
            or actual.get('all_author_sources_delivered') is not True
            or actual.get('runtime_evidence_supplied') is not False
            or actual.get('images') != []):
        raise ValueError('Complete original source-only request differs')
    invocation = runner.read(folder/'invocation.json'); command = invocation['command']
    events = [json.loads(s) for s in (folder/'events.jsonl').read_text().splitlines() if s.strip()]
    if (invocation.get('exit_code') != 0 or '--model' not in command or '--image' in command
            or command[command.index('--model')+1] != policy.MODEL
            or not events or events[-1].get('type') != 'turn.completed'):
        raise ValueError('Original source invocation is incomplete')
    binding = runner.read(root/'source_binding.json')
    if (sha(root/'source_binding.json') != actual['source_binding_sha256']
            or binding['contract_sha256'] != actual['contract_sha256']):
        raise ValueError('Original source or contract binding changed')
    for p,digest in binding['author_sources'].items():
        if sha(Path(p)) != digest: raise ValueError('Original author source changed')
    manifest = runner.read(root/'source_manifest.json')
    expected = {i['id']:(i['path'],i['sha256']) for i in manifest['items'] if i['type']=='source'}
    delivered = actual['complete_author_sources']
    if ({i['id']:(i['path'],i['sha256']) for i in delivered} != expected
            or len(delivered) != len(expected)):
        raise ValueError('Incomplete original source packet')
    for item in delivered:
        p = root/item['path']
        if sha(p) != item['sha256'] or len(p.read_text(errors='replace').splitlines()) != item['line_count']:
            raise ValueError('Delivered source or physical lines changed')
    raw = runner.read(folder/'response.json'); validate_schema(raw, schema)
    try: validator(raw)
    except ValueError as failure:
        if str(failure) != ERROR: raise ValueError('Original validator failure changed') from failure
    else: raise ValueError('Valid response must be reused')
    files = [folder/n for n in ['response.json','schema.json','prompt.txt','validation_error.json','invocation.json','events.jsonl']]
    files += [root/n for n in ['source_binding.json','source_manifest.json','citation_rules.json']]
    return {str(p):sha(p) for p in files}


def recover(folder, *, scoring_policy, schema, prompt, actual, validator):
    folder = Path(folder); root = folder.parent.parent
    parents = qualify(folder,scoring_policy,schema,prompt,actual,validator)
    contract = contract_from_prompt(prompt)
    enhanced = strict_schema(schema,contract)
    alternatives = {k:contract['checks'][k]['permitted_trigger_modes'] for k in actual['criterion_ids']}
    feedback = ('\nONE BOUNDED FROZEN TRIGGER CORRECTION: '+ERROR+'. '
        'Review all original source files and all requested checks again. For an EXISTS finding, '
        'trigger_recipe.trigger_mode must be one of that check\'s ORIGINAL permitted modes below. '
        'A delayed visible effect does not itself prove a delayed trigger: trace the author\'s '
        'actual activation input or automatic event. Select only a source-supported permitted mode; '
        'do not merely relabel unsupported actions, invent inputs, or change source findings to pass. '
        'If no supported recipe exists, report the actual uncertainty; the original validator still applies. '
        'No source findings or recipes are provided locally. Every source, criterion and original '
        'requirement above is unchanged. Return the complete schema.\nORIGINAL PER-CHECK ALTERNATIVES:\n'
        +json.dumps(alternatives,ensure_ascii=False))
    submitted = prompt+feedback
    if len((READ_ONLY_EVAL_INSTRUCTIONS+submitted).encode()) > 1000000:
        raise ValueError('Complete trigger correction exceeds unchanged prompt cap')
    name = folder.name+'_frozen_trigger_correction_v1'
    code = Path(__file__).resolve()
    claim = dict(version=VERSION,parent_bindings=parents,task=name,
        production_bindings={str(p):sha(p) for p in [code,code.with_name('gameness_v3_static.py'),code.with_name('gameness_v4.py')]},
        prompt_sha256=hashlib.sha256(submitted.encode()).hexdigest(),schema=enhanced,
        original_validator_required=True,source_packet_unchanged=True,original_failure_preserved=True,
        local_findings_filled=False,max_new_calls=1)
    path = root/'engineering/static_trigger_recovery'/folder.name/'claim.json'
    if path.exists():
        if runner.read(path) != claim: raise ValueError('Retained trigger correction claim changed')
    else: runner.exclusive_json(path,claim)
    call = root/'model_calls'/name
    if call.exists():
        if not (call/'accepted_response.json').exists():
            raise ValueError('Bounded trigger correction already attempted; preserve failure')
        if (runner.read(call/'schema.json') != enhanced
                or (call/'prompt.txt').read_text() != READ_ONLY_EVAL_INSTRUCTIONS+submitted):
            raise ValueError('Saved trigger correction request changed')
        value = runner.read(saved_model_response(root,name)); validate_schema(value,enhanced); validator(value)
    else:
        value = call_codex(root,name=name,prompt=submitted,schema=enhanced,model=scoring_policy.MODEL,
            timeout=900,max_attempts=1,response_validator=validator)
    delivered = copy.deepcopy(actual); delivered['prompt_sha256'] = sha(call/'prompt.txt')
    delivered['parent_validation_failure'] = dict(path=str(folder/'validation_error.json'),sha256=sha(folder/'validation_error.json'))
    from .mechanic_v3_execution import audit_invocation
    audit_invocation(root,name,delivered)
    files = [path]+[call/n for n in ['response.json','accepted_response.json','prompt.txt','schema.json','invocation.json','events.jsonl','actual_delivery.json']]
    result = dict(version=VERSION,parent_bindings=parents,bindings={str(p):sha(p) for p in files},
        model_recalled=True,full_original_validator_passed=True,original_failure_preserved=True,local_findings_filled=False)
    receipt = path.parent/'receipt.json'
    if receipt.exists():
        if runner.read(receipt) != result: raise ValueError('Trigger recovery receipt changed')
    else: runner.exclusive_json(receipt,result)
    return value,dict(path=str(receipt),sha256=sha(receipt))
