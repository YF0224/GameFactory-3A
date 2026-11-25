"""Recover deterministic wire defects without another planner call or new inputs.

Raw replies, call deadlines and planning identity remain immutable. This module
never invents missing actions, endpoint conditions, source bindings or observations.
An existing same-game Sol checklist can be reused verbatim with its source SHA.
"""
import copy
import json
import re
from pathlib import Path

from .protocol import dump, sha

RECEIPT = 'plan_normalization.json'
VERSION = 'whitebox-unity-plan-normalization.v1'


def _loads(text):
    from .codex import unique_json_object, reject_json_constant
    return json.loads(text, object_pairs_hook=unique_json_object,
                      parse_constant=reject_json_constant)



def parse_saved_response(response, root):
    try:
        value = _loads(Path(response).read_text())
    except (ValueError, TypeError):
        return parse_reply(Path(response).read_text())
    if isinstance(value, dict) and set(value) == {'base_sha256', 'edits'}:
        from . import plan_patches
        base = Path(root)/'model_calls/plan/response.json'
        if plan_patches.loads(base.read_bytes()).get('probes') == []:
            from .empty_probe_patch import replay
        else:
            from .saved_plan_field_patch import replay
        return replay(response, root)
    return parse_reply(Path(response).read_text())


def _placeholder_copy(original, duplicate):
    """The duplicate can erase content, but cannot contradict the populated root."""
    if duplicate == '\x00':
        return 1
    if isinstance(duplicate, dict):
        if not isinstance(original, dict) or duplicate.keys() != original.keys():
            raise ValueError('Embedded skeleton has different fields')
        return sum(_placeholder_copy(original[k], v) for k, v in duplicate.items())
    if isinstance(duplicate, list):
        if not isinstance(original, list):
            raise ValueError('Embedded skeleton changes a field type')
        if not duplicate:
            return 0
        if len(original) != len(duplicate):
            raise ValueError('Embedded skeleton has conflicting items')
        return sum(_placeholder_copy(a, b) for a, b in zip(original, duplicate))
    if type(original) is not type(duplicate) or original != duplicate:
        raise ValueError('Embedded skeleton contradicts substantive planning data')
    return 0


def parse_reply(text):
    try:
        return _loads(text), []
    except (ValueError, TypeError):
        pass
    # A known wire failure embeds a second output skeleton inside the final
    # static_findings string. Accept only a completely populated root prefix and
    # a single structurally matching placeholder skeleton consuming the suffix.
    marker = re.search(r'"static_findings"\s*:\s*"', text)
    if marker is None:
        raise ValueError('No deterministic complete plan can be recovered')
    prefix = _loads(text[:marker.start()].rstrip().removesuffix(',')+'}')
    if not prefix.get('probes') or not prefix.get('capture_plan'):
        raise ValueError('Incomplete planning prefix')
    matches = list(re.finditer(r'\{"capture_plan"\s*:', text[marker.end():]))
    if len(matches) != 1:
        raise ValueError('Ambiguous embedded plan skeleton')
    offset = marker.end()+matches[0].start()
    duplicate = _loads(text[offset:])
    prose = {'static_findings', 'summary', 'watchers'}
    if (set(duplicate)-prose != set(prefix)
            or duplicate.get('planning_identity') != prefix.get('planning_identity')
            or duplicate.get('probes') != [] or duplicate.get('watchers') != []):
        raise ValueError('Embedded object is not a redundant wire skeleton')
    count = _placeholder_copy(prefix, {k:v for k,v in duplicate.items() if k not in prose})
    if not count or '\x00' in duplicate['summary'] or '\x00' in duplicate['static_findings']:
        raise ValueError('Missing substantive plan narrative')
    narrative = _loads('"'+text[marker.end():offset]+'"')
    prefix.update(static_findings=narrative+duplicate['static_findings'],
                  summary=duplicate['summary'], watchers=[])
    return prefix, [{'kind':'remove_redundant_embedded_placeholder_skeleton',
        'skeleton_offset':offset, 'placeholder_count':count,
        'substantive_prefix_preserved':True}]


