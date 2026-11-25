"""Conservative deterministic gates around Sol's semantic judgments.

PASS/FAIL/UNVERIFIED is independent of the highest proved 10/50/100 tier.
No scores are written into historical whitebox eight-column publications.
"""
from .common import inside, sha


def reference(root, ref):
    try:
        path = inside(root, ref['path'])
        if not path.is_file() or sha(path) != ref['sha256']:
            return False
        lines = path.read_text(encoding='utf-8-sig', errors='replace').splitlines()
        return (1 <= ref['line'] <= len(lines) and bool(ref['quote'].strip())
                and ref['quote'] in lines[ref['line'] - 1])
    except (KeyError, ValueError, OSError, TypeError):
        return False


def static_credit(root, row):
    return bool(row['implemented'] and row['binding_explanation'].strip()
                and row['implementation_refs'] and row['entry_refs']
                and all(reference(root, ref) and ref['path'].startswith('project/')
                        for ref in row['implementation_refs'] + row['entry_refs']))


def score(row, code, proof, *, needs_window=False, is_geometry=False, is_import=False):
    """Proof is independently extracted from raw capture, never supplied by judge."""
    execution = row['execution']
    normal = (execution == 'NORMAL' and row['triggered'] and row['state_or_event_changed']
              and row['logs_normal'] and proof['action_delivered']
              and proof['state_event_refs_valid'] and proof['log_refs_valid'])
    visual = (normal and row['verdict'] == 'PASS' and row['all_conditions_met']
              and proof['endpoint_bound'] and (not needs_window or proof['window_complete']))
    imports = row['import_checks']
    if is_import:
        visual = visual and imports['integration'] == 'PASS'
    if is_geometry:
        visual = (visual and proof['original_render_available']
                  and imports['geometry'] == 'PASS' and imports['texture'] == 'PASS')
    credit = 100 if visual else 50 if normal else 10 if code else 0
    # Harness faults cannot manufacture a product zero. Static initial credit is still retained.
    harness = execution == 'HARNESS_ERROR'
    return {'task_id': row['task_id'],
            'verdict': 'UNVERIFIED' if row['verdict'] == 'PASS' and not visual else row['verdict'],
            'model_verdict': row['verdict'], 'execution': execution,
            'credit_percent': None if harness else credit, 'static_credit_percent': 10 if code else 0,
            'import_checks': imports, 'reason': row['reason'], 'proof_gates': proof,
            'policy': 'refine-tiered.v1; max(10,50,100), not additive; not official whitebox total'}
