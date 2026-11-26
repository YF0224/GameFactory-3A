#!/usr/bin/env python3
"""Prepare Snake deliveries and invoke scripts/eval/evaluate.py --stage 1.

No Snake suite, monkeypatch, alternative planner, judge or scoring logic.
Example standards follow the existing review/approval flow.

Usage:
    python3 examples/cross_engine_snake/evaluate_stage1.py --prepare-only
    python3 examples/cross_engine_snake/evaluate_stage1.py --engines godot threejs
    python3 examples/cross_engine_snake/evaluate_stage1.py --static-only
    python3 examples/cross_engine_snake/evaluate_stage1.py
"""
from __future__ import annotations

import argparse
import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))

from pipeline.eval.model_config import EVALUATION_PLANNER_MODEL, JUDGE_MODEL

ENGINES = {
    'threejs': ('three_js', 'index.html'),
    'unity':   ('unity3d',  'Assets/Snake.unity'),
    'ue':      ('ue5',      'SnakeDemo.uproject'),
    'godot':   ('godot',    'project.godot'),
}


def source_hashes(root: Path, ignore) -> dict:
    hashes = {}
    for parent, dirs, files in os.walk(root):
        excluded = ignore(parent, dirs + files)
        dirs[:] = [name for name in dirs if name not in excluded]
        for name in files:
            path = Path(parent) / name
            if name not in excluded and not path.is_symlink():
                hashes[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--engines', nargs='+', choices=ENGINES, default=list(ENGINES))
    parser.add_argument('--out', type=Path, default=HERE / 'out-stage1-standard',
                        help='delivery + eval output root')
    parser.add_argument('--run-id', help='override immutable example revision (Unity v2, others v1)')
    parser.add_argument('--planner', default=EVALUATION_PLANNER_MODEL)
    parser.add_argument('--judge', default=JUDGE_MODEL)
    parser.add_argument('--prepare-only', action='store_true',
                        help='prepare ordinary inputs only; no model calls')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--static-only', action='store_true')
    mode.add_argument('--plan-only', action='store_true')
    mode.add_argument('--list', action='store_true')
    args = parser.parse_args()

    from pipeline.eval.whitebox.core import delivery as contract, prepare, suites, standards
    from pipeline.eval.whitebox.core.paths import write_json
    from stage1_case.case_data import install

    if args.run_id is not None and (
        not args.run_id or Path(args.run_id).name != args.run_id or args.run_id in ('.', '..')
    ):
        parser.error('--run-id must be a single directory name')

    root = args.out.resolve()
    deliveries, pending = [], []

    for source in dict.fromkeys(args.engines):
        engine, entry = ENGINES[source]
        game_id, folder = install(engine)
        run_id = args.run_id or ('authored_v2' if source == 'unity' else 'authored_v1')
        run = root / 'deliveries' / 'sol' / game_id / run_id

        if not (run / 'delivery.json').exists():
            if not (HERE / source / entry).is_file():
                raise RuntimeError(f'Missing authored entry: {source}/{entry}')
            shutil.copytree(HERE / source, run / 'project', ignore=prepare.IGNORE)
            write_json(run / 'delivery.json', {
                'schema': 'bench.delivery.v1',
                'stage': 'stage1',
                'model': 'sol',
                'game_id': game_id,
                'run_id': run.name,
                'engine': engine,
                'project_root': 'project',
                'entry': entry,
                'created_at': datetime.now(timezone.utc).isoformat(),
                'generator': {
                    'kind': 'external_agent',
                    'agent': 'Codex local example author',
                    'framework_used': True,
                },
                'provenance_note': (
                    'Synthetic example. sol is the contract routing slot, '
                    'not attribution to a benchmark model.'
                ),
                'demo_only': True,
            })

        problems = contract.validate(run)
        if problems:
            raise ValueError(f'{run}: {problems}')

        if source_hashes(HERE / source, prepare.IGNORE) != source_hashes(run / 'project', prepare.IGNORE):
            raise ValueError(
                f'Example source changed; preserve this delivery and choose a new '
                f'--run-id or --out: {run}'
            )

        built = suites.get('whitebox').build(game_id)
        try:
            standards.load('whitebox', built['version'], game_id, built['criteria'])
        except ValueError as exc:
            pending.append({
                'game_id': game_id,
                'review': str(folder / 'review.md'),
                'reason': str(exc),
            })
        deliveries.append(run)

    write_json(root / 'inputs.json', {
        'suite': 'whitebox',
        'demo_only': True,
        'deliveries': [str(r) for r in deliveries],
        'pending_reviews': pending,
        'evaluation_entry': 'scripts/eval/evaluate.py',
    })

    command = [
        sys.executable,
        str(REPO / 'scripts' / 'eval' / 'evaluate.py'),
        '--stage', '1',
        '--run-dir', *map(str, deliveries),
    ]
    for key in ('planner', 'judge'):
        if getattr(args, key):
            command += [f'--{key}', getattr(args, key)]
    for key in ('static_only', 'plan_only', 'list'):
        if getattr(args, key):
            command.append('--' + key.replace('_', '-'))

    write_json(root / 'evaluate_command.json', command)
    print('Entry: scripts/eval/evaluate.py --stage 1', flush=True)
    for run in deliveries:
        print(f'Delivery: {run}', flush=True)

    if args.prepare_only:
        print(
            f'Prepared {len(deliveries)} Stage1 deliveries; '
            f'{len(pending)} standards await human review.'
        )
        return 0

    if pending and not (args.static_only or args.list):
        for item in pending:
            print(f'Review required: {item["review"]}', file=sys.stderr)
        print(
            'Stage1 standards approval required; no runtime evaluation started.',
            file=sys.stderr,
        )
        return 2

    return subprocess.run(command, cwd=REPO).returncode


if __name__ == '__main__':
    raise SystemExit(main())
