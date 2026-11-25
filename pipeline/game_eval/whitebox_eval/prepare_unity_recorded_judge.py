"""Package the accepted recording without launching Unity or changing its source."""
from pathlib import Path
import copy
import json
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from pipeline.game_eval.whitebox_eval import batch, core12, runtime
from pipeline.game_eval.whitebox_eval.codex import load_plan_json
from pipeline.game_eval.whitebox_eval.protocol import dump, sha
from .recorded_capture_files import VERSION as CAPTURE_FILES_VERSION, expected_files, link_normalization_receipt
from .recorded_import_review import reviewed_import_paths



NATIVE_OBSERVER_METADATA = {
    'OBSERVER_CONTRACT': 'functional_observer_contract.json',
    'OBSERVER_READINESS': 'functional_observer_readiness.json',
    'STATE_SOURCE_BINDINGS': 'state_source_bindings.jsonl',
}


OPTIONAL_OBSERVER_METADATA = {
    'EVENT_SOURCE_BINDINGS': 'event_source_bindings.jsonl',
    'PUBLIC_AUTO_PROPERTY_BINDINGS': 'public_auto_property_bindings.jsonl',
}

def observer_metadata(attempt):
    return {**NATIVE_OBSERVER_METADATA, **{ident: name for ident, name in OPTIONAL_OBSERVER_METADATA.items()
        if (Path(attempt)/'runtime'/name).is_file()}}

def add_observer_metadata(attempt, manifest):
    """Deliver the original native observer receipts without claiming gameplay success."""
    for ident, name in observer_metadata(attempt).items():
        native = attempt/'runtime'/name
        if native.is_file():
            manifest['items'].append({'id': ident, 'path': 'runtime/'+name,
                'type': 'log', 'sha256': sha(native)})
    return manifest


def copy_static_judgment(recorded, attempt, recorded_protocol):
    from pipeline.game_eval.whitebox_eval import static_existence
    if not static_existence.enabled(recorded_protocol):
        return
    original = static_existence.load(recorded, recorded_protocol)
    target_protocol = batch.read(attempt/'input/pilot_rubric.json')
    expected = static_existence.identity(attempt,target_protocol)
    source = recorded
    if original['identity'] != expected:
        source = None
        ident = batch.read(recorded/'input_manifest.json')['entry']['id']
        for previous in sorted(recorded.parent.glob(ident+'__recorded_judge_v1_*'),reverse=True):
            artifact = previous/'static_existence.json'
            if previous == attempt or not artifact.is_file():
                continue
            try:
                if batch.read(artifact)['result']['identity'] != expected:
                    continue
                batch.verify_inputs(previous)
                static_existence.load(previous,target_protocol)
            except (ValueError,OSError,KeyError):
                continue
            source = previous
            break
        dump(attempt/'recovery_source/static_existence.original.json',batch.read(recorded/'static_existence.json'))
        dump(attempt/'static_source_version_change.json',{
            'schema':'unity-recorded-static-source-version.v1','original_attempt':str(recorded),
            'original_artifact_sha256':sha(recorded/'static_existence.json'),
            'original_identity':original['identity'],'imported_source_identity':expected,
            'identity_rewritten':False,'reuse_from':str(source) if source else None,
            'reason':'Judge the explicitly versioned, actually recorded imported renderer. Reuse only a genuine Sol result with exactly this source identity; otherwise run the original bounded static phase.'})
        if source is None:
            static_timeout = batch.read(attempt/'input_manifest.json')['entry'].get('stage_timeouts', {}).get('static', 1200)
            started = __import__('time').monotonic()
            static_existence.run(attempt, timeout=static_timeout)
            dump(attempt/'imported_static_timing.json', {'timeout_seconds': static_timeout,
                'elapsed_seconds': __import__('time').monotonic()-started,
                'stage': 'static_imported_source', 'uses_plan_time': False})
            return
    from . import static_output_recovery
    if any((source/n).is_file() for n in (static_output_recovery.RECEIPT,static_output_recovery.REUSE)):
        static_output_recovery.copy_judgment(source,attempt)
        return
    from . import cli_static_reuse
    if (source/cli_static_reuse.RECEIPT).is_file() or batch.read(source/'static_existence.json').get('cli_runtime_recovery_sha256'):
        cli_static_reuse.copy_judgment(source,attempt)
        return
    shutil.copy2(source / 'static_existence.json', attempt / 'static_existence.json')
    from .partial_static_existence import RECEIPT as partial_static_receipt
    if (source/partial_static_receipt).is_file():
        shutil.copy2(source/partial_static_receipt, attempt/partial_static_receipt)
    from .static_transport_recovery import RECEIPT as transport_receipt
    if (source/transport_receipt).is_file():
        shutil.copy2(source/transport_receipt, attempt/transport_receipt)
    for folder in sorted((source / 'model_calls').glob('static_existence*')):
        if folder.is_dir():
            shutil.copytree(folder, attempt / 'model_calls' / folder.name)
    static_existence.load(attempt, batch.read(attempt / 'input/pilot_rubric.json'))


