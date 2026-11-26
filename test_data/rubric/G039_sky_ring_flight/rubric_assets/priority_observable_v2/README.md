# G039_sky_ring_flight — priority 资产需求 rubric 修订 v2

本目录是独立修订版；旧 `../rubric.json`、`../per_asset/` 及历史分数均保留。
游戏内索引：`../priority_rubric_current.json`。仅包含 priority gen 对应任务，不代表其他资产任务也已修订。
第一列保留可观察的主体、部件、形状、色彩、材质、相对布局、动作/事件及声音内容；精确坐标、尺寸、时长、速度、计数和技术参数只作来源/诊断。
已有逐资产文件的第二/三维原样保留；自然音效与T-pose补充的是此前缺失的rubric草稿，不是历史有效分数。
本版尚未逐项人工审核/最终冻结，也未自动切换生产 evaluator 或重新评测。采用新 schema，必须显式选择并适配，禁止混用旧分数。

| 类型 | 任务数 |
|---|---:|
| 3D Object | 1 |
| 3D Scene | 1 |
| Audio | 14 |
| CG Video | 3 |

## 第一列逐任务预览

以下仅展示计分目标；完整原文、定性投影记录、排除项、判分锚点和第二/三维见对应 JSON。

### [G039_sky_ring_flight_obj_005](G039_sky_ring_flight_obj_005.json)

- **C001**：Mast-mounted wind streamer array with thin pennant ribbons and a small brass anemometer cage
- **C002**：single object

### [G039_scene_001](G039_scene_001.json)

- **C001**：Floating sky islands above a cloud sea at sunrise
- **C002**：twelve ring gates in multiple sections: low island-edge rings
- **C003**：a wind valley with drifting stream lines and two rising thermal columns
- **C004**：and narrow high-altitude rings near a lighthouse isle
- **C005**：takeoff deck on the first island cliff
- **C006**：bright painterly sky
- **C007**：visual shell only
- **C008**：环架沿分段路线分布
- **C009**：上升气流柱具有可见表现；不验收推力
- **C010**：检查点相对位于环架后下方，不检查距离或复位机制
- 审查提示：no_literal_asset_mention_in_general

### [G039_sfx_001](G039_sfx_001.json)

- **C001**：Short wind swell on takeoff with canvas flutter and propeller spin-up tail

### [G039_sfx_002](G039_sfx_002.json)

- **C001**：Bright ring pass chime with a bell-like ping tail and soft airy pad

### [G039_sfx_003](G039_sfx_003.json)

- **C001**：Ring miss warning with two quick mid-tone notes and a slight flutter

### [G039_sfx_004](G039_sfx_004.json)

- **C001**：Pre-stall caution beep
- **C002**：single mid-frequency tone with soft repetition

### [G039_sfx_005](G039_sfx_005.json)

- **C001**：Stall alarm with urgent dual-tone siren pulses and rising wind noise bed

### [G039_sfx_006](G039_sfx_006.json)

- **C001**：Rising thermal whoosh with light particle sparkle textures and a lift swell

### [G039_sfx_007](G039_sfx_007.json)

- **C001**：Aerial crash impact with wood creak
- **C002**：canvas tear and debris scatter

### [G039_sfx_008](G039_sfx_008.json)

- **C001**：Respawn transition whoosh with airy shimmer and a beacon ping tail

### [G039_sfx_009](G039_sfx_009.json)

- **C001**：Time-out alarm with three descending urgent pulses and a low wind tail

### [G039_sfx_010](G039_sfx_010.json)

- **C001**：Victory sting with bright sky-island bells and a warm rising finish

### [G039_sfx_011](G039_sfx_011.json)

- **C001**：Defeat sting with muted low bells and a cold wind fade

### [G039_sfx_012](G039_sfx_012.json)

- **C001**：Seamless high-altitude wind ambience over a cloud sea
- **C002**：airy and clean
- **C003**：no voices or music

### [G039_sfx_013](G039_sfx_013.json)

- **C001**：Seamless wind-valley turbulence loop with gusty layers

### [G039_sfx_014](G039_sfx_014.json)

- **C001**：Seamless light courier glider engine loop with propeller hum

### [G039_cg_001](G039_cg_001.json)

- **C001**：云海日出
- **C002**：群岛灯塔依次亮起
- **C003**：信使邮翼机在起飞平台展开帆布翼
- **C004**：镜头自灯塔上空掠到平台正后方
- **C005**：无 UI
- **C006**：无文字
- **C007**：无剪辑

### [G039_cg_002](G039_cg_002.json)

- **C001**：机身被上升粒子托举
- **C002**：穿过风谷环门的脉冲光环
- **C003**：风线自侧方掠过镜头
- **C004**：无 UI
- **C005**：无文字

### [G039_cg_003](G039_cg_003.json)

- **C001**：不同意象共用条目：胜利=终岛灯塔点亮
- **C002**：信封送达
- **C003**：邮翼机绕塔盘旋
- **C004**：失败=灯塔灯暗
- **C005**：信封被风卷走
- **C006**：机身停在检查点浮标旁
- **C007**：无 UI
- **C008**：无文字
- 审查提示：multi_variant_cg_requires_delivery_convention, branch_delivery_review

