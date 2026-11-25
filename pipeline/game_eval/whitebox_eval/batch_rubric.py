"""Model-independent expanded visual pilot; never edits frozen benchmark contracts."""
from __future__ import annotations

from .protocol import COLUMNS, criteria
from .profiles import CASES, case_criteria

VERSION = 'whitebox-eightcol-batch-expanded.v3'


def mechanic_specs(frozen):
    case = frozen['game_id']
    if case in CASES:
        return [s for s in case_criteria(case) if s['column']==COLUMNS[1]]
    if case.startswith('G001_'):
        return [s for s in criteria() if s['column']==COLUMNS[1]]
    if case.startswith('G007_'):
        defs = [
            ('entry','入口',['S06','S07'],'正常输入从标题进入可操作谱面，画面和真实状态一致。'),
            ('slow','低速模式',['G01','G06'],'正常移动与Shift组合移动实际速度按300/150逻辑像素每秒减半；按住显示判定点及擦弹环，松开恢复速度并隐藏；需实际前后位移、计时、画面。'),
            ('clear','清屏',['G04','G07'],'正常B键消耗1次清屏资源，使实际在场弹幕清除且给予2秒无敌；必须先有弹幕/资源，不能把按键发送当成功。'),
            ('graze','擦弹计分',['G01','G03','G05'],'正常玩法一次真实擦弹满足2<距离<=8逻辑像素，同弹首次擦弹加10分且meter加10、不扣生命、不重复计分；须真实弹身份/位置、玩家位置、分数和生命前后证据。'),
            ('pause','暂停',['G08'],'正常Esc暂停冻结弹幕推进及谱面计时，恢复后继续，无漂移；不能只看菜单存在。'),
            ('ending','结束',['V01','V02','V03'],'正常玩法进入真实胜/负结算并正常重开，生命3、清屏2、graze/meter/得分/时间轴及艇位全量重置；不得注入状态。'),
        ]
        return [{'id':'mechanic.'+i,'column':COLUMNS[1],'mode':'runtime','group':g,
                 'requirement_ids':ids,'requirement':t} for i,g,ids,t in defs]
    # For the M/L cases, retain every frozen mechanism endpoint, without inventing
    # a different game's mechanics. All constituent conditions remain mandatory.
    return [{'id':'endpoint.'+a['assertion_id'], 'column':COLUMNS[1], 'mode':'runtime',
             'group':a['assertion_id'], 'frozen_assertion_id':a['assertion_id'],
             'requirement_ids':a['requirement_ids'],
             'requirement':a['assertion']+'；下列全部条件成立才PASS：\n'+'\n'.join(s['text'] for s in a['binding']['subchecks'])}
            for a in frozen['assertions'] if a['table_column']=='C2']


def expanded_visual(frozen):
    selected, excluded = [], []
    for a in frozen['assertions']:
        col = a['table_column']
        if col not in {'Q','G'}:
            continue
        for sub in a['binding']['subchecks']:
            text, reqs, topic = sub['text'], sub['requirement_ids'], sub.get('topic','')
            row = {'id':'expanded.'+sub['id'], 'frozen_assertion_id':a['assertion_id'],
                   'frozen_subcheck_id':sub['id'], 'frozen_text':text,'requirement_ids':reqs}
            if col=='Q':
                reference = any(r.startswith('A0') for r in reqs) or any(t in text for t in ('冻结参考图','参照空间关系','冻结的主题与风格'))
                target = COLUMNS[3] if reference else COLUMNS[4]
                if 'I07' in reqs:
                    target=COLUMNS[5]
                row.update(column=target,group='feedback' if target==COLUMNS[5] else sub['id'],
                    mode='reference' if reference else 'visual',requirement=text+' 仅评可视部分，声音不视为通过。')
                if reference:
                    row['requirement']+=' 对照真实参考图核对辨识轮廓、相对比例、主色分区与空间地标；允许几何白模，不要求成品美术。'
            elif '要求行 |' in text:
                cells=[s.strip() for s in text.split('要求行 |',1)[1].split('|')]
                if len(cells)<4:
                    raise ValueError('malformed frozen feedback table: '+sub['id'])
                row.update(column=COLUMNS[5],group='feedback',mode='visual',visual_projection=True,
                    requires_temporal_evidence=True,
                    requirement=f'事件【{cells[0]}】实际发生时可视表现为【{cells[1]}】，结束条件【{cells[3]}】。仅评价可视投影，音频未评。未触发事件不能PASS。')
            elif any(t in topic for t in ('前端界面','UI 必','UI必')) or any(r in {'F10','I06'} for r in reqs):
                row.update(column=COLUMNS[5],group='layout',mode='visual',requirement=text)
            elif topic.startswith('交互反馈'):
                group='feedback' if any(t in text for t in ('成功、失败或拒绝反馈','阶段变化与终局','并发单位')) else 'guidance'
                row.update(column=COLUMNS[5],group=group,mode='visual',requirement=text)
            elif any(r in {'F03','F09','I07'} for r in reqs) and '占位声音验收' not in text:
                row.update(column=COLUMNS[5],group='feedback',mode='visual',requirement=text)
            elif not set(reqs) & {'F05','F06','F08','W07'} and '占位声音验收' not in text:
                # Frozen G also contains case-specific radar/flow/UI requirements.
                # Do not silently drop them merely because the assertion order differs.
                group='layout' if any(t in topic for t in ('界面','UI')) else 'feedback'
                row.update(column=COLUMNS[5],group=group,mode='visual',requirement=text)
            else:
                excluded.append({**row,'reason':'纯声音、音画同步或非可视表头，本协议未评；不算PASS。'})
                continue
            if any(t in row['requirement'] for t in ('流动','翻卷','摆动','旋转','呼吸灯','延迟','毫秒','顿帧','慢动作','后坐','屏幕震动','鼠标控制','动态更新','实时更新','冻结，恢复','失焦')):
                row['requires_temporal_evidence']=True
            selected.append(row)
    keep={'quality.complete','quality.readable','quality.defects','game.layout.hierarchy','game.layout.readable','game.guidance.controls'}
    selected.extend(s for s in criteria() if s['id'] in keep)
    return selected, excluded


