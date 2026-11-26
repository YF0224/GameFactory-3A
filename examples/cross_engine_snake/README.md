# Four Snake projects evaluated through Stage1

The game projects are here:

| Engine | Project entry | Game code |
| --- | --- | --- |
| Three.js | `threejs/index.html` | `threejs/game.js` |
| Unity | `unity/Assets/Snake.unity` | `unity/Assets/SnakeGame.cs` |
| Unreal Engine 5.4 | `ue/SnakeDemo.uproject` | `ue/Source/SnakeDemo/SnakeGame.cpp` |
| Godot | `godot/project.godot` | `godot/snake.gd` |

Each implements movement, food, growth, wall and self collisions, victory,
restart and pause. Arrow keys/WASD steer, R restarts, Space pauses. The authored
projects, requirements and rubrics are synthetic integration fixtures.
They are not original deliveries by any benchmark model.

## Use the existing evaluation entry

From the repository root, install `requirements.txt` and the engines you want to
evaluate. Native Stage1 recording also requires the dependencies and acceptance
receipts checked by each existing adapter. Three.js also needs Node/npm and the
browser dependencies used by its existing adapter. The model steps require
working model access; this command is not an offline evaluation.

Install packages with the same Python that will launch evaluation:

```bash
python3 -m pip install -r requirements.txt
```

The native runtime uses NumPy for frame checks and PyYAML for Unity input
settings, in addition to Requests and Pillow. The evaluator checks these imports
before model calls. If several Python installations are present, use the same
virtual environment for installation and evaluation.

Prepare four ordinary `bench.delivery.v1` inputs and ordinary Stage1 case data:

```bash
python3 examples/cross_engine_snake/evaluate_stage1.py --prepare-only
```

This creates `DEMO_snake_*` case inputs under the standard `test_data/test_samples`,
`GameFactory-3A/eval/rubric_design/contract_history`, and
`test_data/bench_standards/stage1/stage1-criteria.v1` locations. Their source data
remain in `stage1_case/cases/`. Existing different inputs are refused, not
replaced. No Snake module or suite is registered in `pipeline/eval/stage1`.

Read [the standard review](stage1_case/REVIEW.md) before using the normal approval
command. The preparation script does **not** approve its own drafts or invent a
human reviewer. The actual reviewer can freeze exactly those files with the existing tool:

```bash
for engine in three_js unity3d ue5 godot; do
  python3 scripts_new/freeze_standards.py --stage 1 \
    --approve "DEMO_snake_${engine}" --reviewer "<actual reviewer and delegated authority, if applicable>"
done
```

In this workspace the user explicitly delegated rubric definition and approval
to Codex on 2026-11-23; the existing drafts were reviewed and approved through
that command. This does not waive review for a fresh checkout.

After this one-time review, run all four directly through the existing evaluator:

```bash
A3GAME_CODEX_INLINE_SCHEMA=1 python3 scripts_new/evaluate.py --stage 1 \
  --run-dir \
    examples/cross_engine_snake/out-stage1-standard/deliveries/sol/DEMO_snake_three_js/authored_v1 \
    examples/cross_engine_snake/out-stage1-standard/deliveries/sol/DEMO_snake_unity3d/authored_v2 \
    examples/cross_engine_snake/out-stage1-standard/deliveries/sol/DEMO_snake_ue5/authored_v1 \
    examples/cross_engine_snake/out-stage1-standard/deliveries/sol/DEMO_snake_godot/authored_v1 \
  --planner gpt-6.1-sol --judge gpt-6.1-sol
```

The completed runs on 2026-11-23 produced these CLI lines (collected from the
initial run and its preserved recovery logs):

```text
DONE sol DEMO_snake_three_js total=92.86 complete=True
DONE sol DEMO_snake_unity3d total=83.57 complete=True
DONE sol DEMO_snake_ue5 total=89.29 complete=True
DONE sol DEMO_snake_godot total=85.71 complete=True
```

