"""Explicit SHA-bound runtime-initializer entry diagnostics, without scene creation.

This probe does not admit a project to recording or scoring. Native evidence must
first prove that Unity's own PlayMode startup runs the delivered initializer.
"""
from pathlib import Path
import json
import hashlib
import re
import time

from .protocol import dump, sha

VERSION = 'whitebox-runtime-initializer-entry.v1'


def contract(review, *, type_name, method):
    review = Path(review).resolve()
    value = json.loads(review.read_text())
    if (value.get('version') != 'whitebox-runtime-initializer-entry-review.v1'
            or value.get('checks', {}).get('source_not_modified') is not True):
        raise ValueError('Explicit authored runtime entry review required')
    root = Path(value['original_project']).resolve()
    source = Path(value['original_source']).resolve()
    if not source.is_relative_to(root/'Assets') or source.suffix != '.cs':
        raise ValueError('Entry source must be a delivered Assets C# file')
    if not re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*', type_name):
        raise ValueError('Invalid runtime entry type')
    if not re.fullmatch(r'[A-Za-z_]\w*', method):
        raise ValueError('Invalid runtime entry method')
    result = {'version': VERSION, 'case': value['case'], 'project': str(root),
              'source': str(source.relative_to(root)), 'source_sha256': value['source_sha256'],
              'type': type_name, 'method': method, 'load_type': 'AfterSceneLoad',
              'review': str(review), 'review_sha256': sha(review)}
    verify(result, root)
    return result


def _input_source(entry, project, before, binding):
    """Replay the accepted input-read substitution; a receipt alone grants no trust."""
    from .unity_input_migration import migrate_device_reads
    if set(binding) != {'path', 'sha256'}:
        raise ValueError('Runtime input migration requires exact receipt binding')
    path = Path(binding['path'])
    if sha(path) != binding['sha256']:
        raise ValueError('Runtime input migration receipt changed')
    receipt = json.loads(path.read_text())
    if (receipt.get('version') != 'unity-inputsystem-migration.v1'
            or Path(receipt.get('project', '')).resolve() != project
            or receipt.get('gameplay_changes') != []):
        raise ValueError('Runtime input migration belongs to another project or changed gameplay')
    changes = receipt.get('changes')
    if (not isinstance(changes, list) or any(not isinstance(row, dict) for row in changes)
            or len({row.get('path') for row in changes}) != len(changes)):
        raise ValueError('Runtime input migration source inventory is ambiguous')
    rows = [row for row in changes if row.get('path') == entry['source']]
    after = migrate_device_reads(before)
    digest = lambda text: hashlib.sha256(text.encode('utf-8')).hexdigest()
    expected = {'path': entry['source'], 'before_sha256': digest(before),
                'after_sha256': digest(after), 'kind': 'native_input_device_reads_only'}
    if (after != before and rows != [expected]) or (after == before and rows):
        raise ValueError('Runtime input migration does not bind exact device-read transformation')
    return digest(after)


