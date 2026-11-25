"""Artifact model helpers for A3Game-managed asset lifecycle."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


SPAWNABLE_BACKEND_CLASSES = {"StaticMesh", "SkeletalMesh", "Blueprint", "BlueprintGeneratedClass"}
RENDERABLE_BACKEND_CLASSES = SPAWNABLE_BACKEND_CLASSES | {"NiagaraSystem", "ParticleSystem"}
PLAYABLE_BACKEND_CLASSES = {"AnimSequence", "LevelSequence", "MediaSource", "FileMediaSource"}
ARTIFACT_STATES = {"importing", "ready", "failed"}
REPRESENTATION_BY_BACKEND_CLASS = {
    "StaticMesh": "static_mesh",
    "SkeletalMesh": "skeletal_mesh",
    "AnimSequence": "animation",
    "NiagaraSystem": "niagara_system",
    "NiagaraEmitter": "niagara_emitter",
    "ParticleSystem": "particle_system",
    "LevelSequence": "level_sequence",
    "MediaSource": "media",
    "FileMediaSource": "media",
}
PRIMARY_BACKEND_CLASSES = {
    "video": ("FileMediaSource",),
    "avatar": ("SkeletalMesh",),
    "motion": ("AnimSequence",),
    "prop": ("StaticMesh", "SkeletalMesh"),
    "environment": ("StaticMesh",),
}
DEPENDENCY_TYPE_BY_BACKEND_CLASS = {
    "Material": "material",
    "MaterialInstance": "material",
    "MaterialInstanceConstant": "material",
    "Texture": "texture",
    "Texture2D": "texture",
    "TextureCube": "texture",
    "Skeleton": "skeleton",
    "PhysicsAsset": "physics",
    "AnimSequence": "animation",
}

TYPE_ALIASES = {
    "scene": "environment",
    "static_mesh": "prop",
    "object": "prop",
    "weapon": "prop",
    "furniture": "prop",
    "decoration": "prop",
}


@dataclass(frozen=True)
class ArtifactRecord:
    artifact_id: str
    asset_id: str
    type: str
    package_id: str = ""
    category: str = ""
    representation: str = ""
    primary_asset: dict[str, Any] = field(default_factory=dict)
    runtime_capabilities: dict[str, Any] = field(default_factory=dict)
    backend: str = "ue"
    backend_class: str = ""
    backend_path: str = ""
    source_path: str = ""
    spawnable: bool = False
    state: str = "ready"
    editor_backend: dict[str, Any] = field(default_factory=dict)
    runtime: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.state not in ARTIFACT_STATES:
            object.__setattr__(self, "state", "ready")
        if not self.representation:
            object.__setattr__(
                self,
                "representation",
                REPRESENTATION_BY_BACKEND_CLASS.get(self.backend_class, self.backend_class.lower()),
            )
        if not self.primary_asset:
            object.__setattr__(
                self,
                "primary_asset",
                {
                    "backend": self.backend,
                    "class": self.backend_class,
                    "path": self.backend_path,
                },
            )
        if not self.runtime_capabilities:
            object.__setattr__(
                self,
                "runtime_capabilities",
                {
                    "renderable": self.backend_class in RENDERABLE_BACKEND_CLASSES,
                    "spawnable": self.spawnable,
                    "collidable": False,
                    "playable": self.backend_class in PLAYABLE_BACKEND_CLASSES,
                },
            )
        if not self.editor_backend:
            object.__setattr__(self, "editor_backend", {"backend": self.backend, "path": self.backend_path})
        if not self.runtime:
            object.__setattr__(self, "runtime", {"spawnable": self.spawnable, "class": self.backend_class})

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ArtifactRecord":
        metadata = dict(data.get("metadata") or {})
        backend = str(data.get("backend") or "ue")
        backend_class = str(data.get("backend_class") or data.get("class") or "")
        backend_path = str(data.get("backend_path") or data.get("path") or "")
        spawnable = bool(data.get("spawnable", False))
        representation = str(data.get("representation") or "")
        primary_asset = dict(data.get("primary_asset") or {})
        runtime_capabilities = dict(data.get("runtime_capabilities") or data.get("capabilities") or {})
        editor_backend = dict(data.get("editor_backend") or {})
        runtime = dict(data.get("runtime") or {})
        if not editor_backend:
            editor_backend = {"backend": backend, "path": backend_path}
        if not runtime:
            runtime = {"spawnable": spawnable, "class": backend_class}
        state = str(data.get("state") or "ready")
        if state not in ARTIFACT_STATES:
            state = "ready"
        return cls(
            artifact_id=str(data.get("artifact_id") or data.get("id") or ""),
            asset_id=str(data.get("asset_id") or ""),
            package_id=str(data.get("package_id") or data.get("asset_id") or ""),
            type=str(data.get("type") or ""),
            category=str(data.get("category") or ""),
            representation=representation,
            primary_asset=primary_asset,
            runtime_capabilities=runtime_capabilities,
            backend=backend,
            backend_class=backend_class,
            backend_path=backend_path,
            source_path=str(data.get("source_path") or ""),
            spawnable=spawnable,
            state=state,
            editor_backend=editor_backend,
            runtime=runtime,
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "asset_id": self.asset_id,
            "package_id": self.package_id,
            "type": self.type,
            "category": self.category,
            "representation": self.representation,
            "primary_asset": dict(self.primary_asset or {}),
            "runtime_capabilities": dict(self.runtime_capabilities or {}),
            "backend": self.backend,
            "backend_class": self.backend_class,
            "backend_path": self.backend_path,
            "source_path": self.source_path,
            "spawnable": self.spawnable,
            "state": self.state,
            "editor_backend": dict(self.editor_backend or {}),
            "runtime": dict(self.runtime or {}),
            "metadata": dict(self.metadata or {}),
        }


def normalize_artifact_type(asset_type: str) -> str:
    normalized = (asset_type or "").strip().lower().replace("-", "_").replace(" ", "_")
    return TYPE_ALIASES.get(normalized, normalized)


def normalize_backend_path(backend_path: str) -> str:
    path = str(backend_path or "").strip()
    if not path.startswith("/"):
        return path
    return path.split(".", 1)[0]


def asset_id_from_source(source_path: str) -> str:
    stem = Path(source_path or "asset").stem or "asset"
    cleaned = re.sub(r"[^0-9A-Za-z_]+", "_", stem).strip("_").lower()
    return cleaned or "asset"


def _safe_asset_name_part(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_]+", "_", str(value or "").strip()).strip("_").lower()
    return cleaned or "part"


def short_hash(*parts: str, length: int = 6) -> str:
    joined = "|".join(str(part or "") for part in parts)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:length]


def artifact_id_for(backend: str, backend_class: str, asset_id: str, backend_path: str) -> str:
    backend_part = re.sub(r"[^0-9A-Za-z_]+", "_", (backend or "backend").lower()).strip("_") or "backend"
    class_part = re.sub(r"[^0-9A-Za-z_]+", "_", (backend_class or "asset").lower()).strip("_") or "asset"
    asset_part = re.sub(r"[^0-9A-Za-z_]+", "_", (asset_id or "asset").lower()).strip("_") or "asset"
    return f"{backend_part}_{class_part}_{asset_part}_{short_hash(backend, backend_path)}"


def _asset_name_from_path(backend_path: str) -> str:
    path = normalize_backend_path(backend_path)
    return path.rstrip("/").rsplit("/", 1)[-1]


def _select_primary_asset(asset_type: str, asset_id: str, assets: list[dict[str, str]]) -> dict[str, str] | None:
    primary_classes = PRIMARY_BACKEND_CLASSES.get(asset_type)
    if not primary_classes:
        return assets[0] if assets else None
    candidates = [asset for asset in assets if asset.get("class") in primary_classes]
    if not candidates:
        return None
    normalized_asset_id = asset_id.lower()
    for candidate in candidates:
        name = (candidate.get("name") or _asset_name_from_path(candidate.get("path") or "")).lower()
        if name == normalized_asset_id:
            return candidate
    for candidate in candidates:
        name = (candidate.get("name") or _asset_name_from_path(candidate.get("path") or "")).lower()
        if normalized_asset_id in name or name in normalized_asset_id:
            return candidate
    return candidates[0]


def _dependency_groups(assets: list[dict[str, str]], primary_path: str) -> list[dict[str, Any]]:
    groups: dict[str, list[str]] = {}
    for asset in assets:
        backend_path = normalize_backend_path(asset.get("path") or "")
        if not backend_path or backend_path == primary_path:
            continue
        dependency_type = DEPENDENCY_TYPE_BY_BACKEND_CLASS.get(asset.get("class") or "")
        if not dependency_type:
            continue
        groups.setdefault(dependency_type, []).append(backend_path)
    return [{"type": key, "assets": sorted(set(paths))} for key, paths in sorted(groups.items())]


def build_artifact_records(
    import_result: dict[str, Any],
    backend: str = "ue",
    category: str = "",
    classified_assets: list[dict[str, Any]] | None = None,
    include_all_static_meshes: bool = False,
) -> list[ArtifactRecord]:
    source_path = str(import_result.get("src_path") or "")
    asset_type = normalize_artifact_type(str(import_result.get("asset_type") or ""))
    asset_id = asset_id_from_source(source_path)
    category = str(category or import_result.get("category") or "")

    assets_by_path: dict[str, dict[str, str]] = {}
    for asset in classified_assets or []:
        backend_path = normalize_backend_path(str(asset.get("path") or ""))
        if not backend_path:
            continue
        assets_by_path[backend_path] = {
            "path": backend_path,
            "class": str(asset.get("class") or asset.get("backend_class") or ""),
            "name": str(asset.get("name") or _asset_name_from_path(backend_path)),
        }

    for backend_path in import_result.get("imported_paths") or []:
        backend_path = normalize_backend_path(str(backend_path or ""))
        if not backend_path:
            continue
        assets_by_path.setdefault(
            backend_path,
            {
                "path": backend_path,
                "class": str((import_result.get("metadata") or {}).get("backend_class") or ""),
                "name": _asset_name_from_path(backend_path),
            },
        )

    assets = list(assets_by_path.values())
    primary = _select_primary_asset(asset_type, asset_id, assets)
    if primary is None:
        return []

    package_path = str(import_result.get("dest_path") or "").rstrip("/")
    primary_assets = [primary]
    if asset_type == "environment" or include_all_static_meshes:
        scene_meshes = [
            asset
            for asset in assets
            if asset.get("class") == "StaticMesh"
        ]
        if scene_meshes:
            primary_assets = sorted(scene_meshes, key=lambda item: item.get("path") or "")

    records: list[ArtifactRecord] = []
    for index, primary_asset in enumerate(primary_assets):
        backend_path = normalize_backend_path(primary_asset.get("path") or "")
        backend_class = primary_asset.get("class") or ""
        spawnable = backend_class in SPAWNABLE_BACKEND_CLASSES
        part_name = _safe_asset_name_part(
            primary_asset.get("name") or _asset_name_from_path(backend_path)
        ).lower()
        record_asset_id = asset_id
        if len(primary_assets) > 1:
            record_asset_id = f"{asset_id}_{part_name or index}"
        metadata = {
            "dest_path": package_path,
            "package_path": package_path,
            "dependencies": _dependency_groups(assets, backend_path),
        }
        if len(primary_assets) > 1:
            metadata.update(
                {
                    "scene_part_index": index,
                    "scene_part_count": len(primary_assets),
                    "scene_part_name": part_name,
                    "scene_package_id": asset_id,
                }
            )
        if not backend_class:
            metadata["classification"] = "unknown"

        records.append(
            ArtifactRecord(
                artifact_id=artifact_id_for(backend, backend_class or "asset", record_asset_id, backend_path),
                asset_id=record_asset_id,
                package_id=asset_id,
                type=asset_type,
                category=category,
                representation=REPRESENTATION_BY_BACKEND_CLASS.get(backend_class, backend_class.lower()),
                primary_asset={"backend": backend, "class": backend_class, "path": backend_path},
                runtime_capabilities={
                    "renderable": backend_class in RENDERABLE_BACKEND_CLASSES,
                    "spawnable": spawnable,
                    "collidable": asset_type == "environment" and backend_class == "StaticMesh",
                    "playable": backend_class in PLAYABLE_BACKEND_CLASSES,
                },
                backend=backend,
                backend_class=backend_class,
                backend_path=backend_path,
                source_path=source_path,
                spawnable=spawnable,
                state="ready",
                editor_backend={"backend": backend, "path": backend_path, "package_path": package_path},
                runtime={"spawnable": spawnable, "class": backend_class},
                metadata=metadata,
            )
        )
    return records
