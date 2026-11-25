"""One recorded Mechanic correction for source-only alleged runtime bugs.

Original schema/scoring and the failed schema-repair attempt remain immutable.
This is a restricted judge route, never native or general batch admission.
"""
from pathlib import Path
import json
from . import batch, codex
from .protocol import sha

VERSION = 'unity-m-observed-counterexample-correction.v1'
ERROR = 'Basic BUG needs real observed counterexample'
POINTER = 'engineering/unity_m_observed_bug_repair.json'
FILES = {'unity_m_admission.py', 'unity_m_judge.py', 'unity_m_schema_recovery.py',
         'unity_m_shared_schema_repair.py', 'unity_m_output_recovery.py',
         'unity_m_observed_bug_recovery.py'}


def gaps(root, task, raw):
    from .unity_m_delivery import validation_manifest
    from .mechanic_v3 import inspect_references
    manifest = validation_manifest(root, task)
    found = []
    for ident, row in raw['checks'].items():
        for stage, status in [('basic_function', 'BUG'), ('result_outcome', 'CONTRADICTED')]:
            value = row[stage]
            if value['status'] != status:
                continue
            facts = inspect_references(root, manifest, task['rules'], value['evidence'])
            if not value['counterexample'].strip() or not (facts['outcome_times'] or facts['runtime_error_ids']):
                found.append({'check': ident, 'stage': stage})
    return found


def diagnose(root, proto, contract, task, original):
    from . import mechanic_v3_outcome
    from .unity_m_delivery import validation_manifest
    if task['column'] != 'Mechanic':
        raise ValueError('Only the diagnosed recorded Mechanic failure is supported')
    raw = batch.read(original/'response.json')
    codex.validate_schema(raw, task['schema'])
    try:
        mechanic_v3_outcome.evaluate(root, proto, validation_manifest(root, task),
                                   task['rules'], contract, raw, task['specs'])
    except ValueError as error:
        if str(error) != ERROR:
            raise ValueError('Exact original observed-counterexample failure required') from error
    else:
        raise ValueError('A valid judgment must be reused')
    found = gaps(root, task, raw)
    if not found:
        raise ValueError('Actual missing observed counterexample required')
    return found


def require(workspace, identity, column, pointer=None):
    from . import unity_m_admission as admission, unity_m_evidence
    from .unity_m_schema_recovery import resolve_compact
    workspace = Path(workspace).resolve()
    pointer = Path(pointer) if pointer else workspace/POINTER
    reference = batch.read(pointer)
    path = Path(reference['path'])
    if sha(path) != reference['sha256']:
        raise ValueError('Observed-counterexample repair descriptor changed')
    value = batch.read(path)
    if (value.get('version') != VERSION or value.get('identity') != identity
            or value.get('column') != column or column != 'Mechanic'
            or value.get('maximum_new_calls') != 1 or value.get('new_native_calls') != 0):
        raise ValueError('One exact recorded Mechanic counterexample correction required')
    for name, digest in value['bindings'].items():
        if sha(Path(name)) != digest:
            raise ValueError('Original counterexample failure or schema lineage changed')
    current = admission.production()
    before = value['before_production']
    changed = {p for p in before.keys() | current.keys() if before.get(p) != current.get(p)}
    directory = Path(__file__).resolve().parent
    if (current != value['after_production'] or changed != set(value['changed_files'])
            or changed != {str(directory/n) for n in FILES}):
        raise ValueError('Only the exact non-scoring correction dependency delta is admitted')
    for name in changed:
        archive = value['changed_files'][name]
        if name in before:
            if not archive or sha(Path(archive)) != before[name]:
                raise ValueError('Exact archived admitted producer bytes required')
        elif archive is not None:
            raise ValueError('New correction dependencies must be explicit')
    prior = batch.read(Path(value['prior_admission']))
    if prior.get('verification_production') != before:
        raise ValueError('Original complete Unity two-column admission required')
    transition = Path(prior['completed_transition']['path'])
    if sha(transition) != prior['completed_transition']['sha256']:
        raise ValueError('Prior completed transition changed')
    historical = admission.verify_completed_transition(
        workspace, transition, expected_production=before, verification_archives=value['changed_files'])
    if historical['e2e'] != prior['e2e']:
        raise ValueError('Original complete synchronized Unity E2E changed')
    admission._check_regression(value['regression'])
    recorded = workspace/'runs'/identity
    unity_m_evidence.qualify_recorded(recorded)
    root = Path(batch.read(recorded/'unity_m_evidence.json')['root'])
    if str(root) != value['root']:
        raise ValueError('Exact original qualified record required')
    task = batch.read(Path(value['task']))
    original, _ = resolve_compact(root, task)
    if str(original) != value['failed_folder']:
        raise ValueError('Exact immutable equivalent-schema parent required')
    proto = batch.read(root/'input/pilot_rubric.json')
    from .unity_m_judge import contract
    _, cv, _ = contract(workspace, value['case_id'], column)
    if diagnose(root, proto, cv, task, original) != value['reference_gaps']:
        raise ValueError('Counterexample diagnosis changed')
    return dict(restricted=True, identity=identity, column=column, operation='judge',
                new_native_calls=0, descriptor=str(path), sha256=sha(path))