def normalize_coverage(plan, protocol):
    """Describe the declared observation interval, not the rest of a shared probe.

    Native timeline and endpoint validators independently check the trimmed
    interval, last actual input, settling time, source and rubric. Never move a
    sample or remove a probe/action/condition to satisfy validation.
    """
    result = copy.deepcopy(plan)
    coverage = result['coverage']
    if isinstance(coverage, dict):
        from .core12 import targets
        windows = {row['id']:coverage[row['endpoint_id']] for row in targets(protocol)}
    else:
        windows = {row['atom_id']:row for row in coverage}
    changes = []
    for ident, endpoint in result['capture_plan']['endpoints'].items():
        window = windows[ident]
        stamp = endpoint['at_ms']
        if (window['status'] == 'PLANNED' and window['start_ms'] <= stamp
                and stamp < window['end_ms']-500):
            old = window['end_ms']
            window['end_ms'] = stamp+150
            changes.append({'kind':'bound_coverage_to_declared_observation',
                'endpoint_id':ident, 'old_end_ms':old, 'end_ms':stamp+150,
                'sample_at_ms':stamp, 'actions_and_sample_unchanged':True})
    return result, changes


def normalize_source_paths(plan, root):
    """Remove only a redundant project/ prefix backed by frozen file hashes.

    No search, missing-file substitution, action change or source-claim repair.
    The immutable response remains the source for independent receipt replay.
    """
    from .protocol import checked_path
    result = copy.deepcopy(plan)
    project = Path(root)/'input/project'
    changes = []
    frozen = None
    for ident, endpoint in result.get('capture_plan', {}).get('endpoints', {}).items():
        for index, reference in enumerate(endpoint.get('source_evidence', [])):
            original = reference.get('path')
            if not isinstance(original, str) or not original.startswith('project/'):
                continue
            relative = original[len('project/'):]
            if (not relative or any(part in ('', '.', '..') for part in relative.split('/'))
                    or '\\' in relative or Path(relative).is_absolute()):
                raise ValueError('Unsafe project-prefixed source reference: '+original)
            # An existing literal path makes stripping ambiguous, even if its
            # content happens to match. Never choose between two real files.
            literal = project/original
            if literal.exists() or literal.is_symlink():
                raise ValueError('Ambiguous project-prefixed source reference: '+original)
            path = checked_path(project, relative)
            if frozen is None:
                frozen = _loads((Path(root)/'input_manifest.json').read_text())['snapshot_hashes']
            digest = sha(path)
            if digest != reference.get('sha256') or frozen.get(relative) != digest:
                raise ValueError('Project-prefixed source SHA differs from frozen source: '+original)
            reference['path'] = relative
            changes.append({'kind':'normalize_frozen_source_path', 'endpoint_id':ident,
                'reference_index':index, 'original_path':original, 'path':relative,
                'sha256':digest, 'source_claim_and_actions_unchanged':True})
    return result, changes



def normalize_launch_scene(plan, root):
    """Expand only a unique scene shorthand already bound by launch_source."""
    from .protocol import checked_path
    result = copy.deepcopy(plan)
    scene, source = result.get('launch_scene'), result.get('launch_source')
    if (not isinstance(scene, str) or not isinstance(source, str) or '/' in scene
            or '\\' in scene or source == scene or not source.startswith('Assets/')
            or Path(source).suffix not in {'.unity', '.scene'}
            or scene not in {Path(source).stem, Path(source).name}):
        return result, []
    frozen = _loads((Path(root)/'input_manifest.json').read_text())['snapshot_hashes']
    matches = [name for name in frozen if name.startswith('Assets/')
               and Path(name).suffix in {'.unity','.scene'}
               and scene in {Path(name).stem,Path(name).name}]
    if matches != [source]:
        return result, []
    path = checked_path(Path(root)/'input/project', source)
    if sha(path) != frozen[source]:
        raise ValueError('Scene shorthand source differs from frozen delivery')
    result['launch_scene'] = source
    return result, [{'kind':'expand_unique_frozen_scene_shorthand', 'original':scene,
                     'scene':source, 'sha256':frozen[source],
                     'launch_source_and_actions_unchanged':True}]


