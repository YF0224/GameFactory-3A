"""Qualify an immutable, complete telemetry take through existing capture gates.

This operation is offline. It never records, calls a model, changes a native
channel, or makes a diagnostic result eligible without source/bundle validation.
"""
from pathlib import Path
import copy
import shutil
from . import batch, endpoint_sparse, sparse_evidence, sparse_native
from . import mechanic_v3_runner as runner, mechanic_v3_full_scope as full_scope
from . import godot_native_telemetry as telemetry
from .protocol import dump, sha

VERSION = 'whitebox-godot-native-telemetry-reuse.v1'
CLAIM = 'native_telemetry_reuse_claim.json'
PROVENANCE = 'native_telemetry_provenance.json'
CONTINUATION = 'native_telemetry_offline_continuation.json'
PRODUCER = 'native_telemetry_producer_continuation.json'
PRODUCER_FILES = frozenset(('godot_native_telemetry_reuse.py', 'qualified_history.py', 'endpoint_sparse.py',
    'mechanic_v3_service_recovery.py', 'gameness_v3_runtime.py', 'godot_native_draw_recovery.py'))


def production_bindings():
    from .mechanic_v3_cli import production_source_bindings
    return production_source_bindings()


def historical_acceptance(path, archive):
    """Verify exact recorded adapter bytes and both retained native fixture runs."""
    value = runner.read(path)
    if (value.get('version') != telemetry.VERSION or value.get('accepted') is not True
            or len(value.get('cases', [])) != 2
            or {case.get('early_exit') for case in value['cases']} != {False, True}
            or not all(case.get('actual_input') is True and case.get('native_pixel_change') is True
                       and case.get('complete') is not case.get('early_exit')
                       for case in value['cases'])):
        raise ValueError('Complete and early-exit real native acceptance required')
    current = telemetry.bindings()
    if set(value['production_bindings']) != set(current):
        raise ValueError('Historical telemetry production file set differs')
    for name, digest in value['production_bindings'].items():
        if sha(Path(name)) == digest:
            continue
        archived = archive.get(name)
        # Only an additive CLI dispatcher edit can differ from the recorded adapter.
        if (Path(name).name != 'mechanic_v3_cli.py' or not archived
                or archived.get('sha256') != digest
                or sha(Path(archived['path'])) != digest):
            raise ValueError('Recorded native production bytes unavailable: '+name)
    telemetry.verify(value['evidence_bindings'])
    return dict(path=str(path), sha256=sha(path), production_bindings=value['production_bindings'],
                historical_recording_acceptance=True, archive=archive)


def complete_take(native):
    execution = runner.read(native/'execution.json')
    inputs = runner.read(native/'input_view_cleanup.json')
    process = runner.read(native/'process_cleanup.json')
    if (execution.get('complete') is not True or execution.get('status') != 'CAPTURED'
            or execution.get('skipped_sample_slots') != 0 or execution.get('capture_errors') != []
            or execution.get('clock') != 'session_monotonic'
            or execution.get('no_state_injection') is not True):
        raise ValueError('Complete original native capture with every slot required')
    if (not all(inputs.get(k) is True for k in ('input_cleanup', 'capture_callback_disconnected'))
            or inputs.get('held_keys_after_release') != 0
            or not all(process.get(k) is True for k in ('process_cleanup', 'view_cleanup'))
            or process.get('group_alive_after_wait') is not False
            or process.get('timeout') is not False or process.get('returncode') != 0):
        raise ValueError('Actual native input/view/process cleanup required')
    return execution


