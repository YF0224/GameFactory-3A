# Benchmark standard review — G035_rift_expedition

Directory: `/Users/yifanyang/Desktop/GameFactory-3A-game-bench/test_data/bench_standards/whitebox/stage1-criteria.v1/G035_rift_expedition`

Edit `<metric>.json` if needed, then approve with `python scripts_new/freeze_standards.py --stage x --approve G035_rift_expedition`.

## gameness (39 checks)

依据 requirement.txt 与全部给定 CHECKS 冻结共同标准，保留原 criterion id 及 layout、guidance、feedback 含义，不依赖候选实现。三个等级非累加：10% 为源代码中真实实现并接入玩法；50% 为真实触发且基本展示、反馈或指引有效，对象与核心信息正确，无已知基本功能错误，但预期传达结果尚未充分建立；100% 为交付游戏的真实原生结果帧及最少必要上下文，足以看懂本项结果或下一步。界面、布局和指引可随真实界面进入自动触发；清楚的单帧足够，仅在歧义、瞬态效果或因果需要时补充上下文。精确时序、空间运动、数值公式及穷尽分支边界在50%和100%均仅作诊断，不作为门槛；原文保留用于追溯。各项只判断其主要可视结果，不继承 Mechanic 结论，不以装饰或成功标签替代实际效果；拒绝须有操作被处理并拒绝的依据，静止画面不足。未覆盖为未知，不视作错误。未提供候选交付或运行证据，本标准不包含观察、分数或判定。

### `game.layout.hierarchy` 

- **Requirement**: 实际UI信息层级清楚，主要状态与次要信息可区分。
- **Visible goal**: 当前界面的主要状态与次要说明有清楚的视觉层级。
- **Result frame (100%)**: 真实游戏界面中，当前阶段的主要状态和可操作区域醒目，辅助说明能够与之区分。
- **Correct target**: 层级对应当前界面的任务，例如战斗中的玩家状态、手牌与敌方意图，或路线图中的当前位置与可选节点。
- **Necessary context**: 当前真实界面的一张清楚截图即可。
- **Basic function (50%)**: 战斗界面中玩家能辨认主要状态区、行动区和辅助说明。
- **Basic bugs**: 主要状态被装饰或次要说明压住而无法辨认; 主要操作与无关信息混杂，无法识别当前行动区
- **Trigger modes**: automatic, input

### `game.layout.readable` 

- **Requirement**: 实际UI文字、尺寸、对比度及布局可读，无明显遮挡/重叠。
- **Visible goal**: 当前界面的关键文字和控件清楚可读。
- **Result frame (100%)**: 游戏画面中的状态文字、选项和操作提示可辨认，没有妨碍理解的遮挡或重叠。
- **Correct target**: 可读内容属于当前实际界面的状态、目标和操作入口。
- **Necessary context**: 包含关键文字与控件的真实界面截图即可。
- **Basic function (50%)**: 事件面板上的选项及其说明能够直接阅读。
- **Basic bugs**: 关键文字被裁切或遮住到无法理解; 文字与背景无法区分; 控件重叠导致无法辨认操作对象
- **Trigger modes**: automatic, input

### `game.guidance.controls` 

- **Requirement**: 实际游戏展示或清楚传达必要操作方法。
- **Visible goal**: 玩家能从游戏画面了解当前必要的操作方法。
- **Result frame (100%)**: 当前界面显示与可操作对象对应的按键、鼠标动作或明确控件提示。
- **Correct target**: 提示正确对应选节点、出牌、事件选择、结束回合或存档交互等当前可用操作。
- **Necessary context**: 操作提示与其作用对象同屏即可；仅在提示含义不明时补充相关界面。
- **Basic function (50%)**: 战斗画面清楚说明如何出牌或结束回合。
- **Basic bugs**: 必要操作没有任何可理解的界面提示; 提示指向错误按键或错误对象; 关键操作提示被遮住到无法理解
- **Trigger modes**: automatic, input, held

### `expanded.G.s0008` 

- **Requirement**: 悬停卡牌上浮并放大 1.15 倍
- **Visible goal**: 悬停的手牌通过上浮和放大成为明确的当前查看对象。
- **Result frame (100%)**: 指针所在卡牌相对周围手牌突出，其名称和内容仍可辨认。
- **Correct target**: 突出的是实际悬停的那张手牌，卡牌身份与内容没有错配。
- **Necessary context**: 突出状态的一帧通常足够；仅在变化不清楚时补充普通手牌状态。
- **Basic function (50%)**: 悬停手牌后，该牌在手牌区明显突出。
- **Basic bugs**: 突出的是另一张卡牌; 突出后卡牌内容被遮住到无法理解
- **Trigger modes**: input, held

### `expanded.G.s0009` 

- **Requirement**: 拖到目标身上出牌，合法目标高亮
- **Visible goal**: 拖牌指向目标时，合法受牌对象被清楚标出。
- **Result frame (100%)**: 被拖动的卡牌与场上目标关系明确，可接受该牌的对象出现可辨认的高亮。
- **Correct target**: 高亮对象符合该牌的作用对象，攻击牌不会把无关对象标为受击目标。
- **Necessary context**: 拖牌与目标高亮同屏即可；目标关系有歧义时补充卡牌说明。
- **Basic function (50%)**: 拖动攻击牌指向敌人时，敌人出现目标高亮。
- **Basic bugs**: 高亮了错误对象; 目标标记与被拖动卡牌无关; 高亮遮住目标身份到无法辨认
- **Trigger modes**: input, held

### `expanded.G.s0010` 

- **Requirement**: 费用不足时卡牌左右抖动、费用数字红闪
- **Visible goal**: 费用不足的出牌尝试得到明确的费用拒绝反馈。
- **Result frame (100%)**: 尝试使用的卡牌出现警示，费用显示以醒目的错误状态说明不能支付。
- **Correct target**: 警示对应所尝试的卡牌及玩家当前费用，传达费用不足而非出牌成功。
- **Necessary context**: 应能看到被尝试的卡牌、费用及拒绝提示；单纯未变化的手牌不能证明拒绝。
- **Basic function (50%)**: 无法支付的卡牌出牌尝试显示费用警示并保留未打出状态。
- **Basic bugs**: 费用不足却显示出牌成功; 警示指向另一张卡牌或错误资源; 操作被拒但没有可理解的拒绝反馈
- **Trigger modes**: rejection, input

### `expanded.G.s0011` 

- **Requirement**: 抽牌从牌堆飞入手牌
- **Visible goal**: 抽到的卡牌以可辨认的入手表现连接牌堆与手牌。
- **Result frame (100%)**: 画面显示抽牌卡片从牌堆进入手牌的视觉联系，新牌可在手牌区辨认。
- **Correct target**: 入手表现对应实际抽到的卡牌，来源是抽牌堆，去向是玩家手牌。
- **Necessary context**: 入手画面能同时说明来源和去向时一帧即可；否则补充相邻的抽牌与入手画面。
- **Basic function (50%)**: 抽牌时可看见新卡进入玩家手牌区。
- **Basic bugs**: 卡牌被表现为进入错误区域; 只有飞行动画而手牌中没有对应新牌; 入手表现对应错误卡牌
- **Trigger modes**: automatic, input

