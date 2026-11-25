"""资产预留: binary PASS / FAIL / UNVERIFIED, score = 100 * mean(PASS).

Each frozen C3 item x {placeholder, binding, hook}, all rows equal weight
= 100/3 * sum(passed_d / required_d) over the three dimensions.
"""
from ._formats import BINARY, binary_credit, mean_100

KEY = 'asset_slot'
NAME = '资产预留'
FORMAT = 'binary'


def item_schema():
    return BINARY


def credit(row, verdict):
    return binary_credit(row, verdict)


def aggregate(rows, credits):
    return mean_100(rows, credits)
