"""故事完整性: binary PASS / FAIL / UNVERIFIED, score = 100 * mean(PASS).

Fixed generic static checks (background/identity/goal/plot); authored source or delivery documents only.
"""
from ._formats import BINARY, binary_credit, mean_100

KEY = 'story'
NAME = '故事完整性'
FORMAT = 'binary'


def item_schema():
    return BINARY


def credit(row, verdict):
    return binary_credit(row, verdict)


def aggregate(rows, credits):
    return mean_100(rows, credits)
