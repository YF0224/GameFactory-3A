# G013_wind_tower_grapple — priority 资产需求 rubric 修订 v2

本目录是独立修订版；旧 `../rubric.json`、`../per_asset/` 及历史分数均保留。
游戏内索引：`../priority_rubric_current.json`。仅包含 priority gen 对应任务，不代表其他资产任务也已修订。
第一列保留可观察的主体、部件、形状、色彩、材质、相对布局、动作/事件及声音内容；精确坐标、尺寸、时长、速度、计数和技术参数只作来源/诊断。
已有逐资产文件的第二/三维原样保留；自然音效与T-pose补充的是此前缺失的rubric草稿，不是历史有效分数。
本版尚未逐项人工审核/最终冻结，也未自动切换生产 evaluator 或重新评测。采用新 schema，必须显式选择并适配，禁止混用旧分数。

| 类型 | 任务数 |
|---|---:|
| 3D Scene | 1 |
| Audio | 14 |
| CG Video | 3 |

## 第一列逐任务预览

以下仅展示计分目标；完整原文、定性投影记录、排除项、判分锚点和第二/三维见对应 JSON。

### [G013_scene_001](G013_scene_001.json)

- **C001**：Single canyon inspection line with multiple sections (teaching cliff, long-swing gust gap, precision-landing tower cluster)
- **C002**：ring anchors between towers
- **C003**：four checkpoint signal posts
- **C004**：gust-zone ground markers
- **C005**：cloud-mist fall zone at the canyon bottom
- **C006**：realistic stylized palette
- **C007**：峡谷巡检路线具有教学、长摆荡和精密落点区段
- **C008**：锚点与检查点沿路线分布
- **C009**：长摆荡区段内具有阵风带的可见表现
- 审查提示：no_literal_asset_mention_in_general

### [G013_sfx_001](G013_sfx_001.json)

- **C001**：Short soft ping as a candidate anchor enters detection range

### [G013_sfx_002](G013_sfx_002.json)

- **C001**：Taut rope twang as the grapple line pulls tight on connection

### [G013_sfx_003](G013_sfx_003.json)

- **C001**：Metal hook clamping bite onto a ring anchor

### [G013_sfx_004](G013_sfx_004.json)

- **C001**：Dry rebound click as an out-of-range or out-of-angle anchor request is refused

### [G013_sfx_005](G013_sfx_005.json)

- **C001**：Swing wind howl that intensifies with speed
- **C002**：loopable slice for long pendulum arcs

### [G013_sfx_006](G013_sfx_006.json)

- **C001**：Hook detach pop with a rising slip of rope as the grapple releases

### [G013_sfx_007](G013_sfx_007.json)

- **C001**：Short cloth-flap wind cut for mid-air steering adjustment

### [G013_sfx_008](G013_sfx_008.json)

- **C001**：Gust roar swell as the inspector enters a wind band
- **C002**：dust-line texture

### [G013_sfx_009](G013_sfx_009.json)

- **C001**：Muffled landing thud with a light gravel scatter

### [G013_sfx_010](G013_sfx_010.json)

- **C001**：Descending fall slide as the inspector drops into the cloud-mist fall zone

### [G013_sfx_011](G013_sfx_011.json)

- **C001**：Warm signal activation chord as a checkpoint lamp column lights up

### [G013_sfx_012](G013_sfx_012.json)

- **C001**：Noble horn call as the tower-top beacon relights for victory

### [G013_sfx_013](G013_sfx_013.json)

- **C001**：Low sinking tone with desaturated wind as the run fails

### [G013_sfx_014](G013_sfx_014.json)

- **C001**：Canyon wind ambience loop
- **C002**：constant low bed
- **C003**：slight rise inside gust zones
- **C004**：no seam artifacts

### [G013_cg_001](G013_cg_001.json)

- **C001**：峡谷风口全景：一排风塔在风幕中只剩轮廓
- **C002**：塔顶信号灯熄灭
- **C003**：巡检员在崖边扣紧抓钩
- **C004**：镜头掠向巡检线尽头亮着的终点塔
- **C005**：无剪辑
- **C006**：无 UI
- **C007**：无文字

### [G013_cg_002](G013_cg_002.json)

- **C001**：镜头侧跟摆荡中的巡检员冲入风口：尘线横扫画面
- **C002**：绳索被风吹出更大的弧线
- **C003**：衣摆与旗布同向翻卷
- **C004**：HUD 风向标记亮起

### [G013_cg_003](G013_cg_003.json)

- **C001**：胜负不同意象：胜利=终点塔顶信标重新亮起
- **C002**：光沿巡检线逐塔点亮
- **C003**：巡检员收起抓钩远眺
- **C004**：失败=云雾从峡谷底涌上巡检线
- **C005**：信号灯逐盏熄灭
- **C006**：日志合上
- 审查提示：multi_variant_cg_requires_delivery_convention, branch_delivery_review

