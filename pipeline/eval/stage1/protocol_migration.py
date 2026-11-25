"""Explicit attestation for one historical derived budget scalar mismatch.

Frozen score selection and original protocol files never change. A journal is
required before the verified derived protocol can be used by a new attempt.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from .protocol import dump, sha

VERSION = 'whitebox-protocol-budget-migration.v1'
CASE = 'G057_rhythm_machine_hall'

def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':')).encode()).hexdigest()

def migration_record(entry, lock, locked, derived):
    if entry['actual_engine'] not in {'godot', 'three_js'} or entry['case_id'] != CASE:
        raise ValueError('protocol migration is restricted to the diagnosed target case')
    old = {k: v for k, v in locked.items() if k != 'runtime_budget_ms'}
    new = {k: v for k, v in derived.items() if k != 'runtime_budget_ms'}
    if old != new:
        raise ValueError('protocol migration cannot change score selection or other protocol fields')
    if (locked.get('runtime_budget_ms') != 75000 or derived.get('runtime_budget_ms') != 125000
            or derived.get('runtime_budget', {}).get('gameplay_ms') != 125000):
        raise ValueError('protocol migration does not match the diagnosed budget scalar drift')
    return {'version': VERSION, 'case_id': CASE, 'engine': entry['actual_engine'],
        'locked_protocol_sha256': lock['sha256'],
        'frozen_rubric_sha256': entry['frozen_sha256'],
        'derived_protocol_canonical_sha256': digest(derived),
        'unchanged_protocol_fields_canonical_sha256': digest(old),
        'changes': [{'field': 'runtime_budget_ms', 'before': 75000, 'after': 125000}],
        'reason': 'Historical scalar remained 75s while the same locked protocol runtime_budget already specified 125s; regenerate from the identical frozen rubric. New attempt S300/M600 policy is separate.'}

def verify_budget_migration(batch, entry, lock, locked, derived, *, provenance_root=None):
    expected = migration_record(entry, lock, locked, derived)
    path = Path(batch)/'protocol_migrations'/entry['case_id']/'runtime_budget_ms.v1.json'
    if not path.is_file() or json.loads(path.read_text()) != expected:
        raise ValueError('installed rubric selection differs from frozen protocol; explicit budget migration attestation missing or invalid')
    if provenance_root is not None:
        dest = Path(provenance_root)/'input/protocol_provenance'
        dump(dest/'locked_protocol.json', locked)
        dump(dest/'derived_protocol.json', derived)
        dump(dest/'migration.json', {**expected, 'journal_path': str(path.resolve()), 'journal_sha256': sha(path)})
    return derived
