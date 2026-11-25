"""Source-authored Gameness targets with the same tier count as Mechanic.

Companion revisions live with canonical rubrics. Mechanic's frozen files and
all previous Gameness contracts remain byte-for-byte unchanged. Selection uses
requirements only; no implementation, runtime evidence or scores are inputs.
"""
from __future__ import annotations
import copy
import json
from pathlib import Path
from . import batch_rubric, gameness_v3 as policy, tiered_core
from .protocol import sha
from ..contract_identity import fingerprint

VERSION = 'gameness-tiered-core-v1'
RELATIVE_PATH = 'rubric_whitebox_core/gameness_rubric.json'
# Group means retain equal weight. Counts need not be equal between groups.
QUOTAS = {'S': {'layout':3, 'guidance':2, 'feedback':3},
          'M': {'layout':4, 'guidance':3, 'feedback':5},
          'L-Regular': {'layout':5, 'guidance':5, 'feedback':10},
          'L-Stress': {'layout':6, 'guidance':7, 'feedback':12}}
SCOPE_RULE = ('每条只评价其代表性沟通目标；不要求遍历全部对象、界面、事件或分支。'
              '源码只支持10%；实际触发且基本功能正常支持50%；真实原生结果帧清楚、'
              '核心信息和对象大致正确支持100%。精确时间、空间、数值及全部细规格仅诊断。')


def candidates(contract):
    rows, _ = batch_rubric.expanded_visual(contract)
    return [s for s in rows if s['column'] == policy.COLUMN]


def priority(spec):
    """Prefer broad communication goals, then distinct authored visual events."""
    ident, text = spec['id'], spec['requirement']
    preferred = {'game.layout.hierarchy':990, 'game.layout.readable':980,
                 'game.guidance.controls':1000}
    if ident in preferred:
        return preferred[ident]
    if spec['group'] == 'layout':
        return 1000 if 'I06' in spec.get('requirement_ids', []) else 800 if 'F10' in spec.get('requirement_ids', []) else 500
    if spec['group'] == 'guidance':
        return 990 if ('下一步' in text or '当前目标' in text) else 800 if ('代价' in text or '收益' in text) else 500
    if '成功、失败或拒绝' in text:
        return 1000
    if '目标进度、阶段变化' in text:
        return 990
    if '事件【' in text:
        return 900
    return 400


def expectation(spec):
    """Make representative coverage explicit rather than hiding a conjunction."""
    ident, text, group = spec['id'], spec['requirement'], spec['group']
    if ident == 'game.layout.hierarchy':
        goal = '当前真实玩法界面的主要状态与次要信息层级清楚，玩家能辨认重点。'
    elif ident == 'game.layout.readable':
        goal = '当前真实玩法界面的关键文字和控件可辨认、可使用，不因遮挡或重叠而无法理解。'
    elif ident == 'game.guidance.controls':
        goal = '游戏内清楚传达一项推进当前玩法所必需的核心操作方法。'
    elif group == 'layout' and 'I06' in spec.get('requirement_ids', []):
        goal = '当前真实玩法阶段的核心状态信息可见，玩家能理解对象与状态的含义；无需全阶段同屏。'
    elif group == 'guidance' and ('下一步' in text or '当前目标' in text):
        goal = '玩家在当前真实玩法阶段能理解当前目标或下一步可执行操作。'
    elif group == 'guidance' and ('代价' in text or '收益' in text):
        goal = '一项实际玩法选择具有可理解的代价或收益提示，提示对象与选择相符。'
    elif group == 'feedback' and '成功、失败或拒绝' in text:
        goal = '一项代表性核心操作发生后，玩家能辨认操作成功、失败或被正确拒绝的结果。'
    elif group == 'feedback' and '目标进度、阶段变化' in text:
        goal = '一次真实进度更新、阶段切换或终局结果被清楚传达，信息与实际状态相符。'
    elif '事件【' in text and '】' in text:
        event = text.split('事件【', 1)[1].split('】', 1)[0]
        goal = f'真实发生“{event}”时，反馈让玩家辨认该事件及其对应对象和结果。'
    else:
        goal = '以原始需求所述用途为准，证明当前阶段的一项代表性界面、引导或反馈基本传达其意图。'
    return goal + '\n' + SCOPE_RULE


