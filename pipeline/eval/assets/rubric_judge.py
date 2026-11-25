"""Closed, evidence-bound sol judgments. Never repair model fields or scores."""
from __future__ import annotations
import fcntl
import json
import os
import shlex
import subprocess
import time
from pathlib import Path
from .common import OUTPUTS, dump
# Read-only import. Python bytecode is disabled by this package and CLI.
from pipeline.eval.assets.codex import call_codex, validate_schema

MODEL = 'gpt-6.1-sol'
VIEWS = [f'V{i:02d}_{name}' for i, name in enumerate(('front', 'back', 'left', 'right', 'top', 'three_quarter'), 1)]


def obj(properties):
    return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}


def evidence_schema(ids):
    return {'type': 'array', 'items': {'type': 'string', 'enum': ids}, 'minItems': 1, 'maxItems': len(ids)}


def rubric_schema(rubric, ids):
    # Key by dimension and check ID so omissions/duplicates cannot masquerade as coverage.
    return obj({'checks': obj({dim['id']: obj({c['id']: obj({
        'verdict': {'type': 'string', 'enum': ['PASS', 'FAIL', 'UNVERIFIED']},
        'evidence_views': evidence_schema(ids), 'reason': {'type': 'string'}})
        for c in dim['checks']}) for dim in rubric['dimensions']}),
        'limitations': {'type': 'array', 'items': {'type': 'string'}}})


def style_schema(ids):
    return obj({'score': {'type': ['integer', 'null'], 'minimum': 0, 'maximum': 4},
                'verdict': {'type': 'string', 'enum': ['PASS', 'FAIL', 'UNVERIFIED']},
                'evidence_views': evidence_schema(ids), 'reason': {'type': 'string'},
                'limitations': {'type': 'array', 'items': {'type': 'string'}}})


def active_api_processes():
    result = subprocess.run(['ps', '-axo', 'pid=,ppid=,command='], capture_output=True, text=True, check=True)
    whitebox = []; sol = []
    for line in result.stdout.splitlines():
        try:
            pid, ppid, command = line.strip().split(None, 2); args = shlex.split(command)
        except ValueError:
            continue
        if 'pipeline.eval.whitebox.batch' in args:
            whitebox.append(int(pid))
        if 'exec' in args and '--model' in args and MODEL in args and any('codex' in Path(a).name for a in args[:2]):
            sol.append({'pid': int(pid), 'ppid': int(ppid)})
    # A wrapper and native binary in the same invocation count once.
    pids = {p['pid'] for p in sol}
    roots = [p for p in sol if p['ppid'] not in pids]
    return {'whitebox_batch_pids': whitebox, 'sol_invocations': roots}


