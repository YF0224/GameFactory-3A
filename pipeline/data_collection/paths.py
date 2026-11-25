"""Trajectory paths needed by the migrated refine collection runtime."""
from __future__ import annotations

import os
from pathlib import Path

from pipeline.common.paths import REPO_ROOT, rel_to_repo

TRAIN_DATA_ROOT = Path(
    os.environ.get("AAAGF_TRAIN_DATA_ROOT", REPO_ROOT / "train_data")
).expanduser()


def make_trajectory_id(game_id: str, run_id: str) -> str:
    return f"{game_id}__{run_id}"


def trajectory_path(trajectory_id: str) -> Path:
    path = TRAIN_DATA_ROOT / "trajectories" / f"{trajectory_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def collect_json_path() -> Path:
    path = TRAIN_DATA_ROOT / "collect.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
