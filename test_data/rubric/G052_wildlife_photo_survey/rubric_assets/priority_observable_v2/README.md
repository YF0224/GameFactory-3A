# G052_wildlife_photo_survey — priority 资产需求 rubric 修订 v2

本目录是独立修订版；旧 `../rubric.json`、`../per_asset/` 及历史分数均保留。
游戏内索引：`../priority_rubric_current.json`。仅包含 priority gen 对应任务，不代表其他资产任务也已修订。
第一列保留可观察的主体、部件、形状、色彩、材质、相对布局、动作/事件及声音内容；精确坐标、尺寸、时长、速度、计数和技术参数只作来源/诊断。
已有逐资产文件的第二/三维原样保留；自然音效与T-pose补充的是此前缺失的rubric草稿，不是历史有效分数。
本版尚未逐项人工审核/最终冻结，也未自动切换生产 evaluator 或重新评测。采用新 schema，必须显式选择并适配，禁止混用旧分数。

| 类型 | 任务数 |
|---|---:|
| 3D Object | 1 |
| 3D Scene | 1 |
| Audio | 9 |
| CG Video | 2 |

## 第一列逐任务预览

以下仅展示计分目标；完整原文、定性投影记录、排除项、判分锚点和第二/三维见对应 JSON。

### [G052_wildlife_photo_survey_obj_003](G052_wildlife_photo_survey_obj_003.json)

- **C001**：Tiny warm-brown reed warbler perched gripping a reed stem
- **C002**：head tilted mid-song
- **C003**：stylized realistic

### [G052_scene_001](G052_scene_001.json)

- **C001**：Dawn wetland: reed belts
- **C002**：shallow forage flats
- **C003**：a slow water channel with otter bank dens
- **C004**：multiple observation blinds
- **C005**：morning mist
- **C006**：green and pale-gold palette
- **C007**：stylized realistic
- **C008**：湿地区域包含芦苇带、浅滩与水道
- 审查提示：no_literal_asset_mention_in_general

### [G052_sfx_001](G052_sfx_001.json)

- **C001**：Soft cloth snap as camera viewfinder raises

### [G052_sfx_002](G052_sfx_002.json)

- **C001**：Quiet zoom lens tick

### [G052_sfx_003](G052_sfx_003.json)

- **C001**：Gentle focus-lock beep

### [G052_sfx_004](G052_sfx_004.json)

- **C001**：Muffled low-noise shutter click

### [G052_sfx_005](G052_sfx_005.json)

- **C001**：Paper slide as a photo archives

### [G052_sfx_006](G052_sfx_006.json)

- **C001**：Sudden wing beats and a startled call

### [G052_sfx_007](G052_sfx_007.json)

- **C001**：Ink stamp on a survey report cover

### [G052_sfx_008](G052_sfx_008.json)

- **C001**：Low double click of an exhausted shutter

### [G052_sfx_009](G052_sfx_009.json)

- **C001**：Wetland dawn: insects
- **C002**：gentle water ripples
- **C003**：reed rustle
- **C004**：distant bird chorus

### [G052_cg_001](G052_cg_001.json)

- **C001**：Misty wetland at dawn
- **C002**：a surveyor walks a boardwalk with camera ready
- **C003**：an egret glides over shallows
- **C004**：an observation hut lamp glows
- **C005**：cinematic
- **C006**：no text

### [G052_cg_002](G052_cg_002.json)

- **C001**：Inside a survey station
- **C002**：sample photos spread across a desk
- **C003**：a report cover is stamped
- **C004**：outside the wetland wakes in gold light
- **C005**：cinematic
- **C006**：no text

