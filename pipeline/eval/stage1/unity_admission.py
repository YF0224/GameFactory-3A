"""Native admission based on an actual isolated import, never historical paperwork."""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import time

VERSION = 'whitebox-openable-delivery.v1'


def project_candidates(review):
    """Reuse reviewed locations; inspect only their bounded authored stage roots."""
    entry = review['entry']
    values = [review.get('selected_project'), entry.get('project'),
              review.get('source_review', {}).get('source')]
    values += [item.get('project') for item in entry.get('candidates', [])]
    roots = [item.get('path') for item in review.get('blocker_evidence', {}).get('generation_roots', [])]
    values += entry.get('delivery_audit', {}).get('structural_unity_roots', [])
    if entry.get('generation_run'):
        roots.append(entry['generation_run'])
    seen = set()
    for value in values:
        if value:
            path = Path(value).resolve()
            if path not in seen and path.is_dir():
                seen.add(path)
                yield path
    # Old reviews can have no selected path despite a delivered Assets directory.
    for value in roots:
        if not value or not Path(value).is_dir():
            continue
        root = Path(value).resolve()
        for folder, dirs, files in os.walk(root, followlinks=False):
            path = Path(folder)
            dirs[:] = sorted(d for d in dirs if d not in {
                'Library', 'Temp', 'Logs', 'node_modules', '.git', '.godot',
                'Builds', 'validation', '.generation', 'case_input', 'trajectory'})
            if len(path.relative_to(root).parts) > 6:
                dirs[:] = []
                continue
            if 'Assets' in dirs or 'project.godot' in files:
                dirs[:] = []
                if path not in seen:
                    seen.add(path)
                    yield path


def review_project(review, result, acceptances, default_editor, *, authored_entry=None, runtime_entry=None):
    candidates = list(project_candidates(review))
    unity = [p for p in candidates if (p/'Assets').is_dir() and not (p/'project.godot').is_file()]
    if not unity:
        actual = [p for p in candidates if (p/'project.godot').is_file()]
        return dict(result, status='REPORT_DELIVERY_UNAVAILABLE',
                    reason='No openable Unity project at reviewed or bounded delivery locations',
                    inspected_projects=[str(p) for p in candidates],
                    actual_engine_projects=[{'engine':'godot','project':str(p)} for p in actual],
                    admission_policy=VERSION)
    # Prefer reviewed selection. Do not replace a delivered project with another
    # generation or a more complete stage just to obtain a better result.
    selected = unity[0]
    scenes = sorted(str(p.relative_to(selected)) for p in selected.glob('Assets/**/*.unity') if p.is_file())
    from .unity_editor_selection import delivery_format, choose_editor
    format_record = delivery_format(selected, scenes)
    marker = selected/'ProjectSettings/ProjectVersion.txt'
    native = choose_editor(format_record, acceptances)
    editor = Path(native['editor']) if native else Path(default_editor)
    version = format_record['source_editor_version']
    notices = []
    if not marker.is_file():
        notices.append('Original ProjectVersion.txt absent; actual editor import will be recorded')
    if version and native and version != native['editor_version']:
        notices.append('Source/editor versions differ; compatibility must pass native import in a copy')
    manifest = Path(review.get('migration_manifest') or '/nonexistent')
    if not manifest.is_file():
        notices.append('Historical migration manifest absent; freeze current source independently')
    out = dict(result, selected_project=str(selected), scenes=scenes,
               source_editor_version=version, selected_editor=str(editor),
               delivery_format=format_record,
               admission_policy=VERSION, admission_notices=notices,
               required_real_clients=review['entry'].get('required_real_clients', 1))
    if native:
        out['native_editor_acceptance'] = {key:native[key] for key in ['path','sha256','editor','editor_version']}
    if runtime_entry:
        from .unity_runtime_initializer_entry import verify
        if scenes or authored_entry or runtime_entry.get('case') != result['id'] or Path(runtime_entry['project']).resolve() != selected:
            raise ValueError('Runtime initializer must bind this exact delivered project without a scene or builder')
        verify(runtime_entry, selected)
        out['runtime_initializer_entry'] = runtime_entry
    if not scenes and authored_entry:
        out['authored_scene_entry'] = authored_entry
    if not scenes and not authored_entry and not runtime_entry:
        return dict(out, status='REPORT_SCENE_MISSING', reason='Selected delivered project has no Assets/**/*.unity scene; no scene synthesized')
    if not native:
        return dict(out, status='REPORT_EDITOR_UNAVAILABLE', failure_class='EDITOR_COMPATIBILITY',
                    reason='No verified background recorder acceptance for delivered '+format_record['family']+' format')
    if not editor.is_file():
        return dict(out, status='REPORT_EDITOR_UNAVAILABLE', failure_class='EDITOR_COMPATIBILITY', reason='Selected editor executable is absent')
    return dict(out, status='READY', native_open_check_required=True,
                reason='Native isolated import/scene-open required before model planning')


