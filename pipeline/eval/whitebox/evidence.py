"""Turn a recorded take into the judge's evidence set.

Evidence ids (what the judge may cite):

* ``SRC:<path>``   authored project files (1-based line numbers)
* ``DOC:<path>``   delivery documents beside the project (declarations only)
* ``REQUIREMENTS`` the case requirement (context, not proof)
* ``REF:<name>``   reference images (line 0)
* ``ACTION`` / ``STATE`` / ``EVENT`` / ``LOG``   runtime channels (1-based lines)
* ``FRAME:<id>``   one recorded frame (line 0)
* ``VIEW:<asset>`` in-engine 2x2 four-view render of an imported asset (line 0; asset_views.py)
* ``MOTION:T<k>:<asset>`` native gameplay frames during observed motion playback (line 0)

Frames are selected around the actions planned for each criterion
(during, before, after, round-robin across criteria) plus a uniform spread,
then tiled 2x2 at native pixels into ``delivery/sheet_NNN.png`` with a
"FRAME id | t ms" caption. Tiles are verified byte-for-byte against the raw
frames; nothing is resized or synthesized.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .paths import OUTPUTS, read_json, sha256, write_json

VERSION = 'stage1-evidence.v1'
SOURCE_SUFFIXES = {'.gd', '.tscn', '.godot', '.cs', '.unity', '.scene', '.prefab', '.asset', '.cpp', '.h',
                   '.hpp', '.ini', '.uproject', '.uplugin', '.js', '.mjs', '.ts', '.html', '.css', '.gdshader',
                   '.shader', '.tres', '.json'}
SKIP_DIRS = {'node_modules', '.godot', '.import', 'Library', 'Temp', 'obj', 'dist', 'build', 'Intermediate',
             'Saved', 'Binaries', 'DerivedDataCache', '.git'}
WINDOWS_MS = {'before': (-600, -20), 'during': (0, 500), 'after': (180, 3000)}
UNIFORM_FRAMES = 12
MAX_STATE_SAMPLES = 160


def _jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(errors='replace').splitlines() if line.strip()]


def frame_budget(n_runtime_criteria: int) -> int:
    return min(240, max(96, 6 * n_runtime_criteria))


def _frame_rows(runtime: Path, take: int) -> list[dict]:
    rows = []
    # scheduled frames + event-triggered frames (own index, written by the recorder on game log lines)
    indexed = _jsonl(runtime / 'frame_index.jsonl')
    if (runtime / 'event_frame_index.jsonl').is_file():
        indexed = sorted(indexed + _jsonl(runtime / 'event_frame_index.jsonl'),
                         key=lambda r: float(r.get('t_ms', r.get('time_ms', 0))))
    for i, row in enumerate(indexed, 1):
        raw = str(row.get('frame_id') or row.get('id') or f'{i:05d}').removeprefix('FRAME:')
        ident = f'FRAME:T{take}:{raw}'
        path = Path(row.get('path', ''))
        path = path if path.is_absolute() else runtime / path
        if not path.is_file():
            path = runtime / 'frames' / Path(row.get('path', '')).name
        rows.append({'id': ident, 't_ms': float(row.get('t_ms', row.get('time_ms', 0))), 'path': path,
                     'capture_ids': list(row.get('capture_ids') or [])})
    return rows


ANCHORED_ROLES = {'before': ('pre/',), 'during': ('end/', 'hold'), 'after': ('post300/', 'post1000/')}


def action_links(runtime: Path, plan: dict, frames: list[dict]) -> list[dict]:
    """For each recorded action: its criteria and frame ids before / during / after it.

    Action-anchored takes link frames by capture id (``pre/<action_id>`` ...);
    dense takes fall back to windows around the action's RECORDED timestamp."""
    probe_criteria = {p['id']: p['criterion_ids'] for p in plan['probes']}
    by_capture: dict[str, list[str]] = {}
    for f in frames:
        for cid in f['capture_ids']:
            by_capture.setdefault(cid, []).append(f['id'])
    links = []
    for line, act in enumerate(_jsonl(runtime / 'actions.jsonl'), 1):
        probe = act.get('probe_id') or str(act.get('action_id', '')).split('/')[0]
        criteria = act.get('criterion_ids') or probe_criteria.get(probe, [])
        t = float(act.get('t_ms', act.get('start_ms', 0)))
        aid = act.get('action_id')
        anchored = {role: [f for pre in prefixes for f in by_capture.get(pre + str(aid), [])]
                    for role, prefixes in ANCHORED_ROLES.items()} if aid else {}
        if any(anchored.values()):
            windows, source = anchored, 'capture_id'
        else:
            windows = {role: [f['id'] for f in frames if lo <= f['t_ms'] - t <= hi]
                       for role, (lo, hi) in WINDOWS_MS.items()}
            source = 'recorded_time_window'
        links.append({'action_line': line, 'action_id': aid, 'probe_id': probe, 'criterion_ids': criteria,
                      't_ms': t, 'frames': windows, 'link_source': source})
    return links


