"""One exact-schema recovery for an actual unknown incomplete Gameness turn.

The diagnostic remains unknown. No retry of a complete response is permitted.
The original complete source/native context and frozen validators are retained.
"""
from pathlib import Path
import json
from . import batch, codex
from .protocol import sha

VERSION = 'unity-m-unknown-incomplete-shared-schema.v1'
POINTER = 'engineering/unity_m_incomplete_repair.json'
LABEL_POINTER = 'engineering/unity_m_prepared_label_repair.json'
MESSAGE = 'Incomplete response returned, reason: unknown'
FILES = {'unity_m_admission.py', 'unity_m_schema_recovery.py',
         'unity_m_output_recovery.py', 'unity_m_delivery.py',
         'unity_m_incomplete_recovery.py', 'unity_m_judge.py', 'unity_postexit_cleanup.py'}


def validate_unknown(folder):
    folder = Path(folder)
    if (folder/'response.json').exists():
        raise ValueError('Complete responses cannot enter unknown incomplete recovery')
    inv = batch.read(folder/'invocation.json')
    events = [json.loads(line) for line in (folder/'rpc_events.jsonl').read_text().splitlines() if line.strip()]
    ends = [v['params'] for v in events if v.get('method') == 'turn/completed'
            and v.get('params', {}).get('turn', {}).get('id') == inv.get('turn')]
    if (inv.get('status') != 'HARNESS_ERROR' or len(ends) != 1
            or ends[0].get('threadId') != inv.get('thread')
            or ends[0]['turn'].get('status') != 'failed'
            or ends[0]['turn'].get('error', {}).get('message') != MESSAGE):
        raise ValueError('Exact actual unknown incomplete turn required')
    return inv


def validate_failed(folder):
    inv = batch.read(Path(folder)/'invocation.json')
    if MESSAGE in inv.get('error', ''):
        return validate_unknown(folder)
    from .unity_m_output_recovery import validate_truncation
    return validate_truncation(folder)


def _reference(workspace, pointer=None):
    pointer = Path(pointer) if pointer else Path(workspace)/POINTER
    ref = batch.read(pointer)
    continuation = Path(workspace)/LABEL_POINTER
    if pointer.resolve() == (Path(workspace)/POINTER).resolve() and continuation.exists():
        next_ref = batch.read(continuation)
        candidate = Path(next_ref['path'])
        if sha(candidate) != next_ref['sha256']:
            raise ValueError('Prepared label continuation descriptor changed')
        parent = batch.read(candidate).get('prepared_label_parent', {})
        if parent != {'pointer_sha256': sha(pointer), 'descriptor': ref}:
            raise ValueError('Exact immutable restricted parent pointer required')
        ref = next_ref
    path = Path(ref['path'])
    if sha(path) != ref['sha256']:
        raise ValueError('Unknown incomplete repair descriptor changed')
    return path, batch.read(path)


def authorized(root, column):
    root = Path(root).resolve(); workspace = root.parent.parent
    pointer = workspace/POINTER
    if not pointer.exists():
        return False
    path, value = _reference(workspace)
    if value.get('root') != str(root) or column != value.get('column') or column != 'Gameness':
        return False
    for name, digest in value['bindings'].items():
        if sha(Path(name)) != digest:
            raise ValueError('Unknown failure or completed parent bindings changed')
    auth = root/('unity_m_prepared_label_authorization.json' if value.get('prepared_label_parent') else 'unity_m_incomplete_authorization.json')
    if not auth.exists() or batch.read(auth) != {'path': str(path), 'sha256': sha(path)}:
        raise ValueError('Explicit exact recorded incomplete recovery authorization required')
    return True


