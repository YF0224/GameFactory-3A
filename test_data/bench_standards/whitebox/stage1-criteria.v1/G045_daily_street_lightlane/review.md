# Benchmark standard review — G045_daily_street_lightlane

Directory: `/Users/yifanyang/Desktop/GameFactory-3A-game-bench/test_data/bench_standards/whitebox/stage1-criteria.v1/G045_daily_street_lightlane`

Edit `<metric>.json` if needed, then approve with `python scripts_new/freeze_standards.py --stage x --approve G045_daily_street_lightlane`.

## gameness (41 checks)

依据 requirement.txt 与所列 CHECKS 冻结全部条目，未使用候选交付、运行证据或历史判定；本对象不报告得分或实现情况。各 id 保留原 layout、guidance、feedback 分组及含义，所有模型及后续模型适用同一目标。三档非累加：10% 为真实实现已接入玩法，源码可核查原需求参数；50% 为实际触发且基本反馈、界面或引导有效，核心对象与信息正确、无已知基本功能错误，但预期沟通效果尚未充分建立；100% 为真实原生结果画面及最少必要上下文足以让玩家辨认结果或下一步。单幅清晰画面即可，只有真实歧义、瞬态或因果关系需要补充上下文。精确时间、空间运动、数值公式、动画曲线及穷举分支边界在50%和100%均仅作诊断，不要求像素复刻。未覆盖属于未知；拒绝须有操作被处理并明确拒绝的证据，画面不变不足以证明。装饰动画或成功文字不能替代对应真实效果，不继承 Mechanic 判定。无冻结表现项的条目保留其明确排除含义，不新增验收条件。

### `game.layout.hierarchy` 

- **Requirement**: 实际UI信息层级清楚，主要状态与次要信息可区分。
- **Visible goal**: 玩家能从界面中区分当前目标、主要状态与辅助信息。
- **Result frame (100%)**: 真实游戏界面中，当前目标和主要状态具有清楚的视觉主次，辅助提示不会淹没它们。
- **Correct target**: 层级对应街区生活中的目标、资源和状态，次要说明与主要行动信息可区分。
- **Necessary context**: 进入正常游戏界面的清晰画面即可。
- **Basic function (50%)**: 玩家能在HUD中辨认当前目标及相关主要状态。
- **Basic bugs**: 主要目标被次要信息遮蔽而无法辨认; 界面缺乏可辨的主次关系，无法找到主要状态
- **Trigger modes**: automatic, input

### `game.layout.readable` 

- **Requirement**: 实际UI文字、尺寸、对比度及布局可读，无明显遮挡/重叠。
- **Visible goal**: 玩家能读清真实游戏界面的关键文字和控件。
- **Result frame (100%)**: 界面中的状态、提示和操作文字清楚可辨，没有妨碍理解的遮挡或重叠。
- **Correct target**: 可读对象是玩家当前使用的HUD或面板中的必要信息。
- **Necessary context**: 真实界面的清晰完整画面即可。
- **Basic function (50%)**: 玩家能读懂当前界面的关键提示并辨认相应控件。
- **Basic bugs**: 关键文字与背景无法区分; 关键提示被裁切或重叠到无法理解; 必要操作控件不可辨认
- **Trigger modes**: automatic, input

### `game.guidance.controls` 

- **Requirement**: 实际游戏展示或清楚传达必要操作方法。
- **Visible goal**: 游戏画面清楚说明玩家进行街区活动所需的操作方法。
- **Result frame (100%)**: 入场说明或情境提示把必要按键与移动、观察、交互等动作清楚对应。
- **Correct target**: 说明针对当前可用的键鼠操作，交互提示明确指向相应动作。
- **Necessary context**: 显示操作说明或真实交互提示的画面即可。
- **Basic function (50%)**: 玩家能从画面知道如何移动及如何与当前对象交互。
- **Basic bugs**: 必要操作没有可发现的说明; 按键说明对应错误动作; 操作文字被遮挡到无法理解
- **Trigger modes**: automatic, input

### `expanded.G.s0007` 

- **Requirement**: - P06 白天/黄昏/夜间光照变化，夜间道路可见
- **Visible goal**: 街区光照能传达昼夜氛围，夜间道路仍可辨认。
- **Result frame (100%)**: 街区呈现可识别的时段光照，夜景中的道路和可行走方向清楚可见。
- **Correct target**: 光照作用于真实街区道路与场景，而非仅有时段文字或独立装饰画。
- **Necessary context**: 夜间街区画面为主要结果；仅在时段变化含义不清时补充其他时段画面。
- **Basic function (50%)**: 玩家能在夜景中辨认道路并理解当前环境处于夜间。
- **Basic bugs**: 夜间道路黑到无法辨认; 时段标签与场景光照含义明显矛盾
- **Trigger modes**: automatic

### `expanded.G.s0011` 

- **Requirement**: - U01 HUD：日期时间、现金、已付/未付租金、小地图、当前目标、生活状态、附近交互提示、注意度
- **Visible goal**: HUD让玩家理解当前街区生活状况与行动目标。
- **Result frame (100%)**: 游戏画面中的HUD清楚组织日期时间、现金、租金、小地图、目标、生活状态、交互提示和注意度等信息。
- **Correct target**: 信息属于当前玩家与当前街区情境，已付租金和未付租金的含义可辨。
- **Necessary context**: 正常游玩且相关HUD可见的画面即可。
- **Basic function (50%)**: 玩家能从HUD读出自身资源、生活状况及当前行动指向。
- **Basic bugs**: 现金与已付租金混淆; HUD主要信息无法辨认; 提示明显指向错误角色或对象
- **Trigger modes**: automatic

### `expanded.G.s0012` 

- **Requirement**: 低状态突出提醒。
- **Visible goal**: 生活状态偏低时，玩家能看出需要关注的具体状态。
- **Result frame (100%)**: 低状态在HUD或相关提示中被突出显示，玩家可辨认是哪项生活需要出现问题。
- **Correct target**: 突出提醒对应实际偏低的生活状态，而非无关资源或其他角色。
- **Necessary context**: 低状态及对应提醒同屏即可。
- **Basic function (50%)**: 玩家能通过突出提示辨认当前需要照顾的生活状态。
- **Basic bugs**: 提醒标错生活状态; 低状态与正常状态视觉上无法区分; 警告文字不可读
- **Trigger modes**: automatic

### `expanded.G.s0013` 

- **Requirement**: UI 显示与真实状态一致。
- **Visible goal**: 界面准确表达玩家当前可观察的游戏状态。
- **Result frame (100%)**: 状态面板、背包或地图所显示的对象和状态，与同一情境中可见的游戏结果相符。
- **Correct target**: 核对对象为当前玩家的物品、任务、资源或已发现地点，核心状态含义一致。
- **Necessary context**: 状态与其对应结果同屏即可；若不能同屏，只补充关联的结果画面。
- **Basic function (50%)**: 玩家能从界面正确辨认当前物品或任务状态。
- **Basic bugs**: 已交出的物品仍显示为持有; 未完成事项显示为完成; 界面关联了错误对象
- **Trigger modes**: automatic, input

