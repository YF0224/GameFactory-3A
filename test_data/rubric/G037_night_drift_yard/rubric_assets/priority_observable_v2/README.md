# G037_night_drift_yard — priority 资产需求 rubric 修订 v2

本目录是独立修订版；旧 `../rubric.json`、`../per_asset/` 及历史分数均保留。
游戏内索引：`../priority_rubric_current.json`。仅包含 priority gen 对应任务，不代表其他资产任务也已修订。
第一列保留可观察的主体、部件、形状、色彩、材质、相对布局、动作/事件及声音内容；精确坐标、尺寸、时长、速度、计数和技术参数只作来源/诊断。
已有逐资产文件的第二/三维原样保留；自然音效与T-pose补充的是此前缺失的rubric草稿，不是历史有效分数。
本版尚未逐项人工审核/最终冻结，也未自动切换生产 evaluator 或重新评测。采用新 schema，必须显式选择并适配，禁止混用旧分数。

| 类型 | 任务数 |
|---|---:|
| 3D Object | 2 |
| 3D Scene | 1 |
| Audio | 12 |
| CG Video | 3 |

## 第一列逐任务预览

以下仅展示计分目标；完整原文、定性投影记录、排除项、判分锚点和第二/三维见对应 JSON。

### [G037_night_drift_yard_obj_008](G037_night_drift_yard_obj_008.json)

- **C001**：Shallow rain puddle plane with soft edge falloff
- **C002**：translucent dark water surface with faint orange lamp reflections
- **C003**：flat decal-like mesh for a radius zone

### [G037_night_drift_yard_obj_009](G037_night_drift_yard_obj_009.json)

- **C001**：Freestanding yard scoreboard frame with blank magnetic panels and chalk tray
- **C002**：weathered steel and plastic
- **C003**：trackside prop with blank surfaces
- **C004**：single object

### [G037_scene_001](G037_scene_001.json)

- **C001**：Enclosed industrial freight yard at night in steady rain
- **C002**：wet reflective concrete ground
- **C003**：tall sodium lamps cutting light pools
- **C004**：corrugated perimeter walls
- **C005**：scattered cargo containers and tire bundles shaping a drift area
- **C006**：shallow puddles
- **C007**：distant port cranes silhouette
- **C008**：visual shell only
- **C009**：开放堆场
- **C010**：场内分布货箱障碍、路灯与积水洼
- **C011**：围墙位于场地四周；不验收碰撞
- 审查提示：no_literal_asset_mention_in_general

### [G037_sfx_001](G037_sfx_001.json)

- **C001**：Clean countdown beep
- **C002**：rising pitch progressively with a faster urgent variant

### [G037_sfx_002](G037_sfx_002.json)

- **C001**：Start release chime with a low swell and rain-muted tail

### [G037_sfx_003](G037_sfx_003.json)

- **C001**：Short bright combo-up arpeggio
- **C002**：one note per multiplier step
- **C003**：dry mix above rain

### [G037_sfx_004](G037_sfx_004.json)

- **C001**：Drift break cue with two soft descending notes and a faint tire release tail

### [G037_sfx_005](G037_sfx_005.json)

- **C001**：Heavy vehicle collision impact with metal crunch and glass tinkle over rain bed
- **C002**：no distortion

### [G037_sfx_006](G037_sfx_006.json)

- **C001**：Tire puddle splash with water fan whoosh and fine droplet patter

### [G037_sfx_007](G037_sfx_007.json)

- **C001**：Handbrake lever click with mechanical ratchet snap and soft rear-tire chirp

### [G037_sfx_008](G037_sfx_008.json)

- **C001**：Victory sting with warm chords and a proud short fanfare over soft rain tail

### [G037_sfx_009](G037_sfx_009.json)

- **C001**：Defeat sting with muted low strings and a slow rain-heavy fade

### [G037_sfx_010](G037_sfx_010.json)

- **C001**：Seamless steady night rain on concrete ambience with distant port machinery hum
- **C002**：no voices or music

### [G037_sfx_011](G037_sfx_011.json)

- **C001**：Seamless rear-drive coupe engine loop at mid load
- **C002**：no manufacturer identity

### [G037_sfx_012](G037_sfx_012.json)

- **C001**：Seamless wet tire skid loop with rubber squeal layers

### [G037_cg_001](G037_cg_001.json)

- **C001**：暴雨中的 7 号货运堆场俯瞰
- **C002**：路灯盏亮起
- **C003**：集装箱间隙里漂移车驶出工坊雨棚
- **C004**：镜头绕场一周停在起点
- **C005**：无 UI
- **C006**：无文字
- **C007**：无剪辑

### [G037_cg_002](G037_cg_002.json)

- **C001**：低机位贴地跟拍轮胎在湿地上划出的水痕弧线
- **C002**：胎烟掠过镜头
- **C003**：路灯光池被车影劈开
- **C004**：无 UI
- **C005**：无文字

### [G037_cg_003](G037_cg_003.json)

- **C001**：不同意象共用条目：胜利=工坊雨棚灯全亮
- **C002**：白板写下新纪录
- **C003**：车手比出手势
- **C004**：失败=雨棚灯熄灭
- **C005**：白板分数被雨冲淡
- **C006**：车影停在光池边
- **C007**：无 UI
- **C008**：无文字
- 审查提示：multi_variant_cg_requires_delivery_convention, branch_delivery_review

