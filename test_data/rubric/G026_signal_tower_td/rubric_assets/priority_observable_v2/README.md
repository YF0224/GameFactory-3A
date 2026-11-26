# G026_signal_tower_td — priority 资产需求 rubric 修订 v2

本目录是独立修订版；旧 `../rubric.json`、`../per_asset/` 及历史分数均保留。
游戏内索引：`../priority_rubric_current.json`。仅包含 priority gen 对应任务，不代表其他资产任务也已修订。
第一列保留可观察的主体、部件、形状、色彩、材质、相对布局、动作/事件及声音内容；精确坐标、尺寸、时长、速度、计数和技术参数只作来源/诊断。
已有逐资产文件的第二/三维原样保留；自然音效与T-pose补充的是此前缺失的rubric草稿，不是历史有效分数。
本版尚未逐项人工审核/最终冻结，也未自动切换生产 evaluator 或重新评测。采用新 schema，必须显式选择并适配，禁止混用旧分数。

| 类型 | 任务数 |
|---|---:|
| 3D Object | 4 |
| 3D Scene | 1 |
| Audio | 12 |
| CG Video | 2 |

## 第一列逐任务预览

以下仅展示计分目标；完整原文、定性投影记录、排除项、判分锚点和第二/三维见对应 JSON。

### [G026_signal_tower_td_obj_006](G026_signal_tower_td_obj_006.json)

- **C001**：Flat rock build pad with corner brackets and etched grid mark
- **C002**：one-grid build slot
- **C003**：single object

### [G026_signal_tower_td_obj_007](G026_signal_tower_td_obj_007.json)

- **C001**：Single heavy crossbow bolt with fletching and copper tip
- **C002**：projectile prop
- **C003**：single object

### [G026_signal_tower_td_obj_008](G026_signal_tower_td_obj_008.json)

- **C001**：Round stone cannon shell with crack lines
- **C002**：projectile prop
- **C003**：single object

### [G026_signal_tower_td_obj_009](G026_signal_tower_td_obj_009.json)

- **C001**：Canyon gorge entrance arch with warning totems marking the enemy spawn point
- **C002**：single object

### [G026_scene_001](G026_scene_001.json)

- **C001**：Dry canyon with a single S-shaped wind-carved path () crossing the map
- **C002**：rock build pads along the path
- **C003**：signal relay base at the end
- **C004**：gorge entrance at the start
- **C005**：harsh noon light and drifting sand
- **C006**：固定路线呈 S 形
- **C007**：建造位置沿路线两侧分布
- 审查提示：no_literal_asset_mention_in_general

### [G026_sfx_001](G026_sfx_001.json)

- **C001**：Wooden ballista release with bolt whoosh over canyon air

### [G026_sfx_002](G026_sfx_002.json)

- **C001**：Heavy counterweight launch thump with stone whistle and impact boom

### [G026_sfx_003](G026_sfx_003.json)

- **C001**：Cool mist pulse with glass chime and condensation hiss

### [G026_sfx_004](G026_sfx_004.json)

- **C001**：Construction placement thunk with sand settle

### [G026_sfx_005](G026_sfx_005.json)

- **C001**：Deconstruct click with coin sweep

### [G026_sfx_006](G026_sfx_006.json)

- **C001**：Bolt impact into chitin with sand scatter tick

### [G026_sfx_007](G026_sfx_007.json)

- **C001**：Beetle collapse into loose sand with dust puff

### [G026_sfx_008](G026_sfx_008.json)

- **C001**：Two-tone signal station alarm with urgent second beat

### [G026_sfx_009](G026_sfx_009.json)

- **C001**：Wave banner horn with distant swarm chatter underneath

### [G026_sfx_010](G026_sfx_010.json)

- **C001**：Warm victory sting with beacon hum and settling wind

### [G026_sfx_011](G026_sfx_011.json)

- **C001**：Low defeat drone with signal decay hiss

### [G026_sfx_012](G026_sfx_012.json)

- **C001**：Canyon wind ambience loop with faint grain hiss and distant rock whistle
- **C002**：seamless loop
- **C003**：no seam artifacts

### [G026_cg_001](G026_cg_001.json)

- **C001**：峡谷全景：信号塔灯光依次点亮
- **C002**：荒漠爬行者群自谷口涌入
- **C003**：镜头自风蚀岩掠过空置建造格
- **C004**：停在信号塔基地
- **C005**：无 UI
- **C006**：无文字
- **C007**：无剪辑

### [G026_cg_002](G026_cg_002.json)

- **C001**：不同意象共用条目：胜利=信号光柱冲天
- **C002**：风暴过境
- **C003**：旗帜舒展
- **C004**：失败=信号熄灭
- **C005**：虫群漫过基地
- **C006**：灯光熄灭
- **C007**：无 UI
- **C008**：无文字
- 审查提示：multi_variant_cg_requires_delivery_convention, branch_delivery_review

