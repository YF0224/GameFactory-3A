#!/usr/bin/env python3
"""Backfill the game's own log as EVENT channels into finished takes and re-judge mechanic / gamefeel
SIDE BY SIDE (score.json and earlier verdicts are never touched).

Per eval dir:
  takes/<n>/record/event_trace.jsonl  <- game log (UE unreal.log with times; Unity Editor.log, last take only,
                                         order without times - Unity's log is overwritten on every launch)
  evidence_events.json                <- previous evidence of all takes + the EVENT channels
  verdicts_evidence_events.json       <- re-judged mechanic / gamefeel (same judge model as the run)
  score_events.json                   <- scores with those verdicts; compare against score.json
    python scripts/eval/event_backfill.py <eval dir> [...]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from _common import common  # noqa: F401

from pipeline.eval.whitebox.core import evidence, judge, record, standards, suites  # noqa: E402
from pipeline.eval.whitebox.core.paths import read_json, write_json  # noqa: E402
from pipeline.eval.whitebox.core.pipeline import final_verdicts  # noqa: E402

DIMS = ('mechanic', 'gamefeel')


def run(out: Path) -> dict:
    out = out.resolve()
    manifest = read_json(out / 'manifest.json')
    engine, project = manifest['engine'], out / 'runtime' / 'project'
    takes = sorted(int(p.name) for p in (out / 'takes').iterdir()
                   if p.name.isdigit() and int(p.name) < 90 and (p / 'record' / 'record_result.json').is_file())
    backfill = {}
    log_owner = None
    if engine == 'unity3d':        # the Editor.log belongs to the most recent launch only
        log = project / 'Library' / 'GameFactory3A' / 'Editor.log'
        if log.is_file():
            log_owner = max(takes, key=lambda k: (out / 'takes' / str(k) / 'record' / 'record_result.json').stat().st_mtime)
    for k in takes:
        rec = out / 'takes' / str(k) / 'record'
        if engine == 'unity3d' and k != log_owner:
            backfill[k] = 'no game log kept for this take (Unity log overwritten by a later launch)'
            continue
        backfill[k] = record.game_events(rec, engine, project)
    # Evidence rebuilt with the event channels AND event-anchored frames (separate cache / delivery folder;
    # the original evidence.json and delivery/t<n> are untouched).
    parts = [evidence._take_evidence(out, k, cache_name='evidence_events.json', delivery_name=f't{k}_events')
             for k in takes]
    ev_manifest = {'version': evidence.VERSION, 'takes': takes,
                   'items': evidence._static_items(out) + evidence._view_items(out) + [it for p in parts for it in p['items']],
                   'action_links': [l for p in parts for l in p['action_links']],
                   'sheets': [x for p in parts for x in p['sheets']],
                   'event_sheets': [x for p in parts for x in p.get('event_sheets', [])],
                   'frames_recorded': sum(p['frames_recorded'] for p in parts),
                   'frames_delivered': sum(p['frames_delivered'] for p in parts),
                   'event_anchor_frames': sum(p.get('event_anchor_frames', 0) for p in parts),
                   'event_backfill': backfill}
    write_json(out / 'evidence_events.json', ev_manifest)
    crit = read_json(out / 'input' / 'criteria.json')
    rows = [r for r in crit['criteria'] if r['metric'] in DIMS and r['mode'] != 'static']
    frozen = standards.load('stage3', crit['version'], manifest['game_id'], crit['criteria'])
    new = judge.judge(out, manifest, ev_manifest, 'evidence', frozen, only_ids=[r['id'] for r in rows], tag='_events')
    verdicts = {**final_verdicts(out), **new}
    suite = suites.get('stage3')
    old = read_json(out / 'score.json')
    result = suite.score(crit['criteria'], verdicts)
    result.update(game_id=manifest['game_id'], basis='score.json verdicts + mechanic/gamefeel re-judged with game-log EVENT '
                  'channels (verdicts_evidence_events.json)', event_backfill=backfill)
    write_json(out / 'score_events.json', result)
    return {d: (old['dimensions'].get(d, {}).get('S'), result['dimensions'].get(d, {}).get('S')) for d in DIMS}


if __name__ == '__main__':
    for d in sys.argv[1:]:
        print(Path(d).parent.name[:4], run(Path(d)), flush=True)
