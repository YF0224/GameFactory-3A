"""Prepare an explicit, parent-bound checkpoint; never publish partial judgments."""
from pathlib import Path
import copy
import shutil
import time

from . import batch, sparse_evidence
from .endpoint_judge_partition import partial_gate
from .protocol import dump, sha

VERSION = 'unity-endpoint-partial-recovery.v1'


def _event_authorization(path):
    """An explicit, immutable authorization, never inferred from legacy recovery."""
    from . import event_wire
    path = Path(path).resolve()
    record = batch.read(path)
    if (record.get('field') != event_wire.ROW_POLICY_FIELD
            or record.get('value') != event_wire.ROW_POLICY_VERSION
            or not isinstance(record.get('authorization'), str)
            or not record['authorization'].strip()
            or record.get('score_semantics_changed') is not False
            or record.get('original_delivery_immutable') is not True):
        raise ValueError('Explicit EVENT original-row authorization required')
    return {'path': str(path), 'sha256': sha(path)}


def _verify_event_policy(target, receipt):
    from . import event_wire
    saved = receipt.get('event_original_row_authorization')
    manifest = batch.read(target/'evidence_manifest.json')
    if saved is None:
        if event_wire.extended_rows(manifest):
            raise ValueError('Extended EVENT checkpoint missing explicit authorization')
        return
    if (not isinstance(saved, dict) or set(saved) != {'path', 'sha256'}
            or _event_authorization(saved['path']) != saved
            or not event_wire.extended_rows(manifest)
            or sha(target/'evidence_manifest.json') != receipt.get('reviewed_manifest_sha256')):
        raise ValueError('Authorized EVENT checkpoint policy/source changed')
    from .endpoint_judge_partition import FIELD, partition
    if manifest.get(FIELD) != partition(batch.read(target/'input/pilot_rubric.json')):
        raise ValueError('Authorized EVENT checkpoint changed exhaustive criteria')


def prepare(source, target, *, authorization, event_authorization_path=None):
    source, target = Path(source).resolve(), Path(target).resolve()
    if not authorization.strip() or target.parent != source.parent or source == target:
        raise ValueError('Partial recovery requires explicit authorization and the same recovery scope')
    if target.exists() or (source/'scores.json').exists():
        raise ValueError('Existing attempt/result protected')
    batch.verify_inputs(source)
    batch.verify_runtime_sources(source)
    original = batch.read(source/'evidence_manifest.json')
    if original.get('evidence_sets'):
        raise ValueError('Do not replace an existing delivered context; use exact-context recovery')
    # Do not hide or retry pre-existing dynamic calls under singleton names.
    if any(p.name.startswith('evidence_') for p in (source/'model_calls').iterdir()):
        raise ValueError('Existing runtime judge invocation requires explicit lineage review')
    event_authorization = (_event_authorization(event_authorization_path)
                           if event_authorization_path is not None else None)
    bindings = {str(p.relative_to(source)): sha(p) for p in source.rglob('*') if p.is_file()}
    shutil.copytree(source, target)
    history = target/'preparation_history'/'parent_stage'
    history.mkdir(parents=True)
    for name in ('status.json', 'error.json', 'harness_error.json', 'attempt_manifest.json', 'evidence_manifest.json'):
        path = target/name
        if path.is_file():
            shutil.move(str(path), str(history/name))
    dump(target/'endpoint_partial_recovery.json', {
        'version': VERSION, 'at': time.time(), 'authorization': authorization,
        'parent_attempt': str(source), 'parent_bindings': bindings,
        'substantive_change': 'Exhaustive singleton endpoint transport checkpoints; unchanged physical budgets, native frames, rubric, prompt and citation validation. Only otherwise-valid deliverable tasks may run; incomplete tasks cannot score.',
        'counter_reset': False, 'recordings_added': 0,
        'static_calls_added': 0, 'score_eligible': False})
    protocol = batch.read(target/'input/pilot_rubric.json')
    batch.write_attempt_manifest(target, batch.read(target/'input_manifest.json')['entry'],
        protocol['runtime_budget'], previous_attempt=source, phase='endpoint_partial_checkpoint')
    configured = copy.deepcopy(original)
    if event_authorization is not None:
        from . import event_wire
        configured[event_wire.FIELD] = event_wire.VERSION
        configured[event_wire.ROW_POLICY_FIELD] = event_wire.ROW_POLICY_VERSION
    manifest = sparse_evidence.deliver(target, protocol, configured, checkpoint=True)
    dump(target/'evidence_manifest.json', manifest)
    if event_authorization is not None:
        receipt = batch.read(target/'endpoint_partial_recovery.json')
        receipt.update(event_original_row_authorization=event_authorization,
                       reviewed_manifest_sha256=sha(target/'evidence_manifest.json'),
                       substantive_change='Exhaustive singleton checkpoints with exactly reversible EVENT wire and separately authorized original-row policy. Complete contexts, physical citations, 160000 EVENT wire bytes and all scoring rules unchanged; partial results never score.')
        dump(target/'endpoint_partial_recovery.json', receipt)
    batch.trace_summary(target)
    validation = batch.validate_capture_bundle(target, manifest, protocol)
    dump(target/'validation_history/capture_bundle_validation.json', validation)
    eligible = partial_gate(target, protocol, manifest, validation)
    batch.verify_inputs(target)
    batch.verify_runtime_sources(target)
    if any(sha(source/name) != digest for name, digest in bindings.items()):
        raise ValueError('Original recovery source changed')
    dump(target/'endpoint_partial_prepared.json', {
        'version': VERSION, 'eligible_shards': eligible,
        'blocked_shards': [name for name in manifest['evidence_sets'] if name not in eligible],
        'manifest_sha256': sha(target/'evidence_manifest.json'),
        'parent_files_unchanged': True, 'full_capture_valid': False,
        'score_created': False})
    return eligible


