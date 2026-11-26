# G044_robot_workshop — priority 资产需求 rubric 修订 v2

本目录是独立修订版；旧 `../rubric.json`、`../per_asset/` 及历史分数均保留。
游戏内索引：`../priority_rubric_current.json`。仅包含 priority gen 对应任务，不代表其他资产任务也已修订。
第一列保留可观察的主体、部件、形状、色彩、材质、相对布局、动作/事件及声音内容；精确坐标、尺寸、时长、速度、计数和技术参数只作来源/诊断。
已有逐资产文件的第二/三维原样保留；自然音效与T-pose补充的是此前缺失的rubric草稿，不是历史有效分数。
本版尚未逐项人工审核/最终冻结，也未自动切换生产 evaluator 或重新评测。采用新 schema，必须显式选择并适配，禁止混用旧分数。

| 类型 | 任务数 |
|---|---:|
| 3D Scene | 1 |
| Audio | 11 |
| CG Video | 3 |

## 第一列逐任务预览

以下仅展示计分目标；完整原文、定性投影记录、排除项、判分锚点和第二/三维见对应 JSON。

### [G044_scene_001](G044_scene_001.json)

- **C001**：Rivet-bay repair workshop scene
- **C002**：grid floor with painted lane markings
- **C003**：two wall ore chutes on the left edge
- **C004**：hanging lamps
- **C005**：tool wall and rain-streak windows with small-town skyline beyond
- **C006**：clean readable engineering daylight
- **C007**：visual shell only
- **C008**：采矿口具有朝东的输出方向表现；不验收物流
- **C009**：其余布局及交付口由玩家编排，不强制固定位置
- 审查提示：no_literal_asset_mention_in_general

### [G044_sfx_001](G044_sfx_001.json)

- **C001**：Part placement thud with metallic snap-fit click
- **C002**：short and satisfying

### [G044_sfx_002](G044_sfx_002.json)

- **C001**：Part removal: ratchet unbolt and debris scatter
- **C002**：slightly longer than placement

### [G044_sfx_003](G044_sfx_003.json)

- **C001**：Assembly step: brief mechanical press with grinding spark tail

### [G044_sfx_004](G044_sfx_004.json)

- **C001**：Assembly complete: crisp spring-release clunk with bright confirmation tick

### [G044_sfx_005](G044_sfx_005.json)

- **C001**：Delivery count tick: crate lands on slide rail with counting pylon beep

### [G044_sfx_006](G044_sfx_006.json)

- **C001**：Jam alert: two urgent mid-tone pulses with low mechanical strain undertone

### [G044_sfx_007](G044_sfx_007.json)

- **C001**：Recovery flush: pneumatic whoosh with items clearing and relay reset click
- **C002**：also used for line reset profile

### [G044_sfx_008](G044_sfx_008.json)

- **C001**：Shift victory sting: bright industrial marimba and light machinery rhythm rising to proud finish

### [G044_sfx_009](G044_sfx_009.json)

- **C001**：Defeat sting: power-down low mechanical sigh with distant rain tail
- **C002**：also used for deadlock profile

### [G044_sfx_010](G044_sfx_010.json)

- **C001**：Seamless workshop ambience: distant rain on windows
- **C002**：faint radio static and idle machinery hum
- **C003**：no voices or music

### [G044_sfx_011](G044_sfx_011.json)

- **C001**：Seamless conveyor hum loop with two load profiles: light empty roller rattle and heavier loaded rumble

### [G044_cg_001](G044_cg_001.json)

- **C001**：铆钉湾雨后清晨
- **C002**：车间吊灯依次亮起
- **C003**：墙上矿料滑槽落料
- **C004**：台组装台就位
- **C005**：订单板亮出「躯干」
- **C006**：无 UI
- **C007**：无文字
- **C008**：无剪辑
- 审查提示：source_text_display_conflict

### [G044_cg_002](G044_cg_002.json)

- **C001**：传送带物料堆积
- **C002**：红色高亮沿上游蔓延
- **C003**：工程师俯身改线
- **C004**：分流格落位后物料恢复流动
- **C005**：无 UI
- **C006**：无文字

### [G044_cg_003](G044_cg_003.json)

- **C001**：不同意象共用条目：胜利＝传送带满载躯干列队出库
- **C002**：协会徽章点亮
- **C003**：失败＝吊灯熄灭
- **C004**：协会徽章收回
- **C005**：车间归于安静
- **C006**：无 UI
- **C007**：无文字
- 审查提示：multi_variant_cg_requires_delivery_convention, branch_delivery_review

