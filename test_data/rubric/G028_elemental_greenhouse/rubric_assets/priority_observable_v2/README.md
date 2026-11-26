# G028_elemental_greenhouse — priority 资产需求 rubric 修订 v2

本目录是独立修订版；旧 `../rubric.json`、`../per_asset/` 及历史分数均保留。
游戏内索引：`../priority_rubric_current.json`。仅包含 priority gen 对应任务，不代表其他资产任务也已修订。
第一列保留可观察的主体、部件、形状、色彩、材质、相对布局、动作/事件及声音内容；精确坐标、尺寸、时长、速度、计数和技术参数只作来源/诊断。
已有逐资产文件的第二/三维原样保留；自然音效与T-pose补充的是此前缺失的rubric草稿，不是历史有效分数。
本版尚未逐项人工审核/最终冻结，也未自动切换生产 evaluator 或重新评测。采用新 schema，必须显式选择并适配，禁止混用旧分数。

| 类型 | 任务数 |
|---|---:|
| 3D Object | 4 |
| 3D Scene | 1 |
| Audio | 19 |
| CG Video | 4 |

## 第一列逐任务预览

以下仅展示计分目标；完整原文、定性投影记录、排除项、判分锚点和第二/三维见对应 JSON。

### [G028_elemental_greenhouse_obj_012](G028_elemental_greenhouse_obj_012.json)

- **C001**：Broken greenhouse vent gate where vine walkers emerge
- **C002**：overgrown with creepers
- **C003**：single object

### [G028_elemental_greenhouse_obj_013](G028_elemental_greenhouse_obj_013.json)

- **C001**：Greenhouse planter-box build pad with soil grid and metal corner brackets
- **C002**：one-grid build slot
- **C003**：single object

### [G028_elemental_greenhouse_obj_014](G028_elemental_greenhouse_obj_014.json)

- **C001**：Young sprout in a reinforced glass seed capsule beside the vault
- **C002**：hopeful tiny plant
- **C003**：single object

### [G028_elemental_greenhouse_obj_015](G028_elemental_greenhouse_obj_015.json)

- **C001**：Industrial greenhouse air duct segment with frost on one end and heat glow on the other
- **C002**：environment prop
- **C003**：single object

### [G028_scene_001](G028_scene_001.json)

- **C001**：Underground greenhouse interior seen from above: S-shaped path crossing a frost zone and a furnace zone
- **C002**：glass dome overhead with steam pipes
- **C003**：seed vault base at the far end
- **C004**：vine-covered vents
- **C005**：humid jungle light
- **C006**：温室内具有 S 形路线和沿线建造位置
- **C007**：冰霜区与熔炉区有可辨的视觉分区
- 审查提示：no_literal_asset_mention_in_general

### [G028_vo_015](G028_vo_015.json)

- **C001**：Calm but urgent female AI voice over greenhouse PA
- **C002**：Chinese
- **C003**：clean synth tone
- **C004**：slight reverb
- **C005**：警报：恒温系统失控，藤蔓正朝种子库蔓延。管理员，请立即布防。
- **C006**：语音使用声明的语言：Chinese
- **C007**：语音表达声明的情绪：tense
- 审查提示：no_literal_asset_mention_in_general

### [G028_vo_016](G028_vo_016.json)

- **C001**：Warning AI broadcast with falling intonation
- **C002**：Chinese
- **C003**：PA reverb
- **C004**：熔炉区藤蔓已碳化，下一波对火焰免疫。
- **C005**：语音使用声明的语言：Chinese
- **C006**：语音表达声明的情绪：urgent
- 审查提示：no_literal_asset_mention_in_general

### [G028_vo_017](G028_vo_017.json)

- **C001**：Warning AI broadcast with falling intonation
- **C002**：Chinese
- **C003**：PA reverb
- **C004**：冰霜区藤蔓已结晶，下一波对寒霜免疫。
- **C005**：语音使用声明的语言：Chinese
- **C006**：语音表达声明的情绪：urgent
- 审查提示：no_literal_asset_mention_in_general