### `expanded.G.s0014` 

- **Requirement**: UI 适配 1920×1080 与 1280×720（冻结口径）
- **Visible goal**: 界面在适配后的视口中仍保持关键内容可读、操作入口可见。
- **Result frame (100%)**: 适配后的游戏画面中，HUD和当前面板没有把必要文字或按钮裁出可用区域。
- **Correct target**: 适配对象是实际游戏界面的关键信息与控件。
- **Necessary context**: 适配后视口的完整原生画面即可；存在裁切歧义时补充相应界面。
- **Basic function (50%)**: 玩家能在适配后的界面读懂提示并找到必要按钮。
- **Basic bugs**: 关键按钮被裁切而无法使用; 主要文字重叠到无法理解; 面板遮住必要操作入口
- **Trigger modes**: automatic, input

### `expanded.G.s0003` 

- **Requirement**: - L01 基准 1 真实秒＝1 游戏分钟。新日 08:00 开始
- **Visible goal**: 日期时间显示让玩家理解街区生活正在推进，并能辨认新日的清晨状态。
- **Result frame (100%)**: HUD呈现可理解的游戏日期与时钟，新日画面显示清晨生活情境。
- **Correct target**: 时钟表示游戏内日期时间，与所显示的日程情境相符。
- **Necessary context**: 新日画面可独立说明清晨状态；需要说明时钟推进时补充前后时钟画面。
- **Basic function (50%)**: 玩家能读懂当前游戏日期和时段。
- **Basic bugs**: 日期时间显示无法理解; 新日显示与清晨情境明显矛盾; 时钟显示无效内容
- **Trigger modes**: automatic

### `expanded.G.s0004` 

- **Requirement**: 24:00 提示回家，02:00 触发疲劳送回家并跳至当日 08:00（第 N 日 02:00→第 N 日 08:00，不再额外＋1 日）。每天只触发一次该事件。
- **Visible goal**: 玩家能理解角色因疲劳被送回家，并已在家中迎来清晨。
- **Result frame (100%)**: 结果画面显示角色位于家中，伴有疲劳返家说明及清晨状态。
- **Correct target**: 说明针对当前玩家的疲劳返家，地点与日期时段显示应与返家结果相符。
- **Necessary context**: 返家结果与原因同屏即可；原因不在结果中时，仅补充疲劳返家提示画面。
- **Basic function (50%)**: 玩家能从结果画面理解自己为何回家以及接下来可继续生活。
- **Basic bugs**: 声称返家但角色仍在原处; 返家说明指向错误原因或角色; 日期与清晨结果明显矛盾
- **Trigger modes**: automatic

### `expanded.G.s0016` 

- **Requirement**: - S04 刷新恢复一致状态
- **Visible goal**: 重新进入后，玩家能认出此前保存的生活进度已恢复。
- **Result frame (100%)**: 恢复后的游戏画面呈现与保存情境相符的角色位置和主要进度信息。
- **Correct target**: 恢复内容属于此前保存的同一局玩家状态。
- **Necessary context**: 保存前与恢复后的相关画面仅用于建立同一进度的对应关系。
- **Basic function (50%)**: 玩家能在恢复画面中认出已保存的资源或任务进度。
- **Basic bugs**: 恢复成无关旧局; 主要进度被清空却显示恢复成功; 恢复后界面与场景状态明显矛盾
- **Trigger modes**: automatic, input

### `expanded.G.s0017` 

- **Requirement**: 存档带版本号，损坏/不兼容提示恢复选项，不静默清空。正常新开局重置局内数据，不串入旧局。
- **Visible goal**: 存档无法使用时，界面明确解释问题并提供可理解的恢复选择。
- **Result frame (100%)**: 存档错误或不兼容提示中显示恢复选项，玩家能理解可采取的下一步。
- **Correct target**: 提示针对当前无法使用的存档，恢复与新开局的含义可区分。
- **Necessary context**: 实际读档受阻后出现的错误与恢复界面即可。
- **Basic function (50%)**: 玩家能从存档问题提示中找到明确的恢复入口。
- **Basic bugs**: 存档出错后静默清空进度; 错误提示没有可理解的恢复入口; 恢复选项含义与实际结果相反
- **Trigger modes**: automatic, input, rejection

### `expanded.G.s0005` 

- **Requirement**: - A07 处理选项至少包括解释、道歉/清理、赔偿或劳动
- **Visible goal**: 邻里事件处理界面让玩家看懂可选择的补救方式。
- **Result frame (100%)**: 真实事件的处理面板展示解释、道歉或清理、赔偿或劳动等具有明确行动含义的选择。
- **Correct target**: 选项对应当前邻里事件及其受影响对象。
- **Necessary context**: 包含事件对象或事件说明的处理面板即可。
- **Basic function (50%)**: 玩家能在事件面板中辨认处理方式并选择补救行动。
- **Basic bugs**: 选项没有可理解的处理含义; 面板对应错误事件; 必要选项控件不可使用
- **Trigger modes**: input, automatic

### `expanded.G.s0006` 

- **Requirement**: 其结果改变事件状态，避免只有文字提示。
- **Visible goal**: 处理邻里事件后，玩家能看出该事件的实际状态发生变化。
- **Result frame (100%)**: 被处理的事件呈现可辨认的解决或补救进展，如现场恢复或事件条目状态更新。
- **Correct target**: 变化属于玩家刚处理的事件，结果与所选处理含义一致。
- **Necessary context**: 结果已明确关联处理对象时无需补帧；否则补充处理选择或事前状态。
- **Basic function (50%)**: 玩家能看到所选处理使当前事件进入新的可辨认状态。
- **Basic bugs**: 仅显示成功文字而对应事件无实际变化; 变化发生在错误事件上; 处理结果与选项含义相反
- **Trigger modes**: input, automatic

### `expanded.G.s0024` 

- **Requirement**: 事件【移动/跑步】实际发生时可视表现为【步行/跑步动画＋脚步节奏】，结束条件【移动停止】。仅评价可视投影，音频未评。未触发事件不能PASS。
- **Visible goal**: 角色真实移动时，姿态能让玩家辨认正在步行或跑步。
- **Result frame (100%)**: 街区中的玩家角色呈现与当前移动方式相符的行走或奔跑姿态。
- **Correct target**: 可视表现属于正在移动的玩家角色，而非无关角色或静态示意。
- **Necessary context**: 清楚的移动姿态画面即可；姿态含义有歧义时补充相邻动作画面，不评价音频。
- **Basic function (50%)**: 玩家能从角色动作辨认当前移动状态。
- **Basic bugs**: 角色移动时保持明显无关的静态姿势; 步行与跑步表现语义明显颠倒; 动画作用于错误角色
- **Trigger modes**: held, input

