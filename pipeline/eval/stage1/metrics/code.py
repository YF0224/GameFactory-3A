"""Code: binary PASS / FAIL / UNVERIFIED, score = 100 * mean(PASS).

Fixed generic static checks on authored source.
"""
from ._formats import BINARY, binary_credit, mean_100

KEY = 'code'
NAME = 'Code'
FORMAT = 'binary'


def item_schema():
    return BINARY


def credit(row, verdict):
    return binary_credit(row, verdict)


def aggregate(rows, credits):
    return mean_100(rows, credits)
