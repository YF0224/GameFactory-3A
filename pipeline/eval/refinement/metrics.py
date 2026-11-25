"""Stage3 refine metrics: four dimensions, all on the 10 / 50 / 100 outcome frame.

Per check, highest supported tier (not cumulative):
  10  author source proves the refine was implemented and wired in
  50  observed working in the running game on the correct object, no known basic bug
  100 a real frame clearly shows the intended refined result
r(v) in {0, 0.1, 0.5, 1}: Pass = 1, Partial = 0.1 / 0.5, Fail = 0. A check with no
valid judgment (tool failure, self-contradictory verdict) is Unknown.

Dimensions: mechanic (Debugging), gamefeel + vfx (Game-feel Improvement),
import (Asset Import), texture (Texturing).

Per dimension c (paper eq.):  S_c = 100 * mean r over known checks,
Cov_c = known / all checks. A dimension is published once every check has been
judged (Unknown allowed, reported via Cov_c). No overall score.
"""
from __future__ import annotations

from types import SimpleNamespace

from ..whitebox.llm import B
from ..whitebox.metrics import gameness as _gameness
from ..whitebox.metrics import mechanic as _mechanic
from ..whitebox.metrics._formats import SOURCE_SUFFIXES, tiered_credit, tiered_schema

VERSION = 'stage3-refine-dimensions.v2'   # v2: import/texture judged on in-engine VIEW renders
ORDER = ('mechanic', 'gamefeel', 'vfx', 'import', 'texture')
IMPORT_POLICY = 'asset-import-10-50-100.20261124'

_COMMON_RULES = '''Refine检查(tiered)：判断改进后的游戏是否实现了该refine任务的目标。逐项最高档：10%作者源码证明该改动已实现且接入玩法（名称/注释/未调用代码不算）；50%在真实运行中触发且基本功能正常、作用于正确对象、无已知基本bug，但目标结果画面未充分证明；100%真实FRAME清楚显示冻结标准中的目标结果。精确时间/数值/曲线及全部边界分支只作诊断，不作门槛。未覆盖不等于bug；正确拒绝须证明操作被处理。trigger_mode必须是冻结标准允许的方式。
basic_function.triggered_observed：本次录制的真实FRAME或游戏EVENT/STATE/LOG是否显示该功能确实被触发执行（例如游戏自己的日志/事件记录了对应机制的执行、画面出现对应变化），即使目标结果画面看不到也可为true；只是按了键、或功能根本未到达时为false，并引用支持它的FRAME/EVENT/LOG。游戏日志显示机制已执行且无错误/异常即足以证明触发。二值判定：result_outcome=ACHIEVED 表示冻结目标结果已被证明——可用真实结果FRAME，或游戏自身日志/状态行证明后置条件（例如 revival_wave_complete plants_greened=54），引用EVENT/LOG/STATE；画面或日志显示结果错误、报错或崩溃则判BUG/CONTRADICTED并给出反例（记0）；未触发或证据不足保持UNOBSERVED/NOT_PROVEN（不计分）。
EVENT中的“GAME CRASH”是交付游戏自身在该时刻崩溃（引擎崩溃报告，含游戏代码栈）；若崩溃发生在某检查的动作或其结果过程中且栈与该功能相关，可作为该检查的基本bug反例，否则只说明之后的检查未能观察。
AUDIO通道记录游戏声源的开始/停止（对象、clip、音量、静音、场景中AudioListener数量、audible_to_player）及捕获输出的实测响度；active_listeners=0表示Unity不输出任何声音，玩家听不到。
EVENT只表示游戏记录了该事件，不代表玩家已做出选择或某步已锁定；仅凭事件先后推断“违反前置条件”前，须用源码确认该状态确实已锁定。'''

_STANDARD_COMMON = '''Freeze the source-only outcome_frame_v1 standard for every CHECK of this refine dimension of this case,
before any runtime judge, from the refine task text, the case requirement and the author sources of ALL listed
deliveries (one per refining model). No recordings, verdicts or scores are supplied. The same goal applies to
every model. 10% implemented and wired; 50% observed working on the correct object with no known basic bug;
100% a real result frame clearly shows the intended refined outcome. Exact timings, numbers, curves, coordinates
and exhaustive branches are diagnostics only at BOTH 50 and 100 — do not reintroduce them. A single clear frame can
suffice. Copy original_requirement_diagnostic_only byte-for-byte from CHECKS.requirement. Return only the schema.'''


