"""Collection processes that run around an external agent.

live_runner — headless: spawn the agent and capture its stream;
session_collector — interactive sidecar: import the agent's session export
incrementally and observe the workspace; live_assembler / observation_spool —
association and external observation ingress; outer_agent_hook — prepare/
finalize wiring for code-gen tasks; environment — host environment snapshot.
"""
