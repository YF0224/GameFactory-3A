// In-editor playtest recorder for the Unity adapter.
//
// The host client (engine_adapters/unity3d/playtest/client.py) launches one
// dedicated GUI Editor with `-executeMethod GameFactory3APlayTestRecorder.Enter`
// plus `--a3-playtest-*` arguments. This script opens the play scene, focuses
// the Game view, enters Play Mode, captures frames and state snapshots for the
// requested duration, writes the editor-side report, and exits the Editor.
//
// The host owns the scenario timeline: it polls the `play_started.json`
// marker and posts real keyboard events while this script captures. Batch
// mode is refused because the Game view has no render surface without a GUI
// Editor.

using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Text;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

[InitializeOnLoad]
public static class GameFactory3APlayTestRecorder
{
    private const string LogTag = "[GameFactory3APlayTest]";
    private const string PhaseKey = "GameFactory3A.PlayTestRecorder.Phase";
    private const string OutputKey = "GameFactory3A.PlayTestRecorder.Output";
    private const string SceneKey = "GameFactory3A.PlayTestRecorder.Scene";
    private const string FpsKey = "GameFactory3A.PlayTestRecorder.Fps";
    private const string DurationKey = "GameFactory3A.PlayTestRecorder.Duration";
    private const string WarmupKey = "GameFactory3A.PlayTestRecorder.Warmup";
    private const string StartTimeoutKey = "GameFactory3A.PlayTestRecorder.StartTimeout";
    private const string PhaseArmed = "armed";
    private const string PhaseInPlay = "inplay";
    private const double DefaultPlayStartTimeoutSeconds = 300.0;

    // Recorder state, all on the main thread. Everything needed across a
    // domain reload is mirrored in SessionState; these are per-domain views.
    private static string _outputDirectory = "";
    private static string _scenePath = "";
    private static int _fps = 20;
    private static double _durationSeconds = 12.0;
    private static double _warmupSeconds = 0.0;
    private static double _playStartTimeoutSeconds = DefaultPlayStartTimeoutSeconds;
    private static double _enterTimeSeconds;
    private static double _takeStartSeconds = -1.0;
    private static double _lastCaptureSeconds;
    private static int _frameCount;
    private static int _snapshotCount;
    private static int _lastCaptureWidth;
    private static int _lastCaptureHeight;
    private static double _lastCaptureElapsedSeconds;
    private static bool _exiting;
    private static bool _finished;
    private static readonly List<string> Warnings = new List<string>();
    private static readonly List<string> Errors = new List<string>();
    private static List<SnapshotProvider> _providers;

    [Serializable]
    private class EditorReport
    {
        public bool ok;
        public string schema_version = "gamefactory3a.unity3d.playtest_editor_report.v1";
        public string scene = "";
        public int fps;
        public double duration;
        public double warmup;
        public double recorded_seconds;
        public int frames;
        public int state_snapshots;
        public List<int> viewport = new List<int>();
        public List<string> warnings = new List<string>();
        public List<string> errors = new List<string>();
    }

    private sealed class SnapshotProvider
    {
        public UnityEngine.Object Source;
        public MethodInfo Method;
        public string Name;
    }

    // Entering Play Mode triggers a domain reload by default, which clears
    // every static field and event registration. The take therefore survives
    // on SessionState: arguments and the phase are persisted, and this
    // constructor resumes the matching handlers after each domain load. It
    // also covers the executeMethod lookup failing before a freshly updated
    // copy of this script has been compiled.
    static GameFactory3APlayTestRecorder()
    {
        if (!HasPlaytestArgument()) return;
        LoadSessionState();
        switch (SessionState.GetString(PhaseKey, ""))
        {
            case PhaseArmed:
                EditorApplication.update -= WaitForReady;
                EditorApplication.update += WaitForReady;
                break;
            case PhaseInPlay:
                ScheduleInPlay();
                break;
        }
    }

