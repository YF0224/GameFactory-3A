---
name: eval_repair
description: "Agent 在 eval 链路（plan→record→evidence→judge）中自动诊断 HARNESS_ERROR 和引擎故障，分类处置，写恢复脚本到 pipeline/eval/repair/ 注册后续跑，不改评分语义，不动作者原始交付。"
---

# Eval 自动修复

**触发条件**：eval 链路出现 `HARNESS_ERROR`、工具链报错、引擎启动失败、录制超时、传输截断。

---

## 1. 收到问题时，先分类

读 `status.json → error`，找最早的失败定位根因。

| 现象 | 分类 | 处置 |
|---|---|---|
| `HARNESS_ERROR`、capture slot busy、plan schema 失败、模型超时 | 工具链故障 | → 第 2 节 |
| UE C++ 编译错误、缺插件/模块 | 项目启动故障 | → 第 3 节 |
| Unity `error CS*`、缺包、场景打不开 | 项目启动故障 | → 第 3 节 |
| 游戏崩溃、死亡、低分、玩法错误 | 产品表现 | 不处理，保留原貌出分 |

拿不准时按"工具链故障"处理，不要动作者代码。

---

## 2. 工具链故障：写恢复脚本

### 2.1 新建脚本

在 `pipeline/eval/repair/` 下新建 `<engine>_<场景>_recovery.py`：

```python
from pathlib import Path

DESCRIPTION = "一句话：解决什么问题、适用条件"
ENGINES = ["ue5"]          # ["unity3d"] / ["godot"] / ["three_js"] / ["*"]
ERROR_PATTERNS = ["触发此脚本的错误关键词"]

def apply(out: Path, **kwargs) -> dict:
    """
    执行修复。
    返回 {"ok": bool, "action": str, "detail": str}
    ok=True  → 修复成功，可以重试
    ok=False → 需要人工介入
    """
    ...
```

### 2.2 注册

在 `pipeline/eval/repair/__init__.py` 的 `REGISTRY` 里加一行：

```python
'<key>': ('<module_name>', '<filename.py>'),
```

验证：

```python
from pipeline.eval.repair import describe
print(describe())
```

### 2.3 允许修复的范围

- adapter / 录制工具链：引擎启动、连接、录制插件加载、端口冲突、cleanup
- 传输/请求：分片、截断包装、schema 解析
- 环境/配置：缺依赖、引擎版本 API 改名、编译器开关、`manifest.json` 包版本
- 不改变行为的编译兼容：等价新 API、类型转换、`const`/`override`

### 2.4 禁止修复的范围

- 改任何玩法逻辑、数值、胜负条件、AI、关卡、UI 文本
- 改场景/关卡/预制体/资源文件
- 删/注释作者代码、改成空实现
- 改评分语义、rubric、judge 判定、证据充分性
- 改评估工具 / adapter / 录制插件（`A3GamePlayable`、`GameFactory3A*`）

---

## 3. 项目启动/编译修复

**只在评估副本 `runtime/project` 内工作，原始交付只读。**

### 允许

- `.uproject`、`*.Build.cs`、`Config/*.ini`、Unity `ProjectSettings/`、`Packages/manifest.json`、`*.asmdef`
- 缺 `#include`/`using`、API 改名（等价新 API）、类型转换、`const`/`override`

### 禁止

- 改玩法/数值/AI/关卡/资产；删/注释作者代码；联网下载；碰 `Library/`、`Intermediate/`

修不了时：不做任何改动，记录 `not_repairable` 和原因。

---

## 4. 双客户端（需要两个独立引擎实例）

用 `pipeline/eval/repair/independent_ue_pair.py` 或 `dual_client_unity.py`：

- 两端各用独立项目副本，各自 admission/build/录制
- 用 `pair_slots()` 预占两条录制通道后并发启动
- 两端都 PASS 才算 PASS；任一端工具故障记为未验证，不是产品失败
- 双引擎并发前确认内存/显存够用；不够则串行

---

## 5. 资源检查

每次启动引擎前：

```bash
df -h /
```

- 低于 **20 GiB**：停下汇报，不启动引擎
- 始终保留 **8 GiB**
- 多会话并行：`A3GAME_EXCLUSIVE_ENGINE=1 A3GAME_GUI_SLOTS=1`

---

## 6. 修复后

1. 从上次失败的阶段重新跑，不从头重录已有合格实录
2. 修复后如果问题类型是新的，在 `references/fault-patterns.md` 末尾追加一节

---

## 7. 阻塞时的处理

遇到无法修复的情况：保存根因和最后合格阶段，切换到其他可推进项目，根因清楚后回访。

**不继续强推的情况**：
- 作者交付文件真实缺失
- 修复需要改评分语义或作者玩法
- 需要联网或外部服务但不可用
- 双端项目真实双端未接通

---

## 8. 现有脚本速查

```python
from pipeline.eval.repair import describe
print(describe())
```

33 个脚本，覆盖 Godot/Three.js/Unity/UE5 常见工具链故障。故障模式详见 `references/fault-patterns.md`。