def invoke(root, name, prompt, schema, images):
    (root / 'input').mkdir(parents=True, exist_ok=True)
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    with (OUTPUTS / '.asset_sol.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)  # asset_eval itself is strictly serial
        snapshot = active_api_processes()
        # The unmodified whitebox pipeline has nested two-worker pools and does
        # not participate in a shared semaphore. A momentarily free slot is NOT
        # a reservation. Defer rather than race it or alter/stop that batch.
        if snapshot['whitebox_batch_pids'] or snapshot['sol_invocations']:
            folder = root / 'model_calls' / name
            folder.mkdir(parents=True, exist_ok=True)
            (folder / 'prompt.txt').write_text(prompt)
            dump(folder / 'schema.json', schema)
            reason = 'api_concurrency_unavailable: uncoordinated whitebox/sol process active; cannot reserve capacity without modifying background batch'
            dump(folder / 'invocation.json', {'status': 'NOT_INVOKED', 'model_requested': MODEL,
                 'failure_label': 'api_concurrency_unavailable', 'reason': reason, 'process_snapshot': snapshot,
                 'images': [str(p) for p in images], 'timeout': 600, 'max_attempts': 2})
            dump(folder / 'response_absent.json', {'reason': 'No API invocation; no response or judgment fabricated.'})
            return None, reason
        os.environ['A3GAME_SOL_REASONING_EFFORT'] = 'medium'
        for attempt in range(2):
            try:
                result = call_codex(root, name=name if not attempt else name + '_network_retry', prompt=prompt,
                                    schema=schema, model=MODEL, images=images, timeout=600, max_attempts=1)
                validate_schema(result, schema)
                return result, None
            except Exception as exc:
                # call_codex internal retries disabled: at most one total retry,
                # and only for 502/connection interruptions, never code-filled output.
                logs = ''
                for p in (root / 'model_calls').glob(f'{name}*/*'):
                    if p.name in ('stderr.log', 'events.jsonl'):
                        with p.open('rb') as f:
                            f.seek(max(0, p.stat().st_size - 32000)); logs += f.read().decode('utf-8', errors='replace')
                transport = any(token in (logs + str(exc)).lower() for token in (
                    '502', 'stream disconnected', 'connection reset', 'stream interrupted', 'connection closed', 'unexpected eof'))
                if attempt == 0 and transport:
                    dump(root / 'model_calls' / 'network_retry_policy.json', {'reason': str(exc), 'retry': 1, 'max_total_attempts': 2})
                    time.sleep(2)
                    continue
                label = 'sol_transport_failure' if transport else 'sol_invalid_response_or_invocation'
                return None, label + ': ' + str(exc)


def judge_rubric(root, task, rubric, views):
    ids = [v['id'] for v in views]; schema = rubric_schema(rubric, ids)
    prompt = ('对真实GLB的六张多视角图逐条判定下面per-asset rubric的所有checks。只输出封闭JSON。\n'
              '每张图片顶端有视角编号；evidence_views必须逐字引用交付编号，不能虚构观察。'
              'PASS=全部明确目标满足，FAIL=至少一个明确目标被可见证据否定，无法观察=UNVERIFIED。'
              '不用PARTIAL，不为缺失证据打FAIL。原rubric的UNKNOWN映射为本次UNVERIFIED，但由你输出。'
              '世界单位未校准，截图不能证明米制高度、旋转能力或发光能力；不能凭正常静帧断言运行行为。'
              '质量checks若只有1-5 rating_anchors而无二元验收阈值，判UNVERIFIED，不能自行定阈值。'
              'task_input可能来自low-poly priority批次，与原任务有差异；保留原始rubric，明确指出冲突。'
              '不要要求原任务没有的额外约束；无法适用的check由你判UNVERIFIED并解释。\n'
              '第1列只由requirement_compliance维度的PASS/(PASS+FAIL)算出；其余维度仅审计不混入第1列。\n'
              '图片顺序：' + json.dumps(ids) + '\n原任务：' + json.dumps(task, ensure_ascii=False)
              + '\n原始rubric：' + json.dumps(rubric, ensure_ascii=False))
    result, error = invoke(root, 'judge_rubric', prompt, schema, [v['judge_path'] for v in views])
    if result is None:
        return {'score': None, 'pass_count': None, 'fail_count': None, 'unverified_count': None,
                'model_output': None, 'notes': [error], 'failure_label': error.split(':')[0]}
    checks = result['checks'].get('requirement_compliance')
    if checks is None:
        return {'score': None, 'model_output': result, 'notes': ['No requirement_compliance rubric dimension'], 'failure_label': 'rubric_dimension_missing'}
    counts = {s: sum(c['verdict'] == s for c in checks.values()) for s in ('PASS', 'FAIL', 'UNVERIFIED')}
    denominator = counts['PASS'] + counts['FAIL']
    return {'score': counts['PASS'] / denominator if denominator else None,
            'pass_count': counts['PASS'], 'fail_count': counts['FAIL'], 'unverified_count': counts['UNVERIFIED'],
            'check_coverage': denominator / len(checks) if checks else None, 'model_output': result,
            'notes': ['All requirement checks UNVERIFIED; denominator is zero'] if not denominator else [], 'failure_label': None}


def judge_style(root, context, views):
    ids = [v['id'] for v in views]
    prompt = ('评估GLB与游戏原始美术方向是否一致，不评输入prompt的部件满足度，不重复传统几何质量分。'
              '仅根据六张交付图，引用编号。score 0=明确不相容，1=大体不合，2=混合，3=大体一致，4=高度一致。'
              '缺乏适用美术方向或无法判断时score=null、verdict=UNVERIFIED；否则0-1对应FAIL，2-4对应PASS。'
              '不要求单一资产包含全部主色。理由简短且明确可见材质/造型/色彩。\n'
              '原始美术方向：\n' + context['art_direction_verbatim'] + '\n图片顺序：' + json.dumps(ids))
    result, error = invoke(root, 'judge_style', prompt, style_schema(ids), [v['judge_path'] for v in views])
    if result is None:
        return {'score': None, 'model_output': None, 'notes': [error], 'failure_label': error.split(':')[0]}
    if (result['score'] is None) != (result['verdict'] == 'UNVERIFIED'):
        return {'score': None, 'model_output': result, 'notes': ['Model score/verdict inconsistent; no code repair'], 'failure_label': 'sol_semantic_schema_failure'}
    if result['score'] is not None and (result['verdict'] == 'PASS') != (result['score'] >= 2):
        return {'score': None, 'model_output': result, 'notes': ['Model score/verdict inconsistent; no code repair'], 'failure_label': 'sol_semantic_schema_failure'}
    return {'score': result['score'], 'model_output': result, 'notes': result['limitations'], 'failure_label': None}
