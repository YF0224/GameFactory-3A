#!/usr/bin/env python3
"""One-click evaluation: every metric of a stage in one run per delivery.

    python scripts/eval/evaluate.py --stage 1 --models sol --games 1-20 --engines godot,three_js
    python scripts/eval/evaluate.py --stage 1 --run-dir test_data/outputs/initial_game_gen/kimi_k3/G008_dock_beacon_cs/<run_id>
    python scripts/eval/evaluate.py --stage 1 --models sol --games 1 --list
    python scripts/eval/evaluate.py --stage 3 --models glm --games 8 --run-id <run_id>

Results: test_data/outputs/eval/{whitebox,refine}/<suite version>__judge-<judge model>/<model dir>/<GameID>/<run_id>/score.json
Stage 1 (whitebox) scores eight metrics (+ equal-weight total); stage 3 (refinement) scores
mechanic / gamefeel / vfx / import as S_c and Cov_c per dimension, no total.
Only deliveries that pass the delivery.json contract are evaluated (see intake.py).
--static-only stops after the source-only judge (no planning, no engine).
"""
from __future__ import annotations

import argparse
import importlib
import os
import shlex
import sys
from pathlib import Path

from _common import common, parse_models, select_cases
from pipeline.eval import assets
from pipeline.eval.whitebox.core import pipeline, prepare, suites
from pipeline.eval.whitebox.core.delivery import validate
from pipeline.eval.whitebox.core.paths import read_json
from pipeline.eval.whitebox.core.llm import HarnessError
from pipeline.eval.model_config import EVALUATION_PLANNER_MODEL, CLI_JUDGE_MODEL

STAGE_SUITE = {'1': 'whitebox', '3': 'refinement'}
# Unity OnGUI menus only receive the in-engine input driver's keys with IMGUI forwarding
# (validated in the Playable re-test on Sol G005); harmless for non-OnGUI games.
os.environ.setdefault('GAMEFACTORY_UNITY_IMGUI_FORWARD', '1')
# UE background recording (like Unity's runInBackground): focus-gated games (e.g. pause on lost
# focus) keep running while the recording window is in the background. Validated on G060 (Sol, GLM).
os.environ.setdefault('A3GAME_UE_BACKGROUND_FOCUS', '1')
DEFAULT_JUDGE = CLI_JUDGE_MODEL


def deliveries(stage, models, cases, run_id):
    root = common.STAGE_OUTPUT_ROOTS[stage]
    for m in models:
        for case in cases:
            game = root / common.model_dir(m) / case
            run = game / run_id
            if run.exists():
                yield m, case, run.resolve()


