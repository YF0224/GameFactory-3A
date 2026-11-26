# G010_orbital_extraction — priority 资产需求 rubric 修订 v2

本目录是独立修订版；旧 `../rubric.json`、`../per_asset/` 及历史分数均保留。
游戏内索引：`../priority_rubric_current.json`。仅包含 priority gen 对应任务，不代表其他资产任务也已修订。
第一列保留可观察的主体、部件、形状、色彩、材质、相对布局、动作/事件及声音内容；精确坐标、尺寸、时长、速度、计数和技术参数只作来源/诊断。
已有逐资产文件的第二/三维原样保留；自然音效与T-pose补充的是此前缺失的rubric草稿，不是历史有效分数。
本版尚未逐项人工审核/最终冻结，也未自动切换生产 evaluator 或重新评测。采用新 schema，必须显式选择并适配，禁止混用旧分数。

| 类型 | 任务数 |
|---|---:|
| 3D Object | 5 |
| 3D Scene | 1 |
| Audio | 15 |
| CG Video | 4 |

## 第一列逐任务预览

以下仅展示计分目标；完整原文、定性投影记录、排除项、判分锚点和第二/三维见对应 JSON。

### [G010_orbital_extraction_obj_004](G010_orbital_extraction_obj_004.json)

- **C001**：Orbital station storage locker cabinet
- **C002**：polymer gray-blue panel with warning stripe and sliding door
- **C003**：no text on surfaces

### [G010_orbital_extraction_obj_006](G010_orbital_extraction_obj_006.json)

- **C001**：Floor maintenance well extraction hatch with recessed ladder ring and amber caution ring
- **C002**：single mechanism object
- **C003**：no text

### [G010_orbital_extraction_obj_008](G010_orbital_extraction_obj_008.json)

- **C001**：Slim keycard with chip window and frosted translucent shell
- **C002**：collectible pickup scale
- **C003**：blank surfaces without text

### [G010_orbital_extraction_obj_009](G010_orbital_extraction_obj_009.json)

- **C001**：Magazine ammo pickup crate with open lid and brass rounds visible
- **C002**：small glowing rim
- **C003**：no text

### [G010_orbital_extraction_obj_010](G010_orbital_extraction_obj_010.json)

- **C001**：Sealed sample canister with purple glowing core window and clamp brackets
- **C002**：loot scale
- **C003**：no text

### [G010_scene_001](G010_scene_001.json)

- **C001**：Orbital research station interior
- **C002**：linear three-section layout from airlock chamber through lab modules to the dim pressurized deep zone
- **C003**：portholes showing Earth
- **C004**：emergency red lights in deep zone
- **C005**：industrial corridors with frost pipes
- **C006**：主走廊依次串联气闸室、实验舱群和深区
- **C007**：气闸室具有撤离点的可见表现
- **C008**：实验舱群与深区具有柜体，深区具有库房与维修井的可见表现
- 审查提示：no_literal_asset_mention_in_general

### [G010_sfx_001](G010_sfx_001.json)

- **C001**：Compact sci-fi rifle shot with tight punchy report

### [G010_sfx_002](G010_sfx_002.json)

- **C001**：Brass shell casing dropping on metal deck

### [G010_sfx_003](G010_sfx_003.json)

- **C001**：Bullet impact on body armor
- **C002**：hit confirmation thock

### [G010_sfx_004](G010_sfx_004.json)

- **C001**：Distinct higher-pitched headshot confirmation ding layered on impact

### [G010_sfx_005](G010_sfx_005.json)

- **C001**：Short kill confirmation tick

### [G010_sfx_006](G010_sfx_006.json)

- **C001**：Magazine eject
- **C002**：insert and charging handle cycling

### [G010_sfx_007](G010_sfx_007.json)

- **C001**：Dry fire empty magazine click

### [G010_sfx_008](G010_sfx_008.json)

- **C001**：Light boot step on metal grating
- **C002**：low load

### [G010_sfx_009](G010_sfx_009.json)

- **C001**：Heavier dragging boot step under high load

### [G010_sfx_010](G010_sfx_010.json)

- **C001**：Rummaging through container contents
- **C002**：metallic scraping

### [G010_sfx_011](G010_sfx_011.json)

- **C001**：Bright shimmering pickup chime for high-rarity loot

### [G010_sfx_012](G010_sfx_012.json)

- **C001**：Deep zone depressurization klaxon with hissing air vent

### [G010_sfx_013](G010_sfx_013.json)

- **C001**：Station PA broadcast chime and static announcement tone

### [G010_sfx_014](G010_sfx_014.json)

- **C001**：Urgent ticking beep for final of extraction countdown

### [G010_sfx_015](G010_sfx_015.json)

- **C001**：Orbital station interior ambience
- **C002**：air circulation hum with faint electrical buzz
- **C003**：seamless loop

### [G010_cg_001](G010_cg_001.json)

- **C001**：接驳舱缓缓对接轨道研究站气闸
- **C002**：舱门开启漏出应急红光
- **C003**：撤离者检查步枪步入走廊
- **C004**：舷窗外地球缓缓转动
- **C005**：镜头由接驳臂推至走廊入口

### [G010_cg_002](G010_cg_002.json)

- **C001**：逃生舱脱离站体
- **C002**：减速喷口点火
- **C003**：舷窗中轨道站远去
- **C004**：地球晨昏线照亮舱内
- **C005**：撤离者核对背包中的样件
- **C006**：镜头定格样件辉光

### [G010_cg_003](G010_cg_003.json)

- **C001**：警报红光中失压走廊雾气翻涌
- **C002**：漂浮碎片掠过镜头
- **C003**：站体进入再入姿态
- **C004**：地球光弧扫过黑暗舱室
- **C005**：镜头随碎片飘远

### [G010_cg_004](G010_cg_004.json)

- **C001**：深区走廊红色警报灯骤亮旋转
- **C002**：舱壁泄压阀喷出横扫的白雾气流
- **C003**：松脱的电缆与碎片低重力漂浮
- **C004**：压力表盘指针跌入红区
- **C005**：舱门指示由绿转红闪烁
- **C006**：镜头沿走廊快速推进后定格于压力表盘特写

