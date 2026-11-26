# G017_lighthouse_prism — priority 资产需求 rubric 修订 v2

本目录是独立修订版；旧 `../rubric.json`、`../per_asset/` 及历史分数均保留。
游戏内索引：`../priority_rubric_current.json`。仅包含 priority gen 对应任务，不代表其他资产任务也已修订。
第一列保留可观察的主体、部件、形状、色彩、材质、相对布局、动作/事件及声音内容；精确坐标、尺寸、时长、速度、计数和技术参数只作来源/诊断。
已有逐资产文件的第二/三维原样保留；自然音效与T-pose补充的是此前缺失的rubric草稿，不是历史有效分数。
本版尚未逐项人工审核/最终冻结，也未自动切换生产 evaluator 或重新评测。采用新 schema，必须显式选择并适配，禁止混用旧分数。

| 类型 | 任务数 |
|---|---:|
| 3D Object | 1 |
| 3D Scene | 1 |
| Audio | 7 |
| CG Video | 2 |

## 第一列逐任务预览

以下仅展示计分目标；完整原文、定性投影记录、排除项、判分锚点和第二/三维见对应 JSON。

### [G017_lighthouse_prism_obj_003](G017_lighthouse_prism_obj_003.json)

- **C001**：Heavy brass beacon receiver lamp housing with colored glass ring and letter plaque
- **C002**：stylized hand-painted low-poly

### [G017_scene_001](G017_scene_001.json)

- **C001**：Top chamber of a seaside lighthouse at dusk
- **C002**：brass mirror arrays on a ring platform
- **C003**：foggy ocean through round windows
- **C004**：warm lamp glow against cool blue mist
- **C005**：stylized hand-painted
- **C006**：单屏光路谜题主题背景；不验收谜题逻辑
- 审查提示：no_literal_asset_mention_in_general

### [G017_sfx_001](G017_sfx_001.json)

- **C001**：Fine brass gear click as a mirror rotates one step

### [G017_sfx_002](G017_sfx_002.json)

- **C001**：Heavy metal shutter opening or closing thunk with slight reverb

### [G017_sfx_003](G017_sfx_003.json)

- **C001**：Two glass tones merging into one bright harmonic chime

### [G017_sfx_004](G017_sfx_004.json)

- **C001**：Warm confirmation tone as a beacon receiver lights up

### [G017_sfx_005](G017_sfx_005.json)

- **C001**：Short low buzz when light color mismatches a receiver

### [G017_sfx_006](G017_sfx_006.json)

- **C001**：Small uplifting brass fanfare when a puzzle group completes

### [G017_sfx_007](G017_sfx_007.json)

- **C001**：Waves against a lighthouse rock
- **C002**：distant fog horn every
- **C003**：night gulls
- **C004**：no music

### [G017_cg_001](G017_cg_001.json)

- **C001**：Dusk seascape
- **C002**：a letter blows through a lighthouse window
- **C003**：an apprentice keeper reads it and looks up at dark prism arrays
- **C004**：camera pushes toward the brass mirror ring
- **C005**：cinematic
- **C006**：no text

### [G017_cg_002](G017_cg_002.json)

- **C001**：Lighthouse beam sweeps alive layer by layer
- **C002**：light washes over dark waves
- **C003**：a distant ship answers with its horn
- **C004**：the apprentice waves from the gallery
- **C005**：cinematic
- **C006**：no text