def verify(entry, project, *, compatibility=None, input_migration=None):
    if entry.get('version') != VERSION or entry.get('load_type') != 'AfterSceneLoad':
        raise ValueError('Unknown runtime entry contract')
    review = Path(entry['review'])
    if sha(review) != entry['review_sha256']:
        raise ValueError('Authored runtime entry review changed')
    reviewed = json.loads(review.read_text())
    origin = Path(entry['project']).resolve()
    if (Path(reviewed['original_project']).resolve() != origin
            or Path(reviewed['original_source']).resolve() != (origin/entry['source']).resolve()
            or reviewed['source_sha256'] != entry['source_sha256']
            or reviewed['case'] != entry['case']):
        raise ValueError('Runtime entry review/source mismatch')
    project = Path(project).resolve()
    for root in {origin, project}:
        source = root/entry['source']
        expected=entry['source_sha256']
        before=(origin/entry['source']).read_bytes().decode('utf-8')
        if root!=origin and compatibility:
            from .unity_native_compile_recovery import load
            from .unity_member_method_recovery import prepare
            current=load(Path(compatibility['policy_path']).parent,entry['case'],entry['project'])
            if current!=compatibility or compatibility.get('private_method_rename',{}).get('source_sha256')!=expected:
                raise ValueError('Runtime entry compatibility policy changed')
            transformed=prepare(compatibility,origin)
            if transformed['source']!=entry['source']:raise ValueError('Runtime entry compatibility source differs')
            expected=transformed['after_sha256']
            before=transformed['after_utf8']
        if root != origin and input_migration:
            expected=_input_source(entry,project,before,input_migration)
        if (not source.resolve().is_relative_to(root/'Assets') or source.suffix != '.cs'
                or source.is_symlink() or sha(source) != expected):
            raise ValueError('Authored runtime entry source changed or escaped')
        if any(root.glob('Assets/**/*.unity')):
            raise ValueError('Use the existing delivered scene admission path')
    if (not re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*', entry['type'])
            or not re.fullmatch(r'[A-Za-z_]\w*', entry['method'])):
        raise ValueError('Invalid runtime entry identifier')
    return True


