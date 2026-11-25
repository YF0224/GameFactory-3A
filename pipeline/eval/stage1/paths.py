"""Shared paths, model names and the delivery contract for all stages."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

FRAMEWORK = Path(__file__).resolve().parents[3]
BENCH = FRAMEWORK  # compatibility alias for migrated evaluation helpers
DATA_ROOT = Path(os.environ.get('GF3A_DATA_ROOT', FRAMEWORK / 'test_data')).expanduser().resolve()
OUTPUTS = DATA_ROOT / 'outputs'
SAMPLES = DATA_ROOT / 'test_samples'

STAGE_OUTPUT_ROOTS = {
    'stage1': OUTPUTS / 'initial_game_gen',
    'stage3': OUTPUTS / 'game_refine',
}
STAGE3_INPUTS = OUTPUTS / 'game_refine' / 'inputs'
EVAL_ROOTS = {
    'stage1': OUTPUTS / 'eval' / 'whitebox',
    'stage3': OUTPUTS / 'eval' / 'refine',
    'assets': OUTPUTS / 'eval' / 'asset',
}

# Short model id -> existing directory label under the stage output roots.
MODEL_DIRS = {
    'sol': 'gpt_sol6p1',
    'astra': 'gpt_astra6',
    'opus': 'claude_ops5p5',
    'glm': 'glm_5p3',
    'kimi': 'kimi_k3',
}

DELIVERY_FILE = 'delivery.json'
DELIVERY_SCHEMA = 'bench.delivery.v1'


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def model_dir(model: str) -> str:
    if model not in MODEL_DIRS:
        raise ValueError(f'unknown model {model!r}; known: {sorted(MODEL_DIRS)}')
    return MODEL_DIRS[model]


def run_root(stage: str, model: str, game_id: str, run_id: str) -> Path:
    """<stage root>/<model dir>/<GameID>/<run_id>/ for both stage1 and stage3."""
    return STAGE_OUTPUT_ROOTS[stage] / model_dir(model) / game_id / run_id


def eval_root(stage: str, version: str, model: str, game_id: str, run_id: str) -> Path:
    return EVAL_ROOTS[stage] / version / model_dir(model) / game_id / run_id


def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path: Path, data) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    tmp.replace(path)


def resolve_input(value: str | Path) -> Path:
    """Resolve input paths while honoring a relocated test_data tree."""
    path = Path(value).expanduser()
    if path.is_absolute():
        return path.resolve()
    if path.parts[:1] == ('test_data',):
        return DATA_ROOT.joinpath(*path.parts[1:]).resolve()
    return (FRAMEWORK / path).resolve()


def read_profiles(path: Path, *, reader=None) -> dict:
    """Resolve reviewed profile paths against the repository/data root, independent of process cwd."""
    path_fields = {'project', 'source', 'scope_path', 'path'}

    def resolve(value, key=None):
        if isinstance(value, dict):
            return {k: resolve(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [resolve(v, key) for v in value]
        if key in path_fields and isinstance(value, str):
            candidate = Path(value)
            return str(resolve_input(candidate))
        return value

    return resolve((reader or read_json)(path))
