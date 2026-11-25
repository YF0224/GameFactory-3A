"""Stable Unreal Automation Test operations for UEClient v1."""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..config import UEClientConfig
from ..contracts import UEDiagnostic, UEOperationResult


_OPERATION = "testing.run_automation_tests"
_REPORT_FILENAME = "index.json"
_CONTROLLED_ARGUMENT_NAMES = (
    "-execcmds",
    "-reportexportpath",
    "-reportoutputpath",
    "-testexit",
)
_STATE_BY_NUMBER = {
    0: "not_run",
    1: "in_process",
    2: "failed",
    3: "passed",
    4: "skipped",
}


def _editor_command_binary(ue_root: Path) -> Path:
    if os.name == "nt":
        relative = "Engine/Binaries/Win64/UnrealEditor-Cmd.exe"
    elif platform.system() == "Darwin":
        relative = (
            "Engine/Binaries/Mac/UnrealEditor.app"
            "/Contents/MacOS/UnrealEditor"
        )
    else:
        relative = "Engine/Binaries/Linux/UnrealEditor-Cmd"
    return ue_root / relative


def _normalized_key(value: object) -> str:
    return "".join(
        character
        for character in str(value).casefold()
        if character.isalnum()
    )


def _field(
    value: Mapping[str, Any],
    *names: str,
    default: Any = None,
) -> Any:
    normalized = {
        _normalized_key(key): item
        for key, item in value.items()
    }
    for name in names:
        key = _normalized_key(name)
        if key in normalized:
            return normalized[key]
    return default


def _has_field(
    value: Mapping[str, Any],
    *names: str,
) -> bool:
    keys = {
        _normalized_key(key)
        for key in value
    }
    return any(
        _normalized_key(name) in keys
        for name in names
    )


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _state(value: Any) -> str:
    if isinstance(value, int):
        return _STATE_BY_NUMBER.get(value, "unknown")
    text = _normalized_key(value)
    if text in {"success", "succeeded", "pass", "passed"}:
        return "passed"
    if text in {"fail", "failed", "failure"}:
        return "failed"
    if text in {"notrun", "pending"}:
        return "not_run"
    if text in {"inprocess", "running"}:
        return "in_process"
    if text in {"skip", "skipped"}:
        return "skipped"
    return "unknown"


def _report_file_signature(
    report_file: Path,
) -> tuple[int, int] | None:
    try:
        stat = report_file.stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


def _resolve_report_dir(
    project_file: Path,
    report_dir: str,
) -> Path:
    text = str(report_dir or "").strip()
    if not text:
        return (
            project_file.parent
            / "Saved"
            / "Automation"
            / "Reports"
        )
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = project_file.parent / path
    return path.resolve(strict=False)


def _entry_diagnostics(
    test: Mapping[str, Any],
    test_name: str,
) -> list[UEDiagnostic]:
    result: list[UEDiagnostic] = []
    entries = _field(test, "entries", default=[])
    if not isinstance(entries, list):
        return result
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        event = _field(entry, "event", default=entry)
        if not isinstance(event, Mapping):
            event = entry
        event_type = _normalized_key(
            _field(event, "type", "event_type", default="")
        )
        if event_type not in {"error", "warning"}:
            continue
        message = _text(
            _field(event, "message", default="")
        ).strip()
        if not message:
            message = f"{test_name}: Automation Test event"
        elif test_name:
            message = f"{test_name}: {message}"
        line_value = _field(
            entry,
            "line_number",
            "line",
            default=None,
        )
        line = _integer(line_value, default=-1)
        result.append(
            UEDiagnostic(
                severity=event_type,
                message=message,
                code=(
                    "UE_AUTOMATION_TEST_FAILED"
                    if event_type == "error"
                    else "UE_AUTOMATION_TEST_WARNING"
                ),
                file=_text(
                    _field(
                        entry,
                        "filename",
                        "file",
                        default="",
                    )
                ),
                line=line if line >= 0 else None,
                source="unreal_automation_report",
            )
        )
    return result


