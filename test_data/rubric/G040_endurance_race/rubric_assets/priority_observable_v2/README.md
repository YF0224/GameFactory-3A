# G040_endurance_race — priority 资产需求 rubric 修订 v2

本目录是独立修订版；旧 `../rubric.json`、`../per_asset/` 及历史分数均保留。
游戏内索引：`../priority_rubric_current.json`。仅包含 priority gen 对应任务，不代表其他资产任务也已修订。
第一列保留可观察的主体、部件、形状、色彩、材质、相对布局、动作/事件及声音内容；精确坐标、尺寸、时长、速度、计数和技术参数只作来源/诊断。
已有逐资产文件的第二/三维原样保留；自然音效与T-pose补充的是此前缺失的rubric草稿，不是历史有效分数。
本版尚未逐项人工审核/最终冻结，也未自动切换生产 evaluator 或重新评测。采用新 schema，必须显式选择并适配，禁止混用旧分数。

| 类型 | 任务数 |
|---|---:|
| 3D Object | 9 |
| 3D Scene | 3 |
| Audio | 12 |
| CG Video | 4 |
| Motion | 1 |

## 第一列逐任务预览

以下仅展示计分目标；完整原文、定性投影记录、排除项、判分锚点和第二/三维见对应 JSON。

### [G040_endurance_race_obj_001](G040_endurance_race_obj_001.json)

- **C001**：07 number endurance prototype race car
- **C002**：clean side three-quarter profile
- **C003**：deep teal livery with white sail stripe
- **C004**：enclosed canopy LMP silhouette
- **C005**：four separate wheels with visible axle centers and realistic wheel clearance
- **C006**：no intersecting geometry
- **C007**：single centered vehicle on plain studio background

### [G040_endurance_race_obj_002](G040_endurance_race_obj_002.json)

- **C001**：Aggressive endurance race car in crimson red with black kite emblem livery
- **C002**：sharp nose and high rear wing
- **C003**：four separate wheels
- **C004**：same body type as player endurance prototype

### [G040_endurance_race_obj_003](G040_endurance_race_obj_003.json)

- **C001**：Conservative endurance race car in white-grey with wide albatross wing emblem livery
- **C002**：rounded engine cover and modest rear wing
- **C003**：four separate wheels
- **C004**：same body type as player endurance prototype

### [G040_endurance_race_obj_004](G040_endurance_race_obj_004.json)

- **C001**：Balanced endurance race car in slate blue-grey with white gull emblem livery
- **C002**：mid-height rear wing
- **C003**：four separate wheels
- **C004**：same body type as player endurance prototype

### [G040_endurance_race_obj_005](G040_endurance_race_obj_005.json)

- **C001**：Lemon-yellow race officials safety car per reference image with roof light bar and caution stripes
- **C002**：sturdy sedan silhouette
- **C003**：four separate wheels
- **C004**：single object

### [G040_endurance_race_obj_006](G040_endurance_race_obj_006.json)

- **C001**：Coastal pit lane building kit per reference image: modular pit garages with canvas awnings
- **C002**：tire barrier walls and stack
- **C003**：weathered white-steel panels with teal trim
- **C004**：single modular kit

### [G040_endurance_race_obj_007](G040_endurance_race_obj_007.json)

- **C001**：Pit stop equipment set: floor jack
- **C002**：fuel rig with hose
- **C003**：spare tire stack on rack and impact wrench on stand
- **C004**：weathered steel and rubber
- **C005**：single kit

### [G040_endurance_race_obj_008](G040_endurance_race_obj_008.json)

- **C001**：Start line light gantry with five red lamp housings on a graphite steel frame
- **C002**：blank lamp panels
- **C003**：single object

### [G040_endurance_race_obj_009](G040_endurance_race_obj_009.json)

- **C001**：Race podium stage with three stepped platforms
- **C002**：sponsor-free blank panels
- **C003**：gold accent trim and confetti-ready top surface
- **C004**：single object

### [G040_scene_001](G040_scene_001.json)

- **C001**：Stage 1 city street circuit
- **C002**：dry sunny afternoon
- **C003**：closed loop with corner sections
- **C004**：barriers and tire walls
- **C005**：old-town facades and grandstand
- **C006**：white pit lane entry
- **C007**：visual shell only
- **C008**：赛道具有弯道区段、非铺装区域和维修通道
- 审查提示：no_literal_asset_mention_in_general

### [G040_scene_002](G040_scene_002.json)

- **C001**：Stage 2 coastal boulevard circuit
- **C002**：after-rain overcast with wet reflective asphalt
- **C003**：closed loop with corner sections
- **C004**：sea-side guardrails
- **C005**：gull flocks
- **C006**：visual shell only
- **C007**：赛道具有弯道区段、非铺装区域和维修通道
- 审查提示：no_literal_asset_mention_in_general

