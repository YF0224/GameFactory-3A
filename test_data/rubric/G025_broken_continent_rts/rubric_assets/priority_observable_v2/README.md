# G025_broken_continent_rts — priority 资产需求 rubric 修订 v2

本目录是独立修订版；旧 `../rubric.json`、`../per_asset/` 及历史分数均保留。
游戏内索引：`../priority_rubric_current.json`。仅包含 priority gen 对应任务，不代表其他资产任务也已修订。
第一列保留可观察的主体、部件、形状、色彩、材质、相对布局、动作/事件及声音内容；精确坐标、尺寸、时长、速度、计数和技术参数只作来源/诊断。
已有逐资产文件的第二/三维原样保留；自然音效与T-pose补充的是此前缺失的rubric草稿，不是历史有效分数。
本版尚未逐项人工审核/最终冻结，也未自动切换生产 evaluator 或重新评测。采用新 schema，必须显式选择并适配，禁止混用旧分数。

| 类型 | 任务数 |
|---|---:|
| 3D Object | 30 |
| 3D Scene | 1 |
| Audio | 12 |
| CG Video | 5 |
| Motion | 24 |
| T-pose | 2 |

## 第一列逐任务预览

以下仅展示计分目标；完整原文、定性投影记录、排除项、判分锚点和第二/三维见对应 JSON。

### [G025_broken_continent_rts_obj_001](G025_broken_continent_rts_obj_001.json)

- **C001**：Rescue militia: full humanoid
- **C002**：rounded closed dark-grey helmet with horizontal amber visor
- **C003**：sand-toned coveralls with teal shoulder guards
- **C004**：dark trousers and boots
- **C005**：teal boxy backpack
- **C006**：dangling repair tool
- **C007**：no ranged weapon upgrade
- **C008**：single character

### [G025_broken_continent_rts_obj_002](G025_broken_continent_rts_obj_002.json)

- **C001**：Quadruped base machine: low hexagonal pale armored torso
- **C002**：exactly four dark-grey jointed legs with wide triangular feet
- **C003**：single round teal sensor on the front
- **C004**：rectangular folded module on the back
- **C005**：no human face
- **C006**：four-legged silhouette preserved at higher marks
- **C007**：single object

### [G025_broken_continent_rts_obj_003](G025_broken_continent_rts_obj_003.json)

- **C001**：Remote observer: slender pear-shaped deep-blue torso
- **C002**：two legs two arms
- **C003**：smooth featureless head with three vertical mint-green sensor dots
- **C004**：asymmetric copper arc sensor rack behind the left shoulder
- **C005**：standing pose only
- **C006**：no flight parts
- **C007**：single character

### [G025_broken_continent_rts_obj_004](G025_broken_continent_rts_obj_004.json)

- **C001**：Swift armored wolf beast: four-legged wolf form with broad head
- **C002**：dark rust-red body
- **C003**：ivory layered mineral armor on shoulders and back
- **C004**：teal-glow flank markings
- **C005**：low long tail
- **C006**：not a bear
- **C007**：dog or mech
- **C008**：armor is appearance only
- **C009**：single object

### [G025_broken_continent_rts_obj_005](G025_broken_continent_rts_obj_005.json)

- **C001**：Giant-catcher aquatic predator fish: streamlined body with strong jaw for anti-titan duty
- **C002**：deep teal upper and pale belly
- **C003**：complete fins
- **C004**：water-movement only
- **C005**：single object

### [G025_broken_continent_rts_obj_006](G025_broken_continent_rts_obj_006.json)

- **C001**：Swift single-headed two-winged flying predator
- **C002**：long wingspan
- **C003**：grey-green body with signal-orange wing tips
- **C004**：readable talons
- **C005**：single object

### [G025_broken_continent_rts_obj_007](G025_broken_continent_rts_obj_007.json)

- **C001**：Ridge disaster body: colossal moving landmass silhouette with rocky shell and crevasse patterns
- **C002**：teal-green fissure glow
- **C003**：no face and no unit details
- **C004**：collider authored in engine
- **C005**：single object

### [G025_broken_continent_rts_obj_008](G025_broken_continent_rts_obj_008.json)

- **C001**：Light single-person flight transport rig with sling-load structure
- **C002**：canvas-grey body with amber indicator lamps
- **C003**：no weapon mounts
- **C004**：single character

### [G025_broken_continent_rts_obj_009](G025_broken_continent_rts_obj_009.json)

- **C001**：Compact engineering vehicle with folded crane arm and tool rack
- **C002**：sand-toned armor with teal hatch
- **C003**：no weapon appearance
- **C004**：single object

### [G025_broken_continent_rts_obj_010](G025_broken_continent_rts_obj_010.json)

- **C001**：Tall bipedal titan base body with layered rock-plated hide and heavy shoulders
- **C002**：single object

