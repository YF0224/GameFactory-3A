# G015_garden_revival — priority 资产需求 rubric 修订 v2

本目录是独立修订版；旧 `../rubric.json`、`../per_asset/` 及历史分数均保留。
游戏内索引：`../priority_rubric_current.json`。仅包含 priority gen 对应任务，不代表其他资产任务也已修订。
第一列保留可观察的主体、部件、形状、色彩、材质、相对布局、动作/事件及声音内容；精确坐标、尺寸、时长、速度、计数和技术参数只作来源/诊断。
已有逐资产文件的第二/三维原样保留；自然音效与T-pose补充的是此前缺失的rubric草稿，不是历史有效分数。
本版尚未逐项人工审核/最终冻结，也未自动切换生产 evaluator 或重新评测。采用新 schema，必须显式选择并适配，禁止混用旧分数。

| 类型 | 任务数 |
|---|---:|
| 3D Object | 7 |
| 3D Scene | 1 |
| Audio | 13 |
| CG Video | 4 |
| Motion | 7 |
| T-pose | 1 |

## 第一列逐任务预览

以下仅展示计分目标；完整原文、定性投影记录、排除项、判分锚点和第二/三维见对应 JSON。

### [G015_garden_revival_obj_001](G015_garden_revival_obj_001.json)

- **C001**：Bipedal underground garden maintenance researcher with utility backpack
- **C002**：tool gloves and warm-lit helmet lamp
- **C003**：readable silhouette from side view
- **C004**：single character

### [G015_garden_revival_obj_002](G015_garden_revival_obj_002.json)

- **C001**：Single sealed ability equipment pod with glowing seal ring and openable hatch
- **C002**：three pods recolor per ability
- **C003**：single object

### [G015_garden_revival_obj_003](G015_garden_revival_obj_003.json)

- **C001**：Single tall seal gate frame with three distinct lock symbols (dash slit, double-jump riser, wall-grip claw) shown by relief material
- **C002**：single object

### [G015_garden_revival_obj_004](G015_garden_revival_obj_004.json)

- **C001**：Single floating photosynthesis crystal
- **C002**：glowing faceted gem with vine base
- **C003**：collectible with unique silhouette
- **C004**：single object

### [G015_garden_revival_obj_005](G015_garden_revival_obj_005.json)

- **C001**：Single garden record save terminal with green confirm ring and holo panel socket
- **C002**：state shown by material
- **C003**：single object

### [G015_garden_revival_obj_006](G015_garden_revival_obj_006.json)

- **C001**：Single growth checkpoint lamp with plant-stem post and breathing growth light
- **C002**：lights when activated
- **C003**：single object

### [G015_garden_revival_obj_007](G015_garden_revival_obj_007.json)

- **C001**：Single hidden maintenance shortcut door in a mossy wall
- **C002**：slides open with a light band
- **C003**：state shown by geometry
- **C004**：single object

### [G015_scene_001](G015_scene_001.json)

- **C001**：Three connected underground garden layers: bright ground-level flower platforms
- **C002**：hanging vine walkways with light wells
- **C003**：dark root-depth caverns with a glowing core
- **C004**：seal gates
- **C005**：glowing crystals
- **C006**：checkpoint lamps and save terminals along the route
- **C007**：bioluminescent palette
- **C008**：有界区域互联，并有单向深入的空间组织
- **C009**：反向捷径门具有可见表现
- **C010**：具有冲刺裂隙、跳跃高台和相对的抓壁墙面
- **C011**：检查点、存档点和光合晶具有可见表现
- 审查提示：no_literal_asset_mention_in_general

### [G015_sfx_001](G015_sfx_001.json)

- **C001**：Warm bloom chord as an ability pod opens and equipment bonds

### [G015_sfx_002](G015_sfx_002.json)

- **C001**：Muted seal chime hinting which ability a locked gate needs

### [G015_sfx_003](G015_sfx_003.json)

- **C001**：Sharp wind-cut dash burst with dust tail

### [G015_sfx_004](G015_sfx_004.json)

- **C001**：Springy double-jump pop with a light ring

### [G015_sfx_005](G015_sfx_005.json)

- **C001**：Glove cling grip on stone with a short scrape

