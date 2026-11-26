"""Per-case criteria for all eight stage1 metrics, built in one pass.

Sources per case (both must be ``status: frozen``):
``test_samples/<GameID>/rubric_whitebox_core/rubric.json`` (tiered-core-v1, C2 count by tier
S=8/M=12/L=20/L-Stress=25) for mechanic, ``rubric_whitebox_core12/rubric.json`` for C3, the single
frozen ``eval/rubric_design/contract_history/<GameID>/*/rubric.json`` for Q/G,
plus the generic checks below. Rules migrated from the
historical evaluator so the same case gets the same items:

* 机制完整性  one row per scored C2 subcheck; group = its endpoint (assertion)
* 资产预留    one row per scored C3 subcheck x {placeholder, binding, hook}
* 白模输入一致性 / 白模构建质量 / Gameness  Q and G subchecks routed by
  requirement ids / topic / text, plus six generic visual rows
* 故事完整性 / Playable / Code  fixed generic rows

Every row: ``{id, metric, mode, group, requirement, requirement_ids, ...}``;
``mode`` is static | runtime | visual | reference | import.
"""
from __future__ import annotations

from .paths import EVAL_DATA, FRAMEWORK, RUBRIC_ROOT, SAMPLES, read_json, sha256

TIERED = 'rubric_whitebox_core/rubric.json'            # C2 mechanic (tiered-core-v1) - legacy fallback
RUBRIC = 'rubric_whitebox_core12/rubric.json'          # C3 assets - legacy fallback
CONTRACT_HISTORY = FRAMEWORK / 'eval' / 'rubric_design' / 'contract_history'  # legacy fallback
VERSION = 'stage1-criteria.v1'

STORY, MECHANIC, ASSET, INPUT, QUALITY, GAMENESS, PLAYABLE, CODE = (
    'story', 'mechanic', 'asset_slot', 'input_consistency', 'build_quality', 'gameness', 'playable', 'code')

# (id, metric, mode, group, requirement)
GENERIC = [
    ('story.background', STORY, 'static', '背景', '交付文档或游戏文本明确交代故事背景、世界或场景缘由。'),
    ('story.identity', STORY, 'static', '身份', '明确说明玩家身份，且与任务设定一致。'),
    ('story.goal', STORY, 'static', '目标', '明确交代玩家目标和行动动机。'),
    ('story.plot', STORY, 'static', '情节', '具有符合需求的基本开端和结束/成败叙事；S级允许简短开头，不要求长篇故事。'),
    ('quality.complete', QUALITY, 'visual', '完整', '实际画面包含可辨认的场地、角色及关键交互对象，无大块缺失或错误材质。'),
    ('quality.readable', QUALITY, 'visual', '可读', '白模轮廓、光照和对象区分支持理解玩法，不以精细美术水平打分。'),
    ('quality.defects', QUALITY, 'visual', '缺陷', '已观察视角中没有明显穿插、悬空、遮挡或相机严重异常；不得推广为全场景无缺陷。'),
    ('game.layout.hierarchy', GAMENESS, 'visual', 'layout', '实际UI信息层级清楚，主要状态与次要信息可区分。'),
    ('game.layout.readable', GAMENESS, 'visual', 'layout', '实际UI文字、尺寸、对比度及布局可读，无明显遮挡/重叠。'),
    ('game.guidance.controls', GAMENESS, 'visual', 'guidance', '实际游戏展示或清楚传达必要操作方法。'),
    ('play.import', PLAYABLE, 'import', '导入', '本轮真实引擎导入及脚本编译检查成功，无产品级解析/编译错误；不等于平台原生导出包成功。'),
    ('play.launch', PLAYABLE, 'runtime', '启动', '本轮实际加载项目主场景并持续产生有效游戏画面，无阻断性产品错误。'),
    ('play.operate', PLAYABLE, 'runtime', '可操作', '本轮通过正常输入进入游戏且观察到实际操作响应，不只是窗口存在。'),
    ('code.organization', CODE, 'static', '组织', '源码按职责组织，核心流程和依赖可追踪；引用实际代码判断。'),
    ('code.clarity', CODE, 'static', '规范', '核心源码命名、状态管理及重复逻辑没有显著影响理解的缺陷；不是TODO扫描。'),
    ('code.extension', CODE, 'static', '扩展', '资源替换、参数调整或增加机制有清晰边界/接口，不能只凭文件数量。'),
]