### `expanded.G.s0012` 

- **Requirement**: 伤害、格挡、状态层变化都要飘字。
- **Visible goal**: 战斗状态变化通过对应对象的飘字清楚表达。
- **Result frame (100%)**: 发生伤害、获得格挡或状态层变化的对象旁出现可读飘字，能辨认变化种类。
- **Correct target**: 飘字对应实际变化的角色及状态，获得与损失的方向不混淆。
- **Necessary context**: 对象和飘字清楚同屏即可；仅在变化方向不明时补充相关状态显示。
- **Basic function (50%)**: 敌人受伤时，其旁出现伤害飘字。
- **Basic bugs**: 飘字出现在错误对象上; 伤害被显示为恢复或相反; 飘字不可读，无法理解变化种类
- **Trigger modes**: automatic, input

### `expanded.G.s0014` 

- **Requirement**: 事件【路线节点选定】实际发生时可视表现为【节点点亮＋镜头沿路线平移】，结束条件【平移完成】。仅评价可视投影，音频未评。未触发事件不能PASS。
- **Visible goal**: 路线选择反馈让玩家辨认已选节点及所走路线。
- **Result frame (100%)**: 所选节点被点亮，路线视图清楚展示该节点与选定路径的联系。
- **Correct target**: 点亮的是玩家选中的可选节点，所示路径通向该节点。
- **Necessary context**: 点亮节点与路径的一帧足够；若路线视图变化的关系不明，再补充选择前画面。
- **Basic function (50%)**: 选择路线节点后，地图明显标出该节点和所选路线。
- **Basic bugs**: 点亮了错误节点; 路线指示通向与选择不符的节点; 选中状态与未选状态无法辨认
- **Trigger modes**: input

### `expanded.G.s0015` 

- **Requirement**: 事件【赌矿成功】实际发生时可视表现为【晶体喷发＋矿入账飘字】，结束条件【1.2 秒结束】。仅评价可视投影，音频未评。未触发事件不能PASS。
- **Visible goal**: 赌矿成功以晶体和矿收益反馈清楚传达。
- **Result frame (100%)**: 赌矿事件画面出现晶体喷发表现及矿入账飘字，资源显示支持矿获得的含义。
- **Correct target**: 反馈对应裂缝赌矿的矿收益，不能混成受伤或其他事件奖励。
- **Necessary context**: 成功效果与矿收益同屏即可；若只有装饰效果，补充矿资源变化画面。
- **Basic function (50%)**: 赌矿成功画面显示晶体与矿获得反馈。
- **Basic bugs**: 成功反馈却把矿变化显示为损失; 反馈指向错误资源; 只有成功装饰，没有可辨认的矿入账结果
- **Trigger modes**: input, automatic

### `expanded.G.s0016` 

- **Requirement**: 事件【赌矿失败】实际发生时可视表现为【裂缝坍塌＋−20 HP 飘字】，结束条件【1.2 秒结束】。仅评价可视投影，音频未评。未触发事件不能PASS。
- **Visible goal**: 赌矿失败以裂缝坍塌和玩家受伤反馈清楚传达。
- **Result frame (100%)**: 赌矿事件显示裂缝坍塌意象及玩家生命损失飘字，玩家状态呈现受伤结果。
- **Correct target**: 生命损失属于勘探员，不能错误显示为敌人受伤或矿收益。
- **Necessary context**: 失败表现与生命损失清楚同屏即可；受伤关系不明时补充玩家状态变化画面。
- **Basic function (50%)**: 赌矿失败画面清楚显示玩家损失生命。
- **Basic bugs**: 失败显示为玩家恢复生命; 生命损失标在错误对象上; 仅有坍塌装饰而没有可辨认的受伤结果
- **Trigger modes**: input, automatic

### `expanded.G.s0017` 

- **Requirement**: 事件【交换成交】实际发生时可视表现为【稀有卡入组】，结束条件【入组完成】。仅评价可视投影，音频未评。未触发事件不能PASS。
- **Visible goal**: 交换成交后，获得的稀有卡被清楚呈现为加入牌组。
- **Result frame (100%)**: 交易结果或牌组展示中可以辨认新加入的强击或灼烧弹卡牌及其入组状态。
- **Correct target**: 入组对象是该次交换获得的稀有卡，不能用普通卡或仅供预览的商品代替。
- **Necessary context**: 可辨认入组结果的一帧即可；商品预览与已拥有状态不明时补充牌组展示。
- **Basic function (50%)**: 交换结果显示所得稀有卡已出现在玩家牌组中。
- **Basic bugs**: 显示加入了错误卡牌; 只有成交标签而无可辨认的入组结果; 商品预览被误显示为玩家已拥有
- **Trigger modes**: input

### `expanded.G.s0018` 

- **Requirement**: 事件【补给污染生效】实际发生时可视表现为【紫雾附在 HUD 标记上（此后敌人带紫光）】，结束条件【挂载完成】。仅评价可视投影，音频未评。未触发事件不能PASS。
- **Visible goal**: 受损补给造成的污染以明确的状态标记呈现。
- **Result frame (100%)**: HUD 上出现附着紫雾的补给污染标记，玩家能辨认当前携带该状态。
- **Correct target**: 标记表示玩家接受补给后带来的敌方强化污染，不能显示为无关增益。
- **Necessary context**: 带可辨认污染含义的 HUD 一帧即可；紫雾含义不明时补充状态说明。
- **Basic function (50%)**: 接受受损补给后，HUD 可见补给污染标记。
- **Basic bugs**: 污染标记被标成玩家有利增益; 紫雾只作背景装饰，无法辨认污染状态; 标记指向错误状态
- **Trigger modes**: input, automatic

### `expanded.G.s0019` 

- **Requirement**: 事件【存档】实际发生时可视表现为【符文环旋转＋保存成功光圈】，结束条件【光圈结束】。仅评价可视投影，音频未评。未触发事件不能PASS。
- **Visible goal**: 存档石的保存反馈让玩家看懂本次存档已建立。
- **Result frame (100%)**: 存档石周围出现符文环或保存光圈，并有可辨认的已保存状态或存档记录。
- **Correct target**: 反馈对应当前节点的存档石与本次保存，不能将保存失败显示为成功。
- **Necessary context**: 保存效果与已保存信息同屏即可；只有光效时补充可见存档记录，不能仅凭装饰推定保存。
- **Basic function (50%)**: 与存档石交互后，可见保存光效和本次存档状态。
- **Basic bugs**: 未建立存档却显示保存成功; 反馈对应错误存档或错误节点; 只有无保存含义的装饰光圈
- **Trigger modes**: input

### `expanded.G.s0020` 

