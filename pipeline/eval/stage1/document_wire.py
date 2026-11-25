"""Readable exact document bytes and physical citations under existing packet caps."""
import hashlib
import json
import re
from collections import Counter
from functools import lru_cache
from threading import Lock
from .protocol import dump, sha
from pathlib import Path
from . import lossless_log_grammar as grammar

TOKEN_VERSION = 'whitebox-exact-document-tokens.v1'
VERSION = 'whitebox-exact-document-lines.v1'
_PERSIST_LOCK = Lock()


def encode(path, ident):
    return _encode_bytes(Path(path).read_bytes(),ident)


def _encode_bytes(raw, ident):
    text = raw.decode('utf-8')
    contents, endings = [], []
    for physical in text.splitlines(keepends=True):
        parts = physical.splitlines()
        line = parts[0] if parts else ''
        ending = physical[len(line):]
        contents.append(line)
        if endings and endings[-1][0] == ending:
            endings[-1][1] += 1
        else:
            endings.append([ending,1])
    source_sha = hashlib.sha256(raw).hexdigest()
    wire = {'encoding':VERSION, 'evidence_id':ident, 'source_sha256':source_sha,
        'decode':'Expand lines using its readable acyclic symbols/order grammar into original physical '
            '(line_number,text) rows. Expand each line_terminator_runs [terminator,count] in order. '
            'Append the matching terminator to each row and concatenate to reconstruct the exact UTF-8 '
            'source bytes, including whitespace. Cite evidence_id with original physical line numbers. '
            'These are unchanged source/diagnostic documents; they do not assert runtime success.',
        'lines':grammar.encode(contents,list(range(1,len(contents)+1)),source_sha),
        'line_terminator_runs':endings}
    if decode(wire) != raw:
        raise ValueError('Exact document byte equivalence failed')
    return wire


def decode(wire):
    if wire.get('encoding') == TOKEN_VERSION:
        return _decode_tokens(wire)
    if (wire.get('encoding') != VERSION or not isinstance(wire.get('evidence_id'),str)
            or not wire['evidence_id']):
        raise ValueError('Invalid exact document envelope')
    rows = grammar.decode(wire['lines'])
    if [n for n,_ in rows] != list(range(1,len(rows)+1)):
        raise ValueError('Exact document physical lines missing or reordered')
    runs = wire.get('line_terminator_runs')
    if not isinstance(runs,list):
        raise ValueError('Invalid document line terminators')
    total = 0
    for run in runs:
        if (not isinstance(run,list) or len(run)!=2 or type(run[1]) is not int
                or run[1] < 1 or run[0] not in ('','\n','\r','\r\n','\v','\f','\x1c','\x1d','\x1e','\x85','\u2028','\u2029')):
            raise ValueError('Invalid document line terminator run')
        total += run[1]
    if total != len(rows):
        raise ValueError('Document physical occurrence count differs')
    endings = [ending for ending,count in runs for _ in range(count)]
    raw = ''.join(text+ending for (_,text),ending in zip(rows,endings)).encode('utf-8')
    if (len(raw.decode().splitlines()) != len(rows) or
            hashlib.sha256(raw).hexdigest() != wire.get('source_sha256') or
            wire['lines'].get('source_sha256') != wire.get('source_sha256')):
        raise ValueError('Exact document source SHA or physical lines differ')
    return raw


def section(path, ident):
    return _section_bytes(Path(path).read_bytes(),ident)


@lru_cache(maxsize=128)
def _section_bytes(raw, ident):
    candidates=[_encode_bytes(raw,ident),_encode_tokens(raw,ident)]
    wire=min((json.dumps(v,ensure_ascii=False,separators=(',',':')) for v in candidates),key=len)
    return ('\nEVIDENCE '+ident+' (exact document physical lines):\n'+wire)


def verify_section(packet, path, ident):
    marker='\nEVIDENCE '+ident+' (exact document physical lines):\n'
    if packet.count(marker)!=1:
        from .shared_document_wire import verify_section as verify_shared
        return verify_shared(packet,path,ident)
    payload=packet.split(marker,1)[1].split('\n',1)[0]
    try:
        wire=json.loads(payload)
        return wire.get('evidence_id')==ident and decode(wire)==Path(path).read_bytes()
    except (ValueError,KeyError,TypeError):
        return False


