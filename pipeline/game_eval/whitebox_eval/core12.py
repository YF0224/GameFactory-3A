"""Source-bound core12 planning contracts, isolated from historical attempts."""
import copy
from pathlib import Path

from ..contract_identity import contract_digest, fingerprint, verify
from .codex import load_plan_json
from .protocol import COLUMNS, sha

VERSION = 'core12-v1'
AUTHORING = 'gamefactory3a.whitebox_core12.v1'
PLANNING_VERSION = 'whitebox-core12-planning.v1'
CORE12_RUBRIC = 'rubric_whitebox_core12/rubric.json'
LEGACY_RUBRIC = 'rubric_whitebox/rubric.json'


def enabled(protocol):
    from . import tiered_core
    return tiered_core.enabled(protocol) or protocol.get('planning_contract', {}).get('planning_version') == PLANNING_VERSION


def validate_contract(contract, *, case_id, engine, requirement_sha256, legacy, legacy_sha256):
    from ...code_gen.playtest.engine_dispatch import resolve_engine
    if not isinstance(contract, dict):
        raise ValueError('core12 contract must be a JSON object')
    assertions = contract.get('assertions')
    if (not isinstance(assertions, list) or any(not isinstance(row, dict)
            or not isinstance(row.get('binding'), dict) for row in assertions)):
        raise ValueError('core12 contract assertions require explicit bindings')
    if (contract.get('schema_version') != 'gamefactory3a.eval_contract.v1'
            or contract.get('version') != VERSION or contract.get('status') != 'frozen'
            or contract.get('stage') != 'whitebox' or contract.get('game_id') != case_id
            or resolve_engine(contract.get('engine', '')) != resolve_engine(engine)):
        raise ValueError('core12 contract identity, game or engine mismatch')
    expected_id = f'{case_id}.whitebox.{VERSION}.{contract_digest(contract)}'
    if contract.get('contract_id') != expected_id:
        raise ValueError('core12 contract content digest mismatch')
    identity = verify(contract)
    if any(row.get('binding', {}).get('contract_identity') != identity
           for row in contract['assertions']):
        raise ValueError('core12 assertion is missing its frozen contract identity')
    policy = contract.get('task_coverage_policy', {})
    source = policy.get('core12', {})
    if (policy.get('authoring_protocol') != AUTHORING
            or source.get('count') != 12 or source.get('scored_atom_count') != 12
            or source.get('source_sha256') != requirement_sha256
            or policy.get('source_inputs', {}).get('general_requirement.txt') != requirement_sha256
            or source.get('previous_contract_id') != legacy.get('contract_id')
            or source.get('previous_json_sha256') != legacy_sha256
            or source.get('original_rubric') != f'test_data/test_samples/{case_id}/rubric_whitebox'):
        raise ValueError('core12 contract source provenance mismatch')
    ids = [row.get('assertion_id') for row in assertions]
    if any(not isinstance(ident, str) or not ident for ident in ids):
        raise ValueError('core12 assertion IDs must be nonempty')
    if len(ids) != len(set(ids)):
        raise ValueError('duplicate core12 assertion IDs')
    endpoints = [row for row in assertions if row.get('table_column') == 'C2']
    selection = source.get('selection', [])
    if (len(endpoints) != 12 or not isinstance(selection, list) or len(selection) != 12
            or any(not isinstance(selected, dict) for selected in selection)):
        raise ValueError('core12 requires exactly twelve source-selected C2 endpoints')
    endpoint_ids = [row['assertion_id'] for row in endpoints]
    if len(endpoint_ids) != len(set(endpoint_ids)):
        raise ValueError('core12 C2 endpoint IDs must be unique')
    subcheck_ids = set()
    selectors = set()
    for endpoint, selected in zip(endpoints, selection):
        binding = endpoint.get('binding')
        if not isinstance(binding, dict):
            raise ValueError('core12 C2 endpoint is missing its binding')
        subchecks = binding.get('subchecks', [])
        if not isinstance(subchecks, list) or any(not isinstance(sub, dict) for sub in subchecks):
            raise ValueError('core12 endpoint subchecks must be a list of checks')
        scored = [sub for sub in subchecks if sub.get('scoring_role') == 'scored']
        if len(scored) != 1:
            raise ValueError('core12 endpoint requires exactly one scored subcheck')
        for sub in subchecks:
            if not sub.get('id') or sub['id'] in subcheck_ids:
                raise ValueError('duplicate or missing core12 subcheck ID')
            subcheck_ids.add(sub['id'])
        sub = scored[0]
        origin = binding.get('core12_source', {})
        selection_key = (origin.get('selector'), sub.get('text'))
        if (origin.get('path') != 'general_requirement.txt'
                or origin.get('sha256') != requirement_sha256
                or not origin.get('selector') or selection_key in selectors
                or origin['selector'] != selected.get('selector')
                or selected.get('source_file') != 'general_requirement.txt'
                or sub.get('origin') != 'general_requirement_core12_selection'
                or sub.get('system') != 'core12' or not sub.get('source_text')
                or sub.get('text') != selected.get('expectation')
                or sub.get('requirement_ids') != selected.get('requirement_ids')
                or endpoint.get('requirement_ids') != selected.get('requirement_ids')):
            raise ValueError('core12 endpoint selection/source mismatch')
        selectors.add(selection_key)
    def retained(document):
        rows = copy.deepcopy([row for row in document['assertions'] if row['table_column'] != 'C2'])
        for row in rows:
            row.get('binding', {}).pop('contract_identity', None)
        return rows
    if retained(contract) != retained(legacy):
        raise ValueError('core12 changed non-C2 assertions outside planning scope')
    return endpoints


