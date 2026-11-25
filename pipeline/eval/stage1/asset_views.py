"""In-engine multi-view renders of imported assets (import / texture evidence).

For every asset check (rows carrying ``asset_id``; 3d_object / 3d_scene), the imported
artifact is located in the eval working copy ``runtime/project`` by the asset id, rendered
in the engine's editor from four fixed angles in an empty preview scene with neutral
lighting, and the four native-pixel renders are tiled 2x2 (captioned) into
``asset_views/<asset_id>.png``. The judge sees it as ``VIEW:<asset_id>`` (line 0).

The delivered project is never modified: the render script is added to the working
copy for the call and removed afterwards (its addition is recorded). A missing artifact
or failed render is recorded in ``asset_views.json`` and is a harness gap, not a product
fault; the check then relies on gameplay frames.
"""
from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

from .paths import DATA_ROOT, read_json, sha256, write_json

VERSION = 'stage1-asset-views.v1'
HERE = Path(__file__).resolve().parent / 'asset_views_engine'
VIEW_KINDS = ('3d_object', '3d_scene')
UNITY_SUFFIXES = ('.prefab', '.fbx', '.glb', '.gltf', '.obj', '.blend')      # preference order
UNITY_SKIP = {'Library', 'Temp', 'obj', 'Logs', 'UserSettings', 'Packages'}
UNITY_SCRIPT_DIR = Path('Assets') / 'Editor' / 'GameFactory3AAssetViewsEval'
TILE = 640


def targets(rows: list[dict]) -> dict:
    """asset_id -> check ids that use its views."""
    out: dict[str, list[str]] = {}
    for r in rows:
        if r.get('asset_id') and r.get('asset_kind') in VIEW_KINDS:
            out.setdefault(r['asset_id'], []).append(r['id'])
    return out


def _referenced(project: Path, rel: str, code: str) -> bool:
    """Used by the game: its Resources path appears in authored code, or its GUID in a scene/prefab."""
    parts = Path(rel).with_suffix('').parts
    if 'Resources' in parts:
        key = '/'.join(parts[parts.index('Resources') + 1:])
        if f'"{key}"' in code or f'/{Path(key).name}"' in code or f'"{Path(key).name}"' in code:
            return True
    meta = project / (rel + '.meta')
    if meta.is_file():
        guid = next((l.split(':', 1)[1].strip() for l in meta.read_text(errors='replace').splitlines()
                     if l.startswith('guid:')), None)
        if guid and guid in code:
            return True
    return False


def locate_unity(project: Path, asset_id: str) -> list[str]:
    """Candidates by asset id; the artifact the game actually uses comes first."""
    hits = []
    assets = project / 'Assets'
    for p in assets.rglob(f'{asset_id}.*'):
        rel = p.relative_to(project)
        if p.is_file() and p.suffix.lower() in UNITY_SUFFIXES and not set(rel.parts) & UNITY_SKIP:
            hits.append(rel.as_posix())
    if not hits:
        return []
    code = '\n'.join(f.read_text(errors='replace') for f in assets.rglob('*')
                     if f.is_file() and f.suffix in ('.cs', '.unity', '.prefab')
                     and 'GameFactory3A' not in f.as_posix() and f.stat().st_size < 8_000_000
                     and f.stem != asset_id)
    used = {h: _referenced(project, h, code) for h in hits}
    return sorted(hits, key=lambda h: (not used[h], UNITY_SUFFIXES.index(Path(h).suffix.lower()), len(h), h))


