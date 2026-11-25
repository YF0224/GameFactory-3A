// In-editor playtest recorder for the Unity adapter.
//
// The host client (engine_adapters/unity3d/playtest/client.py) launches one
// dedicated GUI Editor with `-executeMethod GameFactory3APlayTestRecorder.Enter`
// plus `--gamefactory-evaluation-*` arguments. This script opens the play scene, focuses
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
using System.Linq.Expressions;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.Playables;
using UnityEngine.Animations;

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
    private static double _nextCaptureSeconds;
    private static double _inputReadyElapsedSeconds = -1.0;
    [Serializable]
    private class SparsePoint
    {
        public double at_ms;
        public string[] capture_ids;
    }
    [Serializable]
    private class SparseSchedule
    {
        public string version;
        public SparsePoint[] points;
    }
    [Serializable]
    private class EndpointSettleGuard
    {
        public string capture_id;
        public string action_id;
        public double stable_after_ms;
    }
    [Serializable]
    private class EndpointSettleGuards
    {
        public string schema;
        public EndpointSettleGuard[] endpoints;
    }
    private static EndpointSettleGuards _endpointSettleGuards;
    private static SparseSchedule _sparseSchedule;
    private static int _sparsePosition;
    private static double _activeSampleMs = -1;
    private static double _scheduledLagMs;
    private static string[] _activeCaptureIds = new string[] { "readiness" };
    private static double _nextStateSeconds;
    private const double RenderReadyTimeoutSeconds = 30.0;
    private static int _skippedSamplingSlots;
    private static readonly List<double> CaptureTimesMs = new List<double>();
    private static readonly List<double> ScreenshotDurationsMs = new List<double>();
    private static int _frameCount;
    private static int _snapshotCount;
    private static int _stateTraceRows;
    private static int _eventTraceRows;
    private static int _lastCaptureWidth;
    private static int _lastCaptureHeight;
    private static double _lastCaptureElapsedSeconds;
    private static bool _exiting;
    private static bool _finished;
    private static GameFactory3AAudioTap _audioTap;
    private static bool _audioLateAttach;
    private static double _audioLastListenerCheck;
    private static GameFactory3AFrameTap _frameTap;
    private static GameFactory3AInputDriver _inputDriver;
    private static bool _useInternalDriver;
    private static bool _capturePending;
    private static double _captureRequestSeconds;
    private static double _captureReadSeconds;
    private static readonly List<string> Warnings = new List<string>();
    private static readonly List<string> Errors = new List<string>();
    private static List<SnapshotProvider> _providers;
    private static List<RuntimeEventSubscription> _eventSubscriptions;
    private static bool _sceneObserversDirty;
    private static string _stateTracePath;
    private static string _eventTracePath;

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
        public double actual_runtime_seconds;
        public double actual_fps;
        public int skipped_sampling_slots;
        public List<double> sampling_intervals_ms = new List<double>();
        public List<double> screenshot_durations_ms = new List<double>();
        public int frames;
        public int state_snapshots;
        public List<int> viewport = new List<int>();
        public List<string> warnings = new List<string>();
        public List<string> errors = new List<string>();
        public ChannelCoverage channels = new ChannelCoverage();
    }

    [Serializable]
    private class ChannelCoverage
    {
        // Which runtime observation channels the take actually captured —
        // downstream gating distinguishes "captured but empty" from
        // "never captured" from these flags, never from the request.
        public bool states_available;
        public int state_rows;
        public string states_source = "";
        public bool events_available;
        public int event_rows;
        public int event_subscriptions;
        public string events_capture_error = "";
        public bool frames_available;
    }

    private sealed class SnapshotProvider
    {
        public object Source;
        public Component Owner;
        public string MemberPath = "";
        public MethodInfo Method;
        public PublicFieldPath[] PublicFields;
        public bool PublicAutoProperties;
        public bool MutableAutoProperties;
        public HashSet<string> AutoPropertyBindings = new HashSet<string>();
        public string Name;
    }

    /// One subscribed public event on a discovered runtime adapter.
    private sealed class RuntimeEventSubscription
    {
        public object Source;
        public EventInfo Event;
        public Delegate Handler;
        public string EventName;
        public string SourceKey;
        public bool ExplicitPublicTarget;
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
            if (args[index] == "--gamefactory-evaluation-output")
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
            FailAndExit("the host must pass --gamefactory-evaluation-output", exitCode: 4);
            return;
        }
        if (Application.isBatchMode && !GraphicsBatchCapture)
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
        if (BackgroundCapture) Application.runInBackground = true;
        // Asset shots at the end of the take need full-resolution textures: with mipmap streaming on, load
        // every mip from the start of the take (nothing changes for projects without streaming).
        if (!string.IsNullOrEmpty(Environment.GetEnvironmentVariable("GAMEFACTORY_UNITY_ASSET_SHOTS_PLAN")))
            Texture.streamingTextureForceLoadAll = true;
        File.WriteAllText(Path.Combine(_outputDirectory, "background_environment.json"),
            "{\"experiment\":true,\"activation\":\"forbidden\",\"runInBackground\":true,\"inputSettingsChanged\":true,\"inputSettingsRecord\":\"background_input_settings.json\"}");
        _takeStartSeconds = EditorApplication.timeSinceStartup;
        _inputReadyElapsedSeconds = -1.0;
        Application.logMessageReceived -= OnGameLog;
        Application.logMessageReceived += OnGameLog;      // game's own Debug.Log -> game_events.jsonl (timed)
        string sparsePath = Path.Combine(_outputDirectory, "capture_schedule.json");
        _sparseSchedule = File.Exists(sparsePath) ? JsonUtility.FromJson<SparseSchedule>(File.ReadAllText(sparsePath)) : null;
        if (_sparseSchedule != null && ((_sparseSchedule.version != "whitebox-endpoint-gameness-sparse.v1" && _sparseSchedule.version != "whitebox-endpoint-gameness-sparse.v2") || _sparseSchedule.points == null))
            throw new InvalidOperationException("Unsupported native sparse capture schedule");
        string guardsPath = Path.Combine(_outputDirectory, "endpoint_settle_guards.json");
        _endpointSettleGuards = File.Exists(guardsPath) ? JsonUtility.FromJson<EndpointSettleGuards>(File.ReadAllText(guardsPath)) : null;
        if (_sparseSchedule != null && _sparseSchedule.version == "whitebox-endpoint-gameness-sparse.v2" &&
            (_endpointSettleGuards == null || _endpointSettleGuards.schema != "whitebox-native-endpoint-settle.v1" || _endpointSettleGuards.endpoints == null))
            throw new InvalidOperationException("Native endpoint settling guards are missing or invalid");
        _sparsePosition = 0;
        _activeSampleMs = -1;
        _scheduledLagMs = 0;
        EventFrames.Reset();
        AudioWatch.Reset();
        AssetWatch.Reset();
        _activeCaptureIds = new string[] { "readiness" };
        _nextStateSeconds = _takeStartSeconds;
        _lastCaptureSeconds = _takeStartSeconds;
        _lastCaptureElapsedSeconds = 0.0;
        _nextCaptureSeconds = _takeStartSeconds + _warmupSeconds;
        _skippedSamplingSlots = 0;
        CaptureTimesMs.Clear();
        ScreenshotDurationsMs.Clear();
        _frameCount = 0;
        _snapshotCount = 0;
        _stateTraceRows = 0;
        _eventTraceRows = 0;
        _providers = FindSnapshotProviders();
        _stateTracePath = Path.Combine(_outputDirectory, "state_trace.jsonl");
        _eventTracePath = Path.Combine(_outputDirectory, "event_trace.jsonl");
        _eventSubscriptions = SubscribeRuntimeEvents();
        _sceneObserversDirty = false;
        SceneManager.sceneLoaded -= OnObservedSceneLoaded;
        SceneManager.sceneLoaded += OnObservedSceneLoaded;
        SceneManager.sceneUnloaded -= OnObservedSceneUnloaded;
        SceneManager.sceneUnloaded += OnObservedSceneUnloaded;
        Directory.CreateDirectory(Path.Combine(_outputDirectory, "frames"));
        var listeners = UnityEngine.Object.FindObjectsOfType<AudioListener>();
        var activeListeners = new List<AudioListener>();
        foreach (var listener in listeners)
            if (listener.enabled && listener.gameObject.activeInHierarchy) activeListeners.Add(listener);
        if (activeListeners.Count == 1)
        {
            _audioTap = activeListeners[0].gameObject.AddComponent<GameFactory3AAudioTap>();
            _audioTap.Begin(_outputDirectory, (EditorApplication.timeSinceStartup - _takeStartSeconds) * 1000.0, _durationSeconds + _warmupSeconds);
        }
        else
        {
            File.WriteAllText(Path.Combine(_outputDirectory, "audio_capture.json"),
                "{\"status\":\"unavailable\",\"source\":\"game_output\",\"error\":\"expected_one_active_listener\"}");
            _audioLateAttach = activeListeners.Count == 0;   // a listener the game creates later is still tapped
            _audioLastListenerCheck = 0.0;
        }
        var captureObject = new GameObject("GameFactory3AReadOnlyFrameObserver");
        captureObject.hideFlags = HideFlags.HideAndDontSave;
        UnityEngine.Object.DontDestroyOnLoad(captureObject);
        _frameTap = captureObject.AddComponent<GameFactory3AFrameTap>();
        _capturePending = false;

        // Activate internal input driver if _scenario.json requested it.
        // InputSystem-only projects can queue native input state. Legacy or dual
        // backend projects require host physical input, selected in the marker.
        _useInternalDriver = false;
        _inputDriver = null;
        var scenarioPath = Path.Combine(_outputDirectory, "_scenario.json");
        if (File.Exists(scenarioPath))
        {
            try
            {
                var scenarioText = File.ReadAllText(scenarioPath);
                var scenario = JsonUtility.FromJson<GameFactory3AInputDriver.Scenario>(scenarioText);
                if (scenario != null && scenario.use_internal_driver && GameFactory3AInputDriver.SupportsInternalInput)
                {
                    var steps = scenario.events;
                    _inputDriver = new GameFactory3AInputDriver();
                    _inputDriver.Begin(_outputDirectory, _takeStartSeconds, _warmupSeconds, steps);
                    _frameTap.beforeManualInputUpdate = _inputDriver.IsolateBackgroundDevices;
                    _useInternalDriver = true;
                    Debug.Log($"{LogTag} internal input driver activated ({steps.Count} steps)");
                }
            }
            catch (Exception ex)
            {
                Errors.Add("HARNESS_ERROR: internal driver init failed: " + ex.Message);
            }
        }

        if (BackgroundCapture && !_useInternalDriver) { FailAndExit("background experiment requires native InputSystem internal transport; no physical fallback", 4); return; }
        FocusGameView();
        EditorApplication.update += CaptureTick;
        Debug.Log($"{LogTag} take started (fps={_fps}, duration={_durationSeconds}s, warmup={_warmupSeconds}s, " +
                  $"providers={_providers.Count}, event_subscriptions={_eventSubscriptions.Count}, " +
                  $"input_driver={(_useInternalDriver ? "internal" : "host")})");
    }

    private static void OnObservedSceneLoaded(Scene scene, LoadSceneMode mode) { _sceneObserversDirty = true; }
    private static void OnObservedSceneUnloaded(Scene scene) { _sceneObserversDirty = true; }

    private static void CaptureTick()
    {
        // Play Mode ended: either the take completed (this script requested
        // the stop) or something stopped it early; both end the take.
        if (!EditorApplication.isPlaying)
        {
            FinishTake();
            return;
        }
        if (_sceneObserversDirty)
        {
            _sceneObserversDirty = false;
            UnsubscribeRuntimeEvents();
            _providers = FindSnapshotProviders();
            _eventSubscriptions = SubscribeRuntimeEvents();
            File.AppendAllText(Path.Combine(_outputDirectory, "observer_lifecycle.jsonl"),
                "{\"event\":\"scene_observers_refreshed\",\"t_ms\":" +
                ((EditorApplication.timeSinceStartup - _takeStartSeconds) * 1000.0).ToString("0.###", CultureInfo.InvariantCulture) +
                ",\"scene\":" + JsonEscape(SceneManager.GetActiveScene().path) +
                ",\"providers\":" + _providers.Count.ToString(CultureInfo.InvariantCulture) + "}\n");
        }
        double now = EditorApplication.timeSinceStartup;
        if (_takeStartSeconds < 0.0)
        {
            _takeStartSeconds = now;
            _lastCaptureSeconds = now;
        }
        double elapsed = now - _takeStartSeconds;
        try { AudioWatch.Poll(_outputDirectory, elapsed * 1000.0); } catch (Exception) { }
        try { AssetWatch.Poll(_outputDirectory, elapsed * 1000.0, _inputReadyElapsedSeconds >= 0.0); } catch (Exception) { }
        if (_inputReadyElapsedSeconds >= 0.0)
        {   // timed state-entry / direct-trigger calls (at_ms after input readiness)
            try { StateEntry.Tick((EditorApplication.timeSinceStartup - _takeStartSeconds) * 1000.0); }
            catch (Exception exception) { Errors.Add("state entry failed: " + exception.Message); }
        }
        if (_audioTap == null && _audioLateAttach && elapsed - _audioLastListenerCheck >= 0.2)
        {   // the game created its AudioListener after the take started: attach the read-only tap now
            _audioLastListenerCheck = elapsed;
            var late = new List<AudioListener>();
            foreach (var l in UnityEngine.Object.FindObjectsOfType<AudioListener>())
                if (l.enabled && l.gameObject.activeInHierarchy) late.Add(l);
            if (late.Count == 1)
            {
                try
                {
                    _audioTap = late[0].gameObject.AddComponent<GameFactory3AAudioTap>();
                    _audioTap.Begin(_outputDirectory, elapsed * 1000.0,
                        Math.Max(1.0, _durationSeconds + _warmupSeconds - Math.Max(0.0, elapsed - Math.Max(0.0, _inputReadyElapsedSeconds))));
                    _audioLateAttach = false;
                }
                catch (Exception exception) { _audioLateAttach = false; RecordWarning("late audio tap failed: " + exception.Message); }
            }
        }
        if (_sparseSchedule != null && now >= _nextStateSeconds)
        {
            _nextStateSeconds = now + 0.1;
            CaptureStateSnapshot(_frameCount, elapsed);
        }
        if (_inputReadyElapsedSeconds < 0.0 && elapsed >= RenderReadyTimeoutSeconds)
        {
            Errors.Add("HARNESS_ERROR: GameView did not produce a focused usable first frame before readiness deadline");
            EditorApplication.isPlaying = false;
            return;
        }
        double captureDeadline = _inputReadyElapsedSeconds + _warmupSeconds + _durationSeconds;
        bool sparseSamplesPending = _sparseSchedule != null && _sparsePosition < _sparseSchedule.points.Length;
        if (_inputReadyElapsedSeconds >= 0.0 && elapsed >= captureDeadline && !sparseSamplesPending && !_capturePending)
        {
            // Stop Play Mode but keep CaptureTick registered: the !isPlaying
            // check above is what finishes the take after the stop completes.
            // A pending end-of-frame read gets a finite flush window. Never
            // enqueue another screenshot or manufacture the final frame.
            if (_capturePending && now - _captureRequestSeconds < 5.0) { if (BackgroundCapture) FocusGameView(); return; }
            if (_capturePending) Errors.Add("HARNESS_ERROR: final end-of-frame capture exceeded flush deadline");
            if (_audioTap != null) _audioTap.Finish();
            if (_inputDriver != null) _inputDriver.Finish();
            // Opt-in end-of-take photos of the imported assets in the running scene (still in Play Mode).
            try
            {
                string shotsPlan = Environment.GetEnvironmentVariable("GAMEFACTORY_UNITY_ASSET_SHOTS_PLAN");
                AssetShots.Capture(shotsPlan, _outputDirectory);
            }
            catch (Exception exception) { Errors.Add("asset shots failed (not a take failure): " + exception.Message); }
            EditorApplication.isPlaying = false;
            return;
        }
        // A usable render surface and verified GameView focus precede input.
        // Readiness has its own bounded deadline; it consumes no input budget.
        if (!FocusGameView())
        {
            WriteInputFocus();
            return;
        }
        WriteInputFocus();
        double interval = _fps > 0 ? 1.0 / _fps : 0.05;
        if (_sparseSchedule != null && _inputReadyElapsedSeconds >= 0)
        {
            if (_capturePending) return;
            double routeMs = (elapsed - _inputReadyElapsedSeconds - _warmupSeconds) * 1000.0;
            bool scheduledDue = _sparsePosition < _sparseSchedule.points.Length && routeMs >= _sparseSchedule.points[_sparsePosition].at_ms;
            // event frames only with spare capture time: next scheduled slot >= 120 ms away (Unity captures at end of
            // frame, ~1 frame each; baseline is every 250 ms, so 400 ms never fired), scheduled capture not behind
            double nextSlotMs = _sparsePosition < _sparseSchedule.points.Length ? _sparseSchedule.points[_sparsePosition].at_ms : 1e12;
            bool spare = nextSlotMs - routeMs >= 120.0 && _scheduledLagMs <= 300.0;
            if (!scheduledDue && spare && EventFrames.TryTake(elapsed * 1000.0, out string eventCapture))
            {   // event-triggered frame (opt-in): only between scheduled slots, which keep priority
                _activeSampleMs = -1;
                _activeCaptureIds = new[] { eventCapture };
                _nextCaptureSeconds = now;
            }
            else
            {
            if (_sparsePosition >= _sparseSchedule.points.Length) return;
            SparsePoint point = _sparseSchedule.points[_sparsePosition];
            if (routeMs < point.at_ms) return;
            if (routeMs - point.at_ms > 350.0)
            {
                File.AppendAllText(Path.Combine(_outputDirectory, "capture_missed.jsonl"),
                    "{\"sample_at_ms\":" + point.at_ms.ToString(CultureInfo.InvariantCulture) +
                    ",\"actual_route_ms\":" + routeMs.ToString(CultureInfo.InvariantCulture) + "}\n");
                _sparsePosition++;
                return;
            }
            if (_endpointSettleGuards != null)
            {
                foreach (EndpointSettleGuard guard in _endpointSettleGuards.endpoints)
                {
                    if (Array.IndexOf(point.capture_ids, guard.capture_id) < 0) continue;
                    double completed = _inputDriver == null ? -1.0 : _inputDriver.CompletedActionMs(guard.action_id);
                    if (completed < 0 || elapsed * 1000.0 < completed + guard.stable_after_ms) return;
                }
            }
            _activeSampleMs = point.at_ms;
            _scheduledLagMs = routeMs - point.at_ms;
            _activeCaptureIds = point.capture_ids;
            _sparsePosition++;
            _nextCaptureSeconds = now;
            }
        }
        if (now < _nextCaptureSeconds || _capturePending)
            return;
        int missed = Math.Max(0, (int)Math.Floor((now - _nextCaptureSeconds) / interval));
        _skippedSamplingSlots += missed;
        _nextCaptureSeconds += (missed + 1) * interval;
        _lastCaptureSeconds = now;
        _capturePending = true;
        _captureRequestSeconds = now;
        if (GraphicsBatchCapture)
        {
            try { CaptureBatchView(); }
            catch (Exception exception) { Errors.Add("native background capture failed: " + exception); EditorApplication.isPlaying = false; }
            finally { _capturePending = false; }
            return;
        }
        _frameTap.Request(() => { _captureReadSeconds = EditorApplication.timeSinceStartup; }, (shot, error) => {
            _capturePending = false;
            if (error != null) { Errors.Add("frame capture failed: " + error); return; }
            CaptureFrame(shot, _captureReadSeconds - _takeStartSeconds);
        });
    }

    private static void CaptureFrame(Texture2D shot, double elapsedSeconds)
    {
        try
        {
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
            if (_activeSampleMs < 0 && _activeCaptureIds != null && _activeCaptureIds.Length == 1
                && _activeCaptureIds[0].StartsWith("event/", StringComparison.Ordinal))
            {   // event-triggered frame: own folder + index, outside the scheduled frame audit and counters
                int n = EventFrames.NextNumber();
                byte[] epng = shot.EncodeToPNG();
                UnityEngine.Object.Destroy(shot);
                Directory.CreateDirectory(Path.Combine(_outputDirectory, "event_frames"));
                string erel = "event_frames/e" + n.ToString("00000") + ".png";
                File.WriteAllBytes(Path.Combine(_outputDirectory, erel), epng);
                File.AppendAllText(Path.Combine(_outputDirectory, "event_frame_index.jsonl"),
                    "{\"frame_id\":\"FRAME:E" + n.ToString("00000") + "\",\"path\":\"" + erel + "\",\"engine\":\"unity3d\"," +
                    "\"t_ms\":" + ((int)Math.Round(elapsedSeconds * 1000)).ToString(CultureInfo.InvariantCulture) +
                    ",\"sample_at_ms\":-1,\"capture_ids\":[" + JsonEscape(_activeCaptureIds[0]) + "],\"trigger\":\"game_log_line\"}\n",
                    new UTF8Encoding(false));
                _activeCaptureIds = new string[0];
                return;
            }
            if (_inputDriver != null && _inputReadyElapsedSeconds >= 0) _inputDriver.InputReady(_lastCaptureWidth, _lastCaptureHeight);
            int frameNumber = _frameCount + 1;
            byte[] png = shot.EncodeToPNG();
            UnityEngine.Object.Destroy(shot);
            string path = Path.Combine(
                _outputDirectory, "frames", $"f{frameNumber:00000}.png");
            File.WriteAllBytes(path, png);
            double completedMs = (EditorApplication.timeSinceStartup - _takeStartSeconds) * 1000;
            string rel = "frames/f" + frameNumber.ToString("00000") + ".png";
            File.AppendAllText(Path.Combine(_outputDirectory, "frame_index.jsonl"),
                "{\"frame_id\":\"FRAME:" + frameNumber.ToString("00000") + "\",\"path\":\"" + rel +
                "\",\"raw_path\":\"" + rel + "\",\"source_path\":\"" + rel +
                "\",\"delivered_path\":null,\"delivery_status\":\"pending_manifest\",\"capture_status\":\"captured\"," +
                "\"engine\":\"unity3d\",\"window\":\"GameView\",\"viewport\":[" + _lastCaptureWidth + "," + _lastCaptureHeight + "]," +
                "\"timestamp_ms\":" + ((int)Math.Round(elapsedSeconds * 1000)).ToString(CultureInfo.InvariantCulture) +
                ",\"t_ms\":" + ((int)Math.Round(elapsedSeconds * 1000)).ToString(CultureInfo.InvariantCulture) +
                ",\"capture_end_t_ms\":" + ((int)Math.Round(completedMs)).ToString(CultureInfo.InvariantCulture) +
                ",\"video_t_ms\":" + ((int)Math.Round((frameNumber-1) * 1000.0 / _fps)).ToString(CultureInfo.InvariantCulture) +
                (_sparseSchedule == null ? "" : ",\"sample_at_ms\":" + _activeSampleMs.ToString(CultureInfo.InvariantCulture) +
                 ",\"capture_ids\":[" + string.Join(",", Array.ConvertAll(_activeCaptureIds, JsonEscape)) + "]") +
                ",\"clock\":\"recorder_session_monotonic\"}\n", new UTF8Encoding(false));
            _frameCount = frameNumber;
            _lastCaptureElapsedSeconds = elapsedSeconds;
            CaptureTimesMs.Add(elapsedSeconds * 1000.0);
            ScreenshotDurationsMs.Add(Math.Max(0.0, completedMs - elapsedSeconds * 1000.0));
            // State is observed after screenshot completion; retain its own time.
            if (_sparseSchedule == null) CaptureStateSnapshot(_frameCount, EditorApplication.timeSinceStartup - _takeStartSeconds);
            WriteInputFocus();
            if (_inputReadyElapsedSeconds < 0.0)
            {
                if (File.Exists(Path.Combine(_outputDirectory, "functional_observer_contract.json"))
                    && !WriteFunctionalObserverReadiness())
                {
                    Errors.Add("HARNESS_ERROR: required functional snapshot unavailable before input; generic component properties are insufficient");
                    FinishTake();
                    EditorApplication.isPlaying = false;
                    return;
                }
                _inputReadyElapsedSeconds = EditorApplication.timeSinceStartup - _takeStartSeconds;
                // Opt-in state entry (state-conditioned evaluation): the game's own methods / fields, called
                // through reflection before any player input. Results go to state_entry_result.json.
                try { StateEntry.Run(Environment.GetEnvironmentVariable("GAMEFACTORY_UNITY_STATE_ENTRY"), _outputDirectory,
                                     (EditorApplication.timeSinceStartup - _takeStartSeconds) * 1000.0); }
                catch (Exception exception) { Errors.Add("state entry failed: " + exception.Message); }
                if (_inputDriver != null) _inputDriver.InputReady(_lastCaptureWidth, _lastCaptureHeight);
                WritePlayStartedMarker();
            }
        }
        catch (Exception exception)
        {
            Errors.Add("frame capture failed: " + exception.Message);
        }
    }

    private static void CaptureStateSnapshot(int frame, double elapsedSeconds)
    {
        bool hasProviders = _providers != null && _providers.Count > 0;
        bool hasAdapters = _stateAdapters != null && _stateAdapters.Count > 0;

        // legacy privileged diagnostics channel (GetStateSnapshot providers):
        // kept byte-compatible for existing consumers
        if (hasProviders)
        {
            var builder = new StringBuilder();
            builder.Append("{\"frame\":").Append(frame.ToString(CultureInfo.InvariantCulture));
            builder.Append(",\"t_sec\":")
                .Append(elapsedSeconds.ToString("0.###", CultureInfo.InvariantCulture));
            builder.Append(",\"state\":{");
            bool firstProvider = true;
            foreach (var provider in _providers)
            {
                if (!ProviderAlive(provider)) continue;
                try
                {
                    object value = ReadProviderSnapshot(provider);
                    if (value == null) continue;
                    if (!firstProvider) builder.Append(",");
                    firstProvider = false;
                    builder.Append(JsonEscape(provider.Name)).Append(":");
                    WriteJsonValue(builder, value);
                    _snapshotCount += 1;
                }
                catch (Exception exception)
                {
                    RecordWarning("state snapshot failed for " + provider.Name + ": " + exception);
                }
            }
            builder.Append("}}");
            File.AppendAllText(Path.Combine(_outputDirectory, "diagnostics.jsonl"),
                builder + "\n", new UTF8Encoding(false));
        }

        if (!hasProviders && !hasAdapters) return;

        // standard state_trace.jsonl row: session-relative ms, the same
        // monotonic take clock the host client stamps actions with
        var trace = new StringBuilder();
        trace.Append("{\"t_ms\":")
            .Append(((int)Math.Round(elapsedSeconds * 1000.0))
                .ToString(CultureInfo.InvariantCulture));
        trace.Append(",\"state\":{");
        bool first = true;
        foreach (var provider in _providers ?? new List<SnapshotProvider>())
        {
            if (!ProviderAlive(provider)) continue;
            try
            {
                object value = ReadProviderSnapshot(provider);
                if (value == null) continue;
                if (!first) trace.Append(",");
                first = false;
                trace.Append(JsonEscape(provider.Name)).Append(":");
                WriteJsonValue(trace, value);
            }
            catch (Exception exception)
            {
                RecordWarning("state snapshot failed for " + provider.Name + ": " + exception);
            }
        }
        if (hasAdapters) WriteAdapterState(trace, ref first);
        trace.Append("}}");
        File.AppendAllText(_stateTracePath, trace + "\n", new UTF8Encoding(false));
        _stateTraceRows += 1;
    }

    /// Append the public scalar runtime surface of every discovered runtime
    /// adapter (components exposing runtime events) as state fields.
    private static void WriteAdapterState(StringBuilder builder, ref bool first)
    {
        var seen = new HashSet<object>();
        foreach (Component adapter in _stateAdapters)
        {
            if (adapter == null || !seen.Add(adapter)) continue;
            Type type = adapter.GetType();
            string sourceName = type.FullName + "@" + adapter.GetInstanceID().ToString(CultureInfo.InvariantCulture);
            bool explicitReadOnlySource = false;
            foreach (SnapshotProvider provider in _providers ?? new List<SnapshotProvider>())
            {
                if (!object.ReferenceEquals(provider.Source, adapter)) continue;
                sourceName = provider.Name;
                if (provider.PublicAutoProperties) explicitReadOnlySource = true;
            }
            foreach (MemberInfo member in type.GetMembers(
                         BindingFlags.Public | BindingFlags.Instance))
            {
                object value;
                if (member is FieldInfo field)
                {
                    if (!IsScalarRuntimeType(field.FieldType)) continue;
                    value = field.GetValue(adapter);
                }
                else if (member is PropertyInfo property
                         && property.CanRead && property.GetIndexParameters().Length == 0)
                {
                    // v4 sources are observed only through reviewed backing-field
                    // paths. The legacy diagnostic channel must not execute an
                    // unrelated authored getter on that same component.
                    if (explicitReadOnlySource) continue;
                    if (!IsScalarRuntimeType(property.PropertyType)) continue;
                    try { value = property.GetValue(adapter, null); }
                    catch { continue; }  // getter with side conditions is not evidence
                }
                else continue;
                if (!first) builder.Append(",");
                first = false;
                builder.Append(JsonEscape(sourceName + "." + member.Name)).Append(":");
                WriteJsonValue(builder, value);
            }
        }
    }

    private static bool IsScalarRuntimeType(Type type)
    {
        if (type.IsEnum) return true;
        if (type == typeof(float) || type == typeof(int) || type == typeof(bool)
            || type == typeof(string)) return true;
        if (type == typeof(Vector2) || type == typeof(Vector3) || type == typeof(Vector4)) return true;
        return false;
    }

    [Serializable]
    private sealed class PublicFieldPath
    {
        public string name;
        public string path;
        public int[] auto_property_segments;
    }

    private static object ReadProviderSnapshot(SnapshotProvider provider)
    {
        if (provider.PublicFields == null) return provider.Method.Invoke(provider.Source, null);
        var result = new Dictionary<string, object>();
        foreach (PublicFieldPath binding in provider.PublicFields)
        {
            object value = provider.Source;
            string[] segments = binding.path.Split('.');
            for (int index = 0; index < segments.Length; index++)
            {
                if (value == null) throw new InvalidOperationException("Public member path is null: " + binding.path);
                string segment = segments[index];
                bool autoProperty = provider.PublicAutoProperties && binding.auto_property_segments != null
                    && Array.IndexOf(binding.auto_property_segments, index) >= 0;
                if (autoProperty)
                {
                    FieldInfo backing;
                    MethodInfo getter;
                    value = provider.MutableAutoProperties
                        ? ReadPublicVerifiedAutoProperty(value, segment, true, out backing, out getter)
                        : ReadPublicReadonlyAutoProperty(value, segment, out backing, out getter);
                    WriteAutoPropertyBinding(provider, binding.path, index, backing, getter);
                }
                else
                {
                    FieldInfo field = value.GetType().GetField(segment, BindingFlags.Public | BindingFlags.Instance);
                    if (field == null) throw new InvalidOperationException("Public field unavailable: " + binding.path);
                    value = field.GetValue(value);
                }
            }
            result.Add(binding.name, value);
        }
        return result;
    }

    private static void WriteAutoPropertyBinding(SnapshotProvider provider, string path, int index, FieldInfo backing, MethodInfo getter)
    {
                    string bindingKey = path + ":" + index;
                    if (provider.AutoPropertyBindings.Add(bindingKey))
                    {
                        var row = new StringBuilder();
                        row.Append(provider.MutableAutoProperties ? "{\"schema\":\"unity-public-auto-property-binding.v2\",\"source_key\":" : "{\"schema\":\"unity-public-auto-property-binding.v1\",\"source_key\":")
                            .Append(JsonEscape(provider.Name)).Append(",\"provider_type\":")
                            .Append(JsonEscape(provider.Source.GetType().FullName)).Append(",\"path\":")
                            .Append(JsonEscape(path)).Append(",\"segment_index\":").Append(index)
                            .Append(",\"declaring_type\":").Append(JsonEscape(backing.DeclaringType.FullName))
                            .Append(",\"property\":").Append(JsonEscape(getter.Name.Substring(4)))
                            .Append(",\"backing_field\":").Append(JsonEscape(backing.Name))
                            .Append(",\"getter_il_base64\":").Append(JsonEscape(Convert.ToBase64String(getter.GetMethodBody().GetILAsByteArray())))
                            .Append(provider.MutableAutoProperties
                                ? ",\"getter_invoked\":false,\"auto_property_verified\":true,\"setter_invoked\":false,\"setter_present\":" + (getter.DeclaringType.GetProperty(getter.Name.Substring(4)).GetSetMethod(true) != null ? "true" : "false") + ",\"backing_readonly\":" + (backing.IsInitOnly ? "true" : "false") + ",\"setter_il_base64\":" + JsonEscape(getter.DeclaringType.GetProperty(getter.Name.Substring(4)).GetSetMethod(true) == null ? "" : Convert.ToBase64String(getter.DeclaringType.GetProperty(getter.Name.Substring(4)).GetSetMethod(true).GetMethodBody().GetILAsByteArray())) + "}"
                                : ",\"getter_invoked\":false,\"readonly_auto_property_verified\":true}");
                        File.AppendAllText(Path.Combine(_outputDirectory,"public_auto_property_bindings.jsonl"), row + "\n", new UTF8Encoding(false));
                    }
    }

    // A bound public get-only auto-property is observed through its compiler backing
    // field after verifying the exact getter IL. Never execute authored getter code.
    private static object ReadPublicReadonlyAutoProperty(object source, string name,
        out FieldInfo backing, out MethodInfo getter)
    {
        PropertyInfo property = source.GetType().GetProperty(name, BindingFlags.Public | BindingFlags.Instance);
        getter = property == null ? null : property.GetGetMethod(false);
        backing = null;
        if (property == null || getter == null || getter.IsStatic || getter.IsVirtual
            || property.GetIndexParameters().Length != 0 || property.GetSetMethod(true) != null
            || !getter.IsDefined(typeof(System.Runtime.CompilerServices.CompilerGeneratedAttribute), false))
            throw new InvalidOperationException("Not a public get-only auto-property: " + name);
        backing = property.DeclaringType.GetField("<" + name + ">k__BackingField",
            BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly);
        byte[] il = getter.GetMethodBody() == null ? null : getter.GetMethodBody().GetILAsByteArray();
        // ldarg.0; ldfld <metadata token>; ret. Any computation/branch/call is rejected.
        if (backing == null || !backing.IsInitOnly || backing.FieldType != property.PropertyType
            || !backing.IsDefined(typeof(System.Runtime.CompilerServices.CompilerGeneratedAttribute), false)
            || il == null || il.Length != 7 || il[0] != 0x02 || il[1] != 0x7b || il[6] != 0x2a
            || getter.Module.ResolveField(BitConverter.ToInt32(il, 2)) != backing)
            throw new InvalidOperationException("Auto-property backing/getter IL unavailable: " + name);
        return backing.GetValue(source);
    }

    private static object ReadPublicVerifiedAutoProperty(object source, string name, bool allowSetter,
        out FieldInfo backing, out MethodInfo getter)
    {
        PropertyInfo property = source.GetType().GetProperty(name, BindingFlags.Public | BindingFlags.Instance);
        getter = property == null ? null : property.GetGetMethod(false);
        MethodInfo setter = property == null ? null : property.GetSetMethod(true);
        backing = null;
        var generated = typeof(System.Runtime.CompilerServices.CompilerGeneratedAttribute);
        if (property == null || getter == null || getter.IsStatic || getter.IsVirtual
            || property.GetIndexParameters().Length != 0 || !getter.IsDefined(generated, false)
            || (!allowSetter && setter != null))
            throw new InvalidOperationException("Not a public verified auto-property: " + name);
        backing = property.DeclaringType.GetField("<" + name + ">k__BackingField",
            BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly);
        byte[] il = getter.GetMethodBody() == null ? null : getter.GetMethodBody().GetILAsByteArray();
        if (backing == null || backing.IsStatic || backing.FieldType != property.PropertyType
            || !backing.IsDefined(generated, false)
            || il == null || il.Length != 7 || il[0] != 0x02 || il[1] != 0x7b || il[6] != 0x2a
            || getter.Module.ResolveField(BitConverter.ToInt32(il, 2)) != backing)
            throw new InvalidOperationException("Auto-property getter/backing IL unavailable: " + name);
        if (setter == null)
        {
            if (!backing.IsInitOnly) throw new InvalidOperationException("Get-only backing must be readonly: " + name);
        }
        else
        {
            byte[] write = setter.GetMethodBody() == null ? null : setter.GetMethodBody().GetILAsByteArray();
            // ldarg.0; ldarg.1; stfld <same metadata token>; ret. Never execute it.
            if (backing.IsInitOnly || setter.IsStatic || setter.IsVirtual || !setter.IsDefined(generated, false)
                || write == null || write.Length != 8 || write[0] != 0x02 || write[1] != 0x03
                || write[2] != 0x7d || write[7] != 0x2a
                || setter.Module.ResolveField(BitConverter.ToInt32(write, 3)) != backing)
                throw new InvalidOperationException("Auto-property setter/backing IL unavailable: " + name);
        }
        return backing.GetValue(source);
    }

    [Serializable]
    private sealed class PublicEventPath
    {
        public string path;
        public string event_name;
        public int[] auto_property_segments;
    }

    // Resolve public instance fields only. Never invoke properties or methods.
    private static object ReadPublicEventTarget(object source, string path, int[] autoPropertySegments = null, SnapshotProvider provider = null)
    {
        object value = source;
        string[] segments = path.Split('.');
        for (int index = 0; index < segments.Length; index++)
        {
            if (value == null) throw new InvalidOperationException("Public event path is null: " + path);
            string segment = segments[index];
            if (autoPropertySegments != null && Array.IndexOf(autoPropertySegments, index) >= 0)
            {
                FieldInfo backing; MethodInfo getter;
                value = ReadPublicVerifiedAutoProperty(value, segment, true, out backing, out getter);
                if (provider != null) WriteAutoPropertyBinding(provider, path, index, backing, getter);
                continue;
            }
            FieldInfo field = value.GetType().GetField(segment, BindingFlags.Public | BindingFlags.Instance);
            if (field == null) throw new InvalidOperationException("Public event field unavailable: " + path);
            value = field.GetValue(value);
        }
        if (value == null) throw new InvalidOperationException("Public event target is null: " + path);
        return value;
    }

    private static FunctionalObserverContract ReadObserverContract()
    {
        string path = Path.Combine(_outputDirectory, "functional_observer_contract.json");
        return File.Exists(path) ? JsonUtility.FromJson<FunctionalObserverContract>(File.ReadAllText(path)) : null;
    }

    private static bool ExplicitEventsSubscribed(FunctionalObserverContract contract, SnapshotProvider provider,
        List<RuntimeEventSubscription> subscriptions)
    {
        foreach (PublicEventPath binding in contract.public_event_paths)
        {
            object target = ReadPublicEventTarget(provider.Source, binding.path, provider.MutableAutoProperties ? binding.auto_property_segments : null, provider.MutableAutoProperties ? provider : null);
            if (!subscriptions.Exists(subscription => object.ReferenceEquals(subscription.Source, target)
                    && subscription.Event.Name == binding.event_name)) return false;
        }
        return true;
    }

    [Serializable]
    private sealed class FunctionalObserverContract
    {
        public string schema;
        public string provider_type;
        public PublicFieldPath[] public_field_paths;
        public string[] required_fields;
        public PublicEventPath[] public_event_paths;
        public bool require_events;
    }

    private static bool WriteFunctionalObserverReadiness()
    {
        var keys = new List<string>();
        FunctionalObserverContract contract = JsonUtility.FromJson<FunctionalObserverContract>(
            File.ReadAllText(Path.Combine(_outputDirectory, "functional_observer_contract.json")));
        foreach (SnapshotProvider provider in _providers ?? new List<SnapshotProvider>())
        {
            if (!ProviderAlive(provider) || provider.Source.GetType().FullName != contract.provider_type) continue;
            if ((contract.public_field_paths != null) != (provider.PublicFields != null)) continue;
            try
            {
                object value = ReadProviderSnapshot(provider);
                if (value == null) continue;
                bool complete = true;
                foreach (string name in contract.required_fields)
                    if (value is IDictionary dictionary ? !dictionary.Contains(name)
                        : value.GetType().GetField(name, BindingFlags.Public | BindingFlags.Instance) == null)
                        complete = false;
                if (contract.require_events)
                {
                    var subscriptions = _eventSubscriptions ?? new List<RuntimeEventSubscription>();
                    if (contract.public_event_paths != null
                        ? !ExplicitEventsSubscribed(contract, provider, subscriptions)
                        : !subscriptions.Exists(subscription => object.ReferenceEquals(subscription.Source, provider.Source)))
                        complete = false;
                }
                if (complete) keys.Add(JsonEscape(provider.Name));
            }
            catch (Exception exception) { RecordWarning("functional observer readiness: " + exception); }
        }
        // Multiple independent runtimes need an explicit disambiguated contract;
        // never silently pick one by component search order.
        bool available = keys.Count == 1;
        File.WriteAllText(Path.Combine(_outputDirectory, "functional_observer_readiness.json"),
            "{\"schema\":\"unity-functional-observer-readiness.v1\",\"available\":" + (available ? "true" : "false") +
            ",\"t_ms\":" + ((EditorApplication.timeSinceStartup - _takeStartSeconds) * 1000).ToString("0.###", CultureInfo.InvariantCulture) +
            ",\"source_keys\":[" + string.Join(",", keys) + "],\"gameplay_verified\":false}", new UTF8Encoding(false));
        return available;
    }

    private static MethodInfo SnapshotMethod(Type type)
    {
        MethodInfo method = type.GetMethod("GetStateSnapshot", BindingFlags.Public | BindingFlags.Instance,
            binder: null, types: Type.EmptyTypes, modifiers: null);
        return method != null && method.ReturnType != typeof(void) && !method.ContainsGenericParameters ? method : null;
    }

    private static void AddSnapshotProvider(List<SnapshotProvider> providers, object source, Component owner, string memberPath)
    {
        MethodInfo method = SnapshotMethod(source.GetType());
        if (method == null) return;
        // Reference identity, not game-defined Equals(): shared UI references
        // must not duplicate snapshots/events, distinct runtimes stay distinct.
        foreach (SnapshotProvider previous in providers)
            if (previous.PublicFields == null && object.ReferenceEquals(previous.Source, source)) return;
        providers.Add(new SnapshotProvider { Source = source, Owner = owner,
            MemberPath = memberPath, Method = method, Name = source.GetType().Name });
    }

    private static bool ProviderAlive(SnapshotProvider provider)
    {
        if (provider.Owner == null) return false;
        if (provider.MemberPath.Length == 0) return true;
        FieldInfo field = provider.Owner.GetType().GetField(provider.MemberPath, BindingFlags.Public | BindingFlags.Instance);
        return field != null && object.ReferenceEquals(field.GetValue(provider.Owner), provider.Source);
    }

    private static List<SnapshotProvider> FindSnapshotProviders()
    {
        var providers = new List<SnapshotProvider>();
        // One hop through PUBLIC FIELDS only: no arbitrary getters, private
        // traversal, static registries or gameplay invocation. A nested target
        // must already implement the public read-only snapshot contract.
        var owners = UnityEngine.Object.FindObjectsOfType<MonoBehaviour>(true);
        Array.Sort(owners, (left, right) => left.GetInstanceID().CompareTo(right.GetInstanceID()));
        string contractPath = Path.Combine(_outputDirectory, "functional_observer_contract.json");
        FunctionalObserverContract explicitContract = File.Exists(contractPath)
            ? JsonUtility.FromJson<FunctionalObserverContract>(File.ReadAllText(contractPath)) : null;
        foreach (MonoBehaviour behaviour in owners)
        {
            // Explicit public field paths or verified get-only auto-property backing.
            // No property getter, static registry or gameplay method invocation.
            if (explicitContract != null && (explicitContract.schema == "unity-functional-observer-contract.v2.public-fields"
                    || explicitContract.schema == "unity-functional-observer-contract.v3.public-events"
                    || explicitContract.schema == "unity-functional-observer-contract.v4.public-auto-properties"
                    || explicitContract.schema == "unity-functional-observer-contract.v5.verified-auto-properties")
                && behaviour.GetType().FullName == explicitContract.provider_type
                && explicitContract.public_field_paths != null)
                providers.Add(new SnapshotProvider { Source = behaviour, Owner = behaviour,
                    PublicFields = explicitContract.public_field_paths,
                    PublicAutoProperties = explicitContract.schema == "unity-functional-observer-contract.v4.public-auto-properties" || explicitContract.schema == "unity-functional-observer-contract.v5.verified-auto-properties",
                    MutableAutoProperties = explicitContract.schema == "unity-functional-observer-contract.v5.verified-auto-properties",
                    Name = behaviour.GetType().Name + ".public_fields" });
            AddSnapshotProvider(providers, behaviour, behaviour, "");
            var fields = behaviour.GetType().GetFields(BindingFlags.Public | BindingFlags.Instance);
            Array.Sort(fields, (left, right) => string.CompareOrdinal(left.Name, right.Name));
            foreach (FieldInfo field in fields)
            {
                if (SnapshotMethod(field.FieldType) == null) continue;
                object target = field.GetValue(behaviour);
                if (target == null || target is UnityEngine.Object) continue;
                AddSnapshotProvider(providers, target, behaviour, field.Name);
            }
        }
        var groups = new Dictionary<string, List<SnapshotProvider>>();
        foreach (SnapshotProvider provider in providers)
        {
            if (!groups.ContainsKey(provider.Name)) groups[provider.Name] = new List<SnapshotProvider>();
            groups[provider.Name].Add(provider);
        }
        var sources = new StringBuilder();
        sources.Append("{\"schema\":\"whitebox-state-source-bindings.v1\",\"sources\":[");
        bool firstSource = true;
        foreach (var group in groups)
        {
            Component canonical = null;
            if (group.Value.Count > 1)
            {
                Type sourceType = group.Value[0].Source.GetType();
                bool sameType = group.Value.TrueForAll(provider => provider.Source.GetType() == sourceType);
                PropertyInfo active = sourceType.GetProperty("Active", BindingFlags.Public | BindingFlags.Static);
                if (sameType && active != null && active.CanRead && active.GetIndexParameters().Length == 0
                    && typeof(Component).IsAssignableFrom(active.PropertyType))
                {
                    try { canonical = active.GetValue(null, null) as Component; }
                    catch { canonical = null; }
                }
            }
            foreach (SnapshotProvider provider in group.Value)
            {
                Component component = provider.Owner;
                bool bound = group.Value.Count == 1 || (provider.MemberPath.Length == 0 && component == canonical);
                provider.Name = bound ? group.Key : provider.Source.GetType().FullName + "@" + component.GetInstanceID().ToString(CultureInfo.InvariantCulture) + (provider.MemberPath.Length == 0 ? "" : "." + provider.MemberPath);
                if (!firstSource) sources.Append(",");
                firstSource = false;
                string hierarchy = component.name;
                for (Transform parent = component.transform.parent; parent != null; parent = parent.parent)
                    hierarchy = parent.name + "/" + hierarchy;
                sources.Append("{\"key\":").Append(JsonEscape(provider.Name));
                sources.Append(",\"type\":").Append(JsonEscape(provider.Source.GetType().FullName));
                sources.Append(",\"instance_id\":").Append(component.GetInstanceID().ToString(CultureInfo.InvariantCulture));
                sources.Append(",\"owner_type\":").Append(JsonEscape(component.GetType().FullName));
                sources.Append(",\"member_path\":").Append(JsonEscape(provider.MemberPath));
                sources.Append(",\"scene\":").Append(JsonEscape(component.gameObject.scene.path));
                sources.Append(",\"hierarchy\":").Append(JsonEscape(hierarchy));
                sources.Append(",\"binding\":").Append(JsonEscape(provider.PublicFields != null ? (provider.PublicAutoProperties ? "explicit-public-auto-property-paths" : "explicit-public-field-paths") : provider.MemberPath.Length > 0 ? "public-field-snapshot" : group.Value.Count == 1 ? "single-instance" : bound ? "public-static-Active" : "separate-instance"));
                sources.Append("}");
            }
        }
        sources.Append("]}");
        File.AppendAllText(Path.Combine(_outputDirectory, "state_source_bindings.jsonl"), sources + "\n", new UTF8Encoding(false));
        return providers;
    }

    // ── runtime event observation (generic, contract-driven) ───────────────
    //
    // Runtime adapters are discovered by shape, never by game id: any active
    // component exposing a public instance event whose delegate is Action or
    // Action<T> is a runtime adapter. Its events are recorded to
    // event_trace.jsonl with {t_ms, event, payload}; the event name prefers
    // the payload's own `type` field (string or enum) and falls back to the
    // C# event name. Adapters without events are not touched.

    private static readonly List<Component> _stateAdapters = new List<Component>();

    private sealed class ReferenceIdentityComparer : IEqualityComparer<object>
    {
        public static readonly ReferenceIdentityComparer Instance = new ReferenceIdentityComparer();
        public new bool Equals(object x, object y) { return object.ReferenceEquals(x, y); }
        public int GetHashCode(object value) { return System.Runtime.CompilerServices.RuntimeHelpers.GetHashCode(value); }
    }

    private static List<RuntimeEventSubscription> SubscribeRuntimeEvents()
    {
        var subscriptions = new List<RuntimeEventSubscription>();
        _stateAdapters.Clear();
        var seen = new HashSet<object>();
        var targets = new List<object>();
        FunctionalObserverContract contract = ReadObserverContract();
        // Explicit nested sources need no GetStateSnapshot method. Their public
        // event callbacks retain original names/payloads and normal cleanup.
        var explicitKeys = new Dictionary<object, string>(ReferenceIdentityComparer.Instance);
        foreach (SnapshotProvider provider in _providers ?? new List<SnapshotProvider>())
        {
            if (!ProviderAlive(provider) || contract == null || contract.public_event_paths == null
                    || provider.PublicFields == null || provider.Source.GetType().FullName != contract.provider_type) continue;
            foreach (PublicEventPath binding in contract.public_event_paths)
            {
                try
                {
                    object target = ReadPublicEventTarget(provider.Source, binding.path, provider.MutableAutoProperties ? binding.auto_property_segments : null, provider.MutableAutoProperties ? provider : null);
                    targets.Add(target);
                    if (!explicitKeys.ContainsKey(target)) explicitKeys[target] = provider.Name + "." + binding.path;
                }
                catch (Exception exception) { RecordWarning("public event path: " + exception); }
            }
        }
        targets.AddRange(UnityEngine.Object.FindObjectsOfType<MonoBehaviour>(true));
        foreach (SnapshotProvider provider in _providers ?? new List<SnapshotProvider>())
            if (ProviderAlive(provider)) targets.Add(provider.Source);
        var subscribedSources = new List<object>();
        foreach (object behaviour in targets)
        {
            if (subscribedSources.Exists(previous => object.ReferenceEquals(previous, behaviour))) continue;
            subscribedSources.Add(behaviour);
            string sourceKey = behaviour.GetType().FullName;
            foreach (SnapshotProvider provider in _providers ?? new List<SnapshotProvider>())
                if (object.ReferenceEquals(provider.Source, behaviour)) { sourceKey = provider.Name; break; }
            if (explicitKeys.TryGetValue(behaviour, out string explicitKey)) sourceKey = explicitKey;
            foreach (EventInfo info in behaviour.GetType().GetEvents(
                         BindingFlags.Public | BindingFlags.Instance))
            {
                Type handlerType = info.EventHandlerType;
                bool isAction = handlerType == typeof(Action);
                bool isActionOfPayload = handlerType.IsGenericType
                    && handlerType.GetGenericTypeDefinition() == typeof(Action<>);
                bool isNamedAction = handlerType.IsGenericType
                    && handlerType.GetGenericTypeDefinition() == typeof(Action<,>)
                    && handlerType.GetGenericArguments()[0] == typeof(string);
                if (!isAction && !isActionOfPayload && !isNamedAction) continue;
                Delegate handler;
                try { handler = CreateSinkDelegate(handlerType, info.Name, sourceKey); }
                catch (Exception exception)
                {
                    RecordWarning("cannot subscribe " + info.Name + ": " + exception.Message);
                    continue;
                }
                try { info.AddEventHandler(behaviour, handler); }
                catch (Exception exception)
                {
                    RecordWarning("cannot subscribe " + info.Name + ": " + exception.Message);
                    continue;
                }
                if (behaviour is Component component && seen.Add(behaviour)) _stateAdapters.Add(component);
                subscriptions.Add(new RuntimeEventSubscription
                {
                    Source = behaviour,
                    Event = info,
                    Handler = handler,
                    EventName = behaviour.GetType().Name + "." + info.Name,
                    SourceKey = sourceKey,
                    ExplicitPublicTarget = explicitKeys.ContainsKey(behaviour),
                });
            }
        }
        // Record actual subscriptions with their owning state provider. A
        // declaration alone never proves a source was connected.
        foreach (SnapshotProvider provider in _providers ?? new List<SnapshotProvider>())
        {
            if (!ProviderAlive(provider) || contract == null || contract.public_event_paths == null
                    || provider.PublicFields == null || provider.Source.GetType().FullName != contract.provider_type) continue;
            foreach (PublicEventPath binding in contract.public_event_paths)
            {
                try
                {
                    object target = ReadPublicEventTarget(provider.Source, binding.path, provider.MutableAutoProperties ? binding.auto_property_segments : null, provider.MutableAutoProperties ? provider : null);
                    foreach (RuntimeEventSubscription subscription in subscriptions)
                    {
                        if (!object.ReferenceEquals(subscription.Source, target) || subscription.Event.Name != binding.event_name) continue;
                        string hierarchy = provider.Owner.name;
                        for (Transform parent = provider.Owner.transform.parent; parent != null; parent = parent.parent)
                            hierarchy = parent.name + "/" + hierarchy;
                        File.AppendAllText(Path.Combine(_outputDirectory, "event_source_bindings.jsonl"),
                            "{\"schema\":\"whitebox-event-source-binding.v1\",\"provider_type\":" + JsonEscape(contract.provider_type) +
                            ",\"state_key\":" + JsonEscape(provider.Name) + ",\"source_key\":" + JsonEscape(subscription.SourceKey) +
                            ",\"source_type\":" + JsonEscape(target.GetType().FullName) + ",\"member_path\":" + JsonEscape(binding.path) +
                            ",\"event_name\":" + JsonEscape(binding.event_name) + ",\"hierarchy\":" + JsonEscape(hierarchy) +
                            ",\"owner_instance_id\":" + provider.Owner.GetInstanceID().ToString(CultureInfo.InvariantCulture) +
                            ",\"binding\":" + JsonEscape(provider.MutableAutoProperties ? "explicit-public-auto-property-event" : "explicit-public-field-event") + "}\n", new UTF8Encoding(false));
                    }
                }
                catch (Exception exception) { RecordWarning("public event binding: " + exception); }
            }
        }
        return subscriptions;
    }

    private static void UnsubscribeRuntimeEvents()
    {
        if (_eventSubscriptions == null) return;
        foreach (RuntimeEventSubscription subscription in _eventSubscriptions)
        {
            string error = null;
            try { subscription.Event.RemoveEventHandler(subscription.Source, subscription.Handler); }
            catch (Exception exception) { error = exception.ToString(); }
            if (subscription.ExplicitPublicTarget)
            {
                try
                {
                    File.AppendAllText(Path.Combine(_outputDirectory, "event_subscription_cleanup.jsonl"),
                        "{\"schema\":\"whitebox-event-subscription-cleanup.v1\",\"source_key\":" + JsonEscape(subscription.SourceKey) +
                        ",\"event_name\":" + JsonEscape(subscription.Event.Name) + ",\"removed\":" + (error == null ? "true" : "false") +
                        ",\"error\":" + JsonEscape(error) + "}\n", new UTF8Encoding(false));
                }
                catch (Exception exception) { RecordWarning("public event cleanup receipt: " + exception); }
            }
        }
        _eventSubscriptions = new List<RuntimeEventSubscription>();
    }

    /// Preserve Action, Action<T>, and named Action<string, T> runtime events.
    private static Delegate CreateSinkDelegate(Type handlerType, string eventName, string sourceKey)
    {
        Type[] arguments = handlerType.IsGenericType ? handlerType.GetGenericArguments() : Type.EmptyTypes;
        if (arguments.Length == 2)
        {
            ParameterExpression raisedName = Expression.Parameter(typeof(string), "eventName");
            ParameterExpression value = Expression.Parameter(arguments[1], "payload");
            MethodInfo namedSink = typeof(GameFactory3APlayTestRecorder).GetMethod(
                "OnNamedAdapterEvent", BindingFlags.NonPublic | BindingFlags.Static);
            return Expression.Lambda(handlerType, Expression.Call(namedSink,
                Expression.Constant(eventName), Expression.Constant(sourceKey), raisedName,
                Expression.Convert(value, typeof(object))), raisedName, value).Compile();
        }
        MethodInfo sink = typeof(GameFactory3APlayTestRecorder).GetMethod(
            "OnAdapterEvent", BindingFlags.NonPublic | BindingFlags.Static);
        ConstantExpression name = Expression.Constant(eventName);
        Expression payload;
        ParameterExpression parameter = null;
        if (handlerType == typeof(Action)) payload = Expression.Constant(null, typeof(object));
        else
        {
            parameter = Expression.Parameter(arguments[0], "payload");
            payload = Expression.Convert(parameter, typeof(object));
        }
        MethodCallExpression call = Expression.Call(sink, name, Expression.Constant(sourceKey), payload);
        return parameter == null
            ? Expression.Lambda(handlerType, call).Compile()
            : Expression.Lambda(handlerType, call, parameter).Compile();
    }

    private static void OnNamedAdapterEvent(string eventName, string sourceKey, string raisedName, object payload)
    {
        WriteAdapterEvent(eventName, sourceKey, payload, raisedName, true);
    }

    private static void OnAdapterEvent(string eventName, string sourceKey, object payload)
    {
        WriteAdapterEvent(eventName, sourceKey, payload, ExtractEventName(payload), false);
    }

    private static void WriteAdapterEvent(string eventName, string sourceKey, object payload, string raisedName, bool named)
    {
        if (_eventTracePath == null) return;
        string name = raisedName ?? eventName;
        var builder = new StringBuilder();
        builder.Append("{\"t_ms\":").Append(((int)Math.Round(
            (EditorApplication.timeSinceStartup - _takeStartSeconds) * 1000.0))
            .ToString(CultureInfo.InvariantCulture));
        builder.Append(",\"event\":").Append(JsonEscape(name));
        builder.Append(",\"source\":").Append(JsonEscape(sourceKey));
        if (named)
        {
            builder.Append(",\"declared_event\":").Append(JsonEscape(eventName));
            builder.Append(",\"name_argument\":");
            WriteJsonValue(builder, raisedName);
        }
        builder.Append(",\"clock\":\"recorder_session_monotonic\"");
        builder.Append(",\"payload\":");
        WriteJsonValue(builder, payload);
        builder.Append("}");
        try
        {
            File.AppendAllText(_eventTracePath, builder + "\n", new UTF8Encoding(false));
            _eventTraceRows += 1;
        }
        catch (Exception)
        {
            // a dropped event row is a capture gap, not a take failure
        }
    }

    /// The payload's own ``type`` field (string or enum), when present, is
    /// the event's real name; the C# event name is only the fallback.
    private static string ExtractEventName(object payload)
    {
        if (payload == null) return null;
        Type type = payload.GetType();
        foreach (FieldInfo field in type.GetFields(BindingFlags.Public | BindingFlags.Instance))
            if ((string.Equals(field.Name, "type", StringComparison.OrdinalIgnoreCase) || string.Equals(field.Name, "key", StringComparison.OrdinalIgnoreCase)))
            {
                object value = field.GetValue(payload);
                if (value is string text && text.Length > 0) return text;
                if (value != null && value.GetType().IsEnum) return value.ToString();
                return null;
            }
        foreach (PropertyInfo property in type.GetProperties(
                     BindingFlags.Public | BindingFlags.Instance))
            if (string.Equals(property.Name, "type", StringComparison.OrdinalIgnoreCase)
                && property.CanRead && property.GetIndexParameters().Length == 0)
            {
                try
                {
                    object value = property.GetValue(payload, null);
                    if (value is string text && text.Length > 0) return text;
                    if (value != null && value.GetType().IsEnum) return value.ToString();
                }
                catch { return null; }
                return null;
            }
        return null;
    }

    private static void FinishTake()
    {
        if (_finished) return;
        _finished = true;
        Application.logMessageReceived -= OnGameLog;
        try { if (_audioTap != null) _audioTap.Finish(); }
        catch (Exception exception) { Errors.Add("HARNESS_ERROR: audio cleanup: " + exception); }
        try { if (_inputDriver != null) _inputDriver.Finish(); }
        catch (Exception exception) { Errors.Add("HARNESS_ERROR: input cleanup: " + exception); }
        if (GraphicsBatchCapture) RestoreBatchView();
        EditorApplication.update -= CaptureTick;
        SceneManager.sceneLoaded -= OnObservedSceneLoaded;
        SceneManager.sceneUnloaded -= OnObservedSceneUnloaded;
        int recordedEventSubscriptions = _eventSubscriptions?.Count ?? 0;
        UnsubscribeRuntimeEvents();
        bool ok = _frameCount >= 2 && Errors.Count == 0;
        bool hasProviders = _providers != null && _providers.Count > 0;
        bool hasAdapters = _stateAdapters.Count > 0;
        bool hasEventSubscriptions = recordedEventSubscriptions > 0;
        double runtimeSeconds = Math.Max(0.0, EditorApplication.timeSinceStartup - _takeStartSeconds);
        var intervals = new List<double>();
        for (int i = 1; i < CaptureTimesMs.Count; i++)
            intervals.Add(CaptureTimesMs[i] - CaptureTimesMs[i - 1]);
        var report = new EditorReport
        {
            ok = ok,
            actual_runtime_seconds = runtimeSeconds,
            actual_fps = runtimeSeconds > 0.0 ? _frameCount / runtimeSeconds : 0.0,
            skipped_sampling_slots = _skippedSamplingSlots,
            sampling_intervals_ms = intervals,
            screenshot_durations_ms = new List<double>(ScreenshotDurationsMs),
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
            channels = new ChannelCoverage
            {
                states_available = hasProviders || hasAdapters,
                state_rows = _stateTraceRows,
                states_source = hasProviders
                    ? "GetStateSnapshot" + (hasAdapters ? "+adapter-properties" : "")
                    : (hasAdapters ? "adapter-properties" : ""),
                events_available = hasEventSubscriptions,
                event_rows = _eventTraceRows,
                event_subscriptions = recordedEventSubscriptions,
                events_capture_error = "",
                frames_available = _frameCount > 0,
            },
        };
        if (ok && _frameCount > 0)
        {
            // The Game view decides the actual capture resolution; report
            // what was captured rather than what was requested.
            report.viewport.Add(_lastCaptureWidth);
            report.viewport.Add(_lastCaptureHeight);
        }
        if (!ok && Errors.Count == 0)
            Errors.Add("visual capture incomplete: fewer than two real frames");
        if (!ok)
            File.WriteAllText(Path.Combine(_outputDirectory, "harness_error.json"),
                "{\"status\":\"HARNESS_ERROR\",\"phase\":\"capture\",\"reason\":\"visual capture incomplete; see editor report\"}");
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
        SceneManager.sceneLoaded -= OnObservedSceneLoaded;
        SceneManager.sceneUnloaded -= OnObservedSceneUnloaded;
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
            .Append(",\"recorder_elapsed_ms\":")
            .Append(((EditorApplication.timeSinceStartup - _takeStartSeconds) * 1000.0).ToString("0.###", CultureInfo.InvariantCulture))
            .Append(",\"input_transport\":\"").Append(_useInternalDriver ? "internal" : "system_events")
            .Append("\",\"input_ready\":").Append(BackgroundCapture ? "false" : "true")
            .Append(",\"background_render_ready\":").Append(BackgroundCapture ? "true" : "false")
            .Append(",\"experimental_background\":").Append(BackgroundCapture ? "true" : "false")
            .Append(",\"target_window\":\"GameView\",\"first_frame_id\":\"FRAME:00001\"}");
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
        builder.Append(",\"actual_runtime_seconds\":").Append(report.actual_runtime_seconds.ToString("0.###", CultureInfo.InvariantCulture));
        builder.Append(",\"actual_fps\":").Append(report.actual_fps.ToString("0.###", CultureInfo.InvariantCulture));
        builder.Append(",\"skipped_sampling_slots\":").Append(report.skipped_sampling_slots.ToString(CultureInfo.InvariantCulture));
        builder.Append(",\"clock\":\"EditorApplication.timeSinceStartup\"");
        builder.Append(",\"video_time_semantics\":\"video_t_ms=(frame_number-1)/fps; real time is t_ms, never frames/fps\"");
        builder.Append(",\"sampling_intervals_ms\":[");
        for (int i = 0; i < report.sampling_intervals_ms.Count; i++)
        {
            if (i > 0) builder.Append(",");
            builder.Append(report.sampling_intervals_ms[i].ToString("0.###", CultureInfo.InvariantCulture));
        }
        builder.Append("],\"screenshot_durations_ms\":[");
        for (int i = 0; i < report.screenshot_durations_ms.Count; i++)
        {
            if (i > 0) builder.Append(",");
            builder.Append(report.screenshot_durations_ms[i].ToString("0.###", CultureInfo.InvariantCulture));
        }
        builder.Append("]");
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
        builder.Append(",\"channels\":{");
        builder.Append("\"states_available\":").Append(report.channels.states_available ? "true" : "false");
        builder.Append(",\"state_rows\":").Append(report.channels.state_rows.ToString(CultureInfo.InvariantCulture));
        builder.Append(",\"states_source\":").Append(JsonEscape(report.channels.states_source));
        builder.Append(",\"events_available\":").Append(report.channels.events_available ? "true" : "false");
        builder.Append(",\"event_rows\":").Append(report.channels.event_rows.ToString(CultureInfo.InvariantCulture));
        builder.Append(",\"event_subscriptions\":").Append(report.channels.event_subscriptions.ToString(CultureInfo.InvariantCulture));
        builder.Append(",\"events_capture_error\":").Append(JsonEscape(report.channels.events_capture_error));
        builder.Append(",\"frames_available\":").Append(report.channels.frames_available ? "true" : "false");
        builder.Append("}");
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

    private static bool GraphicsBatchCapture
    {
        get { return Environment.GetEnvironmentVariable("GAMEFACTORY_UNITY_CAPTURE_POLICY") == "graphics_batch_render_v2"; }
    }
    private static RenderTexture _batchTarget;
    private static bool _batchViewConfigured;
    private static EditorWindow _batchView;
    private static object _batchSizeGroup, _batchOwnedSize;
    private static int _batchOriginalSelectedSize, _batchOriginalSizeCount;
    private static Vector2 _batchOriginalTargetSize;
    [Serializable]
    private sealed class BatchViewCleanup
    {
        public bool ok, custom_size_removed, selected_size_restored, target_size_restored, render_target_released;
        public int original_size_count, final_size_count;
        public List<string> errors = new List<string>();
    }
    private static void RestoreBatchView()
    {
        var report = new BatchViewCleanup { original_size_count = _batchOriginalSizeCount };
        try
        {
            if (_batchSizeGroup != null && _batchOwnedSize != null)
            {
                var groupType = _batchSizeGroup.GetType();
                int count = (int)groupType.GetMethod("GetTotalCount").Invoke(_batchSizeGroup, null);
                for (int index = count - 1; index >= 0; index--)
                {
                    object size = groupType.GetMethod("GetGameViewSize").Invoke(_batchSizeGroup, new object[] { index });
                    if (object.ReferenceEquals(size, _batchOwnedSize))
                        groupType.GetMethod("RemoveCustomSize").Invoke(_batchSizeGroup, new object[] { index });
                }
                report.final_size_count = (int)groupType.GetMethod("GetTotalCount").Invoke(_batchSizeGroup, null);
                report.custom_size_removed = report.final_size_count == _batchOriginalSizeCount;
            }
            else report.custom_size_removed = !_batchViewConfigured;
        }
        catch (Exception exception) { report.errors.Add("owned custom size removal: " + exception); }
        try
        {
            if (_batchView != null)
            {
                var selected = _batchView.GetType().GetProperty("selectedSizeIndex", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
                selected.SetValue(_batchView, _batchOriginalSelectedSize);
                report.selected_size_restored = (int)selected.GetValue(_batchView) == _batchOriginalSelectedSize;
                var playMode = typeof(EditorWindow).Assembly.GetType("UnityEditor.PlayModeView");
                var target = playMode.GetProperty("targetSize", BindingFlags.Instance | BindingFlags.NonPublic);
                target.SetValue(_batchView, _batchOriginalTargetSize);
                report.target_size_restored = (Vector2)target.GetValue(_batchView) == _batchOriginalTargetSize;
            }
            else report.selected_size_restored = report.target_size_restored = !_batchViewConfigured;
        }
        catch (Exception exception) { report.errors.Add("view size restoration: " + exception); }
        try
        {
            if (_batchTarget != null) { _batchTarget.Release(); UnityEngine.Object.DestroyImmediate(_batchTarget); _batchTarget = null; }
            report.render_target_released = _batchTarget == null;
        }
        catch (Exception exception) { report.errors.Add("render target release: " + exception); }
        report.ok = report.custom_size_removed && report.selected_size_restored && report.target_size_restored && report.render_target_released && report.errors.Count == 0;
        File.WriteAllText(Path.Combine(_outputDirectory, "background_view_cleanup.json"), JsonUtility.ToJson(report), new UTF8Encoding(false));
        if (!report.ok) Errors.Add("HARNESS_ERROR: background GameView restoration failed");
    }
    private static void ConfigureBatchView(EditorWindow view)
    {
        if (_batchViewConfigured) return;
        var assembly = typeof(EditorWindow).Assembly;
        var sizesType = assembly.GetType("UnityEditor.GameViewSizes");
        var sizes = sizesType.GetProperty("instance", BindingFlags.Public | BindingFlags.Static | BindingFlags.FlattenHierarchy).GetValue(null);
        var groupType = assembly.GetType("UnityEditor.GameViewSizeGroupType");
        var group = sizesType.GetMethod("GetGroup").Invoke(sizes, new object[] { Enum.Parse(groupType, "Standalone") });
        var sizeType = assembly.GetType("UnityEditor.GameViewSize");
        var kindType = assembly.GetType("UnityEditor.GameViewSizeType");
        object fixedSize = Activator.CreateInstance(sizeType, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null,
            new object[] { Enum.Parse(kindType, "FixedResolution"), 960, 540, "GameFactory owned capture" }, CultureInfo.InvariantCulture);
        int count = (int)group.GetType().GetMethod("GetTotalCount").Invoke(group, null);
        _batchView = view;
        _batchSizeGroup = group;
        _batchOwnedSize = fixedSize;
        _batchOriginalSizeCount = count;
        _batchOriginalSelectedSize = (int)view.GetType().GetProperty("selectedSizeIndex", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance).GetValue(view);
        _batchOriginalTargetSize = (Vector2)assembly.GetType("UnityEditor.PlayModeView").GetProperty("targetSize", BindingFlags.Instance | BindingFlags.NonPublic).GetValue(view);
        group.GetType().GetMethod("AddCustomSize").Invoke(group, new object[] { fixedSize });
        view.GetType().GetProperty("selectedSizeIndex", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance).SetValue(view, count);
        _batchViewConfigured = true;
    }
    private static void CaptureBatchView()
    {
        // Use the same native camera/display/IMGUI renderer as Unity's GameView.
        // No Camera.Render, targetTexture edits, focus callbacks or gameplay calls.
        Type playMode = typeof(EditorWindow).Assembly.GetType("UnityEditor.PlayModeView");
        Type viewType = typeof(EditorWindow).Assembly.GetType("UnityEditor.GameView");
        var view = EditorWindow.GetWindow(viewType, false, null, false);
        ConfigureBatchView(view);
        playMode.GetProperty("targetSize", BindingFlags.Instance | BindingFlags.NonPublic).SetValue(view, new Vector2(960, 540));
        var size = playMode.GetMethod("SetPlayModeViewSize", BindingFlags.Instance | BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
        if (size != null) size.Invoke(size.IsStatic ? null : view, new object[] { new Vector2(960, 540) });
        if (_batchTarget == null) { _batchTarget = new RenderTexture(960, 540, 24, RenderTextureFormat.ARGB32); _batchTarget.Create(); }
        var render = typeof(EditorGUIUtility).GetMethod("RenderPlayModeViewCamerasInternal", BindingFlags.Static | BindingFlags.NonPublic);
        if (render == null) throw new NotSupportedException("native GameView renderer unavailable");
        Event previousEvent = Event.current;
        RenderTexture previous = RenderTexture.active;
        Texture2D shot = null;
        try
        {
            Event.current = new Event { type = EventType.Repaint };
            Canvas.ForceUpdateCanvases();
            render.Invoke(null, new object[] { _batchTarget, 0, Vector2.zero, false, true });
            if (_frameCount == 50)
                File.WriteAllText(Path.Combine(_outputDirectory, "batch_render_diagnostic.json"),
                    "{\"screen_width\":" + Screen.width + ",\"screen_height\":" + Screen.height +
                    ",\"pump_updates\":" + _frameTap.manualInputUpdates + ",\"set_size_found\":" + (size != null ? "true" : "false") + "}");
            _captureReadSeconds = EditorApplication.timeSinceStartup;
            RenderTexture.active = _batchTarget;
            shot = new Texture2D(960, 540, TextureFormat.RGB24, false);
            shot.ReadPixels(new Rect(0, 0, 960, 540), 0, 0, false); shot.Apply(false, false);
            if (SystemInfo.graphicsUVStartsAtTop)
            {
                var pixels = shot.GetPixels32();
                for (int y = 0; y < 540 / 2; y++)
                    for (int x = 0; x < 960; x++)
                    { int a = y * 960 + x; int b = (539 - y) * 960 + x; var pixel = pixels[a]; pixels[a] = pixels[b]; pixels[b] = pixel; }
                shot.SetPixels32(pixels); shot.Apply(false, false);
            }
            CaptureFrame(shot, _captureReadSeconds - _takeStartSeconds); shot = null;
        }
        finally
        {
            if (shot != null) UnityEngine.Object.DestroyImmediate(shot);
            Event.current = previousEvent; RenderTexture.active = previous;
        }
    }
    private static bool BackgroundCapture
    {
        get { string policy = Environment.GetEnvironmentVariable("GAMEFACTORY_UNITY_CAPTURE_POLICY"); return policy == "background_inputsystem_v1" || policy == "graphics_batch_render_v2"; }
    }
    private static bool FocusGameView()
    {
        if (GraphicsBatchCapture) return true;
        if (BackgroundCapture)
        {
            Type type = typeof(EditorWindow).Assembly.GetType("UnityEditor.GameView");
            if (type == null) return false;
            var window = EditorWindow.GetWindow(type, false, null, false);
            if (window == null) return false;
            window.Repaint();
            // Occluded editor windows can drop queued repaints. Ask this owned
            // GameView's host to paint now without Focus/Show/OS activation.
            // This runs Unity's own GameView camera/UI rendering; never draw a
            // substitute frame or invoke a delivered gameplay method.
            var parentField = typeof(EditorWindow).GetField("m_Parent", BindingFlags.Instance | BindingFlags.NonPublic);
            object host = parentField == null ? null : parentField.GetValue(window);
            var immediate = host == null ? null : host.GetType().GetMethod("RepaintImmediately", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
            if (immediate == null) throw new NotSupportedException("owned GameView immediate repaint unavailable");
            immediate.Invoke(host, null);
            EditorApplication.QueuePlayerLoopUpdate();
            return true; // availability, never a focused-window attestation
        }
        return ForegroundGameView();
    }
    private static bool ForegroundGameView()
    {
        try
        {
            Type type = typeof(EditorWindow).Assembly.GetType("UnityEditor.GameView");
            if (type == null) return false;
            if (EditorWindow.focusedWindow == null || EditorWindow.focusedWindow.GetType() != type)
            {
                var window = EditorWindow.GetWindow(type);
                window.Show();
                window.Focus();
            }
            return EditorWindow.focusedWindow != null && EditorWindow.focusedWindow.GetType() == type;
        }
        catch (Exception exception)
        {
            RecordWarning("could not focus the Game view: " + exception.Message);
            return false;
        }
    }

    private static void WriteInputFocus()
    {
        bool focused = EditorWindow.focusedWindow != null && EditorWindow.focusedWindow.GetType().FullName == "UnityEditor.GameView";
        string rectJson = "";
        if (focused)
        {
            // GameView's render rectangle excludes toolbar and letterboxing.
            var window = EditorWindow.focusedWindow;
            var flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
            var property = window.GetType().GetProperty("targetInView", flags);
            if (property != null)
            {
                Rect target = (Rect)property.GetValue(window, null);
                var viewProperty = window.GetType().GetProperty("viewInWindow", flags);
                if (viewProperty != null) target.position += ((Rect)viewProperty.GetValue(window, null)).position;
                target.position += window.position.position;
                rectJson = ",\"screen_rect\":[" + target.x.ToString(CultureInfo.InvariantCulture) + "," + target.y.ToString(CultureInfo.InvariantCulture) + "," + target.width.ToString(CultureInfo.InvariantCulture) + "," + target.height.ToString(CultureInfo.InvariantCulture) + "]";
            }
        }
        string text = "{\"target_window\":\"GameView\",\"focused\":" + (focused ? "true" : "false") + rectJson +
            ",\"t_ms\":" + ((EditorApplication.timeSinceStartup - _takeStartSeconds) * 1000.0).ToString("0.###", CultureInfo.InvariantCulture) + "}";
        // The host reads this while the Editor updates it. Publish a complete
        // snapshot atomically so it never observes a truncated JSON document.
        string path = Path.Combine(_outputDirectory, "input_focus.json");
        string temporary = path + ".tmp";
        File.WriteAllText(temporary, text, new UTF8Encoding(false));
        // Mono File.Replace(..., null) throws on this macOS runtime, even
        // for a valid destination. POSIX rename replaces atomically without
        // deleting the reader's old inode or creating an absent-file window.
        if (Application.platform == RuntimePlatform.OSXEditor || Application.platform == RuntimePlatform.LinuxEditor)
        {
            if (RenameSnapshot(temporary, path) != 0)
                throw new IOException("atomic focus rename failed: errno=" + Marshal.GetLastWin32Error());
        }
        else if (File.Exists(path)) File.Replace(temporary, path, null);
        else File.Move(temporary, path);
    }

    [DllImport("libc", EntryPoint = "rename", SetLastError = true)]
    private static extern int RenameSnapshot(string source, string destination);

    private static void RecordWarning(string message)
    {
        if (!Warnings.Contains(message))
            Warnings.Add(message);
        Debug.LogWarning($"{LogTag} {message}");
    }

    // ── Minimal JSON writing ────────────────────────────────────────────────

    /// Guard against pathological self-referencing payload graphs.
    [ThreadStatic] private static int _jsonDepth;

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
        if (value is Vector2 vector2)
        {
            builder.Append("{\"x\":").Append(vector2.x.ToString("R", CultureInfo.InvariantCulture))
                .Append(",\"y\":").Append(vector2.y.ToString("R", CultureInfo.InvariantCulture))
                .Append('}');
            return;
        }
        if (value is Vector3 vector3)
        {
            builder.Append("{\"x\":").Append(vector3.x.ToString("R", CultureInfo.InvariantCulture))
                .Append(",\"y\":").Append(vector3.y.ToString("R", CultureInfo.InvariantCulture))
                .Append(",\"z\":").Append(vector3.z.ToString("R", CultureInfo.InvariantCulture))
                .Append('}');
            return;
        }
        if (value is Vector4 vector4)
        {
            builder.Append("{\"x\":").Append(vector4.x.ToString("R", CultureInfo.InvariantCulture))
                .Append(",\"y\":").Append(vector4.y.ToString("R", CultureInfo.InvariantCulture))
                .Append(",\"z\":").Append(vector4.z.ToString("R", CultureInfo.InvariantCulture))
                .Append(",\"w\":").Append(vector4.w.ToString("R", CultureInfo.InvariantCulture))
                .Append('}');
            return;
        }
        if (value is Enum enumValue)
        {
            builder.Append(JsonEscape(enumValue.ToString()));
            return;
        }
        if (value is UnityEngine.Object unityObject)
        {
            // engine references are identified, never serialized
            builder.Append(JsonEscape(unityObject ? unityObject.name : ""));
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
        if (_jsonDepth < 4)
        {
            // plain data payload (e.g. a [Serializable] event struct): its
            // public fields then public readable properties
            _jsonDepth += 1;
            try
            {
                builder.Append("{");
                bool first = true;
                foreach (FieldInfo field in value.GetType().GetFields(
                             BindingFlags.Public | BindingFlags.Instance))
                {
                    if (!first) builder.Append(",");
                    first = false;
                    builder.Append(JsonEscape(field.Name)).Append(":");
                    WriteJsonValue(builder, field.GetValue(value));
                }
                foreach (PropertyInfo property in value.GetType().GetProperties(
                             BindingFlags.Public | BindingFlags.Instance))
                {
                    if (!property.CanRead || property.GetIndexParameters().Length > 0) continue;
                    if (!first) builder.Append(",");
                    first = false;
                    builder.Append(JsonEscape(property.Name)).Append(":");
                    try { WriteJsonValue(builder, property.GetValue(value, null)); }
                    catch { builder.Append("null"); }
                }
                builder.Append("}");
            }
            finally
            {
                _jsonDepth -= 1;
            }
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
            if (!argv[index].StartsWith("--gamefactory-evaluation-")) continue;
            string key = argv[index].Substring("--gamefactory-evaluation-".Length);
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


    // ---- Game log events: Debug.Log lines whose call site is the delivered project's own script ----
    // Same clock as frames (EditorApplication.timeSinceStartup - _takeStartSeconds). Evidence only.
    private static int _gameEventCount;
    private static void OnGameLog(string message, string stackTrace, LogType type)
    {
        try
        {
            if (_takeStartSeconds < 0.0 || string.IsNullOrEmpty(_outputDirectory) || _gameEventCount >= 4000) return;
            if (string.IsNullOrEmpty(stackTrace)) return;
            // Call site in the delivered project's scripts: "(at Assets/..." or, when the game assembly was
            // compiled elsewhere, an absolute "(at /.../Assets/...". Engine / package frames never match.
            int at = stackTrace.IndexOf("(at Assets/", StringComparison.Ordinal);
            int start = at >= 0 ? at + 4 : -1;
            if (at < 0)
            {
                for (int i = stackTrace.IndexOf("(at /", StringComparison.Ordinal); i >= 0;
                     i = stackTrace.IndexOf("(at /", i + 4, StringComparison.Ordinal))
                {
                    int close = stackTrace.IndexOf(')', i), a = stackTrace.IndexOf("/Assets/", i, StringComparison.Ordinal);
                    if (a > 0 && (close < 0 || a < close)) { at = i; start = a + 1; break; }
                }
            }
            if (at < 0) return;
            string site = stackTrace.Substring(start, Math.Max(0, stackTrace.IndexOf(')', start) - start));
            if (site.Contains("GameFactory3A")) return;            // the evaluation recorder itself
            double ms = (EditorApplication.timeSinceStartup - _takeStartSeconds) * 1000.0;
            if (_inputReadyElapsedSeconds >= 0.0) EventFrames.OnEvent(ms);
            string text = message.Length > 600 ? message.Substring(0, 600) : message;
            File.AppendAllText(Path.Combine(_outputDirectory, "game_events.jsonl"),
                "{\"t_ms\":" + ms.ToString("0.###", CultureInfo.InvariantCulture) + ",\"source\":" + JsonEscape(site) +
                ",\"level\":\"" + type + "\",\"message\":" + JsonEscape(text) + "}\n");
            _gameEventCount++;
            // Custom bone drivers can report their natural playback without Animator/Animation.
            // Keep these explicitly attributed to the author's log, never to an engine clip observer.
            if (type == LogType.Log) AssetWatch.OnMotionLog(_outputDirectory, ms, text, site);
        }
        catch { }
    }

    // ---- End-of-take asset photos (opt-in GAMEFACTORY_UNITY_ASSET_SHOTS_PLAN=<plan.json>) ----
    // Plan: {"size":640,"assets":[{"id","kind","unity_paths":["Assets/..."],"vertex_counts":[n,...]}]}
    // A renderer belongs to an asset when its mesh comes from one of the asset's files (editor import:
    // AssetDatabase path) or matches one of the original glTF mesh vertex counts (runtime glTFast load).
    // Placed -> Game View (scene lights / post), isolated on a spare layer; not placed but loadable ->
    // spawned copy, Neutral View. Placement is existence in the running scene, not momentary visibility.
    [Serializable] private class ShotAsset { public string id; public string kind; public string[] unity_paths; public int[] vertex_counts; }
    [Serializable] private class ShotMotion { public string id; public string kind; public string[] unity_paths; public string[] model_paths; public int[] vertex_counts; }
    [Serializable] private class ShotPlan { public int size = 640; public ShotAsset[] assets; public ShotMotion[] motions; public int motion_frames = 12; }
    private static class AssetShots
    {
        private static readonly (string name, float yaw, float pitch)[] Views =
            { ("front", 180f, 10f), ("right", 270f, 10f), ("back", 0f, 10f), ("three_quarter_top", 135f, 40f) };
        private const int Layer = 31;

        private static Mesh MeshOf(Renderer r)
        {
            if (r is SkinnedMeshRenderer s) return s.sharedMesh;
            var f = r.GetComponent<MeshFilter>();
            return f != null ? f.sharedMesh : null;
        }

        public static void Capture(string planPath, string outputDirectory)
        {
            if (string.IsNullOrEmpty(planPath) || !File.Exists(planPath)) return;
            // Whether every texture really was at full resolution is reported per asset (streaming).
            Texture.streamingTextureForceLoadAll = true;
            var plan = JsonUtility.FromJson<ShotPlan>(File.ReadAllText(planPath));
            if (plan == null || plan.assets == null || plan.assets.Length == 0) return;   // motion-only plan
            string dir = Path.Combine(outputDirectory, "asset_shots");
            Directory.CreateDirectory(dir);
            var renderers = UnityEngine.Object.FindObjectsOfType<Renderer>(true);
            Vector3 focus = Camera.main != null ? Camera.main.transform.position : Vector3.zero;
            var rows = new List<string>();
            var claimed = new HashSet<string>();        // files named for some asset: never re-assigned by count
            foreach (var a in plan.assets) foreach (var p in a.unity_paths ?? new string[0]) claimed.Add(p);
            foreach (var asset in plan.assets)
            {
                var paths = new HashSet<string>(asset.unity_paths ?? new string[0]);
                var counts = new HashSet<int>(asset.vertex_counts ?? new int[0]);
                var matched = new List<Renderer>();
                foreach (var r in renderers)
                {
                    if (r == null || !r.gameObject.scene.IsValid()) continue;
                    var mesh = MeshOf(r);
                    if (mesh == null) continue;
                    string path = AssetDatabase.GetAssetPath(mesh);
                    // file of this asset; or a runtime / derived mesh (e.g. a rigged copy) with an original vertex count
                    if ((!string.IsNullOrEmpty(path) && paths.Contains(path)) ||
                        ((string.IsNullOrEmpty(path) || !claimed.Contains(path)) && counts.Contains(mesh.vertexCount)))
                        matched.Add(r);
                }
                var row = new StringBuilder("{\"id\":" + JsonEscape(asset.id) + ",\"placed_components\":" + matched.Count);
                GameObject spawned = null;
                if (matched.Count > 0)
                {
                    bool scene = asset.kind == "3d_scene";
                    Renderer nearest = matched[0];
                    foreach (var r in matched)
                        if (r.bounds.SqrDistance(focus) < nearest.bounds.SqrDistance(focus)) nearest = r;
                    var keep = new List<Renderer>();
                    Bounds seed = nearest.bounds; seed.Expand(scene ? 30f : nearest.bounds.extents.magnitude * 2f);
                    foreach (var r in matched)
                        if (r == nearest || ((scene || r.transform.root == nearest.transform.root) && seed.Intersects(r.bounds)))
                            keep.Add(r);
                    matched = keep;
                    row.Append(",\"framing\":" + JsonEscape(scene ? "scene renderers around the player" : "the placed copy nearest the player"));
                }
                else
                {
                    foreach (var p in paths)
                    {
                        var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(p);
                        if (prefab == null) continue;
                        spawned = UnityEngine.Object.Instantiate(prefab, focus + Vector3.up * 200f, Quaternion.identity);
                        foreach (var mb in spawned.GetComponentsInChildren<MonoBehaviour>(true)) mb.enabled = false;
                        matched.AddRange(spawned.GetComponentsInChildren<Renderer>(true));
                        break;
                    }
                }
                row.Append(",\"spawned\":" + (spawned != null ? "true" : "false"));
                if (matched.Count == 0)
                {
                    row.Append(",\"error\":\"no renderer found in the running scene and no loadable asset to spawn\"}");
                    rows.Add(row.ToString());
                    continue;
                }
                string mode = spawned != null ? "neutral" : "game";
                row.Append(",\"view_mode\":\"" + mode + "\"");
                var lods = ForceTopLod(matched);
                row.Append(",\"streaming\":" + StreamingReport(matched));
                row.Append(",\"files\":[" + Shoot(asset.id, matched, mode, plan.size, dir) + "]}");
                foreach (var g in lods) if (g != null) g.ForceLOD(-1);
                rows.Add(row.ToString());
                if (spawned != null) UnityEngine.Object.DestroyImmediate(spawned);
            }
            File.WriteAllText(Path.Combine(dir, "asset_shots.json"),
                "{\"version\":\"a3-asset-shots.v1\",\"engine\":\"unity3d\",\"assets\":[" + string.Join(",", rows) + "]}");
        }

        private static List<LODGroup> ForceTopLod(List<Renderer> renderers)
        {
            var groups = new List<LODGroup>();
            foreach (var r in renderers)
            {
                var g = r != null ? r.GetComponentInParent<LODGroup>() : null;
                if (g != null && !groups.Contains(g)) { g.ForceLOD(0); groups.Add(g); }
            }
            return groups;
        }

        private static string StreamingReport(List<Renderer> renderers)
        {
            var seen = new HashSet<Texture2D>();
            int full = 0;
            var notFull = new List<string>();
            foreach (var r in renderers)
            {
                if (r == null) continue;
                foreach (var m in r.sharedMaterials)
                {
                    if (m == null) continue;
                    foreach (int id in m.GetTexturePropertyNameIDs())
                    {
                        if (!(m.GetTexture(id) is Texture2D t) || !seen.Add(t)) continue;
                        bool ok = !t.streamingMipmaps || !QualitySettings.streamingMipmapsActive || t.loadedMipmapLevel == 0;
                        if (ok) full++; else if (notFull.Count < 20) notFull.Add(JsonEscape(t.name));
                    }
                }
            }
            return "{\"textures\":" + seen.Count + ",\"textures_fully_streamed\":" + full +
                   ",\"fully_streamed\":" + (full == seen.Count ? "true" : "false") +
                   ",\"not_fully_streamed\":[" + string.Join(",", notFull) + "]}";
        }

        // Motion evidence comes from native GameView frames during observed gameplay playback.
        // Do not instantiate a model or sample a clip to substitute for the game's animation state.

        private static string Shoot(string id, List<Renderer> renderers, string mode, int size, string dir)
        {
            var layers = new Dictionary<GameObject, int>();
            var enabled = new Dictionary<Renderer, bool>();
            var lights = new List<(Light light, int mask)>();
            var extra = new List<GameObject>();
            Bounds b = renderers[0].bounds;
            foreach (var r in renderers) b.Encapsulate(r.bounds);
            if (b.extents.magnitude > 30f)          // a scene: frame the ~30 m around its piece nearest the camera
            {
                Vector3 focus = Camera.main != null ? Camera.main.transform.position : b.center;
                Vector3 anchor = b.ClosestPoint(focus);
                var around = new Bounds(anchor, new Vector3(60f, 30f, 60f));
                var clipped = new Bounds(anchor, Vector3.zero); bool any = false;
                foreach (var r in renderers) if (around.Intersects(r.bounds)) { if (!any) { clipped = r.bounds; any = true; } else clipped.Encapsulate(r.bounds); }
                if (any) { clipped.SetMinMax(Vector3.Max(clipped.min, around.min), Vector3.Min(clipped.max, around.max)); b = clipped; }
            }
            foreach (var r in renderers)
            {
                if (!layers.ContainsKey(r.gameObject)) layers[r.gameObject] = r.gameObject.layer;
                r.gameObject.layer = Layer;
                enabled[r] = r.enabled; r.enabled = true;          // existence, not momentary visibility
            }
            if (mode == "neutral")
            {
                foreach (var l in UnityEngine.Object.FindObjectsOfType<Light>()) { lights.Add((l, l.cullingMask)); l.cullingMask &= ~(1 << Layer); }
                var key = new GameObject("GF3A_ShotKey").AddComponent<Light>();
                key.type = LightType.Directional; key.intensity = 1.1f; key.cullingMask = 1 << Layer;
                key.transform.rotation = Quaternion.Euler(45f, 135f, 0f); extra.Add(key.gameObject);
                var fill = new GameObject("GF3A_ShotFill").AddComponent<Light>();
                fill.type = LightType.Directional; fill.intensity = 0.5f; fill.cullingMask = 1 << Layer;
                fill.transform.rotation = Quaternion.Euler(30f, -45f, 0f); extra.Add(fill.gameObject);
            }
            var cam = new GameObject("GF3A_ShotCamera").AddComponent<Camera>(); extra.Add(cam.gameObject);
            cam.cullingMask = 1 << Layer;
            cam.clearFlags = CameraClearFlags.SolidColor;
            cam.backgroundColor = new Color(0.20f, 0.22f, 0.26f);
            cam.fieldOfView = 35f;
            float radius = Mathf.Max(b.extents.magnitude, 0.01f);
            float dist = radius / Mathf.Sin(cam.fieldOfView * 0.5f * Mathf.Deg2Rad) * 1.05f;
            cam.nearClipPlane = Mathf.Max(0.01f, dist - radius * 2f); cam.farClipPlane = dist + radius * 2f;
            var rt = new RenderTexture(size, size, 24, RenderTextureFormat.ARGB32);
            cam.targetTexture = rt;
            var tex = new Texture2D(size, size, TextureFormat.RGB24, false);
            var files = new List<string>();
            try
            {
                foreach (var v in Views)
                {
                    var d = Quaternion.Euler(v.pitch, v.yaw, 0f) * Vector3.forward;
                    cam.transform.position = b.center - d * dist;
                    cam.transform.rotation = Quaternion.LookRotation(d, Vector3.up);
                    cam.Render();
                    RenderTexture.active = rt;
                    tex.ReadPixels(new Rect(0, 0, size, size), 0, 0); tex.Apply();
                    RenderTexture.active = null;
                    string file = id + "__" + mode + "__" + v.name + ".png";
                    File.WriteAllBytes(Path.Combine(dir, file), tex.EncodeToPNG());
                    files.Add("{\"mode\":\"" + mode + "\",\"view\":\"" + v.name + "\",\"file\":" + JsonEscape(file) + ",\"ok\":true}");
                }
            }
            finally
            {
                cam.targetTexture = null;
                UnityEngine.Object.DestroyImmediate(rt); UnityEngine.Object.DestroyImmediate(tex);
                foreach (var kv in layers) if (kv.Key != null) kv.Key.layer = kv.Value;
                foreach (var kv in enabled) if (kv.Key != null) kv.Key.enabled = kv.Value;
                foreach (var l in lights) if (l.light != null) l.light.cullingMask = l.mask;
                foreach (var g in extra) UnityEngine.Object.DestroyImmediate(g);
            }
            return string.Join(",", files);
        }
    }


    // ---- State entry (opt-in GAMEFACTORY_UNITY_STATE_ENTRY=<json>) ----
    // {"calls":[{"object":"TypeName","member":"Method or field","kind":"method|field","args":["2"]}]}
    // Targets: the live instance(s) of the type in the running scene (MonoBehaviour / ScriptableObject),
    // or the type's static member. Only existing members are touched; nothing is compiled or added.
    [Serializable] private class EntryCall { public string @object; public string member; public string kind; public string[] args; public int at_ms; }
    [Serializable] private class EntryPlan { public EntryCall[] calls; }
    private static class StateEntry
    {
        private static Type Find(string name)
        {
            foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
            {
                Type[] types;
                try { types = asm.GetTypes(); } catch (ReflectionTypeLoadException e) { types = e.Types; }
                foreach (var t in types)
                    if (t != null && (t.Name == name || t.FullName == name)) return t;
            }
            return null;
        }

        private static object Convert1(string raw, Type to)
        {
            if (to == typeof(string)) return raw;
            if (to.IsEnum) return Enum.Parse(to, raw, true);
            if (to == typeof(bool)) return raw == "1" || raw.ToLowerInvariant() == "true";
            // the game's own [Serializable] save / snapshot type, given in its JSON form (JsonUtility, as games save)
            if (!to.IsPrimitive && to != typeof(decimal) && to.IsDefined(typeof(SerializableAttribute), false)
                && raw.TrimStart().StartsWith("{", StringComparison.Ordinal))
                return JsonUtility.FromJson(raw, to);
            return Convert.ChangeType(raw, to, CultureInfo.InvariantCulture);
        }

        // Calls run in order; a call with at_ms > 0 waits until that many ms after input readiness (Tick).
        private static readonly List<EntryCall> Pending = new List<EntryCall>();
        private static readonly List<string> Rows = new List<string>();
        private static string _out;
        private static double _startMs;

        public static void Run(string planPath, string outputDirectory, double atMs)
        {
            Pending.Clear(); Rows.Clear(); _out = null;
            if (string.IsNullOrEmpty(planPath) || !File.Exists(planPath)) return;
            var plan = JsonUtility.FromJson<EntryPlan>(File.ReadAllText(planPath));
            _out = outputDirectory; _startMs = atMs;
            Pending.AddRange(plan.calls ?? new EntryCall[0]);
            Tick(atMs);
        }

        public static void Tick(double nowMs)
        {
            if (_out == null) return;
            bool ran = false;
            while (Pending.Count > 0 && Pending[0].at_ms <= nowMs - _startMs)
            {
                var c = Pending[0]; Pending.RemoveAt(0); ran = true;
                Rows.Add(RunOne(c, nowMs));
            }
            if (ran)
                File.WriteAllText(Path.Combine(_out, "state_entry_result.json"),
                    "{\"at_ms\":" + _startMs.ToString("0.###", CultureInfo.InvariantCulture) + ",\"pending\":" + Pending.Count +
                    ",\"calls\":[" + string.Join(",", Rows) + "]}");
        }

        private static string RunOne(EntryCall c, double nowMs)
        {
            const BindingFlags all = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static;
            string error = ""; int targets = 0;
            try
            {
                var type = Find(c.@object);
                if (type == null) throw new Exception("type not found: " + c.@object);
                var instances = new List<object>();
                if (typeof(UnityEngine.Object).IsAssignableFrom(type))
                    foreach (var o in Resources.FindObjectsOfTypeAll(type))
                        if (!(o is Component comp) || comp.gameObject.scene.IsValid()) instances.Add(o);
                var args = c.args ?? new string[0];
                if (c.kind == "field")
                {
                    var f = type.GetField(c.member, all); var p = f == null ? type.GetProperty(c.member, all) : null;
                    if (f == null && p == null) throw new Exception("field/property not found: " + c.member);
                    bool isStatic = f != null ? f.IsStatic : p.GetSetMethod(true).IsStatic;
                    var value = Convert1(args.Length > 0 ? args[0] : "", f != null ? f.FieldType : p.PropertyType);
                    foreach (var inst in isStatic ? new List<object> { null } : instances)
                    { if (f != null) f.SetValue(inst, value); else p.SetValue(inst, value); targets++; }
                }
                else
                {
                    MethodInfo m = null;
                    foreach (var cand in type.GetMethods(all))
                        if (cand.Name == c.member && cand.GetParameters().Length == args.Length) { m = cand; break; }
                    if (m == null) throw new Exception("method not found: " + c.member + "/" + args.Length);
                    var ps = m.GetParameters(); var values = new object[ps.Length];
                    for (int i = 0; i < ps.Length; i++) values[i] = Convert1(args[i], ps[i].ParameterType);
                    foreach (var inst in m.IsStatic ? new List<object> { null } : instances) { m.Invoke(inst, values); targets++; }
                }
                if (targets == 0) throw new Exception("no live instance of " + c.@object + " in the running scene");
            }
            catch (Exception e) { error = (e.InnerException ?? e).Message; }
            return "{\"object\":" + JsonEscape(c.@object) + ",\"member\":" + JsonEscape(c.member) + ",\"kind\":" +
                   JsonEscape(c.kind ?? "method") + ",\"at_ms\":" + c.at_ms + ",\"t_ms\":" + nowMs.ToString("0.###", CultureInfo.InvariantCulture) +
                   ",\"targets\":" + targets + ",\"ok\":" + (error == "" ? "true" : "false") + ",\"error\":" + JsonEscape(error) + "}";
        }
    }


    // ---- Event-triggered frames (opt-in A3GAME_EVENT_FRAMES=1 / GAMEFACTORY_UNITY_EVENT_FRAMES=1) ----
    // Each game Debug.Log line from the delivered project's own scripts queues real Game View captures at
    // +0 / +250 / +700 ms (lines within 120 ms = one event, at most 400 per take). They fill the gaps between
    // scheduled slots (which keep priority), carry sample_at_ms -1 and capture_ids ["event/<ms>/+<offset>"].
    private static class EventFrames
    {
        private static readonly List<KeyValuePair<double, string>> Due = new List<KeyValuePair<double, string>>();
        private static double _lastEventMs = -1e9;
        private static int _taken;
        private static int _enabled = -1;
        private static bool Enabled
        {
            get
            {
                if (_enabled < 0)
                    _enabled = Environment.GetEnvironmentVariable("A3GAME_EVENT_FRAMES") == "1"
                               || Environment.GetEnvironmentVariable("GAMEFACTORY_UNITY_EVENT_FRAMES") == "1" ? 1 : 0;
                return _enabled == 1;
            }
        }
        private static int _written;
        public static int NextNumber() { return ++_written; }
        public static void Reset() { Due.Clear(); _lastEventMs = -1e9; _taken = 0; _written = 0; _enabled = -1; }
        public static void OnEvent(double ms)
        {
            if (!Enabled || ms - _lastEventMs < 120.0) return;
            _lastEventMs = ms;
            foreach (int off in new[] { 0, 250, 700 })
                Due.Add(new KeyValuePair<double, string>(ms + off, "event/" + ms.ToString("0", CultureInfo.InvariantCulture) + "/+" + off));
            Due.Sort((a, b) => a.Key.CompareTo(b.Key));
        }
        public static bool TryTake(double nowMs, out string captureId)
        {
            captureId = null;
            while (Due.Count > 0 && nowMs - Due[0].Key > 400.0) Due.RemoveAt(0);     // too late to be useful
            if (Due.Count == 0 || nowMs < Due[0].Key || _taken >= 400) return false;
            captureId = Due[0].Value; Due.RemoveAt(0); _taken++;
            return true;
        }
    }


    // ---- Asset watch (opt-in GAMEFACTORY_UNITY_ASSET_EVENTS=1): what the running game does with its assets ----
    // Read-only poll (~10 Hz). Every start / end of an animation clip on an Animator / legacy Animation, a sound
    // (AudioSource), a video (VideoPlayer, reached through reflection so projects without the video module still
    // compile) and every active-scene change is one line of asset_events.jsonl with the asset path, owner and take
    // time; each event also asks for event-triggered frames. Nothing is played, stopped or changed.
    private static class AssetWatch
    {
        private class Motion { public string Asset; public float Length; public float Norm; public bool Looping; public bool Completed; public Vector3 Start; public double StartMs; }
        private class Video { public string Url; public bool Playing; public double Time; public double Length; public double StartMs; }
        private static readonly Dictionary<int, Motion> Motions = new Dictionary<int, Motion>();
        private static readonly Dictionary<int, string> Sounds = new Dictionary<int, string>();
        private static readonly Dictionary<int, double> SoundStart = new Dictionary<int, double>();
        private static readonly Dictionary<int, Video> Videos = new Dictionary<int, Video>();
        private static double _nextMs;
        private static string _scene;
        private static int _rows;
        private static int _enabled = -1;
        private static Type _videoType;
        private static bool _videoLooked;
        private static bool Enabled
        {
            get
            {
                if (_enabled < 0) _enabled = Environment.GetEnvironmentVariable("GAMEFACTORY_UNITY_ASSET_EVENTS") == "1" ? 1 : 0;
                return _enabled == 1;
            }
        }
        public static void Reset()
        {
            Motions.Clear(); Sounds.Clear(); SoundStart.Clear(); Videos.Clear();
            _nextMs = 0; _scene = null; _rows = 0; _enabled = -1;
        }
        private static string F(double v) { return v.ToString("0.###", CultureInfo.InvariantCulture); }
        private static string PathOf(UnityEngine.Object o)
        {
            if (o == null) return "";
            string path = AssetDatabase.GetAssetPath(o);
            return string.IsNullOrEmpty(path) ? o.name : path + "#" + o.name;
        }
        private static void Emit(StringBuilder sb, double ms, string kind, string ev, string asset, string owner, string detail, bool frames)
        {
            sb.Append("{\"t_ms\":").Append(F(ms)).Append(",\"kind\":\"").Append(kind).Append("\",\"event\":\"").Append(ev)
              .Append("\",\"asset\":").Append(JsonEscape(asset ?? "")).Append(",\"owner\":").Append(JsonEscape(owner ?? ""));
            if (!string.IsNullOrEmpty(detail)) sb.Append(",\"detail\":{").Append(detail).Append('}');
            sb.Append("}\n");
            _rows++;
            if (frames) EventFrames.OnEvent(ms);
        }
        private static readonly System.Text.RegularExpressions.Regex MotionLog =
            new System.Text.RegularExpressions.Regex(@"^([A-Z][A-Z0-9_]*_MOTION)_(START|END|CANCEL)\s+([A-Za-z][A-Za-z0-9_]*_mot_[0-9]+)(?:\s|$)");
        public static void OnMotionLog(string outputDirectory, double tMs, string message, string site)
        {
            if (!Enabled || string.IsNullOrEmpty(outputDirectory) || _rows >= 8000) return;
            var match = MotionLog.Match(message);
            if (!match.Success) return;
            string ev = match.Groups[2].Value;
            ev = ev == "START" ? "start" : ev == "END" ? "end" : "interrupted";
            var sb = new StringBuilder();
            Emit(sb, tMs, "motion", ev, match.Groups[3].Value, match.Groups[1].Value,
                 "\"observation_source\":\"author_game_log\",\"call_site\":" + JsonEscape(site) +
                 ",\"message\":" + JsonEscape(message), false);
            File.AppendAllText(Path.Combine(outputDirectory, "asset_events.jsonl"), sb.ToString(), new UTF8Encoding(false));
        }
        public static void Poll(string outputDirectory, double tMs, bool inputReady)
        {
            if (!Enabled || string.IsNullOrEmpty(outputDirectory) || tMs < _nextMs || _rows >= 8000) return;
            _nextMs = tMs + 100.0;
            var sb = new StringBuilder();
            string scene = SceneManager.GetActiveScene().path;
            if (scene != _scene) { _scene = scene; Emit(sb, tMs, "level", "loaded", scene, "", null, inputReady); }
            // Motion: Animator (current clip of layer 0) and legacy Animation components.
            foreach (var an in UnityEngine.Object.FindObjectsOfType<Animator>())
            {
                if (an == null || an.gameObject.name.StartsWith("GameFactory3A", StringComparison.Ordinal)) continue;
                string asset = ""; float length = 0f, norm = 0f; bool looping = false;
                if (an.isActiveAndEnabled && an.runtimeAnimatorController != null && an.layerCount > 0)
                {
                    var infos = an.GetCurrentAnimatorClipInfo(0);
                    if (infos.Length > 0 && infos[0].clip != null)
                    {
                        AnimationClip best = infos[0].clip; float w = infos[0].weight;
                        foreach (var i in infos) if (i.clip != null && i.weight > w) { best = i.clip; w = i.weight; }
                        asset = PathOf(best); length = best.length;
                        var state = an.GetCurrentAnimatorStateInfo(0);
                        norm = state.normalizedTime; looping = state.loop;
                    }
                }
                // Controller-less Animators may be driven by an authored PlayableGraph.
                // Observe its dominant weighted clip without changing graph time or weights.
                if (asset == "" && an.isActiveAndEnabled)
                {
                    AnimationClip clip = null; double time = 0; float weight = 0;
                    foreach (var graph in UnityEditor.Playables.Utility.GetAllGraphs())
                    {
                        if (!graph.IsValid() || !graph.IsPlaying()) continue;
                        for (int i = 0; i < graph.GetOutputCount(); i++)
                        {
                            var output = graph.GetOutput(i);
                            if (!output.IsPlayableOutputOfType<AnimationPlayableOutput>()) continue;
                            var animationOutput = (AnimationPlayableOutput)output;
                            if (animationOutput.GetTarget() != an) continue;
                            FindPlayableClip(animationOutput.GetSourcePlayable(), output.GetWeight(), 0,
                                             ref clip, ref time, ref weight);
                        }
                    }
                    if (clip != null)
                    {
                        asset = PathOf(clip); length = clip.length;
                        norm = length > 0f ? (float)(time / length) : 0f; looping = clip.isLooping;
                    }
                }
                Track(sb, tMs, an.GetInstanceID(), asset, length, norm, looping, an.transform, an.gameObject.name, inputReady);
            }
            foreach (var la in UnityEngine.Object.FindObjectsOfType<Animation>())
            {
                if (la == null) continue;
                string asset = ""; float length = 0f, norm = 0f; bool looping = false;
                if (la.isActiveAndEnabled && la.isPlaying)
                    foreach (AnimationState st in la)
                        if (st != null && la.IsPlaying(st.name) && st.clip != null)
                        {
                            asset = PathOf(st.clip); length = st.length; norm = st.normalizedTime;
                            var wrap = st.wrapMode;
                            if (wrap == WrapMode.Default) wrap = st.clip.wrapMode;
                            if (wrap == WrapMode.Default) wrap = la.wrapMode;
                            looping = wrap == WrapMode.Loop || wrap == WrapMode.PingPong;
                            break;
                        }
                Track(sb, tMs, la.GetInstanceID(), asset, length, norm, looping, la.transform, la.gameObject.name, inputReady);
            }
            // Audio: AudioSource start / stop with the clip's asset path (audio_events.jsonl keeps the audibility detail).
            foreach (var src in UnityEngine.Object.FindObjectsOfType<AudioSource>())
            {
                if (src == null || src.gameObject.name.StartsWith("GameFactory3A", StringComparison.Ordinal)) continue;
                int id = src.GetInstanceID();
                bool playing = src.isPlaying && src.clip != null;
                string was; Sounds.TryGetValue(id, out was);
                if (playing && was == null)
                {
                    string a = PathOf(src.clip);
                    Sounds[id] = a; SoundStart[id] = tMs;
                    Emit(sb, tMs, "audio", "start", a, src.gameObject.name,
                         "\"looping\":" + (src.loop ? "true" : "false") + ",\"volume\":" + F(src.volume) +
                         ",\"mute\":" + (src.mute ? "true" : "false") + ",\"duration_ms\":" + F(src.clip.length * 1000.0), inputReady);
                }
                else if (!playing && was != null)
                {
                    double st0; SoundStart.TryGetValue(id, out st0);
                    Emit(sb, tMs, "audio", "stop", was, src.gameObject.name, "\"played_ms\":" + F(tMs - st0), inputReady);
                    Sounds.Remove(id); SoundStart.Remove(id);
                }
            }
            PollVideos(sb, tMs, inputReady);
            if (sb.Length > 0)
                File.AppendAllText(Path.Combine(outputDirectory, "asset_events.jsonl"), sb.ToString(), new UTF8Encoding(false));
        }
        private static void FindPlayableClip(Playable playable, float weight, int depth,
                                             ref AnimationClip best, ref double time, ref float bestWeight)
        {
            if (!playable.IsValid() || weight <= 0f || depth > 32) return;
            if (playable.IsPlayableOfType<AnimationClipPlayable>())
            {
                var clip = ((AnimationClipPlayable)playable).GetAnimationClip();
                if (clip != null && weight > bestWeight)
                { best = clip; time = playable.GetTime(); bestWeight = weight; }
                return;
            }
            for (int i = 0; i < playable.GetInputCount(); i++)
                FindPlayableClip(playable.GetInput(i), weight * playable.GetInputWeight(i), depth + 1,
                                 ref best, ref time, ref bestWeight);
        }
        private static void Track(StringBuilder sb, double tMs, int id, string asset, float length, float norm, bool looping,
                                  Transform owner, string ownerName, bool frames)
        {
            Motion prev; Motions.TryGetValue(id, out prev);
            string was = prev != null ? prev.Asset : "";
            bool same = prev != null && was == asset;
            bool wrapped = same && norm + 0.01f < prev.Norm;
            bool looped = same && prev.Looping && length > 0f &&
                          (wrapped || Mathf.FloorToInt(norm) > Mathf.FloorToInt(prev.Norm));
            // A Playable clip may already be past its end when its mixer weight becomes
            // dominant. Observing that held pose does not prove we witnessed completion.
            bool finished = same && !prev.Looping && !prev.Completed && length > 0f && prev.Norm < 1f && norm >= 1f;
            if (same && !looped && !wrapped && !finished) { prev.Norm = norm; return; }
            if (prev != null && was != "" && !prev.Completed)
            {
                float phase = prev.Looping ? prev.Norm - Mathf.Floor(prev.Norm) : prev.Norm;
                bool completed = looped || finished || (prev.Length > 0f && phase >= 0.97f && phase < 1f);
                var delta = owner != null ? owner.position - prev.Start : Vector3.zero;
                Emit(sb, tMs, "motion", completed ? "end" : "interrupted", was, ownerName,
                     "\"completed\":" + (completed ? "true" : "false") + ",\"played_ms\":" + F(tMs - prev.StartMs) +
                     ",\"length_ms\":" + F(prev.Length * 1000.0) + ",\"last_normalized_time\":" + F(prev.Norm) +
                     ",\"owner_moved_m\":" + F(delta.magnitude), frames);
            }
            // A non-looping Animator can hold its final pose indefinitely. End it once;
            // retain the state until a clip change or a normalized-time reset starts playback again.
            if (finished) { prev.Norm = norm; prev.Completed = true; return; }
            if (asset != "")
            {
                Emit(sb, tMs, "motion", "start", asset, ownerName, "\"length_ms\":" + F(length * 1000.0) +
                     ",\"observed_normalized_time\":" + F(norm) + ",\"looping\":" + (looping ? "true" : "false"), frames);
                Motions[id] = new Motion { Asset = asset, Length = length, Norm = norm, Looping = looping,
                    Start = owner != null ? owner.position : Vector3.zero, StartMs = tMs };
            }
            else Motions.Remove(id);
        }
        private static void PollVideos(StringBuilder sb, double tMs, bool frames)
        {
            if (!_videoLooked) { _videoLooked = true; _videoType = Type.GetType("UnityEngine.Video.VideoPlayer, UnityEngine.VideoModule"); }
            if (_videoType == null) return;
            foreach (var o in UnityEngine.Object.FindObjectsOfType(_videoType))
            {
                var comp = o as Component;
                if (comp == null) continue;
                int id = o.GetInstanceID();
                var clip = _videoType.GetProperty("clip")?.GetValue(o) as UnityEngine.Object;
                string url = clip != null ? PathOf(clip) : (_videoType.GetProperty("url")?.GetValue(o) as string ?? "");
                bool playing = (bool)(_videoType.GetProperty("isPlaying")?.GetValue(o) ?? false);
                double time = Convert.ToDouble(_videoType.GetProperty("time")?.GetValue(o) ?? 0.0, CultureInfo.InvariantCulture);
                double length = Convert.ToDouble(_videoType.GetProperty("length")?.GetValue(o) ?? 0.0, CultureInfo.InvariantCulture);
                Video prev; Videos.TryGetValue(id, out prev);
                if (prev == null)
                {
                    if (string.IsNullOrEmpty(url)) continue;
                    prev = new Video { Url = url, Time = time, Length = length, StartMs = tMs };
                    Videos[id] = prev;
                    Emit(sb, tMs, "video", "open", url, comp.gameObject.name, null, frames);
                }
                if (url != prev.Url)
                {
                    Emit(sb, tMs, "video", "open", url, comp.gameObject.name, null, frames);
                    prev.Url = url; prev.Playing = false; prev.Time = time; prev.Length = length; prev.StartMs = tMs;
                }
                if (playing && !prev.Playing)
                {
                    Emit(sb, tMs, "video", "play", url, comp.gameObject.name, "\"duration_ms\":" + F(length * 1000.0), frames);
                    prev.StartMs = tMs;
                }
                else if (!playing && prev.Playing)
                {
                    double len = prev.Length > 0 ? prev.Length : length;
                    bool ended = len > 0 && prev.Time >= len - 0.3;
                    Emit(sb, tMs, "video", ended ? "end" : "stop_early", url, comp.gameObject.name,
                         "\"played_ms\":" + F(tMs - prev.StartMs) + ",\"last_time_ms\":" + F(prev.Time * 1000.0) +
                         ",\"duration_ms\":" + F(len * 1000.0), frames);
                }
                prev.Playing = playing;
                if (playing) prev.Time = time;
                if (length > 0) prev.Length = length;
            }
        }
    }


    // ---- Audio watch: which game sounds start / stop, and whether a player could hear them ----
    // Read-only poll (every 50 ms) of every AudioSource in the running scene. One row per start / stop with the
    // game object, clip, volume / mute / loop / spatial blend and the scene's active AudioListener count
    // (Unity plays nothing audible without exactly one). Written to audio_events.jsonl on the take clock.
    private static class AudioWatch
    {
        private static readonly Dictionary<int, bool> Playing = new Dictionary<int, bool>();
        private static double _nextMs;
        private static int _rows;
        private static int _lastListeners = -1;
        private static double _dsp0 = -1, _dsp0Ms;
        private static bool _envWritten;
        public static void Reset() { Playing.Clear(); _nextMs = 0; _rows = 0; _lastListeners = -1; _dsp0 = -1; _envWritten = false; }
        public static void Poll(string outputDirectory, double tMs)
        {
            if (string.IsNullOrEmpty(outputDirectory) || tMs < _nextMs || _rows >= 4000) return;
            _nextMs = tMs + 50.0;
            int listeners = 0;
            foreach (var l in UnityEngine.Object.FindObjectsOfType<AudioListener>())
                if (l.enabled && l.gameObject.activeInHierarchy) listeners++;
            var sb = new StringBuilder();
            if (listeners != _lastListeners)
            {   // listener state (PlayOneShot is not visible through isPlaying; game logs cover those calls)
                _lastListeners = listeners;
                sb.Append("{\"t_ms\":").Append(tMs.ToString("0.###", CultureInfo.InvariantCulture))
                  .Append(",\"event\":\"listeners\",\"active_listeners\":").Append(listeners)
                  .Append(",\"note\":\"").Append(listeners == 1 ? "game output audible" :
                      listeners == 0 ? "no active AudioListener: Unity plays nothing audible" : "more than one AudioListener")
                  .Append("\"}\n");
                _rows++;
            }
            if (_dsp0 < 0) { _dsp0 = AudioSettings.dspTime; _dsp0Ms = tMs; }
            else if (!_envWritten && tMs - _dsp0Ms >= 2000.0)
            {   // audio engine diagnostic: does the DSP clock advance in this recording mode?
                _envWritten = true;
                double dspMs = (AudioSettings.dspTime - _dsp0) * 1000.0;
                var cfg = AudioSettings.GetConfiguration();
                File.WriteAllText(Path.Combine(outputDirectory, "audio_environment.json"),
                    "{\"output_sample_rate\":" + AudioSettings.outputSampleRate + ",\"dsp_buffer_size\":" + cfg.dspBufferSize +
                    ",\"speaker_mode\":\"" + cfg.speakerMode + "\",\"dsp_advanced_ms\":" + dspMs.ToString("0.#", CultureInfo.InvariantCulture) +
                    ",\"wall_ms\":" + (tMs - _dsp0Ms).ToString("0.#", CultureInfo.InvariantCulture) +
                    ",\"audio_engine_running\":" + (dspMs > 500.0 ? "true" : "false") +
                    ",\"listener_volume\":" + AudioListener.volume.ToString("0.###", CultureInfo.InvariantCulture) +
                    ",\"listener_paused\":" + (AudioListener.pause ? "true" : "false") + "}");
            }
            foreach (var src in UnityEngine.Object.FindObjectsOfType<AudioSource>())
            {
                if (src == null || src.gameObject.name.StartsWith("GameFactory3A", StringComparison.Ordinal)) continue;
                int id = src.GetInstanceID();
                bool now = src.isPlaying, before;
                Playing.TryGetValue(id, out before);
                if (now == before) continue;
                Playing[id] = now;
                bool enabled = src.enabled && src.gameObject.activeInHierarchy;
                bool audible = now && enabled && !src.mute && src.volume > 0.001f && listeners == 1 && AudioListener.volume > 0.001f && !AudioListener.pause;
                sb.Append("{\"t_ms\":").Append(tMs.ToString("0.###", CultureInfo.InvariantCulture))
                  .Append(",\"event\":\"").Append(now ? "start" : "stop").Append('"')
                  .Append(",\"object\":").Append(JsonEscape(src.gameObject.name))
                  .Append(",\"clip\":").Append(JsonEscape(src.clip != null ? src.clip.name : ""))
                  .Append(",\"volume\":").Append(src.volume.ToString("0.###", CultureInfo.InvariantCulture))
                  .Append(",\"mute\":").Append(src.mute ? "true" : "false")
                  .Append(",\"loop\":").Append(src.loop ? "true" : "false")
                  .Append(",\"spatial_blend\":").Append(src.spatialBlend.ToString("0.##", CultureInfo.InvariantCulture))
                  .Append(",\"active_listeners\":").Append(listeners)
                  .Append(",\"listener_volume\":").Append(AudioListener.volume.ToString("0.###", CultureInfo.InvariantCulture))
                  .Append(",\"audible_to_player\":").Append(audible ? "true" : "false").Append("}\n");
                _rows++;
            }
            if (sb.Length > 0)
                File.AppendAllText(Path.Combine(outputDirectory, "audio_events.jsonl"), sb.ToString(), new UTF8Encoding(false));
        }
    }
}
