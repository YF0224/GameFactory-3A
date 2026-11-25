// Consumes the host's expanded input timeline; never calls gameplay APIs.
// Optional Input System references are resolved at runtime. Legacy projects
// use host physical input: GameView IMGUI events do not update legacy Input.
using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Text;
using UnityEditor;
using UnityEngine;

public sealed class GameFactory3AInputDriver
{
    [Serializable]
    public class Scenario
    {
        public bool use_internal_driver;
        public List<ScenarioEvent> events;
    }

    [Serializable]
    public class ScenarioEvent
    {
        public string action_id;
        public string probe_id;
        public string step_id;
        public string[] criterion_ids;
        public string purpose;
        public string expected_observation;
        public double planned_t_ms;
        public double planned_end_t_ms;
        public double t_ms;
        public string phase;
        public float wheel;          // mouse_wheel: notches, positive = scroll up
        public string key;
        public string action;
        public string button;
        public float x;
        public float y;
        public int index;
    }

    [Serializable]
    private class Delivery
    {
        public string action_id;
        public string probe_id;
        public string step_id;
        public string[] criterion_ids;
        public string purpose;
        public string expected_observation;
        public double action_planned_t_ms;
        public double planned_end_t_ms;
        public double t_ms;
        public double planned_t_ms;
        public string phase;
        public string key;
        public string action;
        public string button;
        public float x;
        public float y;
        public int index;
        public bool sent;
        public bool cleanup_release;
        public bool imgui_queued;
        public string transport;
        public string error;
        public string source = "internal_driver";
    }

    private readonly List<ScenarioEvent> _pending = new List<ScenarioEvent>();
    private readonly Dictionary<string, double> _lastActionDeliveryMs = new Dictionary<string, double>();
    private readonly HashSet<string> _failedActionIds = new HashSet<string>();
    private readonly HashSet<string> _heldKeys = new HashSet<string>();
    private readonly HashSet<string> _heldButtons = new HashSet<string>();
    private double _takeStartSeconds;
    private double _readyOffsetMs;
    private double _warmupMs;
    private bool _ready;
    private bool _finished;
    private string _outputDir;
    private Vector2 _mousePosition = new Vector2(0.5f, 0.5f);
    private Vector2 _mousePixels;
    private bool _haveMousePixels;
    private Type _inputSystemType;
    private MethodInfo _queueStateMethod;

    public void Begin(string outputDir, double takeStartSeconds,
                      double warmupSeconds, List<ScenarioEvent> events)
    {
        if (events == null) throw new ArgumentException("Expanded scenario events are missing");
        _outputDir = outputDir;
        _takeStartSeconds = takeStartSeconds;
        _warmupMs = warmupSeconds * 1000.0;
        _ready = false;
        _finished = false;
        _pending.Clear();
        _heldKeys.Clear();
        _heldButtons.Clear();
        // The Python timeline is ordered already. Insert tap releases with a
        // stable sort so a release precedes a new press at the same timestamp.
        foreach (var ev in events)
        {
            if (ev.phase == "tap")
            {
                var down = JsonUtility.FromJson<ScenarioEvent>(JsonUtility.ToJson(ev));
                down.phase = "down";
                var up = JsonUtility.FromJson<ScenarioEvent>(JsonUtility.ToJson(ev));
                up.phase = "up";
                up.t_ms += 80;
                _pending.Add(down);
                _pending.Add(up);
            }
            else _pending.Add(ev);
        }
        for (int i = 1; i < _pending.Count; i++)
        {
            var ev = _pending[i];
            int j = i - 1;
            while (j >= 0 && _pending[j].t_ms > ev.t_ms)
            {
                _pending[j + 1] = _pending[j];
                j--;
            }
            _pending[j + 1] = ev;
        }
        ResolveNewInputSystem();
        ConfigureBackgroundInput();
        EditorApplication.update -= Tick;
        EditorApplication.update += Tick;
        EditorApplication.playModeStateChanged -= OnPlayModeChanged;
        EditorApplication.playModeStateChanged += OnPlayModeChanged;
    }

    // Called only after the recorder has captured a usable first frame.
    private int _renderWidth, _renderHeight;

