# G009_blackout_stealth — priority 资产需求 rubric 修订 v2

本目录是独立修订版；旧 `../rubric.json`、`../per_asset/` 及历史分数均保留。
游戏内索引：`../priority_rubric_current.json`。仅包含 priority gen 对应任务，不代表其他资产任务也已修订。
第一列保留可观察的主体、部件、形状、色彩、材质、相对布局、动作/事件及声音内容；精确坐标、尺寸、时长、速度、计数和技术参数只作来源/诊断。
已有逐资产文件的第二/三维原样保留；自然音效与T-pose补充的是此前缺失的rubric草稿，不是历史有效分数。
本版尚未逐项人工审核/最终冻结，也未自动切换生产 evaluator 或重新评测。采用新 schema，必须显式选择并适配，禁止混用旧分数。

| 类型 | 任务数 |
|---|---:|
| 3D Object | 2 |
| 3D Scene | 1 |
| Audio | 13 |
| CG Video | 4 |

## 第一列逐任务预览

以下仅展示计分目标；完整原文、定性投影记录、排除项、判分锚点和第二/三维见对应 JSON。

### [G009_blackout_stealth_obj_003](G009_blackout_stealth_obj_003.json)

- **C001**：Classified archive dossier case
- **C002**：brushed steel box with latch and frosted tag slot
- **C003**：blank surfaces without text
- **C004**：pickup scale

### [G009_blackout_stealth_obj_004](G009_blackout_stealth_obj_004.json)

- **C001**：Compact noisemaker decoy device
- **C002**：palm-sized cylinder with timer button and speaker grille
- **C003**：no text

### [G009_scene_001](G009_scene_001.json)

- **C001**：Blackout archive facility interior at night
- **C002**：front yard with fence and cover rows
- **C003**：grand archive hall with steel shelving aisles under emergency lamps
- **C004**：low-ceiling evacuation corridor ending at a hatch
- **C005**：red emergency lamps
- **C006**：moonlight clerestory windows
- **C007**：前院、档案大厅、撤离走廊组成连续空间
- **C008**：前院有入口、成排掩体和大厅门
- **C009**：大厅有档案室隔间，撤离走廊由侧门通向舱口
- **C010**：高掩体柜与低掩体箱具有可辨的高低差别
- 审查提示：no_literal_asset_mention_in_general

### [G009_sfx_001](G009_sfx_001.json)

- **C001**：Boot step on metal grating
- **C002**：clear metallic tap

### [G009_sfx_002](G009_sfx_002.json)

- **C001**：Muffled boot step on carpet
- **C002**：soft thump

### [G009_sfx_003](G009_sfx_003.json)

- **C001**：Accelerating heartbeat pulses as recognition rises

### [G009_sfx_004](G009_sfx_004.json)

- **C001**：Suspicion sting with low strings swell for L1 alert music switch

### [G009_sfx_005](G009_sfx_005.json)

- **C001**：Full alarm tension track sting for L2 alert music switch

### [G009_sfx_006](G009_sfx_006.json)

- **C001**：Short scuffle then muffled body-drop thud for takedown

### [G009_sfx_007](G009_sfx_007.json)

- **C001**：Soft fabric rustle for instant crouch stance switch

### [G009_sfx_008](G009_sfx_008.json)

- **C001**：Case latch click and paper slide as dossier is taken

### [G009_sfx_009](G009_sfx_009.json)

- **C001**：Hatch hiss and uplifting resolution tone on extraction

### [G009_sfx_010](G009_sfx_010.json)

- **C001**：Decoy device arming beep then landing clatter

### [G009_sfx_011](G009_sfx_011.json)

- **C001**：Guard surprised gasp plus sharp alert call upon spotting a downed comrade

### [G009_sfx_012](G009_sfx_012.json)

- **C001**：Dazed groan as a knocked-out guard wakes up

### [G009_sfx_013](G009_sfx_013.json)

- **C001**：Blackout facility ambience
- **C002**：deep electric hum with faint wind through vents
- **C003**：seamless loop

### [G009_cg_001](G009_cg_001.json)

- **C001**：灰堡档案设施灯光骤然熄灭
- **C002**：备用电源指示灯闪烁
- **C003**：潜入者翻过庭院围栏没入阴影
- **C004**：应急灯在墙面投下短暂光带
- **C005**：镜头自围栏俯角推近

### [G009_cg_002](G009_cg_002.json)

- **C001**：红色警报灯旋转扫过档案大厅
- **C002**：数名守卫举灯从各方向汇聚
- **C003**：潜入者贴在档案柜阴影中屏息
- **C004**：镜头扫过光柱与尘粒

### [G009_cg_003](G009_cg_003.json)

- **C001**：警报红光下走廊尽头的撤离舱口缓缓闭合
- **C002**：守卫持灯封锁通道
- **C003**：潜入者视角画面渐暗
- **C004**：镜头随红灯旋转收束

### [G009_cg_004](G009_cg_004.json)

- **C001**：潜入者从舱口跃出翻过庭院围栏
- **C002**：怀中档案匣紧贴胸口
- **C003**：身后设施应急灯仍在闪烁
- **C004**：远处天际透出黎明微光
- **C005**：潜入者没入巷影
- **C006**：镜头定格于围栏上留下的浅浅鞋印

