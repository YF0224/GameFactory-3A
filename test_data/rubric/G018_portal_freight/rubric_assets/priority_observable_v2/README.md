# G018_portal_freight — priority 资产需求 rubric 修订 v2

本目录是独立修订版；旧 `../rubric.json`、`../per_asset/` 及历史分数均保留。
游戏内索引：`../priority_rubric_current.json`。仅包含 priority gen 对应任务，不代表其他资产任务也已修订。
第一列保留可观察的主体、部件、形状、色彩、材质、相对布局、动作/事件及声音内容；精确坐标、尺寸、时长、速度、计数和技术参数只作来源/诊断。
已有逐资产文件的第二/三维原样保留；自然音效与T-pose补充的是此前缺失的rubric草稿，不是历史有效分数。
本版尚未逐项人工审核/最终冻结，也未自动切换生产 evaluator 或重新评测。采用新 schema，必须显式选择并适配，禁止混用旧分数。

| 类型 | 任务数 |
|---|---:|
| 3D Scene | 1 |
| Audio | 9 |
| CG Video | 3 |

## 第一列逐任务预览

以下仅展示计分目标；完整原文、定性投影记录、排除项、判分锚点和第二/三维见对应 JSON。

### [G018_scene_001](G018_scene_001.json)

- **C001**：Orbital freight station cargo bay at night
- **C002**：three connected chambers with white portal-ready wall panels
- **C003**：a trench gap
- **C004**：cargo lift and glow strip lighting
- **C005**：cool white alloy palette with orange-blue accents
- **C006**：多个房间组成主题背景
- **C007**：具有门墙、沟壑与目标区域的空间表现；不验收引擎生成位置
- 审查提示：no_literal_asset_mention_in_general

### [G018_sfx_001](G018_sfx_001.json)

- **C001**：Energy anchoring hum as a portal snaps onto a wall panel

### [G018_sfx_002](G018_sfx_002.json)

- **C001**：Whooshing rift transit sound with subtle reverse tail

### [G018_sfx_003](G018_sfx_003.json)

- **C001**：Hydraulic lift whir as a crate is hefted

### [G018_sfx_004](G018_sfx_004.json)

- **C001**：Light metallic thud of a small crate landing

### [G018_sfx_005](G018_sfx_005.json)

- **C001**：Heavy resonant thud of a heavy crate landing

### [G018_sfx_006](G018_sfx_006.json)

- **C001**：Mechanical click of a pressure plate engaging

### [G018_sfx_007](G018_sfx_007.json)

- **C001**：Confirming delivery beep when a crate reaches its matched berth

### [G018_sfx_008](G018_sfx_008.json)

- **C001**：Short negative buzz for mismatched berth or invalid action

### [G018_sfx_009](G018_sfx_009.json)

- **C001**：Airlock low hum and ventilation hiss inside an orbital station bay
- **C002**：no music

### [G018_cg_001](G018_cg_001.json)

- **C001**：Orbital freight station at night through a viewport
- **C002**：robotic sorter arms spark and stall
- **C003**：a dispatcher picks up a paired rift device as seven berth lights blink
- **C004**：cool whites with orange-blue glow
- **C005**：cinematic
- **C006**：no text

### [G018_cg_002](G018_cg_002.json)

- **C001**：A cargo crate slides out of a glowing rift into its berth
- **C002**：berth light turns green
- **C003**：station PA chime
- **C004**：cinematic
- **C005**：no text

### [G018_cg_003](G018_cg_003.json)

- **C001**：Seven berth lights all green
- **C002**：cargo hold gate opens
- **C003**：a supply ship departs against stars
- **C004**：the dispatcher watches it go
- **C005**：cinematic
- **C006**：no text

