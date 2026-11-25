"""Opt-in Mechanic-only v3. Never changes v1/v2 or the other seven columns.

Source existence, basic function, and complete specification are independent
judgments. References still name actually delivered, SHA-bound physical evidence.
"""
from __future__ import annotations

import copy
import json
import math
import re
from pathlib import Path

from .codex import obj, arr, S, B, I, N, validate_schema
from .protocol import COLUMNS, checked_path, sha

VERSION = 'whitebox-mechanic10-50-100.v3'
CONTRACT_VERSION = 'whitebox-mechanic-basic-path-contract.v1'
MODEL = 'gpt-6.1-sol'
MECHANIC = COLUMNS[1]
MODES = ['input', 'held', 'automatic', 'delayed', 'rejection']
SOURCE_SUFFIXES = {'.gd', '.cs', '.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx', '.html'}


def mechanisms(protocol):
    return [row for row in protocol['criteria'] if row['column'] == MECHANIC]


def contract_schema(protocol):
    fields = {'trigger_modes': arr({'type': 'string', 'enum': MODES}),
              'trigger': S, 'preconditions': S, 'correct_target': S,
              'basic_path': S, 'expected_response': S,
              'max_response_delay_ms': dict(I, minimum=0, maximum=300000),
              'basic_function_bugs': arr(S), 'spec_only_deviations': arr(S),
              'full_requirement': S, 'causal_window_basis': S}
    return obj({'summary': S, 'checks': obj({row['id']: obj(copy.deepcopy(fields))
                                           for row in mechanisms(protocol)})})


def validate_contract(protocol, contract):
    if contract.get('revision') == 'outcome_frame_v1':
        from .mechanic_v3_outcome import validate_contract as outcome_contract
        return outcome_contract(protocol, contract)
    validate_schema(contract, contract_schema(protocol))
    for spec in mechanisms(protocol):
        row = contract['checks'][spec['id']]
        if row['full_requirement'] != spec['requirement']:
            raise ValueError('Contract changed full frozen requirement: ' + spec['id'])
        if not row['trigger_modes'] or len(set(row['trigger_modes'])) != len(row['trigger_modes']):
            raise ValueError('Contract needs unique permitted trigger modes')
        for name in ('trigger', 'preconditions', 'correct_target', 'basic_path', 'expected_response', 'causal_window_basis'):
            if not row[name].strip():
                raise ValueError('Empty basic-path contract field: ' + name)
        if not row['basic_function_bugs']:
            raise ValueError('Basic-path bug conditions must be frozen before runtime judgment')
    return contract


def reference_schema(rules):
    variants = []
    for ident, limit in rules.items():
        variants.append(obj({'id': {'type': 'string', 'enum': [ident]},
                             'line_start': dict(I, **limit), 'line_end': dict(I, **limit),
                             'observation': S}))
    if not variants:
        raise ValueError('No actually delivered evidence IDs')
    return {'anyOf': variants}


def judgment_schema(specs, rules, manifest):
    refs = arr({'$ref': '#/$defs/Citation'})
    source = obj({'status': {'type': 'string', 'enum': ['EXISTS', 'ABSENT', 'UNVERIFIED', 'HARNESS_ERROR']},
                  'reason': S, 'evidence': refs})
    basic = obj({'status': {'type': 'string', 'enum': ['NORMAL', 'BUG', 'UNOBSERVED', 'HARNESS_ERROR']},
                 'trigger_mode': {'type': 'string', 'enum': MODES}, 'triggered': B,
                 'operation_processed': B, 'correct_target': B, 'response_observed': B,
                 'no_basic_bug': B, 'trigger_t_ms': N, 'response_t_ms': N,
                 'deviation_kind': {'type': 'string', 'enum': ['none', 'spec_deviation', 'basic_function_bug', 'insufficient_evidence']},
                 'reason': S, 'counterexample': S, 'evidence': refs})
    checks = {}
    for spec in specs:
        endpoint = manifest.get('endpoint_contracts', {}).get(spec['id'], {})
        conditions = endpoint.get('rubric', endpoint)
        complete = obj({'status': {'type': 'string', 'enum': ['PASS', 'FAIL', 'UNVERIFIED', 'HARNESS_ERROR']},
                        'reason': S, 'counterexample': S, 'preconditions_met': B,
                        'observation_complete': B, 'all_requirements_proven': B,
                        'last_action_completed': B, 'stable_result': B,
                        'visible_conditions': dict(arr(B), minItems=len(conditions.get('visible_conditions', [])),
                                                   maxItems=len(conditions.get('visible_conditions', []))),
                        'state_event_conditions': dict(arr(B), minItems=len(conditions.get('state_event_conditions', [])),
                                                       maxItems=len(conditions.get('state_event_conditions', []))),
                        'evidence': refs})
        checks[spec['id']] = obj({'source_existence': source, 'basic_function': basic, 'full_spec': complete})
    schema = obj({'summary': S, 'limitations': arr(S), 'checks': obj(checks)})
    schema['$defs'] = {'Citation': reference_schema(rules)}
    return schema