    private static bool HasPlaytestArgument()
    {
        string[] args = Environment.GetCommandLineArgs();
        for (int index = 0; index + 1 < args.Length; index++)
        {
            if (args[index] == "--a3-playtest-output")
                return true;
        }
        return false;
    }

    public static void Enter()
    {
        if (SessionState.GetString(PhaseKey, "") == PhaseInPlay)
            return;  // the take already started before a domain reload

        var args = ParseArgs(Environment.GetCommandLineArgs());
        _outputDirectory = Get(args, "output", "");
        _scenePath = Get(args, "scene", "");
        _fps = GetInt(args, "fps", 20);
        _durationSeconds = GetDouble(args, "duration", 12.0);
        _warmupSeconds = GetDouble(args, "warmup", 0.0);
        _playStartTimeoutSeconds = GetDouble(args, "start-timeout", DefaultPlayStartTimeoutSeconds);

        if (string.IsNullOrEmpty(_outputDirectory))
        {
            FailAndExit("the host must pass --a3-playtest-output", exitCode: 4);
            return;
        }
        if (Application.isBatchMode)
        {
            // Frame capture needs the Game view render surface; batch mode
            // would silently produce a take with no evidence.
            FailAndExit("batch mode cannot record playtest frames", exitCode: 4);
            return;
        }

        SaveSessionState();
        SessionState.SetString(PhaseKey, PhaseArmed);
        Debug.Log($"{LogTag} waiting for the Editor to finish loading");
        EditorApplication.update -= WaitForReady;
        EditorApplication.update += WaitForReady;
    }

    private static void WaitForReady()
    {
        if (EditorApplication.isCompiling || EditorApplication.isUpdating)
            return;

        EditorApplication.update -= WaitForReady;
        try
        {
            OpenPlayScene();
            FocusGameView();
            // Phase is stored before entering Play Mode so this constructor
            // can re-register the capture handlers after the domain reload
            // that entering Play Mode triggers by default.
            SessionState.SetString(PhaseKey, PhaseInPlay);
            ScheduleInPlay();
            Debug.Log($"{LogTag} entering Play Mode for scene {_scenePath}");
            EditorApplication.isPlaying = true;
        }
        catch (Exception exception)
        {
            FailAndExit(exception.ToString(), exitCode: 4);
        }
    }

    private static void ScheduleInPlay()
    {
        _enterTimeSeconds = EditorApplication.timeSinceStartup;
        EditorApplication.playModeStateChanged -= HandlePlayModeStateChanged;
        EditorApplication.playModeStateChanged += HandlePlayModeStateChanged;
        EditorApplication.update -= WaitForPlayMode;
        EditorApplication.update += WaitForPlayMode;
    }

    private static void LoadSessionState()
    {
        _outputDirectory = SessionState.GetString(OutputKey, "");
        _scenePath = SessionState.GetString(SceneKey, "");
        _fps = SessionState.GetInt(FpsKey, 20);
        _durationSeconds = SessionState.GetFloat(DurationKey, 12f);
        _warmupSeconds = SessionState.GetFloat(WarmupKey, 0f);
        _playStartTimeoutSeconds = SessionState.GetFloat(
            StartTimeoutKey, (float)DefaultPlayStartTimeoutSeconds);
    }

    private static void SaveSessionState()
    {
        SessionState.SetString(OutputKey, _outputDirectory);
        SessionState.SetString(SceneKey, _scenePath);
        SessionState.SetInt(FpsKey, _fps);
        SessionState.SetFloat(DurationKey, (float)_durationSeconds);
        SessionState.SetFloat(WarmupKey, (float)_warmupSeconds);
        SessionState.SetFloat(StartTimeoutKey, (float)_playStartTimeoutSeconds);
    }

