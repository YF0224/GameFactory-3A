# 游戏 Refine 任务说明

请先按照本文第 3–5 节下载本次需要的 **13 个 Sol 原始游戏工程和对应资产文件**，然后根据以下目录中的三份需求文件，对各游戏执行 refine，完成机制、手感、资产导入和视觉效果修改：

```text
/Users/bohanzeng/Documents/project/gamefactory3a-gamebench/yifan-game-bench/test_data/outputs/game_refine/
```

- `repair_selected200_simple_v2_collect.jsonl`：机制和手感修改需求。
- `repair_import_simple_collect.json`：模型、场景、动作、音频和 CG 等资产导入需求。
- `repair_vfx_collect.jsonl`：视觉效果修改需求。

每个项目的修改要求已经按游戏整理在以下目录中，各 `g<num>/refine.json` 记录该游戏的任务索引，并引用同目录下包含具体修改条目的分类 JSON：

```text
/Users/bohanzeng/Documents/project/gamefactory3a-gamebench/yifan-game-bench/test_data/outputs/playtest/g<num>/refine.json
```

请让模型先完整读取该游戏的 `refine.json` 及其引用的任务文件，再按 JSON 中的要求逐项完成 refine。请在对应的 `test_data/outputs/playtest/g<num>/astra/` 下完成并交付：修改后的完整游戏工程放在 `astra/project/`，逐条修改内容、验证结果和未完成原因记录在 `astra/report.md`。

学长机器上的游戏工程下载和解压目录统一为：

```text
/Users/bohanzeng/Documents/project/gamefactory3a-gamebench/yifan-game-bench/sol_download/
```

游戏压缩包下载到上述 `sol_download/` 下，解压后的工程也放在该目录下，形成 `sol_download/<game_id>/<原始run>/...`。从中找到对应工程，复制到本游戏的 `astra/project/` 后进行修改。游戏资产从 Hugging Face 下载到 `test_data/outputs/asset/<game_id>/assets/`，再按导入任务接入游戏。

## 1. 路径约定

以下路径和命令用于学长的机器，后文相对路径均从学长的仓库根目录解析：

```bash
cd /Users/bohanzeng/Documents/project/gamefactory3a-gamebench/yifan-game-bench
```

| 内容 | 路径 |
| --- | --- |
| 全部选中需求 | `test_data/outputs/game_refine/` |
| 各游戏任务入口 | `test_data/outputs/playtest/g<num>/refine.json` |
| 游戏压缩包下载目录 | `sol_download/outputs/initial_game_gen/gpt_sol6p1/refine_original13_20261104/` |
| 解压后的原游戏仓库 | `sol_download/<game_id>/<原始run>/` |
| Astra 修改后的游戏工程 | `test_data/outputs/playtest/g<num>/astra/project/` |
| 修改说明和验证记录 | `test_data/outputs/playtest/g<num>/astra/report.md` |
| 下载后的共享资产 | `test_data/outputs/asset/<game_id>/assets/` |
| 游戏原始需求、参考图 | `test_data/test_samples/<game_id>/` |

例如 G008 对应 `g8`，G003 对应 `g3`，不是 `g008` 或 `g003`。`astra` 表示修复结果的归属，原始游戏来源仍为 Sol。

## 2. 每个游戏需要读什么

以 G008 为例：

```text
test_data/outputs/playtest/g8/
  refine.json                 # game_id、工程来源、分类任务路径及条目数
  mechanic_gamefeel.json      # 本游戏的机制和手感修改
  import.json                 # 本游戏的资产导入任务，包括 motion
  vfx.json                    # 本游戏的视觉效果修改
  initgame.json               # 原工程来源与入口信息
  astra/
    project/                  # 在这里修改、构建、运行游戏
    report.md                 # 逐条记录修改、验证和未完成原因
```

`refine.json` 是索引，具体修改条目在其 `inputs` 引用的 JSON 中；这些路径相对当前 `g<num>/` 目录解析。读取本游戏的全部条目，按 `game_id`、`selection_id`、`import_id` 或 `task_id` 对应到原需求。

三份全量需求文件都是 **JSONL，每个非空行一个 JSON 对象**，包括扩展名为 `.json` 的 `repair_import_simple_collect.json`。各游戏拆好的 `mechanic_gamefeel.json`、`import.json`、`vfx.json` 则是普通 JSON 数组。

资产任务中重点读取：

