"""Bounded full-source review continuation with explicit validator feedback.

Never edit a model finding or a physical citation. Preserve the exhausted first
correction and accepted sibling shards; strengthen only constraints already
required by the original validator and retain all original author bytes.
"""
import copy
import hashlib
import json
from pathlib import Path
from . import mechanic_v3_runner as runner
from . import gameness_v4_static_review_recovery as first
from .codex import READ_ONLY_EVAL_INSTRUCTIONS, call_codex, saved_model_response, validate_schema
from .protocol import sha

VERSION = 'gameness-v4-static-validation-continuation.v1'
ERRORS = {first.ERROR, 'Invalid physical line range'}
CONTINUATION = 'engineering/static_validator_producer_continuation.json'


RETAINED = 'engineering/accepted_static_producer_continuation.json'


def authorize_retained(root, before_files, engineering_receipt):
    """Retain an accepted correction across an exact non-scoring producer delta."""
    root = Path(root).resolve(); code = Path(__file__).resolve().parent
    allowed = {str(code/name) for name in
        ['gameness_v3_static.py', 'gameness_v4_static_validation_recovery.py']}
    archives = {str(Path(p).resolve()):Path(a).resolve() for p,a in before_files.items()}
    if not archives or set(archives)-allowed:
        raise ValueError('Unrelated accepted static producer delta')
    proof = Path(engineering_receipt).resolve(); diagnosis = runner.read(proof)
    if (diagnosis.get('classification') != 'NON_SCORING_ACCEPTED_STATIC_PRODUCER_CONTINUATION'
            or diagnosis.get('original_validator_unchanged') is not True
            or diagnosis.get('new_model_calls') != 0):
        raise ValueError('Explicit non-scoring producer diagnosis required')
    claims = {}; files = [proof, Path(__file__).resolve()]
    for path in sorted((root/'engineering/static_validation_continuation').glob('*/claim.json')):
        saved = runner.read(path); production = saved['production_bindings']
        drift = {p:d for p,d in production.items() if sha(Path(p)) != d}
        if not drift: continue
        if set(drift) != set(archives):
            raise ValueError('Exact archived accepted producer set required')
        for current,d in drift.items():
            archive = archives[current]
            if archive.name != Path(current).name or sha(archive) != d:
                raise ValueError('Archived accepted producer bytes differ')
        call = root/'model_calls'/saved['task']; receipt = path.parent/'receipt.json'
        # No new or pending invocation can be authorized by this path.
        accepted = call/'accepted_response.json'
        runner.read(saved_model_response(root,saved['task']))
        original_receipt = runner.read(receipt)
        for name,d in {**saved['parent_bindings'],**original_receipt['bindings']}.items():
            if sha(Path(name)) != d: raise ValueError('Accepted static parent artifact changed: '+name)
        claims[str(path)] = dict(before=production,
            after={name:sha(Path(name)) for name in production})
        files.extend([path,receipt,accepted,*map(Path,saved['parent_bindings']),
            *map(Path,original_receipt['bindings'])])
    if not claims: raise ValueError('No already accepted static continuation qualifies')
    files.extend(archives.values()); files.extend(map(Path,archives))
    value = dict(version=VERSION,claims=claims,original_validator_required=True,
        new_model_calls=0,old_failures_preserved=True,
        bindings={str(p):sha(p) for p in files})
    path = root/RETAINED
    if path.exists():
        if runner.read(path) != value: raise ValueError('Accepted static producer continuation changed')
    else: runner.exclusive_json(path,value)
    return value


def verify_retained(root, path, before, after):
    value = runner.read(Path(root)/RETAINED)
    if (value.get('version') != VERSION or value.get('new_model_calls') != 0
            or value.get('original_validator_required') is not True
            or value['claims'].get(str(path)) != dict(before=before,after=after)):
        raise ValueError('Missing exact accepted static producer continuation')
    for name,d in value['bindings'].items():
        if sha(Path(name)) != d: raise ValueError('Accepted static producer binding changed: '+name)


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def authorize_producer(root, before, engineering_receipt):
    """Bind the exact old dispatcher; no author data or validator waiver."""
    root = Path(root).resolve(); before = Path(before).resolve()
    current = Path(__file__).with_name('gameness_v3_static.py').resolve()
    proof = Path(engineering_receipt).resolve()
    if before.name != current.name or sha(before) == sha(current):
        raise ValueError('Exact changed static dispatcher archive required')
    claims = list((root/'engineering/complete_static_review_feedback').glob('*/claim.json'))
    affected = [p for p in claims if runner.read(p)['production_bindings'].get(str(current)) == sha(before)]
    if not affected:
        raise ValueError('No original correction claim binds this exact dispatcher')
    files = [before, current, proof, Path(__file__).resolve(), *affected]
    value = dict(version=VERSION, before_path=str(before), before_sha256=sha(before),
        after_path=str(current), after_sha256=sha(current), claims=[str(p) for p in affected],
        bindings={str(p):sha(p) for p in files}, local_findings_filled=False,
        original_validator_required=True, old_failures_preserved=True)
    path = root/CONTINUATION
    if path.exists():
        if runner.read(path) != value: raise ValueError('Existing static producer continuation differs')
    else: runner.exclusive_json(path, value)
    return value


