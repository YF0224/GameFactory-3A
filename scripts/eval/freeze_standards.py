#!/usr/bin/env python3
"""Draft, review and approve the frozen benchmark standards (one per case and tiered metric).

Standards are written ahead of evaluation from the case requirement, the CHECKS and the
shared baseline (stage3: the original Sol project every model refined), never from
candidate deliveries, and take effect only after human approval. Evaluation refuses to
run on a case without an approved standard.

    python scripts_new/freeze_standards.py --stage 3 --games G015,G030            # draft + review.md
    python scripts_new/freeze_standards.py --stage 3 --status
    python scripts_new/freeze_standards.py --stage 3 --approve G015_garden_revival --reviewer yifan

Output: test_data/bench_standards/<suite>/<criteria version>/<GameID>/{<metric>.json, review.md, approved.json}
"""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor

from _common import common, select_cases  # noqa: F401  (sets sys.path)

from pipeline.eval.stage1 import standards, suites  # noqa: E402

SUITES = {'1': 'stage1', '3': 'stage3'}


def _cases(stage: str, games: str | None) -> list[str]:
    if stage == '3':
        from pipeline.eval.stage3.criteria import INPUTS
        have = sorted(p.name for p in INPUTS.iterdir() if p.is_dir() and p.name[:1] == 'G')
        if not games:
            return have
        wanted = {g.strip().upper()[:4] for g in games.split(',')}
        return [c for c in have if c[:4] in wanted]
    return select_cases(games, None)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--stage', choices=SUITES, required=True)
    ap.add_argument('--games', help="e.g. 'G015,G030' (default: every case of the stage)")
    ap.add_argument('--model', default='claude-opus-5-5', help='standard writer (default Opus 5.5)')
    ap.add_argument('--parallel', type=int, default=2, help='cases drafted at once (metrics run concurrently inside)')
    ap.add_argument('--status', action='store_true')
    ap.add_argument('--approve', metavar='GAME_ID')
    ap.add_argument('--reviewer', default='human')
    args = ap.parse_args()
    suite = SUITES[args.stage]
    build = suites.get(suite).build

    if args.approve:
        rows = build(args.approve)
        folder = standards.bench_dir(suite, rows['version'], args.approve)
        print(standards.approve(folder, args.reviewer))
        return 0

    cases = _cases(args.stage, args.games)
    if args.status:
        for game in cases:
            version = build(game)['version']
            folder = standards.bench_dir(suite, version, game)
            drafted = sorted(p.stem for p in folder.glob('*.json') if p.name != 'approved.json') if folder.is_dir() else []
            state = 'APPROVED' if (folder / 'approved.json').is_file() else ('DRAFTED' if drafted else '-')
            print(f'{game:40s} {state:9s} {",".join(drafted)}')
        return 0

    def one(game):
        crit = build(game)
        baseline = None
        if args.stage == '3':
            sys.path.insert(0, str(common.BENCH / 'scripts_new'))
            from gen.stage3 import source_project
            baseline = source_project(game)['root']
        result = standards.draft(game, crit['criteria'], suite=suite, criteria_version=crit['version'],
                                 requirement=common.SAMPLES / game / 'general_requirement.txt',
                                 model=args.model, baseline=baseline)
        folder = standards.bench_dir(suite, crit['version'], game)
        print(f'{game}: generated {result["generated"]} failed {result["failed"]}\n  review: {folder / "review.md"}',
              flush=True)
        return not result['failed']

    with ThreadPoolExecutor(max_workers=max(1, args.parallel)) as pool:
        ok = all(pool.map(one, cases))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