def normalize_shared_conditions(plan, protocol, root):
    """Reuse the authoritative same-game checklist, never regenerate its rules.

    Legacy recovery attempts may have copied input before a preceding attempt
    froze the shared checklist. Bind that existing Sol contract before actions;
    preserve the new reply and record every replaced checklist verbatim.
    Requirements, routes, actions, timing and claimed reachability do not change.
    """
    from . import endpoint_sparse
    root = Path(root)
    result = copy.deepcopy(plan)
    if not endpoint_sparse.closed_endpoints(protocol):
        return result, []
    shared = root/'input/endpoint_conditions.json'
    frozen_input = shared.is_file()
    if not frozen_input:
        shared = endpoint_sparse.shared_conditions_path(root.parent.parent, protocol)
    if not shared.is_file():
        return result, []
    contract = _loads(shared.read_text())
    endpoints = result['capture_plan']['endpoints']
    if (contract.get('version') != endpoint_sparse.CAPTURE_VERSION
            or contract.get('case_id') != protocol['case_id']
            or set(contract.get('endpoints', {})) != set(endpoints)):
        raise ValueError('Shared endpoint contract differs from frozen game/endpoint set')
    changes = []
    digest = sha(shared)
    for ident, endpoint in endpoints.items():
        canonical = contract['endpoints'][ident]
        if endpoint['rubric']['requirement'] != canonical['requirement']:
            raise ValueError('Shared endpoint requirement differs from saved plan')
        if endpoint['rubric'] != canonical:
            # Explicit metadata repair replaces non-rubric citations with the
            # exact frozen requirement below. If that very result was just
            # frozen as the shared contract, retain the original repair receipt
            # instead of adding a new normalization on the next verification.
            repaired = copy.deepcopy(endpoint['rubric'])
            context = (root/'input/requirement.txt').read_text()+'\n'+(root/'input/frozen_rubric.json').read_text()
            basis = repaired.get('rubric_basis', [])
            if ((root/'route_metadata_repair.json').is_file() and basis
                    and any(text not in context and text != canonical['requirement'] for text in basis)):
                repaired['rubric_basis'] = [canonical['requirement']]
                if repaired == canonical and not frozen_input:
                    continue
            changes.append({'kind':'reuse_shared_frozen_endpoint_conditions',
                'endpoint_id':ident, 'contract_path':str(shared.resolve()),
                'contract_sha256':digest, 'original_rubric':copy.deepcopy(endpoint['rubric']),
                'rubric':copy.deepcopy(canonical), 'actions_and_requirement_unchanged':True})
            endpoint['rubric'] = copy.deepcopy(canonical)
    return result, changes


def normalize_reply(plan, protocol, root):
    from .unsupported_inputs import normalize
    plan = copy.deepcopy(plan)
    prose_changes = []
    if isinstance(plan.get('static_findings'), (list, dict)):
        original = plan['static_findings']
        plan['static_findings'] = json.dumps(original, ensure_ascii=False, sort_keys=True)
        prose_changes.append({'kind':'serialize_static_findings_narrative',
            'original':original, 'text':plan['static_findings'], 'planning_data_unchanged':True})
    from .incomplete_unity_plan import normalize as retain_usable_route
    plan, incomplete = retain_usable_route(plan, protocol, root)
    result, omitted = normalize(plan, protocol, root)
    omitted = prose_changes+incomplete+omitted
    result, source_paths = normalize_source_paths(result, root)
    omitted += source_paths
    result, scene_names = normalize_launch_scene(result, root)
    omitted += scene_names
    result, shared_conditions = normalize_shared_conditions(result, protocol, root)
    omitted += shared_conditions
    from .plan_route_metadata import normalize as repair_metadata
    result, metadata = repair_metadata(result, protocol, root)
    omitted += metadata
    observation = Path(root)/'partial_observation_recovery.json'
    if observation.is_file():
        from .partial_observation_recovery import verify as verify_observation
        verify_observation(root)
        result, observation_changes = retain_usable_route(result, protocol, root)
        omitted += observation_changes
    # An explicitly unreachable item has no executable route. Preserve its
    # source-grounded limitation as the route explanation; create no actions.
    for ident, endpoint in result.get('capture_plan', {}).get('endpoints', {}).items():
        if (endpoint.get('reachability') == 'UNREACHABLE'
                and not endpoint.get('legal_route', '').strip()
                and endpoint.get('limitation', '').strip()
                and endpoint.get('source_evidence')):
            endpoint['legal_route'] = 'UNREACHABLE: '+endpoint['limitation']
            omitted.append({'kind':'unreachable_route_explanation','endpoint_id':ident,
                'original_legal_route':'','legal_route':endpoint['legal_route'],
                'actions_and_conditions_unchanged':True})
    result, timed = normalize_coverage(result, protocol)
    if (Path(root)/'unsupported_input_policy.json').is_file():
        required = 2500+sum(max(100,step['duration_ms']) if step['kind']=='input' else step['duration_ms']
            for probe in result['probes'] for step in probe['steps'])
        if result['max_duration_ms'] < required <= protocol['runtime_budget']['gameplay_ms']:
            timed.append({'kind':'correct_declared_duration_sum','original_ms':result['max_duration_ms'],
                          'required_ms':required,'frozen_budget_ms':protocol['runtime_budget']['gameplay_ms'],
                          'actions_and_samples_unchanged':True})
            result['max_duration_ms'] = required
    return result, omitted+timed