def register(workspace, descriptor):
    from .unity_m_judge import exact_json
    workspace = Path(workspace).resolve()
    path = Path(descriptor).resolve()
    value = batch.read(path)
    target = workspace/POINTER
    # Validate through a temporary engineering pointer; publish only after success.
    candidate = path.parent/'registration_pointer.json'
    exact_json(candidate, {'path': str(path), 'sha256': sha(path)})
    require(workspace, value['identity'], value['column'], candidate)
    exact_json(target, batch.read(candidate))
    return target, value


def resolve(root, task):
    from .unity_m_schema_recovery import resolve_compact, schema_for_task
    root = Path(root)
    path = root/'unity_m_observed_bug_corrections'/(task['name']+'.json')
    if not path.exists():
        return None
    value = batch.read(path)
    original, parent = resolve_compact(root, task)
    folder = root/'model_calls'/('unity_m_'+task['name']+'_observed_bug_correction_01')
    if (value.get('version') != VERSION or value.get('maximum_new_calls') != 1
            or value.get('parent_error') != ERROR
            or value.get('reference_gaps') != gaps(root,task,batch.read(original/'response.json'))
            or value['failed_folder'] != str(original) or value['correction_folder'] != str(folder)
            or value['request_sha256'] != sha(root/'unity_m_requests'/task['column']/(task['name']+'.json'))
            or value['original_folder'] != parent['original_folder']
            or value['prior_prompts'] != parent['prior_prompts']+[parent['prompt']]
            or value['transport_schema'] != schema_for_task(root, task, parent)):
        raise ValueError('Exact bounded observed-counterexample continuation required')
    for name, digest in value['bindings'].items():
        if sha(Path(name)) != digest:
            raise ValueError('Original counterexample response changed')
    if (folder/'response.json').exists():
        if ((folder/'prompt.txt').read_text() != value['prompt']
                or batch.read(folder/'schema.json') != value['transport_schema']
                or batch.read(folder/'invocation.json')['thread'] != batch.read(original/'invocation.json')['thread']):
            raise ValueError('The exact original complete conversation and schema must be retained')
        codex.validate_schema(batch.read(folder/'response.json'), task['schema'])
    return folder, value


def correct(root, proto, contract, task, transport, original, parent, error):
    from .unity_m_judge import exact_json, WINDOW, RESERVE, MARGIN
    from .unity_m_delivery import delivery
    from .unity_m_schema_recovery import schema_for_task
    from .native_image_cli_probe import rpc_invoke
    root = Path(root)
    if str(error) != ERROR or task['column'] != 'Mechanic':
        raise error
    if (root/'judgments'/('unity_m_'+task['name']+'.json')).exists():
        raise ValueError('Accepted judgments cannot be corrected')
    if resolve(root, task):
        raise ValueError('Preserve the existing correction; no unchanged retry')
    found = diagnose(root, proto, contract, task, original)
    proof = delivery(root, original, task, transport, parent)
    schema = schema_for_task(root, task, parent)
    prompt = ('The previous complete response failed the unchanged Mechanic validator: '+ERROR+'. '
        'BUG and CONTRADICTED require actual observed runtime counterexamples in their own evidence. '
        'Source analysis can identify a possible defect but alone does not prove it occurred in this capture. '
        'Actions alone do not prove a gameplay response. Reinspect the complete retained original source and '
        'all original native pixels and runtime evidence. Return a complete independent judgment in the exact '
        'same schema. Choose only statuses and references supported by the actual evidence; no status, score '
        'or reference is prescribed. Do not invent an observation or copy an unsupported previous conclusion. '
        'All frozen criteria, weights and 10/50/100 meanings remain unchanged. No tools, compaction or summary. '
        'Diagnostic fields: '+json.dumps(found, ensure_ascii=False))
    usage = proof['usage']
    required = usage['input_tokens']+usage['output_tokens']+len(prompt.encode())+len(json.dumps(schema).encode())+RESERVE+MARGIN
    if required > min(WINDOW, usage['window']):
        raise ValueError('Observed-counterexample correction exceeds actual retained capacity')
    folder = root/'model_calls'/('unity_m_'+task['name']+'_observed_bug_correction_01')
    descriptor = dict(version=VERSION, maximum_new_calls=1, original_folder=parent['original_folder'],
        failed_folder=str(original), correction_folder=str(folder), prompt=prompt,
        prior_prompts=parent['prior_prompts']+[parent['prompt']], transport_schema=schema,
        request_sha256=sha(root/'unity_m_requests'/task['column']/(task['name']+'.json')),
        parent_error=ERROR, reference_gaps=found, required=required,
        bindings={str(original/n):sha(original/n) for n in
                  ('response.json','prompt.txt','schema.json','invocation.json','retained_session.jsonl')})
    exact_json(root/'unity_m_observed_bug_corrections'/(task['name']+'.json'), descriptor)
    if folder.exists():
        raise ValueError('Existing failed correction must not be retried')
    inv = batch.read(original/'invocation.json')
    raw, _ = rpc_invoke(folder, root, prompt, schema, [], model='gpt-6.1-sol',
                        session=inv['thread'], context_window=WINDOW)
    codex.validate_schema(raw, task['schema'])
    return folder, descriptor, raw
