"""Lossless source-column envelope decoding; original validators remain mandatory."""
import copy
from pathlib import Path
from . import batch, codex, unity_source_review as review
from .protocol import dump, sha

VERSION = 'whitebox-source-column-envelope.v1'
OUTPUT = 'source_envelope_decoded_response.json'
RECEIPT = 'source_envelope_decode.json'


def decode(value, targets):
    """Accept only explicit frozen column metadata and exact field aliases."""
    if not isinstance(value, dict) or set(value) != {'columns'} or not isinstance(value['columns'], list):
        raise ValueError('Not an exact source-column envelope')
    target_map = {row['id']: row for row in targets}
    checks = {}
    for row in value['columns']:
        if not isinstance(row, dict) or set(row) != {'id', 'column', 'criterion_ids', 'score', 'basis', 'evidence', 'runtime_visual_limit'}:
            raise ValueError('Unknown or missing source-column envelope field')
        ident = row['id']
        if not isinstance(ident, str) or ident not in target_map or ident in checks:
            raise ValueError('Unknown or duplicate source column')
        if {key: row[key] for key in ('id', 'column', 'criterion_ids')} != target_map[ident]:
            raise ValueError('Frozen source-column binding changed')
        if not isinstance(row['evidence'], list):
            raise ValueError('Source evidence must remain an array')
        evidence = []
        for ref in row['evidence']:
            if not isinstance(ref, dict) or set(ref) != {'path', 'sha256', 'line_start', 'line_end', 'description'}:
                raise ValueError('Unknown or missing source-reference field')
            evidence.append({('reason' if key == 'description' else key): copy.deepcopy(v) for key, v in ref.items()})
        checks[ident] = {'score': row['score'], 'basis': row['basis'], 'evidence': evidence,
                         'runtime_or_visual_limits': row['runtime_visual_limit']}
    if not checks:
        raise ValueError('Empty source-column envelope')
    return {'checks': checks}


def encode(value, targets, order):
    """Exact inverse: no model text, evidence, physical lines or scores are lost."""
    target_map = {row['id']: row for row in targets}
    rows = []
    for ident in order:
        row = value['checks'][ident]
        rows.append({**copy.deepcopy(target_map[ident]), 'score': row['score'], 'basis': row['basis'],
                     'evidence': [{('description' if key == 'reason' else key): copy.deepcopy(v) for key, v in ref.items()} for ref in row['evidence']],
                     'runtime_visual_limit': row['runtime_or_visual_limits']})
    return {'columns': rows}


def recover(root, name):
    """Resume one successful invocation with a preserved schema failure, never retry it."""
    root = Path(root).resolve()
    folder = root/'model_calls'/name
    paths = {n: folder/n for n in ('response.json', 'schema.json', 'schema_error.json', 'prompt.txt', 'invocation.json')}
    if not all(p.is_file() and not p.is_symlink() for p in paths.values()) or (folder/'accepted_response.json').exists():
        raise ValueError('No eligible preserved source schema failure')
    inv = batch.read(paths['invocation.json'])
    if inv.get('exit_code') != 0 or inv.get('status') == 'TIMEOUT':
        raise ValueError('Schema decoding requires successful invocation, not a service failure')
    error = batch.read(paths['schema_error.json'])
    if error.get('phase') != 'response_schema_validation' or error.get('response_sha256') != sha(paths['response.json']):
        raise ValueError('Schema-failure response binding changed')
    original = batch.read(paths['response.json'])
    schema = batch.read(paths['schema.json'])
    # Only the unchanged source review schema is in scope, never judge/audit.
    protocol = batch.read(root/'input/pilot_rubric.json')
    targets = review.column_targets(protocol)
    ids = list(schema.get('properties', {}).get('checks', {}).get('properties', {}))
    expected = review.schema(protocol, grouped=True)
    expected['properties']['checks']['properties'] = {key: expected['properties']['checks']['properties'][key] for key in ids}
    expected['properties']['checks']['required'] = ids
    if not ids or schema != expected:
        raise ValueError('Not the unchanged source-column schema')
    decoded = decode(original, targets)
    if set(decoded['checks']) != set(ids):
        raise ValueError('Source delivery column coverage changed')
    codex.validate_schema(decoded, schema)
    review.validate_check_rows(root, decoded, persist_normalizations=False)
    order = [row['id'] for row in original['columns']]
    if encode(decoded, targets, order) != original:
        raise ValueError('Source envelope inverse equivalence failed')
    bindings = {name: sha(path) for name, path in paths.items()}
    result_path = folder/OUTPUT
    if result_path.exists() and batch.read(result_path) != decoded:
        raise ValueError('Preserved decoded source response changed')
    if not result_path.exists():
        dump(result_path, decoded)
    receipt = {'version': VERSION, 'source_bindings': bindings, 'normalized_sha256': sha(result_path),
               'column_order': order, 'frozen_column_bindings': [row for row in targets if row['id'] in ids],
               'inverse_equivalent': True, 'source_schema_and_reference_validation': True,
               'score_criteria_evidence_audit_semantics_changed': False, 'model_calls_added': 0}
    receipt_path = folder/RECEIPT
    if receipt_path.exists() and batch.read(receipt_path) != receipt:
        raise ValueError('Source envelope recovery receipt changed')
    if not receipt_path.exists():
        dump(receipt_path, receipt)
    if bindings != {name: sha(path) for name, path in paths.items()}:
        raise ValueError('Preserved source failure changed during decoding')
    return result_path
