# scripts_new — 三阶段生成与评估的统一入口

入口位于 `scripts/eval/`；评估实现统一位于 `pipeline/eval/`。
旧流程（正在跑的测评、Stage3 direct-refine 等）照常使用旧入口。

## 入口

| 脚本 | 作用 |
|---|---|
| `generate.py` | 一键排队生成：每个（项目×模型）一个 agent 会话；stage1 单轮，stage3 最多 10 轮续接同一会话；`--parallel` 默认 1 |
| `intake.py` | 校验交付是否符合 `delivery.json` 契约（我们自己的或外部提交的） |
| `evaluate.py` | 一键评估，stage1 按列分发、stage3 按单元、assets 直通 |

```bash
python scripts_new/generate.py --stage 1 --models sol,glm --games 1-20 --engines godot,three_js
python scripts_new/generate.py --stage 1 --models kimi --games G008 --dry-run
python scripts_new/intake.py   --stage 1 --models kimi --games 31-60
python scripts_new/evaluate.py --stage 1 --status
python scripts_new/evaluate.py --stage 1 --column mechanic -- <mechanic_v3_cli 原有参数>
python scripts_new/evaluate.py --stage assets -- --scope obj --games G001
```

`--` 之后的参数原样转给该列/单元的实现。

## 数据放哪

| 内容 | 位置 |
|---|---|
| 测例需求 + 参考图 | `test_data/test_samples/<GameID>/`（不变） |
| Stage1 白模生成 | `test_data/outputs/initial_game_gen/<模型目录>/<GameID>/<run_id>/` |
| Stage3 refine 输入 | `test_data/outputs/game_refine/inputs/<GameID>/`（从 `outputs/playtest/gN` 逐字节拷贝，见 `COPY_MANIFEST.json`） |
| Stage3 refine 生成 | `test_data/outputs/game_refine/<模型目录>/<GameID>/<run_id>/` |
| 评估结果 | `test_data/outputs/eval/{whitebox,refine,asset}/<评估版本>/<模型目录>/<GameID>/<run_id>/` |

模型目录映射（`config/models.json` 与 `pipeline/eval/stage1/paths.py`）：
`sol→gpt_sol6p1`、`astra→gpt_astra6`、`opus→claude_ops5p5`、`glm→glm_5p3`、`kimi→kimi_k3`。

旧目录（`outputs/playtest/`、`eval/playtest/`、`kimi-k3/` 等）保持原样。

## 评估实现在哪

`GameFactory-3A/pipeline/eval/`，统一包含 Stage1 白膜测评、Stage3、资产评估及 refine 模块，并复用仓库内的引擎适配器。

一次运行同时测全部八个 metric（`stage1/pipeline.py`）：

```
prepare → 静态 judge → 冻结标准 → 第 1~3 轮：plan → 适配器录制（按动作截帧）→ 证据（各轮并集）→ 证据 judge → 八列算分
```

| 文件 | 作用 |
|---|---|
| `stage1/criteria.py` | 每题八列判项（机制读 rubric_whitebox_core，资产读 core12，画面/Gameness 读 contract_history） |
| `stage1/metrics/*.py` | 每列的判词格式和算分；机制、Gameness 为 10/50/100，其余为 PASS/FAIL |
| `stage1/prepare.py` | 快照作者工程、需求、参考图，记录 SHA |
| `stage1/plan.py` | 一次规划覆盖所有运行时判项；输入能力取自适配器 |
| `stage1/record.py` | 直接调用 `client.playtest.record`；与旧流程共用全局 GUI 锁 |
| `stage1/evidence.py` | 证据清单、选帧、原像素 2×2 拼图 |
| `stage1/judge.py` | 所有列判项一起判，按交付内容校验引用 |
| `stage1/llm.py` | 只读模型调用、严格 JSON、封闭 schema |
| `stage1/standards.py` | 机制 v3 / Gameness v4 判前冻结标准：每题每列冻结一次，所有模型共用 |
| `stage1/capture.py` | 按动作截帧：每个输入动作的前/结束/后 300ms/后 1000ms + 每秒基线 |
| `stage1/unity_editor.py` | Unity/团结任意版本：按工程实际格式判系列，选同系列精确或最接近版本 |

某列升级 = 只改 `stage1/metrics/<列>.py`。

