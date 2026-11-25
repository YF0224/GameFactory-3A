"""Original GLB material inventory and real Three.js reference rendering."""
from __future__ import annotations
import json
from pathlib import Path
import struct
import subprocess
from .common import dump, read, sha


def inspect_glb(path):
    data = Path(path).read_bytes()
    if len(data) < 20:
        raise ValueError('Truncated GLB')
    magic, version, length = struct.unpack_from('<4sII', data)
    if magic != b'glTF' or version != 2 or length != len(data):
        raise ValueError('Invalid GLB v2 header/length')
    position, document, binary_size = 12, None, 0
    while position < length:
        size, kind = struct.unpack_from('<II', data, position)
        position += 8
        if size % 4 or position + size > length:
            raise ValueError('Invalid GLB chunk')
        if kind == 0x4E4F534A:
            if document is not None:
                raise ValueError('Multiple GLB JSON chunks')
            document = json.loads(data[position:position + size])
        elif kind == 0x004E4942:
            binary_size += size
        position += size
    if position != length or document is None:
        raise ValueError('Missing GLB JSON')
    # Self-contained source references only; never silently omit external textures.
    for item in document.get('buffers', []) + document.get('images', []):
        if item.get('uri') and not item['uri'].startswith('data:'):
            raise ValueError('External GLB dependency: explicitly package a self-contained GLB: ' + item['uri'])
    for image in document.get('images', []):
        if 'bufferView' in image:
            view = document['bufferViews'][image['bufferView']]
            if view.get('byteOffset', 0) + view['byteLength'] > binary_size:
                raise ValueError('Image bufferView exceeds embedded binary')
    return {'source_sha256': sha(path), 'asset': document.get('asset'),
            'materials': document.get('materials', []), 'images': document.get('images', []),
            'textures': document.get('textures', []), 'skins': document.get('skins', []),
            'mesh_count': len(document.get('meshes', [])),
            'animation_count': len(document.get('animations', [])),
            'extensions_used': document.get('extensionsUsed', []),
            'note': 'Inventory is not a successful decode/import. Native Three.js render must also pass.'}


def render(path, output, config, *, scene=False):
    path, output = Path(path), Path(output)
    inventory = inspect_glb(path)
    framework = Path(__file__).resolve().parents[3]
    renderer = framework / 'pipeline/game_eval/priority_assets/renderer/render.mjs'
    settings = config.get('renderer', {})
    playwright = settings.get('playwright_root')
    if not playwright:
        raise ValueError('renderer.playwright_root required (directory containing node_modules/playwright)')
    output.mkdir(parents=True, exist_ok=False)
    dump(output / 'source.json', inventory)
    command = [settings.get('node', 'node'), str(renderer), str(path), str(output),
               str(playwright), (settings.get('browser') or ''), 'scene' if scene else 'object']
    run = subprocess.run(command, capture_output=True, text=True, timeout=settings.get('timeout_seconds', 180))
    (output / 'stdout.log').write_text(run.stdout)
    (output / 'stderr.log').write_text(run.stderr)
    if run.returncode:
        raise RuntimeError(f'Original GLB render failed ({run.returncode}); see {output}/stderr.log')
    facts = read(output / 'render.json')
    views = [{'path': str(output / row['filename']), 'sha256': sha(output / row['filename']),
              'view': row['id']} for row in facts['views']]
    binding = {'source_path': str(path), 'source_sha256': inventory['source_sha256'],
               'renderer_sha256': sha(renderer),
               'renderer_lock_sha256': sha(renderer.parent / 'package-lock.json'),
               'render_manifest_sha256': sha(output / 'render.json'), 'views': views,
               'comparison_policy': 'Compare original authored appearance; white source is not automatically missing texture. '
               'Camera/lighting differences alone are not deformation or texture failure.'}
    dump(output / 'binding.json', binding)
    return binding
