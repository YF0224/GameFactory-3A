# G043_airship_kitchen — priority 资产需求 rubric 修订 v2

本目录是独立修订版；旧 `../rubric.json`、`../per_asset/` 及历史分数均保留。
游戏内索引：`../priority_rubric_current.json`。仅包含 priority gen 对应任务，不代表其他资产任务也已修订。
第一列保留可观察的主体、部件、形状、色彩、材质、相对布局、动作/事件及声音内容；精确坐标、尺寸、时长、速度、计数和技术参数只作来源/诊断。
已有逐资产文件的第二/三维原样保留；自然音效与T-pose补充的是此前缺失的rubric草稿，不是历史有效分数。
本版尚未逐项人工审核/最终冻结，也未自动切换生产 evaluator 或重新评测。采用新 schema，必须显式选择并适配，禁止混用旧分数。

| 类型 | 任务数 |
|---|---:|
| 3D Object | 1 |
| 3D Scene | 1 |
| Audio | 11 |
| CG Video | 3 |

## 第一列逐任务预览

以下仅展示计分目标；完整原文、定性投影记录、排除项、判分锚点和第二/三维见对应 JSON。

### [G043_airship_kitchen_obj_011](G043_airship_kitchen_obj_011.json)

- **C001**：Airship kitchen brass waste bin with foot pedal and lid
- **C002**：dented metal with painted stripe
- **C003**：single small object

### [G043_scene_001](G043_scene_001.json)

- **C001**：Airship galley kitchen interior scene
- **C002**：single room with five brass-and-oak workstations along side walls
- **C003**：central double-chef working aisle
- **C004**：porthole windows showing cloud sea and floating islands
- **C005**：warm lamp light
- **C006**：steam vents
- **C007**：visual shell only
- **C008**：水槽、案台、灶台、装盘台、出餐口与厨余桶具有可见表现；不检查坐标或工序状态机
- 审查提示：no_literal_asset_mention_in_general

### [G043_sfx_001](G043_sfx_001.json)

- **C001**：New order ticket bell with paper snap
- **C002**：bright brass ding suitable for kitchen pass rail

### [G043_sfx_002](G043_sfx_002.json)

- **C001**：Station work start cue
- **C002**：short water splash / knife tap / griddle sizzle hybrid tick per station start

### [G043_sfx_003](G043_sfx_003.json)

- **C001**：Station step complete chime
- **C002**：bright double tick with small steam hiss tail

### [G043_sfx_004](G043_sfx_004.json)

- **C001**：Denied interaction cue with switchable profiles: busy-station soft knock
- **C002**：invalid-place low buzz
- **C003**：waste-drop thud

### [G043_sfx_005](G043_sfx_005.json)

- **C001**：Handoff pass whoosh with light ceramic clink as item travels between chefs

### [G043_sfx_006](G043_sfx_006.json)

- **C001**：Serve complete: plate slide on brass hatch shelf with satisfying bell ding

### [G043_sfx_007](G043_sfx_007.json)

- **C001**：Order timeout cue with alarm profile: sand-shatter hiss and low warning tone
- **C002**：urgent but short

### [G043_sfx_008](G043_sfx_008.json)

- **C001**：Shift success sting
- **C002**：warm brass band rising with cloud-wind tail
- **C003**：celebratory but light

### [G043_sfx_009](G043_sfx_009.json)

- **C001**：Shift defeat sting
- **C002**：low brass and soft engine winding down
- **C003**：gentle disappointment

### [G043_sfx_010](G043_sfx_010.json)

- **C001**：Seamless airship engine hum with cloud-sea wind
- **C002**：steady low drone with occasional creak
- **C003**：no voices or music

### [G043_sfx_011](G043_sfx_011.json)

- **C001**：Seamless busy kitchen ambience: faint sizzle
- **C002**：bubbling pots and distant clatter layers
- **C003**：no distinct voices

### [G043_cg_001](G043_cg_001.json)

- **C001**：云鲛号飞艇驶离浮岛港
- **C002**：云海翻涌
- **C003**：厨房吊灯亮起
- **C004**：青灰围裙与暖橙围裙厨师系上围裙就位
- **C005**：第一张订单卡飘入
- **C006**：无 UI
- **C007**：无文字
- **C008**：无剪辑

### [G043_cg_002](G043_cg_002.json)

- **C001**：订单卡连续飞入挤满队列
- **C002**：双厨穿梭五工位
- **C003**：蒸汽腾起
- **C004**：耐心条快速缩短
- **C005**：无 UI
- **C006**：无文字

### [G043_cg_003](G043_cg_003.json)

- **C001**：不同意象共用条目：达标＝舷窗霞光
- **C002**：订单板挂满金勾
- **C003**：飞艇升起新航段旗
- **C004**：判负＝厨房熄灯
- **C005**：订单板清空
- **C006**：飞艇降下「暂停中供」旗
- **C007**：无 UI
- **C008**：无文字