### `expanded.G.s0025` 

- **Requirement**: 事件【骑行】实际发生时可视表现为【上车过渡＋车铃提示钮】，结束条件【下车或按铃】。仅评价可视投影，音频未评。未触发事件不能PASS。
- **Visible goal**: 骑行反馈让玩家理解角色已上车并可找到车铃操作。
- **Result frame (100%)**: 玩家角色与自行车呈现明确的骑乘关系，骑行情境中可见车铃提示钮。
- **Correct target**: 骑乘及车铃提示针对玩家当前使用的自行车。
- **Necessary context**: 骑乘结果与车铃提示清晰同屏即可；上车关系不清时补充过渡画面，不评价音频。
- **Basic function (50%)**: 玩家能辨认已进入骑行状态并知道车铃操作入口。
- **Basic bugs**: 显示骑行提示但角色没有实际骑乘; 车铃提示指向错误载具; 车铃控件不可辨认或不可用
- **Trigger modes**: input

### `expanded.G.s0026` 

- **Requirement**: 事件【购物结账】实际发生时可视表现为【收银台金币滚动＋物品入包】，结束条件【动画收束】。仅评价可视投影，音频未评。未触发事件不能PASS。
- **Visible goal**: 购物结账的画面让玩家理解购买的物品已收入背包。
- **Result frame (100%)**: 收银情境中的金币与物品入包表现，清楚关联到已购买物品的背包结果。
- **Correct target**: 表现针对本次购买的商品和玩家背包。
- **Necessary context**: 结果已显示商品入包时无需补帧；否则补充结账表现及对应背包结果，不评价音频。
- **Basic function (50%)**: 玩家能从结账反馈辨认购买完成及所得物品。
- **Basic bugs**: 只有金币装饰动画却未获得商品; 入包物品与购买对象不符; 购买失败却显示结账成功
- **Trigger modes**: input, automatic

### `expanded.G.s0027` 

- **Requirement**: 事件【开关门/进出建筑】实际发生时可视表现为【门开合动画】，结束条件【门闭合】。仅评价可视投影，音频未评。未触发事件不能PASS。
- **Visible goal**: 门的可视开合让玩家理解角色正在通过相应建筑入口。
- **Result frame (100%)**: 玩家使用的建筑入口呈现可辨认的门开启或关闭状态。
- **Correct target**: 发生变化的是本次进出所用的门。
- **Necessary context**: 入口与门状态清楚的画面即可；开合变化不明时补充关联画面，不评价音频。
- **Basic function (50%)**: 玩家能看到当前入口的门对进出行为作出可辨反应。
- **Basic bugs**: 门的表现发生在错误入口; 提示门已打开但对应门仍明显封闭; 门表现与进出结果明显矛盾
- **Trigger modes**: input, automatic

### `expanded.G.s0028` 

- **Requirement**: 事件【拾取/交付】实际发生时可视表现为【物品飞入背包/交出弧线】，结束条件【动画收束】。仅评价可视投影，音频未评。未触发事件不能PASS。
- **Visible goal**: 物品转移的画面让玩家理解拾取或交付的去向。
- **Result frame (100%)**: 被操作物品呈现入包或交出的可辨转移表现，并与对应接收结果相符。
- **Correct target**: 转移对象是本次拾取或交付的物品，接收方为玩家背包或指定交付对象。
- **Necessary context**: 转移方向及结果清楚时无需补帧；否则补充对应背包或接收结果，不评价音频。
- **Basic function (50%)**: 玩家能辨认被操作物品已转交给正确接收方。
- **Basic bugs**: 物品动画指向错误接收方; 只有飞行动画而物品没有实际转移; 转移了错误物品
- **Trigger modes**: input, automatic

### `expanded.G.s0029` 

- **Requirement**: 事件【任务完成】实际发生时可视表现为【任务卡打勾＋日志条目高亮】，结束条件【卡片定格】。仅评价可视投影，音频未评。未触发事件不能PASS。
- **Visible goal**: 任务完成反馈让玩家明确知道完成的是哪项任务。
- **Result frame (100%)**: 已完成任务的任务卡显示完成标记，相关日志条目得到可辨强调。
- **Correct target**: 完成标记与日志强调对应刚完成的同一任务。
- **Necessary context**: 完成任务名称和标记清楚的画面即可；对应关系不清时补充相关日志画面，不评价音频。
- **Basic function (50%)**: 玩家能从任务卡和日志辨认本次任务完成。
- **Basic bugs**: 未完成任务被标记为完成; 任务卡与日志指向不同任务; 完成标记无法辨认
- **Trigger modes**: automatic, input

### `expanded.G.s0030` 

- **Requirement**: 事件【注意度升级】实际发生时可视表现为【HUD 注意度色阶变化＋目击者感叹标记】，结束条件【等级回落或处理完成】。仅评价可视投影，音频未评。未触发事件不能PASS。
- **Visible goal**: 注意度升级的画面让玩家理解邻里已对自己的行为产生警觉。
- **Result frame (100%)**: HUD注意度呈现升级的视觉信号，相关目击者带有可辨的感叹标记。
- **Correct target**: 警觉信号对应当前玩家引发的事件及其目击者。
- **Necessary context**: HUD与目击者同屏即可；关联不清时补充对应事件画面，不评价音频。
- **Basic function (50%)**: 玩家能辨认注意度已升高以及谁在关注自己。
- **Basic bugs**: 警觉标记落在无关对象上; 升级表现反而传达警觉降低; HUD警觉信号不可辨认
- **Trigger modes**: automatic

### `expanded.G.s0031` 

- **Requirement**: 事件【处理补救】实际发生时可视表现为【处理选项面板确认反馈】，结束条件【面板关闭】。仅评价可视投影，音频未评。未触发事件不能PASS。
- **Visible goal**: 处理选项的确认反馈让玩家理解自己的补救选择已被接受。
- **Result frame (100%)**: 处理面板显示与所选补救行动对应的确认反馈。
- **Correct target**: 反馈明确对应当前事件和玩家刚选择的处理方式。
- **Necessary context**: 确认内容能识别选择时单幅即可；否则补充所选选项画面，不评价音频。
- **Basic function (50%)**: 玩家能看出补救选择已被确认。
- **Basic bugs**: 确认了与所选项不同的行动; 拒绝处理却显示已接受; 面板反馈无法关联当前事件
- **Trigger modes**: input, automatic

### `expanded.G.s0032` 

