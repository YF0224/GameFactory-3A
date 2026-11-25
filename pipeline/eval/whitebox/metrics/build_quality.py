"""白模构建质量: binary PASS / FAIL / UNVERIFIED, score = 100 * mean(PASS).

Frozen non-reference Q subchecks plus three generic visual checks.
"""
from ._formats import BINARY, binary_credit, mean_100

KEY = 'build_quality'
NAME = '白模构建质量'
FORMAT = 'binary'


def item_schema():
    return BINARY


def credit(row, verdict):
    return binary_credit(row, verdict)


def aggregate(rows, credits):
    return mean_100(rows, credits)
