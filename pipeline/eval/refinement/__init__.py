"""Stage3 refine evaluation: reuses the stage1 pipeline with its own suite.

    criteria.py  one check per refine task (mechanic / gamefeel / vfx / import)
    metrics.py   10/50/100 outcome frame, per-dimension S_c and Cov_c, no total
                 (v2 adds a separate close-view texture check per 3D import)

Deliveries: ``test_data/outputs/game_refine/<model dir>/<GameID>/<run_id>/`` with a
stage3 ``delivery.json``. Run via ``scripts_new/evaluate.py --stage 3``.
"""
from __future__ import annotations

from ..whitebox.core.suites import Suite
from . import criteria, metrics

SUITE = Suite('stage3', criteria.build, metrics.METRICS, metrics.score, 'stage3_v3')