def load_sources(entry):
    if entry.get('planning_policy') == 'tiered-core-v1':
        from .tiered_core import load_sources as load_tiered
        return load_tiered(entry)
    case = Path(entry['case_directory']).resolve()
    if case.name != entry['case_id'] or case.parent.name != 'test_samples':
        raise ValueError('core12 must come from the selected test_samples game directory')
    requirement = case/'general_requirement.txt'
    legacy_path = case/LEGACY_RUBRIC
    source_path = case/CORE12_RUBRIC
    scoring_path = Path(entry['frozen_rubric']).resolve()
    if (Path(entry['requirement']).resolve() != requirement
            or sha(requirement) != entry['requirement_sha256']
            or sha(scoring_path) != entry['frozen_sha256']):
        raise ValueError('core12 selected requirement/scoring source mismatch')
    if not source_path.is_file() or source_path.is_symlink() or source_path.parent.is_symlink():
        raise ValueError('core12 rubric.json is missing')
    contract, legacy = load_plan_json(source_path), load_plan_json(legacy_path)
    scoring = load_plan_json(scoring_path)
    if scoring.get('status') != 'frozen' or scoring.get('game_id') != entry['case_id']:
        raise ValueError('core12 historical scoring source identity mismatch')
    validate_contract(contract, case_id=entry['case_id'], engine=entry['actual_engine'],
                      requirement_sha256=sha(requirement), legacy=legacy, legacy_sha256=sha(legacy_path))
    return contract, {
        'planning_version': PLANNING_VERSION, 'version': VERSION, 'authoring_protocol': AUTHORING,
        'case_id': entry['case_id'], 'engine': contract['engine'],
        'contract_id': contract['contract_id'], 'source_path': str(source_path),
        'source_relative_path': CORE12_RUBRIC,
        'rubric_sha256': sha(source_path), 'requirement_sha256': sha(requirement),
        'legacy_contract_id': legacy['contract_id'], 'legacy_rubric_sha256': sha(legacy_path),
        'scoring_contract_id': scoring['contract_id'], 'scoring_rubric_sha256': sha(scoring_path),
        'scoring_source_path': str(scoring_path),
    }


def make_protocol(contract, legacy_protocol, provenance):
    if contract.get('version') == 'tiered-core-v1':
        from .tiered_core import make_protocol as make_tiered
        return make_tiered(contract, legacy_protocol, provenance)
    protocol = copy.deepcopy(legacy_protocol)
    mechanisms = []
    for endpoint in (row for row in contract['assertions'] if row['table_column'] == 'C2'):
        sub = next(sub for sub in endpoint['binding']['subchecks'] if sub.get('scoring_role') == 'scored')
        ident = endpoint['assertion_id']
        mechanisms.append({
            'id': f"atom.{ident}.{sub['id']}", 'column': COLUMNS[1], 'mode': 'runtime',
            'group': ident, 'endpoint_id': ident, 'endpoint_weight': 1.0, 'atom_weight': 1.0,
            'frozen_assertion_id': ident, 'frozen_subcheck_id': sub['id'],
            'requirement_ids': list(sub['requirement_ids']), 'requirement': sub['text'],
            'evidence_types': ['action', 'state', 'event', 'frame', 'log'],
        })
    if len(mechanisms) != 12 or len({row['endpoint_id'] for row in mechanisms}) != 12:
        raise ValueError('core12 protocol must contain exactly twelve unique C2 targets')
    protocol['criteria'] = [row for row in protocol['criteria'] if row['column'] != COLUMNS[1]] + mechanisms
    protocol['planning_contract'] = copy.deepcopy(provenance)
    protocol['mechanic_scope'] = 'core12-v1: twelve source-bound C2 endpoints, one scored subcheck each; context adds no targets.'
    targets(protocol)
    return protocol