- `asset_kind`、`task_id`、`asset_path`：资产类型、身份和预期存放位置。
- `target`、`import_goal`、`asset_requirements`：替换哪个对象、需要接入什么行为、有什么约束。
- `general_requirement`、`reference_images`：游戏需求和参考图，路径相对仓库根目录。

`asset_path` 通常是目录，不能据此认为文件已经下载。需要补充导入细节时，按 `import_id` 查询同目录的 `repair_import_collect.json`；该详细文件也按 JSONL 读取。

本次共 13 个游戏、493 条选中任务：

| 目录 | game_id | 机制＋手感 | 导入 | VFX |
| --- | --- | ---: | ---: | ---: |
| `g3` | `G003_gggame_courtyard_rps` | 10 | 18 | 2 |
| `g8` | `G008_dock_beacon_cs` | 19 | 22 | 5 |
| `g15` | `G015_garden_revival` | 14 | 18 | 5 |
| `g20` | `G020_tidal_glyphs` | 8 | 12 | 3 |
| `g25` | `G025_broken_continent_rts` | 28 | 59 | 1 |
| `g30` | `G030_polar_night_td` | 15 | 14 | 7 |
| `g35` | `G035_rift_expedition` | 14 | 40 | 9 |
| `g40` | `G040_endurance_race` | 10 | 16 | 2 |
| `g45` | `G045_daily_street_lightlane` | 19 | 24 | 0 |
| `g50` | `G050_aftermath_holdout` | 20 | 8 | 0 |
| `g55` | `G055_inner_court_investigation` | 20 | 11 | 2 |
| `g58` | `G058_pitch_dreams_football` | 16 | 4 | 0 |
| `g60` | `G060_volcano_stunt_route` | 7 | 9 | 2 |
| 合计 | | 200 | 255 | 38 |

## 3. 从 Hugging Face 下载游戏工程并解压

游戏工程和待导入资产放在同一个 Hugging Face dataset `YY222/bench` 中，使用不同的远端目录和固定版本：

| 内容 | 远端目录 | 固定 revision |
| --- | --- | --- |
| 本批 13 个原游戏工程压缩包 | `outputs/initial_game_gen/gpt_sol6p1/refine_original13_20261104/` | `bf0566d4f717b7212cd5913a978e7a1529cb3976` |
| 各游戏待导入资产 | `outputs/<game_id>/assets/` | `2a6561c93f1e08b7b493b2f640e8ab1e08e06b79` |

先在仓库根目录安装下载工具：

```bash
python3 -m pip install huggingface_hub
```

需要认证时运行 `hf auth login`。以下只下载游戏工程包；资产按第 4 节另外下载。

**完整下载、校验、解压命令**（从仓库根目录执行）：

```bash
(
  set -e
  refine_bench_root="$PWD"
  refine_game_dir="$refine_bench_root/sol_download"
  refine_package_dir="$refine_game_dir/outputs/initial_game_gen/gpt_sol6p1/refine_original13_20261104"

  hf download YY222/bench \
    --repo-type dataset \
    --revision bf0566d4f717b7212cd5913a978e7a1529cb3976 \
    --include "outputs/initial_game_gen/gpt_sol6p1/refine_original13_20261104/*" \
    --local-dir "$refine_game_dir"

  cd "$refine_package_dir"
  shasum -a 256 -c SHA256SUMS

  mkdir -p "$refine_game_dir"
  for archive in ./*.tar.gz; do
    tar -xzkf "$archive" --strip-components=4 -C "$refine_game_dir"
  done
)
```

下载包和解压后的原工程都保存在学长的 `sol_download/` 内：压缩包位于 `sol_download/outputs/initial_game_gen/gpt_sol6p1/refine_original13_20261104/`，解压后的工程位于 `sol_download/<game_id>/<原始run>/`。压缩包包含 `test_data/outputs/initial_game_gen/gpt_sol6p1/` 四层前缀，`--strip-components=4` 将其去掉，使工程落在 `sol_download/<game_id>/<原始run>/...`。`-k` 保留已有文件；重复解压前先核对现有内容。校验失败会停止解压。

下载和解压后得到：

```text
sol_download/outputs/initial_game_gen/gpt_sol6p1/refine_original13_20261104/
  README.md
  manifest.json
  SHA256SUMS
  G003_gggame_courtyard_rps.tar.gz
  G008_dock_beacon_cs.tar.gz
  ...另外 11 个游戏包

sol_download/
  G003_gggame_courtyard_rps/retry9_20261015_063356/pipeline/...
  G008_dock_beacon_cs/retry15_20261015_154525/pipeline/...
  ...另外 11 个游戏原工程
```