    public void InputReady(int width, int height)
    {
        _renderWidth = width; _renderHeight = height;
        if (_ready) return;
        _readyOffsetMs = ElapsedMs();
        _ready = true;
    }

    private double ElapsedMs()
    {
        return Math.Max(0, (EditorApplication.timeSinceStartup - _takeStartSeconds) * 1000.0);
    }

    private void Tick()
    {
        if (_finished || !_ready || !EditorApplication.isPlaying) return;
        double now = ElapsedMs() - _readyOffsetMs - _warmupMs;
        // Do not collapse press and release into the same game frame after a
        // scheduling stall. Keep the actual delivery time in the trace.
        var edges = new Dictionary<string, string>();
        if (Time.frameCount == _lastInputFrame) return;
        _lastInputFrame = Time.frameCount;
        while (_pending.Count > 0 && _pending[0].t_ms <= now)
        {
            var ev = _pending[0];
            string id = IsMouse(ev) ? "mouse:" + ev.button : "key:" + ev.key;
            string earlier;
            if (ev.phase != "move" && edges.TryGetValue(id, out earlier) && earlier != ev.phase) break;
            _pending.RemoveAt(0);
            Deliver(ev, false);
            if (ev.phase != "move") edges[id] = ev.phase;
        }
    }

    private int _lastInputFrame = -1;
    private static bool IsMouse(ScenarioEvent ev)
    {
        return (ev.action ?? "").StartsWith("mouse_", StringComparison.Ordinal);
    }

    private void Deliver(ScenarioEvent ev, bool cleanup)
    {
        string transport = "unavailable";
        string error = "";
        bool sent = false;
        bool imguiQueued = false;
        bool mouse = IsMouse(ev);
        try
        {
            sent = TryInputSystem(ev);
            if (sent)
            {
                transport = "InputSystem.QueueStateEvent";
                if (mouse && Environment.GetEnvironmentVariable("GAMEFACTORY_UNITY_IMGUI_FORWARD") == "1")
                {
                    var guiEvent = new Event();
                    guiEvent.type = ev.phase == "down" ? EventType.MouseDown : ev.phase == "up" ? EventType.MouseUp :
                                    ev.phase == "wheel" ? EventType.ScrollWheel :
                                    _heldButtons.Count > 0 ? EventType.MouseDrag : EventType.MouseMove;
                    guiEvent.button = ev.button == "right" ? 1 : ev.button == "middle" ? 2 : 0;
                    guiEvent.mousePosition = new Vector2(ev.x * (_renderWidth - 1), ev.y * (_renderHeight - 1));
                    if (ev.phase == "wheel") guiEvent.delta = new Vector2(0f, -ev.wheel * 3f);   // IMGUI: positive = down
                    EditorGUIUtility.QueueGameViewInputEvent(guiEvent);
                    imguiQueued = true;
                }
                else if (!mouse && Environment.GetEnvironmentVariable("GAMEFACTORY_UNITY_IMGUI_FORWARD") == "1"
                         && (ev.phase == "down" || ev.phase == "up"))
                {   // keyboard for OnGUI handlers (Event.current.keyCode), same opt-in as mouse forwarding
                    string code = ImguiKeyCode(ev.key);
                    if (code != null && Enum.IsDefined(typeof(KeyCode), code))
                    {
                        var keyEvent = new Event();
                        keyEvent.type = ev.phase == "down" ? EventType.KeyDown : EventType.KeyUp;
                        keyEvent.keyCode = (KeyCode)Enum.Parse(typeof(KeyCode), code);
                        EditorGUIUtility.QueueGameViewInputEvent(keyEvent);
                        imguiQueued = true;
                    }
                }
            }
            else
                throw new NotSupportedException("InputSystem queue unavailable; legacy input requires host physical transport");
        }
        catch (Exception ex)
        {
            error = (ex.InnerException ?? ex).Message;
        }
        if (sent)
        {
            var held = mouse ? _heldButtons : _heldKeys;
            string value = mouse ? ev.button : ev.key;
            if (ev.phase == "down") held.Add(value);
            else if (ev.phase == "up") held.Remove(value);
            if (mouse) _mousePosition = new Vector2(ev.x, ev.y);
        }
        var row = new Delivery { t_ms = ElapsedMs(),
            action_id = ev.action_id, probe_id = ev.probe_id, step_id = ev.step_id,
            criterion_ids = ev.criterion_ids, purpose = ev.purpose,
            expected_observation = ev.expected_observation,
            action_planned_t_ms = ev.planned_t_ms, planned_end_t_ms = ev.planned_end_t_ms,
            planned_t_ms = _readyOffsetMs + _warmupMs + ev.t_ms,
            phase = ev.phase, key = ev.key, action = ev.action, button = ev.button,
            x = ev.x, y = ev.y, index = ev.index, sent = sent,
            cleanup_release = cleanup, imgui_queued = imguiQueued, transport = transport, error = error };
        // sent attests queueing only; state/event traces attest game response.
        File.AppendAllText(Path.Combine(_outputDir, "actions.jsonl"), JsonUtility.ToJson(row) + "\n", new UTF8Encoding(false));
        if (!cleanup && !string.IsNullOrEmpty(ev.action_id))
        {
            if (sent) _lastActionDeliveryMs[ev.action_id] = row.t_ms;
            else _failedActionIds.Add(ev.action_id);
        }
    }

