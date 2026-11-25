"""Rule-based Playable checks (import / launch / operate), decided from the engine's own outputs.

No judge model is involved, so citation format or unrelated gameplay bugs can never change them:

* ``play.import``  the engine's real import / compile result of the working copy
  (Godot / Unity: headless import exit code + product compile errors; UE: build + admission;
  three.js has no import step: the page's own module load, i.e. no load-time syntax/module error).
* ``play.launch``  a recording produced sustained valid game frames (not uniform / black) and the
  engine did not crash at startup (a static title screen counts; a hung game is caught by operate).
  Later gameplay bugs belong to other columns.
* ``play.operate`` real input produced a visible response: the frame after an input differs from
  the frame before it clearly more than the game changes on its own (idle baseline). No visible
  response is UNVERIFIED (the plan may have missed the game's controls), and is retried next take.

A check with no evidence because of a tool failure (no import ran, no take recorded) gets no
verdict: it is reported as HARNESS_ERROR and left out (the case stays unpublished and is re-run),
never scored as 0.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .paths import read_json, write_json

VERSION = 'stage1-playable-rules.v1'
IDS = ('play.import', 'play.launch', 'play.operate')

THUMB = (160, 90)
VALID_STD = 4.0            # grayscale std of a frame that shows something (not a uniform fill)
VALID_MEAN = (3.0, 252.0)  # not black, not white
MIN_VALID_FRAMES = 5
RESPONSE_MIN = 2.0         # mean abs grayscale diff (0..255) that counts as a visible change
RESPONSE_IDLE_FACTOR = 2.0
IDLE_MAX = 20.0           # a game changing this much on its own cannot be judged by frame differences
MIN_RESPONSIVE = 2
CRASH = re.compile(r'Crash!!!|Received signal SIG(SEGV|BUS|ABRT)|Fatal error!|=== Critical error ===|'
                   r'Assertion failed:.*Fatal|Uncaught (SyntaxError|ReferenceError|TypeError).*module|'
                   r'Failed to load module script', re.I)
JS_LOAD_ERROR = re.compile(r'Uncaught SyntaxError|Failed to load module script|Cannot use import statement|'
                           r'Failed to resolve module specifier', re.I)


def _verdict(status, reason, evidence=(), counterexample=''):
    return {'status': status, 'reason': reason, 'preconditions_met': status != 'UNVERIFIED',
            'observation_complete': status != 'UNVERIFIED', 'counterexample': counterexample,
            'evidence': [{'id': e, 'line_start': 0, 'line_end': 0, 'observation': reason[:200]} for e in evidence],
            'decided_by': VERSION}


def _jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(l) for l in path.read_text(errors='replace').splitlines() if l.strip()]


def _gray(path: Path):
    import numpy as np
    from PIL import Image
    with Image.open(path) as im:
        return np.asarray(im.convert('L').resize(THUMB), dtype='float32')


def _frames(record: Path, take: int) -> list[dict]:
    rows = []
    for f in _jsonl(record / 'frame_index.jsonl'):
        p = next((c for c in (record / (f.get('raw_path') or ''), record / (f.get('path') or ''),
                              record.parent / (f.get('raw_path') or '')) if c.is_file()), None)
        if p is not None:
            n = str(f.get('frame_id', '')).split(':')[-1]
            rows.append({'id': f'FRAME:T{take}:{n}', 't_ms': float(f.get('t_ms', f.get('timestamp_ms', 0))), 'path': p})
    return sorted(rows, key=lambda r: r['t_ms'])


def _logs(record: Path) -> str:
    return '\n'.join(p.read_text(errors='replace') for p in
                     (record / 'engine.log', record / 'import.log', record / 'native' / 'Editor.log')
                     if p.is_file())


def _import(out: Path, engine: str, takes: list[Path]) -> dict | None:
    if engine in ('godot', 'unity3d'):
        for record in takes:
            res = record / 'import_result.json'
            if res.is_file():
                r = read_json(res)
                if r.get('timeout'):
                    return None
                from .native_log import godot_product_errors
                log = record / 'import.log'
                parsed_errors = (engine == 'godot' and log.is_file()
                                 and godot_product_errors(log.read_text(errors='replace')))
                if r.get('product_errors') or parsed_errors:
                    return _verdict('FAIL', 'engine import/compile reported product errors', ['IMPORT:T1'],
                                    'product parse/compile errors in the engine import log')
                if r.get('exit_code') == 0:
                    return _verdict('PASS', 'real engine import/compile of the working copy succeeded', ['IMPORT:T1'])
        return None
    if engine == 'ue5':
        adm = out / 'runtime' / 'ue_admission' / 'admission.json'
        if adm.is_file():
            a = read_json(adm)
            ok = a.get('ok', a.get('admitted', True)) is not False
            return (_verdict('PASS', 'UE build and native admission of the working copy succeeded', ['LOG:T1'])
                    if ok else _verdict('FAIL', 'UE build/admission failed', ['LOG:T1'], str(a.get('errors'))[:300]))
        return None
    if engine == 'three_js':
        for record in takes:
            if (record / 'record_result.json').is_file() or _frames(record, 1):
                bad = JS_LOAD_ERROR.search(_logs(record))
                if bad:
                    return _verdict('FAIL', 'page module load error', ['LOG:T1'], bad.group(0))
                return _verdict('PASS', 'page modules loaded without load-time errors', ['LOG:T1'])
        return None
    return None


def _launch(takes: list[tuple[int, Path]]) -> tuple[dict | None, dict]:
    best, stats = None, {}
    for take, record in takes:
        frames = _frames(record, take)
        if not frames:
            continue
        crash = CRASH.search(_logs(record))
        step = max(1, len(frames) // 60)
        sample = frames[::step]
        valid, prev, changes = [], None, 0
        for f in sample:
            g = _gray(f['path'])
            if g.std() >= VALID_STD and VALID_MEAN[0] <= g.mean() <= VALID_MEAN[1]:
                valid.append(f)
                if prev is not None and abs(g - prev).mean() >= 0.5:
                    changes += 1
                prev = g
        stats[take] = {'frames': len(frames), 'sampled': len(sample), 'valid': len(valid), 'changes': changes,
                       'crash': crash.group(0) if crash else None}
        if len(valid) >= MIN_VALID_FRAMES and not (crash and len(valid) < len(sample) // 2):
            return _verdict('PASS', f'take {take}: {len(valid)}/{len(sample)} sampled frames show a live game '
                                    f'({changes} changes over time); no startup crash',
                            [valid[0]['id'], valid[-1]['id']]), stats
        best = _verdict('FAIL', f'take {take}: only {len(valid)}/{len(sample)} sampled frames show game content'
                                + (f'; crash: {crash.group(0)}' if crash else ''),
                        [f['id'] for f in sample[:2]],
                        f'no sustained valid game frames ({len(valid)} valid, {changes} changes)'
                        + (f'; {crash.group(0)}' if crash else ''))
    return best, stats


def _operate(takes: list[tuple[int, Path]]) -> tuple[dict | None, dict]:
    import numpy as np
    stats, any_inputs = {}, False
    for take, record in takes:
        frames = _frames(record, take)
        if len(frames) < 2:
            continue
        times = [f['t_ms'] for f in frames]
        acts = [a for a in _jsonl(record / 'actions.jsonl')
                if a.get('action') not in ('wait',) and a.get('phase') != 'up' and a.get('action_id') != 'system/startup'
                and a.get('sent') is not False and a.get('ok') is not False and 't_ms' in a]
        if not acts:
            continue
        any_inputs = True
        cache = {}

        def gray(i):
            if i not in cache:
                cache[i] = _gray(frames[i]['path'])
            return cache[i]

        def before(t):
            idx = [i for i, x in enumerate(times) if x <= t - 30]
            return idx[-1] if idx else None

        def after(t):
            idx = [i for i, x in enumerate(times) if t + 250 <= x <= t + 1500]
            return idx

        busy = [(a['t_ms'] - 300, a.get('end_t_ms', a['t_ms']) + 1500) for a in acts]
        idle = []
        for i in range(1, len(frames)):
            t0, t1 = times[i - 1], times[i]
            if 200 <= t1 - t0 <= 1600 and not any(s <= t1 and t0 <= e for s, e in busy):
                idle.append(float(abs(gray(i) - gray(i - 1)).mean()))
            if len(idle) >= 20:
                break
        idle_level = float(np.percentile(idle, 75)) if idle else 0.0
        threshold = max(RESPONSE_MIN, RESPONSE_IDLE_FACTOR * idle_level)
        if idle_level > IDLE_MAX:
            stats[take] = {'inputs': len(acts), 'checked': 0, 'responsive': 0, 'idle_level': round(idle_level, 2),
                           'undecidable': 'the view changes too much on its own'}
            continue
        responsive, checked = [], 0
        for a in acts:
            b = before(a['t_ms'])
            post = after(a.get('end_t_ms', a['t_ms']))
            if b is None or not post:
                continue
            checked += 1
            diff = max(float(abs(gray(i) - gray(b)).mean()) for i in post[:4])
            if diff >= threshold:
                responsive.append((a.get('action_id'), frames[b]['id'], frames[post[0]]['id'], round(diff, 2)))
        stats[take] = {'inputs': len(acts), 'checked': checked, 'responsive': len(responsive),
                       'idle_level': round(idle_level, 2), 'threshold': round(threshold, 2)}
        need = min(MIN_RESPONSIVE, checked)
        if checked and len(responsive) >= max(1, need):
            r = responsive[:3]
            return _verdict('PASS', f'take {take}: {len(responsive)}/{checked} inputs changed the game view '
                                    f'beyond its idle change (threshold {threshold:.1f}); e.g. '
                                    + '; '.join(f'{x[0]}: {x[1]}->{x[2]} diff {x[3]}' for x in r),
                            [e for x in r for e in x[1:3]]), stats
    if not any_inputs:
        return None, stats
    total = sum(s.get('checked', 0) for s in stats.values())
    if total == 0 and not any(s.get('undecidable') for s in stats.values()):
        return None, stats          # no frames around any input: missing evidence, not a product result
    # No visible response is not proof the game is broken: the plan may not have used the game's
    # controls (e.g. clicked beside a button). UNVERIFIED (0 credit) and another take retries it.
    return _verdict('UNVERIFIED', f'no visible response beyond idle across {total} checked inputs '
                                  '(game unresponsive, or the inputs were not the game\'s controls)'), stats


def evaluate(out: Path, manifest: dict, upto: int, *, report_dir: Path | None = None) -> dict:
    """Decide the Playable rows from takes 1..upto; writes ``verdicts_playable_rules.json``."""
    out = Path(out)
    from .plan import take_dir
    takes = [(k, take_dir(out, k) / 'record') for k in range(1, upto + 1)
             if (take_dir(out, k) / 'record' / 'record_result.json').is_file()]
    engine = manifest['engine']
    verdicts, harness = {}, {}
    imp = _import(out, engine, [r for _, r in takes] or
                  [take_dir(out, k) / 'record' for k in range(1, upto + 1)])
    launch, launch_stats = _launch(takes)
    operate, operate_stats = _operate(takes)
    for ident, v in zip(IDS, (imp, launch, operate)):
        if v is None:
            harness[ident] = 'HARNESS_ERROR: no engine import/recording evidence for this check (re-run)'
        else:
            verdicts[ident] = v
    destination = Path(report_dir) if report_dir is not None else out
    write_json(destination / 'verdicts_playable_rules.json', verdicts)
    write_json(destination / 'playable_rules.json', {'version': VERSION, 'engine': engine, 'takes': [k for k, _ in takes],
                                             'launch': launch_stats, 'operate': operate_stats,
                                             'harness_errors': harness})
    return verdicts
