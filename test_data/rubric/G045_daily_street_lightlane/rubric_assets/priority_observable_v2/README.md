# G045_daily_street_lightlane — priority 资产需求 rubric 修订 v2

本目录是独立修订版；旧 `../rubric.json`、`../per_asset/` 及历史分数均保留。
游戏内索引：`../priority_rubric_current.json`。仅包含 priority gen 对应任务，不代表其他资产任务也已修订。
第一列保留可观察的主体、部件、形状、色彩、材质、相对布局、动作/事件及声音内容；精确坐标、尺寸、时长、速度、计数和技术参数只作来源/诊断。
已有逐资产文件的第二/三维原样保留；自然音效与T-pose补充的是此前缺失的rubric草稿，不是历史有效分数。
本版尚未逐项人工审核/最终冻结，也未自动切换生产 evaluator 或重新评测。采用新 schema，必须显式选择并适配，禁止混用旧分数。

| 类型 | 任务数 |
|---|---:|
| 3D Object | 15 |
| 3D Scene | 1 |
| Audio | 11 |
| CG Video | 4 |
| Motion | 6 |
| T-pose | 7 |

## 第一列逐任务预览

以下仅展示计分目标；完整原文、定性投影记录、排除项、判分锚点和第二/三维见对应 JSON。

### [G045_daily_street_lightlane_obj_001](G045_daily_street_lightlane_obj_001.json)

- **C001**：Cat-beastfolk resident player
- **C002**：light-beige fur
- **C003**：teal-green short jacket
- **C004**：deep-blue shorts and orange crossbody satchel
- **C005**：clean symmetrical full-body front-facing T-pose
- **C006**：semi-realistic stylized game character
- **C007**：arms extended
- **C008**：feet visible
- **C009**：plain studio background
- **C010**：one character only

### [G045_daily_street_lightlane_obj_002](G045_daily_street_lightlane_obj_002.json)

- **C001**：Neighborhood bicycle per reference image: orange low-step frame
- **C002**：two dark wheels with clear axle hierarchy
- **C003**：beige front basket and dark saddle
- **C004**：frame-and-wheels relationship readable
- **C005**：single object

### [G045_daily_street_lightlane_obj_003](G045_daily_street_lightlane_obj_003.json)

- **C001**：Two-story apartment building per reference image: grey-blue main block with exterior corridor and stairs
- **C002**：orange front door
- **C003**：laundry lines and shared garbage spot
- **C004**：collision-friendly blocky silhouette

### [G045_daily_street_lightlane_obj_004](G045_daily_street_lightlane_obj_004.json)

- **C001**：Neighborhood convenience store per reference image: teal-green awning sign
- **C002**：warm white doors and windows
- **C003**：visible shelves through glass
- **C004**：side parking spot
- **C005**：original branding-free facade

### [G045_daily_street_lightlane_obj_005](G045_daily_street_lightlane_obj_005.json)

- **C001**：Street maintenance and odd-job toolkit set per reference image: toolbox
- **C002**：broom
- **C003**：trash picker
- **C004**：folded crate and small lost-item pouch props
- **C005**：everyday readable silhouettes
- **C006**：single kit

### [G045_daily_street_lightlane_obj_006](G045_daily_street_lightlane_obj_006.json)

- **C001**：Friendly middle-aged neighbor with housework apron
- **C002**：cloth headwrap and small cleaning caddy in hand
- **C003**：sturdy everyday silhouette distinguishable from player
- **C004**：stylized low-poly
- **C005**：single character

### [G045_daily_street_lightlane_obj_007](G045_daily_street_lightlane_obj_007.json)

- **C001**：Young curious neighbor leaning slightly forward with round glasses and a shoulder satchel
- **C002**：energetic posture distinguishable from player
- **C003**：stylized low-poly
- **C004**：single character

### [G045_daily_street_lightlane_obj_008](G045_daily_street_lightlane_obj_008.json)

- **C001**：Retired strolling elder with light windbreaker and walking cane
- **C002**：relaxed friendly posture distinguishable from player
- **C003**：stylized low-poly
- **C004**：single character

### [G045_daily_street_lightlane_obj_009](G045_daily_street_lightlane_obj_009.json)

- **C001**：Young illustrator with beret
- **C002**：sketchbook under one arm and ink-stained fingerless gloves
- **C003**：thoughtful posture distinguishable from player
- **C004**：stylized low-poly
- **C005**：single character

### [G045_daily_street_lightlane_obj_010](G045_daily_street_lightlane_obj_010.json)

- **C001**：Stern but kind landlord with buttoned vest
- **C002**：ledger book in hand and key ring at belt
- **C003**：composed posture distinguishable from player
- **C004**：stylized low-poly
- **C005**：single character

