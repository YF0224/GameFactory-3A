"""Opt-in lossless image transport; original evidence stays untouched."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from PIL import Image

from ..core.paths import sha256, write_json


def lossless_images(folder: Path, images: tuple[Path, ...]) -> tuple[Path, ...]:
    entries, transported = [], []
    cache = {}
    for receipt in sorted(folder.parent.glob('*/image_transport.json')):
        try:
            for item in json.loads(receipt.read_text())['images']:
                if item.get('pixel_equal'):
                    cache[item['original_sha256']] = item
        except (OSError, ValueError, KeyError):
            continue
    for index, source in enumerate(images):
        with Image.open(source) as original:
            if getattr(original, 'n_frames', 1) != 1:
                raise ValueError(f'Animated evidence is not supported: {source}')
            # Preserve alpha whenever present, including palette transparency.
            mode = 'RGBA' if 'A' in original.getbands() or 'transparency' in original.info else 'RGB'
            pixels = original.convert(mode)
            raw = pixels.tobytes()
            target = folder / 'transport_images' / f'{index:03d}.webp'
            target.parent.mkdir(parents=True, exist_ok=True)
            prior = cache.get(sha256(source))
            cached = Path(prior['submitted']) if prior else None
            if cached and cached.is_file() and sha256(cached) == prior['submitted_sha256'] and cached.suffix == '.webp':
                if cached.resolve() != target.resolve():
                    shutil.copyfile(cached, target)
            else:
                pixels.save(target, format='WEBP', lossless=True, quality=100, method=6, exact=True)
            with Image.open(target) as restored:
                if restored.size != pixels.size or restored.convert(mode).tobytes() != raw:
                    raise ValueError(f'Lossless transport pixel mismatch: {source}')
            selected = target if target.stat().st_size < source.stat().st_size else source
            entries.append({'original': str(source), 'original_sha256': sha256(source),
                            'submitted': str(selected), 'submitted_sha256': sha256(selected),
                            'size': list(pixels.size), 'mode': mode,
                            'pixel_sha256': hashlib.sha256(raw).hexdigest(), 'pixel_equal': True,
                            'original_bytes': source.stat().st_size, 'submitted_bytes': selected.stat().st_size})
            transported.append(selected)
    write_json(folder / 'image_transport.json', {'version': 'lossless-original-pixels.v1', 'images': entries})
    return tuple(transported)