def inspect_references(root, manifest, rules, refs):
    from .unity_m_original_sources import qualified as qualified_author_source
    """Fail closed on invalid citations; don't turn harness faults into low scores."""
    index = {row['id']: row for row in manifest['items']}
    if len(index) != len(manifest['items']):
        raise ValueError('Duplicate evidence identity')
    facts = {'types': set(), 'times': set(), 'action_times': set(), 'outcome_times': set(),
             'frame_ids': set(), 'source_ids': set(), 'clocks': set(), 'state_event_times': set(), 'action_rows': [], 'outcome_rows': [], 'runtime_error_ids': set()}
    for ref in refs:
        ident = ref['id']
        if ident not in index or ident not in rules or not ref['observation'].strip():
            raise ValueError('Unknown/undelivered/unexplained citation: ' + ident)
        item, limit = index[ident], rules[ident]
        path = checked_path(root, item['path'])
        if sha(path) != item['sha256']:
            raise ValueError('Evidence SHA changed: ' + ident)
        start, end = ref['line_start'], ref['line_end']
        if type(start) is not int or type(end) is not int or start > end:
            raise ValueError('Invalid physical line range')
        for number in range(start, end + 1):
            if ('enum' in limit and number not in limit['enum']) or number < limit.get('minimum', 0) or number > limit.get('maximum', math.inf):
                raise ValueError('Citation was not physically delivered')
        kind = item['type']
        facts['types'].add(kind)
        if kind in {'frame', 'reference'}:
            if start != 0 or end != 0:
                raise ValueError('Image citation must use 0,0')
            rows = [item] if kind == 'frame' else []
            if kind == 'frame':
                facts['frame_ids'].add(ident)
        else:
            lines = path.read_text(errors='replace').splitlines()
            if not 1 <= start <= end <= len(lines):
                raise ValueError('Citation outside original physical file')
            if kind == 'state' and start != end:
                raise ValueError('State citations must be singleton physical rows')
            rows = []
            if kind in {'state', 'event', 'action'}:
                rows = [json.loads(line) for line in lines[start-1:end]]
            if (kind == 'source' and qualified_author_source(root,item)
                    and path.suffix.lower() in SOURCE_SUFFIXES
                    and not any(word in path.name.lower() for word in ('rubric', 'requirement', 'generation_report', 'context_used'))
                    and any(line.strip() and not line.lstrip().startswith(('#', '//', '<!--')) for line in lines[start-1:end])):
                facts['source_ids'].add(ident)
        # Native engine exceptions are observed runtime failures even when the
        # engine emits no timestamp. They never establish a successful function
        # or provide invented timing. Require an actual engine stack and a
        # separately delivered implementation citation at the failure gate.
        if kind == 'log' and item['path'] == 'runtime/engine.log':
            excerpt = '\n'.join(lines[start-1:end])
            if (re.search(r'SCRIPT ERROR:|Uncaught (?:TypeError|ReferenceError|Error)|(?:TypeError|ReferenceError):', excerpt)
                    and re.search(r'(?:res://[^\s]+:\d+|\bat\s+[^\n]+:\d+)', excerpt)):
                facts['runtime_error_ids'].add(ident)
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError('Non-object native trace row')
            stamp = row.get('t_ms')
            if type(stamp) not in (float, int) or not math.isfinite(stamp) or stamp < 0:
                raise ValueError('Invalid native timestamp')
            clock = row.get('clock', item.get('clock', manifest.get('clock')))
            if not isinstance(clock, str) or not clock:
                raise ValueError('Missing native clock provenance')
            facts['clocks'].add(clock)
            facts['times'].add(stamp)
            if kind in {'state', 'event'}:
                facts['state_event_times'].add(stamp)
            if kind in {'frame', 'state', 'event'}:
                facts['outcome_rows'].append((ident, stamp, row))
            if kind in {'frame', 'state', 'event'}:
                facts['outcome_times'].add(stamp)
            if kind == 'action' and row.get('sent') is True and not row.get('cleanup_release') and row.get('phase') not in {'up', 'release'} and row.get('kind') not in {'wait', 'release'}:
                facts['action_times'].add(stamp)
                facts['action_rows'].append(row)
    if len(facts['clocks']) > 1 or manifest.get('clock') == 'independent_role_local_monotonic':
        raise ValueError('Mixed/unsupported native clock sessions')
    return facts