### [G025_broken_continent_rts_obj_011](G025_broken_continent_rts_obj_011.json)

- **C001**：Energy lord base humanoid with field-projector gauntlets and flowing cape of light
- **C002**：single character

### [G025_broken_continent_rts_obj_012](G025_broken_continent_rts_obj_012.json)

- **C001**：Infected fusion base body: humanoid host overgrown with translucent fungal growths and bio-glow veins
- **C002**：hunched
- **C003**：no gore
- **C004**：single object

### [G025_broken_continent_rts_obj_013](G025_broken_continent_rts_obj_013.json)

- **C001**：Mycelium web tile module: flat fungal network mat with glowing strands
- **C002**：tiling edge for network growth
- **C003**：single object

### [G025_broken_continent_rts_obj_014](G025_broken_continent_rts_obj_014.json)

- **C001**：Aerial production platform: floating disc base with hangar bays
- **C002**：lift rotors and sensor crown
- **C003**：strategic production structure
- **C004**：single object

### [G025_broken_continent_rts_obj_015](G025_broken_continent_rts_obj_015.json)

- **C001**：Swarm insect base unit: sleek chitinous bipedal-insect hybrid drone with thin wings folded at rest
- **C002**：single object

### [G025_broken_continent_rts_obj_016](G025_broken_continent_rts_obj_016.json)

- **C001**：World editor core: floating faceted obelisk with orbiting terrain shards and energy seams
- **C002**：non-attackable abstract structure
- **C003**：no human features
- **C004**：single object

### [G025_broken_continent_rts_obj_017](G025_broken_continent_rts_obj_017.json)

- **C001**：Life-exchange device carried by C02: lantern-like apparatus with twin vitality chambers and amber conduits
- **C002**：attachable prop with visible charge state
- **C003**：single object

### [G025_broken_continent_rts_obj_018](G025_broken_continent_rts_obj_018.json)

- **C001**：Field generator weapon attachment: shoulder-mounted ring emitter with energy coils
- **C002**：attachable to humanoid units
- **C003**：modular accessory
- **C004**：single object

### [G025_broken_continent_rts_obj_019](G025_broken_continent_rts_obj_019.json)

- **C001**：Salvage infantry base body in patchwork armor with mismatched plates and scavenged gear
- **C002**：single character

### [G025_broken_continent_rts_obj_020](G025_broken_continent_rts_obj_020.json)

- **C001**：Creeping root segment: thick gnarled root piece with node joints and faint energy veins
- **C002**：extraction node readable
- **C003**：single object

### [G025_broken_continent_rts_obj_021](G025_broken_continent_rts_obj_021.json)

- **C001**：Adaptive machine production mother core: massive immobile hexagonal reactor core with data spires and reconstruction seams
- **C002**：strategic target
- **C003**：single object

### [G025_broken_continent_rts_obj_022](G025_broken_continent_rts_obj_022.json)

- **C001**：Swarm city node: clustered hive spire with link-antenna crown and hanging pods
- **C002**：population-capacity structure
- **C003**：single object

### [G025_broken_continent_rts_obj_023](G025_broken_continent_rts_obj_023.json)

- **C001**：Root expansion core: colossal buried heart with concentric growth rings and radiating root crown
- **C002**：non-killable strategic object
- **C003**：single object

### [G025_broken_continent_rts_obj_024](G025_broken_continent_rts_obj_024.json)

- **C001**：Environmental response node: raised dais with sheltering canopy frame and signal lattice
- **C002**：resident-cover structure
- **C003**：single object

### [G025_broken_continent_rts_obj_025](G025_broken_continent_rts_obj_025.json)

- **C001**：Companion detection module: compact sensor drone attachable to a hero slot
- **C002**：three-lens array with sweep light
- **C003**：modular accessory
- **C004**：single object

### [G025_broken_continent_rts_obj_026](G025_broken_continent_rts_obj_026.json)

- **C001**：Anti-air launcher attachment: shoulder-carried quad-tube launcher with radar stub
- **C002**：modular accessory for anti-air infantry
- **C003**：single object

### [G025_broken_continent_rts_obj_027](G025_broken_continent_rts_obj_027.json)

- **C001**：Long-range rail designator attachment: slender railgun with stabilizer fins and scope
- **C002**：modular accessory for the long-range expert
- **C003**：single object

### [G025_broken_continent_rts_obj_028](G025_broken_continent_rts_obj_028.json)

- **C001**：Lord heavy hammer attachment: oversized two-handed energy hammer with head capacitor
- **C002**：modular accessory for heavy-strike lords
- **C003**：single object

### [G025_broken_continent_rts_obj_029](G025_broken_continent_rts_obj_029.json)