def require(workspace, identity, column, pointer=None, *, expected_production=None):
    from . import unity_m_admission as admission
    from .unity_m_schema_recovery import shared_schema, key
    workspace = Path(workspace).resolve()
    path, value = _reference(workspace, pointer)
    if (value.get('version') != VERSION or value.get('identity') != identity
            or column != 'Gameness' or value.get('column') != column
            or value.get('maximum_recovery_calls_per_failed_task') != 1
            or value.get('new_native_calls') != 0):
        raise ValueError('Restricted recorded Gameness unknown incomplete route required')
    for name, digest in value['bindings'].items():
        if sha(Path(name)) != digest:
            raise ValueError('Exact incomplete failure and parent proof changed')
    if value.get('prepared_label_parent'):
        parent_ref = value['prepared_label_parent']
        original_pointer = workspace/POINTER
        if parent_ref != {'pointer_sha256': sha(original_pointer), 'descriptor': batch.read(original_pointer)}:
            raise ValueError('Immutable previous restricted repair required')
        previous = batch.read(Path(parent_ref['descriptor']['path']))
        if sha(Path(parent_ref['descriptor']['path'])) != parent_ref['descriptor']['sha256']:
            raise ValueError('Previous restricted descriptor changed')
        for field in ('before_production','identity','column','root','task','failed_folder','completed_mechanic_proof'):
            if value[field] != previous[field]:
                raise ValueError('Prepared request continuation changed original recovery: '+field)
        if any(value['bindings'].get(p) != digest for p,digest in previous['bindings'].items()):
            raise ValueError('All previous failure bindings must survive')
        from .unity_m_judge import preserve_prepared_request
        requests = value.get('preserved_request_bindings', {})
        root = Path(value['root']); plan = batch.read(root/'unity_m_requests/Gameness/plan.json')
        expected = {str(root/'unity_m_requests/Gameness'/(n+'.json')) for n in plan['task_names']}
        expected |= {str(root/'unity_m_requests/Gameness/plan.json'),str(root/'unity_m_common_request.json')}
        if set(requests) != expected or any(sha(Path(p)) != d or value['bindings'].get(p) != d for p,d in requests.items()):
            raise ValueError('Complete exact prepared request set required')
        archives = value['previous_restricted_archives']
        previous_after = previous['after_production']; after = value['after_production']
        delta = {p for p in previous_after.keys() | after.keys() if previous_after.get(p) != after.get(p)}
        if set(archives) != delta or {Path(p).name for p in delta} != {'unity_m_judge.py','unity_m_incomplete_recovery.py'}:
            raise ValueError('Only exact prepared label gate continuation permitted')
        if any(sha(Path(archives[p])) != previous_after[p] for p in delta):
            raise ValueError('Exact previous restricted production bytes required')
    before = value['before_production']
    current = admission.production() if expected_production is None else expected_production
    changed = {p for p in before.keys() | current.keys() if before.get(p) != current.get(p)}
    directory = Path(__file__).resolve().parent
    if (current != value['after_production'] or changed != set(value['changed_files'])
            or changed != {str(directory/n) for n in FILES}):
        raise ValueError('Exact bounded incomplete schema delta required')
    for name in changed:
        old = value['changed_files'][name]
        if name in before:
            if not old or sha(Path(old)) != before[name]:
                raise ValueError('Exact archived previous producer bytes required')
        elif old is not None:
            raise ValueError('New dependency must be explicit')
    parent = batch.read(Path(value['parent_mechanic_repair']))
    if parent['after_production'] != before:
        raise ValueError('Previous actual complete Mechanic producer required')
    prior = batch.read(Path(parent['prior_admission']))
    historical = admission.verify_completed_transition(workspace,
        Path(prior['completed_transition']['path']), expected_production=parent['before_production'],
        verification_archives=parent['changed_files'])
    if historical['e2e'] != prior['e2e']:
        raise ValueError('Original complete Unity two-column E2E changed')
    admission._check_regression(value['regression'])
    _, proof = admission.evidence(workspace, identity, selected_columns=('Mechanic',))
    if proof != value['completed_mechanic_proof']:
        raise ValueError('Completed current-parent Mechanic full-source/pixel E2E changed')
    root = Path(batch.read(workspace/'runs'/identity/'unity_m_evidence.json')['root'])
    failed = Path(value['failed_folder']); validate_unknown(failed)
    task_path = Path(value['task']); task = batch.read(task_path)
    if (value['root'] != str(root) or task_path != root/'unity_m_requests/Gameness'/(task['name']+'.json')
            or failed != root/'model_calls'/('unity_m_'+task['name'])):
        raise ValueError('Exact original failed Gameness task required')
    schema, equivalence = shared_schema(task['schema'])
    if (value['schema_equivalence'] != equivalence
            or len(key(schema).encode()) >= len(key(batch.read(failed/'schema.json')).encode())):
        raise ValueError('Substantive exactly reversible schema reduction required')
    return dict(restricted=True, identity=identity, column=column, operation='judge',
                descriptor=str(path), sha256=sha(path), new_native_calls=0)


def register(workspace, descriptor):
    from .unity_m_judge import exact_json
    descriptor = Path(descriptor).resolve(); value = batch.read(descriptor)
    reference = {'path': str(descriptor), 'sha256': sha(descriptor)}
    # The pointer is not installed until the descriptor has been fully checked.
    import tempfile
    with tempfile.TemporaryDirectory(prefix='unity-incomplete-register-') as temp:
        pointer = Path(temp)/'reference.json'
        pointer.write_text(json.dumps(reference))
        require(workspace, value['identity'], value['column'], pointer)
    continuation = bool(value.get('prepared_label_parent'))
    auth = 'unity_m_prepared_label_authorization.json' if continuation else 'unity_m_incomplete_authorization.json'
    exact_json(Path(value['root'])/auth, reference)
    target = Path(workspace)/(LABEL_POINTER if continuation else POINTER)
    exact_json(target, reference)
    return target, value


