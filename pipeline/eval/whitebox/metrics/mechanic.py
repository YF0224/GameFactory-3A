"""机制完整性: whitebox-mechanic10-50-100.v3 / outcome_frame_v1.

Per atom (one frozen tiered-core C2 subcheck), highest tier only:
  10  author source proves the mechanism exists (cited source line)
  50  observed working on the correct target, no known basic bug
  100 a real result frame clearly shows the intended outcome happened
Endpoint score = 100 * mean(atom credits); column = mean of endpoints.
Exact timing / distances / numbers are diagnostics only, never tier gates.
"""
from collections import defaultdict

from ..core.llm import B
from ._formats import tiered_credit, tiered_schema

KEY = 'mechanic'
NAME = '机制完整性'
FORMAT = 'tiered'
CLEAR = 'clear_target_result'
BASIC_FLAGS = ('correct_target', 'functional_effect_proven', 'no_basic_bug')
RESULT_FLAGS = ('correct_target', 'genuine_gameplay_result', 'causal_context_sufficient', 'no_basic_bug')


def item_schema():
    return tiered_schema(basic_extra={},
                         result_extra={'genuine_gameplay_result': B, 'causal_context_sufficient': B},
                         clear_label=CLEAR)


def credit(row, verdict):
    return tiered_credit(verdict, basic_flags=BASIC_FLAGS, result_flags=RESULT_FLAGS, clear_label=CLEAR)


def aggregate(rows, credits):
    endpoints = defaultdict(list)
    for r in rows:
        endpoints[r['group']].append(credits[r['id']])
    return sum(100.0 * sum(v) / len(v) for v in endpoints.values()) / len(endpoints)


# --- frozen per-case standard (source-only, before any runtime judge) -------
STANDARD_FIELDS = ('visible_goal', 'result_frame_description', 'correct_target', 'necessary_context',
                   'representative_basic_function')

STANDARD_PROMPT = '''Freeze the source-only outcome_frame_v1 standard for every frozen mechanic CHECK of this case.
No runtime images, old verdicts or scores are supplied. Use the frozen mechanism intent and the original
author sources of ALL listed deliveries; never infer goals from a successful recording or implementation
convenience. The same functional goal applies to every model, even if one implementation is incomplete.
10% implementation exists. 50% representative basic function actually works correctly, goal not sufficiently
proven. 100% a real final mechanism-result frame clearly proves its intended visible goal occurred, with correct
target and genuine gameplay effect and no known basic-function bug. This is NOT full original specification compliance.
Exclude exact milliseconds/latency/simultaneity/durations/cooldowns; exact distance/radius/angle/coordinates/speed;
exact damage/multiplier/formula; exhaustive modes/branches/boundaries/parameter combinations. These are diagnostic
only at BOTH 50% and 100%; do not reintroduce them via goal, frame, context or bug definitions. Do not require two
observations, internal fields, per-projectile IDs, guard logs, a positive control, every rejection or full-game
success. A single clear frame can suffice; require additional real context only to resolve actual
target/effect/causality ambiguity. A refusal still needs proof the operation occurred and was handled.
Define visible_goal, result_frame_description, correct_target, necessary_context, representative_basic_function,
basic_function_bugs and permitted_trigger_modes for every CHECK id. Copy original_requirement_diagnostic_only
byte-for-byte from CHECKS.requirement for traceability only. Preserve semantic intent: if the goal is damage, do not
add a kill; if the goal is defeat, damage alone is 50. For compound specs define the principal functional outcome.
Wrong target, enemy healing on attack, fabricated reload resources are bugs; correct effect with numeric discrepancy
is not. Missing footage is unknown, not a product bug. Return only the exact schema.'''

JUDGE_RULES = '''机制完整性(tiered)：逐机制最高档：10%有效实现源码；50%基本功能实测正常、正确对象、无基本bug，但目标结果未充分证明；100%对应机制最终真实画面明确证明冻结标准中的目标结果发生，正确对象、真实玩法效果、必要因果上下文成立，无已知基本bug。100%不是原始完整规格PASS。
忽略精确时间/响应窗口/同帧性/时长/冷却、距离/半径/角度/坐标/速度、伤害/倍率/公式、全部模式/边界/替代分支；只能诊断，不得作为50或100门槛。不要求两个时间点、逐弹ID、守卫日志、特定state、完整正向对照、所有拒绝分支或通关。
优先用对应机制结果的真实FRAME；机制完成后被重置/全局失败不抹去已发生结果。画面清楚时单帧足够。源码/ACTION/STATE/EVENT/日志只作身份/前置/因果上下文，不能单独替代100%的结果画面；单帧含糊应NOT_PROVEN。
目标确实击倒可100；正确目标扣血但击倒未证可50；目标只需伤害则伤害可100。挥刀动画不等于伤害，倒地装饰不等于击倒，成功字样不证明所有机制。错对象、攻击回血、换弹造资源等基本bug不得50/100，保留源码10。普通数值偏差不是基本bug。整体失败不连坐其他机制。
正确拒绝须证明操作发生且被正确处理；仅状态不变不足。processing_basis为visual_effect/explicit_feedback/event_processing/contextual_sequence才可NORMAL。ACHIEVED要求clear_target_result真实FRAME及所有标志true；rejection必须processing_proven。trigger_mode必须是冻结标准允许的触发方式。'''
