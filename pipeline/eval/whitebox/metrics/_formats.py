"""Shared verdict formats used by the metric modules."""
from __future__ import annotations

from ..llm import B, S, arr, enum, obj

REF = obj({'id': S, 'line_start': {'type': 'integer'}, 'line_end': {'type': 'integer'}, 'observation': S})
EVIDENCE = arr(REF)

# --- binary: PASS / FAIL / UNVERIFIED --------------------------------------
BINARY = obj({'status': enum('PASS', 'FAIL', 'UNVERIFIED'), 'reason': S,
              'preconditions_met': B, 'observation_complete': B,
              'counterexample': S, 'evidence': EVIDENCE})


def binary_credit(row, verdict) -> float:
    """PASS=1, FAIL/UNVERIFIED=0. Unsupported PASS/FAIL is downgraded upstream."""
    if verdict['status'] == 'FAIL' and not verdict['counterexample'].strip():
        return 0.0
    return 1.0 if verdict['status'] == 'PASS' else 0.0


def mean_100(rows, credits) -> float:
    return 100.0 * sum(credits[r['id']] for r in rows) / len(rows)


# --- tiered 10 / 50 / 100 outcome frame --------------------------------------
TRIGGER_MODES = ('input', 'held', 'automatic', 'delayed', 'rejection')
PROCESSING_BASIS = ('visual_effect', 'explicit_feedback', 'event_processing',
                    'contextual_sequence', 'unchanged_state_only', 'none')
SOURCE_SUFFIXES = ('.gd', '.cs', '.js', '.mjs', '.ts', '.tscn', '.unity', '.prefab', '.cpp', '.h',
                   '.py', '.html', '.json', '.tres', '.shader', '.gdshader', '.uasset', '.umap', '.ini')


def tiered_schema(*, basic_extra: dict, result_extra: dict, clear_label: str) -> dict:
    return obj({
        'source_existence': obj({'status': enum('EXISTS', 'ABSENT', 'UNVERIFIED', 'HARNESS_ERROR'),
                                 'reason': S, 'evidence': EVIDENCE}),
        'basic_function': obj({'status': enum('NORMAL', 'BUG', 'UNOBSERVED', 'HARNESS_ERROR'),
                               'trigger_mode': enum(*TRIGGER_MODES), 'correct_target': B,
                               'functional_effect_proven': B, 'no_basic_bug': B,
                               'processing_basis': enum(*PROCESSING_BASIS), **basic_extra,
                               'reason': S, 'counterexample': S, 'evidence': EVIDENCE}),
        'result_outcome': obj({'status': enum('ACHIEVED', 'NOT_PROVEN', 'CONTRADICTED', 'HARNESS_ERROR'),
                               'frame_assessment': enum(clear_label, 'ambiguous', 'decorative_only', 'no_frame'),
                               'result_frame_id': S, 'correct_target': B, 'no_basic_bug': B,
                               'processing_proven': B, **result_extra,
                               'reason': S, 'counterexample': S, 'evidence': EVIDENCE}),
        'diagnostics': arr(S),
    })


def _ids(part, prefix):
    return {e['id'] for e in part['evidence'] if e['id'].startswith(prefix)}


def _source_cited(part) -> bool:
    return any(e['id'].startswith('SRC:') and e['id'].lower().endswith(SOURCE_SUFFIXES) and e['line_start'] >= 1
               for e in part['evidence'])


def tiered_credit(verdict, *, basic_flags, result_flags, clear_label) -> float:
    """Highest supported tier, not cumulative: 1.0 / 0.5 / 0.1 / 0.0."""
    src, basic, result = verdict['source_existence'], verdict['basic_function'], verdict['result_outcome']
    if 'HARNESS_ERROR' in (src['status'], basic['status'], result['status']):
        raise ValueError('HARNESS_ERROR inside a verdict: tool failure, not a product score')
    if basic['status'] == 'BUG' and not basic['counterexample'].strip():
        raise ValueError('BUG without an observed counterexample')
    if result['status'] == 'CONTRADICTED' and not result['counterexample'].strip():
        raise ValueError('CONTRADICTED without an observed counterexample')
    bug = basic['status'] == 'BUG' or result['status'] == 'CONTRADICTED'
    rejection = basic['trigger_mode'] == 'rejection'
    outcome = (result['status'] == 'ACHIEVED' and result['frame_assessment'] == clear_label
               and result['result_frame_id'] in (_ids(result, 'FRAME') | _ids(result, 'VIEW'))
               and all(result[f] for f in result_flags)
               and (result['processing_proven'] or not rejection) and not bug)
    if outcome:
        return 1.0
    functional = (basic['status'] == 'NORMAL' and all(basic[f] for f in basic_flags)
                  and basic['processing_basis'] not in ('unchanged_state_only', 'none')
                  and bool(_ids(basic, 'FRAME') | _ids(basic, 'VIEW') | _ids(basic, 'STATE') | _ids(basic, 'EVENT'))
                  and not bug)   # VIEW: in-engine render of an imported asset (only delivered for asset checks)
    if functional:
        return 0.5
    if src['status'] == 'EXISTS' and _source_cited(src):
        return 0.1
    return 0.0