def build(case_directory):
    case_directory = Path(case_directory).resolve()
    source = case_directory / tiered_core.RUBRIC
    requirement = case_directory / 'general_requirement.txt'
    original = json.loads(source.read_text())
    tier = tiered_core.canonical_tier(requirement.read_text())
    count = sum(a['table_column'] == 'C2' for a in original['assertions'])
    if count != tiered_core.COUNTS[tier] or count != sum(QUOTAS[tier].values()):
        raise ValueError('Canonical Mechanic/tier count mismatch: ' + case_directory.name)
    rows = candidates(original)
    selected = []
    for group, quota in QUOTAS[tier].items():
        choices = sorted((s for s in rows if s['group'] == group), key=lambda s:-priority(s))
        if len(choices) < quota:
            raise ValueError('Not enough distinct source targets: ' + case_directory.name + ':' + group)
        for number, spec in enumerate(choices[:quota], 1):
            selected.append(dict(id=f'gameness.tiered.{group}.{number:02d}', column=policy.COLUMN,
                group=group, mode='visual', requirement=expectation(spec),
                requirement_ids=copy.deepcopy(spec.get('requirement_ids', [])),
                source_criterion=copy.deepcopy(spec)))
    selected_ids = {s['source_criterion']['id'] for s in selected}
    result = dict(version=VERSION, case_id=case_directory.name, tier=tier, target_count=count,
        mechanic_target_count=count, group_quotas=copy.deepcopy(QUOTAS[tier]),
        authorized_change='Gameness only: align count with same-case same-tier Mechanic',
        source_bindings={str(source):sha(source), str(requirement):sha(requirement)},
        source_contract_id=original['contract_id'], criteria=selected,
        unselected_source_criteria=[s for s in rows if s['id'] not in selected_ids],
        unselected_policy='Retained for traceability/diagnostics; no implicit extra scored checks',
        selection_basis='Original requirement/rubric only; no author implementation, runtime or scores',
        aggregation='Equal mean of layout/guidance/feedback group means; unchanged 10/50/100 levels',
        prior_results='Preserved under their original rubric; not relabeled or arithmetically converted')
    result['revision_sha256'] = fingerprint(result)
    return result


def validate(value, case_directory):
    if value != build(case_directory):
        raise ValueError('Gameness tiered rubric differs from source-bound authored selection')
    return value


def load(case_directory):
    path = Path(case_directory).resolve() / RELATIVE_PATH
    return validate(json.loads(path.read_text()), case_directory), {str(path):sha(path)}


def write(case_directory):
    value = build(case_directory)
    path = Path(case_directory) / RELATIVE_PATH
    text_path = path.with_suffix('.txt')
    text = (f"# {value['case_id']} Gameness — {value['tier']} / {value['target_count']} checks\n\n"
            f"Policy: {VERSION}\nRevision: {value['revision_sha256']}\n\n{SCOPE_RULE}\n\n")
    for s in value['criteria']:
        text += f"## {s['id']} [{s['group']}]\n\n{s['requirement']}\n\n来源：{s['source_criterion']['id']}\n\n原文（细规格仅诊断）：{s['source_criterion']['requirement']}\n\n"
    text += f"未纳入评分的旧判项：{len(value['unselected_source_criteria'])}；完整原文保存在 JSON 中。\n"
    content = json.dumps(value, ensure_ascii=False, indent=2) + '\n'
    # Never overwrite a different revision or an unrelated session's edits.
    for target, data in ((path, content), (text_path, text)):
        if target.exists():
            if target.read_text() != data:
                raise ValueError('Existing authored Gameness revision differs: ' + str(target))
        else:
            with target.open('x') as handle:
                handle.write(data)
    return value


def apply(protocol, value):
    result = copy.deepcopy(protocol)
    before = [s for s in result['criteria'] if s['column'] != policy.COLUMN]
    result['criteria'] = before + copy.deepcopy(value['criteria'])
    result['gameness_rubric'] = {k:copy.deepcopy(value[k]) for k in
        ('version', 'case_id', 'tier', 'target_count', 'revision_sha256', 'source_bindings')}
    return result


def scoring_protocol(workspace, native_protocol, entry):
    revision = json.loads((Path(workspace)/'gameness_assessment_revision.json').read_text())
    name = revision.get('gameness_rubric_policy')
    from . import gameness_v3_original
    if name is None or name == gameness_v3_original.VERSION:
        return native_protocol, {}
    module = policy_module(name)
    value, bindings = module.load(entry['case_directory'])
    pinned = revision['gameness_rubric_bindings']
    for path, digest in bindings.items():
        if pinned.get(path) != digest:
            raise ValueError('Gameness authored source differs from initialized revision')
    if entry['case_id'] != value['case_id']:
        raise ValueError('Gameness rubric case mismatch')
    return apply(native_protocol, value), dict(value['source_bindings'], **bindings)


def protocol_for_run(root):
    root = Path(root)
    path = root/'gameness_scoring_protocol.json'
    return json.loads((path if path.is_file() else root/'input/pilot_rubric.json').read_text())


def runtime_tasks(protocol, manifest, native_protocol):
    if 'gameness_rubric' not in protocol:
        return None
    native_ids = {s['id'] for s in native_protocol['criteria'] if s['column'] == policy.COLUMN}
    parents = [name for name, subset in manifest['evidence_sets'].items()
               if native_ids.intersection(subset['criterion_ids'])]
    if not parents:
        raise ValueError('No qualified Gameness native evidence set')
    # The existing native delivery sends ALL declared real windows and ALL
    # author source files per request; no invented trigger coverage is inferred.
    specs = policy.criteria(protocol)
    return [(f'gameness_v3_tiered_{n//5+1:02d}', parents[0], specs[n:n+5])
            for n in range(0, len(specs), 5)]


def policy_module(name):
    """Explicit dispatch; legacy workspaces and default v1 remain unchanged."""
    if name == VERSION:
        import sys
        return sys.modules[__name__]
    from . import gameness_v3_independent
    if name == gameness_v3_independent.VERSION:
        return gameness_v3_independent
    raise ValueError('Unknown Gameness rubric policy')
