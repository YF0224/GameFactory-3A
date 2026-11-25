---
name: stage3-eval-runner
description: "运行并看护 Stage3 refine 候选评估（按当前授权选择 planner/judge，UE/Unity 录制）：启动、看进度、区分评估工具故障与项目启动故障、在评估副本内按 stage3-launch-repair 规则修复项目启动问题并续跑、保留证据、按格式汇报。不改评估代码、不改评分、不改原始交付。"
---

# Stage3 评估看护（给运行评估的 Codex 代理）

目标：让每个游戏都尽量走完 **plan → record → evidence → judge → score**，出真实分数。你负责启动、看护、续跑和**项目启动问题的修复**；评估代码和评分规则一律不动（有问题记录下来交给维护者）。

先读同目录旁的 `../stage3-launch-repair/SKILL.md`（修复的允许/禁止范围），以及包里的 `README_stage3评估说明.md`（安装、目录、启动命令）。

## 1. 启动与看护

- 用 README 里的命令在**长期存活的终端**启动（不要 nohup 后退出 shell）。环境变量必须完全照抄（`A3GAME_EXCLUSIVE_ENGINE=1 A3GAME_GUI_SLOTS=1 A3GAME_EVENT_FRAMES=1 A3GAME_MAX_RETRY_TAKES=0 A3GAME_SEED_PLANS=1 A3GAME_DIRECT_ROUNDS=1`），planner/judge 与轮数以本会话最新用户授权为准（2026-11-14 Sol/Opus 续跑均为 `gpt-6.1-sol`，普通两次、direct 一轮）；未指定时才沿 README 默认。Codex CLI 固定 0.166.0，所有 shell 命令都加 `HOMEBREW_NO_AUTO_UPDATE=1`。
- 每 30 分钟：`python3 scripts_new/run_status.py --model <模型> --run-suffix <run-id 去掉模型名的部分>`，并 `df -h /`（低于 20 GiB 停下汇报，任何时候保留 ≥ 8 GiB）。
- 某游戏状态 `HARNESS_ERROR` 时该路会自动继续下一个游戏，**不要停整路**；按第 2 节处理这个游戏，处理完再单独续跑它（第 4 节）。
- 一个游戏卡在同一步超过 40 分钟：看对应日志判断是在等引擎锁（正常，另一路在录制/编译）、模型调用（看 `model_calls/` 最新目录的 events.jsonl 是否在增长）还是卡死；卡死按第 2 节记录，不要杀别的会话的进程。

## 2. 先分类：谁的问题

读 `<eval dir>/status.json` 的 `error`、`takes/<k>/record/record_error.json`，以及：UE `takes/<k>/record/native/take/unreal.log`、`runtime/ue_admission*/`（build.json、admission.json）；Unity `takes/<k>/record/import.log`、`import_result.json`。

| 类别 | 典型报错 | 处理 |
|---|---|---|
| **评估工具故障** | `missed its predeclared capture slot`、`capture slots missing`、`did not deliver actions`、`GUI recording slot ... busy`、`plan needs ... more than`、`model call timeout`、schema/解析错误、`code-mode host` | **不修代码**。记录（第 5 节格式），等维护者修复后续跑 |
| **项目启动故障** | UE `UE native admission failed` 且构建日志有 C++ 编译/链接错误、缺模块/插件；Unity `error CSxxxx` / `Scripts have compiler errors`、缺包、入口场景打不开 | 按第 3 节修复 |
| **产品表现** | 游戏崩溃（`GAME CRASH` 事件）、死亡、卡关、画面不对、低分 | **不是故障**，这就是测评结果，不修、不重跑 |

拿不准时按“评估工具故障”记录，不要动手修。

## 3. 项目启动故障的修复

**只改评估副本** `<eval dir>/runtime/project`，绝不改 `<eval dir>/input/`（冻结快照，改了整个评估作废）和原始交付目录。范围和禁止项严格按 `stage3-launch-repair/SKILL.md`：只允许工程配置和**不改变行为**的编译兼容；不改玩法/数值/场景/资源，不删或注释作者代码。

每次修复都要留档：在 `<eval dir>/runtime/launch_repair/<两位序号>/` 下保存
- `change.diff`：`diff -ru` 形式的完整改动（改前先把要改的文件复制到同目录 `backup/` 下，保持相对路径）
- `receipt.json`：`{"engine", "failure"（原报错）, "logs"（依据的日志路径）, "root_cause", "changes":[{"file","kind":"config|compile_compat|new_stub","why_no_behaviour_change"}], "applied": true/false, "time"}`
- 修完自查一遍 diff：任何一处可能改变“同样输入下游戏做什么”的，回滚（从 backup 复制回去）并在 receipt 里写 `applied: false` 和原因。

### Unity
改好后可以直接续跑：评估会对 `runtime/project` 重新导入编译（第 4 节）。

