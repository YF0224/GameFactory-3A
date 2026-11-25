"""Small stdlib-only delivery checks. These are NOT geometry/quality scores."""
from __future__ import annotations
import json
from pathlib import Path
import struct


def glb_header(path):
    """Read just GLB header and JSON, not geometry buffers or texture pixels."""
    path = Path(path)
    size = path.stat().st_size
    with path.open('rb') as f:
        header = f.read(20)
        if len(header) < 20:
            raise ValueError('Truncated GLB header')
        magic, version, declared, json_length, kind = struct.unpack('<4sIIII', header)
        if magic != b'glTF' or version != 2 or kind != 0x4E4F534A:
            raise ValueError('Expected GLB2 with a first JSON chunk')
        if declared != size:
            raise ValueError(f'GLB declared length {declared} != file length {size}')
        if not 0 < json_length <= min(8 * 1024 * 1024, size - 20):
            raise ValueError('Invalid or over-budget GLB JSON chunk')
        raw = f.read(json_length)
        if len(raw) != json_length:
            raise ValueError('Truncated GLB JSON')
        doc = json.loads(raw)
    triangles = 0; unknown = []; accessors = doc.get('accessors', [])
    for mi, mesh in enumerate(doc.get('meshes', [])):
        for pi, primitive in enumerate(mesh.get('primitives', [])):
            if primitive.get('mode', 4) != 4:
                unknown.append(f'mesh={mi}, primitive={pi}: not triangle-list mode')
                continue
            if 'indices' in primitive:
                count = accessors[primitive['indices']]['count']
            elif 'POSITION' in primitive.get('attributes', {}):
                count = accessors[primitive['attributes']['POSITION']]['count']
            else:
                unknown.append(f'mesh={mi}, primitive={pi}: no count accessor')
                continue
            if not isinstance(count, int) or count < 0 or count % 3:
                raise ValueError('Invalid triangle-list accessor count')
            triangles += count // 3
    return {'header_ok': True, 'json_ok': True, 'file_bytes': size,
            'json_bytes_read': json_length, 'glb_version': version,
            'unique_buffer_triangles_declared': triangles if not unknown else None,
            'mesh_count_declared': len(doc.get('meshes', [])),
            'texture_count_declared': len(doc.get('textures', [])),
            'image_count_declared': len(doc.get('images', [])), 'limitations': unknown + [
                'Header/JSON preflight only: accessor declarations are not decoded geometry.',
                'Does not prove GLB loadability, topology, material decoding, texture resolution or render success.',
                'These declarations are not substituted into any quality score.']}
