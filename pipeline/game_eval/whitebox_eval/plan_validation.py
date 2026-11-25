"""Strict validation for executable, auditable cross-engine input trajectories."""
from __future__ import annotations

import math
from engine_adapters._mouse_plan import MOUSE_KINDS, validate_mouse_step
from collections import Counter

VERSION = "whitebox-executable-actions.v1"
KINDS = {"key_down", "key_up", "key_tap", "chord", "mouse_move", "mouse_down",
         "mouse_up", "mouse_click", "wheel", "wait", "observe"}


def validate_execution_plan(plan: dict, capability: dict, rubric_ids, *, budget_ms: int,
                            max_actions: int = 512) -> dict:
    """Validate either the public action schema or the existing probe schema.

    The recorder's native protocol predates ``actions[]`` and deliberately
    remains the execution format for existing adapters.  This adapter-level
    gate still rejects empty/wait-only plans without translating a probe into
    a fabricated action record.
    """
    if isinstance(plan, dict) and isinstance(plan.get("actions"), list):
        return validate_action_plan(plan, capability, rubric_ids,
                                    budget_ms=budget_ms, max_actions=max_actions)
    if not isinstance(plan, dict) or not isinstance(plan.get("probes"), list):
        raise ValueError("plan must contain executable actions[] or probes[]")
    probes = plan["probes"]
    steps = [step for probe in probes if isinstance(probe, dict)
             for step in probe.get("steps", []) if isinstance(step, dict)]
    if not steps or len(steps) > max_actions:
        raise ValueError("plan step count is empty or exceeds protocol limit")
    real_inputs = 0
    elapsed = 0
    distribution = Counter()
    claimed = set()
    for index, step in enumerate(steps):
        kind = step.get("kind")
        if kind not in {"input", "wait", "wait_until", "move_until", "look"} | MOUSE_KINDS:
            raise ValueError(f"probe step {index} has unsupported kind")
        duration = step.get("timeout_ms", 0) if kind in {"wait_until", "move_until"} else step.get("duration_ms", 0)
        if type(duration) is not int or duration < 0 or duration > 30000:
            raise ValueError(f"probe step {index} has invalid duration/timeout")
        if kind in MOUSE_KINDS:
            validate_mouse_step(step)
            real_inputs += 1
        if kind in {"input", "move_until"} and step.get("key"):
            real_inputs += 1
        if kind == "input" and not step.get("key") and not step.get("taps"):
            raise ValueError(f"probe step {index} input has no physical key")
        ids = step.get("criterion_ids", [])
        if ids and (not isinstance(ids, list) or set(ids) - set(rubric_ids)):
            raise ValueError(f"probe step {index} maps unknown rubric IDs")
        claimed.update(ids)
        distribution[kind] += 1
        elapsed += duration
    if real_inputs == 0:
        raise ValueError("interactive plan must contain real keyboard or mouse input; wait-only plans are rejected")
    if elapsed > budget_ms:
        raise ValueError(f"worst-case probe timeline {elapsed}ms exceeds budget {budget_ms}ms")
    return {"version": VERSION, "format": "probes", "valid": True,
            "action_count": len(steps), "real_input_count": real_inputs,
            "input_distribution": dict(distribution),
            "covered_rubric_ids": sorted(claimed), "worst_case_ms": elapsed,
            "budget_ms": budget_ms}


def _supported_binding_tokens(capability: dict) -> set[str]:
    tokens = set()
    for item in capability.get("keyboard_bindings", []):
        tokens.update(__import__("re").findall(r"['\"]([^'\"]{1,40})['\"]", str(item)))
    return {token.lower() for token in tokens}