def candidates(root):
    root = Path(root)
    # A completed correction takes priority. A timed-out correction does not
    # erase a complete earlier reply; no invocation is created or retried here.
    folders = sorted((root/'model_calls').glob('plan*'), reverse=True)
    if any(p.is_dir() and not (p/'invocation.json').exists() for p in folders):
        return []
    result = []
    for folder in folders:
        response = folder/'response.json'
        invocation = folder/'invocation.json'
        if invocation.is_file() and response.is_file():
            call = _loads(invocation.read_text())
            if call.get('exit_code') == 0:
                result.append(response)
    return result


class InvalidSavedPlan(ValueError):
    """A completed planner response fails substantive plan validation."""


def assessment(root):
    """Read-only qualification, including actual action/endpoint validation.

    Finding a wire repair alone does not establish that a response is usable.
    Failed source/identity verification propagates as a harness error, rather
    than being mistaken for invalid model output.
    """
    from . import batch, core12
    root = Path(root)
    if (root/'sol_plan.json').exists() or (root/'background_record').exists():
        return {'protected': True, 'responses': [], 'recoverable': False}
    batch.verify_inputs(root)
    protocol = core12.verify_attempt(root, 'unity3d')
    reports = []
    for response in candidates(root):
        report = {'response':str(response.relative_to(root)), 'response_sha256':sha(response),
                  'invocation_sha256':sha(response.parent/'invocation.json'),
                  'schema_sha256':sha(response.parent/'schema.json'), 'valid':False}
        stage = 'parse'
        try:
            plan, parsed = parse_saved_response(response, root)
            normalized, timed = normalize_reply(plan, protocol, root)
            report['changes'] = parsed+timed
            stage = 'operation_validation'
            batch.validate_operation_plan(root, normalized, 'unity3d', record_validation=False)
            report['valid'] = True
        except (ValueError, KeyError, TypeError) as exc:
            report.update(rejection_stage=stage, error=str(exc))
        reports.append(report)
    return {'protected':False, 'responses':reports,
            'recoverable':any(r['valid'] for r in reports),
            'substantively_invalid':bool(reports) and all(
                not r['valid'] and r.get('rejection_stage') == 'operation_validation' for r in reports)}


def recoverable(root):
    try:
        return assessment(root)['recoverable']
    except (OSError, ValueError, KeyError, TypeError):
        return False



def ready_for_bounded_resume(root):
    """A verified saved normalization is also resumable before any capture.

    Qualification itself may have already materialized the deterministic plan.
    Never re-open a capture or bypass the queue's once-only recovery counter.
    """
    root = Path(root)
    if (root/'background_record').exists():
        return False
    if not (root/'sol_plan.json').exists():
        return recoverable(root)
    if not (root/RECEIPT).is_file():
        return False
    try:
        return verify(root) is True
    except (OSError, ValueError, KeyError, TypeError):
        return False


