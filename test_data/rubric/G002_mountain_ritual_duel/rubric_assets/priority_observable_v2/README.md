# G002_mountain_ritual_duel — priority 资产需求 rubric 修订 v2

本目录是独立修订版；旧 `../rubric.json`、`../per_asset/` 及历史分数均保留。
游戏内索引：`../priority_rubric_current.json`。仅包含 priority gen 对应任务，不代表其他资产任务也已修订。
第一列保留可观察的主体、部件、形状、色彩、材质、相对布局、动作/事件及声音内容；精确坐标、尺寸、时长、速度、计数和技术参数只作来源/诊断。
已有逐资产文件的第二/三维原样保留；自然音效与T-pose补充的是此前缺失的rubric草稿，不是历史有效分数。
本版尚未逐项人工审核/最终冻结，也未自动切换生产 evaluator 或重新评测。采用新 schema，必须显式选择并适配，禁止混用旧分数。

| 类型 | 任务数 |
|---|---:|
| 3D Object | 3 |
| 3D Scene | 1 |
| Audio | 11 |
| CG Video | 3 |

## 第一列逐任务预览

以下仅展示计分目标；完整原文、定性投影记录、排除项、判分锚点和第二/三维见对应 JSON。

### [G002_mountain_ritual_duel_obj_003](G002_mountain_ritual_duel_obj_003.json)

- **C001**：Ceremonial flintlock pistol with brass barrel
- **C002**：cold-gold filigree and worn walnut grip
- **C003**：single object
- **C004**：no text

### [G002_mountain_ritual_duel_obj_005](G002_mountain_ritual_duel_obj_005.json)

- **C001**：Tall ritual duel banner of rough linen in ritual red with cold-gold pole and tassel
- **C002**：cloth hanging loose
- **C003**：single object
- **C004**：no text on cloth

### [G002_mountain_ritual_duel_obj_006](G002_mountain_ritual_duel_obj_006.json)

- **C001**：Straight ceremonial longblade resting on a low sword stand
- **C002**：cold-steel edge with gold-wrapped hilt
- **C003**：single object

### [G002_scene_001](G002_scene_001.json)

- **C001**：High-post dueling ground above a sea of clouds
- **C002**：circular granite platform with stone railing border；圆形石台
- **C003**：bronze altar bell at the north rim；祭坛铜钟
- **C004**：multiple duel banners spaced evenly along the edge；决斗旗沿台缘均匀分布
- **C005**：morning light and drifting cloud sea below
- 审查提示：no_literal_asset_mention_in_general

### [G002_sfx_001](G002_sfx_001.json)

- **C001**：Sharp longblade swing through mountain air
- **C002**：thin whoosh with faint ring

### [G002_sfx_002](G002_sfx_002.json)

- **C001**：Weapon-on-weapon parry clang with bright metallic ring-off

### [G002_sfx_003](G002_sfx_003.json)

- **C001**：Crisp resonant chime layered over the clang for a perfect parry
- **C002**：bright and clean

### [G002_sfx_004](G002_sfx_004.json)

- **C001**：Dull body impact thud when the player takes a slash

### [G002_sfx_005](G002_sfx_005.json)

- **C001**：Heavy crushing blow with armor giving way
- **C002**：guard-break accent

### [G002_sfx_006](G002_sfx_006.json)

- **C001**：Single strong heartbeat pulse
- **C002**：rising in intensity when looped over three ritual steps

### [G002_sfx_007](G002_sfx_007.json)

- **C001**：Ceremonial flintlock discharge
- **C002**：sharp crack with echoing report across the peaks

### [G002_sfx_008](G002_sfx_008.json)

- **C001**：Off-balance stumble with a scuff of boots on stone

### [G002_sfx_009](G002_sfx_009.json)

- **C001**：Altar bell struck once
- **C002**：long solemn bronze resonance decaying over wind

### [G002_sfx_010](G002_sfx_010.json)

- **C001**：Low mournful mountain wind gust for defeat

### [G002_sfx_011](G002_sfx_011.json)

- **C001**：High-altitude mountain wind ambience with distant cloud-sea hum
- **C002**：seamless loop
- **C003**：no music

### [G002_cg_001](G002_cg_001.json)

- **C001**：云岭哨台晨光
- **C002**：祭坛铜钟被敲响三声
- **C003**：身披旅袍的决斗者拾阶登台
- **C004**：与持重剑的哨卫剑士相对行礼
- **C005**：双方拔刀出鞘映出翻涌云海
- **C006**：镜头由铜钟推至双方中景

### [G002_cg_002](G002_cg_002.json)

- **C001**：决斗者与哨卫剑士收刀背靠背立于台心
- **C002**：镜头低角度环绕
- **C003**：风声渐弱心跳渐强
- **C004**：双方沿直线各走出
- **C005**：衣摆与旗布翻卷
- **C006**：落步时落地震起尘土
- **C007**：双方握住燧发枪柄蓄势待转

### [G002_cg_003](G002_cg_003.json)

- **C001**：胜者将长刀插立台心
- **C002**：铜钟送响
- **C003**：败者收刀踉跄步下石阶
- **C004**：云雾漫过台缘
- **C005**：镜头由台心拉远至云海全景

