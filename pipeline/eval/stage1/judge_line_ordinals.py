"""Reversible citation transport: a closed ordinal maps to one allowed physical line."""
import copy
import hashlib
import json
from pathlib import Path

from .protocol import dump, sha

VERSION = 'whitebox-judge-citation-line-ordinals.v1'
MIN_LINES = 4096
MIN_SCHEMA_BYTES = 65536
FIELDS = ('line_start', 'line_end')


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def encode(schema):
    """Only exact per-evidence citation enums may become closed ordinal ranges."""
    result = copy.deepcopy(schema)
    variants = result.get('$defs', {}).get('Citation', {}).get('anyOf', [])
    mapping = {}
    for variant in variants:
        props = variant.get('properties', {})
        rule = props.get('line_start', {})
        lines = rule.get('enum')
        if not isinstance(lines, list) or len(lines) < MIN_LINES:
            continue
        if (set(rule) != {'type', 'enum'} or rule['type'] != 'integer'
                or any(type(n) is not int or n < 1 for n in lines)
                or lines != sorted(set(lines)) or props.get('line_end') != rule):
            raise ValueError('Ordinal transport requires identical sorted positive physical line enums')
        ident_rule = props.get('id', {})
        ids = ident_rule.get('enum', [])
        if (ident_rule.get('type') != 'string' or len(ids) != 1
                or not isinstance(ids[0], str) or ids[0] in mapping
                or not all(field in variant.get('required', []) for field in FIELDS)
                or any(field+'_ordinal' in props for field in FIELDS)):
            raise ValueError('Ordinal transport requires a unique evidence ID and exact citation fields')
        mapping[ids[0]] = lines.copy()
        for field in FIELDS:
            del props[field]
            props[field+'_ordinal'] = {'type': 'integer', 'minimum': 1, 'maximum': len(lines)}
            required = variant['required']
            required[required.index(field)] = field+'_ordinal'
    if restore(result, mapping) != schema:
        raise ValueError('Citation ordinal schema failed exact inverse proof')
    return result, mapping


def restore(schema, mapping):
    result = copy.deepcopy(schema)
    used = set()
    for variant in result.get('$defs', {}).get('Citation', {}).get('anyOf', []):
        props = variant.get('properties', {})
        ids = props.get('id', {}).get('enum', [])
        if len(ids) != 1 or ids[0] not in mapping:
            continue
        ident = ids[0]
        if ident in used:
            raise ValueError('Duplicate ordinal evidence ID')
        used.add(ident)
        lines = mapping[ident]
        for field in FIELDS:
            ordinal = field+'_ordinal'
            if (props.get(ordinal) != {'type':'integer', 'minimum':1, 'maximum':len(lines)}
                    or field in props or ordinal not in variant['required']):
                raise ValueError('Ordinal range or citation structure changed')
            del props[ordinal]
            props[field] = {'type':'integer', 'enum':lines.copy()}
            required = variant['required']
            required[required.index(ordinal)] = field
    if used != set(mapping):
        raise ValueError('Unused ordinal evidence mapping')
    return result


def codebook(mapping):
    return {'version':VERSION, 'evidence':{
        ident:{'physical_lines':lines, 'count':len(lines),
               'physical_lines_sha256':hashlib.sha256(canonical(lines).encode()).hexdigest()}
        for ident,lines in mapping.items()}}


def write_codebook(folder, mapping):
    folder = Path(folder)
    dump(folder/'citation_line_codebook.json', codebook(mapping))
    return {'version':VERSION, 'codebook_sha256':sha(folder/'citation_line_codebook.json'),
            'evidence_counts':{ident:len(lines) for ident,lines in mapping.items()},
            'proof':'For each evidence ID, ordinal i in [1,N] maps bijectively to original enum[i-1]. Exact schema restoration is verified; all physical-line gaps and citation IDs remain unchanged.'}


def read_mapping(folder, original, receipt):
    folder = Path(folder)
    _, mapping = encode(original)
    path = folder/'citation_line_codebook.json'
    if (receipt.get('version') != VERSION or receipt.get('codebook_sha256') != sha(path)
            or json.loads(path.read_text()) != codebook(mapping)
            or receipt.get('evidence_counts') != {k:len(v) for k,v in mapping.items()}):
        raise ValueError('Citation ordinal codebook changed')
    return mapping


def suffix(folder):
    folder = Path(folder).resolve()
    book = folder/'citation_line_codebook.json'
    # This adds transport instructions only; the original question remains a byte-identical prefix.
    return ('\n\nCitation physical-line transport (reversible; judgment and evidence rules unchanged):\n'
            'Some evidence citation variants in the supplied output schema use line_start_ordinal '
            'and line_end_ordinal instead of line_start and line_end. For these variants only, '
            'return the 1-based index of the actual physical line in that evidence ID exact allowed '
            'line list. Never use a physical line number as an ordinal. Other citation variants '
            'continue to use physical line numbers. The evaluator decodes the ordinals and '
            'validates the result against the unchanged original schema. Choose citations from '
            'actual evidence; this mapping supplies no observations or verdicts.\n'
            'Exact codebook: '+str(book)+' (SHA256 '+sha(book)+'). '
            'The evidence[ID].physical_lines array preserves every original allowed physical line '
            'in sorted order; ordinal i means array[i-1]. Use a bounded read-only Python lookup '
            'for each physical line you intend to cite: load the codebook JSON, take '
            'L=book["evidence"][ID]["physical_lines"], require physical_line in L, '
            'then use L.index(physical_line)+1. Print only the lookup result, not the full list. '
            'Retain the original citation ID, observation, check, status and reasoning.\n')


