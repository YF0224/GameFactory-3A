"""Per-agent collection adapters.

One module per external agent: spawn strategy, stream-event normalization,
and (where implemented) session-export importers. Adding a new agent means
adding ``adapters/<name>.py`` and registering it in :data:`ADAPTERS` —
runners, CLIs and normalizer fallbacks then pick it up automatically;
unknown agent names error instead of being parsed with another agent's
format.
"""
from __future__ import annotations

from .base import AgentAdapter, AgentProcess
from .codex import CodexAdapter
from .codely import CodelyAdapter
from .claude_code import ClaudeCodeAdapter

#: Single source of truth: agent name -> adapter class.
ADAPTERS = {
    "codex": CodexAdapter,
    "codely": CodelyAdapter,
    "claude": ClaudeCodeAdapter,
}

SUPPORTED_AGENTS = tuple(sorted(ADAPTERS))


def get_adapter(agent: str, *, executable: str | None = None, extra_args=()):
    """Construct the registered adapter for ``agent``; unknown names error."""
    try:
        cls = ADAPTERS[agent]
    except KeyError:
        raise ValueError(
            f"unsupported agent {agent!r}; known: {SUPPORTED_AGENTS}"
        ) from None
    return cls(executable or str(agent), extra_args)


def default_normalizer(agent: str):
    """Registry-backed normalizer fallback for adapters that supply none.

    Legacy fixture adapters reuse a registered provider name; an unregistered
    agent without its own normalizer fails here instead of being silently
    parsed with another agent's event format.
    """
    try:
        cls = ADAPTERS[agent]
    except KeyError:
        raise ValueError(
            f"unknown agent {agent!r} and no explicit normalizer supplied; "
            f"known: {SUPPORTED_AGENTS}"
        ) from None
    return cls().normalizer()
