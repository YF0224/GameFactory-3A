# G041_frontier_market — priority 资产需求 rubric 修订 v2

本目录是独立修订版；旧 `../rubric.json`、`../per_asset/` 及历史分数均保留。
游戏内索引：`../priority_rubric_current.json`。仅包含 priority gen 对应任务，不代表其他资产任务也已修订。
第一列保留可观察的主体、部件、形状、色彩、材质、相对布局、动作/事件及声音内容；精确坐标、尺寸、时长、速度、计数和技术参数只作来源/诊断。
已有逐资产文件的第二/三维原样保留；自然音效与T-pose补充的是此前缺失的rubric草稿，不是历史有效分数。
本版尚未逐项人工审核/最终冻结，也未自动切换生产 evaluator 或重新评测。采用新 schema，必须显式选择并适配，禁止混用旧分数。

| 类型 | 任务数 |
|---|---:|
| 3D Object | 2 |
| 3D Scene | 1 |
| Audio | 12 |
| CG Video | 3 |

## 第一列逐任务预览

以下仅展示计分目标；完整原文、定性投影记录、排除项、判分锚点和第二/三维见对应 JSON。

### [G041_frontier_market_obj_008](G041_frontier_market_obj_008.json)

- **C001**：Weathered wooden frontier pass signpost with blank arrow planks at two heights and carved rope motifs
- **C002**：marking the customer trail entrance
- **C003**：single object

### [G041_frontier_market_obj_009](G041_frontier_market_obj_009.json)

- **C001**：Pole-mounted caravan banner with teal pennant and tassel
- **C002**：cloth shape readable from top-down view
- **C003**：raised and lowered states achievable via pivot
- **C004**：single object

### [G041_scene_001](G041_scene_001.json)

- **C001**：Frontier rock-pass market stall scene
- **C002**：single-screen layout with four shelf rows
- **C003**：wooden counter
- **C004**：beige awning
- **C005**：customer path from pass trail entrance through browsing area to counter and exit
- **C006**：warm dusty daylight
- **C007**：rocky cliff backdrop
- **C008**：visual shell only
- **C009**：单屏摊位场景具有成排货架与柜台
- **C010**：入口、浏览区、排队区、柜台和出口具有可读的空间连接；不验收顾客逻辑
- 审查提示：no_literal_asset_mention_in_general

### [G041_sfx_001](G041_sfx_001.json)

- **C001**：Customer entering stall footsteps with soft cloth rustle on packed dirt
- **C002**：neutral friendly tone

### [G041_sfx_002](G041_sfx_002.json)

- **C001**：Transaction coin chime
- **C002**：two bright metal coins landing on wood counter
- **C003**：satisfying clean tail

### [G041_sfx_003](G041_sfx_003.json)

- **C001**：Stock-out alert
- **C002**：soft two-note descending wood block tone
- **C003**：informational not harsh

### [G041_sfx_004](G041_sfx_004.json)

- **C001**：Patience timeout cue
- **C002**：hourglass shatter imitation with glass-sand hiss and low thud

### [G041_sfx_005](G041_sfx_005.json)

- **C001**：Rolling shutter closing on wooden frame
- **C002**：slats clatter and final wooden thud

### [G041_sfx_006](G041_sfx_006.json)

- **C001**：Day settlement abacus rolling and ledger page turn
- **C002**：layered wooden clicks into a calm resolving tone

### [G041_sfx_007](G041_sfx_007.json)

- **C001**：Price tag tick
- **C002**：crisp paper-tag flick and small wooden peg click for price change

### [G041_sfx_008](G041_sfx_008.json)

- **C001**：Victory sting
- **C002**：warm market-day strings and chimes rising to a proud finish with caravan-bell tail

### [G041_sfx_009](G041_sfx_009.json)

- **C001**：Defeat sting
- **C002**：muted low woodwind with dust-wind tail
- **C003**：dignified not dramatic

### [G041_sfx_010](G041_sfx_010.json)

- **C001**：Seamless rocky-pass wind ambience with distant caravan bells and faint market murmur
- **C002**：no voices or music

### [G041_sfx_011](G041_sfx_011.json)

- **C001**：Seamless light market crowd ambience
- **C002**：scattered footsteps and cloth movement
- **C003**：no distinct words

### [G041_sfx_012](G041_sfx_012.json)

- **C001**：Low anxious waiting murmur loop with soft shuffling
- **C002**：layered only while waiting customers present

### [G041_cg_001](G041_cg_001.json)

- **C001**：灰岩隘口晨光
- **C002**：驮队剪影入集
- **C003**：米色雨棚展开
- **C004**：四排货架陈列亮起
- **C005**：摊主挂出价签
- **C006**：无 UI
- **C007**：无文字
- **C008**：无剪辑

### [G041_cg_002](G041_cg_002.json)

- **C001**：隘口步道涌入旅人人群
- **C002**：货架快速空出
- **C003**：柜台前排起长队
- **C004**：沙漏图标亮起
- **C005**：无 UI
- **C006**：无文字

### [G041_cg_003](G041_cg_003.json)

- **C001**：不同意象共用条目：胜利＝雨棚亮灯
- **C002**：商队旗帜升起
- **C003**：金币入库
- **C004**：失败＝雨棚收起
- **C005**：旗帜降下
- **C006**：摊位清冷
- **C007**：无 UI
- **C008**：无文字
- 审查提示：multi_variant_cg_requires_delivery_convention, branch_delivery_review

