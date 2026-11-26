# G056_garden_minigolf — priority 资产需求 rubric 修订 v2

本目录是独立修订版；旧 `../rubric.json`、`../per_asset/` 及历史分数均保留。
游戏内索引：`../priority_rubric_current.json`。仅包含 priority gen 对应任务，不代表其他资产任务也已修订。
第一列保留可观察的主体、部件、形状、色彩、材质、相对布局、动作/事件及声音内容；精确坐标、尺寸、时长、速度、计数和技术参数只作来源/诊断。
已有逐资产文件的第二/三维原样保留；自然音效与T-pose补充的是此前缺失的rubric草稿，不是历史有效分数。
本版尚未逐项人工审核/最终冻结，也未自动切换生产 evaluator 或重新评测。采用新 schema，必须显式选择并适配，禁止混用旧分数。

| 类型 | 任务数 |
|---|---:|
| 3D Object | 2 |
| 3D Scene | 1 |
| Audio | 9 |
| CG Video | 2 |

## 第一列逐任务预览

以下仅展示计分目标；完整原文、定性投影记录、排除项、判分锚点和第二/三维见对应 JSON。

### [G056_garden_minigolf_obj_002](G056_garden_minigolf_obj_002.json)

- **C001**：Single dimpled golf ball with a soft pearl sheen
- **C002**：clean stylized

### [G056_garden_minigolf_obj_003](G056_garden_minigolf_obj_003.json)

- **C001**：Miniature golf hole cup with a slender striped pennant flag and a subtle glow rim
- **C002**：clean stylized

### [G056_scene_001](G056_scene_001.json)

- **C001**：Floating island garden golf course above a sea of clouds: meadow fairway with petal hedges
- **C002**：gentle slope ramp with a wooden bumper
- **C003**：stepped stone tiers with two boards
- **C004**：drifting cloud sea at the edges
- **C005**：bright spring palette
- **C006**：stylized cartoon
- **C007**：球场具有直道、上坡折返与阶梯坡的地形变化
- **C008**：云海边界构成球场外框
- 审查提示：no_literal_asset_mention_in_general

### [G056_sfx_001](G056_sfx_001.json)

- **C001**：Rising soft tone while charging a putt

### [G056_sfx_002](G056_sfx_002.json)

- **C001**：Clean wood-and-putter tap

### [G056_sfx_003](G056_sfx_003.json)

- **C001**：Soft grass rolling hiss

### [G056_sfx_004](G056_sfx_004.json)

- **C001**：Hollow wooden bumper bounce

### [G056_sfx_005](G056_sfx_005.json)

- **C001**：Whistling fall into wind and a soft poof

### [G056_sfx_006](G056_sfx_006.json)

- **C001**：Bright pop and a satisfying rattle as the ball drops

### [G056_sfx_007](G056_sfx_007.json)

- **C001**：Low neutral chime as the cap applies

### [G056_sfx_008](G056_sfx_008.json)

- **C001**：Light airy fanfare with paper-lantern shimmer

### [G056_sfx_009](G056_sfx_009.json)

- **C001**：Floating garden: soft wind over grass
- **C002**：cloud-sea hum
- **C003**：distant songbirds

### [G056_cg_001](G056_cg_001.json)

- **C001**：A floating island garden above an evening cloud sea
- **C002**：paper lanterns light along a three-hole course
- **C003**：an apprentice gardener walks to the first tee with a putter
- **C004**：bright stylized look
- **C005**：cinematic
- **C006**：no text

### [G056_cg_002](G056_cg_002.json)

- **C001**：Three course lanterns light in sequence
- **C002**：paper lanterns rise forming a spring pattern
- **C003**：the gardener raises her putter to a cheering stand
- **C004**：cinematic
- **C005**：no text