- **Requirement**: 事件【读档】实际发生时可视表现为【倒放式闪光】，结束条件【闪光结束】。仅评价可视投影，音频未评。未触发事件不能PASS。
- **Visible goal**: 读档以回溯闪光和恢复后的游戏画面传达返回存档状态。
- **Result frame (100%)**: 读档画面出现可辨认的回溯闪光，恢复的节点与 HUD 状态可见。
- **Correct target**: 恢复画面对应所读取的存档，而非新开局或无关场景。
- **Necessary context**: 闪光含义及恢复对象清楚时使用结果帧；存在歧义时补充存档状态与恢复画面对照。
- **Basic function (50%)**: 读取已有存档后，可见回溯反馈及对应的恢复画面。
- **Basic bugs**: 闪光后显示错误存档场景; 只有读档装饰而没有可辨认的恢复结果; 恢复画面被错误标为新开局
- **Trigger modes**: input

### `expanded.G.s0021` 

- **Requirement**: 事件【出牌】实际发生时可视表现为【卡牌落位＋目标高亮】，结束条件【结算完成】。仅评价可视投影，音频未评。未触发事件不能PASS。
- **Visible goal**: 出牌反馈清楚连接已打出的卡牌和受牌目标。
- **Result frame (100%)**: 打出的卡牌有落位表现，相关目标被高亮，玩家能看懂该牌作用于谁。
- **Correct target**: 落位卡牌与目标对应实际出牌，卡牌身份及受牌对象不混淆。
- **Necessary context**: 卡牌与目标关系明确的一帧即可；手牌与出牌状态不明时补充出牌前画面。
- **Basic function (50%)**: 打出攻击牌时，该牌落位且对应敌人高亮。
- **Basic bugs**: 高亮目标与出牌对象不符; 落位的是另一张卡牌; 未被接受的操作却呈现成功出牌反馈
- **Trigger modes**: input

### `expanded.G.s0022` 

- **Requirement**: 事件【攻击命中（打击/强击）】实际发生时可视表现为【刀光/冲击波＋伤害飘字（强击并震屏）】，结束条件【0.3 秒结束】。仅评价可视投影，音频未评。未触发事件不能PASS。
- **Visible goal**: 打击或强击命中时，受击敌人和伤害反馈清楚可辨。
- **Result frame (100%)**: 受击敌人处出现刀光或冲击波及伤害飘字，画面明确表达攻击命中。
- **Correct target**: 命中表现与伤害飘字对应本次攻击的敌人，表达伤害而非治疗。
- **Necessary context**: 命中特效与受击对象清楚同屏即可；仅在攻击来源有歧义时补充出牌画面。
- **Basic function (50%)**: 打击命中敌人时显示该敌人的命中特效和伤害飘字。
- **Basic bugs**: 命中特效或飘字落在错误对象上; 攻击伤害显示为治疗; 仅有无目标装饰，无法辨认命中结果
- **Trigger modes**: input, automatic

### `expanded.G.s0023` 

- **Requirement**: 事件【蓄能】实际发生时可视表现为【红色气场】，结束条件【0.5 秒结束】。仅评价可视投影，音频未评。未触发事件不能PASS。
- **Visible goal**: 蓄能反馈让玩家辨认勘探员获得了力量强化。
- **Result frame (100%)**: 勘探员周围出现红色气场，并能从状态文字或标记辨认蓄能强化。
- **Correct target**: 气场属于使用蓄能的勘探员，含义是力量增强而非受伤或敌方强化。
- **Necessary context**: 红色气场与强化含义清楚同屏即可；含义不明时补充蓄能卡或状态说明。
- **Basic function (50%)**: 使用蓄能后，勘探员呈现可辨认的红色强化气场。
- **Basic bugs**: 气场出现在错误角色上; 蓄能被显示为负面伤害状态; 气场与任何蓄能状态都没有可辨认联系
- **Trigger modes**: input

### `expanded.G.s0024` 

- **Requirement**: 事件【获得格挡】实际发生时可视表现为【护盾泡】，结束条件【0.3 秒结束】。仅评价可视投影，音频未评。未触发事件不能PASS。
- **Visible goal**: 获得格挡时，护盾表现明确指出被保护的角色。
- **Result frame (100%)**: 获得格挡的角色周围出现护盾泡，相关状态可辨认为防护。
- **Correct target**: 护盾属于实际获得格挡的对象，不能将攻击或受伤表现成获得格挡。
- **Necessary context**: 护盾及其所属角色清楚的一帧即可；效果含义不明时补充格挡状态显示。
- **Basic function (50%)**: 使用防御牌后，勘探员出现可辨认的护盾泡。
- **Basic bugs**: 护盾出现在错误对象上; 没有格挡结果却显示获得格挡; 护盾含义与画面中的伤害状态混淆
- **Trigger modes**: input, automatic

### `expanded.G.s0025` 

- **Requirement**: 事件【中毒结算】实际发生时可视表现为【绿色气泡跳伤】，结束条件【跳伤结束】。仅评价可视投影，音频未评。未触发事件不能PASS。
- **Visible goal**: 中毒结算以绿色气泡和伤害反馈指明受毒伤对象。
- **Result frame (100%)**: 中毒对象处出现绿色气泡与伤害飘字，玩家能辨认这是中毒造成的损伤。
- **Correct target**: 反馈对应携带中毒的对象，伤害含义与其生命状态一致。
- **Necessary context**: 中毒标记、对象及跳伤关系清楚时一帧即可；来源不明时补充状态说明。
- **Basic function (50%)**: 中毒敌人结算毒伤时出现绿色气泡与伤害反馈。
- **Basic bugs**: 毒伤反馈出现在未中毒的错误对象上; 中毒损伤显示为恢复; 只有绿色装饰，无法辨认毒伤结果
- **Trigger modes**: automatic

### `expanded.G.s0026` 

- **Requirement**: 事件【首领攻击】实际发生时可视表现为【冲击波＋0.2 秒震屏＋0.08 秒顿帧】，结束条件【0.3 秒结束】。仅评价可视投影，音频未评。未触发事件不能PASS。
- **Visible goal**: 首领攻击以清楚的冲击表现传达攻击来源及受击方向。
- **Result frame (100%)**: 核心巨兽攻击画面中出现冲击波，玩家能辨认攻击来自首领并指向勘探员。
- **Correct target**: 冲击表现属于首领的攻击，不能混成玩家攻击或首领防御。
- **Necessary context**: 首领、冲击波及受击对象关系清楚的一帧即可；来源有歧义时补充相邻攻击画面。
- **Basic function (50%)**: 首领攻击勘探员时显示可辨认的冲击波。
- **Basic bugs**: 攻击来源被表现为错误角色; 冲击波指向与实际攻击无关的对象; 首领防御被误显示为攻击命中
- **Trigger modes**: automatic

### `expanded.G.s0027` 

- **Requirement**: 事件【胜负结算】实际发生时可视表现为【全屏特效（双结局意象见 W04）】，结束条件【进入结算面板】。仅评价可视投影，音频未评。未触发事件不能PASS。
- **Visible goal**: 终局演出清楚表达本局胜利或失败及相应结局意象。
- **Result frame (100%)**: 终局画面通过全屏表现和结算信息传达本局结果，所示意象能辨认为带回晶体、紫雾随行或信号中断。
- **Correct target**: 演出与本局结果相符，胜利结局意象对应是否携带补给污染，失败不显示为胜利。
- **Necessary context**: 结局意象与结果明确的一帧即可；结果或污染对应关系不明时补充结算面板或污染标记。
- **Basic function (50%)**: 真实终局画面展示可辨认的结果意象并明确本局胜负。
- **Basic bugs**: 胜利与失败含义反转; 结局意象与可见污染状态相反; 只有通用装饰而无法理解本局结果
- **Trigger modes**: automatic

