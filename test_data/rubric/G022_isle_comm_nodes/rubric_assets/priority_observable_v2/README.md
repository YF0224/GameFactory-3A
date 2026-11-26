# G022_isle_comm_nodes — priority 资产需求 rubric 修订 v2

本目录是独立修订版；旧 `../rubric.json`、`../per_asset/` 及历史分数均保留。
游戏内索引：`../priority_rubric_current.json`。仅包含 priority gen 对应任务，不代表其他资产任务也已修订。
第一列保留可观察的主体、部件、形状、色彩、材质、相对布局、动作/事件及声音内容；精确坐标、尺寸、时长、速度、计数和技术参数只作来源/诊断。
已有逐资产文件的第二/三维原样保留；自然音效与T-pose补充的是此前缺失的rubric草稿，不是历史有效分数。
本版尚未逐项人工审核/最终冻结，也未自动切换生产 evaluator 或重新评测。采用新 schema，必须显式选择并适配，禁止混用旧分数。

| 类型 | 任务数 |
|---|---:|
| 3D Object | 1 |
| 3D Scene | 1 |
| Audio | 11 |
| CG Video | 3 |

## 第一列逐任务预览

以下仅展示计分目标；完整原文、定性投影记录、排除项、判分锚点和第二/三维见对应 JSON。

### [G022_isle_comm_nodes_obj_005](G022_isle_comm_nodes_obj_005.json)

- **C001**：Single tall-grass concealment tile module
- **C002**：dense reed cluster on a rock base
- **C003**：readable boundary from top view
- **C004**：single object

### [G022_scene_001](G022_scene_001.json)

- **C001**：Single floating-isle encounter map (): two landing wings
- **C002**：central three communication relay nodes
- **C003**：tall-grass concealment clusters
- **C004**：bridge paths
- **C005**：drifting cloud sea below
- **C006**：bright meadow palette
- **C007**：浮岛格状地图
- **C008**：登陆翼分居两侧，节点位于中央
- **C009**：草丛与节点具有可辨的空间分布
- 审查提示：no_literal_asset_mention_in_general

### [G022_sfx_001](G022_sfx_001.json)

- **C001**：Bright turn-start chime with phase banner swell

### [G022_sfx_002](G022_sfx_002.json)

- **C001**：Short step confirm tick as a move order lands

### [G022_sfx_003](G022_sfx_003.json)

- **C001**：Impact hit with armor ring for ranged and melee attacks

### [G022_sfx_004](G022_sfx_004.json)

- **C001**：Warm green heal pulse chime

### [G022_sfx_005](G022_sfx_005.json)

- **C001**：Mist-part reveal shimmer as hidden units become visible

### [G022_sfx_006](G022_sfx_006.json)

- **C001**：Rising capture tick as the hold ring gains a segment

### [G022_sfx_007](G022_sfx_007.json)

- **C001**：Triumphant node ownership change with relay power-up whine

### [G022_sfx_008](G022_sfx_008.json)

- **C001**：Soft defeat dissolve as an unit falls

### [G022_sfx_009](G022_sfx_009.json)

- **C001**：Victory horn as the relay link relights for the win banner

### [G022_sfx_010](G022_sfx_010.json)

- **C001**：Low defeat tone with fading relay hum for the defeat banner

### [G022_sfx_011](G022_sfx_011.json)

- **C001**：Floating isle wind and distant surf ambience loop with reed rustle
- **C002**：no seam artifacts

### [G022_cg_001](G022_cg_001.json)

- **C001**：浮岛链路全景：中继塔的信号灯逐一熄灭
- **C002**：守备队从双登陆翼登岛
- **C003**：镜头推向中央节点群
- **C004**：无剪辑
- **C005**：无 UI
- **C006**：无文字

### [G022_cg_002](G022_cg_002.json)

- **C001**：占点环满 的瞬间
- **C002**：节点塔换旗
- **C003**：涟漪沿链路扩散到相邻节点
- **C004**：驻留单位举旗示意

### [G022_cg_003](G022_cg_003.json)

- **C001**：胜负不同意象：胜利=三节点信号灯重联点亮
- **C002**：链路光带贯穿浮岛
- **C003**：守备队旗帜升起
- **C004**：失败=节点灯熄灭
- **C005**：静默波纹扩散
- **C006**：守备队收拢残旗
- 审查提示：multi_variant_cg_requires_delivery_convention, branch_delivery_review

