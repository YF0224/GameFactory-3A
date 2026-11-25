"""Readable independent Astra report from preserved verdicts and deterministic audit."""
from collections import Counter
from pathlib import Path
import argparse
import json
from .common import read, dump
from .project_eval_judge import ref


def summaries(root):
    result = read(root/'result.json')
    tasks = {t['task_id']: t for t in read(root/'input/tasks.json')}
    summary = {}
    for kind in ('mechanic', 'gamefeel', 'vfx'):
        rows = [r for r in result['checks'] if tasks[r['task_id']]['kind'] == kind]
        valid = [r['credit_percent'] for r in rows if isinstance(r.get('credit_percent'), (int, float))]
        total = sum(t['kind'] == kind for t in tasks.values())
        summary[kind] = {'mean': round(sum(valid)/len(valid), 4) if len(valid) == total else None,
                         'valid': len(valid), 'denominator': total,
                         'tiers': dict(Counter(str(n) for n in valid))}
    summary['import'] = result['import_summary']
    return summary


def report(root):
    root = Path(root).resolve()
    result = read(root/'result.json')
    policy = read(root/'policy.json')
    old = Path(policy['parent_result']['path']).parent
    new_summary, old_summary = summaries(root), summaries(old)
    audit_path = root/'deterministic_audit.json'
    audit = read(audit_path) if audit_path.exists() else {'status': 'PENDING'}
    if audit.get('status') == 'PASS' and audit['result'] != ref(root/'result.json'):
        raise ValueError('Audit refers to a different result')
    tasks = read(root/'input/tasks.json')
    rows = {r['task_id']: r for r in result['checks']}
    plan = read(root/'plan.json')
    lines = ['# GLM G008：Astra 独立重评', '',
             '状态：'+result['status']+'（未审计）；确定性复核 '+audit['status']+'，独立语义审计 PENDING。', '',
             '同一最终 round_010 GLM 候选；源码检查、整项目 plan 和最终 judge 均为 gpt-6-astra。旧结果完整保留，本次继承旧判词 0 项。', '',
             '规划实际 %.3f 秒，含一次格式修正；共享上限 1800 秒。新原生录制时间轴 %d ms，上限 300000 ms。'
             % (read(root/'stages/plan.json')['elapsed_seconds'], plan['native_plan']['max_duration_ms']), '',
             '音频由 Qwen 观察真实 WAV，Astra 据原始观察最终判定；Astra 未直接听音频。历史合格声学观察复用须逐项注明。', '',
             '两轮使用同一作者候选，但本轮重新plan和录制；覆盖及证据不同，分差不能全部归因于judge模型。', '',
             '| 指标 | 上轮混合判词 | 本次 Astra | 本次分母 |', '|---|---:|---:|---:|']
    for kind, label in [('mechanic', 'Mechanic'), ('gamefeel', 'Gamefeel'), ('vfx', 'VFX')]:
        new, before = new_summary[kind], old_summary[kind]
        lines.append('| %s | %s | %s | %d/%d 有效 |' % (label, before['mean'], new['mean'], new['valid'], new['denominator']))
    for key, label in [('confirmed', 'Import 确认对象'), ('texture_confirmed', 'Texture 确认')]:
        denominator = 'denominator' if key == 'confirmed' else 'texture_denominator'
        a, b = old_summary['import'], new_summary['import']
        lines.append('| %s | %d/%d | %d/%d | 保留全部冻结对象 |' % (label,a[key],a[denominator],b[key],b[denominator]))
    lines += ['', 'Mechanic/Gamefeel 使用既有结果导向 10%/50%/100%；VFX 保留原 refine-tiered.v1 严格口径。未覆盖不冒称产品 bug，工具错误不给产品零分；本报告不生成八列总分。', '',
              '## 逐项依据', '', '| 类别 | 冻结判项 / 目标 | 结果 | Astra 依据 |', '|---|---|---:|---|']
    for task in tasks:
        row = rows[task['task_id']]
        if task['kind'] == 'import':
            outcome = '确认出现' if row.get('confirmed') else row.get('status', 'UNVERIFIED')
            if row.get('texture_confirmed'): outcome += '；纹理确认'
        else:
            outcome = str(row.get('credit_percent'))+'%'
        reason = row.get('reason', '').replace('|', '\\|').replace('\n', '<br>')
        goal = task['goal'].replace('|', '\\|')
        lines.append('| %s | `%s`<br>%s | %s | %s |' % (task['kind'],task['task_id'],goal,outcome,reason))
    lines += ['', '## 原始材料', '', '- [本次结果](result.json)；[发布回执](publication.json)；[确定性复核](deterministic_audit.json)。',
              '- [整项目 plan](plan.json)；[真实实录及帧清单](evidence/manifest.json)；所有请求/响应位于 `model_calls/`。',
              '- [原始独立源码判断](static.json)。']
    if (root/'source_tier_recovery_receipt.json').exists():
        lines += ['- [源码 10% 档修正回执](source_tier_recovery_receipt.json)与[有效源码判断](effective_static.json)：原始判词保留，去除完整规格对源码存在档的污染，不改变运行档及 VFX 规则。']
    lines += ['', '未满足真实双端、角色/输入前置条件的项与原始 motion 载荷缺失均保留为限制；没有补写作者玩法、伪造双端、重置 refine 次数或用参考图替代运行画面。', '']
    (root/'report.md').write_text('\n'.join(lines), encoding='utf-8')
    dump(root/'report_source.json', {'result':ref(root/'result.json'), 'old_result':policy['parent_result'],
         'summary':new_summary, 'old_summary':old_summary, 'report':ref(root/'report.md'),
         'semantic_audit':'PENDING', 'official_eight_column_total':None})
    return new_summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(report(args.root), ensure_ascii=False))


if __name__ == '__main__':
    main()
