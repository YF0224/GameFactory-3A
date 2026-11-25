"""Bound static response size without changing any frozen criterion or evidence."""
import copy
import hashlib
import json
import re
from pathlib import Path

VERSION = 'whitebox-static-judge-shards.v1'
POLICY = 'unity_static_judge_policy.json'
FIELD = 'static_judge_partition'
SIZE = 24


def partition(protocol):
    specs = [row for row in protocol['criteria'] if row['mode'] == 'static']
    digest = hashlib.sha256(json.dumps(specs, ensure_ascii=False, sort_keys=True,
                                      separators=(',', ':')).encode()).hexdigest()
    return {'version': VERSION, 'maximum_checks_per_call': SIZE,
            'static_criteria_sha256': digest,
            'shards': {f'static_{i//SIZE+1:02d}': [row['id'] for row in specs[i:i+SIZE]]
                       for i in range(0, len(specs), SIZE)}}


def tasks(protocol, manifest):
    """The partition is deterministic and exhaustive; no atom can disappear."""
    saved = manifest.get(FIELD)
    specs = [row for row in protocol['criteria'] if row['mode'] == 'static']
    if saved is None:
        return [('static', specs, True)]
    expected = partition(protocol)
    if saved != expected or len({row['id'] for row in specs}) != len(specs):
        raise ValueError('Static judge partition changed frozen checks/order/size')
    by_id = {row['id']: row for row in specs}
    return [(name, [by_id[ident] for ident in identifiers], True)
            for name, identifiers in expected['shards'].items()]


def is_static(manifest, name):
    if FIELD not in manifest:
        return name == 'static'
    shards = manifest[FIELD].get('shards', {})
    if name == 'static':
        raise ValueError('Partitioned static judge cannot fall back to one oversized call')
    return name in shards


def install(root, protocol, manifest):
    """Explicit batch policy applies only before the first judge invocation."""
    root = Path(root).resolve()
    policy_path = root.parents[1]/POLICY
    if not policy_path.is_file():
        return manifest
    validate_policy(policy_path)
    calls = root/'model_calls'
    if calls.exists() and any(p.name == 'static' or re.fullmatch(r'static_\d{2,}', p.name)
           or p.name.startswith('evidence_') for p in calls.iterdir()):
        raise ValueError('Static judge partition must precede judge calls')
    result = copy.deepcopy(manifest)
    result[FIELD] = partition(protocol)
    tasks(protocol, result)
    return result


def validate_policy(policy_path):
    policy = json.loads(policy_path.read_text())
    if (set(policy) != {'version', 'maximum_checks_per_call', 'authorization'}
            or policy['version'] != VERSION or policy['maximum_checks_per_call'] != SIZE
            or not isinstance(policy['authorization'], str) or not policy['authorization'].strip()):
        raise ValueError('Invalid explicit Unity static judge partition policy')
    return policy
