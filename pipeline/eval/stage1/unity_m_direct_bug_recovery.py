"""Exact G018 recorded Mechanic recovery; never a native bootstrap.

The previous complete native E2E, G018 record/evidence and published Gameness
remain immutable. Only one direct-response counterexample correction is new.
A complete formal Mechanic process and both verified publications are required
before creating a production-wide admission.
"""
from pathlib import Path
from . import batch, unity_m_admission as admission
from .protocol import sha
from .mechanic_v3_runner import exclusive_json

IDENTITY = 'Kimi__G018_portal_freight'
VERSION = 'unity-m-g018-direct-bug-recovery.v1'
POINTER = 'engineering/unity_m_g018_direct_bug_repair.json'
ROOT = IDENTITY+'__recorded_judge_v1_1794069749173137000'
FAILURE = '1794112423484604000.json'
FAILURE_SHA = '77bb725174e54f8e1094390440bc140919bcd16a21c7c539ba893af6fd8b35ab'
SCOPE_SHA = 'f2f01fd3b47755f6f21cfdae31d954f1e655ae02080ba4e76d4c221fbb136863'
FILES = {'unity_m_admission.py', 'unity_m_editor_local_recovery.py',
         'unity_m_output_recovery.py', 'unity_m_schema_recovery.py',
         'unity_m_judge.py', 'unity_m_direct_bug_recovery.py'}


def reference(spec):
    path = Path(spec['path'])
    if path.is_symlink() or sha(path) != spec['sha256']:
        raise ValueError('Immutable direct counterexample recovery reference changed')
    return path


def verify_delta(value, before, current):
    directory = Path(__file__).resolve().parent
    changed = {p for p in before.keys() | current.keys() if before.get(p) != current.get(p)}
    expected = {str(directory/n) for n in FILES}
    if (value.get('before_production') != before or value.get('after_production') != current
            or changed != expected or set(value.get('changed_files', {})) != expected):
        raise ValueError('Exact complete direct counterexample production delta required')
    for name in changed:
        archive = value['changed_files'][name]
        if name in before:
            if not archive or sha(Path(archive)) != before[name]:
                raise ValueError('Exact archived direct counterexample parent bytes required')
        elif archive is not None or Path(name).name != 'unity_m_direct_bug_recovery.py':
            raise ValueError('Only the explicit direct recovery dependency may be new')
    admission._check_regression(value['regression'])
    report = batch.read(reference(value['regression']))
    if report.get('production') != current:
        raise ValueError('Regression must bind the complete current production set')


