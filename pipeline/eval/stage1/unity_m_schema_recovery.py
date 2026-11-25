"""One exact-language schema transport recovery for actual truncated output.

Only Citation.anyOf branches differing solely in their id enum are coalesced.
The frozen schema and task remain immutable and validate every recovered result.
"""
from pathlib import Path
import copy
import hashlib
import json
from . import batch, codex
from .protocol import sha

VERSION = 'unity-m-equivalent-citation-schema-recovery.v1'
SHARED_VERSION = 'unity-m-shared-exact-schema-recovery.v1'
SHARED_INITIAL_VERSION = 'unity-m-shared-exact-initial-schema.v1'

def shared_schema(original):
    from .judge_schema_transport import compact, expand
    reduced, citation = compact_schema(original)
    shared = compact(reduced)
    if expand(shared) != expand(reduced):
        raise ValueError('Exact shared schema inverse differs')
    proof = dict(version=SHARED_VERSION, citation_equivalence=citation,
        original_sha256=hashlib.sha256(key(original).encode()).hexdigest(),
        transported_sha256=hashlib.sha256(key(shared).encode()).hexdigest(),
        original_bytes=len(key(original).encode()), transported_bytes=len(key(shared).encode()),
        exact_expanded_schema_sha256=hashlib.sha256(key(expand(reduced)).encode()).hexdigest())
    if proof['transported_bytes'] >= len(key(reduced).encode()):
        raise ValueError('Shared schema requires substantive repeated-node reduction')
    return shared, proof

def shared_authorized(root, task):
    from .unity_m_shared_schema_repair import authorized
    from .unity_m_incomplete_recovery import authorized as incomplete_authorized
    return authorized(root, task['column']) or incomplete_authorized(root,task['column'])


