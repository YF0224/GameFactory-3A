using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Video;

namespace A3Game.EngineAdapters
{
    /// <summary>
    /// Canonical runtime surface for gameplay-triggered audio, video CG and VFX.
    /// Game code supplies event keys; the director owns native AudioSource,
    /// VideoPlayer and ParticleSystem calls and exposes an evidence-friendly log.
    /// </summary>
    public sealed class A3GameMediaDirector : MonoBehaviour
    {
        [Serializable]
        public sealed class MediaEvent
        {
            public string schema_version = "gamefactory3a.media_runtime_event.v1";
            public int seq;
            public long t_monotonic_ms;
            public string event_type;
            public string event_key;
            public string trigger_source;
            public bool playback_call_issued;
            public string asset_path;
        }

        private readonly Dictionary<string, AudioClip> _audio = new Dictionary<string, AudioClip>();
        private readonly Dictionary<string, string> _cgUrls = new Dictionary<string, string>();
        private readonly Dictionary<string, ParticleSystem> _vfx = new Dictionary<string, ParticleSystem>();
        private readonly Dictionary<string, AnimationBinding> _animations = new Dictionary<string, AnimationBinding>();
        private readonly List<MediaEvent> _events = new List<MediaEvent>();

        private sealed class AnimationBinding
        {
            public Animator animator;
            public string stateName;
            public int layer;
        }
        private AudioSource _audioSource;
        private VideoPlayer _videoPlayer;
        private RenderTexture _videoTarget;
        private int _sequence;
        private bool _gameplayPaused;

        /// <summary>Raised when a CG acquires/releases the combat-only pause lock.</summary>
        public event Action<bool> GameplayPauseChanged;

        /// <summary>True while the current CG owns the combat lock.</summary>
        public bool IsGameplayPaused => _gameplayPaused;
        private long _startedAtMs;

        public IReadOnlyList<MediaEvent> Events => _events;
        public VideoPlayer VideoPlayer => _videoPlayer;
        public RenderTexture VideoTarget => _videoTarget;

        private void Awake()
        {
            _startedAtMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            _audioSource = GetComponent<AudioSource>() ?? gameObject.AddComponent<AudioSource>();
            _audioSource.playOnAwake = false;
            _videoPlayer = GetComponent<VideoPlayer>() ?? gameObject.AddComponent<VideoPlayer>();
            _videoPlayer.playOnAwake = false;
            _videoPlayer.isLooping = false;
            _videoPlayer.renderMode = VideoRenderMode.RenderTexture;
            _videoTarget = new RenderTexture(640, 348, 0, RenderTextureFormat.ARGB32);
            _videoTarget.Create();
            _videoPlayer.targetTexture = _videoTarget;
        }

        public bool RegisterAudio(string eventKey, AudioClip clip)
        {
            if (string.IsNullOrWhiteSpace(eventKey) || clip == null) return false;
            _audio[eventKey] = clip;
            return true;
        }

        public bool RegisterCG(string eventKey, string videoUrl)
        {
            if (string.IsNullOrWhiteSpace(eventKey) || string.IsNullOrWhiteSpace(videoUrl)) return false;
            _cgUrls[eventKey] = videoUrl;
            return true;
        }

        public bool RegisterAnimation(string eventKey, Animator animator, string stateName, int layer = 0)
        {
            if (string.IsNullOrWhiteSpace(eventKey) || animator == null || string.IsNullOrWhiteSpace(stateName)) return false;
            _animations[eventKey] = new AnimationBinding { animator = animator, stateName = stateName, layer = layer };
            return true;
        }

        public MediaEvent TriggerAnimation(string eventKey, string triggerSource = "gameplay")
        {
            AnimationBinding binding;
            bool issued = _animations.TryGetValue(eventKey, out binding) && binding != null && binding.animator != null;
            if (issued) binding.animator.Play(binding.stateName, binding.layer, 0f);
            return Record("cg_animation_triggered", eventKey, triggerSource, issued,
                issued ? "Animator:" + binding.stateName : "");
        }

        public bool RegisterVFX(string eventKey, ParticleSystem effect)
        {
            if (string.IsNullOrWhiteSpace(eventKey) || effect == null) return false;
            _vfx[eventKey] = effect;
            effect.Stop(true, ParticleSystemStopBehavior.StopEmittingAndClear);
            return true;
        }

        public MediaEvent TriggerVFX(string eventKey, string triggerSource = "gameplay")
        {
            ParticleSystem effect;
            bool issued = _vfx.TryGetValue(eventKey, out effect) && effect != null;
            if (issued)
            {
                effect.Stop(true, ParticleSystemStopBehavior.StopEmittingAndClear);
                effect.Play(true);
            }
            return Record("vfx_triggered", eventKey, triggerSource, issued,
                issued ? "ParticleSystem:" + effect.name : "");
        }

        public MediaEvent StopVFX(string eventKey, string triggerSource = "gameplay")
        {
            ParticleSystem effect;
            bool issued = _vfx.TryGetValue(eventKey, out effect) && effect != null;
            if (issued) effect.Stop(true, ParticleSystemStopBehavior.StopEmittingAndClear);
            return Record("vfx_stopped", eventKey, triggerSource, issued,
                issued ? "ParticleSystem:" + effect.name : "");
        }

        public MediaEvent TriggerAudio(string eventKey, string triggerSource = "gameplay")
        {
            AudioClip clip;
            bool issued = _audio.TryGetValue(eventKey, out clip) && clip != null && _audioSource != null;
            if (issued) _audioSource.PlayOneShot(clip);
            return Record("audio_triggered", eventKey, triggerSource, issued,
                issued ? "AudioClip:" + clip.name : "");
        }

        public MediaEvent TriggerCG(string eventKey, string triggerSource = "gameplay")
        {
            string url;
            bool issued = _cgUrls.TryGetValue(eventKey, out url) && !string.IsNullOrWhiteSpace(url) && _videoPlayer != null;
            if (issued)
            {
                SetGameplayPaused(true);
                _videoPlayer.url = url;
                _videoPlayer.isLooping = false;
                _videoPlayer.Play();
            }
            return Record("cg_triggered", eventKey, triggerSource, issued, issued ? url : "");
        }

        public MediaEvent[] GetEventLog() => _events.ToArray();

        /// <summary>Release the combat lock when the caller stops the CG.</summary>
        public void StopCG(string eventKey, string triggerSource = "gameplay")
        {
            if (_videoPlayer != null)
                _videoPlayer.Stop();
            SetGameplayPaused(false);
        }

        /// <summary>Called by a VideoPlayer loopPointReached/error callback.</summary>
        public void NotifyCGFinished(bool success)
        {
            SetGameplayPaused(false);
        }

        private void SetGameplayPaused(bool paused)
        {
            if (_gameplayPaused == paused)
                return;
            _gameplayPaused = paused;
            GameplayPauseChanged?.Invoke(paused);
        }

        private void OnDestroy()
        {
            if (_videoTarget != null)
            {
                _videoTarget.Release();
                Destroy(_videoTarget);
            }
        }

        private MediaEvent Record(string type, string key, string source, bool issued, string assetPath)
        {
            var item = new MediaEvent
            {
                seq = ++_sequence,
                t_monotonic_ms = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - _startedAtMs,
                event_type = type,
                event_key = key,
                trigger_source = source,
                playback_call_issued = issued,
                asset_path = assetPath
            };
            _events.Add(item);
            return item;
        }
    }
}
