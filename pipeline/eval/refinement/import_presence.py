"""Import = how many of the required assets actually got into the project (rule-based, no model).

For every asset the game's refine tasks ask to import (``game_refine/inputs/<game>/import.json``), the
delivered project snapshot (``input/project``) is searched for it:

* a file that is a byte copy of one of the asset's original files (sha256), or
* an engine asset whose recorded import source is one of those files: UE ``AssetImportData``
  (``RelativeFilename`` under the asset's own source folder, or a ``FileMD5`` equal to an original file), or
* an engine asset file named after the asset id (Unity / UE / audio / video / animation files).

Score: S = 100 * present / required, with a per-kind breakdown. Whether the imported 3D assets look
like the originals is the texture dimension (texture_binary).
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from ..whitebox.evidence.asset_views import SOURCE_ASSETS
from ..whitebox.core.paths import read_json, write_json
from .criteria import INPUTS

VERSION = 'stage3-import-presence.v1'
SKIP = {'Library', 'Temp', 'obj', 'Logs', 'Intermediate', 'DerivedDataCache', 'Saved', 'Binaries', '.godot',
        'node_modules', '.git', 'GameFactory3AEvaluation', 'GameFactory3AAssetViewsEval'}
ASSET_SUFFIXES = {'.glb', '.gltf', '.fbx', '.obj', '.blend', '.prefab', '.asset', '.anim', '.controller',
                  '.wav', '.ogg', '.mp3', '.mp4', '.webm', '.mov', '.uasset', '.umap', '.tres', '.res', '.png', '.jpg',
                  '.json', '.bytes'}   # .json/.bytes: converted clips (e.g. baked motion) named after the asset
IMPORT_DATA = re.compile(rb'"RelativeFilename"\s*:\s*"([^"]+)"\s*,\s*"Timestamp"\s*:\s*"[^"]*"\s*,\s*"FileMD5"\s*:\s*"([0-9a-f]{32})"')


def _digests(path: Path) -> tuple[str, str]:
    h1, h2 = hashlib.sha256(), hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h1.update(chunk)
            h2.update(chunk)
    return h1.hexdigest(), h2.hexdigest()


def originals(game_id: str, asset_id: str) -> list[dict]:
    game, out = SOURCE_ASSETS / game_id, []
    bases = [game / 'extracted' / asset_id, *game.glob(f'snapshot/outputs/{game_id}/assets/*/{asset_id}')]
    for base in bases:
        for p in base.rglob('*') if base.is_dir() else []:
            if p.is_file() and '.cache' not in p.parts and p.stat().st_size > 0:
                sha, md5 = _digests(p)
                out.append({'path': str(p), 'size': p.stat().st_size, 'sha256': sha, 'md5': md5})
    return out


def _project_files(project: Path):
    for p in project.rglob('*'):
        rel = p.relative_to(project)
        if p.is_file() and not set(rel.parts) & SKIP and p.suffix.lower() in ASSET_SUFFIXES:
            yield p, rel


def evaluate(out: Path) -> dict:
    out = Path(out)
    manifest = read_json(out / 'manifest.json')
    game = manifest['game_id']
    project = out / 'input' / 'project'
    tasks = read_json(INPUTS / game / 'import.json')
    required = {Path(t['asset_path']).name: t['asset_kind'] for t in tasks}
    orig = {a: originals(game, a) for a in required}
    by_size = {}
    for a, files in orig.items():
        for f in files:
            by_size.setdefault(f['size'], []).append((a, f))
    md5s = {f['md5']: a for a, files in orig.items() for f in files}
    found = {a: [] for a in required}
    for p, rel in _project_files(project):
        size = p.stat().st_size
        name = p.name
        for a in required:
            if a.lower() in name.lower() or a.lower() in rel.as_posix().lower():
                found[a].append({'path': rel.as_posix(), 'how': 'named after asset id'})
        if size in by_size:
            sha, _ = _digests(p)
            for a, f in by_size[size]:
                if f['sha256'] == sha:
                    found[a].append({'path': rel.as_posix(), 'how': 'byte copy of original', 'original': f['path']})
        if p.suffix.lower() == '.uasset':
            data = p.read_bytes()
            for src, md5 in set(IMPORT_DATA.findall(data)):
                src_s = src.decode('utf-8', 'replace')
                hit = {a for a in required if f'/{a}/' in src_s or Path(src_s).name.startswith(a)}
                if md5.decode() in md5s:
                    hit.add(md5s[md5.decode()])
                for a in hit:
                    found[a].append({'path': rel.as_posix(), 'how': 'UE import of original', 'source': src_s,
                                     'md5': md5.decode()})
    assets = {}
    for a, kind in required.items():
        strong = [f for f in found[a] if f['how'] != 'named after asset id']
        weak = [f for f in found[a] if f['how'] == 'named after asset id']
        assets[a] = {'kind': kind, 'present': bool(strong or weak), 'basis': 'original file' if strong else
                     ('asset id name' if weak else 'not found'), 'originals': len(orig[a]),
                     'evidence': (strong or weak)[:6],
                     # every engine asset tied to it (original-file match or asset-id name), for in-game photos
                     'engine_assets': sorted({f['path'] for f in strong + weak if f['path'].endswith('.uasset')}),
                     'project_files': sorted({f['path'] for f in strong + weak})}
    present = sum(v['present'] for v in assets.values())
    kinds = {}
    for v in assets.values():
        k = kinds.setdefault(v['kind'], [0, 0])
        k[0] += v['present']
        k[1] += 1
    result = {'version': VERSION, 'game_id': game, 'required': len(required), 'present': present,
              'S': round(100 * present / len(required), 2) if required else None,
              'by_kind': {k: f'{a}/{b}' for k, (a, b) in kinds.items()}, 'assets': assets}
    write_json(out / 'import_presence.json', result)
    return result
