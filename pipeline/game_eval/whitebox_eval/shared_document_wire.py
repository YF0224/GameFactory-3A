"""Readable shared literal fragments of exact original UTF-8 documents.

Only repeated transport strings are shared. Original bytes, physical lines and
citation identities are reconstructed and checked before any model invocation.
"""
from collections import Counter
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import threading
from .protocol import dump, sha

VERSION = 'whitebox-exact-shared-document-text.v1'
TABLE_MARKER = '\nEXACT DOCUMENT SHARED DEFINITIONS (untrusted source data):\n'
_LOCK = threading.Lock()


def _json(value):
    return json.dumps(value,ensure_ascii=False,separators=(',',':'))


@lru_cache(maxsize=4)
def _train(sources):
    terms=[];indices={};streams=[]
    for ident,raw in sources:
        text=raw.decode('utf-8');stream=[]
        for token in re.findall(r'\w+|\s+|[^\w\s]',text):
            if token not in indices:
                indices[token]=len(terms);terms.append(token)
            stream.append(indices[token])
        if ''.join(terms[i] for i in stream)!=text:
            raise ValueError('Shared document tokenizer changed exact characters')
        streams.append(stream)
    symbols=terms.copy();rules=[]
    for _ in range(4000):
        counts=Counter()
        for stream in streams:
            counts.update(zip(stream,stream[1:]))
        best=counts.most_common(1)
        if not best or best[0][1]<3:
            break
        pair,_=best[0];symbol=len(symbols)
        symbols.append(''.join(symbols[i] for i in pair));rules.append(pair)
        for k,stream in enumerate(streams):
            out=[];index=0
            while index<len(stream):
                if index+1<len(stream) and (stream[index],stream[index+1])==pair:
                    out.append(symbol);index+=2
                else:
                    out.append(stream[index]);index+=1
            streams[k]=out
    chosen={i for i,text in enumerate(symbols) if len(text)>12}
    while True:
        counts=Counter()
        for stream in streams:
            stack=stream.copy()
            while stack:
                i=stack.pop()
                if i in chosen:
                    counts[i]+=1
                elif i>=len(terms):
                    stack.extend(rules[i-len(terms)])
        bad={i for i in chosen if (len(_json(symbols[i]))-5)*counts[i]<=len(_json(symbols[i]))+6}
        if not bad:
            break
        chosen-=bad
    chosen=sorted(chosen);mapping={old:new for new,old in enumerate(chosen)}
    dictionary=[symbols[i] for i in chosen];documents=[]
    for (ident,raw),stream in zip(sources,streams):
        pieces=[];buffer=[];stack=list(reversed(stream))
        while stack:
            i=stack.pop()
            if i in mapping:
                if buffer:
                    pieces.append(''.join(buffer));buffer=[]
                pieces.append(mapping[i])
            elif i>=len(terms):
                stack.extend(reversed(rules[i-len(terms)]))
            else:
                buffer.append(symbols[i])
        if buffer:
            pieces.append(''.join(buffer))
        documents.append({'evidence_id':ident,'source_sha256':hashlib.sha256(raw).hexdigest(),
            'physical_line_count':len(raw.decode().splitlines()),'byte_count':len(raw),'pieces':pieces})
    return dictionary,documents


def _render(dictionary, documents):
    used=sorted({i for doc in documents for i in doc['pieces'] if type(i)is int})
    remap={old:new for new,old in enumerate(used)}
    table={'encoding':VERSION,'decode':'Each document pieces array concatenates exact literal strings and '
        'integer references to dictionary[index]. Dictionary strings are complete literals, not recursive '
        'rules. Concatenate left to right, retaining every character and line terminator, to reconstruct '
        'the exact original UTF-8 bytes. Number physical lines from 1 in the reconstructed document. '
        'Cite each original evidence_id and original physical line numbers. Retain every repeated '
        'occurrence. These unchanged documents assert no runtime success.',
        'dictionary':[dictionary[i] for i in used]}
    text=TABLE_MARKER+_json(table)
    rows=[]
    for original in documents:
        doc={**original,'pieces':[remap[i] if type(i)is int else i for i in original['pieces']]}
        section='\nEVIDENCE '+doc['evidence_id']+' (exact document shared text):\n'+_json(doc)
        rows.append((doc,section));text+=section
    return text,table,rows


