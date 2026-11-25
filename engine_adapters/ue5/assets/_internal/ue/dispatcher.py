"""UE asset type dispatcher."""

from __future__ import annotations

from engine_adapters.ue5.assets._internal.types import AssetType, ImportRequest, ValidationResult
from engine_adapters.ue5._internal.transport import Transport

from .importers import AvatarImporter, BaseImporter, GenericImporter, MotionImporter, SceneImporter


from .importers.media import MediaImporter


class UEImportDispatcher:
    def __init__(self, transport: Transport | None = None) -> None:
        self.transport = transport
        self._media = MediaImporter(transport=transport)
        self._avatar = AvatarImporter(transport=transport)
        self._motion = MotionImporter(transport=transport)
        self._scene = SceneImporter(transport=transport)
        self._generic_by_type: dict[str, GenericImporter] = {}

    def importer_for(self, request: ImportRequest) -> BaseImporter:
        if request.asset_type == AssetType.VIDEO:
            return self._media
        if request.asset_type == AssetType.AVATAR:
            return self._avatar
        if request.asset_type == AssetType.MOTION:
            return self._motion
        if request.asset_type in {AssetType.SCENE, AssetType.ENVIRONMENT}:
            return self._scene
        key = request.type_key
        if key not in self._generic_by_type:
            self._generic_by_type[key] = GenericImporter(key, transport=self.transport)
        return self._generic_by_type[key]

    def validate_asset(self, request: ImportRequest) -> ValidationResult:
        return self.importer_for(request).validate(request)

    def import_asset(self, request: ImportRequest) -> dict:
        return self.importer_for(request).import_asset(request)
