"""Explicit batch authorization for deterministic, honest route metadata repair."""
from pathlib import Path

from .protocol import dump, sha

VERSION = 'whitebox-unity-usable-route-policy.v1'


def authorize_route_metadata(attempt, config):
    from . import batch
    attempt = Path(attempt)
    if not config.get('batch'):
        return False
    source = Path(config['batch'])/'unity_execution_policy.json'
    if not source.is_file():
        return False
    policy = batch.read(source)
    if (policy.get('version') != VERSION or policy.get('route_metadata_repair') is not True
            or not policy.get('authorization')):
        raise ValueError('Unknown explicit usable-route authorization')
    target = attempt/'route_metadata_repair.json'
    if target.is_file():
        existing = batch.read(target)
        if existing.get('version') != 'whitebox-route-metadata-repair.v1' or not existing.get('authorization'):
            raise ValueError('Existing route metadata authorization is invalid')
        return True
    # Saved accepted plans, normalization proofs and captures are immutable.
    if any((attempt/name).exists() for name in ('sol_plan.json', 'plan_normalization.json', 'background_record')):
        return False
    dump(target, {'version':'whitebox-route-metadata-repair.v1',
        'authorization':policy['authorization'], 'batch_policy':str(source.resolve()),
        'batch_policy_sha256':sha(source),
        'scope':'Recompute route bindings from original physical actions; withdraw unproved endpoint claims; preserve raw model replies and game source.'})
    return True
