"""Restricted recorded Unity E2E for reversible shared-schema transport.

The original complete admission, recording, failed requests and producer remain
immutable. This route admits only the named recorded column, never new native
work or unrestricted batch dispatch. Completion still requires normal judges,
original validators, publication and synchronization.
"""
from pathlib import Path
from . import batch
from .protocol import sha

VERSION = 'unity-m-recorded-shared-schema-repair.v1'
FILES = {'unity_m_admission.py', 'unity_m_schema_recovery.py',
         'unity_m_shared_schema_repair.py'}


def _descriptor(workspace, pointer):
    ref = batch.read(pointer)
    path = Path(ref['path'])
    if sha(path) != ref['sha256']:
        raise ValueError('Shared schema repair descriptor changed')
    value = batch.read(path)
    if value.get('version') != VERSION:
        raise ValueError('Recorded shared schema repair version required')
    return path, value


def authorized(root, column):
    root = Path(root).resolve()
    workspace = root.parent.parent
    pointer = workspace/'engineering/unity_m_shared_schema_repair.json'
    if not pointer.exists():
        return False
    path, value = _descriptor(workspace, pointer)
    if value.get('root') != str(root) or column not in value.get('columns', []):
        return False
    for name, digest in value['repair_bindings'].items():
        if sha(Path(name)) != digest:
            raise ValueError('Shared schema repair binding changed')
    authorization = root/'unity_m_shared_schema_authorization.json'
    if not authorization.exists() or batch.read(authorization) != {
            'path': str(path), 'sha256': sha(path)}:
        raise ValueError('Explicit recorded schema authorization required')
    return True


def verify(workspace, path, identity, column):
    from . import unity_m_admission as admission, unity_m_evidence
    from .unity_m_output_recovery import validate_truncation
    workspace = Path(workspace).resolve()
    value = batch.read(path)
    if (value.get('version') != VERSION or value.get('identity') != identity
            or value.get('columns') != ['Mechanic'] or column != 'Mechanic'
            or value.get('maximum_recovery_calls_per_failed_task') != 1
            or value.get('new_native_calls') != 0):
        raise ValueError('One exact recorded Mechanic schema repair required')
    recorded = workspace/'runs'/identity
    unity_m_evidence.qualify_recorded(recorded)
    root = Path(batch.read(recorded/'unity_m_evidence.json')['root'])
    if value.get('root') != str(root):
        raise ValueError('Exact qualified recorded source required')
    for name, digest in value['repair_bindings'].items():
        if sha(Path(name)) != digest:
            raise ValueError('Shared repair immutable parent changed')
    current = admission.production()
    before = value['before_production']
    changed = {p for p in before.keys() | current.keys()
               if before.get(p) != current.get(p)}
    directory = Path(__file__).resolve().parent
    if (current != value['after_production']
            or changed != {str(directory/name) for name in FILES}
            or changed != set(value['changed_files'])):
        raise ValueError('Only exact shared-schema and admission delta allowed')
    for name in changed:
        archive = value['changed_files'][name]
        if name in before:
            if not archive or sha(Path(archive)) != before[name]:
                raise ValueError('Exact archived schema producer required')
        elif archive is not None:
            raise ValueError('New shared schema module must be explicit')
    prior = Path(value['prior_admission']['path'])
    if sha(prior) != value['prior_admission']['sha256']:
        raise ValueError('Prior complete admission changed')
    accepted = batch.read(prior)
    if accepted.get('verification_production') != before:
        raise ValueError('Original admitted complete producer required')
    transition = accepted['completed_transition']
    descriptor = Path(transition['path'])
    if sha(descriptor) != transition['sha256']:
        raise ValueError('Prior actual E2E transition changed')
    historical = admission.verify_completed_transition(
        workspace, descriptor, expected_production=before,
        verification_archives=value['changed_files'])
    if historical['e2e'] != accepted['e2e']:
        raise ValueError('Prior actual complete Unity E2E differs')
    regression = Path(value['regression']['path'])
    if (sha(regression) != value['regression']['sha256']
            or batch.read(regression).get('exit_code') != 0
            or batch.read(regression).get('tests_passed', 0) < 1):
        raise ValueError('Passing targeted shared schema regressions required')
    failed = Path(value['failed_task_folder'])
    invocation = validate_truncation(failed)
    if failed.parent != root/'model_calls' or invocation.get('thread') is None:
        raise ValueError('Exact original failed recorded task required')
    task = batch.read(Path(value['task']))
    from .unity_m_schema_recovery import shared_schema, compact_schema, key
    original, _ = compact_schema(task['schema'])
    shared, proof = shared_schema(task['schema'])
    if (batch.read(failed/'schema.json') != original
            or proof != value['schema_equivalence']
            or len(key(shared).encode()) >= len(key(original).encode())):
        raise ValueError('Substantive exact repeated-node reduction required')
    return value


def register(workspace, descriptor):
    from .unity_m_judge import exact_json
    workspace = Path(workspace).resolve()
    path = Path(descriptor).resolve()
    value = batch.read(path)
    verify(workspace, path, value['identity'], 'Mechanic')
    reference = {'path': str(path), 'sha256': sha(path)}
    exact_json(Path(value['root'])/'unity_m_shared_schema_authorization.json', reference)
    target = workspace/'engineering/unity_m_shared_schema_repair.json'
    exact_json(target, reference)
    return target, value


def require(workspace, identity, column, pointer):
    path, _ = _descriptor(workspace, pointer)
    value = verify(workspace, path, identity, column)
    if not authorized(Path(value['root']), column):
        raise ValueError('Registered recorded shared schema authorization required')
    return dict(restricted=True, identity=identity, column=column,
                operation='judge', new_native_calls=0,
                descriptor=str(path), sha256=sha(path))
