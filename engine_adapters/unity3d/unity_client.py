"""Stable Agent-facing facade for Unity3D engine environment operations."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Mapping, Sequence

from ._internal.transport import UnityEditorTransport
from .assets import UnityAssetsClient
from .animation import UnityAnimationClient
from .bindings import UnityBindingsClient
from .build import UnityBuildClient
from .config import DEFAULT_API_VERSION, UnityClientConfig
from .observe import UnityObserveClient
from .project import UnityProjectClient
from .plugin import UnityPluginClient
from .playtest import UnityPlaytestClient
from .reflection import UnityReflectionClient
from .runtime import UnityRuntimeClient
from .testing import UnityTestingClient
from .world import UnityWorldClient


class UnityClient:
    """
    Stable Unity3D engine environment API.

    Agent code must construct UnityClient from `engine_adapters.unity3d` and
    use its public namespace clients. Internal modules are version-specific
    and are not part of the API contract.
    """

    def __init__(
        self,
        project_path: str | Path | None = None,
        unity_root: str | Path | None = None,
        api_version: str = DEFAULT_API_VERSION,
        *,
        host: str | None = None,
        port: int | None = None,
        runtime_host: str | None = None,
        runtime_port: int | None = None,
        editor_batchmode_timeout: int | None = None,
    ) -> None:
        self._config = UnityClientConfig.resolve(
            project_path=project_path,
            unity_root=unity_root,
            api_version=api_version,
            host=host,
            port=port,
            runtime_host=runtime_host,
            runtime_port=runtime_port,
            editor_batchmode_timeout=editor_batchmode_timeout,
        )
        transport = UnityEditorTransport(self._config)

        self.project = UnityProjectClient(self._config)
        self.build = UnityBuildClient(self._config)
        self.testing = UnityTestingClient(self._config)
        self.plugin = UnityPluginClient(self._config)
        self.assets = UnityAssetsClient(
            self._config,
            transport,
        )
        self.animation = UnityAnimationClient(self.assets)
        self.bindings = UnityBindingsClient(
            transport,
            self.assets,
        )
        self.world = UnityWorldClient(
            self._config,
            transport,
            self.assets,
        )
        self.reflection = UnityReflectionClient(
            transport,
            self.assets,
        )
        self.runtime = UnityRuntimeClient(
            self._config,
            self.assets,
        )
        self.observe = UnityObserveClient(
            self._config,
            transport,
        )
        self.playtest = UnityPlaytestClient(self._config)

    @property
    def api_version(self) -> str:
        return self._config.api_version

    def get_environment_info(self) -> dict[str, Any]:
        info = self.project.get_info()
        info["operation"] = "client.get_environment_info"
        info["payload"]["remote_url"] = (
            self._config.remote_url
        )
        info["payload"]["runtime_input_host"] = (
            self._config.runtime_host
        )
        info["payload"]["runtime_input_port"] = (
            self._config.runtime_port
        )
        info["payload"]["editor_batchmode_timeout"] = (
            self._config.editor_batchmode_timeout
        )
        return info

    def generate_game(
        self,
        *,
        asset_sources: Sequence[Mapping[str, Any]] = (),
        mechanic_source: Mapping[str, Any] | None = None,
        ui_source: Mapping[str, Any] | None = None,
        scene_spec: Mapping[str, Any] | None = None,
        build_target: str = "",
        build_output: str = "",
        build: bool = True,
        launch_editor: bool = True,
        enter_play: bool = False,
        play_method: str = "GameFactory3APlayMode.Enter",
        replace_existing: bool = True,
        include_tests: bool = True,
        dry_run: bool = False,
        native_editor: bool = True,
    ) -> dict[str, Any]:
        """Run the Agent-facing generated-game sequence through this client.

        This is orchestration over the same public namespace clients exposed by
        ``UnityClient``.  Asset descriptors must resolve through the canonical
        benchmark output registry; no source path is copied directly from
        ``test_samples`` or the repository's prepared-asset directory.
        """
        if native_editor:
            return self._generate_game_native(
                asset_sources=asset_sources,
                mechanic_source=mechanic_source,
                ui_source=ui_source,
                scene_spec=scene_spec,
                build_target=build_target,
                build_output=build_output,
                build=build,
                launch_editor=launch_editor,
                enter_play=enter_play,
                replace_existing=replace_existing,
                include_tests=include_tests,
                dry_run=dry_run,
            )
        steps: list[dict[str, Any]] = []
        artifacts: list[dict[str, Any]] = []
        warnings: list[str] = []

        def record(result: dict[str, Any]) -> bool:
            steps.append(result)
            artifacts.extend(result.get("artifacts") or [])
            warnings.extend(str(item) for item in result.get("warnings") or [])
            return bool(result.get("ok"))

        validation = self.project.validate()
        if not validation.get("ok"):
            project_path = self._config.project_path
            if project_path is None or project_path.exists():
                return {
                    "ok": False,
                    "operation": "client.generate_game",
                    "artifacts": artifacts,
                    "warnings": warnings,
                    "errors": [
                        "Unity project is not valid and cannot be created "
                        "automatically because its directory already exists",
                        *[str(item) for item in validation.get("errors") or []],
                    ],
                    "payload": {"steps": steps, "validation": validation},
                }
            created = self.project.create(dry_run=dry_run)
            if not record(created):
                return self._workflow_failure(steps, artifacts, warnings)
        else:
            record(validation)

        if mechanic_source is not None:
            mechanic = self.plugin.install(
                mechanic_source,
                replace_existing=replace_existing,
                include_tests=include_tests,
                dry_run=dry_run,
            )
            if not record(mechanic):
                return self._workflow_failure(steps, artifacts, warnings)
        if ui_source is not None:
            ui = self.plugin.install(
                ui_source,
                replace_existing=replace_existing,
                include_tests=False,
                dry_run=dry_run,
            )
            if not record(ui):
                return self._workflow_failure(steps, artifacts, warnings)

        if asset_sources:
            imported = self.assets.import_batch(
                asset_sources,
                options={"replace_existing": replace_existing},
                dry_run=dry_run,
            )
            if not record(imported):
                return self._workflow_failure(steps, artifacts, warnings)

        if scene_spec is not None:
            composed = self.world.compose_scene(
                scene_spec,
                dry_run=dry_run,
            )
            if not record(composed):
                return self._workflow_failure(steps, artifacts, warnings)

        built: dict[str, Any] | None = None
        if build:
            built = self.build.project(
                target=build_target,
                output_path=build_output,
                dry_run=dry_run,
            )
            if not record(built):
                return self._workflow_failure(steps, artifacts, warnings)

        launched: dict[str, Any] | None = None
        if launch_editor:
            extra_args: list[str] = []
            if enter_play:
                if not play_method.strip():
                    return self._workflow_failure(
                        steps,
                        artifacts,
                        warnings,
                        errors=["play_method must not be empty when enter_play is true"],
                    )
                extra_args.extend(["-executeMethod", play_method])
            launched = self.runtime.launch_editor(
                scene_path=str((scene_spec or {}).get("output_scene") or ""),
                extra_args=extra_args,
                dry_run=dry_run,
            )
            if not record(launched):
                return self._workflow_failure(steps, artifacts, warnings)

        payload: dict[str, Any] = {
            "steps": steps,
            "project_path": str(self._config.project_path or ""),
            "build": built,
            "editor": launched,
            "browser": {
                "engine": "unity3d",
                "project_path": str(self._config.project_path or ""),
                "webgl_build": str(
                    (built or {}).get("payload", {}).get("output_path") or ""
                ),
                "gateway_env": {
                    "A3GAME_BROWSER_ENGINE": "unity3d",
                    "A3GAME_UNITY_PROJECT": str(self._config.project_path or ""),
                    "A3GAME_UNITY_ROOT": str(self._config.unity_root or ""),
                },
            },
        }
        return {
            "ok": True,
            "operation": "client.generate_game",
            "artifacts": artifacts,
            "warnings": list(dict.fromkeys(warnings)),
            "errors": [],
            "payload": payload,
        }

    def _generate_game_native(
        self,
        *,
        asset_sources: Sequence[Mapping[str, Any]],
        mechanic_source: Mapping[str, Any] | None,
        ui_source: Mapping[str, Any] | None,
        scene_spec: Mapping[str, Any] | None,
        build_target: str,
        build_output: str,
        build: bool,
        launch_editor: bool,
        enter_play: bool,
        replace_existing: bool,
        include_tests: bool,
        dry_run: bool,
    ) -> dict[str, Any]:
        """Prepare one Unity-native Editor job and execute it once."""
        project = self._config.project_path
        if project is None:
            return self._workflow_failure(
                [], [], [], errors=["project_path is not configured"]
            )
        steps: list[dict[str, Any]] = []
        artifacts: list[dict[str, Any]] = []
        warnings: list[str] = []

        # A generated-game call is allowed to start from an empty output
        # location.  Project creation remains a public UnityClient operation,
        # but the one-call Agent workflow must not require callers to invoke
        # it separately before submitting the native Editor job.
        if not project.is_dir():
            created = self.project.create(dry_run=dry_run)
            steps.append(created)
            artifacts.extend(created.get("artifacts") or [])
            warnings.extend(str(item) for item in created.get("warnings") or [])
            if not created.get("ok"):
                return self._workflow_failure(
                    steps,
                    artifacts,
                    warnings,
                    errors=list(created.get("errors") or []),
                )
        validation = self.project.validate()
        steps.append(validation)
        if not validation.get("ok"):
            return self._workflow_failure(
                steps,
                artifacts,
                warnings,
                errors=list(validation.get("errors") or []),
            )
        jobs = project / "Library" / "GameFactory3A" / "jobs"
        jobs.mkdir(parents=True, exist_ok=True)

        try:
            plugin_entries: list[dict[str, Any]] = []
            legacy_test_targets: list[Path] = []
            for source, include_source_tests in (
                (mechanic_source, include_tests),
                (ui_source, False),
            ):
                if source is None:
                    continue
                descriptor = dict(source)
                task_kind = str(descriptor.get("task_kind") or "").strip()
                descriptor.setdefault("artifact_key", "output_dir")
                resolved = self.plugin._sources.resolve(descriptor, allow_directory=True)
                subpath = {"mechanic": "generated_plugin", "ui": "generated_ui"}.get(task_kind, "")
                source_root = (resolved.path / subpath if subpath else resolved.path).resolve()
                asmdefs = sorted(source_root.rglob("*.asmdef"))
                if not asmdefs:
                    raise ValueError(f"Generated plugin has no asmdef: {source_root}")
                target = project / "Assets" / asmdefs[0].stem
                test_source = resolved.task_dir / "generated_test_source" if include_source_tests and include_tests else None
                plugin_entries.append({
                    "source_root": str(source_root),
                    "target": str(target),
                    "test_source": str(test_source or ""),
                    "replace_existing": replace_existing,
                })
                # Older public plugin.install calls copied the generated test
                # assembly beside the plugin (Assets/<Module>.Tests).  The
                # one-job contract keeps it under Assets/<Module>/Tests.  A
                # Unity project can enter Safe Mode before the Editor job
                # gets a chance to remove that legacy sibling, so clean only
                # the known mechanic targets before writing the manifest.
                if task_kind == "mechanic":
                    legacy_test_targets.append(
                        project / "Assets" / f"{asmdefs[0].stem}.Tests"
                    )
                asmdef = json.loads(asmdefs[0].read_text(encoding="utf-8"))
                if "A3GameRuntime" in asmdef.get("references", []):
                    framework = project / "Assets" / "A3GameRuntime"
                    framework_source = Path(__file__).resolve().parent / "plugin" / "A3GameRuntime"
                    if not any(item.get("target") == str(framework) for item in plugin_entries):
                        plugin_entries.insert(0, {
                            "source_root": str(framework_source),
                            "target": str(framework),
                            "test_source": "",
                            "replace_existing": replace_existing,
                        })

            if replace_existing:
                for legacy_target in legacy_test_targets:
                    if not legacy_target.is_dir():
                        continue
                    shutil.rmtree(legacy_target)
                    legacy_meta = Path(str(legacy_target) + ".meta")
                    if legacy_meta.is_file():
                        legacy_meta.unlink()
                    warnings.append(
                        "Removed legacy generated test assembly directory: "
                        f"{legacy_target}"
                    )

            asset_plan = self.assets.import_batch(
                asset_sources,
                options={"replace_existing": replace_existing},
                dry_run=True,
            ) if asset_sources else {"ok": True, "payload": {"entries": []}}
            if not asset_plan.get("ok"):
                return self._workflow_failure(
                    steps, artifacts, warnings,
                    errors=list(asset_plan.get("errors") or ["asset descriptor resolution failed"]),
                )

            scene_job_path = ""
            if scene_spec is not None:
                scene_job = jobs / "scene.json"
                scene_job.write_text(json.dumps(dict(scene_spec), indent=2), encoding="utf-8")
                scene_job_path = str(scene_job)

            build_job_path = ""
            if build:
                target = str(build_target or "")
                build_plan = self.build.project(
                    target=target,
                    output_path=build_output,
                    scenes=[str((scene_spec or {}).get("output_scene") or "")],
                    dry_run=True,
                )
                if not build_plan.get("ok"):
                    return self._workflow_failure(
                        steps, artifacts, warnings,
                        errors=list(build_plan.get("errors") or ["build plan failed"]),
                    )
                build_job = jobs / "build.json"
                build_job.write_text(json.dumps({
                    "target": build_plan.get("payload", {}).get("target") or target,
                    "output_path": build_plan.get("payload", {}).get("output_path") or build_output,
                    "configuration": "Development",
                    "clean": False,
                    "scenes": [str((scene_spec or {}).get("output_scene") or "")],
                }, indent=2), encoding="utf-8")
                build_job_path = str(build_job)

            manifest = jobs / "generate_game.json"
            manifest.write_text(json.dumps({
                "assets": asset_plan.get("payload", {}).get("entries") or [],
                "plugins": plugin_entries,
                "scene_job": scene_job_path,
                "build_job": build_job_path,
                "play_scene": str((scene_spec or {}).get("output_scene") or ""),
                "enter_play": bool(enter_play and launch_editor),
            }, indent=2), encoding="utf-8")
            if dry_run:
                return {
                    "ok": True,
                    "operation": "client.generate_game",
                    "artifacts": [{"type": "unity_generate_job", "path": str(manifest), "state": "planned"}],
                    "warnings": [],
                    "errors": [],
                    "payload": {"transport": "unity_native_editor", "manifest": str(manifest)},
                }

            # The transport will reuse this project's open GUI Editor. If no
            # Editor is open, it falls back to one batchmode process.
            invocation = UnityEditorTransport(self._config).execute_method(
                "GenerateGame.RunFromCLI",
                args={"manifest": str(manifest)},
                timeout=self._config.editor_batchmode_timeout,
            )
            if not invocation.get("ok"):
                return self._workflow_failure(
                    steps, artifacts, warnings,
                    errors=[str(invocation.get("error") or "Unity native Editor job failed")],
                )
            artifacts.append({"type": "unity_generated_game", "path": str(manifest), "state": "ready"})
            return {
                "ok": True,
                "operation": "client.generate_game",
                "artifacts": artifacts,
                "warnings": list(dict.fromkeys(warnings)),
                "errors": [],
                "payload": {"transport": "unity_native_editor", "manifest": str(manifest), "editor_report": invocation, "project_path": str(project), "browser": {"engine": "unity3d", "project_path": str(project)}},
            }
        except Exception as exc:
            return self._workflow_failure(
                steps, artifacts, warnings,
                errors=[f"{type(exc).__name__}: {exc}"],
            )

    @staticmethod
    def _workflow_failure(
        steps: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        warnings: list[str],
        *,
        errors: Sequence[str] = (),
    ) -> dict[str, Any]:
        last = steps[-1] if steps else {}
        combined = [str(item) for item in errors]
        combined.extend(str(item) for item in last.get("errors") or [])
        return {
            "ok": False,
            "operation": "client.generate_game",
            "artifacts": artifacts,
            "warnings": list(dict.fromkeys(warnings)),
            "errors": list(dict.fromkeys(combined or ["Unity generated-game step failed"])),
            "payload": {"steps": steps, "failed_step": last.get("operation", "")},
        }
