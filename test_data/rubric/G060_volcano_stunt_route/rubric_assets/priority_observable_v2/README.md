# G060_volcano_stunt_route — priority 资产需求 rubric 修订 v2

本目录是独立修订版；旧 `../rubric.json`、`../per_asset/` 及历史分数均保留。
游戏内索引：`../priority_rubric_current.json`。仅包含 priority gen 对应任务，不代表其他资产任务也已修订。
第一列保留可观察的主体、部件、形状、色彩、材质、相对布局、动作/事件及声音内容；精确坐标、尺寸、时长、速度、计数和技术参数只作来源/诊断。
已有逐资产文件的第二/三维原样保留；自然音效与T-pose补充的是此前缺失的rubric草稿，不是历史有效分数。
本版尚未逐项人工审核/最终冻结，也未自动切换生产 evaluator 或重新评测。采用新 schema，必须显式选择并适配，禁止混用旧分数。

| 类型 | 任务数 |
|---|---:|
| 3D Object | 3 |
| 3D Scene | 1 |
| Audio | 13 |
| CG Video | 4 |
| Motion | 3 |
| T-pose | 1 |

## 第一列逐任务预览

以下仅展示计分目标；完整原文、定性投影记录、排除项、判分锚点和第二/三维见对应 JSON。

### [G060_volcano_stunt_route_obj_001](G060_volcano_stunt_route_obj_001.json)

- **C001**：Original volcano-route stunt rider in a heat-vented charcoal jacket with ember-orange accent lines
- **C002**：armored gloves
- **C003**：goggles up
- **C004**：board under arm
- **C005**：stylized semi-realistic
- **C006**：rock-black and ember palette
- **C007**：T-pose

### [G060_volcano_stunt_route_obj_002](G060_volcano_stunt_route_obj_002.json)

- **C001**：Steep heat-warped steel-and-basalt launch ramp with ember vents at the lip and guide stripes
- **C002**：stylized semi-realistic

### [G060_volcano_stunt_route_obj_003](G060_volcano_stunt_route_obj_003.json)

- **C001**：Low training gantry rig of padded rollers
- **C002**：chime gates and score lamps along a stable side path
- **C003**：stylized semi-realistic

### [G060_scene_001](G060_scene_001.json)

- **C001**：Dormant volcano stunt route in multiple sections: ash-snow mixed gentle slope
- **C002**：cinder jump belt with glowing lava pools and warning markers
- **C003**：and a wide crater band with strong heat shimmer
- **C004**：rock-black and ember palette
- **C005**：stylized semi-realistic
- **C006**：分段路线具有检查点、分岔和熔岩池的可见表现；不验收距离或复位
- 审查提示：no_literal_asset_mention_in_general

### [G060_sfx_001](G060_sfx_001.json)

- **C001**：Board carving packed snow
- **C002**：sustained slide

### [G060_sfx_002](G060_sfx_002.json)

- **C001**：Looser gritty slide over cinder ash

### [G060_sfx_003](G060_sfx_003.json)

- **C001**：Spring pop off a jump lip

### [G060_sfx_004](G060_sfx_004.json)

- **C001**：Airy swoosh with a light body swish per aerial trick

### [G060_sfx_005](G060_sfx_005.json)

- **C001**：Rising arpeggio as the combo chain tiers up

### [G060_sfx_006](G060_sfx_006.json)

- **C001**：Compressed landing thud with snow puff

### [G060_sfx_007](G060_sfx_007.json)

- **C001**：Rapid soft ticks during the balance QTE

### [G060_sfx_008](G060_sfx_008.json)

- **C001**：Heavy tumbling slide and a distant whistle

### [G060_sfx_009](G060_sfx_009.json)

- **C001**：Angry lava sizzle and a short alarm tone

### [G060_sfx_010](G060_sfx_010.json)

- **C001**：Small patrol-post bell as a checkpoint logs

### [G060_sfx_011](G060_sfx_011.json)

- **C001**：Two-tone section horn at a segment gate

### [G060_sfx_012](G060_sfx_012.json)

- **C001**：Earnest certification fanfare with drum accents

### [G060_sfx_013](G060_sfx_013.json)

- **C001**：Dormant volcano: geothermal wind
- **C002**：rumbling fumaroles
- **C003**：distant rock falls

### [G060_cg_001](G060_cg_001.json)

- **C001**：Dawn on a dormant volcano
- **C002**：a certified rider takes a number plate from a patrol keeper
- **C003**：first jump ramp waiting beyond mixed snow and cinder
- **C004**：cinematic
- **C005**：no text

### [G060_cg_002](G060_cg_002.json)

- **C001**：Camera tops the big launch ramp looking down over a glowing lava pool
- **C002**：heat shimmer bending the view while the steady side path lights up far below
- **C003**：cinematic
- **C004**：no text

### [G060_cg_003](G060_cg_003.json)

- **C001**：a patrol post lamp the rider brushes off snow and ash and rises
- **C002**：a checkpoint pennant snaps open in the wind
- **C003**：cinematic
- **C004**：no text

### [G060_cg_004](G060_cg_004.json)

- **C001**：A certification dais unfolds in crater dawn light
- **C002**：ending frame variant: gold
- **C003**：silver or bronze badge raised / grey badge with a retry banner
- **C004**：cinematic
- **C005**：no text

### [G060_mot_001](G060_mot_001.json)

- **C001**：A rider cruises on a downhill board in a balanced tuck
- **C002**：动作具有可重复衔接的循环组织；不设循环时长或帧数门槛。
- **C003**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。

### [G060_mot_002](G060_mot_002.json)

- **C001**：A rider crouches then pops a jump off a ramp
- **C002**：board leveling
- **C003**：单次动作具有可辨起始、过程与结束；不设绝对时长门槛。
- **C004**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。

### [G060_mot_003](G060_mot_003.json)

- **C001**：A rider grabs the board and performs a full turn in mid-air
- **C002**：单次动作具有可辨起始、过程与结束；不设绝对时长门槛。
- **C003**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。

### [G060_tpose_001](G060_tpose_001.json)

- **C001**：Volcano stunt rider in heat-vented jacket with goggles and board under arm
- **C002**：clean symmetrical T-pose
- **C003**：stylized semi-realistic
- **C004**：角色以正面 T-pose 展示；按姿态含义辨认，不要求精确关节角度。

