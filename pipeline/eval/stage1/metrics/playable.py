"""Playable: binary PASS / FAIL / UNVERIFIED, score = 100 * mean(PASS).

Fixed generic import / launch / operate checks, decided by rules from the engine import
result and the recordings (playable_rules.py), never by the judge model.
"""
from ._formats import BINARY, binary_credit, mean_100

KEY = 'playable'
NAME = 'Playable'
FORMAT = 'binary'
RULE_BASED = True      # verdicts come from playable_rules.evaluate


def item_schema():
    return BINARY


def credit(row, verdict):
    return binary_credit(row, verdict)


def aggregate(rows, credits):
    return mean_100(rows, credits)
