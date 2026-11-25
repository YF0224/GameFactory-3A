# Evaluation pipeline migration

Status at 2026-11-25: pipeline migration on `eval-pipeline-migration`, based on main `41445aa`. The working directory is `../GameFactory-3A-eval-migration`. Per the user's updated scope, `scripts/eval/` remains at its intermediate migration state; this change does **not** claim acceptance of all one-command generation/evaluation flows.

## Migrated scope and dependencies

- `pipeline/eval/`: stage1, stage3, repairs, asset bridge and shared model defaults (95 files, 88 Python modules including helpers/tests).
- `pipeline/game_eval/asset_eval/`: 28 files, preserving the three independent scoring columns and null for unavailable measurements.
- `pipeline/game_eval/whitebox_eval/`: 338 Python modules in the actual transitive dependency closure. Sparse evidence imports native and Unity verification, which imports their runtime/publication helpers. The source directory was not copied wholesale.
- `pipeline/game_eval/refine/`: 42 files needed by the explicitly retained legacy refinement wrappers. Their provider runtime requires the 43-module `pipeline/data_collection/` dependency closure.
- Engine adapter synchronization: 78 changed/added files relative to main; source bench wins conflicts and target-only files remain.
- `pipeline/code_gen/playtest/engine_dispatch.py`, required package initializers and the dynamically loaded priority-assets renderer (`render.mjs`, `package.json`, `package-lock.json`).
- Whitelisted launchers/frozen prompts in `scripts/eval/` and reusable skills in `agent_skills/eval/`. The four prompt bodies retain source bytes. No further script work is included in the final pipeline verification fixes.

No `test_data/`, historical deliveries, workspaces, archived plugins, recordings, scores, judgment outputs, caches, AGENTS files, or the original eval branch's uncommitted changes are part of this migration. Excluded historical `playable_*`/watch/batch launchers remain excluded; shared functions they supplied are extracted into `stage1/playable_support.py` and `recovery_support.py`.

## Configuration and contracts

`pipeline/eval/stage1/paths.py` uses the current repository root. `GF3A_DATA_ROOT` defaults to `<repo>/test_data`; `test_data/...` input paths resolve under it, other relative inputs resolve under the repository. Legacy `pipeline/common/paths.py` is unchanged, including its collect-jsonl convention. The new `pipeline/data_collection/paths.py` supplies missing trajectory helpers for migrated dependencies without replacing that shared framework module.

- `pipeline/eval/model_config.py` centralizes Astra/Sol/Opus defaults. `A3GAME_PLANNER_MODEL` and `A3GAME_JUDGE_MODEL` override them; `A3GAME_LAUNCH_REPAIR_MODEL` optionally selects the bounded launch repair model. Recovery defaults retain Astra planner/Sol judge; the existing general CLI retains Sol planner/Opus judge. Historical directory names are immutable identities, not current model selectors.
- `A3GAME_UE_ROOT` defaults to `/Users/Shared/Epic Games/UE_5.4` in evaluation recording. Unity discovery supports `A3GAME_UNITY_BINARY`, `A3GAME_UNITY_ROOT` and `A3GAME_TUANJIE_BINARY`; missing editors produce an actionable diagnostic.
- `A3GAME_CONTRACT_HISTORY` overrides the frozen rubric-contract input directory.
- `A3GAME_ASSET_EVAL_ENV` optionally selects the asset metric Python environment (default: current `sys.prefix`). Heavy metric packages, model weights, Node renderer dependencies/browser and generated assets are separate runtime requirements; `requirements-eval.txt` only covers baseline evaluation dependencies.
- The optional delivery requirement path and SHA must agree with generation job notes and engine identity. Preparation freezes that exact requirement and its reference images; existing budget rules consume it. Legacy deliveries remain supported.
- Stage3 criteria accept legacy `game_refine/inputs` or `playtest/gN/refine.json`, alias/full GameID. New inputs verify all four families, hashes, frozen source snapshots, record counts, physical lines and project/model identity. Criterion/scoring construction stays the same. New delivery layout validation binds to its generation job and enforces the ten-round cap.
- The asset bridge accepts `run(argv)` and forwards arguments to the existing evaluator. Renderer adaptation is deferred until the metrics gates allow computation, so preflight needs no render/model execution.

## Verification