def recorded_plan_for_judge(recorded, attempt, *, persist=True):
    plan = load_plan_json(recorded / 'sol_plan.json')
    plan = batch.validate_operation_plan(recorded, plan, 'unity3d')
    if 'planning_identity' not in plan:
        return plan
    for name in ['frozen_rubric.json', 'pilot_rubric.json', 'scoring_frozen_rubric.json',
                 'scoring_pilot_rubric.json', 'legacy_frozen_rubric.json']:
        if sha(recorded / 'input' / name) != sha(attempt / 'input' / name):
            raise ValueError('Recorded core12 contract/budget changed while preparing judge: ' + name)
    before = batch.read(recorded / 'input_manifest.json')['snapshot_hashes']
    after = batch.read(attempt / 'input_manifest.json')['snapshot_hashes']
    changed = {name for name in set(before) | set(after) if before.get(name) != after.get(name)}
    allowed = {'ProjectSettings/GraphicsSettings.asset', 'ProjectSettings/QualitySettings.asset',
               'ProjectSettings/ProjectVersion.txt', 'Packages/packages-lock.json'}
    allowed.update(reviewed_import_paths(recorded))
    from .unity_admission_metadata import plan_paths
    allowed.update(plan_paths(attempt, recorded, before, after))
    from .unity_authored_settings_import import plan_paths as authored_settings_paths
    allowed.update(authored_settings_paths(attempt, recorded, before, after))
    from .unity_native_import_metadata import plan_paths as native_import_paths
    allowed.update(native_import_paths(attempt, recorded, before, after))
    version = batch.read(attempt/'input_manifest.json')['entry'].get('recorded_source_version', {})
    if 'unity_m_input_materialization' in version:
        from .unity_m_input_adapter import materialization_proof
        proof = materialization_proof(recorded)
        if proof != version['unity_m_input_materialization']:
            raise ValueError('Exact input migration materialization changed')
        for row in proof['changes']:
            if not row['added'] and (before.get(row['path']) != row['original_sha256'] or after.get(row['path']) != row['recorded_sha256']):
                raise ValueError('Derived input migration bytes changed')
        allowed.update(row['path'] for row in proof['changes'] if not row['added'])
    if changed - allowed:
        raise ValueError('Recorded judge source differs outside allowed import metadata: ' + str(sorted(changed)))
    identity = core12.plan_identity(attempt, core12.verify_attempt(attempt, 'unity3d'), 'unity3d')
    # The recorded plan was just fully revalidated against its submitted identity.
    # Tool-only edits must not invalidate genuine capture; the derived judge identity
    # explicitly records both fingerprints below. Contract and budget checks stay strict.
    if {key: value for key, value in identity.items() if key not in {'project_sha256','constraints_sha256'}} != {
            key: value for key, value in plan['planning_identity'].items() if key not in {'project_sha256','constraints_sha256'}}:
        raise ValueError('Recorded core12 planner constraints changed while preparing judge')
    derived = copy.deepcopy(plan)
    if 'unity_m_input_materialization' in version:
        from .unity_m_input_adapter import derive_endpoint_references
        derived = derive_endpoint_references(recorded, attempt, derived, proof)
    derived['planning_identity'] = identity
    if runtime.native_actions(derived) != runtime.native_actions(plan):
        raise ValueError('Recorded judge derivation changed native actions')
    batch.validate_operation_plan(attempt, derived, 'unity3d')
    if persist:
        dump(attempt / 'recovery_source/recorded_sol_plan.original.json', plan)
        dump(attempt / 'recorded_plan_derivation.json', {
            'schema': 'unity-core12-recorded-plan-derivation.v1', 'source_attempt': str(recorded),
            'source_plan_sha256': sha(recorded / 'sol_plan.json'),
            'original_identity': plan['planning_identity'], 'derived_identity': identity,
            'changed_import_metadata': sorted(changed), 'actions_and_coverage_unchanged': True,
            'model_response_preserved': True, 'new_model_call': False,
            'runtime_verified': False})
        audit = recorded / 'validation_history/unity_endpoint_coverage_expansion.json'
        if audit.is_file():
            destination = attempt / 'validation_history' / audit.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(audit, destination)
    return derived