def verify_producers(root, claim_path, bindings):
    drift = {p:d for p,d in bindings.items() if sha(Path(p)) != d}
    if not drift: return
    current = Path(__file__).with_name('gameness_v3_static.py').resolve()
    if set(drift) != {str(current)}:
        raise ValueError('Unrelated static correction producer drift')
    value = runner.read(root/CONTINUATION)
    if (value.get('version') != VERSION or str(claim_path) not in value['claims']
            or value['before_sha256'] != drift[str(current)]
            or value['after_path'] != str(current) or value['after_sha256'] != sha(current)):
        raise ValueError('Missing exact source-review dispatcher continuation')
    for p,d in value['bindings'].items():
        if sha(Path(p)) != d: raise ValueError('Static dispatcher continuation changed: '+p)


def qualify(folder, policy, schema, prompt, actual, validator):
    folder = Path(folder); root = folder.parent.parent
    if policy.VERSION != 'whitebox-gameness10-50-100.v4' or (folder/'accepted_response.json').exists():
        raise ValueError('Only a retained failed v4 source response qualifies')
    error = runner.read(folder/'validation_error.json')
    if (error.get('phase') != 'response_plan_validation' or error.get('exception') not in ERRORS
            or error.get('response_sha256') != sha(folder/'response.json')):
        raise ValueError('Unsupported or changed static validation failure')
    if (runner.read(folder/'schema.json') != schema
            or (folder/'prompt.txt').read_text() != READ_ONLY_EVAL_INSTRUCTIONS+prompt
            or actual['prompt_sha256'] != sha(folder/'prompt.txt')
            or actual.get('all_author_sources_delivered') is not True
            or actual.get('runtime_evidence_supplied') is not False):
        raise ValueError('Original full-source request differs')
    invocation = runner.read(folder/'invocation.json'); command = invocation['command']
    events = [json.loads(s) for s in (folder/'events.jsonl').read_text().splitlines() if s.strip()]
    if (invocation.get('exit_code') != 0 or '--model' not in command or '--image' in command
            or command[command.index('--model')+1] != policy.MODEL
            or not events or events[-1].get('type') != 'turn.completed'):
        raise ValueError('Completed source-only frozen-model call required')
    binding = runner.read(root/'source_binding.json')
    if sha(root/'source_binding.json') != actual['source_binding_sha256']:
        raise ValueError('Original source binding changed')
    for p,d in binding['author_sources'].items():
        if sha(Path(p)) != d: raise ValueError('Original author source changed')
    manifest = runner.read(root/'source_manifest.json')
    expected = {i['id']:(i['path'],i['sha256']) for i in manifest['items'] if i['type']=='source'}
    if {i['id']:(i['path'],i['sha256']) for i in actual['complete_author_sources']} != expected:
        raise ValueError('Incomplete original source packet')
    for item in actual['complete_author_sources']:
        p = root/item['path']
        if sha(p) != item['sha256'] or len(p.read_text(errors='replace').splitlines()) != item['line_count']:
            raise ValueError('Delivered source bytes or physical lines changed')
    raw = runner.read(folder/'response.json'); validate_schema(raw, schema)
    try: validator(raw)
    except ValueError as failure:
        if str(failure) != error['exception']: raise ValueError('Original validation failure changed') from failure
    else: raise ValueError('Valid response must be reused')
    files = [folder/n for n in ['response.json','schema.json','prompt.txt','validation_error.json','invocation.json','events.jsonl']]
    files += [root/n for n in ['source_binding.json','source_manifest.json','citation_rules.json']]
    return {str(p):sha(p) for p in files}


def strict_schema(schema, source_ids):
    value = copy.deepcopy(schema)
    # These are exactly the existing completeness/uniqueness constraints.
    value['properties']['inspected_source_ids'] = dict(type='array',
        items=dict(type='string', enum=sorted(source_ids)), minItems=len(source_ids),
        maxItems=len(source_ids), uniqueItems=True)
    return value


