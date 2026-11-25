"""Read frozen playtest task indexes and verify their source selections."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from ..stage1.paths import OUTPUTS, read_json, sha256

ROOT = OUTPUTS / 'playtest'
FAMILIES = ('mechanic_gamefeel', 'vfx', 'import', 'initgame')


def folder(game: str | Path) -> Path:
    path = Path(game)
    if path.name == 'refine.json':
        return path.resolve().parent
    if (ROOT / game / 'refine.json').is_file():
        return ROOT / game
    for p in ROOT.glob('g*/refine.json'):
        if read_json(p)['game_id'] == str(game):
            return p.parent
    raise ValueError(f'No playtest refine.json for {game}')


def load(game: str | Path) -> tuple[Path, dict, dict]:
    directory = folder(game)
    index = read_json(directory / 'refine.json')
    gid = index['game_id']
    if (index.get('schema_version') != 'playtest.case_inputs.v1'
            or index.get('game_directory') != directory.name
            or set(index.get('inputs', {})) != set(FAMILIES)
            or index.get('max_repair_attempts_per_game_model') != 10):
        raise ValueError(f'{gid}: invalid playtest index identity')
    groups = {}
    manifest = read_json(directory.parent / 'manifest.json')
    for family in FAMILIES:
        ref = index['inputs'][family]
        path = (directory / ref['path']).resolve()
        if not path.is_relative_to(directory.resolve()) or sha256(path) != ref['sha256']:
            raise ValueError(f'{gid}: frozen task file changed: {path}')
        rows = read_json(path)
        if (not isinstance(rows, list) or len(rows) != ref['record_count']
                or any(not isinstance(row, dict) or row.get('game_id') != gid for row in rows)):
            raise ValueError(f'{gid}: invalid task identity/count: {family}')
        snapshot = (directory / ref['source_snapshot']).resolve()
        if not snapshot.is_relative_to(directory.parent.resolve() / 'sources'):
            raise ValueError(f'{gid}: source snapshot escapes sources: {family}')
        source = next(s for s in manifest['sources'] if s['family'] == family)
        if sha256(snapshot) != source['sha256']:
            raise ValueError(f'{gid}: frozen source snapshot changed: {family}')
        records = [(line, json.loads(text)) for line, text in enumerate(snapshot.read_text().splitlines(), 1) if text.strip()]
        if len(records) != source['record_count']:
            raise ValueError(f'{gid}: source snapshot count changed: {family}')
        selected = [(n, line, row) for n, (line, row) in enumerate(records, 1) if row['game_id'] == gid]
        if (rows != [row for _, _, row in selected]
                or ref['source_records'] != [{'source_record_index': n, 'physical_line': line} for n, line, _ in selected]):
            raise ValueError(f'{gid}: task selection differs from frozen source: {family}')
        groups[family] = rows
    counts = Counter(row['selection_kind'] for row in groups['mechanic_gamefeel'])
    actual = {key: counts[key] for key in ('mechanic', 'gamefeel')}
    actual.update(vfx=len(groups['vfx']), **{'import': len(groups['import'])})
    if (set(counts) - {'mechanic', 'gamefeel'} or actual != index['task_counts']
            or sum(actual.values()) != index['task_total'] or len(groups['initgame']) != 1
            or groups['initgame'][0].get('selected_project') != index.get('selected_project')
            or groups['initgame'][0].get('source_model') != index.get('source_model')):
        raise ValueError(f'{gid}: count/project metadata changed')
    return directory, index, groups