    private static void WaitForPlayMode()
    {
        if (EditorApplication.isPlaying)
        {
            EditorApplication.update -= WaitForPlayMode;
            return;
        }
        // Play mode was refused or left immediately; the state-changed
        // handler writes the report, so stop waiting without forcing a
        // second exit.
        if (EditorApplication.isPlayingOrWillChangePlaymode)
            return;
        EditorApplication.update -= WaitForPlayMode;
        if (EditorApplication.timeSinceStartup - _enterTimeSeconds >
            _playStartTimeoutSeconds)
        {
            FailAndExit("Play Mode did not start in time", exitCode: 3);
        }
    }

    private static void HandlePlayModeStateChanged(PlayModeStateChange state)
    {
        // Unity 2022 has no ExitedPlayMode value, so the end of the take is
        // detected by polling `EditorApplication.isPlaying` in CaptureTick.
        if (state == PlayModeStateChange.EnteredPlayMode)
            BeginTake();
    }

    private static void BeginTake()
    {
        _takeStartSeconds = -1.0;
        _lastCaptureSeconds = 0.0;
        _lastCaptureElapsedSeconds = 0.0;
        _providers = FindSnapshotProviders();
        Directory.CreateDirectory(Path.Combine(_outputDirectory, "frames"));
        WritePlayStartedMarker();
        EditorApplication.update += CaptureTick;
        Debug.Log($"{LogTag} take started (fps={_fps}, duration={_durationSeconds}s, warmup={_warmupSeconds}s)");
    }

    private static void CaptureTick()
    {
        // Play Mode ended: either the take completed (this script requested
        // the stop) or something stopped it early; both end the take.
        if (!EditorApplication.isPlaying)
        {
            FinishTake();
            return;
        }
        double now = EditorApplication.timeSinceStartup;
        if (_takeStartSeconds < 0.0)
        {
            _takeStartSeconds = now;
            _lastCaptureSeconds = now;
        }
        double elapsed = now - _takeStartSeconds;
        if (elapsed >= _warmupSeconds + _durationSeconds)
        {
            // Stop Play Mode but keep CaptureTick registered: the !isPlaying
            // check above is what finishes the take after the stop completes.
            EditorApplication.isPlaying = false;
            return;
        }
        if (elapsed < _warmupSeconds)
            return;
        double interval = _fps > 0 ? 1.0 / _fps : 0.05;
        if (now - _lastCaptureSeconds < interval)
            return;
        _lastCaptureSeconds = now;
        CaptureFrame(elapsed);
    }

    private static void CaptureFrame(double elapsedSeconds)
    {
        try
        {
            Texture2D shot = ScreenCapture.CaptureScreenshotAsTexture();
            // 64px, not 8: the Game view's settling capture is a full-width
            // sliver (for example 2048x40), tall enough to pass a tiny
            // threshold but useless as evidence.
            if (shot == null || shot.width < 64 || shot.height < 64)
            {
                // Right after Play Mode starts the Game view still needs a
                // moment to build a real render surface; its first captures
                // can be null or degenerate slivers. Wait for a real frame
                // instead of writing it into the evidence.
                if (shot != null) UnityEngine.Object.Destroy(shot);
                RecordWarning("waiting for the Game view to produce a real frame");
                return;
            }
            _lastCaptureWidth = shot.width;
            _lastCaptureHeight = shot.height;
            _lastCaptureElapsedSeconds = elapsedSeconds;
            _frameCount += 1;
            byte[] png = shot.EncodeToPNG();
            UnityEngine.Object.Destroy(shot);
            string path = Path.Combine(
                _outputDirectory, "frames", $"f{_frameCount:00000}.png");
            File.WriteAllBytes(path, png);
            CaptureStateSnapshot(_frameCount, elapsedSeconds);
        }
        catch (Exception exception)
        {
            RecordWarning("frame capture failed: " + exception.Message);
        }
    }