def verify_producer(root, repair, continuation):
    """Authorize an exact offline handoff delta after qualification, never a new take."""
    root, repair, continuation = map(lambda p: Path(p).resolve(), (root, repair, continuation))
    value = runner.read(continuation)
    before = runner.read(repair)['production_bindings']
    after = production_bindings()
    if (value.get('version') != VERSION
            or value.get('classification') != 'QUALIFIED_TELEMETRY_OFFLINE_PRODUCER_CONTINUATION'
            or value.get('root') != str(root)
            or value.get('parent_repair') != str(repair)
            or value.get('parent_repair_sha256') != sha(repair)
            or value.get('qualification_sha256') != sha(root/'source_qualification.json')
            or value.get('production_bindings') != after
            or value.get('maximum_new_native_calls') != 0
            or value.get('scoring_semantics_unchanged') is not True
            or not value.get('root_cause') or set(before) != set(after)):
        raise ValueError('Exact qualified offline producer continuation required')
    changed = {name for name in before if before[name] != after[name]}
    archives = value.get('before_archive', {})
    if (not changed or changed != set(archives)
            or {Path(name).name for name in changed} - PRODUCER_FILES):
        raise ValueError('Offline producer delta includes unauthorized files')
    for name, archived in archives.items():
        if sha(Path(archived)) != before[name]:
            raise ValueError('Original qualified producer bytes changed: '+name)
    if sha(Path(value['patch'])) != value.get('patch_sha256'):
        raise ValueError('Offline producer patch changed')
    return value


def check_diagnostic(workspace, row, diagnostic, repair, *, qualified_root=None):
    workspace, diagnostic, repair = map(lambda p: Path(p).resolve(), (workspace, diagnostic, repair))
    fix = runner.read(repair)
    historical_offline = False
    if fix.get('production_bindings') != production_bindings():
        if qualified_root is None:
            raise ValueError('Explicit current source-bound qualification repair required')
        proof = runner.read(Path(qualified_root)/PRODUCER)
        producer = Path(proof['repair'])
        if sha(producer) != proof['repair_sha256']:
            raise ValueError('Offline producer continuation changed')
        verify_producer(qualified_root, repair, producer)
        historical_offline = True
    if (fix.get('version') != VERSION or fix.get('classification') != 'READ_ONLY_NATIVE_TELEMETRY_QUALIFICATION'
            or fix.get('diagnostic') != str(diagnostic)
            or fix.get('scoring_semantics_unchanged') is not True
            or not fix.get('root_cause') or not fix.get('parent_bindings')):
        raise ValueError('Explicit current source-bound qualification repair required')
    telemetry.verify(fix['parent_bindings'])
    result_path = diagnostic/'diagnostic_result.json'
    result = runner.read(result_path)
    source = Path(result['source']).resolve()
    driver = telemetry
    if result.get('version') == 'whitebox-godot-native-draw.v1':
        from . import godot_native_draw_recovery as driver
    if (source.name != row['entry']['id'] or not row['in_scope']
            or row['entry']['actual_engine'] != 'godot' or fix.get('source') != str(source)
            or result.get('version') != driver.VERSION or result.get('diagnostic_only') is not True
            or result.get('root') != str(diagnostic)
            or result.get('original_plan_actions_windows_unchanged') is not True
            or str(result_path) not in fix['parent_bindings']):
        raise ValueError('Same frozen original diagnostic identity required')
    recorded_draw_bindings = None
    if driver is not telemetry and historical_offline:
        # The outer exact archive gate already proved every changed producer.
        # Keep the native acceptance pinned to the bytes used for this take.
        recorded_draw_bindings = driver.bindings()
        recorded_draw_bindings.update(fix['production_bindings'])
    if driver is not telemetry:
        if driver.verify_recovery_claim(workspace, row, diagnostic, result,
                recorded_bindings=recorded_draw_bindings) != source:
            raise ValueError('Native draw source differs')
    else:
        claim_path = source/'native_capture_telemetry_claim.json'
        claim = runner.read(claim_path)
        original_repair = Path(claim['repair'])
        if (claim.get('root') != str(diagnostic) or claim.get('maximum_attempts') != 1
                or sha(original_repair) != claim['repair_sha256']
                or result['repair_sha256'] != claim['repair_sha256']):
            raise ValueError('Retained native diagnostic claim differs')
        telemetry.verify(runner.read(original_repair)['parent_bindings'])
    batch.verify_inputs(source)
    original = runner.read(source/'input_manifest.json')
    if not full_scope.same_original(original['entry'], row['entry']):
        raise ValueError('Diagnostic source differs from frozen delivery')
    if batch.hashes(diagnostic/'project') != original['snapshot_hashes']:
        raise ValueError('Native author project bytes differ')
    old_execution = runner.read(source/'runtime/execution.json')
    if old_execution.get('complete') is not False or old_execution.get('status') != 'HARNESS_ERROR':
        raise ValueError('Retained parent must be an incomplete harness capture')
    acceptance_path = (workspace/telemetry.ACCEPTANCE if driver is telemetry
                       else driver.acceptance_path(workspace,recorded_bindings=recorded_draw_bindings))
    if result['acceptance_sha256'] != sha(acceptance_path):
        raise ValueError('Recording native acceptance changed')
    acceptance = (historical_acceptance(acceptance_path, fix.get('historical_production_archive', {}))
                  if driver is telemetry else driver.verify_acceptance(acceptance_path,recorded_bindings=recorded_draw_bindings))
    telemetry.verify(result['evidence_bindings'])
    native = diagnostic/'take/runtime'
    required = [p for p in native.rglob('*') if p.is_file()]
    if {str(p): sha(p) for p in required} != {
            k:v for k,v in result['evidence_bindings'].items()
            if Path(k).is_relative_to(native)}:
        raise ValueError('Unbound native diagnostic evidence')
    execution = complete_take(native)
    plan = runner.read(source/'sol_plan.json')
    recorded_plan = runner.read(diagnostic/'plan.json')
    if sha(diagnostic/'plan.json') != sha(source/'runtime/recording_plan.json'):
        raise ValueError('Native execution plan changed')
    for field in ('probes', 'capture_plan', 'watchers', 'max_duration_ms'):
        if plan.get(field) != recorded_plan.get(field):
            raise ValueError('Frozen native plan differs: '+field)
    proto = runner.read(source/'input/pilot_rubric.json')
    schedule = endpoint_sparse.validate_plan(proto, plan, 'godot', root=source)
    # Match runtime._run_engine_unlocked: Godot capture has zero warmup.
    schedule['warmup_ms'] = 0
    if recorded_plan.get('native_capture_schedule') != schedule:
        raise ValueError('Recorded native schedule differs from original plan')
    audit = sparse_evidence.audit_capture(native, schedule)
    if audit['missing_slots_ms'] or audit['actual_screenshots'] != audit['planned_screenshots']:
        raise ValueError('Missing predeclared native screenshots')
    if execution['frames'] != audit['actual_screenshots'] or len(execution['probes']) != len(plan['probes']):
        raise ValueError('Incomplete native execution/probe index')
    from engine_adapters.godot.playtest.scene_entry import resolve_scene
    scene = resolve_scene(diagnostic/'project')
    invocation = runner.read(native/'invocation.json')
    command = [str(telemetry.binary(row)), '--path', str(diagnostic/'project'), '--resolution', '960x540',
        '--position', '40,70', '--script', str(driver.adapter.RECORDER.resolve()), '--',
        str(diagnostic/'plan.json'), str(native), scene['resolved']]
    if invocation.get('command') != command or invocation.get('version') != driver.adapter.VERSION:
        raise ValueError('Native invocation differs from accepted real adapter')
    return dict(source=str(source), diagnostic=str(diagnostic), acceptance=acceptance, audit=audit,
                source_entry=original['entry'])


