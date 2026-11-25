#!/usr/bin/env python3
"""Run only the Stage3 repair stage; evaluation has a separate entry point."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import math
import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parents[1]
FRAMEWORK = BENCH
sys.path.insert(0, str(FRAMEWORK))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from stage3_run_layout import bind_candidate_run

from pipeline.game_eval.refine.batch import normalize, run, exclusive
from pipeline.game_eval.refine.rounds import completion_prompt as _task_status_prompt
from pipeline.game_eval.refine.common import read
from pipeline.game_eval.refine.providers import POLICY as MULTI_PROVIDER_POLICY

SETTING_OVERVIEW = FRAMEWORK / 'agent_skills/setting_overview.md'
MAX_INTERACTION_SECONDS = 30 * 60
MAX_REPAIR_ATTEMPTS = 10
LEGACY_INTERACTION_POLICY = 'agent_turn_1800s_10attempts.v1'
INTERACTION_POLICY = 'fresh_session_1500s_work_300s_handoff_10attempts.v2'


def _interaction_timeout(config):
    """Apply the hard cap even when resuming a frozen older configuration."""
    requested = config['agent'].get('timeout_seconds', MAX_INTERACTION_SECONDS)
    if (type(requested) not in (int, float) or not math.isfinite(requested)
            or requested <= 0):
        raise ValueError('agent.timeout_seconds must be a finite positive number')
    return min(requested, MAX_INTERACTION_SECONDS)


def _validate_generation_budget(config):
    from pipeline.game_eval.refine.rounds import validate_budget
    limit = validate_budget(config)
    prior = config.get('explicit_restart', {}).get('prior_counted_attempts', 0)
    if type(prior) is not int or prior < 0 or prior + limit > MAX_REPAIR_ATTEMPTS:
        raise ValueError('Repair would exceed the cumulative ten-attempt budget')
    return limit


def _generation_config(raw):
    """Freeze effective limits for new batches; never rewrite an existing batch."""
    config = normalize(raw)
    config.setdefault('repair_rounds', MAX_REPAIR_ATTEMPTS)
    _validate_generation_budget(config)
    config['agent']['timeout_seconds'] = _interaction_timeout(config)
    return config


def _validate_execution_mode(config):
    """Reject known read-only ZCode modes before starting a repair attempt."""
    args = config['agent'].get('args', [])
    for index, arg in enumerate(args):
        mode = args[index + 1] if arg == '--mode' and index + 1 < len(args) else (
            arg.split('=', 1)[1] if arg.startswith('--mode=') else None)
        if mode in ('edit', 'plan'):
            raise ValueError('Real repair/playtest requires an executable ZCode mode, not ' + mode)


def _task_ids(game):
    return ([row['selection_id'] for row in game.get('repairs', [])] +
            [item['simple']['import_id'] for item in game.get('imports', [])])


def _task_document(game, payloads):
    """Keep the full frozen task rows alongside resolved payload delivery metadata."""
    repairs = [{k: row.get(k) for k in ('selection_id', 'selection_kind', 'repair_goal',
                'test_action', 'pass_condition', 'trigger', 'stop_condition',
                'acceptance_criteria', 'runtime_evidence_required', 'repair_boundary',
                'effect_type', 'particle_system_required', 'parent_context')}
               for row in game.get('repairs', [])]
    imports = []
    for item in game.get('imports', []):
        simple = item['simple']
        payload = payloads.get(simple['import_id'], {})
        imports.append({
            'import_id': simple['import_id'], 'task_id': simple.get('task_id'),
            'asset_kind': simple.get('asset_kind'), 'requirement': simple,
            'payload_status': payload.get('status'), 'asset_path': payload.get('path'),
            'asset_sha256': payload.get('sha256'),
            'acceptance': {key: item.get('detail', {}).get(key) for key in (
                'import_goal', 'acceptance_criteria', 'runtime_evidence_required',
                'trigger_contract', 'motion_contract', 'dependencies', 'replacement_guide')},
        })
    return {'schema': 'stage3.refine-tasks.v1', 'game_id': game['game_id'],
            'task_ids': _task_ids(game), 'repairs': repairs, 'imports': imports,
            'original_repairs': game.get('repairs', []),
            'original_imports': game.get('imports', []),
            'requirement_binding': game.get('requirement_binding')}


def _write_task_document(game, workspace, payloads):
    from pipeline.game_eval.refine.common import dump, sha
    workspace = Path(workspace)
    document = _task_document(game, payloads)
    requirements = game.get('requirement_binding')
    if requirements:
        if sha(requirements['path']) != requirements['sha256']:
            raise ValueError('Original requirements changed')
        document['original_requirements_text'] = Path(requirements['path']).read_text(encoding='utf-8')
    path = workspace / 'refine_tasks.json'
    # A task handoff must never replace an earlier, source-bound handoff.
    if path.exists():
        raise FileExistsError(path)
    dump(path, document)
    return path


def _ue54_prompt(game):
    if game.get('project', {}).get('engine') not in ('ue5', 'ue', 'unreal', 'unreal5'):
        return ''
    return ('\nUE refine 统一使用 UE 5.4 构建并启动；本机 UE_ROOT / A3GAME_UE_ROOT 为 '
            '`/Users/Shared/Epic Games/UE_5.4`（5.4.4）。允许并要求在当前候选内修复引擎兼容问题，'
            '包括将不支持的 BuildSettingsVersion.V6 适配为 V5、IncludeOrderVersion 适配为 '
            'EngineIncludeOrderVersion.Unreal5_4，以及其他实际编译/API/插件兼容问题；原作者交付只读。'
            '先保存并检查 Build.sh/UnrealBuildTool 的真实退出码及编译日志，再启动本候选；'
            '不得把后续 echo/tail 的成功退出当成构建通过，不以更换游戏入口或伪造玩法掩盖兼容错误。\n')


def _prompt(game, workspace, payloads, limit=10):
    actual_project = (Path(workspace) / 'project').resolve()
    return f'''你是游戏 {game['game_id']} 的唯一修复 agent。只修改当前工作区 `{workspace}/project`，原始作者工程只读。
工程实际落盘于原游戏目录下的新 run_id：`{actual_project}`；当前工作区 project 是指向该候选的兼容入口，修改会直接落盘到新 run。
{_ue54_prompt(game)}

执行顺序（同一个会话、同一次 repair 调用内顺序完成）：
1. 先完整阅读 `{SETTING_OVERVIEW}`，理解 GameFactory-3A 的框架、分层和技能路由，确认 playtest 属于本次 refine 的“修复—验证—再修复”闭环。此时先理解框架，再打开下一步的任务文件；只按该文件路由查对应引擎和本次任务所需技能，不泛读历史批次或排查无关环境。
2. 然后读取 `{workspace}/refine_tasks.json`，这是本游戏本次需要修复的完整 JSON 交付，包含原始条目、验收、资产路径和全部 task ID。逐项理解 mechanic、gamefeel、import、texture、VFX、motion/绑骨/retarget 任务，定位对应工程代码与资产；不得仅凭文件名或任务编号猜需求。
3. 开始针对 JSON 问题作最小必要修复，并按 overview 路由找到对应引擎的 playtest，进行构建/启动、实际操作、录制/观看、修复及复查。可以先针对已知问题修改再 playtest，也可以先 playtest 复现；不把整个环境/权限排查完毕设为所有修改的前置条件。某项资源或工具确实阻塞时逐项记录原因和未验证事实，继续其他可做任务；不得反复查旧日志代替修改，不申请或尝试 OS 键鼠/窗口激活回退。

本次你同时承担 refine 与 Execution/playtest：技能中针对“仅生成 agent 不启动引擎”的一般分工不适用于本次明确授权。允许并要求启动本项目引擎、构建、运行技能规定的 playtest。最终独立 evaluator/judge 由另一脚本执行，本次不得调用；不得用静态检查冒充 playtest。

修复必须覆盖下列全部被选任务及其原始验收，不得只写计划或报告。mechanic、gamefeel、VFX 和导入任务共享本项目最多 {limit} 次 repair attempt（含超时/中断的已发起调用），可提前结束，不要求跑满。每轮使用本游戏同一个 agent 会话；每轮结束更新当前工作区根目录（project/ 外）的 repair_status.json，逐个任务列已完成和未完成/阻塞，并记录本轮 playtest 的真实入口、操作、观察、截图/日志路径及未验证事项。禁止伪造 playtest、状态、画面、资产结果或 PASS；工具失败如实记录，不得冒充产品失败。不得降低需求，不得只复制资产而不接入真实槽位。保留原玩法、入口、ID、组件和既有功能；不修改原始工程、测试、评估工具、数据集或工作区外文件。

playtest 必须包括受影响的实际玩家操作，并按技能录制、观看和复查真实游戏画面。资产检查原始 GLB 与游戏内模型的外观/比例/朝向/形变和 texture/material；动作检查骨骼、蒙皮、绑定、retarget 与实际播放；VFX 检查真实动作下触发/停止时机、形状与挂点。无骨骼角色需要绑定时阅读 `GameFactory-3A/agent_skills/asset_qa/motion/SKILL.md` 并按其流程处理，不猜关节。素材不可用或工具确实不支持时保留准确阻塞及未验证项，不假造通过。只读使用技能规定的正式 playtest 工具，遵守共享锁和原生输入/进程清理规则，不得改造正式评估工具或启动嵌套编辑 agent。

必须在 `{workspace}/repair_report.md` 逐项记录实际改动文件、playtest 实况、已解决/未解决项和外部阻塞。所有 task ID 恰好出现一次，写入 repair_status.json 的 completed_task_ids 或 remaining_tasks：\n完整 task ID 与原始验收以 refine_tasks.json 为准。\n'''


def _completion_prompt(game, number, limit, timeout_seconds=MAX_INTERACTION_SECONDS):
    return (_task_status_prompt(game, number, limit)
            + _ue54_prompt(game)
            + f'\n本轮交互最长 {timeout_seconds:g} 秒（上限30分钟），完成可做工作后立即提交结果并结束回复，不必用满时间。'
            '一次交互从收到本轮指令开始，到你结束回复、交回控制权为止；期间多次工具调用、修改、构建和 playtest 都属于同一轮。'
            '在时间上限前留出保存修改、repair_status.json、repair_report.md、真实证据和清理本轮自有引擎进程的时间。'
            '超时或中断的已发起调用仍占用一次尝试，保留有效改动和未完成项，后续继续同一会话，不重置预算。'
            + '\n遵守先理解 setting_overview、再读 refine_tasks.json、按任务修复与 playtest 复查的顺序。'
            '本轮须实际游玩并复查受影响流程，不得用静态检查替代。'
            '在 repair_report.md 记录操作、观察、真实证据路径、未测试项和阻塞。'
            '遵守技能的原生输入、资源/进程清理和共享执行锁要求，不干扰其他任务。'
            '不得启动最终独立评估或 judge；本轮修复状态不等于正式测评成绩。\n')


def _prepare_project(game, folder, config):
    """Prepare one candidate and its immutable source/task bindings; no model call."""
    import shutil
    from pipeline.game_eval.refine.session import snapshot, snapshot_required_bytes, CACHE_DIRS, inventory, inventory_digest
    from pipeline.game_eval.refine.common import dump, sha
    limit = _validate_generation_budget(config)
    timeout_seconds = _interaction_timeout(config)
    settings = config['agent']
    if settings.get('provider') != 'zcode' and config.get('interaction_policy') != MULTI_PROVIDER_POLICY:
        raise ValueError('This resumable generation entry currently requires the ZCode provider')
    folder = Path(folder)
    workspace = folder / 'workspace'
    source = Path(game['project']['project_root'])
    expected = config.get('frozen_project_sources', {}).get(game['game_id'])
    if expected and inventory_digest(inventory(source)) != expected:
        raise ValueError('Original project differs from frozen matrix source')
    required = snapshot_required_bytes(source) + 2 * sum(
        Path(i['payload']['path']).stat().st_size for i in game.get('imports', [])
        if i['payload']['status'] == 'READY')
    free = shutil.disk_usage(folder).free
    dump(folder / 'disk_before_repair.json', {'free_bytes': free, 'estimated_bytes': required,
         'reserve_bytes': 8 * 1024**3})
    if free < required + 8 * 1024**3:
        raise RuntimeError('Insufficient disk for isolated repair plus 8GiB reserve')
    bind_candidate_run(game, folder, config)
    original = snapshot(source, workspace / 'project')
    if expected and inventory_digest(original) != expected:
        raise ValueError('Original project changed while preparing matrix candidate')
    dump(folder / 'original_project.json', {'root': str(source), 'files': original,
                                          'omitted_generated_directories': sorted(CACHE_DIRS)})
    payloads = {}
    for item in game.get('imports', []):
        simple, payload = item['simple'], item['payload']
        ident = simple['import_id']
        if payload['status'] != 'READY':
            payloads[ident] = {'status': payload['status']}
            continue
        src = Path(payload['path'])
        if sha(src) != payload['sha256']:
            raise ValueError('Payload changed after prepare: ' + str(src))
        relative = Path('assets') / simple['task_id'] / src.name
        for base in (folder / 'frozen', workspace):
            target = base / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
            if sha(target) != payload['sha256']:
                raise ValueError('Payload copy mismatch')
        payloads[ident] = {'status': 'READY', 'path': str(workspace / relative),
            'frozen_path': str(folder / 'frozen' / relative), 'sha256': payload['sha256']}
    dump(folder / 'payloads.json', payloads)
    contracts = []
    for name in ('mechanic_contract.json', 'ui_contract.json', 'scene_manifest.json',
                 'asset_slots.json', 'placeholder_registry.json'):
        src = source.parent / name
        if src.is_file():
            target = workspace / 'contracts' / name
            target.parent.mkdir(exist_ok=True)
            shutil.copy2(src, target)
            contracts.append({'path': str(src), 'sha256': sha(src), 'copy': str(target)})
    dump(folder / 'contract_bindings.json', contracts)
    task_path = _write_task_document(game, workspace, payloads)
    dump(folder / 'task_handoff.json', {'path': str(task_path), 'sha256': sha(task_path),
         'task_ids': _task_ids(game), 'delivery': 'file_read_after_framework_in_same_turn',
         'extra_agent_calls': 0})


def _repair_first(game, folder, config):
    """Dispatch a first turn with no source-only restrictions appended by legacy code."""
    import shutil
    from pipeline.data_collection.runtime.live_runner import AgentRunner
    from pipeline.data_collection.core.artifact_store import ArtifactStore
    from pipeline.game_eval.refine.zcode import ZCodeAdapter
    from pipeline.game_eval.refine.session import inventory, snapshot, snapshot_required_bytes, CACHE_DIRS
    from pipeline.game_eval.refine.rounds import verify_original
    from pipeline.game_eval.refine.common import dump, sha

    _prepare_project(game, folder, config)
    limit = _validate_generation_budget(config)
    timeout_seconds = _interaction_timeout(config)
    settings = config['agent']
    folder = Path(folder)
    workspace = folder / 'workspace'
    payloads = read(folder / 'payloads.json')
    prompt = _prompt(game, workspace, payloads, limit)
    prompt += _completion_prompt(game, 1, limit, timeout_seconds)
    (folder / 'repair_prompt.txt').write_text(prompt, encoding='utf-8')
    adapter = ZCodeAdapter(settings['executable'], settings.get('args', []),
                           prompt_name='agent_playtest_round_001.txt')
    runner = AgentRunner(adapter, timeout_seconds=timeout_seconds)
    try:
        trajectory = runner.run(prompt, workspace=workspace, run_dir=folder / 'agent_session',
            metadata={'game_id': game['game_id'], 'run_id': folder.parent.name + '__' + game['game_id'],
                      'repair_round': 1, 'interaction_timeout_seconds': timeout_seconds}, register=False,
            artifact_store=ArtifactStore(folder / 'blobs'), skip_environment=True)
    finally:
        dump(folder / 'agent_report.json', runner.last_report or {})
        observed = adapter.stream_normalizer
        dump(folder / 'agent_identity.json', {'session_ids': sorted(observed.session_ids),
            'model': observed.model, 'provider_completed': observed.completed,
            'final_response': observed.final_response})
        verify_original(folder)
    report = runner.last_report or {}
    if (report.get('status') != 'completed' or report.get('finalization_error') or
            len(observed.session_ids) != 1 or observed.model != settings['model'] or not observed.completed):
        raise RuntimeError('First repair turn did not complete; preserve this attempt/session before recovery')
    original = read(folder / 'original_project.json')['files']
    repaired = inventory(workspace / 'project')
    dump(folder / 'repaired_project.json', {'files': repaired})
    return {'trajectory': str(trajectory), 'workspace': str(workspace),
            'changed_files': sorted(k for k in set(original) | set(repaired)
                                    if original.get(k) != repaired.get(k))}


def _continue_turn(game, folder, config, number, previous):
    """Continue the same ZCode session with the same playtest contract."""
    from pipeline.data_collection.runtime.live_runner import AgentRunner
    from pipeline.data_collection.core.artifact_store import ArtifactStore
    from pipeline.game_eval.refine.zcode import ZCodeAdapter
    from pipeline.game_eval.refine.rounds import turn_location, verify_original
    from pipeline.game_eval.refine.session import inventory
    from pipeline.game_eval.refine.common import dump, sha, read
    import shutil

    limit = _validate_generation_budget(config)
    if type(number) is not int or not 2 <= number <= limit:
        raise ValueError('Continuation round must be within the configured attempt budget')
    timeout_seconds = _interaction_timeout(config)
    folder = Path(folder)
    settings = config['agent']
    _, root = turn_location(folder, number)
    root.mkdir(parents=True, exist_ok=False)
    verify_original(folder)
    free = shutil.disk_usage(folder).free
    dump(root / 'disk_before_repair.json', {'free_bytes': free, 'reserve_bytes': 8 * 1024**3})
    if free < 8 * 1024**3:
        raise RuntimeError('Insufficient disk for another repair turn plus 8GiB reserve')
    before = inventory(folder / 'workspace/project')
    if before != read(previous)['files']:
        raise ValueError('Project changed outside completed repair turns')
    identity = read(folder / 'agent_identity.json')
    if len(identity['session_ids']) != 1 or identity['model'] != settings['model']:
        raise ValueError('Missing unique original repair session/model')
    session_id = identity['session_ids'][0]
    dump(root / 'binding.json', {'round': number, 'limit': config['repair_rounds'],
        'session_id': session_id, 'model': settings['model'], 'previous_manifest': str(previous),
        'previous_manifest_sha256': sha(previous),
        'initial_identity_sha256': sha(folder / 'agent_identity.json'), 'evaluation_started': False,
        'new_conversation': False, 'prompt_sha256': sha(Path(__file__)),
        'interaction_timeout_seconds': timeout_seconds})
    prompt = (f'继续修复游戏 {game["game_id"]}，第 {number}/{config["repair_rounds"]} 次修复尝试，必须继续原 agent 会话。'
        f'沿用已读的 `{SETTING_OVERVIEW}` 框架与 playtest 路由（上下文缺失时先重读），'
        '再读 `refine_tasks.json`、`repair_report.md`、`repair_status.json` 和已有 playtest 证据。'
        '沿用原任务和验收，按技能规定再次进行真实 playtest，先针对未完成项和上轮观察到的问题作最小必要修改，再复测受影响流程。'
        '保留超时/中断前的有效改动；不得重做已验证任务、伪造证据、改需求或只做静态检查。'
        '更新 repair_report.md 和 repair_status.json，逐任务写明真实 playtest 观察与未解决项。'
        + _completion_prompt(game, number, config['repair_rounds'], timeout_seconds))
    (root / 'prompt.txt').write_text(prompt, encoding='utf-8')
    adapter = ZCodeAdapter(settings['executable'], [*settings.get('args', []), '--resume', session_id],
                           prompt_name=f'agent_repair_round_{number:03d}.txt')
    runner = AgentRunner(adapter, timeout_seconds=timeout_seconds)
    try:
        trajectory = runner.run(prompt, workspace=folder / 'workspace', run_dir=root / 'agent_session',
            metadata={'game_id': game['game_id'], 'repair_round': number,
                      'resumed_session_id': session_id,
                      'interaction_timeout_seconds': timeout_seconds}, register=False,
            artifact_store=ArtifactStore(root / 'blobs'), skip_environment=True)
        report = runner.last_report or {}
        dump(root / 'agent_report.json', report)
        observed = adapter.stream_normalizer
        dump(root / 'agent_identity.json', {'session_ids': sorted(observed.session_ids),
            'model': observed.model, 'provider_completed': observed.completed,
            'final_response': observed.final_response})
        if (report.get('status') != 'completed' or report.get('finalization_error') or
                observed.session_ids != {session_id} or observed.model != settings['model'] or
                not observed.completed):
            raise RuntimeError('Repair turn did not complete in the original session/model')
        after = inventory(folder / 'workspace/project')
        dump(root / 'repaired_project.json', {'files': after})
        report_path = folder / 'workspace/repair_report.md'
        if report_path.is_file():
            (root / 'repair_report.md').write_bytes(report_path.read_bytes())
        dump(root / 'turn_receipt.json', {'round': number, 'session_id': session_id,
            'trajectory': str(trajectory), 'changed_files': sorted(
                p for p in set(before) | set(after) if before.get(p) != after.get(p)),
            'playtest_required_by_prompt': True, 'evaluation_started': False,
            'interaction_timeout_seconds': timeout_seconds})
        return {'round': number, 'session_id': session_id, 'manifest': str(root / 'repaired_project.json'),
                'evaluation_started': False, 'runtime_verdict': None}
    finally:
        verify_original(folder)
        from pipeline.game_eval.whitebox_eval import unity_safety
        cleanup = unity_safety.locks_clear(config['unity'], check_external=True)
        dump(root / 'cleanup.json', {'locks_clear': cleanup})


@contextmanager
def _generation_dispatch(policy=LEGACY_INTERACTION_POLICY):
    """Use the new prompt dispatch only within this CLI; frozen legacy code stays intact."""
    from pipeline.game_eval.refine import rounds
    original_first, original_continue = rounds.repair, rounds.continue_turn
    original_project = rounds.repair_project
    try:
        rounds.repair = _repair_first
        rounds.continue_turn = _continue_turn
        if policy in (INTERACTION_POLICY, MULTI_PROVIDER_POLICY):
            from pipeline.game_eval.refine.fresh_sessions import repair_project
            rounds.repair_project = lambda game, folder, config: repair_project(
                game, folder, config, prepare=_prepare_project,
                instructions=lambda g: _ue54_prompt(g), overview=SETTING_OVERVIEW)
        yield
    finally:
        rounds.repair, rounds.continue_turn = original_first, original_continue
        rounds.repair_project = original_project


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True,
                        help='Frozen repair batch directory; never point this at an author project')
    parser.add_argument('--mode', choices=('prepare', 'repair'), default='prepare')
    parser.add_argument('--matrix-migration', type=Path, help='Explicit ACTIVE migration; repair only')
    parser.add_argument('--interaction-policy', choices=(INTERACTION_POLICY, LEGACY_INTERACTION_POLICY, MULTI_PROVIDER_POLICY),
                        default=INTERACTION_POLICY)
    args = parser.parse_args(argv)

    raw = read(args.config)
    if not args.matrix_migration and args.interaction_policy in (INTERACTION_POLICY, MULTI_PROVIDER_POLICY):
        raw['interaction_policy'] = args.interaction_policy
    migration_record = None
    if args.matrix_migration:
        if args.mode != 'repair':
            parser.error('Matrix migration applies only to repair')
        from refine.recovery import verify_migration, runtime_config
        child_output = args.output.expanduser().resolve()
        matrix_output = child_output.parents[2]
        migration_record = verify_migration(args.matrix_migration, matrix_output)
        job_id = child_output.parent.name + '/' + child_output.name
        expected_raw = migration_record['original_configs'][job_id]
        if raw != expected_raw:
            raise ValueError('CLI configuration differs from frozen matrix identity')
        if args.interaction_policy != expected_raw.get('interaction_policy'):
            raise ValueError('Migration cannot change the frozen interaction policy')
        raw = runtime_config(migration_record, job_id)
    config = _generation_config(raw)
    if args.mode == 'repair':
        _validate_execution_mode(config)
    if config['agent'].get('provider') != 'zcode' and args.interaction_policy != MULTI_PROVIDER_POLICY:
        parser.error('This entry requires a resumable ZCode provider with an explicit model')
    if not SETTING_OVERVIEW.is_file():
        parser.error(f'Missing required agent workflow instructions: {SETTING_OVERVIEW}')
    output = args.output.expanduser().resolve()
    from pipeline.game_eval.refine.common import dump, sha
    prompt_identity = output / 'stage3_prompt_identity.json'
    current_identity = {'script_sha256': sha(Path(__file__)),
                        'setting_overview_sha256': sha(SETTING_OVERVIEW),
                        'playtest_contract': 'agent_skill_routed_real_playtest.v1',
                        'interaction_policy': args.interaction_policy,
                        'run_layout_sha256': sha(Path(__file__).with_name('stage3_run_layout.py'))}
    with exclusive(output.parent / (output.name + '.batch.lock')):
        if prompt_identity.exists() and read(prompt_identity) != current_identity:
            if migration_record is None:
                raise ValueError('Stage3 prompt/setting instructions changed; preserve this run and create a new explicit identity')
            previous_identity = read(prompt_identity)
            if any(previous_identity[k] != current_identity[k] for k in current_identity if k != 'script_sha256'):
                raise ValueError('Migration cannot change frozen prompt semantics or layout')
            from pipeline.game_eval.refine.migration import verify_runtime_config
            from pipeline.game_eval.refine.batch import code_identity
            verify_runtime_config(output, config, code_identity())
            migration = read(output / 'implementation_migration.json')
            old_script = migration['from_prompt_script']
            if sha(old_script['path']) != old_script['sha256'] or old_script['sha256'] != previous_identity['script_sha256']:
                raise ValueError('Missing original prompt script source binding')
        if not prompt_identity.exists():
            if any(output.glob('games/*/stages/repair*.json')):
                raise ValueError('Legacy repair history requires an explicit same-session migration; attempts cannot reset')
            dump(prompt_identity, current_identity)
        with _generation_dispatch(args.interaction_policy):
            result = run(config, output, args.mode)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    failed = {'ERROR', 'SAFETY_STOP', 'BLOCKED_NO_PROJECT'}
    return 2 if args.mode == 'repair' and any(
        isinstance(value, dict) and value.get('status') in failed for value in result.values()) else 0


if __name__ == '__main__':
    import signal
    def stop(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    from pipeline.game_eval.whitebox_eval.unity_safety import SafetyStop
    try:
        raise SystemExit(main())
    except (BlockingIOError, SafetyStop) as exc:
        print(f'SAFETY_STOP: {exc}', file=sys.stderr)
        raise SystemExit(75)
