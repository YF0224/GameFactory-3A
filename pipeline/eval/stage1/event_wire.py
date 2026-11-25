"""Readable, exactly reversible EVENT JSON-lexeme columns; never a summary.

Opt-in only. A column value is the original JSON literal spelling, NOT a parsed
float or inferred state. Every occurrence retains its original physical line.
Legacy callers enforce 512 original rows. The separately authorized wire-byte
policy removes only EVENT original-row capacity, not evidence or citation checks.
"""
import hashlib
from collections import OrderedDict
import json
import re
from pathlib import Path

LEGACY_VERSION = 'whitebox-event-exact-lexeme-columns.v1'
VERSION = 'whitebox-event-exact-lexeme-columns.v2'
NUMERIC_VERSION = 'whitebox-event-exact-lexeme-columns.v3'
FIELD = 'event_wire_transport'
ROW_POLICY_FIELD = 'event_original_row_policy'
ROW_POLICY_VERSION = 'whitebox-event-wire-bytes-only.v1'
POLICY_FIELDS = (FIELD, ROW_POLICY_FIELD)
TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?|true|false|null')
LEGACY_DESCRIPTION = ('For each template, reconstruct each occurrence by interleaving '
    'fragments with its JSON-literal columns: fragments[0]+column[0]+fragments[1] '
    'and so on. Column constants repeat; values are in occurrence order; '
    'tables use zero-based indices; runs are [literal,count]. line_runs are '
    'inclusive [first,last] original physical EVENT line numbers, in order. '
    'Sort reconstructed occurrences by physical line to recover exact selected '
    'UTF-8 bytes including whitespace and line terminators. Cite EVENT using '
    'those physical lines, NEVER column/template/occurrence indices. All event '
    'names, payloads, clocks, roles, repeats, order and failures are unchanged. '
    'Only these physical lines were delivered; omission cannot prove absence. '
    'Compression does NOT reduce original physical-row counts or relax limits.')
DESCRIPTION = LEGACY_DESCRIPTION + (' Numeric number_lexemes columns contain '
    'original number spellings separated by single ASCII spaces; split on that '
    'space, never parse/reformat floats. integer_deltas columns contain a first '
    'base-10 integer followed by signed deltas separated by ASCII spaces; '
    'cumulative exact integer addition reconstructs each original integer '
    'spelling, with no precision loss. All timestamps reconstruct unchanged.')
NUMBER = re.compile(r'-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?')
INTEGER = re.compile(r'-?(?:0|[1-9][0-9]*)')
# v3 only; immutable serialized values, keyed by freshly hashed original bytes
# and exact physical-line selection. Re-reading/hashing prevents stale evidence.
_NUMERIC_CACHE = OrderedDict()


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _column(values):
    choices = [{'values': values}]
    if all(NUMBER.fullmatch(v) for v in values):
        choices.append({'number_lexemes': ' '.join(values)})
    if all(INTEGER.fullmatch(v) and str(int(v)) == v for v in values):
        integers = [int(v) for v in values]
        choices.append({'integer_deltas': ' '.join(str(n) for n in
            [integers[0]] + [b-a for a,b in zip(integers, integers[1:])])})
    if len(set(values)) == 1:
        choices.append({'constant': values[0]})
    table = list(dict.fromkeys(values))
    index = {v: n for n, v in enumerate(table)}
    choices.append({'table': table, 'indices': [index[v] for v in values]})
    runs = []
    for value in values:
        if runs and runs[-1][0] == value:
            runs[-1][1] += 1
        else:
            runs.append([value, 1])
    choices.append({'runs': runs})
    return min(choices, key=lambda value: len(dumps(value).encode('utf-8')))