在 `sol_download/` 中按完整 `game_id` 和原始 run 查找对应工程。任务文件的 `selected_project.project_root`、`launch_entry` 和 `initgame.json` 用于核对来源；其中冻结的原路径前缀 `test_data/outputs/initial_game_gen/gpt_sol6p1/` 对应本次交付的 `sol_download/`，保留后面的游戏、run 和项目内部层级进行定位，任务 JSON 保持原样。

可以先列出工程入口：

```bash
rg --files sol_download -g '*.uproject' -g 'ProjectVersion.txt'
```

UE 工程根目录是 `.uproject` 所在目录；Unity／团结工程根目录包含 `Assets/`、`Packages/` 和 `ProjectSettings/`。G015、G045、G058 为 Unity／团结，其余本批工程为 UE5。按实际工程版本准备对应编辑器和构建工具。

将确认好的完整工程复制到对应的 `astra/project/`，保留源码、场景、资产、配置及所需相对依赖。已有修复副本时继续修改该副本，避免用原件覆盖进度。原始 `sol_download/` 和任务 JSON 保留不改。

**G050 的特殊入口：** 当前 `g50/refine.json` 的 `selected_project` 为 `null`，已有配置在 `test_data/outputs/game_refine/glm_sol_stage3_repair10_hf_20261102/configuration.json` 的 `project_overrides.G050_aftermath_holdout` 中补充了来源：

```text
G050_aftermath_holdout/
  gamefactory_G050_aftermath_holdout_20261023_120741/
    pipeline/G050_aftermath_holdout_whitebox/project/Aftermath.uproject
```

在 `sol_download/` 核对这个 run 和真实入口，再复制工程。未找到时在报告中记录缺少的工程和入口。

## 4. 模型、场景、音频和 CG 如何下载

资产来自 Hugging Face dataset `YY222/bench`，远端与本机的对应关系为：

```text
远端：outputs/<game_id>/assets/<asset_kind>/<task_id>/...
本机：test_data/outputs/asset/<game_id>/assets/<asset_kind>/<task_id>/...
```

推荐使用仓库已有的 [download_assets.py](../asset/download_assets.py)，它会从 Hugging Face 下载，并把远端的 `outputs/` 层级整理成任务 `asset_path` 使用的本机路径。依赖和认证同第 3 节。

**下载全部 13 个游戏的模型、场景、音频和 CG 资产**（从仓库根目录执行）：

```bash
python3 scripts/asset/download_assets.py \
  --revision 2a6561c93f1e08b7b493b2f640e8ab1e08e06b79 \
  --games G003 G008 G015 G020 G025 G030 G035 G040 G045 G050 G055 G058 G060 \
  --kind 3d_object --kind 3d_scene --kind audio --kind cg_video
```

`--games` 支持这里的编号前缀，也支持完整 `game_id`。命令完成后，以 G008 为例，文件位于：

```text
test_data/outputs/asset/G008_dock_beacon_cs/assets/
  3d_object/<task_id>/meshy/model.glb
  3d_scene/<task_id>/<名称>_Portable.zip
  audio/<task_id>/audio.wav
  cg_video/<task_id>/video.mp4
```

这些是常见载荷形式，具体文件以远端交付和下载清单为准。

**只下载一个游戏：** 下面第一条只打印选择配置，第二条实际下载 G008：

```bash
python3 scripts/asset/download_assets.py \
  --revision 2a6561c93f1e08b7b493b2f640e8ab1e08e06b79 \
  --games G008_dock_beacon_cs \
  --kind 3d_object --kind 3d_scene --kind audio --kind cg_video \
  --dry-run

python3 scripts/asset/download_assets.py \
  --revision 2a6561c93f1e08b7b493b2f640e8ab1e08e06b79 \
  --games G008_dock_beacon_cs \
  --kind 3d_object --kind 3d_scene --kind audio --kind cg_video
```

把 `--games` 后的 ID 换成对应游戏即可；也可以一次传多个游戏 ID。上述命令下载该游戏这些类型的全部远端文件，**实际导入以本游戏 `import.json` 选中的任务为准**。只下载某项时加 `--task <task_id>`，多项可重复传 `--task`。

脚本将文件放到上面的本机资产目录，并在 `test_data/outputs/_asset_downloads/<revision>.json` 记录远端版本、文件列表和下载结果。已有同内容文件会复用，冲突文件会保留并报错。下载成功后仍需逐项核对 `import.json` 是否有对应载荷。