A successful fresh run should end with `complete=True` for every case; model
judgments can change the exact scores. See [VERIFICATION.md](VERIFICATION.md) for
recording counts, deductions and the pending audit status.

`A3GAME_CODEX_INLINE_SCHEMA=1` uses the existing full-schema text transport and
strict local validator. The first Three.js and Godot structured-output planner
requests failed with `max_output_tokens`; both failed invocations are retained. Unity uses
`authored_v2` because the initial example omitted editor-generated PlayerSettings
and InputManager files. Its original delivery and failure remain in `authored_v1`.

Alternatively, `A3GAME_CODEX_INLINE_SCHEMA=1 python3 examples/cross_engine_snake/evaluate_stage1.py`
prepares the current revisions and invokes the same evaluator. The helper only prepares data and starts
**`scripts_new/evaluate.py --stage 1 --run-dir ...`** as a subprocess. Planning, native recording, evidence assembly,
judging and scoring all run in the existing Stage1 pipeline. Both model defaults
come from the central evaluation configuration, and `--planner`/`--judge` can
select an explicitly authorized model. No offline judge is substituted.

To invoke that same entry directly for one prepared delivery, for example:

```bash
python3 scripts_new/evaluate.py --stage 1 \
  --run-dir examples/cross_engine_snake/out-stage1-standard/deliveries/sol/DEMO_snake_three_js/authored_v1 \
  --planner gpt-6.1-sol --judge gpt-6.1-sol
```

Use `--engines threejs`, `--engines unity`, `--engines ue` or `--engines godot`
on the helper to select projects. `--list` calls the real CLI's list mode;
`--static-only` runs only the source judge, and does not mean runtime completion.
`--out` selects the helper's delivery directory. Stage1 evaluation outputs use
the CLI's existing layout:

```text
test_data/outputs/eval/whitebox/stage1_v1__judge-<judge>/gpt_sol6p1/DEMO_snake_<engine>/<run-id>/
```

To resume a run after fixing a missing dependency or an interrupted host, keep
its existing `--run-id`. For example, resume only Godot with:

```bash
A3GAME_CODEX_INLINE_SCHEMA=1 python3 examples/cross_engine_snake/evaluate_stage1.py \
  --engines godot --run-id rerun_20261123_01 \
  --planner gpt-6.1-sol --judge gpt-6.1-sol
```

Use the Python environment where you installed `requirements.txt`. A completed
native Godot keyboard/wait take can finish postprocessing automatically when the
recorder's completion marker, original source and plan, all frames, input cleanup
and current process absence pass validation. Native evidence is preserved and
sampling gaps remain in the recovery receipt. An incomplete or conflicting take
still stops for inspection; do not delete its `native` directory to force a retry.
A new `--run-id` creates an independent run instead of resuming the existing one.

The current run IDs are `authored_v2` for Unity and `authored_v1` for the other
three engines. The delivery contract only permits predefined model slots, so these examples
use `sol` for routing; `generator`, `demo_only`, and `provenance_note` explicitly
identify locally authored fixtures. Never include these `DEMO_*` cases in
benchmark model comparisons.

A completed run prints the CLI's `DONE ... total=... complete=True` line for
each engine. Inspect `score.json`, the plan/record/evidence artifacts,
`model_calls` and `manifest.json` in each evaluation directory. No fixed numeric
score is promised: the actual planner, input handling, engine and judge determine
it. `complete=False`, a tool failure, or a source-only score is not a completed
plan → record → judge → score run.

## Existing exploratory evidence

`run.py` and `threejs/record.mjs` are auxiliary local tests. Their outputs cannot
stand in for Stage1 results. The earlier `out-stage1` used a withdrawn experimental
suite; its failures and partial results are retained as diagnostic history, not
as successful normal Stage1 runs. The normal CLI inputs use
`out-stage1-standard` and separate `DEMO_*` case identities.

See [VERIFICATION.md](VERIFICATION.md) for the actual checks and remaining gaps.
