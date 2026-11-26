# G030_polar_night_td — priority 资产需求 rubric 修订 v2

本目录是独立修订版；旧 `../rubric.json`、`../per_asset/` 及历史分数均保留。
游戏内索引：`../priority_rubric_current.json`。仅包含 priority gen 对应任务，不代表其他资产任务也已修订。
第一列保留可观察的主体、部件、形状、色彩、材质、相对布局、动作/事件及声音内容；精确坐标、尺寸、时长、速度、计数和技术参数只作来源/诊断。
已有逐资产文件的第二/三维原样保留；自然音效与T-pose补充的是此前缺失的rubric草稿，不是历史有效分数。
本版尚未逐项人工审核/最终冻结，也未自动切换生产 evaluator 或重新评测。采用新 schema，必须显式选择并适配，禁止混用旧分数。

| 类型 | 任务数 |
|---|---:|
| 3D Object | 9 |
| 3D Scene | 1 |
| Audio | 25 |
| CG Video | 5 |
| Motion | 1 |

## 第一列逐任务预览

以下仅展示计分目标；完整原文、定性投影记录、排除项、判分锚点和第二/三维见对应 JSON。

### [G030_polar_night_td_obj_001](G030_polar_night_td_obj_001.json)

- **C001**：Settlement hearth core furnace with glowing ember heart
- **C002**：iron boiler shell and heat pipes
- **C003**：single object

### [G030_polar_night_td_obj_002](G030_polar_night_td_obj_002.json)

- **C001**：Polar settlement steam generator with flywheel and frost-caked exhaust
- **C002**：single object

### [G030_polar_night_td_obj_003](G030_polar_night_td_obj_003.json)

- **C001**：Frost predator beast drawn to heat
- **C002**：shaggy ice-crusted fur and ember-reflecting eyes
- **C003**：single object

### [G030_polar_night_td_obj_004](G030_polar_night_td_obj_004.json)

- **C001**：Frozen wooden power pole with copper line insulators and snow cap
- **C002**：grid relay prop with visible health
- **C003**：single object

### [G030_polar_night_td_obj_005](G030_polar_night_td_obj_005.json)

- **C001**：Polar sentry ballista tower with heated wind shield and bolt rack
- **C002**：powered turret
- **C003**：single object

### [G030_polar_night_td_obj_006](G030_polar_night_td_obj_006.json)

- **C001**：Frost-rune slow tower with rime crystal emitters and frost mist vents
- **C002**：powered turret
- **C003**：single object

### [G030_polar_night_td_obj_007](G030_polar_night_td_obj_007.json)

- **C001**：Frozen ore mining rig with drill head
- **C002**：ore hopper and steam vent
- **C003**：powered production device
- **C004**：single object

### [G030_polar_night_td_obj_008](G030_polar_night_td_obj_008.json)

- **C001**：Cable-shredding rodent swarm beast with gnawing jaws
- **C002**：hunched frost-furred body and copper-wire nest quills
- **C003**：single object

### [G030_polar_night_td_obj_009](G030_polar_night_td_obj_009.json)

- **C001**：Small frozen repair station with welding tools
- **C002**：spare pole segments and lantern
- **C003**：environment prop
- **C004**：single object

### [G030_scene_001](G030_scene_001.json)

- **C001**：Polar night settlement seen from above: frozen town grid with central glowing hearth core
- **C002**：wooden power lines crossing between buildings
- **C003**：four gate entrances at map edges
- **C004**：aurora band overhead
- **C005**：drifting snow
- **C006**：极夜聚落地图
- **C007**：暖炉核心位于中央
- **C008**：入口分布在东、南、西、北方向
- 审查提示：no_literal_asset_mention_in_general

### [G030_vo_019](G030_vo_019.json)

- **C001**：Resolute old mayor voice
- **C002**：gravelly and calm
- **C003**：Chinese
- **C004**：wind bed
- **C005**：极夜开始了。守住暖炉，守住电网，撑过三夜。
- **C006**：语音使用声明的语言：Chinese
- **C007**：语音表达声明的情绪：tense
- 审查提示：no_literal_asset_mention_in_general

### [G030_vo_020](G030_vo_020.json)

- **C001**：Mayor warning voice
- **C002**：tense
- **C003**：Chinese
- **C004**：东边有动静，是掠食者，它们闻到了热气。
- **C005**：语音使用声明的语言：Chinese
- **C006**：语音表达声明的情绪：tense
- 审查提示：no_literal_asset_mention_in_general

### [G030_vo_021](G030_vo_021.json)

- **C001**：Mayor alarmed voice
- **C002**：quick pace
- **C003**：Chinese
- **C004**：碎线兽来了！它们专咬电杆，盯紧线路。
- **C005**：语音使用声明的语言：Chinese
- **C006**：语音表达声明的情绪：urgent
- 审查提示：no_literal_asset_mention_in_general

### [G030_vo_022](G030_vo_022.json)

- **C001**：Mayor urgent command voice
- **C002**：strained
- **C003**：Chinese
- **C004**：storm bed
- **C005**：寒潮压下来了，发电机撑不住满负荷，排好断电顺序！
- **C006**：语音使用声明的语言：Chinese
- **C007**：语音表达声明的情绪：urgent
- 审查提示：no_literal_asset_mention_in_general

