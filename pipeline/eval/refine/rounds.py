"""Bounded source-only repair turns in one GLM conversation per project.

A completed turn is never a product verdict. No evaluator or engine is called here.
Failed/in-flight turns retain their checkpoint and require diagnosed recovery.
"""
from pathlib import Path
from .common import dump, read, sha, once
from .session import inventory, repair, validate_agent


def validate_budget(config):
    from .repair_budget import selected
    selected(config)  # Reject unknown/unauthorized overlays even on legacy entry points.
    rounds = config.get('repair_rounds', 1)
    if type(rounds) is not int or not 1 <= rounds <= 10:
        raise ValueError('repair_rounds must be an integer from 1 through 10 (first repair included)')
    if config.get('interaction_policy') == 'fresh_session_multi_provider_1500s_work_300s_handoff_10attempts.v3':
        from .providers import validate
        validate(config.get('agent', {}))
        return rounds
    if rounds > 1:
        settings = config.get('agent', {})
        validate_agent(settings)
        if settings['provider'] != 'zcode':
            raise ValueError('Multiple repair rounds currently require the resumable ZCode/GLM provider')
        if any(arg == '--resume' or arg.startswith('--resume=') for arg in settings.get('args', [])):
            raise ValueError('Do not configure a shared --resume session; each project creates its own')
    return rounds


def verify_original(folder):
    original = read(Path(folder) / 'original_project.json')
    if inventory(original['root']) != original['files']:
        from ..stage1.unity_safety import SafetyStop
        raise SafetyStop('Original project changed during repair rounds')


def completion_prompt(game, number, limit):
    import json
    ids = [r['selection_id'] for r in game.get('repairs', [])]
    ids += [i['simple']['import_id'] for i in game.get('imports', [])]
    return (f'\n最多{limit}轮是上限，不是必须跑满；全部可做修改完成后立即结束。'
        '本轮结束时在工作区（project/外）写 repair_status.json，严格使用JSON：'
        + json.dumps({'game_id': game['game_id'], 'round': number,
            'completed_task_ids': [], 'remaining_tasks': [
                {'task_id': '未完成的真实ID', 'actionable': True, 'reason': '具体剩余修改或外部阻塞'}]}, ensure_ascii=False)
        + '。所有任务ID必须各出现一次，位于completed_task_ids或remaining_tasks；完整任务ID：'
        + json.dumps(ids, ensure_ascii=False)
        + '。actionable表示仍有可在本工程内实际执行的修改；外部缺资源/工具阻塞写false和真实原因。'
        '该状态仅控制是否继续编辑，不代表运行通过或测评成绩。不得为了轮次产生无关改动。\n')


def turn_location(folder, number):
    folder = Path(folder)
    stage = 'repair' if number == 1 else f'repair_round_{number:03d}'
    root = folder / 'repair_rounds' / f'round_{number:03d}'
    recovery = folder / 'provider_free_handoff.json'
    if recovery.is_file():
        r = read(recovery)
        if r['round'] == number:
            original = folder / 'stages' / (stage + '.json')
            blocked = Path(r['blocked_receipt'])
            if (sha(original) != r['original_marker_sha256'] or
                    sha(blocked) != r['blocked_receipt_sha256'] or
                    read(blocked).get('provider_called') is not False or
                    Path(read(blocked)['workspace']) != folder / 'workspace'):
                raise ValueError('Provider-free handoff provenance changed')
            raw = (folder if number == 1 else root) / 'agent_session/raw/zcode.jsonl'
            if raw.is_file() and raw.read_text().strip():
                raise ValueError('Cannot recover an attempted provider turn as provider-free')
            stage += '_policy_handoff'
            root = root.with_name(root.name + '_policy_handoff')
    return stage, root


def stop_decision(game, folder, root, number):
    """Source-edit completion only; no runtime success or scoring inference."""
    path = Path(root) / 'repair_status.json'
    live = Path(folder) / 'workspace/repair_status.json'
    if not path.exists() and live.is_file():
        try:
            value = read(live)
            if value.get('round') == number and value.get('game_id') == game['game_id']:
                path.write_bytes(live.read_bytes())
        except (ValueError, AttributeError):
            pass
    if not path.is_file():
        return {'stop': False, 'reason': 'MISSING_COMPLETION_REPORT'}
    try:
        value = read(path)
        ids = [r['selection_id'] for r in game.get('repairs', [])]
        ids += [i['simple']['import_id'] for i in game.get('imports', [])]
        completed = value['completed_task_ids']; remaining = value['remaining_tasks']
        reported = completed + [r['task_id'] for r in remaining]
        if (value['round'] != number or value['game_id'] != game['game_id'] or
                len(reported) != len(set(reported)) or set(reported) != set(ids) or
                any(type(r['actionable']) is not bool or not isinstance(r['reason'], str)
                    or not r['reason'].strip() for r in remaining)):
            raise ValueError('Incomplete, stale or invalid task coverage')
        stop = not any(r['actionable'] for r in remaining)
        return {'stop': stop, 'reason': 'EXTERNAL_BLOCKERS_ONLY' if stop and remaining
                else 'SOURCE_WORK_COMPLETE' if stop else 'ACTIONABLE_TASKS_REMAIN',
                'remaining_tasks': remaining, 'completion_report': str(path),
                'completion_report_sha256': sha(path), 'runtime_verdict': None}
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        return {'stop': False, 'reason': 'INVALID_COMPLETION_REPORT', 'error': str(exc)}