    private static void CaptureStateSnapshot(int frame, double elapsedSeconds)
    {
        if (_providers == null || _providers.Count == 0)
            return;
        var builder = new StringBuilder();
        builder.Append("{\"frame\":").Append(frame.ToString(CultureInfo.InvariantCulture));
        builder.Append(",\"t_sec\":")
            .Append(elapsedSeconds.ToString("0.###", CultureInfo.InvariantCulture));
        builder.Append(",\"state\":{");
        bool firstProvider = true;
        foreach (var provider in _providers)
        {
            try
            {
                object value = provider.Method.Invoke(provider.Source, null);
                if (value == null) continue;
                if (!firstProvider) builder.Append(",");
                firstProvider = false;
                builder.Append(JsonEscape(provider.Name)).Append(":");
                WriteJsonValue(builder, value);
                _snapshotCount += 1;
            }
            catch (Exception exception)
            {
                RecordWarning("state snapshot failed for " + provider.Name + ": " + exception.Message);
            }
        }
        builder.Append("}}");
        string path = Path.Combine(_outputDirectory, "diagnostics.jsonl");
        File.AppendAllText(path, builder + "\n", new UTF8Encoding(false));
    }

    private static List<SnapshotProvider> FindSnapshotProviders()
    {
        var providers = new List<SnapshotProvider>();
        // Privileged diagnostics: any runtime adapter exposing the runtime
        // contract's `GetStateSnapshot()` is captured out-of-band. The data
        // never enters the player-visible observation channel.
        foreach (MonoBehaviour behaviour in UnityEngine.Object.FindObjectsOfType<MonoBehaviour>(true))
        {
            MethodInfo method = behaviour.GetType().GetMethod(
                "GetStateSnapshot",
                BindingFlags.Public | BindingFlags.Instance,
                binder: null,
                types: Type.EmptyTypes,
                modifiers: null);
            if (method == null) continue;
            providers.Add(new SnapshotProvider
            {
                Source = behaviour,
                Method = method,
                Name = behaviour.GetType().Name,
            });
        }
        return providers;
    }

    private static void FinishTake()
    {
        if (_finished) return;
        _finished = true;
        EditorApplication.update -= CaptureTick;
        bool ok = _frameCount > 0;
        var report = new EditorReport
        {
            ok = ok,
            scene = _scenePath,
            fps = _fps,
            duration = _durationSeconds,
            warmup = _warmupSeconds,
            // The editor throttles when idle, so the real wall time of the
            // last capture is the honest recorded length, not frames/fps.
            recorded_seconds = _lastCaptureElapsedSeconds,
            frames = _frameCount,
            state_snapshots = _snapshotCount,
            warnings = Warnings,
            errors = Errors,
        };
        if (ok && _frameCount > 0)
        {
            // The Game view decides the actual capture resolution; report
            // what was captured rather than what was requested.
            report.viewport.Add(_lastCaptureWidth);
            report.viewport.Add(_lastCaptureHeight);
        }
        if (!ok && Errors.Count == 0)
            Errors.Add("no frames were captured");
        WriteEditorReport(report);
        EditorApplication.playModeStateChanged -= HandlePlayModeStateChanged;
        SessionState.EraseString(PhaseKey);
        _exiting = true;
        EditorApplication.Exit(report.ok ? 0 : 1);
    }

    private static void FailAndExit(string message, int exitCode)
    {
        Errors.Add(message);
        Debug.LogError($"{LogTag} {message}");
        var report = new EditorReport
        {
            ok = false,
            scene = _scenePath,
            fps = _fps,
            duration = _durationSeconds,
            warmup = _warmupSeconds,
            warnings = Warnings,
            errors = Errors,
        };
        WriteEditorReport(report);
        SessionState.EraseString(PhaseKey);
        if (!_exiting)
        {
            _exiting = true;
            EditorApplication.Exit(exitCode);
        }
    }

