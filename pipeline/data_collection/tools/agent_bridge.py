"""Small stdio bridge exposing the controlled GameFactory tool boundary.

The bridge deliberately exposes only tools registered on ``MechanicAgentBoundary``.
It is transport glue: all execution and recording remains in ToolDispatcher.
"""
from __future__ import annotations

import json
import sys
import os
from ..runtime.observation_spool import SpoolSink, ENV_SPOOL, ENV_TRAJECTORY
from ..core.collector_sink import as_sink
from ..core.collector import content_block
from pathlib import Path
from typing import Any, Mapping

from .agent_boundary import MechanicAgentBoundary
from ..core.artifact_store import ArtifactStore
from ..core.collector import Collector


class AgentToolBridge:
    """JSON-RPC-like adapter for agents that can call a stdio tool server."""

    def __init__(self, boundary: MechanicAgentBoundary):
        self.boundary = boundary

    def tools(self) -> list[dict[str, Any]]:
        return self.boundary.dispatcher.tool_definitions()

    def call(self, name: str, arguments: Mapping[str, Any] | None = None,
             *, tool_call_id: str | None = None) -> Any:
        return self.boundary.dispatcher.call(
            name, arguments if arguments is not None else {}, tool_call_id=tool_call_id
        )

    def handle(self, request: Mapping[str, Any]) -> dict[str, Any]:
        request_id = request.get("id")
        method = request.get("method")
        try:
            if method in {"tools/list", "list_tools"}:
                result: Any = {"tools": self.tools()}
            elif method in {"tools/call", "call_tool"}:
                params = request.get("params") or {}
                result = self.call(
                    str(params["name"]),
                    params.get("arguments", {}),
                    tool_call_id=params.get("tool_call_id"),
                )
            elif method == "ping":
                result = {"ok": True}
            else:
                raise ValueError(f"unknown bridge method: {method!r}")
            response = {"id": request_id, "ok": True, "result": result}
        except Exception as exc:
            response = {
                "id": request_id,
                "ok": False,
                "error": {"type": type(exc).__name__, "message": str(exc)},
            }

        self.boundary.collector.record_event("tool", "runtime", producer="agent_bridge",
            operation="bridge_response", transport_request_id=request_id,
            content=[content_block("json", data=response, visibility="collector_only")])
        return response


def serve_stdio(bridge: AgentToolBridge, *, input_stream=None, output_stream=None) -> None:
    """Serve one JSON request per line; logs never go to stdout."""
    input_stream = input_stream or sys.stdin
    output_stream = output_stream or sys.stdout
    try:
        for line in input_stream:
            if not line.strip():
                continue
            try:
                request = json.loads(line)
                if not isinstance(request, dict):
                    raise ValueError("bridge request must be an object")
            except ValueError as exc:
                bridge.boundary.collector.record_event("system", "runtime", producer="agent_bridge",
                    audit_code="malformed_bridge_request", error=str(exc))
                response = {"id": None, "ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}
            else:
                response = bridge.handle(request)
            output_stream.write(json.dumps(response, ensure_ascii=False, default=str) + "\n")
            output_stream.flush()
    finally:
        if isinstance(bridge.boundary.collector, SpoolSink):
            bridge.boundary.collector.close()


def create_engine_client(engine: str, workspace: str | Path, **options: Any) -> Any:
    """Construct one of the repository's public engine client facades."""
    key = engine.lower().replace("-", "_")
    project_path = str(workspace)
    if key in {"unity", "unity3d"}:
        from engine_adapters.unity3d import UnityClient
        return UnityClient(project_path=project_path, **options)
    if key == "godot":
        from engine_adapters.godot import GodotClient
        return GodotClient(project_path=project_path, **options)
    if key in {"ue", "ue5", "unreal"}:
        from engine_adapters.ue5 import UEClient
        return UEClient(project_path=project_path, **options)
    if key == "blender":
        from engine_adapters.blender import BlenderClient
        return BlenderClient(project_path=project_path, **options)
    if key in {"three", "three_js", "threejs"}:
        from engine_adapters.three_js import ThreeClient
        return ThreeClient(project_path=project_path, **options)
    raise ValueError(f"unsupported engine: {engine}")


def _infer_engine(collector: Collector) -> str | None:
    """Infer the task engine from trajectory metadata/environment references."""
    metadata = collector.trajectory.get("metadata") or {}
    engine = metadata.get("engine")
    if engine:
        return str(engine)
    environment = collector.trajectory.get("environment_ref") or {}
    engine = environment.get("engine")
    return str(engine) if engine else None


def create_bridge(trajectory_path: str | Path, workspace: str | Path, *, engine: str | None = None, engine_options: Mapping[str, Any] | None = None, include_internal: bool = False, collector: Any = None) -> AgentToolBridge:
    if collector is None:
        if os.environ.get(ENV_SPOOL):
            if Path(trajectory_path).resolve() != Path(os.environ[ENV_TRAJECTORY]).resolve():
                raise ValueError("bridge trajectory does not match the live episode")
            collector = SpoolSink.from_environment()
        else:
            collector = Collector.resume(Path(trajectory_path))
    collector = as_sink(collector)
    engine = engine or _infer_engine(collector)
    boundary = MechanicAgentBoundary(
        collector,
        workspace,
        artifact_store=collector.artifact_store or ArtifactStore(),
    )
    if engine:
        boundary.register_client(
            engine,
            create_engine_client(engine, workspace, **dict(engine_options or {})),
            include_internal=include_internal,
        )
    return AgentToolBridge(boundary)


__all__ = ["AgentToolBridge", "create_bridge", "create_engine_client", "serve_stdio"]

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Serve GameFactory trajectory tools over stdio")
    parser.add_argument("--trajectory", required=True, help="Existing trajectory JSON to resume")
    parser.add_argument("--workspace", required=True, help="Agent write/command workspace")
    parser.add_argument("--engine", default=None, help="unity3d, godot, ue5, blender, or three_js")
    parser.add_argument("--include-internal", action="store_true", help="Expose private/internal client callables for diagnostics")
    args = parser.parse_args()
    serve_stdio(create_bridge(args.trajectory, args.workspace, engine=args.engine, include_internal=args.include_internal))
