---
name: eval-repair
description: "Eval 完整链路闭环与自修复：agent 启动任意引擎（Unity/UE5/Godot/Three.js）执行 plan→record→evidence→judge，遇到 HARNESS_ERROR 或引擎问题时分类诊断、自己写恢复脚本注册到 REGISTRY 并重试，区分工具链故障与作者交付问题，保留证据不改评分语义。"
---

# Eval 完整链路闭环与自修复

适用于所有引擎（Unity / UE5 / Godot / Three.js）的 whitebox 白膜测评和 refinement 阶段测评。  
目标：**每个游戏都走完 plan → record → evidence → judge → score**，遇到工具链问题自己修复并续跑，不改评分语义，不动作者原始交付。

---

## 1. 链路顺序与硬要求

```
能读作者源码并打开入口 → 解决到可执行 plan
有可执行 plan           → 真实原生 record
有合格 record           → evidence + judge
有完整有效判词          → 计算分数 + 立即持久化
```

每一步是工程任务，不是可选步骤：
- **plan 不完整、失败、死亡、未通关、低分** 都不阻断录制，保留原貌出分
- **工具链故障** 须修复并回访，不以 `HARNESS_ERROR`、排队、监护当最终交付
- **缺交付、入口打不开、真实双端未接通** 才按证据单列阻塞，继续其他可推进项

---

## 2. 故障分类：先判断谁的问题

读 `status.json` → `error`、`takes/<k>/record/record_error.json`，以及引擎日志：
- UE：`takes/<k>/record/native/take/unreal.log`、`runtime/ue_admission*/build.json`
- Unity：`takes/<k>/record/import.log`、`import_result.json`

| 类别 | 典型症状 | 处置 |
|---|---|---|
| **工具链故障** | `HARNESS_ERROR`、capture slot busy、plan schema 解析失败、模型超时、GUI slot busy | 按第 3 节修复 |
| **项目启动/编译失败** | UE C++ 编译错误、缺插件/模块；Unity `error CS*`、缺包、入口场景打不开 | 按第 4 节修复 |
| **产品表现** | 游戏崩溃、死亡、卡关、画面不对、低分 | 不是故障，保留原貌出分 |

拿不准时按"工具链故障"记录，不要动手修。

---

## 3. 工具链故障：写恢复脚本到 `pipeline/eval/repair/`

### 诊断流程

1. 从最早的失败定位根因（编译器第一条 error、第一条 missing module、capture slot 冲突等）
2. 判断是否属于"允许修复"范围（见下）
3. 做最小改动，每处只修一个错误

### 允许修复的范围

- **adapter / 录制工具链**：引擎启动、连接、录制插件加载、端口冲突、cleanup
- **传输/请求**：HTTP 413 分片、output 截断、schema 解析错误、无损包装
- **环境/配置**：缺 `#include`/`using`、引擎版本 API 改名、编译器开关、`manifest.json` 包版本
- **不改变行为的编译兼容**：等价新 API、显式类型转换、`const`/`override`、未初始化声明

### 禁止修复的范围

- 改任何玩法逻辑、数值、胜负条件、AI、关卡流程、UI 文本/行为
- 改场景/关卡/预制体/资源文件（`.unity`、`.umap`、`.uasset`、材质、音频等）
- 删除或注释掉作者代码、改成空实现、`#if 0`
- 改评估工具 / adapter / 录制插件（`A3GamePlayable`、`GameFactory3A*`）
- 改评分语义、rubric、judge 判定、证据充分性、HARNESS_ERROR 分类

### 写恢复脚本

在 `pipeline/eval/repair/` 下新建 `<engine>_<场景>_recovery.py`：

```python
from pathlib import Path

DESCRIPTION = "一句话：解决什么问题、适用条件"
ENGINES = ["ue5"]          # ["unity3d"] / ["godot"] / ["three_js"] / ["*"]
ERROR_PATTERNS = ["关键词"]  # 触发此脚本的错误字符串

def apply(out: Path, **kwargs) -> dict:
    """
    执行修复。
    返回 {"ok": bool, "action": str, "detail": str}
    ok=True  → 修复成功可重试
    ok=False → 需要人工介入
    """
    ...
```

在 `pipeline/eval/repair/__init__.py` 的 `REGISTRY` 里加一行后验证：

```python
from pipeline.eval.repair import describe
print(describe())   # 确认注册成功
```

---

## 4. 项目启动/编译修复（评估副本内）

在 **评估副本**（`runtime/project`）里工作，原始交付只读。

**允许：**
1. 工程/环境配置：`.uproject`、`*.Build.cs`、`Config/*.ini`、Unity `ProjectSettings/`、`Packages/manifest.json`、`*.asmdef`
2. 不改变行为的编译兼容：缺 `#include`/`using`、API 改名（等价新 API）、类型转换、`const`/`override`
3. 只为修上面问题而新增的空壳文件（引擎模板内容）

**禁止：**
- 改玩法、数值、AI、关卡、资产、UI 文本
- 删/注释作者代码、改成空实现
- 联网下载、安装第三方包
- 碰评估工具、`Library/`、`Intermediate/`、工作目录外的任何东西

修复后回复包含：`root_cause`、`changes`（文件、类型、为何不改变行为）、`not_fixed`（剩余问题）。没有安全可修的问题时返回 `not_repairable`，不做任何改动。

---

## 5. 双客户端（需要两个独立引擎实例）

用 `pipeline/eval/repair/independent_ue_pair.py` 或 `dual_client_unity.py`：

- 两个客户端各用一份独立项目副本（各自 admission、build、录制插件）
- 用 `pair_slots()` 预占两条录制通道后并发启动
- 聚合时两端都 PASS 才算 PASS；任一端工具故障记为未验证，不是产品失败
- 双引擎并发前确认内存/显存够用（UE 每实例数 GB）；不够就串行
- 结束后逐端真实 cleanup，各端 request/response/frames 都保留

---

## 6. 资源约束

- 每次启动引擎前：`df -h /`，低于 **20 GiB** 停下汇报，始终保留 **8 GiB**
- 多个会话并行时：`A3GAME_EXCLUSIVE_ENGINE=1 A3GAME_GUI_SLOTS=1`，不让两个会话同时占一个 GUI 录制槽位
- 录完立即 cleanup 本任务本例自有进程及已核归属后代；`report_only`、父进程消失不等于 cleanup 完成

---

## 7. 阻塞时的处理

遇到无法修复的情况：
- 保存根因、最后合格阶段、下一工程动作和恢复条件
- 切换到其他可推进的游戏/项目
- 实质修复后回访；约 10 分钟排错时间片不是永久放弃

以下情况保留阻塞状态，不继续强推：
- 作者交付文件真实缺失
- 需要联网或外部服务但不可用
- 双端项目真实双端未接通
- 修复需要改评分语义

---

## 8. 现有恢复脚本速查

```python
from pipeline.eval.repair import describe
print(describe())
```

覆盖范围：Godot 时长/音频/窗口恢复、Three.js 插件、UE 编译兼容/目标恢复/capture 续跑、Unity 音频/IMGUI/builder/输入恢复、双客户端 Unity/UE、通用 launch repair（33 个脚本）。
