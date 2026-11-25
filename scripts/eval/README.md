# scripts/eval — 评估与生成入口

## 环境要求

- macOS, Python 3.9+
- UE 5.4：`A3GAME_UE_ROOT`（默认 `/Users/Shared/Epic Games/UE_5.4`）
- Unity 2022.3 / 团结引擎：`A3GAME_TUANJIE_BINARY`（自动探测）
- Codex CLI **0.166.0**：`export HOMEBREW_NO_AUTO_UPDATE=1 && brew install codex@0.166.0`

## 环境变量

| 变量 | 说明 | 默认 |
|---|---|---|
| `GF3A_DATA_ROOT` | test_data 根目录 | `<repo>/test_data` |
| `A3GAME_UE_ROOT` | UE 5.4 安装目录 | `/Users/Shared/Epic Games/UE_5.4` |
| `A3GAME_TUANJIE_BINARY` | 团结引擎 binary 路径 | 自动探测 |
| `A3GAME_EXCLUSIVE_ENGINE` | 全局引擎互斥锁（并行时必须设为 1） | 未设置 |
| `A3GAME_GUI_SLOTS` | 允许同时占用的 GUI 录制槽位数 | 1 |
| `A3GAME_PLANNER_MODEL` | 覆盖 planner 模型 | config/models.json |
| `A3GAME_JUDGE_MODEL` | 覆盖 judge 模型 | config/models.json |

## 生成游戏

### Stage 1 — 白膜生成

```bash
# 单条需求
python scripts/eval/generate.py --stage 1 \
  --requirement test_data/test_samples/G001_port_guard_arena/general_requirement_threejs.txt \
  --game-id G001_port_guard_arena --engine three_js --models sol

# jsonl 批量并行（每个任务开一个独立 Codex 会话）
python scripts/eval/generate.py --stage 1 \
  --collect test_data/pipeline_collect.jsonl \
  --models sol,glm --parallel 4 [--games G001-G020] [--engines godot,three_js]
```

输出：`test_data/outputs/initial_game_gen/<模型目录>/<GameID>/<engine>_<时间戳>/`

模型目录映射：`sol→gpt_sol6p1`, `glm→glm_5p3`, `kimi→kimi_k3`, `astra→gpt_astra6`, `opus→claude_ops5p5`

**注意**：`pipeline_collect.jsonl` 里的 `design_doc_path` 字段当前未使用（设计文档已在上游有意移除）。

### Stage 3 — Refine 生成

```bash
# 指定游戏
python scripts/eval/generate.py --stage 3 --games g8,g15 --models sol,glm --parallel 2

# 全部 13 个游戏
python scripts/eval/generate.py --stage 3 --models astra --parallel 3

# 单独指定 refine.json
python scripts/eval/generate.py --stage 3 \
  --refine-json test_data/outputs/playtest/g8/refine.json --models kimi
```

输出：`test_data/outputs/playtest/g<N>/<模型>/`

### 通用选项

| 选项 | 说明 |
|---|---|
| `--dry-run` | 只建目录、写第 1 轮 prompt，不调用代理 |
| `--manual` | 写出所有轮次 prompt 供人工驱动 |
| `--finalize` | 强制结束当前 run |
| `--run-id <id>` | 续跑已有 run |

**并行资源**：`A3GAME_EXCLUSIVE_ENGINE=1` 确保多个会话不同时占一个 GUI 录制槽位。

## 评估

```bash
# 白膜测评
python scripts/eval/evaluate.py --stage 1 --games G001 --models sol \
  --planner gpt-6.1-sol --judge gpt-6.1-sol

# Refine 测评
python scripts/eval/evaluate.py --stage 3 --games G003 --models glm --run-id <run>

# 资产测评
python scripts/eval/evaluate.py --stage assets --games G001 --scope obj
python scripts/eval/evaluate.py --stage assets --scope cg --mode preflight --no-sol
```

## 看进度 / 其他工具

```bash
python scripts/eval/run_status.py --model glm --run-suffix <suffix>
python scripts/eval/rescore.py --games G001 --models sol
python scripts/eval/rejudge_takes.py --games G001 --take 2
python scripts/eval/stage3_scores.py
```

## 评分口径摘要

- **Stage 1 白膜**：mechanic / gamefeel / vfx 二元判定（PASS/FAIL/UNVERIFIED）+ Direct Trigger 50% 规则（触发成功且无 bug → 至少 50%）
- **Stage 3 Refine**：同上三列 + import（资产导入）+ texture（游戏内四视角 vs 原资产）
  - import.scene：游戏内拍摄的 VIEW 显示该场景资产的一部分
  - import.motion：ASSET_EVENT 确认触发时机，MOTION 姿势图确认无形变
  - import.audio / cg_video：ASSET_EVENT 确认触发时机与资产匹配
- **资产测评**：3D object / scene / CG / audio / video 三列独立；未完成为 null，不填 0

## 产物目录结构

```
test_data/outputs/
├── initial_game_gen/
│   └── <模型目录>/
│       └── <GameID>/
│           └── <engine>_<时间戳>/   ← Stage 1 生成产物
│               ├── pipeline/
│               └── delivery.json
└── playtest/
    └── g<N>/
        ├── refine.json
        └── <模型>/                  ← Stage 3 refine 产物
            ├── project/
            ├── repair_status.json
            ├── repair_report.md
            └── delivery.json
```

## 恢复脚本

eval 过程中遇到工具链故障，agent 自己写恢复脚本：见 `pipeline/eval/repair/README.md` 和 `agent_skills/eval_repair/SKILL.md`。

## 旧 refine 批次续跑

`scripts/eval/refine/` 下保留了旧版 refine runner（`refine_game.py` + `batch.py`），读同样的 `playtest/g*/refine.json`，产物写到 `initial_game_gen/gpt_sol6p1/<游戏>/<模型>_refine_<批次>/`。旧结果不移动；新批次用 `generate.py --stage 3`，产物布局不同（见上）。
