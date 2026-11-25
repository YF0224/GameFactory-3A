"""Execution and model-call boundary capture integration.

tool_dispatcher — registry of agent-facing tools with recorded execution;
agent_boundary — the controlled workspace tool surface; agent_bridge — stdio
JSON-RPC serving of those tools; dispatch_context — task-local causal context
(CaptureError is defined in core.errors and re-exported here); tracing —
engine/client call tracing; harness_adapter — model request/response
boundary recording plus redacted raw payload archiving.
"""
