"""Stage3 round rotation with durable project handoffs and one cumulative budget.

Each round has a fresh work session and, if time remains, one continuation of
that session solely for handoff/cleanup. Both subcalls consume the same round.
An unclosed claim is never retried automatically.
"""
from pathlib import Path
import shutil
import time
from .common import dump, read, sha
from .session import inventory
from .rounds import validate_budget, verify_original, completion_prompt, stop_decision

POLICY = 'fresh_session_1500s_work_300s_handoff_10attempts.v2'


def invoke(config, workspace, root, prompt, seconds, *, session=None):
    from pipeline.data_collection.runtime.live_runner import AgentRunner
    from pipeline.data_collection.core.artifact_store import ArtifactStore
    if config.get('repair_execution_policy'):
        from ..stage1.repair_execution import active_scope
        scope = active_scope()
        if scope is None:
            raise ValueError('Isolated repair requires its candidate lease')
        prompt += ('\n本轮与其他模型并行；只操作本候选及自己启动的进程。'
                   '禁止按引擎名称批量kill、窗口激活和OS输入；不得连接其他工程。'
                   '原生连接必须沿用以下隔离环境，不使用默认端口：'
                   + __import__('json').dumps(scope['environment'], ensure_ascii=False)
                   + '。UE构建使用正式build客户端的共享构建锁；离开本轮前清理自己的输入与进程。')
    settings = config['agent']
    root.mkdir(parents=True, exist_ok=False)
    (root / 'prompt.txt').write_text(prompt, encoding='utf-8')
    from .providers import adapter as make_adapter
    adapter = make_adapter(settings, root, session=session,
                           runtime_policy=config.get('provider_runtime_policy'))
    runner = AgentRunner(adapter, timeout_seconds=seconds,
                         observation_checkpoint_seconds=1.0, observer_max_files=100000,
                         include_project_symlink=True, startup_counts_toward_timeout=True)
    error = None
    try:
        runner.run(prompt, workspace=workspace, run_dir=root / 'agent_session',
                   register=False, artifact_store=ArtifactStore(root / 'blobs'), skip_environment=True)
    except Exception as exc:
        error = f'{type(exc).__name__}: {exc}'
    finally:
        if hasattr(adapter, 'finalize_identity'):
            try:
                adapter.finalize_identity(workspace)
            except Exception as exc:
                error = f'{error or ""}; identity recovery: {type(exc).__name__}: {exc}'
        stream = adapter.stream_normalizer
        value = {'report': runner.last_report or {}, 'session_ids': sorted(stream.session_ids),
                 'model': stream.model, 'provider_completed': stream.completed, 'error': error,
                 'model_binding': getattr(stream, 'model_binding', 'provider_stream')}
        dump(root / 'receipt.json', value)
    if value['model'] not in (None, settings['model']) or len(value['session_ids']) > 1:
        raise ValueError('Unexpected model/session identity; preserve round for diagnosis')
    if session and value['session_ids'] and value['session_ids'] != [session]:
        raise ValueError('Handoff escaped its work session')
    if value['report'].get('status') not in ('completed', 'timeout') or error:
        raise RuntimeError('Work/handoff requires diagnosed recovery: ' + str(value))
    if value['report'].get('status') == 'completed' and not value['provider_completed']:
        raise RuntimeError('Provider completion not verified')
    if value['report'].get('finalization_error'):
        raise RuntimeError('Collector finalization failed; preserve round')
    return value


