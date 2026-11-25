"""Model defaults shared by evaluation entrypoints and bounded recovery modules.

Set environment overrides before starting the Python process. Explicit CLI model
arguments still win. Historical output directory names remain immutable identities.
"""
import os

ASTRA_MODEL = 'gpt-6-astra'
SOL_MODEL = 'gpt-6.1-sol'
OPUS_MODEL = 'claude-opus-5-5'


def _model(variable, default):
    value = os.environ.get(variable, default).strip()
    if not value:
        raise ValueError(variable + ' must name a model')
    return value


PLANNER_MODEL = _model('A3GAME_PLANNER_MODEL', ASTRA_MODEL)
JUDGE_MODEL = _model('A3GAME_JUDGE_MODEL', SOL_MODEL)
LAUNCH_REPAIR_MODEL = _model('A3GAME_LAUNCH_REPAIR_MODEL', JUDGE_MODEL)

# Preserve the existing general-evaluation CLI's Sol planner / Opus judge defaults.
EVALUATION_PLANNER_MODEL = _model('A3GAME_PLANNER_MODEL', SOL_MODEL)
CLI_JUDGE_MODEL = _model('A3GAME_JUDGE_MODEL', OPUS_MODEL)
