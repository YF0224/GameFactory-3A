"""Shared bootstrap for scripts/eval: paths, imports, case selection."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent          # GameFactory-3A/
FRAMEWORK = REPO                   # pipeline/ lives directly under REPO
if str(FRAMEWORK) not in sys.path:
    sys.path.insert(0, str(FRAMEWORK))

from pipeline.eval.whitebox.core import paths as common  # noqa: E402

MODELS = json.loads((HERE / 'config' / 'models.json').read_text(encoding='utf-8'))
MODELS.pop('_comment', None)


def all_cases() -> list[str]:
    # Migrated layout: game inputs live under test_data/eval_data; test_samples only has collect jsonl.
    roots = [common.EVAL_DATA if hasattr(common, 'EVAL_DATA') else None, common.SAMPLES]
    seen: dict[str, Path] = {}
    for root in roots:
        if root is None:
            continue
        if root.exists():
            for p in root.iterdir():
                if p.is_dir() and re.match(r'G\d{3}_', p.name) and (p / 'general_requirement.txt').is_file():
                    seen.setdefault(p.name, p)
    return sorted(seen)


def select_cases(games: str | None, engines: str | None) -> list[str]:
    """games: 'G001,G008' or '1-20'; engines: 'godot,three_js'."""
    cases = all_cases()
    if games:
        wanted = set()
        for part in games.split(','):
            part = part.strip()
            if re.fullmatch(r'\d+-\d+', part):
                a, b = map(int, part.split('-'))
                wanted |= {f'G{n:03d}' for n in range(a, b + 1)}
            elif part.isdigit():
                wanted.add(f'G{int(part):03d}')
            else:
                wanted.add(part.upper()[:4] if re.match(r'(?i)g\d{3}', part) else part)
        cases = [c for c in cases if c[:4] in wanted or c in wanted]
    if engines:
        from pipeline.eval.whitebox.core.delivery import case_engine
        allowed = {e.strip() for e in engines.split(',')}
        cases = [c for c in cases if case_engine(c) in allowed]
    return cases


def parse_models(models: str | None) -> list[str]:
    names = [m.strip() for m in models.split(',')] if models else list(MODELS)
    unknown = [m for m in names if m not in MODELS]
    if unknown:
        raise SystemExit(f'unknown models {unknown}; known: {list(MODELS)}')
    return names
