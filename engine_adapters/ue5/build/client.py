"""Stable Unreal build operations for UEClient v1."""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import subprocess
import signal
import tempfile
import time
from pathlib import Path
from typing import Any

from ..config import UEClientConfig
from ..contracts import UEDiagnostic, UEOperationResult


_BUILD_LOCK_PATH = Path(tempfile.gettempdir()) / "gamefactory-ue-build.lock"
_CONFLICTING_INSTANCE = re.compile(
    r"ConflictingInstance|UnrealBuildTool_Mutex", re.IGNORECASE
)


@contextlib.contextmanager
def _serialized_build(deadline: float | None = None):
    """Serialize evaluator-owned UBT launches without touching other builds."""
    if os.name == "nt":
        # UBT's own -WaitMutex remains the source of truth on Windows.
        yield
        return

    import fcntl

    with _BUILD_LOCK_PATH.open("a", encoding="utf-8") as lock_file:
        if deadline is None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        else:
            while True:
                try:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("Timed out waiting for evaluator UE build lock")
                    time.sleep(min(0.1, remaining))
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _sys_platform() -> str:
    import platform

    return platform.system()


def _build_script(ue_root: Path) -> tuple[list[str], str]:
    if os.name == "nt":
        return (
            [
                str(
                    ue_root
                    / "Engine"
                    / "Build"
                    / "BatchFiles"
                    / "Build.bat"
                )
            ],
            "Win64",
        )
    if _sys_platform() == "Darwin":
        return (
            [
                "bash",
                str(
                    ue_root
                    / "Engine"
                    / "Build"
                    / "BatchFiles"
                    / "Mac"
                    / "Build.sh"
                ),
            ],
            "Mac",
        )
    return (
        [
            "bash",
            str(
                ue_root
                / "Engine"
                / "Build"
                / "BatchFiles"
                / "Linux"
                / "Build.sh"
            ),
        ],
        "Linux",
    )


def _diagnostics(output: str) -> list[UEDiagnostic]:
    pattern = re.compile(
        r"^(?P<file>.*?)(?:\((?P<line>\d+)\))?"
        r":\s*(?P<severity>error|warning)"
        r"(?:\s+(?P<code>[A-Za-z]+\d+))?:\s*"
        r"(?P<message>.+)$",
        flags=re.IGNORECASE,
    )
    result = []
    for line in output.splitlines():
        match = pattern.match(line.strip())
        if not match:
            continue
        result.append(
            UEDiagnostic(
                severity=match.group("severity").lower(),
                message=match.group("message").strip(),
                code=str(match.group("code") or ""),
                file=str(match.group("file") or "").strip(),
                line=(
                    int(match.group("line"))
                    if match.group("line")
                    else None
                ),
                source="unreal_build_tool",
            )
        )
    return result


def _default_editor_target(project_file: Path) -> tuple[str, dict[str, Any]]:
    """Resolve one literal authored Editor target; never infer from a game name.

    This is a conservative source selector, not a C# evaluator. Ambiguous or
    conditional rules need an explicit caller target, not a guessed build.
    Content-only projects retain the previous UBT conventional default.
    """
    root = project_file.parent.resolve()
    source = root / "Source"
    files = sorted(source.rglob("*.Target.cs")) if source.exists() else []
    if not files:
        return project_file.stem + "Editor", {"policy": "legacy_no_authored_target.v1", "files": []}
    evidence, editors = [], []
    for path in files:
        if any(p.is_symlink() for p in (path, *path.parents)) or not path.resolve().is_relative_to(root):
            raise ValueError("Authored target must be an independent project file: " + str(path))
        raw = path.read_bytes()
        # Mask comments and string/char contents before finding declarations.
        tokens = r'//[^\n]*|/\*[\s\S]*?\*/|@"(?:""|[^"])*"|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\''
        code = re.sub(tokens, lambda m: "\n" * m.group().count("\n") + " ", raw.decode("utf-8-sig"))
        assignments = re.findall(r"\bType\s*=\s*TargetType\.(\w+)\s*;", code)
        name = path.name[:-len(".Target.cs")]
        evidence.append({"path": str(path.relative_to(root)), "sha256": hashlib.sha256(raw).hexdigest(),
                         "literal_types": assignments})
        if "Editor" not in assignments:
            # Dynamic rules cannot safely be ruled out as another Editor target.
            if len(assignments) != 1 or re.search(r"^\s*#", code, re.M):
                raise ValueError("Nonliteral/conditional authored target requires explicit target: " + str(path))
            continue
        classes = re.findall(r"\bclass\s+(\w+)\s*:\s*TargetRules\b", code)
        if (assignments != ["Editor"] or classes != [name + "Target"]
                or len(re.findall(r"\bType\s*=(?!=)", code)) != 1
                or re.search(r"^\s*#|\b(?:if|switch|for|while)\s*\(", code, re.M)
                or not re.search(r"\b" + re.escape(name + "Target") + r"\s*\(\s*TargetInfo\s+\w+\s*\)", code)):
            raise ValueError("Ambiguous/nonliteral authored Editor target: " + str(path))
        editors.append(name)
    if len(editors) != 1:
        raise ValueError("Expected one authored TargetType.Editor; found " + str(editors))
    return editors[0], {"policy": "unique_authored_editor.v1", "files": evidence, "target": editors[0]}


