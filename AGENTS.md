# GameFactory-3A — eval workspace

Authorised evaluation workspace for GameFactory-3A benchmark pipeline.
This directory contains the migrated eval pipeline (`pipeline/eval/`),
scripts (`scripts/eval/`), and test data (`test_data/`).

Agent tasks in this directory:
- Running `scripts/eval/evaluate.py` for stage 1/3 evaluation
- Running `scripts/eval/freeze_standards.py` to draft and approve standards
- Inspecting and repairing eval outputs under `test_data/outputs/eval/`
