"""Rejudge existing Stage3 native recordings after CLI image resizing.

Never plans or records. Uses a distinct immutable call/tag, retains old scores
and verdicts, and publishes only after every new shard has actual pixel proof.
"""
from __future__ import annotations

from ..model_config import JUDGE_MODEL

import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil
import time

from ..stage1 import evidence, judge, prepare, standards
from ..whitebox.llm import HarnessError
from ..whitebox.paths import read_json, sha256, write_json
from . import selected

VERSION = 'stage3-original-image-rejudge.v1'


def recover(out: Path):
    out = out.resolve()
    with (out / '.selected_eval.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (out / 'original_image_recovery.json').is_file():
            selected.final_verdicts(out)
            return read_json(out / 'score.json')
        manifest = prepare.verify(out)
        request = read_json(out / 'selected_request.json')
        dimensions = tuple(request['dimensions'])
        if manifest['suite'] != 'stage3' or manifest['models']['judge'] != JUDGE_MODEL:
            raise HarnessError('Recovery only supports selected Stage3 Sol judgments')
        status = read_json(out / 'status.json')
        if status['state'] == 'running':
            raise HarnessError('A running case must finish its current owner first')
        takes = sorted(int(p.parent.parent.name) for p in out.glob('takes/*/record/record_result.json'))
        if not takes or takes != list(range(1, max(takes)+1)):
            raise HarnessError('Contiguous qualified records required; recovery never records')
        rows = [r for r in read_json(out / 'input/criteria.json')['criteria'] if r['metric'] in dimensions]
        frozen = standards.load('stage3', read_json(out / 'input/criteria.json')['version'], manifest['game_id'], rows)
        parents = [out / 'manifest.json', out / 'selected_request.json', out / 'status.json']
        parents += [out / 'takes' / str(t) / name for t in takes for name in ('plan.json', 'record/record_result.json')]
        bindings = {str(p.relative_to(out)): sha256(p) for p in parents}
        archive = out / 'engineering' / ('original_image_recovery_' + str(time.time_ns()))
        archive.mkdir(parents=True)
        for p in [out / 'status.json', out / 'score.json', *out.glob('verdicts_evidence_t*.json')]:
            if p.is_file():
                shutil.copyfile(p, archive / p.name)
        write_json(archive / 'parent.json', dict(version=VERSION, bindings=bindings,
            reason='Legacy Codex exec --image resized some declared contact sheets',
            new_recording=False, standards_changed=False))
        os.environ['A3GAME_LOSSLESS_IMAGES'] = '1'
        os.environ['A3GAME_ORIGINAL_IMAGE_TRANSPORT'] = '1'
        ev = evidence.build(out, takes)
        tag = '_original_pixels'
        verdicts = judge.judge(out, manifest, ev, 'evidence', frozen,
            only_ids=[r['id'] for r in rows], tag=tag)
        target = out / ('verdicts_evidence' + tag + '.json')
        # All shards must have retained pixel proof, including accepted shards.
        calls = sorted((out / 'model_calls').glob('evidence_original_pixels_[0-9][0-9]'))
        if not calls:
            raise HarnessError('No original-pixel calls')
        delivery = []
        for call in calls:
            accepted = read_json(call / 'accepted_response.json')
            response = (call / accepted['path']).resolve()
            actual = response.parent / 'actual_delivery.json'
            proof = read_json(actual)
            if not proof['all_original_pixels_delivered'] or not all(p['pixel_equal'] for p in proof['images']):
                raise HarnessError('Complete actual image delivery proof required')
            delivery.append(dict(call=call.name, accepted_sha256=sha256(response), actual_delivery=str(actual.relative_to(out)), actual_delivery_sha256=sha256(actual)))
        if any(sha256(out / rel) != digest for rel, digest in bindings.items()):
            raise HarnessError('Parent source/record/stage changed during rejudge')
        receipt = dict(version=VERSION, manifest_sha256=sha256(out / 'manifest.json'),
            verdicts=target.name, verdicts_sha256=sha256(target), last_take=max(takes),
            native_recordings_reused=takes, new_recording=False, old_materials=str(archive.relative_to(out)),
            actual_deliveries=delivery, status='SCORED_PENDING_AUDIT')
        write_json(out / 'original_image_recovery.json', receipt)
        result = selected.selected_score(out, dimensions, provisional=status['state'] != 'done')
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, nargs='+', required=True)
    args = parser.parse_args()
    failed = False
    for out in args.run:
        try:
            result = recover(out)
            print(json.dumps(dict(run=str(out), scores={m:d['S'] for m,d in result['dimensions'].items()}, provisional=result['provisional'])), flush=True)
        except Exception as exc:
            failed = True
            print(json.dumps(dict(run=str(out), status='HARNESS_ERROR', error=str(exc))), flush=True)
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
