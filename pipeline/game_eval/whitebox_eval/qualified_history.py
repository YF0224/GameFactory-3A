"""Explicit judge-only reuse of a previously qualified, immutable native take.

A prior real capture qualification is a capture acceptance, not a product score.
Only constraint-code SHA drift is allowed. Current full capture validators still
run on the read-only evidence view; this receipt never authorizes new execution.
"""
from pathlib import Path
import shutil
import time
from .protocol import sha, dump
from . import mechanic_v3_runner as runner

VERSION = 'qualified-historical-native-view.v1'
FILE = 'qualified_record_reuse.json'
REQUIRED = ('input_manifest.json', 'input/pilot_rubric.json', 'sol_plan.json',
            'evidence_manifest.json', 'trace_summary.json',
            'runtime/action_frame_links.json', 'runtime/capture_schedule.json',
            'runtime/frame_index.jsonl', 'runtime/actions.jsonl',
            'runtime/state_trace.jsonl', 'runtime/event_trace.jsonl')


def prior(source):
    source = Path(source).resolve()
    path = source/'source_qualification.json'
    q = runner.read(path)
    if (Path(q['source']).resolve() != source or
            q.get('original_capture_gate', {}).get('valid') is not True or
            q['original_capture_gate'].get('counts', {}).get('plan_valid') is not True or
            q.get('slot_delivery_correction')):
        raise ValueError('Prior qualification is not an accepted unchanged raw take')
    bindings = q.get('source_bindings', {})
    required = {str(source/n) for n in REQUIRED}
    cleanup = q.get('cleanup_bindings', {})
    if not cleanup or not required <= bindings.keys():
        raise ValueError('Historical qualification lacks physical capture/cleanup bindings')
    for n, digest in cleanup.items():
        if bindings.get(str((source/n).resolve())) != digest:
            raise ValueError('Historical cleanup lacks immutable qualification binding')
    for n, digest in bindings.items():
        if sha(Path(n)) != digest:
            raise ValueError('Historical qualification source changed: '+n)
    return q


def verify_recorded(root, current, recorded):
    root = Path(root).resolve()
    receipt = runner.read(root/FILE)
    if receipt.get('version') != VERSION or receipt.get('execution_allowed') is not False:
        raise ValueError('Not a judge-only qualified historical view')
    source = Path(receipt['source']).resolve()
    if source == root or sha(source/'source_qualification.json') != receipt['qualification_sha256']:
        raise ValueError('Historical qualification proof changed')
    q = prior(source)
    if (not isinstance(recorded, dict) or set(recorded) != set(current) or
            any(recorded[k] != v for k, v in current.items() if k != 'constraints_sha256')):
        raise ValueError('Historical record changed frozen source/contract identity')
    for n in REQUIRED:
        if sha(root/n) != q['source_bindings'][str(source/n)]:
            raise ValueError('Historical view differs from accepted capture: '+n)
    if runner.read(source/'sol_plan.json')['planning_identity'] != recorded:
        raise ValueError('Historical planning identity changed')
    return recorded


def native_acceptance(root):
    """Resolve immutable judge-only provenance to its real recording acceptance."""
    from . import sparse_native, godot_native_telemetry_reuse as telemetry_reuse
    root = Path(root).resolve()
    if (root/FILE).exists():
        receipt = runner.read(root/FILE)
        source = Path(receipt['source']).resolve()
        if (receipt.get('version') != VERSION or receipt.get('execution_allowed') is not False
                or source == root or (source/FILE).exists()
                or sha(source/'source_qualification.json') != receipt['qualification_sha256']):
            raise ValueError('Historical native acceptance lineage differs')
        q = prior(source)
        acceptance = native_acceptance(source)
        if acceptance != q['native_acceptance']:
            raise ValueError('Historical matching native acceptance changed')
        return acceptance
    if (root/telemetry_reuse.PROVENANCE).exists():
        return telemetry_reuse.verify_origin(root)
    entry = runner.read(root/'input_manifest.json')['entry']
    return sparse_native.verify_acceptance(root.parents[1], entry['actual_engine'])


