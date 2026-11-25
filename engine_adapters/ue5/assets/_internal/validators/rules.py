"""Small validation rules used by the M1 import pipeline."""

from __future__ import annotations

from typing import Protocol

from engine_adapters.ue5.assets._internal.pipeline.contracts import ImportResult


class ValidationRule(Protocol):
    name: str

    def check(self, result: ImportResult) -> None:
        ...


class ImportedAssetRule:
    name = "imported_asset"

    def check(self, result: ImportResult) -> None:
        if not result.imported_assets:
            result.add_error("没有可验证的 UE 导入资产")


class PrimaryAssetRule:
    name = "primary_asset"

    EXPECTED_CLASSES = {
        "video": {"FileMediaSource"},
        "avatar": {"SkeletalMesh"},
        "motion": {"AnimSequence"},
        "prop": {"StaticMesh", "SkeletalMesh"},
        "static_mesh": {"StaticMesh", "SkeletalMesh"},
        "weapon": {"StaticMesh", "SkeletalMesh"},
        "environment": {"StaticMesh", "World", "Level"},
        "scene": {"StaticMesh", "World", "Level"},
    }

    def check(self, result: ImportResult) -> None:
        expected = self.EXPECTED_CLASSES.get(result.job.request.type_key)
        if not expected:
            return
        classes = {str(asset.get("class") or "") for asset in result.imported_assets}
        if not classes.intersection(expected):
            result.add_error(
                f"{result.job.request.type_key} 导入结果缺少主资产类型，期望: {', '.join(sorted(expected))}"
            )


class AvatarSkeletonRule:
    name = "avatar_skeleton"

    def check(self, result: ImportResult) -> None:
        if result.job.request.type_key != "avatar":
            return
        mesh = next(
            (asset for asset in result.imported_assets if asset.get("class") == "SkeletalMesh"),
            {},
        )
        has_skeleton = bool(mesh.get("skeleton_path")) or any(
            asset.get("class") == "Skeleton" for asset in result.imported_assets
        )
        if not has_skeleton:
            result.add_error("Avatar 导入结果缺少 Skeleton")


class AvatarPhysicsAssetRule:
    name = "avatar_physics_asset"

    def check(self, result: ImportResult) -> None:
        if result.job.request.type_key != "avatar":
            return
        if not any(asset.get("class") == "PhysicsAsset" for asset in result.imported_assets):
            result.add_error("Avatar 导入结果缺少 PhysicsAsset")


class RequestedMeshKindRule:
    name = "requested_mesh_kind"

    def check(self, result: ImportResult) -> None:
        request = result.job.request
        source_suffix = str(result.source.get("suffix") or "")
        if source_suffix != ".fbx":
            return
        if request.type_key == "avatar":
            expected_class = "SkeletalMesh"
        elif request.type_key in {"prop", "static_mesh", "weapon"}:
            expected_class = "SkeletalMesh" if request.options.get("as_skeletal", False) else "StaticMesh"
        else:
            return

        imported_primary_classes = {
            str(asset.get("class") or "")
            for asset in result.imported_assets
            if asset.get("imported")
        }
        if expected_class not in imported_primary_classes:
            result.add_error(
                f"FBX 导入类型不符合请求: expected={expected_class} actual={sorted(imported_primary_classes)}"
            )


class MotionSkeletonRule:
    name = "motion_skeleton"

    def check(self, result: ImportResult) -> None:
        request = result.job.request
        if request.type_key != "motion":
            return
        animation = next(
            (asset for asset in result.imported_assets if asset.get("class") == "AnimSequence"),
            {},
        )
        actual = str(animation.get("skeleton_path") or "").split(".", 1)[0].strip()
        expected = str(request.options.get("skeleton_asset_path") or "").split(".", 1)[0].strip()
        if not actual:
            result.add_error("Motion 导入结果没有 Skeleton")
            return
        if expected and actual != expected:
            result.add_error(f"Motion Skeleton 不匹配: expected={expected} actual={actual}")


class ValidationRunner:
    def __init__(self, rules: list[ValidationRule] | None = None) -> None:
        self.rules = rules or [
            ImportedAssetRule(),
            PrimaryAssetRule(),
            AvatarSkeletonRule(),
            AvatarPhysicsAssetRule(),
            RequestedMeshKindRule(),
            MotionSkeletonRule(),
        ]

    def validate(self, result: ImportResult) -> None:
        for rule in self.rules:
            rule.check(result)
            if result.errors:
                return