def validate(folder, config):
    """Verify a completed rotation without treating timeouts as successful work."""
    from .repair_budget import selected
    if selected(config):
        return _validate_recovered(folder, config)
    folder = Path(folder)
    saved = read(folder / 'repair_rounds/summary.json')
    limit = validate_budget(config)
    attempted = saved['rounds_attempted']
    if (saved.get('status') != 'REPAIRED' or saved.get('interaction_policy') != config.get('interaction_policy', POLICY)
            or not 1 <= attempted <= limit):
        raise ValueError('Fresh-session repair pass is not closed')
    seen, completed, interrupted = set(), 0, []
    previous = None
    for n in range(1, attempted + 1):
        root = folder / 'repair_rounds' / f'round_{n:03d}'
        binding, receipt = read(root / 'claim.json'), read(root / 'closed.json')
        if binding['round'] != n or binding['previous_manifest_sha256'] != previous:
            raise ValueError('Round source lineage changed')
        for ref in receipt['sources']:
            if sha(ref['path']) != ref['sha256']:
                raise ValueError('Round evidence changed: ' + ref['path'])
        ids = receipt['session_ids']
        if len(ids) != 1 or ids[0] in seen or receipt['model'] != config['agent']['model']:
            raise ValueError('Each round must have a distinct, verified work session')
        seen.update(ids)
        previous = sha(root / 'repaired_project.json')
        if receipt['work_status'] == 'completed':
            completed += 1
        else:
            interrupted.append(n)
    if (completed != saved['rounds_completed'] or interrupted != saved['interrupted_rounds']
            or previous != saved['final_manifest_sha256']
            or inventory(folder / 'workspace/project') != read(saved['final_manifest'])['files']):
        raise ValueError('Final candidate/counts differ from closed rounds')
    return saved