- **Requirement**: 事件【睡觉日结】实际发生时可视表现为【屏幕渐暗→日期横幅→晨光亮起】，结束条件【进入次日 08:00】。仅评价可视投影，音频未评。未触发事件不能PASS。
- **Visible goal**: 睡觉日结反馈让玩家理解旧日结束并已进入新日清晨。
- **Result frame (100%)**: 日期横幅与晨光场景清楚传达睡眠后的新日结果。
- **Correct target**: 横幅日期、HUD日期与玩家醒来的清晨情境相符。
- **Necessary context**: 新日结果已明确标注睡眠日结时单幅即可；否则补充睡觉入口或日结过渡画面，不评价音频。
- **Basic function (50%)**: 玩家能从日结结果辨认已进入新的一天。
- **Basic bugs**: 日期横幅与HUD日期矛盾; 仅播放日结装饰却未进入新日; 晨起结果被错误描述为旧日未结束
- **Trigger modes**: input, automatic

### `expanded.G.s0033` 

- **Requirement**: 事件【房租结算】实际发生时可视表现为【结算面板＋对应 VC04 意象】，结束条件【面板定格】。仅评价可视投影，音频未评。未触发事件不能PASS。
- **Visible goal**: 房租结算画面让玩家理解本次居住结算的真实结果。
- **Result frame (100%)**: 结算面板说明房租处理结果，并以钥匙与明亮夜灯或搬家纸箱等对应意象表达居住去向。
- **Correct target**: 结果指向当前玩家的房租与续约状态，续约和未续约的表达不得颠倒。
- **Necessary context**: 面板与对应意象清楚时单幅即可；分开展示时仅补充关联的结局画面，不评价音频。
- **Basic function (50%)**: 玩家能从房租结算辨认当前居住结果。
- **Basic bugs**: 续约与未续约意象颠倒; 结算面板与实际租金状态矛盾; 结算对象或结果文字不可理解
- **Trigger modes**: input, automatic

### `expanded.G.s0043` 

- **Requirement**: - F10 前端界面：标题（开始/继续/设置/退出）→ HUD（U01 全项）→ 背包/地图/日志面板 → 暂停面板（继续/存档/设置/返回）→ 日结/房租结算面板（U02/U03）
- **Visible goal**: 前端界面让玩家辨认当前页面的用途并找到相应操作入口。
- **Result frame (100%)**: 当前标题、游戏HUD、功能面板或结算页面具有清楚的内容组织和可辨的操作入口。
- **Correct target**: 页面内容与标题、游玩、背包地图日志、暂停或结算的当前用途相符。
- **Necessary context**: 当前真实页面的完整画面即可；仅在页面用途不清时补充其入口画面。
- **Basic function (50%)**: 玩家能在当前页面找到与页面用途相符的主要操作。
- **Basic bugs**: 页面用途与内容明显不符; 主要操作入口被遮挡而不可用; 页面之间缺乏可理解的返回或继续入口
- **Trigger modes**: automatic, input

### `expanded.G.s0044` 

- **Requirement**: 关键状态图标＋文字并用
- **Visible goal**: 关键状态通过图标和文字共同表达，使玩家理解其含义。
- **Result frame (100%)**: 关键状态旁有语义对应的图标与可读文字。
- **Correct target**: 图标和文字指向同一项玩家状态。
- **Necessary context**: 关键状态区域的清晰画面即可。
- **Basic function (50%)**: 玩家能借助图标与文字辨认关键状态。
- **Basic bugs**: 图标与文字含义相反; 关键状态缺少可理解的文字说明; 图标和文字关联到不同状态
- **Trigger modes**: automatic, input

### `expanded.G.s0045` 

- **Requirement**: 窗口失焦自动暂停（C01 模拟冻结口径）。
- **Visible goal**: 窗口失焦后，玩家能辨认游戏处于暂停状态。
- **Result frame (100%)**: 失焦后的游戏窗口显示明确的暂停界面或暂停标识。
- **Correct target**: 暂停提示属于当前游戏窗口，清楚表达当前模拟处于暂停状态。
- **Necessary context**: 包含窗口失焦线索与暂停提示的画面即可；若要消除暂停是否真实生效的歧义，只补充相关状态对照画面。
- **Basic function (50%)**: 玩家能从失焦后的窗口理解游戏已经暂停。
- **Basic bugs**: 显示暂停但可见模拟状态仍持续变化; 暂停界面无法理解; 暂停提示属于错误窗口或页面
- **Trigger modes**: automatic

### `expanded.G.s0021` 

- **Requirement**: 交互提示按候选排序高亮最近对象
- **Visible goal**: 交互高亮让玩家清楚辨认当前将操作的邻近对象。
- **Result frame (100%)**: 邻近交互对象具有明确的选中高亮，提示文字与该对象对应。
- **Correct target**: 高亮对象是当前可交互候选中的近邻目标，名称和动作提示不指向其他对象。
- **Necessary context**: 角色、候选对象和高亮提示同屏即可；精确排序不由截图推断。
- **Basic function (50%)**: 玩家能在交互前辨认当前选中的对象。
- **Basic bugs**: 高亮与提示指向不同对象; 目标高亮无法辨认; 明显不可交互对象被提示为当前有效目标
- **Trigger modes**: automatic, input, held

### `expanded.G.s0022` 

- **Requirement**: 顿帧不改变 C01 时钟口径。
- **Visible goal**: 画面恢复后，游戏时钟仍向玩家呈现连贯、可理解的生活时间。
- **Result frame (100%)**: 恢复后的HUD显示有效日期与时间，并与当前生活情境保持一致。
- **Correct target**: 显示对象是当前局的游戏时钟，不将加载或停顿提示误作游戏时间。
- **Necessary context**: 恢复后的时钟画面为主要结果；需要排除明显日期跳变歧义时补充停顿前画面，截图不证明精确计时公式。
- **Basic function (50%)**: 玩家能在画面恢复后继续读懂当前游戏时间。
- **Basic bugs**: 恢复后时钟显示无效内容; 日期时间与当前场景明显矛盾; 时间显示出现无法解释的倒退或跨日
- **Trigger modes**: automatic

### `expanded.G.s0001` 

- **Requirement**: - M04 E 交互：最近、有效、距离 ≤2m 且无遮挡的对象
- **Visible goal**: 交互后，玩家能看出操作作用于提示中的有效对象。
- **Result frame (100%)**: 当前邻近目标出现与交互提示相符的对话、物品接收或其他对象反馈。
- **Correct target**: 实际反馈对应提示中的可接近、无遮挡交互对象。
- **Necessary context**: 目标身份与反馈同屏即可；结果中看不出原目标时补充交互前提示画面。
- **Basic function (50%)**: 玩家能看到交互指令由当前提示对象响应。
- **Basic bugs**: 操作作用于提示以外的对象; 明确被墙阻隔的对象仍被成功操作; 反馈动作与所示交互含义相反
- **Trigger modes**: input, rejection

### `expanded.G.s0002` 

