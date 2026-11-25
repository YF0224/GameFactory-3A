from __future__ import annotations
import io
import json
import struct
from pathlib import Path
import numpy as np
from PIL import Image
from .common import finite
from .resources import MetricsDeferred
from .image_consistency import rgb_composite

from .constants import GEOMETRY_FORMULA, QUALITY_FORMULA


def glb_texture_sizes(path):
    data = Path(path).read_bytes()
    if data[:4] != b'glTF' or struct.unpack_from('<I', data, 4)[0] != 2:
        raise ValueError('Not a GLB v2')
    offset = 12; document = None; binary = None
    while offset + 8 <= len(data):
        length, kind = struct.unpack_from('<II', data, offset); offset += 8
        chunk = data[offset:offset + length]; offset += length
        if kind == 0x4E4F534A:
            document = json.loads(chunk)
        elif kind == 0x004E4942:
            binary = chunk
    if document is None:
        raise ValueError('GLB JSON missing')
    sizes = []; errors = []
    # Count images referenced by textures, not unused embedded thumbnails.
    ids = set()
    for texture in document.get('textures', []):
        source = texture.get('source', texture.get('extensions', {}).get('KHR_texture_basisu', {}).get('source'))
        if source is not None:
            ids.add(source)
    for i in sorted(ids):
        try:
            im = document['images'][i]
            if 'bufferView' in im:
                view = document['bufferViews'][im['bufferView']]
                if view.get('buffer', 0) != 0 or binary is None:
                    raise ValueError('external GLB buffer unsupported')
                start = view.get('byteOffset', 0); raw = binary[start:start + view['byteLength']]
            else:
                uri = im['uri']
                if uri.startswith('data:'):
                    import base64
                    raw = base64.b64decode(uri.split(',', 1)[1])
                else:
                    p = (Path(path).parent / uri).resolve()
                    if not p.is_relative_to(Path(path).parent.resolve()):
                        raise ValueError('external texture path escapes delivery')
                    raw = p.read_bytes()
            with Image.open(io.BytesIO(raw)) as image:
                sizes.append({'image_index': i, 'width': image.width, 'height': image.height})
        except Exception as e:
            errors.append(f'image {i}: {type(e).__name__}: {e}')
    return sizes, errors


def geometry_quality(path, task):
    from .resources import assert_metrics_idle
    assert_metrics_idle()
    import trimesh
    notes = []; raw = {'load_ok': False, 'degenerate_face_ratio': None, 'nonmanifold_edge_ratio': None,
                       'triangles': None, 'triangle_target': task.get('decimation_target'),
                       'triangle_relative_deviation': None, 'texture_target': task.get('texture_size'),
                       'texture_match_fraction': None, 'texture_sizes': None}
    try:
        scene = trimesh.load(str(path), force='scene', process=False)
        meshes = [m for m in scene.geometry.values() if isinstance(m, trimesh.Trimesh)]
        if not meshes or not all(np.isfinite(m.vertices).all() for m in meshes):
            raise ValueError('No finite triangle meshes')
        # apply node transforms and count instances, not just unique buffers
        instance_meshes = []
        for node in scene.graph.nodes_geometry:
            transform, geometry = scene.graph[node]
            mesh = scene.geometry[geometry].copy(); mesh.apply_transform(transform); instance_meshes.append(mesh)
        meshes = instance_meshes
        tri = sum(len(m.faces) for m in meshes)
        if tri == 0:
            raise ValueError('No triangle faces')
        deg = 0; bad_edges = 0; boundary = 0; unique_edges = 0
        for mesh in meshes:
            vertices = np.asarray(mesh.vertices); faces = np.asarray(mesh.faces)
            extent = max(float(np.ptp(vertices, axis=0).max()), 1e-12)
            deg += int(np.count_nonzero(mesh.area_faces <= (extent * 1e-8) ** 2))
            # Weld coincident positions for topology only, never modify delivery.
            _, inverse = np.unique(np.round(vertices / extent, 10), axis=0, return_inverse=True)
            f = inverse[faces]
            edges = np.sort(np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]]), axis=1)
            _, counts = np.unique(edges, axis=0, return_counts=True)
            bad_edges += int(np.count_nonzero(counts != 2)); boundary += int(np.count_nonzero(counts == 1)); unique_edges += len(counts)
        raw.update(load_ok=True, triangles=tri, degenerate_face_ratio=deg / tri,
                   nonmanifold_edge_ratio=bad_edges / unique_edges, boundary_edge_count=boundary,
                   nonmanifold_definition='edge face incidence !=2, including boundaries; coincident seam vertices welded at relative 1e-10 for diagnostics only')
    except Exception as e:
        return {'geometry_subscore': None, 'raw': raw,
                'notes': [f'GLB decode/geometry unavailable: {type(e).__name__}: {e}',
                          'No zero assigned: decoder support failure cannot prove an invalid asset.'],
                'formula': GEOMETRY_FORMULA}
    try:
        sizes, errors = glb_texture_sizes(path); raw['texture_sizes'] = sizes; notes.extend(errors)
        target = task.get('texture_size')
        if target is not None and not errors:
            raw['texture_match_fraction'] = sum(s['width'] == target and s['height'] == target for s in sizes) / len(sizes) if sizes else 0.
    except Exception as e:
        notes.append('Texture dimensions unavailable: ' + str(e))
    target = task.get('decimation_target')
    if raw.get('triangles') is not None and target and target > 0:
        raw['triangle_relative_deviation'] = abs(raw['triangles'] - target) / target
    required = [raw['degenerate_face_ratio'], raw['nonmanifold_edge_ratio'], raw['triangle_relative_deviation'], raw['texture_match_fraction']]
    if any(x is None for x in required):
        score = None; notes.append('Geometry subscore null: missing target or undecodable texture; weights not redistributed.')
    else:
        d, n, t, m = required
        score = 100 * (1 - .3 * min(d / .01, 1) - .3 * min(n / .1, 1) - .2 * min(t, 1) - .2 * (1 - m))
    return {'geometry_subscore': score, 'raw': raw, 'notes': notes, 'formula': GEOMETRY_FORMULA}


