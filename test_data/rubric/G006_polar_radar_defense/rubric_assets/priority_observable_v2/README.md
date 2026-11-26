# G006_polar_radar_defense — priority 资产需求 rubric 修订 v2

本目录是独立修订版；旧 `../rubric.json`、`../per_asset/` 及历史分数均保留。
游戏内索引：`../priority_rubric_current.json`。仅包含 priority gen 对应任务，不代表其他资产任务也已修订。
第一列保留可观察的主体、部件、形状、色彩、材质、相对布局、动作/事件及声音内容；精确坐标、尺寸、时长、速度、计数和技术参数只作来源/诊断。
已有逐资产文件的第二/三维原样保留；自然音效与T-pose补充的是此前缺失的rubric草稿，不是历史有效分数。
本版尚未逐项人工审核/最终冻结，也未自动切换生产 evaluator 或重新评测。采用新 schema，必须显式选择并适配，禁止混用旧分数。

| 类型 | 任务数 |
|---|---:|
| 3D Object | 4 |
| 3D Scene | 1 |
| Audio | 13 |
| CG Video | 3 |

## 第一列逐任务预览

以下仅展示计分目标；完整原文、定性投影记录、排除项、判分锚点和第二/三维见对应 JSON。

### [G006_polar_radar_defense_obj_005](G006_polar_radar_defense_obj_005.json)

- **C001**：Standard rifle magazine pickup with faint warm glow ring at its base
- **C002**：half-buried in snow
- **C003**：single object

### [G006_polar_radar_defense_obj_007](G006_polar_radar_defense_obj_007.json)

- **C001**：Low corrugated steel snow barrier wall segment with packed drifts against its base
- **C002**：boundary decoration only
- **C003**：single object

### [G006_polar_radar_defense_obj_008](G006_polar_radar_defense_obj_008.json)

- **C001**：Freezing-metal warning lamp post with amber lens
- **C002**：knee-height marker posts around the station
- **C003**：single object

### [G006_polar_radar_defense_obj_009](G006_polar_radar_defense_obj_009.json)

- **C001**：First-person gloved hands pair in arctic mittens with exposed trigger finger
- **C002**：frost-stained parka cuffs
- **C003**：rigged for weapon grip poses

### [G006_scene_001](G006_scene_001.json)

- **C001**：Polar night defense field；雪原防卫场
- **C002**：snowfield centered on a glowing cyan radar core device；雷达核心位于场地中央
- **C003**：multiple enemy spawn gates on the boundary edges
- **C004**：drifting snow particles
- **C005**：low amber station lamps and radar antenna silhouettes under a dark aurora sky
- 审查提示：no_literal_asset_mention_in_general

### [G006_sfx_001](G006_sfx_001.json)

- **C001**：Cold sharp rifle shot with short mechanical action
- **C002**：arctic outdoor crack

### [G006_sfx_002](G006_sfx_002.json)

- **C001**：Brass shell casing tinkling onto packed snow

### [G006_sfx_003](G006_sfx_003.json)

- **C001**：Dry click of confirmation for a body or limb hit
- **C002**：short tick

### [G006_sfx_004](G006_sfx_004.json)

- **C001**：Bright distinct headshot ping
- **C002**：clearly different from body hit tick

### [G006_sfx_005](G006_sfx_005.json)

- **C001**：Low satisfying kill thump with a faint crystalline shatter tail

### [G006_sfx_006](G006_sfx_006.json)

- **C001**：Three-stage reload: magazine release clack
- **C002**：rounds seating rattle
- **C003**：charging handle slam

### [G006_sfx_007](G006_sfx_007.json)

- **C001**：Empty-chamber dry fire click

### [G006_sfx_008](G006_sfx_008.json)

- **C001**：Sonar-like radar sweep ping with faint static tail
- **C002**：station scanner

### [G006_sfx_009](G006_sfx_009.json)

- **C001**：Two-tone urgent station alarm
- **C002**：core under attack or wave incoming

### [G006_sfx_010](G006_sfx_010.json)

- **C001**：Muffled bite of corrosion contact with a pained grunt underneath

### [G006_sfx_011](G006_sfx_011.json)

- **C001**：Slow warm victory sting with faint aurora shimmer tone
- **C002**：dawn after the siege

### [G006_sfx_012](G006_sfx_012.json)

- **C001**：Low collapsing defeat tone with dying station drone

### [G006_sfx_013](G006_sfx_013.json)

- **C001**：Polar night windswept snowfield ambience
- **C002**：wind howl gusts with grain rattle and distant metal creak
- **C003**：seamless loop
- **C004**：no music

### [G006_cg_001](G006_cg_001.json)

- **C001**：极夜风雪中的霜锚站全景
- **C002**：雷达天线在雪幕里旋转
- **C003**：地平线上腐蚀体的暗影成群向站点涌来
- **C004**：站防员背上步枪推上最后一发弹匣
- **C005**：核心的青光在风雪中亮起
- **C006**：镜头自天际雪原推近至核心

### [G006_cg_002](G006_cg_002.json)

- **C001**：雷达屏幕绿色扫描线扫过
- **C002**：边缘敌群信号点逐批亮起
- **C003**：舱内红色警报灯旋转
- **C004**：站防员拉动枪机
- **C005**：快速切至风雪边界线上新一批腐蚀体的剪影

### [G006_cg_003](G006_cg_003.json)

- **C001**：胜负不同意象：胜利意象=风雪渐息
- **C002**：天际透出第一缕极光漫过雷达站
- **C003**：核心青光安然呼吸
- **C004**：失败意象=核心爆出暗红崩解
- **C005**：警报灯逐盏熄灭
- **C006**：雪原重归沉寂只剩风声
- 审查提示：multi_variant_cg_requires_delivery_convention, branch_delivery_review

