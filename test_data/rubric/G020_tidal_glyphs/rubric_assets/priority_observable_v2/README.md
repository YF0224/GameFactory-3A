# G020_tidal_glyphs — priority 资产需求 rubric 修订 v2

本目录是独立修订版；旧 `../rubric.json`、`../per_asset/` 及历史分数均保留。
游戏内索引：`../priority_rubric_current.json`。仅包含 priority gen 对应任务，不代表其他资产任务也已修订。
第一列保留可观察的主体、部件、形状、色彩、材质、相对布局、动作/事件及声音内容；精确坐标、尺寸、时长、速度、计数和技术参数只作来源/诊断。
已有逐资产文件的第二/三维原样保留；自然音效与T-pose补充的是此前缺失的rubric草稿，不是历史有效分数。
本版尚未逐项人工审核/最终冻结，也未自动切换生产 evaluator 或重新评测。采用新 schema，必须显式选择并适配，禁止混用旧分数。

| 类型 | 任务数 |
|---|---:|
| 3D Object | 5 |
| 3D Scene | 1 |
| Audio | 13 |
| CG Video | 4 |
| Motion | 3 |
| T-pose | 1 |

## 第一列逐任务预览

以下仅展示计分目标；完整原文、定性投影记录、排除项、判分锚点和第二/三维见对应 JSON。

### [G020_tidal_glyphs_obj_001](G020_tidal_glyphs_obj_001.json)

- **C001**：Field epigrapher with a storm-oil lantern in hand
- **C002**：wide hooded rain cloak over layered expedition gear
- **C003**：satchel of rubbing papers
- **C004**：stylized semi-realistic
- **C005**：cool teal and stone palette
- **C006**：T-pose

### [G020_tidal_glyphs_obj_002](G020_tidal_glyphs_obj_002.json)

- **C001**：Tall gaunt humanoid warden silhouette carved of wet stone and faint tide-light
- **C002**：hollow kelp-draped shoulders
- **C003**：glowing tide-gold eyes
- **C004**：non-hostile eerie presence
- **C005**：stylized semi-realistic

### [G020_tidal_glyphs_obj_003](G020_tidal_glyphs_obj_003.json)

- **C001**：Rectangular damp stone tablet carved with six abstract tide-glyph slots around a central seal ring
- **C002**：faint golden etched glow
- **C003**：stylized semi-realistic

### [G020_tidal_glyphs_obj_004](G020_tidal_glyphs_obj_004.json)

- **C001**：Circular deep-stone seal altar with six glyph keyholes
- **C002**：tide-gold channeling grooves and a low central pillar
- **C003**：stylized semi-realistic

### [G020_tidal_glyphs_obj_005](G020_tidal_glyphs_obj_005.json)

- **C001**：Antique brass tidal compass with concentric tide-ring engravings
- **C002**：a floating teal-and-gold needle and a moonstone cabochon at its center
- **C003**：matching the bound reference image
- **C004**：stylized semi-realistic
- **C005**：cool teal and tide-gold accents

### [G020_scene_001](G020_scene_001.json)

- **C001**：Tidal ruin interior: a moon-tide antechamber with frescoed walls
- **C002**：a carved inner chamber with moon-phase dials and lamp niches
- **C003**：and a deep seal chamber under a starry domed ceiling
- **C004**：wet stone
- **C005**：faint tide-gold glyph glow
- **C006**：cold teal palette
- **C007**：stylized semi-realistic
- **C008**：房间按线性深入的关系组织
- **C009**：密室具有壁龛与壁灯组
- 审查提示：no_literal_asset_mention_in_general

### [G020_sfx_001](G020_sfx_001.json)

- **C001**：Stone rubbing scrape as a clue is recorded

### [G020_sfx_002](G020_sfx_002.json)

- **C001**：Low resonant glyph tone when a symbol is tentatively assigned

### [G020_sfx_003](G020_sfx_003.json)

- **C001**：Brighter resonant glyph tone plus a soft chime on confirmation

### [G020_sfx_004](G020_sfx_004.json)

- **C001**：Dull stone-door refusal knock for a mistranslation

### [G020_sfx_005](G020_sfx_005.json)

- **C001**：Paper swish as an assumption rolls back

### [G020_sfx_006](G020_sfx_006.json)

- **C001**：Two artifacts click together with a stone chime

### [G020_sfx_007](G020_sfx_007.json)

- **C001**：Heavy stone door grinding open with dust falls

### [G020_sfx_008](G020_sfx_008.json)

- **C001**：Sub-bass pressure rumble rising under the tide

### [G020_sfx_009](G020_sfx_009.json)

- **C001**：Sudden high frequency shriek cutting through silence

### [G020_sfx_010](G020_sfx_010.json)

- **C001**：Small warm chime as alcove lamps ignite

### [G020_sfx_011](G020_sfx_011.json)

- **C001**：Six-note ascending stone aria as seal slots align

### [G020_sfx_012](G020_sfx_012.json)

- **C001**：Rushing tide surge flooding stone halls

### [G020_sfx_013](G020_sfx_013.json)

- **C001**：Low tide wash inside a stone ruin
- **C002**：dripping water
- **C003**：distant hollow echoes
- **C004**：no music

### [G020_cg_001](G020_cg_001.json)

- **C001**：A reef ruin emerges from receding tide at dusk
- **C002**：an epigrapher steps in with a lantern
- **C003**：tide glyphs on frescoes begin to glow
- **C004**：cold teal and gold accents
- **C005**：cinematic
- **C006**：no text

### [G020_cg_002](G020_cg_002.json)

- **C001**：A tidal lock glyph ring rotates into place
- **C002**：a stone door rises revealing a moonlit inner chamber
- **C003**：cinematic
- **C004**：no text

### [G020_cg_003](G020_cg_003.json)

- **C001**：Descent along slick stone steps into a dark seal chamber
- **C002**：faint starry dome above
- **C003**：six-slot altar silhouette in black water reflections
- **C004**：cinematic
- **C005**：no text

### [G020_cg_004](G020_cg_004.json)

- **C001**：multiple glyph light pillars converge
- **C002**：the seal curtain dissolves into rising tide-light
- **C003**：an epigrapher looks back with a lantern
- **C004**：ending frame variant by rating
- **C005**：cinematic
- **C006**：no text

### [G020_mot_001](G020_mot_001.json)

- **C001**：An epigrapher stands idle holding a storm lantern
- **C002**：cloak swaying slightly
- **C003**：动作具有可重复衔接的循环组织；不设循环时长或帧数门槛。
- **C004**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。

### [G020_mot_002](G020_mot_002.json)

- **C001**：An epigrapher walks forward carefully on wet stone
- **C002**：动作具有可重复衔接的循环组织；不设循环时长或帧数门槛。
- **C003**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。

### [G020_mot_003](G020_mot_003.json)

- **C001**：An epigrapher leans forward and presses a rubbing paper onto a carved wall
- **C002**：单次动作具有可辨起始、过程与结束；不设绝对时长门槛。
- **C003**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。

### [G020_tpose_001](G020_tpose_001.json)

- **C001**：Field epigrapher in a hooded rain cloak with lantern and satchel
- **C002**：clean symmetrical T-pose
- **C003**：stylized semi-realistic
- **C004**：cool teal and stone palette
- **C005**：角色以正面 T-pose 展示；按姿态含义辨认，不要求精确关节角度。

