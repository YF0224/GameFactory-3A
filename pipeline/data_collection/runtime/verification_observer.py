"""Explicit verification observation over captured command executions.

A verification is only ever recorded when the HARNESS declared it up front
(``--verify KIND=REGEX``): the rule marks WHICH command executions count as
verification — never the tool's name, never the exit status, never a guess.
For every matching call+result pair already recorded in the trajectory, the
observer binds what is actually observable: the command string, the exit
code when the result payload carries one (the journal path usually does
not), the workspace file versions the command itself references, and the
result's output reference. An observed ``exit_code == 0`` only means the
command returned 0 — it is never a functional-success claim.
"""
from __future__ import annotations

import re
from typing import Any, Iterable


def parse_verification_rules(items: Iterable[Any] | None) -> list[tuple[str, re.Pattern]]:
    """Parse ``KIND=REGEX`` declarations; anything malformed is rejected up
    front rather than silently skipped."""
    rules: list[tuple[str, re.Pattern]] = []
    for item in items or []:
        kind, _, pattern = str(item).partition("=")
        kind = kind.strip()
        if not kind or not pattern:
            raise ValueError(f"verification rule expects KIND=REGEX, got {item!r}")
        rules.append((kind, re.compile(pattern)))
    return rules


def _command_text(call: dict) -> str | None:
    args = call.get("arguments")
    if isinstance(args, dict) and isinstance(args.get("command"), str):
        return args["command"]
    return None


def _referenced_versions(command: str, versions: list[dict]) -> list[str]:
    """Bind the file versions the command ITSELF names — a factual binding,
    not a temporal guess: recorded version paths matched as whole tokens of
    the command string."""
    refs: list[str] = []
    for version in versions:
        path = str(version.get("path") or "")
        if path and re.search(rf"(?<![\w.]){re.escape(path)}(?![\w.])", command):
            if version.get("version_id"):
                refs.append(version["version_id"])
    return refs


def apply_declared_verification_rules(collector, rules) -> list[str]:
    """Record verification observations for real command executions that a
    harness-declared rule explicitly covers. Only a recorded call/result pair
    (a real execution boundary) qualifies; returns the recorded kinds."""
    if not rules:
        return []
    trajectory = collector.trajectory
    events = trajectory.get("events") or []
    versions = (trajectory.get("workspace") or {}).get("file_versions") or []
    recorded: list[str] = []
    for event in events:
        for call in event.get("tool_calls") or []:
            command = _command_text(call)
            if command is None:
                continue
            kind = next((k for k, pattern in rules if pattern.search(command)), None)
            if kind is None:
                continue
            call_id = call.get("tool_call_id")
            result = next((e for e in events
                           if e.get("kind") == "tool_result"
                           and e.get("tool_call_id") == call_id), None)
            if result is None:
                continue  # no execution boundary: nothing observable happened
            blocks = result.get("content") or []
            payload = blocks[0].get("data") if blocks else None
            exit_code = payload.get("exit_code") if isinstance(payload, dict) else None
            output_ref = blocks[0].get("uri") if blocks else None
            version_refs = _referenced_versions(command, versions)
            collector.record_verification(
                kind, payload if isinstance(payload, dict) else None,
                producer="verification_observer",
                origin="harness_declared_rule",
                command=command,
                exit_code=exit_code,
                workspace_version_ids=version_refs,
                output_ref=output_ref,
                tool_call_id=call_id,
                state_ref=version_refs[0] if version_refs else None,
            )
            recorded.append(kind)
    return recorded
