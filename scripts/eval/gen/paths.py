"""Shared paths and helpers for generation (scripts_new/gen)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]        # GameFactory-3A/
FRAMEWORK = REPO                                   # pipeline/ lives directly under REPO
SETTING_OVERVIEW = REPO / 'agent_skills' / 'setting_overview.md'
SAMPLES = REPO / 'test_data' / 'test_samples'
CONFIG = Path(__file__).resolve().parents[1] / 'config' / 'models.json'


def models() -> dict:
    data = json.loads(CONFIG.read_text(encoding='utf-8'))
    data.pop('_comment', None)
    return data


def model_dir(model: str) -> str:
    return models()[model]['method_dir']


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, data) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    tmp.replace(path)


def tree_digest(root: Path, ignore=None) -> str:
    """SHA256 over (relative path, file SHA256) of every regular file, skipping ignored names."""
    h = hashlib.sha256()
    root = Path(root)
    for p in sorted(root.rglob('*')):
        rel = p.relative_to(root)
        if ignore and any(ignore(str(root / Path(*rel.parts[:i])), [rel.parts[i]]) for i in range(len(rel.parts))):
            continue
        if p.is_file() and not p.is_symlink():
            h.update(f'{rel.as_posix()}\0{hashlib.sha256(p.read_bytes()).hexdigest()}\n'.encode())
    return h.hexdigest()