def key(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def compact_schema(original):
    result = copy.deepcopy(original)
    citation = result.get('$defs', {}).get('Citation', {})
    branches = citation.get('anyOf')
    if not isinstance(branches, list) or not branches:
        raise ValueError('Explicit Citation alternatives required')
    groups = {}
    expanded = []
    for branch in branches:
        shape = copy.deepcopy(branch)
        prop = shape.get('properties', {}).get('id', {})
        ids = prop.pop('enum', None)
        if not isinstance(ids, list) or not ids or any(type(i) is not str for i in ids):
            raise ValueError('Explicit string citation identities required')
        # Equal shape includes every validation keyword, including all bounds.
        identity = key(shape)
        group = groups.setdefault(identity, [shape, []])
        group[1].extend(i for i in ids if i not in group[1])
        for ident in ids:
            item = copy.deepcopy(shape);item['properties']['id']['enum'] = [ident]
            expanded.append(key(item))
    merged = []
    inverse = []
    for shape, ids in groups.values():
        branch = copy.deepcopy(shape);branch['properties']['id']['enum'] = ids
        merged.append(branch)
        for ident in ids:
            item = copy.deepcopy(shape);item['properties']['id']['enum'] = [ident]
            inverse.append(key(item))
    # anyOf denotes a union: duplicates/order do not affect its accepted set.
    if set(expanded) != set(inverse):
        raise ValueError('Exact citation language equivalence failed')
    citation['anyOf'] = merged
    proof = dict(version=VERSION, original_sha256=hashlib.sha256(key(original).encode()).hexdigest(),
        transported_sha256=hashlib.sha256(key(result).encode()).hexdigest(),
        original_branches=len(branches), transported_branches=len(merged),
        expanded_union_sha256=hashlib.sha256(key(sorted(set(expanded))).encode()).hexdigest(),
        original_bytes=len(json.dumps(original).encode()), transported_bytes=len(json.dumps(result).encode()))
    if proof['transported_bytes'] >= proof['original_bytes']:
        raise ValueError('Recovery requires a substantive exact schema reduction')
    return result, proof


def resolve_compact(root, task):
    from .unity_m_output_recovery import validate_truncation
    root = Path(root);path = root/'unity_m_schema_corrections'/(task['name']+'.json')
    if not path.exists():return None
    value = batch.read(path)
    is_shared = value.get('version') == SHARED_VERSION
    schema, proof = (shared_schema if is_shared else compact_schema)(task['schema'])
    if is_shared and not shared_authorized(root, task):raise ValueError('Restricted shared schema authorization required')
    original = root/'model_calls'/('unity_m_'+task['name'])
    folder = root/'model_calls'/('unity_m_'+task['name']+'_equivalent_schema_01')
    if (value.get('version') not in {VERSION, SHARED_VERSION} or value.get('maximum_new_calls') != 1
            or value.get('original_folder') != str(original) or value.get('correction_folder') != str(folder)
            or value.get('request_sha256') != sha(root/'unity_m_requests'/task['column']/(task['name']+'.json'))
            or value.get('schema_equivalence') != proof or value.get('transport_schema') != schema):
        raise ValueError('Exact equivalent schema recovery binding required')
    for p,d in value['bindings'].items():
        if sha(Path(p)) != d:raise ValueError('Preserved truncation lineage changed')
    validate_truncation(original)
    failed = Path(value['failed_folder']);validate_truncation(failed)
    if failed != original:
        old = batch.read(root/'unity_m_output_corrections'/(task['name']+'.json'))
        if old['correction_folder'] != str(failed) or value['prior_prompts'] != [old['prompt']]:
            raise ValueError('Exact failed correction history required')
    elif value['prior_prompts']:
        raise ValueError('Unexpected prior correction history')
    return folder, value


def recover(root, task, transport):
    from .unity_m_incomplete_recovery import MESSAGE, recover as recover_unknown
    original=Path(root)/'model_calls'/('unity_m_'+task['name'])
    inv=original/'invocation.json'
    if inv.exists() and MESSAGE in batch.read(inv).get('error',''):
        return recover_unknown(root,task,transport)
    from .unity_m_output_recovery import resolve, validate_truncation
    from .unity_m_delivery import delivery
    from .unity_m_judge import exact_json, WINDOW, RESERVE, MARGIN
    from .native_image_cli_probe import rpc_invoke
    root = Path(root)
    if (root/'judgments'/('unity_m_'+task['name']+'.json')).exists():
        raise ValueError('Accepted judgment cannot enter schema recovery')
    existing = resolve_compact(root, task)
    if existing:
        folder, descriptor = existing
        if not (folder/'response.json').exists():
            raise ValueError('Preserve failed equivalent schema attempt; no unchanged retry')
        raw = batch.read(folder/'response.json')
        codex.validate_schema(raw, task['schema'])
        return folder, descriptor, raw
    failed, previous = resolve(root, task)
    invocation = validate_truncation(failed)
    reduced,_ = compact_schema(task['schema'])
    use_shared = shared_authorized(root, task)
    if batch.read(failed/'schema.json') == reduced and not use_shared:
        raise ValueError('Already reduced failed schema needs a new substantive diagnosis; no unchanged retry')
    proof = delivery(root, failed, task, transport, previous, failed_output=True)
    schema, equivalence = (shared_schema if use_shared else compact_schema)(task['schema'])
    if use_shared and len(key(schema).encode()) >= len(key(batch.read(failed/'schema.json')).encode()):
        raise ValueError('Shared repair must substantively reduce the actual failed schema')
    prompt = ('The preceding output failed without a complete judgment. This is one bounded recovery with '
        'an exactly equivalent structured output schema: Citation alternatives with identical constraints '
        'have been merged by id enum. Identical schema subtrees may share local definitions; expanding them restores every original constraint. Every allowed citation and every bound is unchanged. '
        'Use the complete retained original request, frozen criteria, all author sources and all original native images. '
        'Return the complete JSON judgment with concise reasons and sufficient actual citations. '
        'No score or status is prescribed. Do not call tools, summarize evidence, compact context or omit fields. '
        'The full equivalent schema follows:\n'+json.dumps(schema, ensure_ascii=False))
    usage = proof['usage']
    required = usage['input_tokens']+usage['output_tokens']+len(prompt.encode())+len(json.dumps(schema).encode())+RESERVE+MARGIN
    if required > min(WINDOW, usage['window']) or len(prompt.encode()) > 1000000:
        raise ValueError('Equivalent schema recovery exceeds actual retained capacity')
    original = root/'model_calls'/('unity_m_'+task['name'])
    folder = root/'model_calls'/('unity_m_'+task['name']+'_equivalent_schema_01')
    files = [f/n for f in {original, failed} for n in ('prompt.txt','schema.json','invocation.json','rpc_requests.jsonl','rpc_events.jsonl','retained_session.jsonl')]
    if previous:files.append(root/'unity_m_output_corrections'/(task['name']+'.json'))
    descriptor = dict(version=SHARED_VERSION if use_shared else VERSION, maximum_new_calls=1, original_folder=str(original), failed_folder=str(failed),
        correction_folder=str(folder), prompt=prompt, prior_prompts=[previous['prompt']] if previous else [],
        request_sha256=sha(root/'unity_m_requests'/task['column']/(task['name']+'.json')),
        bindings={str(p):sha(p) for p in files}, transport_schema=schema, schema_equivalence=equivalence,
        parent_error='max_output_tokens', required=required, window=usage['window'])
    exact_json(root/'unity_m_schema_corrections'/(task['name']+'.json'), descriptor)
    if folder.exists():raise ValueError('Existing unqualified schema attempt must be preserved')
    raw,_ = rpc_invoke(folder,root,prompt,schema,[],model='gpt-6.1-sol',session=invocation['thread'],context_window=WINDOW)
    codex.validate_schema(raw, task['schema'])
    return folder, descriptor, raw


def submitted_schema(task, correction):
    if correction and correction.get('version') in {VERSION, SHARED_VERSION, 'unity-m-schema-shape-correction.v1'}:
        schema,proof = (shared_schema if correction.get('version')==SHARED_VERSION else compact_schema)(task['schema'])
        if correction['schema_equivalence'] != proof or correction['transport_schema'] != schema:
            raise ValueError('Equivalent schema proof changed')
        return schema
    return task['schema']


NUMERIC_INITIAL_VERSION = 'unity-m-initial-exact-integer-range-schema.v1'


def compact_numeric_schema(original):
    """Exact integer-enum intervals; never fill a gap or widen a citation set."""
    result, citation_proof = compact_schema(original)
    intervals = []
    def visit(value, path):
        if isinstance(value, dict):
            enum = value.get('enum')
            if (value.get('type') == 'integer' and isinstance(enum, list) and len(enum) > 1
                    and all(type(n) is int for n in enum)):
                ordered = sorted(set(enum))
                if ordered[-1]-ordered[0]+1 == len(ordered):
                    # Keep every other constraint, including any tighter bounds.
                    value.pop('enum')
                    value['minimum'] = max(value.get('minimum', ordered[0]), ordered[0])
                    value['maximum'] = min(value.get('maximum', ordered[-1]), ordered[-1])
                    intervals.append(dict(path=path,minimum=ordered[0],maximum=ordered[-1],
                        count=len(ordered),enum_sha256=hashlib.sha256(key(enum).encode()).hexdigest()))
            for name, child in value.items():visit(child,path+'/'+name)
        elif isinstance(value,list):
            for n,child in enumerate(value):visit(child,path+'/'+str(n))
    visit(result,'')
    if not intervals:raise ValueError('Exact contiguous integer ranges required')
    proof=dict(version=NUMERIC_INITIAL_VERSION,citation_equivalence=citation_proof,
        intervals=intervals,original_sha256=hashlib.sha256(key(original).encode()).hexdigest(),
        transported_sha256=hashlib.sha256(key(result).encode()).hexdigest(),
        original_bytes=len(json.dumps(original).encode()),transported_bytes=len(json.dumps(result).encode()))
    if proof['transported_bytes'] >= proof['original_bytes']:
        raise ValueError('Exact integer schema must substantively reduce transport')
    return result,proof


INITIAL_VERSION = 'unity-m-initial-equivalent-citation-schema.v1'
ENDPOINT_CAPACITY_VERSION = 'unity-m-endpoint-schema-capacity-recovery.v1'


def endpoint_numeric_task(root, task):
    if not task.get('bounded_endpoint_packets') or task.get('column') != 'Mechanic':
        return False
    from .unity_m_judge import verify_endpoint_task
    verify_endpoint_task(root, task)
    return True


def endpoint_capacity_schema(root, task):
    """One equivalent schema after actual pre-score capacity failure.

    The original submission and acknowledged runtime remain immutable. This is
    still the first scoring invocation; no failed judgment is retried here.
    """
    from .unity_m_judge import exact_json
    root=Path(root)
    if not endpoint_numeric_task(root, task):raise ValueError('Original Mechanic endpoints required')
    original=root/'unity_m_schema_submissions'/(task['name']+'.json')
    prior=batch.read(original)
    reduced,old_proof=compact_schema(task['schema'])
    if (prior.get('version')!=INITIAL_VERSION or prior.get('transport_schema')!=reduced
            or prior.get('schema_equivalence')!=old_proof
            or prior.get('request_sha256')!=sha(root/'unity_m_requests'/task['column']/(task['name']+'.json'))):
        raise ValueError('Exact preserved initial endpoint schema required')
    path=root/'unity_m_endpoint_schema_capacity'/(task['name']+'.json')
    schema,proof=compact_numeric_schema(task['schema'])
    if path.exists():
        value=batch.read(path)
        if (value.get('version')!=ENDPOINT_CAPACITY_VERSION or value.get('maximum_scoring_calls')!=1
                or value.get('original_submission_sha256')!=sha(original)
                or value.get('schema_equivalence')!=proof or value.get('transport_schema')!=schema):
            raise ValueError('Exact endpoint capacity schema equivalence required')
        for name,digest in value['bindings'].items():
            if sha(Path(name))!=digest:raise ValueError('Preserved endpoint capacity lineage changed')
        return schema
    if (root/'model_calls'/('unity_m_'+task['name'])).exists():
        raise ValueError('Endpoint capacity recovery only before first scoring invocation')
    failures=[]
    for f in sorted((root/'unity_m_judge_failures').glob('*.json')):
        value=batch.read(f)
        if (value.get('column')=='Mechanic'
                and value.get('error')=="ValueError('Measured complete runtime plus final schema exceeds window')"):
            failures.append(f)
    if not failures:raise ValueError('Actual preserved endpoint final-schema capacity failure required')
    transport=root/'unity_m_runtime_transport'/(task['name']+'.json')
    value=batch.read(transport)
    if (value['original_request_sha256']!=sha(root/'unity_m_requests'/task['column']/(task['name']+'.json'))
            or ''.join(value['chunks'])!=task['prompt']):raise ValueError('Same complete runtime required')
    bindings={str(original):sha(original),str(transport):sha(transport),str(failures[-1]):sha(failures[-1])}
    for name in value['chunk_folders']:
        folder=Path(name)
        for item in ('accepted_intake.json','response.json','invocation.json','retained_session.jsonl'):
            source=folder/item;bindings[str(source)]=sha(source)
        if batch.read(folder/'response.json')!={'receipt':'EXACT_RUNTIME_CHUNK_RETAINED'}:
            raise ValueError('Every runtime chunk must already be accepted')
    exact_json(path,dict(version=ENDPOINT_CAPACITY_VERSION,maximum_scoring_calls=1,
        original_submission_sha256=sha(original),schema_equivalence=proof,transport_schema=schema,
        original_schema_still_validates=True,bindings=bindings))
    return schema


def schema_for_task(root, task, correction):
    """Original accepted requests stay unchanged; every new proof is recomputed."""
    if correction and correction.get('version')=='unity-m-unknown-incomplete-shared-schema.v1':
        from .unity_m_incomplete_recovery import resolve
        resolved=resolve(root,task)
        if not resolved or resolved[1]!=correction:raise ValueError('Exact unknown incomplete schema required')
        return correction['transport_schema']
    if correction and correction.get('version')=='unity-m-observed-counterexample-correction.v1':
        parent=resolve_compact(root,task)
        if not parent:raise ValueError('Exact equivalent-schema parent required')
        schema=schema_for_task(root,task,parent[1])
        if correction['transport_schema']!=schema:raise ValueError('Original observed-counterexample schema changed')
        return schema
    if correction and correction.get('version')=='unity-m-direct-observed-counterexample-correction.v1':
        schema=schema_for_task(root,task,None)
        if correction['transport_schema']!=schema:raise ValueError('Original direct counterexample schema changed')
        return schema
    if correction and correction.get('version')=='unity-m-basic-runtime-reference-correction.v1':
        schema=schema_for_task(root,task,None)
        if correction['transport_schema']!=schema:raise ValueError('Original runtime-reference schema changed')
        return schema
    if correction:return submitted_schema(task,correction)
    root=Path(root);path=root/'unity_m_schema_submissions'/(task['name']+'.json')
    recovered=root/'unity_m_endpoint_schema_capacity'/(task['name']+'.json')
    if recovered.exists():return endpoint_capacity_schema(root,task)
    if not path.exists():return task['schema']
    value=batch.read(path)
    version=value.get('version')
    if version==SHARED_INITIAL_VERSION:
        if not shared_authorized(root, task):raise ValueError('Restricted shared initial schema authorization required')
        schema,proof=shared_schema(task['schema'])
    elif version==NUMERIC_INITIAL_VERSION:
        if not task.get('numeric_event_packets') and not endpoint_numeric_task(root,task):raise ValueError('Exact numeric runtime task required')
        schema,proof=compact_numeric_schema(task['schema'])
    else:schema,proof=compact_schema(task['schema'])
    if (version not in {INITIAL_VERSION,NUMERIC_INITIAL_VERSION,SHARED_INITIAL_VERSION} or value.get('maximum_calls')!=1
            or value.get('request_sha256')!=sha(root/'unity_m_requests'/task['column']/(task['name']+'.json'))
            or value.get('schema_equivalence')!=proof or value.get('transport_schema')!=schema):
        raise ValueError('Exact initial schema equivalence/source proof required')
    return schema


def initial_schema(root,task):
    """Use proven schema reduction only before the first physical invocation."""
    from .unity_m_judge import exact_json
    root=Path(root);path=root/'unity_m_schema_submissions'/(task['name']+'.json')
    if path.exists():
        prior=batch.read(path)
        if prior.get('version')==INITIAL_VERSION and task.get('bounded_endpoint_packets'):
            return endpoint_capacity_schema(root,task)
        return schema_for_task(root,task,None)
    if (root/'model_calls'/('unity_m_'+task['name'])).exists():return task['schema']
    if shared_authorized(root, task):
        schema,proof=shared_schema(task['schema'])
        exact_json(path,dict(version=SHARED_INITIAL_VERSION,maximum_calls=1,
            request_sha256=sha(root/'unity_m_requests'/task['column']/(task['name']+'.json')),
            schema_equivalence=proof,transport_schema=schema,original_schema_still_validates=True))
        return schema
    numeric=bool(task.get('numeric_event_packets')) or endpoint_numeric_task(root,task)
    schema,proof=(compact_numeric_schema if numeric else compact_schema)(task['schema'])
    exact_json(path,dict(version=NUMERIC_INITIAL_VERSION if numeric else INITIAL_VERSION,maximum_calls=1,
        request_sha256=sha(root/'unity_m_requests'/task['column']/(task['name']+'.json')),
        schema_equivalence=proof,transport_schema=schema,original_schema_still_validates=True))
    return schema