def _import_credit(row, verdict, *, result_flags, clear):
    """Asset import tiers: implementation, confirmed replacement, achieved gameplay result.

    Reference validation happens in judge.enforce. Keep a proven replacement even when
    the visible/audible result fails; result bugs disqualify 100, not the binding tier.
    """
    src, basic, result = (verdict[k] for k in ('source_existence', 'basic_function', 'result_outcome'))
    source = src['status'] == 'EXISTS' and any(
        e['id'].startswith('SRC:') and e['id'].lower().endswith(SOURCE_SUFFIXES)
        and e['line_start'] >= 1 for e in src['evidence'])
    binding = (basic['status'] == 'NORMAL' and basic.get('replacement_proven') is True
               and basic['correct_target'] and basic['functional_effect_proven']
               and basic['no_basic_bug']
               and any(e['id'].startswith(('SRC:', 'FRAME:', 'VIEW:', 'MOTION:', 'ASSET_EVENT:',
                                           'LOG:', 'STATE:', 'EVENT:')) for e in basic['evidence']))
    ids = {e['id'] for e in result['evidence']}
    runtime = any(i.startswith(('FRAME:', 'VIEW:', 'MOTION:', 'ASSET_EVENT:', 'EVENT:',
                               'LOG:', 'STATE:', 'AUDIO:')) for i in ids)
    kind = row.get('asset_kind')
    visual = bool(ids & {result['result_frame_id']}) and result['result_frame_id'].startswith(
        ('FRAME:', 'VIEW:', 'MOTION:')) and result['frame_assessment'] == clear
    if kind == 'audio':
        # Actual output plus asset identity/timing are judged from the captured audio and trace;
        # a screenshot cannot prove sound, and is not required for the highest tier.
        result_proof = runtime and any(i.startswith(('ASSET_EVENT:', 'AUDIO:', 'EVENT:'))
                                       or (i.startswith('LOG:T') and i.endswith(':asset_events')) for i in ids)
    elif kind == 'motion':
        poses = {i.split(':')[1] for i in ids if i.startswith(('FRAME:T', 'MOTION:T'))}
        events = {i.split(':')[1] for i in ids if i.startswith('ASSET_EVENT:T')
                  or (i.startswith('LOG:T') and i.endswith(':asset_events'))}
        result_proof = visual and bool(poses & events)
    elif kind == 'cg_video':
        result_proof = visual and any(i.startswith('ASSET_EVENT:')
                                     or (i.startswith('LOG:T') and i.endswith(':asset_events')) for i in ids)
    else:
        result_proof = visual
    if (binding and result['status'] == 'ACHIEVED' and result_proof
            and all(result[f] for f in result_flags)
            and (result['processing_proven'] or basic['trigger_mode'] != 'rejection')):
        return 1.0
    if binding:
        return 0.5
    return 0.1 if source else 0.0