def verify_origin(root):
    """Revalidate the native provenance and each byte of the immutable evidence view."""
    root = Path(root).resolve()
    proof = runner.read(root/PROVENANCE)
    if proof.get('version') != VERSION or proof.get('root') != str(root):
        raise ValueError('Native telemetry provenance differs')
    repair = Path(proof['repair'])
    if sha(repair) != proof['repair_sha256']:
        raise ValueError('Qualification repair changed')
    for name in (CONTINUATION, 'native_telemetry_offline_continuation_2.json'):
        if (root/name).exists():
            continuation = runner.read(root/name)
            if continuation.get('parent_repair_sha256') != sha(repair):
                raise ValueError('Offline qualification continuation parent differs')
            repair = Path(continuation['repair'])
            if sha(repair) != continuation['repair_sha256']:
                raise ValueError('Offline qualification continuation repair changed')
    workspace = Path(proof['workspace'])
    inventory = full_scope.load(workspace)
    row = next(r for r in inventory['entries'] if r['entry']['id'] == root.name)
    result = check_diagnostic(workspace, row, Path(proof['diagnostic']), repair, qualified_root=root)
    for target, original in proof['identical_files'].items():
        if sha(root/target) != sha(Path(original)):
            raise ValueError('Native raw view differs: '+target)
    batch.verify_inputs(root)
    batch.verify_runtime_sources(root)
    return result['acceptance']


