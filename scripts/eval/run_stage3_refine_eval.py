#!/usr/bin/env python3
"""Stage3 refine-candidate evaluation in one command (current pipeline, all fixes on).

    python scripts_new/run_stage3_refine_eval.py --model glm --games G015,G045 \\
        --planner gpt-6-astra --judge gpt-6.1-sol --run-id glm_refine_eval_20261111
    python scripts_new/run_stage3_refine_eval.py --model sol --games all --planner gpt-6-astra --judge gpt-6.1-sol

What it does:
  1. Creates the delivery files for the chosen refine candidates (paths from the refine session's
     sol/glm manifest; the candidate is snapshotted by the eval, the original stays untouched).
  2. Runs scripts_new/evaluate.py --stage 3 with the planner / judge you give.
Scores: mechanic / gamefeel / vfx (10/50/100, judged), import (assets in the project, by rules),
texture (in-game asset photos vs original, mean F, plus availability / coverage), playable (rules).
Results: test_data/outputs/eval/refine/stage3_v3__judge-<judge>/<model dir>/<GameID>/<run id>/score.json
Summary: python scripts_new/stage3_scores.py --root <that eval root> --run-suffix <run id suffix>

Defaults set here: OnGUI forwarding, UE background focus, UE keyboard-only input, 1-hour budget per
game, two GUI slots. Use --lean to judge mechanic / gamefeel with the approved lean rubric.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BENCH = HERE.parent
sys.path.insert(0, str(BENCH / 'GameFactory-3A'))
from pipeline.eval.model_config import PLANNER_MODEL, JUDGE_MODEL
CONTROL = BENCH / 'test_data/outputs/game_refine/stage3_sol_astra_glm_fresh_20261104_210835/direct_agents_20261105_100055'
SHIMS = BENCH / 'test_data/outputs/legacy_deliveries/stage3'
MODEL_DIRS = {'sol': 'gpt_sol6p1', 'glm': 'glm_5p3', 'kimi': 'kimi_k3', 'astra': 'gpt_astra6', 'opus': 'claude_ops5p5'}
GAMES_ROOT = Path(os.environ.get('STAGE3_REFINE_GAMES_ROOT') or BENCH / 'test_data/outputs/initial_game_gen/gpt_sol6p1')
# Control manifests record their original root. Remap only that root's descendants.
def local(value, origin_bench=None):
    if origin_bench is None:
        if not isinstance(value, dict) or not value.get('bench_root'):
            raise ValueError('Control manifest must record bench_root for path relocation')
        origin_bench = str(value['bench_root']).rstrip('/')
        if not Path(origin_bench).is_absolute() or origin_bench == '':
            raise ValueError('Manifest bench_root must be an absolute original root')
    if isinstance(value, str):
        if value == origin_bench:
            return str(BENCH)
        if value.startswith(origin_bench + '/'):
            return str(BENCH) + value[len(origin_bench):]
    if isinstance(value, dict):
        return {k: local(v, origin_bench) for k, v in value.items()}
    if isinstance(value, list):
        return [local(v, origin_bench) for v in value]
    return value


RUN_MARKERS = {'kimi': ('kimi',), 'astra': ('astra',), 'opus': ('opus', 'claude')}


def discovered_manifest(model: str) -> dict:
    """Refine candidates of a model that has no control manifest (downloaded later): for every game of the GLM
    manifest, the newest '<...model...>_refine_<game>...' run folder next to it, with the same relative project path."""
    base = local(json.loads((CONTROL / 'glm' / 'manifest.json').read_text()))
    games = []
    for g in base['games']:
        rel = os.path.relpath(g['candidate_project_root'], g['run_root'])
        entry_rel = os.path.relpath(g['launch_entry'], g['run_root'])
        runs = sorted((d for d in (GAMES_ROOT / g['game_id']).glob('*_refine_*') if d.is_dir()
                       and any(k in d.name.lower() for k in RUN_MARKERS[model])
                       and (d / rel).is_dir()), key=lambda d: d.stat().st_mtime)
        if not runs:
            print(f'MISSING {model} {g["game_id"]}: no downloaded refine run with {rel}', flush=True)
            continue
        run = runs[-1]
        games.append({**g, 'run_root': str(run), 'run_id': run.name, 'agent_model': model,
                      'candidate_project_root': str(run / rel), 'launch_entry': str(run / entry_rel)})
    return {'model': model, 'games': games}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--model', choices=MODEL_DIRS, required=True, help='whose refine candidates')
    ap.add_argument('--games', default='all', help="'all' or e.g. G015,G045,G058,G060")
    ap.add_argument('--planner', default=PLANNER_MODEL)
    ap.add_argument('--judge', default=JUDGE_MODEL)
    ap.add_argument('--run-id', help='default: <model>_refine_eval_<planner>_<judge>')
    ap.add_argument('--lean', action='store_true', help='lean mechanic / gamefeel rubric (approved set)')
    ap.add_argument('--metrics', help='only mechanic,gamefeel (no other dimensions)')
    ap.add_argument('--reuse-root', type=Path, help='reuse matching historical plans; also used by --missing-only')
    ap.add_argument('--replay-plans', action='store_true', help='record historical plans only; requires --metrics and --reuse-root')
    ap.add_argument('--missing-only', action='store_true', help='skip complete applicable columns across historical/Sol roots')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    if a.reuse_root:
        a.reuse_root = a.reuse_root.resolve()
    run_id = a.run_id or f'{a.model}_refine_eval_{a.planner}_{a.judge}'.replace('.', 'p')
    manifest = (local(json.loads((CONTROL / a.model / 'manifest.json').read_text()))
                if (CONTROL / a.model / 'manifest.json').is_file() else discovered_manifest(a.model))
    want = None if a.games == 'all' else {g.strip().upper()[:4] for g in a.games.split(',')}
    runs = []
    dims = tuple(a.metrics.split(',')) if a.metrics else ()
    if a.missing_only and not (dims and a.reuse_root):
        ap.error('--missing-only requires --metrics and --reuse-root')
    if dims:
        from _common import common
        from pipeline.eval.stage3.selected import eligible_prior
    if a.replay_plans and not (dims and a.reuse_root):
        ap.error('--replay-plans requires --metrics and --reuse-root')
    skipped = []
    for g in manifest['games']:
        if want and g['game_id'][:4] not in want:
            continue
        if a.missing_only:
            roots = [a.reuse_root, BENCH / 'test_data/outputs/eval/refine' / f'stage3_v3__judge-{a.judge}']
            prior = [q for root in roots for q in (root / MODEL_DIRS[a.model] / g['game_id']).glob('*')
                     if eligible_prior(q, dims)]
            if prior:
                skipped.append({'game': g['game_id'], 'evidence': [str(q) for q in prior]})
                print(f'SKIP covered {g["game_id"]}: {prior[0]}', flush=True)
                continue
        shim = SHIMS / MODEL_DIRS[a.model] / g['game_id'] / run_id
        if not (shim / 'delivery.json').is_file():
            entry = os.path.relpath(g['launch_entry'], g['candidate_project_root'])
            subprocess.run([sys.executable, str(HERE / 'legacy_delivery.py'), '--stage', '3', '--model', a.model,
                            '--game', g['game_id'], '--project', g['candidate_project_root'], '--entry', entry,
                            '--run-id', run_id, '--source', g['original_project_root']], check=True,
                           capture_output=True)
        runs.append(str(shim))
    print(f'{len(runs)} deliveries, run id {run_id}')
    env = dict(os.environ, A3GAME_EVENT_FRAMES='1', GAMEFACTORY_UNITY_IMGUI_FORWARD='1', A3GAME_UE_BACKGROUND_FOCUS='1',
               A3GAME_PROJECT_BUDGET_S=os.environ.get('A3GAME_PROJECT_BUDGET_S', '3600'),
               A3GAME_GUI_SLOTS=os.environ.get('A3GAME_GUI_SLOTS', '2'), A3GAME_GUI_WAIT_S='7200')
    if dims:
        env['A3GAME_LOSSLESS_IMAGES'] = '1'
        env['A3GAME_ORIGINAL_IMAGE_TRANSPORT'] = '1'
    if a.lean:
        env['A3GAME_STANDARD_SET'] = 'lean'
    else:
        env.pop('A3GAME_STANDARD_SET', None)
    cmd = [sys.executable, '-u', str(HERE / 'evaluate.py'), '--stage', '3', '--planner', a.planner,
           '--judge', a.judge, '--run-dir', *runs]
    if a.metrics:
        cmd += ['--metrics', a.metrics]
    if a.reuse_root:
        cmd += ['--reuse-root', str(a.reuse_root)]
    if a.replay_plans:
        cmd += ['--replay-plans']
    if not runs:
        print('All requested applicable columns already covered.')
        return 0
    if a.dry_run:
        print(' '.join(cmd))
        return 0
    return subprocess.run(cmd, cwd=BENCH, env=env).returncode


if __name__ == '__main__':
    raise SystemExit(main())
