"""Reproduce a conservative legacy static-response conversion without source credit."""
import copy
from pathlib import Path

from . import codex, static_existence, partial_static_existence
from .protocol import dump, sha

VERSION = 'whitebox-static-items-transport.v1'
RECEIPT = 'static_items_transport.json'
MISSING_REFERENCE_REASON = '[TRANSPORT LIMITATION] Original reference has no individual explanation; entry connection is unproven.'


def normalize(root, protocol, original):
    if not isinstance(original, dict) or set(original) != {'identity', 'items'}:
        raise ValueError('Expected exact legacy identity/items shape')
    expected = [row['id'] for row in static_existence.items(protocol)]
    rows = original['items']
    if (not isinstance(rows, list) or len(rows) != len(expected)
            or any(not isinstance(r, dict) or set(r) != {'id','status','reason','evidence'} for r in rows)
            or len({r['id'] for r in rows}) != len(rows) or {r['id'] for r in rows} != set(expected)):
        raise ValueError('Legacy response omitted, duplicated or invented static IDs/fields')
    checks = {}
    for row in rows:
        if row['status'] not in {'EXISTS','MISSING','UNKNOWN'}:
            raise ValueError('Unsupported legacy source status')
        if not isinstance(row['reason'],str) or not row['reason'].strip() or not isinstance(row['evidence'],list):
            raise ValueError('Missing original legacy reason/evidence')
        refs=[]
        for ref in row['evidence']:
            if not isinstance(ref,dict) or set(ref) != {'path','sha256','line_start','line_end','role'}:
                raise ValueError('Unknown legacy source reference shape')
            refs.append({**copy.deepcopy(ref),'reason':MISSING_REFERENCE_REASON})
        checks[row['id']] = {
            'static_existence':'UNKNOWN' if row['status']=='EXISTS' else row['status'],
            'connected_to_entry':False,
            'reason':'[TRANSPORT LIMITATION: no explicit entry connection; EXISTS withdrawn] '+row['reason'],
            'evidence':refs}
    result={'identity':copy.deepcopy(original['identity']),'checks':checks}
    # This enforces the original identity, every original SHA/path/physical line,
    # and canonical schema. No reference or unsupported EXISTS survives by omission.
    return static_existence.validate_result(root,protocol,result)


def source_reply(root, response):
    root, response=Path(root).resolve(),Path(response).resolve()
    partial_static_existence.successful_reply(root,response)
    folders=[p for p in (root/'model_calls').glob('static_existence*') if p.is_dir()]
    if any(p != response.parent for p in folders):
        raise ValueError('Legacy recovery requires the sole original review; no fallback across later attempts')
    error=codex.load_plan_json(response.parent/'schema_error.json')
    if (error.get('response_sha256') != sha(response) or error.get('phase') != 'response_schema_validation'
            or "missing=['checks'], unexpected=['items']" not in str(error.get('exception',''))):
        raise ValueError('No SHA-bound terminal identity/items schema rejection')


def accept(root, protocol, response, *, authorization):
    root,response=Path(root).resolve(),Path(response).resolve()
    if not isinstance(authorization,str) or not authorization.strip():
        raise ValueError('Explicit transport recovery authorization required')
    if any((root/name).exists() for name in ('static_existence.json',RECEIPT,'sol_plan.json','background_record')):
        raise ValueError('Existing review/plan/capture protected')
    source_reply(root,response)
    result=normalize(root,protocol,codex.load_plan_json(response))
    receipt={'version':VERSION,'authorization':authorization,'response':str(response.relative_to(root)),
        'response_sha256':sha(response),'invocation_sha256':sha(response.parent/'invocation.json'),
        'schema_error_sha256':sha(response.parent/'schema_error.json'),
        'transform':'items by exact ID; EXISTS to UNKNOWN; explicit unsupported connection false; missing reference reason marked limitation',
        'original_source_coordinates_unchanged':True,'model_calls_added':0,'gameplay_verified':False}
    dump(root/RECEIPT,receipt)
    dump(root/'static_existence.json',{'version':static_existence.SCHEMA,'result':result,
        'response_sha256':sha(response),'model':static_existence.MODEL,
        'policy':static_existence.policy(protocol)['version'],'transport_normalization_sha256':sha(root/RECEIPT)})
    return verify(root,protocol)


def verify(root, protocol):
    root=Path(root).resolve()
    receipt=codex.load_plan_json(root/RECEIPT);artifact=codex.load_plan_json(root/'static_existence.json')
    if (receipt.get('version')!=VERSION or not receipt.get('authorization')
            or receipt.get('original_source_coordinates_unchanged') is not True
            or receipt.get('model_calls_added')!=0 or receipt.get('gameplay_verified') is not False
            or artifact.get('version')!=static_existence.SCHEMA or artifact.get('model')!=static_existence.MODEL
            or artifact.get('policy')!=static_existence.policy(protocol)['version']
            or artifact.get('transport_normalization_sha256')!=sha(root/RECEIPT)):
        raise ValueError('Static legacy transport receipt or artifact changed')
    response=root/receipt['response'];source_reply(root,response)
    if (sha(response)!=receipt['response_sha256'] or sha(response)!=artifact['response_sha256']
            or sha(response.parent/'invocation.json')!=receipt['invocation_sha256']
            or sha(response.parent/'schema_error.json')!=receipt['schema_error_sha256']):
        raise ValueError('Original static response/invocation/schema rejection changed')
    result=normalize(root,protocol,codex.load_plan_json(response))
    if result!=artifact.get('result'):
        raise ValueError('Legacy static transport differs from conservative derivation')
    return result