def capture_context(recorded, *, two_column_only=False):
    recorded = Path(recorded).resolve()
    capture = recorded / 'background_record'
    manifest = batch.read(recorded / 'input_manifest.json')
    session = batch.read(capture / 'background_session.json')
    plan = batch.read(recorded / 'sol_plan.json')
    assert manifest['entry']['actual_engine'] == 'unity3d'
    original_project=Path(manifest['entry']['project']).resolve()
    if Path(session['source']).resolve() != original_project:
        migration=recorded/'unity_m_native_dispatch/native_project_override.json'
        if not two_column_only or not migration.is_file():
            raise ValueError('Recorded project differs from original without a frozen Unity M migration binding')
        from .unity_m_input_adapter import verify as verify_input_migration
        native=batch.read(recorded/'recorder_acceptance_binding.json')
        verify_input_migration(recorded,migration.parent,Path(native['acceptance']))
        bound=batch.read(migration)
        if (Path(bound['original']).resolve()!=original_project
                or Path(bound['snapshot']).resolve()!=Path(session['source']).resolve()
                or sha(Path(bound['migration']))!=bound['migration_sha256']
                or batch.read(Path(bound['migration'])).get('changes')!=bound.get('migration_changes')
                or bound.get('gameplay_changes')!=[]):
            raise ValueError('Isolated migration/native project binding changed')
    if manifest['entry'].get('runtime_initializer_entry'):
        if plan['launch_scene'] != '':
            raise ValueError('Natural runtime recording requires an empty plan scene')
        from engine_adapters.unity3d.playtest import runtime_initializer
        binding = runtime_initializer.verify_recording(capture/'take')
        original = recorded/'runtime_initializer_record_entry.json'
        accepted = batch.read(recorded/'recorder_acceptance_binding.json')
        if (binding['attempt'] != str(recorded)
                or binding['case'] != manifest['entry']['id']
                or session['scene'] != binding['source']
                or sha(original) != sha(capture/'take/runtime_initializer_entry.json')
                or accepted.get('runtime_initializer_entry_sha256') != sha(original)):
            raise ValueError('Recorded natural entry differs from its accepted source binding')
    else:
        assert session['scene'] == plan['launch_scene']
    assert session['capture_policy'] == 'graphics_batch_render_v2'
    assert session['activation'] == session['os_input'] == 'forbidden'
    stop_policy = session.get('stop_policy')
    legacy_capture = stop_policy is None
    assert legacy_capture or stop_policy == 'action_timeline_complete'
    actions = batch.read(capture / 'actions_input.json')['actions']
    assert actions == runtime.native_actions(plan), 'Recorded actions differ from validated plan'
    from engine_adapters.action_provenance import action_duration_ms
    duration_ms = sum(action_duration_ms(action) for action in actions)
    if not legacy_capture:
        assert round(session['duration'] * 1000) == duration_ms
        assert duration_ms <= session['recording_budget_seconds'] * 1000 <= 1800000
    batch.validate_operation_plan(recorded, plan, 'unity3d')
    gate = batch.validate_capture_plan(recorded, plan=plan)
    assert gate['valid'], gate
    return session, duration_ms, legacy_capture


def qualify_partial(recorded, attempt, *, two_column_only=False):
    """Protect the accepted static call and identity of a pre-plan interruption."""
    from . import static_existence
    recorded, attempt = Path(recorded).resolve(), Path(attempt).resolve()
    ident = batch.read(recorded/'input_manifest.json')['entry']['id']
    prefix = ident+'__recorded_judge_v1_'
    stamp = attempt.name.removeprefix(prefix)
    if (attempt.parent != (recorded.parent.parent/'recovery_runs' if two_column_only else recorded.parent) or not attempt.name.startswith(prefix)
            or not stamp.isdecimal() or not stamp):
        raise ValueError('Partial recorded judge is outside its original identity')
    lineage = batch.read(attempt/'attempt_manifest.json')
    if (lineage.get('previous_attempt') != str(recorded)
            or lineage.get('attempt_id') != attempt.name
            or lineage.get('entry_id') != ident
            or batch.read(attempt/'status.json').get('status') != 'PREPARED'):
        raise ValueError('Partial recorded judge lineage or phase changed')
    protected = ('sol_plan.json','recorded_plan_derivation.json','operation_report.md',
                 'evidence_manifest.json','recorded_capture_provenance.json','judgments','scores.json')
    if any((attempt/name).exists() for name in protected):
        raise ValueError('Partial recorded judge already advanced beyond static handoff')
    runtime = attempt/'runtime'
    if any(p.name != 'project' for p in runtime.iterdir()):
        raise ValueError('Partial recorded judge already materialized capture evidence')
    batch.verify_inputs(recorded)
    batch.verify_inputs(attempt)
    if two_column_only:
        if (attempt/'model_calls').exists():
            raise ValueError('Two-column pre-plan continuation has model calls')
    else:
        calls = attempt/'model_calls'
        if not calls.is_dir() or {p.name for p in calls.iterdir()} != {'static_existence'}:
            raise ValueError('Partial recorded judge model invocations differ from static handoff')
        accepted = calls/'static_existence/accepted_response.json'
        if not accepted.is_file():
            raise ValueError('Partial recorded judge has no accepted static response')
        batch.verify_inputs(recorded)
        batch.verify_inputs(attempt)
        proto = batch.read(attempt/'input/pilot_rubric.json')
        if not static_existence.enabled(proto):
            raise ValueError('Partial recorded judge does not use static existence')
        static_existence.load(attempt, proto)
    manifest = batch.read(attempt/'input_manifest.json')
    version = manifest['entry'].get('recorded_source_version', {})
    expected_project = recorded/'derived_judge_sources'/(ident+'__recorded_urp_'+stamp)
    if (version.get('original_recorded_attempt') != str(recorded)
            or version.get('version_project') != str(expected_project)
            or manifest['entry'].get('project') != str(expected_project)
            or batch.read(expected_project.parent/(expected_project.name+'.json')) != version):
        raise ValueError('Partial recorded judge source version changed')
    snapshot = manifest['snapshot_hashes']
    if (batch.hashes(attempt/'input/project') != snapshot
            or batch.hashes(expected_project) != snapshot
            or batch.hashes(runtime/'project') != snapshot):
        raise ValueError('Partial recorded judge source copies changed')
    return {'stamp':stamp, 'source_version':version,
            'bindings':{str(p.relative_to(attempt)):sha(p) for p in attempt.rglob('*')
                        if p.is_file() and p.relative_to(attempt).parts[0] != 'runtime'
                        and p.name != 'status.json'}}