def validate_action_plan(plan: dict, capability: dict, rubric_ids, *, budget_ms: int,
                         max_actions: int = 512) -> dict:
    """Reject vague, wait-only, unsupported or over-budget plans before launch."""
    if not isinstance(plan, dict) or not isinstance(plan.get("actions"), list):
        raise ValueError("plan.actions must be an executable action list")
    actions = plan["actions"]
    if not actions or len(actions) > max_actions:
        raise ValueError("plan action count is empty or exceeds protocol limit")
    if not isinstance(budget_ms, int) or budget_ms < 1000:
        raise ValueError("recording budget must be an integer >= 1000ms")
    ids = set(rubric_ids)
    supported = _supported_binding_tokens(capability)
    covered = set()
    pressed = set()
    elapsed = 0
    real_inputs = 0
    distribution = Counter()
    for index, action in enumerate(actions):
        if not isinstance(action, dict) or action.get("kind") not in KINDS:
            raise ValueError(f"action {index} has an unsupported kind")
        kind = action["kind"]
        at = action.get("at_ms", elapsed)
        duration = action.get("duration_ms", 0)
        if type(at) not in (int, float) or not math.isfinite(at) or at < elapsed:
            raise ValueError(f"action {index} has invalid/non-monotonic at_ms")
        if type(duration) is not int or not 0 <= duration <= 30000:
            raise ValueError(f"action {index} has invalid duration_ms")
        if not action.get("purpose") or not action.get("evidence_target"):
            raise ValueError(f"action {index} needs purpose and evidence_target")
        mapping = action.get("rubric_ids", [])
        if not isinstance(mapping, list) or set(mapping) - ids:
            raise ValueError(f"action {index} maps unknown rubric IDs")
        covered.update(mapping)
        window = action.get("target_window", "game")
        if not isinstance(window, str) or not window.strip():
            raise ValueError(f"action {index} has no target window")
        if kind.startswith("mouse_") or kind == "wheel":
            if not capability.get("mouse_bindings"):
                raise ValueError(f"action {index} uses mouse but project has no detected mouse binding")
            if kind in {"mouse_move", "mouse_click", "mouse_down", "mouse_up"}:
                x, y = action.get("x"), action.get("y")
                if type(x) not in (int, float) or type(y) not in (int, float) or not (0 <= x <= 1 and 0 <= y <= 1):
                    raise ValueError(f"action {index} mouse coordinates must be normalized 0..1")
        if kind in {"key_down", "key_up", "key_tap", "chord"}:
            keys = action.get("keys", [])
            if not isinstance(keys, list) or not 1 <= len(keys) <= (3 if kind == "chord" else 1):
                raise ValueError(f"action {index} requires a bounded key list")
            for key in keys:
                if not isinstance(key, str) or not key:
                    raise ValueError(f"action {index} has invalid key")
                if supported and key.lower() not in supported:
                    raise ValueError(f"action {index} key {key!r} is not present in source-derived bindings")
                if kind == "key_down":
                    if key in pressed: raise ValueError(f"key {key} pressed twice without release")
                    pressed.add(key)
                elif kind == "key_up":
                    if key not in pressed: raise ValueError(f"key {key} released without a preceding down")
                    pressed.remove(key)
            if kind in {"key_tap", "chord"} and duration > 0 and duration < 20:
                raise ValueError(f"action {index} tap duration is too short")
        if kind in {"key_down", "key_tap", "chord", "mouse_down", "mouse_click", "wheel"}:
            real_inputs += 1
        distribution[kind] += 1
        elapsed = max(int(at), elapsed) + duration
    if pressed:
        raise ValueError(f"plan leaves keys held without release: {sorted(pressed)}")
    if real_inputs == 0:
        raise ValueError("interactive plan must contain real keyboard or mouse input; wait-only plans are rejected")
    missing = ids - covered
    if missing:
        raise ValueError(f"rubric coverage lacks mapped actions/passive observations: {sorted(missing)}")
    if elapsed > budget_ms:
        raise ValueError(f"worst-case action timeline {elapsed}ms exceeds budget {budget_ms}ms")
    return {"version": VERSION, "valid": True, "action_count": len(actions),
            "real_input_count": real_inputs, "input_distribution": dict(distribution),
            "covered_rubric_ids": sorted(covered), "worst_case_ms": elapsed,
            "budget_ms": budget_ms}