@contextlib.contextmanager
def capture_locks(runner):
    paths = runner.locks_clear()
    handles = []
    try:
        for value in paths:
            stream = Path(value).open('a')
            try:
                fcntl.flock(stream, fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BaseException:
                stream.close()
                raise
            handles.append(stream)
        yield paths
    finally:
        for stream in reversed(handles):
            stream.close()


OPEN_SCENE_SOURCE = r'''using System;
using System.IO;
using System.Collections.Generic;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
public static class WhiteboxNativeOpen {
 static string Arg(string key) {var a=Environment.GetCommandLineArgs(); for(int i=0;i<a.Length-1;i++)if(a[i]==key)return a[i+1]; throw new Exception("Missing argument "+key);}
 [Serializable] class Behaviour {public string hierarchy; public string type; public string script_path; public string script_guid; public bool enabled; public bool active;}
 [Serializable] class Result {public bool opened; public string scene; public string editor_version; public int root_count;
  public string inspection_version="whitebox-native-scene-components.v1"; public int missing_script_count;
  public List<Behaviour> behaviours=new List<Behaviour>();}
 static string Hierarchy(Transform t) {return t.parent==null?t.name:Hierarchy(t.parent)+"/"+t.name;}
 public static void Check() {
  string name=Arg("-whiteboxScene");
  var scene=EditorSceneManager.OpenScene(name,OpenSceneMode.Single);
  if(!scene.IsValid()||!scene.isLoaded)throw new Exception("Delivered scene did not open: "+name);
  var result=new Result{opened=true,scene=name,editor_version=Application.unityVersion,root_count=scene.rootCount};
  foreach(var root in scene.GetRootGameObjects())foreach(var transform in root.GetComponentsInChildren<Transform>(true)) {
   result.missing_script_count+=GameObjectUtility.GetMonoBehavioursWithMissingScriptCount(transform.gameObject);
   foreach(var component in transform.GetComponents<MonoBehaviour>()) {
    if(component==null)continue;
    var script=MonoScript.FromMonoBehaviour(component);
    string path=script==null?"":AssetDatabase.GetAssetPath(script);
    result.behaviours.Add(new Behaviour{hierarchy=Hierarchy(transform),type=component.GetType().FullName,
     script_path=path,script_guid=path==""?"":AssetDatabase.AssetPathToGUID(path),
     enabled=component.enabled,active=component.gameObject.activeInHierarchy});
   }
  }
  File.WriteAllText(Arg("-whiteboxReceipt"),JsonUtility.ToJson(result));
  Debug.Log("WHITEBOX_NATIVE_SCENE_OPENED "+name);
 }
}
'''


def run_owned(command, log, timeout, *, env=None):
    """Bound the owned process group; never kill another editor."""
    started = time.time()
    timed_out = False
    with Path(log).open('w') as stream:
        proc = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT,
                                start_new_session=True, env=env)
        try:
            code = proc.wait(timeout=timeout)
        except (subprocess.TimeoutExpired, KeyboardInterrupt, SystemExit) as error:
            timed_out = isinstance(error, subprocess.TimeoutExpired)
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait(timeout=10)
            if not timed_out:
                raise
            code = proc.returncode
    return {'command':command, 'pid':proc.pid, 'exit_code':code,
            'timed_out':timed_out, 'seconds':round(time.time()-started,3),
            'owned_process_exited':proc.poll() is not None}


