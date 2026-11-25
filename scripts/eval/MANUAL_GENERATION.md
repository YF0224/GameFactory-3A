# 手动生成操作说明

自动生成（`generate.py` 直接驱动 codex / claude / zcode / kimi CLI）跑不起来时，用本流程：由人在任意 agent（Kimi 应用、ZCode 应用、Cursor、Claude Code 等）里对话生成，最后用一条命令收尾。产物位置、交付格式与自动生成完全一致，评估照常用 `evaluate.py`。

**一条规则贯穿始终：一个（游戏 × 模型）= 一个新对话；这个对话只做这一个项目。** 不要在一个对话里做多个游戏，也不要中途换对话（换对话等于丢掉上下文；确实必须换时在 repair_report.md 里写明）。

---

## Stage 1：白模生成（单轮）

1. 准备并生成 prompt（不会调用任何 agent）：
   ```bash
   python scripts_new/generate.py --stage 1 --models kimi --games G008 --manual
   ```
   输出一行 `MANUAL kimi G008_dock_beacon_cs <run_id>: prompts in <路径>`。记下 `<run_id>`。
2. 在 agent 里**新开一个对话**，工作目录设为 `GameFactory-3A/`，把 `<run>/.generation/manual/round_01_prompt.md` 的全部内容发过去。
   - 运行环境：`AAAGF_OUTPUT_ROOT=test_data/outputs/initial_game_gen/<模型目录>`（模型目录见 `config/models.json`）。
   - 时间上限按档位：S 1 小时、M 1.5 小时、L 2 小时。Stage 1 不做修复轮，不要追加“继续”。
3. agent 结束后，确认它写了 `<run>/delivery.json`（prompt 末尾有格式），然后收尾：
   ```bash
   python scripts_new/generate.py --stage 1 --models kimi --games G008 --run-id <run_id> --finalize
   ```
   这一步只校验 delivery.json 是否合格（引擎与题目一致、入口文件存在）；不合格会列出问题。

外部人员不使用本仓库脚本时，用 `prompts/stage1_whitebox_public.md` 手工填写占位符即可。

---

## Stage 3：Refine（同一对话最多 10 轮）

1. 准备并生成各轮 prompt：
   ```bash
   python scripts_new/generate.py --stage 3 --models kimi --games G008 --manual
   ```
   这一步会：
   - 把 Sol 原始工程复制到 `test_data/outputs/game_refine/<模型目录>/<题>/<run_id>/project/`（原件只读，复制前后校验）；
   - 写出本题的 `refine_tasks.json`（只含本题任务）；
   - 在 `<run>/.generation/manual/` 写好 `round_01_prompt.md` … `round_10_prompt.md`（已填好路径和任务 ID）。
2. 在 agent 里**新开一个对话**，工作目录设为 `<run>/`（即包含 `project/` 和 `refine_tasks.json` 的目录），发送 `round_01_prompt.md`。
3. 每轮结束后看 `<run>/repair_status.json`：
   - `remaining_tasks` 里还有 `"actionable": true` 的任务 → 在**同一个对话**里发送下一轮的 `round_NN_prompt.md`；
   - 没有可做的剩余任务，或已到第 10 轮 → 结束。
   - 每轮最多 30 分钟；超时或中断的一轮也算一轮。
4. 收尾（`--rounds` 填实际用掉的轮数）：
   ```bash
   python scripts_new/generate.py --stage 3 --models kimi --games G008 --run-id <run_id> --finalize --rounds 4
   ```
   会再次校验 Sol 原始工程未被修改，然后写 stage3 的 `delivery.json`。

外部人员不使用本仓库脚本时，用 `prompts/stage3_refine_public.md`（首轮 + 续接模板）手工填写。

---

## 收尾之后

```bash
python scripts_new/intake.py   --stage 3 --models kimi --games G008      # 检查交付
python scripts_new/evaluate.py --stage 3 --models kimi --games G008 --run-id <run_id>
```

## 注意

- 不要修改 `test_data/outputs/initial_game_gen/gpt_sol6p1/` 下的 Sol 原始工程；`--finalize` 发现原件变化会拒绝收尾。
- 不要在 agent 里调用最终评估或 judge；评估只由 `evaluate.py` 执行。
- 每个 job 复制一份完整引擎工程，开始前留够磁盘（至少 8GiB 余量）。
- 手动 job 不会被自动生成重复启动（状态为 `manual`，只能用 `--finalize` 收尾）。
