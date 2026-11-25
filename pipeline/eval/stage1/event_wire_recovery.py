"""Source-bound EVENT transport recovery; native captures and accepted calls stay immutable."""
from pathlib import Path
import copy
import shutil
import time

from . import batch, event_wire, sparse_evidence
from .protocol import dump, sha

VERSION = 'whitebox-authorized-event-wire-recovery.v1'
RECEIPT = 'event_wire_recovery.json'


def fingerprints(root):
    return {str(p.relative_to(root)): sha(p) for p in root.rglob('*') if p.is_file()}


def restore_plan_binding(root):
    """Restore only the existing submitted-schema identity handoff for Unity.

    All present-day plan validators run before writing the compatibility receipt.
    Frozen inputs, schemas and the executed plan stay unchanged. An existing
    invalid receipt is evidence of drift and must never be overwritten.
    """
    from . import core12, plan_invocation_identity
    root = Path(root).resolve()
    if batch.plan_engine(root) != 'unity3d':
        return {'status': 'NOT_UNITY'}
    gate = batch.validate_capture_plan(root)
    if gate['valid']:
        return {'status': 'ALREADY_VALID'}
    report = root/plan_invocation_identity.REPORT
    if report.exists():
        raise ValueError('Existing plan identity receipt failed validation: '+str(gate))
    plan_path = root/'sol_plan.json'
    original_sha = sha(plan_path)
    plan = batch.read(plan_path)
    protocol = core12.verify_attempt(root, 'unity3d')
    current = core12.plan_identity(root, protocol, 'unity3d')
    recorded = plan.get('planning_identity')
    if recorded == current or plan_invocation_identity.resolve(root, current, recorded) != recorded:
        raise ValueError('Capture failure lacks a submitted-schema identity handoff: '+str(gate))
    validated = batch.validate_operation_plan(root, copy.deepcopy(plan), 'unity3d', record_validation=False)
    if validated != plan or sha(plan_path) != original_sha:
        raise ValueError('Plan handoff would alter the executed route')
    plan_invocation_identity.resolve(root, current, recorded, write=True)
    bindings = plan_invocation_identity.audit_binding(root)
    restored = batch.validate_capture_plan(root)
    if not restored['valid']:
        raise ValueError('Restored invocation handoff still fails plan validation: '+str(restored))
    receipt = {'status': 'RESTORED_SUBMITTED_SCHEMA_BINDING', 'before': gate, 'after': restored,
        'plan_sha256': original_sha, 'bindings': bindings, 'model_calls_added': 0,
        'plan_changed': False, 'scoring_semantics_changed': False}
    dump(root/'event_wire_plan_handoff.json', receipt)
    return receipt


def static_source_origin(root):
    """Keep accepted static invocation paths bound to their original root."""
    root = Path(root).resolve()
    visited = set()
    while (root/RECEIPT).is_file():
        if root in visited:
            raise ValueError('Cyclic EVENT static source lineage')
        visited.add(root)
        receipt = verify(root)
        parent = Path(receipt['parent_attempt']).resolve()
        if parent in visited:
            raise ValueError('Cyclic EVENT static source lineage')
        batch.verify_inputs(root)
        for name in ('input_manifest.json', 'input/pilot_rubric.json', 'static_existence.json'):
            if name not in receipt['parent_bindings'] or sha(root/name) != receipt['parent_bindings'][name]:
                raise ValueError('EVENT static handoff changed frozen artifact: '+name)
        root = parent
    return root


def native_source_origin(root):
    """Resolve an immutable EVENT copy to its original native recording root.

    Absolute paths in genuine native receipts must retain their original meaning.
    Every recovery edge is verified, and the executed plan, input manifest and
    complete native/input file sets must still match the frozen parent copy.
    The caller then runs the original native acceptance verifier at the origin.
    """
    root = Path(root).resolve()
    visited = set()
    while (root/RECEIPT).is_file():
        if root in visited:
            raise ValueError('Cyclic EVENT native source lineage')
        visited.add(root)
        receipt = verify(root)
        parent = Path(receipt['parent_attempt']).resolve()
        if parent in visited:
            raise ValueError('Cyclic EVENT native source lineage')
        batch.verify_inputs(root)
        bindings = receipt['parent_bindings']
        for name in ('input_manifest.json', 'sol_plan.json', 'runtime/multisession_sources.json'):
            if name not in bindings or sha(root/name) != bindings[name]:
                raise ValueError('EVENT native handoff changed frozen identity: '+name)
        for prefix in ('input', 'runtime'):
            expected = {name for name in bindings if name.startswith(prefix+'/')}
            actual = {str(p.relative_to(root)) for p in (root/prefix).rglob('*') if p.is_file()}
            if actual != expected:
                # A controller projection may have been persisted after recording.
                # It is not native source: every frozen member must remain, and
                # the sole extra must equal a fresh projection of the SHA-bound
                # original admission. Unknown or altered files still fail.
                extra = {'runtime/import_result.json'}
                if prefix != 'runtime' or actual != expected | extra or extra <= expected:
                    raise ValueError('EVENT native handoff changed frozen file set: '+prefix)
                from .controller_import_source import projection
                if batch.read(root/'runtime/import_result.json') != projection(root):
                    raise ValueError('EVENT controller import projection changed')
        root = parent
    return root


