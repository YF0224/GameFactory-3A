"""One explicit continuation of a failed ZCode conversation, preserving its attempt."""
from pathlib import Path
import json
from .common import dump, read, sha
from .session import inventory


def verify_previous(config, output, game_id, session_id):
    output = Path(output).resolve()
    if read(output / 'configuration.json') != config:
        raise ValueError('Recovery must use the exact frozen configuration')
    frozen = read(output / 'inventory.json')
    for ref in frozen['sources'].values():
        if sha(ref['path']) != ref['sha256']:
            raise ValueError('Frozen collect changed')
    matches = [g for g in frozen['games'] if g['game_id'] == game_id]
    if len(matches) != 1 or config['agent'].get('provider') != 'zcode':
        raise ValueError('Recovery requires exactly one frozen ZCode game')
    game = matches[0]
    folder = output / 'games' / game_id
    if read(folder / 'stages/repair.json')['status'] != 'ERROR':
        raise ValueError('Only a saved failed repair can be continued')
    if (folder / 'repaired_project.json').exists():
        raise ValueError('Completed repair cannot be retried')
    original = read(folder / 'original_project.json')
    if inventory(original['root']) != original['files']:
        raise ValueError('Original delivery differs from the failed attempt')
    sessions, models = set(), set()
    for line in (folder / 'agent_session/raw/zcode.jsonl').read_text().splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get('sessionId'):
            sessions.add(event['sessionId'])
        if event.get('type') == 'session.updated' and event.get('payload', {}).get('modelId'):
            models.add(event['payload']['modelId'])
    if sessions != {session_id} or models != {config['agent']['model']}:
        raise ValueError('Requested session/model does not match original provider events')
    for item in read(folder / 'payloads.json').values():
        if item['status'] == 'READY' and (sha(item['frozen_path']) != item['sha256'] or sha(item['path']) != item['sha256']):
            raise ValueError('Frozen or workspace payload differs from the failed attempt')
    return game, folder, original


def resume(config, output, game_id, session_id):
    from pipeline.data_collection.runtime.live_runner import AgentRunner
    from pipeline.data_collection.core.artifact_store import ArtifactStore
    from ..stage1 import unity_safety
    from .batch import exclusive, code_identity
    from .zcode import ZCodeAdapter
    game, folder, original = verify_previous(config, output, game_id, session_id)
    unity = config['unity']
    with exclusive(Path(unity['control_root']) / 'whitebox_production_queue.lock'):
        unity_safety.locks_clear(unity, check_external=True)
        recovery = folder / 'repair_continuation_001'
        # Deliberately one bounded continuation. Never replace a failed continuation.
        recovery.mkdir(exist_ok=False)
        dump(recovery / 'binding.json', {
            'session_id': session_id, 'model': config['agent']['model'],
            'previous_failure': str(folder / 'stages/repair.json'),
            'previous_failure_sha256': sha(folder / 'stages/repair.json'),
            'previous_implementation': read(Path(output) / 'code_identity.json'),
            'current_implementation': code_identity(),
            'original_delivery': original['root'],
            'workspace_before': inventory(folder / 'workspace/project'),
            'max_continuations': 1, 'new_conversation_allowed': False})
        previous_report=read(folder/'agent_report.json')
        interruption=previous_report.get('status','unknown')
        dump(recovery/'interruption.json',dict(previous_status=interruption,previous_report_sha256=sha(folder/'agent_report.json'),
            timeout_seconds=config['agent'].get('timeout_seconds',3600),new_conversation=False))
        prompt = (f'继续本会话上一轮因 {interruption} 中断的同一个游戏任务。保持之前全部任务和限制，'
                  '不要再次全量扫描、查找依赖或长篇重新设计。只处理此前任务中有证据的必要修改；不要为了产生diff制造修改。'
                  '无资产任务时不寻找资源、不安装依赖。工程外工具和历史测评材料不可修改。'
                  '每次只编辑有限文件并检查；禁止启动引擎和嵌套agent。缺失动作资源明确列阻塞。'
                  '最终必须在原工作区repair_report.md逐任务列出实际修改及未完成项。不得自行宣称测评通过。')
        (recovery / 'prompt.txt').write_text(prompt)
        settings = config['agent']
        adapter = ZCodeAdapter(settings['executable'], [*settings.get('args', []), '--resume', session_id],
                               prompt_name='agent_resume_input_001.txt')
        runner = AgentRunner(adapter, timeout_seconds=settings.get('timeout_seconds', 3600))
        dump(recovery / 'status.json', {'status': 'STARTED', 'session_id': session_id})
        result = None
        try:
            runner.run(prompt, workspace=folder / 'workspace', run_dir=recovery / 'agent_session',
                metadata={'game_id': game_id, 'run_id': Path(output).name + '__continuation_001',
                          'resumed_session_id': session_id},
                register=False, artifact_store=ArtifactStore(recovery / 'blobs'), skip_environment=True)
            report = runner.last_report or {}
            dump(recovery / 'agent_report.json', report)
            observed = adapter.stream_normalizer
            identity = {'session_ids': sorted(observed.session_ids), 'model': observed.model,
                        'provider_completed': observed.completed, 'final_response': observed.final_response}
            dump(recovery / 'agent_identity.json', identity)
            if (report.get('status') != 'completed' or report.get('finalization_error') or
                observed.session_ids != {session_id} or observed.model != settings['model'] or not observed.completed):
                raise RuntimeError('Same-session continuation did not complete; preserve evidence, no further retry')
            warnings = [] if (folder / 'workspace/repair_report.md').is_file() else ['MISSING_AGENT_REPAIR_REPORT']
            repaired = inventory(folder / 'workspace/project')
            dump(recovery / 'repaired_project.json', {'files': repaired})
            result = {'status': 'REPAIRED', 'session_id': session_id, 'continuation': str(recovery),
                      'repaired_manifest': str(recovery / 'repaired_project.json'),
                      'changed_files': sorted(k for k in set(original['files']) | set(repaired)
                                              if original['files'].get(k) != repaired.get(k)),
                      'formal_score': None, 'warnings': warnings,
                      'note': 'Session completion only; repair quality is evaluated downstream.'}
            dump(recovery / 'status.json', result)
        except BaseException as exc:
            dump(recovery / 'status.json', {'status': 'ERROR', 'error': f'{type(exc).__name__}: {exc}',
                                           'session_id': session_id, 'formal_score': None})
            raise
        finally:
            if inventory(original['root']) != original['files']:
                raise unity_safety.SafetyStop('Original delivery changed during continuation')
            cleanup = unity_safety.locks_clear(unity, check_external=True)
            dump(recovery / 'cleanup.json', {'locks_clear': cleanup, 'engine_started_by_recovery': False})
        return {game_id: result}
