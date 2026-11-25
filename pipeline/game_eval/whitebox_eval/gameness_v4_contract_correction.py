"""One SHA-bound source-contract correction; original validators stay unchanged.

Only completed v4 replies missing frozen bug/trigger alternatives qualify.
The same complete source packet/schema is resent with validator feedback.
No contract field is filled locally and no accepted contract is replaced.
"""
from pathlib import Path
import json
import hashlib
from . import gameness_v4 as policy, mechanic_v3_runner as runner
from .codex import READ_ONLY_EVAL_INSTRUCTIONS, call_codex, saved_model_response, validate_schema
from .protocol import sha

VERSION = 'gameness-v4-contract-validator-feedback.v1'
ERROR = 'Freeze basic bugs and trigger alternatives'
PARENT = 'gameness_v4_source_contract'
CORRECTED = PARENT + '_validator_feedback_v1'


def qualify_parent(folder, protocol, prompt, schema):
    folder = Path(folder); call = folder/'model_calls'/PARENT
    if (call/'accepted_response.json').exists() or (folder/'frozen.json').exists():
        raise ValueError('Never correct an accepted/frozen source contract')
    error = runner.read(call/'validation_error.json')
    if (error.get('phase') != 'response_plan_validation' or error.get('exception') != ERROR
            or error.get('response_sha256') != sha(call/'response.json')):
        raise ValueError('Not the exact SHA-bound source-contract failure')
    if (runner.read(call/'schema.json') != schema
            or (call/'prompt.txt').read_text() != READ_ONLY_EVAL_INSTRUCTIONS + prompt):
        raise ValueError('Original complete source request/schema changed')
    invocation = runner.read(call/'invocation.json'); command = invocation.get('command', [])
    if (invocation.get('exit_code') != 0 or '--model' not in command
            or command[command.index('--model')+1] != policy.MODEL
            or '--image' in command):
        raise ValueError('Completed source-only frozen-model invocation required')
    events = [json.loads(line) for line in (call/'events.jsonl').read_text().splitlines() if line.strip()]
    if not events or events[-1].get('type') != 'turn.completed':
        raise ValueError('Original source-contract request not completed')
    binding = runner.read(folder/'source_binding.json')['bindings']
    for name, digest in binding.items():
        if sha(Path(name)) != digest:
            raise ValueError('Original source binding changed: ' + name)
    raw = runner.read(call/'response.json'); validate_schema(raw, schema)
    try:
        policy.validate_contract(protocol, raw)
    except ValueError as failure:
        if str(failure) != ERROR:
            raise ValueError('Current source validator differs from preserved failure') from failure
    else:
        raise ValueError('Already-valid response must be revalidated without model recall')
    files = [call/name for name in ('response.json','schema.json','prompt.txt',
        'validation_error.json','invocation.json','events.jsonl')]
    files += [folder/name for name in ('source_binding.json','frozen_protocol.json','author_sources.txt')]
    return raw, {str(p.resolve()):sha(p) for p in files}


def correction_prompt(prompt, raw):
    missing = [ident for ident,row in raw['checks'].items()
        if not row['basic_function_bugs'] or not row['permitted_trigger_modes']]
    return prompt + ('\nVALIDATOR FEEDBACK FOR ONE BOUNDED SOURCE-CONTRACT CORRECTION: '
        + ERROR + '. Missing alternatives in: ' + ', '.join(missing) + '. '
        'Return the complete same schema for ALL frozen checks. Each check must freeze at least '
        'one source-grounded basic-function bug condition and one permitted trigger mode. '
        'These describe what would constitute a basic bug; they do not assert a product bug was observed. '
        'Preserve original requirements/IDs/groups and result-oriented meaning. Exact timing, space, '
        'numbers and exhaustive branches remain diagnostic only. No runtime evidence or scores are supplied. '
        'Do not invent implementation or change a scoring gate.\n')


def recover(folder, protocol, prompt, schema):
    folder = Path(folder)
    raw, parents = qualify_parent(folder, protocol, prompt, schema)
    submitted = correction_prompt(prompt, raw)
    if len(submitted.encode()) > 1000000:
        raise ValueError('Complete corrected source-contract request exceeds unchanged cap')
    code = Path(__file__).resolve()
    production = [code, code.with_name('gameness_v3_runtime.py'),
        code.with_name('gameness_v3.py'), code.with_name('gameness_v4.py')]
    claim = dict(version=VERSION, parent_bindings=parents,
        production_bindings={str(p):sha(p) for p in production},
        corrected_task=CORRECTED, prompt_sha256=hashlib.sha256(submitted.encode()).hexdigest(),
        original_failure_preserved=True, source_packet_unchanged=True,
        schema_unchanged=True, validator_unchanged=True, locally_filled_contract_fields=False)
    claim_path = folder/'engineering/contract_validator_feedback/claim.json'
    if claim_path.exists():
        if runner.read(claim_path) != claim:
            raise ValueError('Bounded contract correction claim changed; retain previous attempt')
    else:
        runner.exclusive_json(claim_path, claim)
    call = folder/'model_calls'/CORRECTED
    if call.exists():
        if not (call/'accepted_response.json').exists():
            raise ValueError('Bounded correction is incomplete/failed; preserve it without another call')
        if (runner.read(call/'schema.json') != schema
                or (call/'prompt.txt').read_text() != READ_ONLY_EVAL_INSTRUCTIONS+submitted):
            raise ValueError('Retained corrected contract request changed')
        value = runner.read(saved_model_response(folder, CORRECTED))
        policy.validate_contract(protocol, value)
    else:
        value = call_codex(folder, name=CORRECTED, prompt=submitted, schema=schema,
            model=policy.MODEL, timeout=900, max_attempts=1,
            response_validator=lambda result:policy.validate_contract(protocol, result))
    # Verify the actual completed invocation before freezing its derived contract.
    invocation = runner.read(call/'invocation.json'); command = invocation.get('command', [])
    if (invocation.get('exit_code') != 0 or '--model' not in command
            or command[command.index('--model')+1] != policy.MODEL):
        raise ValueError('Corrected source-contract invocation differs')
    files = [claim_path] + [call/name for name in ('response.json','accepted_response.json',
        'schema.json','prompt.txt','invocation.json','events.jsonl')]
    bindings = dict(parents, **{str(p.resolve()):sha(p) for p in files})
    bindings.update(claim['production_bindings'])
    receipt = dict(version=VERSION, bindings=bindings,
        original_rejected_response_preserved=True, full_original_validator_passed=True,
        schema_unchanged=True, validator_unchanged=True, locally_filled_contract_fields=False, model_recalled=True,
        scoring_policy_changed=False)
    path = folder/'engineering/contract_validator_feedback/receipt.json'
    if path.exists():
        if runner.read(path) != receipt:raise ValueError('Contract correction receipt changed')
    else:runner.exclusive_json(path, receipt)
    return value, dict(path=str(path.resolve()), sha256=sha(path), bindings=bindings)