def _metric(key, name, base, schema_kwargs, flags, clear, extra_rules, extra_standard):
    def credit(row, verdict):
        basic_flags, result_flags = flags
        if verdict['basic_function']['trigger_mode'] != 'rejection':
            basic_flags = tuple(f for f in basic_flags if f != 'processing_proven')
        c = tiered_credit(verdict, basic_flags=basic_flags, result_flags=result_flags, clear_label=clear)
        if key == 'import':
            return _import_credit(row, verdict, result_flags=result_flags, clear=clear)
        # 50% floor (user decision 2026-11-10): the recording proves the feature was triggered (judge flag
        # backed by a runtime FRAME / EVENT / STATE / LOG citation; game log alone suffices, 2026-11-11) and no bug was observed -> at least 50%.
        b, r = verdict['basic_function'], verdict['result_outcome']
        runtime = {e['id'].split(':')[0] for e in b.get('evidence', []) + r.get('evidence', [])} & {'FRAME', 'EVENT', 'STATE', 'LOG', 'AUDIO', 'ASSET_EVENT'}
        if row.get('metric') in ('import', 'texture') and row.get('asset_id'):
            # the imported asset photographed inside the running game (VIEW) is runtime evidence for its own row
            runtime |= {e['id'].split(':')[0] for e in b.get('evidence', []) + r.get('evidence', [])} & {'VIEW', 'MOTION'}
        # Binary verification (user decision 2026-11-11): PASS 1.0 when the frozen target outcome is proven by a
        # result frame / in-game asset view or by the game's own log / state postcondition; FAIL 0.0 when a wrong
        # result, error or crash was observed; otherwise None = UNVERIFIED (excluded from S, counted in coverage).
        # (c above still validates the verdict: BUG / CONTRADICTED need an observed counterexample.)
        if b['status'] == 'BUG' or r['status'] == 'CONTRADICTED':
            return 0.0
        rcites = {e['id'].split(':')[0] for e in r.get('evidence', [])}
        if r['status'] == 'ACHIEVED' and rcites & {'FRAME', 'VIEW', 'MOTION', 'EVENT', 'LOG', 'STATE', 'AUDIO', 'ASSET_EVENT'}:
            return 1.0
        # user decision 2026-11-11: after normal play AND every Direct Trigger round, a check that was really
        # tried (input sent / direct call ran) but whose expected behaviour never appeared in any event frame or
        # game log is FAIL (set by pipeline.score as _not_observed_fail); never-tried / tool faults stay None
        if verdict.get('_direct_clean_run') is True:   # Direct Trigger ran with a clean game log, no result frame
            return 0.5
        if verdict.get('_not_observed_fail') is True:
            return 0.0
        return None

    def aggregate(rows, credits):
        known = [credits[r['id']] for r in rows if credits.get(r['id']) is not None]
        return 100.0 * sum(known) / len(known) if known else None

    return SimpleNamespace(
        KEY=key, NAME=name, FORMAT='tiered', CLEAR=clear, RESULT_FROM_LOG=True,
        item_schema=lambda: tiered_schema(clear_label=clear, **schema_kwargs),
        credit=credit, aggregate=aggregate,
        STANDARD_FIELDS=base.STANDARD_FIELDS,
        STANDARD_PROMPT=_STANDARD_COMMON + '\n' + extra_standard,
        JUDGE_RULES=_COMMON_RULES + extra_rules)


_TRIGGER = {'triggered_observed': B}     # recording shows the feature was triggered (result may be unseen)
_MECH_SCHEMA = {'basic_extra': dict(_TRIGGER), 'result_extra': {'genuine_gameplay_result': B, 'causal_context_sufficient': B}}
_MECH_FLAGS = (_mechanic.BASIC_FLAGS, _mechanic.RESULT_FLAGS)
_GF_SCHEMA = {'basic_extra': {'correct_core_information': B, 'processing_proven': B, **_TRIGGER},
              'result_extra': {'correct_core_information': B, 'recognizable_and_usable': B,
                               'intended_communication_proven': B}}
_GF_FLAGS = (_gameness.BASIC_FLAGS, _gameness.RESULT_FLAGS)