ASSET_DIMENSIONS = {
    'placeholder': '占位：该需求对应的实际占位对象、组件或资源目标已在交付源码/场景中创建并连接真实入口。单有需求清单或声明不算实现；本项不要求替换和挂点也已完成。',
    'binding': '替换：该需求的资源引用、加载、实例化或场景赋值链已真实连接，可将占位资源换成最终资源；只定义未被使用的字段或函数不算。单独核实本项，不要求其他两项同时通过。',
    'hook': '挂点：该需求对应的挂载位置、动作/音效/特效/播放触发接口或场景接入点存在，并有真实调用或绑定链；无调用的空接口不算。单独核实本项，不要求其他两项同时通过。',
}

TEMPORAL_WORDS = ('流动', '翻卷', '摆动', '旋转', '呼吸灯', '延迟', '毫秒', '顿帧', '慢动作', '后坐',
                  '屏幕震动', '鼠标控制', '动态更新', '实时更新', '冻结，恢复', '失焦')
AUDIO_ONLY_REQS = {'F05', 'F06', 'F08', 'W07'}


def _row(ident, metric, mode, group, requirement, requirement_ids=(), **extra):
    return {'id': ident, 'metric': metric, 'mode': mode, 'group': group,
            'requirement': requirement, 'requirement_ids': list(requirement_ids), **extra}


def _scored(subchecks):
    return [s for s in subchecks if s.get('scoring_role', 'scored') == 'scored']


def _mechanic(rubric):
    rows = []
    for a in rubric['assertions']:
        if a['table_column'] != 'C2' or a.get('applicable') is False:
            continue
        for sub in _scored(a['binding']['subchecks']):
            rows.append(_row(f"atom.{a['assertion_id']}.{sub['id']}", MECHANIC, 'runtime',
                             a['assertion_id'], sub['text'], sub['requirement_ids'],
                             endpoint=a['assertion_id'], endpoint_text=a['assertion']))
    return rows


def _assets(rubric):
    rows = []
    for a in rubric['assertions']:
        if a['table_column'] != 'C3' or a.get('applicable') is False:
            continue
        for sub in _scored(a['binding']['subchecks']):
            for dim, rule in ASSET_DIMENSIONS.items():
                rows.append(_row(f"asset.{a['assertion_id']}.{sub['id']}.{dim}", ASSET, 'static',
                                 sub['system'], f'{sub["text"]}\n{rule}', sub['requirement_ids'],
                                 asset_kind=sub['system'], asset_dimension=dim,
                                 asset_item_id=f"asset.{a['assertion_id']}.{sub['id']}"))
    return rows


def _route_visual(sub):
    """Route one frozen Q/G subcheck; return (metric, mode, group, requirement, extra) or None."""
    text, reqs, topic = sub['text'], set(sub['requirement_ids']), sub.get('topic', '')
    extra = {}
    if sub['_column'] == 'Q':
        reference = any(r.startswith('A0') for r in reqs) or any(
            t in text for t in ('冻结参考图', '参照空间关系', '冻结的主题与风格'))
        metric = INPUT if reference else QUALITY
        if 'I07' in reqs:
            metric = GAMENESS
        requirement = text + ' 仅评可视部分，声音不视为通过。'
        if reference:
            requirement += ' 对照真实参考图核对辨识轮廓、相对比例、主色分区与空间地标；允许几何白模，不要求成品美术。'
        group = 'feedback' if metric == GAMENESS else sub['id']
        return metric, ('reference' if reference else 'visual'), group, requirement, extra
    if '要求行 |' in text:
        cells = [c.strip() for c in text.split('要求行 |', 1)[1].split('|')]
        if len(cells) < 4:
            raise ValueError('malformed frozen feedback table: ' + sub['id'])
        extra['requires_temporal_evidence'] = True
        return (GAMENESS, 'visual', 'feedback',
                f'事件【{cells[0]}】实际发生时可视表现为【{cells[1]}】，结束条件【{cells[3]}】。仅评价可视投影，音频未评。未触发事件不能PASS。',
                extra)
    if any(t in topic for t in ('前端界面', 'UI 必', 'UI必')) or reqs & {'F10', 'I06'}:
        return GAMENESS, 'visual', 'layout', text, extra
    if topic.startswith('交互反馈'):
        group = 'feedback' if any(t in text for t in ('成功、失败或拒绝反馈', '阶段变化与终局', '并发单位')) else 'guidance'
        return GAMENESS, 'visual', group, text, extra
    if reqs & {'F03', 'F09', 'I07'} and '占位声音验收' not in text:
        return GAMENESS, 'visual', 'feedback', text, extra
    if not reqs & AUDIO_ONLY_REQS and '占位声音验收' not in text:
        group = 'layout' if any(t in topic for t in ('界面', 'UI')) else 'feedback'
        return GAMENESS, 'visual', group, text, extra
    return None


