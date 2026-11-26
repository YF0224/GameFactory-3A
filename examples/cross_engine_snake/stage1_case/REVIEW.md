# Snake example standard review — delegated approval recorded

These drafts are synthetic example input data for the existing `stage1` suite.
They do not modify Stage1 scoring or add an evaluator. The example helper
does not approve standards. On 2026-11-23 the user explicitly delegated rubric
definition and judging to Codex. Codex reviewed these existing drafts and used
`scripts_new/freeze_standards.py` to record that delegated approval for all four
cases, without claiming independent human review. The local authorization
receipt is `../out-stage1-standard/rubric_authorization.json`.

The four cases use the same requirements and checks, with only their engine
metadata and `game_id` differing. There are eight mechanic endpoints:

1. Steering visibly changes the snake's direction.
2. Contact with food eats the food.
3. Eating food grows the snake.
4. Wall collision produces a failure state.
5. Self collision produces a failure state.
6. Completing the food goal produces a victory state.
7. Restart restores a playable initial board.
8. Pause produces a visible paused state; resume remains in the original requirement.

Each endpoint uses the existing outcome-frame standard fields: visible goal,
result frame, correct target, necessary context, representative basic function,
basic bugs and permitted trigger modes. The original requirement is retained
byte for byte. Timing, exact movement, exact numeric formulas and exhaustive
boundaries remain diagnostic-only under the existing frozen protocol.

The ordinary Stage1 builder also supplies the generic story, code, playable,
visual-quality and Gameness checks. Four C3 resource groups (snake, food, board,
status display) use its existing placeholder/binding/hook expansion. A Q check
covers distinguishing board/snake/food; a G check covers terminal feedback. No
reference image is supplied, so input consistency has no applicable checks.
No criterion is fabricated as passed.

After preparing the data, inspect the full generated review sheets:

- [Three.js](../../../test_data/bench_standards/stage1/stage1-criteria.v1/DEMO_snake_three_js/review.md)
- [Unity](../../../test_data/bench_standards/stage1/stage1-criteria.v1/DEMO_snake_unity3d/review.md)
- [UE](../../../test_data/bench_standards/stage1/stage1-criteria.v1/DEMO_snake_ue5/review.md)
- [Godot](../../../test_data/bench_standards/stage1/stage1-criteria.v1/DEMO_snake_godot/review.md)

The source drafts for each case are under `cases/DEMO_snake_*/standards/`.
The normal approval command is documented in [the example README](../README.md).
The reviewer field must identify the actual reviewer and any delegated authority;
the helper cannot invent an independent review. Native recording and runtime judging have
not been demonstrated merely by preparing this file.
