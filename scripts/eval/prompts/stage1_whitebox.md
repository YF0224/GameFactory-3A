# GameFactory-3A Stage 1 — direct whitebox game generation

你正在执行一个 GameFactory-3A 游戏生成测例。**开始任何规划、代码或资产生成前，必须先完整阅读 `{SETTING_OVERVIEW}`。**它是本项目的总入口和流程规范；必须按它路由到 game_design、engine context、code generation 和 playtest/validation Skills。

## 测例输入

- 游戏测例：`{GAME_ID}`
- 测例目录：`{CASE_ROOT}`
- GameFactory-3A 根目录：`{FRAMEWORK_ROOT}`
- 总入口文档：`{SETTING_OVERVIEW}`
- 游戏需求：`{GENERAL_REQUIREMENT}`
- 目标引擎（必须和 general_requirement.txt 的 engine 字段核对）：`{ENGINE}`
- 本次 run 根目录：`{RUN_ROOT}`
- runner 控制面（prompt/packet/log/attempt bookkeeping）：`{GENERATION_CONTROL_ROOT}`
- 白模工程 task 目录（Layer B/C 和 pipeline 白模产物写入这里）：`{STAGE_WORKSPACE}`
- Layer B mechanic 目录：`{MECHANIC_OUTPUT_ROOT}`
- Layer C UI 目录：`{UI_OUTPUT_ROOT}`
- Layer pipeline 目录：`{PIPELINE_OUTPUT_ROOT}`
- Layer eval 目录：`{EVAL_OUTPUT_ROOT}`

请读取测例目录下相关的 `requirement.txt`、任务 JSONL、参考图片以及目标引擎文档。不要只根据测例标题猜测游戏。

## 本阶段任务

这是第一阶段：**只生成大模型直出的白模游戏**。必须完成以下工作并实际写入工程，而不是只返回设计说明：

1. 按 `setting_overview.md` 的规划流程拆解需求：故事、章节/流程、核心循环、玩家输入、状态、胜负条件、UI、场景和资产依赖；
2. 建立依赖感知的 TODO，并保存任务计划；
3. 使用 primitive、简单材质、占位反馈和代码生成一个可运行的白模游戏；如果测例提供 image 输入或绑定参考图片，必须实际查看图片，白模应尽量贴合对应对象的外观，包括主体类型、轮廓、比例、主配色、标志部件及场景空间关系，不得仅用无差别方块替代；允许简化纹理与细节，但应保留参考图中可辨识的关键特征；
4. 生成 UI、场景、机制和必要的 playtest 入口；
5. 为所有后续真实资产保留稳定的 asset ID、节点/Prefab/Actor 槽位、挂点、动画/音频/VFX 事件接口；
6. 构建、启动、执行主要玩家操作和核心循环验证，记录证据；
7. 按 `setting_overview.md` 的 Validate, play, and iterate 要求检查运行结果。

## 白模阶段的限制

- 不调用 3D、Motion、Audio、Video/CG 或 VFX 生成模型；
- 不导入第二阶段真实资产；
- 可以使用代码、primitive、基础材质和占位反馈完成玩法；有 image 输入时，“白模”不意味着可以忽略参考外观，必须通过组合几何体、比例调整、基础配色等尽量贴合图片；
- 输入图片仅作为外观参考，不等同于导入第二阶段真实资产；不得把图片贴在平面上冒充可交互的三维对象，不要求像素级复刻，图片也不得改变需求中冻结的玩法、碰撞尺寸和数值；

- 不把“写出了代码”当成可玩；必须构建、启动和执行代表性操作；
- 本次直出阶段不执行 Agent repair，`max_repair_attempts = 0`。

## 输出位置和 Layer 规则

白模工程、设计契约、计划、白模说明和验证证据写入：`{STAGE_WORKSPACE}`。这里本身就是 README 定义的 `pipeline/<task_id>/` artifact 目录，不是自定义的 `pipeline/whitebox/` stage 目录。runner 的 prompt、packet、日志等控制文件只写入 `{GENERATION_CONTROL_ROOT}`。可运行工程和实际游戏产物必须写入标准 Layer：

- Layer B 机制工程：`{MECHANIC_OUTPUT_ROOT}`（即 `mechanic/<task_id>/`）；
- Layer C UI 工程/截图：`{UI_OUTPUT_ROOT}`（即 `ui/<task_id>/`）；
- 端到端白模工程：`{PIPELINE_OUTPUT_ROOT}`（即 `pipeline/<task_id>/`）；
- 评测证据：`{EVAL_OUTPUT_ROOT}`（即 `eval/<task_kind>/<task_id>/`）。

请优先使用 `pipeline.common.paths.task_output_dir()` / `eval_output_dir()`，不要手工创建第二套输出根目录。`{RUN_ROOT}` 是本次 run 的根目录，禁止写入 case 输入目录或修改 GameFactory-3A 源码。

至少生成或维护：

- `generation_plan.md`：需求、流程、任务拆解和 TODO；
- `asset_slots.json`：稳定资产槽位和替换接口；
- `placeholder_registry.json`：白模对象到 asset ID 的映射；
- `scene_manifest.json`：场景、节点、挂点和事件；
- `mechanic_contract.json`：输入、状态、事件、胜负和重开；
- `ui_contract.json`：页面、HUD、提示和结算；
- `generation_report.json`：完成项、风险、构建和 playtest 结果；
- `validation/`：build、launch、smoke/playtest 和 review 证据。

完成后不要只在回复中说明结果，必须把文件写入上述 canonical task 目录和标准 Layer。不要创建 `pipeline/whitebox/`、`pipeline/assets/` 或 `pipeline/import_repair/`。
