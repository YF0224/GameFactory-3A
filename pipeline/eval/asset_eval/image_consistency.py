from __future__ import annotations
import numpy as np
from PIL import Image
from .common import finite

DINO_MODEL = 'facebook/dinov2-base'


def rgb_composite(image, background=(196, 202, 209)):
    im = Image.open(image) if not isinstance(image, Image.Image) else image
    im = im.convert('RGBA')
    bg = Image.new('RGBA', im.size, tuple(map(int, background)) + (255,))
    return Image.alpha_composite(bg, im).convert('RGB')


def edge_median(im):
    arr = np.asarray(im.convert('RGB'))
    border = np.concatenate([arr[0], arr[-1], arr[1:-1, 0], arr[1:-1, -1]])
    return tuple(int(x) for x in np.median(border, axis=0))


def comparison_images(reference, renders):
    ref = Image.open(reference)
    has_alpha = 'A' in ref.getbands() or 'transparency' in ref.info
    # Alpha is used exactly; both transparent images get the same neutral RGB
    # background because DINO accepts RGB, not an invented segmentation mask.
    background = (196, 202, 209) if has_alpha else edge_median(ref)
    return [rgb_composite(ref, background)] + [rgb_composite(p, background) for p in renders], {
        'reference_has_alpha': has_alpha, 'background_rgb': list(background),
        'method': 'Use supplied alpha; composite both on neutral RGB for DINO' if has_alpha else
                  'Unsegmented reference unchanged; RGBA render composited on per-channel median of one-pixel reference perimeter',
        'silhouette_iou': None,
        'silhouette_note': 'Not computed: no camera registration and/or no reliable reference mask; no automatic background segmentation.'}


class Dino:
    def __init__(self, cache=None):
        from .resources import assert_metrics_idle
        assert_metrics_idle()
        import torch
        from transformers import AutoImageProcessor, AutoModel
        self.torch = torch
        self.device = 'mps' if torch.backends.mps.is_available() else 'cpu'
        try:
            self.processor = AutoImageProcessor.from_pretrained(DINO_MODEL, cache_dir=cache, local_files_only=True)
            model = AutoModel.from_pretrained(DINO_MODEL, cache_dir=cache, local_files_only=True)
            self.cache_mode = 'verified_local_cache'
        except OSError:
            self.processor = AutoImageProcessor.from_pretrained(DINO_MODEL, cache_dir=cache)
            model = AutoModel.from_pretrained(DINO_MODEL, cache_dir=cache)
            self.cache_mode = 'official_download'
        self.model = model.eval().to(self.device)
        self.revision = getattr(self.model.config, '_commit_hash', None)
        self.fallbacks = []

    def encode(self, images, batch_size=4):
        torch = self.torch; features = []
        for i in range(0, len(images), batch_size):
            from .resources import assert_metrics_idle
            assert_metrics_idle()
            rgb = [rgb_composite(x) for x in images[i:i + batch_size]]
            inputs = self.processor(images=rgb, return_tensors='pt')
            try:
                with torch.inference_mode():
                    cls = self.model(**{k: v.to(self.device) for k, v in inputs.items()}).last_hidden_state[:, 0, :]
            except (RuntimeError, NotImplementedError) as e:
                if self.device != 'mps':
                    raise
                self.fallbacks.append(str(e)); self.device = 'cpu'; self.model.to('cpu')
                with torch.inference_mode():
                    cls = self.model(**inputs).last_hidden_state[:, 0, :]
            feat = cls.cpu().float().numpy()
            if not np.isfinite(feat).all() or np.any(np.linalg.norm(feat, axis=1) == 0):
                raise ValueError('Invalid DINO CLS feature')
            features.append(feat / np.linalg.norm(feat, axis=1, keepdims=True))
        return np.concatenate(features, axis=0)

    def info(self):
        return {'model': DINO_MODEL, 'revision': self.revision, 'cache_mode': self.cache_mode, 'feature': 'last_hidden_state[:,0,:] CLS; L2 normalized',
                'device': self.device, 'cpu_fallbacks': self.fallbacks, 'processor': self.processor.to_dict()}


def image_consistency(dino, reference, views):
    ims, bg = comparison_images(reference, [v['path'] for v in views])
    features = dino.encode(ims)
    sim = features[1:] @ features[0]
    best = int(np.argmax(sim))
    return {'dinov2_cosine_max': finite(sim[best]), 'best_view': views[best]['id'],
            'best_azimuth_deg': views[best]['azimuth_deg'], 'best_elevation_deg': views[best]['elevation_deg'],
            'per_view': {v['id']: finite(s) for v, s in zip(views, sim)}, 'background': bg,
            'reference_path': str(reference)}