### `expanded.G.s0037` 

- **Requirement**: - F10 前端界面：标题（开始/设置/退出，含 seed 显示与输入）→ 路线图界面（当前层/开放状态/已选路径/节点标签）→ 事件面板（选项 1–4）→ 战斗 HUD（HP/费用/牌堆计数/意图栏/污染标记，见 I06）→ 暂停面板（继续/重开/返回/设置）→ 奖励面板 → 结算面板（胜利显示路线选择/构筑终态/剩余 HP 与矿
- **Visible goal**: 当前流程界面以匹配其用途的面板结构呈现必要信息和入口。
- **Result frame (100%)**: 当前真实界面可辨认为标题、路线、事件、战斗、暂停、奖励或结算面板，内容组织让玩家知道所处阶段。
- **Correct target**: 所展示面板包含与其角色对应的核心内容，例如路线选择信息、战斗状态，或胜利结算中的路线与构筑摘要。
- **Necessary context**: 当前面板的一张完整截图即可，不要求以全部流程截图作为同一结果帧的附加门槛。
- **Basic function (50%)**: 路线图面板清楚呈现当前位置、节点标签与可选路线。
- **Basic bugs**: 面板内容与当前阶段明显不符; 核心信息缺失导致无法理解该面板用途; 主要入口被遮住到无法辨认
- **Trigger modes**: automatic, input

### `expanded.G.s0038` 

- **Requirement**: 失败注明倒在哪一节点
- **Visible goal**: 失败结算清楚注明勘探员倒下的节点。
- **Result frame (100%)**: 失败面板上显示可辨认的失败节点名称或地图位置标识。
- **Correct target**: 所注明节点对应本局发生失败的位置，不能显示为其他节点或胜利终点。
- **Necessary context**: 失败面板已明确节点时一帧即可；节点对应关系有歧义时补充失败地点画面。
- **Basic function (50%)**: 失败结算中的节点说明让玩家知道倒在哪里。
- **Basic bugs**: 注明错误失败节点; 仅显示失败而完全无法辨认地点; 节点文字被遮住到无法理解
- **Trigger modes**: automatic

### `expanded.G.s0039` 

- **Requirement**: Enter 重开）
- **Visible goal**: 结算界面清楚展示 Enter 重开的操作入口。
- **Result frame (100%)**: 结算面板上有可读的 Enter 重开提示，玩家能辨认如何开始新一局。
- **Correct target**: 提示对应结算后的重开操作，不能将返回菜单或继续旧局误标为重开。
- **Necessary context**: 包含结算状态和重开提示的一帧即可。
- **Basic function (50%)**: 玩家在结算面板能直接读到 Enter 重开提示。
- **Basic bugs**: 重开提示标注错误按键; 提示把其他操作标成重开; 重开入口被遮住到无法辨认
- **Trigger modes**: automatic

### `expanded.G.s0040` 

- **Requirement**: 关键状态图标＋文字并用
- **Visible goal**: 关键状态通过图标与文字共同表达含义。
- **Result frame (100%)**: 关键状态区中的图标有对应文字标识，玩家不必仅凭颜色猜测状态。
- **Correct target**: 图标和文字指向同一状态，例如生命、矿、格挡或补给污染。
- **Necessary context**: 显示关键状态图标及文字的一帧即可。
- **Basic function (50%)**: 补给污染图标旁有可读的状态名称或说明。
- **Basic bugs**: 图标与文字表达不同状态; 关键状态只有无法解释的颜色标记; 状态文字不可读
- **Trigger modes**: automatic, input

### `expanded.G.s0041` 

- **Requirement**: 窗口失焦自动暂停。
- **Visible goal**: 窗口失焦后，游戏画面清楚显示暂停状态。
- **Result frame (100%)**: 失焦的游戏窗口内可见暂停面板或明确的暂停标识。
- **Correct target**: 暂停显示属于当前游戏阶段，不能误呈现为失败、结算或仍可操作的正常战斗。
- **Necessary context**: 需有窗口失焦与暂停显示的最少可见关联；单纯不变化的游戏画面不能证明暂停。
- **Basic function (50%)**: 游戏窗口失焦后出现清楚的暂停界面。
- **Basic bugs**: 失焦后仍明确显示为进行中的可操作界面; 把失焦显示成失败结算; 暂停标识被遮住到无法辨认
- **Trigger modes**: automatic

### `expanded.G.s0001` 

- **Requirement**: - I06 UI 必须显示的状态：路线图当前层（含第 2 层开放状态）、矿、HP、牌组计数、敌方增益标记须常驻显示
- **Visible goal**: HUD 持续提供理解当前勘探状态所需的核心信息。
- **Result frame (100%)**: 当前玩法画面中可辨认路线层与开放状态、矿、生命、牌组计数和敌方增益状态。
- **Correct target**: 状态标签指向玩家当前资源、当前路线和实际敌方增益，不混淆手牌与牌组或玩家与敌人。
- **Necessary context**: 显示核心状态的真实界面一帧即可；图标含义不明时补充展开说明。
- **Basic function (50%)**: 路线界面中的 HUD 让玩家读懂当前资源与路线开放情况。
- **Basic bugs**: 核心资源标签对应错误对象; 开放与锁定状态表达相反; 关键状态缺失或不可读到无法使用
- **Trigger modes**: automatic

### `expanded.G.s0003` 

- **Requirement**: - L03 目标物/交互物/场景/UI 对象：本 spec §3–§7 引用的界面元素（菜单/HUD/结算面板）与交互物逐类存在且运行时可进入
- **Visible goal**: 当前节点的必要界面或交互物在真实游戏画面中可辨认。
- **Result frame (100%)**: 当前场景显示与阶段对应的菜单、HUD、结算面板或节点交互物，并清楚呈现其用途。
- **Correct target**: 画面中的对象属于需求所述勘探流程，例如事件节点的选项面板或节点完成后的存档石。
- **Necessary context**: 当前真实场景与目标对象同屏即可；用途不明时补充其交互面板。
- **Basic function (50%)**: 节点完成后的场景中可辨认存档石及其交互入口。
- **Basic bugs**: 当前节点展示了无关的交互对象; 必要对象被遮住到无法辨认; 只有装饰替身，无法识别应有的界面或交互用途
- **Trigger modes**: automatic, input

### `expanded.G.s0004` 

- **Requirement**: 数量与属性以对应 G·M 条目为准。
- **Visible goal**: 当前对象的可见身份和核心属性表达与其玩法角色相符。
- **Result frame (100%)**: 卡牌、敌人或路线节点的名称、类型和属性说明能让玩家认出其对应角色。
- **Correct target**: 可见内容遵循需求中的对象语义，例如攻击牌表达攻击，防御牌表达格挡，首领具有可辨认的首领身份。
- **Necessary context**: 对象与其属性说明同屏即可；无法从外观确定身份时补充标签或详情。
- **Basic function (50%)**: 防御卡的名称和说明清楚表达获得格挡。
- **Basic bugs**: 对象名称与所示属性明显错配; 攻击与防御等核心作用被颠倒; 对象身份及核心属性均无法辨认
- **Trigger modes**: automatic, input, held

