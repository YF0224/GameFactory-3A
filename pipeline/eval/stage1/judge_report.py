"""Render judge scores without changing the accepted capture protocol."""
from pathlib import Path

from .protocol import COLUMNS, EQUAL_COLUMNS, LEGACY_GROUPS, dump


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
    if asset and 'by_dimension' in asset:
        labels = {'placeholder': '占位', 'binding': '替换', 'hook': '挂点'}
        lines.extend([f"资产预留：冻结需求共 {asset['required']} 项；占位、替换、挂点分别核验，三个维度等权。",
                      '', '| 维度 | 已证实 / 要求数 | 覆盖率 |', '|---|---:|---:|'])
        for dimension, group in asset['by_dimension'].items():
            lines.append(f"| {labels[dimension]} | {group['reserved']}/{group['required']} | {group['score']:.2f}% |")
        lines.extend(['', '资产列 = (占位覆盖率 + 替换覆盖率 + 挂点覆盖率) / 3；各维度独立计分。', ''])
    elif asset:
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
