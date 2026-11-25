# pipeline/eval/repair — 评估恢复脚本

这个目录存放两类脚本：

1. **现有恢复脚本**（27个）：覆盖 Godot、Three.js、Unity、UE5 常见工具链故障
2. **Agent 在 eval 过程中自己写的新脚本**：遇到 `HARNESS_ERROR` 或工具链故障时，agent 诊断根因后写入此目录，注册到 REGISTRY，下次同类故障自动复用

## 新建恢复脚本规范

**文件名**：`<engine>_<场景简述>_recovery.py`
例：`ue5_missing_plugin_recovery.py`、`unity_shader_compile_recovery.py`

**注册**：写好后在 `__init__.py` 的 `REGISTRY` dict 里加一行：
```python
'ue5_missing_plugin': ('ue5_missing_plugin_recovery', 'ue5_missing_plugin_recovery.py'),
```

**每个脚本必须导出**：

```python
DESCRIPTION: str          # 一句话：解决什么问题、适用条件
ENGINES: list[str]        # ["ue5"] / ["unity3d"] / ["godot"] / ["three_js"] / ["*"]
ERROR_PATTERNS: list[str] # 触发该脚本的错误关键词，用于自动匹配

def apply(out: Path, **kwargs) -> dict:
    """执行修复。
    返回 {"ok": bool, "action": str, "detail": str}
    ok=True 表示修复成功可以重试；ok=False 表示需要人工介入。
    """
    ...
```

**硬性约束**：
- 只修工具链（启动、编译、adapter、录制、传输、cleanup）
- 不改 rubric、judge 语义、分数计算、证据充分性判断
- 不改作者原始源码或资产
- 保存根因、修改文件、前后 SHA

## 双客户端脚本

`dual_client*.py` 和 `independent_ue_pair.py` 也在这里，用于需要两个独立客户端同时运行的测评场景。
使用方式见 `agent_skills/eval_repair/SKILL.md`。

## REGISTRY 查询

```python
from pipeline.eval.repair import modules, describe
print(describe())   # 列出所有脚本和说明
```
