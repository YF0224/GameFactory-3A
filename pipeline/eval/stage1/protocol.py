"""Fixed pilot criteria and deterministic aggregation; never rewrites frozen rubrics."""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from statistics import mean

VERSION = "whitebox-eightcol-sol-pilot.v1"
EQUAL_COLUMNS = "eight-columns-equal.v1"
LEGACY_GROUPS = "macro-groups.v1"
COLUMNS = ["故事完整性", "机制完整性", "资产预留", "白模输入一致性", "白模构建质量", "Gameness", "Playable", "Code"]
# Fixed BEFORE looking at a model's evaluation. Each atomic check has equal weight
# within a column, except Gameness, whose three groups have equal weight.
_DEFS = [
    ("story.background", 0, "static", "背景", "交付文档或游戏文本明确交代故事背景、世界或场景缘由。"),
    ("story.identity", 0, "static", "身份", "明确说明玩家身份，且与任务设定一致。"),
    ("story.goal", 0, "static", "目标", "明确交代玩家目标和行动动机。"),
    ("story.plot", 0, "static", "情节", "具有符合需求的基本开端和结束/成败叙事；S级允许简短开头，不要求长篇故事。"),
    ("mechanic.entry", 1, "runtime", "入口", "通过正常玩家输入从标题进入实际可操作训练场；实际状态及画面一致。"),
    ("mechanic.move", 1, "runtime", "移动", "实际移动输入导致玩家在场景中移动；暂停/面板不是操作前状态。"),
    ("mechanic.hit", 1, "runtime", "攻击", "正常攻击在有效范围/朝向内导致敌人实际HP下降；需输入、位置/朝向、HP前后及画面交叉证据，挥空不算。"),
    ("mechanic.dodge", 1, "runtime", "闪避", "正常闪避在体力足够时产生对应位移且消耗需求规定的15体力；不由此推断无敌帧或所有边界通过。"),
    ("mechanic.pause", 1, "runtime", "暂停", "正常暂停输入后计时及玩法运动冻结，恢复后继续；需足够观察窗口，不以暂停菜单出现代替模拟冻结。"),
    ("mechanic.ending", 1, "runtime", "结束", "正常路径到达胜或负结算且正常重开恢复初始局内状态；不得直接改HP或调用结算函数。"),
    ("asset.placeholder", 2, "static", "占位", "有实际白模占位对象并能追踪到场景/构建代码，不仅是清单名称。"),
    ("asset.binding", 2, "static", "替换", "替换资源的路径、加载/实例化接口与实际场景构建连接；只声明不存在的资源路径不算。"),
    ("asset.hook", 2, "static", "挂点", "存在实际挂点或可追踪的动作/VFX/音效替换接口，不仅是contract承诺。"),
    ("input.objects", 3, "reference", "关键物体", "参考输入中的场景和关键物体在白模中得到对应表达；不要求精细资产。"),
    ("input.proportions", 3, "reference", "比例", "关键物体轮廓和相对比例与参考输入大体一致，按白模标准。"),
    ("input.spatial", 3, "reference", "空间", "场景布局、地标和主要空间关系与输入一致；镜头不足不能猜测。"),
    ("quality.complete", 4, "visual", "完整", "实际画面包含可辨认的场地、角色及关键交互对象，无大块缺失或错误材质。"),
    ("quality.readable", 4, "visual", "可读", "白模轮廓、光照和对象区分支持理解玩法，不以精细美术水平打分。"),
    ("quality.defects", 4, "visual", "缺陷", "已观察视角中没有明显穿插、悬空、遮挡或相机严重异常；不得推广为全场景无缺陷。"),
    ("game.layout.hierarchy", 5, "visual", "layout", "实际UI信息层级清楚，主要状态与次要信息可区分。"),
    ("game.layout.readable", 5, "visual", "layout", "实际UI文字、尺寸、对比度及布局可读，无明显遮挡/重叠。"),
    ("game.guidance.controls", 5, "visual", "guidance", "实际游戏展示或清楚传达必要操作方法。"),
    ("game.guidance.goal", 5, "visual", "guidance", "实际游戏中目标及下一步行动明确。"),
    ("game.feedback.input", 5, "runtime", "feedback", "至少一个已触发的核心输入有明确且对应的可视反馈，须有操作前后画面。"),
    ("game.feedback.event", 5, "runtime", "feedback", "至少一个实际关键事件（如命中/受伤/阶段切换）产生对应可视反馈；没有事件不能猜测；未采音频/触觉则不评价该模态。"),
    ("play.import", 6, "import", "导入", "本轮真实引擎导入及脚本编译检查成功，无产品级解析/编译错误；不等于平台原生导出包成功。"),
    ("play.launch", 6, "runtime", "启动", "本轮实际加载项目主场景并持续产生有效游戏画面，无阻断性产品错误。"),
    ("play.operate", 6, "runtime", "可操作", "本轮通过正常输入进入游戏且观察到实际操作响应，不只是窗口存在。"),
    ("code.organization", 7, "static", "组织", "源码按职责组织，核心流程和依赖可追踪；引用实际代码判断。"),
    ("code.clarity", 7, "static", "规范", "核心源码命名、状态管理及重复逻辑没有显著影响理解的缺陷；不是TODO扫描。"),
    ("code.extension", 7, "static", "扩展", "资源替换、参数调整或增加机制有清晰边界/接口，不能只凭文件数量。"),
]