def persist(root, entry, text):
    """Same immutable bytes across shard threads; retain exact actual encoding."""
    root=Path(root)
    source=root/entry['path']
    digest=sha(source)
    folder=(root/'validation_history/document_wire'/hashlib.sha256(entry['id'].encode()).hexdigest()/digest
            /hashlib.sha256(text.encode()).hexdigest())
    with _PERSIST_LOCK:
        folder.mkdir(parents=True,exist_ok=True)
        actual=folder/'actual_section.txt'
        if actual.exists() and actual.read_text()!=text:
            raise ValueError('Prior exact document encoding differs')
        actual.write_text(text)
        dump(folder/'equivalence.json',{'evidence_id':entry['id'],'path':entry['path'],
            'source_sha256':digest,'actual_section_sha256':sha(actual),
            'original_physical_lines':len(source.read_text().splitlines()),'exact_source_bytes':True,
            'original_numbering_order_occurrences':True,'packet_caps_unchanged':True})


def _encode_tokens(raw, ident):
    text=raw.decode('utf-8')
    tokens=re.findall(r'\w+|\s+|[^\w\s]',text)
    if ''.join(tokens)!=text:
        raise ValueError('Exact document tokenizer changed source characters')
    terminals=list(dict.fromkeys(tokens))
    indices={v:i for i,v in enumerate(terminals)}
    stream=[indices[v] for v in tokens]
    rules=[]
    for _ in range(1000):
        best=Counter(zip(stream,stream[1:])).most_common(1)
        if not best or best[0][1]<3:
            break
        pair,_=best[0]
        symbol=len(terminals)+len(rules)
        output=[];index=0
        while index<len(stream):
            if index+1<len(stream) and (stream[index],stream[index+1])==pair:
                output.append(symbol);index+=2
            else:
                output.append(stream[index]);index+=1
        rules.append(list(pair));stream=output
    wire={'encoding':TOKEN_VERSION,'evidence_id':ident,'source_sha256':hashlib.sha256(raw).hexdigest(),
        'decode':'Terminal indices start at zero. Terminal strings contain exact original characters, including '
            'whitespace and line terminators. Rule i has index len(terminals)+i and concatenates its two '
            'earlier symbols. Expand order left to right and concatenate to reconstruct the exact UTF-8 '
            'document bytes. Number physical lines in that reconstructed source from 1. Retain every '
            'character, repeated occurrence and original citation. This packaging asserts no runtime success.',
        'token_count':len(tokens),'character_count':len(text),'physical_line_count':len(text.splitlines()),
        'terminals':terminals,'rules':rules,'order':stream}
    if _decode_tokens(wire)!=raw:
        raise ValueError('Exact document token byte equivalence failed')
    return wire


def _decode_tokens(wire):
    count=wire.get('token_count');chars=wire.get('character_count');line_count=wire.get('physical_line_count')
    terms,rules,order=(wire.get(k) for k in ('terminals','rules','order'))
    if (not isinstance(wire.get('evidence_id'),str) or not wire['evidence_id'] or
            any(type(n) is not int or not 0<=n<=64*1048576 for n in (count,chars,line_count)) or
            not all(isinstance(v,list) for v in (terms,rules,order)) or
            any(len(v)>count for v in (terms,rules,order)) or
            any(not isinstance(t,str) or not t for t in terms)):
        raise ValueError('Invalid document token grammar')
    sizes=[1]*len(terms);lengths=[len(t) for t in terms]
    for pair in rules:
        if (not isinstance(pair,list) or len(pair)!=2 or
                any(type(i) is not int or not 0<=i<len(sizes) for i in pair)):
            raise ValueError('Invalid or cyclic document token rule')
        size=sum(sizes[i] for i in pair);length=sum(lengths[i] for i in pair)
        if size>count or length>chars:
            raise ValueError('Document token expansion exceeds bounds')
        sizes.append(size);lengths.append(length)
    if (any(type(i) is not int or not 0<=i<len(sizes) for i in order) or
            sum(sizes[i] for i in order)!=count or sum(lengths[i] for i in order)!=chars):
        raise ValueError('Document token occurrence count differs')
    result=[];seen=set();stack=list(reversed(order))
    while stack:
        index=stack.pop();seen.add(index)
        if index<len(terms):result.append(terms[index])
        else:stack.extend(reversed(rules[index-len(terms)]))
    text=''.join(result);raw=text.encode('utf-8')
    if (len(seen)!=len(sizes) or len(text.splitlines())!=line_count or
            hashlib.sha256(raw).hexdigest()!=wire.get('source_sha256')):
        raise ValueError('Document token source SHA or physical occurrence count differs')
    return raw