def _expand(column, count):
    if not isinstance(column, dict):
        raise ValueError('Invalid EVENT column')
    if set(column) == {'number_lexemes'} and isinstance(column['number_lexemes'], str):
        values = column['number_lexemes'].split(' ')
        if any(NUMBER.fullmatch(v) is None for v in values):
            raise ValueError('Invalid EVENT numeric lexical spelling')
    elif set(column) == {'integer_deltas'} and isinstance(column['integer_deltas'], str):
        deltas = column['integer_deltas'].split(' ')
        if (len(deltas) != count or any(INTEGER.fullmatch(v) is None
                or str(int(v)) != v for v in deltas)):
            raise ValueError('Invalid EVENT exact integer delta column')
        total, values = 0, []
        for delta in deltas:
            total += int(delta)
            values.append(str(total))
    elif set(column) == {'constant'}:
        values = [column['constant']] * count
    elif set(column) == {'values'} and isinstance(column['values'], list):
        values = column['values']
    elif set(column) == {'table', 'indices'}:
        table, indices = column['table'], column['indices']
        if (not isinstance(table, list) or not isinstance(indices, list)
                or any(type(i) is not int or not 0 <= i < len(table) for i in indices)):
            raise ValueError('Invalid EVENT column table reference')
        values = [table[i] for i in indices]
    elif set(column) == {'runs'} and isinstance(column['runs'], list):
        values = []
        for run in column['runs']:
            if (not isinstance(run, list) or len(run) != 2
                    or type(run[1]) is not int or not 0 < run[1] <= count - len(values)):
                raise ValueError('Invalid EVENT column occurrence count')
            values.extend([run[0]] * run[1])
    else:
        raise ValueError('Unknown EVENT column encoding')
    if len(values) != count or any(not isinstance(v, str) for v in values):
        raise ValueError('EVENT column occurrence count/literal changed')
    # Validate lexical tokens without float parsing/reformatting or interpolation.
    if any(TOKEN.fullmatch(value) is None for value in values):
        raise ValueError('Invalid EVENT JSON literal')
    return values


def _runs(lines):
    result = []
    for line in lines:
        if result and line == result[-1][1] + 1:
            result[-1][1] = line
        else:
            result.append([line, line])
    return result


def encode(path, selected, *, encoding=VERSION):
    """Encode selected immutable rows; no filtering, deduping or clock changes."""
    if encoding not in {VERSION, NUMERIC_VERSION}:
        raise ValueError('Unknown EVENT wire encoding')
    raw = Path(path).read_bytes()
    source = raw.decode('utf-8').splitlines(keepends=True)
    if (not isinstance(selected, list) or any(type(n) is not int for n in selected)
            or selected != sorted(set(selected))
            or any(not 1 <= n <= len(source) for n in selected)):
        raise ValueError('EVENT selection requires ordered unique original physical lines')
    cache_key = (_sha(raw), tuple(selected))
    if encoding == NUMERIC_VERSION and cache_key in _NUMERIC_CACHE:
        _NUMERIC_CACHE.move_to_end(cache_key)
        return json.loads(_NUMERIC_CACHE[cache_key])
    groups = {}
    originals = []
    for number in selected:
        text = source[number - 1]
        if not isinstance(json.loads(text), dict):
            raise ValueError('EVENT source row is not a JSON object')
        fragments, values, cursor = [], [], 0
        for match in TOKEN.finditer(text):
            if match[0].startswith('"') and text[match.end():].lstrip().startswith(':'):
                continue  # Object keys belong to the unchanged template fragments.
            fragments.append(text[cursor:match.start()])
            values.append(match[0])
            cursor = match.end()
        fragments.append(text[cursor:])
        group = groups.setdefault(tuple(fragments), {'lines': [], 'rows': []})
        group['lines'].append(number)
        group['rows'].append(values)
        originals.append(text.encode('utf-8'))
    templates = []
    if encoding == NUMERIC_VERSION:
        from . import event_wire_numeric as numeric
    for fragments, group in groups.items():
        values = [list(c) for c in zip(*group['rows'])]
        templates.append({'fragments': list(fragments), 'line_runs': _runs(group['lines']),
            'occurrence_count': len(group['lines']),
            'columns': (numeric.template_columns(fragments, values) if encoding == NUMERIC_VERSION
                        else [_column(column) for column in values])})
    selected_bytes = b''.join(originals)
    wire = {'encoding': encoding, 'evidence_id': 'EVENT',
        'decode': numeric.DESCRIPTION if encoding == NUMERIC_VERSION else DESCRIPTION,
        'source_sha256': _sha(raw), 'source_physical_rows': len(source),
        'selected_sha256': _sha(selected_bytes), 'original_physical_rows': len(selected),
        'selected_raw_bytes': len(selected_bytes), 'templates': templates}
    if decode(wire) != dict(zip(selected, originals)):
        raise ValueError('EVENT exact-byte reversible equivalence failed')
    if encoding == NUMERIC_VERSION:
        _NUMERIC_CACHE[cache_key] = dumps(wire)
        while len(_NUMERIC_CACHE) > 24:
            _NUMERIC_CACHE.popitem(last=False)
    return wire