class UEBuildClient:
    def __init__(self, config: UEClientConfig) -> None:
        self._config = config

    def project(
        self,
        *,
        target: str = "",
        configuration: str = "Development",
        clean: bool = False,
        dry_run: bool = False,
        timeout: float | None = None,
        wait_mutex: bool = True,
    ) -> dict[str, Any]:
        ue_root = self._config.ue_root
        project_file = self._config.project_file
        if ue_root is None:
            return UEOperationResult.failure(
                "build.project",
                "ue_root is not configured",
            ).to_dict()
        if project_file is None or not project_file.is_file():
            return UEOperationResult.failure(
                "build.project",
                "project_path does not resolve to an existing "
                ".uproject file",
            ).to_dict()

        prefix, platform = _build_script(ue_root)
        script_path = Path(prefix[-1])
        if not script_path.is_file():
            return UEOperationResult.failure(
                "build.project",
                f"Unreal build script was not found: {script_path}",
            ).to_dict()
        try:
            if str(target).strip():
                resolved_target = str(target).strip()
                target_selection = {"policy": "explicit_target.v1", "target": resolved_target}
            else:
                resolved_target, target_selection = _default_editor_target(project_file)
        except (OSError, UnicodeError, ValueError) as exc:
            return UEOperationResult.failure("build.project", str(exc)).to_dict()
        command = [
            *prefix,
            resolved_target,
            platform,
            str(configuration or "Development"),
            f"-Project={project_file}",
        ]
        # Without -WaitMutex UBT still honors its global lock and reports a
        # competing build immediately; this never bypasses mutual exclusion.
        if wait_mutex:
            command.append("-WaitMutex")
        if clean:
            command.append("-Clean")
        payload = {
            "command": command,
            "cwd": str(project_file.parent),
            "target": resolved_target,
            "target_selection": target_selection,
            "platform": platform,
            "configuration": configuration,
            "clean": clean,
            "dry_run": dry_run,
            "wait_mutex": wait_mutex,
        }
        if dry_run:
            return UEOperationResult.success(
                "build.project",
                payload=payload,
            ).to_dict()

        conflict_retries = 0
        attempt_results: list[dict[str, Any]] = []
        payload["attempt_results"] = attempt_results
        completed = None
        deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
        # Waiting for our lock, UBT's mutex, retries and compilation share one
        # budget. A queued evaluator must not wait forever before its timer starts.
        try:
            build_lock = contextlib.ExitStack()
            build_lock.enter_context(_serialized_build(deadline))
        except TimeoutError as exc:
            payload.update(timeout=True, timeout_phase="evaluator_build_lock",
                           attempts=0, conflict_retries=0)
            return UEOperationResult.failure(
                "build.project", str(exc), payload=payload,
            ).to_dict()
        with build_lock:
            attempt = 0
            while True:
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    payload.update(timeout=True, timeout_phase="build_budget",
                                   attempts=len(attempt_results),
                                   conflict_retries=conflict_retries)
                    return UEOperationResult.failure(
                        "build.project", "Unreal build exhausted its total timeout budget",
                        payload=payload,
                    ).to_dict()
                attempt_command = list(command)
                # A caller that requested fail-fast behavior still gets one
                # bounded recovery path. The evaluator itself always asks for
                # -WaitMutex, but this keeps the public client honest too.
                if attempt and "-WaitMutex" not in attempt_command:
                    attempt_command.append("-WaitMutex")
                try:
                    process = subprocess.Popen(
                        attempt_command,
                        cwd=project_file.parent,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        start_new_session=os.name != "nt",
                    )
                    try:
                        stdout, stderr = process.communicate(timeout=remaining)
                    except subprocess.TimeoutExpired:
                        # Only this client's build group is stopped. Unrelated
                        # builds (including original generation runs) remain
                        # untouched.
                        if os.name != "nt":
                            os.killpg(process.pid, signal.SIGTERM)
                        else:
                            process.terminate()
                        try:
                            stdout, stderr = process.communicate(timeout=10)
                        except subprocess.TimeoutExpired:
                            if os.name != "nt":
                                os.killpg(process.pid, signal.SIGKILL)
                            else:
                                process.kill()
                            stdout, stderr = process.communicate()
                        attempt_results.append({
                            "command": attempt_command, "stdout": stdout,
                            "stderr": stderr, "returncode": process.returncode,
                            "timeout": True,
                        })
                        payload.update(
                            stdout=stdout,
                            stderr=stderr,
                            returncode=process.returncode,
                            timeout=True,
                            attempts=attempt + 1,
                            conflict_retries=conflict_retries,
                        )
                        return UEOperationResult.failure(
                            "build.project",
                            "Unreal build timed out; build process group stopped",
                            payload=payload,
                        ).to_dict()
                    completed = subprocess.CompletedProcess(
                        attempt_command, process.returncode, stdout, stderr
                    )
                except Exception as exc:
                    attempt_results.append({"command": attempt_command,
                        "error": f"{type(exc).__name__}: {exc}"})
                    payload.update(attempts=len(attempt_results),
                        conflict_retries=conflict_retries)
                    return UEOperationResult.failure(
                        "build.project",
                        f"{type(exc).__name__}: {exc}",
                        payload=payload,
                    ).to_dict()

                attempt_results.append({
                    "command": attempt_command, "stdout": completed.stdout,
                    "stderr": completed.stderr, "returncode": completed.returncode,
                    "timeout": False,
                })
                output = "\n".join(
                    item
                    for item in (completed.stdout.strip(), completed.stderr.strip())
                    if item
                )
                if (
                    completed.returncode != 0
                    and _CONFLICTING_INSTANCE.search(output)
                    and (deadline is not None or attempt < 2)
                ):
                    conflict_retries += 1
                    backoff = min(2.0, 0.25 * (2 ** min(attempt, 3)))
                    if deadline is not None:
                        backoff = min(backoff, max(0.0, deadline - time.monotonic()))
                    time.sleep(backoff)
                    attempt += 1
                    continue
                break

        if completed is None:
            return UEOperationResult.failure(
                "build.project", "Unreal build did not produce a process result",
                payload=payload,
            ).to_dict()
        output = "\n".join(
            item
            for item in (
                completed.stdout.strip(),
                completed.stderr.strip(),
            )
            if item
        )
        diagnostics = _diagnostics(output)
        payload.update(
            {
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "attempts": conflict_retries + 1,
                "conflict_retries": conflict_retries,
            }
        )
        if completed.returncode != 0:
            return UEOperationResult.failure(
                "build.project",
                f"Unreal build failed with exit code "
                f"{completed.returncode}",
                diagnostics=diagnostics,
                payload=payload,
            ).to_dict()
        return UEOperationResult.success(
            "build.project",
            diagnostics=diagnostics,
            artifacts=[
                {
                    "type": "unreal_build",
                    "path": str(project_file.parent),
                    "state": "ready",
                }
            ],
            payload=payload,
        ).to_dict()
