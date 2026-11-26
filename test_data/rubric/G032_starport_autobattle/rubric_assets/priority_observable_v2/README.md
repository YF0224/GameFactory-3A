# G032_starport_autobattle — priority 资产需求 rubric 修订 v2

本目录是独立修订版；旧 `../rubric.json`、`../per_asset/` 及历史分数均保留。
游戏内索引：`../priority_rubric_current.json`。仅包含 priority gen 对应任务，不代表其他资产任务也已修订。
第一列保留可观察的主体、部件、形状、色彩、材质、相对布局、动作/事件及声音内容；精确坐标、尺寸、时长、速度、计数和技术参数只作来源/诊断。
已有逐资产文件的第二/三维原样保留；自然音效与T-pose补充的是此前缺失的rubric草稿，不是历史有效分数。
本版尚未逐项人工审核/最终冻结，也未自动切换生产 evaluator 或重新评测。采用新 schema，必须显式选择并适配，禁止混用旧分数。

| 类型 | 任务数 |
|---|---:|
| 3D Object | 1 |
| 3D Scene | 1 |
| Audio | 18 |
| CG Video | 3 |

## 第一列逐任务预览

以下仅展示计分目标；完整原文、定性投影记录、排除项、判分锚点和第二/三维见对应 JSON。

### [G032_starport_autobattle_obj_006](G032_starport_autobattle_obj_006.json)

- **C001**：Small insect-shaped scout drone with translucent wings and a stinger probe
- **C002**：non-humanoid
- **C003**：stylized sci-fi starport style
- **C004**：slightly chunky proportions
- **C005**：navy and teal palette

### [G032_scene_001](G032_scene_001.json)

- **C001**：Starport landing deck at night seen from an oblique top-down angle
- **C002**：a lit tile battle board split into two halves
- **C003**：cargo containers and docked shuttles around the edges
- **C004**：neon teal lights
- **C005**：格状棋盘分成对称的半场
- **C006**：棋盘下方为商店界面留白
- **C007**：边缘道具不覆盖棋盘
- 审查提示：no_literal_asset_mention_in_general

### [G032_sfx_001](G032_sfx_001.json)

- **C001**：Digital purchase confirm with a short coin blip
- **C002**：no music
- **C003**：no voice

### [G032_sfx_002](G032_sfx_002.json)

- **C001**：Holographic panel shuffle swoosh
- **C002**：no music
- **C003**：no voice

### [G032_sfx_003](G032_sfx_003.json)

- **C001**：Magnetic boots clamp onto a deck tile
- **C002**：no music
- **C003**：no voice

### [G032_sfx_004](G032_sfx_004.json)

- **C001**：Rising sci-fi power-up chord with sparkle
- **C002**：no music
- **C003**：no voice

### [G032_sfx_005](G032_sfx_005.json)

- **C001**：Two-tone synth confirm
- **C002**：no music
- **C003**：no voice

### [G032_sfx_006](G032_sfx_006.json)

- **C001**：Klaxon blip and engines powering up
- **C002**：no music
- **C003**：no voice

### [G032_sfx_007](G032_sfx_007.json)

- **C001**：Electric baton strike crackle
- **C002**：no music
- **C003**：no voice

### [G032_sfx_008](G032_sfx_008.json)

- **C001**：Heavy metal shield bash clang
- **C002**：no music
- **C003**：no voice

### [G032_sfx_009](G032_sfx_009.json)

- **C001**：Rail rifle charged shot with a sharp crack
- **C002**：no music
- **C003**：no voice

### [G032_sfx_010](G032_sfx_010.json)

- **C001**：Soft rising healing beam tone
- **C002**：no music
- **C003**：no voice

### [G032_sfx_011](G032_sfx_011.json)

- **C001**：Hammer impact shattering metal plates
- **C002**：no music
- **C003**：no voice

### [G032_sfx_012](G032_sfx_012.json)

- **C001**：Tiny buzzing dart and a sting zip
- **C002**：no music
- **C003**：no voice

### [G032_sfx_013](G032_sfx_013.json)

- **C001**：Armor clatter and power down whine
- **C002**：no music
- **C003**：no voice

### [G032_sfx_014](G032_sfx_014.json)

- **C001**：Short upbeat synth sting
- **C002**：no music
- **C003**：no voice

### [G032_sfx_015](G032_sfx_015.json)

- **C001**：Short descending synth sting
- **C002**：no music
- **C003**：no voice

### [G032_sfx_016](G032_sfx_016.json)

- **C001**：Several coins counting up digitally
- **C002**：no music
- **C003**：no voice

### [G032_sfx_017](G032_sfx_017.json)

- **C001**：Soft countdown tick
- **C002**：no music
- **C003**：no voice

### [G032_sfx_018](G032_sfx_018.json)

- **C001**：Starport deck ambience with distant ship engines and announcements muffled
- **C002**：no music
- **C003**：no voice

### [G032_cg_001](G032_cg_001.json)

- **C001**：A starport candidate deck lights up before a rotation tournament
- **C002**：rows of mechanic squads entering
- **C003**：a commander pressing a candidate badge onto a command console
- **C004**：grandstands glowing
- **C005**：stylized sci-fi starport style
- **C006**：navy and teal palette
- **C007**：cinematic
- **C008**：no text

### [G032_cg_002](G032_cg_002.json)

- **C001**：Three identical mechanic soldiers walk into a beam of light and merge into one taller two-star unit
- **C002**：a star badge ignites above it
- **C003**：the squad salutes
- **C004**：stylized sci-fi starport style
- **C005**：navy and teal palette
- **C006**：cinematic
- **C007**：no text

### [G032_cg_003](G032_cg_003.json)

- **C001**：Dual-imagery ending: victory shows a formal flag handed over and defense lights igniting along the orbital windows
- **C002**：defeat shows the candidate badge taken back and the deck lights dimming
- **C003**：stylized sci-fi starport style
- **C004**：navy and teal palette
- **C005**：cinematic
- **C006**：no text
- 审查提示：multi_variant_cg_requires_delivery_convention

