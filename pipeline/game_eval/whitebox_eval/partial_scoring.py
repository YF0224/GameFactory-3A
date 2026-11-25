"""Versioned partial scoring for the frozen C2 mechanism endpoints."""
from __future__ import annotations

import math
from pathlib import Path

VERSION = 'whitebox-partial-endpoints.v2'
LEGACY_VERSION = 'whitebox-partial-11.v1'
STATIC_VERSION = 'whitebox-static10-runtime90.v1'
TIER_VERSION = 'whitebox-mechanic10-50-100.v1'
CLOSED_TIER_VERSION = 'whitebox-mechanic10-50-100.v2'
SOURCE_VERSIONS = {STATIC_VERSION, TIER_VERSION, CLOSED_TIER_VERSION}
SUPPORTED_VERSIONS = {VERSION, LEGACY_VERSION, *SOURCE_VERSIONS}
INDICATOR_WEIGHTS = {name: 1 / 8 for name in
    ('故事完整性', '机制完整性', '资产预留', '白模输入一致性', '白模构建质量', 'Gameness', 'Playable', 'Code')}
ANCHORS = [0, 25, 50, 75, 100]


def make_rubric(protocol: dict, *, version: str = VERSION) -> dict:
    if version not in SUPPORTED_VERSIONS:
        raise ValueError(f'unsupported partial scoring version: {version}')
    endpoints = {}
    ids = set()
    for atom in protocol['criteria']:
        ident = atom.get('id')
        if not isinstance(ident, str) or not ident.strip() or ident in ids:
            raise ValueError('invalid or duplicate frozen criterion ID')
        ids.add(ident)
        endpoint = atom.get('endpoint_id')
        if atom.get('column') == '机制完整性' and not endpoint:
            raise ValueError(f'missing frozen mechanism endpoint: {ident}')
        if endpoint is None:
            continue
        if not isinstance(endpoint, str) or not endpoint.strip():
            raise ValueError(f'invalid frozen endpoint ID: {ident}')
        if atom.get('column') != '机制完整性' or atom.get('group') != endpoint:
            raise ValueError(f'inconsistent frozen endpoint group: {ident}')
        if atom.get('frozen_assertion_id', endpoint) != endpoint:
            raise ValueError(f'inconsistent frozen assertion ID: {ident}')
        subcheck = atom.get('frozen_subcheck_id')
        if subcheck is not None and ident != f'atom.{endpoint}.{subcheck}':
            raise ValueError(f'inconsistent frozen atom ID: {ident}')
        endpoints.setdefault(endpoint, []).append(ident)
    for endpoint, atom_ids in endpoints.items():
        atoms = [atom for atom in protocol['criteria'] if atom.get('endpoint_id') == endpoint]
        for atom in atoms:
            for key, expected in (('endpoint_weight', 1.0), ('atom_weight', 1 / len(atom_ids))):
                if key in atom:
                    value = atom[key]
                    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not math.isclose(value, expected, rel_tol=0, abs_tol=1e-9):
                        raise ValueError(f'inconsistent frozen {key}: {atom["id"]}')
    count = len(endpoints)
    if count == 0:
        raise ValueError('frozen mechanism protocol has no C2 endpoints (N=0)')
    if version == LEGACY_VERSION and count != 11:
        raise ValueError(f'legacy partial scoring requires 11 endpoints, got {count}')
    rubric = {
        'version': version,
        'source_protocol': protocol['version'],
        'case_id': protocol['case_id'],
        'score_anchors': ANCHORS,
        'unverified_rule': 'UNVERIFIED atoms contribute 0; status remains distinct from score.',
        'endpoint_weight': 1 / count,
        'weight_rationale': f'The frozen rubric defines {count} co-equal C2 mechanism endpoints; each receives 1/{count} of mechanism score.',
        'endpoint_atoms': endpoints,
        'endpoint_score': '100 * verified PASS atoms / all frozen atoms in endpoint; FAIL and UNVERIFIED contribute 0.',
        'indicator_weights': dict(INDICATOR_WEIGHTS),
        'total_formula': 'sum(indicator_score * indicator_weight); mechanism indicator is the endpoint-weighted mean exactly once.',
    }
    if version in {VERSION, *SOURCE_VERSIONS}:
        rubric.update(endpoint_count=count, criterion_ids=sorted(ids))
    if version in SOURCE_VERSIONS:
        from .static_existence import policy, enabled
        if not enabled(protocol):
            raise ValueError('static/runtime scoring requires the frozen policy')
        rubric.update(scoring_policy=policy(protocol),
                      endpoint_score=policy(protocol)['formula'],
                      gameness_groups=['layout','guidance','feedback'])
    if 'asset_reservation_policy' in protocol:
        from .asset_reservation import validate
        validate(protocol)
        import copy
        rubric['asset_reservation_policy'] = copy.deepcopy(protocol['asset_reservation_policy'])
    return rubric


