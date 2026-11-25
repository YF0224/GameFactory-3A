"""Canonical tiered C2 sources; historical core12 contracts remain separate."""
import copy
import re
from pathlib import Path

from ..contract_identity import contract_digest, fingerprint, verify
from .codex import load_plan_json
from .protocol import COLUMNS, sha

VERSION = 'tiered-core-v1'
AUTHORING = 'gamefactory3a.whitebox_tiered_core.v1'
PLANNING_VERSION = 'whitebox-tiered-core-planning.v1'
RUBRIC = 'rubric_whitebox_core/rubric.json'
COUNTS = {'S': 8, 'M': 12, 'L-Regular': 20, 'L-Stress': 25}
PLAN_SECONDS = {'S': 600, 'M': 900, 'L-Regular': 1500, 'L-Stress': 1800}


def canonical_tier(text):
    matches = re.findall(r'(?m)^tier:\s*([^\s#]+)', text)
    if len(matches) != 1:
        raise ValueError('canonical requirement must declare exactly one tier')
    tier = 'L-Regular' if matches[0] == 'L' else matches[0]
    if tier not in COUNTS:
        raise ValueError('unsupported canonical tier: ' + tier)
    return tier


def enabled(protocol):
    return protocol.get('planning_contract', {}).get('planning_version') == PLANNING_VERSION


def retained(contract):
    rows = copy.deepcopy([row for row in contract['assertions'] if row['table_column'] != 'C2'])
    for row in rows:
        row.get('binding', {}).pop('contract_identity', None)
    return rows


def validate_contract(contract, *, case_id, engine, requirement, legacy, legacy_sha256):
    from ...code_gen.playtest.engine_dispatch import resolve_engine
    tier = canonical_tier(requirement.read_text())
    count = COUNTS[tier]
    if (contract.get('schema_version') != 'gamefactory3a.eval_contract.v1'
            or contract.get('version') != VERSION or contract.get('status') != 'frozen'
            or contract.get('stage') != 'whitebox' or contract.get('game_id') != case_id
            or resolve_engine(contract.get('engine', '')) != resolve_engine(engine)
            or contract.get('contract_id') != f'{case_id}.whitebox.{VERSION}.{contract_digest(contract)}'):
        raise ValueError('tiered core contract identity/game/engine/digest mismatch')
    identity = verify(contract)
    assertions = contract['assertions']
    ids = [row['assertion_id'] for row in assertions]
    if len(ids) != len(set(ids)) or any(row['binding'].get('contract_identity') != identity for row in assertions):
        raise ValueError('tiered core duplicate IDs or missing frozen bindings')
    policy = contract['task_coverage_policy']
    source = policy.get('tiered_core', {})
    if (policy.get('authoring_protocol') != AUTHORING or source.get('tier') != tier
            or source.get('count') != count or source.get('scored_atom_count') != count
            or source.get('source_sha256') != sha(requirement)
            or policy.get('source_inputs', {}).get('general_requirement.txt') != sha(requirement)
            or source.get('previous_contract_id') != legacy['contract_id']
            or source.get('previous_json_sha256') != legacy_sha256
            or source.get('original_rubric') != f'test_data/test_samples/{case_id}/rubric_whitebox'):
        raise ValueError('tiered core canonical tier/source provenance mismatch')
    endpoints = [row for row in assertions if row['table_column'] == 'C2']
    selection = source.get('selection', [])
    if len(endpoints) != count or len(selection) != count:
        raise ValueError('tiered core endpoint/selection count differs from canonical tier')
    sub_ids, questions = set(), set()
    from ..preparation.requirement_model import CaseModel
    model = CaseModel(requirement.parent)
    for endpoint, selected in zip(endpoints, selection):
        binding = endpoint['binding']
        subchecks = binding['subchecks']
        if len(subchecks) != 1 or subchecks[0].get('scoring_role') != 'scored':
            raise ValueError('tiered core requires exactly one scored atom per endpoint')
        sub = subchecks[0]
        requirements = [model.requirement(ident) for ident in sub.get('requirement_ids', [])]
        if (not requirements or not all(requirements)
                or sub.get('source_text') != '\n\n'.join(row.text for row in requirements)
                or endpoint.get('max_points') != 1.0
                or endpoint.get('scoring_rule') != {'kind':'tiered_mean','subitems':1,'tiers':{'FAIL':0.0,'PASS':1.0}}):
            raise ValueError('tiered core canonical text or equal endpoint weight mismatch')
        origin = binding.get('tiered_core_source', {})
        key = (origin.get('selector'), sub.get('text'))
        if (sub.get('id') in sub_ids or not sub.get('id') or key in questions
                or not endpoint['assertion_id'].startswith(case_id + '.WB.TC2.')
                or origin.get('path') != 'general_requirement.txt' or origin.get('sha256') != sha(requirement)
                or not origin.get('selector') or origin['selector'] != selected.get('selector')
                or selected.get('source_file') != 'general_requirement.txt'
                or sub.get('origin') != 'general_requirement_tiered_core_selection'
                or sub.get('system') != VERSION or not sub.get('source_text')
                or sub.get('text') != selected.get('expectation')
                or sub.get('requirement_ids') != selected.get('requirement_ids')
                or endpoint.get('requirement_ids') != selected.get('requirement_ids')
                or not selected.get('selection_reason')):
            raise ValueError('tiered core selected atom/source binding mismatch')
        sub_ids.add(sub['id'])
        questions.add(key)
    if retained(contract) != retained(legacy):
        raise ValueError('tiered core changed non-C2 baseline assertions')
    return endpoints


