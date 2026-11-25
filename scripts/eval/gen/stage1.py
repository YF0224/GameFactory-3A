"""Stage1 whitebox generation: one agent session per (game, model), single round.

Output (run root = ``initial_game_gen/<model dir>/<GameID>/<run_id>/``) uses the
framework's standard layers (``pipeline/``, ``mechanic/``, ``ui/``, ``eval/``); the
agent sees ``AAAGF_OUTPUT_ROOT=initial_game_gen/<model dir>`` like before. The
prompt is the frozen ``prompts/stage1_whitebox.md`` plus the delivery contract
(``delivery.json``) so the result can be evaluated by scripts_new/evaluate.py.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from . import runner
from .jobs import Job, now
from .paths import BENCH, FRAMEWORK, SAMPLES, SETTING_OVERVIEW, model_dir

PROMPT = BENCH / 'prompts' / 'stage1_whitebox.md'
OUTPUT = BENCH / 'test_data' / 'outputs' / 'initial_game_gen'
TIMEOUTS = {'S': 3600, 'M': 5400, 'L': 7200}       # per tier, same as the historical batch runner


def case_info(game_id: str) -> dict:
    text = (SAMPLES / game_id / 'general_requirement.txt').read_text(encoding='utf-8')
    engine = re.search(r'(?m)^engine:\s*(\S+)', text)
    tier = re.search(r'(?m)^tier:\s*([^\s#]+)', text)
    if not engine or not tier:
        raise ValueError(f'{game_id}: general_requirement.txt lacks engine/tier')
    return {'engine': engine[1].strip().lower(), 'tier': tier[1]}


def values(game_id: str, root: Path, engine: str) -> dict:
    task = f'{game_id}_whitebox'
    return {
        'GAME_ID': game_id, 'CASE_ROOT': SAMPLES / game_id, 'FRAMEWORK_ROOT': FRAMEWORK,
        'SETTING_OVERVIEW': SETTING_OVERVIEW, 'GENERAL_REQUIREMENT': SAMPLES / game_id / 'general_requirement.txt',
        'ENGINE': engine, 'RUN_ROOT': root, 'GENERATION_CONTROL_ROOT': root / '.generation',
        'STAGE_WORKSPACE': root / 'pipeline' / task, 'PIPELINE_OUTPUT_ROOT': root / 'pipeline' / task,
        'MECHANIC_OUTPUT_ROOT': root / 'mechanic' / task, 'UI_OUTPUT_ROOT': root / 'ui' / task,
        'EVAL_OUTPUT_ROOT': root / 'eval' / 'whitebox' / task,
    }


def delivery_contract(model: str, game_id: str, run_id: str, engine: str, root: Path) -> str:
    return f'''

## 交付契约（必须）

完成后在 `{root}/delivery.json` 写入（`project_root` 为可运行工程目录、`entry` 为作者真实入口，均为相对路径）：

```json
{{"schema": "bench.delivery.v1", "stage": "stage1", "model": "{model}", "game_id": "{game_id}",
  "run_id": "{run_id}", "engine": "{engine}", "project_root": "<相对 RUN_ROOT 的可运行工程目录>",
  "entry": "<相对 project_root：Godot 主场景 / Unity 场景 / UE 地图或 .uproject / Three.js index.html>",
  "created_at": "<ISO8601>", "generator": {{"kind": "bench_script", "agent": "{model}", "framework_used": true}}}}
```
'''


def render(model: str, game_id: str, run_id: str, root: Path) -> str:
    info = case_info(game_id)
    text = PROMPT.read_text(encoding='utf-8')
    for key, value in values(game_id, root, info['engine']).items():
        text = text.replace('{' + key + '}', str(value))
    return text + delivery_contract(model, game_id, run_id, info['engine'], root)


def prepare_job(model: str, game_id: str, run_id: str | None = None) -> Job:
    run_id = run_id or f'{model}_{datetime.now():%Y%m%d_%H%M%S}'
    root = OUTPUT / model_dir(model) / game_id / run_id
    job = Job.load(root)
    if job:
        return job
    info = case_info(game_id)
    job = Job(stage='stage1', model=model, game_id=game_id, run_id=run_id, run_root=str(root), max_rounds=1,
              notes={'engine': info['engine'], 'tier': info['tier'], 'prepared_at': now()})
    job.save()
    return job


def run_job(job: Job, agent, env: dict, dry_run: bool = False) -> Job:
    tier = job.notes['tier'].split('-')[0]
    env = {**env, 'AAAGF_OUTPUT_ROOT': str(OUTPUT / model_dir(job.model))}
    return runner.run(job, agent, first_prompt=lambda: render(job.model, job.game_id, job.run_id, job.root),
                      next_prompt=lambda n: '', finished=lambda n: True, cwd=FRAMEWORK, env=env,
                      round_timeout=TIMEOUTS.get(tier, TIMEOUTS['S']), dry_run=dry_run)