    public double CompletedActionMs(string actionId)
    {
        double completed;
        if (_failedActionIds.Contains(actionId) || _pending.Exists(item => item.action_id == actionId) ||
            !_lastActionDeliveryMs.TryGetValue(actionId, out completed)) return -1.0;
        return completed;
    }

    public static bool SupportsInternalInput
    {
        get
        {
#if ENABLE_INPUT_SYSTEM && !ENABLE_LEGACY_INPUT_MANAGER
            foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
                if (assembly.GetName().Name == "Unity.InputSystem") return true;
#endif
            // With both backends enabled, physical input reaches both. Queued
            // InputSystem events alone would leave legacy Input users idle.
            return false;
        }
    }

    private void ResolveNewInputSystem()
    {
        foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
        {
            if (assembly.GetName().Name != "Unity.InputSystem") continue;
            _inputSystemType = assembly.GetType("UnityEngine.InputSystem.InputSystem");
            if (_inputSystemType == null) return;
            foreach (var method in _inputSystemType.GetMethods(BindingFlags.Public | BindingFlags.Static))
            {
                if (method.Name == "QueueStateEvent" && method.IsGenericMethodDefinition &&
                    method.GetParameters().Length == 3)
                {
                    _queueStateMethod = method;
                    return;
                }
            }
        }
    }

    private object _backgroundKeyboard, _backgroundMouse;
    private readonly List<object> _mutedDevices = new List<object>();
    private readonly List<PropertyInfo> _changedSettings = new List<PropertyInfo>();
    private readonly List<object> _originalSettings = new List<object>();
    private readonly List<object> _appliedSettings = new List<object>();
    private object _settings, _previousKeyboard, _previousMouse;
    private MethodInfo _disableDevice, _enableDevice, _removeDevice;
    private bool _backgroundConfigured;
    private Delegate _inputEventFilter;
    private Type _inputListenerType, _pointerType, _keyboardType;
    private PropertyInfo _inputEventHandled, _inputEventType;
    private int _filteredKeyboardEvents, _filteredPointerEvents, _acceptedOwnedEvents;

    private void FilterInputEvent<TEvent, TDevice>(TEvent inputEvent, TDevice sourceDevice)
    {
        object device = sourceDevice;
        if (ReferenceEquals(device, _backgroundKeyboard) || ReferenceEquals(device, _backgroundMouse))
        { _acceptedOwnedEvents++; return; }
        bool keyboard = _keyboardType.IsInstanceOfType(device);
        if (!keyboard && !_pointerType.IsInstanceOfType(device)) return;
        object boxedEvent = inputEvent;
        string kind = _inputEventType.GetValue(boxedEvent).ToString();
        // Retain real device-removal/configuration events. Discard unrelated
        // state/text input before it changes device state, actions or .current.
        if (kind != "STAT" && kind != "DLTA" && kind != "TEXT" && kind != "IMES") return;
        _inputEventHandled.SetValue(boxedEvent, true);
        if (keyboard) _filteredKeyboardEvents++; else _filteredPointerEvents++;
    }
    private void InstallInputFilter()
    {
        var property = _inputSystemType.GetProperty("onEvent");
        _inputListenerType = property.PropertyType;
        var addition = _inputListenerType.GetMethod("op_Addition", BindingFlags.Public | BindingFlags.Static);
        Type callbackType = addition.GetParameters()[1].ParameterType;
        Type[] arguments = callbackType.GetGenericArguments();
        _inputEventHandled = arguments[0].GetProperty("handled");
        _inputEventType = arguments[0].GetProperty("type");
        _keyboardType = _inputSystemType.Assembly.GetType("UnityEngine.InputSystem.Keyboard");
        _pointerType = _inputSystemType.Assembly.GetType("UnityEngine.InputSystem.Pointer");
        var method = GetType().GetMethod("FilterInputEvent", BindingFlags.NonPublic | BindingFlags.Instance).MakeGenericMethod(arguments);
        _inputEventFilter = Delegate.CreateDelegate(callbackType, this, method);
        addition.Invoke(null, new object[] { property.GetValue(null), _inputEventFilter });
    }