def validate_rubric(rubric: dict) -> None:
    if rubric.get('version') not in SUPPORTED_VERSIONS:
        raise ValueError('unsupported partial scoring version')
    endpoints = rubric.get('endpoint_atoms')
    if not isinstance(endpoints, dict) or not endpoints:
        raise ValueError('frozen mechanism protocol has no C2 endpoints (N=0)')
    if rubric['version'] == LEGACY_VERSION and len(endpoints) != 11:
        raise ValueError('legacy partial scoring requires 11 endpoints')
    if rubric.get('endpoint_count', len(endpoints)) != len(endpoints):
        raise ValueError('endpoint count does not match frozen groups')
    atoms = []
    for endpoint, group in endpoints.items():
        if not isinstance(endpoint, str) or not endpoint.strip() or not isinstance(group, list) or not group:
            raise ValueError('invalid or empty frozen endpoint group')
        if any(not isinstance(ident, str) or not ident.strip() for ident in group):
            raise ValueError('invalid frozen atom ID')
        atoms.extend(group)
    if len(set(atoms)) != len(atoms):
        raise ValueError('duplicate frozen atom IDs or multiple endpoint assignments')
    weight = rubric.get('endpoint_weight')
    if isinstance(weight, bool) or not isinstance(weight, (int, float)) or not math.isfinite(weight) or not math.isclose(weight * len(endpoints), 1.0, rel_tol=0, abs_tol=1e-9):
        raise ValueError('endpoint weights must sum to 1')
    if rubric.get('indicator_weights') != INDICATOR_WEIGHTS:
        raise ValueError('all eight official indicator weights must remain 1/8')
    if 'criterion_ids' in rubric:
        ids = rubric['criterion_ids']
        if not isinstance(ids, list) or any(not isinstance(i, str) or not i.strip() for i in ids) or len(ids) != len(set(ids)) or not set(atoms) <= set(ids):
            raise ValueError('invalid frozen criterion IDs')