def prepare(recorded, *, existing_attempt=None, two_column_only=False, unprepared_resume=None,
            exact_preplan_resume=None):
    recorded = Path(recorded).resolve()
    if two_column_only:
        from .unity_m_evidence import qualify_recorded
        qualify_recorded(recorded)
        if exact_preplan_resume is not None:
            from .unity_m_editor_local_recovery import verify_plan_followup
            _, preserved = verify_plan_followup(recorded, exact_preplan_resume)
            if existing_attempt is None or preserved != Path(existing_attempt):
                raise ValueError('Exact interrupted pre-plan attempt required')
        elif existing_attempt is not None:
            from .unity_m_materialization_resume import verify_prepared_receipt
            verify_prepared_receipt(recorded, Path(existing_attempt))
    capture = recorded / 'background_record'
    verification = batch.read(capture / 'verification.json')
    cleanup = batch.read(capture / 'runner_exit.json')
    from .unity_capture_policy import qualify, RECEIPT
    foreground_qualification = qualify(recorded)
    assert cleanup['cleanup_verified'] and not cleanup['policy_violations']
    assert all(verification['checks'][name] for name in
               ['input_cleanup', 'view_cleanup', 'process_cleanup'])
    batch.verify_inputs(recorded)
    session, duration_ms, legacy_capture = capture_context(recorded, two_column_only=two_column_only)
    entry = copy.deepcopy(batch.read(recorded / 'input_manifest.json')['entry'])
    recorded_protocol = batch.read(recorded / 'input/pilot_rubric.json')
    entry['planning_policy'] = recorded_protocol['planning_contract']['version']
    plan = batch.read(recorded / 'sol_plan.json')
    recorded_project = capture / 'project'
    original_hashes = batch.read(recorded / 'input_manifest.json')['snapshot_hashes']
    observed_hashes = batch.hashes(recorded_project)
    changed_authored = [name for name in original_hashes
                        if observed_hashes.get(name) != original_hashes[name]]
    allowed = {'ProjectSettings/GraphicsSettings.asset',
               'ProjectSettings/QualitySettings.asset',
               'ProjectSettings/ProjectVersion.txt', 'Packages/packages-lock.json'}
    reviewed = reviewed_import_paths(recorded)
    allowed.update(reviewed)
    from .unity_native_import_metadata import proof as native_import_proof
    migration_proof = None
    if two_column_only and (recorded/'unity_m_native_dispatch/native_project_override.json').is_file():
        from .unity_m_input_adapter import materialization_proof
        migration_proof = materialization_proof(recorded)
        allowed.update(row['path'] for row in migration_proof['changes'] if not row['added'])
        # Keep policy-omitted build products in the immutable author version;
        # they were never imported or executed by this native Editor capture.
        omitted_builds={row['path'] for row in migration_proof.get('build_snapshot_exclusions',[])}
        omitted_editor_local={row['path'] for row in migration_proof.get(
            'editor_local_snapshot_exclusions', [])}
        changed_authored=[name for name in changed_authored
                          if name not in omitted_builds | omitted_editor_local]
    native_import_changes = native_import_proof(recorded, native_input_baseline=migration_proof is not None)
    allowed.update(row['path'] for row in native_import_changes)
    from .unity_authored_settings_import import proof as authored_settings_proof, FIELD as authored_settings_field
    authored_settings = authored_settings_proof(recorded)
    allowed.update(row['path'] for row in authored_settings)
    from .unity_ide_metadata import proof as ide_proof
    from .unity_compilation_policy import proof as generated_compile_proof
    from .unity_m_input_adapter import generated_migration_metadata
    ide_changes = [proof for name in changed_authored
        if (proof := (ide_proof(recorded/'input/project', recorded_project, name)
                      or generated_compile_proof(recorded, name)
                      or (generated_migration_metadata(recorded/'input/project', recorded_project, name)
                          if migration_proof else None)))]
    ide_paths = {row['path'] for row in ide_changes}
    from .unity_admission_metadata import proof as admission_metadata_proof
    admission_changes = [admission_metadata_proof(recorded, name) for name in changed_authored
                         if name == 'Assets/GameFactory3AEvaluation/Editor/WhiteboxNativeOpen.cs.meta']
    admission_paths = {row['path'] for row in admission_changes}
    assert set(changed_authored) <= allowed | ide_paths | admission_paths, changed_authored
    partial = qualify_partial(recorded, existing_attempt, two_column_only=two_column_only) if existing_attempt is not None else None
    stamp = partial['stamp'] if partial else (unprepared_resume['stamp'] if unprepared_resume else str(time.time_ns()))
    version = recorded / 'derived_judge_sources' / (entry['id'] + '__recorded_urp_' + stamp)
    if not partial and not unprepared_resume:
        shutil.copytree(recorded / 'input/project', version, ignore=batch.IGNORE)
    for row in admission_changes:
        target = version/row['path']
        if partial:
            if target.exists():
                raise ValueError('Partial admission metadata removal changed')
            continue
        if sha(target) != row['before_sha256']:
            raise ValueError('Generated admission metadata changed during derived input copy')
        target.unlink()
    rendering = []
    for name in sorted(set(changed_authored) - ide_paths - admission_paths):
        source = recorded_project / name
        target = version / name
        rendering.append({'path': name, 'before_sha256': original_hashes[name],
                          'recorded_sha256': sha(source),
                          'original_frozen_input_preserved':True})
        if partial or unprepared_resume:
            if sha(target) != sha(source):
                raise ValueError('Partial imported source changed: '+name)
        else:
            if sha(target) != original_hashes[name]:
                raise ValueError('Derived input copy changed: '+name)
            shutil.copy2(source, target)
    source_version = {
        'schema': 'unity-recorded-import-source-version.v1',
        'original_selected_project': entry['project'],
        'original_recorded_attempt': str(recorded),
        'version_project': str(version), 'recorded_import_serialization': rendering,
        'generated_ide_metadata': ide_changes,
        'orphan_admission_metadata': admission_changes,
        'identity': 'Reviewed delivery with recorded Unity import metadata; see migration provenance',
        'gameplay_changes': [], 'source_selection_unchanged': True,
        'note': 'Explicit derived input version for judging this existing recording. '
                'Original delivery, recorded project and frozen attempt inputs are preserved. '
                'Rendering equivalence to other versions is not claimed.'}
    if migration_proof:
        source_version['unity_m_input_materialization'] = migration_proof
    if native_import_changes:
        source_version['native_editor_import_metadata'] = native_import_changes
    if authored_settings:
        source_version[authored_settings_field] = authored_settings
    if reviewed:
        source_version['schema'] = 'unity-recorded-import-source-version.v2'
        source_version['import_review'] = {'path':str(recorded/'recorded_import_review.json'),
            'sha256':sha(recorded/'recorded_import_review.json'),'reviewed_paths':sorted(reviewed)}
        source_version['imported_asset_context'] = [
            {'authored_path':name,'evidence_path':'recorded_imports/'+name,
             'original_authored_sha256':original_hashes[name],
             'judge_source_sha256':observed_hashes[name],'recorded_sha256':observed_hashes[name]}
            for name in sorted(reviewed)]
    if partial:
        if source_version != partial['source_version']:
            raise ValueError('Partial recorded source provenance differs from current proof')
    else:
        dump(version.parent / (version.name + '.json'), source_version)
    marker=version/'ProjectSettings/ProjectVersion.txt'
    if not marker.is_file():marker=version/plan['launch_scene']
    entry.update(project=str(version), project_marker=str(marker), marker_sha256=sha(marker),
                 recorded_source_version=source_version)
    base = recorded.parent.parent
    attempt = base / 'recovery_runs' / (entry['id'] + '__recorded_judge_v1_' + stamp)
    if partial:
        frozen = batch.read(attempt/'input_manifest.json')
        expected_hashes = dict(original_hashes)
        for row in admission_changes:
            expected_hashes.pop(row['path'])
        expected_hashes.update({row['path']:row['recorded_sha256'] for row in rendering})
        if frozen['entry'] != entry or frozen['snapshot_hashes'] != expected_hashes:
            raise ValueError('Partial recorded judge frozen inputs differ from proven source')
    else:
        source_base = base
        if two_column_only:
            from .unity_m_evidence import qualify_recorded
            _, source_row, _ = qualify_recorded(recorded)
            source_base = Path(source_row['source_batch'])
        if unprepared_resume:
            from .unity_m_materialization_resume import resume_prepare
            resume_prepare(recorded, attempt, source_base, entry, unprepared_resume)
        else:
            batch.prepare(source_base, entry, attempt, previous_attempt=recorded,
                          prefer_explicit_endpoint_conditions=two_column_only)
    if reviewed:
        shutil.copy2(recorded/'recorded_import_review.json',attempt/'recorded_import_review.json')
        for context in source_version['imported_asset_context']:
            destination = attempt/context['evidence_path']
            destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(recorded_project/context['authored_path'],destination)
            if sha(destination) != context['recorded_sha256']:
                raise ValueError('Recorded renderer context copy differs')
    if not partial and not two_column_only:
        copy_static_judgment(recorded, attempt, recorded_protocol)
    plan = recorded_plan_for_judge(recorded, attempt)
    dump(attempt / 'sol_plan.json', plan)
    batch.validate_operation_plan(attempt, plan, 'unity3d')
    batch.write_operation_report(attempt, plan)
    folder = attempt / 'runtime'
    for name in observed_hashes:
        source = recorded_project / name
        target = folder / 'project' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        assert sha(target) == observed_hashes[name]
    installation = recorded_project / 'Assets/GameFactory3AEvaluation/installation.json'
    installed = batch.read(installation)['files']
    instrumentation = []
    for name, digest in installed.items():
        assert name not in original_hashes and sha(recorded_project / name) == digest
        instrumentation.append({'path': name, 'sha256': digest, 'source': str(recorded_project / name)})
    if migration_proof:
        instrumentation.extend({'path':row['path'],'sha256':row['recorded_sha256'],
            'source':str(recorded_project/row['path']),'kind':'verified_native_input_adapter_no_source_credit'}
            for row in migration_proof['changes'] if row['added'])
    instrumentation.append({'path': str(installation.relative_to(recorded_project)),
                            'sha256': sha(installation), 'source': str(installation)})
    dump(folder / 'instrumentation_manifest.json', {'added_files': instrumentation})
    raw = []
    names = expected_files(capture / 'take', session=session)
    for name in sorted(names):
        source = capture / 'take' / name
        shutil.copy2(source, folder / name)
        assert sha(source) == sha(folder / name)
        copied = {'path': name, 'source': str(source), 'sha256': sha(source)}
        if name == 'action_frame_links.json':
            copied['preserved_path'] = 'recovery_source/native_action_frame_links.json'
            destination = attempt/copied['preserved_path']
            destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(source,destination)
        raw.append(copied)
    shutil.copytree(capture / 'take/frames', folder / 'frames')
    log = recorded_project / 'Library/GameFactory3A/Editor.log'
    for name in ['unity_editor.log', 'engine.log', 'import.log']:
        shutil.copy2(log, folder / name)
    result = batch.read(capture / 'result.json')
    engine_result = {'engine': 'unity3d', 'adapter_result': result, 'product_errors': False,
                     'native_evidence': str(capture / 'take')}
    dump(folder / 'engine_result.json', engine_result)
    dump(folder / 'import_result.json', {'engine': 'unity3d', 'product_errors': False,
        'completed': True, 'note': 'Actual import and startup in recorded dedicated Editor; see original log.'})
    dump(folder / 'execution.json', {'engine': 'unity3d', 'status': 'CAPTURED',
        'no_state_injection': True, 'action_rows': len(batch.load_lines(folder / 'actions.jsonl')),
        'declarative_plan_sha256': sha(attempt / 'sol_plan.json'),
        'note': 'Repackaged verified background take; no new engine run or gameplay success claim.'})
    budget = copy.deepcopy(batch.read(attempt / 'input/pilot_rubric.json')['runtime_budget'])
    dump(folder / 'timing.json', {'engine': 'unity3d', 'budget': dict(budget, recording_ms=duration_ms),
        'elapsed_ms': verification['last_ms'], 'timeout': False,
        'recording_budget_ms': budget['recording_ms'], 'recorded_plan_window_ms': duration_ms,
        'note': 'Budget is a ceiling; recording stops after the full native action timeline.'})
    runtime.normalize_channels(attempt, 'unity3d')
    if (attempt/'recovery_source/native_action_frame_links.json').is_file():
        dump(attempt/'action_links_normalization.json',link_normalization_receipt(attempt,capture/'take'))
    limits = (
        f"Case: {entry['id']}. Selected delivery and input migration/version provenance are in "
        'input_manifest.json and recorded_capture_provenance.json. Original delivery and attempts '
        'are preserved. Actual import metadata differences are listed with before/after hashes; '
        'no claim of rendering equivalence to other editor or delivery versions.\n'
        f"Actual take: {verification['frames']} raw frames, {verification['first_ms']}.."
        f"{verification['last_ms']}ms, maximum gap {verification['max_gap_ms']}ms. "
        f"Full action timeline {duration_ms}ms; ceiling {session['recording_budget_seconds']}s. "
        'Internal virtual keyboard/pointer and graphics batch rendering. '
        f"Foreground sampled every 200ms: {verification['foreground_sample_count']} samples, "
        f"PIDs {verification['foreground_pids']}; this is not continuous activation tracing. "
        'Input/device/view/process cleanup verified.\n'
        'Action delivery, purpose, expected observations and plan labels do not prove gameplay '
        'consumption, native restart, a successful retry or victory. Judge these only from actual '
        'frames, readonly state/events and source. Unobserved outcomes remain UNVERIFIED. '
        'Real product exceptions remain in the original Editor log; capture acceptance does not '
        'prove the absence of product errors. The visual judge is not provided full audio. '
        'Judge images are selected by the frozen attempt evidence-frame policy; raw frames/traces are retained.\n')
    extra_limits = recorded / 'capture_limitations.txt'
    channels = batch.read(folder/'channels.json')
    if channels.get('state_trace.jsonl') == 'UNAVAILABLE_STATE_CHANNEL':
        limits += ('\nState observation is unavailable in this actual take: the original native report '
                   'records zero state snapshots and no exposed state provider. The empty canonical '
                   'state channel is an explicit unavailable marker, never an observation of game state. '
                   'Inputs and real images do not substitute for required state/event proof; retain '
                   'only demonstrated source credit when normal execution cannot be established.\n')
    if channels.get('event_trace.jsonl') == 'UNAVAILABLE_EVENT_CHANNEL':
        limits += ('\nEvent observation is unavailable in this actual take. The original native report '
                   'records zero emitted event rows and no capture error; the subscription count is retained '
                   'in the original report. No raw event file was created. '
                   'The empty canonical event channel is not evidence of an observed absence of game events. '
                   'Use actual state/action/frame/log evidence where sufficient; event-dependent conditions '
                   'without another valid observation remain UNVERIFIED.\n')
    if extra_limits.is_file():
        limits += '\nCase-specific reviewed observations and limitations:\n' + extra_limits.read_text()
    (attempt / 'capture_limitations.txt').write_text(limits)
    dump(attempt / 'recorded_capture_provenance.json', {'source_attempt': str(recorded),
        'source_version': source_version, 'raw_identical_copies': raw,
        'raw_copy_policy': CAPTURE_FILES_VERSION, 'raw_copy_file_names': sorted(names),
        'capture_verification_sha256': sha(capture / 'verification.json'),
        'cleanup_verification_sha256': sha(capture / 'runner_exit.json'),
        'foreground_qualification': foreground_qualification,
        'background_session': session, 'recorded_plan_window_ms': duration_ms,
        'legacy_capture_metadata': legacy_capture,
        'frozen_protocol_unchanged': sha(attempt / 'input/pilot_rubric.json') == sha(recorded / 'input/pilot_rubric.json')})
    if (recorded/RECEIPT).is_file():
        shutil.copy2(recorded/RECEIPT, attempt/RECEIPT)
        with (attempt/'capture_limitations.txt').open('a') as handle:
            handle.write('\nForeground presence permitted by explicit user authorization. Native foreground-only failure remains in the original verification; see '+RECEIPT+'.\n')
    return finish_materialized(recorded, attempt, partial, two_column_only=two_column_only)


