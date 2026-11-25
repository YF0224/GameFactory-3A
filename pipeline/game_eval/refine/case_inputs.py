"""Read per-game task indexes, preserving frozen collect identity and full rows."""
from collections import Counter
from pathlib import Path

from .common import inside, jsonl, read, resolve, sha

FAMILIES = {'mechanic_gamefeel': 'repair', 'vfx': 'vfx', 'import': 'simple', 'initgame': 'initial'}


def load(config, games=None):
    bindings = config['case_inputs']
    wanted = list(games if games is not None else config.get('games') or bindings)
    if not wanted or len(wanted) != len(set(wanted)) or set(wanted) - set(bindings):
        raise ValueError('Missing/duplicate per-game input binding')
    if not config.get('include_vfx'):
        raise ValueError('Per-game inputs require VFX to remain included')
    rows = {key: [] for key in FAMILIES.values()}
    cases = {}
    for gid in wanted:
        ref = bindings[gid]
        index_path = resolve(config['bench_root'], ref['path'])
        if sha(index_path) != ref['sha256']:
            raise ValueError('Frozen per-game index changed: ' + gid)
        index = read(index_path)
        if (index.get('schema_version') != 'playtest.case_inputs.v1' or index.get('game_id') != gid
                or index.get('game_directory') != index_path.parent.name
                or set(index.get('inputs', {})) != set(FAMILIES)
                or index.get('max_repair_attempts_per_game_model') != 10):
            raise ValueError('Invalid per-game index identity: ' + gid)
        refs = [{'path': str(index_path), 'sha256': ref['sha256']}]
        grouped = {}
        for family, key in FAMILIES.items():
            item = index['inputs'][family]
            path = inside(index_path.parent, item['path'])
            if sha(path) != item['sha256']:
                raise ValueError('Per-game task file changed: ' + str(path))
            values = read(path)
            if (not isinstance(values, list) or len(values) != item['record_count'] or
                    any(not isinstance(row, dict) or row.get('game_id') != gid for row in values)):
                raise ValueError('Per-game file contains invalid/foreign rows: ' + gid)
            original = config['frozen_collect_sources'][key]
            snapshot = inside(index_path.parent.parent,
                              str(Path(index_path.parent.name) / item['source_snapshot']))
            if (sha(snapshot) != original['sha256'] or sha(original['path']) != original['sha256']):
                raise ValueError('Per-game snapshot differs from frozen collect: ' + family)
            selected = [(n + 1, line, row) for n, (line, row) in enumerate(jsonl(snapshot))
                        if row['game_id'] == gid]
            positions = [{'source_record_index': n, 'physical_line': line} for n, line, _ in selected]
            if values != [row for _, _, row in selected] or item['source_records'] != positions:
                raise ValueError('Per-game tasks differ from original selection: ' + gid + '/' + family)
            # Runtime task values come from this game's JSON. Full collects only verify provenance.
            rows[key].extend((row, {**original, 'line': pos['physical_line']})
                             for row, pos in zip(values, positions))
            refs.extend(({'path': str(path), 'sha256': item['sha256']},
                         {'path': str(snapshot), 'sha256': original['sha256']}))
            grouped[family] = values
        counts = Counter(row['selection_kind'] for row in grouped['mechanic_gamefeel'])
        actual = {key: counts[key] for key in ('mechanic', 'gamefeel')}
        actual.update(vfx=len(grouped['vfx']), **{'import': len(grouped['import'])})
        if (set(counts) - {'mechanic', 'gamefeel'} or actual != index['task_counts']
                or sum(actual.values()) != index['task_total'] or len(grouped['initgame']) != 1
                or grouped['initgame'][0].get('selected_project') != index.get('selected_project')
                or grouped['initgame'][0].get('source_model') != index.get('source_model')):
            raise ValueError('Per-game count/project metadata changed: ' + gid)
        cases[gid] = {'path': str(index_path), 'sha256': ref['sha256'], 'sources': refs}
    return rows, cases


def verify(binding):
    for ref in binding['sources']:
        if sha(ref['path']) != ref['sha256']:
            raise ValueError('Per-game input changed during repair: ' + ref['path'])


def prompt(binding):
    return (f"本游戏的任务入口为 {binding['path']}。完整读取该 refine.json，"
            '再按 inputs 中的相对路径读取本游戏的 mechanic_gamefeel.json、vfx.json、import.json 和 initgame.json。'
            '这些输入只读，不修改任务或来源；不要把其他游戏的任务加入本轮。'
            'workspace/refine_tasks.json 补充本游戏的详细导入要求、实际素材位置和来源，仍须完整读取。'
            'model_project_directories 是整理阶段预留位置，实际修改工程以本轮 workspace/project 为准。')
