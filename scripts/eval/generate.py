#!/usr/bin/env python3
"""One-click generation queue: one agent session per (game, model).

    python scripts_new/generate.py --stage 1 --models sol,glm --games 1-20 --engines godot,three_js
    python scripts_new/generate.py --stage 3 --models glm --games 8 --parallel 2
    python scripts_new/generate.py --stage 3 --models sol --games 8 --dry-run      # prepare + prompt only
    python scripts_new/generate.py --stage 3 --models kimi --games 8 --manual       # prompts for a human-driven agent
    python scripts_new/generate.py --stage 3 --models kimi --games 8 --run-id <run> --finalize --rounds 4

Stage 1: single round, frozen prompts/stage1_whitebox.md, output under
         test_data/outputs/initial_game_gen/<model dir>/<GameID>/<run_id>/.
Stage 3: up to 10 rounds resuming the SAME agent session, output under
         test_data/outputs/game_refine/<model dir>/<GameID>/<run_id>/.
Jobs run --parallel at a time (default 1). Re-running with --run-id continues an
existing job (next round of the same session); finished jobs are skipped.

Manual mode (no CLI): --manual prepares the job and writes every round's prompt
to <run>/.generation/manual/; after the rounds are done by hand in one agent
conversation, --finalize writes delivery.json (see MANUAL_GENERATION.md).
"""
from __future__ import annotations

import argparse
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

from _common import BENCH, parse_models, select_cases  # noqa: F401  (sys.path)
from gen import agents, stage1, stage3


def build_jobs(args):
    models = parse_models(args.models)
    if args.stage == '1':
        cases = select_cases(args.games, args.engines)
        return [(m, g, lambda m=m, g=g: (stage1.prepare_job(m, g, args.run_id), stage1)) for m in models for g in cases]
    wanted = set(select_cases(args.games, None))
    cases = [g for g in stage3.games() if g in wanted]
    return [(m, g, lambda m=m, g=g: (stage3.prepare_job(m, g, args.run_id)[0], stage3)) for m in models for g in cases]


def manual(job, module):
    """Write every round's prompt for a human-driven agent conversation; no agent call."""
    folder = job.control / 'manual'
    folder.mkdir(parents=True, exist_ok=True)
    if module is stage1:
        (folder / 'round_01_prompt.md').write_text(
            stage1.render(job.model, job.game_id, job.run_id, job.root), encoding='utf-8')
    else:
        ids, engine = job.notes['task_ids'], job.notes['source']['engine']
        (folder / 'round_01_prompt.md').write_text(
            stage3.first_prompt(job.game_id, job.root, engine, ids), encoding='utf-8')
        for n in range(2, job.max_rounds + 1):
            (folder / f'round_{n:02d}_prompt.md').write_text(
                stage3.next_prompt(job.game_id, engine, ids, n), encoding='utf-8')
    job.notes['manual'] = True
    job.status = 'manual'
    job.save()
    return f'MANUAL {job.model} {job.game_id} {job.run_id}: prompts in {folder}'


def finalize(job, module, rounds):
    """Close a manually driven job: verify the original and write delivery.json."""
    if module is stage1:
        from pipeline.eval.stage1.delivery import validate
        problems = validate(job.root)
        if problems:
            return f'FAILED {job.model} {job.game_id} {job.run_id}: delivery.json {problems}'
    else:
        if not rounds or not 1 <= rounds <= job.max_rounds:
            return f'FAILED {job.model} {job.game_id}: --rounds must be 1..{job.max_rounds}'
        job.rounds = [{'round': n, 'manual': True} for n in range(1, rounds + 1)]
        job.session_id = job.session_id or 'manual'
        stage3.write_delivery(job)
    job.status = 'done'
    job.save()
    return f'DONE {job.model} {job.game_id} {job.run_id} (manual, finalized)'


def run_one(model, game, make, args):
    if args.finalize:
        module = stage1 if args.stage == '1' else stage3
        from gen.jobs import Job
        from gen.paths import model_dir
        job = Job.load(module.OUTPUT / model_dir(model) / game / args.run_id)
        if job is None or job.status != 'manual':
            return f'FAILED {model} {game} {args.run_id}: no manual job to finalize'
        return finalize(job, module, args.rounds)
    job, module = make()
    if args.manual:
        return manual(job, module)
    if job.status == 'manual':
        return f'SKIP {model} {game} {job.run_id}: manual job, finish it with --finalize'
    if job.status == 'done':
        return f'SKIP {model} {game} {job.run_id}: already done'
    agent, env = agents.for_model(model)
    job = module.run_job(job, agent, env, dry_run=args.dry_run)
    detail = job.notes.get('error', '')
    return f'{job.status.upper()} {model} {game} {job.run_id} rounds={len(job.rounds)} {detail}'.rstrip()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--stage', choices=('1', '3'), required=True)
    p.add_argument('--models', help='comma list (default: all in config/models.json)')
    p.add_argument('--games', help="'1-20' or 'G001,G008' (default: all)")
    p.add_argument('--engines', help='stage 1 filter, e.g. godot,three_js,unity3d,ue5')
    p.add_argument('--parallel', type=int, default=1, help='agent sessions running at once (default 1)')
    p.add_argument('--run-id', help='continue / name a specific run (single model+game recommended)')
    p.add_argument('--dry-run', action='store_true', help='prepare job and write the round-1 prompt only')
    p.add_argument('--manual', action='store_true', help='prepare job and write all round prompts for manual use')
    p.add_argument('--finalize', action='store_true', help='finish a manual job (needs --run-id)')
    p.add_argument('--rounds', type=int, help='stage 3 --finalize: rounds actually used')
    args = p.parse_args(argv)
    if args.finalize and not args.run_id:
        p.error('--finalize needs --run-id of the manual job')

    jobs = build_jobs(args)
    if not jobs:
        print('no jobs selected', file=sys.stderr)
        return 2
    if args.run_id and len(jobs) > 1:
        p.error('--run-id names one job; select a single model and game')
    print(f'queue: {len(jobs)} job(s), parallel={args.parallel}', flush=True)
    failed = 0
    with ThreadPoolExecutor(max_workers=max(1, args.parallel)) as pool:
        futures = {pool.submit(run_one, m, g, make, args): (m, g) for m, g, make in jobs}
        for f in as_completed(futures):
            m, g = futures[f]
            try:
                line = f.result()
                failed += line.startswith('FAILED')
                print(line, flush=True)
            except Exception as exc:
                failed += 1
                print(f'ERROR {m} {g}: {type(exc).__name__}: {exc}', file=sys.stderr, flush=True)
                traceback.print_exc()
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