### `expanded.G.s0002` 

- **Requirement**: - L01 生成对象：路线图与节点图标、**卡牌 6 种（打击/防御/强击/护壁/蓄能/灼烧弹）**、敌人 3 型（外缘/精英/首领，原创造型）、勘探员角色、事件面板、存档石、HUD（矿/HP/牌组/标记）。
- **Visible goal**: 游戏对象以可辨认的视觉身份呈现其在裂谷勘探中的角色。
- **Result frame (100%)**: 当前画面中的路线节点、卡牌、角色、敌人或事件对象具有可识别外观与必要标签。
- **Correct target**: 可见对象对应需求中的勘探员、裂谷敌人、命名卡牌、存档石及相关界面，不以无关装饰混充。
- **Necessary context**: 展示当前对象身份的真实游戏帧即可；外观有歧义时补充名称或详情。
- **Basic function (50%)**: 战斗画面能区分勘探员、敌人和玩家手牌。
- **Basic bugs**: 玩家与敌人的身份混淆; 卡牌标签与对象身份错配; 必要对象仅有无法辨认的占位表现
- **Trigger modes**: automatic, input

### `expanded.G.s0046` 

- **Requirement**: 界面支持玩家判断当前资源和行动条件，并明确传达无法执行的原因。
- **Visible goal**: 界面让玩家理解当前行动的资源条件及不可用原因。
- **Result frame (100%)**: 相关选项旁显示所需资源与当前资源，不能执行时有明确的不足或受限说明。
- **Correct target**: 条件说明对应正在考虑的操作和正确资源，例如矿不足不能支付营地补给。
- **Necessary context**: 操作选项、资源及条件说明同屏即可；若依靠拒绝反馈，需有该操作被处理的可见提示。
- **Basic function (50%)**: 营地选项清楚显示支付条件，并说明资源不足导致不可用。
- **Basic bugs**: 不可用原因指向错误资源; 提示可执行但控件实际上不可用; 拒绝后没有可理解的原因说明
- **Trigger modes**: automatic, input, rejection

### `expanded.G.s0042` 

- **Requirement**: 玩家能在操作前知道当前目标及可执行的下一步，不依赖阅读工程文档。
- **Visible goal**: 玩家在行动前能从画面理解当前目标和可执行的下一步。
- **Result frame (100%)**: 当前界面显示阶段目标，并以可辨认的节点、选项或操作入口指向下一步。
- **Correct target**: 目标与当前勘探阶段相符，例如选路线、处理事件或应对战斗，不要求玩家查阅工程文档。
- **Necessary context**: 阶段目标与相关行动入口同屏即可。
- **Basic function (50%)**: 路线图说明当前需要选择分支，并清楚标出可选节点。
- **Basic bugs**: 目标说明属于错误阶段; 界面没有可辨认的下一步入口; 把锁定操作提示为当前可执行动作
- **Trigger modes**: automatic, input

### `expanded.G.s0044` 

- **Requirement**: 目标进度、阶段变化与终局结果向玩家明确呈现。
- **Visible goal**: 阶段结果反馈让玩家看懂当前勘探进展。
- **Result frame (100%)**: 阶段完成或终局画面清楚标明刚取得的进展及当前所处阶段。
- **Correct target**: 进度与实际路线阶段相符，普通节点完成不被误标为整局胜利。
- **Necessary context**: 进度或结果明确的一帧即可；阶段关系有歧义时补充相邻路线画面。
- **Basic function (50%)**: 节点完成后的路线图清楚标出已走路径和当前阶段。
- **Basic bugs**: 普通节点完成被显示为整局胜利; 进度指向错误路线阶段; 结果文字相互矛盾而无法理解进展
- **Trigger modes**: automatic, input

### `expanded.G.s0049` 

- **Requirement**: 长期后果、跨阶段保留或失去的状态有可观察的解释；仅在需求存在时判断。
- **Visible goal**: 界面解释会延续到后续阶段的关键后果。
- **Result frame (100%)**: 补给污染的状态说明清楚表达其会影响后续战斗，玩家能理解该状态的持续意义。
- **Correct target**: 说明将受损补给与后续敌方强化关联，不能误称为仅当前画面装饰或玩家增益。
- **Necessary context**: 状态标记与后果说明同屏即可；说明只在事件面板出现时使用该面板。
- **Basic function (50%)**: 受损补给说明告知玩家，接受补给会让后续敌人更强。
- **Basic bugs**: 把持续污染解释为玩家有利状态; 错误告知污染在离开节点后消失; 只有无解释标记，无法理解跨阶段后果
- **Trigger modes**: automatic, input, held

### `expanded.G.s0045` 

- **Requirement**: 冻结玩法中的资源/路线/时机选择有可理解的代价与收益提示。
- **Visible goal**: 选择界面在玩家决定前说明主要代价与收益。
- **Result frame (100%)**: 路线节点或事件选项旁有可读的风险、支付资源和预期收益提示。
- **Correct target**: 说明对应当前选项，例如交换消耗矿或生命并获得稀有卡，不颠倒付出与获得。
- **Necessary context**: 待选对象与代价收益说明同屏即可。
- **Basic function (50%)**: 交换商选项清楚展示支付资源与可获得的稀有卡。
- **Basic bugs**: 代价和收益方向颠倒; 说明属于另一选项; 关键风险被表达为无代价收益
- **Trigger modes**: automatic, input, held

### `expanded.G.s0047` 

- **Requirement**: 危险预警与恢复入口可发现，玩家能据此调整操作。
- **Visible goal**: 玩家能发现危险提示及适用的恢复入口。
- **Result frame (100%)**: 危险相关界面清楚展示敌方意图或风险说明，并让适用的存读档、暂停或重开入口易于辨认。
- **Correct target**: 预警对应当前威胁，恢复入口名称准确，不把不可用的恢复方式描述为可用。
- **Necessary context**: 当前危险或恢复界面已明确用途时一帧即可；入口含义不明时补充相关面板。
- **Basic function (50%)**: 失败后的界面清楚给出可理解的重开或读档恢复入口。
- **Basic bugs**: 危险提示指向错误敌人或错误意图; 恢复入口被遮住到无法发现; 不可用的恢复方式被明确标为可用
- **Trigger modes**: automatic, input

### `expanded.G.s0043` 

- **Requirement**: 核心操作产生的成功、失败或拒绝反馈可被区分；此处不重复计算 C2 数值正确性。
- **Visible goal**: 核心操作的反馈清楚表达本次操作是成功、失败还是被拒绝。
- **Result frame (100%)**: 当前操作结果有可读提示或明确的对象状态，玩家不会把拒绝误认为成功。
- **Correct target**: 反馈对应本次操作和受影响对象，表达结果类别，不重复要求精确数值核算。
- **Necessary context**: 结果含义清楚的一帧即可；拒绝需有操作被处理的明确反馈，不能仅用未变化画面。
- **Basic function (50%)**: 资源不足的操作显示明确拒绝原因，与正常成功反馈可区分。
- **Basic bugs**: 拒绝被显示为成功; 成功操作被显示为失败; 提示与本次操作或对象无关
- **Trigger modes**: input, automatic, rejection