### UE
**当前评估代码要求 `runtime/project` 与冻结快照逐字节一致才允许 admission**，直接改副本会被拒绝（而且失败的 admission 会把副本重置回快照）。所以 UE 只做：
1. 在 `runtime/launch_repair/<序号>/` 里写好 `change.diff` 和 `receipt.json`（`applied: false`，`reason: "UE admission requires authored-identical copy; patch prepared for maintainer"`），**不要改 `runtime/project`**；
2. 汇报给维护者，维护者集成后会用这个补丁续跑。

## 4. 续跑一个游戏

1. 确认这一路已经离开该游戏（status 不再是 running），且没有该游戏的引擎进程在跑。
2. 把失败那次的 `takes/<k>/record` **改名**保留：`record_failed_<原因>_<日期>`（例如 `record_failed_launch_20261113`）。**不要删除**任何目录、锁或证据。
3. 用和原来完全相同的命令、相同 `--run-id`，`--games` 只写这个游戏号（例如 `--games G030`）单独运行。已完成的步骤自动跳过，已有的 plan 会复用，只补录制和之后的步骤。
4. 同一游戏同一种启动故障最多修 2 轮；仍不行就停，按第 5 节汇报。

## 4b. 新的故障类型：写一个可复用的 repair 脚本

评估流程本身不含针对具体失败的恢复分支。遇到**没见过**的工具/录制/启动故障时，恢复脚本由你（代理）自己写，放进 `GameFactory-3A/pipeline/eval/repair/`，之后所有批次都能复用：

1. 先看 `pipeline/eval/repair/__init__.py` 的 `REGISTRY`，确认没有现成模块能处理；有就直接 import 调用，不重复写。
2. 新建 `pipeline/eval/repair/<引擎>_<症状>_recovery.py`，要求：
   - 只修评估侧（评估副本、环境、传输、已接受阶段/实录的复用），**不改游戏行为、不改评分、不改证据**；
   - 保留原失败、原请求/响应/实录和 claim，从最后合格阶段续接，不重跑已完成的部分；
   - 在它修复的那个 run 目录旁边写 receipt（做了什么、依据的日志、前后 SHA、为什么不算新录制）；
   - 顶层 import 只用绝对路径（`from pipeline.eval.stage1 import ...`），同目录兄弟用 `from . import ...`；
   - 写一个离线测试放 `GameFactory-3A/test/`，用假的输入验证它不会改到不该改的东西。
3. 在 `REGISTRY` 里登记一行（模块名 → 阶段 + 一句话用途）。
4. 用完汇报：模块名、修复了哪个游戏、receipt 路径、是否复用。别人的会话正在用的模块不要改语义，需要改就新建一个并在汇报里说明差异。

## 5. 汇报格式（发给维护者）

每个出问题的游戏一段：

```
模型 / 游戏 / run-id：
类别：评估工具故障 | 项目启动故障（已修复续跑 / UE 补丁待集成 / 无法安全修复） | 卡死
status.json：<原文>
报错原文：<record_error.json 或日志关键行>
日志路径：<...>
已做的处理：<改名了哪个目录、修复留档路径、续跑结果>
```

另外每 30 分钟一行进度：各路当前游戏/阶段、已出分游戏的 Mech/GF/VFX/Imp/Tex。

## 禁止

- 修改 `GameFactory-3A/`、`scripts_new/` 里的任何评估代码或 `test_data/bench_standards/` 评分标准；重新冻结标准。
- 删除评估目录、take、录像、模型调用记录；删锁；杀不是本次评估启动的进程。
- 因为分数低、游戏失败或崩溃而重跑；手填或改分数。
- 改原始交付或 `input/` 冻结快照；用别的模型/别的版本的项目代替。


## 2026-11-14 Sol / Opus 工具故障的授权修复与验收边界

> 本节仅记录用户于 2026-11-14 明确授权修复评估工具的这次例外；上方“看护代理不得改评估代码/评分”仍为默认规则。Kimi 暂不处理；不改冻结标准、作者原件、input、既有成绩及失败证据。Codex CLI 固定 0.166.0，所有命令前加 `HOMEBREW_NO_AUTO_UPDATE=1`，全机同一时刻最多一个 native 引擎；全局最多两个 evaluator；已有旧路占额时新路等容量，不增加第三个 evaluator、不终止他人进程。磁盘低于 20 GiB 停下汇报，至少保留 8 GiB。

