// Runtime-only observer attached to the existing AudioListener during evaluation.
// Never mutates the audio samples or records the microphone.
using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using UnityEngine;

public sealed class GameFactory3AAudioTap : MonoBehaviour
{
    private readonly object gate = new object();
    private FileStream stream;
    private string output;
    private int rate, channels;
    private long bytes, origin;
    private double initialOffsetMs, firstSampleMs = -1, maximumDurationSeconds;
    private bool finished, overflow;
    private string error;

    [Serializable] private sealed class Capture
    {
        public string status, source = "game_output", clock = "monotonic_session_ms", error;
        public string synchronization_precision = "listener DSP buffer; not sample-aligned to frames";
        public double start_t_ms, end_t_ms, duration_s, expected_duration_s;
        public bool coverage_complete;
        public int sample_rate, channels;
    }

    public void Begin(string directory, double offsetMs, double durationSeconds)
    {
        lock (gate)
        {
            if (double.IsNaN(durationSeconds) || double.IsInfinity(durationSeconds) || durationSeconds <= 0 || durationSeconds > 3600)
                throw new ArgumentOutOfRangeException("durationSeconds");
            maximumDurationSeconds = durationSeconds;
            output = directory; rate = AudioSettings.outputSampleRate;
            initialOffsetMs = offsetMs; origin = Stopwatch.GetTimestamp();
            Directory.CreateDirectory(output);
            stream = new FileStream(Path.Combine(output, "audio.wav"), FileMode.CreateNew, FileAccess.Write, FileShare.Read);
            stream.Write(new byte[44], 0, 44);
        }
    }

    private void OnAudioFilterRead(float[] data, int channelCount)
    {
        lock (gate)
        {
            if (stream == null || finished || error != null) return;
            try
            {
                if (channels != 0 && channels != channelCount) { error = "audio_channel_count_changed"; return; }
                channels = channelCount;
                if (firstSampleMs < 0) firstSampleMs = initialOffsetMs +
                    (Stopwatch.GetTimestamp() - origin) * 1000.0 / Stopwatch.Frequency;
                if (bytes + data.Length * 2L > Math.Min(rate * channelCount * 2.0 * (maximumDurationSeconds + 2), int.MaxValue - 44L))
                { overflow = true; return; }
                var pcm = new byte[data.Length * 2];
                for (int i = 0; i < data.Length; i++)
                {
                    short value = (short)(Math.Max(-1.0, Math.Min(1.0, data[i])) * 32767);
                    pcm[2*i] = (byte)(value & 255); pcm[2*i+1] = (byte)((value >> 8) & 255);
                }
                stream.Write(pcm, 0, pcm.Length); bytes += pcm.Length;
            }
            catch (Exception) { error = "audio_write_failed"; }
        }
    }

    public void Finish()
    {
        Capture metadata;
        lock (gate)
        {
            if (finished || output == null) return;
            finished = true;
            try
            {
                if (stream != null)
                {
                    stream.Position = 0;
                    using (var writer = new BinaryWriter(stream, Encoding.UTF8, true))
                    {
                        writer.Write(Encoding.ASCII.GetBytes("RIFF")); writer.Write((int)(36 + bytes));
                        writer.Write(Encoding.ASCII.GetBytes("WAVEfmt ")); writer.Write(16); writer.Write((short)1);
                        writer.Write((short)Math.Max(1, channels)); writer.Write(rate);
                        writer.Write(rate * Math.Max(1, channels) * 2); writer.Write((short)(Math.Max(1, channels) * 2));
                        writer.Write((short)16); writer.Write(Encoding.ASCII.GetBytes("data")); writer.Write((int)bytes);
                    }
                    stream.Dispose(); stream = null;
                }
            }
            catch (Exception) { error = "wav_finalize_failed"; }
            double duration = channels > 0 && rate > 0 ? bytes / (double)(rate * channels * 2) : 0;
            bool complete = duration >= maximumDurationSeconds - 0.5;
            metadata = new Capture { status = bytes > 0 && error == null && !overflow ? (complete ? "captured" : "partial") : "capture_failed",
                error = error ?? (overflow ? "audio_duration_limit" : (bytes == 0 ? "no_listener_samples" : (!complete ? "listener_capture_ended_before_take" : null))),
                start_t_ms = Math.Max(0, firstSampleMs), end_t_ms = Math.Max(0, firstSampleMs) + duration * 1000,
                duration_s = duration, expected_duration_s = maximumDurationSeconds, coverage_complete = complete,
                sample_rate = rate, channels = channels };
        }
        File.WriteAllText(Path.Combine(output, "audio_capture.json"), JsonUtility.ToJson(metadata, true));
    }
    // Play-mode exit/domain reload must finalize before this observer is destroyed.
    private void OnDisable() { Finish(); }
    private void OnDestroy() { Finish(); }
}
