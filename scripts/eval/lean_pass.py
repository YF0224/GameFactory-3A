#!/usr/bin/env python3
"""Re-judge mechanic / gamefeel of finished stage3 evaluations under the approved LEAN rubric.

Same checks, same recordings and evidence (union of all takes); only the per-check rubric is the
lean one (test_data/bench_standards/stage3/<criteria version>+lean/). Writes
``verdicts_evidence_lean.json`` (overrides the take verdicts for those checks) and re-scores.
Earlier verdicts stay on disk. Then runs the texture pass (imported vs original-asset render).

    python scripts/eval/lean_pass.py [--judge claude-opus-5-5] [--suffix _refine_eval_20261110] [--root <eval root>]
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ['A3GAME_STANDARD_SET'] = 'lean'          # before importing standards

from _common import common  # noqa: E402

from pipeline.eval.whitebox.core import evidence, judge, pipeline, standards  # noqa: E402
from pipeline.eval.whitebox.core.paths import read_json  # noqa: E402

ROOT = common.OUTPUTS / 'eval' / 'refine' / 'stage3_v3__judge-claude-opus-5-5'
DIMS = ('mechanic', 'gamefeel')


def _credit(metrics, row, verdict):
    try:
        return metrics[row['metric']].credit(row, verdict)
    except ValueError:
        return -1.0


def run_one(out: Path, judge_model: str, dims=DIMS) -> dict:
    """Mirror the original passes: take N re-judges (lean rubric) exactly the checks that take judged,
    on the same cumulative evidence; each check keeps its best take (proven in any take counts)."""
    from pipeline.eval.whitebox.core import suites
    st = read_json(out / 'status.json') if (out / 'status.json').is_file() else {}
    if not (st.get('step') == 'score' and st.get('state') == 'done'):
        return {'skip': f'not finished ({st.get("step")} {st.get("state")})'}
    if (out / 'lean_pass.json').is_file():
        return {'skip': 'already done'}
    manifest = read_json(out / 'manifest.json')
    manifest = {**manifest, 'models': {**manifest['models'], 'judge': judge_model}}
    crit = read_json(out / 'input' / 'criteria.json')
    rows = {r['id']: r for r in crit['criteria'] if r['metric'] in dims and r['mode'] != 'static'}
    frozen = standards.load('stage3', crit['version'], manifest['game_id'], crit['criteria'])
    metrics = suites.get('stage3').metrics
    best, passes = {}, []
    for f in sorted(out.glob('verdicts_evidence_t[0-9]*.json')):
        take = int(f.stem.split('_t')[-1])
        ids = [i for i in read_json(f) if i in rows]
        if not ids or take == 0:
            continue
        ev = evidence.build(out, list(range(1, take + 1)))
        got = judge.judge(out, manifest, ev, 'evidence', frozen, only_ids=ids, tag=f'_lean_t{take}')
        passes.append({'take': take, 'checks': len(ids)})
        for i, v in got.items():
            if i not in best or _credit(metrics, rows[i], v) >= _credit(metrics, rows[i], best[i]):
                best[i] = v
    old = out / 'verdicts_evidence_lean.json'
    if old.is_file():                      # single-call version superseded (kept for the record)
        old.rename(out / 'verdicts_evidence_lean_singlecall.json')
    from pipeline.eval.whitebox.core.paths import write_json
    write_json(old, best)
    write_json(out / 'lean_pass.json', {'judge': judge_model, 'passes': passes, 'rule': 'per take, best take per check'})
    result = pipeline.score(out)
    return {k: result['dimensions'][k]['S'] for k in dims if k in result['dimensions']}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--judge', default='claude-opus-5-5')
    ap.add_argument('--suffix', default='_refine_eval_20261110')
    ap.add_argument('--root', type=Path, default=ROOT)
    ap.add_argument('--only', help='<model dir>/<GameID prefix>, e.g. glm_5p3/G015')
    ap.add_argument('--with-import', action='store_true', help='also re-judge import (e.g. after new asset renders)')
    a = ap.parse_args()
    dims = DIMS + (('import',) if a.with_import else ())
    for out in sorted(a.root.glob(f'*/*/*{a.suffix}')):
        if a.only and f'{out.parents[1].name}/{out.parent.name[:4]}' != a.only:
            continue
        try:
            print(out.parents[1].name, out.parent.name[:4], run_one(out, a.judge, dims), flush=True)
        except Exception as exc:        # noqa: BLE001
            print(out.parents[1].name, out.parent.name[:4], 'ERROR', type(exc).__name__, exc, file=sys.stderr, flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
