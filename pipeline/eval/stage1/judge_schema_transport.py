"""Lossless sharing of repeated judge schema nodes; exact citation sets remain closed."""
import copy
from collections import Counter
import hashlib
import json
from pathlib import Path

from .protocol import dump, sha

VERSION = 'whitebox-judge-shared-schema.v1'
WIRE_ENUM_COMPACT_MIN = 4096


def _key(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def expand(schema):
    """Resolve only local definitions; reject cycles and unsupported references."""
    definitions = schema.get('$defs', {})

    def resolve(value, stack=()):
        if isinstance(value, list):
            return [resolve(item, stack) for item in value]
        if not isinstance(value, dict):
            return value
        if '$ref' in value:
            ref = value['$ref']
            if set(value) != {'$ref'} or not ref.startswith('#/$defs/'):
                raise ValueError('Unsupported shared judge schema reference')
            name = ref[len('#/$defs/'):]
            if name in stack or name not in definitions:
                raise ValueError('Cyclic or missing shared judge schema definition')
            return resolve(definitions[name], (*stack, name))
        alternatives = value.get('anyOf')
        if (set(value) == {'anyOf'} and alternatives
                and all(isinstance(item, dict) and set(item) == {'type','minimum','maximum'}
                        and item['type'] == 'integer' and type(item['minimum']) is int
                        and type(item['maximum']) is int and item['minimum'] <= item['maximum']
                        for item in alternatives)):
            numbers = sorted({number for item in alternatives
                              for number in range(item['minimum'], item['maximum'] + 1)})
            return {'type':'integer', 'enum':numbers}
        return {key: resolve(item, stack) for key, item in value.items()}

    return resolve({key: value for key, value in schema.items() if key != '$defs'})


def compact(schema):
    """Intern repeated schema nodes, including the two exact physical-line enums."""
    counts = Counter()

    def eligible(value):
        return isinstance(value, dict) and ('type' in value or 'anyOf' in value)

    def count(value):
        if eligible(value):
            counts[_key(value)] += 1
        if isinstance(value, dict):
            for item in value.values():
                count(item)
        elif isinstance(value, list):
            for item in value:
                count(item)

    count(schema)
    definitions = {}

    def share(value, root=False):
        if isinstance(value, list):
            return [share(item) for item in value]
        if not isinstance(value, dict):
            return value
        result = {key: share(item) for key, item in value.items()}
        if not root and eligible(value):
            key = _key(value)
            if counts[key] > 1 and len(key.encode()) >= 512:
                name = 'Shared_' + hashlib.sha256(key.encode()).hexdigest()
                if name in schema.get('$defs', {}):
                    raise ValueError('Shared judge schema definition collision')
                definitions[name] = result
                return {'$ref': '#/$defs/' + name}
        return result

    result = share(copy.deepcopy(schema), root=True)
    if definitions:
        result['$defs'] = {**result.get('$defs', {}), **definitions}
    if expand(result) != expand(schema):
        raise ValueError('Shared judge schema changed accepted output semantics')
    return result


def wire_schema(schema):
    """Encode every large integer whitelist as an exact union of closed ranges."""
    result = compact(schema)
    ranges = []

    def visit(value, path='$'):
        if isinstance(value, dict):
            enum = value.get('enum')
            if (isinstance(enum, list) and len(enum) >= WIRE_ENUM_COMPACT_MIN
                    and enum and all(type(item) is int for item in enum)):
                if enum != sorted(set(enum)):
                    raise ValueError('Large integer citation enum must be sorted and unique')
                intervals = []
                for item in enum:
                    if intervals and item == intervals[-1][1] + 1:
                        intervals[-1][1] = item
                    else:
                        intervals.append([item, item])
                encoded = {'anyOf': [dict(type='integer', minimum=lo, maximum=hi)
                                     for lo, hi in intervals]}
                if len(_key(encoded)) >= len(_key(value)):
                    return
                ranges.append({
                    'path': path, 'count': len(enum), 'interval_count': len(intervals),
                    'enum_sha256': hashlib.sha256(_key(enum).encode()).hexdigest(),
                })
                value.clear()
                value.update(encoded)
                return
            for key, item in list(value.items()):
                visit(item, f'{path}.{key}')
        elif isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, f'{path}[{index}]')

    visit(result)
    if expand(result) != expand(schema):
        raise ValueError('Integer range transform changed the exact schema')
    return result, ranges