def repair_project(game, folder, config, *, prepare, instructions, overview):
    from .repair_budget import selected
    if selected(config):
        return _repair_recovered(game, folder, config, instructions=instructions, overview=overview)
    folder = Path(folder)
    limit = validate_budget(config)
    prior = config.get('explicit_restart', {}).get('prior_counted_attempts', 0)
    if type(prior) is not int or prior < 0 or prior + limit > 10:
        raise ValueError('Cumulative round budget exceeds ten')
    summary = folder / 'repair_rounds/summary.json'
    if summary.exists() and read(summary).get('status') == 'REPAIRED':
        return validate(folder, config)
    workspace = folder / 'workspace'
    case_input = game.get('case_input')
    if config.get('case_inputs'):
        from .case_inputs import load as load_cases
        _, cases = load_cases(config, [game['game_id']])
        if case_input != cases[game['game_id']]:
            raise ValueError('Prepared per-game inputs differ from frozen configuration')
    motion_delivery = None
    if config.get('motion_sources'):
        from .motion_delivery import prepare_delivery
        motion_delivery = prepare_delivery(game, folder, config, prepare)
    elif not (folder / 'original_project.json').exists():
        prepare(game, folder, config)
    handoff = workspace / 'project/AGENT.md'
    previous = None
    completed, interrupted, sessions = 0, [], set()
    decision = {'stop': False, 'reason': 'ROUND_LIMIT_REACHED'}
    for n in range(1, limit + 1):
        root = folder / 'repair_rounds' / f'round_{n:03d}'
        if (root / 'closed.json').exists():
            closed = read(root / 'closed.json')
            for ref in closed['sources']:
                if sha(ref['path']) != ref['sha256']:
                    raise ValueError('Closed round evidence changed')
            if read(root / 'claim.json')['previous_manifest_sha256'] != (sha(previous) if previous else None):
                raise ValueError('Closed round parent changed')
        else:
            if root.exists():
                raise ValueError('Unclosed attempted round; diagnose before recovery, never reset budget')
            if previous and inventory(workspace / 'project') != read(previous)['files']:
                raise ValueError('Candidate changed after last closed round')
            verify_original(folder)
            if case_input:
                from .case_inputs import verify as verify_case
                verify_case(case_input)
            if motion_delivery:
                from .motion_delivery import verify_delivery
                verify_delivery(motion_delivery)
            from ..stage1 import unity_safety
            unity_safety.locks_clear(config['unity'], check_external=True)
            free = shutil.disk_usage(workspace).free
            dump(folder / 'repair_disk_checks' / f'round_{n:03d}.json',
                 {'free_bytes': free, 'reserve_bytes': 8 * 1024**3})
            if free < 8 * 1024**3:
                raise unity_safety.SafetyStop('Insufficient disk for another round plus 8GiB reserve')
            root.mkdir(parents=True)
            if handoff.is_file():
                (root / 'incoming_AGENT.md').write_bytes(handoff.read_bytes())
            else:
                handoff.write_text('# Stage3 handoff\n\nHost-created initial state. No accepted task completions yet.\n'
                                   f'Read {workspace}/refine_tasks.json and {overview}.\n', encoding='utf-8')
            dump(root / 'claim.json', {'round': n, 'cumulative_attempt': prior + n,
                 'interaction_policy': config.get('interaction_policy', POLICY), 'previous_manifest_sha256': sha(previous) if previous else None,
                 'incoming_handoff_sha256': sha(handoff), 'started_unix': time.time(),
                 'work_seconds': 1500, 'handoff_seconds': 300, 'counts_toward_limit': True})
            budget = min(float(config['agent'].get('timeout_seconds', 1800)), 1800)
            started = time.monotonic()
            prompt = (f'第{prior+n}/最多10轮，本轮新会话。先完整读 {overview}，然后读项目 {handoff}，'
                      f'再读 {workspace}/refine_tasks.json。项目为 {workspace}/project，原项目只读。'
                      '按正式引擎技能实际修改、构建、原生playtest、查看真实画面；禁止OS输入、嵌套agent或改评估工具。'
                      '25分钟工作后本轮另留最多5分钟在同会话总结；下一轮新会话只通过项目AGENT.md接续。'
                      '尽早保存实际修改、repair_status.json和repair_report.md，超时仍占本轮；不要等待计时耗尽。'
                      'AGENT.md记录需求进度、改动、真实构建退出码和证据路径、失败尝试、未验证项、下一操作和进程清理。'
                      '可完成时提前结束；修复自报不等于eval成绩。所有任务共用十轮，不按分类重置。'
                      + instructions(game) + completion_prompt(game, n, limit))
            if case_input:
                from .case_inputs import prompt as case_prompt
                prompt += case_prompt(case_input)
                dump(root / 'case_input.json', case_input)
            if motion_delivery:
                from .motion_delivery import prompt as motion_prompt
                prompt += motion_prompt(motion_delivery)
                dump(root / 'motion_delivery.json', motion_delivery)
            work = invoke(config, workspace, root / 'work', prompt, min(1500, budget))
            ids = work['session_ids']
            if len(ids) != 1 or ids[0] in sessions or work['model'] != config['agent']['model']:
                raise ValueError('Fresh work session not verified; no automatic retry')
            remaining = min(300, budget - (time.monotonic() - started))
            if remaining > 1:
                invoke(config, workspace, root / 'handoff',
                       f'本轮工作阶段已结束。现在仅总结和清理，不再开展新修复；最多{remaining:.0f}秒。'
                       f'更新项目 {handoff}：逐项进度、真实改动/构建/运行证据、已试失败、未验证和外部阻塞、'
                       '明确下一轮操作；关闭本轮自有引擎/输入进程并记录真实清理。'
                       + completion_prompt(game, n, limit), remaining, session=ids[0])
            if sha(handoff) == read(root / 'claim.json')['incoming_handoff_sha256']:
                # This is an explicit host marker, never a fabricated agent summary.
                with handoff.open('a') as out:
                    out.write(f'\nHost checkpoint: round {n} handoff was not updated. '
                              f'Inspect {root}/work/receipt.json and repair_status.json; '
                              'prior task claims remain unverified.\n')
            (root / 'AGENT.md').write_bytes(handoff.read_bytes())
            verify_original(folder)
            unity_safety.locks_clear(config['unity'], check_external=True)
            dump(root / 'repaired_project.json', {'files': inventory(workspace / 'project')})
            refs = [root / 'claim.json', root / 'AGENT.md', root / 'repaired_project.json',
                    root / 'work/receipt.json']
            if case_input:
                refs.append(root / 'case_input.json')
                refs.extend(Path(ref['path']) for ref in case_input['sources'])
                verify_case(case_input)
            if motion_delivery:
                refs.append(root / 'motion_delivery.json')
                # Bind both companion documents and the exact delivered NPZ/JSON bytes.
                refs.extend(Path(ref['path']) for ref in motion_delivery['sources'])
                verify_delivery(motion_delivery)
            if (root / 'handoff/receipt.json').exists():
                refs.append(root / 'handoff/receipt.json')
            closed = {'round': n, 'session_ids': ids, 'model': work['model'],
                      'work_status': work['report']['status'],
                      'sources': [{'path': str(p), 'sha256': sha(p)} for p in refs]}
            dump(root / 'closed.json', closed)
        if set(closed['session_ids']) & sessions:
            raise ValueError('Work session reused across rounds')
        sessions.update(closed['session_ids'])
        completed += closed['work_status'] == 'completed'
        if closed['work_status'] != 'completed': interrupted.append(n)
        previous = root / 'repaired_project.json'
        decision = stop_decision(game, folder, root, n)
        dump(summary, {'status': 'RUNNING', 'interaction_policy': config.get('interaction_policy', POLICY), 'rounds_attempted': n,
                       'rounds_completed': completed, 'interrupted_rounds': interrupted})
        if decision['stop']: break
    dump(folder / 'repaired_project.json', read(previous))
    result = {'status': 'REPAIRED', 'interaction_policy': config.get('interaction_policy', POLICY), 'rounds_attempted': n,
              'rounds_completed': completed, 'interrupted_rounds': interrupted, 'rounds_limit': limit,
              'stop_reason': decision['reason'] if decision['stop'] else 'ROUND_LIMIT_REACHED',
              'source_completion': decision, 'final_manifest': str(previous),
              'final_manifest_sha256': sha(previous), 'evaluation_started': False, 'runtime_verdict': None}
    dump(summary, result)
    return validate(folder, config)


