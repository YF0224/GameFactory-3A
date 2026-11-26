# G055_inner_court_investigation — priority 资产需求 rubric 修订 v2

本目录是独立修订版；旧 `../rubric.json`、`../per_asset/` 及历史分数均保留。
游戏内索引：`../priority_rubric_current.json`。仅包含 priority gen 对应任务，不代表其他资产任务也已修订。
第一列保留可观察的主体、部件、形状、色彩、材质、相对布局、动作/事件及声音内容；精确坐标、尺寸、时长、速度、计数和技术参数只作来源/诊断。
已有逐资产文件的第二/三维原样保留；自然音效与T-pose补充的是此前缺失的rubric草稿，不是历史有效分数。
本版尚未逐项人工审核/最终冻结，也未自动切换生产 evaluator 或重新评测。采用新 schema，必须显式选择并适配，禁止混用旧分数。

| 类型 | 任务数 |
|---|---:|
| 3D Object | 4 |
| 3D Scene | 1 |
| Audio | 10 |
| CG Video | 5 |
| Motion | 4 |
| T-pose | 1 |

## 第一列逐任务预览

以下仅展示计分目标；完整原文、定性投影记录、排除项、判分锚点和第二/三维见对应 JSON。

### [G055_inner_court_investigation_obj_001](G055_inner_court_investigation_obj_001.json)

- **C001**：Original young court investigator Shen Zhiwei: understated dark-teal commoner robe with faint embroidery
- **C002**：hair in a plain bun with wooden pin
- **C003**：cloth shoes
- **C004**：sharp calm gaze
- **C005**：stylized semi-realistic ancient court style
- **C006**：vermilion-and-indigo palette
- **C007**：T-pose
- 审查提示：unresolved_spec_ref

### [G055_inner_court_investigation_obj_002](G055_inner_court_investigation_obj_002.json)

- **C001**：Small scorched silk incense pouch with charred rim and faint residual ash
- **C002**：tied with a cut thread
- **C003**：ancient court stylized

### [G055_inner_court_investigation_obj_003](G055_inner_court_investigation_obj_003.json)

- **C001**：Hand-bound duty-rota manuscript copy with thread binding holes
- **C002**：brush annotations and half-page tear
- **C003**：ancient court stylized

### [G055_inner_court_investigation_obj_004](G055_inner_court_investigation_obj_004.json)

- **C001**：Wax seal imprint fragment on cracked paper with a clear directional fissure pattern and vermilion stamp edge
- **C002**：ancient court stylized

### [G055_scene_001](G055_scene_001.json)

- **C001**：Original stylized ancient palace night quarter: vermilion columns
- **C002**：indigo eaves
- **C003**：paper lantern rows
- **C004**：screen corridors
- **C005**：rain slick courtyard stones and a secret passage mouth behind a wall panel
- **C006**：write-realist stylized
- **C007**：宫廷夜景作为氛围基线，区域名称与用途按原文解释；不强制引擎章节布局
- 审查提示：unresolved_spec_ref, no_literal_asset_mention_in_general

### [G055_sfx_001](G055_sfx_001.json)

- **C001**：Soft paper lift from a desk as evidence is taken

### [G055_sfx_002](G055_sfx_002.json)

- **C001**：Two-note ink-strength chime as evidence strengthens

### [G055_sfx_003](G055_sfx_003.json)

- **C001**：Fabric layers rustling as a disguise is donned

### [G055_sfx_004](G055_sfx_004.json)

- **C001**：Faint attention ping as a guard's gaze lingers

### [G055_sfx_005](G055_sfx_005.json)

- **C001**：Low watch drum marking raised district alert

### [G055_sfx_006](G055_sfx_006.json)

- **C001**：Muffled brief struggle sounds
- **C002**：non-lexical

### [G055_sfx_007](G055_sfx_007.json)

- **C001**：Soft jade ornament clink as a relation shifts

### [G055_sfx_008](G055_sfx_008.json)

- **C001**：Ink brush swipe with a short string swell

### [G055_sfx_009](G055_sfx_009.json)

- **C001**：Scroll unrolling with a soft xiao flute phrase

### [G055_sfx_010](G055_sfx_010.json)

- **C001**：Palace night: watchman's clapper far away
- **C002**：wind through eaves
- **C003**：lantern flame hum

### [G055_cg_001](G055_cg_001.json)

- **C001**：Palace walls at night
- **C002**：lantern rows light one by one
- **C003**：an investigator stands with a lamp on an outer corridor of Jinsè courtyard
- **C004**：watch drums sound as a roster is secretly swapped
- **C005**：vermilion and indigo night palette
- **C006**：cinematic
- **C007**：no text

### [G055_cg_002](G055_cg_002.json)

- **C001**：Morning book corridor of the protocol bureau
- **C002**：a duty-rota page corner lifts
- **C003**：wet ink and a registry stamp beside it
- **C004**：lanterns dim into daylight
- **C005**：cinematic
- **C006**：no text

### [G055_cg_003](G055_cg_003.json)

- **C001**：Dusk at the abandoned cold palace
- **C002**：patched wall beside fresh mortar
- **C003**：a tattered archive page lifts in dust light
- **C004**：cinematic
- **C005**：no text

### [G055_cg_004](G055_cg_004.json)

- **C001**：Under imperial desk lamps a tampered page and the original roster lie side by side
- **C002**：the wax crack direction matches the seal
- **C003**：rain outside stops abruptly
- **C004**：cinematic
- **C005**：no text

### [G055_cg_005](G055_cg_005.json)

- **C001**：A verdict scroll unrolls
- **C002**：ending frame follows one of the six ending groups
- **C003**：palace and key figures as in-game
- **C004**：cinematic
- **C005**：no text

### [G055_mot_001](G055_mot_001.json)

- **C001**：A court investigator stands idle
- **C002**：sleeve hand folded
- **C003**：lantern light swaying
- **C004**：动作具有可重复衔接的循环组织；不设循环时长或帧数门槛。
- **C005**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。
- 审查提示：unresolved_spec_ref

### [G055_mot_002](G055_mot_002.json)

- **C001**：A court investigator walks forward along a lamp-lit corridor
- **C002**：动作具有可重复衔接的循环组织；不设循环时长或帧数门槛。
- **C003**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。
- 审查提示：unresolved_spec_ref

### [G055_mot_003](G055_mot_003.json)

- **C001**：A court investigator crouches low
- **C002**：moving quietly behind a screen
- **C003**：动作具有可重复衔接的循环组织；不设循环时长或帧数门槛。
- **C004**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。
- 审查提示：unresolved_spec_ref

### [G055_mot_004](G055_mot_004.json)

- **C001**：A court investigator leans over a desk
- **C002**：carefully lifting a paper with both hands
- **C003**：单次动作具有可辨起始、过程与结束；不设绝对时长门槛。
- **C004**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。
- 审查提示：unresolved_spec_ref

### [G055_tpose_001](G055_tpose_001.json)

- **C001**：Young court investigator in dark-teal commoner robe with wooden hair pin
- **C002**：clean symmetrical T-pose
- **C003**：stylized semi-realistic ancient court style
- **C004**：角色以正面 T-pose 展示；按姿态含义辨认，不要求精确关节角度。
- 审查提示：unresolved_spec_ref

