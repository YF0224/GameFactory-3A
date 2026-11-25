"""Bounded lossless expansion of independent-contract provenance, never verdicts.

A model may copy the exact original source requirement instead of its scoped
wrapper. Only that exact metadata abbreviation is recoverable. All goals,
bugs, facts and thresholds remain byte-for-byte JSON-equivalent to the reply.
The original rejected reply/claim is retained; no accepted-model marker is
created, and the unchanged full validator must accept the derived contract.
"""
from __future__ import annotations
import copy
import json
from pathlib import Path
from . import gameness_v3_independent as policy, gameness_v3 as base
from .codex import READ_ONLY_EVAL_INSTRUCTIONS
from .protocol import sha

VERSION = 'gameness-contract-provenance-expansion.v1'


def expand(protocol, raw):
    if not policy.active(protocol):
        raise ValueError('Metadata recovery is independent-v2 only')
    specs = base.criteria(protocol)
    if set(raw['checks']) != {s['id'] for s in specs}:
        raise ValueError('Metadata recovery cannot change criterion identities')
    value = copy.deepcopy(raw); changes = []
    for spec in specs:
        ident = spec['id']; actual = raw['checks'][ident]['original_requirement_diagnostic_only']
        expected = spec['requirement']
        if actual == expected:
            continue
        original = spec.get('source_criterion', {}).get('requirement')
        if not original or actual != original or not expected.startswith(original + '\n固定范围：'):
            raise ValueError('Not an exact original-source metadata abbreviation: ' + ident)
        value['checks'][ident]['original_requirement_diagnostic_only'] = expected
        changes.append(dict(criterion_id=ident, field='original_requirement_diagnostic_only', before=actual, after=expected))
    if not changes:
        raise ValueError('No diagnosed metadata abbreviation to recover')
    # This is the SAME schema and semantic validator that rejected the reply.
    policy.validate_contract(protocol, value)
    return value, changes


def recover(folder: Path, protocol, prompt, schema):
    folder = Path(folder)
    call = folder/'model_calls/gameness_v3_source_contract'
    if (call/'accepted_response.json').exists() or (folder/'frozen.json').exists():
        raise ValueError('Do not recover an accepted/frozen contract')
    for name in ('response.json', 'validation_error.json', 'prompt.txt', 'schema.json', 'events.jsonl'):
        if not (call/name).is_file():
            raise ValueError('Missing original failed request: ' + name)
    error = json.loads((call/'validation_error.json').read_text())
    if error.get('exception') != 'Original Gameness identity/requirement changed' or error.get('response_sha256') != sha(call/'response.json'):
        raise ValueError('Not the diagnosed SHA-bound provenance failure')
    if (call/'prompt.txt').read_text() != READ_ONLY_EVAL_INSTRUCTIONS + prompt or json.loads((call/'schema.json').read_text()) != schema:
        raise ValueError('Original failed contract request differs')
    # Never handle an active request or a transport/timeout failure as parsing.
    events = [json.loads(s) for s in (call/'events.jsonl').read_text().splitlines() if s.strip()]
    if not events or events[-1].get('type') != 'turn.completed':
        raise ValueError('Original model request not completed')
    binding = json.loads((folder/'source_binding.json').read_text())['bindings']
    for name, digest in binding.items():
        if sha(Path(name)) != digest:
            raise ValueError('Contract source binding changed: ' + name)
    value, changes = expand(protocol, json.loads((call/'response.json').read_text()))
    output = folder/'engineering/requirement_metadata_expansion'
    output.mkdir(parents=True, exist_ok=True)
    def save(path, data):
        text = json.dumps(data, ensure_ascii=False, indent=2) + '\n'
        if path.exists():
            if path.read_text() != text:
                raise ValueError('Preserved recovery differs: ' + str(path))
        else:
            with path.open('x') as handle: handle.write(text)
    derived = output/'contract.json'; save(derived, value)
    paths = [call/n for n in ('response.json', 'validation_error.json', 'prompt.txt', 'schema.json', 'events.jsonl')]
    paths += [folder/n for n in ('source_binding.json', 'frozen_protocol.json', 'author_sources.txt')]
    paths += [Path(__file__).resolve(), Path(policy.__file__).resolve(), Path(base.__file__).resolve(), derived]
    bindings = {str(p.resolve()):sha(p) for p in paths}
    receipt = dict(version=VERSION, category='HARNESS_ERROR_RECOVERED_METADATA_ONLY', bindings=bindings,
        changes=changes, semantic_equivalence='Only exact original requirement provenance expanded with its predeclared scope. All model goals, facts, bugs and gates unchanged.',
        original_rejected_response_preserved=True, accepted_response_marker_created=False,
        scoring_policy_changed=False, model_recalled=False, full_original_validator_passed=True)
    path = output/'receipt.json'; save(path, receipt)
    return value, dict(path=str(path.resolve()), sha256=sha(path), bindings=bindings)


def verify(recovery):
    if sha(Path(recovery['path'])) != recovery['sha256']:
        raise ValueError('Contract metadata recovery receipt changed')
    for name, digest in recovery['bindings'].items():
        if sha(Path(name)) != digest:
            raise ValueError('Contract metadata recovery lineage changed: ' + name)