def decode(wire):
    """Return physical-line -> exact original bytes, rejecting altered mappings."""
    from .event_wire_numeric import DESCRIPTION as NUMERIC_DESCRIPTION, expand_template_columns
    if (not isinstance(wire, dict) or wire.get('encoding') not in {LEGACY_VERSION, VERSION, NUMERIC_VERSION}
            or wire.get('evidence_id') != 'EVENT'
            or wire.get('decode') != {LEGACY_VERSION: LEGACY_DESCRIPTION, VERSION: DESCRIPTION, NUMERIC_VERSION: NUMERIC_DESCRIPTION}.get(wire.get('encoding'))):
        raise ValueError('Invalid EVENT wire identity')
    total, source_count = wire.get('original_physical_rows'), wire.get('source_physical_rows')
    if (type(total) is not int or type(source_count) is not int
            or not 0 <= total <= source_count or not isinstance(wire.get('templates'), list)):
        raise ValueError('Invalid EVENT physical occurrence count')
    rows = {}
    for template in wire['templates']:
        if not isinstance(template, dict) or set(template) != {
                'fragments', 'line_runs', 'occurrence_count', 'columns'}:
            raise ValueError('Invalid EVENT template')
        count, fragments, columns = (template['occurrence_count'],
            template['fragments'], template['columns'])
        if (type(count) is not int or not 0 < count <= total
                or not isinstance(fragments, list) or not all(isinstance(s, str) for s in fragments)
                or not isinstance(columns, list) or len(fragments) != len(columns) + 1
                or not isinstance(template['line_runs'], list)):
            raise ValueError('Invalid EVENT template shape/count')
        lines = []
        for run in template['line_runs']:
            if (not isinstance(run, list) or len(run) != 2
                    or any(type(n) is not int for n in run)
                    or not 1 <= run[0] <= run[1] <= source_count
                    or run[1] - run[0] + 1 > count - len(lines)):
                raise ValueError('Invalid EVENT physical line range')
            lines.extend(range(run[0], run[1] + 1))
        if len(lines) != count or lines != sorted(set(lines)):
            raise ValueError('EVENT physical occurrence mapping changed')
        if wire['encoding'] == LEGACY_VERSION and any(isinstance(c, dict) and
                set(c).intersection({'number_lexemes', 'integer_deltas'}) for c in columns):
            raise ValueError('Legacy EVENT schema has no numeric column encoding')
        values = (expand_template_columns(columns, count) if wire['encoding'] == NUMERIC_VERSION
                  else [_expand(column, count) for column in columns])
        for index, number in enumerate(lines):
            if number in rows:
                raise ValueError('Duplicate EVENT physical occurrence')
            text = ''.join(fragments[slot] + column[index] for slot, column in enumerate(values)) + fragments[-1]
            if len(text.splitlines(keepends=True)) != 1 or not isinstance(json.loads(text), dict):
                raise ValueError('EVENT physical JSON row changed')
            rows[number] = text.encode('utf-8')
    raw = b''.join(rows[n] for n in sorted(rows))
    if (len(rows) != total or len(raw) != wire.get('selected_raw_bytes')
            or _sha(raw) != wire.get('selected_sha256')):
        raise ValueError('EVENT selected source SHA/count changed')
    return {n: rows[n] for n in sorted(rows)}


def enabled(manifest):
    value = manifest.get(FIELD)
    if value is not None and value not in {VERSION, NUMERIC_VERSION}:
        raise ValueError('Unknown EVENT wire transport opt-in')
    return value in {VERSION, NUMERIC_VERSION}


def extended_rows(manifest):
    """Explicit 2026-11-01 authorization; old manifests keep the row cap."""
    value = manifest.get(ROW_POLICY_FIELD)
    if value not in (None, ROW_POLICY_VERSION):
        raise ValueError('Unknown EVENT original-row policy')
    if value is not None and not enabled(manifest):
        raise ValueError('Extended EVENT rows require exact wire transport')
    return value == ROW_POLICY_VERSION


