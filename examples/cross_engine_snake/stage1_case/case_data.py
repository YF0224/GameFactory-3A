"""Author ordinary Stage1 example input files, without registering an evaluator.

Only DEMO_snake_* cases are installed. Standards are drafts; human review uses
scripts_new/freeze_standards.py, exactly as for any other Stage1 case.
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
MECHANICS = (
    ('move', '方向键或 WASD 可以改变蛇前进的方向。', '蛇在棋盘上沿玩家选择的方向移动。'),
    ('food', '蛇碰到食物后会吃掉食物。', '蛇已经到达食物所在的位置并吃掉食物。'),
    ('grow', '吃到食物后蛇身增长。', '蛇吃到食物后出现增长的蛇身。'),
    ('wall', '撞到棋盘边界后游戏失败。', '蛇碰到棋盘边界后画面显示失败状态。'),
    ('self', '撞到自己的蛇身后游戏失败。', '蛇碰到自身后画面显示失败状态。'),
    ('win', '吃到三个食物后游戏胜利。', '完成食物目标后画面显示胜利状态。'),
    ('restart', '按 R 可以从终局重新开始游戏。', '重新开始后棋盘上出现可继续游玩的初始蛇和食物。'),
    ('pause', '空格可以暂停和继续游戏。', '游戏画面能够显示暂停状态。'),
)


def write_once(path: Path, content: bytes) -> None:
    """Reuse identical inputs; never overwrite another case or an earlier revision."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != content:
            raise ValueError(f'Existing example input differs; preserve it and use a new revision: {path}')
    else:
        with path.open('xb') as stream:
            stream.write(content)


def json_bytes(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def rubric(game_id: str, engine: str, assertions: list) -> dict:
    return {'status': 'frozen', 'game_id': game_id, 'engine': engine,
            'provenance': 'Locally authored synthetic example, not a benchmark sample.',
            'assertions': assertions}


def assertion(column: str, ident: str, text: str, **extra) -> dict:
    sub = {'id': ident, 'text': text, 'requirement_ids': [], 'scoring_role': 'scored', **extra}
    return {'table_column': column, 'assertion_id': ident, 'assertion': text,
            'binding': {'subchecks': [sub]}}


def install(engine: str) -> tuple[str, Path]:
    from pipeline.eval.stage1 import criteria, standards, suites
    from pipeline.eval.stage1.paths import SAMPLES

    game_id = 'DEMO_snake_' + engine
    fixture = HERE / 'cases' / game_id
    requirement = (f'tier: S\nengine: {engine}\n\n'
                   'Build a small playable Snake game on a visible grid. Use arrow keys or WASD.\n'
                   'Food is eaten on contact and grows the snake. Walls and self-collision end the run.\n'
                   'Eating three foods wins. R restarts the game; Space pauses and resumes.\n'
                   'Show the controls, food progress, pause, failure and victory states clearly.\n'
                   'Keep the snake, food, board and status display identifiable in the source.\n'
                   'The declared entry must launch the actual game and respond to normal input.\n'
                   'This is a synthetic integration example, not a historical benchmark delivery.\n')
    core = rubric(game_id, engine, [assertion('C2', key, text) for key, text, _ in MECHANICS])
    assets = rubric(game_id, engine, [assertion('C3', key, text, system=key) for key, text in (
        ('snake', '蛇的显示对象可以在源码中定位并接入游戏。'),
        ('food', '食物的显示对象可以在源码中定位并接入游戏。'),
        ('board', '棋盘的显示对象可以在源码中定位并接入游戏。'),
        ('status', '状态显示对象可以在源码中定位并接入游戏。'),
    )])
    visual = rubric(game_id, engine, [
        assertion('Q', 'board', '运行画面可以区分棋盘、蛇和食物。', topic='白模场景'),
        assertion('G', 'end', '终局提供清楚的成功、失败或拒绝反馈。', topic='交互反馈'),
    ])
    files = {
        'general_requirement.txt': requirement.encode('utf-8'),
        criteria.TIERED: json_bytes(core),
        criteria.RUBRIC: json_bytes(assets),
    }
    for relative, content in files.items():
        write_once(fixture / relative, content)
        write_once(SAMPLES / game_id / relative, content)
    content = json_bytes(visual)
    write_once(fixture / 'contract' / 'rubric.json', content)
    write_once(criteria.CONTRACT_HISTORY / game_id / 'example_v1' / 'rubric.json', content)

    built = criteria.build(game_id)
    rows = built['criteria']
    folder = standards.bench_dir('stage1', built['version'], game_id)
    metrics = suites.get('stage1').metrics
    outcomes = {f'atom.{key}.{key}': outcome for key, _, outcome in MECHANICS}
    for metric in suites.tiered(suites.get('stage1')):
        mine = [row for row in rows if row['metric'] == metric]
        if not mine:
            continue
        checks = {}
        for row in mine:
            outcome = outcomes.get(row['id'], row['requirement'])
            check = {
                'visible_goal': outcome,
                'result_frame_description': outcome,
                'necessary_context': '游戏棋盘和相关状态信息可见。',
                'representative_basic_function': outcome,
                'basic_function_bugs': ['对应功能没有可见响应。', '可见结果作用于错误的对象。'],
                'permitted_trigger_modes': ['input', 'automatic'],
                'original_requirement_diagnostic_only': row['requirement'],
            }
            key = 'correct_target' if metric == 'mechanic' else 'correct_target_and_information'
            check[key] = '贪吃蛇游戏中的蛇、食物或相应状态信息。'
            checks[row['id']] = check
        standard = {'revision': standards.VERSION,
                    'summary': 'Synthetic Snake example draft. Human approval is still required.',
                    'diagnostic_only_categories': list(standards.DIAGNOSTIC), 'checks': checks}
        standards.validate(metric, mine, standard, metrics)
        document = {'version': standards.VERSION, 'suite': 'stage1', 'criteria_version': built['version'],
                    'game_id': game_id, 'metric': metric, 'author': 'example fixture author',
                    'criteria_ids': [row['id'] for row in mine], 'standard': standard}
        content = json_bytes(document)
        write_once(fixture / 'standards' / f'{metric}.json', content)
        write_once(folder / f'{metric}.json', content)
    standards.write_review(folder, rows, 'stage1')
    return game_id, folder
