"""Gameness: whitebox-gameness10-50-100.v4 / outcome_frame_v1.

All original layout / guidance / feedback checks of the frozen contract,
highest tier only per check:
  10  author source proves the feedback/UI/guidance is wired to gameplay
  50  triggered and observed working: correct target and core information
  100 a real frame clearly communicates the intended result to the player
Score = mean of the three group means (each 100 * mean credits).
"""
from collections import defaultdict

from ..core.llm import B
from ._formats import tiered_credit, tiered_schema

KEY = 'gameness'
NAME = 'Gameness'
FORMAT = 'tiered'
GROUPS = ('layout', 'guidance', 'feedback')
CLEAR = 'clear_intended_result'
BASIC_FLAGS = ('correct_target', 'functional_effect_proven', 'no_basic_bug',
               'correct_core_information', 'processing_proven')
RESULT_FLAGS = ('correct_target', 'no_basic_bug', 'correct_core_information',
                'recognizable_and_usable', 'intended_communication_proven')


def item_schema():
    return tiered_schema(basic_extra={'correct_core_information': B, 'processing_proven': B},
                         result_extra={'correct_core_information': B, 'recognizable_and_usable': B,
                                       'intended_communication_proven': B},
                         clear_label=CLEAR)


def credit(row, verdict):
    basic = verdict['basic_function']
    flags = BASIC_FLAGS if basic['trigger_mode'] == 'rejection' else BASIC_FLAGS[:-1]
    return tiered_credit(verdict, basic_flags=flags, result_flags=RESULT_FLAGS, clear_label=CLEAR)


def aggregate(rows, credits):
    groups = defaultdict(list)
    for r in rows:
        groups[r['group']].append(credits[r['id']])
    if set(groups) != set(GROUPS):
        raise ValueError('Gameness needs layout, guidance and feedback groups')
    return sum(100.0 * sum(v) / len(v) for v in groups.values()) / len(GROUPS)


# --- frozen per-case standard (source-only, before any runtime judge) -------
STANDARD_FIELDS = ('visible_goal', 'result_frame_description', 'correct_target_and_information',
                   'necessary_context', 'representative_basic_function')

STANDARD_PROMPT = '''Freeze the source-only Gameness v4 outcome_frame_v1 standard for ALL frozen Gameness CHECKS of this
case, using original requirements and the original author sources of ALL listed deliveries, before any runtime
judge. No runtime evidence, old scores or verdicts are supplied. Preserve criterion ids and the original
layout/guidance/feedback groups and meanings; do not turn UI/guidance/feedback checks into mechanic defeat/win
checks. Same criterion/goal across models, irrespective of implementation completeness.
Three non-additive levels: 10% real implementation wired to gameplay; 50% actually triggered, basic
feedback/UI/guidance works with correct object/core information and no known basic bug, intended result not
sufficiently established; 100% a delivered real native result frame and MINIMUM necessary context show the intended
communication works, broadly correct and recognizable so the player understands the result or next action. Broad
semantic correctness, NOT pixel similarity or full original specification. A clear single frame suffices; more
context only to resolve real ambiguity/transient effect/causality. Layout or on-screen instructions may be
automatically triggered by entering the genuine screen.
Exact timing/latency/sample count/duration/cooldown; exact coordinates/dimensions/distance/velocity; exact
numerical values; animation curves/flashing and all branches/boundaries are diagnostics ONLY at BOTH 50 and 100.
Core information must still be correct and usable: wrong object, reversed victory/defeat, key text obscured beyond
understanding or unusable controls are basic bugs. Uncovered is unknown, not a bug. Correct refusal needs the
operation handled and refused, not an unchanged screen alone. A decorative animation or success label cannot stand
in for its actual effect. Do not inherit Mechanic results. Copy original_requirement_diagnostic_only exactly from
CHECKS.requirement for traceability, not as gates. Return the exact schema, no score.'''

JUDGE_RULES = '''Gameness(tiered)：逐项取最高档：10%作者源码有效接入玩法；50%实际触发且基本功能正常，正确对象/核心信息、无已知基本bug，但目标结果尚未充分证明；100%真实原生画面及最少上下文清楚显示冻结标准中预定的反馈/界面/引导大致正确，信息和对象正确可辨认，玩家能理解结果或下一步。不追求像素相似、完整细规格、精确时间/空间/数值、持续时长、动画曲线、稳定性、全部边界/分支。清楚单帧足够；有歧义才补必要上下文。进入界面显示UI/说明可算自动触发。动画/成功字不能代替对应真实效果；错误对象/错误信息/关键遮挡不可成功。未覆盖不是bug。正确拒绝须实际操作被处理。失败/死亡不抹去已实现反馈。不继承机制列结论。
source_existence EXISTS须引用实际实现SRC行，名称/注释/占位不算；basic_function NORMAL须真实运行证据；result_outcome ACHIEVED须真实FRAME和全部核心正确标志。声音/触觉未采不评价，只评可视投影。trigger_mode必须是冻结标准允许的触发方式。'''