def criteria():
    return [{"id": i, "column": COLUMNS[c], "mode": m, "group": g, "requirement": t} for i, c, m, g, t in _DEFS]


def dump(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_lines(path: Path):
    if not path.is_file():
        return []
    rows = []
    for number, text in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not text.strip():
            continue
        try:
            rows.append(json.loads(text))
        except json.JSONDecodeError as exc:
            # Preserve the original stream; never repair interleaved writers.
            raise ValueError(f'invalid JSONL at {path}:{number}: {exc}; raw bytes preserved') from exc
    return rows


def checked_path(root: Path, relative: str):
    p = (root / relative).resolve()
    if Path(relative).is_absolute() or not p.is_relative_to(root.resolve()) or not p.is_file():
        raise ValueError(f"invalid evidence path: {relative}")
    return p


def _valid_timestamp(value):
    # bool is an int subclass; NaN/Infinity and negative offsets are not clocks.
    return (type(value) in (int, float) and value >= 0
            and (not isinstance(value, float) or math.isfinite(value)))


def validate_judgments(raw: dict, manifest: dict, root: Path, specs=None):
    """Validate provenance/coverage, not semantic truth. Unproved claims score zero."""
    index = {e["id"]: e for e in manifest["items"]}
    # Verify source hashes BEFORE considering claims.
    for item in index.values():
        if sha(checked_path(root, item["path"])) != item["sha256"]:
            raise ValueError(f"evidence was modified: {item['id']}")
    entries = raw.get("checks", [])
    counts = Counter(x.get("id") for x in entries)
    if any(n != 1 for n in counts.values()):
        raise ValueError("duplicate judgment IDs")
    specs = criteria() if specs is None else specs
    allowed = {c['id'] for c in specs}
    if set(counts) - allowed:
        raise ValueError("unexpected judgment ID")
    candidates = {x['id']: x for x in entries}
    file_lines = {}
    validated = []
    for spec in specs:
        row = candidates.get(spec['id'], {})
        status = row.get('status', 'UNVERIFIED')
        if status not in {'PASS', 'FAIL', 'UNVERIFIED'}:
            raise ValueError(f"invalid status {status}")
        refs = row.get('evidence', [])
        problems = []
        if status in {'PASS', 'FAIL'} and not refs:
            problems.append('no evidence references')
        types = set()
        times = []
        action_times = []
        frame_times = []
        state_times = []
        clocks = set()
        multisession = manifest.get('clock') == 'independent_role_local_monotonic'
        session_times = {}

        def record_time(value, item, trace_row=None):
            if not _valid_timestamp(value):
                problems.append('invalid evidence timestamp')
                return False
            # Inherit only declared provenance; never convert unrelated clocks.
            labels = [manifest.get('clock'), item.get('clock')]
            if trace_row is not None:
                labels.append(trace_row.get('clock'))
            declared = [label for label in labels if label is not None]
            if any(not isinstance(label, str) or not label.strip() for label in declared):
                problems.append('invalid evidence clock')
                return False
            clocks.update(declared or [None])
            session = None
            if multisession:
                session = (trace_row or item).get('session_id') or item['id'].split(':',1)[0]
                if session not in {'A','B'}:
                    problems.append('missing native evidence session')
                    return False
            bucket = session_times.setdefault(session, {'action':[], 'state':[], 'frame':[], 'times':[]})
            if item['type']=='action':
                if trace_row is not None and trace_row.get('sent') is True and trace_row.get('kind') not in {'release','wait'}:
                    bucket['action'].append(value)
            else:bucket['times'].append(value)
            if item['type'] in {'state','frame'}:bucket[item['type']].append(value)
            if item['type'] == 'action':
                if trace_row is not None and trace_row.get('sent') is True and trace_row.get('kind') not in {'release','wait'}:
                    action_times.append(value)
            else:
                times.append(value)
            if item['type'] == 'state':state_times.append(value)
            if item['type'] == 'frame':
                frame_times.append(value)
            return True

        for ref in refs:
            item = index.get(ref.get('id'))
            if item is None:
                problems.append('unknown evidence ID')
                continue
            types.add(item['type'])
            if item['type'] == 'frame':
                record_time(item.get('t_ms'), item)
                continue
            if item['type'] == 'reference':
                continue
            # Every other file citation uses ORIGINAL physical line numbers,
            # including events and new/unknown text evidence channel types.
            if item['path'] not in file_lines:
                file_lines[item['path']] = checked_path(root, item['path']).read_text(errors='replace').splitlines()
            lines = file_lines[item['path']]
            lo, hi = ref.get('line_start'), ref.get('line_end')
            trace = item['type'] in {'state', 'action', 'event'}
            if not (type(lo) is int and type(hi) is int and 1 <= lo <= hi <= len(lines)):
                problems.append('invalid trace range' if trace else 'invalid line range')
                continue
            if trace:
                previous = {}
                for line in lines[lo-1:hi]:
                    try:
                        trace_row = json.loads(line)
                    except (ValueError, TypeError):
                        problems.append('invalid trace row')
                        continue
                    if not isinstance(trace_row, dict):
                        problems.append('invalid trace row')
                        continue
                    value = trace_row.get('t_ms')
                    if record_time(value, item, trace_row):
                        session=trace_row.get('session_id') if multisession else None
                        if session in previous and value < previous[session]:
                            problems.append('non-monotonic trace clock')
                        previous[session] = value
        if len(clocks) > 1:
            problems.append('incompatible or missing evidence clocks')
        mode = spec['mode']
        if status in {'PASS', 'FAIL'}:
            if mode == 'static' and not types & {'source', 'document'}:
                problems.append('static claim without source')
            if mode in {'visual', 'reference'} and 'frame' not in types:
                problems.append('visual claim without delivered runtime frame')
            if mode == 'reference' and 'reference' not in types:
                problems.append('reference comparison without delivered reference')
            if spec.get('requires_temporal_evidence'):
                if not any(len(set(v['frame']))>=2 and (v['state'] or v['action']) for v in session_times.values()):
                    problems.append('temporal visual claim needs multiple frames and actual trace')
                if row.get('preconditions_met') is not True or row.get('observation_complete') is not True:
                    problems.append('temporal visual trigger/window not established')
            if mode == 'runtime':
                if spec['id']=='play.launch':
                    if not types & {'state', 'frame'} or 'log' not in types:
                        problems.append('launch needs actual scene observation and engine log')
                elif 'action' not in types or not types & {'state', 'frame'}:
                    problems.append('runtime claim needs actual input and outcome')
                if status=='PASS' and spec['id']!='play.launch':
                    if not any(len(set(v['state']))>=2 and any(min(v['state'])<=t<=max(v['state']) for t in v['action']) for v in session_times.values()):
                        problems.append('dynamic PASS needs actual action and before/after delivered state')
                if row.get('preconditions_met') is not True:
                    problems.append('trigger preconditions not established')
                if not any(len(set(v['times']))>=2 and (spec['id']=='play.launch' or any(min(v['times'])<=t<=max(v['times']) for t in v['action'])) for v in session_times.values()):
                    problems.append('no synchronized before/action/after window')
                if row.get('observation_complete') is not True:
                    problems.append('observation window incomplete')
                if spec['id'] in {'mechanic.hit', 'game.feedback.input', 'game.feedback.event'}:
                    if not any(len(set(v['frame']))>=2 and any(min(v['frame'])<=t<=max(v['frame']) for t in v['action']) for v in session_times.values()):
                        problems.append('visual response needs synchronized before/after frames')
            if mode == 'import' and 'log' not in types:
                problems.append('import claim without actual import log')
            if status == 'FAIL' and not row.get('counterexample'):
                problems.append('FAIL requires actual counterexample')
        if spec.get('execution_tiers') in {'whitebox-mechanic10-50-100.v1', 'whitebox-mechanic10-50-100.v2'}:
            from .endpoint_sparse import execution_schema
            from .codex import validate_schema
            validate_schema(row.get('execution'), execution_schema())
            if status == 'PASS' and not set(manifest.get('endpoint_frames', {}).get(spec['id'], [])) & {ref['id'] for ref in refs}:
                problems.append('complete endpoint frame missing')
            if status == 'PASS' and row['execution']['status'] != 'NORMAL':
                problems.append('complete PASS requires observed normal execution')
            if spec.get('execution_tiers') == 'whitebox-mechanic10-50-100.v2':
                from .endpoint_sparse import endpoint_verification_schema
                verify = row.get('endpoint_verification')
                validate_schema(verify, endpoint_verification_schema())
                contract = manifest.get('endpoint_contracts', {}).get(spec['id'], {})
                rubric = contract.get('rubric', {})
                if status == 'PASS' and (not contract or not verify['last_action_completed']
                        or not verify['stable_result'] or not verify['reason'].strip()
                        or any(len(verify[key]) != len(rubric.get(key, [])) or not all(verify[key])
                               for key in ('visible_conditions','state_event_conditions'))):
                    problems.append('complete endpoint obligations or stable final action not verified')
                if status == 'PASS' and not problems:
                    from .endpoint_sparse import observation_support
                    observed, endpoint = observation_support(root, {'scoring_policy':{'version':spec['execution_tiers']}}, {**row, **spec})
                    if not observed or not endpoint:
                        problems.append('complete endpoint final action or stable frame lacks actual execution support')
        if problems:
            status = 'UNVERIFIED'
        validated.append({**row, **spec, 'status': status,
                          'score': 1 if status == 'PASS' else 0,
                          'validation_issues': problems})
    return validated


def aggregate(rows: list[dict], *, valid: bool, method: str, protocol=VERSION, scope=None, aggregation=EQUAL_COLUMNS):
    if aggregation not in {EQUAL_COLUMNS, LEGACY_GROUPS}:
        raise ValueError("unknown aggregation rule")
    from .asset_reservation import coverage as asset_coverage
    by_col = {}
    for col in COLUMNS:
        group = [r for r in rows if r['column'] == col]
        if not valid:
            score = None
        elif col == COLUMNS[1] and protocol == 'whitebox-eightcol-batch-expanded.v4':
            endpoints = {}
            for row in group:
                endpoint = row.get('endpoint_id')
                weight = row.get('endpoint_weight')
                atom_weight = row.get('atom_weight')
                if not endpoint or not isinstance(weight, (int, float)) or weight <= 0 or not isinstance(atom_weight, (int, float)) or atom_weight <= 0:
                    raise ValueError('v4 mechanic atom is missing valid preregistered weights')
                endpoints.setdefault(endpoint, {'weight': weight, 'atoms': []})
                if endpoints[endpoint]['weight'] != weight:
                    raise ValueError('inconsistent endpoint weight')
                endpoints[endpoint]['atoms'].append(row)
            endpoint_scores = []
            for endpoint, data in endpoints.items():
                weights = [r['atom_weight'] for r in data['atoms']]
                if not math.isclose(sum(weights), 1.0, rel_tol=0, abs_tol=1e-9):
                    raise ValueError(f'v4 atom weights do not normalize for {endpoint}')
                endpoint_scores.append((data['weight'], 100 * sum(r['score'] * r['atom_weight'] for r in data['atoms'])))
            score = (sum(w * s for w, s in endpoint_scores) / sum(w for w, _ in endpoint_scores)) if endpoint_scores else 0.0
        elif col == 'Gameness':
            score = 100 * mean(mean(r['score'] for r in group if r['group'] == g) for g in ['layout', 'guidance', 'feedback'])
        else:
            score = 100 * mean(r['score'] for r in group)
        by_col[col] = {'score': round(score, 2) if score is not None else None,
                       'counts': dict(Counter(r['status'] for r in group)), 'checks': len(group)}
        if col == COLUMNS[2]:
            covered = asset_coverage(group)
            if covered is not None:
                by_col[col]['coverage'] = covered
    overall = None
    if valid:
        if aggregation == EQUAL_COLUMNS:
            overall = round(mean(by_col[n]['score'] for n in COLUMNS), 2)
        else:
            c = mean(by_col[n]['score'] for n in COLUMNS[:3])
            q = mean(by_col[n]['score'] for n in COLUMNS[3:5])
            overall = round(mean([c, q, by_col['Gameness']['score'], by_col['Playable']['score']]), 2)
    result = {'protocol': protocol, 'method': method, 'valid': valid,
            'aggregation': aggregation, 'code_in_total': aggregation == EQUAL_COLUMNS,
            'scope': scope or 'G001 pilot; six predeclared mechanic smoke checks, NOT full frozen mechanism correctness',
            'score_semantics': 'budget-bounded verified completion; UNVERIFIED=0; harness errors invalidate the run',
            'native_export_tested': False, 'audio_judged': False,
            'columns': by_col, 'overall_score': overall,
            'status_counts': dict(Counter(r['status'] for r in rows)), 'checks': rows}
    if protocol == 'whitebox-eightcol-batch-expanded.v4':
        mechanics = [r for r in rows if r['column'] == COLUMNS[1]]
        counts = Counter(r['status'] for r in mechanics)
        result['mechanic_evidence_coverage'] = {
            'total_atoms': len(mechanics), 'pass': counts['PASS'], 'fail': counts['FAIL'],
            'unverified': counts['UNVERIFIED'],
            'coverage_rate': round((counts['PASS'] + counts['FAIL']) / len(mechanics), 4) if mechanics else 0.0,
            'fail_rate': round(counts['FAIL'] / len(mechanics), 4) if mechanics else 0.0,
            'unverified_rate': round(counts['UNVERIFIED'] / len(mechanics), 4) if mechanics else 0.0,
            'semantics': 'FAIL and UNVERIFIED each contribute 0; UNVERIFIED is not an established product defect.'}
    return result



def write_operation_report(root: Path, plan: dict):
    """Human-readable view of the same frozen plan; never execution proof."""
    lines = ['# Sol 操作报告（计划）', '',
             '本文件从 sol_plan.json 确定性生成，不代表测试已经执行或通过。实际结果见 runtime/execution.json。', '',
             plan['summary'], '', '## 静态发现', '', plan['static_findings'], '',
             f"运行预算上限：{plan['max_duration_ms']} ms。", '']
    for probe in plan['probes']:
        lines += [f"## {probe['id']}", '', probe['purpose'], '',
                  '检查项：' + ', '.join(probe['criterion_ids']), '',
                  '前提：`' + json.dumps(probe['preconditions'], ensure_ascii=False) + '`', '',
                  '| 步骤 | 类型 | 输入 | 时长/超时 ms | 观察条件 |',
                  '|---|---|---|---|---|']
        for step in probe['steps']:
            condition = ''
            if step['kind'] in {'wait_until', 'move_until'}:
                condition = f"{step['watch']} {step['op']} {step['target_watch'] or step['value']}"
            if step['kind'].startswith('mouse_'):
                physical = json.dumps({key: step[key] for key in
                    ('x', 'y', 'to_x', 'to_y', 'button', 'delta_x', 'delta_y')
                    if key in step}, ensure_ascii=False, sort_keys=True)
            else:
                physical = step.get('key', '')
            physical = physical.replace('|', '\\|')
            lines.append(f"| {step['id']} | {step['kind']} | {physical} | {step['duration_ms']}/{step.get('timeout_ms', 0)} | {condition} |")
        lines.append('')
    (root/'operation_report.md').write_text('\n'.join(lines), encoding='utf-8')

def write_report(root: Path, report: dict):
    dump(root / 'scores.json', report)
    names = COLUMNS + ['总分']
    values = [report['columns'][n]['score'] for n in COLUMNS] + [report['overall_score']]
    cell = lambda x: 'INVALID' if x is None else f'{x:.2f}'
    formula = ('总分 = (故事完整性 + 机制完整性 + 资产预留 + 白模输入一致性 + 白模构建质量 + Gameness + Playable + Code) / 8。每列权重1/8。'
               if report.get('aggregation', LEGACY_GROUPS) == EQUAL_COLUMNS else
               '旧口径：总分 = mean(mean(故事,机制,资产预留), mean(输入一致性,构建质量), Gameness, Playable)。Code不进总分。')
    lines = ['# 白模八列试评', '', f"协议：`{report['protocol']}`；有效运行：{report['valid']}",
             '', '**这是预算内已验证完成度，不是完整 frozen benchmark 正确率。UNVERIFIED 按0分计；工具错误整次无效。**',
             '机制列仅六项固定抽测；故事/资产/Code为静态证据审查。Playable导入项不是原生导出包验证；未评价音频/触觉。', '',
             '| Method | ' + ' | '.join(names) + ' |', '|---|' + '---|' * len(names),
             '| ' + report['method'] + ' | ' + ' | '.join(cell(v) for v in values) + ' |', '',
             formula, '']
    if report.get('judge_summary'):
        lines.extend([report['judge_summary'], ''])
    if report.get('limitations'):
        lines.extend(['适用范围与限制：', ''] + ['- ' + x for x in report['limitations']] + [''])
    asset = report['columns'][COLUMNS[2]].get('coverage')
    if asset:
        lines.extend(['资产预留：逐个要求核对对应插口，' + f"{asset['reserved']}/{asset['required']} 已证实绑定。",
                      '', '| 类别 | 有效插口 / 要求数 | 该部分覆盖率 |', '|---|---:|---:|'])
        for kind, group in asset['by_kind'].items():
            lines.append(f"| {kind} | {group['reserved']}/{group['required']} | {group['score']:.2f}% |")
        lines.extend(['', '全列按冻结要求逐项等权；类别小计不另加权。冻结的复合VFX要求仍按原条件核验。', ''])
    lines.extend(['## 逐项证据', ''])
    for r in report['checks']:
        lines.extend([f"### {r['id']} — {r['status']}", r['requirement'], '', r.get('reason', '未返回判断'), ''])
        if r.get('frozen_subcheck_id'):
            lines.append(f"- 冻结来源：`{r['frozen_assertion_id']}` / `{r['frozen_subcheck_id']}`；需求：{', '.join(r.get('requirement_ids', []))}")
        for e in r.get('evidence', []):
            lines.append(f"- `{e['id']}` lines {e.get('line_start')}–{e.get('line_end')}: {e.get('observation', '')}")
        if r.get('validation_issues'):
            lines.append('- 校验降级：' + '; '.join(r['validation_issues']))
        lines.append('')
    (root / 'report.md').write_text('\n'.join(lines), encoding='utf-8')
