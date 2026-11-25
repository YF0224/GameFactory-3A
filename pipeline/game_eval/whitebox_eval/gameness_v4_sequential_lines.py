"""Exactly reversible sequential numbering for complete physical evidence lines."""
import hashlib,json,re
VERSION='gameness-v4-two-literal-sequential-lines.v1'
WIRE_HEADER='TWO_LITERAL_NUMBERED_LAYERS_V1\n'
HEADER='EXACT_SEQUENTIAL_EVIDENCE_LINES_V1\n'
MARKER='EXACT_SEQUENTIAL_LINES '
NOTICE=("EXPLICIT SEQUENTIAL SOURCE TRANSPORT: remove TWO_LITERAL_NUMBERED_LAYERS_V1 header; "
 "expand the outer nonrecursive literal dictionary once to recover the inner literal wire, "
 "then expand the inner nonrecursive dictionary once. Remove EXACT_SEQUENTIAL_EVIDENCE_LINES_V1. "
 "For each EXACT_SEQUENTIAL_LINES JSON header, read exactly its UTF-8 bytes field after the newline. "
 "Those are ALL original physical line contents in order, including blank lines. Prefix those "
 "lines with consecutive '1: ', '2: ', etc., preserving every newline. Verify lines and numbered_sha256. "
 "Then expand EXACT_EVIDENCE_BODY_ALIAS. Cite the original evidence IDs and recovered physical "
 "line numbers. Every original source byte, runtime row and occurrence is retained; no summary "
 "or omitted source is allowed. All original native images are attached to the final turn.\n")
EVIDENCE=re.compile(r'(?m)^EVIDENCE ([^\n]+)\n')
NUMBERED=re.compile(r'(?:[1-9][0-9]*: [^\n]*\n)+')
def digest(text):return hashlib.sha256(text.encode('utf-8')).hexdigest()
def encode(text):
 if HEADER in text or MARKER in text:raise ValueError('Reserved sequential source grammar occurs in input')
 edits=[]
 for match in EVIDENCE.finditer(text):
  found=NUMBERED.match(text,match.end())
  if found is None:continue
  rows=found[0].splitlines(keepends=True)
  if [int(s.split(': ',1)[0]) for s in rows]!=list(range(1,len(rows)+1)):continue
  body=''.join(s.split(': ',1)[1] for s in rows)
  meta=dict(lines=len(rows),bytes=len(body.encode('utf-8')),numbered_sha256=digest(found[0]))
  edits.append((found.start(),found.end(),MARKER+json.dumps(meta,separators=(',',':'))+'\n'+body))
 result=text
 for start,end,replacement in reversed(edits):result=result[:start]+replacement+result[end:]
 wire=HEADER+result
 if decode(wire)!=text:raise ValueError('Complete sequential source round trip differs')
 return wire

def _unique(pairs):
 result={}
 for key,value in pairs:
  if key in result:raise ValueError('Duplicate sequential metadata key')
  result[key]=value
 return result

def decode(wire):
 if not isinstance(wire,str) or not wire.startswith(HEADER):raise ValueError('Explicit sequential version header required')
 raw=wire[len(HEADER):].encode('utf-8');result=[];position=0;marker=MARKER.encode('ascii')
 while position<len(raw):
  candidate=raw.find(marker,position)
  if candidate<0:result.append(raw[position:]);break
  if candidate and raw[candidate-1]!=10:raise ValueError('Sequential marker must start a physical line')
  result.append(raw[position:candidate]);end=raw.find(b'\n',candidate)
  if end<0:raise ValueError('Unterminated sequential metadata')
  meta=json.loads(raw[candidate+len(marker):end],object_pairs_hook=_unique)
  if not isinstance(meta,dict) or set(meta)!={'lines','bytes','numbered_sha256'}:raise ValueError('Exact sequential metadata required')
  count,size=meta['lines'],meta['bytes'];start=end+1
  if (type(count)!=int or type(size)!=int or not 0<count<=size or not 0<size<=len(raw)-start
      or not isinstance(meta['numbered_sha256'],str) or re.fullmatch('[0-9a-f]{64}',meta['numbered_sha256']) is None):raise ValueError('Invalid sequential line count, byte length or digest')
  body=raw[start:start+size].decode('utf-8');rows=body.splitlines(keepends=True)
  if len(rows)!=count or any(not line.endswith('\n') for line in rows):raise ValueError('Exact original physical newlines required')
  original=''.join(str(i)+': '+line for i,line in enumerate(rows,1))
  if digest(original)!=meta['numbered_sha256']:raise ValueError('Original physical numbered source digest differs')
  result.append(original.encode('utf-8'));position=start+size
 return b''.join(result).decode('utf-8')
