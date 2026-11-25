"""Private UE Python execution transport."""

from __future__ import annotations

import json
import sys
import tempfile
import textwrap
import time
from pathlib import Path
from typing import Any

from ...config import UEClientConfig
from .remote_control import RemoteControlClient


def _remote_node_sort_key(
    node: dict[str, Any],
    project_file: Path | None,
) -> tuple[int, str]:
    expected_name = (
        project_file.stem.lower()
        if project_file is not None
        else ""
    )
    expected_root = (
        project_file.parent.as_posix().rstrip("/").lower()
        if project_file is not None
        else ""
    )
    node_name = str(
        node.get("project_name") or ""
    ).strip().lower()
    node_root = (
        str(node.get("project_root") or "")
        .strip()
        .replace("\\", "/")
        .rstrip("/")
        .lower()
    )
    project_match = int(
        bool(expected_name)
        and node_name == expected_name
        and (
            not expected_root
            or node_root == expected_root
        )
    )
    return (
        -project_match,
        str(node.get("node_id") or ""),
    )


def _isolated_nodes(nodes, project_file):
    if project_file is None or not project_file.is_absolute():
        raise RuntimeError("Isolated remote execution requires an exact absolute project")
    expected = project_file.parent.resolve()
    matched = []
    for node in nodes:
        raw_root = str(node.get("project_root") or "").strip()
        root = Path(raw_root).expanduser()
        # Never resolve relative discovery metadata against our working directory.
        if (raw_root and root.is_absolute() and root.resolve() == expected
                and str(node.get("project_name") or "") == project_file.stem
                and node.get("node_id")):
            matched.append(node)
    return matched