class ProviderRecoveryRequired(RuntimeError):
    """Failure was preserved; coordinator must diagnose before another attempt."""


def _validate_recovered(folder, config):
    from .repair_budget import Budget
    folder = Path(folder).resolve()
    budget = Budget(folder, config)
    saved = read(folder / 'repair_rounds/summary.json')
    state = budget.counts()
    for key, value in state.items():
        if saved.get(key) != value:
            raise ValueError('Saved repair budget/counts changed: ' + key)
    final = budget.checkpoint
    if (saved.get('status') != 'REPAIRED' or budget.needs_recovery
            or state['unresolved_attempts'] or not state['rounds_completed']
            or saved.get('interaction_policy') != config['interaction_policy']
            or saved.get('evaluation_started') is not False
            or saved.get('runtime_verdict') is not None
            or saved.get('final_manifest') != final['path']
            or saved.get('final_manifest_sha256') != final['sha256']
            or inventory(folder / 'workspace/project') != read(final['path'])['files']
            or read(folder / 'repaired_project.json')['files'] != read(final['path'])['files']):
        raise ValueError('Recovered repair is not closed on its exact candidate')
    verify_original(folder)
    if state['effective_remaining']:
        n = state['physical_attempt']
        decision = saved.get('source_completion', {})
        if not decision.get('stop') or decision.get('reason') not in ('SOURCE_WORK_COMPLETE', 'EXTERNAL_BLOCKERS_ONLY'):
            raise ValueError('Early budget completion needs an explicit source completion report')
        report = decision.get('completion_report')
        if not report or sha(report) != decision.get('completion_report_sha256'):
            raise ValueError('Source completion report changed')
    return saved


