"""
operators/gen_motion/funcs/cloud_rig_animate.py

Cloud rigging + animation, for the TokenHub / Tripo backend.

Separate from `rig_character` and `generate_motion` because the pipeline shape
differs. The local stack splits the work three ways — Puppeteer predicts a
skeleton, MoMask generates a BVH clip, a Blender pass retargets one onto the
other. The cloud stack has no intermediate BVH and no mapping file:
`tripo-3d-rigging` returns a rigged mesh and `tripo-3d-animation` retargets a
preset clip onto the skeleton that same task produced.

API constraints these helpers encode:

  * The mesh goes in as a URL. The endpoints download it themselves; this
    gateway has no upload endpoint and rejects `data:` URIs.
  * Animation chains off the rigging *task id*, not the rigged file or its URL.
    The skeleton lives server-side against that task and expires after 24 hours.
  * `spec="mixamo"` cannot be animated. Rigging for animation must use
    `spec="tripo"`; mixamo output is for DCC import only.
  * Motion comes from a fixed preset library, not from a text description.
"""
from __future__ import annotations

from typing import Any, Optional


def check_riggable(
    mesh_url: str,
    check_model: Any,
    *,
    mesh_bytes: Optional[bytes] = None,
    mesh_format: str = ".glb",
) -> dict[str, Any]:
    """
    Ask whether this mesh can be rigged, and as what topology.

    Returns ``{"riggable": bool, "rig_type": str, "unclassified": bool,
    "raw": dict}``. Pass the returned ``rig_type`` to `rig_mesh`.
    """
    return check_model.infer(
        mesh_bytes, mesh_format=mesh_format, mesh_url=mesh_url
    )


def rig_mesh(
    mesh_url: str,
    rig_model: Any,
    *,
    mesh_bytes: Optional[bytes] = None,
    mesh_format: str = ".glb",
    rig_type: str = "biped",
    rig_spec: str = "tripo",
    out_format: str = "glb",
    seed: int = 42,
    attempts: int = 1,
    on_attempt: Optional[Any] = None,
) -> dict[str, Any]:
    """
    Rig one mesh in the cloud, optionally retrying for a usable skeleton.

    Rigging is not deterministic: the same mesh and parameters can yield a
    skeleton with one named limb chain or with four. With ``attempts > 1`` each
    result is inspected and the best kept, stopping early once one has every
    limb chain its topology calls for.

    Returns the wrapper's dict, plus:
        rig_report (dict)  — `inspect_rig` output for the kept attempt
        rig_attempts (int) — how many calls were made

    Args:
        attempts:   Maximum rigging calls. Each one is billed.
        on_attempt: Optional ``fn(index, report, accepted)`` for progress.
    """
    from models.gen_motion.tripo_rigging_model import (
        EXPECTED_LIMBS,
        inspect_rig,
    )

    wanted = EXPECTED_LIMBS.get(str(rig_type).lower(), 0)
    best: dict[str, Any] | None = None
    best_report: dict[str, Any] | None = None

    for index in range(max(1, attempts)):
        result = rig_model.infer(
            mesh_bytes,
            mesh_format=mesh_format,
            seed=seed + index,
            mesh_url=mesh_url,
            rig_type=rig_type,
            rig_spec=rig_spec,
            out_format=out_format,
        )
        _require_bytes(result, "Rigging")

        # Only GLB can be inspected, so `attempts` is a no-op for FBX output.
        payload = result.get("glb_bytes")
        report = inspect_rig(payload) if payload else {
            "bones": 0, "named": 0, "anonymous": 0, "limbs": 0,
            "limb_names": [], "has_spine": False, "has_head": False,
        }
        accepted = bool(wanted) and report["limbs"] >= wanted

        if best_report is None or report["limbs"] > best_report["limbs"]:
            best, best_report = result, report

        if on_attempt is not None:
            on_attempt(index + 1, report, accepted)
        if accepted or not payload:
            break

    assert best is not None and best_report is not None
    best["rig_report"] = best_report
    best["rig_attempts"] = index + 1
    return best


def animate_rigged(
    rig_task_id: str,
    animation_model: Any,
    animation: str,
    *,
    out_format: str = "glb",
    animate_in_place: bool = False,
    seed: int = 42,
) -> dict[str, Any]:
    """
    Retarget a preset clip onto a skeleton a rigging task produced.

    Args:
        rig_task_id: ``task_id`` from `rig_mesh`'s result. Valid for 24 hours.
        animation:   A ``preset:`` identifier matching the rig's topology.
    """
    if not rig_task_id:
        raise ValueError(
            "rig_task_id is required: the animation endpoint works against the "
            "skeleton held server-side for a completed rigging task, not "
            "against a mesh or a URL."
        )
    result = animation_model.infer(
        rig_task_id,
        animation,
        seed=seed,
        out_format=out_format,
        animate_in_place=animate_in_place,
    )
    _require_bytes(result, "Animation")
    return result


def convert_format(
    mesh_url: str,
    format_model: Any,
    *,
    mesh_bytes: Optional[bytes] = None,
    output_format: str = "fbx",
    mesh_format: str = ".glb",
) -> dict[str, Any]:
    """Convert a mesh to another container in the cloud (FBX for engine import)."""
    result = format_model.infer(
        mesh_bytes,
        mesh_format=mesh_format,
        mesh_url=mesh_url,
        output_format=output_format,
    )
    _require_bytes(result, "Format conversion")
    return result


def _require_bytes(result: dict[str, Any], stage: str) -> None:
    """
    Fail on an empty artifact before it is written to disk.

    Accepts either key: ``file_bytes`` from the cloud stages, ``glb_bytes``
    from the local backend.
    """
    payload = result.get("file_bytes") or result.get("glb_bytes")
    if not isinstance(payload, (bytes, bytearray)) or not payload:
        raise RuntimeError(
            f"{stage} model returned no file bytes. "
            f"Keys present: {sorted(result)}"
        )


__all__ = ["check_riggable", "rig_mesh", "animate_rigged", "convert_format"]
