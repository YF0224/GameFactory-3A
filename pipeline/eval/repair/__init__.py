"""Repairs: one module per known evaluation failure, kept apart from the evaluation itself.

The pipeline is meant to run without these. When a project cannot be evaluated for a reason that is not a
product result (build / import / capture / transport / launch failure, a one-off platform difference), the
failure is recorded with its evidence, and a repair module here turns the last known-good state into a
evaluable one - reusing the existing record, plan or acceptance instead of re-running everything.

Each module keeps its own public entry points and receipts; nothing here is imported by the normal path
unless a failure is being repaired. They are grouped here together so a repair can be found, reused and
reviewed in one place, and so the evaluation code stays readable.

A repair must never change what the game does, the scoring rules or the evidence: it may only fix the
evaluation side (project copy, environment, transport, recovery of an accepted stage) and must write a
receipt next to the run it repaired. Product failures (crash, wrong result, low score) are not repaired.

Usage: import the module you need and call its entry point, e.g.

    from pipeline.eval.repair import ue_compile_compat
    plan = ue_compile_compat.selection(out)

``REGISTRY`` lists every module with the stage it belongs to and a one-line purpose, for discovery.
``fal`` / ``unresolved`` failures are described in the eval workflow notes; add new repairs as new modules
and register them here rather than as branches inside the evaluator.
"""
from __future__ import annotations

REGISTRY = {
    # launch / build
    'launch_repair': ('stage1', 'Sol repairs a project that does not build / import / start (environment + '
                                 'behaviour-preserving compile compatibility) in the eval copy'),
    'ue_compile_compat': ('stage1', 'reviewed, SHA-bound UE compile compatibility plan applied to the '
                                    'admission reference copy'),
    'completed_local_plugin_recovery': ('stage1', 'reuse a recorded take after a local plugin path change'),
    # capture / recording recovery
    'ue_g020_admission_recovery': ('stage1', 'recover a UE admission that stopped after the project copy was built'),
    'ue_g020_capture_continuation': ('stage1', 'continue a UE take whose capture was cut by a map load'),
    'ue_g025_launch_path_recovery': ('stage1', 'correct a launch path that does not match the delivered project'),
    'ue_g025_take2_recovery': ('stage1', 'finish a second take after the same predeclared capture slot failure'),
    'ue_g035_target_recovery': ('stage1', 're-target the capture window of a take that missed its action window'),
    'unity_g009_builder_recovery': ('stage1', 'record a Unity project whose authored scene needs the builder path'),
    'unity_natural_entry_recovery': ('stage1', 'reach a Unity project through its natural entry after a build stop'),
    'unity_authored_scene_recovery': ('stage1', 'open an authored Unity scene after an incomplete import'),
    'unity_imgui_transport_recovery': ('stage1', 'forward IMGUI input when the project has no Input System action'),
    'unity_input_recovery': ('stage1', 'restore missing input settings from the frozen snapshot'),
    'unity_audio_recovery': ('stage1', 'attach the audio observer when the editor build lacks the module'),
    'vite_build_only_recovery': ('stage1', 'build a Vite-based Three.js project without launching a browser'),
    'web_readiness_recovery': ('stage1', 'recover a web project that never became ready (readiness probe)'),
    'three_g011_addon_recovery': ('stage1', 'resolve a Three.js addon alias import that the bundler cannot serve'),
    'godot_duration_recovery': ('stage1', 'recover a Godot take cut by the recording duration limit'),
    'godot_duration_batch': ('stage1', 'batch of Godot duration recoveries'),
    'godot_duration_metadata_recovery': ('stage1', 'recover Godot duration metadata for a finished take'),
    'godot_duration_audio_metadata_recovery': ('stage1', 'recover Godot audio duration metadata'),
    'godot_existing_window_recovery': ('stage1', 'attach to an already running Godot window (no relaunch)'),
    'godot_import_log_recovery': ('stage1', 'diagnose a Godot import failure from its log'),
    'dual_client_unity_recovery': ('stage1', 'recover the second independent Unity client of a dual-client pair'),
}


def modules():
    """Names of the repair modules that exist on disk (registered ones first)."""
    import pkgutil
    present = {m.name for m in pkgutil.iter_modules(__path__)}
    return [name for name in REGISTRY if name in present] + sorted(present - set(REGISTRY) - {'__init__'})


def describe() -> list[dict]:
    """Machine-readable list of the available repairs (stage, purpose)."""
    return [{'module': name, 'stage': REGISTRY.get(name, ('stage1', ''))[0], 'purpose': REGISTRY.get(name, ('', ''))[1]}
            for name in modules()]