def verify(target):
    target = Path(target).resolve()
    receipt = batch.read(target/'endpoint_partial_recovery.json')
    source = Path(receipt['parent_attempt']).resolve()
    if (receipt.get('version') != VERSION or source == target or source.parent != target.parent
            or receipt.get('counter_reset') is not False or receipt.get('recordings_added') != 0
            or receipt.get('score_eligible') is not False):
        raise ValueError('Invalid endpoint checkpoint lineage')
    mutable = {'status.json', 'error.json', 'harness_error.json', 'attempt_manifest.json',
               'evidence_manifest.json', 'trace_summary.json'}
    for relative, digest in receipt['parent_bindings'].items():
        original = (source/relative).resolve()
        copied = (target/relative).resolve()
        if not original.is_relative_to(source) or not copied.is_relative_to(target) or sha(original) != digest:
            raise ValueError('Endpoint checkpoint parent source changed: '+relative)
        if relative not in mutable and not relative.startswith(('validation_history/', 'delivery/')):
            if sha(copied) != digest:
                raise ValueError('Endpoint checkpoint frozen input/accepted response changed: '+relative)
    manifest = batch.read(target/'attempt_manifest.json')
    if manifest['attempt_id'] != target.name or manifest['previous_attempt'] != str(source):
        raise ValueError('Endpoint checkpoint attempt provenance mismatch')
    _verify_event_policy(target, receipt)
    return receipt


def resume_missing_attempt_manifest(target, *, failure_path):
    """Repair only an interrupted pre-call handoff, retaining that exact identity."""
    target = Path(target).resolve()
    failure_path = Path(failure_path).resolve()
    failure = batch.read(failure_path)
    if (failure.get('target') != str(target) or 'attempt_manifest.json' not in failure.get('error', '')
            or (target/'attempt_manifest.json').exists() or (target/'scores.json').exists()
            or any(p.name.startswith('evidence_') for p in (target/'model_calls').iterdir())):
        raise ValueError('Not the qualified pre-call manifest handoff failure')
    receipt = batch.read(target/'endpoint_partial_recovery.json')
    source = Path(receipt['parent_attempt'])
    protocol = batch.read(target/'input/pilot_rubric.json')
    dump(target/'preparation_resume.json', {'version': VERSION,
        'failure_path': str(failure_path), 'failure_sha256': sha(failure_path),
        'root_cause': 'Checkpoint preparation archived the parent attempt manifest but omitted the new immutable attempt manifest required by the unchanged core12 budget gate.',
        'repair': 'Persist formal attempt identity with identical frozen runtime budget before capture validation.',
        'new_attempt_created': False, 'model_calls_before_resume': 0,
        'new_recordings': 0, 'limits_or_scoring_changed': False})
    batch.write_attempt_manifest(target, batch.read(target/'input_manifest.json')['entry'],
        protocol['runtime_budget'], previous_attempt=source, phase='endpoint_partial_checkpoint')
    verify(target)
    manifest = batch.read(target/'evidence_manifest.json')
    validation = batch.validate_capture_bundle(target, manifest, protocol)
    dump(target/'validation_history/capture_bundle_validation.json', validation)
    eligible = partial_gate(target, protocol, manifest, validation)
    dump(target/'endpoint_partial_prepared.json', {'version': VERSION,
        'eligible_shards': eligible, 'blocked_shards': [name for name in manifest['evidence_sets'] if name not in eligible],
        'manifest_sha256': sha(target/'evidence_manifest.json'),
        'parent_files_unchanged': True, 'full_capture_valid': False, 'score_created': False})
    return eligible
