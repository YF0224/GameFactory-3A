# G003_gggame_courtyard_rps — priority 资产需求 rubric 修订 v2

本目录是独立修订版；旧 `../rubric.json`、`../per_asset/` 及历史分数均保留。
游戏内索引：`../priority_rubric_current.json`。仅包含 priority gen 对应任务，不代表其他资产任务也已修订。
第一列保留可观察的主体、部件、形状、色彩、材质、相对布局、动作/事件及声音内容；精确坐标、尺寸、时长、速度、计数和技术参数只作来源/诊断。
已有逐资产文件的第二/三维原样保留；自然音效与T-pose补充的是此前缺失的rubric草稿，不是历史有效分数。
本版尚未逐项人工审核/最终冻结，也未自动切换生产 evaluator 或重新评测。采用新 schema，必须显式选择并适配，禁止混用旧分数。

| 类型 | 任务数 |
|---|---:|
| 3D Object | 6 |
| 3D Scene | 1 |
| Audio | 14 |
| CG Video | 4 |
| Motion | 6 |
| T-pose | 2 |

## 第一列逐任务预览

以下仅展示计分目标；完整原文、定性投影记录、排除项、判分锚点和第二/三维见对应 JSON。

### [G003_gggame_courtyard_rps_obj_001](G003_gggame_courtyard_rps_obj_001.json)

- **C001**：Cheerful anime-style young man with brown short hair
- **C002**：green short tang-style jacket over cream inner shirt
- **C003**：red waistband with three rock-paper-scissors themed charms
- **C004**：dark wide trousers and brown boots
- **C005**：five-head anime proportions
- **C006**：single character

### [G003_gggame_courtyard_rps_obj_002](G003_gggame_courtyard_rps_obj_002.json)

- **C001**：Portly well-off tycoon in anime style
- **C002**：curled mustache
- **C003**：black top hat
- **C004**：short tailcoat with pocket-watch chain
- **C005**：striped trousers
- **C006**：heavy rounded silhouette unified to the anime house style
- **C007**：single character

### [G003_gggame_courtyard_rps_obj_003](G003_gggame_courtyard_rps_obj_003.json)

- **C001**：Anime-style schoolgirl with tea-brown short hair and a side hair clip
- **C002**：beige knit vest over white short-sleeve shirt
- **C003**：dark-gray pleated skirt
- **C004**：brown shoes with white loose socks
- **C005**：no dark tights
- **C006**：sport shorts underneath
- **C007**：five-head anime proportions
- **C008**：single character

### [G003_gggame_courtyard_rps_obj_004](G003_gggame_courtyard_rps_obj_004.json)

- **C001**：Anime-style wizard with black vertical hair and a beard
- **C002**：blue-and-gold robed outfit
- **C003**：lightning motifs as surface decoration only baked into cloth pattern
- **C004**：no electric effects on body geometry
- **C005**：five-head anime proportions
- **C006**：single character

### [G003_gggame_courtyard_rps_obj_005](G003_gggame_courtyard_rps_obj_005.json)

- **C001**：Blunt ceremonial courtyard duel knife with wooden grip and cloth tassel
- **C002**：clearly a game prop rather than a weapon
- **C003**：single object

### [G003_gggame_courtyard_rps_obj_006](G003_gggame_courtyard_rps_obj_006.json)

- **C001**：Stylized oversized cartoon pants layer piece in brick-red cloth with white stitching
- **C002**：single object

### [G003_scene_001](G003_scene_001.json)

- **C001**：Anime-style courtyard league arena
- **C002**：a four-sided residential courtyard with independent player yards connected by stone paths；独立可识别的小院，与道路、矮墙、长凳和花植组成统一场景
- **C003**：low brick walls
- **C004**：wooden benches and potted plants
- **C005**：a central reveal pedestal with rock-paper-scissors totem and lanterns；揭晓台位于中央
- **C006**：warm afternoon light
- **C007**：unified brick-red and tile-gray palette
- 审查提示：no_literal_asset_mention_in_general

### [G003_vo_012](G003_vo_012.json)

- **C001**：Warm playful storyteller voice
- **C002**：courtyard league opener
- **C003**：brief
- **C004**：裁拳巷一年一度的联赛开始了——出拳吧，把对手的裤子赢回来！
- **C005**：语音使用声明的语言：Chinese
- **C006**：语音表达声明的情绪：joyful
- 审查提示：no_literal_asset_mention_in_general

### [G003_vo_013](G003_vo_013.json)

- **C001**：Amused storyteller voice reacting to the first comedic cut
- **C002**：brief
- **C003**：裤子飞出去了！这一局，有人要光着回家咯。
- **C004**：语音使用声明的语言：Chinese
- **C005**：语音表达声明的情绪：joyful
- 审查提示：no_literal_asset_mention_in_general

### [G003_vo_014](G003_vo_014.json)

