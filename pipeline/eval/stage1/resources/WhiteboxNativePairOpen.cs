using System;
using System.IO;
using System.Linq;
using System.Reflection;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

// Observation only: no calls into authored networking/input/gameplay methods.
[InitializeOnLoad]
public static class WhiteboxNativePairOpen {
    [Serializable] class Observation {
        public string schema="whitebox-native-pair-observation.v1", role, session, error, state_json;
        public bool is_host, connected, test_mode, ignore_focus;
        public double editor_time, unix_ms;
        public int pid;
    }
    static double last;
    static bool requested;
    static string Arg(string name) {
        var args=Environment.GetCommandLineArgs();
        for(int i=0;i+1<args.Length;i++) if(args[i]==name) return args[i+1];
        return "";
    }
    static object Field(object target,string name) {
        var field=target.GetType().GetField(name,BindingFlags.Instance|BindingFlags.Public);
        if(field==null) throw new InvalidOperationException("Missing public observation field "+name);
        return field.GetValue(target);
    }
    static WhiteboxNativePairOpen() {
        if(Arg("--whitebox-pair-output")!="") EditorApplication.update+=Update;
    }
    public static void Enter() {
        string output=Arg("--whitebox-pair-output");
        Directory.CreateDirectory(output);
        if(File.Exists(Path.Combine(output,"entered.json"))) throw new InvalidOperationException("Preserve prior native pair evidence");
        File.WriteAllText(Path.Combine(output,"entered.json"),"{\"pid\":"+System.Diagnostics.Process.GetCurrentProcess().Id+"}");
        EditorSceneManager.OpenScene(Arg("--whitebox-pair-scene"));
        EditorApplication.isPlaying=true;
    }
    static void Update() {
        string output=Arg("--whitebox-pair-output");
        if(output=="") return;
        if(File.Exists(Arg("--whitebox-pair-stop"))) {
            if(EditorApplication.isPlaying) EditorApplication.isPlaying=false;
            else if(!EditorApplication.isPlayingOrWillChangePlaymode) EditorApplication.Exit(0);
            return;
        }
        if(!EditorApplication.isPlaying || EditorApplication.timeSinceStartup-last<.25) return;
        last=EditorApplication.timeSinceStartup;
        try {
            var sessions=Resources.FindObjectsOfTypeAll<MonoBehaviour>().Where(x=>x!=null && x.GetType().FullName=="NetworkSession" && x.gameObject.scene.IsValid()).ToArray();
            if(sessions.Length!=1) return;
            var session=sessions[0]; var state=Field(session,"latest");
            var row=new Observation {role=Arg("--whitebox-pair-role"),session=(string)Field(session,"sessionId"),
                error=(string)Field(session,"error"),is_host=(bool)Field(session,"isHost"),
                connected=(bool)Field(session,"connected"),test_mode=(bool)Field(session,"testMode"),
                ignore_focus=(bool)Field(session,"ignoreFocus"),state_json=state==null?"":JsonUtility.ToJson(state),
                editor_time=EditorApplication.timeSinceStartup,unix_ms=DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                pid=System.Diagnostics.Process.GetCurrentProcess().Id};
            File.AppendAllText(Path.Combine(output,"observations.jsonl"),JsonUtility.ToJson(row)+"\n");
        } catch(Exception e) {
            if(!requested) { requested=true; File.WriteAllText(Path.Combine(output,"observer_error.txt"),e.ToString()); }
        }
    }
}
