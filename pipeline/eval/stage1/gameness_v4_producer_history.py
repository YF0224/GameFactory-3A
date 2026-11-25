"""Explicit, exact-authorization producer history for transport-only evolution.

Original authorizations and publications remain immutable. A changed producer
requires an archived byte-identical original, an explicit current producer SHA,
a preserved parent authorization SHA, all original non-code bindings, targeted
regression evidence, and a concrete transport-only semantic equivalence record.
This grants neither new runtime admission nor permission to replace evidence.
"""
from pathlib import Path
import hashlib
from .protocol import sha
from . import mechanic_v3_runner as runner

VERSION = 'gameness-v4-exact-producer-history.v1'
DIRECTORY = 'engineering/gameness_producer_history'
ALLOWED = {'gameness_v4_persistent_text.py', 'gameness_v4_persistent_literal.py',
           'gameness_v4_persistent_capacity.py',
           'mechanic_v3_persistent_text.py',
           'mechanic_v3_cli.py', 'gameness_v4_producer_history.py',
           'gameness_v4_runtime.py', 'mechanic_v3_execution.py',
           'gameness_v4_bounded_text.py', 'gameness_v4_migration.py', 'two_column_sync.py',
           'mechanic_v3_delivery_audit_v3.py', 'mechanic_v3_delivery_audit_v4.py'}


def receipt_path(root, auth, producer, expected):
    key = hashlib.sha256((str(producer.resolve())+'\n'+expected+'\n'+sha(producer)).encode()).hexdigest()
    return root/DIRECTORY/sha(auth)/(key+'.json')


def verify(root, auth, producer, expected):
    root, auth, producer = Path(root).resolve(), Path(auth).resolve(), Path(producer).resolve()
    code = Path(__file__).resolve().parent
    if producer.parent != code or producer.name not in ALLOWED:
        raise ValueError('Producer history cannot change evidence, scoring or unrelated code')
    if auth.parent != root/'engineering' or auth.name not in {
            'gameness_persistent_original_text.json', 'gameness_persistent_capacity_continuation.json'}:
        raise ValueError('Exact persistent authorization required')
    value = runner.read(receipt_path(root,auth,producer,expected))
    if (value.get('version') != VERSION or value.get('identity') != root.name
            or value.get('authorization') != {'path':str(auth),'sha256':sha(auth)}
            or value.get('producer') != str(producer) or value.get('before_sha256') != expected
            or value.get('after_sha256') != sha(producer)
            or value.get('scope') != 'TRANSPORT_ONLY_NO_SCORE_OR_EVIDENCE_CHANGE'):
        raise ValueError('Explicit exact-auth historical producer continuation required')
    archive = Path(value['before_archive'])
    if archive.resolve() == producer or sha(archive) != expected:
        raise ValueError('Exact archived original producer required')
    evidence = runner.read(auth)['bindings']
    expected_data = {p:d for p,d in evidence.items() if Path(p).parent != code}
    if value.get('unchanged_parent_data') != expected_data:
        raise ValueError('Every original non-code binding must remain pinned')
    for name,digest in expected_data.items():
        if sha(Path(name)) != digest:
            raise ValueError('Historical producer cannot replace parent evidence: '+name)
    for field in ('equivalence', 'regression'):
        proof=value[field];path=Path(proof['path'])
        if sha(path) != proof['sha256']:
            raise ValueError('Producer history proof changed')
    equivalence=runner.read(Path(value['equivalence']['path']))
    if (equivalence.get('scoring_unchanged') is not True
            or equivalence.get('all_original_bytes_and_pixels_required') is not True
            or equivalence.get('compaction_still_rejected') is not True
            or equivalence.get('production_admission_granted') is not False):
        raise ValueError('Explicit transport-only equivalence required')
    regression=runner.read(Path(value['regression']['path']))
    if regression.get('exit_code') != 0 or regression.get('tests_passed',0) < 1:
        raise ValueError('Passed targeted transport regressions required')
    return value