def resolve(root, task):
    root = Path(root); path = root/'unity_m_incomplete_corrections'/(task['name']+'.json')
    if not path.exists():
        return None
    from .unity_m_schema_recovery import shared_schema
    value = batch.read(path)
    original = root/'model_calls'/('unity_m_'+task['name'])
    folder = root/'model_calls'/('unity_m_'+task['name']+'_unknown_shared_schema_01')
    schema, proof = shared_schema(task['schema'])
    if (not authorized(root, task['column']) or value.get('version') != VERSION
            or value.get('maximum_new_calls') != 1 or value['parent_error'] != MESSAGE
            or value['original_folder'] != str(original) or value['correction_folder'] != str(folder)
            or value['request_sha256'] != sha(root/'unity_m_requests'/task['column']/(task['name']+'.json'))
            or value['transport_schema'] != schema or value['schema_equivalence'] != proof
            or value.get('prior_prompts') != []):
        raise ValueError('Exact unknown incomplete continuation required')
    for name, digest in value['bindings'].items():
        if sha(Path(name)) != digest:
            raise ValueError('Original unknown incomplete request changed')
    validate_unknown(original)
    if (folder/'response.json').exists():
        if ((folder/'prompt.txt').read_text() != value['prompt']
                or batch.read(folder/'schema.json') != schema
                or batch.read(folder/'invocation.json')['thread'] != batch.read(original/'invocation.json')['thread']):
            raise ValueError('Same retained conversation and exact schema required')
        codex.validate_schema(batch.read(folder/'response.json'), task['schema'])
    return folder, value


def recover(root, task, transport):
    from .unity_m_judge import exact_json, WINDOW, RESERVE, MARGIN
    from .unity_m_delivery import delivery
    from .unity_m_schema_recovery import shared_schema, key
    from .native_image_cli_probe import rpc_invoke
    root = Path(root)
    if not authorized(root, task['column']):
        raise ValueError('Restricted exact recorded unknown incomplete authorization required')
    if (root/'judgments'/('unity_m_'+task['name']+'.json')).exists():
        raise ValueError('Accepted judgment cannot enter recovery')
    if resolve(root, task):
        raise ValueError('Preserve attempted unknown recovery; no unchanged retry')
    original = root/'model_calls'/('unity_m_'+task['name']); inv = validate_unknown(original)
    proof = delivery(root, original, task, transport, failed_output=True)
    schema, equivalence = shared_schema(task['schema'])
    if len(key(schema).encode()) >= len(key(batch.read(original/'schema.json')).encode()):
        raise ValueError('Substantive reduction of actual failed schema required')
    prompt = ('The preceding turn returned no complete judgment: incomplete response, reason unknown. '
        'This is one bounded recovery using an exactly equivalent structured output schema. Identical '
        'schema subtrees share local definitions; expansion restores every original constraint. Citation '
        'alternatives differing only by their identity enum are merged without changing any allowed citation. '
        'Use the retained complete original request, frozen criteria, all original author sources and all '
        'native pixels. Return the complete independent JSON judgment with concise reasons and actual '
        'evidence citations under the schema below. No status or score is prescribed. Do not call tools, '
        'summarize or compact context, omit fields, or repeat sources/images.\n'+json.dumps(schema, ensure_ascii=False))
    usage = proof['usage']; required = usage['input_tokens']+usage['output_tokens']+len(prompt.encode())+len(json.dumps(schema).encode())+RESERVE+MARGIN
    if required > min(WINDOW, usage['window']) or len(prompt.encode()) > 1000000:
        raise ValueError('Unknown incomplete recovery exceeds actual retained capacity')
    folder = root/'model_calls'/('unity_m_'+task['name']+'_unknown_shared_schema_01')
    value = dict(version=VERSION, maximum_new_calls=1, parent_error=MESSAGE,
        original_folder=str(original), correction_folder=str(folder), prior_prompts=[], prompt=prompt,
        request_sha256=sha(root/'unity_m_requests'/task['column']/(task['name']+'.json')),
        transport_schema=schema, schema_equivalence=equivalence, required=required, window=usage['window'],
        bindings={str(original/n):sha(original/n) for n in ('prompt.txt','schema.json','invocation.json',
                  'rpc_requests.jsonl','rpc_events.jsonl','retained_session.jsonl')})
    exact_json(root/'unity_m_incomplete_corrections'/(task['name']+'.json'), value)
    if folder.exists():
        raise ValueError('Existing unknown recovery cannot be retried')
    raw, _ = rpc_invoke(folder, root, prompt, schema, [], model='gpt-6.1-sol', session=inv['thread'], context_window=WINDOW)
    codex.validate_schema(raw, task['schema'])
    return folder, value, raw
