#!/usr/bin/env python3
"""One extra targeted take for named checks of a finished stage3 eval run (new recording, nothing old re-recorded).

    python scripts_new/extra_take.py --run <eval dir> --checks vfx.0032,motion.G015_mot_005,vfx.0038 \\
        --label take6_wall_revival_20261111 [--no-state-entry] [--dry-run]

* The next take number k is planned by the run's planner for ONLY the named checks, with the judge's reasons for
  them as feedback (same make_plan / coverage rules as the batched loop), recorded with the run's recorder
  settings (event frames on), evidence_t<k>.json is built for takes 1..k, and the judge is asked about the named
  checks only (tag _t<k>). score() then merges take k as a normal later take.
* Earlier takes, their evidence manifests and verdicts are not touched: SHA-256 before / after in the receipt.
  score.json / coverage.json / takes.json before the take are copied to judge_versions/before_<label>/.
* A named check the planner declares unreachable (and that was not executed) may get one state-entry take
  (k+1, separate state-conditioned track in state_conditioned.json) unless --no-state-entry.
* Audio evaluation is not changed here.
* The plan sees the game's own log from earlier takes and declares trigger signals; the receipt records which of
  them the game printed in this take.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

BENCH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH / 'GameFactory-3A'))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pipeline.eval.stage1 import budgets, evidence, judge, pipeline, plan, prepare, record, standards  # noqa: E402
from pipeline.eval.stage1.paths import read_json, write_json  # noqa: E402
from rejudge_takes import credits, input_hashes, sha, JUDGE_CODE, git_rev  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--run', type=Path, required=True)
    ap.add_argument('--checks', required=True, help='comma-separated check ids or unique substrings')
    ap.add_argument('--label', required=True)
    ap.add_argument('--no-state-entry', action='store_true')
    ap.add_argument('--state-entry', action='store_true',
                    help='run the named checks as one state-entry take (separate state-conditioned track) instead')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    out = a.run.resolve()
    if read_json(out / 'status.json').get('state') == 'running':
        print('refusing: run is still running'); return 2
    manifest = read_json(out / 'manifest.json')
    suite = manifest.get('suite', 'stage3')
    crit = read_json(out / 'input' / 'criteria.json')
    rows = crit['criteria']
    runtime = [r['id'] for r in plan.targets(rows)]
    ids = []
    for want in (x.strip() for x in a.checks.split(',') if x.strip()):
        hit = [i for i in runtime if i == want or want in i]
        if len(hit) != 1:
            print(f'refusing: "{want}" matches {len(hit)} runtime checks: {hit[:5]}'); return 2
        ids.append(hit[0])
    takes = sorted(int(p.name) for p in (out / 'takes').iterdir() if p.name.isdigit())
    k = max(takes) + 1
    new_dir, before_dir = out / 'judge_versions' / a.label, out / 'judge_versions' / f'before_{a.label}'
    if new_dir.exists():
        print(f'refusing: {new_dir} exists'); return 2
    frozen = standards.load(suite, crit['version'], manifest['game_id'], rows)
    metrics = __import__('pipeline.eval.stage1.suites', fromlist=['get']).get(suite).metrics
    verdicts = pipeline.final_verdicts(out, upto=pipeline.BATCH_MAX_TAKES)
    feedback = pipeline._feedback(out, k, ids, verdicts)
    print(f'{out.parent.name}/{out.name}: take {k} for {len(ids)} checks: {ids}')
    if a.dry_run:
        print(json.dumps(feedback, ensure_ascii=False)[:1500]); return 0

    os.environ.update(GAMEFACTORY_UNITY_IMGUI_FORWARD='1', A3GAME_UE_BACKGROUND_FOCUS='1', A3GAME_UE_KEYBOARD_ONLY='1',
                      A3GAME_EVENT_FRAMES='1')
    before = input_hashes(out, takes)
    before['verdict_files'] = {p.name: sha(p) for p in sorted(out.glob('verdicts_*.json'))}
    old_credit = credits(out, rows, metrics)
    old_score = read_json(out / 'score.json') if (out / 'score.json').is_file() else {}
    before_dir.mkdir(parents=True, exist_ok=True)
    for name in ('score.json', 'coverage.json', 'takes.json'):
        if (out / name).is_file():
            shutil.copy2(out / name, before_dir / name)
    new_dir.mkdir(parents=True)
    receipt = {'version': 'stage3-extra-take.v1', 'run': str(out), 'label': a.label, 'take': k, 'checks': ids,
               'started': time.strftime('%Y-%m-%dT%H:%M:%S'), 'planner': manifest['models']['planner'],
               'judge': manifest['models']['judge'], 'git_head': git_rev(),
               'code_sha256': {f: sha(BENCH / 'GameFactory-3A' / f) for f in JUDGE_CODE + (
                   'pipeline/eval/stage1/plan.py', 'pipeline/eval/stage1/record.py',
                   'engine_adapters/unity3d/import_generated/GameFactory3APlayTestRecorder.cs')},
               'recorder_env': {'A3GAME_EVENT_FRAMES': '1'}, 'feedback': feedback,
               'earlier_inputs_before': before, 'audio_chain': 'unchanged'}
    write_json(new_dir / 'receipt.json', receipt)
    take_manifest = {**manifest, 'budget': budgets.for_take(manifest['budget'], 1)}
    if a.state_entry:                       # state-conditioned track only; normal score.json is not changed
        if (out / 'state_conditioned.json').is_file():           # copy only: the book keeps every state take
            shutil.copy2(out / 'state_conditioned.json', before_dir / 'state_conditioned.json')
        pipeline._state_take(out, manifest, rows, metrics, frozen, ids, k)
        state = read_json(out / 'state_conditioned.json')
        after = input_hashes(out, takes)
        after['verdict_files'] = {n: sha(out / n) for n in before['verdict_files']}
        changed = sorted(x for x in before if before[x] != after.get(x))
        pipeline._status(out, 'score', 'done')
        receipt.update(mode='state_entry', finished=time.strftime('%Y-%m-%dT%H:%M:%S'), state_conditioned=state,
                       earlier_inputs_unchanged=not changed, earlier_inputs_changed=changed,
                       score_json_changed=sha(out / 'score.json') != sha(before_dir / 'score.json'))
        write_json(new_dir / 'receipt.json', receipt)
        print(json.dumps({x: receipt[x] for x in ('earlier_inputs_unchanged', 'score_json_changed', 'state_conditioned')},
                         ensure_ascii=False, indent=1)[:4000])
        return 0 if state.get('done') and not state.get('error') and not changed else 1
    error = None
    try:
        pipeline._status(out, f'extra_plan_t{k}', 'running')
        p = plan.make_plan(out, take_manifest, k, ids, feedback)
        pipeline._status(out, f'extra_record_t{k}', 'running')
        prepare.verify(out)
        record.record(out, take_manifest, p, k)
        receipt['trigger_signals'] = pipeline.check_trigger_signals(out, k)
        pipeline._status(out, f'extra_judge_t{k}', 'running')
        ev = evidence.build(out, list(range(1, k + 1)))
        judge.judge(out, manifest, ev, 'evidence', frozen, only_ids=ids, tag=f'_t{k}')
    except Exception as exc:                                     # recorded; earlier results stay as they were
        error = f'{type(exc).__name__}: {str(exc)[:800]}'
        print('take failed:', error)
    cov = read_json(plan.take_dir(out, k) / 'plan_coverage.json') if (plan.take_dir(out, k) / 'plan_coverage.json').is_file() else {}
    acts = plan.take_dir(out, k) / 'record' / 'actions.jsonl'
    executed = set()
    for line in (acts.read_text(errors='replace').splitlines() if acts.is_file() else []):
        try:
            executed.update(json.loads(line).get('criterion_ids') or [])
        except ValueError:
            pass
    state = None
    deep = [i for i in ids if i in (cov.get('declared_unreachable') or {}) and i not in executed]
    if not error and deep and not a.no_state_entry and manifest['engine'] in pipeline.state_entry.ENV:
        print(f'state-entry take {k + 1} for {deep}')
        pipeline._state_take(out, manifest, rows, metrics, frozen, deep, k + 1)
        state = read_json(out / 'state_conditioned.json')
    after = input_hashes(out, takes)
    after['verdict_files'] = {n: sha(out / n) for n in before['verdict_files']}
    changed = sorted(x for x in before if before[x] != after.get(x))
    if not error:
        pipeline.score(out)
        pipeline._status(out, 'score', 'done')
    else:
        pipeline._status(out, 'score', 'done')                   # earlier score.json unchanged
    new_score = read_json(out / 'score.json')
    new_credit = credits(out, rows, metrics)
    dims = ('mechanic', 'gamefeel', 'vfx', 'import', 'texture')
    receipt.update(finished=time.strftime('%Y-%m-%dT%H:%M:%S'), error=error, earlier_inputs_unchanged=not changed,
                   earlier_inputs_changed=changed, plan_coverage=cov, executed=sorted(executed & set(ids)),
                   credit={i: {'before': old_credit.get(i), 'after': new_credit.get(i)} for i in ids},
                   score_before={d: old_score.get('dimensions', {}).get(d, {}).get('S') for d in dims},
                   score_after={d: new_score.get('dimensions', {}).get(d, {}).get('S') for d in dims},
                   state_conditioned=state)
    write_json(new_dir / 'receipt.json', receipt)
    print(json.dumps({x: receipt[x] for x in ('error', 'earlier_inputs_unchanged', 'earlier_inputs_changed',
                                              'executed', 'credit', 'score_before', 'score_after')},
                     ensure_ascii=False, indent=1))
    return 1 if error or changed else 0


if __name__ == '__main__':
    raise SystemExit(main())
