"""Wall-clock and model-call budgets by complexity tier.

Same tier envelopes as the historical evaluator (S 75 s / M 180 s / L 300 s of
gameplay). Budgets are pinned into each run's manifest before anything runs,
so later edits here never change an existing run.
"""
from __future__ import annotations

import re

from .paths import SAMPLES

VERSION = 'stage1-budgets.v1'

TIERS = {
    'S': {'engine_startup_ms': 90000, 'menu_prepare_ms': 15000, 'gameplay_ms': 75000,
          'capture_tail_ms': 10000, 'single_step_ms': 30000, 'engine_call_ms': 210000,
          'plan_timeout_s': 600, 'judge_timeout_s': 900},
    'M': {'engine_startup_ms': 180000, 'menu_prepare_ms': 30000, 'gameplay_ms': 180000,
          'capture_tail_ms': 15000, 'single_step_ms': 60000, 'engine_call_ms': 450000,
          'plan_timeout_s': 900, 'judge_timeout_s': 1200},
    'L': {'engine_startup_ms': 300000, 'menu_prepare_ms': 45000, 'gameplay_ms': 300000,
          'capture_tail_ms': 20000, 'single_step_ms': 60000, 'engine_call_ms': 720000,
          'plan_timeout_s': 1500, 'judge_timeout_s': 1800},
}
# Frozen per-case exceptions (not tuned from results).
CASE_OVERRIDES = {
    'G057_rhythm_machine_hall': {'gameplay_ms': 125000, 'engine_startup_ms': 90000,
                                 'menu_prepare_ms': 15000, 'capture_tail_ms': 12000,
                                 'engine_call_ms': 270000, 'single_step_ms': 60000},
}


def case_tier(game_id: str) -> str:
    """Canonical tier from ``tier:`` in general_requirement.txt (S / M / L-Regular / L-Stress)."""
    from .paths import EVAL_DATA
    req = EVAL_DATA / game_id / 'general_requirement.txt'
    if not req.exists():
        req = SAMPLES / game_id / 'general_requirement.txt'
    text = req.read_text(encoding='utf-8')
    found = re.findall(r'(?m)^tier:\s*([^\s#]+)', text)
    if len(found) != 1:
        raise ValueError(f'{game_id}: general_requirement.txt must declare exactly one tier')
    return 'L-Regular' if found[0] == 'L' else found[0]


def budget_for(game_id: str) -> dict:
    tier = case_tier(game_id)
    row = dict(TIERS[tier.split('-')[0]])
    row.update(CASE_OVERRIDES.get(game_id, {}))
    row['recording_ms'] = row['gameplay_ms']
    row['total_wall_clock_ms'] = (row['engine_startup_ms'] + row['menu_prepare_ms']
                                  + row['gameplay_ms'] + row['capture_tail_ms'])
    if row['total_wall_clock_ms'] > row['engine_call_ms']:
        raise ValueError(f'{game_id}: engine call cap does not cover component budgets')
    return {'version': VERSION, 'tier': tier, **row}


#: Follow-up takes chase the checks earlier takes did not reach, which usually lie deeper in the
#: game: they get a longer recording (and proportionally longer engine call).
TAKE_SCALE = {1: 1.0, 2: 1.0, 3: 1.0}   # follow-ups target few checks; keep each take short


def for_take(budget: dict, take: int) -> dict:
    scale = TAKE_SCALE.get(take, max(TAKE_SCALE.values()))
    if scale == 1.0:
        return budget
    row = dict(budget)
    extra = round(budget['gameplay_ms'] * (scale - 1))
    row['gameplay_ms'] = budget['gameplay_ms'] + extra
    row['recording_ms'] = budget['recording_ms'] + extra
    row['total_wall_clock_ms'] = budget['total_wall_clock_ms'] + extra
    row['engine_call_ms'] = budget['engine_call_ms'] + extra
    row['take_scale'] = scale
    return row
