# G007_crystal_probe_run — priority 资产需求 rubric 修订 v2

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

### [G007_scene_001](G007_scene_001.json)

- **C001**：Interior of a giant translucent crystal seen at micro scale: vast indigo crystal cavern with layered floating hexagonal pillars along both sides；悬浮晶柱沿左右边缘分层布置
- **C002**：glowing cyan energy veins running through floor and walls；发光晶脉沿背景地面延伸
- **C003**：drifting luminous dust motes
- **C004**：a clean open vertical corridor in the center for bullet-hell gameplay；中央弹幕走廊保持净空，不被主体景物遮挡
- **C005**：deep parallax fading to dark blue
- **C006**：stylized sci-fi mood consistent with the reference image
- **C007**：no text
- **C008**：顶部界面留白区不放置主体景物
- 审查提示：no_literal_asset_mention_in_general

### [G007_sfx_001](G007_sfx_001.json)

- **C001**：Short glassy energy scan tick
- **C002**：bright and clean crystal shaver sound
- **C003**：suitable for rapid repeated playback without smearing

### [G007_sfx_002](G007_sfx_002.json)

- **C001**：Soft descending electronic confirmation blip with engine throttle-down feel
- **C002**：single clean tone

### [G007_sfx_003](G007_sfx_003.json)

- **C001**：Crystal shattering impact: glassy crack burst with low sub thump
- **C002**：brief and harsh

### [G007_sfx_004](G007_sfx_004.json)

- **C001**：Energy shield recharge hum
- **C002**：rising barrier tone with subtle shimmer tail

### [G007_sfx_005](G007_sfx_005.json)

- **C001**：Resonance pulse blast: deep low-frequency shockwave boom with glassy harmonic overtone
- **C002**：wide stereo surge

### [G007_sfx_006](G007_sfx_006.json)

- **C001**：Short dry negative buzz
- **C002**：low double click
- **C003**：clearly distinct from all success sounds

### [G007_sfx_007](G007_sfx_007.json)

- **C001**：Rising two-note confirmation chime with glassy bell tone
- **C002**：rewarding and short

### [G007_sfx_008](G007_sfx_008.json)

- **C001**：Bright victory fanfare of three ascending glass bell notes with soft synth pad tail

### [G007_sfx_009](G007_sfx_009.json)

- **C001**：Low descending defeat tone with muffled crystal debris fading out
- **C002**：somber and short

### [G007_sfx_010](G007_sfx_010.json)

- **C001**：Deep crystal cavern ambience: slow low-frequency resonance hum with faint crystalline shimmer overtones and distant sub-creaks
- **C002**：seamless loop
- **C003**：no melody

### [G007_cg_001](G007_cg_001.json)

- **C001**：开场镜头：深空陨石带中一块篮球场大小的巨晶「星髓晶」泛着蓝紫辉光
- **C002**：勘探舱内白色小型探测艇「尘针号」被微缩光束逐级缩小至微尘尺度
- **C003**：随后高速穿入晶面
- **C004**：画面切入晶体内部——幽蓝晶格穹顶
- **C005**：发光晶脉与悬浮晶柱在纵深中展开
- **C006**：能量珠如星群漂浮
- **C007**：镜头由外部宏观推入内部微观
- **C008**：@
- **C009**：探测艇与晶体场景造型与游戏内资产同源

### [G007_cg_002](G007_cg_002.json)

- **C001**：结算镜头：晶体内部能量珠渐渐平息
- **C002**：晶面透出一道撤离光门
- **C003**：白色探测艇「尘针号」拖着金色扫描光尾迹穿过残余能量珠群驶向光门
- **C004**：出晶瞬间艇体恢复原尺度
- **C005**：数据光流回传至勘探舱屏幕
- **C006**：晶面在身后缓缓愈合
- **C007**：镜头由内部跟随拉出至巨晶全景
- **C008**：@
- **C009**：与游戏内资产造型同源

### [G007_cg_003](G007_cg_003.json)

- **C001**：画面定格于白色探测艇尘针号贴弹瞬间
- **C002**：艇艏扫描环收拢成一道金色数据流注入艇侧脉冲槽
- **C003**：脉冲槽图标由灰转亮
- **C004**：+1 浮动徽记跳出
- **C005**：背景晶脉泛起青金涟漪
- **C006**：镜头微推至艇侧特写

