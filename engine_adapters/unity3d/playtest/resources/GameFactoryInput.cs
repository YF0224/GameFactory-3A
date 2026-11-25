// User-authorized input migration. Reads native Input System devices only.
// It never invokes game methods, edits gameplay state, or manufactures outcomes.
using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.InputSystem.Controls;

public static class GameFactoryInput
{
    [Serializable] public sealed class Axis { public string name, negativeButton, positiveButton, altNegativeButton, altPositiveButton; public float gravity, dead, sensitivity; public int snap, invert, type, axis, joyNum; [NonSerialized] public float value; [NonSerialized] public int frame = -1; }
    [Serializable] private sealed class AxisFile { public Axis[] axes; }
    private static Axis[] axes;
    private static readonly Dictionary<string, string> keyNames = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase) {
        {"return","Enter"},{"enter","NumpadEnter"},{"keypadenter","NumpadEnter"},{"escape","Escape"},{"esc","Escape"},{"space","Space"},
        {"left","LeftArrow"},{"right","RightArrow"},{"up","UpArrow"},{"down","DownArrow"},
        {"leftctrl","LeftCtrl"},{"leftcontrol","LeftCtrl"},{"rightctrl","RightCtrl"},{"rightcontrol","RightCtrl"},
        {"leftcommand","LeftMeta"},{"rightcommand","RightMeta"},{"leftapple","LeftMeta"},{"rightapple","RightMeta"},
        {"leftwindows","LeftMeta"},{"rightwindows","RightMeta"},{"backquote","Backquote"},{"capslock","CapsLock"},
        {"numlock","NumLock"},{"scrolllock","ScrollLock"},{"print","PrintScreen"},{"pause","Pause"},
        {"[","LeftBracket"},{"]","RightBracket"},{";","Semicolon"},{"'","Quote"},{",","Comma"},{".","Period"},{"/","Slash"},{"\\","Backslash"},{"-","Minus"},{"=","Equals"},{"`","Backquote"}
    };
    private static ButtonControl MouseButton(int button) {
        var mouse=Mouse.current; if(mouse==null)return null;
        switch(button){case 0:return mouse.leftButton;case 1:return mouse.rightButton;case 2:return mouse.middleButton;case 3:return mouse.backButton;case 4:return mouse.forwardButton;default:throw new NotSupportedException("Input migration: mouse button "+button);}
    }
    private static ButtonControl Control(string value) {
        if(string.IsNullOrEmpty(value))return null;
        string name=value.Replace(" ","").ToLowerInvariant();
        if(name=="none")return null;
        if(name.StartsWith("mouse") && int.TryParse(name.Substring(5),out var mouse))return MouseButton(mouse);
        if(name.StartsWith("joystick")) {
            if(Joystick.current==null && Gamepad.current==null)return null;
            throw new NotSupportedException("Input migration: joystick mappings require device-specific validation: "+value);
        }
        if(Keyboard.current==null)return null;
        if(name.StartsWith("alpha") && name.Length==6)name="Digit"+name.Substring(5);
        else if(name.Length==1 && char.IsDigit(name[0]))name="Digit"+name;
        else if(name.StartsWith("keypad")) {
            string tail=name.Substring(6);
            if(tail.Length==1 && char.IsDigit(tail[0]))name="Numpad"+tail;
            else { var pad=new Dictionary<string,string>{{"plus","Plus"},{"minus","Minus"},{"multiply","Multiply"},{"divide","Divide"},{"period","Period"},{"enter","Enter"},{"equals","Equals"}}; if(pad.TryGetValue(tail,out var suffix))name="Numpad"+suffix; }
        }
        if(keyNames.TryGetValue(name,out var mapped))name=mapped;
        if(!Enum.TryParse<Key>(name,true,out var key))throw new NotSupportedException("Input migration: unmapped key "+value);
        return key==Key.None?null:Keyboard.current[key];
    }
    public static bool GetKey(KeyCode key){return GetKey(key.ToString());}
    public static bool GetKeyDown(KeyCode key){return GetKeyDown(key.ToString());}
    public static bool GetKeyUp(KeyCode key){return GetKeyUp(key.ToString());}
    public static bool GetKey(string key){var c=Control(key);return c!=null && c.isPressed;}
    public static bool GetKeyDown(string key){var c=Control(key);return c!=null && c.wasPressedThisFrame;}
    public static bool GetKeyUp(string key){var c=Control(key);return c!=null && c.wasReleasedThisFrame;}
    public static bool GetMouseButton(int button){var c=MouseButton(button);return c!=null && c.isPressed;}
    public static bool GetMouseButtonDown(int button){var c=MouseButton(button);return c!=null && c.wasPressedThisFrame;}
    public static bool GetMouseButtonUp(int button){var c=MouseButton(button);return c!=null && c.wasReleasedThisFrame;}
    public static Vector3 mousePosition {get {var p=Mouse.current==null?Vector2.zero:Mouse.current.position.ReadValue();return new Vector3(p.x,p.y,0);}}
    public static Vector2 mouseScrollDelta {get {return Mouse.current==null?Vector2.zero:Mouse.current.scroll.ReadValue()/120f;}}
    public static bool anyKeyDown {get {
        if(Keyboard.current!=null)foreach(var key in Keyboard.current.allKeys)if(key.wasPressedThisFrame)return true;
        for(int i=0;i<5;i++)if(GetMouseButtonDown(i))return true;return false;
    }}
    private static Axis[] Axes {get {
        if(axes==null){var text=Resources.Load<TextAsset>("GameFactoryInputAxes");if(text==null)throw new InvalidOperationException("Input migration axis manifest missing");axes=JsonUtility.FromJson<AxisFile>(text.text).axes;}
        return axes;
    }}
    private static float Raw(Axis a){
        float v=0;
        if(a.type==0)v=((GetKey(a.positiveButton)||GetKey(a.altPositiveButton))?1f:0f)-((GetKey(a.negativeButton)||GetKey(a.altNegativeButton))?1f:0f);
        else if(a.type==1){var m=Mouse.current;if(m!=null){if(a.axis==0)v=m.delta.ReadValue().x;else if(a.axis==1)v=m.delta.ReadValue().y;else if(a.axis==2)v=mouseScrollDelta.y;else throw new NotSupportedException("Input migration mouse axis "+a.axis);}v*=a.sensitivity;}
        else if(a.type==2){if(Joystick.current!=null || Gamepad.current!=null)throw new NotSupportedException("Input migration joystick axis requires device-specific validation");}
        else throw new NotSupportedException("Input migration axis type "+a.type);
        if(Mathf.Abs(v)<a.dead)v=0;return a.invert!=0?-v:v;
    }
    private static float ReadAxis(string name,bool raw){
        bool found=false;float chosen=0;
        foreach(var a in Axes)if(a.name==name){found=true;float v=Raw(a);
            if(!raw && a.type==0){if(a.frame!=Time.frameCount){if(a.snap!=0 && v!=0 && Mathf.Sign(v)!=Mathf.Sign(a.value))a.value=0;a.value=Mathf.MoveTowards(a.value,v,(v==0?a.gravity:a.sensitivity)*Time.unscaledDeltaTime);a.frame=Time.frameCount;}v=a.value;}
            if(Mathf.Abs(v)>Mathf.Abs(chosen))chosen=v;
        }
        if(!found)throw new ArgumentException("Input Axis "+name+" is not set up (preserved migration error)");return chosen;
    }
    public static float GetAxis(string name){return ReadAxis(name,false);}
    public static float GetAxisRaw(string name){return ReadAxis(name,true);}
    private static bool Button(string name,int phase){
        bool found=false,result=false;
        foreach(var a in Axes)if(a.name==name){found=true;foreach(var value in new[]{a.positiveButton,a.altPositiveButton,a.negativeButton,a.altNegativeButton}){var c=Control(value);if(c!=null)result|=phase==0?c.isPressed:phase==1?c.wasPressedThisFrame:c.wasReleasedThisFrame;}}
        if(!found)throw new ArgumentException("Input Button "+name+" is not set up (preserved migration error)");return result;
    }
    public static bool GetButton(string name){return Button(name,0);}
    public static bool GetButtonDown(string name){return Button(name,1);}
    public static bool GetButtonUp(string name){return Button(name,2);}
}
