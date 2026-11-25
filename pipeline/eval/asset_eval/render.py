"""Reuse priority_assets' renderer, without modifying its read-only source.

Only configuration is adapted: alpha framebuffer, transparent background, camera
list and screenshot alpha. Geometry loading, materials, lights, normalization,
Draco/KTX/Meshopt decoders and HTTP isolation are exactly the existing renderer.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from .common import BENCH, FRAMEWORK, dump, read, sha, tool

SOURCE = FRAMEWORK / 'pipeline/eval/priority_assets/renderer/render.mjs'
STANDARD = [('V01_front', 0, 0), ('V02_back', 180, 0), ('V03_left', 270, 0),
            ('V04_right', 90, 0), ('V05_top', 0, 89), ('V06_three_quarter', 45, 15)]
RING = [(f'R{i + 1:02d}', i * 30, 15) for i in range(12)]


def configured_renderer(folder, scope='obj'):
    if scope not in ('obj', 'scene'):
        raise ValueError('scope must be obj or scene')
    folder.mkdir(parents=True, exist_ok=True)
    text = SOURCE.read_text()
    replacements = [
        ("const here = path.dirname(fileURLToPath(import.meta.url));", f'const here = {json.dumps(str(SOURCE.parent))};'),
        ('{antialias:true, preserveDrawingBuffer:true}', '{antialias:true, preserveDrawingBuffer:true, alpha:true}'),
        ("scene.background=new THREE.Color('#c4cad1');", 'scene.background=null;'),
        ("const views=presetArg==='scene'?sceneViews:objectViews;", 'const views=' + json.dumps(STANDARD + RING) + ';'),
        ("const object=gltf.scene; object.updateMatrixWorld(true);", "const object=gltf.scene; if(" + json.dumps(scope) + "==='scene')object.traverse(o=>{if(o.isLight)o.intensity=0;}); object.updateMatrixWorld(true);"),
        ('await page.screenshot({path:path.join(out,filename)});', 'await page.screenshot({path:path.join(out,filename),omitBackground:true});'),
        ("background:'#c4cad1'", "background:'transparent RGBA'")]
    for old, new in replacements:
        if text.count(old) != 1:
            raise RuntimeError('Read-only renderer changed; refusing an unverified adapter: ' + old)
        text = text.replace(old, new)
    dest = folder / 'render.mjs'
    dest.write_text(text)
    dump(folder / 'provenance.json', {'source_path': str(SOURCE), 'source_sha256': sha(SOURCE),
         'adapter_sha256': sha(dest), 'configuration_replacements': [{'old': a, 'new': b} for a, b in replacements],
         'policy': 'No edits to priority_assets. Reuse native loader/material/normalization; for scene scope disable embedded GLB lights so lighting is standardized by evaluator hemisphere/directional lights; object scope preserves prior behavior.'})
    return dest


def render_glb(asset, out, adapter, playwright_root=None, browser=None, *, scope="obj"):
    if scope not in ("obj", "scene"):
        raise ValueError("scope must be obj or scene")
    from .resources import assert_metrics_idle
    assert_metrics_idle()
    pw = playwright_root or BENCH / '.tools/playwright-root'
    tool(['node', adapter, asset, out, pw, browser or '', scope], timeout=300)
    info = read(out / 'render.json')
    from PIL import Image, ImageDraw
    mapping = []
    for v in info['views']:
        p = out / v['filename']
        im = Image.open(p).convert('RGBA')
        alpha = im.getchannel('A')
        if alpha.getextrema() != (0, 255):
            raise ValueError(f'Not a nonempty transparent foreground: {p}, alpha={alpha.getextrema()}')
        v['path'] = str(p.resolve()); v['sha256'] = sha(p)
        if v['id'].startswith('V'):
            # Labels are only for sol. Pixel metrics use the untouched RGBA image.
            rgb = Image.new('RGBA', im.size, '#c4cad1'); rgb.alpha_composite(im)
            labelled = Image.new('RGB', (im.width, im.height + 36), '#20242a')
            labelled.paste(rgb.convert('RGB'), (0, 36))
            ImageDraw.Draw(labelled).text((12, 10), f"{v['id']} | azimuth={v['azimuth_deg']} elev={v['elevation_deg']}", fill='white')
            lp = out / (v['id'] + '_labelled.png'); labelled.save(lp)
            v['judge_path'] = str(lp.resolve())
        mapping.append(v)
    info['views'] = mapping
    dump(out / 'manifest.json', info)
    return info


def standard_views(info, scope="obj"):
    """Six standard scoring views for both object and scene."""
    return [v for v in info["views"] if v["id"].startswith("V")]


def ring_views(info):
    return [v for v in info["views"] if v["id"].startswith("R")]
