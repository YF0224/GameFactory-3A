using System;
using System.IO;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEditor.SceneManagement;
using UnityEngine;

public static class SnakeBuild {
    public static void Build() {
        string output=null;
        var args=Environment.GetCommandLineArgs();
        for(int i=0;i<args.Length-1;i++)if(args[i]=="-snakeBuild")output=args[i+1];
        if(String.IsNullOrEmpty(output))throw new ArgumentException("-snakeBuild <absolute app path> required");
        var scene=EditorSceneManager.NewScene(NewSceneSetup.EmptyScene,NewSceneMode.Single);
        var game=new GameObject("Snake"); game.AddComponent<SnakeGame>();
        var camera=new GameObject("Camera").AddComponent<Camera>();
        camera.clearFlags=CameraClearFlags.SolidColor; camera.backgroundColor=Color.black;
        camera.transform.position=new Vector3(0,0,-10);
        EditorSceneManager.SaveScene(scene,"Assets/Snake.unity");
        PlayerSettings.productName="Snake Demo";
        PlayerSettings.defaultScreenWidth=800; PlayerSettings.defaultScreenHeight=600;
        PlayerSettings.fullScreenMode=FullScreenMode.Windowed;
        PlayerSettings.macRetinaSupport=false;
        PlayerSettings.runInBackground=true;
        PlayerSettings.colorSpace=ColorSpace.Gamma;
        PlayerSettings.SetScriptingBackend(BuildTargetGroup.Standalone,ScriptingImplementation.Mono2x);
        var report=BuildPipeline.BuildPlayer(new BuildPlayerOptions {
            scenes=new[]{"Assets/Snake.unity"},locationPathName=output,
            target=BuildTarget.StandaloneOSX,options=BuildOptions.Development
        });
        if(report.summary.result!=BuildResult.Succeeded)throw new Exception("Snake build failed: "+report.summary.result);
    }
}