### `expanded.G.s0048` 

- **Requirement**: 并发单位或多个事件同时发生时，关键反馈仍能对应到正确对象。
- **Visible goal**: 多个对象同屏时，关键反馈仍能清楚归属于正确对象。
- **Result frame (100%)**: 包含多个敌人或反馈的画面中，伤害、状态或目标标记与各自对象有明确视觉联系。
- **Correct target**: 被攻击或状态变化的对象与其反馈对应，不把其他敌人的反馈归给当前目标。
- **Necessary context**: 对象及关联反馈同屏即可；归属仍不明时补充目标选中或相邻结果画面。
- **Basic function (50%)**: 多敌人战斗中，受击敌人的伤害飘字清楚归属于该敌人。
- **Basic bugs**: 反馈标在错误对象上; 重叠遮挡导致无法辨认反馈归属; 不同对象的目标或状态标记明显错配
- **Trigger modes**: input, automatic

## mechanic (20 checks)

This freezes a source-only outcome_frame_v1 standard for the 20 G035 Rift Expedition mechanic checks. It is based only on requirement.txt and the CHECKS list. No baseline project or candidate deliveries were supplied, and no runtime frames or verdicts were used. Each check names one visible principal outcome, the correct target, the context needed to remove ambiguity, one representative basic function and up to 3 key bugs. Four kinds of detail stay diagnostic only, at both 50% and 100%: exact timing, exact space or motion, exact numbers or formulas (wager or reward amounts, damage, block, heal, caps, poison values) and exhaustive coverage of branches and edge cases.

### `atom.G035_rift_expedition.WB.TC2.01.C2.tiered.01` 

- **Requirement**: 不同分支 → 不同风险/收益组合；已选路径记录落盘；第 2 层开放状态更新
- **Visible goal**: Choosing a first-layer branch on the route map records that branch as the chosen path and updates which second-layer branches are shown as open or locked.
- **Result frame (100%)**: The route map after a first-layer choice. The chosen node is marked as taken in the path record, and the second-layer branches show open or locked states that match that choice.
- **Correct target**: The first-layer branch node the player clicked, and the second-layer branches whose open or locked state depends on it.
- **Necessary context**: The first-layer branches with their visible risk/reward labels before the choice, so the frame shows which branch was picked.
- **Basic function (50%)**: Clicking an available first-layer node selects it, records it on the map, enters that node's event or battle, and reveals the matching second-layer availability.
- **Basic bugs**: The second-layer open/locked state ignores the first-layer choice, or all branches stay identical whatever was chosen; The chosen path is not recorded and disappears on the map after the node; A different node than the one clicked is selected or entered
- **Trigger modes**: input

### `atom.G035_rift_expedition.WB.TC2.02.C2.tiered.02` 

- **Requirement**: 点击未解锁分支被拒且无副作用
- **Visible goal**: Clicking a second-layer branch that is shown as locked is refused: no node is entered and the run state is unchanged.
- **Result frame (100%)**: The route map right after clicking a locked branch. The branch stays locked, the player stays on the map (perhaps with refusal feedback), and HP, ore, deck count and the path record are unchanged.
- **Correct target**: A second-layer branch that is locked because of the first-layer choice.
- **Necessary context**: The branch is visibly locked before the click, and HUD values are visible before and after, so the click is shown to have happened and to have been refused.
- **Basic function (50%)**: The route map enforces the unlock rules, so only branches opened by the first-layer choice can be entered.
- **Basic bugs**: The locked branch is entered or its event/battle starts; Resources, deck or path record change after the refused click; The click counts as a selection and blocks the legal branches afterwards
- **Trigger modes**: rejection, input

### `atom.G035_rift_expedition.WB.TC2.03.C2.tiered.03` 

- **Requirement**: 原生赌矿实际押二十矿，按冻结随机序列给出六十矿收益或二十HP损失。
- **Visible goal**: Taking the gamble at the rift-crack event really wagers ore and resolves to one of two outcomes: an ore payout or an HP loss.
- **Result frame (100%)**: The gamble event result. The HUD shows the wagered ore spent, and either a net ore gain from the payout (crystal-eruption style feedback) or reduced player HP (collapse style feedback).
- **Correct target**: The player's ore and HP in the current run.
- **Necessary context**: The ore and HP values before choosing the gamble option, so the change can be attributed to the gamble.
- **Basic function (50%)**: Choosing the gamble option in the gamble event changes the player's resources according to a win or loss result.
- **Basic bugs**: No ore is deducted for the wager, yet a payout is given; Both or neither outcome is applied, such as losing HP and also gaining the payout; The result changes the wrong resource, or the enemy or another entity, instead of the player
- **Trigger modes**: input

### `atom.G035_rift_expedition.WB.TC2.04.C2.tiered.04` 

- **Requirement**: 矿不足时押注/交换/营地被拒且无副作用
- **Visible goal**: When the player lacks enough ore, an ore-costing action (gamble wager, ore trade or camp heal) is refused and nothing changes.
- **Result frame (100%)**: The event or camp panel after selecting the ore-costing option with too little ore. The option is shown as rejected or disabled, and ore, HP and deck count are unchanged, with no card or heal granted.
- **Correct target**: The ore-costing option of the gamble, trader or camp node, and the player's resources.
- **Necessary context**: The HUD shows the ore balance below the option's cost before the attempt, plus evidence that the option was actually chosen.
- **Basic function (50%)**: Ore-costing event options check the ore balance before applying any effect.
- **Basic bugs**: The effect (payout, rare card or heal) is granted despite too little ore; Ore goes negative or HP or the deck changes after the refusal; The refusal blocks the rest of the event, so the player cannot skip or continue
- **Trigger modes**: rejection, input

### `atom.G035_rift_expedition.WB.TC2.05.C2.tiered.05` 

- **Requirement**: 普通卡二选一/稀有卡入组；构筑叠加 → 战力曲线变化
- **Visible goal**: After a battle win, the picked reward card (one of two common cards, or a rare card) is added to the deck, and the build or power display reflects it.
- **Result frame (100%)**: The reward or deck view after picking. The chosen card is in the deck, the deck count has gone up, and the build or power panel shows the updated build.
- **Correct target**: The player's deck and the specific card that was picked.
- **Necessary context**: The reward panel showing the offered choices and which one was picked, and the deck count before.
- **Basic function (50%)**: The reward panel offers cards after a battle win, and the selected card is added to the persistent deck.
- **Basic bugs**: A different card than the one picked is added, or both common options are added; The deck count does not change, or the card vanishes at the next node; A rare card is offered from a source that should only give common cards
- **Trigger modes**: input

### `atom.G035_rift_expedition.WB.TC2.06.C2.tiered.06` 