def verify(canonical):
    canonical = Path(canonical).resolve()
    claim = runner.read(canonical/CLAIM)
    root = Path(claim['root'])
    if (claim.get('version') != VERSION or claim.get('maximum_recording_attempts') != 0
            or root.name != canonical.name or claim.get('identity') != canonical.name):
        raise ValueError('Native telemetry reuse claim differs')
    proof = runner.read(root/PROVENANCE)
    if sha(Path(proof['repair'])) != claim['repair_sha256']:
        raise ValueError('Reuse claim repair differs')
    verify_origin(root)
    qualification = runner.read(root/'source_qualification.json')
    telemetry.verify(qualification['source_bindings'])
    gate = batch.validate_capture_bundle(root)
    if not gate['valid']:
        raise ValueError('Qualified telemetry bundle differs: '+str(gate))
    return root


def qualify(workspace, row, diagnostic, repair):
    workspace, diagnostic, repair = map(lambda p: Path(p).resolve(), (workspace, diagnostic, repair))
    canonical = workspace/'runs'/row['entry']['id']
    if (canonical/CLAIM).exists():
        claim = runner.read(canonical/CLAIM)
        root = Path(claim['root'])
        if (root/'source_qualification.json').exists():
            if runner.read(repair).get('classification') == 'QUALIFIED_TELEMETRY_OFFLINE_PRODUCER_CONTINUATION':
                value = runner.read(repair)
                parent = Path(value['parent_repair'])
                # Original provenance and both bounded offline failures stay immutable.
                proof = runner.read(root/PROVENANCE)
                latest = Path(proof['repair'])
                for name in (CONTINUATION, 'native_telemetry_offline_continuation_2.json'):
                    if (root/name).exists():
                        latest = Path(runner.read(root/name)['repair'])
                if parent != latest:
                    raise ValueError('Offline producer continuation skipped its qualified parent')
                verify_producer(root, parent, repair)
                producer_path = root/PRODUCER
                expected = dict(version=VERSION, repair=str(repair), repair_sha256=sha(repair),
                                maximum_new_native_calls=0, new_recording=False)
                if producer_path.exists():
                    if runner.read(producer_path) != expected:
                        raise ValueError('Offline producer continuation already claimed')
                else:
                    if any((root/name).exists() for name in ('model_calls', 'requests', 'mechanic_score.json')):
                        raise ValueError('Offline producer handoff must precede judge invocation')
                    runner.exclusive_json(producer_path, expected)
            return verify(canonical)
        if claim.get('repair_sha256') == sha(repair):
            raise ValueError('Preserve failed offline qualification; substantive bound repair required')
        checked = check_diagnostic(workspace, row, diagnostic, repair)
        fix = runner.read(repair)
        previous = runner.read(root/CONTINUATION) if (root/CONTINUATION).exists() else claim
        continuation_name = 'native_telemetry_offline_continuation_2.json' if (root/CONTINUATION).exists() else CONTINUATION
        if (fix.get('resume_root') != str(root) or fix.get('parent_repair_sha256') != previous['repair_sha256']
                or fix.get('parent_claim_sha256') != sha(canonical/CLAIM)
                or not fix.get('failure') or sha(Path(fix['failure'])) != fix.get('failure_sha256')
                or (root/'model_calls').exists() or (root/'mechanic_score.json').exists()):
            raise ValueError('Same failed offline stage and immutable parent claim required')
        runner.exclusive_json(root/continuation_name, dict(version=VERSION,repair=str(repair),
            repair_sha256=sha(repair),parent_repair_sha256=previous['repair_sha256'],
            maximum_attempts=1,maximum_new_native_calls=0,failure=fix['failure'],
            failure_sha256=fix['failure_sha256']))
        verify_origin(root)
        return finish_view(workspace, root, canonical, Path(checked['source']), diagnostic)
    checked = check_diagnostic(workspace, row, diagnostic, repair)
    source = Path(checked['source'])
    root = workspace/'native_telemetry_reuse'/row['entry']['id']/sha(repair)/'runs'/row['entry']['id']
    runner.disk(workspace, 'native_telemetry_offline_evidence', 2*1024**3)
    runner.exclusive_json(canonical/CLAIM, dict(version=VERSION, identity=root.name, root=str(root),
        repair=str(repair), repair_sha256=sha(repair), maximum_recording_attempts=0,
        original_failure_and_diagnostic_preserved=True))
    root.mkdir(parents=True, exist_ok=False)
    identical = {}
    runner.link_tree(source/'input', root/'input')
    runner.link_tree(diagnostic/'take/runtime', root/'runtime')
    runner.link_tree(diagnostic/'project', root/'runtime/project', runtime=True)
    for directory, origin in [('input', source/'input'), ('runtime', diagnostic/'take/runtime'),
                              ('runtime/project', diagnostic/'project')]:
        for path in (root/directory).rglob('*'):
            if path.is_file():
                relative = path.relative_to(root/directory)
                parent = origin/relative
                if parent.is_file(): identical[str(path.relative_to(root))] = str(parent)
    for name in ('input_manifest.json', 'attempt_manifest.json', 'sol_plan.json',
                 'endpoint_conditions_receipt.json', 'native_record_completion_policy.json'):
        if (source/name).exists():
            shutil.copy2(source/name, root/name)
            identical[name] = str(source/name)
    shutil.copy2(diagnostic/'plan.json', root/'runtime/recording_plan.json')
    identical['runtime/recording_plan.json'] = str(diagnostic/'plan.json')
    dump(root/PROVENANCE, dict(version=VERSION, root=str(root), workspace=str(workspace),
        diagnostic=str(diagnostic), source=str(source), repair=str(repair), repair_sha256=sha(repair),
        identical_files=identical, new_recording=False, new_native_call=False,
        scoring_semantics_unchanged=True))
    return finish_view(workspace, root, canonical, source, diagnostic)


