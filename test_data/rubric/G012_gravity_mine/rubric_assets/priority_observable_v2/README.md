# G012_gravity_mine — priority 资产需求 rubric 修订 v2

本目录是独立修订版；旧 `../rubric.json`、`../per_asset/` 及历史分数均保留。
游戏内索引：`../priority_rubric_current.json`。仅包含 priority gen 对应任务，不代表其他资产任务也已修订。
第一列保留可观察的主体、部件、形状、色彩、材质、相对布局、动作/事件及声音内容；精确坐标、尺寸、时长、速度、计数和技术参数只作来源/诊断。
已有逐资产文件的第二/三维原样保留；自然音效与T-pose补充的是此前缺失的rubric草稿，不是历史有效分数。
本版尚未逐项人工审核/最终冻结，也未自动切换生产 evaluator 或重新评测。采用新 schema，必须显式选择并适配，禁止混用旧分数。

| 类型 | 任务数 |
|---|---:|
| 3D Object | 2 |
| 3D Scene | 1 |
| Audio | 10 |
| CG Video | 3 |

## 第一列逐任务预览

以下仅展示计分目标；完整原文、定性投影记录、排除项、判分锚点和第二/三维见对应 JSON。

### [G012_gravity_mine_obj_004](G012_gravity_mine_obj_004.json)

- **C001**：Single wall-mounted steam valve vent with a brass nozzle
- **C002**：single object

### [G012_gravity_mine_obj_005](G012_gravity_mine_obj_005.json)

- **C001**：Single checkpoint pedestal base used as both floor and ceiling safety anchor
- **C002**：warm lamp ring state shown by material
- **C003**：same mesh instance on both surfaces
- **C004**：single object

### [G012_scene_001](G012_scene_001.json)

- **C001**：One deep mine with multiple vertical sections
- **C002**：walkable floor and walkable ceiling apart
- **C003**：hanging lamps
- **C004**：wet rock and copper steam pipes
- **C005**：warm work-light pockets in the dark
- **C006**：矿井由连续区段组成
- **C007**：地面与顶面相对分离
- **C008**：检查点位于区段起始处，地面与顶面具有对应锚点，锚点不与陷阱重叠
- **C009**：压锤、蒸汽喷口和尖刺具有可见表现；不验收周期或伤害
- 审查提示：no_literal_asset_mention_in_general

### [G012_sfx_001](G012_sfx_001.json)

- **C001**：Low resonant gravity-flip hum with a metallic click of the two-state wrench

### [G012_sfx_002](G012_sfx_002.json)

- **C001**：Falling weightless whoosh while airborne between surfaces

### [G012_sfx_003](G012_sfx_003.json)

- **C001**：Heavy landing thud with dust puff tail on either surface

### [G012_sfx_004](G012_sfx_004.json)

- **C001**：Sharp metallic trap-hit shriek
- **C002**：hazard contact

### [G012_sfx_005](G012_sfx_005.json)

- **C001**：Recovering two-note chime as the mechanic re-anchors at the checkpoint

### [G012_sfx_006](G012_sfx_006.json)

- **C001**：Rhythmic mechanical warning clunk as the ceiling hammer enters its danger phase

### [G012_sfx_007](G012_sfx_007.json)

- **C001**：Pressured steam blast hiss from a wall vent during its jet phase

### [G012_sfx_008](G012_sfx_008.json)

- **C001**：Rising industrial victory sting as the gravity core reboots

### [G012_sfx_009](G012_sfx_009.json)

- **C001**：Low collapsing defeat tone with a fading lamp hum

### [G012_sfx_010](G012_sfx_010.json)

- **C001**：Deep mine ambience
- **C002**：low structural drone with water drips and distant creaks
- **C003**：seamless loop
- **C004**：no music

### [G012_cg_001](G012_cg_001.json)

- **C001**：矿井升降笼载着维修工沉入井道
- **C002**：头顶吊灯摇晃
- **C003**：镜头掠过上下双接触面
- **C004**：尽头失稳的主重力核泛着乱流红光
- **C005**：无剪辑
- **C006**：无 UI
- **C007**：无文字

### [G012_cg_002](G012_cg_002.json)

- **C001**：维修工扳动反转扳手
- **C002**：青色重力光圈荡开
- **C003**：镜头保持水平而角色旋转——上方变成脚下
- **C004**：顶面巷道在视野中展开

### [G012_cg_003](G012_cg_003.json)

- **C001**：胜负不同意象：胜利=主重力核重启
- **C002**：矿井灯光逐层亮起
- **C003**：维修工收起扳手
- **C004**：失败=引力乱流卷起尘土
- **C005**：维修工被吊回井口
- **C006**：灯光逐层熄灭
- 审查提示：multi_variant_cg_requires_delivery_convention, branch_delivery_review

