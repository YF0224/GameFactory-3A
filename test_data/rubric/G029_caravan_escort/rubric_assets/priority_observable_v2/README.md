# G029_caravan_escort — priority 资产需求 rubric 修订 v2

本目录是独立修订版；旧 `../rubric.json`、`../per_asset/` 及历史分数均保留。
游戏内索引：`../priority_rubric_current.json`。仅包含 priority gen 对应任务，不代表其他资产任务也已修订。
第一列保留可观察的主体、部件、形状、色彩、材质、相对布局、动作/事件及声音内容；精确坐标、尺寸、时长、速度、计数和技术参数只作来源/诊断。
已有逐资产文件的第二/三维原样保留；自然音效与T-pose补充的是此前缺失的rubric草稿，不是历史有效分数。
本版尚未逐项人工审核/最终冻结，也未自动切换生产 evaluator 或重新评测。采用新 schema，必须显式选择并适配，禁止混用旧分数。

| 类型 | 任务数 |
|---|---:|
| 3D Object | 1 |
| 3D Scene | 3 |
| Audio | 19 |
| CG Video | 4 |

## 第一列逐任务预览

以下仅展示计分目标；完整原文、定性投影记录、排除项、判分锚点和第二/三维见对应 JSON。

### [G029_caravan_escort_obj_004](G029_caravan_escort_obj_004.json)

- **C001**：Sand-and-log cheval de frise roadblock blocking an one-grid lane
- **C002**：wooden stakes and lashed beams
- **C003**：single object

### [G029_scene_001](G029_scene_001.json)

- **C001**：Plains migration route segment seen from above: open dry grassland with wheel-rut trail
- **C002**：scattered rocks and dried shrubs
- **C003**：light dust haze
- **C004**：morning light
- **C005**：平原区域具有连续的单线路线
- 审查提示：no_literal_asset_mention_in_general

### [G029_scene_002](G029_scene_002.json)

- **C001**：Canyon migration route segment seen from above: narrow rock canyon with wind-carved walls
- **C002**：scattered boulders and ledge shadows
- **C003**：midday light
- **C004**：峡谷区域具有连续的单线路线
- 审查提示：no_literal_asset_mention_in_general

### [G029_scene_003](G029_scene_003.json)

- **C001**：Ferry crossing route segment seen from above: gravel riverbank with drifting ice floes on the water
- **C002**：wooden ferry moored at shallow
- **C003**：dusk light
- **C004**：渡口区域具有连续的单线路线
- **C005**：渡口平台位于路线终点
- 审查提示：no_literal_asset_mention_in_general

### [G029_vo_015](G029_vo_015.json)

- **C001**：Warm elder voice
- **C002**：resolute and slow
- **C003**：Chinese
- **C004**：slight outdoor wind bed
- **C005**：旱季要结束了。种子和水都装好了，趁河面还没封冻，出发。
- **C006**：语音使用声明的语言：Chinese
- **C007**：语音表达声明的情绪：calm
- 审查提示：no_literal_asset_mention_in_general

### [G029_vo_016](G029_vo_016.json)

- **C001**：Young scout voice
- **C002**：quick and tense
- **C003**：Chinese
- **C004**：distant echo
- **C005**：前方峡谷有伏兵，布置好防线再进。
- **C006**：语音使用声明的语言：Chinese
- **C007**：语音表达声明的情绪：urgent
- 审查提示：no_literal_asset_mention_in_general

### [G029_vo_017](G029_vo_017.json)

- **C001**：Elder voice with urgency
- **C002**：Chinese
- **C003**：dusk wind bed
- **C004**：渡船只等到日落。这一段，不能停。
- **C005**：语音使用声明的语言：Chinese
- **C006**：语音表达声明的情绪：tense
- 审查提示：no_literal_asset_mention_in_general

### [G029_vo_018](G029_vo_018.json)

- **C001**：Relieved joyful elder voice
- **C002**：Chinese
- **C003**：river wash bed
- **C004**：过了河，就是新的牧场。孩子们，我们到了。
- **C005**：语音使用声明的语言：Chinese
- **C006**：语音表达声明的情绪：joyful
- 审查提示：no_literal_asset_mention_in_general

### [G029_vo_019](G029_vo_019.json)

- **C001**：Grieving elder voice
- **C002**：low and broken
- **C003**：Chinese
- **C004**：篷车……倒了。部落的冬天，怎么办。
- **C005**：语音使用声明的语言：Chinese
- **C006**：语音表达声明的情绪：tense
- 审查提示：no_literal_asset_mention_in_general

### [G029_sfx_001](G029_sfx_001.json)

- **C001**：Device deploy with wooden legs snapping open and dust settle

### [G029_sfx_002](G029_sfx_002.json)

- **C001**：Dull rejection thud
- **C002**：out-of-circle placement refused

### [G029_sfx_003](G029_sfx_003.json)

- **C001**：Device pack-up click with coin sweep on top

### [G029_sfx_004](G029_sfx_004.json)

- **C001**：Portable ballista release with bolt whoosh

### [G029_sfx_005](G029_sfx_005.json)

- **C001**：Enemy striking wooden roadblock with wood crack layers

### [G029_sfx_006](G029_sfx_006.json)

- **C001**：Bolt impact into scrap armor with fabric tear

### [G029_sfx_007](G029_sfx_007.json)

- **C001**：Raider collapse with gear clatter and dust

### [G029_sfx_008](G029_sfx_008.json)

- **C001**：Warm water spring pulse chime for caravan repair

### [G029_sfx_009](G029_sfx_009.json)

- **C001**：Wooden wagon hull impact with splinter crack

### [G029_sfx_010](G029_sfx_010.json)

- **C001**：Scout horn warning with two rising notes

### [G029_sfx_011](G029_sfx_011.json)

- **C001**：Checkpoin flag snap with relieved exhale tone

### [G029_sfx_012](G029_sfx_012.json)

- **C001**：Warm victory sting with river wash and sail flap

### [G029_sfx_013](G029_sfx_013.json)

- **C001**：Low defeat drone with scattered seed taps

### [G029_sfx_014](G029_sfx_014.json)

- **C001**：Wagon rolling ambience loop with creaking wheels
- **C002**：sail flutter and wind hiss
- **C003**：seamless loop

### [G029_cg_001](G029_cg_001.json)

- **C001**：晨光中长老阿岩将种子袋交上篷车
- **C002**：护卫队收起营火
- **C003**：风帆张满
- **C004**：篷车驶出绿洲边缘
- **C005**：无 UI
- **C006**：无文字
- **C007**：无剪辑
- 审查提示：no_literal_asset_mention_in_general

### [G029_cg_002](G029_cg_002.json)

- **C001**：斥候登高远眺
- **C002**：峡谷岩脊上伏兵剪影绰绰
- **C003**：斥候向篷车方向打出手势警报
- **C004**：无 UI
- **C005**：无文字

### [G029_cg_003](G029_cg_003.json)

- **C001**：夕阳下的河湾渡口
- **C002**：渡船泊在浅滩
- **C003**：河面浮冰漂近
- **C004**：最后路在暮色里展开
- **C005**：无 UI
- **C006**：无文字

### [G029_cg_004](G029_cg_004.json)

- **C001**：不同意象共用条目：胜利=篷车驶上渡船
- **C002**：河对岸绿意隐现
- **C003**：失败=篷车倾覆
- **C004**：种子袋散落风沙
- **C005**：无 UI
- **C006**：无文字
- 审查提示：no_literal_asset_mention_in_general, multi_variant_cg_requires_delivery_convention, branch_delivery_review