    private void ApplySetting(string name, string value)
    {
        var property = _settings.GetType().GetProperty(name);
        _changedSettings.Add(property);
        _originalSettings.Add(property.GetValue(_settings));
        object applied = Enum.Parse(property.PropertyType, value);
        _appliedSettings.Add(applied);
        property.SetValue(_settings, applied);
    }

    // Managed frontend only: keepSendingEvents=true never disables OS hardware.
    // Run before every manual pump so newly attached devices cannot leak input.
    public bool IsolateBackgroundDevices()
    {
        if (!_backgroundConfigured) return false;
        var assembly = _inputSystemType.Assembly;
        var keyboard = assembly.GetType("UnityEngine.InputSystem.Keyboard");
        var mouse = assembly.GetType("UnityEngine.InputSystem.Mouse");
        var devices = (System.Collections.IEnumerable)_inputSystemType.GetProperty("devices").GetValue(null);
        foreach (object device in devices)
        {
            if (ReferenceEquals(device, _backgroundKeyboard) || ReferenceEquals(device, _backgroundMouse)) continue;
            if (!keyboard.IsInstanceOfType(device) && !mouse.IsInstanceOfType(device)) continue;
            if (!(bool)device.GetType().GetProperty("enabled").GetValue(device)) continue;
            _disableDevice.Invoke(null, new object[] { device, true });
            if (!_mutedDevices.Contains(device)) _mutedDevices.Add(device);
        }
        _backgroundKeyboard.GetType().GetMethod("MakeCurrent").Invoke(_backgroundKeyboard, null);
        _backgroundMouse.GetType().GetMethod("MakeCurrent").Invoke(_backgroundMouse, null);
        return true;
    }

