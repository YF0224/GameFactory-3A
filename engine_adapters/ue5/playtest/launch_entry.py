"""UE5 launch entry resolution and diagnostics.

Exposes what map the project intends to start with, where it came from,
whether that map exists as a .umap file, and a classification of whether
the delivery is launchable or missing its configured startup map.
"""

from __future__ import annotations

import configparser
from dataclasses import dataclass
from pathlib import Path


@dataclass
class LaunchEntryResolution:
    """Result of resolving a UE5 project's launch entry.

    Attributes:
        configured_map: The map reference from config (e.g. "/Game/Maps/Main"),
                       empty string if no map configured or config absent.
        config_source: Where the configured_map came from (e.g.
                      "Config/DefaultEngine.ini [/Script/Engine.Engine].GameDefaultMap")
        resolved_path: Expected .umap file path relative to project root
                      (e.g. "Content/Maps/Main.umap"), None if no map configured.
        exists: Whether the resolved .umap file actually exists on disk.
        other_maps: List of other .umap files found in Content/, for diagnostics.
        classification: One of:
            - "LAUNCHABLE": Has a configured map and the file exists
            - "PRODUCT_MISSING_STARTUP_MAP": Configured map but file absent
            - "NO_CONFIGURED_MAP": No startup map configured (may use engine default)
            - "NO_CONFIG": Config file doesn't exist
    """
    configured_map: str
    config_source: str
    resolved_path: str | None
    exists: bool
    other_maps: list[str]
    classification: str


def resolve_launch_entry(project_root: Path) -> LaunchEntryResolution:
    """Resolve the UE5 project's intended startup map.

    Checks Config/DefaultEngine.ini for [/Script/Engine.Engine].GameDefaultMap
    or EditorStartupMap, resolves /Game/... references to Content/....umap paths,
    and classifies whether the project is launchable.

    Args:
        project_root: Path to the UE5 project root (containing Config/, Content/)

    Returns:
        LaunchEntryResolution with all diagnostic fields populated.
    """
    project_root = Path(project_root).resolve()
    config_path = project_root / "Config" / "DefaultEngine.ini"

    # Find all existing .umap files for diagnostics
    content_dir = project_root / "Content"
    other_maps = []
    if content_dir.is_dir():
        for umap in content_dir.rglob("*.umap"):
            if "/Intermediate/" not in str(umap):
                other_maps.append(str(umap.relative_to(project_root)))

    if not config_path.is_file():
        return LaunchEntryResolution(
            configured_map="",
            config_source="Config/DefaultEngine.ini (absent)",
            resolved_path=None,
            exists=False,
            other_maps=other_maps,
            classification="NO_CONFIG"
        )

    # Parse the ini file
    config = configparser.ConfigParser(strict=False, allow_no_value=True)
    try:
        # UE ini files may have duplicate keys; read_string handles them
        config.read_string(config_path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return LaunchEntryResolution(
            configured_map="",
            config_source="Config/DefaultEngine.ini (parse failed)",
            resolved_path=None,
            exists=False,
            other_maps=other_maps,
            classification="NO_CONFIG"
        )

    # Check multiple possible config locations
    candidates = [
        ("/Script/Engine.Engine", "GameDefaultMap"),
        ("/Script/Engine.Engine", "EditorStartupMap"),
        ("/Script/EngineSettings.GameMapsSettings", "GameDefaultMap"),
        ("/Script/EngineSettings.GameMapsSettings", "EditorStartupMap"),
    ]

    configured_map = ""
    config_source_detail = ""

    for section, key in candidates:
        if config.has_option(section, key):
            value = config.get(section, key).strip()
            if value:
                configured_map = value
                config_source_detail = f"[{section}].{key}"
                break

    if not configured_map:
        return LaunchEntryResolution(
            configured_map="",
            config_source=f"Config/DefaultEngine.ini (no GameDefaultMap/EditorStartupMap found)",
            resolved_path=None,
            exists=False,
            other_maps=other_maps,
            classification="NO_CONFIGURED_MAP"
        )

    # Resolve /Game/Maps/MainLevel or /Game/Maps/MainLevel.MainLevel to Content/.umap
    map_ref = configured_map
    if "." in map_ref:
        # Strip .MapName suffix
        map_ref = map_ref.split(".")[0]

    if map_ref.startswith("/Game/"):
        relative_path = map_ref[len("/Game/"):]
        resolved_path = f"Content/{relative_path}.umap"
    else:
        # Non-standard reference; treat as-is
        resolved_path = f"{map_ref}.umap"

    full_path = project_root / resolved_path
    exists = full_path.is_file()

    if exists:
        classification = "LAUNCHABLE"
    else:
        classification = "PRODUCT_MISSING_STARTUP_MAP"

    return LaunchEntryResolution(
        configured_map=configured_map,
        config_source=f"Config/DefaultEngine.ini {config_source_detail}",
        resolved_path=resolved_path,
        exists=exists,
        other_maps=other_maps,
        classification=classification
    )


__all__ = ["resolve_launch_entry", "LaunchEntryResolution"]
