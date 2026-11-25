"""Keep invocation identity stable across tool edits, never across input/contract changes."""
import re
from pathlib import Path

from .protocol import dump, sha

VERSION = 'whitebox-invocation-constraints-identity.v1'
REPORT = 'validation_history/plan_invocation_identity.json'


def invocation_folder(root):
    """Keep legacy plan precedence; recognize one explicit Mechanic invocation."""
    root=Path(root)
    legacy=root/'model_calls/plan'
    if (legacy/'schema.json').is_file():return legacy
    candidates=[root/'model_calls'/name for name in (
        'plan_v3_outcome_frame_v1','plan_v3_fixed_context',
        'plan_v3_observation_recovery_v1','plan_v3_complete_capture_map')
        if (root/'model_calls'/name/'schema.json').is_file()]
    if len(candidates)>1:
        raise ValueError('Ambiguous Mechanic planner invocation schemas')
    return candidates[0] if candidates else legacy


def resolve(root, current, recorded, *, write=False):
    """Only the auxiliary tool fingerprint may use the exact submitted schema value.

    Real source, rubric, protocol/budgets and all actions still undergo the normal
    validators. Nothing in the model response or frozen identity is rewritten.
    """
    from . import batch
    root = Path(root)
    if not isinstance(recorded, dict):
        return current
    if recorded == current and (not write or not (root/'model_calls/plan/schema.json').is_file()):
        return current
    if (set(recorded) != set(current) or any(recorded[k] != current[k]
            for k in current if k != 'constraints_sha256')):
        return current  # Preserve the ordinary strict error for real identity changes.
    digest = recorded.get('constraints_sha256')
    if not isinstance(digest, str) or re.fullmatch(r'[0-9a-f]{64}', digest) is None:
        return current
    call = invocation_folder(root)
    schemas = [p for p in (call/'schema.json', call/'original_schema.json') if p.is_file()]
    if not schemas:
        return current
    bindings = {}
    for path in schemas:
        schema = batch.read(path)
        properties = schema.get('properties', {}).get('planning_identity', {}).get('properties', {})
        expected = {}
        for key, value in properties.items():
            if value.get('type') != 'string' or len(value.get('enum', [])) != 1:
                raise ValueError('Submitted plan identity is not a frozen singleton: '+key)
            expected[key] = value['enum'][0]
        if expected != recorded:
            raise ValueError('Plan identity does not match its original invocation schema')
        bindings[str(path.resolve())] = sha(path)
    report = {'version':VERSION, 'invocation_identity':recorded,
              'current_validator_identity':current, 'bindings':bindings,
              'allowed_difference':'constraints_sha256 only; evaluator implementation fingerprint',
              'source_rubric_protocol_actions_and_evidence_checks_preserved':True,
              'model_response_and_frozen_identity_unchanged':True}
    if write:
        dump(root/REPORT, report)
    return dict(recorded)


def audit_binding(root):
    """Bind the compatibility decision and submitted schemas after packaging too."""
    from . import batch, core12
    root = Path(root)
    candidates = [root]
    provenance = root/'recorded_capture_provenance.json'
    if provenance.is_file():
        candidates.append(Path(batch.read(provenance)['source_attempt']))
    result = {}
    for source in candidates:
        path = source/REPORT
        if not path.is_file():
            continue
        report = batch.read(path)
        engine = batch.plan_engine(source)
        protocol = core12.verify_attempt(source, engine)
        batch.verify_inputs(source)
        current = core12.plan_identity(source, protocol, engine)
        original = report['invocation_identity']
        if (report.get('version') != VERSION
                or report.get('model_response_and_frozen_identity_unchanged') is not True
                or report.get('source_rubric_protocol_actions_and_evidence_checks_preserved') is not True
                or resolve(source, current, original) != original
                or any(report['current_validator_identity'].get(k) != original[k]
                       for k in original if k != 'constraints_sha256')):
            raise ValueError('Invalid invocation identity compatibility receipt')
        call=invocation_folder(source)
        allowed = {(call/name).resolve()
                   for name in ('schema.json','original_schema.json')
                   if (call/name).is_file()}
        if set(map(Path, report['bindings'])) != allowed:
            raise ValueError('Invocation identity schema bindings changed')
        for name, digest in report['bindings'].items():
            if sha(Path(name)) != digest:
                raise ValueError('Invocation identity submitted schema changed')
            result[name] = digest
        result[str(path.resolve())] = sha(path)
    from .native_saved_plan_recovery import audit_binding as native_handoff_bindings
    result.update(native_handoff_bindings(root))
    from .native_diagnostic_plan_recovery import audit_binding as diagnostic_bindings
    result.update(diagnostic_bindings(root))
    from .native_static_partition_recovery import RECEIPT as native_partition, verify as verify_native_partition
    if (root/native_partition).is_file():result.update(verify_native_partition(root))
    from .native_service_recovery import RECEIPT as native_service, verify as verify_native_service
    if (root/native_service).is_file():result.update(verify_native_service(root))
    return result


