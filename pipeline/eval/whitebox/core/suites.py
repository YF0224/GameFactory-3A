"""Evaluation suites: what a run measures (criteria + metrics + scoring).

The stage1 pipeline (prepare -> judge -> plan -> takes -> score) is shared;
a suite only supplies how a case's criteria are built, the metric modules
(verdict format, credit, aggregation) and how a case is scored. A run records
its suite name in ``manifest.json`` and every step resolves it from there.

* ``stage1`` — whitebox eight metrics, equal-weight total
* ``stage3`` — refine tasks (mechanic / gamefeel / vfx / import), per-dimension
  S_c and Cov_c, no total (``pipeline.eval.refinement``)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Suite:
    name: str
    build: Callable[[str], dict]           # game_id -> {'criteria': [...], ...}
    metrics: dict                          # metric key -> module-like object
    score: Callable[[list, dict], dict]    # (rows, verdicts) -> score dict
    eval_version: str


def get(name: str) -> Suite:
    if name == 'stage1':
        from . import criteria
        from ..metrics import BY_KEY, score_case
        return Suite('stage1', criteria.build, BY_KEY, score_case, 'stage1_v1')
    if name == 'stage3':
        from ..stage3 import SUITE
        return SUITE
    raise KeyError(f'unknown evaluation suite {name!r}')


def tiered(suite: Suite) -> tuple:
    return tuple(k for k, m in suite.metrics.items() if m.FORMAT == 'tiered')