def _repair_recovered(game, folder, config, *, instructions, overview):
    """Resume via a supplemental journal; legacy claims/directories stay intact."""
    from .repair_budget import Budget, provider_circuit_state
    from ..stage1 import unity_safety
    folder = Path(folder).resolve()
    validate_budget(config)
    budget = Budget(folder, config)  # Explicit migration must precede dispatch.
    summary = folder / 'repair_rounds/summary.json'
    if summary.is_file() and read(summary).get('repair_budget_policy') == config['repair_budget_policy'] and read(summary).get('status') == 'REPAIRED':
        return _validate_recovered(folder, config)
    if (folder / 'input').exists() or (folder / 'result.json').exists():
        raise ValueError('Cannot resume source repair after evaluation started')
    workspace = folder / 'workspace'
    handoff = workspace / 'project/AGENT.md'
    case_input = game.get('case_input')
    if config.get('case_inputs'):
        from .case_inputs import load as load_cases
        _, cases = load_cases(config, [game['game_id']])
        if case_input != cases[game['game_id']]:
            raise ValueError('Prepared per-game inputs differ from frozen configuration')
    motion_delivery = None
    if config.get('motion_sources'):
        from .motion_delivery import prepare_delivery
        def already_prepared(*args):
            raise ValueError('Recovery cannot replace an existing candidate')
        motion_delivery = prepare_delivery(game, folder, config, already_prepared)
    decision = {'stop': False, 'reason': 'ROUND_LIMIT_REACHED'}
    while budget.counts()['effective_remaining'] > 0:
        n = budget.next_attempt()
        verify_original(folder)
        if case_input:
            from .case_inputs import verify as verify_case
            verify_case(case_input)
        if motion_delivery:
            from .motion_delivery import verify_delivery
            verify_delivery(motion_delivery)
        unity_safety.locks_clear(config['unity'], check_external=True)
        free = shutil.disk_usage(workspace).free
        if free < 8 * 1024**3:
            raise unity_safety.SafetyStop('Insufficient disk for another round plus 8GiB reserve')
        dump(folder / 'repair_disk_checks' / f'round_{n:03d}.json',
             {'free_bytes': free, 'reserve_bytes': 8 * 1024**3})
        root = folder / 'repair_rounds' / f'round_{n:03d}'
        root.mkdir()  # Exclusive physical slot: never overwrite an interrupted attempt.
        if handoff.is_file():
            (root / 'incoming_AGENT.md').write_bytes(handoff.read_bytes())
        else:
            handoff.write_text('# Stage3 handoff\nHost-created checkpoint; read prior failure evidence.\n')
        state = budget.counts()
        dump(root / 'claim.json', {'round': n, 'physical_attempt': n,
             'cumulative_attempt': budget.revision['identity']['prior_counted_attempts'] + n,
             'interaction_policy': config['interaction_policy'], 'repair_budget_policy': config['repair_budget_policy'],
             'previous_manifest_sha256': budget.checkpoint['sha256'],
             'incoming_handoff_sha256': sha(handoff), 'started_unix': time.time(),
             'work_seconds': 1500, 'handoff_seconds': 300, 'counts_toward_limit': True,
             'parent_failure': budget.parent_failure, 'recovery_target': budget.recovery_target,
             'effective_used_before': state['effective_used'], 'budget_revision': state['budget_revision']})
        prior_sessions = budget.sessions.copy()
        budget = budget.started_attempt(root)
        dump(summary, {'status': 'RUNNING', 'interaction_policy': config['interaction_policy'], **budget.counts()})
        seconds = min(float(config['agent'].get('timeout_seconds', 1800)), 1800)
        started = time.monotonic()
        prompt = (f'物理尝试{n}；有效预算已用{state["effective_used"]}/{state["effective_limit"]}，'
                  f'剩余最多{state["effective_remaining"]}轮；恢复目标旧round_{state["recovery_target"]:03d}。'
                  f'本轮新会话，先完整读 {overview}、项目 {handoff}、{workspace}/refine_tasks.json。'
                  f'项目 {workspace}/project；保留既有真实修改，原件只读。'
                  '按正式引擎技能修改、构建、原生playtest；禁止OS输入、嵌套agent或修改评估工具。'
                  '最多25分钟工作，再在同会话最多5分钟交接清理；提前完成即可结束。'
                  '及时保存repair_status.json、repair_report.md，更新AGENT.md真实进度、构建证据、失败、阻塞及下一步。'
                  '超时及明确网络鉴权失败按来源账本处理，不可自行重试或重置十轮预算；修复自报不等于eval。'
                  + instructions(game) + completion_prompt(game, n, state['effective_limit']))
        if case_input:
            from .case_inputs import prompt as case_prompt
            prompt += case_prompt(case_input)
            dump(root / 'case_input.json', case_input)
        if motion_delivery:
            from .motion_delivery import prompt as motion_prompt
            prompt += motion_prompt(motion_delivery)
            dump(root / 'motion_delivery.json', motion_delivery)
        try:
            work = invoke(config, workspace, root / 'work', prompt, min(1500, seconds))
            ids = work['session_ids']
            if len(ids) != 1 or set(ids) & prior_sessions or work['model'] != config['agent']['model']:
                raise ValueError('Fresh work session not verified; preserve failed attempt')
            remaining = min(300, seconds - (time.monotonic() - started))
            if remaining > 1:
                invoke(config, workspace, root / 'handoff',
                       f'仅更新项目 {handoff}、repair_status.json及真实证据并清理自己的输入和进程；不开展新修复。'
                       + completion_prompt(game, n, state['effective_limit']), remaining, session=ids[0])
            if sha(handoff) == read(root / 'claim.json')['incoming_handoff_sha256']:
                with handoff.open('a') as out:
                    out.write(f'\nHost checkpoint: physical attempt {n}; inspect work/handoff receipts.\n')
            (root / 'AGENT.md').write_bytes(handoff.read_bytes())
            verify_original(folder)
            unity_safety.locks_clear(config['unity'], check_external=True)
            dump(root / 'repaired_project.json', {'files': inventory(workspace / 'project')})
            refs = [root / 'claim.json', root / 'AGENT.md', root / 'repaired_project.json', root / 'work/receipt.json']
            if (root / 'handoff/receipt.json').is_file():
                refs.append(root / 'handoff/receipt.json')
            for binding in (case_input, motion_delivery):
                if binding:
                    refs.extend(Path(ref['path']) for ref in binding['sources'])
            for name in ('case_input.json', 'motion_delivery.json'):
                if (root / name).is_file():
                    refs.append(root / name)
            if case_input:
                verify_case(case_input)
            if motion_delivery:
                verify_delivery(motion_delivery)
            dump(root / 'closed.json', {'round': n, 'session_ids': ids, 'model': work['model'],
                 'work_status': work['report']['status'],
                 'sources': [{'path': str(p), 'sha256': sha(p)} for p in refs]})
            decision = stop_decision(game, folder, root, n)
        except Exception:
            budget = budget.record_attempt(root)
            dump(summary, {'status': 'RECOVERY_REQUIRED', 'interaction_policy': config['interaction_policy'],
                           **budget.counts(), 'provider_circuit': provider_circuit_state([root]),
                           'evaluation_started': False})
            raise
        budget = budget.record_attempt(root)
        if budget.needs_recovery:
            dump(summary, {'status': 'RECOVERY_REQUIRED', 'interaction_policy': config['interaction_policy'],
                           **budget.counts(), 'provider_circuit': provider_circuit_state([root]),
                           'evaluation_started': False})
            raise ProviderRecoveryRequired('Attempt preserved; explicit failure recovery required before dispatch')
        dump(summary, {'status': 'RUNNING', 'interaction_policy': config['interaction_policy'], **budget.counts()})
        if decision['stop']:
            break
    dump(folder / 'repaired_project.json', read(budget.checkpoint['path']))
    result = {'status': 'REPAIRED', 'interaction_policy': config['interaction_policy'], **budget.counts(),
              'interrupted_rounds': [n for n, r in sorted(budget.records.items()) if r['outcome'] != 'SUCCESS'],
              'rounds_limit': budget.revision['limit'],
              'stop_reason': decision['reason'] if decision['stop'] else 'ROUND_LIMIT_REACHED',
              'source_completion': decision, 'final_manifest': budget.checkpoint['path'],
              'final_manifest_sha256': budget.checkpoint['sha256'],
              'evaluation_started': False, 'runtime_verdict': None}
    dump(summary, result)
    return _validate_recovered(folder, config)
