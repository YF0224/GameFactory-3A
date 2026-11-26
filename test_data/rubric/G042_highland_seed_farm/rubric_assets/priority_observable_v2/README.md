# G042_highland_seed_farm — priority 资产需求 rubric 修订 v2

本目录是独立修订版；旧 `../rubric.json`、`../per_asset/` 及历史分数均保留。
游戏内索引：`../priority_rubric_current.json`。仅包含 priority gen 对应任务，不代表其他资产任务也已修订。
第一列保留可观察的主体、部件、形状、色彩、材质、相对布局、动作/事件及声音内容；精确坐标、尺寸、时长、速度、计数和技术参数只作来源/诊断。
已有逐资产文件的第二/三维原样保留；自然音效与T-pose补充的是此前缺失的rubric草稿，不是历史有效分数。
本版尚未逐项人工审核/最终冻结，也未自动切换生产 evaluator 或重新评测。采用新 schema，必须显式选择并适配，禁止混用旧分数。

| 类型 | 任务数 |
|---|---:|
| 3D Object | 4 |
| 3D Scene | 1 |
| Audio | 11 |
| CG Video | 3 |

## 第一列逐任务预览

以下仅展示计分目标；完整原文、定性投影记录、排除项、判分锚点和第二/三维见对应 JSON。

### [G042_highland_seed_farm_obj_005](G042_highland_seed_farm_obj_005.json)

- **C001**：Single highland furrow soil plot tile
- **C002**：moist brown tilled earth with ridge lines and small stone edging
- **C003**：flat readable from view for grid tiling

### [G042_highland_seed_farm_obj_006](G042_highland_seed_farm_obj_006.json)

- **C001**：Wooden highland rain collection barrel with ladle resting on rim and small tap
- **C002**：water source for manual watering
- **C003**：single object

### [G042_highland_seed_farm_obj_007](G042_highland_seed_farm_obj_007.json)

- **C001**：Colored prayer flag line strung between two weathered wooden posts
- **C002**：five small cloth flags with simple nature motifs
- **C003**：ridge-line ambience kit
- **C004**：single kit

### [G042_highland_seed_farm_obj_008](G042_highland_seed_farm_obj_008.json)

- **C001**：Woven highland harvest basket with carrying strap and a few loose produce pieces
- **C002**：delivery and sale container
- **C003**：single object

### [G042_scene_001](G042_scene_001.json)

- **C001**：Highland plateau seed farm scene
- **C002**：single-screen furrow plot field on a terraced slope
- **C003**：wooden seed station counter at lower right
- **C004**：distant ridgeline with prayer-flag lines and sea of clouds
- **C005**：cool daylight
- **C006**：visual shell only
- **C007**：垄作田块呈行列排列
- **C008**：种子站柜台具有可见表现
- 审查提示：no_literal_asset_mention_in_general

### [G042_sfx_001](G042_sfx_001.json)

- **C001**：Seed planting into furrow soil
- **C002**：soft dig and drop with earth settle

### [G042_sfx_002](G042_sfx_002.json)

- **C001**：Watering can splash on tilled soil
- **C002**：light splatter with soil darkening hiss

### [G042_sfx_003](G042_sfx_003.json)

- **C001**：Harvest pickup
- **C002**：sickle cut through stalk then crisp produce lift

### [G042_sfx_004](G042_sfx_004.json)

- **C001**：Sale coin chime
- **C002**：two bright coins on wood table with clean tail

### [G042_sfx_005](G042_sfx_005.json)

- **C001**：Order expired alert
- **C002**：two firm descending bell notes with muted thud end

### [G042_sfx_006](G042_sfx_006.json)

- **C001**：Order fulfilled chime
- **C002**：warm ascending two-note bell with cloth snap tail

### [G042_sfx_007](G042_sfx_007.json)

- **C001**：Day advance cue
- **C002**：soft morning wind chime and single wood tick for day banner

### [G042_sfx_008](G042_sfx_008.json)

- **C001**：Season victory sting
- **C002**：bright highland strings and bells rising to clear-sky finish

### [G042_sfx_009](G042_sfx_009.json)

- **C001**：Season defeat sting
- **C002**：muted low strings with cold wind tail
- **C003**：dignified not dramatic

### [G042_sfx_010](G042_sfx_010.json)

- **C001**：Seamless highland plateau wind with distant bird calls and faint prayer-flag flutter
- **C002**：no voices or music

### [G042_sfx_011](G042_sfx_011.json)

- **C001**：Seamless soft highland rain on soil and wooden awning
- **C002**：gentle and steady
- **C003**：no thunder

### [G042_cg_001](G042_cg_001.json)

- **C001**：云脊高原晨雾
- **C002**：育种员走向 空田
- **C003**：翻开垄土
- **C004**：种子站木屋炊烟升起
- **C005**：第一粒种子入土
- **C006**：无 UI
- **C007**：无文字
- **C008**：无剪辑

### [G042_cg_002](G042_cg_002.json)

- **C001**：云层过境
- **C002**：雨幕落下梯田
- **C003**：垄土吸水
- **C004**：苗芽顶土拔节
- **C005**：阶段图标依次点亮
- **C006**：无 UI
- **C007**：无文字
- 审查提示：no_literal_asset_mention_in_general

### [G042_cg_003](G042_cg_003.json)

- **C001**：不同意象共用条目：胜利＝种子站挂牌亮灯
- **C002**：新种入库
- **C003**：云海放晴
- **C004**：失败＝试验田木牌摘下
- **C005**：田垄归于荒草
- **C006**：暮色沉降
- **C007**：无 UI
- **C008**：无文字
- 审查提示：multi_variant_cg_requires_delivery_convention, branch_delivery_review