def make_protocol(frozen):
    if frozen.get('status')!='frozen':
        raise ValueError('batch uses frozen contracts only, not latest draft files')
    common=[s for s in criteria() if s['column'] not in set(COLUMNS[1:2]+COLUMNS[3:6])]
    visuals,excluded=expanded_visual(frozen)
    specs=common+mechanic_specs(frozen)+visuals
    if len({s['id'] for s in specs})!=len(specs):
        raise ValueError('duplicate criterion IDs')
    if {s['column'] for s in specs}!=set(COLUMNS):
        raise ValueError('missing score column')
    if {s['group'] for s in specs if s['column']=='Gameness'}!={'layout','guidance','feedback'}:
        raise ValueError('missing Gameness group')
    from .budgets import budget_for
    # The v3 protocol carries the gameplay budget for the case's own tier and
    # complexity rather than a universal 75 s smoke envelope. prepare() still
    # overlays the versioned recording protocol; this is the frozen baseline.
    gameplay_ms = budget_for(frozen['game_id'], frozen.get('tier', 'S'))['gameplay_ms']
    return {'version':VERSION,'case_id':frozen['game_id'],'criteria':specs,
        'excluded_subchecks':excluded,'aggregation':'eight-columns-equal.v1',
        'mechanic_scope':'S: six preregistered smoke behaviors; M/L: all frozen C2 endpoints, each endpoint conjunctive; not full benchmark scoring',
        'selection':'All frozen Q; G selected by semantic topic/requirement, not assertion position; every feedback-table visual cell. Same case identical across all methods.',
        'sampling':'Up to 48 actual frames: uniformly over full take and each press before/after; deterministic thinning. Native 2x2 sheets; all reference images.',
        'viewport':[960,540],'runtime_budget_ms':gameplay_ms,'max_watchers':32,'max_probes':10,
        'judge_shard_size':20,'max_successful_plan_calls':1,'max_technical_retries':0,
        'unverified_scores_zero':True,'harness_error_invalidates_run':True,
        'full_frozen_score':None,'audio_judged':False,'native_export_tested':False,
        'static_scope':'Story, asset reservation and Code use authored delivery implementation/documents, not requirements or contract declarations alone.'}


V4_VERSION = 'whitebox-eightcol-batch-expanded.v4'


def _atomic_mechanic_specs(frozen):
    """Use frozen, independently bound C2 subchecks as the v4 atomic units."""
    rows = []
    for endpoint in (a for a in frozen['assertions'] if a['table_column'] == 'C2'):
        endpoint_id = endpoint['assertion_id']
        atoms = endpoint['binding']['subchecks']
        if not atoms:
            raise ValueError(f'C2 endpoint has no atomic frozen subchecks: {endpoint_id}')
        endpoint_weight = 1.0
        atom_weight = 1.0 / len(atoms)
        for sub in atoms:
            atom_id = f"atom.{endpoint_id}.{sub['id']}"
            rows.append({
                'id': atom_id, 'column': COLUMNS[1], 'mode': 'runtime',
                'group': endpoint_id, 'endpoint_id': endpoint_id,
                'endpoint_weight': endpoint_weight, 'atom_weight': atom_weight,
                'frozen_assertion_id': endpoint_id,
                'frozen_subcheck_id': sub['id'],
                'requirement_ids': list(sub['requirement_ids']),
                'requirement': sub['text'],
                'evidence_types': ['action', 'state', 'event', 'frame', 'log'],
            })
    ids = [r['id'] for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError('duplicate v4 atom IDs')
    return rows


def make_protocol_v4(frozen):
    """Build v4 while keeping every non-mechanic column identical to v3."""
    legacy = make_protocol(frozen)
    mechanisms = _atomic_mechanic_specs(frozen)
    criteria_v4 = [s for s in legacy['criteria'] if s['column'] != COLUMNS[1]] + mechanisms
    from .budgets import budget_for
    budget = budget_for(frozen['game_id'], frozen.get('tier', 'S'))
    return {**legacy, 'version': V4_VERSION, 'criteria': criteria_v4,
        'mechanic_scope': 'Frozen C2 endpoints split into frozen bound subchecks; endpoints have equal preregistered weight, atoms equal weight within endpoint. PASS/FAIL/UNVERIFIED are evidence-only; UNVERIFIED=0 and coverage is reported.',
        'mechanic_aggregation': {'version': 'endpoint-equal-atom-normalized.v1',
            'endpoint_weights': 'equal across frozen C2 endpoints',
            'atom_weights': 'equal within each endpoint; normalized to sum 1'},
        'runtime_budget': budget}