def recover(folder, *, scoring_policy, schema, prompt, actual, validator):
    folder = Path(folder); root = folder.parent.parent
    parents = qualify(folder, scoring_policy, schema, prompt, actual, validator)
    old_claim_path = root/'engineering/complete_static_review_feedback'/folder.name/'claim.json'
    old_call = root/'model_calls'/(folder.name+'_complete_review_feedback_v1')
    if old_claim_path.exists():
        claim = runner.read(old_claim_path)
        if claim['parent_bindings'] != parents: raise ValueError('First correction parent changed')
        verify_producers(root, old_claim_path, claim['production_bindings'])
        if old_call.exists():
            old_prompt = (old_call/'prompt.txt').read_text()
            if (runner.read(old_call/'schema.json') != schema
                    or not old_prompt.startswith(READ_ONLY_EVAL_INSTRUCTIONS+prompt)
                    or digest(old_prompt[len(READ_ONLY_EVAL_INSTRUCTIONS):]) != claim['prompt_sha256']):
                raise ValueError('First correction request changed')
        if old_call.exists() and (old_call/'accepted_response.json').exists():
            value = runner.read(saved_model_response(root, old_call.name)); validator(value)
            receipt = old_claim_path.parent/'receipt.json'; saved = runner.read(receipt)
            for p,d in saved['bindings'].items():
                if sha(Path(p)) != d: raise ValueError('Accepted first correction artifact changed')
            return value, dict(path=str(receipt), sha256=sha(receipt))
        if not (old_call/'validation_error.json').exists():
            raise ValueError('First correction must finish before a diagnosed continuation')
        err = runner.read(old_call/'validation_error.json')
        if (err.get('phase') != 'response_plan_validation' or err.get('exception') not in ERRORS
                or err.get('response_sha256') != sha(old_call/'response.json')):
            raise ValueError('Unsupported exhausted correction failure')
        invocation = runner.read(old_call/'invocation.json'); command = invocation['command']
        events = [json.loads(line) for line in (old_call/'events.jsonl').read_text().splitlines() if line.strip()]
        if (invocation.get('exit_code') != 0 or '--model' not in command or '--image' in command
                or command[command.index('--model')+1] != scoring_policy.MODEL
                or not events or events[-1].get('type') != 'turn.completed'):
            raise ValueError('Exhausted correction invocation incomplete')
        rejected = runner.read(old_call/'response.json'); validate_schema(rejected, schema)
        try: validator(rejected)
        except ValueError as failure:
            if str(failure) != err['exception']:
                raise ValueError('Exhausted correction validator failure changed') from failure
        else: raise ValueError('Valid first correction must be reused')
        paths = [old_claim_path]+[old_call/n for n in ['prompt.txt','schema.json','response.json','validation_error.json','invocation.json','events.jsonl']]
        parents.update({str(p):sha(p) for p in paths})
    elif runner.read(folder/'validation_error.json')['exception'] == first.ERROR:
        # Preserve the original one-correction path for genuinely new failures.
        return first.recover(folder, scoring_policy=scoring_policy, schema=schema,
            prompt=prompt, actual=actual, validator=validator)
    ids = [i['id'] for i in actual['complete_author_sources']]
    rules = runner.read(root/'citation_rules.json')
    enhanced = strict_schema(schema, ids)
    feedback = ('\nBOUNDED SOURCE VALIDATOR CONTINUATION: all earlier failed responses are retained. '
        'Review every delivered original source before reporting its ID. The stricter inspected_source_ids '
        'schema only expresses the original exact completeness validator; do not copy IDs without review. '
        'Every source citation MUST use original physical lines with line_start <= line_end. '
        'An inverted range is invalid: reread the relevant original lines and provide a correct supported '
        'citation; do not blindly swap endpoints. Do not alter findings merely to obtain validation. '
        'All original check meanings, full sources, and the final validator are unchanged. '
        'No runtime credit is available. Return the complete schema for every requested check.\n'
        'EXACT PHYSICAL SOURCE LIMITS:\n'+json.dumps(rules,ensure_ascii=False))
    submitted = prompt+feedback
    if len((READ_ONLY_EVAL_INSTRUCTIONS+submitted).encode()) > 1000000:
        raise ValueError('Complete static continuation exceeds unchanged prompt cap')
    name = folder.name+'_validation_continuation_v1'
    path = root/'engineering/static_validation_continuation'/folder.name/'claim.json'
    files = [Path(__file__).resolve(), Path(__file__).with_name('gameness_v3_static.py'),
             Path(__file__).with_name('gameness_v4.py')]
    claim = dict(version=VERSION, parent_bindings=parents, task=name,
        prompt_sha256=digest(submitted), schema=enhanced,
        production_bindings={str(p):sha(p) for p in files}, original_validator_required=True,
        original_source_packet_unchanged=True, earlier_failures_preserved=True, local_findings_filled=False)
    if path.exists():
        saved = runner.read(path)
        if {k:v for k,v in saved.items() if k!='production_bindings'} != {k:v for k,v in claim.items() if k!='production_bindings'}:
            raise ValueError('Retained static continuation changed')
        if saved['production_bindings'] != claim['production_bindings']:
            verify_retained(root,path,saved['production_bindings'],claim['production_bindings'])
    else: runner.exclusive_json(path, claim)
    call = root/'model_calls'/name
    if call.exists():
        if not (call/'accepted_response.json').exists():
            raise ValueError('Bounded static validation continuation already attempted; preserve failure')
        if (runner.read(call/'schema.json') != enhanced
                or (call/'prompt.txt').read_text() != READ_ONLY_EVAL_INSTRUCTIONS+submitted):
            raise ValueError('Saved static continuation request changed')
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
        if runner.read(receipt) != result: raise ValueError('Static continuation receipt changed')
    else: runner.exclusive_json(receipt,result)
    return value,dict(path=str(receipt),sha256=sha(receipt))