def prepare_prompt(folder, prompt):
    folder = Path(folder)
    transform = json.loads((folder/'schema_transform.json').read_text())
    if 'citation_line_transport' not in transform:
        return prompt
    (folder/'original_prompt.txt').write_text(prompt)
    submitted = prompt + suffix(folder)
    (folder/'prompt.txt').write_text(submitted)
    dump(folder/'prompt_transform.json', {'version':VERSION,
        'original_sha256':sha(folder/'original_prompt.txt'), 'submitted_sha256':sha(folder/'prompt.txt'),
        'schema_transform_sha256':sha(folder/'schema_transform.json'),
        'suffix_sha256':hashlib.sha256(suffix(folder).encode()).hexdigest()})
    return submitted


def original_prompt_identity(folder):
    folder = Path(folder)
    if (folder/'judge_format_prompt.json').is_file():
        from .judge_format_recovery import prompt_identity
        return prompt_identity(folder)
    if not (folder/'prompt_transform.json').is_file():
        return sha(folder/'prompt.txt')
    from .judge_schema_transport import verify
    receipt = json.loads((folder/'prompt_transform.json').read_text())
    transform = verify(folder)
    original = folder/'original_prompt.txt'
    if ('citation_line_transport' not in transform or receipt.get('version') != VERSION
            or receipt.get('original_sha256') != sha(original)
            or receipt.get('submitted_sha256') != sha(folder/'prompt.txt')
            or receipt.get('schema_transform_sha256') != sha(folder/'schema_transform.json')
            or receipt.get('suffix_sha256') != hashlib.sha256(suffix(folder).encode()).hexdigest()
            or (folder/'prompt.txt').read_text() != original.read_text() + suffix(folder)):
        raise ValueError('Citation ordinal prompt transport changed')
    return receipt['original_sha256']


def decode(folder, value):
    folder = Path(folder)
    from .judge_schema_transport import verify
    from .codex import validate_schema
    receipt = verify(folder)
    original = json.loads((folder/'original_schema.json').read_text())
    mapping = read_mapping(folder, original, receipt['citation_line_transport'])
    submitted = json.loads((folder/'schema.json').read_text())
    validate_schema(value, submitted)
    result = copy.deepcopy(value)
    checks = result['checks']
    checks = list(checks.values()) if isinstance(checks, dict) else checks
    references = []
    for check_index, check in enumerate(checks):
        for ref_index, ref in enumerate(check['evidence']):
            ident = ref['id']
            if ident not in mapping:
                continue
            entry = {'check_index':check_index, 'evidence_index':ref_index, 'id':ident}
            for field in FIELDS:
                ordinal = ref.pop(field+'_ordinal')
                physical = mapping[ident][ordinal-1]
                ref[field] = physical
                entry[field+'_ordinal'] = ordinal
                entry[field] = physical
            references.append(entry)
    validate_schema(result, original)
    return result, references


def save_decoded(folder, raw):
    folder = Path(folder)
    original_prompt_identity(folder)
    decoded, references = decode(folder, raw)
    dump(folder/'decoded_response.json', decoded)
    dump(folder/'citation_line_decode.json', {'version':VERSION,
        'raw_response_sha256':sha(folder/'response.json'),
        'decoded_response_sha256':sha(folder/'decoded_response.json'),
        'schema_transform_sha256':sha(folder/'schema_transform.json'),
        'prompt_transform_sha256':sha(folder/'prompt_transform.json'),
        'references':references, 'original_schema_validated':True})
    return decoded


def verify_decoded(path, binding):
    path = Path(path)
    folder = path.parent
    receipt_path = folder/'citation_line_decode.json'
    receipt = json.loads(receipt_path.read_text())
    if (path.name != 'decoded_response.json' or receipt.get('version') != VERSION
            or binding.get('judge_line_receipt_sha256') != sha(receipt_path)
            or receipt.get('raw_response_sha256') != sha(folder/'response.json')
            or receipt.get('decoded_response_sha256') != sha(path)
            or receipt.get('schema_transform_sha256') != sha(folder/'schema_transform.json')
            or receipt.get('prompt_transform_sha256') != sha(folder/'prompt_transform.json')
            or receipt.get('original_schema_validated') is not True):
        raise ValueError('Citation ordinal decoded response binding changed')
    original_prompt_identity(folder)
    # Re-parse raw JSON with the same duplicate-key/non-finite rejection as the live path.
    from .codex import load_plan_json
    expected, references = decode(folder, load_plan_json(folder/'response.json'))
    if load_plan_json(path) != expected or receipt.get('references') != references:
        raise ValueError('Citation ordinal decode no longer equals the original response')
    return receipt