    [Serializable] private class BackgroundCleanup
    {
        public string schema = "unity-background-input-cleanup.v1";
        public bool keys_and_buttons_released, virtual_devices_removed, settings_restored, muted_devices_restored, ok;
        public int muted_device_count, filtered_keyboard_events, filtered_pointer_events, accepted_owned_events;
        public bool input_filter_removed;
        public List<string> errors = new List<string>();
    }
    private void RestoreBackgroundInput()
    {
        if (_settings == null) return;
        var report = new BackgroundCleanup();
        report.muted_device_count = _mutedDevices.Count;
        try
        {
            // Consume queued releases while the owned devices still exist.
            _inputSystemType.GetMethod("Update", BindingFlags.Public | BindingFlags.Static, null, Type.EmptyTypes, null).Invoke(null, null);
            report.keys_and_buttons_released = _heldKeys.Count == 0 && _heldButtons.Count == 0;
            if (_backgroundKeyboard != null)
            {
                object anyKey = _backgroundKeyboard.GetType().GetProperty("anyKey").GetValue(_backgroundKeyboard);
                report.keys_and_buttons_released &= !(bool)anyKey.GetType().GetProperty("isPressed").GetValue(anyKey);
            }
            if (_backgroundMouse != null)
                foreach (string name in new string[] { "leftButton", "rightButton", "middleButton" })
                {
                    object button = _backgroundMouse.GetType().GetProperty(name).GetValue(_backgroundMouse);
                    report.keys_and_buttons_released &= !(bool)button.GetType().GetProperty("isPressed").GetValue(button);
                }
        }
        catch (Exception ex) { report.errors.Add("release: " + ex.Message); }
        _backgroundConfigured = false;
        try
        {
            if (_inputEventFilter != null)
            {
                var subtraction = _inputListenerType.GetMethod("op_Subtraction", BindingFlags.Public | BindingFlags.Static);
                subtraction.Invoke(null, new object[] { _inputSystemType.GetProperty("onEvent").GetValue(null), _inputEventFilter });
                _inputEventFilter = null;
            }
            report.input_filter_removed = true;
        }
        catch (Exception ex) { report.errors.Add("remove input filter: " + ex.Message); }
        report.filtered_keyboard_events = _filteredKeyboardEvents;
        report.filtered_pointer_events = _filteredPointerEvents;
        report.accepted_owned_events = _acceptedOwnedEvents;
        foreach (object device in new object[] { _backgroundKeyboard, _backgroundMouse })
        {
            if (device == null) continue;
            try { _removeDevice.Invoke(null, new object[] { device }); }
            catch (Exception ex) { report.errors.Add("remove owned device: " + ex.Message); }
        }
        report.virtual_devices_removed = report.errors.Count == 0;
        _backgroundKeyboard = _backgroundMouse = null;
        int mutedErrors = report.errors.Count;
        foreach (object device in _mutedDevices)
        {
            try
            {
                if ((bool)device.GetType().GetProperty("added").GetValue(device))
                    _enableDevice.Invoke(null, new object[] { device });
            }
            catch (Exception ex) { report.errors.Add("restore muted device: " + ex.Message); }
        }
        report.muted_devices_restored = report.errors.Count == mutedErrors;
        int settingsErrors = report.errors.Count;
        for (int i = _changedSettings.Count - 1; i >= 0; i--)
        {
            try
            {
                object current = _changedSettings[i].GetValue(_settings);
                if (!Equals(current, _appliedSettings[i]))
                    throw new InvalidOperationException("setting changed by product: " + _changedSettings[i].Name);
                _changedSettings[i].SetValue(_settings, _originalSettings[i]);
            }
            catch (Exception ex) { report.errors.Add("restore setting: " + ex.Message); }
        }
        report.settings_restored = report.errors.Count == settingsErrors;
        foreach (object device in new object[] { _previousKeyboard, _previousMouse })
        {
            if (device == null) continue;
            try
            {
                if ((bool)device.GetType().GetProperty("added").GetValue(device))
                    device.GetType().GetMethod("MakeCurrent").Invoke(device, null);
            }
            catch (Exception ex) { report.errors.Add("restore current device: " + ex.Message); }
        }
        report.ok = report.keys_and_buttons_released && report.virtual_devices_removed && report.settings_restored && report.muted_devices_restored && report.input_filter_removed && report.errors.Count == 0;
        File.WriteAllText(Path.Combine(_outputDir, "background_input_cleanup.json"), JsonUtility.ToJson(report), new UTF8Encoding(false));
        _settings = null;
    }
    private void ConfigureBackgroundInput()
    {
        string policy = Environment.GetEnvironmentVariable("GAMEFACTORY_UNITY_CAPTURE_POLICY");
        if ((policy != "background_inputsystem_v1" && policy != "graphics_batch_render_v2") || _inputSystemType == null) return;
        object settings = _inputSystemType.GetProperty("settings", BindingFlags.Public | BindingFlags.Static).GetValue(null);
        _settings = settings;
        var background = settings.GetType().GetProperty("backgroundBehavior");
        var editor = settings.GetType().GetProperty("editorInputBehaviorInPlayMode");
        string beforeBackground = background.GetValue(settings).ToString();
        string beforeEditor = editor.GetValue(settings).ToString();
        ApplySetting("backgroundBehavior", "IgnoreFocus");
        ApplySetting("editorInputBehaviorInPlayMode", "AllDeviceInputAlwaysGoesToGameView");
        if (Environment.GetEnvironmentVariable("GAMEFACTORY_UNITY_CAPTURE_POLICY") == "graphics_batch_render_v2")
        {
            ApplySetting("updateMode", "ProcessEventsManually");
            var deviceType = _inputSystemType.Assembly.GetType("UnityEngine.InputSystem.InputDevice");
            _disableDevice = _inputSystemType.GetMethod("DisableDevice", new Type[] { deviceType, typeof(bool) });
            _enableDevice = _inputSystemType.GetMethod("EnableDevice", new Type[] { deviceType });
            _removeDevice = _inputSystemType.GetMethod("RemoveDevice", new Type[] { deviceType });
            _previousKeyboard = _inputSystemType.Assembly.GetType("UnityEngine.InputSystem.Keyboard").GetProperty("current").GetValue(null);
            _previousMouse = _inputSystemType.Assembly.GetType("UnityEngine.InputSystem.Mouse").GetProperty("current").GetValue(null);
            var add = _inputSystemType.GetMethod("AddDevice", BindingFlags.Public | BindingFlags.Static, null, new Type[] { typeof(string), typeof(string), typeof(string) }, null);
            _backgroundKeyboard = add.Invoke(null, new object[] { "Keyboard", "GameFactoryBackgroundKeyboard", null });
            _backgroundMouse = add.Invoke(null, new object[] { "Mouse", "GameFactoryBackgroundMouse", null });
            _backgroundKeyboard.GetType().GetMethod("MakeCurrent").Invoke(_backgroundKeyboard, null);
            _backgroundMouse.GetType().GetMethod("MakeCurrent").Invoke(_backgroundMouse, null);
            InstallInputFilter();
            _backgroundConfigured = true;
            IsolateBackgroundDevices();
        }
        File.WriteAllText(Path.Combine(_outputDir, "background_input_settings.json"),
            "{\"background_before\":\"" + beforeBackground + "\",\"editor_before\":\"" + beforeEditor +
            "\",\"background_after\":\"IgnoreFocus\",\"editor_after\":\"AllDeviceInputAlwaysGoesToGameView\",\"scope\":\"owned Editor process only; no settings asset saved\"}");
    }