def select_frames(frames: list[dict], links: list[dict], budget: int) -> list[str]:
    known = {f['id'] for f in frames}
    chosen: list[str] = []

    def take(ident):
        if ident in known and ident not in chosen and len(chosen) < budget:
            chosen.append(ident)

    by_criterion: dict[str, list[dict]] = {}
    for link in links:
        for c in link['criterion_ids']:
            by_criterion.setdefault(c, []).append(link)
    for role in ('during', 'before', 'after'):          # one frame of each role per criterion first
        for own in by_criterion.values():
            hit = [f for link in own for f in link['frames'][role]]
            if hit:
                take(hit[0])
    per_criterion = {c: list(dict.fromkeys(f for link in own for role in ('during', 'before', 'after')
                                           for f in link['frames'][role]))
                     for c, own in by_criterion.items()}
    for turn in range(max((len(q) for q in per_criterion.values()), default=0)):
        for q in per_criterion.values():
            if turn < len(q):
                take(q[turn])
    if frames:
        n = min(UNIFORM_FRAMES, budget)
        for k in range(n):
            take(frames[round(k * (len(frames) - 1) / max(1, n - 1))]['id'])
    order = {f['id']: i for i, f in enumerate(frames)}
    return sorted(chosen, key=order.get)


def _sheets(frames: list[dict], selected: list[str], delivery: Path) -> list[dict]:
    from PIL import Image, ImageDraw
    by_id = {f['id']: f for f in frames}
    items, sheets = [], []
    for s in range(0, len(selected), 4):
        group = [by_id[i] for i in selected[s:s + 4]]
        images = [Image.open(f['path']).convert('RGB') for f in group]
        w = max(i.width for i in images)
        h = max(i.height for i in images)
        caption = 18
        sheet = Image.new('RGB', (2 * w, 2 * (h + caption)), 'white')
        draw = ImageDraw.Draw(sheet)
        path = delivery / f'sheet_{len(sheets) + 1:03d}.png'
        for k, (f, img) in enumerate(zip(group, images)):
            x, y = (k % 2) * w, (k // 2) * (h + caption)
            draw.text((x + 4, y + 2), f'{f["id"]} | {int(f["t_ms"])} ms', fill='black')
            sheet.paste(img, (x, y + caption))
            items.append({'id': f['id'], 't_ms': f['t_ms'], 'raw': str(f['path']), 'raw_sha256': sha256(f['path']),
                          'sheet': path.name, 'tile_rect': [x, y + caption, img.width, img.height]})
        sheet.save(path)
        sheets.append(path)
        with Image.open(path) as saved:        # verify native pixels were not altered
            for it in items[-len(group):]:
                x, y, tw, th = it['tile_rect']
                with Image.open(it['raw']) as raw:
                    if saved.crop((x, y, x + tw, y + th)).tobytes() != raw.convert('RGB').tobytes():
                        raise RuntimeError(f'tile {it["id"]} differs from its raw frame')
    return items


GRID = 3                    # context / event frames: 3x3 per sheet
GRID_TILE_W = 682           # ~ what the model resolves per frame anyway (sheet 2046 px wide, not re-shrunk)
GRID_JPEG_QUALITY = 88


def _grid_sheets(frames: list[dict], selected: list[str], delivery: Path, start: int, grid: int | None = None) -> list[dict]:
    """Compact sheets for context / event frames: each frame downscaled to GRID_TILE_W wide, 3x3 per JPEG
    sheet. The original frame stays on disk (raw / raw_sha256) and each tile records its rect and scale,
    so every cited tile traces back to its native frame."""
    from PIL import Image, ImageDraw
    by_id = {f['id']: f for f in frames}
    items, n = [], start
    GRID_ = grid or GRID                       # denser grids (4x4, 5x5) only when a call's image count is short
    TILE_W = GRID_TILE_W * GRID // GRID_       # same sheet width, smaller tiles
    per = GRID_ * GRID_
    for s in range(0, len(selected), per):
        group = [by_id[i] for i in selected[s:s + per]]
        tiles = []
        for f in group:
            with Image.open(f['path']) as im:
                im = im.convert('RGB')
                scale = TILE_W / im.width
                tiles.append((f, im.resize((TILE_W, max(1, round(im.height * scale))), Image.LANCZOS), scale))
        th = max(t[1].height for t in tiles)
        caption = 16
        sheet = Image.new('RGB', (GRID_ * TILE_W, GRID_ * (th + caption)), 'white')
        draw = ImageDraw.Draw(sheet)
        n += 1
        path = delivery / (f'grid_{n:03d}.jpg' if GRID_ == GRID else f'grid{GRID_}_{n:03d}.jpg')
        for k, (f, img, scale) in enumerate(tiles):
            x, y = (k % GRID_) * TILE_W, (k // GRID_) * (th + caption)
            draw.text((x + 4, y + 2), f'{f["id"]} | {int(f["t_ms"])} ms', fill='black')
            sheet.paste(img, (x, y + caption))
            items.append({'id': f['id'], 't_ms': f['t_ms'], 'raw': str(f['path']), 'raw_sha256': sha256(f['path']),
                          'sheet': path.name, 'tile_rect': [x, y + caption, img.width, img.height],
                          'tile_scale': round(scale, 4), 'tile_format': 'jpeg_downscaled'})
        sheet.save(path, quality=GRID_JPEG_QUALITY)
    return items


def _state_samples(runtime: Path, links: list[dict]) -> list[int]:
    rows = _jsonl(runtime / 'state_trace.jsonl')
    if not rows:
        return []
    times = [float(r.get('t_ms', 0)) for r in rows]
    picked = {1, len(rows)}
    for link in links:
        for off in (-100, 0, 100, 300, 600, 1100):
            target = link['t_ms'] + off
            picked.add(min(range(len(rows)), key=lambda i: abs(times[i] - target)) + 1)
    previous = None
    for i, r in enumerate(rows, 1):
        values = {k: v for k, v in r.items() if k not in ('t_ms', 'frame', 'time') and not isinstance(v, (dict, list))}
        if previous is not None and values != previous:
            picked.add(i)
        previous = values
    return sorted(picked)[:MAX_STATE_SAMPLES]


def build_static(out: Path) -> dict:
    """Source / document / requirement evidence only (judged before recording)."""
    out = Path(out)
    if (out / 'evidence_static.json').is_file():
        return read_json(out / 'evidence_static.json')
    manifest = {'version': VERSION, 'takes': [], 'items': _static_items(out), 'action_links': [], 'sheets': [],
                'frames_recorded': 0, 'frames_delivered': 0}
    write_json(out / 'evidence_static.json', manifest)
    return manifest


def _item(ident, path, kind, **extra):
    return {'id': ident, 'path': str(path), 'type': kind, 'sha256': sha256(path),
            'lines': len(Path(path).read_text(errors='replace').splitlines()) if kind in
            ('source', 'document', 'requirement', 'channel') else 0, **extra}


def _asset_keys(out: Path) -> dict:
    """asset id -> lower-case keys that identify it in the recorder's asset events: the asset id itself, its UE
    package paths (/Game/...) and its project file paths / stems (Assets/..., Movies/x.mp4)."""
    path = out / 'import_presence.json'
    if not path.is_file():
        try:
            from ..stage3 import import_presence
            import_presence.evaluate(out)
        except Exception:                                    # not a stage3 run / no import tasks
            return {}
    if not path.is_file():
        return {}
    keys = {}
    for asset, a in read_json(path).get('assets', {}).items():
        k = {asset.lower()}
        for f in a.get('project_files', []):
            p = Path(f)
            k.add(f.lower())
            k.add(p.stem.lower())
            if f.startswith('Content/'):
                k.add(('/Game/' + p.relative_to('Content').with_suffix('').as_posix()).lower())
        keys[asset] = {x for x in k if len(x) >= 4}
    return keys


def _event_asset_id(path: str, keys: dict) -> str | None:
    """Resolve one event without attributing shared filenames or ID prefixes to other assets."""
    path = path.replace('\\', '/').lower()
    matches = {}
    for asset, candidates in keys.items():
        for key in candidates:
            key = key.replace('\\', '/').lower()
            if not re.search(r'(?<![\w])' + re.escape(key) + r'(?![\w])', path):
                continue
            # Explicit IDs and complete paths outrank short, potentially shared stems.
            rank = (3 if key == asset.lower() else 2 if '/' in key else 1, len(key))
            matches[asset] = max(matches.get(asset, (0, 0)), rank)
    if not matches:
        return None
    best = max(matches.values())
    owners = [asset for asset, rank in matches.items() if rank == best]
    return owners[0] if len(owners) == 1 else None


def _loudness_after(runtime: Path, t_ms: float, window_ms: float = 1500.0):
    """RMS level (dBFS) of the captured game output in the window after t_ms; None when nothing was captured."""
    wav, cap = runtime / 'audio.wav', runtime / 'audio_capture.json'
    if not wav.is_file() or not cap.is_file():
        return None
    try:
        import array, math, wave
        start = float(read_json(cap).get('start_t_ms') or 0.0)
        with wave.open(str(wav)) as w:
            if w.getsampwidth() != 2:
                return None
            rate, ch = w.getframerate(), w.getnchannels()
            first = max(0, int((t_ms - start) / 1000.0 * rate))
            last = min(w.getnframes(), int((t_ms + window_ms - start) / 1000.0 * rate))
            if last <= first:
                return None
            w.setpos(first)
            data = array.array('h', w.readframes(last - first))
        if not data:
            return None
        rms = math.sqrt(sum(x * x for x in data) / len(data)) / 32768.0
        return round(20 * math.log10(rms), 1) if rms > 0 else -120.0
    except Exception:
        return None


def asset_event_items(out: Path, runtime: Path, take: int) -> list[dict]:
    """Stage3: ASSET_EVENT:T<k>:<asset> - the recorder's events for ONE imported asset (motion / audio / video start,
    end, interruption / early stop, with take time, owner and timing detail; audio starts carry the measured output
    level), so the asset's import checks see when the game used it. Level loads are kept as context lines."""
    src = runtime / 'asset_events.jsonl'
    crit = out / 'input' / 'criteria.json'
    if not src.is_file() or not crit.is_file():
        return []
    checks = {}
    for r in read_json(crit)['criteria']:
        if r.get('asset_id') and r['metric'] == 'import':
            checks.setdefault(r['asset_id'], []).append(r['id'])
    keys = _asset_keys(out)
    for asset in checks:
        keys.setdefault(asset, {asset.lower()})
    rows = _jsonl(src)
    levels = [r for r in rows if r.get('kind') == 'level']
    grouped = {}
    for r in rows:
        if r.get('kind') != 'level':
            asset = _event_asset_id(str(r.get('asset', '')), keys)
            if asset in checks:
                grouped.setdefault(asset, []).append(r)
    folder = runtime / 'asset_events'
    items = []
    for asset, ids in sorted(checks.items()):
        mine = grouped.get(asset, [])
        if not mine:
            continue
        for r in mine:
            if r.get('kind') == 'audio' and r.get('event') == 'start':
                level = _loudness_after(runtime, float(r.get('t_ms', 0.0)))
                if level is not None:
                    target = r['detail'] if isinstance(r.get('detail'), dict) else r
                    target['output_rms_dbfs_next_1500ms'] = level
        folder.mkdir(exist_ok=True)
        dest = folder / f'{asset}.jsonl'
        with dest.open('w', encoding='utf-8') as f:
            for r in sorted(levels + mine, key=lambda x: float(x.get('t_ms', 0.0))):
                f.write(json.dumps(r, ensure_ascii=False) + '\n')
        items.append(_item(f'ASSET_EVENT:T{take}:{asset}', dest, 'channel', check_ids=ids))
    return items


def _static_items(out: Path) -> list[dict]:
    inputs, items = out / 'input', []
    project = inputs / 'project'
    for p in sorted(project.rglob('*')):
        rel = p.relative_to(project)
        if p.is_file() and not p.is_symlink() and not set(rel.parts) & SKIP_DIRS and p.suffix in SOURCE_SUFFIXES:
            items.append(_item('SRC:' + rel.as_posix(), p, 'source'))
    docs = inputs / 'delivery_documents'
    for p in sorted(docs.rglob('*')) if docs.is_dir() else []:
        if p.is_file():
            items.append(_item('DOC:' + p.relative_to(docs).as_posix(), p, 'document'))
    items.append(_item('REQUIREMENTS', inputs / 'requirement.txt', 'requirement'))
    refs = inputs / 'references'
    for p in sorted(refs.glob('*')) if refs.is_dir() else []:
        items.append(_item('REF:' + p.name, p, 'image'))
    return items


MAX_EVENT_FRAMES = 240


def event_anchor_frames(runtime: Path, frames: list[dict]) -> list[str]:
    """Frames around the game's own timed events (event_trace.jsonl rows with t_ms): the first frame up to
    1.5 s after each event (the result) and the last frame up to 1 s before it (the state it changed).
    Untimed events (Unity log order only) anchor nothing."""
    path = runtime / 'event_trace.jsonl'
    if not path.is_file() or not frames:
        return []
    times = []
    for line in path.read_text(errors='replace').splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row.get('t_ms'), (int, float)):
            times.append(float(row['t_ms']))
    chosen: list[str] = []
    for t in sorted(times):
        # event-triggered frames the recorder took for this event (+0 / +250 / +700 ms), then the usual pair
        own = [f for f in frames if t <= f['t_ms'] <= t + 1500
               and any(c.startswith('event/') for c in f.get('capture_ids', []))][:3]
        after = next((f for f in frames if t <= f['t_ms'] <= t + 1500), None)
        before = next((f for f in reversed(frames) if t - 1000 <= f['t_ms'] < t), None)
        for f in own + [after, before]:
            if f is not None and f['id'] not in chosen:
                chosen.append(f['id'])
    return chosen[:MAX_EVENT_FRAMES]


def audio_trace(runtime: Path) -> None:
    """AUDIO channel: each game sound start / stop the recorder saw (audio_events.jsonl: object, clip, volume,
    mute, active listeners, audible_to_player) plus, when the game output was captured (audio.wav, one active
    listener), its measured loudness in the 1.5 s after each start. Without a listener Unity outputs nothing:
    the row says so instead of a loudness."""
    src, dst = runtime / 'audio_events.jsonl', runtime / 'audio_trace.jsonl'
    if not src.is_file() or dst.is_file():
        return
    rows = _jsonl(src)
    wav, cap = runtime / 'audio.wav', runtime / 'audio_capture.json'
    start_ms, samples, rate, ch = None, None, 0, 1
    if wav.is_file() and cap.is_file():
        try:
            import wave, array, math
            meta = read_json(cap)
            start_ms = meta.get('start_t_ms')
            with wave.open(str(wav)) as w:
                rate, ch = w.getframerate(), w.getnchannels()
                samples = array.array('h', w.readframes(w.getnframes()))
        except Exception:                                   # noqa: BLE001 - loudness is optional
            samples = None
    out = []
    env = runtime / 'audio_environment.json'
    engine_off = False
    if env.is_file():
        e = read_json(env)
        engine_off = e.get('audio_engine_running') is False
        out.append({'t_ms': 0, 'event': 'audio_environment', **e,
                    'note': ('Unity reports its audio engine off: no sound output can be captured or measured in this take; '
                             'inspect authored audio settings and launch configuration to establish the cause')
                    if engine_off else 'audio engine running'})
    for r in rows:
        r = dict(r)
        if r.get('event') == 'start':
            if samples is not None and start_ms is not None and rate:
                import math
                a = int(max(0, (r['t_ms'] - start_ms) / 1000 * rate)) * ch
                b = min(len(samples), a + int(1.5 * rate) * ch)
                seg = samples[a:b]
                rms = math.sqrt(sum(x * x for x in seg) / len(seg)) / 32768 if len(seg) else 0.0
                r['output_rms_dbfs_1500ms'] = round(20 * math.log10(rms), 1) if rms > 0 else None
                r['output_heard'] = bool(rms > 10 ** (-60 / 20))
            elif engine_off:
                r['output_heard'] = None
                r['output_note'] = 'Unity audio engine off: output not measurable; this measurement alone does not establish the cause'
            else:
                r['output_heard'] = None
                r['output_note'] = ('game output not capturable: no active AudioListener, so Unity plays nothing audible'
                                    if r.get('active_listeners') == 0 else 'game output was not captured in this take')
        out.append(r)
    dst.write_text(''.join(json.dumps(x, ensure_ascii=False) + '\n' for x in out), encoding='utf-8')


def video_endpoint_frames(runtime: Path, frames: list[dict], channels: list[dict]) -> list[dict]:
    """First observed native frame of playback, plus last only for an observed natural end.

    stop_early never establishes a user skip: that requires input/game/source evidence at judging.
    A frame more than 500 ms from an endpoint is not presented as that endpoint.
    The observer polls at 10 Hz: omit the final 100 ms before an observed end,
    where the game may already have transitioned away from the video.
    """
    frames = sorted(frames, key=lambda f: f['t_ms'])
    all_rows = sorted(_jsonl(runtime / 'asset_events.jsonl'), key=lambda r: float(r.get('t_ms', 0)))
    samples = []
    for channel in channels:
        for start in _jsonl(Path(channel['path'])):
            if start.get('kind') != 'video' or start.get('event') != 'play':
                continue
            begin = float(start['t_ms'])
            stop = next((r for r in all_rows if r.get('kind') == 'video'
                         and r.get('owner') == start.get('owner') and float(r.get('t_ms', 0)) > begin
                         and r.get('event') in ('end', 'stop_early', 'close', 'open', 'play')), None)
            end = float(stop['t_ms']) if stop else float('inf')
            inside = [f for f in frames if begin <= f['t_ms'] < end]
            if not inside:
                continue
            base = {'asset_event_id': channel['id'], 'check_ids': channel['check_ids'],
                    'playback_end_event': stop.get('event') if stop else 'unobserved'}
            if inside[0]['t_ms'] - begin <= 500:
                samples.append({**base, 'id': inside[0]['id'], 'video_role': 'first_observed'})
            tail = [f for f in inside if f['t_ms'] <= end - 100]
            if stop and stop['event'] == 'end' and tail and end - tail[-1]['t_ms'] <= 500:
                samples.append({**base, 'id': tail[-1]['id'], 'video_role': 'last_before_natural_end',
                                'end_poll_guard_ms': 100})
    return samples


def _take_evidence(out: Path, take: int, cache_name: str = 'evidence.json', delivery_name: str | None = None) -> dict:
    """Channels, frame sheets and action links of one recorded take (cached per take)."""
    from .plan import take_dir
    folder = take_dir(out, take)
    cached = folder / cache_name
    if cached.is_file():
        return read_json(cached)
    runtime, plan = folder / 'record', read_json(folder / 'plan.json')
    items = []
    audio_trace(runtime)
    for name, file in (('ACTION', 'actions.jsonl'), ('STATE', 'state_trace.jsonl'), ('EVENT', 'event_trace.jsonl'),
                       ('AUDIO', 'audio_trace.jsonl'), ('LOG', 'engine.log'), ('IMPORT', 'import.log')):
        if (runtime / file).is_file() and (runtime / file).stat().st_size:
            items.append(_item(f'{name}:T{take}', runtime / file, 'channel'))
    # Preserve the complete observed trace, including renamed clips which cannot yet be bound
    # to a canonical import asset id. A raw observation never asserts that identity mapping.
    if (runtime / 'asset_events.jsonl').is_file() and (runtime / 'asset_events.jsonl').stat().st_size:
        items.append(_item(f'LOG:T{take}:asset_events', runtime / 'asset_events.jsonl', 'channel'))
    items += asset_event_items(out, runtime, take)      # stage3: per imported asset, when the game used it
    frames = _frame_rows(runtime, take)
    items += motion_gameplay_items(runtime, take, frames,
                                   [it for it in items if it['id'].startswith('ASSET_EVENT:')])
    links = [dict(l, take=take) for l in action_links(runtime, plan, frames)]
    targets = read_json(folder / 'plan_coverage.json')['targets']
    selected = select_frames(frames, links, frame_budget(len(targets)))
    video_samples = video_endpoint_frames(runtime, frames, [it for it in items if it['id'].startswith('ASSET_EVENT:')])
    selected = list(dict.fromkeys(selected + [f['id'] for f in video_samples]))
    anchors = event_anchor_frames(runtime, frames)      # result frames of the game's own logged events
    order = {f['id']: i for i, f in enumerate(frames)}
    dname = delivery_name or f't{take}'
    delivery = out / 'delivery' / dname
    delivery.mkdir(parents=True, exist_ok=True)
    # action-anchored frames: native 2x2 PNG sheets (detail); extra event-anchored frames: compact 3x3 grids
    extra = sorted(set(anchors) - set(selected), key=order.get)
    delivered = _sheets(frames, sorted(selected, key=order.get), delivery)
    sheet_count = len({d['sheet'] for d in delivered})
    delivered += _grid_sheets(frames, extra, delivery, 0) if extra else []
    for d in delivered:
        items.append({'id': d['id'], 'path': d['raw'], 'type': 'frame', 'sha256': d['raw_sha256'], 'lines': 0,
                      't_ms': d['t_ms'], 'sheet': f'{dname}/{d["sheet"]}', 'tile_rect': d['tile_rect']})
    for it in items:
        if it['type'] == 'frame':
            it['video_endpoints'] = [f for f in video_samples if f['id'] == it['id']]
    states = _state_samples(runtime, links)
    for it in items:
        if it['id'] == f'STATE:T{take}':
            it['state_lines'] = states
    anchor_set = set(anchors)
    result = {'take': take, 'items': items, 'action_links': links,
              'sheets': sorted({f'{dname}/{d["sheet"]}' for d in delivered}),
              'event_sheets': sorted({f'{dname}/{d["sheet"]}' for d in delivered if d['id'] in anchor_set},
                                     key=lambda x: (not x.split('/')[-1].startswith('grid_'), x)),
              'event_anchor_frames': len(anchors),
              'frames_recorded': len(frames), 'frames_delivered': len(delivered)}
    write_json(cached, result)
    return result


def _ingame_shot_items(out: Path, have: set) -> list[dict]:
    """Stage3: the asset photographed INSIDE the running game at the end of the latest normal take (UE / Unity
    recorder asset shots) as VIEW:<asset>, and the original file's reference render as SRCVIEW:<asset>, for
    assets without an empty-scene VIEW (e.g. UE). Real recorder captures only; 4 views on one 2x2 sheet."""
    try:
        from ..stage3 import texture_ingame
    except ImportError:
        return []
    shots_dir = texture_ingame.latest_shots(out)
    crit = out / 'input' / 'criteria.json'
    if shots_dir is None or not crit.is_file():
        return []
    checks = {}
    for r in read_json(crit)['criteria']:
        if r.get('asset_id') and r['metric'] in ('import', 'texture'):
            checks.setdefault(r['asset_id'], []).append(r['id'])
    folder = out / 'evidence_views'
    folder.mkdir(exist_ok=True)
    originals = OUTPUTS / 'eval' / 'refine' / '_reference_renderer' / 'originals' / read_json(out / 'manifest.json')['game_id']
    orig = read_json(originals / 'originals.json')['assets'] if (originals / 'originals.json').is_file() else {}
    items = []
    for s in read_json(shots_dir / 'asset_shots.json')['assets']:
        a = s['id']
        files = [shots_dir / f['file'] for f in s.get('files', []) if f.get('ok')]
        if a in have or a not in checks or s.get('error') or len(files) < 4:
            continue
        sheet = texture_ingame._sheet(files[:4], folder / f'{a}__ingame.png', f'VIEW:{a} in-game ({s.get("view_mode", "game")})')
        items.append({'id': f'VIEW:{a}', 'path': str(sheet), 'type': 'image', 'sha256': sha256(sheet), 'lines': 0,
                      'check_ids': checks[a], 'artifact': str(shots_dir), 'loader': 'in-game recorder shot ('
                      + str(s.get('view_mode', 'game')) + ' view)'})
        o = orig.get(a) or {}
        if o.get('ok') and Path(o['sheet']).is_file():
            items.append({'id': f'SRCVIEW:{a}', 'path': o['sheet'], 'type': 'image', 'sha256': sha256(Path(o['sheet'])),
                          'lines': 0, 'check_ids': checks[a]})
    return items


def motion_gameplay_items(runtime: Path, take: int, frames: list[dict], events: list[dict]) -> list[dict]:
    """Associate natural gameplay frames with an observed motion interval; never pose or re-render a model.

    Only frames at/after start and strictly before an observed end, interruption, or the owner's next
    start qualify. The first interval with at least two distinct frame times is shown, up to five seconds.
    A dark, distant or occluded character stays that way: association is not proof of visual correctness.
    """
    from PIL import Image, ImageDraw
    all_motion = sorted((r for r in _jsonl(runtime / 'asset_events.jsonl') if r.get('kind') == 'motion'),
                        key=lambda r: float(r.get('t_ms', 0)))
    frames = sorted((f for f in frames if f['path'].is_file()), key=lambda f: f['t_ms'])
    items = []
    for channel in events:
        asset = channel['id'].rsplit(':', 1)[-1]
        starts = [r for r in _jsonl(Path(channel['path']))
                  if r.get('kind') == 'motion' and r.get('event') == 'start']
        for start in starts:
            begin = float(start['t_ms'])
            end = begin + 5000.0
            for r in all_motion:
                if (float(r.get('t_ms', 0)) > begin and r.get('owner') == start.get('owner')
                        and r.get('event') in ('end', 'interrupted', 'start')):
                    end = min(end, float(r['t_ms']))
                    break
            candidates = [f for f in frames if begin <= f['t_ms'] < end]
            # A retry/event frame may share a timestamp; it does not supply another pose in time.
            distinct = {f['t_ms']: f for f in candidates}
            candidates = list(distinct.values())
            if len(candidates) < 2:
                continue
            count = min(12, len(candidates))
            selected = [candidates[round(i * (len(candidates) - 1) / (count - 1))] for i in range(count)]
            ident = f'MOTION:T{take}:{asset}'
            folder = runtime / 'motion_gameplay'
            folder.mkdir(exist_ok=True)
            dest = folder / f'{asset}.png'
            with Image.open(selected[0]['path']) as first:
                width, height = first.size
            cols, cap = 2, 40
            sheet = Image.new('RGB', (cols * width, ((count + cols - 1) // cols) * (height + cap)))
            draw = ImageDraw.Draw(sheet)
            provenance = []
            for i, f in enumerate(selected):
                x, y = (i % cols) * width, (i // cols) * (height + cap)
                with Image.open(f['path']) as im:
                    if im.size != (width, height):
                        raise ValueError(f'{ident}: native frame dimensions changed during playback')
                    sheet.paste(im.convert('RGB'), (x, y + cap))
                draw.text((x + 6, y + 3), f'{ident} | native gameplay', fill='white')
                draw.text((x + 6, y + 20), f'{f["id"]} | t={f["t_ms"]:.1f} ms', fill='white')
                provenance.append({'id': f['id'], 't_ms': f['t_ms'], 'path': str(f['path']),
                                   'sha256': sha256(f['path']), 'tile_rect': [x, y + cap, width, height]})
            sheet.save(dest)
            with Image.open(dest) as saved:
                for f in provenance:
                    x, y, w, h = f['tile_rect']
                    with Image.open(f['path']) as original:
                        if saved.crop((x, y, x + w, y + h)).tobytes() != original.convert('RGB').tobytes():
                            raise RuntimeError(f'{ident}: tile {f["id"]} differs from its native frame')
            item = {'id': ident, 'path': str(dest), 'type': 'image', 'sha256': sha256(dest), 'lines': 0,
                    'check_ids': channel['check_ids'], 'artifact': str(runtime / 'asset_events.jsonl'),
                    'recording_origin': 'native_gameplay', 'native_pixels_verified': True,
                    'asset_event_id': channel['id'],
                    'owner': start.get('owner', ''), 'playback_window_ms': [begin, end], 'frames': provenance,
                    'loader': 'Unmodified native gameplay frames during observed motion playback; '
                              'no animation override, clip sampling, model copy, extra light or camera. '
                              'Timing association alone does not prove the character is visible or undistorted.'}
            write_json(folder / f'{asset}.json', item)
            items.append(item)
            break
    return items


def _view_items(out: Path) -> list[dict]:
    path = out / 'asset_views' / 'asset_views.json'
    items = []
    # Recorder asset shots exist without the optional empty-scene asset_views pass.
    # Motion evidence is take-specific and comes exclusively from native gameplay frames.
    views = read_json(path)['assets'] if path.is_file() else {}
    for asset_id, a in sorted(views.items()):
        if a.get('ok') and a.get('sheet'):
            items.append({'id': f'VIEW:{asset_id}', 'path': a['sheet']['path'], 'type': 'image',
                          'sha256': a['sheet']['sha256'], 'lines': 0, 'check_ids': a.get('check_ids', []),
                          'artifact': a.get('path'), 'loader': a.get('loader')})
    items += _ingame_shot_items(out, {i['id'][5:] for i in items})
    src = out / 'asset_views' / 'source' / 'source_views.json'
    for asset_id, a in sorted(read_json(src)['assets'].items()) if src.is_file() else []:
        if a.get('ok') and a.get('sheet'):        # render of the original asset file (texture baseline)
            items.append({'id': f'SRCVIEW:{asset_id}', 'path': a['sheet']['path'], 'type': 'image',
                          'sha256': a['sheet']['sha256'], 'lines': 0,
                          'check_ids': (views.get(asset_id) or {}).get('check_ids', [])})
    return items


def build(out: Path, takes: list[int]) -> dict:
    """Union evidence of the static items, the asset views and every recorded take so far."""
    out = Path(out)
    name = f'evidence_t{max(takes)}.json'
    if (out / name).is_file():
        return read_json(out / name)
    parts = [_take_evidence(out, k) for k in takes]
    manifest = {'version': VERSION, 'takes': list(takes),
                'items': _static_items(out) + _view_items(out) + [it for p in parts for it in p['items']],
                'action_links': [l for p in parts for l in p['action_links']],
                'sheets': [s for p in parts for s in p['sheets']],
                'event_sheets': [s for p in parts for s in p.get('event_sheets', [])],
                'frames_recorded': sum(p['frames_recorded'] for p in parts),
                'frames_delivered': sum(p['frames_delivered'] for p in parts)}
    write_json(out / name, manifest)
    return manifest
