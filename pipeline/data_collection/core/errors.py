"""Core exception types.

The kernel must not depend on upper integration layers: ``CaptureError``
lives here so ``core.collector_sink`` does not need ``tools`` to raise it
(:mod:`pipeline.data_collection.tools.dispatch_context` re-imports it for
compatibility; the class identity is unchanged).
"""


class CaptureError(RuntimeError):
    """Persistence failed, not a tool execution failure."""