### [G040_scene_003](G040_scene_003.json)

- **C001**：Stage 3 night harbor circuit
- **C002**：night rain with standing water reflections
- **C003**：closed loop with corner sections
- **C004**：container cranes silhouettes
- **C005**：dock lights and warehouses
- **C006**：visual shell only
- **C007**：赛道具有弯道区段、非铺装区域和维修通道
- **C008**：积水区域具有可见表现；不验收打滑阈值
- 审查提示：no_literal_asset_mention_in_general

### [G040_sfx_001](G040_sfx_001.json)

- **C001**：Race start light beep sequence
- **C002**：one short tone per red lamp then a bright green release tone

### [G040_sfx_002](G040_sfx_002.json)

- **C001**：Lap complete chime with two quick bright notes and short tail

### [G040_sfx_003](G040_sfx_003.json)

- **C001**：Car-to-car collision impact
- **C002**：mixed metal crunch and carbon shatter
- **C003**：short and punchy

### [G040_sfx_004](G040_sfx_004.json)

- **C001**：Penalty announcement beep
- **C002**：two firm descending tones for cut-track or unsafe overtake

### [G040_sfx_005](G040_sfx_005.json)

- **C001**：Team radio alert ping with switchable tone profiles: safety car yellow flag
- **C002**：green flag release and pit call reminder

### [G040_sfx_006](G040_sfx_006.json)

- **C001**：Low fuel warning tone
- **C002**：soft amber two-pulse alert suitable for repeating every

### [G040_sfx_007](G040_sfx_007.json)

- **C001**：Pit stop mechanic loop-ready burst: impact wrench bursts
- **C002**：jack clunk and fuel rig hiss in one take

### [G040_sfx_008](G040_sfx_008.json)

- **C001**：Championship victory sting
- **C002**：bright coastal horns with rising finish and sea-breeze tail

### [G040_sfx_009](G040_sfx_009.json)

- **C001**：Defeat sting
- **C002**：muted low brass with rain ambience tail
- **C003**：also used for retirement scene profile

### [G040_sfx_010](G040_sfx_010.json)

- **C001**：Seamless endurance engine loop at mid load
- **C002**：no manufacturer identity

### [G040_sfx_011](G040_sfx_011.json)

- **C001**：Seamless rain on tarmac ambience with distant sea surf
- **C002**：no thunder
- **C003**：no voices

### [G040_sfx_012](G040_sfx_012.json)

- **C001**：Seamless tire squeal loop that ramps in during slides and hard cornering
- **C002**：peaks on loss-of-control events

### [G040_cg_001](G040_cg_001.json)

- **C001**：涛澜湾清晨
- **C002**：原创赛车（深青 07 号、红隼、信天翁、灰鸥涂装）列队出场
- **C003**：维修区清场
- **C004**：老城街道/滨海大道/夜雨港口闪切
- **C005**：柠檬黄安全车就位
- **C006**：最后停在发车灯架
- **C007**：无 UI
- **C008**：无文字
- **C009**：无剪辑

### [G040_cg_002](G040_cg_002.json)

- **C001**：维修区俯视
- **C002**：千斤顶抬起深青 07 号赛车
- **C003**：换胎与加油枪动作
- **C004**：胎堆滚动
- **C005**：出站汇入雨后车流
- **C006**：无 UI
- **C007**：无文字

### [G040_cg_003](G040_cg_003.json)

- **C001**：黄旗挥动
- **C002**：柠檬黄安全车驶出领跑
- **C003**：雨幕扫过滨海赛道
- **C004**：车流压缩成列后绿旗恢复
- **C005**：无 UI
- **C006**：无文字

### [G040_cg_004](G040_cg_004.json)

- **C001**：不同意象共用条目按真实终局择一播放：登顶＝颁奖台喷洒
- **C002**：白帆车队举杯
- **C003**：未登顶＝颁奖灯照向别家
- **C004**：07 号车停在雨中
- **C005**：退赛＝赛车被推回维修区
- **C006**：灯光熄灭
- **C007**：无 UI
- **C008**：无文字
- 审查提示：branch_delivery_review

### [G040_endurance_race_mot_001](G040_endurance_race_mot_001.json)

- **C001**：Race car rolls into the pit
- **C002**：brakes
- **C003**：receives a tire-and-fuel service beat
- **C004**：then launches on the release signal
- **C005**：单次动作具有可辨起始、过程与结束；不设绝对时长门槛。
- 审查提示：duplicate_asset_requirement_entry

