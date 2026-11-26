# G034_tinker_backpack — priority 资产需求 rubric 修订 v2

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

### [G034_scene_001](G034_scene_001.json)

- **C001**：Rusty wasteland junkyard battle stage
- **C002**：side view framing
- **C003**：piles of scrap and broken machines
- **C004**：a patched tent
- **C005**：dusty orange sky
- **C006**：侧视战斗构图，玩家在左、敌人在右
- **C007**：前景为手牌和背包格界面保持清晰留白
- 审查提示：no_literal_asset_mention_in_general

### [G034_vo_017](G034_vo_017.json)

- **C001**：A cheerful young tinker voice
- **C002**：confident
- **C003**：一只背包，一路修过去。试炼开始。
- **C004**：语音使用声明的语言：Chinese
- **C005**：语音表达声明的情绪：confident
- 审查提示：no_literal_asset_mention_in_general

### [G034_vo_018](G034_vo_018.json)

- **C001**：A flat robotic guard voice with metallic distortion
- **C002**：未经许可，禁止通过。
- **C003**：语音使用声明的语言：Chinese
- **C004**：语音表达声明的情绪：cold
- 审查提示：no_literal_asset_mention_in_general

### [G034_vo_019](G034_vo_019.json)

- **C001**：A young tinker voice
- **C002**：focused
- **C003**：发电塔里那只蜂后……就是这次试炼的终点。
- **C004**：语音使用声明的语言：Chinese
- **C005**：语音表达声明的情绪：focused
- 审查提示：no_literal_asset_mention_in_general

### [G034_vo_020](G034_vo_020.json)

- **C001**：A young tinker voice
- **C002**：proud and happy
- **C003**：灯亮了。试炼完成。
- **C004**：语音使用声明的语言：Chinese
- **C005**：语音表达声明的情绪：proud
- 审查提示：no_literal_asset_mention_in_general

### [G034_vo_021](G034_vo_021.json)

- **C001**：A young tinker voice
- **C002**：frustrated but not giving up
- **C003**：工具散了一地……再来一次。
- **C004**：语音使用声明的语言：Chinese
- **C005**：语音表达声明的情绪：frustrated
- 审查提示：no_literal_asset_mention_in_general

### [G034_sfx_001](G034_sfx_001.json)

- **C001**：Metal tool clinking as it is picked up
- **C002**：no music
- **C003**：no voice

### [G034_sfx_002](G034_sfx_002.json)

- **C001**：Satisfying click of an item snapping into a grid slot
- **C002**：no music
- **C003**：no voice

### [G034_sfx_003](G034_sfx_003.json)

- **C001**：Small ratchet click
- **C002**：no music
- **C003**：no voice

### [G034_sfx_004](G034_sfx_004.json)

- **C001**：Dull buzz with a soft rattle
- **C002**：no music
- **C003**：no voice

### [G034_sfx_005](G034_sfx_005.json)

- **C001**：Bright gear-meshing chime
- **C002**：no music
- **C003**：no voice

### [G034_sfx_006](G034_sfx_006.json)

- **C001**：Card slap with a metal tick
- **C002**：no music
- **C003**：no voice

### [G034_sfx_007](G034_sfx_007.json)

- **C001**：Wrench clanging on metal
- **C002**：no music
- **C003**：no voice

### [G034_sfx_008](G034_sfx_008.json)

- **C001**：Heavy hammer smash on scrap
- **C002**：no music
- **C003**：no voice

### [G034_sfx_009](G034_sfx_009.json)

- **C001**：Bright flash with a whooshing hum
- **C002**：no music
- **C003**：no voice

### [G034_sfx_010](G034_sfx_010.json)

- **C001**：Tape measure snapping back
- **C002**：no music
- **C003**：no voice

### [G034_sfx_011](G034_sfx_011.json)

- **C001**：Thick canvas absorbing an impact
- **C002**：no music
- **C003**：no voice

### [G034_sfx_012](G034_sfx_012.json)

- **C001**：Robot taking a hit
- **C002**：metal crunch
- **C003**：no music
- **C004**：no voice

### [G034_sfx_013](G034_sfx_013.json)

- **C001**：Mechanical buzzing intensifying with a reactor hum
- **C002**：no music
- **C003**：no voice

### [G034_sfx_014](G034_sfx_014.json)

- **C001**：Cheerful clockwork music box flourish
- **C002**：no music
- **C003**：no voice

### [G034_sfx_015](G034_sfx_015.json)

- **C001**：Machinery winding down to a stop
- **C002**：no music
- **C003**：no voice

### [G034_sfx_016](G034_sfx_016.json)

- **C001**：Junkyard wind with creaking metal and distant clanks
- **C002**：no music
- **C003**：no voice

### [G034_cg_001](G034_cg_001.json)

- **C001**：A traveling tinker packs tools into a huge patched backpack in a cluttered workshop
- **C002**：then steps out into a rusty wasteland junkyard toward a dark old power tower
- **C003**：stylized steampunk tinker style
- **C004**：brass
- **C005**：rust
- **C006**：leather and canvas
- **C007**：cinematic
- **C008**：no text

### [G034_cg_002](G034_cg_002.json)

- **C001**：Inside a dark power tower
- **C002**：a large mechanical queen bee awakens
- **C003**：its reactor core abdomen glowing
- **C004**：brass wings unfolding with sparks
- **C005**：stylized steampunk tinker style
- **C006**：brass
- **C007**：rust
- **C008**：leather and canvas
- **C009**：cinematic
- **C010**：no text

### [G034_cg_003](G034_cg_003.json)

- **C001**：The old power tower lights up from bottom to top
- **C002**：sparks flying
- **C003**：the tinker stands below with the backpack as lights spread across the junkyard at dusk
- **C004**：stylized steampunk tinker style
- **C005**：brass
- **C006**：rust
- **C007**：leather and canvas
- **C008**：cinematic
- **C009**：no text

