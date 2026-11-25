"""Stage1 metrics: per-column verdict format and scoring.

Every metric module exposes:

* ``KEY`` / ``NAME``
* ``item_schema()``      JSON schema of one judge verdict for this metric's rows
* ``credit(row, verdict)`` -> float in [0, 1] (raises ValueError on a
  self-contradictory verdict; that is a harness error, never a product score)
* ``aggregate(rows, credits)`` -> column score 0..100

Two verdict formats exist today: ``binary`` (PASS / FAIL / UNVERIFIED) and
``tiered`` (10/50/100 outcome frame). A column is upgraded by editing only
its own module.
"""
from __future__ import annotations

from . import (story, mechanic, asset_slot, input_consistency, build_quality,
               gameness, playable, code)

ALL = [story, mechanic, asset_slot, input_consistency, build_quality, gameness, playable, code]
BY_KEY = {m.KEY: m for m in ALL}
VERSION = 'stage1-eight-metrics-equal.v1'


def score_case(rows: list[dict], verdicts: dict) -> dict:
    """Score every metric of one case; total = mean of present metrics (equal weight).

    ``verdicts`` maps criterion id -> verdict. A row without a verdict is not
    scored and makes its metric (and the total) incomplete — never zero-filled.
    """
    columns, missing = {}, []
    for m in ALL:
        mine = [r for r in rows if r['metric'] == m.KEY]
        if not mine:
            continue
        absent = [r['id'] for r in mine if r['id'] not in verdicts]
        if absent:
            missing += absent
            columns[m.KEY] = {'name': m.NAME, 'score': None, 'missing': len(absent), 'items': len(mine)}
            continue
        credits = {r['id']: m.credit(r, verdicts[r['id']]) for r in mine}
        columns[m.KEY] = {'name': m.NAME, 'score': round(m.aggregate(mine, credits), 2),
                          'items': len(mine), 'credits': credits}
    complete = not missing
    total = (round(sum(c['score'] for c in columns.values()) / len(columns), 2) if complete else None)
    return {'version': VERSION, 'complete': complete, 'total': total,
            'missing_verdicts': missing, 'columns': columns}