def recorded_derivation_identity(root, current, recorded):
    """Revalidate retained judge-only plan derivation across evaluator tool edits.

    The derivation and its source plan predate judging. Only the evaluator hash
    may differ from today's identity; native actions and all frozen inputs are
    checked again, without rewriting either identity or issuing a plan call.
    """
    from . import batch
    from .recorded_import_review import reviewed_import_paths
    root = Path(root).resolve()
    receipt = batch.read(root/'recorded_plan_derivation.json')
    source = Path(receipt['source_attempt']).resolve()
    version=batch.read(root/'input_manifest.json')['entry'].get('recorded_source_version',{})
    unity_m='unity_m_input_materialization' in version
    if unity_m:
        from .unity_m_evidence import qualify_recorded
        qualify_recorded(source)
        if root.parent!=source.parent.parent/'recovery_runs':
            raise ValueError('Unity M derived identity outside frozen workspace')
    if (receipt.get('schema') != 'unity-core12-recorded-plan-derivation.v1'
            or source == root or (not unity_m and source.parent != root.parent)
            or receipt.get('actions_and_coverage_unchanged') is not True
            or receipt.get('model_response_preserved') is not True
            or receipt.get('new_model_call') is not False
            or batch.read(root/'recorded_capture_provenance.json')['source_attempt'] != str(source)):
        raise ValueError('Invalid recorded judge plan derivation')
    if (not isinstance(recorded, dict) or recorded != receipt.get('derived_identity')
            or set(current) != set(recorded)
            or any(current[k] != recorded[k] for k in current if k != 'constraints_sha256')
            or re.fullmatch(r'[0-9a-f]{64}', str(recorded.get('constraints_sha256'))) is None):
        raise ValueError('Recorded judge derivation changed frozen identity')
    original = batch.read(source/'sol_plan.json')
    derived = batch.read(root/'sol_plan.json')
    expected=original
    if unity_m:
        from .unity_m_input_adapter import materialization_proof, derive_endpoint_references
        proof=materialization_proof(source)
        if proof!=version['unity_m_input_materialization']:raise ValueError('Native input proof changed')
        expected=derive_endpoint_references(source,root,original,proof)
    if (sha(source/'sol_plan.json') != receipt['source_plan_sha256']
            or sha(root/'recovery_source/recorded_sol_plan.original.json') != sha(source/'sol_plan.json')
            or original.get('planning_identity') != receipt.get('original_identity')
            or derived.get('planning_identity') != recorded
            or {k:v for k,v in expected.items() if k != 'planning_identity'} !=
               {k:v for k,v in derived.items() if k != 'planning_identity'}):
        raise ValueError('Recorded judge derivation changed source plan or native route')
    batch.verify_inputs(root)
    batch.verify_inputs(source)
    batch.validate_operation_plan(source, original, 'unity3d', record_validation=False)
    for name in ('frozen_rubric.json', 'pilot_rubric.json', 'scoring_frozen_rubric.json',
                 'scoring_pilot_rubric.json', 'legacy_frozen_rubric.json'):
        if sha(root/'input'/name) != sha(source/'input'/name):
            raise ValueError('Recorded judge derivation changed rubric/budget: '+name)
    before = batch.read(source/'input_manifest.json')['snapshot_hashes']
    after = batch.read(root/'input_manifest.json')['snapshot_hashes']
    changed = {name for name in before.keys() | after.keys() if before.get(name) != after.get(name)}
    allowed = {'ProjectSettings/GraphicsSettings.asset', 'ProjectSettings/QualitySettings.asset',
               'ProjectSettings/ProjectVersion.txt', 'Packages/packages-lock.json'}
    allowed.update(reviewed_import_paths(source))
    from .unity_admission_metadata import plan_paths
    allowed.update(plan_paths(root, source, before, after))
    from .unity_authored_settings_import import plan_paths as authored_settings_paths
    allowed.update(authored_settings_paths(root, source, before, after))
    from .unity_native_import_metadata import plan_paths as native_import_paths
    allowed.update(native_import_paths(root, source, before, after))
    if unity_m:
        allowed.update(row['path'] for row in proof['changes'] if not row['added'])
    if changed != set(receipt['changed_import_metadata']) or changed - allowed:
        raise ValueError('Recorded judge derivation changed unreviewed project input')
    return dict(recorded)