def prepare_source(candidate, review, runner, output):
    """Snapshot current bytes and try the project before spending planner calls."""
    if candidate.get('runtime_initializer_entry'):
        from .unity_runtime_admission import prepare_source as prepare_runtime
        return prepare_runtime(candidate, review, runner, output)
    output = Path(output)/'native_admission'/candidate['id']/str(time.time_ns())
    output.mkdir(parents=True, exist_ok=False)
    source = Path(candidate['selected_project']).resolve()
    from engine_adapters.unity3d.playtest import background_record as background
    with capture_locks(runner):
        from pipeline.eval.stage1 import runtime
        occupied = runtime.active_gui_engines()
        if occupied:
            raise RuntimeError('Native open check occupied: '+json.dumps(occupied))
        projection = candidate.get('generated_output_projection')
        if projection:
            from .unity_source_output_projection import snapshot as projected_snapshot
            snapshot = projected_snapshot(projection, candidate['id'], source, output/'project')
        else:
            snapshot = background.snapshot_project(source, output/'project', runner.MIGRATION)
        runner.dump(output/'source_snapshot.json', snapshot)
        sandbox = output/'project'
        # Apply reviewed namespace imports against the untouched snapshot first.
        # Input migration can legitimately rewrite the same source/asmdef files;
        # doing it first makes the import policy mistake those deterministic
        # adapter changes for source drift.
        compatibility = None
        if candidate.get('import_compatibility'):
            from .unity_compile_compatibility import apply as apply_imports
            compatibility = apply_imports(candidate['import_compatibility'], candidate['id'],
                sandbox, output/'import_compatibility.json')
        editor_compatibility = None
        if candidate.get('editor_compile_compatibility'):
            from .unity_editor_compile_compatibility import apply as apply_editor_compatibility
            editor_compatibility = apply_editor_compatibility(candidate['editor_compile_compatibility'],
                candidate['id'], sandbox, output/'editor_compile_compatibility.json')
        native_compile = None
        if candidate.get('native_compile_recovery'):
            from .unity_native_compile_recovery import apply as apply_native_compile
            native_compile = apply_native_compile(candidate['native_compile_recovery'], candidate,
                sandbox, output/'native_compile_recovery.json')
        # Existing migrated projects already have native Input System support.
        # A new migration, when necessary, is derived here rather than demanding
        # a historical manifest. All original bytes remain untouched.
        settings = sandbox/'ProjectSettings/ProjectSettings.asset'
        text = settings.read_text(errors='replace') if settings.is_file() else ''
        if not re.search(r'(?m)^[ \t]*activeInputHandler:[ \t]*1[ \t]*$', text):
            from .unity_input_migration import migrate_input
            migration_receipt = output/'input_migration.json'
            migrate_input(sandbox, migration_receipt, package_root=getattr(runner,'input_system_package_root',None))
            migration = None
        from .unity_runtime_dependencies import prepare as prepare_runtime_dependencies
        dependency_receipt = output/'observer_runtime_dependencies.json'
        prepare_runtime_dependencies(sandbox, candidate['selected_editor'], dependency_receipt)
        authored = None
        admission_deadline = time.monotonic() + getattr(runner, 'open_timeout_seconds', 240)
        if candidate.get('authored_scene_entry'):
            from .unity_authored_entry import run as run_authored
            authored = run_authored(candidate, sandbox, output, runner, max(1, admission_deadline-time.monotonic()))
        helper = sandbox/'Assets/GameFactory3AEvaluation/Editor/WhiteboxNativeOpen.cs'
        if helper.exists():
            raise ValueError('Refuse to overwrite a delivered native-open helper')
        helper.parent.mkdir(parents=True, exist_ok=True)
        helper.write_text(OPEN_SCENE_SOURCE)
        native_result = output/'opened_scene.json'
        command = [candidate['selected_editor'], '-batchmode', '-nographics', '-quit',
                   '-projectPath', str(sandbox), '-executeMethod', 'WhiteboxNativeOpen.Check',
                   '-whiteboxScene', candidate['scenes'][0], '-whiteboxReceipt', str(native_result),
                   '-logFile', str(output/'editor.log')]
        execution = run_owned(command, output/'process.log', max(1, admission_deadline-time.monotonic()))
        opened = runner.batch.read(native_result) if native_result.is_file() else {}
        original = background.check_original(snapshot)
        helper.unlink()
        if helper.with_suffix('.cs.meta').is_file():
            helper.with_suffix('.cs.meta').unlink()
        record = {'schema':VERSION, 'id':candidate['id'], 'source_project':str(source),
                  'project':str(sandbox), 'editor':candidate['selected_editor'],
                  'source_snapshot':str(output/'source_snapshot.json'), 'source_unchanged':original,
                  'authored_scene_entry':authored,
                  'import_compatibility':compatibility,
                  'editor_compile_compatibility':editor_compatibility,
                  'native_compile_recovery':native_compile,
                  'observer_runtime_dependencies':{'path':str(dependency_receipt),
                      'sha256':runner.sha(dependency_receipt)},
                  'execution':execution, 'opened_scene':opened,
                  'native_editor_acceptance':candidate.get('native_editor_acceptance'),
                  'notices':candidate.get('admission_notices', []),
                  'delivery_format':candidate.get('delivery_format'),
                  'product_status':'OPENED' if execution['exit_code']==0 and opened.get('opened') is True else 'NATIVE_OPEN_FAILED',
                  'model_calls':0, 'recordings':0}
        # The probe performs no gameplay input or view activation.
        record['cleanup'] = {'input_cleanup':True, 'view_cleanup':True,
                             'process_cleanup':execution['owned_process_exited']}
        if original.get('ok') is not True:
            raise RuntimeError('Original source changed during isolated native open')
        record['project_hashes'] = runner.batch.hashes(sandbox)
        if record['product_status'] != 'OPENED':
            from .unity_editor_selection import failure_classification
            record['failure_class'] = failure_classification((output/'editor.log').read_text(errors='replace')) if (output/'editor.log').is_file() else 'HARNESS'
        runner.dump(output/'result.json', record)
        if record['product_status'] != 'OPENED':
            from .unity_editor_selection import NativeAdmissionError
            raise NativeAdmissionError('Actual native project import/scene open failed; see '+str(output/'result.json'), record['failure_class'])
    runner.locks_clear()
    updated = dict(candidate, selected_project=str(sandbox),
                   native_open_receipt=str(output/'result.json'), native_open_receipt_sha256=runner.sha(output/'result.json'),
                   native_open_check_required=False)
    return updated


def verify_open_receipt(path, runner, project, editor):
    path = Path(path).resolve()
    receipt = runner.batch.read(path)
    if (receipt.get('schema') != VERSION or receipt.get('product_status') != 'OPENED'
            or Path(receipt['project']).resolve()!=Path(project).resolve()
            or Path(receipt['editor']).resolve()!=Path(editor).resolve()
            or not receipt.get('source_unchanged',{}).get('ok')
            or not all(receipt.get('cleanup',{}).get(key) is True for key in ['input_cleanup','view_cleanup','process_cleanup'])
            or runner.batch.hashes(Path(project)) != receipt.get('project_hashes')):
        raise ValueError('Native open receipt does not bind the current project/editor/source/cleanup')
    return receipt
