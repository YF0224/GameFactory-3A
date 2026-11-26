# G047_oldtown_fire_rescue — priority 资产需求 rubric 修订 v2

本目录是独立修订版；旧 `../rubric.json`、`../per_asset/` 及历史分数均保留。
游戏内索引：`../priority_rubric_current.json`。仅包含 priority gen 对应任务，不代表其他资产任务也已修订。
第一列保留可观察的主体、部件、形状、色彩、材质、相对布局、动作/事件及声音内容；精确坐标、尺寸、时长、速度、计数和技术参数只作来源/诊断。
已有逐资产文件的第二/三维原样保留；自然音效与T-pose补充的是此前缺失的rubric草稿，不是历史有效分数。
本版尚未逐项人工审核/最终冻结，也未自动切换生产 evaluator 或重新评测。采用新 schema，必须显式选择并适配，禁止混用旧分数。

| 类型 | 任务数 |
|---|---:|
| 3D Scene | 1 |
| Audio | 11 |
| CG Video | 3 |

## 第一列逐任务预览

以下仅展示计分目标；完整原文、定性投影记录、排除项、判分锚点和第二/三维见对应 JSON。

### [G047_scene_001](G047_scene_001.json)

- **C001**：Rainy night old-town street with a burning two-story timber-and-brick shop house
- **C002**：cracked signboard
- **C003**：hydrant and wet cobblestones reflecting fire light
- **C004**：ember-orange against charcoal
- **C005**：stylized semi-realistic
- **C006**：场景具有上下楼层的空间表现；不验收火格或人员分布
- 审查提示：no_literal_asset_mention_in_general

### [G047_sfx_001](G047_sfx_001.json)

- **C001**：Pressurized water hiss through a hand nozzle

### [G047_sfx_002](G047_sfx_002.json)

- **C001**：Wet sizzle as flames extinguish

### [G047_sfx_003](G047_sfx_003.json)

- **C001**：Loud wood crackle as fire spreads to a new cell

### [G047_sfx_004](G047_sfx_004.json)

- **C001**：Double muffled hammer thuds breaking debris

### [G047_sfx_005](G047_sfx_005.json)

- **C001**：Ominous creaking beam warning before collapse

### [G047_sfx_006](G047_sfx_006.json)

- **C001**：Distant worried human shouting for help
- **C002**：non-lexical vocal

### [G047_sfx_007](G047_sfx_007.json)

- **C001**：Frightened short whimper
- **C002**：non-lexical vocal

### [G047_sfx_008](G047_sfx_008.json)

- **C001**：Relieved two-note confirm as a resident reaches safety

### [G047_sfx_009](G047_sfx_009.json)

- **C001**：Low urgent alarm signaling a blocked rescue route

### [G047_sfx_010](G047_sfx_010.json)

- **C001**：All-clear fire bell fading into quiet rain

### [G047_sfx_011](G047_sfx_011.json)

- **C001**：Roaring house fire with rain patter
- **C002**：distant alarm bells
- **C003**：wind-fed crackle

### [G047_cg_001](G047_cg_001.json)

- **C001**：Winter night old-town street
- **C002**：a timber shopfront bursts with fire tongues
- **C003**：a volunteer firefighter shoulders a water tank and dashes down the lane
- **C004**：cries for help from upper windows
- **C005**：cinematic
- **C006**：no text

### [G047_cg_002](G047_cg_002.json)

- **C001**：A rescued resident steps out to safety and turns to nod
- **C002**：the firefighter wipes his mask and heads back in
- **C003**：fire light on wet cobbles
- **C004**：cinematic
- **C005**：no text

### [G047_cg_003](G047_cg_003.json)

- **C001**：Three residents and the firefighter stand in the backyard exit watching the fire die down
- **C002**：bell turns to a calm town clock
- **C003**：night rain softens
- **C004**：cinematic
- **C005**：no text

