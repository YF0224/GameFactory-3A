# G031_dream_archive — priority 资产需求 rubric 修订 v2

本目录是独立修订版；旧 `../rubric.json`、`../per_asset/` 及历史分数均保留。
游戏内索引：`../priority_rubric_current.json`。仅包含 priority gen 对应任务，不代表其他资产任务也已修订。
第一列保留可观察的主体、部件、形状、色彩、材质、相对布局、动作/事件及声音内容；精确坐标、尺寸、时长、速度、计数和技术参数只作来源/诊断。
已有逐资产文件的第二/三维原样保留；自然音效与T-pose补充的是此前缺失的rubric草稿，不是历史有效分数。
本版尚未逐项人工审核/最终冻结，也未自动切换生产 evaluator 或重新评测。采用新 schema，必须显式选择并适配，禁止混用旧分数。

| 类型 | 任务数 |
|---|---:|
| 3D Object | 5 |
| 3D Scene | 3 |
| Audio | 14 |
| CG Video | 2 |

## 第一列逐任务预览

以下仅展示计分目标；完整原文、定性投影记录、排除项、判分锚点和第二/三维见对应 JSON。

### [G031_dream_archive_obj_004](G031_dream_archive_obj_004.json)

- **C001**：Dream reward healing crystal on a brass archive pedestal
- **C002**：warm paper-white glow
- **C003**：single object

### [G031_dream_archive_obj_005](G031_dream_archive_obj_005.json)

- **C001**：Dream reward carving knife with ink-black blade and brass archive handle
- **C002**：single object

### [G031_dream_archive_obj_006](G031_dream_archive_obj_006.json)

- **C001**：Dream reward silent pendulum in a glass archive vial
- **C002**：brass frame
- **C003**：single object

### [G031_dream_archive_obj_008](G031_dream_archive_obj_008.json)

- **C001**：Dream reward quill feather with drifting ink trail
- **C002**：brass clasp
- **C003**：single object

### [G031_dream_archive_obj_009](G031_dream_archive_obj_009.json)

- **C001**：Dream reward echo charm amulet with ink-drop pendant and brass ring
- **C002**：single object

### [G031_scene_001](G031_scene_001.json)

- **C001**：Dream archive normal room seen from above: m paper-and-ink reading hall with bookshelf walls；单屏房间
- **C002**：floating dust
- **C003**：brass lamps and scattered scrolls
- **C004**：entry door south and sealed exit north
- **C005**：入口门在南侧，封印出口门在北侧
- **C006**：障碍沿墙布置
- 审查提示：no_literal_asset_mention_in_general

### [G031_scene_002](G031_scene_002.json)

- **C001**：Dream archive elite forbidden room seen from above: larger ink-stained reading vault with reinforced shelves；单屏房间
- **C002**：darker pools of ink
- **C003**：broken catalog cards
- **C004**：为巨影砸地预警圈留出可见空间；不验收预警触发
- 审查提示：no_literal_asset_mention_in_general

### [G031_scene_003](G031_scene_003.json)

- **C001**：Dream archive final core library seen from above: grand central shelf spire with the first-dream scroll glow
- **C002**：ink floor ripples
- **C003**：brass latticework overhead
- **C004**：单屏房间
- **C005**：初梦卷宗具有展示位置，并设出口
- 审查提示：no_literal_asset_mention_in_general

### [G031_sfx_001](G031_sfx_001.json)

- **C001**：Carving knife swing with ink whoosh tail

### [G031_sfx_002](G031_sfx_002.json)

- **C001**：Ink splash impact on crawler with paper tear

### [G031_sfx_003](G031_sfx_003.json)

- **C001**：Heavy ink impact on shade with low thud

### [G031_sfx_004](G031_sfx_004.json)

- **C001**：Crawler dissolving into ink drips with light rattle

### [G031_sfx_005](G031_sfx_005.json)

- **C001**：Shade dissolving with deep ink swirl and paper sigh

### [G031_sfx_006](G031_sfx_006.json)

- **C001**：Player hurt gasp with ink sting

### [G031_sfx_007](G031_sfx_007.json)

- **C001**：Room clear chime as reward choices appear

### [G031_sfx_008](G031_sfx_008.json)

- **C001**：Wax seal cracking and door creak open

### [G031_sfx_009](G031_sfx_009.json)

- **C001**：Healing crystal warm chime

### [G031_sfx_010](G031_sfx_010.json)

- **C001**：Carving knife pick-up with sharp metallic ring

### [G031_sfx_011](G031_sfx_011.json)

- **C001**：Silent pendulum pick-up with clockwork tick

### [G031_sfx_012](G031_sfx_012.json)

- **C001**：Archive victory sting with lamps lighting one by one

### [G031_sfx_013](G031_sfx_013.json)

- **C001**：Defeat drone with ink swallowing fade

### [G031_sfx_014](G031_sfx_014.json)

- **C001**：Dream archive ambience loop with paper rustle
- **C002**：distant ink drips and clockwork ticks
- **C003**：seamless loop

### [G031_cg_001](G031_cg_001.json)

- **C001**：档案馆长廊全景：墨色走廊的房间彼此漂移重排
- **C002**：初梦卷宗的微光没入深处
- **C003**：档案馆员点亮手灯步入走廊
- **C004**：无 UI
- **C005**：无文字
- **C006**：无剪辑

### [G031_cg_002](G031_cg_002.json)

- **C001**：不同意象共用条目：胜利=初梦卷宗归位书架
- **C002**：馆内灯火次第亮起
- **C003**：失败=墨迹漫过书架
- **C004**：手灯熄灭
- **C005**：无 UI
- **C006**：无文字
- 审查提示：multi_variant_cg_requires_delivery_convention, branch_delivery_review