- **Requirement**: 节点保存后改变路线、牌组和资源，读档恢复快照及随机游标。
- **Visible goal**: Loading the save-stone save brings back the saved route, deck and resources after they were changed following the save.
- **Result frame (100%)**: The game right after loading. The route record, deck count, HP and ore shown match the values at the save stone, not the changed values from after the save.
- **Correct target**: The player's full run state: route record, deck, ore, HP and enemy-buff marker.
- **Necessary context**: The state shown at the save stone, and a later state that differs from it, so the restore is clearly caused by the load.
- **Basic function (50%)**: Interacting with the save stone after a node saves the run, and the load entry restores that snapshot.
- **Basic bugs**: Loading keeps the changed state, or restores only part of it (for example HP but not the deck); Loading restores a different or older snapshot than the latest save; A gamble after loading gives a different result than it did after the original save (random state not restored)
- **Trigger modes**: input

### `atom.G035_rift_expedition.WB.TC2.07.C2.tiered.07` 

- **Requirement**: 战斗中不可存档；无存档时读档入口无效
- **Visible goal**: Saving or loading in an illegal situation is refused: saving during battle, or loading when no save exists, does nothing.
- **Result frame (100%)**: The game after the illegal attempt. Either the battle continues with no save created, or the load entry with no save is unavailable or refused and the current state is unchanged.
- **Correct target**: The save or load entry used in the illegal situation.
- **Necessary context**: The frame must show the illegal condition (an active battle screen, or no existing save) and that the save or load attempt was made.
- **Basic function (50%)**: Save and load are available only at legal points (the save stone after node completion, with an existing save for loading).
- **Basic bugs**: A save is created mid-battle and can later be loaded; Loading with no save resets or corrupts the current run, or goes to a blank state; The refused attempt changes HP, ore, deck or battle state
- **Trigger modes**: rejection, input

### `atom.G035_rift_expedition.WB.TC2.08.C2.tiered.08` 

- **Requirement**: 同 seed 路线图与事件序列一致；不同 seed 不同
- **Visible goal**: Starting a run with the same seed reproduces the same route map and event outcomes, while a different seed gives a different route map.
- **Result frame (100%)**: The route map of a run started with a shown seed. Its layout and branch labels match another run with the same seed, or visibly differ from a run with a different seed.
- **Correct target**: The route map layout, branch labels and event results of the run.
- **Necessary context**: The seed shown on the start screen for each run being compared, plus the compared map, since the claim is inherently comparative.
- **Basic function (50%)**: The start screen shows the seed and accepts a seed, and run generation uses it.
- **Basic bugs**: The same seed gives a different map or gamble results; A different seed gives exactly the same map every time (the seed is ignored); The seed shown does not match the seed actually used
- **Trigger modes**: input

### `atom.G035_rift_expedition.WB.TC2.09.C2.tiered.09` 

- **Requirement**: 暂停面板打开，冻结战斗与事件流程
- **Visible goal**: Pressing Esc during gameplay opens the pause panel and freezes the battle or event flow behind it.
- **Result frame (100%)**: The pause menu (continue, restart, return to menu) shown over a battle or event screen, with the underlying battle or event state not advancing.
- **Correct target**: The current gameplay phase (route map, event or battle) being paused.
- **Necessary context**: The gameplay screen just before Esc, so the pause is attributable and the underlying state can be seen not to change.
- **Basic function (50%)**: Esc toggles a pause panel that blocks gameplay input, and continue returns to the same phase.
- **Basic bugs**: Enemy turns, event results or card plays still happen while the panel is open; Gameplay input passes through the pause panel; Resuming loses or resets the phase state
- **Trigger modes**: input

### `atom.G035_rift_expedition.WB.TC2.10.C2.tiered.10` 

- **Requirement**: - V01 成功条件：击败路线终点首领 → 胜利结算（显示路线选择、构筑终态、剩余 HP 与矿）；结局按是否带「补给污染」二选一。
- **Visible goal**: Defeating the final boss leads to a victory settlement showing the route taken, the final build and the remaining HP and ore, with the ending that matches whether the supply-contamination marker is carried.
- **Result frame (100%)**: The victory settlement screen after the boss dies. It lists the chosen route, final deck, remaining HP and ore, and shows the ending (crystal returned, or purple mist following) that matches the run's contamination status.
- **Correct target**: The route's final boss and the run's victory result.
- **Necessary context**: The boss being defeated in battle just before, and the contamination marker state, so the ending can be checked.
- **Basic function (50%)**: Reducing the boss's HP to zero ends the battle and triggers the victory settlement.
- **Basic bugs**: Victory triggers without defeating the boss, or the boss's death does not end the run; The ending shown contradicts the contamination marker state; The settlement shows wrong or reset route, deck, HP or ore values
- **Trigger modes**: automatic, input

### `atom.G035_rift_expedition.WB.TC2.11.C2.tiered.11` 

- **Requirement**: - V02 失败条件：战斗中 HP 归零且未读档 → 失败结算（注明倒在哪一节点，即时判负）。
- **Visible goal**: When the player's HP reaches zero in battle without loading a save, the run ends immediately in a defeat settlement that names the node where the player fell.
- **Result frame (100%)**: The defeat settlement screen after HP hits zero, showing the failure message and the node where the player fell.
- **Correct target**: The player, and the battle node where HP reached zero.
- **Necessary context**: The battle where the player's HP reaches zero, so the defeat is attributable to that battle.
- **Basic function (50%)**: Player HP zero in battle is detected and triggers defeat.
- **Basic bugs**: The battle continues with HP at or below zero; The defeat screen names the wrong node or no node; Defeat triggers while HP is still above zero
- **Trigger modes**: automatic

### `atom.G035_rift_expedition.WB.TC2.12.C2.tiered.12` 

- **Requirement**: 原生重开清空本局路线、构筑和资源，回到初始局。
- **Visible goal**: Restarting clears the current run's route, build and resources and returns to a fresh initial run.
- **Result frame (100%)**: The game right after restart. A fresh first-layer route map with no path recorded, starting HP and ore, the starter deck count and no contamination marker.
- **Correct target**: The whole run state: route record, deck, ore, HP and markers.
- **Necessary context**: The progressed state before restart (changed deck, resources or route), so the reset is visible.
- **Basic function (50%)**: The restart entry in the pause or settlement screen starts a new run from initial values.
- **Basic bugs**: Cards, ore, HP or the contamination marker carry over into the new run; The route record or layer progress is not cleared; Restart produces a broken or empty initial state
- **Trigger modes**: input

### `atom.G035_rift_expedition.WB.TC2.13.C2.tiered.13` 

- **Requirement**: 正常进入新回合时费用恢复三、抽五张，不能超支打牌。
- **Visible goal**: At the start of each new player turn, energy refills to full and a new hand is drawn, and cards cannot be played beyond the available energy.
- **Result frame (100%)**: The battle HUD at the start of a new turn, showing refilled energy and a freshly drawn hand after the previous turn's energy was spent.
- **Correct target**: The player's energy counter and hand in the current battle.
- **Necessary context**: The end of the previous turn, with energy spent, so the refill and redraw are attributable to the new turn.
- **Basic function (50%)**: Ending the turn, then the enemy acting, starts a new player turn with energy reset and cards drawn. Plays that cost more than the current energy are refused.
- **Basic bugs**: Energy is not refilled, or it accumulates beyond full across turns; No new cards are drawn at turn start; A card can be played with insufficient energy, driving energy negative
- **Trigger modes**: automatic, input, rejection