### [G015_sfx_006](G015_sfx_006.json)

- **C001**：Crisp crystal collect chime with a soft vine hum

### [G015_sfx_007](G015_sfx_007.json)

- **C001**：Mossy door slide with light-band shimmer reveal

### [G015_sfx_008](G015_sfx_008.json)

- **C001**：Two-note terminal save confirmation

### [G015_sfx_009](G015_sfx_009.json)

- **C001**：Warm rising checkpoint activation call

### [G015_sfx_010](G015_sfx_010.json)

- **C001**：Low reset pulse with rebuilding shimmer as an interval resets

### [G015_sfx_011](G015_sfx_011.json)

- **C001**：Grand revival wave swell as the garden core restarts

### [G015_sfx_012](G015_sfx_012.json)

- **C001**：Underground garden breathing ambience loop
- **C002**：soft bioluminescent hum
- **C003**：no seam artifacts

### [G015_sfx_013](G015_sfx_013.json)

- **C001**：Cavern water drip echo ambience loop
- **C002**：sparse and calm

### [G015_cg_001](G015_cg_001.json)

- **C001**：镜头随维护研究员沿检修井下潜
- **C002**：掠过枯萎的花圃平台与熄灭的生长灯标
- **C003**：停在深处微光中的生长核心
- **C004**：无剪辑
- **C005**：无 UI
- **C006**：无文字

### [G015_cg_002](G015_cg_002.json)

- **C001**：封存装备舱开启
- **C002**：能力装备在研究员身上合体点亮（冲刺靴/跳簧/抓壁爪其一）
- **C003**：对应门禁符号在远处闪现

### [G015_cg_003](G015_cg_003.json)

- **C001**：旧区墙面滑开检修暗道
- **C002**：光带沿暗道贯通到后区
- **C003**：研究员回望新旧两条路径的分岔

### [G015_cg_004](G015_cg_004.json)

- **C001**：成败不同意象：胜利=生长核心重启
- **C002**：复苏波沿园区扩散
- **C003**：植物逐层回绿
- **C004**：记录仪写下完成
- **C005**：失败=只读快照展示后园区光点收拢
- **C006**：记录仪合上
- 审查提示：multi_variant_cg_requires_delivery_convention, branch_delivery_review

### [G015_mot_001](G015_mot_001.json)

- **C001**：Readable side-view run loop for the researcher with backpack sway
- **C002**：动作具有可重复衔接的循环组织；不设循环时长或帧数门槛。
- **C003**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。

### [G015_mot_002](G015_mot_002.json)

- **C001**：Arc jump readable takeoff-air-landing with knee tuck
- **C002**：单次动作具有可辨起始、过程与结束；不设绝对时长门槛。
- **C003**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。

### [G015_mot_003](G015_mot_003.json)

- **C001**：Second jump triggered at apex with a spring twist
- **C002**：readable mid-air boost
- **C003**：单次动作具有可辨起始、过程与结束；不设绝对时长门槛。
- **C004**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。

### [G015_mot_004](G015_mot_004.json)

- **C001**：Fast forward dash with body lean and trail-ready pose
- **C002**：单次动作具有可辨起始、过程与结束；不设绝对时长门槛。
- **C003**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。

### [G015_mot_005](G015_mot_005.json)

- **C001**：Wall grab
- **C002**：slow slide
- **C003**：then kick-off jump to the opposite wall
- **C004**：readable contact poses
- **C005**：单次动作具有可辨起始、过程与结束；不设绝对时长门槛。
- **C006**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。

### [G015_mot_006](G015_mot_006.json)

- **C001**：Reach and press interaction with a terminal or pod
- **C002**：confirm nod
- **C003**：单次动作具有可辨起始、过程与结束；不设绝对时长门槛。
- **C004**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。

### [G015_mot_007](G015_mot_007.json)

- **C001**：Recover from a fall: crouch at checkpoint then rise back to exploration stance
- **C002**：单次动作具有可辨起始、过程与结束；不设绝对时长门槛。
- **C003**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。

### [G015_tpose_001](G015_tpose_001.json)

- **C001**：Front T-pose reference of the garden maintenance researcher
- **C002**：limbs separated
- **C003**：backpack clear of joints