- 源头和逐例原文：`test_data/outputs/eval/refine/supervision/opus_astra_20261113/sol_opus_repair_triage_20261114_1012.json`。Sol G045 evidence：第二次 schema 错误 `$.checks: expected object`；Opus G050 plan：第二次 schema 错误 `$.probes[0].steps[1]: value does not match any allowed schema variant`。工具端 `pipeline/eval/stage1/llm.py` 的恢复仅在 `A3GAME_STAGE3_FORMAT_RECOVERY=1` 时生效：原始所有回复、错误及 SHA 原样保留，按最近错误提示生成新独立调用，单个 shard 历次尝试总计最多四次；响应仍按原闭合 schema 和原 validator 校验。`judge.py` 明示输入 CHECKS 是列表、输出 checks 是按判项 ID 索引的对象。不允许将失败回复作为新成绩、不允许无限原样重试。 隔离回归已验证：第4次合法回复可接受、4次均失败后不会发起第5次、未开启恢复时仍只允许原2次；回执见上述授权续跑目录的 `format_recovery_regression/receipt.json`（无真实模型调用）。
- Opus G045 原 plan 有 33 个合法零时长步骤，但 Unity adapter 要求正时长。`pipeline/eval/stage1/plan.py` 新计划最小值 1 ms；仅对历史零时长 plan 的执行动作按原验证器已经预留的每步 100 ms 转换，plan JSON 不变。`record.py` 写 `takes/<take>/record/duration_compat.json`：原 plan SHA、每个动作 ID 与原/有效时长。2026-11-14 隔离测试以 G045 原 plan 验证 33 步转换、原 SHA 不变、所有执行动作正时长；**不是 Unity 原生录制验收**。
- UE Sol G055 / Opus G055 均报 `UE native exit timeout`。UE recorder 插件 `A3GamePlaytestRecorderSubsystem.{h,cpp}` 增加 `IsTickableWhenPaused()`，让已开始录制及音频退出在作者暂停游戏时继续前进，不改变游戏暂停状态；**已通过 UE 5.4 真实暂停录制验收（2026-11-14）**：正式 admission 编译成功，作者日志有 `IC_FLAME_LIFECYCLE paused=1`，暂停菜单后的原生帧继续采集，20/20 个索引 PNG 均可解码，WAV 非空（4.992 秒实际缓冲），native returncode=0，capture 缺槽为空，process/view/input cleanup 全通过且无残留，原 input digest 不变。证据见 `test_data/outputs/eval/refine/supervision/opus_astra_20261113/sol_opus_authorized_repair_20261114_1040/ue_pause_validation/{receipt.json,postcheck.json,record/native/take/}`。此验收证明“已开始录制后进入作者暂停菜单”仍能采帧并退出；不代表 Sol/Opus 整题已完成，不证明暂停期间全墙钟长度音频或精确音画同步。更换插件导致 UE admission pin 失效时，`record.py` 将旧 `runtime/ue_admission` 和 `runtime/project` 顺序改名为 `ue_admission_stale_NNN` / `project_stale_NNN` 并写原因，再从冻结 input 重建副本；不删原失败材料。2026-11-14 隔离测试覆盖旧目录完整归档和新副本重建，未代替 UE 原生验收。若原生仍 timeout，保留原报错、status 与 native 日志，按新根因修复，不把 timeout 当游戏结果。
- 续跑只用原 run-id、原来源绑定与 `gpt-6.1-sol` planner/judge，普通两次/direct 一轮、`A3GAME_EXCLUSIVE_ENGINE=1 A3GAME_GUI_SLOTS=1`；重跑前逐例核有没有真实完整 score、在途子进程、旧 plan/take、磁盘与单引擎锁。录制失败且**该 take 没有在途进程**时，只把原 `takes/<take>/record` 改名为唯一 `record_failed_<cause>_<timestamp>` 并保留全部失败原文，再续录；格式故障沿原目录续接并显式开启格式恢复变量。G015/G030 已完整出分的不重测；G025 不测。原队列配置：`.../opus_astra_20261113/sol_after_astra_20261113_215737/config.json` 和 `.../opus_remaining_20261113_180458/config.json`。每 30 分钟报告 Sol/Opus 各游戏阶段和本轮真实新分；HARNESS_ERROR、traceback、非等待引擎锁的 40 分钟停滞，按第 5 节附 status 原文、报错原文、take 日志路径，不清目录/锁/其他会话进程。

- 真实格式恢复验收：Sol G045 的 `evidence_t1_04` 从原失败沿同 run 接受了 `model_calls/evidence_t1_04_003/response.json`，并进入 `plan_t2`；以 `accepted_response.json` 的原路径和 SHA 核验，不只看文件存在。Unity 零时长修复仍只有隔离执行动作测试，等 Opus G045 的实际录制结果后才标记原生通过。统一修复验收索引见上述队列目录的 `repair_verification.json`。


## 2026-11-14 Kimi UE 恢复经验

用户明确授权修 harness 的本次恢复、历史 provenance/transaction、optional failed take 发布阻断与 G035 音频并发崩溃，见 [已验证事实与限制](references/kimi-ue-compat-20261114.md)。仅在遇到相同恢复问题时读取；区分编译验收、隔离录制与正式出分。
