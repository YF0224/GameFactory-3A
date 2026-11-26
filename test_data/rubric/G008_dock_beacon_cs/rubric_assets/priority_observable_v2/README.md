# G008_dock_beacon_cs — priority 资产需求 rubric 修订 v2

本目录是独立修订版；旧 `../rubric.json`、`../per_asset/` 及历史分数均保留。
游戏内索引：`../priority_rubric_current.json`。仅包含 priority gen 对应任务，不代表其他资产任务也已修订。
第一列保留可观察的主体、部件、形状、色彩、材质、相对布局、动作/事件及声音内容；精确坐标、尺寸、时长、速度、计数和技术参数只作来源/诊断。
已有逐资产文件的第二/三维原样保留；自然音效与T-pose补充的是此前缺失的rubric草稿，不是历史有效分数。
本版尚未逐项人工审核/最终冻结，也未自动切换生产 evaluator 或重新评测。采用新 schema，必须显式选择并适配，禁止混用旧分数。

| 类型 | 任务数 |
|---|---:|
| 3D Object | 9 |
| 3D Scene | 1 |
| Audio | 17 |
| CG Video | 4 |
| Motion | 7 |
| T-pose | 2 |

## 第一列逐任务预览

以下仅展示计分目标；完整原文、定性投影记录、排除项、判分锚点和第二/三维见对应 JSON。

### [G008_dock_beacon_cs_obj_001](G008_dock_beacon_cs_obj_001.json)

- **C001**：Attacker team operator in rain-soaked tactical gear
- **C002**：rust-orange container accents
- **C003**：compact plate carrier
- **C004**：hooded hardshell with beacon-cyan trim
- **C005**：readable silhouette for first-person and spectate views
- **C006**：single character

### [G008_dock_beacon_cs_obj_002](G008_dock_beacon_cs_obj_002.json)

- **C001**：Defender team operator in anchorage guard gear
- **C002**：rain-night blue and warning-yellow accents
- **C003**：heavier vest with mooring hooks
- **C004**：helmet with short visor
- **C005**：readable silhouette distinct from the attacker
- **C006**：single character

### [G008_dock_beacon_cs_obj_003](G008_dock_beacon_cs_obj_003.json)

- **C001**：Portable data-core beacon device
- **C002**：armored casing with a cyan indicator ring and keypad
- **C003**：mountable on objective pedestals
- **C004**：clearly readable interaction silhouette
- **C005**：single object

### [G008_dock_beacon_cs_obj_004](G008_dock_beacon_cs_obj_004.json)

- **C001**：Compact service pistol with rain-proof slide serrations
- **C002**：first-person usable weapon model
- **C003**：single object
- 审查提示：unresolved_spec_ref

### [G008_dock_beacon_cs_obj_005](G008_dock_beacon_cs_obj_005.json)

- **C001**：Short submachine gun with folding grip and suppressor mount
- **C002**：high-rate close-quarters weapon
- **C003**：single object
- 审查提示：unresolved_spec_ref

### [G008_dock_beacon_cs_obj_006](G008_dock_beacon_cs_obj_006.json)

- **C001**：Standard assault rifle with rail handguard and mid-length barrel
- **C002**：all-round weapon
- **C003**：single object
- 审查提示：unresolved_spec_ref

### [G008_dock_beacon_cs_obj_007](G008_dock_beacon_cs_obj_007.json)

- **C001**：Pump-action shotgun with breaching choke and wide heat guard
- **C002**：close-range heavy impact weapon
- **C003**：single object
- 审查提示：unresolved_spec_ref

### [G008_dock_beacon_cs_obj_008](G008_dock_beacon_cs_obj_008.json)

- **C001**：Long sniper rifle with mounted scope
- **C002**：bipod and rain-hooded lens
- **C003**：precision weapon with visible breath-sway when scoped
- **C004**：single object
- 审查提示：unresolved_spec_ref

### [G008_dock_beacon_cs_obj_009](G008_dock_beacon_cs_obj_009.json)

- **C001**：Belt-fed light machine gun with deployable bipod and carrying handle
- **C002**：sustained-fire weapon
- **C003**：single object
- 审查提示：unresolved_spec_ref

### [G008_scene_001](G008_scene_001.json)

- **C001**：Storm-night dockyard combat environment with separated attacker and defender yards
- **C002**：three objective yards
- **C003**：central connector
- **C004**：container push lanes
- **C005**：water culvert
- **C006**：wet steel and floodlights
- **C007**：one coherent scene
- **C008**：no split panels
- **C009**：no labels
- **C010**：no text
- **C011**：码头具有不同区域及连接通路
- **C012**：相邻目标区之间有横向支援连接，外围具有绕后水道
- **C013**：可见门、薄墙和不同材质区域；不验收破坏或穿透机制
- 审查提示：unresolved_spec_ref, no_literal_asset_mention_in_general

### [G008_sfx_001](G008_sfx_001.json)

- **C001**：Sharp compact pistol shot with brass ejection tick tail
- **C002**：distinct crack

### [G008_sfx_002](G008_sfx_002.json)

- **C001**：Fast light submachine gun burst with metallic bolt chatter

### [G008_sfx_003](G008_sfx_003.json)

- **C001**：Full assault rifle report with clear mid-body punch and casing tinkle

### [G008_sfx_004](G008_sfx_004.json)

- **C001**：Deep close-range shotgun blast with heavy wet-air thump

### [G008_sfx_005](G008_sfx_005.json)

- **C001**：Long heavy sniper crack with echoing rain-field report

