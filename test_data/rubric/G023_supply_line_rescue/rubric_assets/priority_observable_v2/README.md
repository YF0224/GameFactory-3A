# G023_supply_line_rescue — priority 资产需求 rubric 修订 v2

本目录是独立修订版；旧 `../rubric.json`、`../per_asset/` 及历史分数均保留。
游戏内索引：`../priority_rubric_current.json`。仅包含 priority gen 对应任务，不代表其他资产任务也已修订。
第一列保留可观察的主体、部件、形状、色彩、材质、相对布局、动作/事件及声音内容；精确坐标、尺寸、时长、速度、计数和技术参数只作来源/诊断。
已有逐资产文件的第二/三维原样保留；自然音效与T-pose补充的是此前缺失的rubric草稿，不是历史有效分数。
本版尚未逐项人工审核/最终冻结，也未自动切换生产 evaluator 或重新评测。采用新 schema，必须显式选择并适配，禁止混用旧分数。

| 类型 | 任务数 |
|---|---:|
| 3D Scene | 1 |
| Audio | 10 |
| CG Video | 3 |

## 第一列逐任务预览

以下仅展示计分目标；完整原文、定性投影记录、排除项、判分锚点和第二/三维见对应 JSON。

### [G023_scene_001](G023_scene_001.json)

- **C001**：Mountain supply network: base depot at the foot
- **C002**：three frontline outposts up the ridge
- **C003**：four cliffside single-lane segments ()
- **C004**：two rockfall blockage spots
- **C005**：drifting snow and cloud mist
- **C006**：alpine palette
- **C007**：基地与沿线节点由连续路线连接，形成返回基地的连接关系
- **C008**：节点具有车辆停驻空间的可见表现；不验收容量或调度
- 审查提示：no_literal_asset_mention_in_general

### [G023_sfx_001](G023_sfx_001.json)

- **C001**：Dispatch confirmation signal with engine rev and departure chirp

### [G023_sfx_002](G023_sfx_002.json)

- **C001**：Rockfall route-blocked alert with distant rumble

### [G023_sfx_003](G023_sfx_003.json)

- **C001**：Reroute hint swish as the alternate path unfolds

### [G023_sfx_004](G023_sfx_004.json)

- **C001**：Warm delivery beacon chime as cargo unloads

### [G023_sfx_005](G023_sfx_005.json)

- **C001**：Light restock tick as surplus cargo returns to base ledger

### [G023_sfx_006](G023_sfx_006.json)

- **C001**：Pulsing deadlock warning as the system begins reranking

### [G023_sfx_007](G023_sfx_007.json)

- **C001**：Urgent supply crisis alarm for a starved outpost

### [G023_sfx_008](G023_sfx_008.json)

- **C001**：Victory horn as the rescue window closes with all outposts supplied

### [G023_sfx_009](G023_sfx_009.json)

- **C001**：Low defeat tone with closing wind for the failed supply line

### [G023_sfx_010](G023_sfx_010.json)

- **C001**：High-mountain wind ambience loop with faint distant avalanche rumbles
- **C002**：no seam artifacts

### [G023_cg_001](G023_cg_001.json)

- **C001**：雪线山道全景：山脚基地灯火与哨站的烟囱遥相呼应
- **C002**：一队改装卡车挂上防滑链
- **C003**：镜头沿单线栈道推向云雾中的哨站
- **C004**：无剪辑
- **C005**：无 UI
- **C006**：无文字

### [G023_cg_002](G023_cg_002.json)

- **C001**：山壁雪崩倾泻而下吞没 A-B 栈道
- **C002**：红叉警示亮起
- **C003**：在途卡车驶离后调头寻找绕行路线
- **C004**：改道箭头沿备用边展开

### [G023_cg_003](G023_cg_003.json)

- **C001**：胜负不同意象：胜利=窗口关闭
- **C002**：三站信标同时亮起
- **C003**：车队在雪光中鸣笛
- **C004**：失败=哨站红光熄灭
- **C005**：雪线封锁
- **C006**：调度台灯收拢
- 审查提示：multi_variant_cg_requires_delivery_convention, branch_delivery_review