    private bool TryInputSystem(ScenarioEvent ev)
    {
#if !ENABLE_INPUT_SYSTEM
        return false;
#else
        if (_queueStateMethod == null) return false;
        var assembly = _inputSystemType.Assembly;
        bool mouse = IsMouse(ev);
        var deviceType = assembly.GetType("UnityEngine.InputSystem." + (mouse ? "Mouse" : "Keyboard"));
        var current = deviceType == null ? null : deviceType.GetProperty("current", BindingFlags.Public | BindingFlags.Static);
        object device = mouse ? _backgroundMouse : _backgroundKeyboard;
        if (device == null) device = current == null ? null : current.GetValue(null);
        if (device == null) return false;
        var stateType = assembly.GetType("UnityEngine.InputSystem.LowLevel." + (mouse ? "MouseState" : "KeyboardState"));
        if (stateType == null) return false;
        object state;
        Vector2 position = Vector2.zero;
        if (mouse)
        {
            if (_renderWidth <= 0 || _renderHeight <= 0) throw new InvalidOperationException("Game render size unavailable");
            // JSON uses a top-left origin; InputSystem positions use bottom-left pixels.
            position = new Vector2(ev.x * (_renderWidth - 1), (1 - ev.y) * (_renderHeight - 1));
            state = Activator.CreateInstance(stateType);
            ushort buttons = 0;
            foreach (string button in _heldButtons) buttons |= ButtonBit(button);
            ushort bit = ButtonBit(ev.button);
            if (ev.phase == "down") buttons |= bit;
            else if (ev.phase == "up") buttons &= (ushort)~bit;
            stateType.GetField("position").SetValue(state, position);
            stateType.GetField("buttons").SetValue(state, buttons);
            if (ev.phase == "wheel")      // Input System scroll: 120 per notch (positive = up)
                stateType.GetField("scroll").SetValue(state, new Vector2(0f, ev.wheel * 120f));
            // only an explicit mouse_move / mouse_drag turns a mouse-look camera; positioning before a click / hold /
            // wheel carries no delta (no camera swing)
            bool explicitMove = ev.action == "mouse_move" || ev.action == "mouse_drag";
            stateType.GetField("delta").SetValue(state, _haveMousePixels && explicitMove ? position - _mousePixels : Vector2.zero);
        }
        else
        {
            var keyType = assembly.GetType("UnityEngine.InputSystem.Key");
            if (keyType == null) return false;
            var keys = new HashSet<string>(_heldKeys);
            if (ev.phase == "down") keys.Add(ev.key);
            else keys.Remove(ev.key);
            Array values = Array.CreateInstance(keyType, keys.Count);
            int index = 0;
            foreach (string key in keys) values.SetValue(Enum.Parse(keyType, InputSystemKeyName(key), true), index++);
            // KeyboardState(params Key[]) preserves all currently held keys.
            state = Activator.CreateInstance(stateType, new object[] { values });
        }
        _queueStateMethod.MakeGenericMethod(stateType).Invoke(null, new object[] { device, state, -1.0 });
        if (mouse) { _mousePixels = position; _haveMousePixels = true; }
        return true;
#endif
    }