### [G030_vo_023](G030_vo_023.json)

- **C001**：Relieved warm mayor voice
- **C002**：Chinese
- **C003**：morning wind bed
- **C004**：天亮了。北炉镇，活下来了。
- **C005**：语音使用声明的语言：Chinese
- **C006**：语音表达声明的情绪：joyful
- 审查提示：no_literal_asset_mention_in_general

### [G030_vo_024](G030_vo_024.json)

- **C001**：Bittersweet low mayor voice
- **C002**：Chinese
- **C003**：morning wind bed
- **C004**：天亮了，可暖炉只剩残火……收拾行装，往南走。
- **C005**：语音使用声明的语言：Chinese
- **C006**：语音表达声明的情绪：tense
- 审查提示：no_literal_asset_mention_in_general

### [G030_vo_025](G030_vo_025.json)

- **C001**：Grieving broken mayor voice
- **C002**：near whisper
- **C003**：Chinese
- **C004**：暖炉熄了……
- **C005**：语音使用声明的语言：Chinese
- **C006**：语音表达声明的情绪：tense
- 审查提示：no_literal_asset_mention_in_general

### [G030_sfx_001](G030_sfx_001.json)

- **C001**：Steam generator steady hum with flywheel ticks

### [G030_sfx_002](G030_sfx_002.json)

- **C001**：Power line disconnect crackle with dying hum

### [G030_sfx_003](G030_sfx_003.json)

- **C001**：Overload trip alarm with relay clack and warning tone

### [G030_sfx_004](G030_sfx_004.json)

- **C001**：Rodent bite into frozen wood pole with wire snap

### [G030_sfx_005](G030_sfx_005.json)

- **C001**：Power pole snapping and falling with wire whip

### [G030_sfx_006](G030_sfx_006.json)

- **C001**：Welding torch repair loop with progress ticks

### [G030_sfx_007](G030_sfx_007.json)

- **C001**：Sentry ballista release with cold bolt whoosh

### [G030_sfx_008](G030_sfx_008.json)

- **C001**：Bolt impact into frost fur with ice crack

### [G030_sfx_009](G030_sfx_009.json)

- **C001**：Frost predator growl with breath hiss

### [G030_sfx_010](G030_sfx_010.json)

- **C001**：Hearth core impact with ember burst and low boom

### [G030_sfx_011](G030_sfx_011.json)

- **C001**：Night bell with rising wind and distant howl

### [G030_sfx_012](G030_sfx_012.json)

- **C001**：Day chime with settling wind

### [G030_sfx_013](G030_sfx_013.json)

- **C001**：Panel open tick with list shuffle

### [G030_sfx_014](G030_sfx_014.json)

- **C001**：Building placement thunk into frozen ground

### [G030_sfx_015](G030_sfx_015.json)

- **C001**：Mining drill cycle with ore clink and steam puff

### [G030_sfx_016](G030_sfx_016.json)

- **C001**：Sunrise victory sting with warm brass and wind settle

### [G030_sfx_017](G030_sfx_017.json)

- **C001**：Hearth dying drone with wind swallowing town

### [G030_sfx_018](G030_sfx_018.json)

- **C001**：Polar blizzard ambience loop with wind gusts
- **C002**：distant hearth hum and snow hiss
- **C003**：seamless loop

### [G030_cg_001](G030_cg_001.json)

- **C001**：北炉镇全景：太阳沉入地平线
- **C002**：暴风雪起
- **C003**：暖炉核心点亮镇中心灯光
- **C004**：电网依次亮起
- **C005**：镇长合上电闸
- **C006**：无 UI
- **C007**：无文字
- **C008**：无剪辑

### [G030_cg_002](G030_cg_002.json)

- **C001**：东门哨位外风雪中浮现掠食者群的绿色眼点
- **C002**：电网哨灯闪动告警
- **C003**：无 UI
- **C004**：无文字

### [G030_cg_003](G030_cg_003.json)

- **C001**：寒潮前锋横扫聚落
- **C002**：发电机外壳结霜转速变慢
- **C003**：负载栏数字下坠
- **C004**：无 UI
- **C005**：无文字
- 审查提示：no_literal_asset_mention_in_general, source_text_display_conflict

### [G030_cg_004](G030_cg_004.json)

- **C001**：地平线日出
- **C002**：极光淡去
- **C003**：镇民推开木门
- **C004**：暖炉火光稳定
- **C005**：烟囱升起炊烟
- **C006**：无 UI
- **C007**：无文字

### [G030_cg_005](G030_cg_005.json)

- **C001**：日出但暖炉只剩微光
- **C002**：镇民收拾行装与账册
- **C003**：车队驶向南方地平线
- **C004**：无 UI
- **C005**：无文字

### [G030_polar_night_td_mot_001](G030_polar_night_td_mot_001.json)

- **C001**：Repair animation tightens a cable
- **C002**：turns a handwheel and restarts the generator with a cold blue glow
- **C003**：单次动作具有可辨起始、过程与结束；不设绝对时长门槛。
- 审查提示：duplicate_asset_requirement_entry