class ImageQuality:
    def __init__(self):
        import torch
        self.device = 'mps' if torch.backends.mps.is_available() else 'cpu'
        self.models = {}; self.errors = {}; self.fallbacks = {}

    def score(self, name, image):
        from .resources import assert_metrics_idle
        assert_metrics_idle()
        import torch
        import pyiqa
        if name in self.errors:
            raise RuntimeError(self.errors[name])
        device = 'cpu' if name == 'niqe' else self.device  # NIQE uses float64
        if name not in self.models:
            try:
                self.models[name] = pyiqa.create_metric(name, device=device)
            except Exception as e:
                self.errors[name] = f'{type(e).__name__}: {e}'
                raise
        model = self.models[name]
        x = torch.from_numpy(np.asarray(rgb_composite(image)).copy()).permute(2, 0, 1).unsqueeze(0).float() / 255.
        try:
            with torch.inference_mode():
                return finite(model(x.to(model.device)).item())
        except (RuntimeError, NotImplementedError) as e:
            if str(model.device) == 'cpu':
                raise
            self.fallbacks[name] = str(e); model.to('cpu'); model.device = torch.device('cpu')
            with torch.inference_mode():
                return finite(model(x).item())

    def evaluate(self, views, geometry):
        raw = {}; notes = []
        for name in ('musiq', 'brisque', 'niqe'):
            values = []
            for v in views:
                try:
                    values.append(self.score(name, v['path']))
                except MetricsDeferred:
                    raise
                except Exception as e:
                    notes.append(f'{name} {v["id"]}: {type(e).__name__}: {e}'); values.append(None)
            valid = [x for x in values if x is not None]
            raw[name] = {'per_view': dict(zip([v['id'] for v in views], values)),
                         'mean': finite(np.mean(valid)) if len(valid) == len(views) and valid else None,
                         'known_views': len(valid), 'required_views': len(views)}
        m = raw['musiq']['mean']; g = geometry['geometry_subscore']
        if m is not None and not 0 <= m <= 100:
            notes.append('MUSIQ outside expected 0-100; quality index null, no silent clipping.'); m = None
        score = .5 * m + .5 * g if m is not None and g is not None else None
        if score is None:
            notes.append('Quality index null: required MUSIQ or geometry subscore unavailable; no weight redistribution.')
        return {'quality_index': score, 'musiq_normalized': m / 100 if m is not None else None,
                'image_metrics': raw, 'geometry': geometry, 'notes': notes, 'formula': QUALITY_FORMULA,
                'reference_only': ['brisque', 'niqe'], 'cpu_fallbacks': self.fallbacks.copy()}
