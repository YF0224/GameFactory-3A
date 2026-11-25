---
name: eval-repair
description: "在 eval 过程中遇到 HARNESS_ERROR 或工具链故障时，诊断根因、自己写恢复脚本、注册到 REGISTRY 并重试。适用于所有引擎（Unity、UE5、Godot、Three.js）的 stage1/stage3 录制、编译、adapter、传输类故障；不用于改评分语义。"
---

# Eval 过程中的自修复流程

## 什么时候用这个 skill

- eval 跑出 `HARNESS_ERROR`（工具链失败，非产品 bug）
- 编译失败、adapter 启动失败、录制超时、传输截断
- 双客户端需要两个独立引擎实例同时运行

**不适用**：评分语义问题（rubric / judge 判定 / 分数计算）、作者原始代码 bug。

---

## 修复流程

### 1. 诊断根因

从最早的失败定位最小故障点：
- 读 `record/native/` 下的引擎日志、cleanup 回执
- 检查 `evidence/` 和 `model_calls/` 下的请求/响应
- 确认失败属于哪一类（见下）

**故障分类**：

| 类型 | 描述 | 处置 |
|---|---|---|
| `compile_compat` | 编译/包版本不兼容 | 写 `ue_compile_compat.py` / `unity_editor_compile_compatibility.py` 类型脚本 |
| `adapter_start` | 引擎启动/连接失败 | 检查端口、plugin 是否加载、binary 路径 |
| `record_timeout` | 录制超时 | 检查 `UE_LATE_TOLERANCE_MS`，写 recovery 脚本延长等待 |
| `transport` | 请求/响应传输截断 | 分片、无损包装，保存原文和 SHA |
| `missing_file` | 依赖文件缺失 | 只补可再生成的文件，不动作者原始资产 |

### 2. 写恢复脚本

在 `pipeline/eval/repair/` 下新建文件，命名为 `<engine>_<场景>_recovery.py`。

**必须包含**：

```python
from pathlib import Path

DESCRIPTION = "一句话说明：解决什么问题、适用条件"
ENGINES = ["ue5"]          # or ["unity3d"] / ["godot"] / ["three_js"] / ["*"]
ERROR_PATTERNS = ["关键词"]  # 触发此脚本的错误字符串

def apply(out: Path, **kwargs) -> dict:
    """
    执行修复。
    返回 {"ok": bool, "action": str, "detail": str}
    ok=True 表示修复成功可以重试
    ok=False 表示需要人工介入
    """
    ...
```

**硬性约束**（违反则不写此脚本，报告为需要人工处理）：
- 只改工具链，不改 rubric / judge / 分数计算 / 证据充分性
- 不改作者原始源码或资产（只读）
- 保存根因、修改文件路径、前后 SHA

### 3. 注册到 REGISTRY

在 `pipeline/eval/repair/__init__.py` 的 `REGISTRY` dict 里追加：

```python
'<key>': ('<module_name>', '<filename.py>'),
```

### 4. 验证并重试

```python
from pipeline.eval.repair import modules, describe
print(describe())   # 确认注册成功
```

然后从上次失败的阶段重新跑，不要从头重录已有合格实录。

---

## 双客户端（需要两个独立引擎实例）

用 `pipeline/eval/repair/independent_ue_pair.py` 或 `dual_client_unity.py`：

- 两个客户端各用一份独立项目副本（各自 admission、各自 build、各自录制插件）
- 用 `pair_slots()` 预占两条录制通道后并发启动
- 聚合时两端都 PASS 才算 PASS；任何一端工具故障记为未验证，不是产品失败
- 结束后逐端真实 cleanup，各端 request/response/frames 都保留

**资源检查**：双引擎并发前确认内存/显存够用（UE 每实例数 GB）；不够就串行。

---

## 现有脚本速查

```python
from pipeline.eval.repair import describe
print(describe())
```

覆盖范围：Godot 时长/音频/窗口恢复、Three.js 插件、UE 编译兼容/目标恢复、
Unity 音频/IMGUI/builder/输入恢复、双客户端 Unity/UE、通用 launch repair。

---

## 不能修的情况

遇到以下情况停止写脚本，记录为阻塞并上报：
- 作者交付文件真实缺失（不是工具链问题）
- 需要联网或外部服务但不可用
- 双端项目真实双端未接通
- 修复需要改评分语义
