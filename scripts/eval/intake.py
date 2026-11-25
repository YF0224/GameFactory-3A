#!/usr/bin/env python3
"""Validate deliveries (ours or external) against the delivery contract.

    python scripts_new/intake.py --stage 1 --models kimi --games 1-20
    python scripts_new/intake.py --run-dir test_data/outputs/initial_game_gen/kimi_k3/G008_dock_beacon_cs/<run_id>

Read-only. Reports every run directory and its contract problems.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from _common import common, parse_models, select_cases
from pipeline.eval.stage1.delivery import validate


def iter_runs(stage: str, models: list[str], cases: list[str]):
    root = common.STAGE_OUTPUT_ROOTS[stage]
    for m in models:
        for case in cases:
            game_dir = root / common.model_dir(m) / case
            if not game_dir.is_dir():
                continue
            for run in sorted(game_dir.iterdir()):
                if run.is_dir() and not run.is_symlink():
                    yield m, case, run


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--stage', choices=('1', '3'))
    p.add_argument('--models')
    p.add_argument('--games')
    p.add_argument('--engines')
    p.add_argument('--run-dir', type=Path, help='check one run directory only')
    args = p.parse_args(argv)

    if args.run_dir:
        runs = [('-', args.run_dir.parent.name, args.run_dir.resolve())]
    elif args.stage:
        runs = list(iter_runs('stage' + args.stage, parse_models(args.models),
                              select_cases(args.games, args.engines)))
    else:
        p.error('give --stage or --run-dir')

    bad = 0
    for model, case, run in runs:
        problems = validate(run)
        bad += bool(problems)
        print(f'{"OK  " if not problems else "FAIL"} {model:6} {case} {run.name}')
        for problem in problems:
            print(f'       - {problem}')
    print(f'{len(runs)} runs, {bad} not admissible', file=sys.stderr)
    return 1 if bad else 0


if __name__ == '__main__':
    raise SystemExit(main())