- **Requirement**: 不能隔墙对话或拾取。多个候选按距离、稳定对象 ID 排序，提示与实际对象一致。
- **Visible goal**: 交互反馈清楚表明当前对象是否可被操作，避免将隔墙对象误作已成功交互。
- **Result frame (100%)**: 操作结果指向提示中的有效对象；受墙体阻隔的操作则出现可理解的不可交互反馈。
- **Correct target**: 提示和实际响应属于同一对象，墙体阻隔不能被表达为成功对话或拾取。
- **Necessary context**: 结果与目标清楚时单幅即可；拒绝场景需有已处理操作的反馈及可见阻隔关系，画面不变不能单独证明拒绝。
- **Basic function (50%)**: 玩家能从反馈辨认当前对象被操作或因阻隔而不能操作。
- **Basic bugs**: 提示对象与响应对象不一致; 隔墙操作被错误显示为成功; 拒绝反馈无法辨认所针对对象
- **Trigger modes**: input, rejection

### `expanded.G.s0041` 

- **Requirement**: - F09 屏幕震动：本作无震动需求（生活模拟固定手感）
- **Visible goal**: 本条明确不设屏幕震动的独立可视结果要求。
- **Result frame (100%)**: 不存在必须交付的震动画面，普通游戏画面不承担证明震动有无的任务。
- **Correct target**: 无独立冻结目标，不以是否出现屏幕震动判断沟通效果。
- **Necessary context**: 无需为本条增加截图或动态上下文。
- **Basic function (50%)**: 本条未规定独立的画面基本功能。
- **Basic bugs**: 本条无独立基本功能错误项；不得把未提供震动视为错误
- **Trigger modes**: automatic

### `expanded.G.s0042` 

- **Requirement**: 表现层自由，不设冻结项。
- **Visible goal**: 本条保留表现层自由，不增加独立可视结果要求。
- **Result frame (100%)**: 不存在本条要求的固定表现画面。
- **Correct target**: 无独立冻结对象，具体视觉风格不作为本条验收目标。
- **Necessary context**: 无需为本条增加证据画面。
- **Basic function (50%)**: 本条未规定独立的画面基本功能。
- **Basic bugs**: 本条无独立基本功能错误项；不得因表现形式不同判错
- **Trigger modes**: automatic

### `expanded.G.s0050` 

- **Requirement**: 界面支持玩家判断当前资源和行动条件，并明确传达无法执行的原因。
- **Visible goal**: 行动界面让玩家理解当前资源是否支持所选行动及不能执行的原因。
- **Result frame (100%)**: 所选行动旁显示相关资源或条件，受阻时明确说明缺少什么。
- **Correct target**: 提示对应当前行动所需的现金、物品或状态条件。
- **Necessary context**: 行动条件画面即可；拒绝结果须包含操作已被处理的明确原因反馈。
- **Basic function (50%)**: 玩家能根据界面理解当前行动为何可用或受阻。
- **Basic bugs**: 拒绝原因指向无关资源; 条件说明与行动可用性相反; 受阻后没有可理解的原因反馈
- **Trigger modes**: automatic, input, rejection

### `expanded.G.s0046` 

- **Requirement**: 玩家能在操作前知道当前目标及可执行的下一步，不依赖阅读工程文档。
- **Visible goal**: 玩家在行动前能从游戏内界面知道当前目标及可做的下一步。
- **Result frame (100%)**: 目标提示说明当前要做的事，并给出可理解的行动对象、地点或操作入口。
- **Correct target**: 指引对应当前任务阶段与可用行动，不依赖工程文档。
- **Necessary context**: 执行行动前的目标或任务提示画面即可。
- **Basic function (50%)**: 玩家能从当前目标提示找到下一步行动方向。
- **Basic bugs**: 引导指向错误对象或地点; 目标文字无法理解; 提示要求的行动在当前情境不可执行且无说明
- **Trigger modes**: automatic, input

### `expanded.G.s0048` 

- **Requirement**: 目标进度、阶段变化与终局结果向玩家明确呈现。
- **Visible goal**: 目标状态反馈让玩家理解当前取得的进展或阶段结果。
- **Result frame (100%)**: 目标卡、日志或阶段结算清楚标示当前进展及其完成或待补救含义。
- **Correct target**: 呈现内容对应当前目标的真实状态，阶段结果不被误写为无条件结束游戏。
- **Necessary context**: 当前目标或阶段结果明确的画面即可；只有变化含义不明时补充前一状态。
- **Basic function (50%)**: 玩家能辨认目标目前处于何种进展状态。
- **Basic bugs**: 完成与失败结果颠倒; 反馈对应错误目标; 阶段状态无法辨认
- **Trigger modes**: automatic, input

### `expanded.G.s0053` 

- **Requirement**: 长期后果、跨阶段保留或失去的状态有可观察的解释；仅在需求存在时判断。
- **Visible goal**: 玩家能从界面解释理解早先行动为何影响当前机会或保留状态。
- **Result frame (100%)**: 对话、日志或目标说明把当前帮助、延期或其他后果与此前的信任、发现或行动记录联系起来。
- **Correct target**: 解释指向需求已有的长期后果及相关角色或记录。
- **Necessary context**: 因果解释已在当前画面明确时无需补帧；否则仅补充所指早先记录。
- **Basic function (50%)**: 玩家能理解当前机会或后果与此前行动的关系。
- **Basic bugs**: 将后果归给错误角色或事件; 解释与当前保留状态明显矛盾; 长期后果已出现却没有可理解的原因说明
- **Trigger modes**: automatic, input

### `expanded.G.s0049` 

- **Requirement**: 冻结玩法中的资源/路线/时机选择有可理解的代价与收益提示。
- **Visible goal**: 选择提示让玩家理解当前资源、路线或行动安排的代价与收益。
- **Result frame (100%)**: 任务、地图或行动选项中清楚说明当前选择会消耗什么、带来什么或承担何种后果。
- **Correct target**: 提示属于需求中的真实生活选择，如工作报酬、消费、路线限制或期限风险。
- **Necessary context**: 包含所选行动及其代价收益说明的画面即可。
- **Basic function (50%)**: 玩家能在选择前看懂该行动的主要取舍。
- **Basic bugs**: 将消耗误写为奖励; 代价收益说明对应错误行动; 关键取舍信息不可理解
- **Trigger modes**: automatic, input

### `expanded.G.s0051` 

- **Requirement**: 危险预警与恢复入口可发现，玩家能据此调整操作。
- **Visible goal**: 风险提示让玩家找到可采取的恢复或补救行动。
- **Result frame (100%)**: 生活状态或邻里风险出现时，画面说明问题并提供可发现的休息、补救或安全恢复入口。
- **Correct target**: 预警与入口对应当前风险，不引入需求之外的战斗或死亡系统。
- **Necessary context**: 风险说明与相关行动入口清楚的画面即可。
- **Basic function (50%)**: 玩家能根据预警找到处理当前问题的行动入口。
- **Basic bugs**: 预警指出错误风险; 恢复入口无法发现或使用; 所示入口与当前问题无关
- **Trigger modes**: automatic, input

