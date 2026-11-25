"""Texture = imported 3D assets as they appear in the real game vs the original asset (stage3).

Per required 3D object / scene that import_presence found (N assets):
  A_i = 1 if the asset is placed in the running game scene (in-game Game View shot), else 0
        (imported but not placed -> spawned copy, Neutral View; not loadable -> error).
  F_i = 1 if the shot (Game View, or Neutral View for a spawned copy) keeps the original asset's
        textures / colours / material / shape, judged against ORIG:<asset> (the original file rendered
        with a fixed reference loader: Unity + glTFast, neutral rig, same four angles). An asset that
        cannot be loaded or shot gets F_i = 0.
  S_texture = 100 * mean F_i over assets with a valid visual judgement (N_valid); reported beside it:
  availability = 100 * mean A_i over all N, coverage = 100 * N_valid / N, and F by view type.

In-game shots come from the latest take that has them (UE: <take>/record/native/take/asset_shots).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from ..stage1 import asset_views
from ..whitebox.llm import call_model
from ..whitebox.paths import OUTPUTS, read_json, sha256, write_json

VERSION = 'stage3-texture-ingame.v1'
REFERENCE = OUTPUTS / 'eval' / 'refine' / '_reference_renderer'
from engine_adapters.unity3d.editor_paths import resolve_editor
PROMPT = '''For each ASSET you get two images, each a 2x2 sheet of four views (front, right, back, three-quarter top):
ORIG:<asset> is the ORIGINAL asset file rendered with a neutral light rig; SHOT:<asset> is the same asset
photographed INSIDE the delivered game ({modes}). Decide only F: does the in-game asset keep the original's
surface - same textures, colour regions, material look and overall shape? F=false if the game shows it
untextured / plain white or grey / default or pink material where the original is textured, with wrong
textures, broken UVs, missing parts, or as a different-looking asset. Ignore background, framing, scale and
the game's lighting mood, as long as colours and textures can still be told apart. For a SCENE asset the
in-game shot covers only the part of the scene around the player: compare that part with the matching part
of the original (its surfaces, colours and textures), not the whole layout. Images in order: {order}.
Return only the schema.'''


def blank(path: Path) -> bool:
    """A shot with (almost) no pixel variation carries no picture - a capture failure, not the asset's look."""
    from PIL import Image, ImageStat
    with Image.open(path) as im:
        return ImageStat.Stat(im.convert('L')).stddev[0] < 1.0


def apply_blank_rule(out: Path) -> dict:
    """Re-apply the blank-shot rule to an existing texture_ingame.json (no model call): assets whose in-game
    shots are all blank become not evaluable instead of F=0. Earlier version kept as texture_ingame.before_blank.json."""
    out = Path(out)
    result = read_json(out / 'texture_ingame.json')
    shots_dir = Path(result['shots']) if result.get('shots') else latest_shots(out)
    shots = {x['id']: x for x in read_json(shots_dir / 'asset_shots.json')['assets']}
    changed = []
    for a, row in result['assets'].items():
        files = [shots_dir / f['file'] for f in shots.get(a, {}).get('files', []) if f.get('ok')]
        if row.get('F') is not None and len(files) >= 4 and all(f.is_file() for f in files) and all(blank(f) for f in files):
            row.update(F=None, judged_F_before_blank_rule=row['F'],
                       basis='not evaluable: every in-game shot is a blank image (capture produced no picture)')
            changed.append(a)
    if changed:
        shutil.copy2(out / 'texture_ingame.json', out / 'texture_ingame.before_blank.json')
        result = aggregate(result)
        result['blank_rule_applied'] = changed
        write_json(out / 'texture_ingame.json', result)
    return result


def latest_shots(out: Path) -> Path | None:
    def take_no(p):            # .../takes/<n>/record/native/.../asset_shots/asset_shots.json (UE and Unity)
        parts = p.relative_to(out).parts
        return int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else -1
    def normal(p):             # a state-conditioned take is not the game as delivered: skip its shots
        plan_file = out / 'takes' / str(take_no(p)) / 'plan.json'
        return not (plan_file.is_file() and 'state_entry' in plan_file.read_text(errors='replace'))
    found = sorted((p for p in out.glob('takes/*/record/native/**/asset_shots/asset_shots.json') if normal(p)),
                   key=take_no)
    return found[-1].parent if found else None