### [G028_vo_018](G028_vo_018.json)

- **C001**：Relieved warm AI voice
- **C002**：Chinese
- **C003**：soft PA reverb
- **C004**：恒温恢复。种子库安全，母株开始发芽。
- **C005**：语音使用声明的语言：Chinese
- **C006**：语音表达声明的情绪：joyful
- 审查提示：no_literal_asset_mention_in_general

### [G028_vo_019](G028_vo_019.json)

- **C001**：Failing low-power AI voice with static decay
- **C002**：Chinese
- **C003**：种子库穹顶破裂……系统离线。
- **C004**：语音使用声明的语言：Chinese
- **C005**：语音表达声明的情绪：tense
- 审查提示：no_literal_asset_mention_in_general

### [G028_sfx_001](G028_sfx_001.json)

- **C001**：Frost tower shot with crystal chime and mist hiss

### [G028_sfx_002](G028_sfx_002.json)

- **C001**：Flame tower ignition burst with low whoosh

### [G028_sfx_003](G028_sfx_003.json)

- **C001**：Short flame crackle tick for burn damage over time

### [G028_sfx_004](G028_sfx_004.json)

- **C001**：Ice-and-fire interwoven shatter chime
- **C002**：dual-layer burst

### [G028_sfx_005](G028_sfx_005.json)

- **C001**：Crystal rock tower shot with stone percussion

### [G028_sfx_006](G028_sfx_006.json)

- **C001**：Dry deflect ping with particle dissipation tail
- **C002**：zero-damage feel

### [G028_sfx_007](G028_sfx_007.json)

- **C001**：Two-tone immunity wave warning with greenhouse alarm undertone

### [G028_sfx_008](G028_sfx_008.json)

- **C001**：Rising transformation swell with glass chime finish

### [G028_sfx_009](G028_sfx_009.json)

- **C001**：Plant stalk snap and leaf scatter with wilting hiss

### [G028_sfx_010](G028_sfx_010.json)

- **C001**：Glass dome impact crack with alarm echo

### [G028_sfx_011](G028_sfx_011.json)

- **C001**：Wave banner horn with vine rustle underneath

### [G028_sfx_012](G028_sfx_012.json)

- **C001**：Warm victory sting with sprouting chime and settling steam

### [G028_sfx_013](G028_sfx_013.json)

- **C001**：Low defeat drone with glass shatter tail

### [G028_sfx_014](G028_sfx_014.json)

- **C001**：Greenhouse ambience loop with water mist hiss
- **C002**：distant mechanical hum and drips
- **C003**：seamless loop
- **C004**：no seam artifacts

### [G028_cg_001](G028_cg_001.json)

- **C001**：地下温室「四季穹顶」全景：冰霜区与熔炉区雾气对冲
- **C002**：失控苗圃的藤蔓行者破土而出
- **C003**：镜头推向种子库大门
- **C004**：无 UI
- **C005**：无文字
- **C006**：无剪辑

### [G028_cg_002](G028_cg_002.json)

- **C001**：熔炉区蒸汽扫过藤蔓植株
- **C002**：枝条碳化成焦黑晶壳
- **C003**：火免疫图标意象浮现
- **C004**：无 UI
- **C005**：无文字

### [G028_cg_003](G028_cg_003.json)

- **C001**：冰霜区寒气漫过藤蔓植株
- **C002**：枝条凝出蓝白冰晶
- **C003**：冰免疫图标意象浮现
- **C004**：无 UI
- **C005**：无文字

### [G028_cg_004](G028_cg_004.json)

- **C001**：不同意象共用条目：胜利=恒温恢复
- **C002**：种子库母株破土发芽
- **C003**：暖光铺满穹顶
- **C004**：失败=穹顶玻璃破裂
- **C005**：藤蔓吞没种子库
- **C006**：灯光熄灭
- **C007**：无 UI
- **C008**：无文字
- 审查提示：multi_variant_cg_requires_delivery_convention, branch_delivery_review

