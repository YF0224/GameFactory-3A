# G050_aftermath_holdout — priority 资产需求 rubric 修订 v2

本目录是独立修订版；旧 `../rubric.json`、`../per_asset/` 及历史分数均保留。
游戏内索引：`../priority_rubric_current.json`。仅包含 priority gen 对应任务，不代表其他资产任务也已修订。
第一列保留可观察的主体、部件、形状、色彩、材质、相对布局、动作/事件及声音内容；精确坐标、尺寸、时长、速度、计数和技术参数只作来源/诊断。
已有逐资产文件的第二/三维原样保留；自然音效与T-pose补充的是此前缺失的rubric草稿，不是历史有效分数。
本版尚未逐项人工审核/最终冻结，也未自动切换生产 evaluator 或重新评测。采用新 schema，必须显式选择并适配，禁止混用旧分数。

| 类型 | 任务数 |
|---|---:|
| 3D Object | 1 |
| 3D Scene | 1 |
| Audio | 9 |
| CG Video | 4 |
| Motion | 4 |

## 第一列逐任务预览

以下仅展示计分目标；完整原文、定性投影记录、排除项、判分锚点和第二/三维见对应 JSON。

### [G050_aftermath_holdout_obj_001](G050_aftermath_holdout_obj_001.json)

- **C001**：Reinforced community gate barricade: sandbag line
- **C002**：timber brace frame and a hanging storm lamp
- **C003**：stylized semi-realistic

### [G050_scene_001](G050_scene_001.json)

- **C001**：Earthquake-damaged small community courtyard at dusk: two-story brick shelter with tarped roof
- **C002**：campfire
- **C003**：sandbag gate
- **C004**：ration shelves and a communal dining table
- **C005**：dust-grey palette with firelight
- **C006**：stylized semi-realistic
- **C007**：上下楼层组成基地
- **C008**：基地具有床位、储物间、工作台、门禁和餐桌
- 审查提示：no_literal_asset_mention_in_general

### [G050_sfx_001](G050_sfx_001.json)

- **C001**：Pencil scratch on paper as a task is assigned

### [G050_sfx_002](G050_sfx_002.json)

- **C001**：Double hammer thud reinforcing the gate

### [G050_sfx_003](G050_sfx_003.json)

- **C001**：Warm bowls and soft grateful chatter around food

### [G050_sfx_004](G050_sfx_004.json)

- **C001**：Careful rummaging through shelves and debris

### [G050_sfx_005](G050_sfx_005.json)

- **C001**：Sharp rotating alarm for a night raid

### [G050_sfx_006](G050_sfx_006.json)

- **C001**：Brief scuffle and grain sack dragged away

### [G050_sfx_007](G050_sfx_007.json)

- **C001**：Muted morning chime for a new day

### [G050_sfx_008](G050_sfx_008.json)

- **C001**：Distant convoy air-horn with crowd relief

### [G050_sfx_009](G050_sfx_009.json)

- **C001**：Quiet aftershock night: wind over rubble
- **C002**：distant dog bark
- **C003**：dying fire crackle

### [G050_cg_001](G050_cg_001.json)

- **C001**：Dawn over an earthquake-cracked community lane
- **C002**：a group leader steps out of a damaged two-story shelter
- **C003**：four residents look up from a campfire
- **C004**：cinematic
- **C005**：no text

### [G050_cg_002](G050_cg_002.json)

- **C001**：Night rain stops over the courtyard
- **C002**：residents count a ransacked storeroom
- **C003**：looter silhouettes lurk far away as the gate lamp lights up
- **C004**：cinematic
- **C005**：no text

### [G050_cg_003](G050_cg_003.json)

- **C001**：Light drizzle at dawn
- **C002**：survivors gather at the barricade
- **C003**：the leader looks down the road out of town
- **C004**：cinematic
- **C005**：no text

### [G050_cg_004](G050_cg_004.json)

- **C001**：Convoy lights sweep into the community
- **C002**：ending frame variant: residents boarding trucks / wounded helped away / empty shelter with dying fire
- **C003**：cinematic
- **C004**：no text

### [G050_mot_001](G050_mot_001.json)

- **C001**：An old craftsman hammers a brace plank with steady swings
- **C002**：动作具有可重复衔接的循环组织；不设循环时长或帧数门槛。
- **C003**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。
- 审查提示：no_literal_asset_mention_in_general

### [G050_mot_002](G050_mot_002.json)

- **C001**：A lean scout walks forward briskly
- **C002**：动作具有可重复衔接的循环组织；不设循环时长或帧数门槛。
- **C003**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。
- 审查提示：no_literal_asset_mention_in_general

### [G050_mot_003](G050_mot_003.json)

- **C001**：A young laborer lifts and walks with a supply crate
- **C002**：动作具有可重复衔接的循环组织；不设循环时长或帧数门槛。
- **C003**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。
- 审查提示：no_literal_asset_mention_in_general

### [G050_mot_004](G050_mot_004.json)

- **C001**：An elderly woman sits by a cot
- **C002**：checking a bandage roll
- **C003**：动作具有可重复衔接的循环组织；不设循环时长或帧数门槛。
- **C004**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。
- 审查提示：no_literal_asset_mention_in_general

