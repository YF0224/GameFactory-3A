# G016_theater_sorting — priority 资产需求 rubric 修订 v2

本目录是独立修订版；旧 `../rubric.json`、`../per_asset/` 及历史分数均保留。
游戏内索引：`../priority_rubric_current.json`。仅包含 priority gen 对应任务，不代表其他资产任务也已修订。
第一列保留可观察的主体、部件、形状、色彩、材质、相对布局、动作/事件及声音内容；精确坐标、尺寸、时长、速度、计数和技术参数只作来源/诊断。
已有逐资产文件的第二/三维原样保留；自然音效与T-pose补充的是此前缺失的rubric草稿，不是历史有效分数。
本版尚未逐项人工审核/最终冻结，也未自动切换生产 evaluator 或重新评测。采用新 schema，必须显式选择并适配，禁止混用旧分数。

| 类型 | 任务数 |
|---|---:|
| 3D Object | 1 |
| 3D Scene | 1 |
| Audio | 6 |
| CG Video | 2 |

## 第一列逐任务预览

以下仅展示计分目标；完整原文、定性投影记录、排除项、判分锚点和第二/三维见对应 JSON。

### [G016_theater_sorting_obj_003](G016_theater_sorting_obj_003.json)

- **C001**：Flat brass floor inlay marker ring with a glowing warm-gold disc and stage-light housing
- **C002**：stylized hand-painted low-poly

### [G016_scene_001](G016_scene_001.json)

- **C001**：Vintage single-screen theater interior at night
- **C002**：empty stage with heavy red curtains
- **C003**：backstage storage corridor and auditorium seats visible in soft spotlight
- **C004**：warm wood and stage-red palette
- **C005**：stylized hand-painted
- **C006**：俯视格状主题背景；不验收判定格
- 审查提示：no_literal_asset_mention_in_general

### [G016_sfx_001](G016_sfx_001.json)

- **C001**：Wooden crate sliding across worn stage boards
- **C002**：short dry creak
- **C003**：no music

### [G016_sfx_002](G016_sfx_002.json)

- **C001**：Bright small chime confirming a crate covers its goal marker

### [G016_sfx_003](G016_sfx_003.json)

- **C001**：Short low mechanical buzz for an illegal move rejection

### [G016_sfx_004](G016_sfx_004.json)

- **C001**：Reversed-feeling short whoosh as a move is rolled back

### [G016_sfx_005](G016_sfx_005.json)

- **C001**：Brief cheerful theater re-opening jingle with applause tail
- **C002**：no vocals

### [G016_sfx_006](G016_sfx_006.json)

- **C001**：Quiet empty theater at night
- **C002**：faint hall hum
- **C003**：distant stage rigging creaks
- **C004**：no music

### [G016_cg_001](G016_cg_001.json)

- **C001**：Night interior of an old theater
- **C002**：house lights turn on one by one
- **C003**：a small boxy brass robot pushes a prop crate across the empty stage toward a glowing gold marker
- **C004**：warm wood and stage-red palette
- **C005**：cinematic
- **C006**：no text

### [G016_cg_002](G016_cg_002.json)

- **C001**：Theater fully relit: stage
- **C002**：backstage and auditorium light up in sequence
- **C003**：an opening banner drops
- **C004**：the small brass robot bows center stage under a spotlight
- **C005**：cinematic
- **C006**：no text