def load_sources(entry):
    case = Path(entry['case_directory']).resolve()
    requirement = case / 'general_requirement.txt'
    source = case / RUBRIC
    legacy_path = case / 'rubric_whitebox/rubric.json'
    scoring = Path(entry['frozen_rubric']).resolve()
    if (case.name != entry['case_id'] or case.parent.name != 'test_samples'
            or Path(entry['requirement']).resolve() != requirement
            or sha(requirement) != entry['requirement_sha256'] or sha(scoring) != entry['frozen_sha256']
            or not source.is_file() or source.is_symlink() or source.parent.is_symlink()):
        raise ValueError('tiered core selected source is missing or changed; no legacy fallback')
    contract, legacy = load_plan_json(source), load_plan_json(legacy_path)
    validate_contract(contract, case_id=case.name, engine=entry['actual_engine'], requirement=requirement,
                      legacy=legacy, legacy_sha256=sha(legacy_path))
    baseline = load_plan_json(scoring)
    tier = canonical_tier(requirement.read_text())
    selected_tier = 'L-Regular' if entry.get('tier') == 'L' else entry.get('tier', tier)
    if selected_tier != tier:
        raise ValueError('selected tier differs from canonical requirement')
    if baseline.get('status') != 'frozen' or baseline.get('game_id') != case.name:
        raise ValueError('tiered core historical scoring source mismatch')
    return contract, {'planning_version': PLANNING_VERSION, 'version': VERSION,
        'authoring_protocol': AUTHORING, 'case_id': case.name, 'engine': contract['engine'],
        'tier': tier, 'target_count': COUNTS[tier], 'contract_id': contract['contract_id'],
        'source_path': str(source), 'source_relative_path': RUBRIC, 'rubric_sha256': sha(source),
        'requirement_sha256': sha(requirement), 'legacy_contract_id': legacy['contract_id'],
        'legacy_rubric_sha256': sha(legacy_path), 'scoring_contract_id': baseline['contract_id'],
        'scoring_rubric_sha256': sha(scoring), 'scoring_source_path': str(scoring)}


