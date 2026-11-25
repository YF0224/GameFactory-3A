"""Validate the entire generation queue before creating any output directories."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .paths import DATA_ROOT, FRAMEWORK

ENGINES = {'godot', 'three_js', 'unity3d', 'ue5'}


def data_path(value) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path.resolve()
    if path.parts and path.parts[0] == 'test_data':
        return (DATA_ROOT / Path(*path.parts[1:])).resolve()
    return (FRAMEWORK / path).resolve()


def matches(game_id: str, selection: str | None) -> bool:
    if not selection or selection == 'all':
        return True
    for part in selection.split(','):
        part = part.strip()
        span = re.fullmatch(r'(?i)G?(\d+)-G?(\d+)', part)
        if span and int(span[1]) <= int(game_id[1:4]) <= int(span[2]):
            return True
        if part.isdigit() and game_id[:4] == f'G{int(part):03d}':
            return True
        if part.upper() in (game_id.upper(), game_id[:4].upper()):
            return True
    return False


def stage1_tasks(args) -> list[dict]:
    from .stage1 import case_info
    errors, rows = [], []
    if args.requirement:
        path = data_path(args.requirement)
        rows = [{'game_id': args.game_id or path.parent.name,
                 'engine': args.engine, 'general_requirement_path': str(path)}]
    else:
        collect = data_path(args.collect or DATA_ROOT / 'pipeline_collect.jsonl')
        try:
            lines = collect.read_text(encoding='utf-8').splitlines()
        except OSError as exc:
            raise ValueError(str(exc)) from exc
        for n, line in enumerate(lines, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError('expected a JSON object')
                rows.append({**row, '_line': n})
            except ValueError as exc:
                errors.append(f'{collect}:{n}: {exc}')
    tasks, seen = [], set()
    for row in rows:
        label = f'line {row.get("_line", 1)} ({row.get("game_id", "?")})'
        try:
            gid = row['game_id']
            if not re.fullmatch(r'G\d{3}_[A-Za-z0-9_]+', gid):
                raise ValueError('game_id must be a full Gnnn_name identifier')
            requirement = data_path(row['general_requirement_path'])
            info = case_info(gid, requirement, row.get('engine'))
            engine = info['engine']
            if engine not in ENGINES:
                raise ValueError(f'unknown engine: {engine}')
            identity = (gid, engine)
            if identity in seen:
                raise ValueError(f'duplicate task: {gid}/{engine}')
            seen.add(identity)
            tasks.append({'game_id': gid, 'engine': engine, 'requirement': requirement})
        except (KeyError, TypeError, ValueError, OSError) as exc:
            errors.append(f'{label}: {exc}')
    allowed = set(args.engines.split(',')) if args.engines else ENGINES
    if allowed - ENGINES:
        errors.append(f'unknown engine filter: {sorted(allowed - ENGINES)}')
    if errors:
        raise ValueError('Invalid generation inputs; no jobs created:\n' + '\n'.join(errors))
    return [t for t in tasks if matches(t['game_id'], args.games) and t['engine'] in allowed]
