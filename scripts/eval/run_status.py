#!/usr/bin/env python3
"""One-screen progress of a stage3 run:  python3 scripts_new/run_status.py [--run-suffix _refine_eval_20261111g]"""
import argparse, glob, json, os, time
ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    'test_data/outputs/eval/refine/stage3_v3__judge-gpt-6.1-sol')
DIRS = {'glm': 'glm_5p3', 'sol': 'gpt_sol6p1', 'kimi': 'kimi_k3', 'astra': 'gpt_astra6', 'opus': 'claude_ops5p5'}
ap = argparse.ArgumentParser(); ap.add_argument('--run-suffix', default='_refine_eval_20261112c')
ap.add_argument('--model', default='glm', choices=sorted(DIRS)); a = ap.parse_args()
R = f'{ROOT}/{DIRS[a.model]}'
print(time.strftime('%H:%M:%S'), a.model, 'run', a.run_suffix)
print(f"{'game':6} {'step':22} {'state':13} {'takes':>5} {'attempted':>9} {'>=50':>5} {'Mech':>5} {'GF':>5} {'VFX':>5} {'Imp':>5} {'Tex':>5}")
for d in sorted(glob.glob(f'{R}/*/{a.model}{a.run_suffix}')):
    g = d.split('/')[-2][:4]
    try:
        s = json.load(open(d + '/status.json'))
    except (OSError, ValueError):
        print(f'{g:6} not started'); continue
    cov = json.load(open(d + '/coverage.json')) if os.path.exists(d + '/coverage.json') else {}
    sc = json.load(open(d + '/score.json')).get('dimensions', {}) if os.path.exists(d + '/score.json') else {}
    S = lambda k: '-' if sc.get(k, {}).get('S') is None else f"{sc[k]['S']:.0f}"
    takes = len(glob.glob(d + '/takes/[0-9]*/record/record_result.json'))
    att = f"{cov.get('attempt_coverage', 0)*100:.0f}%" if cov else '-'
    ev = f"{cov.get('evidence_coverage', 0)*100:.0f}%" if cov else '-'
    print(f"{g:6} {s.get('step','')[:22]:22} {s.get('state',''):13} {takes:>5} {att:>9} {ev:>5} {S('mechanic'):>5} {S('gamefeel'):>5} {S('vfx'):>5} {S('import'):>5} {S('texture'):>5}"
          + (f"  ERROR: {s.get('error','')[:70]}" if s.get('state') == 'HARNESS_ERROR' else ''))
