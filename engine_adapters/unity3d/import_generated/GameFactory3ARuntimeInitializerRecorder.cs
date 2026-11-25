using System;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Collections.Generic;
using System.Security.Cryptography;
using UnityEditor;
using UnityEngine;
using UnityEngine.SceneManagement;
// Validates and observes natural author startup; never invokes author code.
[InitializeOnLoad]
public static class GameFactory3ARuntimeInitializerRecorder {
 const string Key="GameFactory3A.RuntimeInitializerRecorder.";
 [Serializable] public class ObjectRow {public string hierarchy; public string type; public string script_path; public string script_guid; public bool active; public bool enabled;}
 [Serializable] public class Result {public string version="unity-runtime-initializer-native-record-entry.v1"; public string source; public string source_sha256; public string type; public string method; public string editor_version; public bool after_scene_load_attribute; public bool startup_scene_unsaved; public bool entry_method_invoked_by_wrapper; public bool scene_created_by_wrapper; public bool gameplay_component_added_by_wrapper; public bool view_activated; public bool entered_play_mode; public bool exited_play_mode; public bool observed_author_component; public string error=""; public List<ObjectRow> objects=new List<ObjectRow>();}
 static Result result;
 static GameFactory3ARuntimeInitializerRecorder() { Resume(); }
 static string Arg(string key) {var args=Environment.GetCommandLineArgs();for(int i=0;i<args.Length-1;i++)if(args[i]==key)return args[i+1];throw new Exception("Missing argument "+key);}
 static string Digest(string path) {using(var hash=SHA256.Create())using(var stream=File.OpenRead(path))return BitConverter.ToString(hash.ComputeHash(stream)).Replace("-", "").ToLowerInvariant();}
 static string Hierarchy(Transform t) {return t.parent==null?t.name:Hierarchy(t.parent)+"/"+t.name;}
 static void Save() {File.WriteAllText(Arg("--gamefactory-runtime-entry-receipt"),JsonUtility.ToJson(result,true));}
 static void Resume() {if(!SessionState.GetBool(Key+"active",false))return;EditorApplication.playModeStateChanged-=Changed;EditorApplication.playModeStateChanged+=Changed;}
 static void Load() {if(result==null)result=JsonUtility.FromJson<Result>(File.ReadAllText(Arg("--gamefactory-runtime-entry-receipt")));}
 public static void Enter() {
  result=new Result{source=Arg("--gamefactory-runtime-entry-source"),source_sha256=Arg("--gamefactory-runtime-entry-source-sha256"),type=Arg("--gamefactory-runtime-entry-type"),method=Arg("--gamefactory-runtime-entry-method"),editor_version=Application.unityVersion};
  try {
   if(EditorApplication.isPlayingOrWillChangePlaymode)throw new Exception("Runtime entry requires idle Editor startup");
   var scene=SceneManager.GetActiveScene();result.startup_scene_unsaved=scene.IsValid()&&scene.isLoaded&&scene.path=="";
   if(!result.startup_scene_unsaved)throw new Exception("Expected Editor default unsaved startup scene");
   if(Digest(result.source)!=result.source_sha256)throw new Exception("Runtime entry source SHA changed");
   var script=AssetDatabase.LoadAssetAtPath<MonoScript>(result.source);var type=script==null?null:script.GetClass();
   if(type==null||type.FullName!=result.type||!typeof(MonoBehaviour).IsAssignableFrom(type))throw new Exception("Runtime entry MonoScript type mismatch");
   var method=type.GetMethod(result.method,BindingFlags.Static|BindingFlags.Public|BindingFlags.NonPublic|BindingFlags.DeclaredOnly);
   if(method==null||method.ReturnType!=typeof(void)||method.GetParameters().Length!=0||method.ContainsGenericParameters)throw new Exception("Runtime entry must be declared static void zero-argument method");
   var attributes=method.GetCustomAttributes(typeof(RuntimeInitializeOnLoadMethodAttribute),false).Cast<RuntimeInitializeOnLoadMethodAttribute>().ToArray();
   result.after_scene_load_attribute=attributes.Length==1&&attributes[0].loadType==RuntimeInitializeLoadType.AfterSceneLoad;
   if(!result.after_scene_load_attribute)throw new Exception("Authored AfterSceneLoad attribute missing");
   Save();SessionState.SetBool(Key+"active",true);Resume();GameFactory3APlayTestRecorder.Enter();
  } catch(Exception error) {result.error=error.ToString();Save();SessionState.SetBool(Key+"active",false);EditorApplication.Exit(4);}
 }
 static void Changed(PlayModeStateChange change) {
  if(!SessionState.GetBool(Key+"active",false))return;Load();
  try {
   if(change==PlayModeStateChange.EnteredPlayMode){
    result.entered_play_mode=true;
    foreach(var component in Resources.FindObjectsOfTypeAll<MonoBehaviour>()) {
     if(component==null||component.GetType().FullName!=result.type||!component.gameObject.scene.IsValid()||!component.gameObject.scene.isLoaded)continue;
     var script=MonoScript.FromMonoBehaviour(component);var path=script==null?"":AssetDatabase.GetAssetPath(script);if(path!=result.source)continue;
     result.objects.Add(new ObjectRow{hierarchy=Hierarchy(component.transform),type=result.type,script_path=path,script_guid=AssetDatabase.AssetPathToGUID(path),active=component.gameObject.activeInHierarchy,enabled=component.enabled});
    }
    result.observed_author_component=result.objects.Any(row=>row.active&&row.enabled);
    if(!result.observed_author_component)throw new Exception("Natural startup has no active authored entry component");
   }
   if(change==PlayModeStateChange.EnteredEditMode)result.exited_play_mode=true;
   if(Digest(result.source)!=result.source_sha256)throw new Exception("Runtime entry source changed during capture");
   Save();
   if(change==PlayModeStateChange.EnteredEditMode){SessionState.SetBool(Key+"active",false);EditorApplication.playModeStateChanged-=Changed;}
  }catch(Exception error){result.error=error.ToString();Save();SessionState.SetBool(Key+"active",false);EditorApplication.Exit(4);}
 }
}