- **C001**：Lure fungal strain: small immobile spore pod with lure-tendril crown and faint mist
- **C002**：abstract seduction effect only
- **C003**：no gore
- **C004**：single object

### [G025_broken_continent_rts_obj_030](G025_broken_continent_rts_obj_030.json)

- **C001**：Sedentary vine: rooted creeping vine cluster with thorned stems and area-hold posture
- **C002**：terrain-control flora
- **C003**：single object

### [G025_scene_001](G025_scene_001.json)

- **C001**：Broken continent RTS map: thirteen randomly stitched terrain regions (titan wastes, energy territory, machine zone, infection zone, disaster path, observation range, ecology zone, link zone, editor zone, exchange zone, dispatch zone, salvage zone, root zone) with faction bases
- **C002**：fog of war
- **C003**：seam conflict bands
- **C004**：drifting dust and disaster trails
- **C005**：不同区域以拼接方式组成地图，区域接缝可辨
- **C006**：装饰场景不代替导航、碰撞或战争迷雾机制验收
- 审查提示：no_literal_asset_mention_in_general

### [G025_sfx_001](G025_sfx_001.json)

- **C001**：Bright resource income tick with faction-neutral tone

### [G025_sfx_002](G025_sfx_002.json)

- **C001**：Two-stage technology unlock chime with data shimmer

### [G025_sfx_003](G025_sfx_003.json)

- **C001**：Uneasy infection alert with fungal undertone

### [G025_sfx_004](G025_sfx_004.json)

- **C001**：Deep disaster warning horn with ground rumble

### [G025_sfx_005](G025_sfx_005.json)

- **C001**：Global rule preview notice with ticking countdown

### [G025_sfx_006](G025_sfx_006.json)

- **C001**：Impact hit tick for combat damage with counter-match color ring

### [G025_sfx_007](G025_sfx_007.json)

- **C001**：Region unlock fanfare with terrain resolve

### [G025_sfx_008](G025_sfx_008.json)

- **C001**：Low root expansion rumble as the creep radius advances

### [G025_sfx_009](G025_sfx_009.json)

- **C001**：Grand strategic victory horn for the expedition objective

### [G025_sfx_010](G025_sfx_010.json)

- **C001**：Low expedition defeat tone with dust-down wind

### [G025_sfx_011](G025_sfx_011.json)

- **C001**：Broken continent wind ambience loop with faint dust storms
- **C002**：no seam artifacts

### [G025_sfx_012](G025_sfx_012.json)

- **C001**：Disaster zone ambience loop: distant grinding and sub-bass pressure

### [G025_cg_001](G025_cg_001.json)

- **C001**：破碎大陆全景：十三块漂移区域在灾变尘幕中缓缓错动
- **C002**：十四面旗帜在风中断续可见
- **C003**：灾害体的轮廓在地平线推进
- **C004**：无剪辑
- **C005**：无 UI
- **C006**：无文字

### [G025_cg_002](G025_cg_002.json)

- **C001**：所选阵营的基地在对应区域点亮
- **C002**：侦察单位与首批生产队列展开
- **C003**：开局目标横幅在画面上定格

### [G025_cg_003](G025_cg_003.json)

- **C001**：区域接缝的光带点亮
- **C002**：新区域的文明轮廓在迷雾中显形
- **C003**：解锁横幅标注区域名与解锁条件达成瞬间
- **C004**：不泄露未解锁区域信息

### [G025_cg_004](G025_cg_004.json)

- **C001**：两支异构阵营的单位在区域接缝相遇
- **C002**：克制关系以色框与伤害数字呈现
- **C003**：灾害或全局规则在远景介入

### [G025_cg_005](G025_cg_005.json)

- **C001**：胜负不同意象：胜利=远征目标达成光柱
- **C002**：所选阵营旗帜插上目标区域
- **C003**：大陆尘幕散开一角
- **C004**：失败=目标灰幕落下
- **C005**：基地灯火收拢
- **C006**：灾害体轮廓压近
- 审查提示：multi_variant_cg_requires_delivery_convention, branch_delivery_review

### [G025_mot_001](G025_mot_001.json)

- **C001**：Readable militia march loop with tool sway
- **C002**：动作具有可重复衔接的循环组织；不设循环时长或帧数门槛。
- **C003**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。

### [G025_mot_002](G025_mot_002.json)

- **C001**：Kneeling repair action with tool strokes
- **C002**：单次动作具有可辨起始、过程与结束；不设绝对时长门槛。
- **C003**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。

### [G025_mot_003](G025_mot_003.json)

- **C001**：Lifting a survivor to shoulder carry
- **C002**：单次动作具有可辨起始、过程与结束；不设绝对时长门槛。
- **C003**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。

### [G025_mot_004](G025_mot_004.json)

