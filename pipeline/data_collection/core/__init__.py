"""Single-writer trajectory kernel: canonical facts, storage, no agent knowledge.

collector / collector_sink / event_writer — one canonical immutable event log
with atomic checkpoints; artifact_store — content-addressed blobs;
telemetry — the single metering source; workspace_tracker — immutable file
versions (tracker + polling observer).
"""