stage3 直接复用 stage1 流水线，只提供自己的 suite（`stage1/suites.py` 按 manifest 里记录的 suite 取判项和 metric）：

| 文件 | 作用 |
|---|---|
| `stage3/criteria.py` | 每个 refine 任务一个判项：mechanic / gamefeel / vfx / import（13 题共 493 项，与 task_counts 一致），通用规则，不写死任何题 |
| `stage3/metrics.py` | 五个维度都用 10/50/100：mechanic（Debugging）、gamefeel + vfx（Game-feel）、import（Asset Import）、texture（Texturing）；每维发布 S_c 与 Cov_c，全部判完才发布，无总分；audio 导入最高 50（未采声音） |
| texture（stage3_v2 起） | 每个 3d_object / 3d_scene 导入额外一个只评贴图/材质的判项；100% 必须是近景真实帧；planner 被要求靠近资产并停留 1–2 s，带判项的停留步骤会在中间与结尾截帧 |

```
python scripts_new/evaluate.py --stage 3 --models glm --games 8 --run-id <run_id>
```

## 当前状态

- 已迁移但**未实际运行过**：仅做导入/编译检查和纯函数检查
- 已验证：判项与 32 道历史题 5161 项逐条一致；两份已发布分数用新 metric 重算一致；Unity 编辑器选择对现有交付全部有解
- 按动作截帧：three.js、Unity、无条件等待的 Godot 计划用截帧计划表；Godot 带 wait_until、UE5 用 10fps 连续录制 + 按真实动作时间取帧（录制器本身不支持输入事件触发截帧，适配层未改）
- 生成侧已迁移到 `scripts_new/gen/`（不再调用旧 scripts/）：
  - `agents.py` 四种 CLI（codex / claude / zcode / kimi）的启动与同会话续接，事件日志按轮保存
  - `runner.py` 多轮驱动：第 1 轮记录会话 id，之后只续接该会话；中断/超时的轮也计入预算；换会话即判失败
  - `stage1.py` 冻结 prompt `prompts/stage1_whitebox.md` + delivery.json 契约，单轮，按档位超时
  - `stage3.py` 复制 Sol 原工程到 `game_refine/<模型目录>/<题>/<run>/project`（原件只读、前后校验摘要），写本题 `refine_tasks.json`，沿用旧修复 prompt，每轮 30 分钟、最多 10 轮，agent 报告无可做剩余任务即停，结束写 stage3 delivery.json
  - 本机 PATH 暂无 kimi / zcode CLI，运行前需安装或在 models.json 配 executable
  - CLI 跑不了时用手动流程：`generate.py --manual` 生成各轮 prompt → 在 agent 里同一对话逐轮发送 → `generate.py --finalize` 收尾，见 `MANUAL_GENERATION.md`；对外模板见 `prompts/stage1_whitebox_public.md`、`prompts/stage3_refine_public.md`
- UE 录制（2026-11-09）：走适配器底层 `native_record.record`，自带截帧计划（按动作）、空闲私有端口、3 s 预热；按用户决定 B，单帧允许晚到 ≤3 s（原 350 ms），每帧实际晚到写入 `capture_lateness.json`。插件数字键映射已修（`engine_adapters/ue5/plugin/_archive/20261109_digit_keys/`）
- Unity 录制：旧输入工程先在评估副本做 Input System 迁移（回执 `runtime/unity_input_migration.json`），用 `graphics_batch_render_v2` 后台策略（禁止回退系统键鼠）
- 尚未迁移：assets
- stage3 尚缺：3D 资产的原始 GLB 参考渲染（本机多数题资产文件未下载，暂用题目自带参考图）
- 旧 run 没有 `delivery.json`，需要回填后才能评估
- 多轮录制：每个交付最多 3 轮（所有模型相同）。第 2 轮起只为仍无运行证据的判项重新 plan（分级列 ≤10% 且无已观察 bug、二元列 UNVERIFIED），带上前几轮计划和 judge 原因；只重判这些判项，证据为各轮并集；某轮没有新解决任何判项即停。最终每个判项取最近一次判词，过程记录在 takes.json
- 计分沿用旧规则：二元六列 UNVERIFIED 记 0，机制 / Gameness 按 10/50/100，总分为八列等权平均
- 建议评估时先对同一题的所有模型一起跑（evaluate.py 会先 prepare 全部再逐个评估），这样冻结标准能参考到所有模型的源码
