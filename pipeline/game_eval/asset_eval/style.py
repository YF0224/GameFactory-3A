from __future__ import annotations
import numpy as np
from PIL import Image
from .common import finite


def palette_metric(images, palette_hex, *, all_pixels=False):
    from .resources import assert_metrics_idle
    assert_metrics_idle()
    if not palette_hex:
        return {'weighted_mean_deltaE2000': None, 'pixel_fraction_deltaE_lt10': None,
                'notes': ['No hex palette in game W06; no palette invented.']}
    from skimage.color import rgb2lab, deltaE_ciede2000
    from sklearn.cluster import KMeans
    chunks = []
    for p in images:
        im = p if isinstance(p, Image.Image) else Image.open(p)
        arr = np.asarray(im.convert('RGBA'))
        # Alpha >= 0.95 excludes antialiased background mixtures.
        mask = np.ones(arr.shape[:2], dtype=bool) if all_pixels else arr[:, :, 3] >= 243
        chunks.append(arr[:, :, :3][mask])
    pixels = np.concatenate(chunks)
    if not len(pixels):
        raise ValueError('No foreground pixels for palette metric')
    lab = rgb2lab(pixels.reshape(-1, 1, 3) / 255.).reshape(-1, 3)
    target_rgb = np.asarray([[int(h[i:i + 2], 16) for i in (1, 3, 5)] for h in palette_hex]) / 255.
    target = rgb2lab(target_rgb.reshape(-1, 1, 3)).reshape(-1, 3)
    # Deterministic bounded fit. Full foreground pixels determine occupancy and
    # ΔE<10 fraction; that fraction is NOT inferred from cluster centers.
    fit = lab[np.linspace(0, len(lab) - 1, min(50000, len(lab)), dtype=int)]
    k = min(5, len(np.unique(fit, axis=0)))
    model = KMeans(n_clusters=k, n_init=10, random_state=0).fit(fit)
    counts = np.zeros(k, dtype=np.int64); below = 0
    for start in range(0, len(lab), 100000):
        x = lab[start:start + 100000]
        counts += np.bincount(model.predict(x), minlength=k)
        de = deltaE_ciede2000(x[:, None, :], target[None, :, :])
        below += int(np.count_nonzero(de.min(axis=1) < 10))
    center_de = deltaE_ciede2000(model.cluster_centers_[:, None, :], target[None, :, :]).min(axis=1)
    weights = counts / counts.sum()
    return {'weighted_mean_deltaE2000': finite(np.sum(weights * center_de)),
            'pixel_fraction_deltaE_lt10': below / len(lab), 'foreground_pixels': len(lab),
            'k_requested': 5, 'k_effective': k, 'fit_pixels': len(fit), 'palette_hex': palette_hex,
            'clusters_lab': model.cluster_centers_.tolist(), 'cluster_weights': weights.tolist(),
            'cluster_nearest_deltaE2000': center_de.tolist(), 'notes': []}


def game_dispersion(rows):
    """Per game/provider/scope. Content diversity is confounded with style."""
    groups = {}
    for row in rows:
        vec = row.get('style_embedding')
        if vec is not None:
            groups.setdefault((row['game'], row['provider'], row['scope']), []).append((row['task_id'], vec))
    out = []
    for (game, pro, scope), entries in sorted(groups.items()):
        x = np.array([e[1] for e in entries]); x /= np.linalg.norm(x, axis=1, keepdims=True)
        if len(x) < 2:
            out.append(dict(game=game, provider=pro, scope=scope, n=len(x), mean=None, variance=None,
                            outliers=[], notes=['Need at least two delivered DINO embeddings']))
            continue
        dist = np.maximum(0., 1 - x @ x.T); pair = dist[np.triu_indices(len(x), k=1)]
        avg = dist.sum(axis=1) / (len(x) - 1)
        # Prespecified outlier rule, no tuning to observed scores.
        threshold = float(avg.mean() + 2 * avg.std())
        out.append(dict(game=game, provider=pro, scope=scope, n=len(x), mean=finite(pair.mean()),
                        variance=finite(pair.var()), outliers=[entries[i][0] for i in range(len(x)) if avg[i] > threshold],
                        per_asset_mean_distance={e[0]: finite(a) for e, a in zip(entries, avg)}, outlier_threshold=threshold,
                        notes=['Population variance; outlier > mean(per-asset distance)+2std; diagnostic only, not a pure style measure.']))
    return out