class PythonRPCTransport:
    def __init__(
        self,
        config: UEClientConfig | None = None,
        remote_control: RemoteControlClient | None = None,
    ) -> None:
        self.config = config or UEClientConfig.resolve()
        self.remote_control = (
            remote_control
            or RemoteControlClient(self.config.remote_url)
        )

    def execute(
        self,
        script: str,
        timeout: int = 120,
    ) -> dict[str, Any]:
        if self.config.python_transport == "remote_control":
            if self.config.repair_project_root is not None or self.config.native_client_only:
                return self._execute_project_http(script, timeout)
            return self.remote_control.execute_python(
                script,
                timeout=min(timeout, 10),
            )
        return self._execute_remote(script, timeout)

    def _execute_project_http(
        self,
        script: str,
        timeout: int,
    ) -> dict[str, Any]:
        """Execute through the leased HTTP endpoint with an in-editor identity guard.

        Check on every call, in the same Python command as the requested script:
        a port reused by another Editor must never receive the requested work.
        Discovery and an earlier readiness response are not identity guarantees.
        """
        project = self.config.project_file
        if project is None or not project.is_absolute() or not project.is_file():
            raise RuntimeError("Isolated HTTP Python requires an exact existing project")
        if self.config.host != "127.0.0.1":
            raise RuntimeError("Isolated HTTP Python requires a local leased endpoint")
        expected = str(project.resolve())
        guarded = textwrap.dedent(
            f"""\
            import os as _a3_rpc_os
            import unreal as _a3_rpc_unreal
            _a3_rpc_project = _a3_rpc_unreal.Paths.get_project_file_path()
            _a3_rpc_project = _a3_rpc_unreal.Paths.convert_relative_path_to_full(_a3_rpc_project)
            if _a3_rpc_os.path.realpath(_a3_rpc_project) != {expected!r}:
                raise RuntimeError("UEClient HTTP Python project mismatch; requested script refused")
            exec(compile({script!r}, "<UEClient exact-project HTTP>", "exec"), globals(), globals())
            """
        )
        response = self.remote_control.execute_python(
            guarded,
            timeout=max(1, timeout),
        )
        if not isinstance(response, dict) or response.get("ReturnValue") is not True:
            raise RuntimeError(
                "UE HTTP Python command failed or lacked acknowledgement; "
                "check editor Python log and exact project identity"
            )
        return response

    def execute_json(
        self,
        script: str,
        result_var: str = "result",
        timeout: int = 120,
    ) -> Any:
        with tempfile.NamedTemporaryFile(
            "w",
            suffix=".json",
            delete=False,
            encoding="utf-8",
        ) as result_file:
            result_path = Path(result_file.name)

        wrapped_script = script + textwrap.dedent(
            f"""\

            import json as _aaagf_json
            with open({result_path.as_posix()!r}, "w", encoding="utf-8") as _aaagf_result_file:
                _aaagf_json.dump({result_var}, _aaagf_result_file, ensure_ascii=False)
            """
        )
        try:
            self.execute(wrapped_script, timeout=timeout)
            return json.loads(
                result_path.read_text(encoding="utf-8")
            )
        finally:
            result_path.unlink(missing_ok=True)

    def _execute_remote(
        self,
        script: str,
        timeout: int,
    ) -> dict[str, Any]:
        plugin_path = self.config.python_plugin_path
        if plugin_path is None or not plugin_path.exists():
            raise RuntimeError(
                "UE Python remote_execution.py directory was not found: "
                f"{plugin_path or '<not configured>'}"
            )

        plugin_text = str(plugin_path)
        if plugin_text not in sys.path:
            sys.path.append(plugin_text)

        import remote_execution

        isolated = self.config.repair_project_root is not None or self.config.native_client_only
        if isolated:
            if self.config.python_command_port is None:
                raise RuntimeError("Native-only Python execution requires a leased command port")
            remote_config = remote_execution.RemoteExecutionConfig()
            remote_config.command_endpoint = ("127.0.0.1", self.config.python_command_port)
            remote = remote_execution.RemoteExecution(remote_config)
        else:
            remote = remote_execution.RemoteExecution()
        remote.start()
        try:
            deadline = time.time() + timeout
            while (
                not (_isolated_nodes(remote.remote_nodes, self.config.project_file)
                     if isolated else remote.remote_nodes)
                and time.time() < deadline
            ):
                time.sleep(0.1)
            if not remote.remote_nodes:
                raise RuntimeError(
                    "No UE Python Remote Execution node was discovered"
                )

            time.sleep(
                min(
                    0.5,
                    max(0.0, deadline - time.time()),
                )
            )
            nodes = sorted(
                (_isolated_nodes(remote.remote_nodes, self.config.project_file)
                 if isolated else remote.remote_nodes),
                key=lambda node: _remote_node_sort_key(
                    node,
                    self.config.project_file,
                ),
            )
            if not nodes:
                raise RuntimeError('No exact repair project node discovered; foreign nodes refused')
            errors: list[str] = []
            for node in nodes:
                node_id = str(node.get("node_id") or "")
                if not node_id:
                    continue
                try:
                    remote.open_command_connection(node_id)
                    return self._run_remote_script(
                        remote,
                        remote_execution,
                        node,
                        script,
                    )
                except Exception as exc:
                    errors.append(
                        f"{node.get('project_name') or 'UE'}"
                        f"[{node_id}]: "
                        f"{type(exc).__name__}: {exc}"
                    )
                    try:
                        remote.close_command_connection()
                    except Exception:
                        pass
            raise RuntimeError(
                "Unable to connect to a UE Python "
                "Remote Execution node: "
                + " | ".join(errors)
            )
        finally:
            remote.stop()

    @staticmethod
    def _run_remote_script(
        remote: Any,
        remote_execution: Any,
        node: dict[str, Any],
        script: str,
    ) -> dict[str, Any]:
        with tempfile.NamedTemporaryFile(
            "w",
            suffix=".py",
            delete=False,
            encoding="utf-8",
        ) as script_file:
            script_file.write(script)
            script_path = Path(script_file.name)
        try:
            result = remote.run_command(
                script_path.as_posix(),
                unattended=True,
                exec_mode=remote_execution.MODE_EXEC_FILE,
                raise_on_failure=True,
            )
            return {
                "ok": bool(result.get("success", True)),
                "transport": "python_remote_execution",
                "remote_node": node,
                "result": result,
            }
        finally:
            script_path.unlink(missing_ok=True)


def call_ue_python(
    script: str,
    timeout: int = 120,
) -> dict[str, Any]:
    return PythonRPCTransport().execute(
        script,
        timeout=timeout,
    )


def _call_ue_python_json(
    script: str,
    result_var: str = "result",
    timeout: int = 120,
) -> Any:
    return PythonRPCTransport().execute_json(
        script,
        result_var=result_var,
        timeout=timeout,
    )
