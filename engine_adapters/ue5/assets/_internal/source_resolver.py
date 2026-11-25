"""Resolve generated A3Game artifacts from task descriptors."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from pipeline.common import paths


ASSET_TYPE_TASK_KIND = {
    "avatar": "3d_object",
    "effect": "3d_object",
    "environment": "3d_object",
    "material": "3d_object",
    "prop": "3d_object",
    "static_mesh": "3d_object",
    "texture": "3d_object",
    "weapon": "3d_object",
    "scene": "3d_scene",
    "motion": "motion",
    "audio": "audio",
    "video": "cg_video",
    "media": "cg_video",
    "cg_video": "cg_video",
}


@dataclass(frozen=True)
class ResolvedAssetSource:
    game_id: str
    run_id: str
    task_kind: str
    task_id: str
    artifact_key: str
    task_dir: Path
    meta_path: Path
    path: Path
    metadata: dict[str, Any]

    def descriptor(self) -> dict[str, str]:
        return {
            "game_id": self.game_id,
            "run_id": self.run_id,
            "task_kind": self.task_kind,
            "task_id": self.task_id,
            "artifact_key": self.artifact_key,
        }


class GeneratedAssetSourceResolver:
    """Resolve one file declared by a generated task's ``meta.json``."""

    def resolve(
        self,
        source: Mapping[str, Any],
        *,
        asset_type: str = "",
        allow_directory: bool = False,
    ) -> ResolvedAssetSource:
        if not isinstance(source, Mapping):
            raise TypeError(
                "UE asset source must be a descriptor object with "
                "game_id, run_id, task_kind, and task_id; raw paths "
                "are not part of the UEClient v1 contract"
            )

        descriptor = dict(source)
        game_id = str(descriptor.get("game_id") or "").strip()
        task_id = str(descriptor.get("task_id") or "").strip()
        run_id = str(
            descriptor.get("run_id")
            or paths.DEFAULT_RUN_ID
        ).strip()
        task_kind = str(
            descriptor.get("task_kind")
            or ASSET_TYPE_TASK_KIND.get(
                str(asset_type or "").strip().lower(),
                "",
            )
        ).strip()
        missing = [
            name
            for name, value in {
                "game_id": game_id,
                "run_id": run_id,
                "task_kind": task_kind,
                "task_id": task_id,
            }.items()
            if not value
        ]
        if missing:
            raise ValueError(
                "UE asset source descriptor is missing: "
                + ", ".join(missing)
            )
        paths.check_kind(task_kind)

        task_dir = paths.task_output_dir(
            game_id,
            task_kind,
            task_id,
            run_id=run_id,
            create=False,
        ).resolve()
        meta_path = task_dir / "meta.json"
        if not meta_path.is_file():
            raise FileNotFoundError(
                f"Generated asset metadata was not found: {meta_path}"
            )
        try:
            metadata = json.loads(
                meta_path.read_text(encoding="utf-8")
            )
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Generated asset metadata is invalid JSON: {meta_path}"
            ) from exc
        if not isinstance(metadata, dict):
            raise ValueError(
                f"Generated asset metadata must be an object: {meta_path}"
            )
        self._validate_identity(
            metadata,
            game_id=game_id,
            run_id=run_id,
            task_kind=task_kind,
            task_id=task_id,
        )

        artifact_key = str(
            descriptor.get("artifact_key") or ""
        ).strip()
        if artifact_key:
            candidate_keys = [artifact_key]
        else:
            candidate_keys = self._artifact_keys(metadata)
            if len(candidate_keys) != 1:
                available = ", ".join(candidate_keys) or "(none)"
                raise ValueError(
                    "artifact_key is required when meta.json declares "
                    f"zero or multiple artifact files; available: {available}"
                )
            artifact_key = candidate_keys[0]

        raw_path = metadata.get(artifact_key)
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ValueError(
                f"meta.json does not declare artifact {artifact_key!r}"
            )
        artifact_path = Path(raw_path).expanduser()
        if not artifact_path.is_absolute():
            artifact_path = task_dir / artifact_path
        artifact_path = artifact_path.resolve()
        try:
            artifact_path.relative_to(task_dir)
        except ValueError as exc:
            raise ValueError(
                "Generated artifact path must stay inside its task "
                f"directory: {artifact_path}"
            ) from exc
        exists = (
            artifact_path.exists()
            if allow_directory
            else artifact_path.is_file()
        )
        if not exists:
            raise FileNotFoundError(
                f"Generated artifact file was not found: {artifact_path}"
            )

        return ResolvedAssetSource(
            game_id=game_id,
            run_id=run_id,
            task_kind=task_kind,
            task_id=task_id,
            artifact_key=artifact_key,
            task_dir=task_dir,
            meta_path=meta_path,
            path=artifact_path,
            metadata=metadata,
        )

    @staticmethod
    def _artifact_keys(metadata: Mapping[str, Any]) -> list[str]:
        keys = []
        for key, value in metadata.items():
            if (
                key == "output_dir"
                or not key.endswith("_path")
                or not isinstance(value, str)
                or not value.strip()
            ):
                continue
            keys.append(str(key))
        return sorted(keys)

    @staticmethod
    def _validate_identity(
        metadata: Mapping[str, Any],
        *,
        game_id: str,
        run_id: str,
        task_kind: str,
        task_id: str,
    ) -> None:
        expected = {
            "game_id": game_id,
            "run_id": run_id,
            "task_kind": task_kind,
            "task_id": task_id,
        }
        mismatches = []
        for key, expected_value in expected.items():
            actual = str(metadata.get(key) or "").strip()
            if actual and actual != expected_value:
                mismatches.append(
                    f"{key}={actual!r} (expected {expected_value!r})"
                )
        if mismatches:
            raise ValueError(
                "Generated asset metadata identity mismatch: "
                + "; ".join(mismatches)
            )