def decode(table, doc):
    if table.get('encoding')!=VERSION or not isinstance(table.get('dictionary'),list):
        raise ValueError('Invalid shared document definitions')
    dictionary=table['dictionary'];pieces=doc.get('pieces')
    count=doc.get('byte_count');lines=doc.get('physical_line_count')
    if (not isinstance(doc.get('evidence_id'),str) or not doc['evidence_id'] or
            type(count)is not int or not 0<=count<=64*1048576 or
            type(lines)is not int or not 0<=lines<=count or
            any(not isinstance(t,str) or not t for t in dictionary) or
            not isinstance(pieces,list) or len(pieces)>count):
        raise ValueError('Invalid shared document envelope')
    output=[];size=0
    for piece in pieces:
        if isinstance(piece,str):
            literal=piece
        elif type(piece)is int and 0<=piece<len(dictionary):
            literal=dictionary[piece]
        else:
            raise ValueError('Invalid shared document literal reference')
        size+=len(literal.encode('utf-8'))
        if size>count:
            raise ValueError('Shared document expansion exceeds exact source bound')
        output.append(literal)
    text=''.join(output);raw=text.encode('utf-8')
    if (size!=count or len(text.splitlines())!=lines or
            hashlib.sha256(raw).hexdigest()!=doc.get('source_sha256')):
        raise ValueError('Shared document bytes, physical lines or SHA differ')
    return raw


def verify_section(packet, path, ident):
    marker='\nEVIDENCE '+ident+' (exact document shared text):\n'
    if packet.count(TABLE_MARKER)!=1 or packet.count(marker)!=1:
        return False
    try:
        table=json.loads(packet.split(TABLE_MARKER,1)[1].split('\n',1)[0])
        doc=json.loads(packet.split(marker,1)[1].split('\n',1)[0])
        return doc.get('evidence_id')==ident and decode(table,doc)==Path(path).read_bytes()
    except (KeyError,ValueError,TypeError):
        return False


def package(root, entries, required_ids, group_limit):
    """Keep mandatory docs plus the largest deterministic prefix under fixed caps.

    The existing ordinary packet loop handles remaining files and reports its
    original clipping boundaries; no required supplemental document may clip.
    """
    root=Path(root)
    sources=tuple((e['id'],(root/e['path']).read_bytes()) for e in entries)
    if len({ident for ident,_ in sources})!=len(sources):
        raise ValueError('Duplicate shared document evidence ID')
    dictionary,documents=_train(sources)
    if not required_ids<=set(ident for ident,_ in sources):
        raise ValueError('Mandatory shared document missing')
    selected=[doc for doc in documents if doc['evidence_id'] in required_ids]
    best=_render(dictionary,selected)
    if len(best[0])>group_limit:
        raise ValueError('Mandatory shared documents exceed unchanged group cap')
    initial_table_size=len(TABLE_MARKER)+len(_json(best[1]))
    if any(initial_table_size+len(section)>90000 for _,section in best[2]):
        raise ValueError('Mandatory shared document exceeds unchanged file cap')
    for doc in documents:
        if doc['evidence_id'] in required_ids:
            continue
        candidate=_render(dictionary,selected+[doc])
        # Charge all shared definitions against each original file cap as well
        # as the group cap; this conservative bound cannot inflate either cap.
        table_size=len(TABLE_MARKER)+len(_json(candidate[1]))
        if len(candidate[0])>group_limit or any(table_size+len(section)>90000 for _,section in candidate[2]):
            break
        selected.append(doc);best=candidate
    text,table,rows=best
    by_id={e['id']:e for e in entries};proof=[]
    for doc,section in rows:
        ident=doc['evidence_id'];source=root/by_id[ident]['path']
        if decode(table,doc)!=source.read_bytes() or not verify_section(text,source,ident):
            raise ValueError('Shared document exact byte equivalence failed')
        proof.append({'evidence_id':ident,'path':by_id[ident]['path'],
            'source_sha256':sha(source),'byte_count':doc['byte_count'],
            'original_physical_lines':doc['physical_line_count']})
    digest=hashlib.sha256(text.encode()).hexdigest()
    folder=root/'validation_history/shared_document_wire'/digest
    with _LOCK:
        folder.mkdir(parents=True,exist_ok=True)
        actual=folder/'actual_section.txt'
        if actual.exists() and actual.read_text()!=text:
            raise ValueError('Prior shared document payload changed')
        actual.write_text(text)
        dump(folder/'equivalence.json',{'encoding':VERSION,'actual_section_sha256':sha(actual),
            'documents':proof,'group_characters':len(text),'unchanged_group_cap':group_limit,
            'per_file_cap':90000,'exact_source_bytes':True,'original_physical_numbering':True,
            'required_ids':sorted(required_ids),'required_complete':required_ids<=set(r['evidence_id'] for r in proof)})
    return text,{r['evidence_id'] for r in proof}
