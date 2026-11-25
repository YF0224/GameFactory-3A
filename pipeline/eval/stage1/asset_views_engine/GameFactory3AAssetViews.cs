// Eval-owned editor script (copied into the eval working copy only, removed afterwards).
// Renders each requested project asset in an empty preview scene from four fixed
// angles under one neutral light rig and writes one PNG per view plus a material report.
// Nothing in the delivered project is modified or saved.
//
// Neutral preview contract: the asset's own behaviours are disabled (no gameplay code
// runs) and lights embedded in the asset are disabled (e.g. glTF photometric lights that
// a game rescales at runtime would otherwise blow the surfaces out); both are recorded.
#if UNITY_EDITOR
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;

public static class GameFactory3AAssetViews
{
    [Serializable] public class Job { public string id; public string path; public bool runtime_gltf; }
    [Serializable] public class JobFile { public string output_dir; public int size = 640; public Job[] jobs; }
    [Serializable] public class MaterialInfo { public string renderer; public string material; public string shader; public string[] textures; public bool error_shader; }
    [Serializable] public class ViewInfo { public string name; public string file; public float yaw; public float pitch; }
    [Serializable] public class Result
    {
        public string id; public string path; public bool ok; public string error = "";
        public string asset_type = ""; public string loader = ""; public int renderers; public int skinned_renderers; public int missing_materials;
        public int embedded_lights_disabled; public int behaviours_disabled;
        public float[] bounds_center; public float[] bounds_size;
        public List<MaterialInfo> materials = new List<MaterialInfo>();
        public List<ViewInfo> views = new List<ViewInfo>();
    }
    [Serializable] public class Report { public string unity_version; public string render_pipeline; public string rig; public List<Result> results = new List<Result>(); }

    const float KeyIntensity = 1.1f, FillIntensity = 0.5f, Ambient = 0.45f;
    static readonly (string name, float yaw, float pitch)[] Views =
        { ("front", 180f, 10f), ("right", 270f, 10f), ("back", 0f, 10f), ("three_quarter_top", 135f, 40f) };

    static string Arg(string name)
    {
        var a = Environment.GetCommandLineArgs();
        for (int i = 0; i < a.Length - 1; i++) if (a[i] == name) return a[i + 1];
        return null;
    }

    // Batchmode without -quit: jobs run on the editor update loop (runtime glTF loads are
    // asynchronous), then the editor exits.
    static JobFile s_job; static Report s_report; static int s_next; static Result s_cur; static Job s_curJob;
    static System.Threading.Tasks.Task s_task; static object s_gltf; static GameObject s_root; static int s_stage; static double s_deadline;

    public static void Run()
    {
        try
        {
            s_job = JsonUtility.FromJson<JobFile>(File.ReadAllText(Arg("-gf3aViewsJob")));
            Directory.CreateDirectory(s_job.output_dir);
            s_report = new Report
            {
                unity_version = Application.unityVersion,
                render_pipeline = GraphicsSettings.currentRenderPipeline ? GraphicsSettings.currentRenderPipeline.GetType().Name : "builtin",
                rig = $"empty scene, flat ambient {Ambient}, key {KeyIntensity} (pitch 45, yaw 135), fill {FillIntensity} (pitch 30, yaw -45), fov 35"
            };
            s_next = 0; s_stage = 0;
            EditorApplication.update += Step;
        }
        catch (Exception e) { Debug.LogError("GF3A asset views failed: " + e); EditorApplication.Exit(2); }
    }

    static void Finish(string error = null)
    {
        if (s_cur != null)
        {
            if (error != null) { s_cur.ok = false; s_cur.error = error; } else s_cur.ok = s_cur.views.Count == Views.Length;
            s_report.results.Add(s_cur);
            File.WriteAllText(Path.Combine(s_job.output_dir, "unity_asset_views.json"), JsonUtility.ToJson(s_report, true));
        }
        s_cur = null; s_task = null; s_root = null; s_stage = 0;
    }

