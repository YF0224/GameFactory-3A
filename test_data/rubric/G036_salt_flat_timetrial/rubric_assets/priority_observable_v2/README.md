# G036_salt_flat_timetrial — priority 资产需求 rubric 修订 v2

本目录是独立修订版；旧 `../rubric.json`、`../per_asset/` 及历史分数均保留。
游戏内索引：`../priority_rubric_current.json`。仅包含 priority gen 对应任务，不代表其他资产任务也已修订。
第一列保留可观察的主体、部件、形状、色彩、材质、相对布局、动作/事件及声音内容；精确坐标、尺寸、时长、速度、计数和技术参数只作来源/诊断。
已有逐资产文件的第二/三维原样保留；自然音效与T-pose补充的是此前缺失的rubric草稿，不是历史有效分数。
本版尚未逐项人工审核/最终冻结，也未自动切换生产 evaluator 或重新评测。采用新 schema，必须显式选择并适配，禁止混用旧分数。

| 类型 | 任务数 |
|---|---:|
| 3D Object | 1 |
| 3D Scene | 1 |
| Audio | 11 |
| CG Video | 3 |

## 第一列逐任务预览

以下仅展示计分目标；完整原文、定性投影记录、排除项、判分锚点和第二/三维见对应 JSON。

### [G036_salt_flat_timetrial_obj_005](G036_salt_flat_timetrial_obj_005.json)

- **C001**：Pole-mounted orange-and-white striped wind sock with pivot ring
- **C002**：simple cloth cone readable from distance
- **C003**：single object set of one pole and sock

### [G036_scene_001](G036_scene_001.json)

- **C001**：Bright daytime white salt-flat proving ground
- **C002**：closed loop of compacted salt板 main line with matte white sheen
- **C003**：a shorter loose salt-crystal outer line
- **C004**：telemetry gate spots
- **C005**：survey tower and maintenance sheds on the horizon
- **C006**：low mountains far away
- **C007**：harsh noon light
- **C008**：visual shell only
- **C009**：封闭环形路线
- **C010**：分段计时门沿路线分布
- **C011**：主线与外线存在分岔，压实盐板与酥松带可辨
- 审查提示：no_literal_asset_mention_in_general

### [G036_sfx_001](G036_sfx_001.json)

- **C001**：Clean electronic countdown beep
- **C002**：rising pitch progressively
- **C003**：short decay

### [G036_sfx_002](G036_sfx_002.json)

- **C001**：Race start release chime with a low engine-friendly tone and short swell

### [G036_sfx_003](G036_sfx_003.json)

- **C001**：Checkpoint pass confirmation blip with a bright ping tail
- **C002**：telemetry flavor

### [G036_sfx_004](G036_sfx_004.json)

- **C001**：Missed-gate warning tone
- **C002**：two quick descending notes with slight distortion

### [G036_sfx_005](G036_sfx_005.json)

- **C001**：Loose salt crust rumble with granular scrape and low thud
- **C002**：vehicle leaving track

### [G036_sfx_006](G036_sfx_006.json)

- **C001**：Fast position reset whoosh with a soft teleport shimmer tail

### [G036_sfx_007](G036_sfx_007.json)

- **C001**：Time-out alarm with three urgent pulses and a dark low tail

### [G036_sfx_008](G036_sfx_008.json)

- **C001**：Victory sting with bright salt-flat airy chords and a rising finish

### [G036_sfx_009](G036_sfx_009.json)

- **C001**：Defeat sting with muted low strings and a soft distant wind tail

### [G036_sfx_010](G036_sfx_010.json)

- **C001**：Seamless dry salt-flat wind ambience with subtle distant telemetry hum
- **C002**：steady direction
- **C003**：no voices or music

### [G036_sfx_011](G036_sfx_011.json)

- **C001**：Seamless heavy prototype engine loop at mid load
- **C002**：no manufacturer identity

### [G036_cg_001](G036_cg_001.json)

- **C001**：白色盐湖全景
- **C002**：遥测站灯带依次点亮
- **C003**：灰隼试验车驶出维护棚
- **C004**：镜头掠过分段计时门停在起跑拱门
- **C005**：无 UI
- **C006**：无文字
- **C007**：无剪辑

### [G036_cg_002](G036_cg_002.json)

- **C001**：追车镜头贴地掠过盐板
- **C002**：试验车尾迹与尘雾拉长
- **C003**：外线酥松带反光一闪
- **C004**：无 UI
- **C005**：无文字

### [G036_cg_003](G036_cg_003.json)

- **C001**：不同意象共用条目：胜利=冲线横幅
- **C002**：遥测站灯带全亮
- **C003**：纪录墙上墙
- **C004**：失败=超时暗角
- **C005**：车队纪录墙留空
- **C006**：车影停在盐面
- **C007**：无 UI
- **C008**：无文字
- 审查提示：multi_variant_cg_requires_delivery_convention, branch_delivery_review