def qualify(workspace, identity, operation, column, descriptor, *, expected_production=None):
    from . import unity_m_editor_local_recovery as editor
    from . import unity_m_evidence, unity_m_judge as judge
    from .unity_m_output_recovery import DIRECT_BUG_VERSION, verify_direct_bug_authorization
    workspace = Path(workspace).resolve()
    path = Path(descriptor).resolve(); value = batch.read(path)
    if (identity != IDENTITY or operation != 'judge' or column != 'Mechanic'
            or value.get('version') != VERSION or value.get('identity') != IDENTITY
            or value.get('column') != column or value.get('operation') != operation
            or value.get('new_native_calls') != 0 or value.get('maximum_correction_calls') != 1
            or value.get('batch_admitted') is not False or value.get('scoring_changed') is not False):
        raise ValueError('Only exact G018 recorded Mechanic judge recovery is admitted')
    scope = workspace/'scopes/unity_m_original/scope.json'
    if sha(scope) != SCOPE_SHA:
        raise ValueError('Original frozen Unity M scope changed')
    parent_path = reference(value['parent_editor_recovery'])
    parent = batch.read(parent_path)
    before = parent['verification_production']
    # Revalidate the historical descriptor against its own immutable producer;
    # the separate complete delta check below grants current recorded-only use.
    editor.qualify(workspace, IDENTITY, 'judge', parent_path, expected_production=before)
    current = admission.production() if expected_production is None else expected_production
    verify_delta(value, before, current)
    recorded = workspace/'runs'/IDENTITY
    unity_m_evidence.qualify_recorded(recorded)
    pointer = batch.read(recorded/'unity_m_evidence.json')
    root = Path(pointer['root'])
    if root != workspace/'recovery_runs'/ROOT or value.get('root') != str(root):
        raise ValueError('Exact existing qualified G018 evidence attempt required')
    for name, digest in value['bindings'].items():
        if Path(name).is_symlink() or sha(Path(name)) != digest:
            raise ValueError('Preserved G018 request, accepted result or lineage changed: '+name)
    failure = root/'unity_m_judge_failures'/FAILURE
    task_path = root/'unity_m_requests/Mechanic/mechanic_singleton_10.json'
    original = root/'model_calls/unity_m_mechanic_singleton_10'
    required = {scope, recorded/'unity_m_evidence.json', root/'unity_m_judge_producer.json',
                root/'unity_m_requests/Mechanic/plan.json', root/'unity_m_common_request.json',
                root/'unity_m_native_pixel_proof.json', task_path, failure}
    required.update(original/n for n in ('response.json', 'prompt.txt', 'schema.json',
                                       'invocation.json', 'retained_session.jsonl',
                                       'rpc_requests.jsonl', 'rpc_events.jsonl'))
    required.update(root/'judgments'/f'unity_m_mechanic_singleton_{n:02d}.json' for n in range(1,10))
    if not {str(p) for p in required} <= set(value['bindings']) or sha(failure) != FAILURE_SHA:
        raise ValueError('Complete exact G018 parent failure and accepted shard bindings required')
    if (value.get('task') != str(task_path) or value.get('parent_failure') != str(failure)
            or value.get('parent_producer_sha256') != sha(root/'unity_m_judge_producer.json')):
        raise ValueError('Exact G018 task/failure/original producer required')
    authorization = dict(version=DIRECT_BUG_VERSION, workspace=str(workspace), identity=IDENTITY,
        column='Mechanic', case_id='G018_portal_freight', root=str(root), task=str(task_path),
        original_folder=str(original), maximum_new_calls=1, new_native_calls=0,
        production=current, parent_failure=str(failure), bindings=value['bindings'],
        reference_gaps=value['reference_gaps'])
    # Registration and every dispatch must reproduce the actual unchanged validator.
    from .unity_m_observed_bug_recovery import diagnose
    task = batch.read(task_path); proto = batch.read(root/'input/pilot_rubric.json')
    _, contract, _ = judge.contract(workspace, authorization['case_id'], 'Mechanic')
    if diagnose(root, proto, contract, task, original) != value['reference_gaps']:
        raise ValueError('Exact G018 original counterexample diagnosis changed')
    source = batch.read(root/'unity_m_judge_producer.json')
    producer = dict(source, production=current)
    repair = reference(value['judge_repair'])
    rv = batch.read(repair)
    if (rv.get('parent_producer_sha256') != sha(root/'unity_m_judge_producer.json')
            or rv.get('after_producer') != producer
            or rv.get('parent_failure_bindings', {}).get(str(failure)) != FAILURE_SHA):
        raise ValueError('Exact formal judge producer continuation required')
    old_production = source['production']
    changed = {p for p in old_production.keys() | current.keys()
               if old_production.get(p) != current.get(p)}
    if (rv.get('classification') != 'NON_SCORING_TRANSPORT_AND_METADATA_REPAIR'
            or set(rv.get('changed_files', {})) != changed
            or rv.get('regression') != value['regression']):
        raise ValueError('Complete exact formal judge repair delta and regression required')
    for name in changed:
        old = rv['changed_files'][name]
        if name in old_production:
            if not old or sha(Path(old['archive'])) != old_production[name]:
                raise ValueError('Exact original judge producer bytes required')
        elif old is not None:
            raise ValueError('New formal judge recovery dependency must be explicit')
    prior_continuation = root/'unity_m_judge_continuation.json'
    if prior_continuation.exists():
        verify_continuation(prior_continuation, repair, rv, historical=expected_production is not None)
    auth_path = root/'unity_m_direct_observed_authorization.json'
    if auth_path.exists():
        if batch.read(auth_path) != authorization:
            raise ValueError('Immutable registered G018 authorization changed')
        verify_direct_bug_authorization(root, task, expected_production=current)
    return value, authorization


def verify_continuation(path, repair, value, *, historical=False):
    expected = dict(path=str(path), sha256=sha(path))
    if value.get('parent_continuation') == expected:
        return
    # A historical repair may already have produced the immutable first
    # continuation. Bind that exact receipt rather than requiring self-reference.
    executed = dict(repair_path=str(repair), repair_sha256=sha(repair),
                    parent_producer_sha256=value['parent_producer_sha256'],
                    after_producer=value['after_producer'])
    if not historical or batch.read(path) != executed:
        raise ValueError('Exact preserved prior judge continuation required')


def require(workspace, identity, operation, column, pointer=None):
    from .unity_m_resume_context import POINTER as resume_pointer, require as require_resume
    if (Path(workspace)/resume_pointer).exists():
        return require_resume(workspace, identity, operation, column)
    pointer = Path(pointer) if pointer else Path(workspace)/POINTER
    descriptor = reference(batch.read(pointer))
    value, _ = qualify(workspace, identity, operation, column, descriptor)
    return dict(restricted=True, identity=IDENTITY, operation='judge', column='Mechanic',
                new_native_calls=0, descriptor=str(descriptor), sha256=sha(descriptor))