### `atom.G035_rift_expedition.WB.TC2.14.C2.tiered.14` 

- **Requirement**: 原生打一张一费打击实际扣一费并对合法敌人结算六点基础攻击伤害。
- **Visible goal**: Playing a Strike card spends its energy and deals attack damage to the targeted enemy.
- **Result frame (100%)**: The battle right after the Strike resolves. The energy counter has dropped, the card has left the hand, and the targeted enemy's HP has dropped, with hit feedback on that enemy.
- **Correct target**: The legal enemy the Strike was played on.
- **Necessary context**: The enemy HP and player energy before the play, and which enemy was targeted (important when there are 2 enemies).
- **Basic function (50%)**: Clicking or dragging a Strike onto an enemy plays the card, spending energy and applying damage.
- **Basic bugs**: Damage goes to the wrong enemy or to the player, or the enemy is healed; No energy is spent, or the card stays in hand and can be replayed for free; Damage is applied with no card played, or the card is consumed with no damage
- **Trigger modes**: input

### `atom.G035_rift_expedition.WB.TC2.15.C2.tiered.15` 

- **Requirement**: 原生打一张一费防御得到五点格挡，敌人攻击按真实格挡抵扣。
- **Visible goal**: Playing a Defend card gives the player block, and the enemy's next attack loses less HP because of that block.
- **Result frame (100%)**: The battle after the enemy attacks. The player's block is used up and the HP loss is smaller than the attack by the block amount, with block or shield feedback.
- **Correct target**: The player character's block and HP.
- **Necessary context**: The Defend play showing block gained, plus the enemy attack intent or value, so the reduced HP loss is attributable to block.
- **Basic function (50%)**: Playing Defend spends energy and adds a visible block value to the player.
- **Basic bugs**: Block is gained but the enemy attack still removes full HP; Block is given to the enemy instead of the player; Block is gained without spending energy or consuming the card
- **Trigger modes**: input, automatic

### `atom.G035_rift_expedition.WB.TC2.16.C2.tiered.16` 

- **Requirement**: 通过蓄能获得本回合力量后增加攻击伤害，回合结束力量清零。
- **Visible goal**: After playing Energize, the player's attack cards deal more damage that turn, and the strength buff is gone after the turn ends.
- **Result frame (100%)**: The battle after an attack played under the Energize buff. A strength indicator is on the player and the enemy loses more HP than a normal hit of that card. After the turn ends, the strength indicator is cleared.
- **Correct target**: The player's strength status and the attacked enemy's HP.
- **Necessary context**: The Energize play and its strength indicator before the attack, so the extra damage is attributable to it.
- **Basic function (50%)**: Playing Energize applies a temporary strength status to the player that adds to attack card damage.
- **Basic bugs**: Strength persists into the next turn or stacks permanently; Strength boosts the enemy, or reduces damage instead of increasing it; The strength indicator shows but attack damage is unchanged
- **Trigger modes**: input, automatic

### `atom.G035_rift_expedition.WB.TC2.17.C2.tiered.17` 

- **Requirement**: 中毒三层在回合结束实际造成三点伤害并递减为两层。
- **Visible goal**: A poisoned enemy takes poison damage at the end of the turn, and its poison stack count goes down by one.
- **Result frame (100%)**: The battle right after the end-of-turn poison tick. The poisoned enemy's HP has dropped with poison feedback, and its poison stack indicator shows one fewer stack.
- **Correct target**: The enemy carrying the poison status (for example from Burn Shell).
- **Necessary context**: The enemy's poison stacks and HP before the end of the turn, so the tick is attributable to poison.
- **Basic function (50%)**: Poison stacks on an enemy are resolved automatically at the end of the turn.
- **Basic bugs**: Poison deals no damage or never decreases; Poison damages the player or another enemy instead of the poisoned one; The poison stacks drop to zero immediately, or increase
- **Trigger modes**: automatic

### `atom.G035_rift_expedition.WB.TC2.18.C2.tiered.18` 

- **Requirement**: 已有十张牌时获得新卡须先合法弃一张后入组，不直接超过上限。
- **Visible goal**: When the deck is already full and a new card is gained, the player must discard a card first, and only then is the new card added, so the deck never goes over the cap.
- **Result frame (100%)**: The reward or deck screen after gaining a card with a full deck. A discard prompt is shown or completed, the discarded card is gone, the new card is present, and the deck count stays at the cap.
- **Correct target**: The player's deck, the discarded card and the newly gained card.
- **Necessary context**: The deck count at the cap before the gain, so the discard requirement is attributable.
- **Basic function (50%)**: Gaining a card checks the deck cap and asks for a discard when the deck is full.
- **Basic bugs**: The new card is added directly and the deck goes over the cap; The new card is lost without the player choosing a discard, or a different card than the chosen one is removed; The discard prompt cannot be completed, soft-locking the reward
- **Trigger modes**: input, rejection

### `atom.G035_rift_expedition.WB.TC2.19.C2.tiered.19` 

- **Requirement**: 选择免费受损补给点获得普通卡后，后续战斗敌方攻击增加二且跨节点保留。
- **Visible goal**: Taking the damaged supply point gives a free common card and applies the supply-contamination marker, which makes enemies in later battles hit harder and persists across nodes.
- **Result frame (100%)**: A later battle after the supply point. The contamination marker is still on the HUD and the enemy's attack (intent or damage taken) is higher than that enemy's normal attack.
- **Correct target**: Enemies in battles after the supply point, and the player's persistent contamination marker.
- **Necessary context**: The supply-point choice granting the card and marker, plus the enemy's normal attack value for comparison, so the increase is attributable to contamination.
- **Basic function (50%)**: Choosing the damaged supply point adds a common card to the deck and sets a visible contamination marker.
- **Basic bugs**: The marker appears but enemy attack is unchanged in later battles; The marker or attack increase is lost at the next node or the next layer; The increase is applied to the player's attacks instead of the enemies'
- **Trigger modes**: input, delayed

### `atom.G035_rift_expedition.WB.TC2.20.C2.tiered.20` 

- **Requirement**: 首领前营地正常消耗二十矿恢复十五HP并受HP上限约束，余额不足不免费治疗。
- **Visible goal**: Using the camp before the boss spends ore and restores the player's HP without going over max HP, and with too little ore no free heal is given.
- **Result frame (100%)**: The camp result. The HUD shows the ore reduced and the player's HP increased, but not above the max HP shown.
- **Correct target**: The player's ore and HP at the pre-boss camp node.
- **Necessary context**: The HP, max HP and ore before using the camp, so the heal and the cost are attributable.
- **Basic function (50%)**: The camp heal option checks the ore balance, deducts the cost and heals the player.
- **Basic bugs**: HP goes above max HP; The heal is given without deducting ore, or when ore is insufficient; Ore is deducted but HP does not increase
- **Trigger modes**: input, rejection