Executed locally on macOS with Python 3.15.2. Other Python versions were not exercised; `tomli` is a conditional dependency for the retained refine runtime on Python below 3.11. No real engine, agent/model, or generated-asset metric run was executed.

Required imports:

```text
Required imports: OK
Repair modules: 26

```

The source currently has **26** discoverable repair modules, with 24 registry entries; `godot_completed_record_recovery` and `ue_completed_shutdown_recovery` are not registered in the source either. The request's expected count of 24 is stale; registration semantics were preserved.

AST parsing and direct import of all non-test modules under `pipeline/eval`, `pipeline/game_eval`, and `pipeline/data_collection`:

```text
Imported: 538
Failures: 0

```

```sh
python3 -m pytest -q test/test_stage1_*.py test/test_eval_pipeline_migration.py test/test_independent_ue_pair.py
```

```text
=========================== short test summary info ============================
FAILED test/test_stage1_dual_client_kimi.py::test_real_frozen_source_review
FAILED test/test_stage1_dual_client_kimi.py::test_scope_relocation_rejected
FAILED test/test_stage1_dual_client_kimi.py::test_four_gap_receipts_are_static_and_two_client_only
FAILED test/test_stage1_dual_client_unity_bounded.py::test_original_profile_bindings_are_current
4 failed, 648 passed, 2 skipped, 4 subtests passed in 29.44s
```

The four failures require absent historical results: three Kimi frozen scope/gap-receipt fixtures and one original Unity `NetworkSession.cs` snapshot. No new skips were added. Previously, the stage1-only run reported `4 failed, 629 passed, 2 skipped, 4 subtests passed in 34.44s`; the final combined run adds the 15 new migration regressions and four independent UE tests. The new regressions cover selected requirement freezing/budgets/reference inputs, delivery/job/engine mismatches, playtest task and source tampering, record/count/round validation, asset argv forwarding, and cwd-independent data/model overrides.

Existing asset smoke suite:

```text
3 failed, 15 passed in 0.23s
```

Two failures require generated G001 GLBs, intentionally not copied. The third is a source incompatibility: `asset_eval/render.py` expects the literal `const object=gltf.scene; object.updateMatrixWorld(true);`, whereas the current priority-assets renderer inserts an authored-light block between those statements. The strict adapter rejects this version. Metrics that need rendering remain blocked until that source/adapter pair is reconciled and validated. No lighting or scoring policy was changed to bypass the check.

Direct asset preflight through the pipeline bridge:

```python
from pipeline.eval.assets import run
run(['--scope', 'obj', '--mode', 'preflight', '--games', 'G001', '--no-sol'])
```

```text
{"out": "/Users/yifanyang/Desktop/GameFactory-3A-eval-migration/test_data/outputs/eval/asset_eval/20261125_204620_obj_no_sol", "records": 12, "delivered": 0, "glb_header_pass": 0, "status": "preflight_only", "heavy_imports": {"torch": false, "numpy": false, "transformers": false, "pyiqa": false, "trimesh": false, "PIL": false, "skimage": false, "sklearn": false}, "api_calls": 0}

```

All 12 per-asset result files retain null input/style/quality scores. Stage1 G001 builds 151 criteria; Stage3 g8 resolves to `G008_dock_beacon_cs` and builds 49 criteria. All 13 copied playtest task indexes passed source verification. `git grep -n "/Users/yifanyang" -- pipeline/eval pipeline/game_eval/asset_eval engine_adapters scripts/eval agent_skills/eval` returned no matches. `git diff origin/main --check` passed.

Real engine regression was not performed. Motion evidence retains the source's UE-tested status; Unity motion remains untested here, and neither was retested in this migration.

## Deferred scripts acceptance

`scripts/eval/` is preserved as requested, with earlier successful dry-runs for explicit Three.js G001, mixed Godot/Three.js collect G001 and Stage3 g8/Sol. Those dry-runs preceded the final requirement binding and do not prove final launcher compatibility. Remaining work includes asset CLI argv/scope forwarding, latest-delivery/new playtest discovery, legacy Stage3 wrapper roots/manifest handling, the missing `scripts/agent_notes/engine_env.md` config reference, and README references to `scripts_new`. Full launcher `--help`/list acceptance and end-to-end one-command operation are deferred. Use the direct pipeline asset bridge for the preflight shown above.

## Local data, excluded from Git

