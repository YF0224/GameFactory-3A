"""Readable aliases for byte-identical numbered evidence bodies, never excerpts.

Every original ID, physical line and occurrence is reconstructed before sending.
The first complete literal body remains directly visible in the same request.
"""
import hashlib
import json
import re

VERSION = 'whitebox-exact-evidence-body-alias.v1'
NOTICE = ('EXACT REPEATED EVIDENCE BODY ALIASES: a numbered body may be shared by '
          'multiple original evidence IDs. An alias repeats the entire earlier literal '
          'numbered body unchanged, with the same physical line numbers. Cite the '
          'current original evidence ID. These are original data, not success claims.\n')
HEADER = re.compile(r'(?m)^EVIDENCE ([^\n]+)\n')
NUMBERED = re.compile(r'(?:[1-9][0-9]*: [^\n]*\n)+')
MARKER = 'EXACT_EVIDENCE_BODY_ALIAS '


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def blocks(text):
    seen = set()
    for header in HEADER.finditer(text):
        label = header.group(1)
        # Restrict to the two existing literal-numbered document formats.
        ident = label.removesuffix(' (complete original source)')
        if any(c.isspace() for c in ident):
            continue
        if ident in seen:
            raise ValueError('Duplicate evidence ID in exact body transport')
        seen.add(ident)
        yield ident, header.end()


def encode(text):
    known = {}; edits = []; aliases = []
    for ident, start in blocks(text):
        match = NUMBERED.match(text, start)
        if match is None:
            continue
        body = match.group()
        # No inferred renumbering: compare complete literal numbered bodies.
        if [int(line.split(':', 1)[0]) for line in body.splitlines()] != list(range(1, len(body.splitlines())+1)):
            continue
        key = digest(body)
        if key in known:
            target, original = known[key]
            if body != original:
                raise ValueError('Evidence body digest collision')
            alias = dict(encoding=VERSION, evidence_id=ident, target_id=target,
                         numbered_body_sha256=key, physical_line_count=len(body.splitlines()))
            replacement = MARKER+json.dumps(alias, ensure_ascii=False, separators=(',', ':'))+'\n'
            if len(replacement.encode()) < len(body.encode()):
                edits.append((start, match.end(), replacement)); aliases.append(alias)
        else:
            known[key] = (ident, body)
    wire = text
    for start, end, replacement in reversed(edits):
        wire = wire[:start]+replacement+wire[end:]
    if aliases:
        wire = NOTICE+wire
    if decode(wire) != text:
        raise ValueError('Exact evidence packet expansion differs')
    return wire, dict(version=VERSION, original_sha256=digest(text), submitted_sha256=digest(wire),
                     original_bytes=len(text.encode()), submitted_bytes=len(wire.encode()),
                     aliases=aliases, exact_expansion=True, physical_lines_unchanged=True)


def decode(wire):
    if not wire.startswith(NOTICE):
        return wire
    text = wire[len(NOTICE):]; known = {}; edits = []
    for ident, start in blocks(text):
        if text.startswith(MARKER, start):
            end = text.find('\n', start)
            alias = json.loads(text[start+len(MARKER):end])
            target = alias.get('target_id')
            if (alias.get('encoding') != VERSION or alias.get('evidence_id') != ident or target not in known):
                raise ValueError('Invalid, forward or cyclic evidence body alias')
            body = known[target]
            if (digest(body) != alias.get('numbered_body_sha256') or
                    len(body.splitlines()) != alias.get('physical_line_count')):
                raise ValueError('Evidence body alias SHA/physical count differs')
            known[ident] = body; edits.append((start, end+1, body))
        else:
            match = NUMBERED.match(text, start)
            if match is not None:
                known[ident] = match.group()
    for start, end, body in reversed(edits):
        text = text[:start]+body+text[end:]
    return text
