# G027_dune_maze_td — priority 资产需求 rubric 修订 v2

本目录是独立修订版；旧 `../rubric.json`、`../per_asset/` 及历史分数均保留。
游戏内索引：`../priority_rubric_current.json`。仅包含 priority gen 对应任务，不代表其他资产任务也已修订。
第一列保留可观察的主体、部件、形状、色彩、材质、相对布局、动作/事件及声音内容；精确坐标、尺寸、时长、速度、计数和技术参数只作来源/诊断。
已有逐资产文件的第二/三维原样保留；自然音效与T-pose补充的是此前缺失的rubric草稿，不是历史有效分数。
本版尚未逐项人工审核/最终冻结，也未自动切换生产 evaluator 或重新评测。采用新 schema，必须显式选择并适配，禁止混用旧分数。

| 类型 | 任务数 |
|---|---:|
| 3D Object | 2 |
| 3D Scene | 1 |
| Audio | 13 |
| CG Video | 2 |

## 第一列逐任务预览

以下仅展示计分目标；完整原文、定性投影记录、排除项、判分锚点和第二/三维见对应 JSON。

### [G027_dune_maze_td_obj_002](G027_dune_maze_td_obj_002.json)

- **C001**：Single rammed-sand plank barrier wall with rope bindings and warning pennant
- **C002**：blocks an one-grid lane
- **C003**：top-down readable silhouette
- **C004**：single object

### [G027_dune_maze_td_obj_004](G027_dune_maze_td_obj_004.json)

- **C001**：Single desert ant burrow mound with dark entry hole and ring of excavated sand
- **C002**：single object

### [G027_scene_001](G027_scene_001.json)

- **C001**：Open desert sand field seen from above
- **C002**：west-edge ant burrow mound and east-edge oasis outpost base
- **C003**：three wind-driven sand ridges
- **C004**：dune grass and bleached rocks along the border
- **C005**：harsh noon light
- **C006**：开放沙地格状场地
- **C007**：蚁穴标志物位于西侧边缘，基地位于东侧边缘
- **C008**：沙丘具有可见表现；不验收移动逻辑
- 审查提示：no_literal_asset_mention_in_general

### [G027_sfx_001](G027_sfx_001.json)

- **C001**：Dry wooden ballista release with bolt whoosh and desert air

### [G027_sfx_002](G027_sfx_002.json)

- **C001**：Rammed sand plank wall slamming into sand with settle hiss

### [G027_sfx_003](G027_sfx_003.json)

- **C001**：Structure collapse into sand with coin sweep on top

### [G027_sfx_004](G027_sfx_004.json)

- **C001**：Dull rejection thud with brief sand puff
- **C002**：negative but soft

### [G027_sfx_005](G027_sfx_005.json)

- **C001**：Short rising shimmer tick marking a recalculated route

### [G027_sfx_006](G027_sfx_006.json)

- **C001**：Bolt impact into chitin with grain scatter tick

### [G027_sfx_007](G027_sfx_007.json)

- **C001**：Ant body collapsing into loose sand with dust puff

### [G027_sfx_008](G027_sfx_008.json)

- **C001**：Two-tone desert outpost alarm with urgent second beat

### [G027_sfx_009](G027_sfx_009.json)

- **C001**：Wave banner horn with distant ant chatter underneath

### [G027_sfx_010](G027_sfx_010.json)

- **C001**：Deep sand slide rumble with wind gust
- **C002**：slow decay

### [G027_sfx_011](G027_sfx_011.json)

- **C001**：Warm victory sting with flag flap and settling wind

### [G027_sfx_012](G027_sfx_012.json)

- **C001**：Low defeat drone with sand swallowing hiss

### [G027_sfx_013](G027_sfx_013.json)

- **C001**：Desert wind ambience loop with faint grain hiss and distant dune whistle
- **C002**：seamless loop
- **C003**：no seam artifacts

### [G027_cg_001](G027_cg_001.json)

- **C001**：荒漠正午：西缘蚁穴尘柱升起
- **C002**：沙蚁群自穴口涌出
- **C003**：镜头掠过空旷沙地与沙脊
- **C004**：停在东缘前哨基地的旗帜上
- **C005**：无 UI
- **C006**：无文字
- **C007**：无剪辑

### [G027_cg_002](G027_cg_002.json)

- **C001**：不同意象共用条目：胜利=蚁群绕开绿洲远去
- **C002**：基地旗帜舒展
- **C003**：日光转暖
- **C004**：失败=沙蚁涌入基地
- **C005**：水脉断流
- **C006**：沙尘掩埋哨站
- **C007**：无 UI
- **C008**：无文字
- 审查提示：multi_variant_cg_requires_delivery_convention, branch_delivery_review