def make_protocol(contract, baseline, provenance):
    from .batch_rubric import V4_VERSION
    if baseline.get('version') != V4_VERSION:
        raise ValueError('tiered static/runtime scoring requires the frozen v4 eight-column baseline')
    from . import core12
    shadow = copy.deepcopy(contract)
    mechanisms = []
    for endpoint in (row for row in shadow['assertions'] if row['table_column'] == 'C2'):
        sub = endpoint['binding']['subchecks'][0]
        ident = endpoint['assertion_id']
        mechanisms.append({'id': f"atom.{ident}.{sub['id']}", 'column': COLUMNS[1], 'mode': 'runtime',
            'group': ident, 'endpoint_id': ident, 'endpoint_weight': 1.0, 'atom_weight': 1.0,
            'frozen_assertion_id': ident, 'frozen_subcheck_id': sub['id'],
            'requirement_ids': list(sub['requirement_ids']), 'requirement': sub['text'],
            'evidence_types': ['action', 'state', 'event', 'frame', 'log']})
    protocol = copy.deepcopy(baseline)
    protocol['criteria'] = [row for row in protocol['criteria'] if row['column'] != COLUMNS[1]] + mechanisms
    protocol['planning_contract'] = copy.deepcopy(provenance)
    protocol['mechanic_scope'] = f"{VERSION}: {provenance['tier']} {len(mechanisms)} source-bound endpoints, one scored atom each."
    from . import static_existence, frame_budget
    protocol['scoring_policy'] = static_existence.policy(protocol)
    protocol['evidence_frame_policy'] = frame_budget.policy(protocol)
    targets(protocol)
    return protocol


def targets(protocol):
    planning = protocol.get('planning_contract', {})
    tier = planning.get('tier')
    rows = [row for row in protocol['criteria'] if row['column'] == COLUMNS[1]]
    count = COUNTS.get(tier)
    if (not enabled(protocol) or planning.get('version') != VERSION
            or planning.get('authoring_protocol') != AUTHORING or planning.get('source_relative_path') != RUBRIC
            or planning.get('target_count') != count or len(rows) != count
            or len({row.get('endpoint_id') for row in rows}) != count or len({row['id'] for row in rows}) != count
            or any(row.get('mode') != 'runtime' or row.get('endpoint_weight') != 1.0
                   or row.get('atom_weight') != 1.0 or row['id'] != f"atom.{row['endpoint_id']}.{row['frozen_subcheck_id']}"
                   for row in rows)):
        raise ValueError('tiered core target count/identity/weight mismatch')
    return rows


def verify_attempt(root, engine):
    from . import core12, batch_rubric
    from . import runtime_budgets as budgets
    root = Path(root)
    protocol = load_plan_json(root / 'input/pilot_rubric.json')
    targets(protocol)
    manifest = load_plan_json(root / 'input_manifest.json')
    contract, provenance = load_sources(manifest['entry'])
    baseline = load_plan_json(root / 'input/scoring_pilot_rubric.json')
    provenance['scoring_protocol_sha256'] = fingerprint(baseline)
    if protocol['planning_contract'] != provenance or manifest.get('planning_contract') != provenance:
        raise ValueError('tiered core frozen provenance mismatch')
    from ...code_gen.playtest.engine_dispatch import resolve_engine
    if resolve_engine(engine) != resolve_engine(provenance['engine']):
        raise ValueError('tiered core frozen engine mismatch')
    for filename, key in [('frozen_rubric.json', 'rubric_sha256'), ('legacy_frozen_rubric.json', 'legacy_rubric_sha256'),
                          ('scoring_frozen_rubric.json', 'scoring_rubric_sha256'), ('requirement.txt', 'requirement_sha256')]:
        if sha(root / 'input' / filename) != provenance[key]:
            raise ValueError('tiered core frozen source drift: ' + filename)
    maker = batch_rubric.make_protocol_v4 if baseline.get('version') == batch_rubric.V4_VERSION else batch_rubric.make_protocol
    if baseline != maker(load_plan_json(root / 'input/scoring_frozen_rubric.json')):
        raise ValueError('tiered core scoring baseline derivation mismatch')
    expected = make_protocol(contract, baseline, provenance)
    from . import endpoint_sparse
    if manifest['entry'].get('evaluation_policy') == endpoint_sparse.VERSION:
        endpoint_sparse.freeze(expected)
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
    if protocol != expected or sha(root / 'input/pilot_rubric.json') != manifest['protocol_sha256']:
        raise ValueError('tiered core pilot derivation mismatch')
    budgets.validate_tiered_budget(protocol['runtime_budget'])
    if protocol['runtime_budget'] != load_plan_json(root / 'attempt_manifest.json')['budget']:
        raise ValueError('tiered core immutable budget mismatch')
    if protocol['runtime_budget']['tier'] != provenance['tier']:
        raise ValueError('tiered core budget differs from canonical tier')
    return protocol
