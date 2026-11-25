# GameFactory-3A Stage 3 — asset import, playtest and repair

你正在执行同一个游戏测例的第三阶段。**开始前必须先阅读 `{SETTING_OVERVIEW}`，并遵循其中的“Validate, play, and iterate”流程。**

## 测例输入

- 游戏测例：`{GAME_ID}`
- 测例目录：`{CASE_ROOT}`
- GameFactory-3A 根目录：`{FRAMEWORK_ROOT}`
- 总入口文档：`{SETTING_OVERVIEW}`
- 目标引擎：`{ENGINE}`
- 第一阶段白模 run/workspace：`{WHITEBOX_RUN_ROOT}` / `{WHITEBOX_WORKSPACE}`
- 第一阶段资产接口：`{ASSET_SLOTS}`
- 第二阶段资产根/manifest：`{ASSET_OUTPUT_ROOT}` / `{ASSET_MANIFEST}`
- 当前集成 pipeline task 目录：`{STAGE_WORKSPACE}`
- runner 控制面：`{GENERATION_CONTROL_ROOT}`
- 本轮 attempt 控制目录（prompt/log/attempt_result）：`{REPAIR_ATTEMPT_ROOT}`
- 当前 pipeline 工程目录：`{PIPELINE_OUTPUT_ROOT}`
- 当前 eval 证据目录：`{EVAL_OUTPUT_ROOT}`
- 当前 repair attempt：`{REPAIR_ATTEMPT}`
- 最大 repair 次数：`{MAX_REPAIR_ATTEMPTS}`
- 上一轮验证报告：`{PREVIOUS_REPORT}`
- 上一轮错误日志：`{PREVIOUS_LOG}`

## 本轮任务

如果当前是 attempt 00：

1. 按 asset ID、槽位和 contract 将第二阶段资产导入白模；
2. 检查比例、朝向、挂点、碰撞、动画、音频、视频、VFX 触发和 UI 绑定；
3. 构建、启动、执行主要玩家操作和完整核心流程；
4. 录制并检查运行过程，不要只看源代码或一张截图。

如果当前是 repair attempt：

1. 先阅读上一轮验证证据；
2. 定位真实问题所属层：资产、导入元数据、机制、UI、场景、灯光、VFX 或配置；
3. 进行最小、可追踪的修复；
4. 修复后重新构建、启动、playtest 和 review；
5. 输出本轮变更、验证结果和仍存在的问题。

## 允许和禁止

允许修复资产导入路径、场景引用、节点绑定、材质/贴图引用、动画控制器、音频/视频/VFX 绑定、由导入造成的兼容代码和阻止运行的配置问题。

禁止修改需求、评分结果、核心游戏目标；禁止重新生成第二阶段资产；禁止通过删除核心玩法或跳过验证来伪造成功。

本轮结束后由外部脚本判断是否通过。你不能自行宣布 benchmark 成功。

## 轮次约束

- `attempt_00` 是首次导入和验证，不计为 repair；
- `attempt_01` 到 `attempt_{MAX_REPAIR_ATTEMPTS}` 最多 `{MAX_REPAIR_ATTEMPTS}` 轮 repair；
- 每轮必须保存独立报告、日志、diff 和验证证据；
- 每轮必须在 `{REPAIR_ATTEMPT_ROOT}/validation_summary.json` 写入机器可读结果，至少包含 `status`（`PASS`、`FAIL` 或 `UNKNOWN`）、构建结果、playtest 结果、变更摘要和证据路径；
- 不得覆盖 attempt 00 或任何已经保存的历史证据。

输出位置：当前集成工程写入 `{PIPELINE_OUTPUT_ROOT}`（标准 `pipeline/<task_id>/`），机制/UI 产物分别写入 `{MECHANIC_OUTPUT_ROOT}` / `{UI_OUTPUT_ROOT}`，验证和评测证据写入 `{EVAL_OUTPUT_ROOT}`。本轮 prompt、日志、attempt 结果和 repair bookkeeping 只写入 `{REPAIR_ATTEMPT_ROOT}`。不要创建 `pipeline/import_repair/`，也不要修改任何 parent run 的原始白模或资产任务输入。
