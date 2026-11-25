from __future__ import annotations
import hashlib
import json
import math
import os
import subprocess
import sys
from pathlib import Path

FRAMEWORK = Path(__file__).resolve().parents[3]
BENCH = FRAMEWORK
from pipeline.eval.stage1.paths import DATA_ROOT, SAMPLES, resolve_input
ASSETS = DATA_ROOT / 'outputs/asset'
OUTPUTS = DATA_ROOT / 'outputs/eval/asset_eval'
ENV = Path(os.environ.get('A3GAME_ASSET_EVAL_ENV', sys.prefix)).expanduser()


def dump(path: Path, value):
    """Reject NaN instead of quietly publishing non-JSON scores."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(text)
    tmp.replace(path)


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def tool(args, timeout=240):
    r = subprocess.run(list(map(str, args)), capture_output=True, text=True, timeout=timeout)
    if r.returncode:
        raise RuntimeError(f'{args[0]} exit={r.returncode}: {r.stderr[-1600:]}')
    return r


def finite(value):
    x = float(value)
    if not math.isfinite(x):
        raise ValueError(f'non-finite metric: {x}')
    return x


def validate_out(path):
    path = Path(path).resolve()
    if not path.is_relative_to(OUTPUTS.resolve()) or path == OUTPUTS.resolve():
        raise ValueError(f'Output must be a run subdirectory of {OUTPUTS}; source paths are read-only')
    path.mkdir(parents=True, exist_ok=True)
    return path


def check_environment():
    import sys
    if Path(sys.prefix).resolve() != ENV.resolve():
        raise RuntimeError(f'Use {ENV}/bin/python (not {sys.executable})')
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    os.environ['PYTORCH_ENABLE_MPS_FALLBACK'] = '1'
    os.environ['A3GAME_SOL_REASONING_EFFORT'] = 'medium'
    # Do not silently switch weights to a third-party mirror.
    os.environ['HF_ENDPOINT'] = 'https://huggingface.co'