def submission(schema):
    """Keep physical lines unless an exact ordinal transport materially reduces wire size."""
    submitted, ranges = wire_schema(schema)
    from .judge_line_ordinals import encode, MIN_SCHEMA_BYTES
    if len(_key(submitted).encode()) < MIN_SCHEMA_BYTES:
        return submitted, ranges, {}
    encoded, mapping = encode(schema)
    if not mapping:
        return submitted, ranges, {}
    ordinal, ordinal_ranges = wire_schema(encoded)
    if len(_key(ordinal).encode()) >= len(_key(submitted).encode()):
        return submitted, ranges, {}
    return ordinal, ordinal_ranges, mapping


def write(folder, schema):
    """Freeze both identities and bind the byte-level wire transform for audit."""
    folder = Path(folder)
    submitted, ranges, mapping = submission(schema)
    dump(folder/'original_schema.json', schema)
    (folder/'schema.json').write_text(json.dumps(submitted, ensure_ascii=False, separators=(',', ':')) + '\n')
    extra = {}
    if mapping:
        from .judge_line_ordinals import write_codebook
        extra['citation_line_transport'] = write_codebook(folder, mapping)
    dump(folder/'schema_transform.json', {
        'version': VERSION,
        'original_sha256': sha(folder/'original_schema.json'),
        'submitted_sha256': sha(folder/'schema.json'),
        'original_bytes': (folder/'original_schema.json').stat().st_size,
        'submitted_bytes': (folder/'schema.json').stat().st_size,
        'semantics': 'Repeated nodes use local $defs. Large integer citation enums use exact unions of closed integer ranges; expansion restores every original permitted physical line.',
        'wire_integer_enums': ranges, **extra})
    return submitted


def verify(folder):
    folder = Path(folder)
    receipt = json.loads((folder/'schema_transform.json').read_text())
    if (receipt.get('version') != VERSION
            or receipt.get('original_sha256') != sha(folder/'original_schema.json')
            or receipt.get('submitted_sha256') != sha(folder/'schema.json')):
        raise ValueError('Shared judge schema identity changed')
    original = json.loads((folder/'original_schema.json').read_text())
    submitted = json.loads((folder/'schema.json').read_text())
    if 'citation_line_transport' in receipt:
        expected, ranges, mapping = submission(original)
        if not mapping:
            raise ValueError('Unnecessary or missing citation ordinal transport')
        from .judge_line_ordinals import read_mapping
        read_mapping(folder, original, receipt['citation_line_transport'])
    else:
        # Historical accepted schemas retain the original transport, independent of new policy.
        expected, ranges = wire_schema(original)
    if expected != submitted or receipt.get('wire_integer_enums', []) != ranges:
        raise ValueError('Judge schema wire transform differs from the bound exact whitelist')
    return receipt


def same_retry_schema(primary, retry):
    """A retry may change wire syntax only with verified exact equivalence."""
    primary, retry = Path(primary), Path(retry)
    if sha(primary/'schema.json') == sha(retry/'schema.json'):
        return True
    receipt = verify(retry)
    if receipt['original_sha256'] != sha(primary/'schema.json'):
        if not (primary/'schema_transform.json').is_file():
            raise ValueError('Shared judge retry changed original schema identity')
        original = verify(primary)
        if receipt['original_sha256'] != original['original_sha256']:
            raise ValueError('Shared judge retry changed original schema identity')
    return True