    static void Step()
    {
        try
        {
            if (s_stage == 0)
            {
                if (s_next >= s_job.jobs.Length) { EditorApplication.update -= Step; EditorApplication.Exit(0); return; }
                s_curJob = s_job.jobs[s_next++];
                s_cur = new Result { id = s_curJob.id, path = s_curJob.path };
                NewPreviewScene();
                if (!s_curJob.runtime_gltf) { Render(Spawn(s_curJob, s_cur)); Finish(); return; }
                s_cur.loader = "GLTFast.GltfImport (runtime loader, as the game loads it)";
                var type = Type.GetType("GLTFast.GltfImport, glTFast");
                if (type == null) { Finish("glTFast runtime loader not in this project"); return; }
                var ctor = type.GetConstructors().OrderBy(c => c.GetParameters().Length).First();
                // Editor (not play mode): the default frame-budget defer agent needs DontDestroyOnLoad.
                var defer = Type.GetType("GLTFast.UninterruptedDeferAgent, glTFast");
                var gltf = ctor.Invoke(ctor.GetParameters().Select(p => p.ParameterType.Name == "IDeferAgent" && defer != null
                    ? Activator.CreateInstance(defer) : (p.HasDefaultValue ? p.DefaultValue : null)).ToArray());
                s_root = new GameObject(s_curJob.id);
                var load = type.GetMethods().First(m => m.Name == "Load" && m.GetParameters().Length >= 1 && m.GetParameters()[0].ParameterType == typeof(string));
                var args = load.GetParameters().Select((p, i) => i == 0 ? (object)Path.GetFullPath(s_curJob.path) : (p.HasDefaultValue ? p.DefaultValue : null)).ToArray();
                s_task = (System.Threading.Tasks.Task)load.Invoke(gltf, args);
                s_gltf = gltf;
                s_stage = 1; s_deadline = EditorApplication.timeSinceStartup + 300;
                return;
            }
            if (EditorApplication.timeSinceStartup > s_deadline) { Finish("runtime glTF load timed out"); return; }
            if (!s_task.IsCompleted) return;
            if (s_task.IsFaulted) { Finish("runtime glTF load failed: " + s_task.Exception?.GetBaseException().Message); return; }
            var gl = s_gltf; var t = gl.GetType();
            if (s_stage == 1)
            {
                if (!(bool)s_task.GetType().GetProperty("Result").GetValue(s_task)) { Finish("runtime glTF load returned false"); return; }
                var inst = t.GetMethods().First(m => m.Name == "InstantiateMainSceneAsync" && m.GetParameters().Length >= 1 && m.GetParameters()[0].ParameterType == typeof(Transform));
                var args = inst.GetParameters().Select((p, i) => i == 0 ? (object)s_root.transform : (p.HasDefaultValue ? p.DefaultValue : null)).ToArray();
                s_task = (System.Threading.Tasks.Task)inst.Invoke(gl, args);
                s_stage = 2; return;
            }
            s_cur.asset_type = "glTF (runtime)";
            Render(Prepare(s_root, s_cur)); Finish();
        }
        catch (Exception e) { var x = e.GetBaseException(); Finish(x.GetType().Name + ": " + x.Message); Debug.LogError("GF3A job failed: " + x); }
    }

    static void NewPreviewScene()
    {
        EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
        RenderSettings.ambientMode = AmbientMode.Flat;
        RenderSettings.ambientLight = new Color(Ambient, Ambient, Ambient);
    }

    static (GameObject inst, Result r) Spawn(Job j, Result r)
    {
        var asset = AssetDatabase.LoadMainAssetAtPath(j.path);
        if (asset == null) throw new Exception("asset did not load: " + j.path);
        r.asset_type = asset.GetType().Name;
        var go = asset as GameObject;
        if (go == null) throw new Exception("not a GameObject/model asset: " + r.asset_type);
        r.loader = "AssetDatabase (editor import)";
        var inst = (GameObject)PrefabUtility.InstantiatePrefab(go) ?? UnityEngine.Object.Instantiate(go);
        return Prepare(inst, r);
    }