def _parse_automation_report(
    report_file: Path,
) -> dict[str, Any]:
    try:
        payload = json.loads(
            report_file.read_text(encoding="utf-8-sig")
        )
    except FileNotFoundError:
        return {
            "ok": False,
            "errors": [
                f"Automation Report was not found: {report_file}"
            ],
            "diagnostics": [],
            "warnings": [],
            "payload": {},
        }
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "errors": [
                "Automation Report could not be parsed: "
                f"{type(exc).__name__}: {exc}"
            ],
            "diagnostics": [],
            "warnings": [],
            "payload": {},
        }
    if not isinstance(payload, Mapping):
        return {
            "ok": False,
            "errors": [
                "Automation Report root must be a JSON object"
            ],
            "diagnostics": [],
            "warnings": [],
            "payload": {},
        }

    raw_tests = _field(payload, "tests", default=[])
    tests = (
        [
            test
            for test in raw_tests
            if isinstance(test, Mapping)
        ]
        if isinstance(raw_tests, list)
        else []
    )
    states = {
        "passed": 0,
        "failed": 0,
        "not_run": 0,
        "in_process": 0,
        "skipped": 0,
        "unknown": 0,
    }
    diagnostics: list[UEDiagnostic] = []
    failed_without_event: list[str] = []
    for test in tests:
        test_name = _text(
            _field(
                test,
                "full_test_path",
                "test_display_name",
                "name",
                default="",
            )
        ).strip()
        state = _state(
            _field(test, "state", default="")
        )
        states[state] += 1
        test_diagnostics = _entry_diagnostics(
            test,
            test_name,
        )
        diagnostics.extend(test_diagnostics)
        if (
            state == "failed"
            and not any(
                item.severity == "error"
                for item in test_diagnostics
            )
        ):
            failed_without_event.append(
                test_name or "Unnamed Automation Test"
            )
    diagnostics.extend(
        UEDiagnostic(
            severity="error",
            message=f"{name}: Automation Test failed",
            code="UE_AUTOMATION_TEST_FAILED",
            source="unreal_automation_report",
        )
        for name in failed_without_event
    )

    summary_present = any(
        _has_field(payload, name)
        for name in (
            "succeeded",
            "succeeded_with_warnings",
            "failed",
            "not_run",
            "in_process",
        )
    )
    if summary_present:
        succeeded = _integer(
            _field(payload, "succeeded", default=0)
        )
        succeeded_with_warnings = _integer(
            _field(
                payload,
                "succeeded_with_warnings",
                default=0,
            )
        )
        failed = _integer(
            _field(payload, "failed", default=0)
        )
        not_run = _integer(
            _field(payload, "not_run", default=0)
        )
        in_process = _integer(
            _field(payload, "in_process", default=0)
        )
    else:
        succeeded = states["passed"]
        succeeded_with_warnings = 0
        failed = states["failed"]
        not_run = states["not_run"]
        in_process = states["in_process"]

    passed = succeeded + succeeded_with_warnings
    skipped = states["skipped"]
    known_total = (
        passed
        + failed
        + not_run
        + in_process
        + skipped
    )
    tests_found = (
        len(tests)
        if tests
        else known_total
    )
    unknown = max(
        states["unknown"],
        tests_found - known_total,
    )
    warnings: list[str] = []
    if succeeded_with_warnings:
        warnings.append(
            f"{succeeded_with_warnings} Automation Test(s) "
            "passed with warnings"
        )
    errors: list[str] = []
    if tests and (
        passed != states["passed"]
        or failed != states["failed"]
        or not_run != states["not_run"]
        or in_process != states["in_process"]
    ):
        errors.append(
            "Automation Report summary is inconsistent with "
            "individual test states"
        )
    if tests_found == 0:
        errors.append(
            "Automation Report contains no matching tests"
        )
    if failed:
        errors.append(
            f"{failed} Automation Test(s) failed"
        )
    if not_run:
        errors.append(
            f"{not_run} Automation Test(s) did not run"
        )
    if in_process:
        errors.append(
            f"{in_process} Automation Test(s) remained in process"
        )
    if skipped:
        errors.append(
            f"{skipped} Automation Test(s) were skipped"
        )
    if unknown:
        errors.append(
            f"{unknown} Automation Test(s) have an unknown state"
        )
    if tests_found and passed != tests_found:
        errors.append(
            "Not all matching Automation Tests passed"
        )

    return {
        "ok": not errors,
        "errors": list(dict.fromkeys(errors)),
        "diagnostics": diagnostics,
        "warnings": warnings,
        "payload": {
            "report_created_on": _text(
                _field(
                    payload,
                    "report_created_on",
                    default="",
                )
            ),
            "total_duration": _number(
                _field(
                    payload,
                    "total_duration",
                    default=0,
                )
            ),
            "tests_found": tests_found,
            "tests_passed": passed,
            "tests_succeeded": succeeded,
            "tests_succeeded_with_warnings": (
                succeeded_with_warnings
            ),
            "tests_failed": failed,
            "tests_not_run": not_run,
            "tests_in_process": in_process,
            "tests_skipped": skipped,
            "tests_unknown": unknown,
        },
    }


