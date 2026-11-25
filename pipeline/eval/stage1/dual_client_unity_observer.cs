using System;
using System.IO;
using System.Linq;
using System.Reflection;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

// Read-only observation of authored public session state. No gameplay/network calls.
[InitializeOnLoad]
public static class Stage1DualUnityObserver {
    [Serializable] class Observation {
        public string schema="stage1-unity-pair-observation.v1", model, role, actual_role, session, error, state_json;
        public bool is_host, connected, test_mode, ignore_focus;
        public double unix_ms;
        public int pid;
    }
    static double last;
    static string Arg(string key) {
        var args=Environment.GetCommandLineArgs();
        for(int i=0;i+1<args.Length;i++) if(args[i]==key) return args[i+1];
        return "";
    }
    static object Read(object target,string key) {
        var type=target.GetType();
        var field=type.GetField(key,BindingFlags.Public|BindingFlags.Instance);
        if(field!=null) return field.GetValue(target);
        var property=type.GetProperty(key,BindingFlags.Public|BindingFlags.Instance);
        if(property!=null) return property.GetValue(target,null);
        throw new InvalidOperationException("Missing public session member "+key);
    }
    static Stage1DualUnityObserver() {
        if(Arg("--s1-pair-output")!="") EditorApplication.update+=Update;
    }
    public static void Enter() {
        Directory.CreateDirectory(Arg("--s1-pair-output"));
        EditorSceneManager.OpenScene(Arg("--s1-pair-scene"));
        EditorApplication.isPlaying=true;
    }
    static void Update() {
        string output=Arg("--s1-pair-output");
        if(output=="") return;
        if(File.Exists(Arg("--s1-pair-stop"))) {
            if(EditorApplication.isPlaying) EditorApplication.isPlaying=false;
            else if(!EditorApplication.isPlayingOrWillChangePlaymode) EditorApplication.Exit(0);
            return;
        }
        if(!EditorApplication.isPlaying || EditorApplication.timeSinceStartup-last<.25) return;
        last=EditorApplication.timeSinceStartup;
        try {
            bool sol=Arg("--s1-pair-model")=="Sol";
            string type=sol?"NetworkSession":"Waterworks.WaterworksRuntimeAdapter";
            var found=Resources.FindObjectsOfTypeAll<MonoBehaviour>().Where(x=>x!=null &&
                x.GetType().FullName==type && x.gameObject.scene.IsValid()).ToArray();
            if(found.Length!=1) return;
            var obj=found[0]; var state=Read(obj,sol?"latest":"State");
            var row=new Observation {model=Arg("--s1-pair-model"),role=Arg("--s1-pair-role"),
                actual_role=(string)Read(obj,sol?"role":"Role"),
                session=sol?(string)Read(obj,"sessionId"):Arg("--s1-pair-session"),
                error=(string)Read(obj,sol?"error":"Error"),is_host=(bool)Read(obj,sol?"isHost":"IsHost"),
                connected=(bool)Read(obj,sol?"connected":"Connected"),
                test_mode=sol && (bool)Read(obj,"testMode"),ignore_focus=sol && (bool)Read(obj,"ignoreFocus"),
                state_json=state==null?"":JsonUtility.ToJson(state),
                unix_ms=DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                pid=System.Diagnostics.Process.GetCurrentProcess().Id};
            File.AppendAllText(Path.Combine(output,"observations.jsonl"),JsonUtility.ToJson(row)+"\n");
        } catch(Exception e) {
            File.AppendAllText(Path.Combine(output,"observer_error.txt"),e.ToString()+"\n");
        }
    }
}
