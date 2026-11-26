# G049_underwater_salvage — priority 资产需求 rubric 修订 v2

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

### [G049_scene_001](G049_scene_001.json)

- **C001**：Sunken science vessel wreck on a shallow shelf: broken outer hull
- **C002**：tilted mid cabin
- **C003**：deep power core chamber with amber lights
- **C004**：emergency air posts
- **C005**：drifting silt and god rays
- **C006**：deep-blue palette
- **C007**：stylized semi-realistic
- **C008**：水下区域具有分层深度感，不验收绝对深度
- **C009**：部件与气桩具有可见表现
- 审查提示：no_literal_asset_mention_in_general

### [G049_sfx_001](G049_sfx_001.json)

- **C001**：Rhythmic underwater metal unscrewing strain

### [G049_sfx_002](G049_sfx_002.json)

- **C001**：Muffled clunk as a part breaks free

### [G049_sfx_003](G049_sfx_003.json)

- **C001**：Short dull rejection clank for out-of-order dismantle

### [G049_sfx_004](G049_sfx_004.json)

- **C001**：Soft fabric and metal rasp as a part is shouldered

### [G049_sfx_005](G049_sfx_005.json)

- **C001**：short air hose refill hiss

### [G049_sfx_006](G049_sfx_006.json)

- **C001**：Soft low-air warning tone

### [G049_sfx_007](G049_sfx_007.json)

- **C001**：Rapid urgent oxygen alarm

### [G049_sfx_008](G049_sfx_008.json)

- **C001**：Deep single-tone pressure warning

### [G049_sfx_009](G049_sfx_009.json)

- **C001**：Muffled tinnitus fading into surface splash

### [G049_sfx_010](G049_sfx_010.json)

- **C001**：Metal part dropped into a salvage crate

### [G049_sfx_011](G049_sfx_011.json)

- **C001**：Deep underwater ambience: pressure hum
- **C002**：slow bubbles
- **C003**：distant creaks

### [G049_cg_001](G049_cg_001.json)

- **C001**：Morning sea surface at a salvage barge
- **C002**：a crane lowers a diver into a blue water column
- **C003**：a sunken vessel silhouette appears below
- **C004**：cinematic
- **C005**：no text

### [G049_cg_002](G049_cg_002.json)

- **C001**：A dive lamp sweeps across a rusted core chamber
- **C002**：sealed doors and a faint air-post light in the dark
- **C003**：pressure rumble grows
- **C004**：cinematic
- **C005**：no text

### [G049_cg_003](G049_cg_003.json)

- **C001**：The last part breaks the surface and drops into the salvage crate
- **C002**：deck lights run on
- **C003**：the diver removes the mask looking at open sea
- **C004**：cinematic
- **C005**：no text

