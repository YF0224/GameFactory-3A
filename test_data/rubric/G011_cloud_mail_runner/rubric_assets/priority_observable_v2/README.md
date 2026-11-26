# G011_cloud_mail_runner — priority 资产需求 rubric 修订 v2

本目录是独立修订版；旧 `../rubric.json`、`../per_asset/` 及历史分数均保留。
游戏内索引：`../priority_rubric_current.json`。仅包含 priority gen 对应任务，不代表其他资产任务也已修订。
第一列保留可观察的主体、部件、形状、色彩、材质、相对布局、动作/事件及声音内容；精确坐标、尺寸、时长、速度、计数和技术参数只作来源/诊断。
已有逐资产文件的第二/三维原样保留；自然音效与T-pose补充的是此前缺失的rubric草稿，不是历史有效分数。
本版尚未逐项人工审核/最终冻结，也未自动切换生产 evaluator 或重新评测。采用新 schema，必须显式选择并适配，禁止混用旧分数。

| 类型 | 任务数 |
|---|---:|
| 3D Object | 3 |
| 3D Scene | 1 |
| Audio | 8 |
| CG Video | 3 |

## 第一列逐任务预览

以下仅展示计分目标；完整原文、定性投影记录、排除项、判分锚点和第二/三维见对应 JSON。

### [G011_cloud_mail_runner_obj_004](G011_cloud_mail_runner_obj_004.json)

- **C001**：Single mid-height relay step platform
- **C002**：entry to the upper storm-ridge route
- **C003**：each vertical rise
- **C004**：cloud-stone slab on support struts
- **C005**：single object

### [G011_cloud_mail_runner_obj_005](G011_cloud_mail_runner_obj_005.json)

- **C001**：Single floating mail-beacon light piece
- **C002**：small glowing envelope-shaped crystal with a soft ring
- **C003**：independent silhouette
- **C004**：single object

### [G011_cloud_mail_runner_obj_006](G011_cloud_mail_runner_obj_006.json)

- **C001**：Single checkpoint beacon lamp post with amber lens and a warm breath-light
- **C002**：state shown by material
- **C003**：single object

### [G011_scene_001](G011_scene_001.json)

- **C001**：finite side-view sky mail route with upper storm-ridge platform route
- **C002**：lower safe cloud-deck route
- **C003**：five checkpoint beacons and a distant lighthouse
- **C004**：drifting sea of clouds below
- **C005**：hand-painted bright palette
- **C006**：有限且连续的路线
- **C007**：起始段为无障碍教学段
- **C008**：上层通道高于下层，入口设中继台阶
- **C009**：连续障碍具有高、低、高的相对排列
- **C010**：检查点沿路线分布；不验收激活逻辑
- 审查提示：no_literal_asset_mention_in_general

### [G011_sfx_001](G011_sfx_001.json)

- **C001**：Bright wind-cutting whoosh for jump takeoff

### [G011_sfx_002](G011_sfx_002.json)

- **C001**：Cloth-and-deck friction swish for the slide

### [G011_sfx_003](G011_sfx_003.json)

- **C001**：Crisp envelope-ping chime as a light piece is collected

### [G011_sfx_004](G011_sfx_004.json)

- **C001**：Muffled impact thud for hitting a barrier

### [G011_sfx_005](G011_sfx_005.json)

- **C001**：Warm rising two-note call as a checkpoint beacon lights

### [G011_sfx_006](G011_sfx_006.json)

- **C001**：Rising updraft gust entering the storm-ridge upper route

### [G011_sfx_007](G011_sfx_007.json)

- **C001**：Lighthouse bell ringing twice for a completed delivery run

### [G011_sfx_008](G011_sfx_008.json)

- **C001**：Low descending tone as the letters scatter into the clouds

### [G011_cg_001](G011_cg_001.json)

- **C001**：暴风云带逼近悬空邮路的远景
- **C002**：镜头缓缓推近最后一位云端邮差背包上的急件
- **C003**：远处云端灯塔在风幕中透出橙光
- **C004**：无剪辑
- **C005**：无 UI
- **C006**：无文字的定格开场

### [G011_cg_002](G011_cg_002.json)

- **C001**：镜头随邮差踏上 中继台阶拉升
- **C002**：展现上层暴风脊线通道——高密度光件在风中排列
- **C003**：与下层稳妥栈道形成对比

### [G011_cg_003](G011_cg_003.json)

- **C001**：胜负不同意象：胜利=邮差冲过终点门框
- **C002**：灯塔钟声响起
- **C003**：光件汇入灯塔
- **C004**：失败=急件散落云海
- **C005**：邮差在检查点灯旁坐望风暴
- 审查提示：multi_variant_cg_requires_delivery_convention, branch_delivery_review