- **C001**：Militia falling to inactive state
- **C002**：单次动作具有可辨起始、过程与结束；不设绝对时长门槛。
- **C003**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。

### [G025_mot_005](G025_mot_005.json)

- **C001**：Smooth observer glide-walk loop with sensor rack steady
- **C002**：动作具有可重复衔接的循环组织；不设循环时长或帧数门槛。
- **C003**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。

### [G025_mot_006](G025_mot_006.json)

- **C001**：Observer field-cast attack with arm extension
- **C002**：单次动作具有可辨起始、过程与结束；不设绝对时长门槛。
- **C003**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。

### [G025_mot_007](G025_mot_007.json)

- **C001**：Observer flinch from a hit
- **C002**：单次动作具有可辨起始、过程与结束；不设绝对时长门槛。
- **C003**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。

### [G025_mot_008](G025_mot_008.json)

- **C001**：Observer collapsing to inactive state
- **C002**：单次动作具有可辨起始、过程与结束；不设绝对时长门槛。
- **C003**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。

### [G025_mot_009](G025_mot_009.json)

- **C001**：Heavy titan stomp loop with mass shift
- **C002**：动作具有可重复衔接的循环组织；不设循环时长或帧数门槛。
- **C003**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。

### [G025_mot_010](G025_mot_010.json)

- **C001**：Titan overhead slam attack
- **C002**：单次动作具有可辨起始、过程与结束；不设绝对时长门槛。
- **C003**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。

### [G025_mot_011](G025_mot_011.json)

- **C001**：Titan body flinch from a hit
- **C002**：单次动作具有可辨起始、过程与结束；不设绝对时长门槛。
- **C003**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。

### [G025_mot_012](G025_mot_012.json)

- **C001**：Titan heavy collapse
- **C002**：单次动作具有可辨起始、过程与结束；不设绝对时长门槛。
- **C003**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。

### [G025_mot_013](G025_mot_013.json)

- **C001**：Regal energy lord striding loop with cape sway
- **C002**：动作具有可重复衔接的循环组织；不设循环时长或帧数门槛。
- **C003**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。

### [G025_mot_014](G025_mot_014.json)

- **C001**：Energy lord two-handed field blast cast
- **C002**：单次动作具有可辨起始、过程与结束；不设绝对时长门槛。
- **C003**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。

### [G025_mot_015](G025_mot_015.json)

- **C001**：Energy lord stagger from a hit
- **C002**：单次动作具有可辨起始、过程与结束；不设绝对时长门槛。
- **C003**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。

### [G025_mot_016](G025_mot_016.json)

- **C001**：Energy lord falling with field dissipation
- **C002**：单次动作具有可辨起始、过程与结束；不设绝对时长门槛。
- **C003**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。

### [G025_mot_017](G025_mot_017.json)

- **C001**：Hunched infected host shamble loop with fungal sway
- **C002**：动作具有可重复衔接的循环组织；不设循环时长或帧数门槛。
- **C003**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。

### [G025_mot_018](G025_mot_018.json)

- **C001**：Infected host claw lunge attack
- **C002**：单次动作具有可辨起始、过程与结束；不设绝对时长门槛。
- **C003**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。

### [G025_mot_019](G025_mot_019.json)

- **C001**：Infected host recoil from a hit
- **C002**：单次动作具有可辨起始、过程与结束；不设绝对时长门槛。
- **C003**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。

### [G025_mot_020](G025_mot_020.json)

- **C001**：Infected host dissolving collapse
- **C002**：单次动作具有可辨起始、过程与结束；不设绝对时长门槛。
- **C003**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。

### [G025_mot_021](G025_mot_021.json)

- **C001**：Salvage infantry scavenger walk loop with plate rattle
- **C002**：动作具有可重复衔接的循环组织；不设循环时长或帧数门槛。
- **C003**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。

### [G025_mot_022](G025_mot_022.json)

- **C001**：Scrap rifle aim and fire
- **C002**：单次动作具有可辨起始、过程与结束；不设绝对时长门槛。
- **C003**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。

### [G025_mot_023](G025_mot_023.json)

- **C001**：Patchwork armor flinch
- **C002**：单次动作具有可辨起始、过程与结束；不设绝对时长门槛。
- **C003**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。

### [G025_mot_024](G025_mot_024.json)

- **C001**：Salvage infantry collapse
- **C002**：单次动作具有可辨起始、过程与结束；不设绝对时长门槛。
- **C003**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。

### [G025_tpose_001](G025_tpose_001.json)

- **C001**：Front T-pose of the rescue militia
- **C002**：closed helmet intact
- **C003**：limbs separated
- **C004**：tool clear of joints

### [G025_tpose_002](G025_tpose_002.json)

- **C001**：Front T-pose of the remote observer
- **C002**：sensor rack clear of shoulders

