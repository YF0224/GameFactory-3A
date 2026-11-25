"""Shared provenance and completeness gates for persisted judge shards."""
from __future__ import annotations

import json
from pathlib import Path

FALLBACK_VERSION = 'automatic-unverified-valid-capture.v1'
VALIDATION_VERSIONS = {'frozen-keyed-judgments.v1', 'exact-alias-inputfix.v2'}


def fallback_issues(value, prefix='') -> list[str]:
    """Use explicit provenance, never infer contamination from a score of zero."""
    issues = []
    if isinstance(value, dict):
        for key, item in value.items():
            path = f'{prefix}.{key}' if prefix else key
            if key in {'fallback', 'judge_fallback'} and item is True:
                issues.append(path)
            elif key == 'validation_version' and item == FALLBACK_VERSION:
                issues.append(path + '=' + FALLBACK_VERSION)
            if isinstance(item, (dict, list)):
                issues.extend(fallback_issues(item, path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            issues.extend(fallback_issues(item, f'{prefix}[{index}]'))
    return issues


def run_fallback_issues(root: Path) -> list[str]:
    issues = []
    for name in ('status.json', 'scores.json', 'rubric_verdicts.json'):
        path = root / name
        if path.is_file():
            issues.extend(fallback_issues(json.loads(path.read_text()), name))
    return issues


def validate_saved_shard(artifact: dict, specs: list[dict]) -> None:
    if not isinstance(artifact, dict):
        raise ValueError("saved judge artifact must be an object")
    contamination = fallback_issues(artifact)
    if contamination:
        raise ValueError('automatic judge fallback contamination: ' + ', '.join(contamination))
    if artifact.get('validation_version') not in VALIDATION_VERSIONS:
        raise ValueError('unsupported saved judge validation version')
    expected = [spec['id'] for spec in specs]
    if len(set(expected)) != len(expected):
        raise ValueError('duplicate frozen shard criterion IDs')
    raw = artifact.get('raw')
    if not isinstance(raw, dict):
        raise ValueError('saved judge raw must be an object')
    for name, rows in (('raw.checks', raw.get('checks')), ('rows', artifact.get('rows'))):
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError(f'saved judge {name} must be a list of checks')
        ids = [row.get('id') for row in rows]
        if any(not isinstance(ident, str) for ident in ids) or len(ids) != len(expected) or set(ids) != set(expected):
            raise ValueError(f'saved judge {name} omitted, duplicated or invented check IDs')
        if any(row.get('status') not in {'PASS', 'FAIL', 'UNVERIFIED'} for row in rows):
            raise ValueError(f'invalid saved judge {name} evidence status')
