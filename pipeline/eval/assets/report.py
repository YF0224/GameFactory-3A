from __future__ import annotations
from collections import Counter, defaultdict
import csv
import json
import platform
from pathlib import Path
import statistics
from .common import dump
from .constants import GEOMETRY_FORMULA, QUALITY_FORMULA, VABENCH


def cells(row):
    c = row['columns']
    return {'input_score': c['input']['score'], 'style_sol_0_4': c['style']['score'],
            'palette_mean_deltaE2000': c['style'].get('palette', {}).get('weighted_mean_deltaE2000'),
            'palette_fraction_lt10': c['style'].get('palette', {}).get('pixel_fraction_deltaE_lt10'),
            'quality_index_0_100': c['quality']['score']}


def summary(values):
    known = [v for v in values if v is not None]
    return {'mean': statistics.mean(known) if known else None, 'known': len(known), 'null': len(values) - len(known),
            'coverage': len(known) / len(values) if values else None}


def format_summary(s):
    return f"{s['mean']:.4f} ({s['known']}/{s['known'] + s['null']}; null={s['null']})" if s['mean'] is not None else f"null (0/{s['null']})"


def write_reports(out, rows, inventory, metadata, dispersion):
    fields = ['game', 'task_id', 'provider', 'scope', 'input_mode', 'delivered', 'input_score', 'style_sol_0_4',
              'palette_mean_deltaE2000', 'palette_fraction_lt10', 'quality_index_0_100', 'failure_label', 'notes']
    with (out / 'scores.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fields); writer.writeheader()
        for row in rows:
            # Literal null, not a fake zero or an ambiguous empty numeric cell.
            values = {**{k: row[k] for k in fields if k in row}, **cells(row), 'notes': ' | '.join(row['notes'])}
            writer.writerow({k: ('null' if v is None else v) for k, v in values.items() if k in fields})
    groups = defaultdict(list)
    for row in rows:
        # Never average image and text input adherence together.
        groups[row['game'], row['provider'], row['scope'], row['input_mode']].append(row)
    judging = ('复用历史判词，本次未调用sol' if metadata.get('source_run') else
               ('跳过' if metadata.get('no_sol') else '见逐资产 JSON（预检不会调用）'))
    body = ['# 3D 资产评测结果', '', '三列独立报告，不合并总分。第1列 image/text 分组，不跨输入模式平均。',
            '第2列保留 sol 风格分、色板 ΔE、色板覆盖三个独立量，不将其混成标量。',
            '均值只代表有值的交付资产；括号为有值数/计划数及 null 数，不能据此声称全量质量。', '',
            f"- 运行：`{out}`", f"- 状态：{metadata['status']}",
            f"- 记录：{len(rows)}；实际交付：{sum(r['delivered'] for r in rows)}；排除未交付provider行：{len(metadata.get('excluded_missing_asset_rows', []))}；耗时：{metadata.get('elapsed_seconds', 0):.1f}s。",
            f"- 测试模式：{metadata.get('mode', 'metrics')}；API 调用数：{metadata.get('api_calls', 0)}；rubric 判定：{judging}。",
            '元数据预检不等于渲染、推理或评分链路通过；null 不代表零分。', '',
            '| 游戏 | provider | scope | 输入模式 | 第1列输入符合度 | 第2列sol(0–4) | 色板ΔE↓ | ΔE<10占比↑ | 第3列质量(0–100) |',
            '|---|---|---|---|---|---|---|---|---|']
    aggregated = []
    for (game, pro, scope, mode), group in sorted(groups.items()):
        agg = {k: summary([cells(r)[k] for r in group]) for k in cells(group[0])}
        aggregated.append(dict(game=game, provider=pro, scope=scope, input_mode=mode, metrics=agg))
        order = ['input_score', 'style_sol_0_4', 'palette_mean_deltaE2000', 'palette_fraction_lt10', 'quality_index_0_100']
        body.append('| ' + ' | '.join([game, pro, scope, mode] + [format_summary(agg[k]) for k in order]) + ' |')
    body += ['', '## null 与失败原因', '']
    null_counts = {k: summary([cells(r)[k] for r in rows]) for k in cells(rows[0])} if rows else {}
    for key, values in null_counts.items():
        body.append(f"- {key}：{values['known']} 有值，{values['null']} null。")
    for label, count in Counter(r['failure_label'] for r in rows if r['failure_label']).items():
        body.append(f'- {label}：{count} 行。')
    body += ['', '逐资产原因见 JSON notes 与下方 appendix 失败清单；缺失模型输出从未由代码补齐。',
             '', '## 游戏级风格离散度', '']
    for item in dispersion:
        body.append(f"- {item['game']} / {item['provider']} / {item['scope']}：n={item['n']}，距离均值={item['mean']}，方差={item['variance']}；离群={item['outliers']}。")
    body += ['此统计也受资产类别差异影响，不能解释为纯风格指标。', '', '## 阶段进度', '',
             f"本次scope={','.join(sorted({r['scope'] for r in rows}))}：{len(rows)}条计划记录；{sum(r['delivered'] for r in rows)}份交付；耗时{metadata.get('elapsed_seconds', 0):.1f}s；null数见上表。",
             '本次按用户明确授权使用完整priority清单评测Obj/Scene。',
             'motion 与 VFX 不实现；不启动 GUI 引擎，不改生成代码。']
    (out / 'report.md').write_text('\n'.join(body) + '\n')
    appendix = ['# 方法与审计附录', '', '## 数据盘点', '',
                f"- 游戏数：{inventory['games']}；W06 有 hex 色板：{inventory['palette_games_count']}；无色板：{inventory['no_palette_games']}。",
                f"- 任务/rubric 覆盖：`{json.dumps(inventory['coverage'], ensure_ascii=False)}`。",
                '- rubric 按任务后缀映射：G001_obj_005 → G001_port_guard_arena_obj_005.json；也兼容基础短 task_id 文件名。',
                f"- rubric prompt 差异审计：{len(inventory['rubric_prompt_mismatches']) if inventory.get('rubric_content_audited', True) else '未执行（本次跳过 rubric 内容读取）'}。不能默默覆盖任务prompt。", '',
                '### provider（按真实metadata/目录，不按扩展名猜测）', '']
    for item in inventory['providers']:
        appendix.append(f"- {item['kind']} / {item['provider']}：{item['deliveries']}；{item['classification']}。")
    appendix += [str(inventory['scene_note'] or ''), '', '## 指标定义与限制', '',
        '- 第1列image：facebook/dinov2-base，最后隐藏层CLS、L2归一化，12个方位角0..330°/30°、仰角15°，与参考图取最大余弦；记录最佳视角。不是相机对齐指标，不用PSNR/SSIM/LPIPS。',
        '- 参考图带alpha时保留其alpha；DINO需RGB，两侧alpha均合成到固定中性RGB(196,202,209)。无alpha时不猜参考掩码，render合成到参考图一像素周边的逐通道RGB中位色；参考图保持原样。',
        '- 轮廓IoU本版不计算：未做相机配准且不能保证参考掩码；统一null并解释。',
        '- 第1列text：sol逐条输出所有rubric checks。只把requirement_compliance维度计入输入符合度，G/Q维度仅保留审计，避免风格与传统质量掺入第1列。score=PASS/(PASS+FAIL)；UNVERIFIED单列；分母零或无rubric则null。',
        '- 原rubric中的PARTIAL不使用；UNKNOWN通过提示要求模型自行输出UNVERIFIED。判定结果不由代码补字段、改名或补分。未校准的静帧不能验证米制高度或动态发光/旋转。',
        '- 六个标准视角：V01_front(0,0)、V02_back(180,0)、V03_left(270,0)、V04_right(90,0)、V05_top(0,89)、V06_three_quarter(45,15)。sol图片顶部编号，不参与像素指标。',
        '- 渲染复用priority_assets/renderer/render.mjs，配置补丁仅设置alpha/透明、视角、路径与截图参数；灯光、材质、解码、native几何和归一化不变。原始source hash与配置补丁落盘，不编辑旧实现。',
        '- 色板：六视角前景alpha>=243；sRGB转Lab(D65)，确定性均匀最多50000像素拟合k-means(k=5,n_init=10,seed=0；纯色图k退化为1)。所有前景像素分配最近Lab中心，按真实占比加权各中心到W06色板的最近ΔE2000。另在所有前景像素直接计算最近色板ΔE<10的真实像素占比，不用中心近似占比。无W06 hex时两项null。',
        '- 游戏级风格离散度：每资产六视角DINO CLS单位向量取均值后再归一化，同游戏/provider/scope计算不重复两两余弦距离的总体均值和方差。离群=资产平均距离>这些平均距离的均值+2标准差。n<2为null。不进单资产分。',
        '- MUSIQ：pyiqa musiq原始六视角均值/100，无缺视角均值代替完整均值。BRISQUE/NIQE仅参考；NIQE的float64使用CPU，其他优先MPS，异常算子回退CPU并记录。',
        '- 几何：trimesh process=False、按节点变换计三角形实例；面积<= (模型最大轴跨度*1e-8)^2为退化；拓扑诊断临时按相对1e-10精度焊接UV缝重合点，边关联面数!=2（含边界）为非流形。不会修改输入网格。贴图检查所有被textures引用的图像尺寸，不信metadata自报。',
        '- Object几何公式：' + GEOMETRY_FORMULA,
        '- Scene几何公式(0-100)：100*(1 - 0.375*min(degenerate_face_ratio/0.01,1) - 0.375*min(nonmanifold_edge_ratio/0.10,1) - 0.25*(1-texture_match_fraction))。移除目标三角面数偏差项后，按剩余原始权重比例归一化；退化面阈值1%，非流形边阈值10%，边关联面数!=2按原定义(含边界)统计。',
        '- 传统质量公式：' + QUALITY_FORMULA,
        '- 权重为原实现的预设工程权重，不是经人类MOS校准的通用感知分。Object缺失必需项为null且不重分配权重；Scene只移除目标面数项并重归一剩余权重。',
        '', '## sol 调用与共享并发', '',
        '- 只import whitebox_eval.codex.call_codex；model=gpt-6.1-sol，reasoning=medium，images传入6张编号图，timeout=600秒。',
        '- asset_eval自身串行+跨进程文件锁。502/断流最多重试1次；call_codex内部重试关闭。无模型替代、无代码修复JSON。',
        '- 正在运行的只读whitebox batch有未共享信号量的嵌套并行池；瞬时空闲不构成可保留slot。因此检测到batch/其他sol时不发起调用，标记api_concurrency_unavailable。未修改、停止或节流该批次。缺少response用response_absent.json记录，而非伪造response。',
        '', '## 游戏输入形象参考', '',
        '- 匹配规则：3D object任务的明确role（character/player/enemy/npc等）+image_path，校验文件位于test_samples；视频阶段必须由sol指明候选reference和主角区域，无法匹配就停止，不按名字猜。']
    for game, refs in sorted(inventory['character_references'].items()):
        if game in {r['game'] for r in rows}:
            for ref in refs:
                appendix.append(f"- {game} / {ref['task_id']} / {ref['role']}：`{ref['path']}`")
    appendix += ['', '## 生成侧上下文检查（不修改生成器）', '',
                 '- 基础任务prompt是否包含完整梗概只做精确原文包含检查，不能据此推断语义上没有任何世界观。',
                 '- 实际object metadata还有shared_prompt/context_excerpt；video request还有GAME CONTEXT。基础任务和真实发给服务的prompt分开检查，不能仅凭本地保留full_context声称全部原文已传给服务。',
                 '```json', json.dumps(inventory['generation_context_audit'], ensure_ascii=False, indent=2), '```',
                 '```json', json.dumps(inventory['generation_context_examples'], ensure_ascii=False, indent=2), '```',
                 '', '## VABench 对齐', '',
                 VABENCH['alignment_status'],
                 '', '## 模型、依赖与设备', '',
                 '完整版本见 environment.json / requirements.lock.txt，DINO revision/processor见 models.json；权重不写入输入目录。',
                 'DINO官方仓库：https://huggingface.co/facebook/dinov2-base',
                 'pyiqa官方实现：https://github.com/chaofengc/IQA-PyTorch',
                 '视频/音频后续新依赖尚未安装；不会回退base环境。video.py/audio.py仅有阶段辅助函数，完整后续评测尚未实现或验收。',
                 '', '## 失败清单', '']
    appendix += ['', '## Scene包与provider归属', '']
    for bundle in inventory.get('scene_bundle_deliveries', []):
        appendix.append(f"- {bundle['task_id']}：`{bundle['archive_path']}`；{bundle['reason']}")
    for r in rows:
        if r['failure_label']:
            appendix.append(f"- {r['task_id']} / {r['provider']}：{r['failure_label']}；" + ' | '.join(r['notes']))
    (out / 'appendix.md').write_text('\n'.join(appendix) + '\n')
    dump(out / 'aggregate.json', {'groups': aggregated, 'metric_coverage': null_counts, 'style_dispersion': dispersion})
    dump(out / 'run.json', metadata)
