"""Case selections derived from requirements before inspecting implementations."""
from .protocol import criteria

VERSION = 'whitebox-eightcol-sol-cases.v1'
COMMON = {
 'mechanic.entry': ('入口', '通过正常玩家输入从标题进入实际可操作的本测例游戏场景；状态与画面一致。'),
 'mechanic.pause': ('暂停', '正常Esc暂停冻结计时及玩法模拟，再正常恢复并继续推进；需要前后足够观察窗口，不以菜单出现替代模拟冻结。'),
 'mechanic.ending': ('结束', '通过正常玩法到达一个真实胜/负结算，并正常重开；HP、计时、局内进度和本测例关键状态恢复初始值。不得注入状态或调用结算。'),
}
CASES = {
 'G002_mountain_ritual_duel': [
  ('mechanic.entry', ['S06','S07']),
  ('mechanic.hit', ['G05','M03'], '普通攻击', '正常决斗中，在有效距离和朝向内、反击窗口外LMB普通攻击，使剑士实际HP减少20；需要真实输入、命中前提、HP前后及同步画面。'),
  ('mechanic.block', ['G03','M01'], '方向格挡', '正常敌方攻击时，RMB+匹配方向产生一次普通成功格挡：玩家HP不变、体力扣10，并出现格挡反馈；未被攻击、方向不明、仅举盾或完美格挡不得冒充此检查通过。'),
  ('mechanic.ritual', ['M05'], '仪式攻击', '正常T开启仪式攻击；验证实际背靠背准备、转身射击过程及合法命中的结局或取消恢复；按M05原文的输入、时间与次数限制检查，不以按T或播放动画代替实际闭环。'),
  ('mechanic.pause', ['S10','G06']),
  ('mechanic.ending', ['V01','V02','V03']),
 ],
 'G006_polar_radar_defense': [
  ('mechanic.entry', ['S06','S07']),
  ('mechanic.hit', ['G02','G03'], '开火伤害', '实际正常开火扣减弹匣并对敌人造成对应部位伤害：身体34、头68、四肢24中的至少一种；需要命中部位、前后HP和同步画面。只开火或空射不能通过。'),
  ('mechanic.reload', ['G02','G04'], '换弹经济', '先正常射击使弹匣未满，正常R换弹耗时约2秒，从备弹向30容量弹匣转移相同弹数；验证开始、完成、弹匣和备弹前后，未满/有备弹前提明确。'),
  ('mechanic.radar', ['G07'], '雷达脉冲', '防卫战真实推进至少一个8秒扫描周期，看到核心青色脉冲与HUD存活敌人标记、持续约2秒后消退；标记对应实际存活敌人，不以计时器声明或静态圆环替代。'),
  ('mechanic.pause', ['G08','G07']),
  ('mechanic.ending', ['V01','V02','V03']),
 ],
}

def case_criteria(case_id):
    if case_id not in CASES:
        raise ValueError(f'No predeclared case profile: {case_id}')
    selected = []
    for entry in CASES[case_id]:
        ident, reqs = entry[:2]
        group, text = entry[2:] if len(entry)>2 else COMMON[ident]
        selected.append({'id':ident, 'column':'机制完整性', 'mode':'runtime',
                         'group':group, 'requirement':text, 'requirement_ids':reqs})
    old = criteria()
    result = old[:4] + selected + old[10:]
    return result
