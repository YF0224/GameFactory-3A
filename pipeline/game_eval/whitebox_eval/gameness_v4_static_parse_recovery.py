"""Exact complete source-review suffix recovery, without calls or field repairs.

A completed reply may restart its full root after an unfinished prefix. Only one
unaltered, final schema AND original-policy-valid root qualifies. Failed bytes,
request, source binding and inverse UTF-8 proof remain immutable. No accepted
model-call marker is manufactured; the review invokes this validator on reuse.
"""
from pathlib import Path
import hashlib
import json
import re
from . import mechanic_v3_runner as runner
from .codex import validate_schema, unique_json_object, reject_json_constant
from .protocol import sha

VERSION = 'gameness-v4-complete-source-review-suffix.v1'


def complete_suffix(text, schema, validator):
    decoder = json.JSONDecoder(object_pairs_hook=unique_json_object, parse_constant=reject_json_constant)
    try:
        decoder.decode(text)
    except ValueError:
        pass
    else:
        raise ValueError('Valid JSON requires ordinary source review')
    candidates = []
    for match in re.finditer(r'\{\s*"', text):
        try:
            value, end = decoder.raw_decode(text, match.start())
            validate_schema(value, schema)
            validator(value)
        except (ValueError, TypeError, KeyError):
            continue
        candidates.append((match.start(), end, value))
    if len(candidates) != 1:
        raise ValueError('Exactly one complete schema-and-policy-valid source suffix required')
    start, end, value = candidates[0]
    if start == 0 or text[end:].strip() or not text[:start].lstrip().startswith('{'):
        raise ValueError('Only a final full source review after an unfinished root qualifies')
    try:
        decoder.raw_decode(text.lstrip())
    except ValueError:
        pass
    else:
        raise ValueError('A preceding complete answer cannot be discarded')
    # A restarted answer must follow an unclosed root, not a closed malformed
    # wrapper. Ignore braces within strings; never edit/repair the prefix.
    depth = 0; inside = False; escaped = False
    for char in text[:start]:
        if escaped:
            escaped = False
        elif inside and char == '\\':
            escaped = True
        elif char == '"':
            inside = not inside
        elif not inside:
            if char in '{[': depth += 1
            elif char in '}]': depth -= 1
            if depth < 0: raise ValueError('Malformed closed prefix is not a root restart')
    if depth <= 0:
        raise ValueError('Source restart needs an unclosed original root')
    return value, start, end


def immutable(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data: raise ValueError('Retained source parse proof changed')
    else:
        with path.open('xb') as stream: stream.write(data)


def recover(folder, *, scoring_policy, schema, submitted_prompt, validator, actual):
    folder = Path(folder).resolve(); root = folder.parent.parent
    if (scoring_policy.VERSION != 'whitebox-gameness10-50-100.v4'
            or not re.fullmatch(r'gameness_source_v1_[0-9]+', folder.name)):
        raise ValueError('Exact source-review v4 parse recovery only')
    if (folder/'accepted_response.json').exists():
        raise ValueError('Never replace an accepted source response')
    response = folder/'response.json'; original = response.read_bytes(); text = original.decode('utf-8')
    error = runner.read(folder/'parse_error.json')
    if (error.get('phase') != 'response_json_parse' or error.get('response_sha256') != sha(response)
            or error.get('response_text') != text):
        raise ValueError('Original source parse failure changed')
    if (runner.read(folder/'schema.json') != schema or (folder/'prompt.txt').read_text() != submitted_prompt
            or actual.get('prompt_sha256') != hashlib.sha256(submitted_prompt.encode()).hexdigest()
            or actual.get('images') != [] or actual.get('model') != scoring_policy.MODEL
            or actual.get('runtime_evidence_supplied') is not False):
        raise ValueError('Original complete source request/schema changed')
    invocation = runner.read(folder/'invocation.json'); command = invocation.get('command', [])
    events = [json.loads(line) for line in (folder/'events.jsonl').read_text().splitlines() if line.strip()]
    if (invocation.get('exit_code') != 0 or '--model' not in command
            or command[command.index('--model')+1] != scoring_policy.MODEL or '--image' in command
            or not events or events[-1].get('type') != 'turn.completed'):
        raise ValueError('Completed source-only frozen-model invocation required')
    binding_path = root/'source_binding.json'; binding = runner.read(binding_path)
    if binding.get('scoring_protocol') != scoring_policy.VERSION:
        raise ValueError('Source binding is not the original v4 review')
    delivery_path = root/'requests'/folder.name/'actual_delivery.json'
    if (runner.read(delivery_path) != actual
            or actual.get('source_binding_sha256') != sha(binding_path)
            or actual.get('all_author_sources_delivered') is not True
            or actual.get('old_scores_supplied') is not False
            or actual.get('identity') != binding.get('identity')
            or actual.get('contract_sha256') != binding.get('contract_sha256')):
        raise ValueError('Original actual-delivery/source-binding proof changed')
    manifest = runner.read(root/'source_manifest.json')
    delivered = actual['complete_author_sources']
    expected = {i['id']: (i['path'], i['sha256']) for i in manifest['items'] if i['type'] == 'source'}
    if (len(delivered) != len(expected)
            or {i['id']:(i['path'],i['sha256']) for i in delivered} != expected
            or {k:v[1] for k,v in expected.items()} != binding['source_sha256_by_id']):
        raise ValueError('Incomplete original author-source delivery')
    for name, digest in binding['author_sources'].items():
        if sha(Path(name)) != digest: raise ValueError('Original author source changed')
    for item in actual['complete_author_sources']:
        file = root/item['path']
        if sha(file) != item['sha256'] or len(file.read_text(errors='replace').splitlines()) != item['line_count']:
            raise ValueError('Delivered author source/physical lines changed')
    value, start, end = complete_suffix(text, schema, validator)
    prefix, suffix, trailing = text[:start].encode(), text[start:end].encode(), text[end:].encode()
    if prefix+suffix+trailing != original: raise ValueError('Source response inverse byte proof failed')
    output = folder/'complete_source_suffix'
    for name, data in [('incomplete_prefix.txt', prefix), ('complete_response.json', suffix), ('trailing.txt', trailing)]:
        immutable(output/name, data)
    files = [folder/n for n in ['response.json','schema.json','prompt.txt','parse_error.json','invocation.json','events.jsonl']]
    files += [delivery_path, binding_path, root/'source_manifest.json', root/'citation_rules.json', Path(__file__).resolve(),
              Path(__file__).with_name('gameness_v3_static.py'), Path(__file__).with_name('codex.py')]
    files += [output/n for n in ['incomplete_prefix.txt','complete_response.json','trailing.txt']]
    receipt = dict(version=VERSION, bindings={str(p.resolve()):sha(p) for p in files},
        original_author_bindings=binding['author_sources'], model_recalled=False, response_edited=False,
        accepted_response_marker_created=False, full_original_validator_passed=True,
        exact_response_inverse=True, suffix_start_utf8_byte=len(prefix), suffix_end_utf8_byte=len(prefix)+len(suffix),
        original_failure_preserved=True, scoring_semantics_changed=False)
    path = output/'receipt.json'
    if path.exists():
        if runner.read(path) != receipt: raise ValueError('Retained source suffix lineage changed')
    else: runner.exclusive_json(path, receipt)
    return value
