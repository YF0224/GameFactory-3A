"""Create an isolated candidate and the first repair turn of its own agent session."""
from __future__ import annotations
from pathlib import Path
import hashlib
import json
import shutil
from .common import dump, sha, read

# Only generated caches. Keep authored binaries/plugins, assets, save fixtures and metadata.
CACHE_DIRS = {'.git', '.godot', 'node_modules', 'Library', 'Temp', 'Logs', 'DerivedDataCache', 'Intermediate'}


def inventory_digest(files):
    return hashlib.sha256(json.dumps(files, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def inventory(root):
    root = Path(root)
    result = {}
    def visit(folder):
        for path in sorted(folder.iterdir()):
            rel = path.relative_to(root).as_posix()
            if path.is_symlink():
                raise ValueError(f'Project symlink requires explicit safe materialization: {path}')
            if path.is_dir():
                if path.parent != root or path.name not in CACHE_DIRS:
                    visit(path)
            elif path.is_file():
                result[rel] = sha(path)
    visit(root)
    return result


def snapshot_required_bytes(source):
    """Estimate both authored copies using exactly the snapshot's inclusion rule."""
    source = Path(source)
    return 2 * sum((source / relative).stat().st_size for relative in inventory(source))


def snapshot(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination == source or destination.is_relative_to(source):
        raise ValueError('Snapshot must be outside original project')
    if destination.exists():
        raise FileExistsError(destination)
    before = inventory(source)
    destination.mkdir(parents=True)
    for relative in before:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / relative, target)
    if inventory(destination) != before or inventory(source) != before:
        raise ValueError('Snapshot copy changed or source changed during snapshot')
    return before


def combined_prompt(game, workspace, payloads):
    # Never deliver evaluator-only slot guesses, prior scores or evidence wiring to repair agent.
    simple = [{**item['simple'], 'selected_project': {**game['project'],
               'project_root': str(Path(workspace) / 'project'), 'launch_entry': None},
               'resolved_payload': {k: v for k, v in payloads.get(item['simple']['import_id'], {}).items()
                                    if k != 'frozen_path'}}
              for item in game['imports']]
    import json
    repairs = [{k: item[k] for k in ('selection_id', 'selection_kind', 'repair_goal',
                                     'test_action', 'pass_condition')} for item in game['repairs']]
    vfx = [{k: item.get(k) for k in ('selection_id', 'repair_boundary', 'effect_type', 'trigger',
            'stop_condition', 'particle_system_required', 'acceptance_criteria', 'runtime_evidence_required')}
            for item in game['repairs'] if item['selection_kind'] == 'vfx']
    return f'''修复并导入游戏 {game['game_id']}。本次只用这一个会话完成全部任务。
唯一允许修改的游戏工程：{workspace}/project。原交付禁止修改。资产在本工作区 assets/。
保持真实玩法、入口、ID、组件、碰撞和触发时序；不能伪造状态/录像/截图或降低验收条件。
所有 Mechanic、Gamefeel、VFX 要求都要实际实现；不能仅生成计划。导入资源必须接入游戏真实槽位，
不能只复制文件。几何资产保留原材质/纹理/比例/轴向，检查蒙皮变形、白膜/粉材质和穿模。
缺失或歧义资产要报告阻塞，不生成假替代、不阻塞其他可做修复。音频、动作、视频按各自类型集成。
禁止 OS 键鼠、窗口激活、前台回退、修改 evaluator/测试或原始交付。不得启动引擎；真实录制由外部已验收
adapter 执行。只做源码/资源导入修改和不启动引擎的检查。不得调用嵌套编辑 agent 会话。
结束时在工作区 repair_report.md 列出每个任务的改动路径、真实入口、尚未解决问题，不自行宣布测评分。
修复任务：{json.dumps(repairs, ensure_ascii=False)}
VFX 原始边界与验收：{json.dumps(vfx, ensure_ascii=False)}
资产导入任务：{json.dumps(simple, ensure_ascii=False)}
'''


def validate_agent(settings):
    """Fail before copying/editing when a declared model cannot be enforced."""
    provider = settings.get('provider', 'codex')
    model = settings.get('model')
    if provider == 'zcode':
        if not isinstance(model, str) or not model.strip():
            raise ValueError('ZCode requires exact agent.model and --expected-model')
        args = settings.get('args', [])
        values = [args[i + 1] for i, v in enumerate(args[:-1]) if v == '--expected-model']
        if values != [model]:
            raise ValueError('ZCode args must enforce agent.model exactly once via --expected-model')
    elif model:
        raise ValueError('agent.model is not wired for this provider; configure an enforced provider instead')
    if not settings.get('provider') or not settings.get('executable'):
        raise ValueError('Explicit agent.provider and agent.executable required; no default fallback')


def repair(game, folder, config):
    from pipeline.data_collection.adapters import get_adapter
    from pipeline.data_collection.runtime.live_runner import AgentRunner
    from pipeline.data_collection.core.artifact_store import ArtifactStore
    from .rounds import validate_budget
    validate_budget(config)
    validate_agent(config.get('agent', {}))
    folder = Path(folder)
    workspace = folder / 'workspace'
    source = Path(game['project']['project_root'])
    import shutil as _disk
    estimate = snapshot_required_bytes(source)
    free = _disk.disk_usage(folder).free
    dump(folder / 'disk_before_repair.json', {'free_bytes': free, 'estimated_bytes': estimate,
         'reserve_bytes': 8 * 1024**3})
    if free < estimate + 8 * 1024**3:
        raise RuntimeError('Insufficient disk for isolated repair plus 8GiB reserve')
    from .rounds import turn_location
    initial_stage, _ = turn_location(folder, 1)
    provider_free = initial_stage != 'repair'
    if provider_free:
        saved_original = read(folder / 'original_project.json')
        original = saved_original['files']
        if (Path(saved_original['root']) != source or inventory(source) != original or
                inventory(workspace / 'project') != original):
            raise ValueError('Provider-free first-turn workspace is not pristine author delivery')
    else:
        original = snapshot(source, workspace / 'project')
    dump(folder / 'original_project.json', {'root': str(source), 'files': original,
                                          'omitted_generated_directories': sorted(CACHE_DIRS)})
    payloads = {}
    for item in game['imports']:
        payload, simple = item['payload'], item['simple']
        ident = simple['import_id']
        if payload['status'] != 'READY':
            payloads[ident] = {'status': payload['status']}
            continue
        src = Path(payload['path'])
        if sha(src) != payload['sha256']:
            raise ValueError('Payload changed after prepare: ' + str(src))
        # Preserve pristine evaluator copy outside editing workspace.
        relative = Path('assets') / simple['task_id'] / src.name
        for base in (folder / 'frozen', workspace):
            dst = base / relative
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            if sha(dst) != payload['sha256']:
                raise ValueError('Payload copy mismatch')
        payloads[ident] = {'status': 'READY', 'path': str(workspace / relative),
                          'frozen_path': str(folder / 'frozen' / relative), 'sha256': payload['sha256']}
    dump(folder / 'payloads.json', payloads)
    # Resolve current contracts beside the actually selected project. An old initial-game index
    # may reference a different run (G050); preserve that provenance, do not copy stale contracts.
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
    prompt = combined_prompt(game, workspace, payloads)
    requirements = game.get('requirement_binding')
    if requirements:
        text = Path(requirements['path']).read_text()
        if sha(requirements['path']) != requirements['sha256']:
            raise ValueError('Original requirements changed')
        prompt += '\n原始完整需求（不可改写）：\n' + text
    prompt += '\n限制修改为本轮任务所必需；禁止无关重写、替换引擎或删除已有功能。报告区分静态检查、未执行运行验证和未解决问题。\n'

    rounds = config.get('repair_rounds', 1)
    if rounds > 1:
        prompt += (f'\n这是本项目纯修复第1轮，上限{rounds}轮；若有剩余可做修改，后续续接同一会话。'
                   '本轮只修改真实工程和检查源码/资源，不运行测评、judge或引擎，不读取历史分数。'
                   '按现有优先级尽可能完成修复，并报告下一轮仍需做的任务；不能宣称运行PASS。\n')
    if rounds > 1:
        from .rounds import completion_prompt
        prompt += completion_prompt(game, 1, rounds)
    (folder / 'repair_prompt.txt').write_text(prompt, encoding='utf-8')
    settings = config.get('agent', {})
    if settings.get('provider') == 'zcode':
        from .zcode import ZCodeAdapter
        adapter = ZCodeAdapter(settings['executable'], settings.get('args', []))
    else:
        adapter = get_adapter(settings.get('provider', 'codex'), executable=settings.get('executable'),
                              extra_args=tuple(settings.get('args', [])))
    runner = AgentRunner(adapter, timeout_seconds=settings.get('timeout_seconds', 7200))
    session_dir = folder / ('agent_session_policy_handoff' if provider_free else 'agent_session')
    try:
        trajectory = runner.run(prompt, workspace=workspace, run_dir=session_dir,
            metadata={'game_id': game['game_id'], 'run_id': folder.parent.name + '__' + game['game_id']},
            register=False, artifact_store=ArtifactStore(folder / 'blobs'), skip_environment=True)
    finally:
        if inventory(source) != original:
            from ..stage1.unity_safety import SafetyStop
            raise SafetyStop('Original project changed during agent session')
    report = runner.last_report or {}
    dump(folder / 'agent_report.json', report)
    if report.get('status') != 'completed' or report.get('finalization_error'):
        raise RuntimeError('Repair session failed; no automatic second conversation: ' + str(report))
    if settings.get('provider') == 'zcode':
        observed = adapter.stream_normalizer
        identity = {'session_ids': sorted(observed.session_ids), 'model': observed.model,
                    'provider_completed': observed.completed, 'final_response': observed.final_response}
        dump(folder / 'agent_identity.json', identity)
        if len(observed.session_ids) != 1 or observed.model != settings.get('model') or not observed.completed:
            raise RuntimeError('ZCode did not complete exactly one session with the configured model; see agent_identity.json')
    repaired = inventory(workspace / 'project')
    dump(folder / 'repaired_project.json', {'files': repaired})
    return {'trajectory': str(trajectory), 'workspace': str(workspace),
            'changed_files': sorted(k for k in set(original) | set(repaired) if original.get(k) != repaired.get(k))}