### [G045_daily_street_lightlane_obj_011](G045_daily_street_lightlane_obj_011.json)

- **C001**：Convenience store clerk with striped apron
- **C002**：small name badge and handheld scanner pouch
- **C003**：welcoming posture distinguishable from player
- **C004**：stylized low-poly
- **C005**：single character

### [G045_daily_street_lightlane_obj_012](G045_daily_street_lightlane_obj_012.json)

- **C001**：Small old-town box delivery van with rounded cab
- **C002**：two visible axles and blank side panels
- **C003**：environment traffic only not player drivable
- **C004**：single object

### [G045_daily_street_lightlane_obj_013](G045_daily_street_lightlane_obj_013.json)

- **C001**：Old-style street lamp post with warm lantern head and blank lit panel
- **C002**：curved arm and cast base
- **C003**：night lane landmark
- **C004**：single object

### [G045_daily_street_lightlane_obj_014](G045_daily_street_lightlane_obj_014.json)

- **C001**：Wooden riverside park bench with slat backrest and armrests on small stone pads
- **C002**：rest interaction landmark
- **C003**：single object

### [G045_daily_street_lightlane_obj_015](G045_daily_street_lightlane_obj_015.json)

- **C001**：Retro neighborhood vending machine with lit front panel
- **C002**：blank branding and coin slot
- **C003**：shopping street fixture
- **C004**：single object

### [G045_scene_001](G045_scene_001.json)

- **C001**：Lantern-lane old town street scene at dusk-to-night: low-poly cartoon residential street with apartment
- **C002**：convenience store
- **C003**：shopping street stalls
- **C004**：riverside park path
- **C005**：back alleys with crates and rooftops reachable by stairs
- **C006**：street lamps turning on one by one
- **C007**：warm evening light
- **C008**：visual shell only
- **C009**：不同区域具有交互点与猫式捷径的空间表现
- **C010**：公寓与便利店之间存在路线连接；不验收距离、耗时和交互判定
- 审查提示：no_literal_asset_mention_in_general

### [G045_sfx_001](G045_sfx_001.json)

- **C001**：Soft neighborhood footstep on asphalt
- **C002**：two light cloth-shoe taps suitable for alternating loop while moving

### [G045_sfx_002](G045_sfx_002.json)

- **C001**：Classic bicycle bell ring
- **C002**：bright double ding with metal tail

### [G045_sfx_003](G045_sfx_003.json)

- **C001**：Convenience store checkout: register drawer pop with coin and receipt tick

### [G045_sfx_004](G045_sfx_004.json)

- **C001**：Wooden street door open and soft latch close
- **C002**：two-stage friendly cue

### [G045_sfx_005](G045_sfx_005.json)

- **C001**：Item pickup: light cloth-grab and small pouch rustle

### [G045_sfx_006](G045_sfx_006.json)

- **C001**：Task complete warm chime with journal page tick
- **C002**：also used for neighborhood remedy handling profile

### [G045_sfx_007](G045_sfx_007.json)

- **C001**：Neighbor notice alert: soft surprised vocal-less gasp tone with rising attention ping

### [G045_sfx_008](G045_sfx_008.json)

- **C001**：Day settle cue: gentle night fade with morning bird tick
- **C002**：also used for rent settlement profile

### [G045_sfx_009](G045_sfx_009.json)

- **C001**：Seamless daytime street ambience: light market chatter murmur
- **C002**：distant scooters and shop clatter
- **C003**：no distinct words

### [G045_sfx_010](G045_sfx_010.json)

- **C001**：Seamless dusk ambience: lamp turn-on hum
- **C002**：evening crowd thinning with distant kitchen sounds

### [G045_sfx_011](G045_sfx_011.json)

- **C001**：Seamless night ambience: crickets
- **C002**：occasional distant car pass and lamp buzz

### [G045_cg_001](G045_cg_001.json)

- **C001**：清晨街道
- **C002**：路灯依次熄灭
- **C003**：便利店开门
- **C004**：猫兽人居民走出公寓
- **C005**：路口人流与车灯开始流动
- **C006**：无 UI
- **C007**：无文字
- **C008**：无剪辑

### [G045_cg_002](G045_cg_002.json)

- **C001**：路灯依次点亮
- **C002**：街灯下人流与自行车流交织
- **C003**：商业街橱窗亮起
- **C004**：猫兽人主角剪影驻足路口
- **C005**：无 UI
- **C006**：无文字

### [G045_cg_003](G045_cg_003.json)

- **C001**：日历翻到第三日
- **C002**：桌上租金纸袋与硬币
- **C003**：窗外夜灯
- **C004**：房东门口的交互点亮起
- **C005**：无 UI
- **C006**：无文字

