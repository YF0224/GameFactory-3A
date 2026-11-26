# G021_outpost_assault — priority 资产需求 rubric 修订 v2

本目录是独立修订版；旧 `../rubric.json`、`../per_asset/` 及历史分数均保留。
游戏内索引：`../priority_rubric_current.json`。仅包含 priority gen 对应任务，不代表其他资产任务也已修订。
第一列保留可观察的主体、部件、形状、色彩、材质、相对布局、动作/事件及声音内容；精确坐标、尺寸、时长、速度、计数和技术参数只作来源/诊断。
已有逐资产文件的第二/三维原样保留；自然音效与T-pose补充的是此前缺失的rubric草稿，不是历史有效分数。
本版尚未逐项人工审核/最终冻结，也未自动切换生产 evaluator 或重新评测。采用新 schema，必须显式选择并适配，禁止混用旧分数。

| 类型 | 任务数 |
|---|---:|
| 3D Object | 1 |
| 3D Scene | 1 |
| Audio | 13 |
| CG Video | 3 |

## 第一列逐任务预览

以下仅展示计分目标；完整原文、定性投影记录、排除项、判分锚点和第二/三维见对应 JSON。

### [G021_outpost_assault_obj_003](G021_outpost_assault_obj_003.json)

- **C001**：Single desert ground pit trap with hinged cover plates and warning stakes
- **C002**：consumed-state appearance is readable
- **C003**：single object

### [G021_scene_001](G021_scene_001.json)

- **C001**：Two fixed top-down desert-coast maps: friendly outpost () with keep
- **C002**：build pads
- **C003**：trap pads
- **C004**：enemy target island () with core
- **C005**：outer bastions
- **C006**：defense lines and landing points
- **C007**：sand dunes
- **C008**：sea mist and flags
- **C009**：前哨与目标岛具有俯视地图表现
- **C010**：具有建造位、陷阱位和登陆区域的可见表现
- **C011**：登陆区域分别位于东滩、南崖和西湾
- **C012**：敌方核心、外围工事和防线具有可见层次
- 审查提示：no_literal_asset_mention_in_general

### [G021_sfx_001](G021_sfx_001.json)

- **C001**：Heavy construction placement thunk with sand settle

### [G021_sfx_002](G021_sfx_002.json)

- **C001**：Deconstruct refund click with coin sweep

### [G021_sfx_003](G021_sfx_003.json)

- **C001**：Crisp rapid sentry tower shot with mechanical bolt cycle

### [G021_sfx_004](G021_sfx_004.json)

- **C001**：Impact hit tick for unit damage with slight armor ring

### [G021_sfx_005](G021_sfx_005.json)

- **C001**：Ground trap snapping shut with debris burst

### [G021_sfx_006](G021_sfx_006.json)

- **C001**：Bright loot pop as salvage numbers rise

### [G021_sfx_007](G021_sfx_007.json)

- **C001**：Warm upgrade pulse with two rising ticks

### [G021_sfx_008](G021_sfx_008.json)

- **C001**：Two-tone incoming wave alert with distant surf

### [G021_sfx_009](G021_sfx_009.json)

- **C001**：Deep keep hit boom with stone crack

### [G021_sfx_010](G021_sfx_010.json)

- **C001**：Grand core destruction burst with collapse rumble

### [G021_sfx_011](G021_sfx_011.json)

- **C001**：Victory horn call for the captured enemy core

### [G021_sfx_012](G021_sfx_012.json)

- **C001**：Low defeat tone with falling wind for the fallen outpost

### [G021_sfx_013](G021_sfx_013.json)

- **C001**：Desert coast wind and surf ambience loop with faint sand hiss
- **C002**：no seam artifacts

### [G021_cg_001](G021_cg_001.json)

- **C001**：荒漠海岸前哨全景：主堡旗帜在风沙中展开
- **C002**：镜头掠过空置的建造位与抢滩口
- **C003**：停在海峡对岸敌方核心的轮廓
- **C004**：无剪辑
- **C005**：无 UI
- **C006**：无文字

### [G021_cg_002](G021_cg_002.json)

- **C001**：敌方登陆艇轮廓逼近海岸线
- **C002**：波次路径预览在地图上展开
- **C003**：主堡警报灯点亮——枪兵/装甲/破甲三色剪影沿预览路线推进

### [G021_cg_003](G021_cg_003.json)

- **C001**：不同意象共用条目：胜利=敌方核心爆裂光柱
- **C002**：前哨旗帜插上残骸
- **C003**：局败=主堡坍塌沙尘
- **C004**：旗帜倒下
- **C005**：撤回=队伍旗帜收拢退回防线（简短非终局）