def continue_turn(game, folder, config, number, previous):
    from pipeline.data_collection.runtime.live_runner import AgentRunner
    from pipeline.data_collection.core.artifact_store import ArtifactStore
    from .zcode import ZCodeAdapter
    folder = Path(folder)
    settings = config['agent']
    _, root = turn_location(folder, number)
    root.mkdir(parents=True, exist_ok=False)
    verify_original(folder)
    import shutil
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
    dump(root / 'binding.json', {
        'round': number, 'limit': config['repair_rounds'], 'session_id': session_id,
        'model': settings['model'], 'previous_manifest': str(previous),
        'previous_manifest_sha256': sha(previous),
        'initial_identity_sha256': sha(folder / 'agent_identity.json'),
        'evaluation_started': False, 'new_conversation': False})
    prompt = (f'继续修复同一 Sol 项目 {game["game_id"]}，纯修复第{number}/{config["repair_rounds"]}轮。'
        '延续最初全部 mechanic/gamefeel/VFX/导入任务及其冻结边界，只修改当前工作区 project/。'
        '先读 repair_report.md 和已有改动，优先处理未完成项，再检查已修改调用链的具体缺陷。'
        '若前一轮超时，保留当前已写入修改，不重新扫描整个工程，不重做已完成项；尽快收敛并提交状态清单。'
        '工具若返回权限拒绝，不得重复尝试或绕过；使用已允许的读写工具并记录阻塞。'
        '不得为了产生diff而无关重写；没有可做修改就如实报告。'
        '缺失资产保持明确阻塞，不生成替代资产、不降低条件。'
        '本阶段不进行评测：不得启动引擎、浏览器、judge、评估器或嵌套agent；'
        '不读取历史评分/判词；只做源码和资源检查、必要修改。'
        '保留原玩法/入口/ID/功能，禁止修改原交付、测试、评估工具、训练数据和工程外文件。'
        '更新 repair_report.md，逐任务列实际修改路径、未完成项、静态检查与运行未验证事实。'
        '修复会话完成不代表运行PASS，之后由独立测评验证。')
    prompt += completion_prompt(game, number, config['repair_rounds'])
    (root / 'prompt.txt').write_text(prompt, encoding='utf-8')
    adapter = ZCodeAdapter(settings['executable'], [*settings.get('args', []), '--resume', session_id],
                           prompt_name=f'agent_repair_round_{number:03d}.txt')
    runner = AgentRunner(adapter, timeout_seconds=settings.get('timeout_seconds', 7200))
    try:
        trajectory = runner.run(prompt, workspace=folder / 'workspace', run_dir=root / 'agent_session',
            metadata={'game_id': game['game_id'], 'run_id': folder.parent.parent.name + '__' + game['game_id'],
                      'repair_round': number, 'resumed_session_id': session_id}, register=False,
            artifact_store=ArtifactStore(root / 'blobs'), skip_environment=True)
        report = runner.last_report or {}
        dump(root / 'agent_report.json', report)
        observed = adapter.stream_normalizer
        dump(root / 'agent_identity.json', {'session_ids': sorted(observed.session_ids),
            'model': observed.model, 'provider_completed': observed.completed,
            'final_response': observed.final_response})
        if (report.get('status') != 'completed' or report.get('finalization_error') or
                observed.session_ids != {session_id} or observed.model != settings['model'] or not observed.completed):
            raise RuntimeError('Repair turn did not complete in the original session/model; no automatic replacement')
        after = inventory(folder / 'workspace/project')
        dump(root / 'repaired_project.json', {'files': after})
        if (folder / 'workspace/repair_report.md').is_file():
            (root / 'repair_report.md').write_bytes((folder / 'workspace/repair_report.md').read_bytes())
        return {'round': number, 'session_id': session_id, 'trajectory': str(trajectory),
                'manifest': str(root / 'repaired_project.json'),
                'changed_files': sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p)),
                'evaluation_started': False, 'runtime_verdict': None}
    finally:
        verify_original(folder)
        from ..stage1 import unity_safety
        cleanup = unity_safety.locks_clear(config['unity'], check_external=True)
        dump(root / 'cleanup.json', {'locks_clear': cleanup, 'engine_started_by_turn': False})


