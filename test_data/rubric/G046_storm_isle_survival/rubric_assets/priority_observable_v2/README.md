# G046_storm_isle_survival — priority 资产需求 rubric 修订 v2

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

### [G046_storm_isle_survival_obj_001](G046_storm_isle_survival_obj_001.json)

- **C001**：Primitive stone hand-axe with lashed grey flint head and driftwood handle
- **C002**：stylized cartoon voxel-era look

### [G046_storm_isle_survival_obj_002](G046_storm_isle_survival_obj_002.json)

- **C001**：Driftwood signal bonfire kit: stacked log star pyramid with dry kindling and a small orange signal banner
- **C002**：stylized cartoon

### [G046_scene_001](G046_scene_001.json)

- **C001**：Top-down stylized cartoon voxel storm island environment with southern beach landing；海滩位于南部，林地位于中央，岩地位于北部
- **C002**：central woodland
- **C003**：northern rock area and storm sea boundary
- **C004**：one coherent game-ready three-dimensional scene
- **C005**：no text
- 审查提示：no_literal_asset_mention_in_general

### [G046_sfx_001](G046_sfx_001.json)

- **C001**：Dry woody chop of splitting a log block

### [G046_sfx_002](G046_sfx_002.json)

- **C001**：Short brittle crack of breaking a stone block

### [G046_sfx_003](G046_sfx_003.json)

- **C001**：Soft muffled thud placing a block into world

### [G046_sfx_004](G046_sfx_004.json)

- **C001**：Quick carpentry tap-tap as a recipe completes

### [G046_sfx_005](G046_sfx_005.json)

- **C001**：Gust slap with rain hiss as a storm surge hits

### [G046_sfx_006](G046_sfx_006.json)

- **C001**：Warm confirm chord as a shelter roof registers

### [G046_sfx_007](G046_sfx_007.json)

- **C001**：Rasping crank as the signal bonfire is lit

### [G046_sfx_008](G046_sfx_008.json)

- **C001**：Distant ship horn through clearing wind

### [G046_sfx_009](G046_sfx_009.json)

- **C001**：Daytime island: gull calls
- **C002**：easy surf
- **C003**：leaves in breeze
- **C004**：no music

### [G046_sfx_010](G046_sfx_010.json)

- **C001**：Night storm: rising wind
- **C002**：heavier rain on leaves
- **C003**：distant thunder rolls

### [G046_cg_001](G046_cg_001.json)

- **C001**：Storm-night sea
- **C002**：a life ring washes onto a dark island beach
- **C003**：a shipwrecked crew member crawls ashore looking back at a sinking freighter
- **C004**：teal-dark palette with warm deck lights
- **C005**：cinematic
- **C006**：no text

### [G046_cg_002](G046_cg_002.json)

- **C001**：Sky slams dark
- **C002**：wind lines rake the sea
- **C003**：lightning outlines a half-built shelter
- **C004**：the survivor hugs a plank
- **C005**：cinematic
- **C006**：no text

### [G046_cg_003](G046_cg_003.json)

- **C001**：A flare climbs over the island
- **C002**：a rescue ship cuts through the last swell
- **C003**：its searchlight settles on the shelter and bonfire
- **C004**：the survivor waves
- **C005**：cinematic
- **C006**：no text

