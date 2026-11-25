"""Readable exact literal references without JSON-escaping the full source body.

Only the dictionary is JSON. The template retains ordinary UTF-8 text, with ~~
for a literal tilde and ~xy for one explicit, nonrecursive dictionary literal.
The validated shared-document template and original bytes are never replaced.
"""
import json
from . import exact_evidence_alias as alias
from . import gameness_v4_literal_container as shared_container

VERSION = 'gameness-v4-readable-raw-literal-container.v1'
ALPHABET = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_-'
NOTICE = shared_container.NOTICE + (
    'EXACT READABLE LITERAL TEMPLATE: the following dictionary contains complete original '
    'literal strings. In TEMPLATE, ~~ means one literal ~; ~xy means dictionary[index], '
    'where index=64*position(x)+position(y) in alphabet '
    + ALPHABET + '. All other characters remain literal, including line endings. '
    'Expand once from left to right; dictionary literals are NOT recursively expanded. '
    'Then expand the included evidence-body aliases and cite only original evidence IDs '
    'and physical lines. The template itself is not executable and asserts no success.\n')
MARKER = '\nEXACT RAW UTF-8 TEMPLATE:\n'


def encode(body, template_packet):
    table, doc, raw = shared_container.parse(template_packet)
    aliased, alias_proof = alias.encode(body)
    if raw != aliased.encode('utf-8'):
        raise ValueError('Raw template must contain every original body byte')
    dictionary = table['dictionary']
    if len(dictionary) > 4096:
        raise ValueError('Raw literal dictionary exceeds the fixed two-digit alphabet')
    pieces = []
    for piece in doc['pieces']:
        if type(piece) is int:
            pieces.append('~'+ALPHABET[piece//64]+ALPHABET[piece%64])
        else:
            pieces.append(piece.replace('~','~~'))
    template = ''.join(pieces)
    header = dict(encoding=VERSION,dictionary=dictionary,
        aliased_sha256=alias.digest(aliased),aliased_bytes=len(aliased.encode()),
        aliased_physical_lines=len(aliased.splitlines()),original_sha256=alias.digest(body),
        template_bytes=len(template.encode()))
    wire = NOTICE+json.dumps(header,ensure_ascii=False,separators=(',',':'))+MARKER+template
    if decode(wire) != body:
        raise ValueError('Raw literal reconstruction changed original evidence bytes')
    return wire, dict(version=VERSION,original_sha256=alias.digest(body),submitted_sha256=alias.digest(wire),
        original_bytes=len(body.encode()),submitted_bytes=len(wire.encode()),alias_proof=alias_proof,
        exact_expansion=True,physical_lines_unchanged=True,synthetic_id_is_citable=False)


def decode(wire):
    if not wire.startswith(NOTICE):
        raise ValueError('Missing raw literal decoding and citation rules')
    rest=wire[len(NOTICE):]
    header,end=json.JSONDecoder().raw_decode(rest)
    if not rest[end:].startswith(MARKER):
        raise ValueError('Missing exact raw template boundary')
    template=rest[end+len(MARKER):]
    dictionary=header.get('dictionary')
    if (header.get('encoding')!=VERSION or not isinstance(dictionary,list) or len(dictionary)>4096
            or any(not isinstance(x,str) or not x for x in dictionary)
            or len(template.encode())!=header.get('template_bytes')):
        raise ValueError('Raw literal encoding, dictionary or byte count changed')
    pieces=[];start=0
    while start<len(template):
        pos=template.find('~',start)
        if pos<0:
            pieces.append(template[start:]);break
        pieces.append(template[start:pos])
        if template[pos:pos+2]=='~~':
            pieces.append('~');start=pos+2;continue
        if pos+2>=len(template) or any(c not in ALPHABET for c in template[pos+1:pos+3]):
            raise ValueError('Invalid raw literal reference')
        index=64*ALPHABET.index(template[pos+1])+ALPHABET.index(template[pos+2])
        if index>=len(dictionary):raise ValueError('Unknown raw literal dictionary index')
        pieces.append(dictionary[index]);start=pos+3
    aliased=''.join(pieces)
    if (alias.digest(aliased)!=header.get('aliased_sha256') or len(aliased.encode())!=header.get('aliased_bytes')
            or len(aliased.splitlines())!=header.get('aliased_physical_lines')):
        raise ValueError('Raw template expansion changed original physical text')
    body=alias.decode(aliased)
    if alias.digest(body)!=header.get('original_sha256'):
        raise ValueError('Original evidence body SHA differs')
    return body