### [G008_sfx_006](G008_sfx_006.json)

- **C001**：Sustained light machine gun hammering loop burst
- **C002**：belt-feed rattle

### [G008_sfx_007](G008_sfx_007.json)

- **C001**：Dry body-hit confirmation tick
- **C002**：short and neutral

### [G008_sfx_008](G008_sfx_008.json)

- **C001**：Bright headshot ping
- **C002**：clearly distinct from body tick

### [G008_sfx_009](G008_sfx_009.json)

- **C001**：Muffled through-material penetration thud with debris crunch

### [G008_sfx_010](G008_sfx_010.json)

- **C001**：Low satisfying kill confirmation stamp

### [G008_sfx_011](G008_sfx_011.json)

- **C001**：Three-stage reload: mag release clack
- **C002**：rounds rattle
- **C003**：charging handle rack

### [G008_sfx_012](G008_sfx_012.json)

- **C001**：Flashbang bang into a long high tinnitus whine holding then fading

### [G008_sfx_013](G008_sfx_013.json)

- **C001**：Wet steel and grate footsteps with puddle splashes
- **C002**：three movement states layerable (run, silent walk, crouch)

### [G008_sfx_014](G008_sfx_014.json)

- **C001**：Beacon alarm chirp and electronic plant/defuse progress beeps
- **C002**：audible

### [G008_sfx_015](G008_sfx_015.json)

- **C001**：Two-tone round win/lose sting
- **C002**：victory rising
- **C003**：defeat falling

### [G008_sfx_016](G008_sfx_016.json)

- **C001**：Heavy sustained rainstorm ambience over wet steel and water
- **C002**：distant thunder rolls
- **C003**：seamless loop
- **C004**：no music

### [G008_sfx_017](G008_sfx_017.json)

- **C001**：Dockyard metal creak and mooring rope groan under wind
- **C002**：sparse and low
- **C003**：seamless loop

### [G008_cg_001](G008_cg_001.json)

- **C001**：暴雨夜的锚湾码头全景俯瞰
- **C002**：闪电照亮集装箱迷宫
- **C003**：信标队与锚卫队各干员自泊位两侧登场亮相
- **C004**：数据核心信标特写泛起青光
- **C005**：镜头自天际雨幕俯冲至两队对峙中景

### [G008_cg_002](G008_cg_002.json)

- **C001**：雨幕中双方沿两条主攻路线推进的快速剪辑——破门手切墙
- **C002**：侦察员投扫描
- **C003**：狙击镜内雨珠滑过
- **C004**：交火火花在积水面上炸开

### [G008_cg_003](G008_cg_003.json)

- **C001**：安装意象=信标指示灯由黄转绿
- **C002**：倒计时环亮起
- **C003**：拆除意象=剪线火花一闪
- **C004**：指示灯熄灭
- **C005**：镜头推近信标特写后定格（不同意象素材）

### [G008_cg_004](G008_cg_004.json)

- **C001**：胜方干员在雨幕中列队合影
- **C002**：信标青光映亮雨珠
- **C003**：败方收拾装备撤离泊位
- **C004**：比分牌在积水中倒映定格
- **C005**：镜头缓缓拉远至雨夜全景

### [G008_mot_001](G008_mot_001.json)

- **C001**：Operator sprinting tactically with weapon up
- **C002**：splash steps through rain puddles
- **C003**：动作具有可重复衔接的循环组织；不设循环时长或帧数门槛。
- **C004**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。
- 审查提示：unresolved_spec_ref

### [G008_mot_002](G008_mot_002.json)

- **C001**：Three-stage rifle reload: magazine drop
- **C002**：fresh mag seating
- **C003**：charging handle rack
- **C004**：单次动作具有可辨起始、过程与结束；不设绝对时长门槛。
- **C005**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。
- 审查提示：unresolved_spec_ref

### [G008_mot_003](G008_mot_003.json)

- **C001**：Operator kneels and plants the data-core beacon on a pedestal with a progress-paced two-hand mount
- **C002**：单次动作具有可辨起始、过程与结束；不设绝对时长门槛。
- **C003**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。
- 审查提示：unresolved_spec_ref

### [G008_mot_004](G008_mot_004.json)

- **C001**：Short explosive sprint with shoulder charge against a door panel
- **C002**：单次动作具有可辨起始、过程与结束；不设绝对时长门槛。
- **C003**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。
- 审查提示：unresolved_spec_ref

### [G008_mot_005](G008_mot_005.json)

- **C001**：Slow silent walk with weight-shifted steps
- **C002**：weapon low
- **C003**：动作具有可重复衔接的循环组织；不设循环时长或帧数门槛。
- **C004**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。
- 审查提示：unresolved_spec_ref

### [G008_mot_006](G008_mot_006.json)

- **C001**：Operator kneels and defuses the mounted beacon with wire clippers in a progress-paced motion
- **C002**：单次动作具有可辨起始、过程与结束；不设绝对时长门槛。
- **C003**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。
- 审查提示：unresolved_spec_ref

### [G008_mot_007](G008_mot_007.json)

- **C001**：Downed operator reaches out and calls for help while prone
- **C002**：weak struggling motion
- **C003**：动作具有可重复衔接的循环组织；不设循环时长或帧数门槛。
- **C004**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。
- 审查提示：unresolved_spec_ref

### [G008_tpose_001](G008_tpose_001.json)

- **C001**：Front T-pose reference of the attacker operator

### [G008_tpose_002](G008_tpose_002.json)

- **C001**：Front T-pose reference of the defender operator

