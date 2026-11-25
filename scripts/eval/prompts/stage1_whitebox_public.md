# GameFactory-3A Stage 1 — 白模游戏生成（对外公开版 prompt）

> 使用方式：把下面 `{...}` 占位符替换成实际值后，交给你自己的 coding agent。
> 必须同时提供 GameFactory-3A 框架（方案 A：框架 + prompt），结果才与基准可比。
> 交付后用 `python scripts_new/intake.py --run-dir <RUN_ROOT>` 自检。

| 占位符 | 含义 | 示例 |
|---|---|---|
| `{GAME_ID}` | 测例 ID | `G008_dock_beacon_cs` |
| `{CASE_ROOT}` | 测例目录 | `test_data/test_samples/G008_dock_beacon_cs` |
| `{FRAMEWORK_ROOT}` | GameFactory-3A 根目录 | `GameFactory-3A` |
| `{ENGINE}` | 目标引擎，须与 `general_requirement.txt` 的 `engine` 一致 | `ue5` |
| `{MODEL}` | 生成模型短名：`sol / astra / opus / glm / kimi` 或你自己的名字 | `kimi` |
| `{RUN_ID}` | 本次运行 ID，等于输出目录名 | `kimi_20261107_120000` |
| `{RUN_ROOT}` | 输出目录 = `test_data/outputs/initial_game_gen/<模型目录>/{GAME_ID}/{RUN_ID}` | |

---

你正在执行一个 GameFactory-3A 游戏生成测例。**开始任何规划、代码或资产生成前，必须先完整阅读 `{FRAMEWORK_ROOT}/agent_skills/setting_overview.md`。**它是本项目的总入口和流程规范；必须按它路由到 game_design、engine context、code generation 和 playtest/validation Skills。

## 测例输入

- 游戏测例：`{GAME_ID}`，测例目录：`{CASE_ROOT}`
- 目标引擎：`{ENGINE}`
- 输出目录（本次 run 根目录）：`{RUN_ROOT}`

请读取测例目录下的 `general_requirement.txt`、`requirement.txt`、任务 JSONL 和参考图片，以及目标引擎文档。不要只根据测例标题猜测游戏。

## 本阶段任务

只生成大模型直出的白模游戏，必须实际写入工程，而不是只返回设计说明：

1. 按 `setting_overview.md` 的规划流程拆解需求：故事、流程、核心循环、玩家输入、状态、胜负条件、UI、场景和资产依赖；
2. 建立依赖感知的 TODO 并保存任务计划；
3. 用 primitive、简单材质、占位反馈和代码生成可运行的白模游戏；有参考图时必须实际查看，白模尽量贴合主体类型、轮廓、比例、主配色、标志部件和空间关系；
4. 生成 UI、场景、机制和必要的 playtest 入口；
5. 为后续真实资产保留稳定的 asset ID、节点/Prefab/Actor 槽位、挂点、动画/音频/VFX 事件接口；
6. 构建、启动、执行主要玩家操作和核心循环验证，记录证据。

## 限制

- 不调用 3D、Motion、Audio、Video/CG 或 VFX 生成模型，不导入真实资产；
- 参考图只作外观参考，不得贴在平面上冒充三维对象，不得改变需求中冻结的玩法、碰撞尺寸和数值；
- “写出了代码”不等于可玩，必须构建、启动并执行代表性操作；
- 不做额外 repair 轮次；不修改测例输入目录和 GameFactory-3A 源码。

## 输出位置

所有产物只写入 `{RUN_ROOT}`，按框架标准 Layer：`mechanic/`、`ui/`、`pipeline/`、`eval/`。至少包含：
`generation_plan.md`、`asset_slots.json`、`placeholder_registry.json`、`scene_manifest.json`、`mechanic_contract.json`、`ui_contract.json`、`generation_report.json`、`validation/`。

## 交付契约（必须）

完成后在 `{RUN_ROOT}/delivery.json` 写入：

```json
{
  "schema": "bench.delivery.v1",
  "stage": "stage1",
  "model": "{MODEL}",
  "game_id": "{GAME_ID}",
  "run_id": "{RUN_ID}",
  "engine": "{ENGINE}",
  "project_root": "<可运行工程目录，相对 RUN_ROOT>",
  "entry": "<真实入口，相对 project_root：Godot 主场景 / Unity 场景 / UE 地图 / Three.js index.html>",
  "created_at": "<ISO8601 时间>",
  "generator": {"kind": "external_agent", "agent": "<你的 agent 名称与版本>", "framework_used": true}
}
```

没有 `delivery.json` 或字段不合格的交付不会进入评估。
