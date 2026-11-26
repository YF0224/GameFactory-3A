# G053_field_investigation — priority 资产需求 rubric 修订 v2

本目录是独立修订版；旧 `../rubric.json`、`../per_asset/` 及历史分数均保留。
游戏内索引：`../priority_rubric_current.json`。仅包含 priority gen 对应任务，不代表其他资产任务也已修订。
第一列保留可观察的主体、部件、形状、色彩、材质、相对布局、动作/事件及声音内容；精确坐标、尺寸、时长、速度、计数和技术参数只作来源/诊断。
已有逐资产文件的第二/三维原样保留；自然音效与T-pose补充的是此前缺失的rubric草稿，不是历史有效分数。
本版尚未逐项人工审核/最终冻结，也未自动切换生产 evaluator 或重新评测。采用新 schema，必须显式选择并适配，禁止混用旧分数。

| 类型 | 任务数 |
|---|---:|
| 3D Scene | 1 |
| Audio | 10 |
| CG Video | 3 |

## 第一列逐任务预览

以下仅展示计分目标；完整原文、定性投影记录、排除项、判分锚点和第二/三维见对应 JSON。

### [G053_scene_001](G053_scene_001.json)

- **C001**：Original three-domain field research landscape: flower slope meadow Z01 with sparse trees
- **C002**：creek bay Z02 with shallow water
- **C003**：wooden bridge and reed bank
- **C004**：thunder crystal hill Z03 with blue-grey rocks and amber crystals
- **C005**：central research station S01
- **C006**：matching bound reference art style
- **C007**：stylized semi-realistic
- **C008**：不同地形区域组成场景与氛围基线；不验收可玩直径或引擎互通
- 审查提示：unresolved_spec_ref, no_literal_asset_mention_in_general

### [G053_sfx_001](G053_sfx_001.json)

- **C001**：Steady scanning hum for the scan beam

### [G053_sfx_002](G053_sfx_002.json)

- **C001**：Bright two-note register as a species first scans

### [G053_sfx_003](G053_sfx_003.json)

- **C001**：Short warning ping as a creature becomes alert

### [G053_sfx_004](G053_sfx_004.json)

- **C001**：Soft discovery ding as a field clue registers

### [G053_sfx_005](G053_sfx_005.json)

- **C001**：Deep confirming bell as a hypothesis is verified

### [G053_sfx_006](G053_sfx_006.json)

- **C001**：Meaty impact clang with slight elemental shimmer

### [G053_sfx_007](G053_sfx_007.json)

- **C001**：Warm rising melody as a companion is collected

### [G053_sfx_008](G053_sfx_008.json)

- **C001**：Uplifting chime as thunder crystal hill unlocks

### [G053_sfx_009](G053_sfx_009.json)

- **C001**：Flower slope morning: songbirds
- **C002**：breeze through grass
- **C003**：distant creek

### [G053_sfx_010](G053_sfx_010.json)

- **C001**：Creek bay: running shallow water
- **C002**：reed rustle
- **C003**：occasional warble

### [G053_cg_001](G053_cg_001.json)

- **C001**：Misty morning over a flower slope
- **C002**：a field researcher shoulders a satchel and steps from a research station
- **C003**：three domain outlines in the mist
- **C004**：matching bound art style
- **C005**：cinematic
- **C006**：no text

### [G053_cg_002](G053_cg_002.json)

- **C001**：A hill trail lights up as the researcher tops the ridge
- **C002**：the amber silhouette of a thunder crystal beast emerges from fog
- **C003**：matching bound reference
- **C004**：cinematic
- **C005**：no text

### [G053_cg_003](G053_cg_003.json)

- **C001**：Inside the research station a report cover is stamped
- **C002**：conclusion text follows the verified hypothesis
- **C003**：outside creatures roam at ease
- **C004**：matching bound art style
- **C005**：cinematic
- **C006**：no text

