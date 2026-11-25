"""Readable token-table packaging of exact native observer metadata bytes.

No rows are sampled, inferred, re-serialized as JSON, or removed. Physical lines,
JSON spelling, whitespace, occurrences and final line terminators are reversible.
"""
import hashlib
import json
import re
from pathlib import Path

VERSION = 'unity-observer-exact-token-lines.v1'
IDS = frozenset({'PUBLIC_AUTO_PROPERTY_BINDINGS'})
TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|[^"\\]+|\\.', re.DOTALL)


def encode(path, ident):
    if ident not in IDS:
        raise ValueError('Unsupported observer metadata ID')
    raw = Path(path).read_bytes()
    text = raw.decode('utf-8')
    symbols, indices, rows = [], {}, []
    for line in text.splitlines(keepends=True):
        tokens = TOKEN.findall(line)
        if ''.join(tokens) != line:
            raise ValueError('Observer metadata tokenizer lost source characters')
        row = []
        for token in tokens:
            if token not in indices:
                indices[token] = len(symbols)
                symbols.append(token)
            row.append(indices[token])
        rows.append(row)
    wire = {'encoding': VERSION, 'evidence_id': ident,
        'source_sha256': hashlib.sha256(raw).hexdigest(),
        'decode': 'Each rows entry is one original physical line, numbered from 1. Concatenate symbols[index] in row order, retaining every character and line terminator. Concatenate all decoded rows to reconstruct the exact UTF-8 source bytes. Cite this evidence_id using its original physical line numbers; these are metadata receipts, not invented gameplay states or events.',
        'symbols': symbols, 'rows': rows}
    if decode(wire) != raw:
        raise ValueError('Observer metadata byte equivalence failed')
    return wire


def decode(wire):
    if wire.get('encoding') != VERSION or wire.get('evidence_id') not in IDS:
        raise ValueError('Invalid observer metadata encoding')
    symbols, rows = wire.get('symbols'), wire.get('rows')
    if (not isinstance(symbols, list) or not all(isinstance(s, str) for s in symbols)
            or not isinstance(rows, list)):
        raise ValueError('Invalid observer metadata token tables')
    lines = []
    for row in rows:
        if (not isinstance(row, list) or not row or any(type(i) is not int
                or not 0 <= i < len(symbols) for i in row)):
            raise ValueError('Invalid observer metadata token reference')
        line = ''.join(symbols[i] for i in row)
        if len(line.splitlines(keepends=True)) != 1:
            raise ValueError('Observer metadata physical line changed')
        lines.append(line)
    raw = ''.join(lines).encode('utf-8')
    if len(raw.decode('utf-8').splitlines(keepends=True)) != len(rows):
        raise ValueError('Observer metadata physical occurrence count changed')
    if hashlib.sha256(raw).hexdigest() != wire.get('source_sha256'):
        raise ValueError('Observer metadata source SHA changed')
    return raw


def section(path, ident):
    return ('\nEVIDENCE '+ident+' (exact native metadata token lines):\n'
            + json.dumps(encode(path, ident), ensure_ascii=False, separators=(',', ':')))


def verify_section(packet, path, ident):
    marker = '\nEVIDENCE '+ident+' (exact native metadata token lines):\n'
    if packet.count(marker) != 1:
        return False
    payload = packet.split(marker, 1)[1].split('\n', 1)[0]
    wire = json.loads(payload)
    return wire.get('evidence_id') == ident and decode(wire) == Path(path).read_bytes()
