# G014_dual_zone_waterworks — priority 资产需求 rubric 修订 v2

本目录是独立修订版；旧 `../rubric.json`、`../per_asset/` 及历史分数均保留。
游戏内索引：`../priority_rubric_current.json`。仅包含 priority gen 对应任务，不代表其他资产任务也已修订。
第一列保留可观察的主体、部件、形状、色彩、材质、相对布局、动作/事件及声音内容；精确坐标、尺寸、时长、速度、计数和技术参数只作来源/诊断。
已有逐资产文件的第二/三维原样保留；自然音效与T-pose补充的是此前缺失的rubric草稿，不是历史有效分数。
本版尚未逐项人工审核/最终冻结，也未自动切换生产 evaluator 或重新评测。采用新 schema，必须显式选择并适配，禁止混用旧分数。

| 类型 | 任务数 |
|---|---:|
| 3D Scene | 1 |
| Audio | 12 |
| CG Video | 3 |

## 第一列逐任务预览

以下仅展示计分目标；完整原文、定性投影记录、排除项、判分锚点和第二/三维见对应 JSON。

### [G014_scene_001](G014_scene_001.json)

- **C001**：Split hydro facility in a high mountain: upstream sluice zone with two pressure plates
- **C002**：discharge channel and gate A1
- **C003**：downstream pump-house zone with lever station and two doors
- **C004**：convergence terminal zone with joint-goal platform
- **C005**：wet concrete
- **C006**：steel rails and water light bands
- **C007**：industrial palette
- **C008**：水闸区与泵房区相互分离，并通向汇合终点区
- **C009**：水闸区具有压板、水道闸门和泄洪水道
- **C010**：泵房区具有拉杆和门
- **C011**：终点区与检查点具有可见标识；不验收共享或激活机制
- 审查提示：no_literal_asset_mention_in_general

### [G014_sfx_001](G014_sfx_001.json)

- **C001**：Heavy pressure plate sinking thunk with metal strain

### [G014_sfx_002](G014_sfx_002.json)

- **C001**：Industrial lever ratchet pull with valve hiss

### [G014_sfx_003](G014_sfx_003.json)

- **C001**：Sluice gate rising with hydraulic whine and water release

### [G014_sfx_004](G014_sfx_004.json)

- **C001**：Gate falling back with a low clunk and brief water settle

### [G014_sfx_005](G014_sfx_005.json)

- **C001**：Short bright ping as a teammate marker appears

### [G014_sfx_006](G014_sfx_006.json)

- **C001**：Soft dissolve-in shimmer with a rising resolve as a worker respawns

### [G014_sfx_007](G014_sfx_007.json)

- **C001**：Brief urgent alert as the gate safely repositions a blocked player

### [G014_sfx_008](G014_sfx_008.json)

- **C001**：Twin-lamp convergence chime for the joint win beacons

### [G014_sfx_009](G014_sfx_009.json)

- **C001**：Pulsing alarm for mechanism deadlock timeout

### [G014_sfx_010](G014_sfx_010.json)

- **C001**：Low descending tone as the repair window expires

### [G014_sfx_011](G014_sfx_011.json)

- **C001**：Discharge channel rushing water ambience loop
- **C002**：constant bed
- **C003**：no seam artifacts

### [G014_sfx_012](G014_sfx_012.json)

- **C001**：Pump-house machinery low hum ambience loop with faint steam

### [G014_cg_001](G014_cg_001.json)

- **C001**：航拍山体隔断的高山水利枢纽：上游水闸区与下游泵房区检修灯同时亮起
- **C002**：镜头沿水线推向汇合终点台
- **C003**：无剪辑
- **C004**：无 UI
- **C005**：无文字

### [G014_cg_002](G014_cg_002.json)

- **C001**：分屏对切：A 端踩下压板的同时 B 端门铰上扬
- **C002**：水线光带流过门洞
- **C003**：两端维护员隔屏对望
- **C004**：ping 标注在两帧间穿针引线

### [G014_cg_003](G014_cg_003.json)

- **C001**：胜负不同意象：胜利=双端维护员在终点台并肩
- **C002**：双灯同亮
- **C003**：汇流光带贯穿全图
- **C004**：失败=警示灯闪烁
- **C005**：水线光带熄灭
- **C006**：检修记录合上注明原因
- 审查提示：multi_variant_cg_requires_delivery_convention, branch_delivery_review

