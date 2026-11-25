"""Shared asset pipeline request and result types."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional


class AssetType(str, Enum):
    AVATAR = "avatar"
    SKELETON = "skeleton"
    MOTION = "motion"
    SCENE = "scene"
    ENVIRONMENT = "environment"
    STATIC_MESH = "static_mesh"
    MATERIAL = "material"
    TEXTURE = "texture"
    EFFECT = "effect"
    AUDIO = "audio"
    VIDEO = "video"


SUPPORTED_IMPORT_ASSET_TYPE_NAMES = ("avatar", "motion", "scene", "environment", "static_mesh", "effect", "material", "texture", "prop", "weapon", "object", "video")
ASSET_GROUP_TYPE_NAMES = ("avatar", "skeleton", "motion", "environment", "effect", "prop")

_ASSET_TYPE_ALIASES = {
    "media": "video",
    "cg_video": "video",
    "avatars": "avatar",
    "skeletalmesh": "avatar",
    "skeletons": "skeleton",
    "motions": "motion",
    "animation": "motion",
    "animations": "motion",
    "animsequence": "motion",
    "scene": "environment",
    "scenes": "environment",
    "environments": "environment",
    "effects": "effect",
    "niagara": "effect",
    "materials": "material",
    "textures": "texture",
    "staticmesh": "static_mesh",
    "static_meshes": "static_mesh",
    "mesh": "static_mesh",
    "meshes": "static_mesh",
    "props": "prop",
    "furniture": "prop",
    "decoration": "prop",
    "decorations": "prop",
    "object": "prop",
    "objects": "prop",
    "weapon": "prop",
    "weapons": "prop",
}


def normalize_asset_type_name(asset_type: str) -> str:
    normalized = (asset_type or "").strip().lower().replace("-", "_").replace(" ", "_")
    normalized = _ASSET_TYPE_ALIASES.get(normalized, normalized)
    if normalized in {"prop", "weapon"}:
        return normalized
    try:
        AssetType(normalized)
    except ValueError as exc:
        supported = ", ".join(sorted({*SUPPORTED_IMPORT_ASSET_TYPE_NAMES, "skeleton", "static_mesh", "audio"}))
        raise ValueError(f"不支持的资产类型: {asset_type}（支持: {supported}）") from exc
    return normalized


def canonical_asset_type(asset_type: str) -> AssetType:
    normalized = normalize_asset_type_name(asset_type)
    if normalized in {"prop", "weapon"}:
        return AssetType.STATIC_MESH
    return AssetType(normalized)


@dataclass(frozen=True)
class ImportRequest:
    src_path: str
    asset_type: AssetType
    dst_path: str = ""
    options: dict[str, Any] = field(default_factory=dict)
    asset_type_name: str = ""

    @classmethod
    def from_values(cls, src_path: str, asset_type: str, dst_path: str = "", **options: Any) -> "ImportRequest":
        normalized_name = normalize_asset_type_name(asset_type)
        return cls(
            src_path=Path(src_path).expanduser().resolve().as_posix(),
            asset_type=canonical_asset_type(normalized_name),
            dst_path=dst_path,
            options=dict(options),
            asset_type_name=normalized_name,
        )

    @property
    def type_key(self) -> str:
        return self.asset_type_name or self.asset_type.value


@dataclass(frozen=True)
class AssetQuery:
    asset_type: Optional[AssetType] = None
    asset_type_name: str = ""
    root_path: str = ""

    @classmethod
    def from_values(cls, asset_type: Optional[str] = None, root_path: str = "") -> "AssetQuery":
        if asset_type is None or asset_type == "":
            return cls(root_path=root_path)
        normalized_name = normalize_asset_type_name(asset_type)
        return cls(asset_type=canonical_asset_type(normalized_name), asset_type_name=normalized_name, root_path=root_path)

    @property
    def type_key(self) -> str:
        return self.asset_type_name or (self.asset_type.value if self.asset_type else "")


@dataclass(frozen=True)
class ImportResult:
    asset_type: str
    src_path: str
    dest_path: str
    imported_paths: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result = {
            "asset_type": self.asset_type,
            "src_path": self.src_path,
            "dest_path": self.dest_path,
            "imported_paths": self.imported_paths,
        }
        result.update(self.metadata)
        return result


@dataclass(frozen=True)
class AssetRecord:
    name: str
    path: str
    class_name: str = ""
    package_path: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AssetRecord":
        metadata = dict(data)
        name = str(metadata.pop("name", ""))
        path = str(metadata.pop("path", ""))
        class_name = str(metadata.pop("class", metadata.pop("class_name", "")))
        package_path = str(metadata.pop("package_path", ""))
        return cls(name=name, path=path, class_name=class_name, package_path=package_path, metadata=metadata)

    def to_dict(self) -> dict[str, Any]:
        result = dict(self.metadata)
        result.update(
            {
                "name": self.name,
                "path": self.path,
                "class": self.class_name,
                "package_path": self.package_path,
            }
        )
        return result


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
