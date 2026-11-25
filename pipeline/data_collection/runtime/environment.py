"""
pipeline/data_collection/environment.py

Machine/harness environment snapshot for trajectories (schema §4.1 依赖环境).

Captures what explains and (partially) reproduces a run: OS, Python, the
installed package list, GPU, agent CLI, model, and engine version. A small
summary is inlined into ``environment_ref``; the full snapshot (complete
package list, raw probe outputs) goes to the artifact store as uri+sha256.

Every probe is best-effort: bounded timeout, failure degrades to
``{"status": "unknown", "reason": ...}`` — collection never blocks or crashes
on a probe. Machine-absolute paths, hostnames and user names are never stored
(schema §8.2); workspace paths are used for detection only.

Stdlib only.
"""
from __future__ import annotations

import json
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

from ..core.event_writer import now_iso

_PROBE_TIMEOUT_SECONDS = 15.0


def _run(command: list[str], *, timeout: float = _PROBE_TIMEOUT_SECONDS) -> str | None:
    """Run one probe command; return stripped stdout or None on any failure."""
    try:
        finished = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if finished.returncode != 0:
        return None
    return finished.stdout.strip() or None


def _unknown(reason: str) -> dict[str, Any]:
    return {"status": "unknown", "reason": reason}


# ── probes ───────────────────────────────────────────────────────────────────

def capture_os() -> dict[str, Any]:
    info: dict[str, Any] = {
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
    }
    if info["system"] == "Darwin":
        product = _run(["sw_vers", "-productVersion"])
        if product:
            info["macos_version"] = product
    return info


def capture_python() -> dict[str, Any]:
    return {
        "version": platform.python_version(),
        "implementation": platform.python_implementation(),
        # Never the absolute interpreter path (schema §8.2): basename only.
        "executable_name": Path(sys.executable).name if sys.executable else None,
    }


def capture_packages() -> list[dict[str, Any]]:
    """Every installed distribution, name-sorted; a broken dist is skipped."""
    from importlib import metadata

    seen: dict[str, str | None] = {}
    for distribution in metadata.distributions():
        name = (distribution.metadata.get("Name") or "").strip()
        if not name:
            continue
        seen.setdefault(name, distribution.version)
    return [
        {"name": name, "version": seen[name]}
        for name in sorted(seen, key=str.lower)
    ]


def capture_gpu() -> dict[str, Any]:
    system = platform.system()
    names: list[str] = []
    driver: str | None = None
    if system == "Darwin":
        output = _run(["system_profiler", "SPDisplaysDataType"], timeout=30.0)
        if not output:
            return _unknown("system_profiler unavailable")
        for line in output.splitlines():
            if "Chipset Model:" in line:
                name = line.split("Chipset Model:", 1)[1].strip()
                if name and name not in names:
                    names.append(name)
    elif system == "Linux":
        output = _run(
            ["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"]
        )
        if not output:
            return _unknown("nvidia-smi unavailable")
        for line in output.splitlines():
            parts = [part.strip() for part in line.split(",", 1)]
            if parts and parts[0]:
                names.append(parts[0])
                if len(parts) > 1 and parts[1]:
                    driver = parts[1]
    else:
        return _unknown(f"no gpu probe for {system}")
    if not names:
        return _unknown("no gpu detected")
    gpu: dict[str, Any] = {"names": names}
    if driver:
        gpu["driver"] = driver
    return gpu


def capture_agent(name: str | None, *, known_version: str | None = None) -> dict[str, Any]:
    if not name:
        return _unknown("agent name not provided")
    agent: dict[str, Any] = {"name": name}
    if known_version:
        agent["version"] = known_version
        agent["source"] = "session_record"
        return agent
    output = _run([name, "--version"], timeout=5.0)
    agent["version"] = output.splitlines()[0].strip() if output else None
    agent["source"] = "cli_probe" if output else "unavailable"
    if not output:
        agent["reason"] = f"`{name} --version` failed or not on PATH"
    return agent