def register(workspace, descriptor):
    from .unity_m_judge import exact_json
    workspace = Path(workspace).resolve(); descriptor = Path(descriptor).resolve()
    value, authorization = qualify(workspace, IDENTITY, 'judge', 'Mechanic', descriptor)
    root = Path(value['root'])
    exact_json(root/'unity_m_direct_observed_authorization.json', authorization)
    exact_json(workspace/POINTER, dict(path=str(descriptor), sha256=sha(descriptor)))
    require(workspace, IDENTITY, 'judge', 'Mechanic')
    return workspace/POINTER, value


def verify_process(process, workspace, judge_repair):
    args = process.get('args', [])
    expected = {'--workspace': str(Path(workspace).resolve()), '--phase': 'unity-m-judge',
                '--ids': IDENTITY, '--column': 'Mechanic', '--judge-repair': str(judge_repair)}
    if (not isinstance(args, list) or len(args) < 4
            or args[1:4] != ['-u', '-m', 'pipeline.eval.stage1.mechanic_v3_cli']
            or process.get('exit_code') != 0
            or not isinstance(process.get('pid'), int) or process['pid'] <= 0
            or process.get('finished', 0) <= process.get('started', 0)
            or any(args.count(k) != 1 or args.index(k) + 1 >= len(args)
                   or args[args.index(k) + 1] != v for k, v in expected.items())
            or '--acceptance-case' in args
            or not any(s.startswith('UNITY_M_COLUMN_PUBLISHED ' + IDENTITY + ' Mechanic ')
                       and s.endswith(' SYNCED') for s in process.get('final_stdout', '').splitlines())):
        raise ValueError('Actual complete formal Mechanic publication/sync process required')


def verify_complete(workspace, descriptor):
    workspace = Path(workspace).resolve(); value = batch.read(descriptor)
    repair = reference(value['repair'])
    qualification, _ = qualify(workspace, IDENTITY, 'judge', 'Mechanic', repair)
    process = batch.read(reference(value['completed_process']))
    verify_process(process, workspace, reference(qualification['judge_repair']))
    root, proof = admission.evidence(workspace, IDENTITY)
    current = admission.production()
    continuations = [root/'unity_m_judge_continuation.json',
                     *sorted((root/'unity_m_judge_continuations').glob('*.json'))]
    matches = [p for p in continuations if p.exists()
               and batch.read(p)['after_producer']['production'] == current
               and batch.read(p)['repair_sha256'] == qualification['judge_repair']['sha256']]
    if len(matches) != 1:
        raise ValueError('Actual current complete producer continuation required')
    task = batch.read(root/'unity_m_requests/Mechanic/mechanic_singleton_10.json')
    from .unity_m_output_recovery import resolve_direct_bug
    resolved = resolve_direct_bug(root, task)
    if not resolved:
        raise ValueError('Real bounded direct counterexample correction required')
    correction_folder, _ = resolved
    judgment = batch.read(root/'judgments/unity_m_mechanic_singleton_10.json')
    if (judgment.get('response_sha256') != sha(correction_folder/'response.json')
            or judgment.get('actual_delivery', {}).get('session_sha256') != sha(correction_folder/'retained_session.jsonl')):
        raise ValueError('Accepted corrected task must use the actual bounded response')
    from .unity_m_judge import publication_path
    published = batch.read(publication_path(workspace, IDENTITY, 'Mechanic'))
    required = [matches[0], reference(qualification['judge_repair']),
                root/'unity_m_direct_observed_authorization.json',
                root/'unity_m_direct_observed_corrections/mechanic_singleton_10.json']
    if any(published.get('bindings', {}).get(str(p)) != sha(p) for p in required):
        raise ValueError('Actual Mechanic publication must bind the current repair and correction')
    # Existing Gameness is independently revalidated, never recalled for admission.
    publication = root/'unity_m_gameness_score.json'
    if str(publication) not in qualification['bindings']:
        raise ValueError('Unchanged already published Gameness result required')
    return qualification, proof, batch.read(matches[0])['after_producer']


def create(workspace, descriptor):
    _, proof, producer = verify_complete(workspace, descriptor)
    value = dict(version=admission.VERSION,
        capability='UNITY_M_MECHANIC_V3_GAMENESS_V4_ORIGINAL_PIXELS',
        verification_production=admission.production(), executed_producer=producer,
        e2e=proof, direct_bug_recovery=dict(path=str(Path(descriptor).resolve()),sha256=sha(descriptor)),
        scoring_unchanged=True, model='gpt-6.1-sol')
    path = admission.admission_path(workspace, value['verification_production'])
    if path.exists():
        if batch.read(path) != value:
            raise ValueError('Immutable completed G018 direct counterexample admission changed')
    else:
        exclusive_json(path, value)
    return path, value
