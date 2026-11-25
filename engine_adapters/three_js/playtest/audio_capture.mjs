/** Per-page WebAudio output tap. Runs before game code; never uses a microphone. */
export function installAudioCapture() {
  const NativeContext = globalThis.AudioContext || globalThis.webkitAudioContext;
  if (!NativeContext || !globalThis.AudioNode) return;
  const connect = AudioNode.prototype.connect;
  const disconnect = AudioNode.prototype.disconnect;
  const captures = new Map();
  const errors = [];
  const capture = { captures, errors, mediaPlayed: false, timing: [] };
  globalThis.__A3GAME_AUDIO_CAPTURE__ = capture;
  document.addEventListener('play', (event) => {
    if (event.target instanceof HTMLMediaElement) capture.mediaPlayed = true;
  }, true);
  // Existing audio routing remains intact; mirror only nodes sent to destination.
  AudioNode.prototype.connect = function (destination, ...args) {
    const result = connect.call(this, destination, ...args);
    const record = captures.get(this.context);
    if (record && destination === this.context.destination && this !== record.processor) {
      try { connect.call(this, record.tap, args[0] || 0, 0); }
      catch (error) { errors.push(String(error.message || error).slice(0, 120)); }
    }
    return result;
  };
  AudioNode.prototype.disconnect = function (...args) {
    const record = captures.get(this.context);
    const result = disconnect.apply(this, args);
    if (record && args[0] === this.context.destination) {
      try { disconnect.call(this, record.tap); } catch { /* already disconnected */ }
    }
    return result;
  };
  function RecordedContext(...args) {
    const ctx = new NativeContext(...args);
    try {
      const tap = ctx.createGain();
      const processor = ctx.createScriptProcessor(4096, 2, 2);
      const record = { tap, processor, rate: ctx.sampleRate, blocks: [], frames: 0,
        startContextTime: null, overflow: false, gaps: false, previousEnd: null };
      captures.set(ctx, record);
      connect.call(tap, processor);
      // Silent processor output keeps the observation branch running.
      connect.call(processor, ctx.destination);
      processor.onaudioprocess = (event) => {
        const input = event.inputBuffer;
        if (record.startContextTime === null) record.startContextTime = event.playbackTime;
        if (record.previousEnd !== null && Math.abs(event.playbackTime - record.previousEnd) > 0.01) record.gaps = true;
        record.previousEnd = event.playbackTime + input.length / ctx.sampleRate;
        if (record.frames + input.length > ctx.sampleRate * 180) { record.overflow = true; return; }
        const left = input.getChannelData(0);
        const right = input.numberOfChannels > 1 ? input.getChannelData(1) : left;
        const block = new Int16Array(input.length * 2);
        for (let i = 0; i < input.length; i++) {
          block[2*i] = Math.round(Math.max(-1, Math.min(1, left[i])) * 32767);
          block[2*i+1] = Math.round(Math.max(-1, Math.min(1, right[i])) * 32767);
        }
        record.blocks.push(block);
        record.frames += input.length;
      };
    } catch (error) { errors.push(String(error.message || error).slice(0, 120)); }
    return ctx;
  }
  RecordedContext.prototype = NativeContext.prototype;
  Object.setPrototypeOf(RecordedContext, NativeContext);
  globalThis.AudioContext = RecordedContext;
  if (globalThis.webkitAudioContext) globalThis.webkitAudioContext = RecordedContext;
}

export function sampleAudioClock(simulationMs) {
  const capture = globalThis.__A3GAME_AUDIO_CAPTURE__;
  if (!capture) return;
  capture.timing.push({ simulation_t_ms: simulationMs, performance_t_ms: performance.now(),
    contexts: [...capture.captures.keys()].map(ctx => ({ context_time_s: ctx.currentTime, state: ctx.state })) });
}

export function exportAudioCapture() {
  const capture = globalThis.__A3GAME_AUDIO_CAPTURE__;
  const failure = (error) => ({ metadata: { status: 'unavailable', source: 'game_output', error } });
  if (!capture) return failure('WebAudio API unavailable');
  if (capture.errors.length) return failure(`audio_tap_error: ${capture.errors[0]}`);
  if (capture.mediaPlayed) return failure('HTMLMediaElement playback not captured by WebAudio tap');
  if (capture.captures.size !== 1) return failure(capture.captures.size ? 'multiple_audio_contexts_not_mixed' : 'no_audio_context');
  const record = [...capture.captures.values()][0];
  if (!record.frames) return failure('no_audio_samples');
  if (record.overflow || record.gaps) return failure(record.overflow ? 'audio_duration_limit' : 'audio_callback_gaps');
  const bytes = new Uint8Array(record.frames * 4);
  let cursor = 0;
  for (const block of record.blocks) {
    const view = new DataView(bytes.buffer);
    for (const sample of block) { view.setInt16(cursor, sample, true); cursor += 2; }
  }
  let binary = '';
  for (let i = 0; i < bytes.length; i += 8192) binary += String.fromCharCode(...bytes.subarray(i, i+8192));
  return { pcm_base64: btoa(binary), sample_rate: record.rate, metadata: {
    status: 'captured', source: 'game_output', clock: 'browser_audio_context_ms',
    start_t_ms: record.startContextTime * 1000, duration_s: record.frames / record.rate,
    synchronization_precision: 'audio callback; fixed simulation requires clock mapping; not frame exact',
    clock_mapping: capture.timing, channels: 2,
  }};
}

export function pcmWav(pcm, rate, channels = 2) {
  const header = Buffer.alloc(44);
  header.write('RIFF', 0); header.writeUInt32LE(36 + pcm.length, 4); header.write('WAVEfmt ', 8);
  header.writeUInt32LE(16, 16); header.writeUInt16LE(1, 20); header.writeUInt16LE(channels, 22);
  header.writeUInt32LE(rate, 24); header.writeUInt32LE(rate * channels * 2, 28);
  header.writeUInt16LE(channels * 2, 32); header.writeUInt16LE(16, 34);
  header.write('data', 36); header.writeUInt32LE(pcm.length, 40);
  return Buffer.concat([header, pcm]);
}
