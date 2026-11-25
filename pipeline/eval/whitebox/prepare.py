"""Prepare one evaluation run: freeze inputs before anything is executed.

Layout of an eval run directory (``paths.eval_root(...)``)::

    input/project/            read-only snapshot of the author's project
    input/requirement.txt     general_requirement.txt of the case
    input/references/         reference images of the case (REF:...)
    input/delivery_documents/ .md/.json/.txt beside the project (DOC:...)
    input/criteria.json       frozen criteria of all eight metrics
    runtime/project/          working copy the engine actually opens
    manifest.json             sources, SHA256s, budget, models

The author's original delivery is never modified; ``prepare`` fails if it
changes while being copied.
"""
from __future__ import annotations

import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path

from . import budgets, suites
from .delivery import validate as validate_delivery
from .paths import DELIVERY_FILE, SAMPLES, read_json, sha256, write_json

VERSION = 'stage1-prepare.v1'
IGNORE = shutil.ignore_patterns('.git', '.godot', '.import', 'Library', 'Temp', 'obj', 'Logs',
                                'node_modules', 'dist', 'Intermediate', 'Saved', 'DerivedDataCache',
                                'Binaries', '__pycache__', '.DS_Store')
DOC_SUFFIXES = {'.md', '.json', '.txt'}
REF_SUFFIXES = {'.png', '.jpg', '.jpeg', '.webp'}


def tree_hashes(root: Path) -> dict:
    out = {}
    for p in sorted(Path(root).rglob('*')):
        if p.is_file() and not p.is_symlink() and not IGNORE(str(p.parent), [p.name]):
            out[str(p.relative_to(root))] = sha256(p)
    return out


def tree_digest(hashes: dict) -> str:
    h = hashlib.sha256()
    for path, digest in sorted(hashes.items()):
        h.update(f'{path}\0{digest}\n'.encode())
    return h.hexdigest()


def _delivery_documents(run_dir: Path, project: Path) -> list[Path]:
    """Narrative/contract files next to (not inside) the project; declarations, not proof."""
    docs = []
    for p in sorted(run_dir.rglob('*')):
        if (p.is_file() and not p.is_symlink() and p.suffix in DOC_SUFFIXES
                and not p.is_relative_to(project) and p.name != DELIVERY_FILE
                and 'eval' not in p.relative_to(run_dir).parts[:1]):
            docs.append(p)
    return docs


def prepare(run_dir: Path, out: Path, *, models: dict, suite: str = 'stage1', playable_only: bool = False) -> dict:
    """Snapshot one delivery (``run_dir`` holds delivery.json) into eval dir ``out``."""
    run_dir, out = Path(run_dir).resolve(), Path(out)
    problems = validate_delivery(run_dir, playable_only=playable_only and suite == 'stage1')
    if problems:
        raise ValueError(f'{run_dir}: delivery not admissible: {problems}')
    if (out / 'manifest.json').exists():
        return read_json(out / 'manifest.json')            # already prepared: never re-snapshot
    delivery = read_json(run_dir / DELIVERY_FILE)
    game_id, project = delivery['game_id'], (run_dir / delivery['project_root']).resolve()
    case = SAMPLES / game_id

    before = tree_hashes(project)
    inputs = out / 'input'
    shutil.copytree(project, inputs / 'project', ignore=IGNORE)
    shutil.copytree(project, out / 'runtime' / 'project', ignore=IGNORE)
    shutil.copyfile(case / 'general_requirement.txt', inputs / 'requirement.txt')
    for i, ref in enumerate(sorted(p for p in case.glob('**/ref_images/*')
                                   if p.is_file() and p.suffix.lower() in REF_SUFFIXES), 1):
        dest = inputs / 'references' / f'{i}_{ref.name}'
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ref, dest)
    for doc in _delivery_documents(run_dir, project):
        dest = inputs / 'delivery_documents' / doc.relative_to(run_dir)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(doc, dest)
    frozen = suites.get(suite).build(game_id)
    write_json(inputs / 'criteria.json', frozen)
    if tree_hashes(project) != before:
        raise RuntimeError(f'{project}: original delivery changed while snapshotting')

    manifest = {
        'version': VERSION, 'prepared_at': datetime.now(timezone.utc).isoformat(),
        'delivery': delivery, 'delivery_dir': str(run_dir),
        'game_id': game_id, 'engine': delivery['engine'], 'entry': delivery['entry'],
        'project_source': str(project), 'project_digest': tree_digest(before),
        'snapshot_digest': tree_digest(tree_hashes(inputs / 'project')),
        'input_hashes': {k: v for k, v in tree_hashes(inputs).items() if not k.startswith('project/')},
        'criteria_sha256': sha256(inputs / 'criteria.json'),
        'suite': suite, 'budget': budgets.budget_for(game_id), 'models': models,
    }
    write_json(out / 'manifest.json', manifest)
    return manifest


def verify(out: Path) -> dict:
    """Re-check the frozen inputs before every later stage."""
    out = Path(out)
    manifest = read_json(out / 'manifest.json')
    if tree_digest(tree_hashes(out / 'input' / 'project')) != manifest['snapshot_digest']:
        raise RuntimeError('input/project snapshot changed after prepare')
    current = {k: v for k, v in tree_hashes(out / 'input').items() if not k.startswith('project/')}
    if current != manifest['input_hashes']:
        raise RuntimeError('frozen inputs changed after prepare')
    return manifest
