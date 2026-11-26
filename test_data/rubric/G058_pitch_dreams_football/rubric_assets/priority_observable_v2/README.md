# G058_pitch_dreams_football — priority 资产需求 rubric 修订 v2

本目录是独立修订版；旧 `../rubric.json`、`../per_asset/` 及历史分数均保留。
游戏内索引：`../priority_rubric_current.json`。仅包含 priority gen 对应任务，不代表其他资产任务也已修订。
第一列保留可观察的主体、部件、形状、色彩、材质、相对布局、动作/事件及声音内容；精确坐标、尺寸、时长、速度、计数和技术参数只作来源/诊断。
已有逐资产文件的第二/三维原样保留；自然音效与T-pose补充的是此前缺失的rubric草稿，不是历史有效分数。
本版尚未逐项人工审核/最终冻结，也未自动切换生产 evaluator 或重新评测。采用新 schema，必须显式选择并适配，禁止混用旧分数。

| 类型 | 任务数 |
|---|---:|
| 3D Scene | 1 |
| Audio | 10 |
| CG Video | 4 |
| Motion | 1 |

## 第一列逐任务预览

以下仅展示计分目标；完整原文、定性投影记录、排除项、判分锚点和第二/三维见对应 JSON。

### [G058_scene_001](G058_scene_001.json)

- **C001**：Top-down stylized community football pitch environment with penalty boxes；小型球场
- **C002**：center circle
- **C003**：sidelines
- **C004**：bench zone and simple surrounding grass
- **C005**：one coherent game-ready three-dimensional scene
- **C006**：no UI
- **C007**：labels or text
- **C008**：禁区与中圈在俯视图中清晰可辨
- 审查提示：no_literal_asset_mention_in_general

### [G058_sfx_001](G058_sfx_001.json)

- **C001**：Standard football kickoff whistle
- **C002**：clear and dry

### [G058_sfx_002](G058_sfx_002.json)

- **C001**：Firm boot-to-ball punch

### [G058_sfx_003](G058_sfx_003.json)

- **C001**：Small-stadium goal roar with a short whistle tail

### [G058_sfx_004](G058_sfx_004.json)

- **C001**：Leather glove slap as the keeper saves

### [G058_sfx_005](G058_sfx_005.json)

- **C001**：Referee short-short-long foul whistle

### [G058_sfx_006](G058_sfx_006.json)

- **C001**：Two calm half-time whistle notes

### [G058_sfx_007](G058_sfx_007.json)

- **C001**：Ledger page and coin drop for reward income

### [G058_sfx_008](G058_sfx_008.json)

- **C001**：Card pack flip with a wax-seal pop

### [G058_sfx_009](G058_sfx_009.json)

- **C001**：Firm contract stamp for a transfer

### [G058_sfx_010](G058_sfx_010.json)

- **C001**：Community pitch ambience: crowd murmur
- **C002**：light wind over grass
- **C003**：distant traffic

### [G058_cg_001](G058_cg_001.json)

- **C001**：Top-down view of a small-town community pitch
- **C002**：eleven player silhouettes line up as six rival club flags rise
- **C003**：first whistle blows
- **C004**：bright stylized top-down look
- **C005**：cinematic
- **C006**：no text

### [G058_cg_002](G058_cg_002.json)

- **C001**：Top-down replay of a goal: the ball arcs into the net with a light trail
- **C002**：stands ripple in a wave
- **C003**：scoreboard ticks
- **C004**：cinematic
- **C005**：no text

### [G058_cg_003](G058_cg_003.json)

- **C001**：A league table settles on the final round
- **C002**：the rival's flag and ours hang side by side
- **C003**：stadium lights snap on for a night fixture
- **C004**：cinematic
- **C005**：no text

### [G058_cg_004](G058_cg_004.json)

- **C001**：The season table unfurls
- **C002**：ending frame variant: our flag rises onto the champion league board / the squad huddles waving to the stands
- **C003**：cinematic
- **C004**：no text

### [G058_pitch_dreams_football_mot_001](G058_pitch_dreams_football_mot_001.json)

- **C001**：Player receives a pass
- **C002**：takes one controlled touch
- **C003**：swings through a shot
- **C004**：and follows through toward the goal
- **C005**：单次动作具有可辨起始、过程与结束；不设绝对时长门槛。
- **C006**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。
- 审查提示：duplicate_asset_requirement_entry, no_literal_asset_mention_in_general

