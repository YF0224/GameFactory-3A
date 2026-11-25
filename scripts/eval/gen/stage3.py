"""Stage3 refine generation: one agent per (game, model), multi-round on one session.

Layout (run root = ``game_refine/<model dir>/<GameID>/<run_id>/``)::

    project/              working copy of the original Sol project (the agent edits only this)
    refine_tasks.json     this game's tasks only (mechanic / gamefeel / vfx / import)
    repair_status.json    written by the agent each round (completed / remaining tasks)
    repair_report.md      written by the agent (changes, playtest observations, blockers)
    delivery.json         written by us after the last round (stage3 contract)
    .generation/          job state, prompts and agent logs per round

The original Sol delivery is read-only; its digest is checked before and after
copying and again when the job finishes. Up to ``MAX_ROUNDS`` rounds share one
budget; a round counts even if it timed out. The job stops early once the agent
reports no actionable remaining task.
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

from . import runner
from .jobs import Job, now
from .paths import BENCH, FRAMEWORK, SETTING_OVERVIEW, model_dir, read_json, tree_digest, write_json

MAX_ROUNDS = 10
ROUND_TIMEOUT = 30 * 60
INPUTS = BENCH / 'test_data/outputs/game_refine/inputs'
IMPORT_DETAIL = BENCH / 'test_data/outputs/game_refine/repair_import_collect.json'
OUTPUT = BENCH / 'test_data/outputs/game_refine'
IGNORE = shutil.ignore_patterns('.git', 'Intermediate', 'Saved', 'DerivedDataCache', 'Binaries', 'Library',
                                'Temp', 'obj', 'Logs', '.godot', 'node_modules', '.DS_Store')
ENGINES = {'ue5': 'ue5', 'ue': 'ue5', 'unreal': 'ue5', 'unity/tuanjie': 'unity3d', 'unity': 'unity3d',
           'tuanjie': 'unity3d', 'unity3d': 'unity3d', 'godot': 'godot', 'three_js': 'three_js'}


def games() -> list[str]:
    return sorted(p.name for p in INPUTS.iterdir() if p.is_dir() and p.name.startswith('G'))


def source_project(game_id: str) -> dict:
    """The original Sol project: refine.json, else one consistent project named by the task files."""
    folder = INPUTS / game_id
    chosen = read_json(folder / 'refine.json').get('selected_project')
    origin = 'refine.json'
    if not chosen:
        found = {}
        for name in ('vfx.json', 'import.json'):
            for task in read_json(folder / name):
                sp = task.get('selected_project')
                if sp:
                    found[json.dumps(sp, sort_keys=True)] = (name, sp)
        if len(found) != 1:
            raise ValueError(f'{game_id}: no unique original project (refine.json has none, task files name {len(found)})')
        origin, chosen = next(iter(found.values()))
    root = (BENCH / chosen['project_root']).resolve()
    if not root.is_dir():
        raise ValueError(f'{game_id}: original project missing at {root}')
    engine = ENGINES.get(str(chosen['engine']).lower())
    if not engine:
        raise ValueError(f'{game_id}: unknown engine {chosen["engine"]}')
    entry = str((BENCH / chosen['launch_entry']).resolve().relative_to(root))
    return {'root': str(root), 'engine': engine, 'entry': entry, 'origin': origin, 'raw': chosen}


def task_document(game_id: str) -> dict:
    folder = INPUTS / game_id
    details = {}
    if IMPORT_DETAIL.is_file():
        for line in IMPORT_DETAIL.read_text(encoding='utf-8').splitlines():
            if line.strip():
                row = json.loads(line)
                details[row.get('import_id')] = row
    repairs = read_json(folder / 'mechanic_gamefeel.json') + read_json(folder / 'vfx.json')
    imports = []
    for t in read_json(folder / 'import.json'):
        d = details.get(t['import_id'], {})
        asset = BENCH / t['asset_path'] if t.get('asset_path') else None
        imports.append({'import_id': t['import_id'], 'asset_kind': t['asset_kind'], 'requirement': t,
                        'asset_path': str(asset) if asset else None,
                        'payload_status': 'READY' if asset and asset.exists() else 'MISSING_PAYLOAD',
                        'acceptance': {k: d.get(k) for k in ('import_goal', 'acceptance_criteria',
                                                             'runtime_evidence_required', 'trigger_contract',
                                                             'motion_contract', 'dependencies', 'replacement_guide')}})
    ids = ([r.get('selection_id') or r.get('gamefeel_id') for r in repairs] + [i['import_id'] for i in imports])
    requirement = BENCH / 'test_data/test_samples' / game_id / 'general_requirement.txt'
    return {'schema': 'stage3.refine-tasks.v2', 'game_id': game_id, 'task_ids': ids,
            'repairs': repairs, 'imports': imports,
            'original_requirements_text': requirement.read_text(encoding='utf-8')}


def _ue_note(engine: str) -> str:
    if engine != 'ue5':
        return ''
    return ('\nUE refine 统一使用 UE 5.4 构建并启动；本机 UE_ROOT / A3GAME_UE_ROOT 为 `/Users/Shared/Epic Games/UE_5.4`（5.4.4）。'
            '允许并要求在当前候选内修复引擎兼容问题，包括将不支持的 BuildSettingsVersion.V6 适配为 V5、IncludeOrderVersion '
            '适配为 EngineIncludeOrderVersion.Unreal5_4，以及其他实际编译/API/插件兼容问题；原作者交付只读。先保存并检查 '
            'Build.sh/UnrealBuildTool 的真实退出码及编译日志，再启动本候选；不得把后续 echo/tail 的成功退出当成构建通过，'
            '不以更换游戏入口或伪造玩法掩盖兼容错误。\n')


def _status_contract(game_id: str, ids: list, n: int) -> str:
    example = {'game_id': game_id, 'round': n, 'completed_task_ids': [],
               'remaining_tasks': [{'task_id': '未完成的真实ID', 'actionable': True, 'reason': '具体剩余修改或外部阻塞'}]}
    return (f'\n最多{MAX_ROUNDS}轮是上限，不是必须跑满；全部可做修改完成后立即结束。本轮结束时在工作区（project/外）写 '
            'repair_status.json，严格使用JSON：' + json.dumps(example, ensure_ascii=False)
            + '。所有任务ID必须各出现一次，位于completed_task_ids或remaining_tasks；完整任务ID：'
            + json.dumps(ids, ensure_ascii=False)
            + '。actionable表示仍有可在本工程内实际执行的修改；外部缺资源/工具阻塞写false和真实原因。'
            '该状态仅控制是否继续编辑，不代表运行通过或测评成绩。不得为了轮次产生无关改动。\n'
            f'本轮交互最长 {ROUND_TIMEOUT // 60} 分钟，完成可做工作后立即提交结果并结束回复。在时间上限前留出保存修改、'
            'repair_status.json、repair_report.md、真实证据和清理本轮自有引擎进程的时间。超时或中断的调用仍占用一次尝试，'
            '后续继续同一会话，不重置预算。不得启动最终独立评估或 judge；本轮修复状态不等于正式测评成绩。\n')


def first_prompt(game_id: str, workspace: Path, engine: str, ids: list) -> str:
    return f'''你是游戏 {game_id} 的唯一修复 agent。只修改当前工作区 `{workspace}/project`，原始作者工程只读。
{_ue_note(engine)}
执行顺序（同一个会话内顺序完成）：
1. 先完整阅读 `{SETTING_OVERVIEW}`，理解 GameFactory-3A 的框架、分层和技能路由，确认 playtest 属于本次 refine 的“修复—验证—再修复”闭环；只按任务所需路由查对应引擎和技能，不泛读历史批次或排查无关环境。
2. 然后读取 `{workspace}/refine_tasks.json`，这是本游戏本次需要修复的完整任务，包含原始条目、验收、资产路径和全部 task ID。逐项理解 mechanic、gamefeel、import、texture、VFX、motion/绑骨/retarget 任务，定位对应工程代码与资产；不得仅凭文件名或任务编号猜需求。
3. 针对任务作最小必要修复，并按 overview 路由找到对应引擎的 playtest，进行构建/启动、实际操作、录制/观看、修复及复查。某项资源或工具确实阻塞时逐项记录原因和未验证事实，继续其他可做任务；不申请或尝试 OS 键鼠/窗口激活回退。

本次你同时承担 refine 与 playtest：允许并要求启动本项目引擎、构建、运行技能规定的 playtest。最终独立评估由另一脚本执行，本次不得调用；不得用静态检查冒充 playtest。

修复必须覆盖全部任务及其原始验收，不得只写计划或报告。全部任务共享最多 {MAX_ROUNDS} 轮，可提前结束。每轮结束更新工作区根目录（project/ 外）的 repair_status.json，并记录本轮 playtest 的真实入口、操作、观察、截图/日志路径及未验证事项。禁止伪造 playtest、状态、画面、资产结果或 PASS；工具失败如实记录。不得降低需求，不得只复制资产而不接入真实槽位。保留原玩法、入口、ID、组件和既有功能；不修改原始工程、评估工具、数据集或工作区外文件。

playtest 必须包括受影响的实际玩家操作，并按技能录制、观看和复查真实游戏画面。资产检查游戏内模型的外观/比例/朝向/形变和 texture/material；动作检查骨骼、蒙皮、绑定、retarget 与实际播放；VFX 检查真实动作下触发/停止时机、形状与挂点。无骨骼角色需要绑定时阅读 `{FRAMEWORK}/agent_skills/asset_qa/motion/SKILL.md` 并按其流程处理。素材不可用或工具不支持时保留准确阻塞，不假造通过。遵守共享锁和原生输入/进程清理规则，不改造正式评估工具，不启动嵌套 agent。

必须在 `{workspace}/repair_report.md` 逐项记录实际改动文件、playtest 实况、已解决/未解决项和外部阻塞。
''' + _status_contract(game_id, ids, 1)


def next_prompt(game_id: str, engine: str, ids: list, n: int) -> str:
    return (f'继续修复游戏 {game_id}，第 {n}/{MAX_ROUNDS} 轮，继续本会话。沿用已读的 `{SETTING_OVERVIEW}` 框架与 playtest 路由'
            '（上下文缺失时先重读），再读 refine_tasks.json、repair_report.md、repair_status.json 和已有 playtest 证据。'
            '先针对未完成项和上轮观察到的问题作最小必要修改，再按技能做真实 playtest 复测受影响流程。保留之前的有效改动；'
            '不得重做已验证任务、伪造证据、改需求或只做静态检查。更新 repair_report.md 和 repair_status.json。'
            + _ue_note(engine) + _status_contract(game_id, ids, n))


def finished(workspace: Path, ids: list) -> bool:
    """Stop once the agent reports no actionable remaining task (malformed status -> keep going)."""
    path = workspace / 'repair_status.json'
    try:
        status = read_json(path)
        remaining = status.get('remaining_tasks') or []
        seen = list(status.get('completed_task_ids') or []) + [r['task_id'] for r in remaining]
    except (OSError, ValueError, KeyError, TypeError):
        return False
    return sorted(seen) == sorted(ids) and not any(r.get('actionable') for r in remaining)


def prepare_job(model: str, game_id: str, run_id: str | None = None) -> tuple[Job, dict]:
    source = source_project(game_id)
    run_id = run_id or f'{model}_refine_{datetime.now():%Y%m%d_%H%M%S}'
    root = OUTPUT / model_dir(model) / game_id / run_id
    job = Job.load(root)
    if job:
        return job, source
    before = tree_digest(Path(source['root']), IGNORE)
    shutil.copytree(source['root'], root / 'project', ignore=IGNORE)
    if tree_digest(Path(source['root']), IGNORE) != before:
        raise RuntimeError(f'{game_id}: original project changed while copying')
    doc = task_document(game_id)
    write_json(root / 'refine_tasks.json', doc)
    job = Job(stage='stage3', model=model, game_id=game_id, run_id=run_id, run_root=str(root),
              max_rounds=MAX_ROUNDS, notes={'source': {**source, 'digest': before}, 'task_ids': doc['task_ids'],
                                            'prepared_at': now()})
    job.save()
    return job, source


def write_delivery(job: Job) -> None:
    source = job.notes['source']
    if tree_digest(Path(source['root']), IGNORE) != source['digest']:
        raise RuntimeError(f'{job.game_id}: original Sol project changed during refine')
    write_json(job.root / 'delivery.json', {
        'schema': 'bench.delivery.v1', 'stage': 'stage3', 'model': job.model, 'game_id': job.game_id,
        'run_id': job.run_id, 'engine': source['engine'], 'project_root': 'project', 'entry': source['entry'],
        'created_at': now(), 'generator': {'kind': 'bench_script', 'agent': job.model, 'framework_used': True},
        'source': {'path': source['root'], 'sha256_manifest': source['digest'], 'selected_by': source['origin']},
        'rounds_used': len(job.rounds), 'session_id': job.session_id})


def run_job(job: Job, agent, env: dict, dry_run: bool = False) -> Job:
    ws, ids, engine = job.root, job.notes['task_ids'], job.notes['source']['engine']
    return runner.run(job, agent,
                      first_prompt=lambda: first_prompt(job.game_id, ws, engine, ids),
                      next_prompt=lambda n: next_prompt(job.game_id, engine, ids, n),
                      finished=lambda n: finished(ws, ids), cwd=ws, env=env,
                      round_timeout=ROUND_TIMEOUT, on_done=lambda: write_delivery(job), dry_run=dry_run)
