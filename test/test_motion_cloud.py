#!/usr/bin/env python3
"""
test/test_motion_cloud.py

Integration test for the cloud rigging + animation chain
(TokenHub / Tripo), the drop-in replacement for Puppeteer + MoMask.

Two modes, and the difference matters:

  --stub  (default)  No network, no key, no credits. Exercises the plumbing:
                     task parsing, artifact paths, meta.json, the operator's
                     branch logic. This is what CI runs.

  --real             Real API calls against tokenhub.tencentmaas.com. Costs
                     credits and needs TOKENHUB_API_KEY plus post-pay billing
                     enabled at console.cloud.tencent.com/tokenhub/inference.

THE MESH GOES IN AS A URL. These endpoints download the mesh themselves, the
gateway has no upload endpoint, and a `data:` URI is accepted by /submit and then
fails in the worker with FailedOperation.DownloadError. So `--real` needs
`--mesh-url <public link>`; a local path alone cannot be submitted, and the test
says so rather than failing inside a billed call.

Results are written as local files and reviewed locally: `rig_viewer.html` beside
them reads both GLB and FBX and reports the bone count, the clips, and any bone
bound to nothing.

Usage:
    python test/test_motion_cloud.py                          # stub, no cost
    TOKENHUB_API_KEY=sk-... python test/test_motion_cloud.py --real \
        --mesh-url https://example.com/tpose_body_lo.glb --out-format fbx
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "test" / "harness"))

PASSED: list[str] = []
FAILED: list[tuple[str, str]] = []

#: A URL the stub accepts and no real call is ever made against.
STUB_MESH_URL = "https://stub.invalid/tpose_body_lo.glb"


def check(name: str, condition: bool, detail: str = "") -> bool:
    if condition:
        PASSED.append(name)
        print(f"  \033[32mPASS\033[0m {name}")
    else:
        FAILED.append((name, detail))
        print(f"  \033[31mFAIL\033[0m {name}" + (f"\n       {detail}" if detail else ""))
    return bool(condition)


#: Humanoid meshes to try, in preference order. These are build products of the
#: 3AGameFactory knight demo, not fixtures — absent from a fresh checkout, which
#: is why the test falls back to a URL-only run when none is present.
_MESH_CANDIDATES = (
    "test_data/outputs/*/*/assets/3d_object/*/parts/tpose_body_lo.glb",
    "test_data/outputs/*/*/assets/3d_object/*/parts/tpose_body.glb",
)


def find_humanoid_mesh(explicit: str | None = None) -> Path | None:
    """A local copy of the mesh, used for the cache key and for nothing else."""
    if explicit:
        path = Path(explicit)
        return path if path.is_file() else None
    for root in (_REPO_ROOT, _REPO_ROOT.parent / "GameFactory-3A"):
        for pattern in _MESH_CANDIDATES:
            matches = sorted(root.glob(pattern))
            if matches:
                return matches[0]
    return None


def build_operator(*, real: bool, output_dir: Path, run_id: str):
    """Wire GenMotionOperator to either the stub or the real cloud models."""
    from operators.gen_motion.operator import GenMotionOperator

    if not real:
        import stubs
        return GenMotionOperator(
            output_dir=str(output_dir),
            run_id=run_id,
            rig_check_model=stubs.StubTripoRigCheckModel(),
            cloud_rig_model=stubs.StubTripoRiggingModel(),
            cloud_animation_model=stubs.StubTripoAnimationModel(),
            cloud_format_model=stubs.StubTripoFormatModel(),
        )

    from models.gen_motion.tripo_rigging_model import (
        TripoAnimationModel,
        TripoFormatModel,
        TripoRigCheckModel,
        TripoRiggingModel,
    )
    cache = str(_REPO_ROOT / ".cache" / "tokenhub")
    return GenMotionOperator(
        output_dir=str(output_dir),
        run_id=run_id,
        rig_check_model=TripoRigCheckModel(cache_dir=cache, verbose=True),
        cloud_rig_model=TripoRiggingModel(cache_dir=cache, verbose=True),
        cloud_animation_model=TripoAnimationModel(cache_dir=cache, verbose=True),
        cloud_format_model=TripoFormatModel(cache_dir=cache, verbose=True),
    )


def magic_ok(path: Path, out_format: str) -> tuple[bool, str]:
    """Whether a file opens as the container that was asked for."""
    head = path.read_bytes()[:21]
    if out_format == "glb":
        return head[:4] == b"glTF", f"first 4 bytes: {head[:4]!r}"
    return head.startswith(b"Kaydara FBX Binary"), f"first 21 bytes: {head!r}"


def test_cloud_rig(op, task: dict, out_format: str) -> dict:
    """Rigging alone: a mesh URL in, a rigged file out."""
    print("\ncloud_rig — skeleton and skin weights from the cloud")
    result = op.run({**task, "task_id": "cloud_rig_001", "task_type": "cloud_rig"})

    rigged = result.get("rigged_glb_path")
    check("a rigged file path is returned", bool(rigged), str(result))
    if rigged:
        path = Path(rigged)
        check("the rigged file exists and is not empty",
              path.is_file() and path.stat().st_size > 0,
              f"{rigged}: {path.stat().st_size if path.is_file() else 'missing'} bytes")
        # The extension has to follow the requested container, or an engine
        # importer picks the wrong reader and reports a corrupt file.
        check(f"it is named .{out_format}", path.suffix == f".{out_format}",
              f"got {path.suffix}")
        ok, detail = magic_ok(path, out_format)
        check(f"it opens as a real {out_format.upper()}", ok, detail)

    check("the local backend keys are still present",
          "rig_path" in result and "motion_bvh_path" in result,
          "a returned key was removed — that breaks callers (README: never "
          "remove or rename a returned dict key)")
    return result


def test_cloud_humanoid(op, task: dict, out_format: str) -> dict:
    """The full chain: check → rig → animate with a preset clip."""
    print("\ncloud_humanoid — rig, then retarget a preset clip onto it")
    result = op.run({
        **task,
        "task_id": "cloud_humanoid_001",
        "task_type": "cloud_humanoid",
        "animation": "preset:walk",
    })

    for key in ("rigged_glb_path", "animated_glb_path"):
        value = result.get(key)
        check(f"{key} is returned", bool(value), str(result)[:200])
        if value:
            ok, detail = magic_ok(Path(value), out_format)
            check(f"{key} opens as a real {out_format.upper()}", ok, detail)

    # The animated file must differ from the rigged one — an animation step
    # that returned its input unchanged would pass every check above.
    rigged, animated = result.get("rigged_glb_path"), result.get("animated_glb_path")
    if rigged and animated:
        check("the animated file is not byte-identical to the rigged one",
              Path(rigged).read_bytes() != Path(animated).read_bytes(),
              "animation returned its input unchanged")
    return result


def test_mesh_url_is_required(op, task: dict) -> None:
    """A cloud task without a mesh URL must fail before it is billed."""
    print("\na cloud task without a mesh URL is refused")
    without = {k: v for k, v in task.items() if k != "mesh_url"}
    try:
        op.run({**without, "task_id": "no_url", "task_type": "cloud_rig"})
        check("a missing mesh_url is refused", False, "it was accepted")
    except ValueError as exc:
        # The message has to say what to do about it: "pass a URL" is not
        # actionable when the file is on a laptop and there is no upload endpoint.
        check("a missing mesh_url is refused, saying the mesh is fetched remotely",
              "mesh_url" in str(exc) and "upload" in str(exc).lower(), str(exc))


def test_free_text_motion_is_refused(op, task: dict) -> None:
    """
    A motion *description* must be refused, not approximated.

    This endpoint retargets a fixed preset library; it is not MoMask.
    """
    print("\na free-text motion description is refused")
    try:
        op.run({**task, "task_id": "free_text", "task_type": "cloud_humanoid",
                "animation": "walk forward at a steady pace"})
        check("free text is refused", False, "it was accepted")
    except ValueError as exc:
        check("free text is refused, naming the preset form",
              "preset:" in str(exc), str(exc))


def test_mixamo_cannot_be_animated(op, task: dict) -> None:
    """
    `spec=mixamo` must be refused for the animated chain, before it is billed.

    The retarget step rejects mixamo-named skeletons, so the failure would
    otherwise land after the rigging call has already been paid for.
    """
    print("\na mixamo rig is refused for the animated chain")
    try:
        op.run({**task, "task_id": "mixamo_anim", "task_type": "cloud_humanoid",
                "animation": "preset:walk", "rig_spec": "mixamo"})
        check("a mixamo rig is refused for animation", False, "it was accepted")
    except ValueError as exc:
        check("a mixamo rig is refused before the rigging call",
              "mixamo" in str(exc).lower() and "cloud_rig" in str(exc), str(exc))


def test_rig_inspection(op, task: dict) -> None:
    """
    `inspect_rig` must separate a usable skeleton from an unusable one.

    Two rigs of the same mesh can carry the same bone count and the same clean
    weights, differing only in how many joints are named — and only named
    joints are driven by a preset clip.
    """
    print("\nrig inspection separates a named skeleton from an anonymous one")
    from models.gen_motion.tripo_rigging_model import inspect_rig

    import stubs
    good = inspect_rig(stubs.make_rigged_glb(limbs=4, anonymous=4))
    poor = inspect_rig(stubs.make_rigged_glb(limbs=1, anonymous=13))

    check("a four-chain rig reports 4 limbs", good["limbs"] == 4, str(good))
    check("a one-chain rig reports 1 limb", poor["limbs"] == 1, str(poor))
    check("the anonymous joints are counted",
          poor["anonymous"] == 13 and good["anonymous"] == 4,
          f"good={good['anonymous']} poor={poor['anonymous']}")
    check("the spine and head are recognised",
          good["has_spine"] and good["has_head"], str(good))
    # Same total bones, different quality — the case a bone count misses.
    same = inspect_rig(stubs.make_rigged_glb(limbs=1, anonymous=6))
    other = inspect_rig(stubs.make_rigged_glb(limbs=1, anonymous=6))
    check("inspection is stable for identical input",
          same == other, f"{same} != {other}")


def test_rig_retry_picks_the_better_skeleton(op, task: dict) -> None:
    """
    With `rig_attempts > 1`, a poor first rig must be retried and the best kept.

    Rigging is non-deterministic, so without a retry the caller keeps whatever
    the first call happened to produce.
    """
    print("\na poor first rig is retried and the better one kept")
    # The stub's rig quality advances per call and earlier tests have already
    # called it; reset so this test starts from the poor rig.
    op.cloud_rig_model._attempt = 0

    result = op.run({**task, "task_id": "retry_rig", "task_type": "cloud_rig",
                     "rig_type": "quadruped", "rig_attempts": 3,
                     "out_format": "glb"})

    report_path = result.get("rig_report_path")
    check("a rig report is written", bool(report_path), str(result)[:200])
    if not report_path:
        return

    import json as _json
    report = _json.loads(Path(report_path).read_text())
    check("the report records how many attempts were made",
          report.get("attempts", 0) >= 2,
          f"attempts={report.get('attempts')} — the stub's first rig has one "
          "limb chain, so at least one retry was required")
    check("the kept rig has every limb chain its topology needs",
          report["limbs"] == report["expected_limbs"],
          f"limbs={report['limbs']} expected={report['expected_limbs']}")
    check("the report names the limb chains it found",
          len(report.get("limb_names", [])) == report["limbs"],
          str(report.get("limb_names")))


def test_rig_check_classification_is_parsed(op, task: dict) -> None:
    """
    The rig type must be read from a refusal as well as from a pass.

    A refusal arrives as ``status: failed`` with the classification only in
    ``error.message``, and `others` must never be forwarded as a `rig_type`.
    """
    print("\nrig-check classification is parsed from both a pass and a refusal")
    from models.gen_motion.tripo_rigging_model import (
        RIG_TYPES,
        UNCLASSIFIED,
        _parse_check,
    )

    passed = _parse_check({"status": "completed",
                           "output": {"riggable": True, "rig_type": "quadruped"}})
    check("a pass yields riggable and its rig_type",
          passed["riggable"] and passed["rig_type"] == "quadruped", str(passed))
    check("a pass is not flagged unclassified",
          not passed["unclassified"], str(passed))

    refused = _parse_check({
        "status": "failed",
        "error": {"code": "FailedOperation.NotRiggable",
                  "message": "model is not riggable, rig_type=others"}})
    check("a refusal is not riggable", not refused["riggable"], str(refused))
    check("a refusal still yields its classification",
          refused["rig_type"] == UNCLASSIFIED, str(refused))
    check("an unclassifiable mesh is flagged as such",
          refused["unclassified"], str(refused))
    check("'others' is not a rig_type the rigging endpoint accepts",
          UNCLASSIFIED not in RIG_TYPES, f"{UNCLASSIFIED} in {sorted(RIG_TYPES)}")

    biped_refusal = _parse_check({
        "status": "failed",
        "error": {"message": "model is not riggable, rig_type=biped"}})
    check("a refusal naming a real topology is not flagged unclassified",
          biped_refusal["rig_type"] == "biped"
          and not biped_refusal["unclassified"], str(biped_refusal))


def test_rig_type_from_check_is_used(op, task: dict) -> None:
    """
    The rigging call must use the topology rig-check reported, not the default.

    Sending `biped` for a quadruped yields a skeleton the quadruped presets
    cannot drive, and the mismatch is only visible once the clip plays.
    """
    print("\nthe rig_type from rig-check reaches the rigging call")
    op.rig_check_model._rig_type = "quadruped"
    op.cloud_rig_model.calls.clear()

    op.run({**task, "task_id": "rig_type_flow", "task_type": "cloud_rig",
            # Deliberately wrong, to prove the check's answer wins.
            "rig_type": "biped", "out_format": "glb"})

    forwarded = [c for c in op.cloud_rig_model.calls if c.get("op") == "infer"]
    check("the rigging call received the checked rig_type",
          bool(forwarded) and forwarded[0]["rig_type"] == "quadruped",
          f"got {forwarded[0]['rig_type'] if forwarded else 'no call'!r}, "
          "expected 'quadruped'")


def test_preset_follows_rig_type(op, task: dict) -> None:
    """The default preset must match the topology rig-check reported."""
    print("\nthe default animation preset follows the rig type")
    from models.gen_motion.tripo_rigging_model import default_preset

    check("a quadruped gets the quadruped walk",
          default_preset("quadruped") == "preset:quadruped:walk",
          default_preset("quadruped"))
    check("a biped gets the plain walk",
          default_preset("biped") == "preset:walk", default_preset("biped"))
    check("a serpentine gets its own march",
          default_preset("serpentine") == "preset:serpentine:march",
          default_preset("serpentine"))

    op.rig_check_model._rig_type = "quadruped"
    op.cloud_animation_model.calls.clear()
    op.run({**task, "task_id": "preset_flow", "task_type": "cloud_humanoid",
            "out_format": "glb"})
    animated = [c for c in op.cloud_animation_model.calls if c.get("op") == "infer"]
    check("a quadruped rig is animated with a quadruped preset",
          bool(animated) and animated[0]["animation"] == "preset:quadruped:walk",
          f"got {animated[0]['animation'] if animated else 'no call'!r}")
    op.rig_check_model._rig_type = "biped"


def test_bad_rig_type_is_refused_locally(op, task: dict) -> None:
    """An unknown `rig_type` must be refused before the call is made."""
    print("\nan invalid rig_type is refused without calling the API")
    try:
        op.run({**task, "task_id": "bad_type", "task_type": "cloud_rig",
                "skip_rig_check": True, "rig_type": "octopus"})
        check("an invalid rig_type is refused", False, "it was accepted")
    except ValueError as exc:
        check("an invalid rig_type is refused, listing the accepted values",
              "octopus" in str(exc) and "quadruped" in str(exc), str(exc))


def test_single_attempt_does_not_retry(op, task: dict) -> None:
    """The default must stay at one call, because every attempt is billed."""
    print("\nthe default makes exactly one rigging call")
    before = len(op.cloud_rig_model.calls)
    op.run({**task, "task_id": "one_shot", "task_type": "cloud_rig",
            "rig_type": "quadruped", "out_format": "glb"})
    check("one task_type='cloud_rig' run costs one rigging call",
          len(op.cloud_rig_model.calls) - before == 1,
          f"made {len(op.cloud_rig_model.calls) - before} calls")


def test_rig_inspection_reads_both_naming_schemes(op, task: dict) -> None:
    """
    `inspect_rig` must understand both skeletons this service emits.

    Non-bipeds come back as ``tripo::0_Left_Limb_0``, bipeds as ``L_Thigh`` /
    ``R_Forearm``. Recognising only the prefixed form scores a complete
    humanoid rig as zero named joints.
    """
    print("\nrig inspection reads the generic and humanoid naming schemes")
    from models.gen_motion.tripo_rigging_model import inspect_rig

    import stubs
    generic = inspect_rig(stubs.make_rigged_glb(limbs=4, anonymous=4))
    check("a generic rig is recognised", generic["scheme"] == "generic",
          str(generic))
    check("its limb chains are counted", generic["limbs"] == 4, str(generic))

    humanoid = inspect_rig(stubs.make_humanoid_glb())
    check("a humanoid rig is recognised", humanoid["scheme"] == "humanoid",
          str(humanoid))
    check("its four limbs are counted", humanoid["limbs"] == 4, str(humanoid))
    check("anatomy is not counted as anonymous", humanoid["anonymous"] == 0,
          f"{humanoid['anonymous']} joints read as unresolved")
    check("the spine and head are found",
          humanoid["has_spine"] and humanoid["has_head"], str(humanoid))

    poor = inspect_rig(stubs.make_rigged_glb(limbs=1, anonymous=13))
    check("a one-chain rig still reports 1 limb", poor["limbs"] == 1, str(poor))
    check("its unresolved joints are counted", poor["anonymous"] == 13,
          str(poor))


def test_flipped_joints_are_detected(op, task: dict) -> None:
    """
    `inspect_animation` must flag joints the retarget inverted.

    A clip whose first frame sits ~180 deg from a joint's rest orientation
    points that bone backwards and shears the skin across it. The rig itself
    passes every check, so the clip is where this has to be caught.
    """
    print("\nan inverted retarget is detected, a large pose is not")
    from models.gen_motion.tripo_rigging_model import (
        FLIPPED_JOINT_DEGREES,
        inspect_animation,
    )

    import stubs
    flipped = inspect_animation(stubs.make_animated_glb(first_frame_degrees=174))
    check("a 174 deg first frame is flagged", bool(flipped["flipped"]),
          str(flipped))
    check("the flagged joint is named",
          bool(flipped["flipped"]) and flipped["flipped"][0][0],
          str(flipped["flipped"]))

    # A horse that animated correctly reached 108 deg, so the threshold has to
    # sit above a legitimate mid-stride pose.
    posed = inspect_animation(stubs.make_animated_glb(first_frame_degrees=108))
    check("a 108 deg first frame is not flagged", not posed["flipped"],
          str(posed))
    check("the threshold sits between the two",
          108 < FLIPPED_JOINT_DEGREES < 174,
          f"FLIPPED_JOINT_DEGREES={FLIPPED_JOINT_DEGREES}")


def test_animation_report_is_written(op, task: dict) -> None:
    """The operator must record how the clip landed, beside the animated file."""
    print("\nthe animated run writes an animation report")
    result = op.run({**task, "task_id": "anim_report",
                     "task_type": "cloud_humanoid", "out_format": "glb"})

    path = result.get("anim_report_path")
    check("an animation report is returned", bool(path), str(result)[:200])
    if not path:
        return
    import json as _json
    report = _json.loads(Path(path).read_text())
    for key in ("clip", "joints", "moving", "flipped", "worst"):
        check(f"the report carries {key}", key in report, str(report))


def test_unrecognised_task_type(op, task: dict) -> None:
    print("\nan unknown task_type names the supported ones")
    try:
        op.run({**task, "task_id": "bogus", "task_type": "cloud_teleport"})
        check("an unknown task_type is refused", False, "it was accepted")
    except NotImplementedError as exc:
        check("an unknown task_type is refused, listing what is supported",
              "cloud_rig" in str(exc) and "cloud_humanoid" in str(exc),
              str(exc))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--real", action="store_true",
                        help="Call the real API (costs credits, needs a key)")
    parser.add_argument("--mesh-url", default=None,
                        help="Public http(s) link to the humanoid mesh to rig")
    parser.add_argument("--mesh", default=None,
                        help="Local copy of the same mesh, used for the cache key")
    parser.add_argument("--out-format", default="glb", choices=("glb", "fbx"),
                        help="Container the provider should return")
    parser.add_argument("--out", default=None,
                        help="Output directory (default: test_data/outputs/...)")
    args = parser.parse_args()

    mode = "REAL API" if args.real else "STUB (no network, no cost)"
    print(f"cloud rigging + animation chain — {mode}")
    print("=" * 66)

    if args.real:
        if not os.environ.get("TOKENHUB_API_KEY"):
            print("\nTOKENHUB_API_KEY is not set. Get a key at "
                  "https://console.cloud.tencent.com/tokenhub and enable "
                  "post-pay billing at "
                  "https://console.cloud.tencent.com/tokenhub/inference")
            return 2
        if not args.mesh_url:
            print("\n--mesh-url is required for --real. The endpoint downloads "
                  "the mesh itself:\n"
                  "  - there is no upload endpoint on this gateway, and\n"
                  "  - a data: URI is accepted by /submit and then fails in the\n"
                  "    worker with FailedOperation.DownloadError.\n"
                  "Host the mesh (object storage is what the provider's own\n"
                  "results are served from) and pass the link.")
            return 2

    mesh_url = args.mesh_url or STUB_MESH_URL
    mesh = find_humanoid_mesh(args.mesh)
    print(f"mesh_url: {mesh_url}")
    print(f"local copy: {mesh}"
          + (f"  ({mesh.stat().st_size / 1e6:.1f} MB)" if mesh else " (none — "
             "cache keys will use the URL)"))
    print(f"out_format: {args.out_format}\n")

    out_dir = Path(args.out) if args.out else (
        _REPO_ROOT / "test_data" / "outputs" / "_cloud_motion_test")
    out_dir.mkdir(parents=True, exist_ok=True)

    task = {
        "mesh_url": mesh_url,
        "out_format": args.out_format,
        "seed": 42,
    }
    if mesh is not None:
        task["target_mesh_path"] = str(mesh)

    op = build_operator(real=args.real, output_dir=out_dir, run_id="cloud_test")

    t0 = time.time()
    test_cloud_rig(op, task, args.out_format)
    test_cloud_humanoid(op, task, args.out_format)
    test_mesh_url_is_required(op, task)
    test_free_text_motion_is_refused(op, task)
    test_mixamo_cannot_be_animated(op, task)
    if not args.real:
        # These need a scripted sequence of rig qualities and classifications,
        # which only the stub can provide.
        test_rig_check_classification_is_parsed(op, task)
        test_rig_type_from_check_is_used(op, task)
        test_preset_follows_rig_type(op, task)
        test_bad_rig_type_is_refused_locally(op, task)
        test_rig_inspection(op, task)
        test_rig_inspection_reads_both_naming_schemes(op, task)
        test_flipped_joints_are_detected(op, task)
        test_animation_report_is_written(op, task)
        test_rig_retry_picks_the_better_skeleton(op, task)
        test_single_attempt_does_not_retry(op, task)
    test_unrecognised_task_type(op, task)
    elapsed = time.time() - t0

    print("\n" + "=" * 66)
    print(f"{len(PASSED)} passed, {len(FAILED)} failed  ({elapsed:.1f}s)")
    print(f"artifacts: {out_dir}")
    print("Review them locally:\n"
          f"  python3 test_data/outputs/_viewer_lib/install_rig_viewers.py {out_dir}\n"
          "  cd test_data/outputs && python3 -m http.server 8765")
    if FAILED:
        for name, detail in FAILED:
            print(f"  FAILED: {name}" + (f" — {detail}" if detail else ""))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
