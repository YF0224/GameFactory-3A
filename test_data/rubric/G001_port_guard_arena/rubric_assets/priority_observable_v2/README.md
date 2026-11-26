# G001_port_guard_arena — priority 资产需求 rubric 修订 v2

本目录是独立修订版；旧 `../rubric.json`、`../per_asset/` 及历史分数均保留。
游戏内索引：`../priority_rubric_current.json`。仅包含 priority gen 对应任务，不代表其他资产任务也已修订。
第一列保留可观察的主体、部件、形状、色彩、材质、相对布局、动作/事件及声音内容；精确坐标、尺寸、时长、速度、计数和技术参数只作来源/诊断。
已有逐资产文件的第二/三维原样保留；自然音效与T-pose补充的是此前缺失的rubric草稿，不是历史有效分数。
本版尚未逐项人工审核/最终冻结，也未自动切换生产 evaluator 或重新评测。采用新 schema，必须显式选择并适配，禁止混用旧分数。

| 类型 | 任务数 |
|---|---:|
| 3D Object | 2 |
| 3D Scene | 1 |
| Audio | 9 |
| CG Video | 3 |

## 第一列逐任务预览

以下仅展示计分目标；完整原文、定性投影记录、排除项、判分锚点和第二/三维见对应 JSON。

### [G001_port_guard_arena_obj_005](G001_port_guard_arena_obj_005.json)

- **C001**：Round wooden training dummy post wrapped in frayed rope with strike marks

### [G001_port_guard_arena_obj_006](G001_port_guard_arena_obj_006.json)

- **C001**：Industrial rotating warning beacon lamp on a steel pole
- **C002**：amber lens that can glow
- **C003**：no text

### [G001_scene_001](G001_scene_001.json)

- **C001**：Abandoned seaport training arena
- **C002**：walled yard；围墙围合的训练场地
- **C003**：shipping container covers on four sides；集装箱掩体分布在场地四周
- **C004**：gantry crane silhouettes beyond the walls
- **C005**：sea fog and dusk lighting
- 审查提示：no_literal_asset_mention_in_general

### [G001_sfx_001](G001_sfx_001.json)

- **C001**：Short whoosh of a boxing swing through sea air

### [G001_sfx_002](G001_sfx_002.json)

- **C001**：Crisp fist-on-metal clang with slight ring-off
- **C002**：layered over a low thud

### [G001_sfx_003](G001_sfx_003.json)

- **C001**：Low frequency body impact thud for guard attacks hitting the player

### [G001_sfx_004](G001_sfx_004.json)

- **C001**：Rising low-frequency mechanical charge-up hum during guard wind-up

### [G001_sfx_005](G001_sfx_005.json)

- **C001**：Heavy metal body collapse with mechanical failure whine and part clatter

### [G001_sfx_006](G001_sfx_006.json)

- **C001**：Short uplifting victory sting for training completion

### [G001_sfx_007](G001_sfx_007.json)

- **C001**：Low somber defeat tone

### [G001_sfx_008](G001_sfx_008.json)

- **C001**：Single low heartbeat pulse accent for player low-HP tension

### [G001_sfx_009](G001_sfx_009.json)

- **C001**：Abandoned seaport ambience
- **C002**：steady sea wind with distant waves and gull calls
- **C003**：seamless loop

### [G001_cg_001](G001_cg_001.json)

- **C001**：海雾弥漫的废弃港口全景
- **C002**：远方舰队黑影逼近
- **C003**：一群机械守卫从静止桩态苏醒
- **C004**：红色目镜逐一点亮
- **C005**：捍卫者放下行囊走入训练场大门
- **C006**：镜头由远处龙门吊缓推至大门
- **C007**：警示黄光扫过

### [G001_cg_002](G001_cg_002.json)

- **C001**：镜头从倒地的机械守卫拉升
- **C002**：场地两角的守卫目镜由暗转亮
- **C003**：从桩态逐一站起
- **C004**：肩部警示灯齐闪
- **C005**：警示灯柱光锥由黄转绿扫过全场
- **C006**：短促而肃杀的机械苏醒演出

### [G001_cg_003](G001_cg_003.json)

- **C001**：警示灯由黄转绿扫过全场
- **C002**：倒地机械守卫冒出余烬青烟
- **C003**：捍卫者收拳立于场地中央
- **C004**：海雾中透出晨光
- **C005**：镜头环绕半周后定格

