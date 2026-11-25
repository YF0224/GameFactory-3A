"""Strict reversible representation mapping for source-review column-list JSON.

Only maps already supplied literal text and references. No defaults, inference,
source edits, score changes, or waived source/schema validation.
"""
from pathlib import Path
import json
from .protocol import dump,sha
VERSION='source-score-column-list-lossless.v1'
RECEIPT='source_score_response_transport.json'

def unpack(raw, bindings, case_id):
    if (not isinstance(raw,dict) or set(raw)!={'evaluation_type','case_id','scope','columns'}
            or raw['evaluation_type']!='initial_source_code_scores' or raw['case_id']!=case_id
            or not isinstance(raw['scope'],str) or not raw['scope'].strip()
            or not isinstance(raw['columns'],list)):
        raise ValueError('Not the exact source-score column-list representation')
    expected={row['id']:row['column'] for row in bindings}
    checks={};order=[]
    for row in raw['columns']:
        if (not isinstance(row,dict) or set(row)!={'id','column','score','score_basis','source_explanation','evidence'}
                or row['id'] not in expected or row['id'] in checks
                or row['column']!=expected[row['id']]
                or not all(isinstance(row[k],str) and row[k].strip() for k in ('score_basis','source_explanation'))
                or not isinstance(row['evidence'],list)):
            raise ValueError('Invalid or ambiguous source column representation')
        evidence=[]
        for ref in row['evidence']:
            if not isinstance(ref,dict) or set(ref)!={'path','sha256','line_start','line_end'}:
                raise ValueError('Source reference fields are not an exact representation')
            evidence.append(dict(ref,reason=row['source_explanation']))
        checks[row['id']]={'score':row['score'],'basis':row['score_basis'],
            'runtime_or_visual_limits':raw['scope']+'\n'+row['source_explanation'],'evidence':evidence}
        order.append(row['id'])
    if set(checks)!=set(expected):raise ValueError('Source column coverage differs')
    value={'checks':checks}
    # Reconstruct from mapped text/references, with only literal envelope/order
    # metadata. All per-column explanation and source bytes come from value.
    restored={'evaluation_type':raw['evaluation_type'],'case_id':case_id,'scope':raw['scope'],'columns':[]}
    for ident in order:
        row=checks[ident];prefix=raw['scope']+'\n';explanation=row['runtime_or_visual_limits'][len(prefix):]
        refs=[]
        for ref in row['evidence']:
            if ref['reason']!=explanation:raise ValueError('Shared reference explanation changed')
            refs.append({k:ref[k] for k in ('path','sha256','line_start','line_end')})
        restored['columns'].append({'id':ident,'column':expected[ident],'score':row['score'],
            'score_basis':row['basis'],'source_explanation':explanation,'evidence':refs})
    if restored!=raw:raise ValueError('Source response mapping is not reversible')
    return value

def read(root,protocol,response,*,persist=False):
    from . import batch,unity_source_review as review
    root=Path(root);response=Path(response);raw=batch.read(response)
    if isinstance(raw,dict) and set(raw)=={'checks'}:return raw
    manifest=batch.read(root/'input_manifest.json');case=manifest['entry']['case_id']
    bindings=review.column_targets(protocol)
    schema_file=response.parent/'schema.json'
    if batch.read(schema_file)!=review.schema(protocol,grouped=True):
        raise ValueError('Original submitted source schema differs from exact grouped schema')
    value=unpack(raw,bindings,case)
    review.validate(root,protocol,value)
    receipt={'version':VERSION,'response':str(response.relative_to(root)),'response_sha256':sha(response),
        'schema_sha256':sha(schema_file),'input_manifest_sha256':sha(root/'input_manifest.json'),
        'bindings':bindings,'mapping':{'score':'score','basis':'score_basis',
        'runtime_or_visual_limits':['scope','source_explanation'],'evidence.reason':'source_explanation shared by the original reference group'},
        'roundtrip_equal':True,'canonical_result':value,'new_model_calls':0,'changed_scores':0,
        'source_sha_and_physical_line_validation':'unchanged strict unity_source_review.validate'}
    path=root/RECEIPT
    if persist:
        if path.exists() and batch.read(path)!=receipt:raise ValueError('Source response transport receipt changed')
        dump(path,receipt)
    elif batch.read(path)!=receipt:raise ValueError('Source response transport binding changed')
    return value