def capture_engine(engine: str | None, workspace: str | None) -> dict[str, Any]:
    """Detect the engine name/version from the project files when possible."""
    if not engine:
        return _unknown("engine not provided")
    result: dict[str, Any] = {"name": engine}
    if not workspace:
        result.update(_unknown("no workspace provided; version not detected"))
        return result
    root = Path(workspace)
    if engine in {"unity", "unity3d"}:
        version_file = root / "ProjectSettings" / "ProjectVersion.txt"
        if version_file.is_file():
            for line in version_file.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("m_EditorVersionWithRevision:"):
                    result["version"] = line.split(":", 1)[1].strip()
                    result["source"] = "project_file"
                    return result
        result.update(_unknown("ProjectSettings/ProjectVersion.txt not found"))
        return result
    if engine in {"godot", "godot4"}:
        project = root / "project.godot"
        if project.is_file():
            for line in project.read_text(encoding="utf-8", errors="replace").splitlines():
                if "config/features" in line:
                    text = line.split("(", 1)[1] if "(" in line else line
                    parts = [p for p in text.replace('"', " ").replace(")", " ").split() if p]
                    if parts:
                        result["version"] = parts[0]
                        result["source"] = "project_file"
                        return result
        result.update(_unknown("project.godot features not found"))
        return result
    if engine in {"ue", "ue5", "unreal"}:
        for project in sorted(root.glob("*.uproject")):
            try:
                association = json.loads(project.read_text(encoding="utf-8")).get("EngineAssociation")
            except (ValueError, OSError):
                continue
            if association:
                result["version"] = str(association)
                result["source"] = "project_file"
                return result
        result.update(_unknown("no .uproject with EngineAssociation"))
        return result
    if engine in {"blender", "three", "three_js", "threejs"}:
        if engine == "blender":
            output = _run(["blender", "--version"])
            if output:
                result["version"] = output.splitlines()[0].strip()
                result["source"] = "binary"
                return result
        else:
            package = root / "package.json"
            if package.is_file():
                try:
                    three = json.loads(package.read_text(encoding="utf-8")).get("dependencies", {}).get("three")
                except (ValueError, OSError):
                    three = None
                if three:
                    result["version"] = str(three)
                    result["source"] = "package_json"
                    return result
        result.update(_unknown("engine version probe unavailable"))
        return result
    result.update(_unknown(f"no version probe for engine {engine!r}"))
    return result


# ── assembly ─────────────────────────────────────────────────────────────────

def capture_environment(
    *,
    agent: str | None = None,
    agent_version: str | None = None,
    model: str | None = None,
    engine: str | None = None,
    workspace: str | None = None,
    artifact_store: Any = None,
) -> dict[str, Any]:
    """Build the trajectory ``environment_ref``: inline summary + full snapshot.

    The complete package list and raw probe outputs go to the artifact store;
    the inline summary keeps only bounded, path-free facts so the trajectory
    stays readable. Without an artifact store the snapshot is skipped with an
    explicit reason (never silently dropped).
    """
    os_info = capture_os()
    python_info = capture_python()
    packages = capture_packages()
    gpu = capture_gpu()
    agent_info = capture_agent(agent, known_version=agent_version)
    engine_info = capture_engine(engine, workspace)

    snapshot = {
        "captured_at": now_iso(),
        "os": os_info,
        "python": python_info,
        "gpu": gpu,
        "packages": packages,
        "probes": {
            "os": "sw_vers -productVersion" if os_info.get("macos_version") else None,
            "gpu": "system_profiler SPDisplaysDataType / nvidia-smi",
            "agent": f"{agent} --version" if agent else None,
        },
    }

    reference: dict[str, Any] = {
        # All facts below are observed on the collector host; the agent's own
        # shell/project interpreters and remote execution ends are NOT implied
        # (record them as separate snapshots at their actual source).
        "scope": "collector_host",
        "captured_at": snapshot["captured_at"],
        "os": os_info,
        "python": python_info,
        "gpu": gpu,
        "agent": agent_info,
        "engine": engine_info,
        "packages": {"count": len(packages)},
    }
    if model:
        reference["model"] = model

    if artifact_store is not None:
        payload = json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n"
        stored = artifact_store.put(payload, ext=".json", mime_type="application/json")
        reference["packages"]["snapshot"] = {
            "uri": stored["uri"],
            "sha256": stored["sha256"],
            "mime_type": stored["mime_type"],
            "size_bytes": stored.get("size_bytes"),
        }
    else:
        reference["packages"]["snapshot"] = None
        reference["packages"]["missing_reason"] = "no_artifact_store"

    return reference