### `expanded.G.s0047` 

- **Requirement**: 核心操作产生的成功、失败或拒绝反馈可被区分；此处不重复计算 C2 数值正确性。
- **Visible goal**: 核心操作反馈让玩家辨认本次行动是成功、失败还是被拒绝。
- **Result frame (100%)**: 操作结果以清楚的状态、对象变化或原因提示表达本次行动的结果。
- **Correct target**: 反馈指向刚执行的行动与目标，成功和受阻含义不混淆。
- **Necessary context**: 结果与对象明确时单幅即可；拒绝须有已处理操作的明确反馈，必要时补充操作前情境。
- **Basic function (50%)**: 玩家能看懂当前操作的结果类别。
- **Basic bugs**: 失败或拒绝显示为成功; 反馈指向错误操作或对象; 结果文字与可见实际效果相反
- **Trigger modes**: input, automatic, rejection

### `expanded.G.s0052` 

- **Requirement**: 并发单位或多个事件同时发生时，关键反馈仍能对应到正确对象。
- **Visible goal**: 多个对象或事件在场时，玩家仍能把关键反馈对应到正确对象。
- **Result frame (100%)**: 当前关键提示通过对象名称、位置标记或事件标题清楚表明反馈归属。
- **Correct target**: 反馈明确属于本次行动或事件涉及的角色、物品或任务。
- **Necessary context**: 相关对象与反馈同屏且归属清楚即可；存在真实歧义时仅补充对应事件画面。
- **Basic function (50%)**: 玩家能在多个对象的场景中辨认关键反馈针对谁。
- **Basic bugs**: 反馈错误归属其他角色或事件; 关键反馈被其他提示遮到无法理解; 对象标记与提示名称相互矛盾
- **Trigger modes**: automatic, input

## mechanic (20 checks)

冻结每项机制的可见结果标准：以截图证明目标对象发生了要求的核心游戏效果，并保留原始要求作为诊断依据。

### `atom.G045_daily_street_lightlane.WB.TC2.01.C2.tiered.01` 

- **Requirement**: 玩家通过原生交互完成两米内无遮挡目标的操作，超距或遮挡目标不可远程触发。
- **Visible goal**: 玩家对近处无遮挡目标完成原生交互，目标出现对应的交互结果。
- **Result frame (100%)**: 画面同时显示玩家、被操作的无遮挡目标及交互后的明确状态变化。
- **Correct target**: 交互结果作用于玩家当前面对的近处无遮挡目标。
- **Necessary context**: 目标可见且玩家处于可进行原生交互的位置，画面能辨认操作对象和结果。
- **Basic function (50%)**: 原生交互能对有效目标产生实际结果，并对远处或被遮挡目标拒绝远程触发。
- **Basic bugs**: 交互作用于错误目标; 远处目标被远程触发; 被遮挡目标被远程触发
- **Trigger modes**: input, rejection

### `atom.G045_daily_street_lightlane.WB.TC2.02.C2.tiered.02` 

- **Requirement**: 通过原生上下车交互切换步行与自行车状态并可继续移动。
- **Visible goal**: 玩家通过原生上下车交互在步行与自行车状态之间切换，并继续移动。
- **Result frame (100%)**: 画面显示玩家已处于切换后的步行或骑车状态，并在场景中继续移动。
- **Correct target**: 状态切换作用于玩家与当前可用的自行车。
- **Necessary context**: 画面能同时辨认玩家状态、自行车关系和切换后的位置变化。
- **Basic function (50%)**: 上下车交互能完成步行与骑车状态转换，转换后移动仍然可用。
- **Basic bugs**: 上下车后状态未改变; 状态切换作用于错误对象; 切换后无法继续移动
- **Trigger modes**: input

### `atom.G045_daily_street_lightlane.WB.TC2.03.C2.tiered.03` 

- **Requirement**: 打开原生菜单或暂停后世界模拟不推进，关闭后恢复。
- **Visible goal**: 打开原生菜单或暂停后世界模拟停止，关闭后恢复推进。
- **Result frame (100%)**: 画面显示菜单或暂停界面覆盖游戏世界，关闭后同一世界状态继续变化。
- **Correct target**: 暂停影响游戏世界模拟，而非仅显示界面。
- **Necessary context**: 画面能辨认暂停状态以及关闭后世界恢复运行的结果。
- **Basic function (50%)**: 原生暂停控制能冻结世界模拟并在恢复后继续。
- **Basic bugs**: 暂停期间世界仍推进; 关闭菜单后世界未恢复; 仅界面变化而模拟未暂停
- **Trigger modes**: input

### `atom.G045_daily_street_lightlane.WB.TC2.04.C2.tiered.04` 

- **Requirement**: 精力经正常游戏降至二十以下时跑步速度降低百分之二十，等于二十时不触发。
- **Visible goal**: 精力不足时玩家跑步状态明显降为较慢移动状态。
- **Result frame (100%)**: 画面显示低精力玩家仍在移动，但跑步表现已变为较慢的移动表现。
- **Correct target**: 速度变化作用于玩家的跑步移动。
- **Necessary context**: 画面能辨认玩家精力处于不足状态及其移动状态。
- **Basic function (50%)**: 精力正常消耗到不足后，跑步速度降低；精力处于临界正常状态时不提前触发。
- **Basic bugs**: 低精力跑步速度未降低; 速度降低作用于错误移动状态; 精力未达到不足状态就降低速度
- **Trigger modes**: automatic

### `atom.G045_daily_street_lightlane.WB.TC2.05.C2.tiered.05` 

- **Requirement**: 花费八十现金获得饭团，实际食用增加三十五饱腹且该物品不能重复食用。
- **Visible goal**: 玩家购买并实际食用饭团后，饱腹状态增加且该饭团被消耗。
- **Result frame (100%)**: 画面显示购买所得饭团已被食用，饱腹值或状态上升，物品不再可重复食用。
- **Correct target**: 现金扣除、饱腹增加和物品消耗作用于同一饭团及玩家。
- **Necessary context**: 画面能辨认购买、饭团、食用后的饱腹变化和物品状态。
- **Basic function (50%)**: 玩家能用现金获得饭团并实际食用一次，食用产生饱腹效果且不能重复使用。
- **Basic bugs**: 未付款即可获得饭团; 食用后饱腹未增加; 已食用饭团仍可重复食用
- **Trigger modes**: input

### `atom.G045_daily_street_lightlane.WB.TC2.06.C2.tiered.06` 

