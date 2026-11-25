#!/usr/bin/env python3
"""Make an existing (pre-contract) delivery evaluable without touching it.

Writes ``<shim root>/<model dir>/<GameID>/<run_id>/delivery.json`` whose
``project_root`` points (absolute) at the original project, which stays
read-only; evaluate.py copies it into its own eval directory.

    python scripts_new/legacy_delivery.py --stage 3 --model glm --game G003_gggame_courtyard_rps \\
        --project <.../p> --entry GG.uproject --run-id glm_G003_experiment
then
    python scripts_new/evaluate.py --stage 3 --run-dir <printed shim dir> --source-only
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from _common import common
from pipeline.eval.whitebox.delivery import validate
from pipeline.eval.whitebox.paths import DELIVERY_SCHEMA, write_json

SHIM_ROOT = common.OUTPUTS / 'legacy_deliveries'


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--stage', choices=('1', '3'), required=True)
    p.add_argument('--model', required=True)
    p.add_argument('--game', required=True)
    p.add_argument('--project', type=Path, required=True, help='existing project directory (read-only)')
    p.add_argument('--entry', required=True, help='entry relative to --project')
    p.add_argument('--engine', help='default: from the case requirement')
    p.add_argument('--run-id', required=True)
    p.add_argument('--source', help='stage 3: original project the candidate was refined from')
    p.add_argument('--rounds', type=int, default=0, help='stage 3: rounds used, if known')
    args = p.parse_args(argv)

    from pipeline.eval.whitebox.delivery import case_engine
    project = args.project.resolve()
    run = SHIM_ROOT / f'stage{args.stage}' / common.model_dir(args.model) / args.game / args.run_id
    data = {'schema': DELIVERY_SCHEMA, 'stage': f'stage{args.stage}', 'model': args.model, 'game_id': args.game,
            'run_id': args.run_id, 'engine': args.engine or (case_engine(args.game) or '').replace('-', '_'),
            'project_root': str(project), 'entry': args.entry,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'generator': {'kind': 'legacy_shim', 'agent': args.model, 'framework_used': True,
                          'original_location': str(project)}}
    if args.stage == '3':
        data.update(source={'path': args.source or '', 'sha256_manifest': ''}, rounds_used=args.rounds)
    write_json(run / 'delivery.json', data)
    problems = validate(run)
    print(run)
    for problem in problems:
        print('  -', problem)
    return 1 if problems else 0


if __name__ == '__main__':
    raise SystemExit(main())