    private static void WritePlayStartedMarker()
    {
        var builder = new StringBuilder();
        builder.Append("{\"play_started_wall\":\"")
            .Append(DateTime.UtcNow.ToString("o", CultureInfo.InvariantCulture))
            .Append("\",\"editor_pid\":")
            .Append(
                System.Diagnostics.Process.GetCurrentProcess().Id
                    .ToString(CultureInfo.InvariantCulture))
            .Append("}");
        File.WriteAllText(
            Path.Combine(_outputDirectory, "play_started.json"),
            builder.ToString(),
            new UTF8Encoding(false));
    }

    private static void WriteEditorReport(EditorReport report)
    {
        try
        {
            Directory.CreateDirectory(_outputDirectory);
            File.WriteAllText(
                Path.Combine(_outputDirectory, "_editor_report.json"),
                EditorReportToJson(report),
                new UTF8Encoding(false));
        }
        catch (Exception exception)
        {
            Debug.LogError($"{LogTag} could not write editor report: {exception}");
        }
    }

    private static string EditorReportToJson(EditorReport report)
    {
        var builder = new StringBuilder();
        builder.Append("{\"ok\":").Append(report.ok ? "true" : "false");
        builder.Append(",\"schema_version\":").Append(JsonEscape(report.schema_version));
        builder.Append(",\"scene\":").Append(JsonEscape(report.scene));
        builder.Append(",\"fps\":").Append(report.fps.ToString(CultureInfo.InvariantCulture));
        builder.Append(",\"duration\":")
            .Append(report.duration.ToString("0.###", CultureInfo.InvariantCulture));
        builder.Append(",\"warmup\":")
            .Append(report.warmup.ToString("0.###", CultureInfo.InvariantCulture));
        builder.Append(",\"recorded_seconds\":")
            .Append(report.recorded_seconds.ToString("0.###", CultureInfo.InvariantCulture));
        builder.Append(",\"frames\":").Append(report.frames.ToString(CultureInfo.InvariantCulture));
        builder.Append(",\"state_snapshots\":")
            .Append(report.state_snapshots.ToString(CultureInfo.InvariantCulture));
        builder.Append(",\"viewport\":[");
        for (int index = 0; index < report.viewport.Count; index++)
        {
            if (index > 0) builder.Append(",");
            builder.Append(report.viewport[index].ToString(CultureInfo.InvariantCulture));
        }
        builder.Append("]");
        builder.Append(",\"warnings\":").Append(JsonStringList(report.warnings));
        builder.Append(",\"errors\":").Append(JsonStringList(report.errors));
        builder.Append("}");
        return builder.ToString();
    }

    private static void OpenPlayScene()
    {
        if (string.IsNullOrWhiteSpace(_scenePath))
            return;
        string projectRoot = Directory.GetParent(Application.dataPath).FullName;
        string resolved = _scenePath;
        if (!Path.IsPathRooted(resolved))
            resolved = Path.Combine(projectRoot, resolved);
        if (!File.Exists(resolved))
            throw new FileNotFoundException($"Play scene was not found: {_scenePath}");
        _scenePath = resolved;
        EditorSceneManager.OpenScene(resolved, OpenSceneMode.Single);
    }

    private static void FocusGameView()
    {
        try
        {
            // Keyboard events during Play Mode reach gameplay only when the
            // Game view owns key focus; entering play from a script does not
            // guarantee that.
            EditorApplication.ExecuteMenuItem("Window/General/Game");
        }
        catch (Exception exception)
        {
            RecordWarning("could not focus the Game view: " + exception.Message);
        }
    }

    private static void RecordWarning(string message)
    {
        if (!Warnings.Contains(message))
            Warnings.Add(message);
        Debug.LogWarning($"{LogTag} {message}");
    }

    // ── Minimal JSON writing ────────────────────────────────────────────────