    static (GameObject inst, Result r) Prepare(GameObject inst, Result r)
    {
        inst.transform.position = Vector3.zero;
        foreach (var mb in inst.GetComponentsInChildren<MonoBehaviour>(true)) if (mb && mb.enabled) { mb.enabled = false; r.behaviours_disabled++; }
        foreach (var l in inst.GetComponentsInChildren<Light>(true)) if (l.enabled) { l.enabled = false; r.embedded_lights_disabled++; }
        return (inst, r);
    }

    static void Render((GameObject inst, Result r) target)
    {
        var (inst, r) = target;
        var job = s_job;

        var renderers = inst.GetComponentsInChildren<Renderer>(true).Where(x => x.enabled && x.gameObject.activeInHierarchy).ToArray();
        r.renderers = renderers.Length;
        r.skinned_renderers = renderers.Count(x => x is SkinnedMeshRenderer);
        if (renderers.Length == 0) throw new Exception("asset has no active renderers");
        var b = renderers[0].bounds;
        foreach (var x in renderers) b.Encapsulate(x.bounds);
        r.bounds_center = new[] { b.center.x, b.center.y, b.center.z };
        r.bounds_size = new[] { b.size.x, b.size.y, b.size.z };
        foreach (var x in renderers)
            foreach (var m in x.sharedMaterials)
            {
                var info = new MaterialInfo { renderer = x.name, material = m ? m.name : "<missing>", shader = m && m.shader ? m.shader.name : "" };
                if (m == null) r.missing_materials++;
                info.error_shader = m != null && (m.shader == null || m.shader.name == "Hidden/InternalErrorShader");
                if (m != null)
                    info.textures = m.GetTexturePropertyNames().Select(p => m.GetTexture(p)).Where(t => t != null)
                        .Select(t => t.name).Distinct().ToArray();
                r.materials.Add(info);
            }

        var key = new GameObject("GF3A_KeyLight").AddComponent<Light>();
        key.type = LightType.Directional; key.intensity = KeyIntensity; key.transform.rotation = Quaternion.Euler(45f, 135f, 0f);
        var fill = new GameObject("GF3A_FillLight").AddComponent<Light>();
        fill.type = LightType.Directional; fill.intensity = FillIntensity; fill.transform.rotation = Quaternion.Euler(30f, -45f, 0f);

        var cam = new GameObject("GF3A_ViewCamera").AddComponent<Camera>();
        cam.clearFlags = CameraClearFlags.SolidColor;
        cam.backgroundColor = new Color(0.20f, 0.22f, 0.26f);
        cam.fieldOfView = 35f;
        float radius = Mathf.Max(b.extents.magnitude, 0.01f);
        float dist = radius / Mathf.Sin(cam.fieldOfView * 0.5f * Mathf.Deg2Rad) * 1.05f;
        cam.nearClipPlane = Mathf.Max(0.01f, dist - radius * 2f);
        cam.farClipPlane = dist + radius * 2f;

        var rt = new RenderTexture(job.size, job.size, 24, RenderTextureFormat.ARGB32) { antiAliasing = 4 };
        cam.targetTexture = rt;
        var tex = new Texture2D(job.size, job.size, TextureFormat.RGB24, false);
        foreach (var v in Views)
        {
            var dir = Quaternion.Euler(v.pitch, v.yaw, 0f) * Vector3.forward;   // camera sits at center - dir*dist
            cam.transform.position = b.center - dir * dist;
            cam.transform.rotation = Quaternion.LookRotation(dir, Vector3.up);
            cam.Render();
            RenderTexture.active = rt;
            tex.ReadPixels(new Rect(0, 0, job.size, job.size), 0, 0);
            tex.Apply();
            RenderTexture.active = null;
            var file = Safe(r.id) + "__" + v.name + ".png";
            File.WriteAllBytes(Path.Combine(job.output_dir, file), tex.EncodeToPNG());
            r.views.Add(new ViewInfo { name = v.name, file = file, yaw = v.yaw, pitch = v.pitch });
        }
        cam.targetTexture = null;
        UnityEngine.Object.DestroyImmediate(rt);
        UnityEngine.Object.DestroyImmediate(tex);
    }

    static string Safe(string s) => new string(s.Select(c => char.IsLetterOrDigit(c) || c == '_' || c == '-' || c == '.' ? c : '_').ToArray());
}
#endif
