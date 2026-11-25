"""Resolve raw UE import paths into classified package assets."""

from __future__ import annotations

from time import sleep

from engine_adapters.ue5.assets._internal.artifacts.models import normalize_backend_path
from engine_adapters.ue5.assets._internal.pipeline.contracts import ImportResult
from engine_adapters.ue5.assets._internal.types import AssetQuery
from engine_adapters.ue5.assets._internal.ue.registry import UEAssetRegistry


class UEImportedAssetPostProcessor:
    PRIMARY_CLASSES = {
        "video": {"FileMediaSource"},
        "avatar": {"SkeletalMesh"},
        "motion": {"AnimSequence"},
        "prop": {"StaticMesh", "SkeletalMesh"},
        "static_mesh": {"StaticMesh", "SkeletalMesh"},
        "weapon": {"StaticMesh", "SkeletalMesh"},
        "environment": {"StaticMesh", "World", "Level"},
        "scene": {"StaticMesh", "World", "Level"},
    }

    def __init__(self, registry: UEAssetRegistry | None = None) -> None:
        self.registry = registry or UEAssetRegistry()

    def post_process(self, result: ImportResult) -> None:
        request = result.job.request
        raw_result = result.raw_result
        raw_result.setdefault("asset_type", request.type_key)
        raw_result.setdefault("src_path", request.src_path)
        raw_result.setdefault("dest_path", request.dst_path)

        imported_paths = {
            normalize_backend_path(path)
            for path in raw_result.get("imported_paths") or []
            if normalize_backend_path(path)
        }
        raw_result["imported_paths"] = sorted(imported_paths)
        if not imported_paths:
            result.imported_assets = []
            return

        dest_path = str(raw_result.get("dest_path") or "").rstrip("/")
        package_assets = self._list_assets(root_path=dest_path)
        typed_assets = self._list_assets(
            asset_type=request.type_key,
            root_path=dest_path,
        )
        assets_by_path: dict[str, dict] = {}
        for asset in package_assets:
            path = normalize_backend_path(asset.get("path") or "")
            if path:
                assets_by_path[path] = dict(asset)
        for asset in typed_assets:
            path = normalize_backend_path(asset.get("path") or "")
            if path:
                assets_by_path[path] = {**assets_by_path.get(path, {}), **asset}

        primary_classes = self.PRIMARY_CLASSES.get(request.type_key, set())
        classified = []
        for path, asset in assets_by_path.items():
            asset_class = str(asset.get("class") or "")
            is_current_import = path in imported_paths
            if not is_current_import and asset_class in primary_classes:
                continue
            classified.append({**asset, "imported": is_current_import})

        if not classified:
            classified = [
                {
                    "path": path,
                    "class": "",
                    "name": path.rsplit("/", 1)[-1],
                    "imported": True,
                }
                for path in imported_paths
            ]
        result.imported_assets = sorted(
            classified,
            key=lambda item: str(item.get("path") or ""),
        )
        self._refresh_skeleton_metadata(
            result,
            asset_type=request.type_key,
            root_path=dest_path,
            imported_paths=imported_paths,
        )

    def _refresh_skeleton_metadata(
        self,
        result: ImportResult,
        *,
        asset_type: str,
        root_path: str,
        imported_paths: set[str],
    ) -> None:
        expected_class = {
            "avatar": "SkeletalMesh",
            "motion": "AnimSequence",
        }.get(asset_type)
        if not expected_class:
            return

        for attempt in range(5):
            current = [
                asset
                for asset in result.imported_assets
                if asset.get("imported")
                and asset.get("class") == expected_class
            ]
            if current and all(
                str(asset.get("skeleton_path") or "").strip()
                for asset in current
            ):
                return
            if attempt:
                sleep(0.25)
            refreshed = self._list_assets(
                asset_type=asset_type,
                root_path=root_path,
            )
            refreshed_by_path = {
                normalize_backend_path(asset.get("path") or ""): asset
                for asset in refreshed
                if normalize_backend_path(asset.get("path") or "")
                in imported_paths
            }
            if not refreshed_by_path:
                continue
            result.imported_assets = [
                {
                    **asset,
                    **refreshed_by_path.get(
                        normalize_backend_path(asset.get("path") or ""),
                        {},
                    ),
                }
                for asset in result.imported_assets
            ]

    def _list_assets(self, asset_type: str = "", root_path: str = "") -> list[dict]:
        try:
            return self.registry.list_assets(
                AssetQuery.from_values(
                    asset_type=asset_type or None,
                    root_path=root_path,
                )
            )
        except Exception as exc:
            return []