    private static void WriteJsonValue(StringBuilder builder, object value)
    {
        if (value == null)
        {
            builder.Append("null");
            return;
        }
        if (value is bool flag)
        {
            builder.Append(flag ? "true" : "false");
            return;
        }
        if (value is string text)
        {
            builder.Append(JsonEscape(text));
            return;
        }
        if (value is float single)
        {
            builder.Append(single.ToString("R", CultureInfo.InvariantCulture));
            return;
        }
        if (value is double real)
        {
            builder.Append(real.ToString("R", CultureInfo.InvariantCulture));
            return;
        }
        if (value is IConvertible convertible && value is not IEnumerable)
        {
            try
            {
                builder.Append(Convert.ToDouble(convertible)
                    .ToString("R", CultureInfo.InvariantCulture));
                return;
            }
            catch
            {
                // Non-numeric IConvertible falls through to string form.
            }
        }
        if (value is IDictionary dictionary)
        {
            builder.Append("{");
            bool first = true;
            foreach (DictionaryEntry entry in dictionary)
            {
                if (!first) builder.Append(",");
                first = false;
                builder.Append(JsonEscape(Convert.ToString(entry.Key, CultureInfo.InvariantCulture)));
                builder.Append(":");
                WriteJsonValue(builder, entry.Value);
            }
            builder.Append("}");
            return;
        }
        if (value is IEnumerable sequence)
        {
            builder.Append("[");
            bool first = true;
            foreach (object item in sequence)
            {
                if (!first) builder.Append(",");
                first = false;
                WriteJsonValue(builder, item);
            }
            builder.Append("]");
            return;
        }
        builder.Append(JsonEscape(Convert.ToString(value, CultureInfo.InvariantCulture)));
    }

    private static string JsonStringList(List<string> values)
    {
        var builder = new StringBuilder();
        builder.Append("[");
        for (int index = 0; index < values.Count; index++)
        {
            if (index > 0) builder.Append(",");
            builder.Append(JsonEscape(values[index]));
        }
        builder.Append("]");
        return builder.ToString();
    }

    private static string JsonEscape(string value)
    {
        if (value == null) return "\"\"";
        var builder = new StringBuilder();
        builder.Append('"');
        foreach (char character in value)
        {
            switch (character)
            {
                case '"': builder.Append("\\\""); break;
                case '\\': builder.Append("\\\\"); break;
                case '\n': builder.Append("\\n"); break;
                case '\r': builder.Append("\\r"); break;
                case '\t': builder.Append("\\t"); break;
                default:
                    if (character < ' ')
                        builder.Append("\\u")
                            .Append(((int)character).ToString("x4", CultureInfo.InvariantCulture));
                    else
                        builder.Append(character);
                    break;
            }
        }
        builder.Append('"');
        return builder.ToString();
    }

    // ── Command-line parsing (GenerateGame conventions) ───────────────────

    private static Dictionary<string, string> ParseArgs(string[] argv)
    {
        var result = new Dictionary<string, string>();
        for (int index = 0; index < argv.Length; index++)
        {
            if (!argv[index].StartsWith("--a3-playtest-")) continue;
            string key = argv[index].Substring("--a3-playtest-".Length);
            string value = index + 1 < argv.Length && !argv[index + 1].StartsWith("--")
                ? argv[++index]
                : "";
            result[key] = value;
        }
        return result;
    }

    private static string Get(Dictionary<string, string> args, string key, string fallback)
    {
        if (args.TryGetValue(key, out string value) && !string.IsNullOrEmpty(value))
            return value;
        return fallback;
    }

    private static int GetInt(Dictionary<string, string> args, string key, int fallback)
    {
        if (args.TryGetValue(key, out string value) &&
            int.TryParse(value, NumberStyles.Integer, CultureInfo.InvariantCulture, out int parsed))
            return parsed;
        return fallback;
    }

    private static double GetDouble(Dictionary<string, string> args, string key, double fallback)
    {
        if (args.TryGetValue(key, out string value) &&
            double.TryParse(value, NumberStyles.Float, CultureInfo.InvariantCulture, out double parsed))
            return parsed;
        return fallback;
    }
}