PROBE_SOURCE = r'''using System;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Collections.Generic;
using System.Security.Cryptography;
using UnityEditor;
using UnityEngine;
using UnityEngine.SceneManagement;
[InitializeOnLoad]
public static class WhiteboxRuntimeInitializerProbe {
 const string Key="GameFactory3A.RuntimeEntryProbe.";
 [Serializable] public class ObjectRow {public string hierarchy; public string type; public string script_path; public string script_guid; public bool active; public bool enabled;}
 [Serializable] public class Result {public string version="whitebox-runtime-initializer-entry-probe.v1"; public string source; public string source_sha256; public string type; public string method; public string editor_version; public bool after_scene_load_attribute; public bool startup_scene_unsaved; public bool entry_method_invoked_by_probe; public bool scene_created_by_probe; public bool gameplay_component_added_by_probe; public bool gameplay_input_sent; public bool view_activated; public bool entered_play_mode; public bool exited_play_mode; public bool observed_author_component; public string error=""; public List<ObjectRow> objects=new List<ObjectRow>();}
 static Result result; static double playAt=-1; static bool stopping;
 static WhiteboxRuntimeInitializerProbe() {EditorApplication.delayCall+=Resume;}
 static string Arg(string key) {var args=Environment.GetCommandLineArgs();for(int i=0;i<args.Length-1;i++)if(args[i]==key)return args[i+1];throw new Exception("Missing argument "+key);}
 static string Digest(string path) {using(var hash=SHA256.Create())using(var stream=File.OpenRead(path))return BitConverter.ToString(hash.ComputeHash(stream)).Replace("-", "").ToLowerInvariant();}
 static string Hierarchy(Transform t) {return t.parent==null?t.name:Hierarchy(t.parent)+"/"+t.name;}
 static void Save() {File.WriteAllText(Arg("-whiteboxRuntimeReceipt"),JsonUtility.ToJson(result,true));}
 static void Resume() {if(!SessionState.GetBool(Key+"active",false))return;Load();EditorApplication.update-=Tick;EditorApplication.update+=Tick;EditorApplication.playModeStateChanged-=Changed;EditorApplication.playModeStateChanged+=Changed;}
 static void Load() {if(result==null)result=JsonUtility.FromJson<Result>(File.ReadAllText(Arg("-whiteboxRuntimeReceipt")));}
 public static void Check() {
  result=new Result{source=Arg("-whiteboxRuntimeSource"),source_sha256=Arg("-whiteboxRuntimeSHA"),type=Arg("-whiteboxRuntimeType"),method=Arg("-whiteboxRuntimeMethod"),editor_version=Application.unityVersion};
  try {
   if(EditorApplication.isPlayingOrWillChangePlaymode)throw new Exception("Probe requires idle Editor startup");
   var scene=SceneManager.GetActiveScene();result.startup_scene_unsaved=scene.IsValid()&&scene.isLoaded&&scene.path=="";
   if(!result.startup_scene_unsaved)throw new Exception("Expected Editor default unsaved startup scene");
   if(Digest(result.source)!=result.source_sha256)throw new Exception("Entry source SHA changed");
   var script=AssetDatabase.LoadAssetAtPath<MonoScript>(result.source);var type=script==null?null:script.GetClass();
   if(type==null||type.FullName!=result.type||!typeof(MonoBehaviour).IsAssignableFrom(type))throw new Exception("Entry MonoScript type mismatch");
   var method=type.GetMethod(result.method,BindingFlags.Static|BindingFlags.Public|BindingFlags.NonPublic|BindingFlags.DeclaredOnly);
   if(method==null||method.ReturnType!=typeof(void)||method.GetParameters().Length!=0||method.ContainsGenericParameters)throw new Exception("Entry must be a declared static void zero-argument method");
   var attr=method.GetCustomAttributes(typeof(RuntimeInitializeOnLoadMethodAttribute),false).Cast<RuntimeInitializeOnLoadMethodAttribute>().ToArray();
   result.after_scene_load_attribute=attr.Length==1&&attr[0].loadType==RuntimeInitializeLoadType.AfterSceneLoad;
   if(!result.after_scene_load_attribute)throw new Exception("Author AfterSceneLoad attribute missing");
   Save();SessionState.SetBool(Key+"active",true);SessionState.SetString(Key+"deadline",(EditorApplication.timeSinceStartup+120).ToString("R",System.Globalization.CultureInfo.InvariantCulture));Resume();EditorApplication.isPlaying=true;
  } catch(Exception error) {result.error=error.ToString();Save();EditorApplication.Exit(1);}
 }
 static void Changed(PlayModeStateChange change) {
  if(!SessionState.GetBool(Key+"active",false))return;Load();
  if(change==PlayModeStateChange.EnteredPlayMode){result.entered_play_mode=true;playAt=EditorApplication.timeSinceStartup;Save();}
  if(change==PlayModeStateChange.EnteredEditMode){result.exited_play_mode=true;Save();SessionState.SetBool(Key+"active",false);EditorApplication.Exit(result.error==""&&result.observed_author_component?0:1);}
 }
 static void Tick() {
  if(!SessionState.GetBool(Key+"active",false))return;Load();
  double deadline=double.Parse(SessionState.GetString(Key+"deadline","0"),System.Globalization.CultureInfo.InvariantCulture);
  if(EditorApplication.timeSinceStartup>deadline){result.error="Native startup probe deadline exceeded";Save();SessionState.SetBool(Key+"active",false);EditorApplication.Exit(1);return;}
  if(!EditorApplication.isPlaying||stopping)return;
  if(playAt<0){result.entered_play_mode=true;playAt=EditorApplication.timeSinceStartup;}
  if(EditorApplication.timeSinceStartup-playAt<2)return;
  foreach(var component in Resources.FindObjectsOfTypeAll<MonoBehaviour>()) {
   if(component==null||component.GetType().FullName!=result.type||!component.gameObject.scene.IsValid()||!component.gameObject.scene.isLoaded)continue;
   var script=MonoScript.FromMonoBehaviour(component);var path=script==null?"":AssetDatabase.GetAssetPath(script);
   if(path!=result.source)continue;
   result.objects.Add(new ObjectRow{hierarchy=Hierarchy(component.transform),type=result.type,script_path=path,script_guid=AssetDatabase.AssetPathToGUID(path),active=component.gameObject.activeInHierarchy,enabled=component.enabled});
  }
  result.observed_author_component=result.objects.Any(row=>row.active&&row.enabled);
  if(!result.observed_author_component)result.error="Unity entered PlayMode but no active authored component was observed";
  if(Digest(result.source)!=result.source_sha256)result.error="Entry source changed during native startup";
  stopping=true;Save();EditorApplication.isPlaying=false;
 }
}
'''