def _visual(rubric):
    rows, excluded = [], []
    for a in rubric['assertions']:
        if a['table_column'] not in ('Q', 'G'):
            continue
        for sub in a['binding']['subchecks']:
            routed = _route_visual(dict(sub, _column=a['table_column']))
            base = {'id': 'expanded.' + sub['id'], 'frozen_assertion_id': a['assertion_id'],
                    'requirement_ids': sub['requirement_ids']}
            if routed is None:
                excluded.append({**base, 'text': sub['text'],
                                 'reason': '纯声音、音画同步或非可视表头，本协议未评；不算PASS。'})
                continue
            metric, mode, group, requirement, extra = routed
            if any(t in requirement for t in TEMPORAL_WORDS):
                extra['requires_temporal_evidence'] = True
            rows.append(_row(base['id'], metric, mode, group, requirement, sub['requirement_ids'],
                             frozen_assertion_id=a['assertion_id'], **extra))
    return rows, excluded


def _checked(path, game_id) -> dict:
    rubric = read_json(path)
    if rubric.get('status') != 'frozen':
        raise ValueError(f'{path}: only frozen rubrics are evaluated')
    if rubric.get('game_id') != game_id:
        raise ValueError(f'{path}: game_id mismatch')
    return rubric


def _load_whitebox_rubric(game_id: str) -> dict | None:
    """Load merged whitebox rubric from test_data/rubric/<GameID>/whitebox/rubric.json."""
    p = RUBRIC_ROOT / game_id / 'whitebox' / 'rubric.json'
    if p.exists():
        return read_json(p)
    return None


def contract_path(game_id: str):
    """The single frozen scoring contract under eval/rubric_design/contract_history."""
    frozen = [p for p in sorted((CONTRACT_HISTORY / game_id).glob('*/rubric.json'))
              if read_json(p).get('status') == 'frozen']
    if len(frozen) != 1:
        raise ValueError(f'{game_id}: expected exactly one frozen contract, found {len(frozen)}')
    return frozen[0]


def build(game_id: str) -> dict:
    """Return the frozen criteria set for one case (all eight metrics)."""
    # Try new merged rubric first (test_data/rubric/<GameID>/whitebox/rubric.json)
    wb = _load_whitebox_rubric(game_id)
    if wb:
        tiered = wb.get('mechanic', {})
        core12 = wb.get('asset_slot', {})
        frozen_rubric = wb.get('gameness', {})
        # Build rows directly from merged rubric sections
        tiered_rubric = {'assertions': tiered.get('assertions', []), 'status': 'frozen', 'game_id': game_id}
        core12_rubric = {'assertions': core12.get('assertions', []), 'status': 'frozen', 'game_id': game_id}
        frozen = {'assertions': frozen_rubric.get('assertions', []), 'status': 'frozen', 'game_id': game_id}
    else:
        # Fall back to legacy paths
        core12_path = EVAL_DATA / game_id / RUBRIC
        tiered_path = EVAL_DATA / game_id / TIERED
        if not core12_path.exists():
            core12_path = SAMPLES / game_id / RUBRIC
        if not tiered_path.exists():
            tiered_path = SAMPLES / game_id / TIERED
        tiered_rubric = _checked(tiered_path, game_id)
        core12_rubric = _checked(core12_path, game_id)
        frozen = _checked(contract_path(game_id), game_id)

    visual, excluded = _visual(frozen)
    rows = ([_row(*g) for g in GENERIC] + _mechanic(tiered_rubric) + _assets(core12_rubric) + visual)
    ids = [r['id'] for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError(f'{game_id}: duplicate criterion ids')
    metrics = {r['metric'] for r in rows}
    missing = {STORY, MECHANIC, ASSET, INPUT, QUALITY, GAMENESS, PLAYABLE, CODE} - metrics
    if missing - {INPUT}:      # some cases have no reference images -> no input-consistency rows
        raise ValueError(f'{game_id}: no criteria for metrics {sorted(missing)}')
    if {r['group'] for r in rows if r['metric'] == GAMENESS} != {'layout', 'guidance', 'feedback'}:
        raise ValueError(f'{game_id}: Gameness must have layout, guidance and feedback groups')
    return {'version': VERSION, 'game_id': game_id, 'engine': core12_rubric.get('engine'),
            'criteria': rows, 'excluded': excluded}
