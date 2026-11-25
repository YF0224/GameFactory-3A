"""A direct, owner-thread facade over the existing Collector, not an event model."""
import threading
from .errors import CaptureError


class CollectorSink:
    def __init__(self, collector):
        self.collector = collector
        self.context_identity = collector
        self.owner_thread = threading.get_ident()

    def __getattr__(self, name):
        value = getattr(self.collector, name)
        if not callable(value) or not (name.startswith("record_") or name in {"open_request", "close_request"}):
            return value
        def record(*args, **kwargs):
            if threading.get_ident() != self.owner_thread:
                raise CaptureError("CollectorSink must be used on its writer thread; enqueue observations instead")
            try:
                return value(*args, **kwargs)
            except CaptureError:
                raise
            except Exception as exc:
                raise CaptureError(f"collector persistence failed: {exc}") from exc
        return record


def as_sink(collector):
    return collector if isinstance(collector, CollectorSink) or getattr(collector, "is_observation_sink", False) else CollectorSink(collector)
