# G033_card_caravan — priority 资产需求 rubric 修订 v2

本目录是独立修订版；旧 `../rubric.json`、`../per_asset/` 及历史分数均保留。
游戏内索引：`../priority_rubric_current.json`。仅包含 priority gen 对应任务，不代表其他资产任务也已修订。
第一列保留可观察的主体、部件、形状、色彩、材质、相对布局、动作/事件及声音内容；精确坐标、尺寸、时长、速度、计数和技术参数只作来源/诊断。
已有逐资产文件的第二/三维原样保留；自然音效与T-pose补充的是此前缺失的rubric草稿，不是历史有效分数。
本版尚未逐项人工审核/最终冻结，也未自动切换生产 evaluator 或重新评测。采用新 schema，必须显式选择并适配，禁止混用旧分数。

| 类型 | 任务数 |
|---|---:|
| 3D Scene | 1 |
| Audio | 21 |
| CG Video | 3 |

## 第一列逐任务预览

以下仅展示计分目标；完整原文、定性投影记录、排除项、判分锚点和第二/三维见对应 JSON。

### [G033_scene_001](G033_scene_001.json)

- **C001**：Desert caravan camp battle stage at sunset
- **C002**：side view framing
- **C003**：sand dunes
- **C004**：parked caravan wagons and cloth tents behind
- **C005**：open sand area in front for two combatants
- **C006**：侧视战斗构图，玩家在左、敌人在右
- **C007**：前景为手牌界面保持清晰留白
- 审查提示：no_literal_asset_mention_in_general

### [G033_vo_017](G033_vo_017.json)

- **C001**：A steady caravan leader voice
- **C002**：warm and determined
- **C003**：绿洲之心必须送到。沙海再大，也有尽头。
- **C004**：语音使用声明的语言：Chinese
- **C005**：语音表达声明的情绪：determined
- 审查提示：no_literal_asset_mention_in_general

### [G033_vo_018](G033_vo_018.json)

- **C001**：A deep menacing bandit chief voice
- **C002**：slow and threatening
- **C003**：把水晶留下，我放你们走出沙海。
- **C004**：语音使用声明的语言：Chinese
- **C005**：语音表达声明的情绪：menacing
- 审查提示：no_literal_asset_mention_in_general

### [G033_vo_019](G033_vo_019.json)

- **C001**：A caravan leader voice
- **C002**：startled
- **C003**：沙在动……是古道的守护巨蛇！
- **C004**：语音使用声明的语言：Chinese
- **C005**：语音表达声明的情绪：shocked
- 审查提示：no_literal_asset_mention_in_general

### [G033_vo_020](G033_vo_020.json)

- **C001**：A caravan leader voice
- **C002**：quiet and moved
- **C003**：看，绿洲。
- **C004**：语音使用声明的语言：Chinese
- **C005**：语音表达声明的情绪：relieved
- 审查提示：no_literal_asset_mention_in_general

### [G033_vo_021](G033_vo_021.json)

- **C001**：A caravan leader voice fading under wind
- **C002**：沙暴……吞没了一切。
- **C003**：语音使用声明的语言：Chinese
- **C004**：语音表达声明的情绪：despair
- 审查提示：no_literal_asset_mention_in_general

### [G033_sfx_001](G033_sfx_001.json)

- **C001**：Paper card sliding off a deck
- **C002**：no music
- **C003**：no voice

### [G033_sfx_002](G033_sfx_002.json)

- **C001**：Card flicked onto a table with a whoosh
- **C002**：no music
- **C003**：no voice

### [G033_sfx_003](G033_sfx_003.json)

- **C001**：Deck of cards shuffling
- **C002**：no music
- **C003**：no voice

### [G033_sfx_004](G033_sfx_004.json)

- **C001**：Short wooden knock
- **C002**：no music
- **C003**：no voice

### [G033_sfx_005](G033_sfx_005.json)

- **C001**：Blade slash hitting cloth and flesh
- **C002**：no music
- **C003**：no voice

### [G033_sfx_006](G033_sfx_006.json)

- **C001**：Heavy blunt impact with sand burst
- **C002**：no music
- **C003**：no voice

### [G033_sfx_007](G033_sfx_007.json)

- **C001**：Metal shield ring
- **C002**：no music
- **C003**：no voice

### [G033_sfx_008](G033_sfx_008.json)

- **C001**：Low power-up whoosh
- **C002**：no music
- **C003**：no voice

### [G033_sfx_009](G033_sfx_009.json)

- **C001**：Bubbling liquid hiss
- **C002**：no music
- **C003**：no voice

### [G033_sfx_010](G033_sfx_010.json)

- **C001**：Cracking armor with a sand gust
- **C002**：no music
- **C003**：no voice

### [G033_sfx_011](G033_sfx_011.json)

- **C001**：Enemy war roar with drum hit
- **C002**：no music
- **C003**：no voice

### [G033_sfx_012](G033_sfx_012.json)

- **C001**：Bright magical chime
- **C002**：no music
- **C003**：no voice

### [G033_sfx_013](G033_sfx_013.json)

- **C001**：Satisfying card-in-deck slide and chime
- **C002**：no music
- **C003**：no voice

### [G033_sfx_014](G033_sfx_014.json)

- **C001**：Short triumphant oud-like flourish played by synth
- **C002**：no music
- **C003**：no voice

### [G033_sfx_015](G033_sfx_015.json)

- **C001**：Wind blowing over sand with a low drone
- **C002**：no music
- **C003**：no voice

### [G033_sfx_016](G033_sfx_016.json)

- **C001**：Desert wind with distant caravan bells
- **C002**：no music
- **C003**：no voice

### [G033_cg_001](G033_cg_001.json)

- **C001**：A desert caravan of wagons crosses golden dunes at sunset carrying a glowing green crystal in an ornate chest
- **C002**：the leader in an indigo robe looks toward the horizon
- **C003**：stylized desert caravan adventure style
- **C004**：sand
- **C005**：terracotta and indigo cloth
- **C006**：cinematic
- **C007**：no text

### [G033_cg_002](G033_cg_002.json)

- **C001**：The sand ahead swirls and collapses
- **C002**：a colossal dune serpent with sandstone scales and a glowing gem crest rises roaring from the desert
- **C003**：stylized desert caravan adventure style
- **C004**：sand
- **C005**：terracotta and indigo cloth
- **C006**：cinematic
- **C007**：no text

### [G033_cg_003](G033_cg_003.json)

- **C001**：The caravan crests the final dune and a lush oasis appears below
- **C002**：palm trees and blue water
- **C003**：the green crystal glowing brightly
- **C004**：stylized desert caravan adventure style
- **C005**：sand
- **C006**：terracotta and indigo cloth
- **C007**：cinematic
- **C008**：no text