def prepare(source, target, *, authorization_path, encoding=event_wire.VERSION, singleton=False):
    if type(singleton) is not bool:
        raise ValueError('EVENT singleton partition opt-in must be boolean')
    if encoding not in {event_wire.VERSION, event_wire.NUMERIC_VERSION}:
        raise ValueError('Unknown EVENT recovery encoding')
    source, target = Path(source).resolve(), Path(target).resolve()
    authorization_path = Path(authorization_path).resolve()
    authorization = batch.read(authorization_path)
    if (authorization.get('value') != event_wire.ROW_POLICY_VERSION
            or not authorization.get('authorization') or authorization.get('score_semantics_changed') is not False):
        raise ValueError('Explicit global EVENT original-row authorization required')
    if (source == target or source.parent != target.parent or target.exists()
            or (source/'scores.json').exists()):
        raise ValueError('Existing attempt/result protected')
    batch.verify_inputs(source)
    batch.verify_runtime_sources(source)
    old = batch.read(source/'evidence_manifest.json')
    if not old.get('evidence_sets') and not singleton:
        raise ValueError('Undelivered capture requires explicit exhaustive singleton preparation')
    if old.get('judge_transport_partition'):
        raise ValueError('A separately frozen judge partition requires explicit context review')
    accepted = {p.stem: sha(p) for p in (source/'judgments').glob('evidence_*.json')}
    for folder in (source/'model_calls').iterdir():
        if folder.name.startswith('evidence_') and folder.name not in accepted:
            raise ValueError('Failed dynamic call cannot be silently renamed/retried: '+folder.name)
    bindings = fingerprints(source)
    shutil.copytree(source, target, symlinks=True)
    history = target/'preparation_history'/'authorized_event_wire_parent'
    history.mkdir(parents=True, exist_ok=False)
    for name in ('attempt_manifest.json','evidence_manifest.json','status.json','harness_error.json',
                 'error.json','endpoint_partial_recovery.json','partial_judge_receipt.json',
                 'endpoint_partial_prepared.json','native_clock_binding.json'):
        path = target/name
        if path.is_file():
            shutil.move(str(path), str(history/name))
    protocol = batch.read(target/'input/pilot_rubric.json')
    batch.write_attempt_manifest(target,batch.read(target/'input_manifest.json')['entry'],
        protocol['runtime_budget'],previous_attempt=source,phase='authorized_event_wire_recovery')
    manifest = copy.deepcopy(old)
    manifest[event_wire.FIELD] = encoding
    manifest[event_wire.ROW_POLICY_FIELD] = event_wire.ROW_POLICY_VERSION
    if singleton:
        from .endpoint_judge_partition import FIELD, partition
        if old.get('evidence_sets') or type(singleton) is not bool:
            raise ValueError('Cannot repartition an existing delivered context')
        manifest[FIELD] = partition(protocol)
    # Existing accepted contexts retain their exact partition and transport.
    manifest = sparse_evidence.deliver(target,protocol,manifest,checkpoint=True)
    for name in accepted:
        # No added evidence can silently change what an inherited accepted response saw.
        preserved = copy.deepcopy(old['evidence_sets'][name])
        preserved.update({key: old.get(key) for key in event_wire.POLICY_FIELDS})
        manifest['evidence_sets'][name] = preserved
    if (source/'native_clock_binding.json').is_file():
        from . import native_clock_binding
        native_clock_binding.declare(target)
        manifest = native_clock_binding.apply(target,manifest)
    dump(target/'evidence_manifest.json',manifest)
    dump(target/RECEIPT,{'version':VERSION,'encoding':encoding,'singleton':singleton,'at':time.time(),'parent_attempt':str(source),
        'parent_bindings':bindings,'authorization_path':str(authorization_path),
        'authorization_sha256':sha(authorization_path),'manifest_sha256':sha(target/'evidence_manifest.json'),
        'preserved_accepted_shards':accepted,'recordings_added':0,'counter_reset':False,
        'raw_evidence_changed':False,'scoring_semantics_changed':False,
        'substantive_change':'Exact EVENT wire plus explicitly authorized original-row policy; unchanged byte cap and full physical context. Old accepted tasks retain their exact prior transports.'})
    batch.trace_summary(target)
    verify(target)
    restore_plan_binding(target)
    validation = batch.validate_capture_bundle(target,manifest,protocol)
    dump(target/'validation_history/capture_bundle_validation.json',validation)
    dump(target/'authorized_event_wire_prepared.json',{'manifest_sha256':sha(target/'evidence_manifest.json'),
        'capture_valid':validation['valid'],'preserved_accepted_shards':list(accepted),
        'deliverable_shards':[n for n,s in manifest['evidence_sets'].items() if 'transport_blocked' not in s],
        'blocked_shards':{n:s['transport_blocked'] for n,s in manifest['evidence_sets'].items() if 'transport_blocked' in s}})
    return target


