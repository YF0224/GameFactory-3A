# G005_broken_realm_echo — priority 资产需求 rubric 修订 v2

本目录是独立修订版；旧 `../rubric.json`、`../per_asset/` 及历史分数均保留。
游戏内索引：`../priority_rubric_current.json`。仅包含 priority gen 对应任务，不代表其他资产任务也已修订。
第一列保留可观察的主体、部件、形状、色彩、材质、相对布局、动作/事件及声音内容；精确坐标、尺寸、时长、速度、计数和技术参数只作来源/诊断。
已有逐资产文件的第二/三维原样保留；自然音效与T-pose补充的是此前缺失的rubric草稿，不是历史有效分数。
本版尚未逐项人工审核/最终冻结，也未自动切换生产 evaluator 或重新评测。采用新 schema，必须显式选择并适配，禁止混用旧分数。

| 类型 | 任务数 |
|---|---:|
| 3D Object | 9 |
| 3D Scene | 2 |
| Audio | 15 |
| CG Video | 3 |

## 第一列逐任务预览

以下仅展示计分目标；完整原文、定性投影记录、排除项、判分锚点和第二/三维见对应 JSON。

### [G005_broken_realm_echo_obj_006](G005_broken_realm_echo_obj_006.json)

- **C001**：Floating purple resonance anchor
- **C002**：a crystal stake pinned into fractured ground with slow swirling shards around it
- **C003**：glowy interaction silhouette
- **C004**：single object

### [G005_broken_realm_echo_obj_007](G005_broken_realm_echo_obj_007.json)

- **C001**：Amber-glowing relic chest with stone shell and blue seal seams
- **C002**：one-time reward chest
- **C003**：single object

### [G005_broken_realm_echo_obj_008](G005_broken_realm_echo_obj_008.json)

- **C001**：Cyan-glowing supply cairn of stacked stones with a small vent light
- **C002**：refill point prop
- **C003**：single object

### [G005_broken_realm_echo_obj_009](G005_broken_realm_echo_obj_009.json)

- **C001**：Heavy blue-grey chain stretched across a bridge gap
- **C002**：thick links anchored to stone posts
- **C003**：removable obstacle
- **C004**：single object

### [G005_broken_realm_echo_obj_010](G005_broken_realm_echo_obj_010.json)

- **C001**：Long pale-blue straight blade with subtle glow edge and dark grip
- **C002**：player weapon prop
- **C003**：single object

### [G005_broken_realm_echo_obj_011](G005_broken_realm_echo_obj_011.json)

- **C001**：Golden longbow with faint resonance string
- **C002**：archer fiend weapon prop
- **C003**：single object

### [G005_broken_realm_echo_obj_012](G005_broken_realm_echo_obj_012.json)

- **C001**：Blue-grey rectangular tower shield slab with worn rim
- **C002**：shield fiend prop
- **C003**：single object

### [G005_broken_realm_echo_obj_013](G005_broken_realm_echo_obj_013.json)

- **C001**：Warm paper lantern hanging from a dark wood post
- **C002**：subtle warm-cold glow
- **C003**：courtyard ambience prop
- **C004**：single object

### [G005_broken_realm_echo_obj_015](G005_broken_realm_echo_obj_015.json)

- **C001**：Blue glowing return portal disc set on stone floor
- **C002**：slow ripple ring
- **C003**：scene transition interaction point
- **C004**：single object

### [G005_scene_001](G005_scene_001.json)

- **C001**：Shattered realm ruins field
- **C002**：fractured stone floor with solid debris blocks
- **C003**：columns
- **C004**：a bridge with a chained gate
- **C005**：an amber chest
- **C006**：a cyan supply cairn
- **C007**：drifting echo particles and dusk-blue fog
- **C008**：low-poly stylized
- **C009**：断垣区域内分布实体废墟
- **C010**：场景具有门、锁链、宝箱和补给点的可见表现
- 审查提示：no_literal_asset_mention_in_general

### [G005_scene_002](G005_scene_002.json)

- **C001**：Moonlit outer garden
- **C002**：night blue-purple palette with a moon and moonlight
- **C003**：columns and corridors
- **C004**：warm and cold paper lanterns
- **C005**：a red torii gate
- **C006**：drifting echo particles and a blue return portal
- **C007**：low-poly stylized
- **C008**：外苑具有返回门与补给点的可见表现
- **C009**：灯笼与鸟居作为氛围件
- **C010**：月亮不要求在默认镜头中始终可见
- 审查提示：no_literal_asset_mention_in_general

### [G005_sfx_001](G005_sfx_001.json)

- **C001**：Crisp light sword slash with a thin resonance tail

### [G005_sfx_002](G005_sfx_002.json)

- **C001**：Deep heavy sword impact with body-weight crunch

### [G005_sfx_003](G005_sfx_003.json)

- **C001**：Metal-on-metal guard clang with short ring-off

### [G005_sfx_004](G005_sfx_004.json)

- **C001**：Bright dedicated parry chime layered over the clang
- **C002**：clean and rewarding

### [G005_sfx_005](G005_sfx_005.json)

- **C001**：Sharp guard-break ping with a rising can-pursue hint tail

### [G005_sfx_006](G005_sfx_006.json)

- **C001**：Air-slicing blink-step whoosh with faint echo shimmer

### [G005_sfx_007](G005_sfx_007.json)

- **C001**：Sweeping release surge
- **C002**：layered shimmer bloom as the realm-release aura bursts

### [G005_sfx_008](G005_sfx_008.json)

- **C001**：Low crystalline stake-drive thump with rising hum as an anchor surfaces

### [G005_sfx_009](G005_sfx_009.json)

- **C001**：Crystalline shatter as an anchor is pulled free and dissipates

### [G005_sfx_010](G005_sfx_010.json)

- **C001**：Stone seal release with warm chime as the chest grants crystals

### [G005_sfx_011](G005_sfx_011.json)

- **C001**：Soft sustained restoration hum rising to a close chime over

### [G005_sfx_012](G005_sfx_012.json)

- **C001**：Solemn victory sting with fading echo particles feel

### [G005_sfx_013](G005_sfx_013.json)

- **C001**：Low descending defeat tone
- **C002**：clearly distinct from victory

### [G005_sfx_014](G005_sfx_014.json)

- **C001**：Shattered realm ruins ambience
- **C002**：hollow wind over debris with faint echo drips
- **C003**：seamless loop
- **C004**：no music

### [G005_sfx_015](G005_sfx_015.json)

- **C001**：Moonlit outer garden ambience
- **C002**：soft wind chimes and paper lantern creak with night hush
- **C003**：seamless loop
- **C004**：no music

### [G005_cg_001](G005_cg_001.json)

- **C001**：断界废墟中残响粒子漂浮如尘
- **C002**：持刀的残响猎人驻足于断垣之间
- **C003**：衣摆扬起
- **C004**：远处界卫指挥官的身影自废墟深处现身
- **C005**：护甲泛起金光
- **C006**：长剑拄地
- **C007**：镜头由粒子特写拉至双人对峙全景

### [G005_cg_002](G005_cg_002.json)

- **C001**：指挥官护甲崩开一角
- **C002**：核心透出红光
- **C003**：残响锚点自地面拔起悬浮
- **C004**：废墟随震动剥落碎屑
- **C005**：镜头震动推近指挥官面部护甲

### [G005_cg_003](G005_cg_003.json)

- **C001**：指挥官缓缓碎解为漫天残响粒子
- **C002**：核心结晶划出光弧落入猎人掌心
- **C003**：废墟归于平静
- **C004**：月光自穹顶洒落
- **C005**：残响粒子如雪飘散