def targets(protocol):
    from . import tiered_core
    if tiered_core.enabled(protocol):
        return tiered_core.targets(protocol)
    planning = protocol.get('planning_contract', {})
    if (not enabled(protocol) or planning.get('version') != VERSION
            or planning.get('authoring_protocol') != AUTHORING
            or planning.get('source_relative_path') != CORE12_RUBRIC):
        raise ValueError('plan requires a source-attested core12-v1 attempt; create a new attempt')
    rows = [row for row in protocol['criteria'] if row['column'] == COLUMNS[1]]
    endpoints = [row.get('endpoint_id') for row in rows]
    ids = [row['id'] for row in rows]
    if (len(rows) != 12 or len(set(endpoints)) != 12 or None in endpoints
            or len(set(ids)) != 12 or any(row['id'] != f"atom.{row['endpoint_id']}.{row['frozen_subcheck_id']}"
                                        for row in rows)):
        raise ValueError('core12 pilot must have twelve unique endpoints and scored atoms')
    if any(row.get('column') != COLUMNS[1] or row.get('mode') != 'runtime'
           or row.get('endpoint_weight') != 1.0 or row.get('atom_weight') != 1.0
           for row in rows):
        raise ValueError('core12 pilot contains an invalid C2 target mapping')
    return rows


def verify_attempt(root, engine):
    root = Path(root)
    protocol = load_plan_json(root/'input/pilot_rubric.json')
    from . import tiered_core
    if tiered_core.enabled(protocol):
        return tiered_core.verify_attempt(root, engine)
    targets(protocol)
    manifest = load_plan_json(root/'input_manifest.json')
    contract, provenance = load_sources(manifest['entry'])
    baseline = load_plan_json(root/'input/scoring_pilot_rubric.json')
    provenance['scoring_protocol_sha256'] = fingerprint(baseline)
    if protocol['planning_contract'] != provenance:
        raise ValueError('core12 frozen attempt provenance mismatch')
    if manifest.get('planning_contract') != provenance:
        raise ValueError('core12 input manifest source provenance mismatch')
    from ...code_gen.playtest.engine_dispatch import resolve_engine
    if resolve_engine(engine) != resolve_engine(provenance['engine']):
        raise ValueError('core12 plan engine differs from frozen source')
    if (provenance.get('source_relative_path') != CORE12_RUBRIC
            or sha(root/'input/frozen_rubric.json') != provenance['rubric_sha256']
            or sha(root/'input/legacy_frozen_rubric.json') != provenance['legacy_rubric_sha256']
            or sha(root/'input/scoring_frozen_rubric.json') != provenance['scoring_rubric_sha256']
            or sha(root/'input/requirement.txt') != provenance['requirement_sha256']
            or sha(root/'input/pilot_rubric.json') != manifest['protocol_sha256']):
        raise ValueError('core12 frozen input SHA256 mismatch')
    from . import batch_rubric
    maker = batch_rubric.make_protocol_v4 if baseline.get('version') == batch_rubric.V4_VERSION else batch_rubric.make_protocol
    if baseline != maker(load_plan_json(root/'input/scoring_frozen_rubric.json')):
        raise ValueError('core12 scoring baseline is not derived from its historical frozen rubric')
    expected = make_protocol(contract, baseline, provenance)
    from . import asset_reservation
    if manifest['entry'].get('asset_reservation_policy') is not None:
        if manifest['entry']['asset_reservation_policy'] not in asset_reservation.SUPPORTED_VERSIONS:
            raise ValueError('unknown frozen asset reservation policy')
        asset_reservation.freeze(expected, contract, case_directory=root/'input/asset_tasks',
                                 rubric_sha256=provenance['rubric_sha256'],
                                 version=manifest['entry']['asset_reservation_policy'])
    from . import multiclient
    if manifest['entry'].get('native_sessions'):
        multiclient.freeze(expected,manifest['entry']['native_sessions'])
    asset_reservation.validate(protocol)
    expected['runtime_budget'] = protocol['runtime_budget']
    if 'input_capabilities' in protocol:
        expected['input_capabilities'] = protocol['input_capabilities']
    if protocol != expected:
        raise ValueError('pilot_rubric.json is not derived from the selected core12 contract')
    from . import budgets
    budget = protocol['runtime_budget']
    if budget.get('version') in budgets.UNITY_VERSIONS | {budgets.RECOVERY_VERSION}:
        budgets.validate_pinned_budget(budget)
    elif (engine != 'ue5' or budget.get('version') != budgets.VERSION
          or budget.get('engine') != engine or type(budget.get('gameplay_ms')) is not int
          or budget['gameplay_ms'] <= 0 or budget.get('recording_ms') != budget['gameplay_ms']
          or budget.get('engine_call_ms', 0) < sum(budget.get(key, 0) for key in (
              'import_build_ms', 'launch_wait_ms', 'recording_ms', 'capture_tail_ms'))):
        raise ValueError('core12 runtime budget is unsupported or does not cover execution')
    attempt = load_plan_json(root/'attempt_manifest.json')
    if protocol['runtime_budget'] != attempt['budget']:
        raise ValueError('core12 budget differs from the immutable attempt budget')
    return protocol