def verify(target):
    target = Path(target).resolve()
    receipt = batch.read(target/RECEIPT)
    source = Path(receipt['parent_attempt']).resolve()
    if (receipt.get('version') != VERSION or source == target or source.parent != target.parent
            or receipt.get('counter_reset') is not False or receipt.get('recordings_added') != 0
            or receipt.get('scoring_semantics_changed') is not False):
        raise ValueError('Invalid EVENT recovery lineage')
    if sha(Path(receipt['authorization_path'])) != receipt['authorization_sha256']:
        raise ValueError('EVENT row authorization changed')
    if sha(target/'evidence_manifest.json') != receipt['manifest_sha256']:
        raise ValueError('EVENT recovery reviewed manifest changed')
    for relative,digest in receipt['parent_bindings'].items():
        parent = (source/relative).resolve()
        if not parent.is_relative_to(source) or sha(parent) != digest:
            raise ValueError('EVENT parent source changed: '+relative)
        if relative.startswith(('runtime/','input/','model_calls/')) and sha(target/relative) != digest:
            raise ValueError('EVENT recovery frozen input/real capture/old model call changed: '+relative)
    parent_manifest = batch.read(source/'evidence_manifest.json')
    manifest = batch.read(target/'evidence_manifest.json')
    if manifest.get(event_wire.FIELD) != receipt.get('encoding', event_wire.VERSION):
        raise ValueError('EVENT recovery encoding changed')
    if not event_wire.extended_rows(manifest):
        raise ValueError('Missing authorized EVENT policy')
    from .frame_budget import tasks
    protocol = batch.read(target/'input/pilot_rubric.json')
    if receipt.get('singleton', False):
        from .endpoint_judge_partition import FIELD, partition
        if parent_manifest.get('evidence_sets'):
            raise ValueError('Repartitioned an existing delivered context')
        frozen = partition(protocol)
        if manifest.get(FIELD) != frozen:
            raise ValueError('EVENT recovery changed exhaustive singleton criteria')
        parent_manifest = {**parent_manifest,
            'evidence_frame_policy': manifest['evidence_frame_policy'],
            'evidence_sets': {name: {'criterion_ids': ids} for name, ids in frozen['shards'].items()}}
    if tasks(protocol,parent_manifest) != tasks(protocol,manifest):
        raise ValueError('EVENT recovery changed frozen judge tasks')
    for name in receipt['preserved_accepted_shards']:
        expected = copy.deepcopy(parent_manifest['evidence_sets'][name])
        expected.update({key:parent_manifest.get(key) for key in event_wire.POLICY_FIELDS})
        if manifest['evidence_sets'][name] != expected:
            raise ValueError('Accepted original delivery context changed: '+name)
        if batch.read(target/'judgments'/f'{name}.json')['raw'] != batch.read(source/'judgments'/f'{name}.json')['raw']:
            raise ValueError('Inherited accepted response changed: '+name)
    attempt = batch.read(target/'attempt_manifest.json')
    if attempt['attempt_id'] != target.name or attempt['previous_attempt'] != str(source):
        raise ValueError('EVENT recovery identity mismatch')
    return receipt