The worktree has G001–G060 sample inputs, `test_data/pipeline_collect.jsonl`, playtest task manifests/source snapshots and the g8 source project needed for dry-run validation. Frozen rubric history and repair-import task inputs are local only. `test_data/publish/` contains the original requirements/rubrics plus 60 asset requirement/common-rubric JSONs (579 source asset rubrics). The asset export uses allowlists and a recursive field audit found no model/provider/judgment/actual-score fields. Motion rubric text is preserved as an input requirement; it is not a claim that the asset CLI supports that modality. No `test_data` path is staged or committed.

## Relationship to the existing eval branch

This branch starts from main, without merging, resetting or switching the original checkout's `eval` branch. It does not replace `scripts/run_eval.py` or `pipeline/game_eval/evaluation/` from that branch. The new pipeline and `scripts/eval/` are a separate migration. Of the 235 paths changed on the existing eval branch, these four also change here and need deliberate reconciliation if both branches are merged:

- `engine_adapters/godot/playtest/client.py`
- `engine_adapters/godot/playtest/observe_recorder.gd`
- `pipeline/code_gen/playtest/engine_dispatch.py`
- `pipeline/game_eval/__init__.py`

Original checkout validation against the initial snapshot:

```text
Branch: eval
Full status unchanged: True
Files verified: 1108
Changed files: 0
```

The original status still has 84 collapsed entries; all 1108 snapshotted files and the complete porcelain status are unchanged. The worktree is retained.

## Same-name conflicts: bench authoritative

The initial copy found 31 differing existing-main files, all engine adapters. Target-only files were retained. Subsequent portable configuration edits are described above.

- `engine_adapters/godot/config.py`
- `engine_adapters/godot/playtest/client.py`
- `engine_adapters/three_js/_internal/transport/node.py`
- `engine_adapters/three_js/playtest/client.py`
- `engine_adapters/three_js/playtest/record.mjs`
- `engine_adapters/three_js/plugin/A3GamePlayable/src/engine/asset-library.js`
- `engine_adapters/three_js/plugin/A3GamePlayable/src/engine/runtime-host.js`
- `engine_adapters/three_js/plugin/A3GamePlayable/src/engine/scene-loader.js`
- `engine_adapters/three_js/plugin/A3GamePlayable/src/engine/visual-kit.js`
- `engine_adapters/ue5/_internal/transport/python_rpc.py`
- `engine_adapters/ue5/assets/_internal/artifacts/models.py`
- `engine_adapters/ue5/assets/_internal/postprocessors/ue_assets.py`
- `engine_adapters/ue5/assets/_internal/source_resolver.py`
- `engine_adapters/ue5/assets/_internal/types.py`
- `engine_adapters/ue5/assets/_internal/ue/asset_types.py`
- `engine_adapters/ue5/assets/_internal/ue/dispatcher.py`
- `engine_adapters/ue5/assets/_internal/validators/rules.py`
- `engine_adapters/ue5/build/client.py`
- `engine_adapters/ue5/config.py`
- `engine_adapters/ue5/playtest/client.py`
- `engine_adapters/ue5/playtest/recorder.py`
- `engine_adapters/ue5/plugin/A3GamePlayable/Source/A3GamePlayable/A3GamePlayable.Build.cs`
- `engine_adapters/ue5/plugin/A3GamePlayable/Source/A3GamePlayable/Private/Playtest/A3GamePlaytestRecorderSubsystem.cpp`
- `engine_adapters/ue5/plugin/A3GamePlayable/Source/A3GamePlayable/Public/Playtest/A3GamePlaytestRecorderSubsystem.h`
- `engine_adapters/ue5/project/client.py`
- `engine_adapters/ue5/runtime/client.py`
- `engine_adapters/ue5/testing/client.py`
- `engine_adapters/ue5/ue_client.py`
- `engine_adapters/unity3d/_internal/transport/unity_editor.py`
- `engine_adapters/unity3d/import_generated/GameFactory3APlayTestRecorder.cs`
- `engine_adapters/unity3d/playtest/client.py`

## Structural comparison against source pipeline/eval

No source files are missing (excluding `__pycache__`). The 31 intentional differences are listed individually below. All other files are byte-identical to the current source. Model defaults already present in source were retained.