def _tile(out_dir: Path, asset_id: str, views: list[dict], prefix: str = 'VIEW') -> dict:
    from PIL import Image, ImageDraw
    images = [Image.open(out_dir / 'raw' / v['file']).convert('RGB') for v in views]
    w, h = max(i.width for i in images), max(i.height for i in images)
    cap = 28
    sheet = Image.new('RGB', (2 * w, 2 * (h + cap)), (0, 0, 0))
    draw = ImageDraw.Draw(sheet)
    rects = []
    for k, (v, img) in enumerate(zip(views, images)):
        x, y = (k % 2) * w, (k // 2) * (h + cap)
        draw.text((x + 8, y + 6), f'{prefix}:{asset_id} | {v["name"]} (yaw {v["yaw"]:g}, pitch {v["pitch"]:g})',
                  fill=(255, 255, 255))
        sheet.paste(img, (x, y + cap))
        rects.append({'view': v['name'], 'rect': [x, y + cap, img.width, img.height],
                      'raw_sha256': sha256(out_dir / 'raw' / v['file'])})
    path = out_dir / f'{asset_id}.png'
    sheet.save(path)
    # Tiles are native pixels: verify byte-for-byte against the raw renders.
    check = Image.open(path).convert('RGB')
    for (v, img), r in zip(zip(views, images), rects):
        x, y, iw, ih = r['rect']
        if check.crop((x, y, x + iw, y + ih)).tobytes() != img.tobytes():
            raise RuntimeError(f'{asset_id}: tiled view {v["name"]} differs from its raw render')
    return {'path': str(path), 'sha256': sha256(path), 'tiles': rects}


SOURCE_ASSETS = DATA_ROOT / 'outputs' / 'game_refine' / 'hf_sol_repair10_20261102'
MODEL_SUFFIXES = ('.fbx', '.glb', '.gltf', '.obj', '.blend')


def source_index(game_id: str, asset_ids) -> dict:
    """sha256 -> asset_id of the original asset files every model imported from."""
    index, game = {}, SOURCE_ASSETS / game_id
    for a in asset_ids:
        for base in (game / 'extracted' / a, *game.glob(f'snapshot/outputs/{game_id}/assets/*/{a}')):
            if base.is_dir():
                for p in base.rglob('*'):
                    if p.is_file() and p.suffix.lower() in MODEL_SUFFIXES and '.cache' not in p.parts:
                        index.setdefault(sha256(p), a)
    return index


def content_index(projects: list[Path], asset_ids, game_id: str | None = None) -> dict:
    """sha256 -> asset_id, from the original source assets and from files named by asset id in any
    delivery of the same case: models copied under another name are found by content."""
    index = source_index(game_id, asset_ids) if game_id else {}
    for project in projects:
        assets = Path(project) / 'Assets'
        for a in asset_ids:
            for p in assets.rglob(f'{a}.*') if assets.is_dir() else []:
                if p.is_file() and p.suffix.lower() in UNITY_SUFFIXES and p.suffix.lower() != '.prefab':
                    index.setdefault(sha256(p), a)
    return index


def locate_by_content(project: Path, index: dict) -> dict:
    found: dict[str, list[str]] = {}
    for p in (project / 'Assets').rglob('*'):
        rel = p.relative_to(project)
        if p.is_file() and p.suffix.lower() in UNITY_SUFFIXES and p.suffix.lower() != '.prefab' \
                and not set(rel.parts) & UNITY_SKIP:
            a = index.get(sha256(p))
            if a:
                found.setdefault(a, []).append(rel.as_posix())
    return found


def render_unity(out: Path, binary: str, rows: list[dict], timeout_s: float = 1800, peers=()) -> dict:
    out = Path(out).resolve()          # Unity resolves job paths from inside the project
    folder = out / 'asset_views'
    if (folder / 'asset_views.json').is_file():
        return read_json(folder / 'asset_views.json')
    project = (out / 'runtime' / 'project').resolve()
    wanted = targets(rows)
    located = {a: locate_unity(project, a) for a in wanted}
    method = {a: 'asset_id' for a, hits in located.items() if hits}
    missing = [a for a in wanted if not located[a]]
    if missing:
        index = content_index([Path(p) / 'runtime' / 'project' for p in peers] + [project], missing,
                              read_json(out / 'manifest.json')['game_id'])
        for a, hits in locate_by_content(project, index).items():
            if a in missing:
                located[a], method[a] = sorted(hits), 'content_sha256'
    # StreamingAssets is not imported by the editor: those models are loaded the way games load them (glTFast).
    jobs = [{'id': a, 'path': hits[0], 'runtime_gltf': '/StreamingAssets/' in '/' + hits[0]}
            for a, hits in located.items() if hits]
    raw = folder / 'raw'
    raw.mkdir(parents=True, exist_ok=True)
    result = {'version': VERSION, 'engine': 'unity3d', 'editor': binary, 'located': located,
              'locate_method': method, 'assets': {}}
    if jobs:
        script_dir = project / UNITY_SCRIPT_DIR
        if script_dir.exists():
            raise RuntimeError(f'{script_dir} already exists; inspect before rendering')
        script_dir.mkdir(parents=True)
        src = HERE / 'GameFactory3AAssetViews.cs'
        shutil.copy2(src, script_dir / src.name)
        result['instrumentation'] = {'added': (UNITY_SCRIPT_DIR / src.name).as_posix(), 'sha256': sha256(src),
                                     'removed_after': True}
        job = folder / 'unity_job.json'
        write_json(job, {'output_dir': str(raw), 'size': TILE, 'jobs': jobs})
        log = folder / 'unity_views.log'
        started = time.monotonic()
        from .record import engine_lock          # A3GAME_EXCLUSIVE_ENGINE: one engine process on the machine
        try:
            with engine_lock():
                proc = subprocess.run([binary, '-batchmode', '-projectPath', str(project),
                                       '-executeMethod', 'GameFactory3AAssetViews.Run', '-gf3aViewsJob', str(job),
                                       '-logFile', str(log)], capture_output=True, text=True, timeout=timeout_s)
            result['exit_code'], result['timeout'] = proc.returncode, False
        except subprocess.TimeoutExpired:
            result['exit_code'], result['timeout'] = None, True
        finally:
            shutil.rmtree(script_dir, ignore_errors=True)
            meta = script_dir.with_name(script_dir.name + '.meta')
            meta.unlink(missing_ok=True)
        result['elapsed_ms'] = round((time.monotonic() - started) * 1000)
        report_path = raw / 'unity_asset_views.json'
        report = read_json(report_path) if report_path.is_file() else {'results': []}
        result['render_pipeline'] = report.get('render_pipeline')
        result['rig'] = report.get('rig')
        for r in report['results']:
            entry = {k: r.get(k) for k in ('path', 'ok', 'error', 'asset_type', 'loader', 'renderers',
                                           'skinned_renderers', 'missing_materials', 'embedded_lights_disabled',
                                           'behaviours_disabled', 'bounds_center', 'bounds_size', 'materials')}
            if r.get('ok'):
                entry['sheet'] = _tile(folder, r['id'], r['views'])
            result['assets'][r['id']] = entry
    for a in wanted:
        if a not in result['assets']:
            result['assets'][a] = {'ok': False, 'error': 'no imported artifact found by asset id' if not located[a]
                                   else 'editor produced no render (see unity_views.log)'}
        result['assets'][a]['check_ids'] = wanted[a]
    write_json(folder / 'asset_views.json', result)
    return result


# --- original (source) asset renders: the baseline for texture -------------------------------

def source_files(game_id: str, asset_id: str) -> list[Path]:
    game = SOURCE_ASSETS / game_id
    found = []
    for base in (game / 'extracted' / asset_id, *game.glob(f'snapshot/outputs/{game_id}/assets/*/{asset_id}')):
        if base.is_dir():
            found += [p for p in base.rglob('*') if p.is_file() and p.suffix.lower() in MODEL_SUFFIXES
                      and '.cache' not in p.parts]
    return sorted(found, key=lambda p: (p.suffix.lower() != '.glb', len(str(p))))


def _has_gltfast(project: Path) -> bool:
    m = project / 'Packages' / 'manifest.json'
    return m.is_file() and 'com.unity.cloud.gltfast' in m.read_text(errors='replace')


def render_source_unity(out: Path, binary: str, timeout_s: float = 1800) -> dict:
    out = Path(out).resolve()
    """Render the ORIGINAL asset file of every asset that has a VIEW, with the same editor, rig and angles.

    The source is matched to the imported artifact by content when it is a byte copy, otherwise the
    primary model file of that asset (glb first). glTF is loaded by the project's glTFast runtime loader
    (the reference glTF loader; nothing is added to the project); other formats are copied into a
    temporary eval-only folder of the working copy, imported, rendered and removed."""
    out = Path(out)
    folder = out / 'asset_views' / 'source'
    if (folder / 'source_views.json').is_file():
        return read_json(folder / 'source_views.json')
    views = read_json(out / 'asset_views' / 'asset_views.json')
    project = (out / 'runtime' / 'project').resolve()
    game_id = read_json(out / 'manifest.json')['game_id']
    gltfast = _has_gltfast(project)
    jobs, chosen, copies = [], {}, []
    tmp = project / 'Assets' / 'GameFactory3AAssetViewsEvalSource'
    for a, v in views['assets'].items():
        files = source_files(game_id, a)
        if not files:
            chosen[a] = None
            continue
        imported = project / v['path'] if v.get('path') else None
        same = [f for f in files if imported and imported.is_file() and sha256(f) == sha256(imported)]
        f = (same or files)[0]
        chosen[a] = {'path': str(f), 'sha256': sha256(f), 'byte_identical_to_imported': bool(same)}
        if f.suffix.lower() in ('.glb', '.gltf') and gltfast:
            jobs.append({'id': a, 'path': str(f), 'runtime_gltf': True})
        else:
            tmp.mkdir(parents=True, exist_ok=True)
            dest = tmp / f'{a}{f.suffix.lower()}'
            shutil.copy2(f, dest)
            copies.append(dest)
            jobs.append({'id': a, 'path': dest.relative_to(project).as_posix(), 'runtime_gltf': False})
    raw = folder / 'raw'
    raw.mkdir(parents=True, exist_ok=True)
    result = {'version': VERSION, 'engine': 'unity3d', 'editor': binary, 'source_root': str(SOURCE_ASSETS),
              'sources': chosen, 'assets': {}}
    if jobs:
        script_dir = project / UNITY_SCRIPT_DIR
        if script_dir.exists():
            raise RuntimeError(f'{script_dir} already exists; inspect before rendering')
        script_dir.mkdir(parents=True)
        src = HERE / 'GameFactory3AAssetViews.cs'
        shutil.copy2(src, script_dir / src.name)
        job = folder / 'unity_job.json'
        write_json(job, {'output_dir': str(raw), 'size': TILE, 'jobs': jobs})
        from .record import engine_lock          # A3GAME_EXCLUSIVE_ENGINE: one engine process on the machine
        try:
            with engine_lock():
                proc = subprocess.run([binary, '-batchmode', '-projectPath', str(project),
                                       '-executeMethod', 'GameFactory3AAssetViews.Run', '-gf3aViewsJob', str(job),
                                       '-logFile', str(folder / 'unity_views.log')],
                                      capture_output=True, text=True, timeout=timeout_s)
            result['exit_code'] = proc.returncode
        except subprocess.TimeoutExpired:
            result['exit_code'] = None
        finally:
            for d in (script_dir, tmp):
                shutil.rmtree(d, ignore_errors=True)
                d.with_name(d.name + '.meta').unlink(missing_ok=True)
        report_path = raw / 'unity_asset_views.json'
        report = read_json(report_path) if report_path.is_file() else {'results': []}
        result['rig'] = report.get('rig')
        for r in report['results']:
            entry = {k: r.get(k) for k in ('ok', 'error', 'loader', 'renderers', 'missing_materials',
                                           'embedded_lights_disabled', 'materials')}
            if r.get('ok'):
                entry['sheet'] = _tile(folder, r['id'], r['views'], prefix='SRCVIEW')
            result['assets'][r['id']] = entry
    for a in views['assets']:
        result['assets'].setdefault(a, {'ok': False, 'error': 'no original asset file found' if not chosen.get(a)
                                        else 'editor produced no render'})
    write_json(folder / 'source_views.json', result)
    return result
