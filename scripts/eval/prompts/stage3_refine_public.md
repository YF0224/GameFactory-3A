# GameFactory-3A Stage 3 — Refine（对外公开版 prompt）

> 用法：一个（游戏 × 模型）= 你的 agent 里的**一个对话**。第 1 轮发「首轮 prompt」，之后每轮在**同一对话**里发「续接 prompt」，最多 10 轮，agent 报告没有可做的剩余任务即可提前结束。
> 推荐用 `python scripts_new/generate.py --stage 3 --models <模型> --games <题> --manual` 自动生成已填好的各轮 prompt；本文件是手工填写用的模板。
> 必须提供 GameFactory-3A 框架（框架 + prompt），结果才与基准可比。

| 占位符 | 含义 |
|---|---|
| `{GAME_ID}` | 例如 `G008_dock_beacon_cs` |
| `{WORKSPACE}` | 本次 refine 工作区 = `test_data/outputs/game_refine/<模型目录>/{GAME_ID}/<run_id>`，其中 `project/` 是从 Sol 原始工程复制的候选 |
| `{SETTING_OVERVIEW}` | `GameFactory-3A/agent_skills/setting_overview.md` |
| `{TASK_IDS}` | `refine_tasks.json` 里的全部 `task_ids`（JSON 数组） |
| `{N}` | 当前轮次（2..10） |

---

## 首轮 prompt

你是游戏 {GAME_ID} 的唯一修复 agent。只修改当前工作区 `{WORKSPACE}/project`，原始作者工程只读。

执行顺序（同一个对话内顺序完成）：
1. 先完整阅读 `{SETTING_OVERVIEW}`，理解 GameFactory-3A 的框架、分层和技能路由，确认 playtest 属于本次 refine 的“修复—验证—再修复”闭环；只按任务所需路由查对应引擎和技能。
2. 然后读取 `{WORKSPACE}/refine_tasks.json`，这是本游戏本次需要修复的完整任务，包含原始条目、验收、资产路径和全部 task ID。逐项理解 mechanic、gamefeel、import、texture、VFX、motion/绑骨/retarget 任务，定位对应工程代码与资产；不得仅凭文件名或任务编号猜需求。
3. 针对任务作最小必要修复，并按 overview 路由找到对应引擎的 playtest，进行构建/启动、实际操作、录制/观看、修复及复查。某项资源或工具确实阻塞时逐项记录原因，继续其他可做任务。

你同时承担 refine 与 playtest：允许并要求启动本项目引擎、构建、运行技能规定的 playtest。最终独立评估由另一脚本执行，本次不得调用；不得用静态检查冒充 playtest。

修复必须覆盖全部任务及其原始验收，不得只写计划或报告。全部任务共享最多 10 轮，可提前结束。禁止伪造 playtest、状态、画面、资产结果或 PASS；工具失败如实记录。不得降低需求，不得只复制资产而不接入真实槽位。保留原玩法、入口、ID、组件和既有功能；不修改原始工程、评估工具、数据集或工作区外文件。

playtest 必须包括受影响的实际玩家操作，并录制、观看和复查真实游戏画面。资产检查游戏内模型的外观/比例/朝向/形变和材质；动作检查骨骼、蒙皮、绑定、retarget 与实际播放；VFX 检查真实动作下触发/停止时机、形状与挂点。

必须在 `{WORKSPACE}/repair_report.md` 逐项记录实际改动文件、playtest 实况、已解决/未解决项和外部阻塞。

本轮结束时在工作区（project/ 外）写 `repair_status.json`，严格 JSON：
`{"game_id": "{GAME_ID}", "round": 1, "completed_task_ids": [], "remaining_tasks": [{"task_id": "未完成的真实ID", "actionable": true, "reason": "具体剩余修改或外部阻塞"}]}`。
所有任务 ID 必须各出现一次，位于 completed_task_ids 或 remaining_tasks；完整任务 ID：{TASK_IDS}。actionable 表示仍有可在本工程内实际执行的修改；外部缺资源/工具阻塞写 false。每轮最长 30 分钟，留出保存修改、状态文件、报告和清理自有引擎进程的时间。

---

## 续接 prompt（第 {N} 轮，在同一对话里发送）

继续修复游戏 {GAME_ID}，第 {N}/10 轮，继续本对话。沿用已读的 `{SETTING_OVERVIEW}` 框架与 playtest 路由（上下文缺失时先重读），再读 refine_tasks.json、repair_report.md、repair_status.json 和已有 playtest 证据。先针对未完成项和上轮观察到的问题作最小必要修改，再做真实 playtest 复测受影响流程。保留之前的有效改动；不得重做已验证任务、伪造证据、改需求或只做静态检查。更新 repair_report.md 和 repair_status.json（"round": {N}，规则同首轮）。

---

## 结束

最后一轮后不需要 agent 写 delivery.json，由 `generate.py --finalize` 生成（会校验 Sol 原始工程未被修改）。