def _process_diagnostics(output: str) -> list[UEDiagnostic]:
    pattern = re.compile(
        r"(?P<source>Log[^:]+):\s*"
        r"(?P<severity>Error|Warning):\s*"
        r"(?P<message>.+)$",
        flags=re.IGNORECASE,
    )
    diagnostics: list[UEDiagnostic] = []
    for line in output.splitlines():
        match = pattern.search(line.strip())
        if not match:
            continue
        diagnostics.append(
            UEDiagnostic(
                severity=match.group("severity").lower(),
                message=match.group("message").strip(),
                code="UE_AUTOMATION_PROCESS_LOG",
                source=match.group("source"),
            )
        )
        if len(diagnostics) >= 200:
            break
    return diagnostics


def _unique_strings(values: Sequence[str]) -> list[str]:
    return list(
        dict.fromkeys(
            value
            for value in values
            if value
        )
    )


def _result(
    *,
    ok: bool,
    artifacts: Sequence[Mapping[str, Any]] = (),
    diagnostics: Sequence[UEDiagnostic] = (),
    warnings: Sequence[str] = (),
    errors: Sequence[str] = (),
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    return UEOperationResult(
        operation=_OPERATION,
        ok=ok,
        artifacts=tuple(
            dict(artifact)
            for artifact in artifacts
        ),
        diagnostics=tuple(diagnostics),
        warnings=tuple(_unique_strings(warnings)),
        errors=tuple(_unique_strings(errors)),
        payload=dict(payload),
    ).to_dict()


class UETestingClient:
    def __init__(self, config: UEClientConfig) -> None:
        self._config = config

    def run_automation_tests(
        self,
        test_filter: str,
        *,
        report_dir: str = "",
        extra_args: Sequence[str] = (),
        timeout: float | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        filter_text = str(test_filter or "").strip()
        base_payload: dict[str, Any] = {
            "command": [],
            "cwd": "",
            "test_filter": filter_text,
            "report_dir": "",
            "report_file": "",
            "dry_run": dry_run,
            "returncode": None,
            "stdout": "",
            "stderr": "",
            "timed_out": False,
            "tests_found": 0,
            "tests_passed": 0,
            "tests_succeeded": 0,
            "tests_succeeded_with_warnings": 0,
            "tests_failed": 0,
            "tests_not_run": 0,
            "tests_in_process": 0,
            "tests_skipped": 0,
            "tests_unknown": 0,
        }
        if not filter_text:
            return _result(
                ok=False,
                errors=["test_filter must not be empty"],
                payload=base_payload,
            )
        if any(
            character in filter_text
            for character in (";", "\r", "\n")
        ):
            return _result(
                ok=False,
                errors=[
                    "test_filter must not contain command separators"
                ],
                payload=base_payload,
            )
        if timeout is not None and timeout <= 0:
            return _result(
                ok=False,
                errors=["timeout must be greater than zero"],
                payload=base_payload,
            )
        if isinstance(extra_args, (str, bytes)):
            return _result(
                ok=False,
                errors=[
                    "extra_args must be a sequence of arguments, "
                    "not a string"
                ],
                payload=base_payload,
            )
        resolved_extra_args = [
            str(argument)
            for argument in extra_args
        ]
        for argument in resolved_extra_args:
            lowered = argument.strip().casefold()
            if any(
                lowered == name
                or lowered.startswith(f"{name}=")
                for name in _CONTROLLED_ARGUMENT_NAMES
            ):
                return _result(
                    ok=False,
                    errors=[
                        "extra_args must not override ExecCmds, "
                        "ReportExportPath, or TestExit"
                    ],
                    payload=base_payload,
                )

        ue_root = self._config.ue_root
        project_file = self._config.project_file
        if ue_root is None:
            return _result(
                ok=False,
                errors=["ue_root is not configured"],
                payload=base_payload,
            )
        if project_file is None or not project_file.is_file():
            return _result(
                ok=False,
                errors=[
                    "project_path does not resolve to an existing "
                    ".uproject file"
                ],
                payload=base_payload,
            )
        editor = _editor_command_binary(ue_root)
        if not editor.is_file():
            return _result(
                ok=False,
                errors=[
                    "Unreal Editor command binary was not found: "
                    f"{editor}"
                ],
                payload=base_payload,
            )

        resolved_report_dir = _resolve_report_dir(
            project_file,
            report_dir,
        )
        report_file = (
            resolved_report_dir
            / _REPORT_FILENAME
        )
        command = [
            str(editor),
            str(project_file),
            "-unattended",
            "-nop4",
            "-nosplash",
            "-NoSound",
            "-stdout",
            "-FullStdOutLogOutput",
            "-UTF8Output",
            (
                "-ExecCmds=Automation RunTests "
                f"{filter_text}; Quit"
            ),
            "-TestExit=Automation Test Queue Empty",
            f"-ReportExportPath={resolved_report_dir}",
            *resolved_extra_args,
        ]
        base_payload.update(
            {
                "command": command,
                "cwd": str(project_file.parent),
                "report_dir": str(resolved_report_dir),
                "report_file": str(report_file),
            }
        )
        if dry_run:
            return _result(
                ok=True,
                artifacts=[
                    {
                        "type": "automation_report",
                        "path": str(resolved_report_dir),
                        "state": "planned",
                    }
                ],
                payload=base_payload,
            )

        try:
            resolved_report_dir.mkdir(
                parents=True,
                exist_ok=True,
            )
        except OSError as exc:
            return _result(
                ok=False,
                errors=[
                    "Automation Report directory could not be "
                    f"created: {type(exc).__name__}: {exc}"
                ],
                payload=base_payload,
            )
        previous_signature = _report_file_signature(
            report_file
        )

        process_errors: list[str] = []
        try:
            completed = subprocess.run(
                command,
                cwd=project_file.parent,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
            base_payload.update(
                {
                    "returncode": completed.returncode,
                    "stdout": _text(completed.stdout),
                    "stderr": _text(completed.stderr),
                }
            )
            if completed.returncode != 0:
                process_errors.append(
                    "Unreal Automation process failed with "
                    f"exit code {completed.returncode}"
                )
        except subprocess.TimeoutExpired as exc:
            base_payload.update(
                {
                    "stdout": _text(exc.stdout),
                    "stderr": _text(exc.stderr),
                    "timed_out": True,
                }
            )
            process_errors.append(
                "Unreal Automation process timed out"
                + (
                    f" after {timeout} seconds"
                    if timeout is not None
                    else ""
                )
            )
        except Exception as exc:
            process_errors.append(
                "Unreal Automation process could not be started: "
                f"{type(exc).__name__}: {exc}"
            )

        process_output = "\n".join(
            value
            for value in (
                base_payload["stdout"],
                base_payload["stderr"],
            )
            if value
        )
        diagnostics = _process_diagnostics(
            process_output
        )
        current_signature = _report_file_signature(
            report_file
        )
        report_is_fresh = (
            current_signature is not None
            and current_signature != previous_signature
        )
        artifacts: list[dict[str, Any]] = []
        report_errors: list[str] = []
        report_warnings: list[str] = []
        if report_is_fresh:
            artifacts.append(
                {
                    "type": "automation_report",
                    "path": str(resolved_report_dir),
                    "state": "ready",
                }
            )
            report = _parse_automation_report(
                report_file
            )
            base_payload.update(report["payload"])
            diagnostics.extend(report["diagnostics"])
            report_errors.extend(report["errors"])
            report_warnings.extend(report["warnings"])
        elif current_signature is None:
            report_errors.append(
                f"Automation Report was not produced: {report_file}"
            )
        else:
            report_errors.append(
                "Automation Report was not updated by this run: "
                f"{report_file}"
            )

        errors = [
            *process_errors,
            *report_errors,
        ]
        ok = not errors
        return _result(
            ok=ok,
            artifacts=artifacts,
            diagnostics=diagnostics,
            warnings=report_warnings,
            errors=errors,
            payload=base_payload,
        )