def finish_materialized(recorded, attempt, partial=None, *, two_column_only=False, preserved_delivery=False):
    """Finish delivery from verified native bytes without changing the prepared identity."""
    recorded,attempt=Path(recorded),Path(attempt)
    from .unity_capture_policy import RECEIPT
    folder=attempt/'runtime'
    verification=batch.read(recorded/'background_record/verification.json')
    source_version=batch.read(attempt/'input_manifest.json')['entry']['recorded_source_version']
    from .unity_authored_generated_assets import declare, RECEIPT as generated_receipt
    generated=declare(recorded,attempt)
    batch.verify_inputs(attempt)
    batch.verify_runtime_sources(attempt)
    if preserved_delivery:
        if not two_column_only:raise ValueError('Only exact Unity M checkpoint may preserve delivery')
        manifest=batch.read(attempt/'evidence_manifest.json')
    elif two_column_only:
        from . import sparse_evidence
        manifest=batch.create_manifest(attempt)
        proto=batch.read(attempt/'input/pilot_rubric.json')
        for path in sorted((attempt/'input/delivery_documents').glob('**/*')):
            if path.is_file():
                manifest['items'].append({'id':'DOC:'+str(path.relative_to(attempt/'input/delivery_documents')),
                    'path':str(path.relative_to(attempt)),'type':'document','sha256':sha(path)})
        manifest=sparse_evidence.deliver(attempt,proto,manifest,checkpoint=True)
        dump(attempt/'evidence_manifest.json',manifest)
        batch.trace_summary(attempt)
    else:
        manifest = batch.deliver(attempt)
    if not preserved_delivery:
        # Native observer metadata is raw capture evidence. Keep method errors in ENGINE
        # while delivering the independently verified provider/field/source bindings.
        # Runtime log type excludes these files from source-only static packets.
        add_observer_metadata(attempt, manifest)
        if generated:
            manifest['items'].append({'id':'AUTHORED_GENERATED_ASSETS','path':generated_receipt,'type':'document','sha256':sha(attempt/generated_receipt)})
            for row in generated:
                manifest['items'].append({'id':'AUTHORED_GENERATED_ASSET:'+row['path'],'path':'runtime/project/'+row['path'],'type':'document','sha256':row['sha256']})
        if (attempt/RECEIPT).is_file():
            manifest['items'].append({'id': 'FOREGROUND_CAPTURE_QUALIFICATION', 'path': RECEIPT,
                'type': 'document', 'sha256': sha(attempt/RECEIPT)})
        for ident, relative in [('CAPTURE_LIMITATIONS', 'capture_limitations.txt'),
                                ('RECORDED_CAPTURE_PROVENANCE', 'recorded_capture_provenance.json')]:
            manifest['items'].append({'id': ident, 'path': relative, 'type': 'document', 'sha256': sha(attempt / relative)})
        derivation = attempt / 'recorded_plan_derivation.json'
        if derivation.is_file():
            manifest['items'].append({'id': 'RECORDED_PLAN_DERIVATION', 'path': derivation.name,
                                     'type': 'document', 'sha256': sha(derivation)})
        import_review = attempt/'recorded_import_review.json'
        if import_review.is_file():
            manifest['items'].append({'id':'RECORDED_IMPORT_REVIEW','path':import_review.name,
                                     'type':'document','sha256':sha(import_review)})
            for context in source_version['imported_asset_context']:
                manifest['items'].append({'id':'RECORDED_IMPORTED_ASSET:'+context['authored_path'],
                    'path':context['evidence_path'],'type':'document','sha256':context['recorded_sha256']})
        normalization = attempt/'action_links_normalization.json'
        if normalization.is_file():
            manifest['items'].append({'id':'ACTION_LINKS_NORMALIZATION','path':normalization.name,
                                     'type':'document','sha256':sha(normalization)})
        static_version = attempt/'static_source_version_change.json'
        if static_version.is_file():
            manifest['items'].append({'id':'STATIC_SOURCE_VERSION_CHANGE','path':static_version.name,
                                     'type':'document','sha256':sha(static_version)})
        # These are source hypotheses and verified cleanup receipts, not new scoring weights.
        for name in ('static_code_scores.json','static_source_scores.json','source_code_score_normalization.json','static_existence_normalization.json','static_items_transport.json','plan_normalization.json','recorder_acceptance_binding.json'):
            source=recorded/name
            if source.is_file():
                destination=attempt/('recorder_acceptance_binding.json' if name=='recorder_acceptance_binding.json' else 'recovery_source/'+name)
                destination.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(source,destination)
                ident='RECORDER_ACCEPTANCE_BINDING' if name=='recorder_acceptance_binding.json' else 'INITIAL_SOURCE_SCORES:'+name
                manifest['items'].append({'id':ident,'path':str(destination.relative_to(attempt)),
                    'type':'document','sha256':sha(destination)})
        cleanup_path=folder/'native_cleanup.json'
        dump(cleanup_path,{key:verification['checks'][key] for key in ('input_cleanup','view_cleanup','process_cleanup')})
        manifest['items'].append({'id':'NATIVE_CLEANUP','path':'runtime/native_cleanup.json','type':'document','sha256':sha(cleanup_path)})
        from .unity_deferred_source_judge import install as install_supplemental_diagnostics
        if not two_column_only:
            manifest=install_supplemental_diagnostics(recorded,attempt,manifest)
        from .unity_evidence_order import prioritize
        manifest=prioritize(attempt,manifest)
        from .static_judge_shards import install as partition_static
        if not two_column_only:
            manifest = partition_static(attempt, batch.read(attempt/'input/pilot_rubric.json'), manifest)
        dump(attempt / 'evidence_manifest.json', manifest)
    gate = batch.validate_capture_bundle(attempt, manifest)
    dump(attempt / 'validation_history/capture_bundle_validation.json', gate)
    if two_column_only and not gate['valid']:
        from .endpoint_judge_partition import partial_gate
        eligible=partial_gate(attempt,batch.read(attempt/'input/pilot_rubric.json'),manifest,gate)
        dump(attempt/'unity_m_partial_delivery.json',{'eligible_parents':eligible,'complete_column_required':True,
            'manifest_sha256':sha(attempt/'evidence_manifest.json'),'capture_gate_sha256':sha(attempt/'validation_history/capture_bundle_validation.json'),
            'blocked_parents':[n for n in manifest['evidence_sets'] if n not in eligible]})
    else:
        assert gate['valid'], gate
    if partial:
        for name, digest in partial['bindings'].items():
            if sha(attempt/name) != digest:
                raise ValueError('Partial recorded judge preserved artifact changed: '+name)
        dump(attempt/'recorded_static_handoff_resume.json', {
            'schema':'unity-recorded-static-handoff-resume.v1',
            'source_attempt':str(recorded), 'judge_attempt':str(attempt),
            'preserved_bindings':partial['bindings'],
            'new_model_calls':0, 'new_recordings':0, 'at':time.time()})
    batch.status(attempt, 'READY_JUDGE', source_attempt=str(recorded), score=None)
    dump(recorded / 'active_background_judge_attempt.json', {'attempt': str(attempt), 'phase': 'ready_judge', 'at': time.time()})
    print('READY_JUDGE ' + str(attempt), flush=True)
    return attempt


if __name__ == '__main__':
    prepare(sys.argv[1])
