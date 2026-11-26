# G048_polar_return_trek — priority 资产需求 rubric 修订 v2

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

### [G048_polar_return_trek_obj_002](G048_polar_return_trek_obj_002.json)

- **C001**：Slim expedition route flag: orange pennant on a wire-core stake with ice crusting
- **C002**：stylized semi-realistic

### [G048_scene_001](G048_scene_001.json)

- **C001**：Vast polar icefield under gale
- **C002**：wind-carved snow ridges
- **C003**：frozen river shortcut with cracked ice patches
- **C004**：a distant research station glow on the horizon
- **C005**：white-blue palette with amber lights
- **C006**：stylized semi-realistic
- **C007**：分段返程路线具有庇护所、分岔与破冰点的可见表现
- 审查提示：no_literal_asset_mention_in_general

### [G048_sfx_001](G048_sfx_001.json)

- **C001**：Crunching snow footsteps at walking pace

### [G048_sfx_002](G048_sfx_002.json)

- **C001**：Lighter crisp footsteps on ice

### [G048_sfx_003](G048_sfx_003.json)

- **C001**：Stake punching into packed snow

### [G048_sfx_004](G048_sfx_004.json)

- **C001**：Match flare then steady fuel-block flame

### [G048_sfx_005](G048_sfx_005.json)

- **C001**：Sharp ice sheet crack and water splash

### [G048_sfx_006](G048_sfx_006.json)

- **C001**：Low pulsing device alarm for hypothermia

### [G048_sfx_007](G048_sfx_007.json)

- **C001**：Fast urgent device alarm for body failure

### [G048_sfx_008](G048_sfx_008.json)

- **C001**：Long single alarm tone for frostbite

### [G048_sfx_009](G048_sfx_009.json)

- **C001**：Faint data-sensor beep as records take cold damage

### [G048_sfx_010](G048_sfx_010.json)

- **C001**：Muffled station bell through thinning wind

### [G048_sfx_011](G048_sfx_011.json)

- **C001**：Howling polar gale with gust swells and fine snow hiss

### [G048_cg_001](G048_cg_001.json)

- **C001**：Polar station window with storm clouds gathering
- **C002**：an observer packs data disks into a satchel
- **C003**：glances at an aurora photo
- **C004**：and pushes out into the wind
- **C005**：cinematic
- **C006**：no text
- 审查提示：no_literal_asset_mention_in_general

### [G048_cg_002](G048_cg_002.json)

- **C001**：A wall of wind and snow sweeps over the ridge swallowing visibility
- **C002**：the observer leans into the gale
- **C003**：a shelter's warm light flickers far ahead
- **C004**：cinematic
- **C005**：no text

### [G048_cg_003](G048_cg_003.json)

- **C001**：The gale eases
- **C002**：station lights turn on one by one
- **C003**：the observer hands over a data disk as faint aurora unfolds in the night sky
- **C004**：cinematic
- **C005**：no text

