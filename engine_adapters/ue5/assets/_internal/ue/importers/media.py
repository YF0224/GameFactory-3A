"""Import project-local movies as saved FileMediaSource assets."""
from __future__ import annotations

import hashlib
import re
import textwrap
from pathlib import Path

from engine_adapters.ue5._internal.transport import Transport
from engine_adapters.ue5.assets._internal.types import ImportRequest
from ..asset_types import ASSET_TYPE_SUFFIXES, default_dest_for_asset_type
from ..builders.base import ScriptBuilder
from .base import BaseImporter


class MediaImportScriptBuilder(ScriptBuilder):
    def build_import_script(self, request: ImportRequest, dest_path: str) -> str:
        source = Path(request.src_path)
        hasher = hashlib.sha256()
        with source.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                hasher.update(chunk)
        digest = hasher.hexdigest()
        name = str(request.options.get("asset_name") or re.sub(r"[^A-Za-z0-9_]", "_", source.stem))
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise ValueError("Media asset_name must use letters, digits and underscores, starting with a letter or underscore")
        if any(part in {".", "..", ""} for part in dest_path.lstrip("/").split("/")):
            raise ValueError("Media destination must be a normalized /Game package path")
        return textwrap.dedent(f'''\
            import hashlib
            import os
            import shutil
            import tempfile
            from pathlib import Path
            import unreal

            def _media_sha256(path):
                digest = hashlib.sha256()
                with open(path, "rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
                return digest.hexdigest()

            source = Path({str(source)!r})
            expected_sha256 = {digest!r}
            if _media_sha256(source) != expected_sha256:
                raise RuntimeError("Media source changed before Editor execution")
            content = Path(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_content_dir())).resolve()
            movie = content / "Movies" / "A3Game" / expected_sha256 / source.name
            if not movie.resolve().is_relative_to(content):
                raise RuntimeError("Media file must remain inside project Content")
            asset_path = {dest_path!r} + "/" + {name!r}
            media = unreal.load_asset(asset_path)
            if media is not None and not isinstance(media, unreal.FileMediaSource):
                raise RuntimeError("Existing media destination is not a FileMediaSource: " + asset_path)
            if movie.exists() and _media_sha256(movie) != expected_sha256:
                raise RuntimeError("Existing project movie has a different SHA256")
            movie.parent.mkdir(parents=True, exist_ok=True)
            if not movie.exists():
                fd, temporary = tempfile.mkstemp(prefix=".import-", dir=str(movie.parent))
                os.close(fd)
                try:
                    shutil.copyfile(source, temporary)
                    if _media_sha256(temporary) != expected_sha256:
                        raise RuntimeError("Media source changed during copy")
                    os.replace(temporary, movie)
                finally:
                    if os.path.exists(temporary):
                        os.unlink(temporary)
            if media is None:
                media = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
                    {name!r}, {dest_path!r}, unreal.FileMediaSource, unreal.FileMediaSourceFactoryNew())
            if not isinstance(media, unreal.FileMediaSource):
                raise RuntimeError("Failed to create FileMediaSource: " + asset_path)
            media.set_file_path(str(movie))
            if not unreal.EditorAssetLibrary.save_loaded_asset(media, only_if_is_dirty=False):
                raise RuntimeError("Failed to save FileMediaSource: " + asset_path)
            if _media_sha256(movie) != expected_sha256:
                raise RuntimeError("Saved movie SHA256 mismatch")
            imported_paths = [str(media.get_path_name()).split(".", 1)[0]]
            media_metadata = {{
                "backend_class": "FileMediaSource",
                "source_sha256": expected_sha256,
                "movie_file": str(movie),
                "file_path": str(media.get_editor_property("file_path")),
                "saved": True,
            }}
        ''')


class MediaImporter(BaseImporter):
    asset_type_name = "video"

    def __init__(self, transport: Transport | None = None) -> None:
        super().__init__(default_dest_for_asset_type("video"), ASSET_TYPE_SUFFIXES["video"],
                         MediaImportScriptBuilder(), transport=transport)

    def execute(self, request: ImportRequest, dest_path: str) -> dict:
        script = self.builder.build_import_script(request, dest_path)
        payload = self.transport.execute_json(
            script + '\nresult = {"imported_paths": imported_paths, "metadata": media_metadata}\n')
        if not isinstance(payload, dict) or not payload.get("imported_paths"):
            raise RuntimeError("Media import did not return a saved FileMediaSource")
        return {"asset_type": request.type_key, "src_path": request.src_path,
                "dest_path": dest_path, **payload}