def valid_native(entry, native, execution):
    """Require actual lifecycle, exact source identity, and observed component rows."""
    positive = ['after_scene_load_attribute', 'startup_scene_unsaved', 'entered_play_mode',
                'exited_play_mode', 'observed_author_component']
    negative = ['entry_method_invoked_by_probe', 'scene_created_by_probe',
                'gameplay_component_added_by_probe', 'gameplay_input_sent', 'view_activated']
    return (execution.get('exit_code') == 0 and execution.get('timed_out') is False
            and execution.get('owned_process_exited') is True
            and native.get('version') == 'whitebox-runtime-initializer-entry-probe.v1'
            and native.get('error') == '' and bool(native.get('editor_version'))
            and all(native.get(k) == entry[k] for k in ('source', 'source_sha256', 'type', 'method'))
            and all(native.get(k) is True for k in positive)
            and all(native.get(k) is False for k in negative)
            and any(isinstance(row, dict) and row.get('type') == entry['type']
                    and row.get('script_path') == entry['source']
                    and re.fullmatch(r'[0-9a-f]{32}', row.get('script_guid', ''))
                    and row.get('active') is True and row.get('enabled') is True
                    for row in native.get('objects', [])))


def probe(entry, sandbox, editor, output, *, timeout=240, compatibility=None, input_migration=None, retain_helper=False):
    """Run under shared lease and all execution locks, supplied by the caller."""
    from .unity_admission import run_owned
    verify(entry, sandbox, compatibility=compatibility, input_migration=input_migration)
    sandbox, output = Path(sandbox).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    helper = sandbox/'Assets/GameFactory3AEvaluation/Editor/WhiteboxRuntimeInitializerProbe.cs'
    if helper.exists():
        raise ValueError('Refuse to overwrite an existing runtime entry probe')
    helper.parent.mkdir(parents=True, exist_ok=True)
    helper.write_text(PROBE_SOURCE)
    # Preserve the exact injected diagnostic even after its temporary project copy is removed.
    (output/'WhiteboxRuntimeInitializerProbe.cs').write_text(PROBE_SOURCE)
    receipt = output/'native_runtime_entry.json'
    command = [str(editor), '-batchmode', '-nographics', '-projectPath', str(sandbox),
               '-executeMethod', 'WhiteboxRuntimeInitializerProbe.Check',
               '-whiteboxRuntimeReceipt', str(receipt), '-whiteboxRuntimeSource', entry['source'],
               '-whiteboxRuntimeSHA', sha(sandbox/entry['source']), '-whiteboxRuntimeType', entry['type'],
               '-whiteboxRuntimeMethod', entry['method'], '-logFile', str(output/'editor.log')]
    execution = None
    try:
        execution = run_owned(command, output/'process.log', timeout)
    finally:
        # Delete only this exact, task-created helper; leave all native diagnostics intact.
        if not retain_helper and helper.exists() and sha(helper) == sha(output/'WhiteboxRuntimeInitializerProbe.cs'):
            helper.unlink()
            meta = helper.with_suffix('.cs.meta')
            if meta.is_file():
                meta.unlink()
    native = json.loads(receipt.read_text()) if receipt.is_file() else {}
    verify(entry, sandbox, compatibility=compatibility, input_migration=input_migration)
    effective=dict(entry,source_sha256=sha(sandbox/entry['source']))
    ok = valid_native(effective, native, execution)
    result = {'version': VERSION, 'at': time.time(), 'contract': entry, 'execution': execution,
              'native_receipt': str(receipt), 'native_receipt_sha256': sha(receipt) if receipt.is_file() else None,
              'probe_source_sha256': sha(output/'WhiteboxRuntimeInitializerProbe.cs'),
              'source_compatibility':compatibility,'input_migration':input_migration,'effective_source_sha256':effective['source_sha256'],'diagnostic_helper_retained':retain_helper,
              'diagnostic_only': True, 'model_calls': 0, 'recordings': 0, 'score_created': False,
              'native_entry_observed': ok, 'cleanup': {'input_cleanup': True, 'view_cleanup': True,
                  'process_cleanup': execution['owned_process_exited']}}
    dump(output/'result.json', result)
    return result
