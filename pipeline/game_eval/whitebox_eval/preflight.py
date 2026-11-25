"""Read-only recording preflight; never activates or terminates an engine process."""
from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path

from .plan_validation import validate_execution_plan


def preflight(entry: dict, capability: dict, plan: dict, rubric_ids, output: Path,
              *, budget_ms: int, gui_status: dict, active_engines=None) -> dict:
    started = time.monotonic()
    project = Path(capability["project_root"]) if capability.get("project_root") else None
    checks = {
        "delivery": bool(project and project.is_dir()),
        "launch_source": bool(capability.get("launch_source")),
        "launch_scene": capability.get("launch_scene_exists") is True,
        "adapter": capability.get("current_adapter_capability") not in (None, "UNSUPPORTED"),
        "gui_available": bool(gui_status.get("available")) if capability.get("engine") != "three_js" else True,
        "no_gui_engine_conflict": not bool(active_engines),
        "output_parent_writable": output.parent.is_dir() and os.access(output.parent, os.W_OK),
        "budget_valid": isinstance(budget_ms, int) and budget_ms >= 1000,
    }
    plan_check = None
    try:
        plan_check = validate_execution_plan(plan, capability, rubric_ids, budget_ms=budget_ms)
    except (ValueError, TypeError, KeyError) as exc:
        checks["plan_valid"] = False
        plan_error = str(exc)
    else:
        checks["plan_valid"] = True
        plan_error = None
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output, prefix=".preflight-", delete=True):
        checks["output_writable"] = True
    reason = None
    if not all(checks.values()):
        reason = (plan_error if not checks.get("plan_valid") else
                  "; ".join(key for key, value in checks.items() if not value))
    return {"version": "whitebox-preflight.v1", "entry_id": entry.get("id"),
            "engine": capability.get("engine"), "checked_unix": time.time(),
            "checks": checks, "plan": plan_check, "plan_error": plan_error,
            "gui_status": gui_status, "active_engines": active_engines or [],
            "ready": all(checks.values()), "blocking_reason": reason,
            "elapsed_ms": round((time.monotonic() - started) * 1000, 2)}
