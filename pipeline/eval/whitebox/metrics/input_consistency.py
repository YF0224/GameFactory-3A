"""白模输入一致性: binary PASS / FAIL / UNVERIFIED, score = 100 * mean(PASS).

Frozen Q subchecks that compare against the reference images.
"""
from ._formats import BINARY, binary_credit, mean_100

KEY = 'input_consistency'
NAME = '白模输入一致性'
FORMAT = 'binary'


def item_schema():
    return BINARY


def credit(row, verdict):
    return binary_credit(row, verdict)


def aggregate(rows, credits):
    return mean_100(rows, credits)
