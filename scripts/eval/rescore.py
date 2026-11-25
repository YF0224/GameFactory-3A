#!/usr/bin/env python3
"""Re-check finished evaluations against the current citation rules, without new model calls.

Every evidence pass is re-enforced from its already-accepted judge replies (same shards,
same evidence, same frozen standards); then the case is scored again. The previous verdict
files and score are moved to ``_rescore_archive/<UTC time>/`` first. Nothing is recorded or
re-judged; a pass whose replies are missing is left as it was and reported.

    python scripts_new/rescore.py <eval dir> [<eval dir> ...]
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from _common import common  # noqa: F401  (sets sys.path)

from pipeline.eval.whitebox import judge, pipeline, standards  # noqa: E402
from pipeline.eval.whitebox.paths import read_json, write_json  # noqa: E402


def _standards(out: Path, manifest: dict, rows: list[dict]) -> dict:
    """Bench standards (current runs) or the per-run frozen standards of older runs."""
    suite = manifest.get('suite', 'stage1')
    version = read_json(out / 'input' / 'criteria.json')['version']
    try:
        return standards.load(suite, version, manifest['game_id'], rows)
    except ValueError:
        pass
    old = out.parents[2] / '_standards' / 'outcome_frame_v1' / manifest['models']['judge'] / manifest['game_id']
    found = {f.stem: read_json(f)['standard'] for f in old.glob('*.json') if 'standard' in read_json(f)}
    if not found:
        raise SystemExit(f'{out}: no standards found (bench or {old})')
    return found


def _no_new_calls(*_a, **_k):
    raise RuntimeError('rescore never calls a model: a shard has no accepted reply')


judge.call_model = _no_new_calls


def rescore(out: Path) -> dict:
    manifest = read_json(out / 'manifest.json')
    rows = read_json(out / 'input' / 'criteria.json')['criteria']
    frozen = _standards(out, manifest, rows)
    passes = sorted(out.glob('verdicts_evidence_t*.json'))
    if not passes:
        return {'out': str(out), 'skipped': 'no evidence passes'}
    archive = out / '_rescore_archive' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    archive.mkdir(parents=True)
    for f in passes + [out / 'score.json']:
        if f.is_file():
            shutil.copy2(f, archive / f.name)
    changed = 0
    for f in passes:
        tag = f.stem.removeprefix('verdicts_evidence')               # '_t1'
        take = int(tag.removeprefix('_t'))
        before = read_json(f)
        evidence = read_json(out / ('evidence_static.json' if take == 0 else f'evidence_t{take}.json'))
        f.unlink()
        try:
            after = judge.judge(out, manifest, evidence, 'evidence', frozen, only_ids=list(before), tag=tag)
        except Exception:
            shutil.copy2(archive / f.name, f)                          # keep the old pass
            raise
        changed += sum(1 for k in before if before[k] != after.get(k))
    result = pipeline.score(out)
    write_json(archive / 'rescore.json', {'reason': 'current citation rules re-applied to accepted replies',
                                          'changed_verdicts': changed})
    return {'out': str(out), 'changed_verdicts': changed, 'archive': str(archive),
            'dimensions': {k: (v['S'], v['Cov']) for k, v in result.get('dimensions', {}).items()}}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('eval_dirs', nargs='+', type=Path)
    for d in ap.parse_args().eval_dirs:
        print(rescore(d.resolve()), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