- **Requirement**: 通过原生睡觉进入下一次八点，精力恢复一百，不重复结算跳过时段的被动衰减。
- **Visible goal**: 玩家通过原生睡觉进入下一次早晨，精力恢复。
- **Result frame (100%)**: 画面显示睡觉后时间进入下一次早晨，玩家精力恢复，跳过时段的衰减未被重复结算。
- **Correct target**: 睡觉影响当前玩家的时间、精力和一次时段结算。
- **Necessary context**: 画面能辨认睡觉前后时间与精力状态，以及恢复后的游戏状态。
- **Basic function (50%)**: 原生睡觉能推进到下一次早晨并恢复精力，同时完成一次正常的跳时处理。
- **Basic bugs**: 睡觉后未进入下一次早晨; 精力未恢复; 跳过时段造成重复衰减
- **Trigger modes**: input, automatic

### `atom.G045_daily_street_lightlane.WB.TC2.07.C2.tiered.07` 

- **Requirement**: 把六件商品按标签放回后获得三百五十现金，未实际完成时不能从面板直接领取。
- **Visible goal**: 玩家将六件商品按标签放回后，任务奖励现金实际增加。
- **Result frame (100%)**: 画面显示商品已放回对应标签位置，任务完成状态出现并显示现金增加。
- **Correct target**: 商品放置到各自标签对应位置，奖励归于玩家账户。
- **Necessary context**: 画面能辨认商品、标签位置、完成状态和奖励变化。
- **Basic function (50%)**: 完成实际归类放置后才结算奖励，任务面板本身不能直接领取。
- **Basic bugs**: 商品放错标签仍算完成; 未实际放置即可领取奖励; 奖励未增加或重复发放
- **Trigger modes**: input, automatic, rejection

### `atom.G045_daily_street_lightlane.WB.TC2.08.C2.tiered.08` 

- **Requirement**: 领取货物并把它交给目标后获得四百五十现金，不凭任务面板点击直接结算。
- **Visible goal**: 玩家领取货物并将其交给目标后，任务奖励现金实际增加。
- **Result frame (100%)**: 画面显示目标收到货物，交付完成状态出现并显示现金增加。
- **Correct target**: 货物交给任务指定目标，奖励归于玩家账户。
- **Necessary context**: 画面能辨认货物、指定目标、交付结果和奖励变化。
- **Basic function (50%)**: 领取并实际交付货物后才结算奖励，任务面板不能直接完成交付。
- **Basic bugs**: 交给错误目标仍算完成; 未领取或未交付即可结算; 奖励未增加或重复发放
- **Trigger modes**: input, automatic, rejection

### `atom.G045_daily_street_lightlane.WB.TC2.09.C2.tiered.09` 

- **Requirement**: 超过一百二十游戏分钟后实际交货，按逾期二百五十报酬一次结算。
- **Visible goal**: 玩家在逾期后实际完成交货，系统显示逾期交付并结算对应报酬。
- **Result frame (100%)**: 画面显示货物已交给目标、任务标记为逾期完成并出现一次报酬结算。
- **Correct target**: 逾期状态和报酬作用于同一份货物交付任务。
- **Necessary context**: 画面能辨认交货目标、逾期任务状态和一次性报酬结果。
- **Basic function (50%)**: 超过任务期限后实际交货能按逾期规则完成一次结算。
- **Basic bugs**: 未实际交货即可逾期结算; 交给错误目标仍结算; 逾期报酬重复发放
- **Trigger modes**: input, automatic

### `atom.G045_daily_street_lightlane.WB.TC2.10.C2.tiered.10` 

- **Requirement**: 通过原生借车和归还流程完成任务，按时归还与暂不归还产生不同信任和后续对话。
- **Visible goal**: 玩家通过原生借车并归还，按时归还与暂不归还产生不同信任和后续对话。
- **Result frame (100%)**: 画面显示借车关系及归还后的对话或信任结果，能看出两种处理产生不同后果。
- **Correct target**: 借车、归还、信任变化和对话作用于借车双方及该自行车。
- **Necessary context**: 画面能辨认借车对象、自行车、归还状态和后续对话或信任反馈。
- **Basic function (50%)**: 原生借车流程能记录借用，并根据归还处理产生相应后续关系结果。
- **Basic bugs**: 未借车即可归还; 归还状态未被记录; 按时归还与暂不归还产生相同后果
- **Trigger modes**: input, automatic

### `atom.G045_daily_street_lightlane.WB.TC2.11.C2.tiered.11` 

- **Requirement**: 房租日通过有效清理劳动抵扣剩余欠款，每份至多三百，不能同时领取对应现金或把超额抵扣变现。
- **Visible goal**: 房租日玩家通过有效清理劳动抵扣欠款，欠款减少且未获得对应现金。
- **Result frame (100%)**: 画面显示清理劳动完成、剩余欠款减少，并显示抵扣而非现金奖励。
- **Correct target**: 劳动成果抵扣玩家的实际欠租余额。
- **Necessary context**: 画面能辨认房租日、清理劳动完成、欠款变化和现金状态。
- **Basic function (50%)**: 有效清理劳动能用于抵扣欠租，每份抵扣有上限，不能同时领取现金或将超额转成现金。
- **Basic bugs**: 未完成清理即可抵扣; 抵扣错误债务或错误账户; 抵扣同时变成现金或可无限超额兑换
- **Trigger modes**: input, automatic, rejection

### `atom.G045_daily_street_lightlane.WB.TC2.12.C2.tiered.12` 

- **Requirement**: 保存后刷新通过原生继续流程恢复同一局的时间、资源和任务进度，不静默清空或重复领取。
- **Visible goal**: 保存后通过原生继续流程恢复同一局的时间、资源和任务进度。
- **Result frame (100%)**: 画面显示继续进入后仍保留此前的时间、资源和任务进度，未出现静默清空或重复领取。
- **Correct target**: 恢复结果对应保存的同一局玩家状态和任务状态。
- **Necessary context**: 画面能辨认继续流程以及保存前后可比较的时间、资源和任务进度。
- **Basic function (50%)**: 原生保存并继续能恢复同一局的关键状态且不重复发放任务奖励。
- **Basic bugs**: 继续后时间或资源被清空; 任务进度丢失; 继续后重复领取奖励
- **Trigger modes**: input, automatic

### `atom.G045_daily_street_lightlane.WB.TC2.13.C2.tiered.13` 

- **Requirement**: WASD按实际相机水平朝向移动，鼠标可正常改变第三人称观察方向。
- **Visible goal**: WASD移动方向随相机水平朝向变化，鼠标能改变第三人称观察方向。
- **Result frame (100%)**: 画面显示第三人称玩家在鼠标转向后朝相机相应水平方向移动。
- **Correct target**: 移动方向作用于玩家，并与当前相机水平朝向一致。
- **Necessary context**: 画面能辨认第三人称相机、玩家朝向及转向后的移动结果。
- **Basic function (50%)**: WASD按相机水平朝向移动，鼠标可连续改变第三人称观察方向。
- **Basic bugs**: 移动方向固定在世界坐标; 鼠标不能改变观察方向; 玩家与相机方向明显脱节
- **Trigger modes**: input, held

