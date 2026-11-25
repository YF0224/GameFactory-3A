#!/usr/bin/env python3
"""Collect stage3 refine scores into one table (Markdown).

    python scripts_new/stage3_scores.py                         # default: the 2026-11-10 Sol/GLM run
    python scripts_new/stage3_scores.py --root <eval root> --run-suffix _refine_eval_20261110

Writes <root>/scores_<suffix>.md and prints it. Provisional scores (more takes may follow)
are marked; games not yet scored show their current step.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from _common import common

DIMS = ('mechanic', 'gamefeel', 'vfx', 'import', 'texture')
ROOT = common.OUTPUTS / 'eval' / 'refine' / 'stage3_v3__judge-claude-opus-5-5'
NAMES = {'gpt_sol6p1': 'Sol', 'glm_5p3': 'GLM'}


def cell(d):
    if not d:
        return '—'
    if d.get('S') is None:
        return f'… (cov {d["Cov"]:.0%})'
    return f'{d["S"]:.1f} ({d["Cov"]:.0%})'


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', type=Path, default=ROOT)
    ap.add_argument('--run-suffix', default='_refine_eval_20261110')
    a = ap.parse_args()
    lines = [f'# Stage3 refine scores — {a.root.name} / *{a.run_suffix}', '',
             'S per dimension (coverage in brackets), 10/50/100 per check, no total. '
             'Playable = import/launch/operate by rules. Status 未审计.', '',
             '| Model | Game | ' + ' | '.join(DIMS) + ' | Playable | Takes | State |',
             '|' + '---|' * (len(DIMS) + 5)]
    for run in sorted(a.root.glob(f'*/*/*{a.run_suffix}')):
        model, game = NAMES.get(run.parents[1].name, run.parents[1].name), run.parent.name[:4]
        sc = json.loads((run / 'score.json').read_text()) if (run / 'score.json').is_file() else {}
        st = json.loads((run / 'status.json').read_text()) if (run / 'status.json').is_file() else {}
        tk = json.loads((run / 'takes.json').read_text()) if (run / 'takes.json').is_file() else {}
        dims = sc.get('dimensions', {})
        pl = (sc.get('playable') or {}).get('score')
        stale = (run / 'score.json').is_file() and (run / 'status.json').is_file() and \
            (run / 'score.json').stat().st_mtime > (run / 'status.json').stat().st_mtime
        if sc and st.get('step') == 'score' and not sc.get('provisional'):
            state = 'final'
        elif stale or (not st and (run / 'takes').is_dir()):
            state = f'running (after take {len(tk.get("history", []))})'
        elif st.get('state') == 'HARNESS_ERROR':
            state = f'tool error at {st.get("step")} (being fixed / resumed)'
        else:
            state = f'{st.get("step", "prepared")} {st.get("state", "")}'.strip()
        lines.append(f'| {model} | {game} | ' + ' | '.join(cell(dims.get(k)) for k in DIMS)
                     + f' | {"—" if pl is None else pl} | {len(tk.get("history", []))} | {state} |')
    text = '\n'.join(lines) + '\n'
    out = a.root / f'scores{a.run_suffix}.md'
    out.write_text(text, encoding='utf-8')
    print(text + f'\nwritten: {out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
