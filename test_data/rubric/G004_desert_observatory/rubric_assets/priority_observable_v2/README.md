# G004_desert_observatory — priority 资产需求 rubric 修订 v2

本目录是独立修订版；旧 `../rubric.json`、`../per_asset/` 及历史分数均保留。
游戏内索引：`../priority_rubric_current.json`。仅包含 priority gen 对应任务，不代表其他资产任务也已修订。
第一列保留可观察的主体、部件、形状、色彩、材质、相对布局、动作/事件及声音内容；精确坐标、尺寸、时长、速度、计数和技术参数只作来源/诊断。
已有逐资产文件的第二/三维原样保留；自然音效与T-pose补充的是此前缺失的rubric草稿，不是历史有效分数。
本版尚未逐项人工审核/最终冻结，也未自动切换生产 evaluator 或重新评测。采用新 schema，必须显式选择并适配，禁止混用旧分数。

| 类型 | 任务数 |
|---|---:|
| 3D Object | 4 |
| 3D Scene | 1 |
| Audio | 15 |
| CG Video | 4 |

## 第一列逐任务预览

以下仅展示计分目标；完整原文、定性投影记录、排除项、判分锚点和第二/三维见对应 JSON。

### [G004_desert_observatory_obj_007](G004_desert_observatory_obj_007.json)

- **C001**：Fallen machine armor plate chunk with torn brackets and cooling fins
- **C002**：half-buried in drifted sand
- **C003**：single object

### [G004_desert_observatory_obj_008](G004_desert_observatory_obj_008.json)

- **C001**：Cracked bronze mirror panel from the observatory dome
- **C002**：cloudy reflective surface with sand scratches
- **C003**：leaning against a wall
- **C004**：single object

### [G004_desert_observatory_obj_009](G004_desert_observatory_obj_009.json)

- **C001**：Small bronze checkpoint beacon pedestal with a cold-blue light column emitter ring
- **C002**：knee height
- **C003**：single object

### [G004_desert_observatory_obj_010](G004_desert_observatory_obj_010.json)

- **C001**：Small carved talisman tablet of the oasis settlement wells
- **C002**：sandstone disc with etched wave glyphs
- **C003**：carried charm prop
- **C004**：single object

### [G004_scene_001](G004_scene_001.json)

- **C001**：Desert observatory circular main hall；圆形主厅
- **C002**：chamber centered on a raised bronze-ring pedestal
- **C003**：multiple massive concrete pillars evenly spaced on an inner ring at radius；立柱围绕中心均匀分布
- **C004**：an outer walkway
- **C005**：dome skylight shafts with drifting sand
- **C006**：weathered concrete and brass surfaces
- **C007**：观测基座居中，外围设环形走道
- 审查提示：no_literal_asset_mention_in_general

### [G004_vo_014](G004_vo_014.json)

- **C001**：Low resolute female wasteland narrator voice
- **C002**：wind behind
- **C003**：brief
- **C004**：沙海之眼又在咆哮。今天，让它彻底安静下来。
- **C005**：语音使用声明的语言：Chinese
- **C006**：语音表达声明的情绪：tense
- 审查提示：no_literal_asset_mention_in_general

### [G004_vo_015](G004_vo_015.json)

- **C001**：Relieved quiet narrator voice over settling wind
- **C002**：brief
- **C003**：核心已停摆。沙海之眼，就此长眠。
- **C004**：语音使用声明的语言：Chinese
- **C005**：语音表达声明的情绪：calm
- 审查提示：no_literal_asset_mention_in_general

### [G004_sfx_001](G004_sfx_001.json)

- **C001**：Bright metallic penetration ping rising in pitch
- **C002**：weak-point crit highlight

### [G004_sfx_002](G004_sfx_002.json)

- **C001**：Dull muffled metal ricochet thud with debris clatter
- **C002**：armored hit

### [G004_sfx_003](G004_sfx_003.json)

- **C001**：Heavy gauntlet swing through dusty air
- **C002**：no impact

### [G004_sfx_004](G004_sfx_004.json)

- **C001**：Deep sub-bass machine roar with cracking metal and collapsing plates
- **C002**：phase transition

### [G004_sfx_005](G004_sfx_005.json)

- **C001**：Urgent short warning beep with distinct pitch per hazard type
- **C002**：ground danger telegraph

### [G004_sfx_006](G004_sfx_006.json)

- **C001**：Sweeping energy beam howl with air sizzle
- **C002**：rotating light beam

### [G004_sfx_007](G004_sfx_007.json)

- **C001**：Gritted breath with a low body impact thud
- **C002**：player takes damage

### [G004_sfx_008](G004_sfx_008.json)

- **C001**：Cloth-and-sand tumble roll
- **C002**：quick dodge swish

### [G004_sfx_009](G004_sfx_009.json)

- **C001**：Warm rising chime as checkpoint light column revives the technician

### [G004_sfx_010](G004_sfx_010.json)

- **C001**：Solemn uplifting sting with faint wind settling
- **C002**：boss core shutdown

### [G004_sfx_011](G004_sfx_011.json)

- **C001**：Low descending defeat tone with rising sandstorm hiss

### [G004_sfx_012](G004_sfx_012.json)

- **C001**：Endless desert sandstorm ambience outside the dome
- **C002**：wind hiss and grain rattle
- **C003**：seamless loop

### [G004_sfx_013](G004_sfx_013.json)

- **C001**：Observatory machine idle hum
- **C002**：deep rotating mechanism drone with periodic mirror-disc clicks
- **C003**：seamless loop

### [G004_cg_001](G004_cg_001.json)

- **C001**：沙暴中天文台剪影由远及近
- **C002**：失控观测机的青色目镜光扫过沙丘
- **C003**：静默技师披斗篷推开主厅大门
- **C004**：穹顶漏下一柱天光
- **C005**：观测机镜盘缓缓转向来者
- **C006**：镜头由沙漠全景推至大门内逆光中景

### [G004_cg_002](G004_cg_002.json)

- **C001**：镜头震动中观测机外层装甲板逐片崩落砸起沙尘
- **C002**：躯干转向枢轴暴露并锁紧
- **C003**：警示灯带由青转橙
- **C004**：碎片坠地的烟尘漫过外环走道

### [G004_cg_003](G004_cg_003.json)

- **C001**：残余装甲碎片被磁力场整圈抛离
- **C002**：悬浮核心晶体暴露并过载发亮
- **C003**：警报灯全红
- **C004**：核心的青光在主厅地面投下旋转扫掠的影

### [G004_cg_004](G004_cg_004.json)

- **C001**：胜负不同意象：胜利意象=核心晶体熄灭
- **C002**：沙暴声渐息
- **C003**：晨光穿过穹顶破洞照亮主厅
- **C004**：静默技师收刀立于基座旁
- **C005**：失败意象=警报灯逐一熄灭
- **C006**：流沙漫过倒地的技师
- **C007**：观测机目镜光重新亮起扫视空厅
- 审查提示：multi_variant_cg_requires_delivery_convention, branch_delivery_review