def prepare_view(workspace, row, source, *, destination=None):
    """Use only an existing self-qualified raw take; never manufacture acceptance."""
    from . import batch, core12, sparse_evidence, sparse_native
    from .pending_publication import cleanup_source
    workspace, source = Path(workspace).resolve(), Path(source).resolve()
    root = workspace/'runs'/row['entry']['id'] if destination is None else Path(destination).resolve()
    if not root.is_relative_to(workspace) or root.name != row['entry']['id'] or root.parent.name != 'runs':
        raise ValueError('Historical view destination is outside the original workspace identity')
    q = prior(source)
    retained = root.exists()
    if retained and (root/'source_qualification.json').exists():
        retained_q = runner.read(root/'source_qualification.json')
        if Path(retained_q['source']).resolve() != source:
            raise ValueError('Retained historical view has a different requested source')
        for n, digest in retained_q['source_bindings'].items():
            if sha(Path(n)) != digest:
                raise ValueError('Retained historical view binding changed')
        verify_recorded(root, core12.plan_identity(root, runner.read(root/'input/pilot_rubric.json'),
                        row['entry']['actual_engine']), runner.read(root/'sol_plan.json')['planning_identity'])
        return root
    if retained:
        # Resume only our pre-invocation failed view, never an unrelated/used run.
        proof = runner.read(root/FILE)
        if (proof.get('source') != str(source) or proof.get('execution_allowed') is not False or
                proof.get('qualification_sha256') != sha(source/'source_qualification.json') or
                (root/'model_calls').exists() or (root/'requests').exists()):
            raise ValueError('Incomplete view lacks unchanged pre-invocation lineage')
        for n in REQUIRED:
            if sha(root/n) != sha(source/n):
                raise ValueError('Incomplete historical view changed: '+n)
    batch.verify_inputs(source)
    batch.verify_runtime_sources(source)
    entry = runner.read(source/'input_manifest.json')['entry']
    from . import mechanic_v3_full_scope as scope
    if not scope.same_original(row['entry'], entry):
        raise ValueError('Historical qualification is not the frozen original')
    runner.source_scope_authorization(entry, workspace)
    acceptance = native_acceptance(source)
    if acceptance != q['native_acceptance']:
        raise ValueError('Historical matching native acceptance changed')
    cleanup, origin = cleanup_source(source)
    if not cleanup or cleanup != q['cleanup_bindings']:
        raise ValueError('Historical actual cleanup changed')
    runner.disk(workspace, 'qualified_historical_evidence_view', 1024**3)
    if not retained:
        root.mkdir(parents=True)
        runner.link_tree(source/'input', root/'input')
        runner.link_tree(source/'runtime', root/'runtime', runtime=True)
        for n in ('input_manifest.json', 'sol_plan.json', 'trace_summary.json'):
            shutil.copy2(source/n, root/n)
    # The source-selected project and author launch provenance remain unchanged.
    attempt = source/'attempt_manifest.json'
    if attempt.exists():
        dst = root/'attempt_manifest.json'
        if dst.exists() and sha(dst) != sha(attempt):
            raise ValueError('Historical attempt provenance changed')
        if not dst.exists():
            shutil.copy2(attempt, dst)
    manifest = runner.read(source/'evidence_manifest.json')
    if not retained:
        for item in manifest['delivery_sheets']:
            src = source/item['path']; dst = root/item['path']
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.hardlink_to(src)
        shutil.copy2(source/'evidence_manifest.json', root/'evidence_manifest.json')
        receipt = dict(version=VERSION, source=str(source), qualification_sha256=sha(source/'source_qualification.json'),
                       execution_allowed=False, created=runner.stamp(), scoring_semantics_unchanged=True)
        runner.exclusive_json(root/FILE, receipt)
    for engine in ('godot', 'three_js'):
        src = source.parents[1]/'engineering/native_acceptance'/(engine+'.json')
        dst = workspace/'engineering/native_acceptance'/(engine+'.json')
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists() and dst.read_bytes() != src.read_bytes():
                raise ValueError('Conflicting historical native acceptance')
            if not dst.exists():
                shutil.copy2(src, dst)
    proto = runner.read(root/'input/pilot_rubric.json')
    gate = batch.validate_capture_bundle(root, manifest, proto)
    if not gate['valid']:
        dump(root/('qualified_history_validation_failure_'+str(time.time_ns())+'.json'), gate)
        raise ValueError('Historical view failed current full capture validation: '+str(gate))
    sparse_evidence.validate(root, proto, manifest)
    bindings = dict(q['source_bindings'])
    if attempt.exists():
        bindings[str(attempt)] = sha(attempt)
        bindings[str(root/'attempt_manifest.json')] = sha(root/'attempt_manifest.json')
    bindings.update({str(source/'source_qualification.json'): sha(source/'source_qualification.json'),
                     str(root/FILE): sha(root/FILE)})
    qualified = dict(q, time=runner.stamp(), source_bindings=bindings,
                     historical_qualification=dict(receipt_path=str(root/FILE), current_capture_gate=gate),
                     new_recording=False, raw_record_reused=True, corrected_delivery_validated=True,
                     view_manifest_sha256=sha(root/'evidence_manifest.json'),
                     notice='按新结果导向契约重新评价已资格化历史实录；只复用原采集，不复用旧判词')
    runner.exclusive_json(root/'source_qualification.json', qualified)
    return root