### `atom.G045_daily_street_lightlane.WB.TC2.14.C2.tiered.14` 

- **Requirement**: 原生持续跑步消耗耐力至零时转步行，仍保留基础操作能力。
- **Visible goal**: 持续跑步消耗耐力至零后，玩家自动转为步行并仍可操作。
- **Result frame (100%)**: 画面显示耐力耗尽、玩家处于步行状态且仍能继续移动。
- **Correct target**: 耐力耗尽效果作用于玩家的跑步状态。
- **Necessary context**: 画面能辨认耐力为空、步行状态和仍可移动的玩家。
- **Basic function (50%)**: 原生持续跑步会消耗耐力，耐力耗尽后限制为步行而不失去基础操作。
- **Basic bugs**: 耐力耗尽仍保持跑步; 耐力耗尽后无法移动; 耐力未耗尽就错误转为步行
- **Trigger modes**: held, automatic

### `atom.G045_daily_street_lightlane.WB.TC2.15.C2.tiered.15` 

- **Requirement**: 正常移动不能穿越主要建筑碰撞体，贴墙时镜头缩短距离避免长期进入不透明墙。
- **Visible goal**: 玩家正常移动不能穿过主要建筑，贴墙观察时镜头保持可见而不长期进入墙内。
- **Result frame (100%)**: 画面显示玩家停在建筑碰撞体前，贴近建筑时相机仍显示可辨认的玩家和场景。
- **Correct target**: 碰撞限制作用于玩家与主要建筑，镜头避让作用于相机。
- **Necessary context**: 画面能辨认主要建筑表面、玩家位置和贴墙时的相机视野。
- **Basic function (50%)**: 正常移动被主要建筑阻挡，贴墙时相机不会长期穿入不透明墙体。
- **Basic bugs**: 玩家可穿过主要建筑; 相机长期位于墙内; 碰撞使玩家失去基础移动
- **Trigger modes**: held, automatic

### `atom.G045_daily_street_lightlane.WB.TC2.16.C2.tiered.16` 

- **Requirement**: 通过交付声明的猫式捷径攀越后在地图记录该捷径，不允许任意墙面无条件攀越。
- **Visible goal**: 玩家通过声明的猫式捷径攀越后，该捷径被记录在地图中。
- **Result frame (100%)**: 画面显示玩家已通过指定猫式捷径到达另一侧，地图出现对应捷径记录。
- **Correct target**: 攀越和地图记录作用于交付声明的指定捷径。
- **Necessary context**: 画面能辨认指定捷径、玩家通过结果和地图记录标记。
- **Basic function (50%)**: 只有声明的猫式捷径能完成攀越并写入地图记录，任意墙面不能无条件攀越。
- **Basic bugs**: 任意墙面都可攀越; 未通过捷径就出现记录; 记录指向错误捷径
- **Trigger modes**: input, automatic, rejection

### `atom.G045_daily_street_lightlane.WB.TC2.17.C2.tiered.17` 

- **Requirement**: 原生回安全点或扶正自行车恢复可移动状态，但不发奖励、不清除债务或任务。
- **Visible goal**: 玩家通过原生回安全点或扶正自行车恢复可移动状态。
- **Result frame (100%)**: 画面显示玩家或自行车已恢复正常可移动状态，同时奖励、债务和任务状态未被清除。
- **Correct target**: 恢复操作作用于受困玩家或倒置自行车及其移动状态。
- **Necessary context**: 画面能辨认恢复前后的移动状态，以及保留的奖励、债务或任务信息。
- **Basic function (50%)**: 回安全点或扶正自行车能解除受困状态并恢复移动，不改变经济和任务结算。
- **Basic bugs**: 恢复后仍无法移动; 恢复错误对象; 恢复操作发放奖励或清除债务任务
- **Trigger modes**: input, automatic

### `atom.G045_daily_street_lightlane.WB.TC2.18.C2.tiered.18` 

- **Requirement**: 现金足够后通过原生交租交易扣款并减少实际欠租，单纯持有现金不能算已付。
- **Visible goal**: 现金足够时玩家通过原生交租交易付款，实际欠租减少。
- **Result frame (100%)**: 画面显示交租交易完成、现金扣除且欠租余额降低。
- **Correct target**: 扣款和欠租减少作用于玩家当前租金债务。
- **Necessary context**: 画面能辨认交租界面、付款结果、现金变化和欠租变化。
- **Basic function (50%)**: 持有现金不会自动算作付款，只有原生交租交易完成才减少实际欠租。
- **Basic bugs**: 持有现金即被视为已付款; 交易未完成却减少欠租; 扣款或欠租变化作用于错误账户
- **Trigger modes**: input, rejection

### `atom.G045_daily_street_lightlane.WB.TC2.19.C2.tiered.19` 

- **Requirement**: 原截止到期且现金不足时，仅房东信任至少二十可延期一次至第四天二十点。
- **Visible goal**: 截止到期且现金不足时，符合信任条件的玩家获得一次延期至指定后续期限。
- **Result frame (100%)**: 画面显示房租到期、现金不足、延期被接受并更新为新的截止状态。
- **Correct target**: 延期作用于玩家当前房租债务和期限。
- **Necessary context**: 画面能辨认到期状态、现金不足、房东信任条件和延期后的期限。
- **Basic function (50%)**: 满足最低房东信任时可获得一次延期；不满足条件时延期被拒绝。
- **Basic bugs**: 现金足够时错误触发延期条件; 低信任仍可延期; 延期可无限重复或作用于错误债务
- **Trigger modes**: input, rejection

### `atom.G045_daily_street_lightlane.WB.TC2.20.C2.tiered.20` 

- **Requirement**: 正常完成约定或归还借物积累信任后，在二十和四十阈值分别解锁对应帮助，不提前开放。
- **Visible goal**: 玩家通过完成约定或归还借物积累信任后，达到相应门槛才解锁对应帮助。
- **Result frame (100%)**: 画面显示信任提升并出现已解锁的帮助选项；未达到门槛的更高帮助仍未开放。
- **Correct target**: 信任和帮助解锁作用于玩家与对应关系方。
- **Necessary context**: 画面能辨认完成约定或归还结果、信任状态和帮助选项的解锁状态。
- **Basic function (50%)**: 正常完成约定或归还借物能积累信任，帮助按信任门槛逐步开放且不会提前开放。
- **Basic bugs**: 未完成约定即增加信任; 未达到门槛提前解锁帮助; 信任增加或帮助作用于错误对象
- **Trigger modes**: input, automatic, rejection