def score(rubric: dict, verdicts: dict, indicator_scores: dict | None = None) -> dict:
    if rubric.get('version') in SOURCE_VERSIONS:
        raise ValueError('static scoring requires independently validated source judgments via apply_to_report')
    validate_rubric(rubric)
    checks = {row['id']: row for row in verdicts.get('checks', [])}
    if len(checks) != len(verdicts.get('checks', [])):
        raise ValueError('duplicate verdict IDs')
    if 'criterion_ids' in rubric and not set(checks) <= set(rubric['criterion_ids']):
        raise ValueError('verdict contains unknown frozen criterion IDs')
    if any(row.get('status') not in {'PASS', 'FAIL', 'UNVERIFIED'} for row in checks.values()):
        raise ValueError('invalid evidence status')
    endpoint_scores = {}
    for endpoint, atom_ids in rubric['endpoint_atoms'].items():
        rows = [checks.get(atom) for atom in atom_ids]
        verified = [row for row in rows if row and row.get('status') in {'PASS', 'FAIL'}]
        passed = sum(row['status'] == 'PASS' for row in verified)
        score_value = round(100 * passed / len(atom_ids), 2)
        states = {row.get('status') for row in rows if row}
        status = 'PASS' if len(verified) == len(rows) and passed == len(rows) else ('FAIL' if 'FAIL' in states else 'UNVERIFIED')
        endpoint_scores[endpoint] = {'status': status, 'score': score_value,
            'weight': rubric['endpoint_weight'], 'pass_atoms': passed,
            'fail_atoms': sum(bool(row and row.get('status') == 'FAIL') for row in rows),
            'unverified_atoms': sum(bool(not row or row.get('status') == 'UNVERIFIED') for row in rows),
            'atom_ids': atom_ids,
            'rationale': f'{passed}/{len(atom_ids)} frozen atoms have verified PASS evidence.',
            'evidence_judgments': [{'id': ident, 'status': checks.get(ident, {}).get('status', 'UNVERIFIED'),
                'reason': checks.get(ident, {}).get('reason', 'No validated evidence judgment'),
                'evidence': checks.get(ident, {}).get('evidence', [])} for ident in atom_ids]}
    mechanism = round(sum(row['score'] * row['weight'] for row in endpoint_scores.values()), 2)
    indicators = dict(indicator_scores or {})
    indicators['机制完整性'] = mechanism
    total = None
    weights = rubric['indicator_weights']
    if all(isinstance(indicators.get(key), (int, float)) and not isinstance(indicators[key], bool)
           and math.isfinite(indicators[key]) and 0 <= indicators[key] <= 100 for key in weights):
        total = round(sum(indicators[key] * weights[key] for key in weights), 2)
    return {'rubric_version': rubric['version'], 'endpoints': endpoint_scores,
        'indicator_scores': indicators, 'indicator_weights': weights,
        'total_score': total, 'calculation': rubric['total_formula']}


def write_rubric(path: Path, protocol: dict) -> str:
    from .protocol import dump, sha
    rubric = make_rubric(protocol)
    dump(path, rubric)
    return sha(path)


def apply_to_report(report: dict, protocol: dict, *, version=None, root=None, static_result=None) -> dict:
    """Single authoritative calculation for new runs and independent audit."""
    from . import static_existence
    uses_static=static_existence.enabled(protocol)
    selected = protocol['scoring_policy']['version'] if uses_static else VERSION
    version=version or selected
    if version != selected and (uses_static or version not in {VERSION, LEGACY_VERSION}):
        raise ValueError('scoring version differs from the immutable source policy')
    if version in SOURCE_VERSIONS:
        if static_result is None:
            if root is None:
                raise ValueError('static scoring requires independent source judgments')
            static_result=static_existence.load(root,protocol)
        if version in {TIER_VERSION, CLOSED_TIER_VERSION}:
            from . import endpoint_sparse
            if root is None:
                raise ValueError('mechanism tiers require original runtime evidence')
            partial=endpoint_sparse.apply(report,protocol,static_result,root)
        else:
            partial=static_existence.apply(report,protocol,static_result)
        if root is not None:
            from .protocol import sha
            report['static_existence_sha256']=sha(Path(root)/'static_existence.json')
        return partial
    rubric = make_rubric(protocol, version=version)
    partial = score(rubric, {'checks': report['checks']},
                    {name: data['score'] for name, data in report['columns'].items()})
    if partial['total_score'] is None:
        raise ValueError('all eight valid indicators are required for a total score')
    report['columns']['机制完整性']['score'] = partial['indicator_scores']['机制完整性']
    report['overall_score'] = partial['total_score']
    report['scoring_protocol'] = version
    report['mechanism_endpoints'] = partial['endpoints']
    report['indicator_weights'] = partial['indicator_weights']
    report['calculation'] = partial['calculation']
    return partial
