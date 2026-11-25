"""Stable project inspection operations for UEClient v1."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from ..config import UEClientConfig
from ..contracts import UEOperationResult


def _project_paths(
    project_path: Path,
) -> tuple[Path, Path, str]:
    if project_path.suffix.lower() == ".uproject":
        return (
            project_path.parent,
            project_path,
            project_path.stem,
        )
    return (
        project_path,
        project_path / f"{project_path.name}.uproject",
        project_path.name,
    )


def _editor_binary(ue_root: Path) -> Path:
    if os.name == "nt":
        relative = "Engine/Binaries/Win64/UnrealEditor.exe"
    elif sys_platform() == "Darwin":
        relative = (
            "Engine/Binaries/Mac/UnrealEditor.app"
            "/Contents/MacOS/UnrealEditor"
        )
    else:
        relative = "Engine/Binaries/Linux/UnrealEditor"
    return ue_root / relative


def sys_platform() -> str:
    import platform

    return platform.system()


def _validate_project_name(project_name: str) -> None:
    if not re.fullmatch(
        r"[A-Za-z][A-Za-z0-9_]*",
        project_name,
    ):
        raise ValueError(
            "Unreal C++ project name must start with a letter "
            "and contain only letters, digits, and underscores: "
            f"{project_name!r}"
        )


def _engine_plugin_entries(
    ue_root: Path,
) -> list[dict[str, Any]]:
    candidates = (
        (
            "PythonScriptPlugin",
            "Engine/Plugins/Experimental/"
            "PythonScriptPlugin/PythonScriptPlugin.uplugin",
        ),
        (
            "EditorScriptingUtilities",
            "Engine/Plugins/Editor/EditorScriptingUtilities/"
            "EditorScriptingUtilities.uplugin",
        ),
        (
            "RemoteControl",
            "Engine/Plugins/VirtualProduction/"
            "RemoteControl/RemoteControl.uplugin",
        ),
        (
            "RemoteControlWebInterface",
            "Engine/Plugins/VirtualProduction/"
            "RemoteControlWebInterface/"
            "RemoteControlWebInterface.uplugin",
        ),
        (
            "PixelStreaming",
            "Engine/Plugins/Media/PixelStreaming/"
            "PixelStreaming.uplugin",
        ),
        (
            "Interchange",
            "Engine/Plugins/Interchange/Runtime/"
            "Interchange.uplugin",
        ),
        (
            "InterchangeEditor",
            "Engine/Plugins/Interchange/Editor/"
            "InterchangeEditor.uplugin",
        ),
        (
            "USDImporter",
            "Engine/Plugins/Importers/USDImporter/"
            "USDImporter.uplugin",
        ),
    )
    return [
        {"Name": name, "Enabled": True}
        for name, relative_path in candidates
        if (ue_root / relative_path).is_file()
    ]


def _write_source_files(
    project_dir: Path,
    project_name: str,
) -> None:
    source_root = project_dir / "Source"
    module_root = source_root / project_name
    module_root.mkdir(parents=True, exist_ok=True)
    (module_root / f"{project_name}.Build.cs").write_text(
        "\n".join(
            (
                "using UnrealBuildTool;",
                "",
                f"public class {project_name} : ModuleRules",
                "{",
                (
                    f"    public {project_name}("
                    "ReadOnlyTargetRules Target) : base(Target)"
                ),
                "    {",
                (
                    "        PCHUsage = "
                    "PCHUsageMode.UseExplicitOrSharedPCHs;"
                ),
                "        PublicDependencyModuleNames.AddRange(",
                "            new[]",
                "            {",
                '                "Core",',
                '                "CoreUObject",',
                '                "Engine"',
                "            });",
                "    }",
                "}",
                "",
            )
        ),
        encoding="utf-8",
    )
    (module_root / f"{project_name}.cpp").write_text(
        "\n".join(
            (
                '#include "Modules/ModuleManager.h"',
                "",
                "IMPLEMENT_PRIMARY_GAME_MODULE(",
                "    FDefaultGameModuleImpl,",
                f"    {project_name},",
                f'    "{project_name}");',
                "",
            )
        ),
        encoding="utf-8",
    )
    for suffix, target_type in (
        ("", "Game"),
        ("Editor", "Editor"),
    ):
        target_name = f"{project_name}{suffix}"
        (
            source_root
            / f"{target_name}.Target.cs"
        ).write_text(
            "\n".join(
                (
                    "using UnrealBuildTool;",
                    "",
                    (
                        f"public class {target_name}Target "
                        ": TargetRules"
                    ),
                    "{",
                    (
                        f"    public {target_name}Target("
                        "TargetInfo Target) : base(Target)"
                    ),
                    "    {",
                    f"        Type = TargetType.{target_type};",
                    (
                        "        DefaultBuildSettings = "
                        "BuildSettingsVersion.V5;"
                    ),
                    (
                        "        IncludeOrderVersion = "
                        "EngineIncludeOrderVersion.Latest;"
                    ),
                    (
                        "        ExtraModuleNames.Add("
                        f'"{project_name}");'
                    ),
                    "    }",
                    "}",
                    "",
                )
            ),
            encoding="utf-8",
        )


def _write_project_files(
    project_dir: Path,
    project_file: Path,
    project_name: str,
    ue_root: Path,
    api_version: str,
) -> None:
    _validate_project_name(project_name)
    project_dir.mkdir(parents=True, exist_ok=True)
    content_roots = (
        "Avatars",
        "Motions",
        "Scenes",
        "Environments",
        "Props",
        "Weapons",
        "Materials",
        "Textures",
        "Effects",
        "Audio",
        "Sequences",
    )
    for name in content_roots:
        (
            project_dir
            / "Content"
            / "Imported"
            / name
        ).mkdir(parents=True, exist_ok=True)
    (project_dir / "Content" / "Maps").mkdir(
        parents=True,
        exist_ok=True,
    )
    (project_dir / "Plugins").mkdir(
        parents=True,
        exist_ok=True,
    )

    project_file.write_text(
        json.dumps(
            {
                "FileVersion": 3,
                "EngineAssociation": "",
                "Category": "3AGameFactory",
                "Description": (
                    "3AGameFactory generated Unreal project."
                ),
                "Modules": [
                    {
                        "Name": project_name,
                        "Type": "Runtime",
                        "LoadingPhase": "Default",
                    }
                ],
                "Plugins": _engine_plugin_entries(ue_root),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    config_dir = project_dir / "Config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "DefaultEngine.ini").write_text(
        "\n".join(
            (
                "[/Script/PythonScriptPlugin."
                "PythonScriptPluginSettings]",
                "bRemoteExecution=True",
                "",
            )
        ),
        encoding="utf-8",
    )
    _write_source_files(project_dir, project_name)
    (project_dir / ".a3game-ue.json").write_text(
        json.dumps(
            {
                "engine": "ue5",
                "api_version": api_version,
                "engine_root": str(ue_root),
                "project_file": str(project_file),
                "project_name": project_name,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


class UEProjectClient:
    def __init__(self, config: UEClientConfig) -> None:
        self._config = config

    def get_info(self) -> dict[str, Any]:
        project_file = self._config.project_file
        ue_root = self._config.ue_root
        return UEOperationResult.success(
            "project.get_info",
            payload={
                "api_version": self._config.api_version,
                "engine_version": self._config.engine_version,
                "ue_root": str(ue_root) if ue_root else "",
                "ue_root_exists": bool(
                    ue_root and ue_root.is_dir()
                ),
                "project_path": str(
                    self._config.project_path or ""
                ),
                "project_file": str(project_file or ""),
                "project_exists": bool(
                    project_file and project_file.is_file()
                ),
            },
        ).to_dict()

    def create(
        self,
        *,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        ue_root = self._config.ue_root
        project_path = self._config.project_path
        if ue_root is None:
            return UEOperationResult.failure(
                "project.create",
                "ue_root is not configured",
            ).to_dict()
        if project_path is None:
            return UEOperationResult.failure(
                "project.create",
                "project_path is not configured",
            ).to_dict()

        editor = _editor_binary(ue_root)
        if not editor.is_file():
            return UEOperationResult.failure(
                "project.create",
                f"Unreal Editor was not found: {editor}",
            ).to_dict()

        project_dir, project_file, project_name = (
            _project_paths(project_path)
        )
        try:
            _validate_project_name(project_name)
        except ValueError as exc:
            return UEOperationResult.failure(
                "project.create",
                str(exc),
            ).to_dict()
        if project_file.exists():
            return UEOperationResult.failure(
                "project.create",
                f"Project already exists: {project_file}",
            ).to_dict()

        payload = {
            "api_version": self._config.api_version,
            "dry_run": dry_run,
            "ue_root": str(ue_root),
            "editor": str(editor),
            "project_dir": str(project_dir),
            "project_file": str(project_file),
            "project_name": project_name,
            "editor_target": f"{project_name}Editor",
            "game_target": project_name,
            "plugins": _engine_plugin_entries(ue_root),
        }
        if dry_run:
            return UEOperationResult.success(
                "project.create",
                artifacts=[
                    {
                        "type": "unreal_project",
                        "path": str(project_file),
                        "state": "planned",
                    }
                ],
                payload=payload,
            ).to_dict()

        try:
            _write_project_files(
                project_dir,
                project_file,
                project_name,
                ue_root,
                self._config.api_version,
            )
        except Exception as exc:
            return UEOperationResult.failure(
                "project.create",
                f"{type(exc).__name__}: {exc}",
                payload=payload,
            ).to_dict()

        return UEOperationResult.success(
            "project.create",
            artifacts=[
                {
                    "type": "unreal_project",
                    "path": str(project_file),
                    "state": "ready",
                }
            ],
            payload=payload,
        ).to_dict()

    def validate(self) -> dict[str, Any]:
        errors: list[str] = []
        ue_root = self._config.ue_root
        project_file = self._config.project_file
        if ue_root is None:
            errors.append("ue_root is not configured")
        elif not ue_root.is_dir():
            errors.append(f"ue_root does not exist: {ue_root}")
        if self._config.project_path is None:
            errors.append("project_path is not configured")
        elif project_file is None:
            errors.append(
                "project_path does not resolve to exactly "
                "one .uproject file"
            )
        elif not project_file.is_file():
            errors.append(
                f"project file does not exist: {project_file}"
            )

        if errors:
            return UEOperationResult.failure(
                "project.validate",
                *errors,
                payload={
                    "api_version": self._config.api_version,
                },
            ).to_dict()
        return UEOperationResult.success(
            "project.validate",
            payload={
                "api_version": self._config.api_version,
                "project_file": str(project_file),
                "ue_root": str(ue_root),
            },
        ).to_dict()
