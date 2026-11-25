"""Read-only reporting of actual capture timing and script-calculated partial scores."""
from pathlib import Path
import json
from .protocol import sha


def load(path):
    return json.loads(path.read_text()) if path.is_file() else {}


def row_scores(row):
    selected=row.get('scores')
    if isinstance(selected,dict):return selected
    return load(Path(selected)) if selected else load(Path(row['run'])/'scores.json')


def capture_details(root):
    root = Path(root)
    timing = load(root/'runtime/timing.json')
    budget = load(root/'runtime/budget_resolution.json')
    engine = load(root/'runtime/engine_result.json')
    payload = engine.get('adapter_result', {}).get('payload', {})
    report = payload.get('report', {})
    files = ['runtime/timing.json', 'runtime/budget_resolution.json',
             'runtime/shared_web_toolchain.json', 'runtime/preflight.json',
             'gui_session_blocker.json', 'runtime/execution.json']
    artifacts = ['sol_plan.json','operation_report.md','status.json','runtime/engine_result.json',
                 'evidence_manifest.json','trace_summary.json','rubric_verdicts.json','scores.json',
                 'runtime/actions.jsonl','runtime/state_trace.jsonl','runtime/event_trace.jsonl',
                 'runtime/frame_index.jsonl','runtime/execution.json','harness_error.json']
    return {'artifacts': {name: {'exists': (root/name).is_file(),
                        'sha256': sha(root/name) if (root/name).is_file() else None}
                        for name in artifacts},
            'elapsed_ms': timing.get('elapsed_ms'),
            'budget': budget.get('effective_budget', timing.get('budget')),
            'plan_max_duration_ms': budget.get('plan_max_duration_ms'),
            'timeout': timing.get('timeout'), 'timeout_reason': timing.get('timeout_reason'),
            'phase_timings_ms': payload.get('phase_timings_ms', {}),
            'recorder_wallclock_seconds': report.get('wallclock_seconds'),
            'capture_deadline_ms': report.get('capture_deadline_ms'),
            'requested_seconds': report.get('requested_seconds'),
            'channel_coverage': report.get('channel_coverage', {}),
            'audio_capture': report.get('audio_capture', {}),
            'warnings': engine.get('adapter_result', {}).get('warnings', []),
            'bindings': {name: sha(root/name) for name in files if (root/name).is_file()}}


def partial_score_lines(batch, rows):
    lines=[]
    for row in rows:
        if not row['valid']:continue
        report=row_scores(row)
        endpoints=report.get('mechanism_endpoints',{})
        if not endpoints:continue
        n=len(endpoints)
        lines += ['', f"### {row['id']}：机制端点 N={n}", '',
            f"评分协议 `{report.get('scoring_protocol')}`；八列各占 1/8，端点等权 1/{n}。资产预留按原协议计分。",
            '', '| 端点 | 权重 | 分数 | 状态 |','|---|---|---|---|']
        for endpoint,item in endpoints.items():
            lines.append(f"| {endpoint} | {item['weight']:.8f} | {item['score']:.2f} | {item['status']} |")
    return lines


def capture_lines(rows):
    def seconds(value):
        return '—' if value is None else f'{value/1000:.3f}'
    lines = ['', '## 逐例录制预算与实际耗时', '',
             '单位为秒。阶段预算是上限；实际总耗时包括准备/录制/收尾，非歌曲通过时长。预检阻塞的例未启动游戏，录制耗时为—。', '',
             '| 测例 | 引擎 | import/build预算 | 启动预算 | 录制预算 | 总预算 | 实际总耗时 | 录制器墙钟 | 状态 |',
             '|---|---|---|---|---|---|---|---|---|']
    for row in rows:
        detail = row.get('recording', {})
        budget = detail.get('budget') or {}
        wall = detail.get('recorder_wallclock_seconds')
        lines.append('| '+row['id']+' | '+str(row['actual_engine'])+' | '+' | '.join(seconds(budget.get(key)) for key in
            ('import_build_ms','launch_wait_ms','recording_ms','engine_call_ms'))+' | '+seconds(detail.get('elapsed_ms'))+' | '+('—' if wall is None else f'{wall:.3f}')+' | '+row['status']+' |')
    for row in rows:
        detail = row.get('recording', {})
        lines += ['', f"- `{row['id']}`：`{row['run']}/runtime/timing.json`；阶段实际耗时(ms) `{json.dumps(detail.get('phase_timings_ms',{}))}`；超时 `{detail.get('timeout')}`，原因 `{detail.get('timeout_reason')}`。"]
        if detail.get('channel_coverage'):
            lines.append('  - 实际通道：`'+json.dumps(detail['channel_coverage'],ensure_ascii=False)+'`；音频：`'+json.dumps(detail.get('audio_capture',{}),ensure_ascii=False)+'`。缺少音频证据不证明音频通过。')
        if row.get('reason'):
            lines.append('  - 状态原因：'+(f"[{row['failure_label']}] " if row.get('failure_label') else '')+row['reason'])
    return lines


def outcome_counts(rows):
    """Count verified runtime counterexamples separately from evaluator failures."""
    from collections import Counter
    examples = []
    unverified = 0
    for row in rows:
        if not row['valid']:
            continue
        scores = row_scores(row)
        for check in scores.get('checks', []):
            if check.get('status') == 'UNVERIFIED':
                unverified += 1
            if check.get('status') == 'FAIL' and check.get('mode') != 'static':
                examples.append({'case': row['id'], 'criterion': check['id'],
                    'reason': check.get('reason'), 'evidence': check.get('evidence', [])})
    return {'status_counts': dict(Counter(row['status'] for row in rows)),
            'harness_error_cases': sum(r['status']=='HARNESS_ERROR' for r in rows),
            'blocked_engine_collector_cases': sum(r['status']=='BLOCKED_ENGINE_COLLECTOR' for r in rows),
            'verified_runtime_failure_cases': len({e['case'] for e in examples}),
            'verified_runtime_failure_items': len(examples),
            'unverified_items_in_valid_scores': unverified,
            'runtime_counterexamples': examples}


def outcome_lines(counts):
    lines = ['', '## 错误与游戏反例分类', '',
        f"- HARNESS_ERROR：{counts['harness_error_cases']} 例；BLOCKED_ENGINE_COLLECTOR：{counts['blocked_engine_collector_cases']} 例。均无游戏分数。",
        f"- 有有效运行反例的游戏：{counts['verified_runtime_failure_cases']} 例、{counts['verified_runtime_failure_items']} 个运行评分项。只有通过证据审计的整例中的 runtime FAIL 计入；未到达流程不计为游戏失败。",
        f"- 有效评分中的 UNVERIFIED：{counts['unverified_items_in_valid_scores']} 项；详细原因和证据位于各例 rubric_verdicts.json。"]
    for item in counts['runtime_counterexamples']:
        lines.append(f"- `{item['case']}` / `{item['criterion']}`：{item['reason']}；证据 `{json.dumps(item['evidence'],ensure_ascii=False)}`。")
    return lines
