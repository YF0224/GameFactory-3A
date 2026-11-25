"""Source-based coverage guidance; no score, rubric, or gameplay-state changes."""
import os


def enabled():
    return os.environ.get('A3GAME_COVERAGE_RECORDING') == '1'


def instructions():
    return [
        'COVERAGE RECORDING: increase distinct meaningful interactions, not arbitrary key spam.',
        'For each reachable target, include the setup path from a fresh launch, the exact authored control, '
        'and a post-action wait long enough for the authored animation/timer/result to complete.',
        'A key label drawn on a HUD is not proof of a key binding. Read its actual input handler. '
        'For Canvas hitboxes, plan mouse coordinates only when the native viewport pointer capability is enabled.',
        'Split long source-defined delays into legal wait steps; do not stop after entering the game. '
        'Stay within the frozen gameplay/time/step budgets. Do not invent shortcuts, teleport, or edit state.',
        'Use the remaining budget for different reachable mechanic and feedback branches: confirm/cancel, '
        'selection changes, action completion, resource changes, success/failure, and progression where implemented. '
        'Only include branches supported by this author source and targeted requirements.',
        'Capture an observable baseline, the action, and its outcome: add explicit waits for motion and transient '
        'feedback and list their criterion_ids on those steps. Input acknowledgment alone is not evidence of success.',
        'Follow-up takes restart the game: replay all prerequisites before the missing target. Use prior action '
        'timings and judge reasons to change the route or wait time; never replace a deep sequence with Enter twice.',
        'Report truly unreachable targets in uncovered with the missing prerequisite. Never claim a target is '
        'covered just because a probe names its criterion id. Do not replay an unchanged failed route indefinitely.',
    ]


def enrich_feedback(feedback, earlier_plans, ids, verdicts):
    """Preserve complete bounded step sequences so a follow-up can fix its route."""
    result = dict(feedback)
    result['coverage_mode'] = True
    result['restart_from_fresh_launch'] = True
    result['earlier_action_sequences'] = [
        {'take': take, 'probes': p['probes'], 'uncovered': p.get('uncovered', [])}
        for take, p in earlier_plans
    ]
    result['runtime_statuses'] = {
        i: {part: verdicts.get(i, {}).get(part) for part in ('basic_function', 'result_outcome')}
        for i in ids
    }
    return result
