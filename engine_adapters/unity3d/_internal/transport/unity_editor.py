"""Private Unity editor subprocess transport.

Unity does not have Unreal's Python Remote Execution or HTTP Remote Control.
This transport uses the ``-batchmode -quit -executeMethod`` CLI pattern:

1. Write args to a JSON job file
2. Run ``Unity -batchmode -quit -projectPath <proj> -executeMethod <Class.Method>``
3. The C# script writes a JSON report to a temp file
4. The Python transport reads the JSON report and returns it
"""

from __future__ import annotations

import glob
import hashlib
import json
import os
import platform
import re
import subprocess
import tempfile
import time
from uuid import uuid4
from pathlib import Path
from typing import Any, Mapping

from ...config import UnityClientConfig


def has_injected_compilation_error(log: str) -> bool:
    """Attribute compiler diagnostics from harness-owned C# files to the harness.

    Test the diagnostic source path, not the missing type in its message: a
    delivered script mentioning a recorder type is still a product diagnostic.
    """
    sources = (
        "GameFactory3AInputDriver", "GameFactory3APlayTestRecorder",
        "GameFactory3AFrameTap", "GameFactory3AAudioTap",
    )
    for line in log.splitlines():
        if not re.search(r"\berror CS\d+", line, re.IGNORECASE):
            continue
        source = re.split(r"\(\d+\s*,|:\d+[:(]", line, maxsplit=1)[0]
        if re.search(r"(?:^|[/\\])(?:" + "|".join(sources) + r")\.cs$",
                     source.strip(), re.IGNORECASE):
            return True
    return False


def find_unity_binary(
    explicit: str | Path | None = None,
) -> Path | None:
    """Locate a Unity editor binary; newest installed version wins."""
    if explicit:
        path = Path(explicit).expanduser()
        if path.is_dir():
            candidates = _unity_binary_candidates(path)
            existing = next(
                (candidate for candidate in candidates if candidate.is_file()),
                None,
            )
            return existing or path
        return path
    env_value = (
        os.environ.get("A3GAME_UNITY_ROOT")
        or os.environ.get("AAAGF_UNITY")
    )
    if env_value:
        return Path(env_value)

    patterns = {
        "Windows": [
            r"C:\Program Files\Unity\Hub\Editor\*\Editor\Unity.exe",
        ],
        "Darwin": [
            "/Applications/Unity/Hub/Editor/*/Unity.app/Contents/MacOS/Unity",
        ],
        "Linux": [
            str(Path.home() / "Unity" / "Hub" / "Editor" / "*" / "Editor" / "Unity"),
        ],
    }.get(platform.system(), [])
    found = sorted(
        p for pattern in patterns for p in glob.glob(pattern)
    )
    return Path(found[-1]) if found else None


def _unity_binary_candidates(root: Path) -> list[Path]:
    """Return platform layouts accepted for an explicit Unity install root."""
    return [
        root / "Unity.app" / "Contents" / "MacOS" / "Unity",
        root / "Contents" / "MacOS" / "Unity",
        root / "Editor" / "Unity.exe",
        root / "Unity.exe",
        root / "Editor" / "Unity",
        root / "Unity",
    ]


def playtest_recorder_files() -> list[tuple[Path, Path]]:
    """Bundled observers in isolated assemblies, never a game's Editor asmdef.

    The recorder observes game providers through reflection. Its sole static
    runtime dependency is the read-only AudioTap, with an explicit assembly
    reference. No game assembly definition is modified.
    """
    root = Path(__file__).resolve().parents[2]
    base = Path("Assets/GameFactory3AEvaluation")
    return [
        (root / "import_generated/GameFactory3APlayTestRecorder.cs",
         base / "Editor/GameFactory3APlayTestRecorder.cs"),
        (root / "import_generated/GameFactory3ARuntimeInitializerRecorder.cs",
         base / "Editor/GameFactory3ARuntimeInitializerRecorder.cs"),
        (root / "import_generated/GameFactory3A.Evaluation.Editor.asmdef",
         base / "Editor/GameFactory3A.Evaluation.Editor.asmdef"),
        (root / "import_generated/GameFactory3AInputDriver.cs",
         base / "Editor/GameFactory3AInputDriver.cs"),
        (root / "runtime_generated/GameFactory3AFrameTap.cs",
         base / "Runtime/GameFactory3AFrameTap.cs"),
        (root / "runtime_generated/GameFactory3AAudioTap.cs",
         base / "Runtime/GameFactory3AAudioTap.cs"),
        (root / "runtime_generated/GameFactory3A.Evaluation.Runtime.asmdef",
         base / "Runtime/GameFactory3A.Evaluation.Runtime.asmdef"),
    ]