def for_subset(manifest, subset):
    """Preserve a prior accepted shard's exact transport independently."""
    return {**manifest, **{k: subset[k] for k in POLICY_FIELDS if k in subset}}


def binding(wire):
    return {'encoding': wire['encoding'], 'source_sha256': wire['source_sha256'],
        'selected_sha256': wire['selected_sha256'],
        'original_physical_rows': wire['original_physical_rows'],
        'selected_raw_bytes': wire['selected_raw_bytes'],
        'wire_bytes': len(dumps(wire).encode('utf-8')),
        'wire_sha256': _sha(dumps(wire).encode('utf-8'))}


def section(path, selected, expected, *, extended=False):
    from .endpoint_channels import BYTE_LIMIT, ROW_LIMIT
    if type(extended) is not bool:
        raise ValueError('EVENT row policy must be boolean')
    wire = encode(path, selected, encoding=expected['encoding'])
    if (binding(wire) != expected or (not extended and wire['original_physical_rows'] > ROW_LIMIT)
            or len(dumps(wire).encode('utf-8')) > BYTE_LIMIT):
        raise ValueError('EVENT wire exceeds frozen transport or differs from selection')
    return '\nEVIDENCE EVENT (exact original physical occurrences; lossless lexeme columns):\n' + dumps(wire)


MARKER = '\nEVIDENCE EVENT (exact original physical occurrences; lossless lexeme columns):\n'


def verify_section(prompt, path, selected, expected, *, extended=False):
    """Prove actual prompt contains exactly the reviewed encoding/whitelist."""
    canonical = section(path, selected, expected, extended=extended)
    if prompt.count(MARKER) != 1:
        raise ValueError('EVENT actual delivery section missing or duplicated')
    submitted = prompt.split(MARKER, 1)[1].split('\n', 1)[0]
    if submitted != canonical.split(MARKER, 1)[1]:
        raise ValueError('EVENT actual delivery differs from exact encoded source')
    decoded = decode(json.loads(submitted))
    if list(decoded) != selected:
        raise ValueError('EVENT actual physical citation whitelist changed')
    return True


def persist(root, evidence_set, path, selected, expected, *, extended=False):
    """Save original bytes, wire, reversible proof and reference map for audit."""
    from .protocol import dump, sha
    if not isinstance(evidence_set, str) or re.fullmatch(r'[A-Za-z0-9_-]+', evidence_set) is None:
        raise ValueError('Invalid EVENT evidence-set receipt path')
    base = (Path(root)/'validation_history').resolve()
    folder = (base/evidence_set/'event_wire').resolve()
    if not folder.is_relative_to(base):
        raise ValueError('EVENT receipt escaped validation history')
    folder.mkdir(parents=True, exist_ok=True)
    encoded = encode(path, selected, encoding=expected['encoding'])
    if binding(encoded) != expected:
        raise ValueError('EVENT persisted wire differs from declared transport')
    decoded = decode(encoded)
    for name, raw in [('original_selected.jsonl', b''.join(decoded.values())),
                      ('submitted_wire.json', dumps(encoded).encode('utf-8'))]:
        target = folder/name
        if target.exists() and target.read_bytes() != raw:
            raise ValueError('Preserved EVENT wire receipt conflicts with current source')
        target.write_bytes(raw)
    dump(folder/'equivalence.json', {'encoding': encoded['encoding'],
        'source': str(Path(path).resolve()), 'source_sha256': encoded['source_sha256'],
        'original_selected_sha256': sha(folder/'original_selected.jsonl'),
        'submitted_wire_sha256': sha(folder/'submitted_wire.json'),
        'original_physical_lines': selected, 'occurrence_count': len(selected),
        'exact_utf8_expansion_equal': True,
        'citation_ids': 'EVENT with original physical line numbers only',
        'evidence_rows_changed': False, 'row_limit_reinterpreted': False,
        'original_row_policy': ROW_POLICY_VERSION if extended else 'legacy-512-original-rows',
        'judge_response_schema_changed': False, 'rubric_changed': False})