### [G045_cg_004](G045_cg_004.json)

- **C001**：二选一意象共用条目按真实结算结果择一播放：续约＝灯芯巷夜灯全亮
- **C002**：房间钥匙落定
- **C003**：纸箱收起
- **C004**：未续约＝搬家纸箱堆上门口
- **C005**：夜灯昏暗
- **C006**：主角回望街区
- **C007**：无 UI
- **C008**：无文字

### [G045_mot_001](G045_mot_001.json)

- **C001**：Cat-beastfolk resident idle: relaxed standing with slight breathing
- **C002**：tail sway and occasional head look around
- **C003**：动作具有可重复衔接的循环组织；不设循环时长或帧数门槛。
- **C004**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。

### [G045_mot_002](G045_mot_002.json)

- **C001**：Casual neighborhood walking gait
- **C002**：natural arm swing with tail counterbalance
- **C003**：动作具有可重复衔接的循环组织；不设循环时长或帧数门槛。
- **C004**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。

### [G045_mot_003](G045_mot_003.json)

- **C001**：Light jogging run
- **C002**：energetic forward lean
- **C003**：tail trailing
- **C004**：动作具有可重复衔接的循环组织；不设循环时长或帧数门槛。
- **C005**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。

### [G045_mot_004](G045_mot_004.json)

- **C001**：Small standing jump about apex with anticipation
- **C002**：air tuck and landing recovery
- **C003**：tail flick
- **C004**：单次动作具有可辨起始、过程与结束；不设绝对时长门槛。
- **C005**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。

### [G045_mot_005](G045_mot_005.json)

- **C001**：Reaching out and interacting with an object: extend arm
- **C002**：small pick or press gesture
- **C003**：then settle back
- **C004**：单次动作具有可辨起始、过程与结束；不设绝对时长门槛。
- **C005**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。

### [G045_mot_006](G045_mot_006.json)

- **C001**：Seated cycling pedal motion leaning slightly forward
- **C002**：hands on handlebar
- **C003**：tail flowing behind
- **C004**：动作具有可重复衔接的循环组织；不设循环时长或帧数门槛。
- **C005**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。

### [G045_tpose_001](G045_tpose_001.json)

- **C001**：Cat-beastfolk resident
- **C002**：clean symmetrical full-body front-facing T-pose
- **C003**：arms fully extended horizontally
- **C004**：feet visible
- **C005**：empty hands
- **C006**：semi-realistic stylized character
- **C007**：plain light-gray studio background
- **C008**：one character only

### [G045_tpose_002](G045_tpose_002.json)

- **C001**：Middle-aged neighbor in clean symmetrical T-pose
- **C002**：housework apron and cloth headwrap
- **C003**：empty hands
- **C004**：full body front view
- **C005**：plain background
- **C006**：角色以正面 T-pose 展示；按姿态含义辨认，不要求精确关节角度。

### [G045_tpose_003](G045_tpose_003.json)

- **C001**：Young curious neighbor in clean symmetrical T-pose
- **C002**：round glasses and shoulder satchel
- **C003**：empty hands
- **C004**：full body front view
- **C005**：plain background
- **C006**：角色以正面 T-pose 展示；按姿态含义辨认，不要求精确关节角度。

### [G045_tpose_004](G045_tpose_004.json)

- **C001**：Retired strolling elder in clean symmetrical T-pose
- **C002**：light windbreaker and walking cane set aside
- **C003**：empty hands
- **C004**：full body front view
- **C005**：plain background
- **C006**：角色以正面 T-pose 展示；按姿态含义辨认，不要求精确关节角度。

### [G045_tpose_005](G045_tpose_005.json)

- **C001**：Young illustrator in clean symmetrical T-pose
- **C002**：beret and fingerless gloves
- **C003**：sketchbook set aside
- **C004**：empty hands
- **C005**：full body front view
- **C006**：plain background
- **C007**：角色以正面 T-pose 展示；按姿态含义辨认，不要求精确关节角度。

### [G045_tpose_006](G045_tpose_006.json)

- **C001**：Landlord in clean symmetrical T-pose
- **C002**：buttoned vest and key ring at belt
- **C003**：ledger set aside
- **C004**：empty hands
- **C005**：full body front view
- **C006**：plain background
- **C007**：角色以正面 T-pose 展示；按姿态含义辨认，不要求精确关节角度。

### [G045_tpose_007](G045_tpose_007.json)

- **C001**：Convenience store clerk in clean symmetrical T-pose
- **C002**：striped apron and name badge
- **C003**：empty hands
- **C004**：full body front view
- **C005**：plain background
- **C006**：角色以正面 T-pose 展示；按姿态含义辨认，不要求精确关节角度。

