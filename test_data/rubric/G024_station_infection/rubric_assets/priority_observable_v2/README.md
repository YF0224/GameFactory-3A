# G024_station_infection — priority 资产需求 rubric 修订 v2

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

### [G024_station_infection_obj_005](G024_station_infection_obj_005.json)

- **C001**：Single station alarm column with stacked pulse lamps and clean housing
- **C002**：alarm state readable from management view
- **C003**：single object

### [G024_station_infection_obj_006](G024_station_infection_obj_006.json)

- **C001**：Single wall-mounted security disposal projector with targeting lens and three-step charge ring
- **C002**：disposal beam emitter
- **C003**：single object

### [G024_scene_001](G024_scene_001.json)

- **C001**：Single-level closed ecological station: corridor spine plus public cultivation bay
- **C002**：six-slot isolation pod rack at one end
- **C003**：patrol walkways
- **C004**：ventilation glow and plant racks
- **C005**：clean lab palette with bioluminescent accents
- **C006**：单层封闭生态站
- **C007**：舱段走廊与公共区相连
- 审查提示：no_literal_asset_mention_in_general

### [G024_sfx_001](G024_sfx_001.json)

- **C001**：Pathogen scanner sweep tone with result chirp

### [G024_sfx_002](G024_sfx_002.json)

- **C001**：Two-note positive detection marker as an infection is confirmed

### [G024_sfx_003](G024_sfx_003.json)

- **C001**：Sealed barrier hum as isolation completes

### [G024_sfx_004](G024_sfx_004.json)

- **C001**：Short denial buzz when the isolation bay is full

### [G024_sfx_005](G024_sfx_005.json)

- **C001**：Disposal beam pulse per discrete click
- **C002**：charge step

### [G024_sfx_006](G024_sfx_006.json)

- **C001**：Resolving chime as the converted entity dissolves after the third hit

### [G024_sfx_007](G024_sfx_007.json)

- **C001**：Rising conversion alarm as a member turns hostile

### [G024_sfx_008](G024_sfx_008.json)

- **C001**：Severe outbreak alarm for the over-eight active infection failure

### [G024_sfx_009](G024_sfx_009.json)

- **C001**：Clean victory chime as the shift ends with zero active infections

### [G024_sfx_010](G024_sfx_010.json)

- **C001**：Low containment-failure tone with station lockdown rumble

### [G024_sfx_011](G024_sfx_011.json)

- **C001**：Closed ecological station ambience loop: ventilation hum
- **C002**：cultivation pump rhythm
- **C003**：faint plant rustle
- **C004**：no seam artifacts

### [G024_cg_001](G024_cg_001.json)

- **C001**：生态站内景：巡检指示灯逐盏亮起
- **C002**：成员的红标警报灯忽然亮起又熄灭
- **C003**：镜头扫过检测仪与隔离舱
- **C004**：停在轮值钟 的刻度上
- **C005**：无剪辑
- **C006**：无 UI
- **C007**：无文字

### [G024_cg_002](G024_cg_002.json)

- **C001**：俯视走廊：巡游成员擦肩而过
- **C002**：不可见的涟漪从潜伏者扩散到邻近成员
- **C003**：红线在两人卡片间一闪即隐
- **C004**：检测仪红灯初亮
- **C005**：不得标出未检测成员的潜伏真值

### [G024_cg_003](G024_cg_003.json)

- **C001**：胜负不同意象：胜利=全站绿灯逐段恢复
- **C002**：隔离舱面板归零
- **C003**：培育舱重新亮起
- **C004**：失败=红灯全开
- **C005**：站体熔断门落下
- **C006**：轮值钟停在超限刻度
- 审查提示：multi_variant_cg_requires_delivery_convention, branch_delivery_review

