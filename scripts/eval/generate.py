#!/usr/bin/env python3
"""One-click generation queue: one agent session per (game, model).

    python scripts/eval/generate.py --stage 1 --models sol,glm --games 1-20 --engines godot,three_js
    python scripts/eval/generate.py --stage 3 --models glm --games 8 --parallel 2
    python scripts/eval/generate.py --stage 3 --models sol --games 8 --dry-run      # prepare + prompt only
    python scripts/eval/generate.py --stage 3 --models kimi --games 8 --manual       # prompts for a human-driven agent
    python scripts/eval/generate.py --stage 3 --models kimi --games 8 --run-id <run> --finalize --rounds 4

Stage 1: single round, frozen prompts/stage1_whitebox.md, output under
         test_data/outputs/initial_game_gen/<model dir>/<GameID>/<run_id>/.
Stage 3: up to 10 rounds resuming the SAME agent session, output under
         test_data/outputs/playtest/g<N>/<model>/.
Jobs run --parallel at a time (default 1). Re-running with --run-id continues an
existing job (next round of the same session); finished jobs are skipped.

Manual mode (no CLI): --manual prepares the job and writes every round's prompt
to <run>/.generation/manual/; after the rounds are done by hand in one agent
conversation, --finalize writes delivery.json (see MANUAL_GENERATION.md).
"""
from __future__ import annotations

import argparse
import sys
import os
from pathlib import Path
from datetime import datetime
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

from _common import BENCH, parse_models, select_cases  # noqa: F401  (sys.path)
from gen import agents, stage1, stage3


def build_jobs(args):
    from gen.inputs import stage1_tasks, matches
    from gen.playtest_inputs import load
    models = parse_models(args.models)
    if args.stage == '1':
        tasks = stage1_tasks(args)  # validates the entire input before any mkdir
        return [(m, task['game_id'] + '/' + task['engine'],
                 lambda m=m, task=task: (stage1.prepare_job(
                     m, task['game_id'], args.run_id, requirement=task['requirement'], engine=task['engine']), stage1))
                for task in tasks for m in models]
    candidates = [Path(args.refine_json).resolve()] if args.refine_json else stage3.games()
    tasks = []
    errors = []
    for game in candidates:
        try:
            directory, index, _ = load(game)
            if not (matches(index['game_id'], args.games)
                    or args.games and directory.name in args.games.split(',')):
                continue
            stage3.source_project(game)
            stage3.task_document(game)
            tasks.append((str(directory / 'refine.json'), index['game_id']))
        except (ValueError, OSError, KeyError, TypeError) as exc:
            errors.append(f'{game}: {exc}')
    if errors:
        raise ValueError('Invalid refine inputs; no jobs created:\n' + '\n'.join(errors))
    return [(m, gid, lambda m=m, game=game: (stage3.prepare_job(m, game, args.run_id)[0], stage3))
            for game, gid in tasks for m in models]


def manual(job, module):
    """Write every round's prompt for a human-driven agent conversation; no agent call."""
    folder = job.control / 'manual'
    folder.mkdir(parents=True, exist_ok=True)
    if module is stage1:
        (folder / 'round_01_prompt.md').write_text(
            stage1.render(job.model, job.game_id, job.run_id, job.root, Path(job.notes['requirement']), job.notes['engine']), encoding='utf-8')
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
        from gen.jobs import Job
        from gen.paths import model_dir
        module = stage1 if args.stage == '1' else stage3
        if module is stage1:
            root = stage1.OUTPUT / model_dir(model) / game.split('/')[0] / args.run_id
        else:
            from gen.playtest_inputs import folder
            root = folder(game) / model
        job = Job.load(root)
        if job is None or job.status != 'manual' or job.run_id != args.run_id:
            raise ValueError(f'No matching manual job to finalize: {root}')
        message = finalize(job, module, args.rounds)
    else:
        job, module = make()
        if args.manual:
            message = manual(job, module)
        elif job.status in ('manual', 'done'):
            message = f'SKIP {model} {game}: {job.status}'
        else:
            agent, env = (None, {}) if args.dry_run else agents.for_model(model)
            # Native engine operations share the framework engine/GUI slot leases.
            env = {**env, 'A3GAME_EXCLUSIVE_ENGINE': os.environ.get('A3GAME_EXCLUSIVE_ENGINE', '1'),
                   'A3GAME_GUI_SLOTS': os.environ.get('A3GAME_GUI_SLOTS', '1')}
            job = module.run_job(job, agent, env, dry_run=args.dry_run)
            message = f'{job.status.upper()} {model} {game} rounds={len(job.rounds)} {job.notes.get("error", "")}'.strip()
    return {'model': model, 'game': game, 'status': 'failed' if message.startswith('FAILED') else job.status,
            'run_id': job.run_id, 'run_root': str(job.root), 'message': message,
            'prompts': [str(p) for p in sorted(job.control.glob('rounds/*/prompt.txt'))]}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--stage', choices=('1', '3'), required=True)
    inputs = p.add_mutually_exclusive_group()
    inputs.add_argument('--requirement', type=Path, help='stage 1: one requirement file')
    inputs.add_argument('--collect', type=Path, help='stage 1: JSONL queue (default test_data/pipeline_collect.jsonl)')
    inputs.add_argument('--refine-json', type=Path, help='stage 3: a playtest/gN/refine.json')
    p.add_argument('--game-id', help='stage 1 single requirement: full game identifier')
    p.add_argument('--engine', choices=('godot', 'three_js', 'unity3d', 'ue5'), help='stage 1 single requirement engine override')
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

    if args.stage == '3' and (args.requirement or args.collect or args.engine or args.game_id):
        p.error('requirement/collect/engine/game-id are stage 1 inputs')
    if args.stage == '1' and args.refine_json:
        p.error('--refine-json requires stage 3')
    if (args.engine or args.game_id) and not args.requirement:
        p.error('--engine and --game-id require --requirement')
    if args.parallel < 1:
        p.error('--parallel must be positive')
    if sum((args.dry_run, args.manual, args.finalize)) > 1:
        p.error('choose only one of --dry-run, --manual, --finalize')
    try:
        jobs = build_jobs(args)
    except (ValueError, OSError) as exc:
        p.error(str(exc))
    if not jobs:
        print('no jobs selected', file=sys.stderr)
        return 2
    if args.run_id and len(jobs) > 1:
        p.error('--run-id names one job; select a single model and game')
    print(f'queue: {len(jobs)} job(s), parallel={args.parallel}', flush=True)
    failed = 0
    results = []
    with ThreadPoolExecutor(max_workers=max(1, args.parallel)) as pool:
        futures = {pool.submit(run_one, m, g, make, args): (m, g) for m, g, make in jobs}
        for f in as_completed(futures):
            m, g = futures[f]
            try:
                result = f.result()
                results.append(result)
                failed += result['status'] == 'failed'
                print(result['message'] + f' run={result["run_root"]}', flush=True)
                for prompt in result['prompts']:
                    print('prompt:', prompt, flush=True)
            except Exception as exc:
                failed += 1
                results.append({'model': m, 'game': g, 'status': 'failed', 'error': str(exc)})
                print(f'ERROR {m} {g}: {type(exc).__name__}: {exc}', file=sys.stderr, flush=True)
                traceback.print_exc()
    from gen.paths import OUTPUTS, write_json
    summary = OUTPUTS / 'generation_summaries' / f'{datetime.now():%Y%m%d_%H%M%S_%f}.json'
    write_json(summary, {'stage': args.stage, 'jobs': sorted(results, key=lambda r: (r['game'], r['model'])), 'failed': failed})
    print(f'summary: {summary}')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