def _sheet(files: list[Path], dest: Path, label: str) -> Path:
    from PIL import Image, ImageDraw
    ims = [Image.open(f).convert('RGB') for f in files]
    w, h = ims[0].size
    cap = 24
    sheet = Image.new('RGB', (2 * w, 2 * (h + cap)), (0, 0, 0))
    d = ImageDraw.Draw(sheet)
    for k, (f, im) in enumerate(zip(files, ims)):
        x, y = (k % 2) * w, (k // 2) * (h + cap)
        d.text((x + 6, y + 5), f'{label} | {f.stem.split("__")[-1]}', fill=(255, 255, 255))
        sheet.paste(im, (x, y + cap))
    sheet.save(dest)
    return dest


def render_originals(game_id: str, asset_ids: list[str], folder: Path) -> dict:
    """Original asset files rendered once with the reference renderer (cached per game)."""
    folder.mkdir(parents=True, exist_ok=True)
    cache = folder / 'originals.json'
    if cache.is_file():
        return read_json(cache)
    project = REFERENCE / 'project'
    jobs, chosen = [], {}
    for a in asset_ids:
        files = [f for f in asset_views.source_files(game_id, a) if f.suffix.lower() in ('.glb', '.gltf')]
        if files:
            chosen[a] = {'path': str(files[0]), 'sha256': sha256(files[0])}
            jobs.append({'id': a, 'path': str(files[0]), 'runtime_gltf': True})
    raw = folder / 'raw'
    raw.mkdir(exist_ok=True)
    result = {'reference_project': str(project), 'sources': chosen, 'assets': {}}
    if jobs:
        unity = str(resolve_editor(family='tuanjie'))
        script_dir = project / asset_views.UNITY_SCRIPT_DIR
        script_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(asset_views.HERE / 'GameFactory3AAssetViews.cs', script_dir / 'GameFactory3AAssetViews.cs')
        job = folder / 'unity_job.json'
        write_json(job, {'output_dir': str(raw.resolve()), 'size': 640, 'jobs': jobs})
        from ..whitebox.record import engine_lock   # A3GAME_EXCLUSIVE_ENGINE: one engine process on the machine
        try:
            with engine_lock():
                subprocess.run([unity, '-batchmode', '-projectPath', str(project), '-executeMethod',
                                'GameFactory3AAssetViews.Run', '-gf3aViewsJob', str(job.resolve()),
                                '-logFile', str((folder / 'unity.log').resolve())], capture_output=True, timeout=1800)
        finally:
            shutil.rmtree(script_dir, ignore_errors=True)
            script_dir.with_name(script_dir.name + '.meta').unlink(missing_ok=True)
        report = raw / 'unity_asset_views.json'
        for r in (read_json(report)['results'] if report.is_file() else []):
            if r.get('ok'):
                files = [raw / v['file'] for v in r['views']]
                result['assets'][r['id']] = {'ok': True, 'sheet': str(_sheet(files, folder / f'{r["id"]}.png', f'ORIG:{r["id"]}'))}
            else:
                result['assets'][r['id']] = {'ok': False, 'error': r.get('error')}
    write_json(cache, result)
    return result


def evaluate(out: Path, model: str) -> dict:
    out = Path(out).resolve()
    from . import import_presence
    pres = import_presence.evaluate(out)
    game = pres['game_id']
    three_d = [a for a, v in pres['assets'].items() if v['kind'] in ('3d_object', '3d_scene') and v['present']]
    shots_dir = latest_shots(out)
    shots = {x['id']: x for x in read_json(shots_dir / 'asset_shots.json')['assets']} if shots_dir else {}
    folder = out / 'texture_ingame'
    folder.mkdir(exist_ok=True)
    orig = render_originals(game, three_d, OUTPUTS / 'eval' / 'refine' / '_reference_renderer' / 'originals' / game)
    rows, pairs, images, order, modes = {}, [], [], [], set()
    for a in three_d:
        s = shots.get(a)
        files = [shots_dir / f['file'] for f in (s or {}).get('files', []) if f.get('ok')] if s else []
        if s and not s.get('error') and len(files) >= 4 and all(blank(f) for f in files):
            rows[a] = {'A': 1 if s.get('view_mode', 'game') == 'game' else 0, 'F': None,
                       'view_mode': s.get('view_mode', 'game'),
                       'basis': 'not evaluable: every in-game shot is a blank image (capture produced no picture)'}
            continue
        if not s or s.get('error') or len(files) < 4:
            rows[a] = {'A': 0, 'F': None, 'view_mode': None,
                       'basis': 'not evaluable (not shot / not loadable): ' + str((s or {}).get('error', 'no in-game shot'))}
            continue
        mode = s.get('view_mode', 'game')
        stream = s.get('streaming') or {}
        if stream and stream.get('fully_streamed') is False:
            # Shot while textures were still at a low mip (UE recorder waits up to stream_seconds): the picture
            # cannot show the real texture, so it is not evaluable - never a wrong-texture verdict.
            rows[a] = {'A': 1 if mode == 'game' else 0, 'F': None, 'view_mode': mode, 'streaming': stream,
                       'basis': f'not evaluable: textures not fully streamed in at capture '
                                f'({stream.get("textures_fully_streamed")}/{stream.get("textures")} textures)'}
            continue
        rows[a] = {'A': 1 if mode == 'game' else 0, 'view_mode': mode,   # A: placed in the running scene 'placed_components': s.get('placed_components'),
                   'hidden_at_capture_unhidden_for_shot': bool(s.get('hidden_at_capture_unhidden_for_shot')),
                   **({'streaming': stream} if stream else {})}
        if not (orig['assets'].get(a) or {}).get('ok'):
            rows[a].update(F=None, basis='original could not be rendered by the reference loader')
            continue
        shot_sheet = _sheet(files, folder / f'{a}__shot.png', f'SHOT:{a} ({mode})')
        pairs.append(a)
        images += [orig['assets'][a]['sheet'], str(shot_sheet)]
        order += [f'ORIG:{a}', f'SHOT:{a}']
        modes.add('game lighting' if mode == 'game' else 'neutral unlit copy')
    if pairs:
        item = {'type': 'object', 'additionalProperties': False, 'required': ['F', 'reason'],
                'properties': {'F': {'type': 'boolean'}, 'reason': {'type': 'string'}}}
        schema = {'type': 'object', 'additionalProperties': False, 'required': pairs,
                  'properties': {a: item for a in pairs}}
        reply = call_model(out / 'model_calls', name='texture_ingame_v2',
                           prompt=PROMPT.format(modes=' / '.join(sorted(modes)), order=', '.join(order)),
                           schema=schema, cwd=out / 'input', images=images, model=model, timeout=1800)
        for a in pairs:
            rows[a].update(F=1 if reply[a]['F'] else 0, reason=reply[a]['reason'])
    result = aggregate({'version': VERSION, 'game_id': game, 'judge': model,
                        'shots': str(shots_dir) if shots_dir else None, 'assets': rows,
                        'at': time.strftime('%Y-%m-%dT%H:%M:%S')})
    write_json(out / 'texture_ingame.json', result)
    return result


def aggregate(result: dict) -> dict:
    """Texture = mean F over assets with a valid visual judgement (no +A, no /2).
    Availability = share of the required 3D assets placed in the game; Coverage = share judged."""
    rows = result['assets']
    n = len(rows)
    valid = [r for r in rows.values() if r.get('F') is not None]
    by_view = {}
    for r in valid:
        by_view.setdefault(r.get('view_mode') or 'unknown', []).append(r['F'])
    result.update(
        N=n, N_valid=len(valid),
        S=round(100 * sum(r['F'] for r in valid) / len(valid), 2) if valid else None,
        availability=round(100 * sum(r['A'] for r in rows.values()) / n, 2) if n else None,
        coverage=round(100 * len(valid) / n, 2) if n else None,
        F_by_view={k: {'n': len(v), 'S': round(100 * sum(v) / len(v), 2)} for k, v in by_view.items()},
        not_evaluable=[a for a, r in rows.items() if r.get('F') is None],
        formula='S_texture = 100 * mean F over valid assets; availability and coverage reported separately')
    for k in ('mean_F', 'mean_A', 'not_measurable'):
        result.pop(k, None)
    return result


def rescore(out: Path) -> dict:
    """Recompute the aggregates of an existing texture_ingame.json (no model call)."""
    f = Path(out) / 'texture_ingame.json'
    result = aggregate(read_json(f))
    write_json(f, result)
    return result