def accept(root):
    from . import batch, core12
    root = Path(root)
    if (root/'background_record').exists():
        raise ValueError('Existing capture is protected')
    if (root/'sol_plan.json').exists():
        verify(root)
        return batch.validate_operation_plan(root, batch.read(root/'sol_plan.json'), 'unity3d')
    protocol = core12.verify_attempt(root, 'unity3d')
    errors = []
    for response in candidates(root):
        try:
            plan, parsed = parse_saved_response(response, root)
            normalized, timed = normalize_reply(plan, protocol, root)
            validated = batch.validate_operation_plan(root, normalized, 'unity3d')
        except (ValueError, KeyError, TypeError) as exc:
            errors.append(str(exc))
            continue
        dump(root/'sol_plan.json', validated)
        from .endpoint_sparse import freeze_conditions
        freeze_conditions(root, protocol, validated)
        dump(root/RECEIPT, {'version':VERSION, 'response':str(response.relative_to(root)),
            'response_sha256':sha(response), 'schema_sha256':sha(response.parent/'schema.json'),
            'invocation_sha256':sha(response.parent/'invocation.json'),
            'plan_sha256':sha(root/'sol_plan.json'), 'changes':parsed+timed,
            'planning_identity':validated['planning_identity'],
            'model_calls_added':0, 'raw_response_and_deadlines_unchanged':True,
            'actions_samples_rubric_and_source_bindings_unchanged':not any(
                change['kind'] in {'replay_saved_empty_probe_correction', 'replay_saved_field_correction'} for change in parsed) and not any(
                change['kind'] in {'omit_unsupported_input', 'reuse_shared_frozen_endpoint_conditions', 'recompute_route_metadata',
                    'withdraw_incomplete_endpoint_claim', 'schedule_retained_route_observations', 'map_retained_observation_windows'}
                for change in timed),
            'partial_observation_recovery_sha256':sha(root/'partial_observation_recovery.json')
                if (root/'partial_observation_recovery.json').is_file() else None,
            'route_metadata_policy_sha256':sha(root/'route_metadata_repair.json')
                if (root/'route_metadata_repair.json').is_file() else None,
            'unsupported_input_policy_sha256':sha(root/'unsupported_input_policy.json')
                if (root/'unsupported_input_policy.json').is_file() else None})
        batch.write_operation_report(root, validated)
        verify(root)
        return validated
    error_type = InvalidSavedPlan if assessment(root).get('substantively_invalid') else ValueError
    raise error_type('Saved plan cannot be deterministically normalized: '+'; '.join(errors))


def verify(root):
    """Reconstruct from the immutable reply; compare all substantive plan values."""
    from . import batch, core12, unity_planning
    from .codex import decode_plan_coverage
    root = Path(root)
    receipt = batch.read(root/RECEIPT)
    response = root/receipt['response']
    if response.resolve().parent.parent != (root/'model_calls').resolve():
        raise ValueError('Plan normalization response escaped model call directory')
    for path, key in ((response,'response_sha256'), (response.parent/'schema.json','schema_sha256'),
                      (response.parent/'invocation.json','invocation_sha256'), (root/'sol_plan.json','plan_sha256')):
        if sha(path) != receipt[key]:
            raise ValueError('Normalized plan source changed: '+str(path))
    policy = root/'unsupported_input_policy.json'
    if receipt.get('unsupported_input_policy_sha256') != (sha(policy) if policy.is_file() else None):
        raise ValueError('Unsupported-input authorization changed')
    metadata_policy = root/'route_metadata_repair.json'
    if receipt.get('route_metadata_policy_sha256') != (sha(metadata_policy) if metadata_policy.is_file() else None):
        raise ValueError('Route metadata authorization changed')
    observation = root/'partial_observation_recovery.json'
    if receipt.get('partial_observation_recovery_sha256') != (sha(observation) if observation.is_file() else None):
        raise ValueError('Partial observation recovery binding changed')
    protocol = core12.verify_attempt(root,'unity3d')
    plan, parsed = parse_saved_response(response, root)
    result, timed = normalize_reply(plan,protocol,root)
    if isinstance(result['coverage'], dict):
        result, _ = unity_planning.expand(result,protocol)
    result = decode_plan_coverage(result)
    from .plan_invocation_identity import resolve as invocation_identity
    identity = invocation_identity(root,core12.plan_identity(root,protocol,'unity3d'),result.get('planning_identity'))
    if (receipt['version'] != VERSION or receipt['changes'] != parsed+timed
            or result != batch.read(root/'sol_plan.json')
            or receipt['planning_identity'] != identity):
        raise ValueError('Plan normalization no longer reproduces the saved plan')
    return True


def audit_binding(root):
    """Independent audit also binds the raw reply behind a packaged recording."""
    from . import batch
    root = Path(root)
    if (root/RECEIPT).is_file():
        return verify(root)
    copied = root/'recovery_source'/RECEIPT
    if copied.is_file():
        source = Path(batch.read(root/'recorded_capture_provenance.json')['source_attempt'])
        if sha(copied) != sha(source/RECEIPT):
            raise ValueError('Packaged normalization receipt differs from original')
        verify(source)
        preserved = root/'recovery_source/recorded_sol_plan.original.json'
        if preserved.is_file() and batch.read(preserved) != batch.read(source/'sol_plan.json'):
            raise ValueError('Packaged original plan differs from normalized source')
    return True