def basic_supported(basic, contract, facts):
    if basic['trigger_mode'] not in contract['trigger_modes']:
        raise ValueError('Judge invented a non-frozen trigger mode')
    if basic['status'] != 'NORMAL':
        return False
    if not all(basic[key] for key in ('triggered', 'operation_processed', 'correct_target', 'response_observed', 'no_basic_bug')):
        return False
    if basic['deviation_kind'] not in {'none', 'spec_deviation'}:
        return False
    if not basic['reason'].strip() or len(facts['outcome_times']) < 2 or not facts['frame_ids']:
        return False
    trigger, response = basic['trigger_t_ms'], basic['response_t_ms']
    if (type(trigger) not in (int, float) or type(response) not in (int, float)
            or not math.isfinite(trigger) or not math.isfinite(response)
            or trigger < 0 or not 0 <= response - trigger <= contract['max_response_delay_ms']):
        return False
    if not any(abs(response - value) <= 1 for value in facts['outcome_times']):
        return False
    # Auto mechanisms use actual autonomous outcome/trigger observations; no
    # irrelevant keyboard event is demanded. Rejection does not demand mutation.
    if basic['trigger_mode'] == 'automatic':
        return any(abs(trigger - value) <= 1 for value in facts['outcome_times'])
    return any(abs(trigger - value) <= 1 for value in facts['action_times'])


def credit(source, basic, full, *, source_valid, basic_valid, full_valid):
    if any(row['status'] == 'HARNESS_ERROR' for row in (source, basic, full)):
        raise ValueError('HARNESS_ERROR is not a product score')
    if full['status'] == 'PASS' and (not basic_valid or basic['status'] != 'NORMAL'):
        raise ValueError('Complete PASS contradicts unproven basic functionality')
    if basic['status'] == 'NORMAL' and (not basic['no_basic_bug'] or basic['deviation_kind'] == 'basic_function_bug'):
        raise ValueError('NORMAL contradicts basic-function bug')
    if full_valid and basic_valid:
        return 1.0
    if basic_valid:
        return .5
    if source['status'] == 'EXISTS' and source_valid:
        return .1
    return 0.0


