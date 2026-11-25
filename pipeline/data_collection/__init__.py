"""
GameFactory-3A training-trajectory collection (``pipeline/data_collection``).

Format authority: ``benchmark/gamefactory3a_agent_trajectory_schema_unity.md`` (v5).

Layout (subpackages by responsibility)::

    core/      single-writer trajectory kernel (no agent knowledge)
    adapters/  one module per agent + the agent registry (add agents here)
    runtime/   collection processes around an agent (headless / sidecar)
    tools/     execution and model-call boundary capture integration
    quality/   validator, honest gap audit, direct training reads

Three ways to collect (per-agent, via the registry)::

    headless  runtime.live_runner.AgentRunner(get_adapter("codex"), ...)
              `python -m pipeline.data_collection live --provider codex ...`
    sidecar   runtime.session_collector.SessionCollector(agent="codely", ...)
              `python -m pipeline.data_collection sidecar --agent codely ...`
    import    adapters.codely_autosave.convert / adapters.codex_rollout.*
              (post-hoc, from an agent's session export)

Compat note: the package-root public API below is preserved; legacy deep
module paths (``pipeline.data_collection.collector`` etc.) migrated to the
subpackages — no forwarding shims are provided.
"""
from .adapters import (
    ADAPTERS,
    SUPPORTED_AGENTS,
    AgentAdapter,
    AgentProcess,
    ClaudeCodeAdapter,
    CodelyAdapter,
    CodexAdapter,
    get_adapter,
)
from .core.artifact_store import ArtifactStore
from .core.collector import (
    COLLECTOR_VERSION,
    COMPLETENESS,
    CONTENT_TYPES,
    EVENT_KINDS,
    OPERATIONS,
    SOURCES,
    TRAINING_POLICIES,
    TRAINING_STATUS,
    VISIBILITY,
    Collector,
    content_block,
)
from .core.collector_sink import CollectorSink
from .core.event_writer import (
    TRAJECTORY_INDEX_SCHEMA_VERSION,
    TRAJECTORY_SCHEMA_VERSION,
    TrajectoryWriter,
    atomic_write_json,
    load_json,
    now_iso,
)
from .core.errors import CaptureError
from .core.telemetry import TelemetryWriter
from .core.workspace_tracker import WorkspaceTracker
from .quality.capture_audit import audit_capture
from .quality.export import export_sft
from .quality.loader import TrajectoryLoader
from .quality.validator import Finding, validate_file, validate_trajectory
from .runtime.environment import capture_environment
from .runtime.live_assembler import LiveAssembler
from .runtime.live_runner import AgentRunner, LiveTrajectoryCollector
from .runtime.observation_spool import SpoolReader, SpoolSink
from .runtime.outer_agent_hook import (
    collection_enabled,
    finalize_code_gen_trajectory,
    record_playtest_take,
    start_code_gen_trajectory,
)
from .runtime.session_collector import SessionCollector
from .runtime.codex_sidecar import CodexRolloutCollector
from .runtime.claude_sidecar import ClaudeSessionCollector
from .tools.agent_boundary import MechanicAgentBoundary
from .tools.agent_bridge import AgentToolBridge, create_bridge, create_engine_client, serve_stdio
from .tools.dispatch_context import current_dispatch
from .tools.harness_adapter import HarnessAdapter, redact
from .tools.tool_dispatcher import ToolDispatcher
from .tools.tracing import (
    content_for_payload,
    record_engine_operation,
    run_command,
    safe_jsonable,
    traced_client,
    traced_tool,
)

from .adapters.codely_autosave import convert as convert_codely_autosave
from .adapters.codely_autosave import validate as validate_codely_autosave
from .adapters.codex_rollout import (
    convert_partitioned_rollout,
    convert_run_rollout,
    partition_rollout,
    write_partitioned,
)

__all__ = [
    # registry / per-agent interface
    "ADAPTERS",
    "SUPPORTED_AGENTS",
    "get_adapter",
    # adapters
    "AgentAdapter",
    "AgentProcess",
    "CodexAdapter",
    "ClaudeCodeAdapter",
    "CodelyAdapter",
    "convert_codely_autosave",
    "validate_codely_autosave",
    "partition_rollout",
    "write_partitioned",
    "convert_partitioned_rollout",
    "convert_run_rollout",
    # core
    "COLLECTOR_VERSION",
    "COMPLETENESS",
    "CONTENT_TYPES",
    "EVENT_KINDS",
    "OPERATIONS",
    "SOURCES",
    "TRAINING_POLICIES",
    "TRAINING_STATUS",
    "TRAJECTORY_INDEX_SCHEMA_VERSION",
    "TRAJECTORY_SCHEMA_VERSION",
    "VISIBILITY",
    "ArtifactStore",
    "CaptureError",
    "Collector",
    "CollectorSink",
    "TelemetryWriter",
    "TrajectoryWriter",
    "WorkspaceTracker",
    "atomic_write_json",
    "content_block",
    "load_json",
    "now_iso",
    # runtime
    "AgentRunner",
    "ClaudeSessionCollector",
    "CodexRolloutCollector",
    "LiveAssembler",
    "LiveTrajectoryCollector",
    "SessionCollector",
    "SpoolReader",
    "SpoolSink",
    "capture_environment",
    "collection_enabled",
    "current_dispatch",
    "finalize_code_gen_trajectory",
    "record_playtest_take",
    "start_code_gen_trajectory",
    # tools
    "AgentToolBridge",
    "HarnessAdapter",
    "MechanicAgentBoundary",
    "ToolDispatcher",
    "content_for_payload",
    "create_bridge",
    "create_engine_client",
    "record_engine_operation",
    "redact",
    "run_command",
    "safe_jsonable",
    "serve_stdio",
    "traced_client",
    "traced_tool",
    # quality
    "Finding",
    "TrajectoryLoader",
    "audit_capture",
    "export_sft",
    "validate_file",
    "validate_trajectory",
]