def runtime_dependency_errors(engines) -> list[str]:
    """Check imports before spending model calls on a native evaluation."""
    packages = [('requests', 'requests'), ('PIL', 'Pillow'), ('numpy', 'numpy')]
    if 'unity3d' in engines:
        packages.append(('yaml', 'PyYAML'))
    errors = []
    for module, package in packages:
        try:
            importlib.import_module(module)
        except ImportError as exc:
            errors.append(f'{package}: {exc}')
    return errors


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--stage', choices=('1', '3', 'assets'), required=True)
    p.add_argument('--models')
    p.add_argument('--games')
    p.add_argument('--engines')
    p.add_argument('--run-id', default='latest', help="run directory name (default: 'latest')")
    p.add_argument('--run-dir', type=Path, nargs='+', help='evaluate exactly these delivery directories')
    p.add_argument('--planner', default=EVALUATION_PLANNER_MODEL)
    p.add_argument('--judge', default=DEFAULT_JUDGE,
                   help='judge (and frozen-standard) model; claude-* runs via Claude Code, gpt-* via Codex')
    p.add_argument('--static-only', action='store_true', help='stage 1: source-only static rows, no engine')
    p.add_argument('--plan-only', action='store_true',
                   help='also make (and validate) the take-1 plan, but record nothing; judge on source only')
    p.add_argument('--source-only', action='store_true',
                   help='judge every criterion on source evidence only (no plan / engine; 10%% tier at most)')
    p.add_argument('--metrics', help='stage 3 selected dimensions: mechanic,gamefeel')
    p.add_argument('--reuse-root', type=Path, help='historical eval root for source-bound plan reuse')
    p.add_argument('--replay-plans', action='store_true', help='record historical plans only; no planner calls')
    p.add_argument('--list', action='store_true', help='only list what would be evaluated')
    args = p.parse_args(argv)

    if args.stage == 'assets':
        return assets.run([])
    stage, suite = ('whitebox' if args.stage == '1' else 'refinement'), STAGE_SUITE[args.stage]

    if args.run_dir:
        names = {v: k for k, v in common.MODEL_DIRS.items()}
        runs = [r.resolve() for r in args.run_dir]
        # Support both:
        # 1. Standard layout: <model_dir>/<GameID>/<run_id>  -> parents[1] is model_dir
        # 2. Direct game dir: <GameID>  -> fall back to 'sol' as default model slot
        todo = []
        for r in runs:
            model_candidate = names.get(r.parents[1].name, r.parents[1].name)
            if model_candidate not in common.MODEL_DIRS:
                model_candidate = 'sol'
            todo.append((model_candidate, r.parent.name, r))
    else:
        todo = list(deliveries(stage, parse_models(args.models), select_cases(args.games, args.engines), args.run_id))
    # One eval tree per (suite version, judge model): verdicts and frozen standards never mix judges.
    root = common.EVAL_ROOTS[stage] / f'{suites.get(suite).eval_version}__judge-{args.judge}'
    models = {'planner': args.planner, 'judge': args.judge}
    ready = []
    for model, case, run in todo:
        problems = validate(run)
        out = root / common.model_dir(model) / case / run.name
        if problems:
            print(f'SKIP {model} {case} {run.name}: {problems[0]}')
        elif args.list:
            print(f'TODO {model} {case} {run.name} -> {out}')
        else:
            ready.append((model, case, run, out))
    if ready and not (args.static_only or args.plan_only or args.source_only):
        engines = {read_json(run / 'delivery.json')['engine'] for _, _, run, _ in ready}
        dependency_errors = runtime_dependency_errors(engines)
        if dependency_errors:
            install = shlex.join([sys.executable, '-m', 'pip', 'install', '-r',
                                  str(Path(__file__).resolve().parents[1] / 'requirements.txt')])
            p.exit(2, 'Runtime dependencies unavailable; no evaluation was started.\n'
                   + '\n'.join(dependency_errors) + f'\nPython: {sys.executable}\nInstall: {install}\n')
    if args.metrics:
        if suite != 'stage3' or args.static_only or args.plan_only or args.source_only:
            p.error('--metrics requires a normal stage 3 runtime evaluation')
        from pipeline.eval.refinement import selected
        dims = tuple(args.metrics.split(','))
        if not dims or set(dims) - set(selected.ALLOWED):
            p.error('selected dimensions must be mechanic,gamefeel')
        failed = 0
        for model, case, run, out in ready:
            try:
                result = selected.run(run, out, models=models, dimensions=dims, reuse_root=args.reuse_root, replay_plans=args.replay_plans)
                print(model, case, {k: (v['S'], v['Cov']) for k, v in result['dimensions'].items()}, flush=True)
            except Exception as exc:
                failed += 1
                print(f'HARNESS_ERROR {model} {case}: {type(exc).__name__}: {exc}', flush=True)
        return 1 if failed else 0
    # Phase 1: prepare every delivery first, so a case's shared frozen standard
    # sees all of its models' sources regardless of evaluation order.
    for model, case, run, out in ready:
        prepare.prepare(run, out, models=models, suite=suite)
    failed = 0
    for model, case, run, out in ready:
        peers = [o for _, c, _, o in ready if c == case and o != out]
        try:
            result = pipeline.run(run, out, standards_root=root, peers=peers, models=models, suite=suite,
                                  stop_after=('plan_only' if args.plan_only else
                                              'source_only' if args.source_only else
                                              'static_judge' if args.static_only else None))
            if 'dimensions' in result:
                dims = ' '.join(f'{k}={d["S"]}(cov {d["Cov"]})' for k, d in result['dimensions'].items())
                print(f'DONE {model} {case} {dims} complete={result["complete"]}')
            else:
                print(f'DONE {model} {case} total={result["total"]} complete={result["complete"]}')
        except HarnessError as exc:
            failed += 1
            print(f'HARNESS_ERROR {model} {case}: {exc}', file=sys.stderr)
        except Exception as exc:
            failed += 1
            print(f'ERROR {model} {case}: {type(exc).__name__}: {exc}', file=sys.stderr)
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