- **C001**：Triumphant storyteller announcement with crowd cheer behind
- **C002**：brief
- **C003**：本巷拳王，诞生了！
- **C004**：语音使用声明的语言：Chinese
- **C005**：语音表达声明的情绪：joyful
- 审查提示：no_literal_asset_mention_in_general

### [G003_sfx_001](G003_sfx_001.json)

- **C001**：Soft UI tap confirming a rock-paper-scissors selection

### [G003_sfx_002](G003_sfx_002.json)

- **C001**：Dramatic short reveal sting with a freeze-frame whoosh as gestures show

### [G003_sfx_003](G003_sfx_003.json)

- **C001**：Bright ascending step-gain chime for round winners

### [G003_sfx_004](G003_sfx_004.json)

- **C001**：Neutral two-note tie tone prompting a re-throw

### [G003_sfx_005](G003_sfx_005.json)

- **C001**：Comedic cloth rip plus cartoon whoosh as pants fly off
- **C002**：clearly playful

### [G003_sfx_006](G003_sfx_006.json)

- **C001**：Knife lift from a wooden stand with a light metallic ring

### [G003_sfx_007](G003_sfx_007.json)

- **C001**：Cloth rustle as an outer pants marker is put on or removed

### [G003_sfx_008](G003_sfx_008.json)

- **C001**：Light departing footsteps on stone path
- **C002**：departure cue

### [G003_sfx_009](G003_sfx_009.json)

- **C001**：Descending comedic eliminate sting
- **C002**：distinct from victory fanfare

### [G003_sfx_010](G003_sfx_010.json)

- **C001**：Short festive courtyard victory fanfare with crowd cheer
- **C002**：final winner only

### [G003_sfx_011](G003_sfx_011.json)

- **C001**：Lazy afternoon courtyard ambience
- **C002**：breeze through potted plants
- **C003**：distant neighborhood chatter and occasional songbird
- **C004**：seamless loop
- **C005**：no music

### [G003_cg_001](G003_cg_001.json)

- **C001**：午后裁拳巷全景
- **C002**：布幔拉开
- **C003**：灯笼摇曳
- **C004**：参赛者（绿衣少年、礼帽富商、针织背心少女、蓝金袍法师）依次步入各自小院亮相
- **C005**：揭晓台上的石剪布图腾转动
- **C006**：镜头由巷口推入至揭晓台

### [G003_cg_002](G003_cg_002.json)

- **C001**：出拳全屏界面展开
- **C002**：各院参赛者剪影对峙
- **C003**：拳型图标在指尖酝酿
- **C004**：倒计时数字落下
- **C005**：镜头快速掠过每间小院

### [G003_cg_003](G003_cg_003.json)

- **C001**：持刀者踏步逼近
- **C002**：刀光一闪定格
- **C003**：被割者惊愕抖动
- **C004**：裤子划出抛物线飞出院墙（喜剧化）
- **C005**：全场镜头短促定格后恢复

### [G003_cg_004](G003_cg_004.json)

- **C001**：拳王登上揭晓台高举双拳
- **C002**：彩带落下
- **C003**：全体欢呼
- **C004**：镜头拉远至巷院全景
- **C005**：出局者们灰溜溜夹着排队离院
- **C006**：布幔合拢（不同意象）

### [G003_mot_001](G003_mot_001.json)

- **C001**：Anime boy winds up and throws a rock-paper-scissors pose with a confident grin
- **C002**：单次动作具有可辨起始、过程与结束；不设绝对时长门槛。
- **C003**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。

### [G003_mot_002](G003_mot_002.json)

- **C001**：Anime boy picks up a ceremonial duel knife from a stand and raises it
- **C002**：单次动作具有可辨起始、过程与结束；不设绝对时长门槛。
- **C003**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。

### [G003_mot_003](G003_mot_003.json)

- **C001**：Anime boy staggers comically as his pants fly off
- **C002**：covering himself and wobbling off balance
- **C003**：单次动作具有可辨起始、过程与结束；不设绝对时长门槛。
- **C004**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。

### [G003_mot_004](G003_mot_004.json)

- **C001**：Portly tycoon shakes his fist three times then throws a rock-paper-scissors pose with flourish
- **C002**：单次动作具有可辨起始、过程与结束；不设绝对时长门槛。
- **C003**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。

### [G003_mot_005](G003_mot_005.json)

- **C001**：Tycoon swings the ceremonial duel knife in a clearly playful exaggerated slash
- **C002**：no gore
- **C003**：单次动作具有可辨起始、过程与结束；不设绝对时长门槛。
- **C004**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。

### [G003_mot_006](G003_mot_006.json)

- **C001**：Tycoon raises both fists and laughs in triumph on the reveal pedestal
- **C002**：单次动作具有可辨起始、过程与结束；不设绝对时长门槛。
- **C003**：整体保持原地表演的组织，不以零位移容差判定；跳跃等任务所需的垂直运动允许保留。

### [G003_tpose_001](G003_tpose_001.json)

- **C001**：Front T-pose reference of the GG master

### [G003_tpose_002](G003_tpose_002.json)

- **C001**：Front T-pose reference of the tycoon

