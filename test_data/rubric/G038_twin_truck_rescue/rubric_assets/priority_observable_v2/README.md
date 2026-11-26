# G038_twin_truck_rescue — priority 资产需求 rubric 修订 v2

本目录是独立修订版；旧 `../rubric.json`、`../per_asset/` 及历史分数均保留。
游戏内索引：`../priority_rubric_current.json`。仅包含 priority gen 对应任务，不代表其他资产任务也已修订。
第一列保留可观察的主体、部件、形状、色彩、材质、相对布局、动作/事件及声音内容；精确坐标、尺寸、时长、速度、计数和技术参数只作来源/诊断。
已有逐资产文件的第二/三维原样保留；自然音效与T-pose补充的是此前缺失的rubric草稿，不是历史有效分数。
本版尚未逐项人工审核/最终冻结，也未自动切换生产 evaluator 或重新评测。采用新 schema，必须显式选择并适配，禁止混用旧分数。

| 类型 | 任务数 |
|---|---:|
| 3D Object | 2 |
| 3D Scene | 1 |
| Audio | 14 |
| CG Video | 3 |

## 第一列逐任务预览

以下仅展示计分目标；完整原文、定性投影记录、排除项、判分锚点和第二/三维见对应 JSON。

### [G038_twin_truck_rescue_obj_008](G038_twin_truck_rescue_obj_008.json)

- **C001**：Roadside recovery checkpoint marker post with orange reflector band and small flag
- **C002**：lightweight steel pole
- **C003**：readable at distance
- **C004**：single object

### [G038_twin_truck_rescue_obj_009](G038_twin_truck_rescue_obj_009.json)

- **C001**：Bent steel mountain warning signpost with blank chevron panel and rockfall hazard plate
- **C002**：weathered yellow-black paint
- **C003**：single object

### [G038_scene_001](G038_scene_001.json)

- **C001**：Mountain valley rescue route at overcast morning
- **C002**：staging camp at the foot with a stalled supply van
- **C003**：a long safe river road and a shorter narrow canyon shortcut with three fresh rockfall piles
- **C004**：checkpoint marker posts every
- **C005**：delivery relay station over the pass
- **C006**：wind-carved rock walls
- **C007**：visual shell only
- **C008**：山脚营地装货点与交付站之间具有路线连接
- **C009**：稳路与险路共享起终点
- **C010**：检查点沿线分布，并有落石区与碎石的可见表现
- 审查提示：no_literal_asset_mention_in_general

### [G038_sfx_001](G038_sfx_001.json)

- **C001**：Synchronized start countdown beep with a clear low tail for both clients

### [G038_sfx_002](G038_sfx_002.json)

- **C001**：Steel winch cable creak and ratchet clicks with layered tension variants from slack to critical

### [G038_sfx_003](G038_sfx_003.json)

- **C001**：Cable snap with sharp whip crack and recoiling steel whip tail
- **C002**：no distortion

### [G038_sfx_004](G038_sfx_004.json)

- **C001**：Cargo transfer whoosh with a soft landing thud in a truck bed

### [G038_sfx_005](G038_sfx_005.json)

- **C001**：Heavy truck collision impact with rock crunch and cargo shift rattle

### [G038_sfx_006](G038_sfx_006.json)

- **C001**：Distant rockfall rumble with rolling scree patter
- **C002**：warning flavor for blocked zone approach

### [G038_sfx_007](G038_sfx_007.json)

- **C001**：Pneumatic rock drill bursts with debris clatter
- **C002**：loopable segments that rise with clearing progress

### [G038_sfx_008](G038_sfx_008.json)

- **C001**：Road cleared confirmation with dust settle swish and a short bright resolve note

### [G038_sfx_009](G038_sfx_009.json)

- **C001**：Two-tone radio chime with a soft static tail
- **C002**：non-verbal coordination cue

### [G038_sfx_010](G038_sfx_010.json)

- **C001**：Victory sting with warm brass chords and a mountain-echo tail

### [G038_sfx_011](G038_sfx_011.json)

- **C001**：Defeat sting with muted low strings and a cold wind tail

### [G038_sfx_012](G038_sfx_012.json)

- **C001**：Seamless heavy winch tractor engine loop at mid load
- **C002**：no manufacturer identity

### [G038_sfx_013](G038_sfx_013.json)

- **C001**：Seamless recovery truck engine loop slightly higher pitch character than the tractor

### [G038_sfx_014](G038_sfx_014.json)

- **C001**：Seamless mountain valley wind ambience with distant scree falls and bird-free rocky stillness
- **C002**：no voices or music

### [G038_cg_001](G038_cg_001.json)

- **C001**：山脚营地晨雾
- **C002**：被困物资车闪着双闪停在峡谷
- **C003**：A 牵引车绞盘就位
- **C004**：B 清障车驶向落石区
- **C005**：镜头自垭口俯冲到双车汇合
- **C006**：无 UI
- **C007**：无文字
- **C008**：无剪辑

### [G038_cg_002](G038_cg_002.json)

- **C001**：B 清障车凿开落石
- **C002**：碎石飞溅
- **C003**：警示带撤除
- **C004**：A 牵引车拖拽物资车从敞开的窄弯通过
- **C005**：无 UI
- **C006**：无文字

### [G038_cg_003](G038_cg_003.json)

- **C001**：不同意象共用条目：胜利=交付站灯亮
- **C002**：物资箱入库
- **C003**：双车鸣笛
- **C004**：失败=山谷夜幕
- **C005**：营地灯暗
- **C006**：物资箱滞留原地
- **C007**：无 UI
- **C008**：无文字
- 审查提示：multi_variant_cg_requires_delivery_convention, branch_delivery_review