def plan_identity(root, protocol, engine):
    manifest = load_plan_json(root/'input_manifest.json')
    constraints = {name: sha(Path(__file__).parent/name) for name in (
        'core12.py', 'core12_planning.py', 'unity_planning.py', 'codex.py', 'runtime.py',
        'batch.py', 'budgets.py', 'tiered_core.py', 'static_existence.py', 'frame_budget.py')}
    planning_version = protocol['planning_contract']['planning_version']
    from . import endpoint_sparse
    if endpoint_sparse.enabled(protocol):
        for name in ('endpoint_sparse.py', 'sparse_evidence.py'):
            constraints[name] = sha(Path(__file__).parent/name)
    from . import multiclient
    if multiclient.enabled(protocol):
        for name in ('multiclient.py', 'action_links.py', 'endpoint_channels.py'):
            constraints[name] = sha(Path(__file__).parent/name)
    return {'planning_version': planning_version,
            'contract_id': protocol['planning_contract']['contract_id'],
            'rubric_sha256': protocol['planning_contract']['rubric_sha256'],
            'project_sha256': fingerprint(manifest['snapshot_hashes']),
            'constraints_sha256': fingerprint({'protocol_sha256': sha(root/'input/pilot_rubric.json'),
                                            'engine': engine, 'planning_version': planning_version,
                                            'constraint_sources': constraints})}


def recorded_plan_identity(root, current, recorded):
    """Validate an unchanged accepted recording across evaluator code updates.

    Execution always uses current constraints. Retrospective capture audits can
    retain a historical constraint hash only while every binding of the prior
    independent acceptance remains unchanged. All other identity fields and all
    current plan/source/evidence validations still apply.
    """
    if recorded == current:
        return current
    if (not isinstance(recorded, dict) or set(recorded) != set(current)
            or any(recorded[key] != value for key, value in current.items()
                   if key != 'constraints_sha256')):
        raise ValueError('recorded plan changed frozen source/contract identity')
    digest = recorded.get('constraints_sha256')
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
        raise ValueError('recorded plan has no historical constraint SHA256')
    root = Path(root).resolve()
    from . import godot_native_telemetry_reuse as telemetry_reuse
    if (root/telemetry_reuse.PROVENANCE).is_file():
        return telemetry_reuse.verify_recorded_identity(root, current, recorded)
    if (root/'qualified_record_reuse.json').is_file():
        from .qualified_history import verify_recorded
        return verify_recorded(root, current, recorded)
    if (root/'native_capture_recovery.json').is_file():
        from .native_capture_recovery import verify_recorded_capture
        return verify_recorded_capture(root, current, recorded)
    accepted = load_plan_json(root/'independent_publication_audit.json')
    required = {'sol_plan.json', 'input/pilot_rubric.json', 'input_manifest.json',
                'runtime/frame_index.jsonl', 'runtime/actions.jsonl',
                'runtime/state_trace.jsonl', 'runtime/event_trace.jsonl'}
    bindings = accepted.get('bindings', {})
    if (accepted.get('valid') is not True
            or Path(accepted.get('source_run', '')).resolve() != root
            or accepted.get('capture', {}).get('valid') is not True
            or accepted.get('capture', {}).get('counts', {}).get('plan_valid') is not True
            or not required <= bindings.keys()):
        raise ValueError('recorded constraint identity lacks independent capture acceptance')
    from .integrity import audit_bindings
    actual = audit_bindings(root)
    if any(actual.get(name) != digest for name, digest in bindings.items()):
        raise ValueError('recorded capture changed since independent acceptance')
    return recorded
