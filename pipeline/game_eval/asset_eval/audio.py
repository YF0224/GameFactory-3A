"""Stage-4 helpers; dialogue and sound effects must never share semantics.

Full stage deferred until prior gates pass. ASR/emotion/ECAPA/DNSMOS and audio
listening are NOT pretended to work through a text/image-only sol invocation.
"""
from __future__ import annotations
import json
import re
import unicodedata
from .common import tool


def normalize_transcript(text):
    return ''.join(c.lower() for c in unicodedata.normalize('NFKC', text)
                   if c.isalnum())


def cer(reference, hypothesis):
    r, h = normalize_transcript(reference), normalize_transcript(hypothesis)
    if not r:
        return None
    prev = list(range(len(h) + 1))
    for i, a in enumerate(r, 1):
        row = [i]
        for j, b in enumerate(h, 1):
            row.append(min(row[-1] + 1, prev[j] + 1, prev[j - 1] + (a != b)))
        prev = row
    return prev[-1] / len(r)


def signal_metrics(path):
    """Decode original audio; no score for missing loudness or failed models."""
    import subprocess
    from .resources import assert_metrics_idle
    assert_metrics_idle()
    import numpy as np
    probe = json.loads(tool(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', path]).stdout)
    s = next(s for s in probe['streams'] if s['codec_type'] == 'audio')
    sr, channels = int(s['sample_rate']), int(s['channels'])
    duration = float(s.get('duration', probe['format'].get('duration', 0)))
    if not 0 < duration <= 120 or sr * channels * duration * 4 > 64 * 1024 * 1024:
        raise ValueError('Local audio pilot limited to 120s and 64MiB decoded PCM')
    assert_metrics_idle()
    r = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-threads', '1', '-i', str(path), '-threads', '1', '-f', 'f32le', '-acodec', 'pcm_f32le', '-'], capture_output=True, check=True, timeout=120)
    pcm = np.frombuffer(r.stdout, dtype='<f4')
    if not pcm.size or not np.isfinite(pcm).all():
        raise ValueError('Empty/nonfinite audio')
    assert_metrics_idle()
    loud = tool(['ffmpeg', '-nostdin', '-v', 'info', '-threads', '1', '-i', path, '-filter_threads', '1', '-threads', '1', '-af', 'ebur128=peak=true', '-f', 'null', '-'])
    summary = loud.stderr.rsplit('Summary:', 1)[-1] if 'Summary:' in loud.stderr else ''
    matches = re.findall(r'I:\s*(-?\d+(?:\.\d+)?)\s+LUFS', summary)
    return {'sample_rate': sr, 'channels': channels, 'duration_sec': len(pcm) / (sr * channels),
            'integrated_lufs': float(matches[-1]) if matches else None,
            'clipping_sample_fraction': float(np.mean(np.abs(pcm) >= .999)),
            'silence_sample_fraction': float(np.mean(np.abs(pcm) < 10 ** (-60 / 20))),
            'silence_definition': 'sample amplitude below -60dBFS, not VAD speech silence',
            'quality_index': None,
            'notes': ([] if matches else ['LUFS unavailable (including silent/nonfinite integrated loudness).']) + ['Stage-4 perceptual model not run; no substitute quality index from signal measures.']}


class Clap:
    """Official LAION repository, lazy download only in the audio stage."""
    def __init__(self, cache=None):
        from .resources import assert_metrics_idle
        assert_metrics_idle()
        import torch
        from transformers import ClapModel, ClapProcessor
        self.torch = torch
        self.device = 'mps' if torch.backends.mps.is_available() else 'cpu'
        ident = 'laion/clap-htsat-unfused'
        self.ident = ident
        self.processor = ClapProcessor.from_pretrained(ident, cache_dir=cache)
        self.model = ClapModel.from_pretrained(ident, cache_dir=cache).eval().to(self.device)
        self.revision = getattr(self.model.config, '_commit_hash', None)
        self.fallbacks = []

    def similarity(self, waveform_48000_mono, prompt):
        from .resources import assert_metrics_idle
        assert_metrics_idle()
        inputs = self.processor(text=[prompt], audios=[waveform_48000_mono], sampling_rate=48000,
                                return_tensors='pt', padding=True)
        try:
            with self.torch.inference_mode():
                o = self.model(**{k: v.to(self.device) for k, v in inputs.items()})
        except (RuntimeError, NotImplementedError) as exc:
            self.fallbacks.append(str(exc))
            if self.device == 'cpu':
                raise
            self.device = 'cpu'; self.model.to('cpu')
            with self.torch.inference_mode():
                o = self.model(**inputs)
        # Not temperature-scaled logits: cosine in the normalized joint space.
        a = o.audio_embeds[0]; t = o.text_embeds[0]
        from .common import finite
        return finite(self.torch.nn.functional.cosine_similarity(a[None], t[None]).cpu().item())

    def info(self):
        return {'model': self.ident, 'revision': self.revision, 'device': self.device,
                'cpu_fallbacks': self.fallbacks, 'feature': 'CLAP normalized text/audio embedding cosine; not logits'}


STAGE_STATUS = 'G001 SFX CLAP/signal pilot; dialogue models, perceptual index and sol audio listening unvalidated'
from .constants import VABENCH


def waveform_48k(path):
    """Bounded mono float decode for the official CLAP sampling rate."""
    import subprocess
    from .resources import assert_metrics_idle
    assert_metrics_idle()
    import numpy as np
    # Each sample is separately checked by signal_metrics (<=120s); CLAP uses
    # its documented max-length crop/padding. Decode cap is independent.
    r = subprocess.run(['ffmpeg','-nostdin','-v','error','-threads','1','-i',str(path),
        '-t','120','-ac','1','-ar','48000','-threads','1','-f','f32le','-acodec','pcm_f32le','-'],
        capture_output=True, check=True, timeout=120)
    a = np.frombuffer(r.stdout, dtype='<f4').copy()
    if not a.size or not np.isfinite(a).all():
        raise ValueError('Empty/nonfinite CLAP waveform')
    return a
