"""Persist the numeric source-only credits already established by the Sol review.

This report never awards runtime/visual credit or adds a scoring column. The original
Sol checks and model bytes remain the scoring authority for the existing mechanic tiers.
"""
from collections import defaultdict
from pathlib import Path
from . import batch, static_existence
from .protocol import COLUMNS, dump, sha


def save(root):
    root = Path(root)
    protocol = batch.read(root/'input/pilot_rubric.json')
    result = static_existence.load(root, protocol)
    specs = {row['id']: row for row in static_existence.items(protocol)}
    checks = {}
    for ident, value in result['checks'].items():
        exists = value['static_existence'] == 'EXISTS' and value['connected_to_entry'] is True
        checks[ident] = {**value, 'rubric': specs[ident], 'source_credit': 10.0 if exists else 0.0,
                         'implementation_proved': exists, 'runtime_credit': None}
    count = len(checks)
    implemented = sum(row['implementation_proved'] for row in checks.values())
    columns = {column: {'source_score': None, 'reason': 'Not determined by the saved source-existence review; final frozen rubric judge required'}
               for column in COLUMNS}
    columns[COLUMNS[1]] = {'source_score': round(sum(row['source_credit'] for row in checks.values())/count, 2) if count else None,
        'reason': 'Existing 10% source tier only; final mechanism takes max(10%, 50%, 100%), never adds this report'}
    calls = []
    for folder in sorted((root/'model_calls').glob('static_existence*')):
        invocation = folder/'invocation.json'
        if invocation.is_file():
            value = batch.read(invocation)
            calls.append({'path': str(invocation.relative_to(root)), 'sha256': sha(invocation),
                          'seconds': value.get('seconds', value.get('elapsed_seconds'))})
    payload = {'version': 'whitebox-source-code-scores.v1', 'static_artifact_sha256': sha(root/'static_existence.json'),
        'identity': result['identity'], 'columns': columns, 'checks': checks,
        'implementation_coverage_percent': round(100*implemented/count, 2) if count else None,
        'coverage_is_not_formal_completeness_or_visual_score': True,
        'whitebox_source_score': None,
        'whitebox_reason': 'Visual proportions/readability and final scene result require real frames; code existence alone cannot prove them',
        'model_calls': calls, 'extra_model_calls': 0, 'extra_weight': 0}
    dump(root/'static_code_scores.json', payload)
    return payload