METRICS = {
    'mechanic': _metric('mechanic', 'Mechanic', _mechanic, _MECH_SCHEMA, _MECH_FLAGS, _mechanic.CLEAR,
                        '\n[mechanic] 修复后的机制结果必须真实发生在正确对象上；动画或文字不能代替真实效果。',
                        'Dimension: mechanic repair. Define the principal functional outcome of each repair goal.'),
    'gamefeel': _metric('gamefeel', 'Gamefeel', _gameness, _GF_SCHEMA, _GF_FLAGS, _gameness.CLEAR,
                        '\n[gamefeel] 反馈/UI/镜头/引导须在对应事件或输入时可见地传达预期信息；装饰性动画不算对应效果。',
                        'Dimension: gamefeel (input/event feedback, UI state, camera, guidance).'),
    'vfx': _metric('vfx', 'VFX', _gameness, _GF_SCHEMA, _GF_FLAGS, _gameness.CLEAR,
                   '\n[vfx] 视觉效果须在正确挂点/对象上、按触发条件出现并结束；不要求原生粒子组件，白模占位效果可算；不得改变机制结果。',
                   'Dimension: visual effects; placeholder effects are acceptable, native particles are not required.'),
    'import': _metric('import', 'Import', _mechanic,
                      {**_MECH_SCHEMA, 'basic_extra': {**_TRIGGER, 'replacement_proven': B}},
                      _MECH_FLAGS, _mechanic.CLEAR,
                      '\n[import 2026-11-24] 五种资产（3d_object、scene/3d_scene、motion、audio、cg_video）统一最高支持档10/50/100，不再二值计分。'
                      '本段覆盖上文通用二值规则及旧冻结标准中冲突的分档、外观门槛和audio最高50限制；不覆盖资产身份、目标接口、需求触发时机。'
                      '10：作者有实际实现代码，source_existence=EXISTS并引用带行号SRC；只有注释、路径名或资产文件存在不能证明接口已替换。'
                      '50：目标接口/槽位确实绑定或替换成指定资产。basic_function专门判断替换接入：身份和正确目标明确、可达的真实赋值或序列化绑定有证据，'
                      '则replacement_proven=true、status=NORMAL、correct_target/functional_effect_proven/no_basic_bug=true；不要求已达到100档的表现。'
                      '可用带行号的作者代码与绑定资源、导入来源，或运行时对象/资产事件来证实；仅有加载函数、相似名称、路径字符串或文件存在不算实际替换。'
                      'triggered_observed只说明本次是否触发，未触发不抹去已证实的替换。身份/绑定不足则replacement_proven=false且UNOBSERVED。'
                      '100：在已证实替换基础上，真实游玩达到下列对应资产结果，result_outcome=ACHIEVED及结果标志为true；motion/CG须引用同take事件和真实结果帧。'
                      '表现错误、声音被禁用、时机错误、明显形变等写result_outcome的CONTRADICTED/NOT_PROVEN和诊断，不抹去独立证实的50档替换；绑定本身错误才basic_function=BUG。'
                      '工具故障为HARNESS_ERROR，缺失证据不伪造产品bug；仅有源码实现但替换未证实保留10。'
                      '以下按资产类型判断100档；旧冻结标准仅继续约束资产身份、接入对象和触发时机。'
                      '资产须真实导入引擎并接入对应目标/槽位。3d_object：10%源码证明该资产被加载并挂到目标对象；'
                      '50%源码接入正确目标且VIEW显示资产在引擎内完整导入（几何完整、有材质），或游戏FRAME显示它出现在正确对象上；'
                      '100%源码/FRAME证明接入正确目标，且VIEW四视角的外形、比例与主色与REF参考图大体一致。'
                      'UE暂无VIEW四视图时以真实游戏FRAME对照REF，报告视角覆盖不足；不把缺少VIEW当成产品bug。'
                      '外观只按REF图像判断；描述中的风格或细节词（如low-poly、helmet lamp）不是额外扣分条件。'
                      '几何缺失/破碎、朝向或比例明显错误为基本bug。'
                      'scene/3d_scene：游戏内拍摄的VIEW（in-game recorder shot）或FRAME显示启动后的游戏场景就是该场景资产的一部分即可判ACHIEVED；不要求整体场景外观与REF一致。'
                      'motion：ASSET_EVENT 显示该动作在对应输入/事件时被触发播放（start，未立即interrupted），'
                      '且同一 take 的 MOTION 原生游玩连续帧（或 FRAME）显示动作在实际游戏角色上自然播放；未见明显形变就记作无明显形变，只有实际观察到肢体明显拉伸撕裂、T-pose、部件脱离等异常才判定有形变。不能用单独模型展示、强制采样姿势代替真实游玩表现；不因角色较小、画面偏暗或局部遮挡而单独把无明显形变判为未验证。'
                      'cg_video、audio：ASSET_EVENT 显示播放的就是这个资产，且触发时机与需求声明的时机相符'
                      '（audio 可参考 output_rms_dbfs_next_1500ms 确认有实际声音输出）。audio 没有最高50%的限制；身份、时机和实际输出已证明且无已知bug时可判ACHIEVED，不要求视觉帧证明声音。'
                      'cg_video 画面只比较真实播放首帧与自然结束前尾帧；输入及游戏日志/源码确认用户主动跳过时只比较首帧。stop_early 本身不能证明跳过，异常中断或端点画面缺失不能据此确认结果。'
                      '若导入后改名导致缺少按资产ID绑定的ASSET_EVENT，可用完整LOG:T<k>:asset_events中的原始事件，但必须引用作者源码或导入来源建立该路径与目标资产的明确对应；不得凭动作名相似推断。motion仍须同一take的MOTION或FRAME证明真实游玩表现。事件缺失或身份对应不足时为未验证，不当作产品bug。',
                      'Dimension: asset import and binding. For all five asset kinds: 10 is implementation code; '
                      '50 is the confirmed replacement/binding of the intended live slot to the specified asset, '
                      'independent of whether the final gameplay result succeeds; 100 is the type-specific achieved gameplay result. '
                      'File presence or a load/path string alone is not binding proof. basic_function describes replacement, '
                      'result_outcome describes final gameplay behaviour. 3d_object is judged from source wiring plus the in-engine '
                      'four-view render VIEW:<asset> against REF; scene / 3d_scene from the in-game shot showing part of the imported scene, without a whole-scene REF match; audio has no 50% cap; motion / cg_video / audio from the '
                      'recorder\'s ASSET_EVENT for that asset (triggered, at the declared moment) plus, for motion, the same take\'s native gameplay MOTION frames (or FRAME) showing natural playback. Record no obvious deformation when none is observed; require an actually observed obvious defect to judge deformation, and do not mark this criterion unverified solely for small characters, dim lighting or partial occlusion. Never use a staged model preview. For 3D appearance, use the reference image '
                      'as the sole visual target; description words such as low-poly or helmet lamp add no visual requirements. '
                      'Keep the asset identity and intended source binding, but do not turn descriptive prose into appearance gates.'),
    'texture': _metric('texture', 'Texture', _gameness, _GF_SCHEMA, _GF_FLAGS, _gameness.CLEAR,
                       '\n[texture] 只评导入3D资产的贴图/材质：基准是原始资产文件在同一引擎、灯光与视角下的渲染 SRCVIEW，'
                       '比较导入引擎后的渲染 VIEW。10%源码或资源证明资产被赋予材质/贴图；50% VIEW 中贴图材质正常显示但与'
                       ' SRCVIEW 的一致性不能充分判断；100% VIEW 清楚保留 SRCVIEW 的主色分区、表面图案与质感。'
                       '原始资产有贴图而导入后缺失/缺省灰白粉材质、贴错贴图、原始资产没有的UV错乱为基本bug。'
                       'REF 只作背景；没有 SRCVIEW 时才以 REF 为参照。不评接入位置或动作。',
                       'Dimension: texturing of imported 3D objects / scenes: the in-engine render VIEW:<asset> is '
                       'compared with the render of the original asset file SRCVIEW:<asset> (same engine, light rig '
                       'and angles); REF is context. Lost / default / magenta materials, wrong texture or UV breakage '
                       'not present in the original are basic bugs.'),
}