| 类型 | 常见载荷与接入方式 |
| --- | --- |
| `3d_object` | 通常使用任务目录下的 `meshy/model.glb`；按任务匹配正确对象，并带入所需贴图、材质。 |
| `3d_scene` | 可能是 `<名称>_Portable.zip`；先查看包内目录，再将对应场景、贴图和依赖解压到该任务目录，找到 `scene.glb`。 |
| `audio` | 通常是 `audio.wav`；按任务接入对应触发、播放和结束逻辑。 |
| `cg_video` | 通常是 `video.mp4`；按任务接入触发、跳过及播放后的游戏状态。 |
| `motion` | 本批另有 Git 来源的 NPZ，按下一节获取。 |

如果只想用 Hugging Face CLI 原样下载某个资产目录，也可以运行下面这条命令。这是上面脚本的替代方式，按需选用：

```bash
hf download YY222/bench \
  --repo-type dataset \
  --revision 2a6561c93f1e08b7b493b2f640e8ab1e08e06b79 \
  --include "outputs/G008_dock_beacon_cs/assets/*" \
  --local-dir downloads/hf_assets
```

这条命令保留远端层级，结果位于 `downloads/hf_assets/outputs/G008_dock_beacon_cs/assets/`。若使用此方式，需把该 `assets/` 中的内容复制到 `test_data/outputs/asset/G008_dock_beacon_cs/assets/`，再按 `import.json` 接入。优先使用前面的脚本可直接放到目标位置。远端该目录也可能包含 motion 等额外交付；本批动作任务仍按第 5 节的固定来源核对。

下载前确认有足够空间容纳素材、解压和工程副本，并额外保留至少 8GiB。没有对应载荷的任务记录具体缺失文件；文件到位后还需要在游戏中完成实际导入与接入。

## 5. Motion 动作数据如何获取

本批动作源来自本仓库固定 Git 提交：

```text
commit: e1f7c4ab7190d4f6e6c7d3dae2162c15c2b8764c
路径：test_data/outputs/assets/motion/gpt6p1_sol_omnicontrol/<game_id>/motion/<task_id>/motion.npz
```

使用 [acquire_refine_motion_git.py](../asset/acquire_refine_motion_git.py) 按任务提取，无需切换当前工作分支。在仓库根目录执行；若本地尚无该提交，先获取提交：

```bash
git fetch origin e1f7c4ab7190d4f6e6c7d3dae2162c15c2b8764c

python3 scripts/asset/acquire_refine_motion_git.py \
  --inventory test_data/outputs/game_refine/glm_sol_stage3_repair10_hf_20261102/inventory.json \
  --commit e1f7c4ab7190d4f6e6c7d3dae2162c15c2b8764c \
  --output test_data/outputs/game_refine/motion_sources_local \
  --fetch
```

结果包括：

```text
motion_sources_local/
  acquisition_selection.json
  completion.json
  payloads/<game_id>/<task_id>/motion.npz
```

`completion.json` 保存文件路径、SHA 和缺失任务。按 `game_id`、`task_id` 对应本游戏 `import.json`，从 `payloads/` 获取动作源。若交付材料已包含原来的 `motion_git_pr18_20261103/`，也可核对其中 `completion.json` 后复用；有 `decoded/<game_id>/<task_id>/motion.json` 时可结合原 NPZ 阅读数组数据，跨机器按实际目录解析路径。

NPZ 是动作数据源，需要根据任务和目标角色完成骨架对应、retarget、引擎导入与播放；不能当成已可直接导入的 FBX。现有该提交来源核验覆盖 **78 项中的 76 项**，以下两项没有精确匹配的动作源：

- G030：`G030_polar_night_td_mot_001`。
- G040：`G040_endurance_race_mot_001`。

这两项在报告中记录缺失来源和待补文件，保留原任务 ID。

## 6. 修改和交付要求

1. 逐个游戏读取完整任务，确认原工程和素材，将游戏副本放到对应 `astra/project/`。
2. 按选中条目完成机制、手感、VFX 和资产接入。资产需要在真实场景、角色或事件中使用，并满足任务声明的触发与结束条件。
3. 用对应引擎构建并运行修改后的工程，通过实际操作检查任务行为，保存构建日志、关键截图或录像。
4. 在 `astra/report.md` 按原任务 ID 记录修改文件、实现内容、验证方式和结果。源码已实现、构建通过、实际运行通过分别记录；未完成项写具体原因及缺少的输入。

最终每个游戏交付可继续打开和修改的完整工程，以及逐条修改／验证记录。已有实验的续接记录和共享引擎租约按其原约定保留。
