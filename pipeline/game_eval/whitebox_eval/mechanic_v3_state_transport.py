"""Opt-in exact STATE packet grammar after measured full-source overflow.

Changes only the representation of the already selected STATE JSON value.
Every byte, sample, field, provenance and citation line remains recoverable.
"""
from functools import lru_cache
from pathlib import Path
import hashlib
import json
from . import document_wire
from .protocol import dump, sha
from .mechanic_v3_runner import read, exclusive_json, stamp

VERSION = 'mechanic-exact-state-packet-tokens.v1'
MARKER = ('EVIDENCE STATE: exact raw source trace lines and values, not inferred success. '
          'Lossless encoding: replace each provenance_ref with provenance_tables[provenance_ref] '
          'under the provenance key to reconstruct its exact raw row. Cite STATE using the '
          'original line, never the table index:\n')
NOTE = ('EXACT STATE PACKET TRANSPORT: Expand the readable terminal/rule/order grammar below '
        'to reconstruct the exact preceding exact-state-columns.v1 or exact-provenance-table.v1 '
        'JSON value, then apply its unchanged decoding instructions. All samples, physical STATE '
        'line numbers, values and provenance are preserved. Cite original STATE lines, never '
        'grammar indices. This representation asserts no runtime success.\n')


def _claim(root, name):
    return Path(root)/'engineering/exact_state_transport'/(name+'.json')


@lru_cache(maxsize=8)
def encode(raw):
    wire=document_wire._encode_tokens(raw, 'STATE:exact-selected-packet')
    if document_wire.decode(wire)!=raw:
        raise ValueError('State packet bytes changed')
    return json.dumps(wire,ensure_ascii=False,separators=(',',':'))


def extract(body):
    if body.count(MARKER)!=1:
        raise ValueError('Expected exactly one original STATE packet')
    start=body.index(MARKER)+len(MARKER)
    value,end=json.JSONDecoder().raw_decode(body[start:])
    if value.get('encoding') not in {'exact-state-columns.v1','exact-provenance-table.v1'}:
        raise ValueError('Unsupported STATE packet encoding')
    return start,start+end,body[start:start+end]


def authorize(root,name,parent,diagnosis):
    root=Path(root).resolve();diagnosis=Path(diagnosis).resolve()
    if (root/'model_calls'/name).exists():
        raise ValueError('State preflight cannot replace a model invocation')
    failure=read(diagnosis)
    if failure.get('classification')!='COMPLETE_SOURCE_STATE_PACKET_OVERFLOW':
        raise ValueError('Measured full-source overflow diagnosis required')
    if failure.get('measured_prompt_bytes',0)<=failure.get('unchanged_maximum_prompt_bytes',1000000):
        raise ValueError('No demonstrated request overflow')
    from . import mechanic_v3_execution as execution
    paths=[Path(__file__),Path(execution.__file__),Path(document_wire.__file__),
           root/'input_manifest.json',root/'source_qualification.json',
           root/'evidence_manifest.json',root/'trace_summary.json',
           root/'runtime/state_trace.jsonl',diagnosis]
    claim=dict(version=VERSION,time=stamp(),task=name,parent=parent,
               bindings={str(p.resolve()):sha(p) for p in paths},
               scoring_semantics_unchanged=True,selection_and_citations_unchanged=True,
               maximum_prompt_bytes_unchanged=True,product_score=None)
    target=_claim(root,name)
    if target.exists():
        old=read(target)
        if old['bindings']!=claim['bindings']:raise ValueError('State claim binding changed')
        return old
    exclusive_json(target,claim)
    return claim


def apply(root,name,parent,body):
    claim_path=_claim(root,name)
    if not claim_path.exists():return body
    claim=read(claim_path)
    if claim.get('version')!=VERSION or claim['task']!=name or claim['parent']!=parent:
        raise ValueError('State transport identity changed')
    for path,digest in claim['bindings'].items():
        if sha(Path(path))!=digest:raise ValueError('State transport binding changed: '+path)
    start,end,original=extract(body)
    raw=original.encode('utf-8');encoded=encode(raw)
    if len(encoded.encode())>=len(raw):
        raise ValueError('State grammar does not reduce measured request')
    wire=json.loads(encoded)
    if document_wire.decode(wire)!=raw:raise ValueError('State exact byte equivalence failed')
    replacement=NOTE+encoded
    result=body[:start]+replacement+body[end:]
    if result[:start]!=body[:start] or result[start+len(replacement):]!=body[end:]:
        raise ValueError('Non-STATE evidence changed')
    folder=Path(root)/'requests'/name
    folder.mkdir(parents=True,exist_ok=True)
    # Preflight artifacts are not model actual_delivery receipts.
    (folder/'state_packet.original.json').write_bytes(raw)
    (folder/'state_packet.submitted.json').write_text(encoded)
    dump(folder/'state_packet_equivalence.json',dict(version=VERSION,
        claim_sha256=sha(claim_path),original_bytes=len(raw),submitted_bytes=len(encoded.encode()),
        original_sha256=hashlib.sha256(raw).hexdigest(),
        submitted_sha256=hashlib.sha256(encoded.encode()).hexdigest(),
        exact_original_json_bytes=True,non_state_context_byte_identical=True,
        original_state_line_numbers_values_fields_occurrences=True))
    return result