| Relative path under `pipeline/eval/` | Change | Reason |
|---|---|---|
| `__init__.py` | changed | Correct package description: asset bridge and sparse evidence reuse game_eval dependencies. |
| `assets/__init__.py` | changed | Replace placeholder with lazy main(argv) delegation; preserve asset evaluator argument parsing. |
| `repair/godot_duration_batch.py` | changed | Resolve targets through DATA_ROOT and import the extracted playable helper as a package module. |
| `repair/launch_repair.py` | changed | Use agent_skills/eval/stage3-launch-repair/SKILL.md. |
| `repair/three_g011_addon_recovery.py` | changed | Relocate recovery/artifact paths and producer fingerprints to the repository/DATA_ROOT; retain recovery policy and historical run identity. |
| `repair/ue_g020_admission_recovery.py` | changed | Relocate recovery/artifact paths and producer fingerprints to the repository/DATA_ROOT; retain recovery policy and historical run identity. |
| `repair/ue_g020_capture_continuation.py` | changed | Relocate recovery/artifact paths and producer fingerprints to the repository/DATA_ROOT; retain recovery policy and historical run identity. |
| `repair/ue_g025_launch_path_recovery.py` | changed | Relocate recovery/artifact paths and producer fingerprints to the repository/DATA_ROOT; retain recovery policy and historical run identity. |
| `repair/ue_g025_take2_recovery.py` | changed | Relocate recovery/artifact paths and producer fingerprints to the repository/DATA_ROOT; retain recovery policy and historical run identity. |
| `repair/ue_g035_target_recovery.py` | changed | Relocate recovery/artifact paths and producer fingerprints to the repository/DATA_ROOT; retain recovery policy and historical run identity. |
| `repair/unity_authored_scene_recovery.py` | changed | Relocate recovery/artifact paths and producer fingerprints to the repository/DATA_ROOT; retain recovery policy and historical run identity. |
| `repair/unity_g009_builder_recovery.py` | changed | Relocate recovery/artifact paths and producer fingerprints to the repository/DATA_ROOT; retain recovery policy and historical run identity. |
| `repair/unity_natural_entry_recovery.py` | changed | Relocate recovery/artifact paths and producer fingerprints to the repository/DATA_ROOT; retain recovery policy and historical run identity. |
| `stage1/asset_views.py` | changed | Resolve source assets through DATA_ROOT. |
| `stage1/budgets.py` | changed | Accept the selected requirement file so engine variants use their own existing budget rules. |
| `stage1/criteria.py` | changed | Resolve frozen rubric contract history through DATA_ROOT or A3GAME_CONTRACT_HISTORY. |
| `stage1/delivery.py` | changed | Bind optional requirement path/SHA to generation notes; support verified playtest deliveries and repair-round limits; reject non-object JSON. |
| `stage1/dual_client_kimi.py` | changed | Read relative profile paths using shared path resolution; use repository-relative producer fingerprints. |
| `stage1/dual_client_unity.py` | changed | Read relative profile paths using shared path resolution; use repository-relative producer fingerprints. |
| `stage1/paths.py` | changed | Use repository root and GF3A_DATA_ROOT; resolve relative inputs/profile fields independently of cwd. |
| `stage1/playable_support.py` | added | Extract only library helpers required by pipeline recovery/dual-client code; exclude historical batch dispatchers. |
| `stage1/prepare.py` | changed | Freeze the bound requirement and its reference images; derive the budget from that same requirement. |
| `stage1/recovery_support.py` | added | Extract the shared library needed by original-scene recovery; exclude historical CLI orchestration. |
| `stage1/standards.py` | changed | Point the standards diagnostic to the migrated scripts/eval/freeze_standards.py. |
| `stage1/unity_authored_builder.py` | changed | Resolve runner/helper locations in the repository; retain original recovery verification. |
| `stage1/unity_authored_scene.py` | changed | Resolve runner/helper locations in the repository and repository-relative producer identity. |
| `stage1/unity_natural_entry.py` | changed | Use DATA_ROOT for original projects and the extracted playable library instead of scripts_new imports. |
| `stage1/unity_original_scene_job_preflight.py` | changed | Use DATA_ROOT for fixtures/targets and the extracted playable helper; preserve admission rules. |
| `stage3/__init__.py` | changed | Update entrypoint path in package documentation. |
| `stage3/criteria.py` | changed | Support both legacy refine inputs and source-verified playtest indexes; keep existing criterion construction. |
| `stage3/inputs.py` | added | Verify frozen task/source hashes, record/physical-line selections, identities, counts and the ten-round contract. |
