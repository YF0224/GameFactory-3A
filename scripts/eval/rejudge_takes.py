#!/usr/bin/env python3
"""Re-judge the recorded takes of one stage3 eval run with the current judge - no re-recording, no re-planning.

    python scripts_new/rejudge_takes.py --run <eval dir> [--takes 1,2,3,4] --label rejudge_20261111 [--dry-run]

What changes: only the judge (code version, and how its input is organised per call: image cap, per-call
action / image index, CLI image arguments). What stays bound and is verified unchanged (SHA-256 before / after):
  * each take's plan, plan_coverage, record/actions.jsonl, frame_index.jsonl, event_frame_index.jsonl,
    event_trace.jsonl, state_trace.jsonl, engine.log;
  * every native frame file referenced by the evidence manifests (raw_sha256 / path);
  * the cached evidence manifests evidence_t<k>.json themselves - they are LOADED, never rebuilt, so the new
    judge sees exactly the same action links, frame ids, event index and sheets as the original judge;
  * input/criteria.json and the approved frozen standard (standards.load refuses edits).
Per take k the new judge is asked about the same checks as before (plan_coverage.json 'targets' of take k)
with evidence_t<k>.json (= union of takes 1..k, as in the original run).

Old results are moved (never deleted) to judge_versions/<old label>/ : verdicts_evidence_t<k>.json, the
model_calls/evidence_t<k>_* folders, score.json, coverage.json, takes.json. New verdicts are written under the
original names so the normal score() reads them; judge_versions/<label>/receipt.json records both versions,
all input hashes, the judge code hashes and the new / old scores.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

BENCH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH / 'GameFactory-3A'))

from pipeline.eval.stage1 import evidence, judge, llm, pipeline, standards  # noqa: E402
from pipeline.eval.stage1.paths import read_json, write_json  # noqa: E402

TAKE_FILES = ('plan.json', 'plan_coverage.json', 'record/actions.jsonl', 'record/frame_index.jsonl',
              'record/event_frame_index.jsonl', 'record/event_trace.jsonl', 'record/state_trace.jsonl',
              'record/engine.log')
JUDGE_CODE = ('pipeline/eval/stage1/judge.py', 'pipeline/eval/stage1/llm.py', 'pipeline/eval/stage1/evidence.py',
              'pipeline/eval/stage3/metrics.py', 'pipeline/eval/stage1/metrics/_formats.py')


def sha(p: Path) -> str | None:
    if not p.is_file():
        return None
    h = hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def input_hashes(out: Path, takes: list[int]) -> dict:
    """Everything the new judge must see unchanged."""
    result = {'input/criteria.json': sha(out / 'input' / 'criteria.json'), 'manifest.json': sha(out / 'manifest.json')}
    frames = {}
    for k in takes:
        for name in TAKE_FILES:
            result[f'takes/{k}/{name}'] = sha(out / 'takes' / str(k) / name)
        result[f'evidence_t{k}.json'] = sha(out / f'evidence_t{k}.json')
        if not (out / f'evidence_t{k}.json').is_file():          # e.g. a state-entry take that was not judged
            continue
        for it in read_json(out / f'evidence_t{k}.json')['items']:
            if it['type'] == 'frame':
                raw = Path(it.get('raw') or it.get('path', ''))
                if raw.is_file() and str(raw) not in frames:
                    frames[str(raw)] = sha(raw)
    result['frames'] = {'count': len(frames),
                        'sha256_of_list': hashlib.sha256(json.dumps(sorted(frames.items())).encode()).hexdigest()}
    return result


def git_rev() -> str | None:
    try:
        return subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=BENCH, capture_output=True, text=True).stdout.strip()
    except OSError:
        return None


def credits(out: Path, rows: list, metrics: dict) -> dict:
    v = pipeline.final_verdicts(out, upto=pipeline.BATCH_MAX_TAKES)
    res = {}
    for r in rows:
        if r['id'] in v and r['mode'] != 'static':
            try:
                res[r['id']] = metrics[r['metric']].credit(r, v[r['id']])
            except ValueError:
                res[r['id']] = None
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--run', type=Path, required=True, help='eval dir (contains manifest.json, takes/, evidence_t*.json)')
    ap.add_argument('--takes', default='all', help="'all' (every take with verdicts) or e.g. 1,2,3,4")
    ap.add_argument('--label', required=True, help='name of the new judge version, e.g. rejudge_20261111')
    ap.add_argument('--old-label', default='original', help='name for the archived judge version')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    out = a.run.resolve()
    status = read_json(out / 'status.json')
    if status.get('state') == 'running':
        print(f'refusing: {out} is still running ({status.get("step")})'); return 2
    found = sorted(int(p.stem.rsplit('_t', 1)[1]) for p in out.glob('verdicts_evidence_t[1-9]*.json'))
    takes = found if a.takes == 'all' else [int(x) for x in a.takes.split(',')]
    missing = [k for k in takes if not (out / f'evidence_t{k}.json').is_file() or
               not (out / 'takes' / str(k) / 'plan_coverage.json').is_file()]
    if missing:
        print(f'refusing: takes {missing} have no cached evidence manifest / plan_coverage'); return 2
    new_dir, old_dir = out / 'judge_versions' / a.label, out / 'judge_versions' / a.old_label
    if new_dir.exists():
        print(f'refusing: {new_dir} exists (choose another --label)'); return 2

    manifest = read_json(out / 'manifest.json')
    suite = manifest.get('suite', 'stage3')
    crit = read_json(out / 'input' / 'criteria.json')
    rows = crit['criteria']
    frozen = standards.load(suite, crit['version'], manifest['game_id'], rows)      # refuses edited standards
    metrics = __import__('pipeline.eval.stage1.suites', fromlist=['get']).get(suite).metrics
    targets = {k: read_json(out / 'takes' / str(k) / 'plan_coverage.json')['targets'] for k in takes}
    before = input_hashes(out, takes)
    code = {f: sha(BENCH / 'GameFactory-3A' / f) for f in JUDGE_CODE}
    print(f'{out.name}: re-judge takes {takes} ({sum(len(v) for v in targets.values())} check-takes), '
          f'{before["frames"]["count"]} native frames bound; judge model {manifest["models"]["judge"]}')
    if a.dry_run:
        for k in takes:
            ev = read_json(out / f'evidence_t{k}.json')
            r = [x for x in rows if x['id'] in set(targets[k])]
            print(f'  t{k}: {len(targets[k])} checks -> {len(judge.size_shards(r, 8, ev, out))} calls')
        return 0

    old_scores = read_json(out / 'score.json') if (out / 'score.json').is_file() else None
    old_credit = credits(out, rows, metrics)
    # archive (move, never delete) the old judge version
    old_dir.mkdir(parents=True, exist_ok=True)
    (old_dir / 'model_calls').mkdir(exist_ok=True)
    moved = []
    for k in takes:
        for p in [out / f'verdicts_evidence_t{k}.json', *sorted((out / 'model_calls').glob(f'evidence_t{k}_*'))]:
            if p.exists():
                dest = (old_dir / 'model_calls' / p.name) if p.parent.name == 'model_calls' else old_dir / p.name
                shutil.move(str(p), str(dest)); moved.append(str(dest.relative_to(out)))
    for name in ('score.json', 'coverage.json', 'takes.json'):
        if (out / name).is_file():
            shutil.copy2(out / name, old_dir / name); moved.append(f'judge_versions/{a.old_label}/{name} (copy)')
    new_dir.mkdir(parents=True)
    receipt = {'version': 'stage3-rejudge.v1', 'run': str(out), 'label': a.label, 'old_label': a.old_label,
               'started': time.strftime('%Y-%m-%dT%H:%M:%S'), 'takes': takes, 'targets_per_take': targets,
               'judge_model': manifest['models']['judge'], 'git_head': git_rev(), 'judge_code_sha256': code,
               'judge_settings': {'MAX_IMAGES': judge.MAX_IMAGES, 'MAX_IMAGE_BYTES': judge.MAX_IMAGE_BYTES,
                                  'OWN_SHARE': judge.OWN_SHARE, 'per_call_index': True,
                                  'cli_image_args': '--image=<path> ... -- -'},
               'inputs_before': before, 'archived_old_version': moved,
               'not_changed': 'recordings, plans, evidence manifests (loaded from cache), criteria, frozen standards'}
    write_json(new_dir / 'receipt.json', receipt)
    errors = {}
    for k in takes:
        ev = read_json(out / f'evidence_t{k}.json')                          # cached manifest, not rebuilt
        assert sha(out / f'evidence_t{k}.json') == before[f'evidence_t{k}.json']
        print(f'  judging t{k}: {len(targets[k])} checks ...', flush=True)
        try:
            judge.judge(out, manifest, ev, 'evidence', frozen, only_ids=targets[k], tag=f'_t{k}')
        except Exception as exc:                                             # recorded; other takes continue
            errors[k] = f'{type(exc).__name__}: {str(exc)[:600]}'
            print(f'  t{k} FAILED: {errors[k]}', flush=True)
    after = input_hashes(out, takes)
    changed = sorted(k for k in before if before[k] != after.get(k))
    for k in takes:                                                          # keep a copy with the new version
        if (out / f'verdicts_evidence_t{k}.json').is_file():
            shutil.copy2(out / f'verdicts_evidence_t{k}.json', new_dir / f'verdicts_evidence_t{k}.json')
    new_credit = credits(out, rows, metrics)
    new_scores = None
    if not errors:
        pipeline.score(out)
        new_scores = read_json(out / 'score.json')
        shutil.copy2(out / 'score.json', new_dir / 'score.json')
    vis = 0
    for p in sorted((out / 'model_calls').glob('evidence_t*')):
        r = p / 'response.json'
        if r.is_file() and any(w in ' '.join(read_json(r).get('limitations', []))
                               for w in ('摘要', 'summary', '无法直接查看', 'not directly', '没有可直接', '像素不可见')):
            vis += 1
    receipt.update(finished=time.strftime('%Y-%m-%dT%H:%M:%S'), errors=errors, inputs_after_unchanged=not changed,
                   inputs_changed=changed, calls_reporting_unseen_images=vis,
                   credit_old=old_credit, credit_new=new_credit,
                   score_old={d: (old_scores or {}).get('dimensions', {}).get(d, {}).get('S') for d in ('mechanic', 'gamefeel', 'vfx', 'import', 'texture')},
                   score_new={d: (new_scores or {}).get('dimensions', {}).get(d, {}).get('S') for d in ('mechanic', 'gamefeel', 'vfx', 'import', 'texture')})
    write_json(new_dir / 'receipt.json', receipt)
    print(json.dumps({k: receipt[k] for k in ('errors', 'inputs_after_unchanged', 'inputs_changed',
                                              'calls_reporting_unseen_images', 'score_old', 'score_new')},
                     ensure_ascii=False, indent=1))
    return 1 if errors or changed else 0


if __name__ == '__main__':
    raise SystemExit(main())