def _install_playtest_recorder(project_path: Path) -> list[Path]:
    """Install observers, updating only files whose ownership is attested.

    A reserved-looking directory alone is not ownership: validate *all* file
    collisions before any write or legacy cleanup. A journal permits future
    upgrades only while installed bytes still match our previous installation.
    """
    project_path = Path(project_path).resolve()
    files = [(source, project_path / relative)
             for source, relative in playtest_recorder_files()]
    journal = project_path / "Assets/GameFactory3AEvaluation/installation.json"
    legacy = project_path / "Assets/Editor/GameFactory3APlayTestRecorder.cs"
    legacy_meta = legacy.with_suffix(".cs.meta")
    allowed = {str(dest.relative_to(project_path)) for _, dest in files} | {str(legacy.relative_to(project_path))}
    # A symlinked destination (including any parent) is not our isolated copy.
    for target in [journal, legacy, legacy_meta] + [d for _, d in files]:
        for part in [target] + list(target.parents):
            if part == project_path: break
            if part.is_symlink():
                raise RuntimeError(f"evaluation observer collision; refusing symlink: {part}")
    owned = {}
    if journal.exists():
        try:
            previous = json.loads(journal.read_text(encoding="utf-8"))
            owned = previous["files"]
            if (previous.get("schema") != "unity-observer-installation.v1" or
                not isinstance(owned, dict) or not set(owned).issubset(allowed) or
                any(not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{64}", v) for v in owned.values())):
                raise ValueError("invalid ownership schema/path/digest")
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise RuntimeError(f"invalid observer installation journal; refusing overwrite: {journal}") from error
    digest = lambda data: hashlib.sha256(data).hexdigest()
    # Complete preflight, including the old single-file path, before ANY write.
    for source, destination in files:
        if destination.exists():
            current = destination.read_bytes()
            relative = str(destination.relative_to(project_path))
            if current != source.read_bytes() and owned.get(relative) != digest(current):
                raise RuntimeError(f"evaluation observer collision; refusing overwrite: {destination}")
    migration = None
    if legacy.exists():
        data = legacy.read_bytes()
        recorder = next((source for source, dest in files if dest.name == legacy.name), None)
        if not ((recorder is not None and data == recorder.read_bytes()) or
                owned.get(str(legacy.relative_to(project_path))) == digest(data)):
            raise RuntimeError(f"unattested legacy observer; refusing overwrite or duplicate class: {legacy}")
        migration = {"source": str(legacy.relative_to(project_path)), "sha256": digest(data)}
        archive = project_path / "Library/GameFactory3A/observer_migrations" / digest(data)
        # No unverified gameplay source is ever deleted. Exact owned bytes and
        # associated Unity metadata are preserved before removing the old class.
        archive.mkdir(parents=True, exist_ok=True)
        for old in [legacy, legacy_meta]:
            if old.exists():
                archived = archive / old.name
                if archived.exists() and archived.read_bytes() != old.read_bytes():
                    raise RuntimeError(f"legacy observer archive collision: {archived}")
                archived.write_bytes(old.read_bytes())
        migration["archive"] = str(archive.relative_to(project_path))
    for source, destination in files:
        destination.parent.mkdir(parents=True, exist_ok=True)
        data = source.read_bytes()
        if not destination.is_file() or destination.read_bytes() != data:
            temporary = destination.with_name(destination.name + ".install.tmp")
            temporary.write_bytes(data)
            temporary.replace(destination)
    if migration is not None:
        for old in [legacy, legacy_meta]:
            if old.exists(): old.unlink()
    record = {"schema": "unity-observer-installation.v1",
              "files": {str(dest.relative_to(project_path)): digest(source.read_bytes()) for source, dest in files}}
    if migration is not None: record["legacy_migration"] = migration
    temporary = journal.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    temporary.replace(journal)
    return [destination for _, destination in files]


def install_editor_script(
    project_path: Path | None,
    class_method: str,
) -> Path | None:
    """Install a bundled Editor script required by an executeMethod call."""
    if project_path is None or not project_path.is_dir():
        return None
    class_name = str(class_method or "").split(".", 1)[0].strip()
    if not class_name:
        return None
    if class_name == "GameFactory3APlayTestRecorder":
        return _install_playtest_recorder(project_path)[0]
    source = (
        Path(__file__).resolve().parents[2]
        / "import_generated"
        / f"{class_name}.cs"
    )
    if not source.is_file():
        return None
    destination = project_path / "Assets" / "Editor" / source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_bytes = source.read_bytes()
    if not destination.is_file() or destination.read_bytes() != source_bytes:
        destination.write_bytes(source_bytes)
    return destination


def install_editor_scripts(
    project_path: Path | None,
    class_method: str,
) -> list[Path]:
    """Install an Editor entry point and its bundled Unity-native helpers."""
    installed: list[Path] = []
    if (project_path is not None and project_path.is_dir()
            and str(class_method or "").split(".", 1)[0].strip() in {"GameFactory3APlayTestRecorder", "GameFactory3ARuntimeInitializerRecorder"}):
        return _install_playtest_recorder(project_path)
    entry = install_editor_script(project_path, class_method)
    if entry is not None:
        installed.append(entry)
    class_name = str(class_method or "").split(".", 1)[0].strip()
    dependencies = {
        "ImportGeneratedAvatar": ("RepairImportedModelMaterials",),
        "ImportGeneratedMesh": ("RepairImportedModelMaterials",),
        "GenerateGame": (
            "GameFactory3AEditorBridge",
            "ImportBatch",
            "ImportGeneratedAvatar",
            "RepairImportedModelMaterials",
            "ImportGeneratedMotion",
            "ImportGeneratedMesh",
            "ImportGeneratedMaterial",
            "ImportGeneratedTexture",
            "ImportGeneratedScene",
            "ImportNativeScene",
            "ImportUnityPackage",
            "ComposeScene",
            "BuildPlayer",
        ),
    }.get(class_name, ())
    source_root = Path(__file__).resolve().parents[2] / "import_generated"
    if project_path is None or not project_path.is_dir():
        return installed
    destination_root = project_path / "Assets" / "Editor"
    destination_root.mkdir(parents=True, exist_ok=True)
    for dependency in dependencies:
        source = source_root / f"{dependency}.cs"
        destination = destination_root / source.name
        if not source.is_file():
            continue
        source_bytes = source.read_bytes()
        if not destination.is_file() or destination.read_bytes() != source_bytes:
            destination.write_bytes(source_bytes)
        if destination not in installed:
            installed.append(destination)
    return installed


def install_editor_bridge(project_path: Path | None) -> Path | None:
    """Install the generic live-Editor job bridge into one Unity project."""
    if project_path is None or not project_path.is_dir():
        return None
    source = (
        Path(__file__).resolve().parents[2]
        / "import_generated"
        / "GameFactory3AEditorBridge.cs"
    )
    if not source.is_file():
        return None
    destination = project_path / "Assets" / "Editor" / source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_bytes = source.read_bytes()
    if not destination.is_file() or destination.read_bytes() != source_bytes:
        destination.write_bytes(source_bytes)
    return destination


def _editor_instance_is_live(project_path: Path) -> bool:
    instance = project_path / "Library" / "EditorInstance.json"
    if not instance.is_file():
        return False
    try:
        payload = json.loads(instance.read_text(encoding="utf-8"))
        process_id = int(payload.get("process_id") or 0)
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    if process_id <= 0:
        return False
    try:
        os.kill(process_id, 0)
        return True
    except PermissionError:
        # Managed macOS runners can deny process signalling even for the
        # user's own GUI app. Unity owns these two files and removes them on a
        # normal exit, so together they are the best non-privileged liveness
        # signal available to the client.
        return (project_path / "Temp" / "UnityLockfile").exists()
    except (OSError, ProcessLookupError):
        return False


def _licensing_diagnostic(
    process_log: str,
    returncode: int | None,
) -> dict[str, Any] | None:
    """Classify Unity startup failures caused by its local license daemon.

    Unity emits these messages before it loads the project or compiles C#.
    They are host prerequisites, so callers need a distinct blocked result
    instead of treating them as an import/build failure.
    """
    log = str(process_log or "")
    lowered = log.casefold()
    fatal_markers = (
        "ipc channel to licensingclient doesn't exist",
        "ipc channel to licensingclient does not exist",
        "failed to connect to licenseclient",
        "connection to channel: \"licenseclient",
        "failed to handshake to channel",
        "unsupported protocol version",
        "timed out waiting for the licenseclient",
        "timed out waiting for licensingclient",
        "licensingclient has failed validation",
    )
    marker = next(
        (item for item in fatal_markers if item in lowered),
        None,
    )
    connected = (
        "successfully connected to licensingclient" in lowered
        or "connected to licensingclient" in lowered
    )
    # Hub can probe an older unversioned daemon first.  That probe may log a
    # protocol/signature error before Unity connects to its versioned daemon;
    # successful connection and exit mean the intermediate warning is benign.
    if connected and returncode == 0:
        return None
    # Exit 199 is Unity's licensing/bootstrap abort on the supported Editor.
    if marker is None and returncode != 199:
        return None
    if marker is None:
        marker = "unity exit code 199"
    tail = log[-4000:] if log else ""
    return {
        "blocked": True,
        "blocked_stage": "licensing",
        "reason": marker,
        "connected_before_failure": connected,
        "log_tail": tail,
        "action": (
            "Activate this Unity Editor installation in Unity Hub (or keep a "
            "licensed Editor session open), then retry the UnityClient call. "
            "3AGameFactory cannot bypass Unity licensing."
        ),
    }


def _licensing_error(diagnostic: Mapping[str, Any]) -> str:
    return (
        "Unity batchmode is blocked by LicensingClient: "
        f"{diagnostic.get('reason', 'license IPC failure')}. "
        f"{diagnostic.get('action', '')}"
    ).strip()


class UnityEditorTransport:
    """Subprocess-based transport for Unity editor batchmode operations."""

    def __init__(
        self,
        config: UnityClientConfig | None = None,
    ) -> None:
        self.config = config or UnityClientConfig.resolve()
        self._processes: dict[int, subprocess.Popen[Any]] = {}

    @property
    def unity_binary(self) -> Path | None:
        return find_unity_binary(self.config.unity_root)

    def _execute_live_editor(
        self,
        class_method: str,
        *,
        job_path: Path,
        report_path: Path,
        timeout: int,
    ) -> dict[str, Any] | None:
        project_path = self.config.project_path
        if project_path is None or not _editor_instance_is_live(project_path):
            return None
        try:
            bridge_path = install_editor_bridge(project_path)
            installed_scripts = install_editor_scripts(project_path, class_method)
        except OSError as exc:
            return {
                "ok": False,
                "error": (
                    "Unity live Editor scripts could not be installed: "
                    f"{type(exc).__name__}: {exc}"
                ),
                "transport": "live_editor_bridge",
            }
        if bridge_path is None:
            return None

        bridge_root = project_path / "Library" / "GameFactory3A"
        inbox = bridge_root / "inbox"
        completed = bridge_root / "completed"
        inbox.mkdir(parents=True, exist_ok=True)
        completed.mkdir(parents=True, exist_ok=True)
        request_id = uuid4().hex
        request_path = inbox / f"{request_id}.json"
        status_path = completed / f"{request_id}.json"
        request_path.write_text(
            json.dumps(
                {
                    "request_id": request_id,
                    "class_method": class_method,
                    "job_path": str(job_path),
                    "report_path": str(report_path),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        started = time.monotonic()
        deadline = started + timeout
        while time.monotonic() < deadline:
            if status_path.is_file():
                break
            if not _editor_instance_is_live(project_path):
                return {
                    "ok": False,
                    "error": "Unity GUI Editor exited while processing the live job",
                    "transport": "live_editor_bridge",
                    "request_id": request_id,
                }
            time.sleep(0.1)
        else:
            return {
                "ok": False,
                "error": f"Unity live Editor job timed out after {timeout}s",
                "timed_out": True,
                "transport": "live_editor_bridge",
                "request_id": request_id,
                "request_path": str(request_path),
            }

        try:
            status = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return {
                "ok": False,
                "error": f"Unity live Editor status is invalid: {type(exc).__name__}: {exc}",
                "transport": "live_editor_bridge",
                "request_id": request_id,
            }
        if not status.get("ok"):
            return {
                "ok": False,
                "error": str(status.get("error") or "Unity live Editor job failed"),
                "transport": "live_editor_bridge",
                "request_id": request_id,
            }
        if not report_path.is_file():
            return {
                "ok": False,
                "error": "Unity live Editor completed without a report file",
                "transport": "live_editor_bridge",
                "request_id": request_id,
            }
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return {
                "ok": False,
                "error": f"Unity live Editor report is invalid: {type(exc).__name__}: {exc}",
                "transport": "live_editor_bridge",
                "request_id": request_id,
            }
        if not isinstance(report, dict):
            return {
                "ok": False,
                "error": "Unity live Editor report root must be a JSON object",
                "transport": "live_editor_bridge",
                "request_id": request_id,
            }
        report.setdefault("transport", "live_editor_bridge")
        report.setdefault("request_id", request_id)
        report.setdefault("class_method", class_method)
        report.setdefault("project_path", str(project_path))
        report.setdefault("job_path", str(job_path))
        report.setdefault("report_path", str(report_path))
        report.setdefault("editor_bridge", str(bridge_path))
        if installed_scripts:
            report.setdefault("editor_scripts", [str(path) for path in installed_scripts])
        report.setdefault("elapsed_seconds", time.monotonic() - started)
        return report

    def execute_method(
        self,
        class_method: str,
        *,
        args: dict[str, Any] | None = None,
        timeout: int | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Run a Unity ``-executeMethod`` invocation and return the JSON report."""
        unity = self.unity_binary
        project_path = self.config.project_path

        resolved_timeout = timeout or self.config.editor_batchmode_timeout
        report_path = Path(
            tempfile.mktemp(
                suffix=".json",
                prefix="unity_report_",
            )
        )
        job_args = dict(args or {})
        job_path = Path(
            tempfile.mktemp(
                suffix=".json",
                prefix="unity_job_",
            )
        )
        job_path.parent.mkdir(parents=True, exist_ok=True)
        job_path.write_text(
            json.dumps(job_args, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        log_path = report_path.with_suffix(".unity.log")

        command = [
            str(unity) if unity else "Unity",
            "-batchmode",
            "-quit",
            "-nographics",
            "-projectPath",
            str(project_path) if project_path else "",
            "-executeMethod",
            str(class_method),
            "-logFile",
            str(log_path),
            "--job",
            str(job_path),
            "--report",
            str(report_path),
        ]

        payload: dict[str, Any] = {
            "command": command,
            "class_method": class_method,
            "project_path": str(project_path) if project_path else "",
            "job_path": str(job_path),
            "report_path": str(report_path),
            "log_path": str(log_path),
            "dry_run": dry_run,
            "timeout": resolved_timeout,
        }
        if dry_run:
            return {"ok": True, "dry_run": True, **payload}

        if unity is None or not unity.exists():
            return {
                "ok": False,
                "error": (
                    f"Unity editor binary was not found: {unity or '<not configured>'}"
                ),
            }
        if project_path is None or not project_path.is_dir():
            return {
                "ok": False,
                "error": (
                    f"Unity project path is not a directory: {project_path}"
                ),
            }

        # Prefer one already-open, licensed GUI Editor. This avoids spawning a
        # second LicensingClient and also keeps import/compose/build work in a
        # single project session. Batchmode remains the fallback when no live
        # instance is available.
        live_result = self._execute_live_editor(
            class_method,
            job_path=job_path,
            report_path=report_path,
            timeout=resolved_timeout,
        )
        if live_result is not None:
            return live_result

        try:
            bridge_script = install_editor_bridge(project_path)
            installed_scripts = install_editor_scripts(
                project_path,
                class_method,
            )
        except OSError as exc:
            return {
                "ok": False,
                "error": (
                    "Unity Editor script could not be installed for "
                    f"{class_method}: {type(exc).__name__}: {exc}"
                ),
                **payload,
            }
        if installed_scripts:
            payload["editor_scripts"] = [str(path) for path in installed_scripts]
        if bridge_script is not None:
            payload["editor_bridge"] = str(bridge_script)

        try:
            completed = subprocess.run(
                command,
                # Unity editor scripts receive project-relative Assets paths.
                # Keep the process cwd at the generated project root so their
                # File/Directory operations and AssetDatabase paths refer to
                # the same project instead of the caller's workspace.
                cwd=str(project_path),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=resolved_timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            payload["returncode"] = None
            payload["timed_out"] = True
            payload["stdout"] = str(exc.stdout or "")
            payload["stderr"] = str(exc.stderr or "")
            process_log = (
                log_path.read_text(
                    encoding="utf-8",
                    errors="replace",
                )
                if log_path.is_file()
                else payload["stdout"]
            )
            payload["stdout"] = process_log
            licensing = _licensing_diagnostic(process_log, None)
            if licensing is not None:
                payload["license_status"] = licensing
                return {
                    "ok": False,
                    "blocked": True,
                    "blocked_stage": "licensing",
                    "error": _licensing_error(licensing),
                    "errors": [_licensing_error(licensing)],
                    **payload,
                }
            return {
                "ok": False,
                "error": (
                    f"Unity batchmode timed out after {resolved_timeout}s"
                ),
                **payload,
            }
        except Exception as exc:
            return {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                **payload,
            }

        payload["returncode"] = completed.returncode
        process_log = (
            log_path.read_text(
                encoding="utf-8",
                errors="replace",
            )
            if log_path.is_file()
            else ""
        )
        payload["stdout"] = process_log
        payload["stderr"] = ""

        licensing = _licensing_diagnostic(
            process_log,
            completed.returncode,
        )
        if licensing is not None:
            payload["license_status"] = licensing
            return {
                "ok": False,
                "blocked": True,
                "blocked_stage": "licensing",
                "error": _licensing_error(licensing),
                "errors": [
                    _licensing_error(licensing),
                    *(
                        [f"Unity exited with code {completed.returncode}"]
                        if completed.returncode is not None
                        else []
                    ),
                ],
                **payload,
            }

        if report_path.is_file():
            try:
                report = json.loads(
                    report_path.read_text(encoding="utf-8")
                )
            except json.JSONDecodeError as exc:
                return {
                    "ok": False,
                    "error": (
                        f"Unity report JSON could not be parsed: "
                        f"{type(exc).__name__}: {exc}"
                    ),
                    **payload,
                }
            if isinstance(report, dict):
                report.setdefault("returncode", completed.returncode)
                report.setdefault("stdout", process_log)
                report.setdefault("stderr", "")
                report.setdefault("class_method", class_method)
                report.setdefault("project_path", str(project_path))
                report.setdefault("job_path", str(job_path))
                report.setdefault("report_path", str(report_path))
                report.setdefault("log_path", str(log_path))
                if completed.returncode != 0 and report.get("ok", True):
                    report["ok"] = False
                    report.setdefault("errors", [])
                    report["errors"] = list(report["errors"]) + [
                        f"Unity exited with code {completed.returncode}"
                    ]
                return report
            return {
                "ok": False,
                "error": "Unity report root must be a JSON object",
                **payload,
            }
        return {
            "ok": False,
            "error": (
                f"Unity wrote no report file (exit {completed.returncode}); "
                f"see log: {log_path}"
            ),
            **payload,
        }

    def execute_json(
        self,
        class_method: str,
        *,
        args: dict[str, Any] | None = None,
        timeout: int = 120,
    ) -> Any:
        """Run an editor method and return the report JSON directly."""
        result = self.execute_method(
            class_method,
            args=args,
            timeout=timeout,
        )
        return result

    def is_ready(self, timeout: float = 5.0) -> bool:
        """Check if Unity editor is running and responsive."""
        unity = self.unity_binary
        if unity is None or not unity.exists():
            return False
        project_path = self.config.project_path
        if project_path is None or not project_path.is_dir():
            return False
        try:
            result = self.execute_method(
                "StatusCheck.RunFromCLI",
                timeout=int(timeout),
            )
            return bool(result.get("ok"))
        except Exception:
            return False

    def is_editor_live(self) -> bool:
        """Return whether this configured project has a live GUI Editor."""
        project_path = self.config.project_path
        return bool(project_path and _editor_instance_is_live(project_path))

    def wait_for_editor(self, timeout: float = 120.0) -> dict[str, Any]:
        """Wait for a GUI Editor launched for this project to initialize."""
        project_path = self.config.project_path
        if project_path is None:
            return {"ok": False, "error": "project_path is not configured"}
        deadline = time.monotonic() + max(float(timeout), 0.1)
        while time.monotonic() < deadline:
            if _editor_instance_is_live(project_path):
                return {
                    "ok": True,
                    "transport": "live_editor_bridge",
                    "project_path": str(project_path),
                }
            time.sleep(0.25)
        return {
            "ok": False,
            "error": f"Unity GUI Editor did not become ready after {timeout:.0f}s",
            "transport": "live_editor_bridge",
            "project_path": str(project_path),
        }

    def launch_editor(
        self,
        scene_path: str = "",
        extra_args: list[str] | None = None,
    ) -> subprocess.Popen[Any]:
        """Launch the Unity editor with GUI for runtime sessions."""
        unity = self.unity_binary
        project_path = self.config.project_path
        if unity is None or not unity.exists():
            raise FileNotFoundError(
                f"Unity editor binary was not found: {unity}"
            )
        if project_path is None or not project_path.is_dir():
            raise FileNotFoundError(
                f"Unity project path is not a directory: {project_path}"
            )
        # Keep GUI Editor logs inside the generated project. Unity's default
        # global Editor.log is shared by every project and can trigger a
        # macOS replace-file dialog when another Unity instance owns it,
        # leaving a client-launched Editor stuck before it creates its
        # EditorInstance marker.
        project_log = project_path / "Library" / "GameFactory3A" / "Editor.log"
        project_log.parent.mkdir(parents=True, exist_ok=True)
        command = [
            str(unity),
            "-projectPath",
            str(project_path),
            "-logFile",
            str(project_log),
        ]
        resolved_extra_args = [str(arg) for arg in (extra_args or [])]
        if os.environ.get("GAMEFACTORY_UNITY_CAPTURE_POLICY") == "graphics_batch_render_v2":
            if "-nographics" in resolved_extra_args:
                raise RuntimeError("background rendering requires a graphics device")
            if "-batchmode" not in resolved_extra_args:
                resolved_extra_args.insert(0, "-batchmode")
        if "-executeMethod" in resolved_extra_args:
            index = resolved_extra_args.index("-executeMethod")
            if index + 1 < len(resolved_extra_args):
                install_editor_scripts(
                    project_path,
                    resolved_extra_args[index + 1],
                )
        if scene_path:
            command.append(str(scene_path))
        command.append(
            f"-A3GameRuntimeInputPort={self.config.runtime_port}"
        )
        command.extend(resolved_extra_args)

        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
        process = subprocess.Popen(
            command,
            cwd=str(project_path),
            creationflags=creationflags,
            start_new_session=os.name != "nt",
        )
        self._processes[process.pid] = process
        return process

    def stop_editor(self, process_id: int) -> bool:
        """Terminate a tracked Unity editor process."""
        process = self._processes.get(int(process_id))
        if process is None:
            return False
        if process.poll() is None:
            process.terminate()
        self._processes.pop(process.pid, None)
        return True
