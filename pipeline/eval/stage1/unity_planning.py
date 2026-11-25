"""Compact Unity core12 mapping with explicit endpoint-to-atom provenance."""
import copy

from . import core12

VERSION = 'unity-core12-planning.v1'


def enabled(protocol):
    return core12.enabled(protocol)


def endpoint_atoms(protocol):
    return {row['endpoint_id']: [row] for row in core12.targets(protocol)}


def schema(protocol, identity):
    from . import core12_planning
    return core12_planning.schema(protocol, 'unity3d', identity)


def prompt(protocol, identity):
    from . import core12_planning
    return core12_planning.prompt(protocol, 'unity3d', identity)


def expand(result, protocol):
    groups = endpoint_atoms(protocol)
    coverage = result.get('coverage')
    if not isinstance(coverage, dict):
        return copy.deepcopy(result), None
    if set(coverage) != set(groups):
        raise ValueError('Compact coverage endpoint IDs differ from the frozen core endpoints')
    expanded = copy.deepcopy(result)
    expanded['coverage'] = [dict(copy.deepcopy(coverage[endpoint]), atom_id=rows[0]['id'])
                            for endpoint, rows in groups.items()]
    for probe in expanded['probes']:
        identifiers = probe['criterion_ids']
        if len(identifiers) != len(set(identifiers)) or set(identifiers) - set(groups):
            raise ValueError('Compact probe references duplicate or non-core12 endpoints')
        probe['criterion_ids'] = [groups[endpoint][0]['id'] for endpoint in identifiers]
    from . import tiered_core
    journal = {'version': 'unity-tiered-core-planning.v1' if tiered_core.enabled(protocol) else VERSION,
               'planning_contract': copy.deepcopy(protocol['planning_contract']),
               'model_endpoint_windows': copy.deepcopy(coverage),
               'endpoint_to_atom_ids': {endpoint: [rows[0]['id']] for endpoint, rows in groups.items()},
               'semantics': f'{len(groups)} endpoints map one-to-one to {len(groups)} frozen core scored atoms. '
                            'Planned windows only; no gameplay evidence or verified outcomes.'}
    return expanded, journal