def _game(rows):
    from .criteria import INPUTS
    for r in rows:
        for g in (p.name for p in INPUTS.iterdir() if p.is_dir()):
            if r['id'].startswith(g) or r['id'].startswith(g[:4] + '.'):
                return g
    return ''


def score(rows: list[dict], verdicts: dict) -> dict:
    """Per-dimension S_c and Cov_c; published once every check is judged. No total."""
    dims = {}
    for key in ORDER:
        mine = [r for r in rows if r['metric'] == key]
        if not mine:
            continue
        m, credits, unknown = METRICS[key], {}, []
        for r in mine:
            v = verdicts.get(r['id'])
            if v is None:
                continue
            try:
                credits[r['id']] = m.credit(r, v)
            except ValueError as exc:            # HARNESS_ERROR / contradictory verdict -> Unknown
                credits[r['id']] = None
                unknown.append({'id': r['id'], 'reason': str(exc)})
        judged = len(credits)
        known = sum(c is not None for c in credits.values())
        complete = judged == len(mine)
        s = m.aggregate(mine, credits)
        dims[key] = {'name': m.NAME, 'checks': len(mine), 'judged': judged, 'known': known,
                     'S': round(s, 2) if complete and s is not None else None,
                     'Cov': round(known / len(mine), 4), 'published': complete,
                     'unknown': unknown, 'credits': credits}
    if 'import' in dims:
        dims['import']['scoring_policy'] = IMPORT_POLICY
    complete = all(d['published'] for d in dims.values())
    return {'version': VERSION, 'complete': complete, 'total': None, 'dimensions': dims,
            'missing_verdicts': [r['id'] for r in rows if r['id'] not in verdicts]}