def evaluate(root, protocol, manifest, rules, contracts, raw, specs):
    if contracts.get('revision') == 'outcome_frame_v1':
        from .mechanic_v3_outcome import evaluate as outcome_evaluate
        return outcome_evaluate(root, protocol, manifest, rules, contracts, raw, specs)
    validate_contract(protocol, contracts)
    validate_schema(raw, judgment_schema(specs, rules, manifest))
    result = {}
    for spec in specs:
        ident = spec['id']
        row = raw['checks'][ident]
        source, basic, full = (row[key] for key in ('source_existence', 'basic_function', 'full_spec'))
        if any(value['status'] == 'HARNESS_ERROR' for value in (source, basic, full)):
            raise ValueError('HARNESS_ERROR must remain an unscored engineering task: ' + ident)
        sf, bf, ff = (inspect_references(root, manifest, rules, value['evidence']) for value in (source, basic, full))
        source_valid = bool(sf['source_ids'])
        if source['status'] == 'EXISTS' and (not source_valid or not source['reason'].strip()):
            raise ValueError('Source existence requires actual delivered implementation lines')
        basic_valid = basic_supported(basic, contracts['checks'][ident], bf)
        if basic['status'] == 'NORMAL' and not basic_valid:
            raise ValueError('Claimed NORMAL has insufficient causal native evidence: ' + ident)
        if basic['status'] == 'BUG' and (not basic['counterexample'].strip() or not (bf['outcome_times'] or (bf['runtime_error_ids'] and bf['source_ids']))):
            raise ValueError('BUG needs observed counterexample, not missing evidence')
        if full['status'] == 'FAIL' and (not full['counterexample'].strip() or not (ff['outcome_times'] or (ff['runtime_error_ids'] and ff['source_ids']))):
            raise ValueError('Full FAIL needs observed counterexample')
        endpoint = manifest.get('endpoint_contracts', {}).get(ident, {})
        endpoint_ids = set(manifest.get('endpoint_frames', {}).get(ident, []))
        full_valid = bool(full['status'] == 'PASS' and basic_valid
                          and all(full[key] for key in ('preconditions_met', 'observation_complete', 'all_requirements_proven', 'last_action_completed', 'stable_result'))
                          and full['reason'].strip() and all(full['visible_conditions']) and all(full['state_event_conditions'])
                          and endpoint_ids & ff['frame_ids'] and endpoint.get('reachability') == 'EXECUTABLE')
        if full_valid:
            # All modes keep the predeclared final-action/stable endpoint gate.
            # Only the basic tier removes the v2 input-between-states condition.
            from .endpoint_sparse import observation_support
            _, full_valid = observation_support(root, protocol, {'id': ident, 'evidence': full['evidence']})
        if full['status'] == 'PASS' and not full_valid:
            raise ValueError('Complete PASS lacks all original requirements/stable endpoint: ' + ident)
        value = credit(source, basic, full, source_valid=source_valid, basic_valid=basic_valid, full_valid=full_valid)
        result[ident] = dict(copy.deepcopy(row), credit=value, source_evidence_valid=source_valid,
                             basic_evidence_valid=basic_valid, full_evidence_valid=full_valid)
    return result


def aggregate(protocol, checks):
    expected = {spec['id'] for spec in mechanisms(protocol)}
    if set(checks) != expected:
        raise ValueError('Every frozen Mechanic atom must be scored exactly once')
    endpoints = {}
    for spec in mechanisms(protocol):
        if spec.get('endpoint_weight', 1) != 1 or spec.get('atom_weight', 1) != 1:
            raise ValueError('Unsupported nonuniform frozen Mechanic weight')
        endpoint = spec.get('endpoint_id')
        if not endpoint:
            raise ValueError('Missing frozen endpoint')
        endpoints.setdefault(endpoint, []).append(spec['id'])
    groups = {}
    for endpoint, ids in endpoints.items():
        values = [checks[ident]['credit'] for ident in ids]
        if any(type(value) not in (int, float) or value not in (0, .1, .5, 1) for value in values):
            raise ValueError('Invalid v3 tier')
        groups[endpoint] = {'score': round(100 * sum(values) / len(values), 2),
                            'weight': 1 / len(endpoints), 'atom_ids': ids}
    return {'scoring_protocol': VERSION, 'column': MECHANIC,
            'score': round(sum(row['score'] * row['weight'] for row in groups.values()), 2),
            'mechanism_endpoints': groups, 'checks': checks,
            'status': 'SCORED_PENDING_AUDIT', 'audit_status': '未审计',
            'other_columns': 'NOT_REEVALUATED', 'valid': True}