    private static ushort ButtonBit(string button)
    {
        return (ushort)(button == "right" ? 2 : button == "middle" ? 4 : 1);
    }

    // IMGUI (OnGUI) key code for a planned key name (null when it has none).
    private static string ImguiKeyCode(string key)
    {
        if (string.IsNullOrEmpty(key)) return null;
        if (key.Length == 1 && char.IsLetter(key[0])) return key.ToUpperInvariant();
        if (key.Length == 1 && char.IsDigit(key[0])) return "Alpha" + key;
        if (key.StartsWith("numpad", StringComparison.Ordinal) && key.Length == 7 && char.IsDigit(key[6])) return "Keypad" + key[6];
        switch (key)
        {
            case "enter": case "return": return "Return";
            case "numpadenter": return "KeypadEnter";
            case "leftshift": return "LeftShift"; case "rightshift": return "RightShift";
            case "leftcontrol": return "LeftControl"; case "rightcontrol": return "RightControl";
            case "leftalt": return "LeftAlt"; case "rightalt": return "RightAlt";
            case "left_arrow": return "LeftArrow"; case "right_arrow": return "RightArrow";
            case "up_arrow": return "UpArrow"; case "down_arrow": return "DownArrow";
            case "apostrophe": return "Quote"; case "backquote": return "BackQuote";
            case "pageup": return "PageUp"; case "pagedown": return "PageDown"; case "capslock": return "CapsLock";
            case "leftbracket": return "LeftBracket"; case "rightbracket": return "RightBracket";
            default: return char.ToUpperInvariant(key[0]) + key.Substring(1);   // space, escape, tab, backspace, f1, comma ...
        }
    }

    private static string InputSystemKeyName(string key)
    {
        switch (key)
        {
            case "enter": case "return": return "Enter";
            case "leftshift": return "LeftShift";
            case "leftcontrol": return "LeftCtrl";
            case "rightcontrol": return "RightCtrl";
            case "apostrophe": return "Quote";
            case "left_arrow": return "LeftArrow";
            case "right_arrow": return "RightArrow";
            case "up_arrow": return "UpArrow";
            case "down_arrow": return "DownArrow";
            default:
                return key.Length == 1 && char.IsDigit(key[0]) ? "Digit" + key : key;
        }
    }

    public void Finish()
    {
        if (_finished) return;
        _finished = true;
        EditorApplication.update -= Tick;
        EditorApplication.playModeStateChanged -= OnPlayModeChanged;
        foreach (string button in new List<string>(_heldButtons))
            Deliver(new ScenarioEvent { action = "mouse_up", phase = "up", button = button,
                x = _mousePosition.x, y = _mousePosition.y, index = -1 }, true);
        foreach (string key in new List<string>(_heldKeys))
            Deliver(new ScenarioEvent { action = "key", phase = "up", key = key, index = -1 }, true);
        RestoreBackgroundInput();
        if (_pending.Count > 0)
            File.AppendAllText(Path.Combine(_outputDir, "actions.jsonl"), JsonUtility.ToJson(new Delivery {
                t_ms = ElapsedMs(), action = "pending_inputs", index = -1, sent = false,
                error = _pending.Count + " input events were not dispatched before take end" }) + "\n", new UTF8Encoding(false));
    }

    private void OnPlayModeChanged(PlayModeStateChange state)
    {
        if (state == PlayModeStateChange.ExitingPlayMode || state == PlayModeStateChange.EnteredEditMode)
            Finish();
    }
}