def finish_view(workspace, root, canonical, source, diagnostic):
    from . import runtime
    runtime.normalize_channels(root, 'godot')
    sparse_native.cleanup(root, 'godot')
    manifest = batch.deliver(root)
    gate = batch.validate_capture_bundle(root, manifest)
    runner.exclusive_json(root/'validation_history'/('telemetry_capture_bundle_'+str(__import__('time').time_ns())+'.json'), gate)
    if not gate['valid']:
        raise ValueError('Telemetry evidence qualification failed: '+str(gate))
    qualification = runner.qualify_source(root, workspace=workspace)
    qualification.update(recording='REUSED_COMPLETE_REAL_NATIVE_TELEMETRY_RECORD',
        historical_source=str(source), diagnostic=str(diagnostic), new_recording=False,
        raw_record_reused=True, diagnostic_became_eligible_only_after_full_capture_gates=True,
        notice='按新冻结契约评价已完整录制的原生诊断实录；离线完整资格化，无新增录制，无旧判词复用')
    runner.exclusive_json(root/'source_qualification.json', qualification)
    return verify(canonical)


def verify_recorded_identity(root, current, recorded):
    """Keep only the tool fingerprint from the fully validated, unchanged plan."""
    root = Path(root).resolve()
    verify_origin(root)
    proof = runner.read(root/PROVENANCE)
    source = Path(proof['source'])
    recovery = runner.read(source/'prerecord_recovery.json')
    validation = runner.read(source/'validation_history/core12_plan_validation.json')
    if (set(current) != set(recorded)
            or any(current[k] != recorded[k] for k in current if k != 'constraints_sha256')
            or validation.get('planning_identity') != recorded
            or recovery.get('full_original_validators') is not True
            or recovery.get('operation_sha256') != sha(source/'sol_plan.json')
            or sha(root/'sol_plan.json') != sha(source/'sol_plan.json')):
        raise ValueError('Native telemetry recorded plan identity differs')
    telemetry.verify(recovery['source_bindings'])
    if not runner.read(source/'validation_history/capture_plan_validation.json').get('valid'):
        raise ValueError('Retained executable capture plan validation required')
    return dict(recorded)