def repair_project(game, folder, config):
    """Reuse successful turns, refuse failed turns, and count the first repair as 1."""
    from .repair_budget import selected
    if selected(config):
        raise ValueError('Explicit budget recovery must use fresh_sessions.repair_project')
    limit = validate_budget(config)
    folder = Path(folder)
    first_stage, _ = turn_location(folder, 1)
    once(folder, first_stage, lambda: repair(game, folder, config))
    if limit == 1:
        return {'rounds_completed': 1, 'evaluation_started': False}
    if (folder / 'repair_rounds/summary.json').is_file():
        saved = read(folder / 'repair_rounds/summary.json')
        if saved.get('status') == 'REPAIRED':
            if (not 1 <= saved['rounds_completed'] <= limit or
                    inventory(folder / 'workspace/project') != read(saved['final_manifest'])['files'] or
                    sha(saved['final_manifest']) != saved['final_manifest_sha256'] or
                    read(folder / 'repaired_project.json')['files'] != read(saved['final_manifest'])['files']):
                raise ValueError('Completed repair snapshot changed')
            return saved
    if (folder / 'input').exists() or (folder / 'result.json').exists():
        # Never edit a project after evaluation has frozen it. Completed repair
        # invocations can still be reused for evaluating that exact snapshot.
        saved = read(folder / 'repair_rounds/summary.json')
        if saved.get('status') != 'REPAIRED' or not 1 <= saved['rounds_completed'] <= limit:
            raise ValueError('Cannot continue repairs after evaluation started')
        if inventory(folder / 'workspace/project') != read(folder / 'repaired_project.json')['files']:
            raise ValueError('Completed repaired project changed')
        return saved
    first = folder / 'repair_rounds/round_001'
    if not first.exists():
        first.mkdir(parents=True)
        dump(first / 'repaired_project.json', read(folder / 'repaired_project.json'))
        dump(first / 'agent_identity.json', read(folder / 'agent_identity.json'))
        (first / 'agent_report.json').write_bytes((folder / 'agent_report.json').read_bytes())
        if (folder / 'workspace/repair_report.md').is_file():
            (first / 'repair_report.md').write_bytes((folder / 'workspace/repair_report.md').read_bytes())
    first_identity = read(first / 'agent_identity.json')
    if (first_identity != read(folder / 'agent_identity.json') or
            first_identity.get('model') != config['agent']['model'] or
            len(first_identity.get('session_ids', [])) != 1):
        raise ValueError('Original repair session identity changed')
    previous = first / 'repaired_project.json'
    completed = 1
    attempted = 1
    interrupted = []
    decision = stop_decision(game, folder, first, 1)
    for number in range(2, limit + 1):
        if decision['stop']:
            break
        from .interruption import checkpoint
        partial = checkpoint(folder, number, config)
        if partial is not None:
            if (partial['previous_manifest'] != str(previous) or
                    partial['previous_manifest_sha256'] != sha(previous)):
                raise ValueError('Interrupted turn no longer binds previous completed source')
            previous = Path(partial['manifest'])
            attempted = number
            interrupted.append(number)
            decision = {'stop': False, 'reason': 'DIAGNOSED_TIMEOUT_CONTINUE_SAME_SESSION'}
            continue
        verify_original(folder)
        from ..stage1 import unity_safety
        unity_safety.locks_clear(config['unity'], check_external=True)
        stage_name, root = turn_location(folder, number)
        # Persist progress before the next provider call; a kill cannot reset the cap.
        dump(folder / 'repair_rounds/summary.json', {'rounds_completed': completed, 'rounds_attempted': number,
             'interrupted_rounds': interrupted, 'rounds_limit': limit, 'next_round': number, 'evaluation_started': False})
        try:
            result = once(folder, stage_name,
                          lambda n=number, p=previous: continue_turn(game, folder, config, n, p))
        except RuntimeError:
            from .interruption import preserve_timeout
            partial = preserve_timeout(folder, number, previous, config)
            if partial is None:
                raise
            previous = Path(partial['manifest'])
            attempted = number
            interrupted.append(number)
            decision = {'stop': False, 'reason': 'DIAGNOSED_TIMEOUT_CONTINUE_SAME_SESSION'}
            continue
        binding = read(root / 'binding.json')
        if (binding['previous_manifest'] != str(previous) or
                binding['previous_manifest_sha256'] != sha(previous) or
                binding['initial_identity_sha256'] != sha(folder / 'agent_identity.json')):
            raise ValueError('Repair round source/session chain changed')
        previous = root / 'repaired_project.json'
        if result['manifest'] != str(previous):
            raise ValueError('Repair round manifest escaped its frozen round directory')
        observed = read(root / 'agent_identity.json')
        if (observed['session_ids'] != first_identity['session_ids'] or
                observed['model'] != first_identity['model'] or not observed['provider_completed']):
            raise ValueError('Saved turn session/model differs from the original repair')
        completed += 1
        attempted = number
        decision = stop_decision(game, folder, root, number)
    final = read(previous)
    if inventory(folder / 'workspace/project') != final['files']:
        raise ValueError('Final source differs from the last completed repair turn')
    dump(folder / 'repaired_project.json', final)
    result = {'status': 'REPAIRED', 'rounds_completed': completed, 'rounds_attempted': attempted,
              'interrupted_rounds': interrupted, 'rounds_limit': limit,
              'stop_reason': decision['reason'] if decision['stop'] else 'ROUND_LIMIT_REACHED',
              'source_completion': decision,
              'evaluation_started': False, 'runtime_verdict': None,
              'final_manifest': str(previous), 'final_manifest_sha256': sha(previous)}
    dump(folder / 'repair_rounds/summary.json', result)
    return result
