# G059_observatory_pinball — priority 资产需求 rubric 修订 v2

本目录是独立修订版；旧 `../rubric.json`、`../per_asset/` 及历史分数均保留。
游戏内索引：`../priority_rubric_current.json`。仅包含 priority gen 对应任务，不代表其他资产任务也已修订。
第一列保留可观察的主体、部件、形状、色彩、材质、相对布局、动作/事件及声音内容；精确坐标、尺寸、时长、速度、计数和技术参数只作来源/诊断。
已有逐资产文件的第二/三维原样保留；自然音效与T-pose补充的是此前缺失的rubric草稿，不是历史有效分数。
本版尚未逐项人工审核/最终冻结，也未自动切换生产 evaluator 或重新评测。采用新 schema，必须显式选择并适配，禁止混用旧分数。

| 类型 | 任务数 |
|---|---:|
| 3D Object | 2 |
| 3D Scene | 1 |
| Audio | 11 |
| CG Video | 3 |

## 第一列逐任务预览

以下仅展示计分目标；完整原文、定性投影记录、排除项、判分锚点和第二/三维见对应 JSON。

### [G059_observatory_pinball_obj_001](G059_observatory_pinball_obj_001.json)

- **C001**：Chrome-and-pearl pinball with tiny embedded star flecks
- **C002**：clean brass-era look

### [G059_observatory_pinball_obj_003](G059_observatory_pinball_obj_003.json)

- **C001**：Pair of brass-capped pinball flipper assemblies with pivot pins and spring mounts
- **C002**：brass-era look

### [G059_scene_001](G059_scene_001.json)

- **C001**：Observatory exhibit hall at night housing a single brass star-chart pinball table: tilted playfield with star-rail lamp bands
- **C002**：comet lane and planet orbit targets
- **C003**：deep-blue and brass palette
- **C004**：stylized
- **C005**：倾斜台面具有靶标、发射轨道与返回通道的可见表现；不验收判定
- 审查提示：no_literal_asset_mention_in_general

### [G059_sfx_001](G059_sfx_001.json)

- **C001**：Ratcheting plunger wind-up

### [G059_sfx_002](G059_sfx_002.json)

- **C001**：Spring launch pop

### [G059_sfx_003](G059_sfx_003.json)

- **C001**：Brass medallion ding on target hit

### [G059_sfx_004](G059_sfx_004.json)

- **C001**：Rising short chime as a chain progresses

### [G059_sfx_005](G059_sfx_005.json)

- **C001**：Bright multiplier up-chime

### [G059_sfx_006](G059_sfx_006.json)

- **C001**：Layered starlight choir as two extra balls enter

### [G059_sfx_007](G059_sfx_007.json)

- **C001**：Glissando down the return lane

### [G059_sfx_008](G059_sfx_008.json)

- **C001**：Muffled drain drop under the table

### [G059_sfx_009](G059_sfx_009.json)

- **C001**：Two overlapped drain thuds with one settle tone

### [G059_sfx_010](G059_sfx_010.json)

- **C001**：Grand observatory record bell

### [G059_sfx_011](G059_sfx_011.json)

- **C001**：Quiet exhibit hall: machine hum
- **C002**：faint gallery reverb
- **C003**：night wind outside

### [G059_cg_001](G059_cg_001.json)

- **C001**：A brass star-chart pinball table in a night observatory hall
- **C002**：camera glides along lit star-rail bands as a single pearl ball rolls onto the launch rail
- **C003**：deep-blue and brass
- **C004**：cinematic
- **C005**：no text

### [G059_cg_002](G059_cg_002.json)

- **C001**：Three comet targets link into a light trail
- **C002**：two new balls slide down from the star rail as the table lamps blaze to full
- **C003**：cinematic
- **C004**：no text

### [G059_cg_003](G059_cg_003.json)

- **C001**：Table lamp bands settle tier by tier to the final multiplier
- **C002**：achieved: a star chart unfolds above the playfield
- **C003**：failed: lamps dim warmly
- **C004**：cinematic
- **C005**：no text
- 审查提示：multi_variant_cg_requires_delivery_convention, branch_delivery_review

