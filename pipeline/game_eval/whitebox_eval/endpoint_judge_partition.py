"""Exhaustive singleton dispatch checkpoints; never authorize an incomplete score."""
import hashlib
import json

FIELD = 'endpoint_judge_partition'
VERSION = 'whitebox-endpoint-singleton-checkpoint.v1'


def partition(protocol):
    from .sparse_evidence import groups
    specs = [spec for group in groups(protocol) for spec in group]
    if len({spec['id'] for spec in specs}) != len(specs):
        raise ValueError('Duplicate frozen endpoint criterion')
    return {'version': VERSION,
            'criteria_sha256': hashlib.sha256(json.dumps(specs, ensure_ascii=False,
                sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
            'shards': {f'evidence_{index:02d}': [spec['id']]
                       for index, spec in enumerate(specs, 1)}}


def groups(protocol, manifest):
    saved = manifest.get(FIELD)
    expected = partition(protocol)
    if saved != expected:
        raise ValueError('Endpoint partition changed frozen criteria, order or coverage')
    indexed = {spec['id']: spec for spec in protocol['criteria']}
    return [[indexed[ident] for ident in ids] for ids in expected['shards'].values()]


class IncompleteEndpointDelivery(ValueError):
    pass


def blocked(error):
    return {'version': VERSION, 'kind': 'INPUT_CAPACITY_EXCEEDED',
            'error': str(error), 'score_eligible': False}


def partial_gate(root, protocol, manifest, capture_validation):
    """Only the known transport incompleteness may differ from the full gate.

    The full gate is still invalid. Revalidate every raw visual/endpoint chain,
    all completed transports and every blocked transport's actual failure.
    """
    from . import sparse_evidence
    expected_issue = 'Invalid action evidence index: ' + incomplete_message(manifest)
    if capture_validation.get('valid') or capture_validation.get('issues') != [expected_issue]:
        raise ValueError('Partial judge requires otherwise-valid raw capture: ' + str(capture_validation))
    sparse_evidence.validate(root, protocol, manifest, allow_incomplete=True)
    return [name for name, subset in manifest['evidence_sets'].items()
            if 'transport_blocked' not in subset]


def incomplete_message(manifest):
    return 'Endpoint transport incomplete: ' + ','.join(name for name, subset in
        manifest['evidence_sets'].items() if 'transport_blocked' in subset)
