// Passive observer: waits for a fully rendered GameView before reading pixels.
// No game functions, input providers, camera settings or gameplay state are changed.
using System;
using System.Collections;
using UnityEngine;

[DefaultExecutionOrder(-32000)]
public sealed class GameFactory3AFrameTap : MonoBehaviour
{
    private bool pending;
    private System.Reflection.MethodInfo _manualInputUpdate;
    public int manualInputUpdates;
    public Func<bool> beforeManualInputUpdate;
    private void Update()
    {
        if (Environment.GetEnvironmentVariable("GAMEFACTORY_UNITY_CAPTURE_POLICY") != "graphics_batch_render_v2") return;
        if (_manualInputUpdate == null)
        {
            foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
            {
                if (assembly.GetName().Name != "Unity.InputSystem") continue;
                var type = assembly.GetType("UnityEngine.InputSystem.InputSystem");
                _manualInputUpdate = type.GetMethod("Update", System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Static, null, Type.EmptyTypes, null);
            }
        }
        if (_manualInputUpdate != null) { if (beforeManualInputUpdate != null && !beforeManualInputUpdate()) return; _manualInputUpdate.Invoke(null, null); if (beforeManualInputUpdate != null) beforeManualInputUpdate(); manualInputUpdates++; }
    }
    public void Request(Action captureStarting, Action<Texture2D, string> completed)
    {
        if (pending) throw new InvalidOperationException("screenshot request already pending");
        pending = true;
        StartCoroutine(ReadFrame(captureStarting, completed));
    }
    private IEnumerator ReadFrame(Action captureStarting, Action<Texture2D, string> completed)
    {
        yield return new WaitForEndOfFrame();
        Texture2D image = null;
        string error = null;
        try
        {
            captureStarting();
            image = CaptureScreen();
        }
        catch (Exception exception) { error = exception.Message; }
        pending = false;
        completed(image, error);
    }

    private Texture2D CaptureScreen()
    {
        // Read the rendered backbuffer at end-of-frame, including overlay UI.
        // Never re-render Camera.main or modify a delivered camera's target:
        // doing so lost OnGUI/canvas results and broke camera-less UI scenes.
        int width = Screen.width;
        int height = Screen.height;
        if (width <= 0 || height <= 0)
            throw new InvalidOperationException("GameView backbuffer has no usable dimensions");
        RenderTexture previous = RenderTexture.active;
        Texture2D image = null;
        try
        {
            RenderTexture.active = null;
            image = new Texture2D(width, height, TextureFormat.RGB24, false);
            image.ReadPixels(new Rect(0, 0, width, height), 0, 0, false);
            image.Apply(false, false);
            return image;
        }
        catch
        {
            if (image != null) UnityEngine.Object.Destroy(image);
            throw;
        }
        finally { RenderTexture.active = previous; }
    }
}
