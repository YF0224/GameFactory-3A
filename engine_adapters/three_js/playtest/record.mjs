#!/usr/bin/env node
/**
 * Fixed-tick A3Game capture: --url URL --output-dir BASE (1280x720, 20fps, 14s).
 * --preview / --poster writes one PNG; --mode overview uses an optional game camera hook.
 * Plans use keyboard/pointer events; simulation advances independently of capture speed.
 * Every invocation preserves a unique take. Only a verified MP4 receives `completed`;
 * PNG-only success is `preview_completed`. --source-hash labels the captured build.
 */

import { mkdir, mkdtemp, readFile, rename, stat, writeFile } from 'node:fs/promises';
import { appendFileSync, existsSync, mkdtempSync, readFileSync, renameSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';
import assert from 'node:assert/strict';
import path from 'node:path';
import { EventSnapshots } from './event_snapshots.mjs';
import { actionMetadata } from './action_provenance.mjs';
import { navigateWithRetry, ensureInputFocus } from './browser_runtime.mjs';
import { installAudioCapture, sampleAudioClock, exportAudioCapture, pcmWav } from './audio_capture.mjs';

function parseArgs(argv) {
  const out = {};
  const supported = new Set(['url', 'output-dir', 'duration', 'fps', 'width', 'height',
    'playwright-root', 'browser-executable', 'action-plan', 'look', 'warmup', 'hold',
    'mode', 'clock', 'allow-partial-plan', 'self-test', 'preview', 'poster', 'source-hash',
    'software-renderer', 'capture-schedule']);
  for (let i = 2; i < argv.length; i += 1) {
    const key = argv[i].slice(2);
    if (!argv[i].startsWith('--') || !supported.has(key)) throw new Error(`Unknown option: ${argv[i]}`);
    if (['self-test', 'allow-partial-plan', 'preview', 'poster', 'software-renderer'].includes(key) && (!argv[i + 1] || argv[i + 1].startsWith('--'))) {
      out[key] = 'true';
    } else {
      if (!argv[i + 1] || argv[i + 1].startsWith('--')) throw new Error(`Missing value for --${key}`);
      out[key] = argv[++i];
    }
  }
  return out;
}

/**
 * Discover {actions, sustained, warmup, look}, returning only serializable plan fields.
 * Priority: declared plan, action/key bindings, DOM actions, generic keyboard fallback.
 * `sustained` holds keyboard inputs through warmup and capture; `warmup` is unrecorded
 * simulation time; `look` selects auto/off/pan. Keyboard inputs use event.code.
 */
const DISCOVERY = () => {
  const game = globalThis.__A3GAME_GAME__;
  const input = game?.input;

  // Binding inference uses substring matching; discrete verbs override holds.
  const HELD = new RegExp([
    'forward|back|left|right|up|down|strafe|ascend|descend|thrust|yaw|pitch|roll',
    'run|walk|sprint|dash|crouch|sneak|prone|slide|swim|climb|hover|fly|glide',
    'accel|throttle|brake|boost|nitro|nos|drift|gas|handbrake|ebrake|clutch',
    'draw|charge|aim|zoom|scope|focus|hold|pull|push|drag|carry|grab|grapple',
    'block|guard|defend|shield|parry|brace|cover',
    'auto|spray|beam|burn|heal|repair|mine|dig|build|paint|spray',
    'interact|use|open|channel|cast|revive|capture|hack|lockpick',
    'look|turn|pan|orbit|lean|peek|freelook',
  ].join('|'), 'i');
  const TAPPED = /toggle|switch|cycle|next|prev|swap|select|equip|holster|sheathe|reload|jump|hop|dodge|roll_dodge|evade|blink|teleport|respawn|reset|restart|pause|menu|map|inventory|emote|taunt|horn|light|flash/i;

  const isHeld = (action) => !TAPPED.test(action) && HELD.test(action);

  const asPlan = (source, actions, extra = {}) => ({ source, actions, ...extra });

  const declared = (() => {
    const exposed = globalThis.__A3GAME_PLAYTEST__ ?? game?.playtestActions;
    let value = exposed?.actions ?? exposed;
    if (typeof value === 'function') value = value();
    if (exposed == null) return null;
    if (!Array.isArray(value)) throw new Error('__A3GAME_PLAYTEST__.actions must be an array');
    const scalar = (item) => ['string', 'number', 'boolean'].includes(typeof item) ? item : undefined;
    const list = (items) => Array.isArray(items) ? items.map(scalar) : undefined;
    const safeActions = value.map((item) => {
      if (!item || typeof item !== 'object') throw new Error('Invalid declared action');
      return Object.fromEntries([
        ...['id', 'name', 'label', 'mouse', 'hold', 'click', 'duration', 'seconds'].map((key) => [key, scalar(item[key])]),
        ...['keys', 'taps'].map((key) => [key, list(item[key])]),
      ]);
    });
    return asPlan('declared', safeActions, {
      sustained: list(exposed?.sustained ?? exposed?.hold),
      warmup: scalar(exposed?.warmup),
      look: scalar(exposed?.look),
    });
  })();
  if (declared) return declared;

  const actions = [];
  const seen = new Set();
  const push = (id, extra) => {
    if (!id || seen.has(id)) return;
    seen.add(id);
    actions.push({ id, label: id, ...extra });
  };
  const bind = (code, action) => {
    if (/^Mouse0$/i.test(code)) push(action, { mouse: true, hold: isHeld(action) });
    else if (/^Mouse/i.test(code)) return;            // only button 0 is emulable
    else if (isHeld(action)) push(action, { keys: [code] });
    else push(action, { taps: [code] });
  };
  for (const [code, action] of Object.entries(input?.actionBindings ?? {})) bind(code, action);
  for (const [code, action] of Object.entries(input?.keyBindings ?? {})) bind(code, action);

  if (actions.length) {
    // Infer sustained throttle only when vehicle-specific bindings exist.
    const drive = actions.find((item) => /^(accel\w*|throttle|gas|forward)$/i.test(item.id));
    const vehicular = /brake|handbrake|ebrake|drift|steer|clutch|nitro|nos|respawn|lap|gear/i;
    const sustained = drive && actions.some((item) => vehicular.test(item.id))
      ? [drive.id]
      : [];
    return asPlan('input_router', actions, { sustained });
  }

  const dom = [...document.querySelectorAll('[data-game-action]')]
    .map((node) => ({
      id: node.getAttribute('data-game-action'),
      label: node.getAttribute('aria-label') || node.textContent?.trim() || '',
      click: '[data-game-action="' + CSS.escape(node.getAttribute('data-game-action') || '') + '"]',
    }))
    .filter((item) => item.id);
  if (dom.length) return asPlan('dom', dom);

  return asPlan('fallback', [
    { id: 'forward', keys: ['KeyW'] },
    { id: 'left', keys: ['KeyA'] },
    { id: 'right', keys: ['KeyD'] },
    { id: 'jump', taps: ['Space'] },
    { id: 'primary', mouse: true },
  ]);
};

/** Map an action name back to the key code that triggers it, for `sustained`. */
const RESOLVE = (names) => {
  const input = globalThis.__A3GAME_GAME__?.input;
  const table = { ...(input?.keyBindings ?? {}), ...(input?.actionBindings ?? {}) };
  return names.map((name) => {
    if (/^(Key|Digit|Arrow|Numpad|F\d)/.test(name) || /^(Space|Shift|Control|Alt|Tab|Enter|Escape)/.test(name)) {
      return { name, code: name };                     // already a code
    }
    const code = Object.entries(table).find(([, action]) => action === name)?.[0];
    return { name, code: code && !/^Mouse/i.test(code) ? code : null };
  });
};

function normalize(raw, source, budgetSeconds, fps, allowPartial = false) {
  if (!Array.isArray(raw)) throw new Error('Plan actions must be an array');
  const codes = (value, name) => {
    if (value === undefined) return [];
    if (!Array.isArray(value) || value.some((code) => typeof code !== 'string' || !code.trim())) {
      throw new Error(`${name} must contain keyboard codes`);
    }
    return [...new Set(value)];
  };
  const actions = raw.map((item, index) => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) throw new Error(`Invalid action ${index}`);
    const seconds = item.duration ?? item.seconds;
    if (seconds !== undefined && (!Number.isFinite(Number(seconds)) || Number(seconds) <= 0)) {
      throw new Error(`Invalid duration for action ${index}`);
    }
    let pointer = null;
    if (item.pointer !== undefined) {
      const p = item.pointer;
      if (!p || !['mouse_move', 'mouse_click', 'mouse_drag', 'mouse_down', 'mouse_up', 'mouse_hold', 'mouse_wheel'].includes(p.kind)) throw new Error(`Invalid pointer gesture ${index}`);
      for (const field of (p.kind === 'mouse_drag' ? ['x', 'y', 'to_x', 'to_y'] : ['x', 'y'])) {
        if (typeof p[field] !== 'number' || !Number.isFinite(p[field]) || p[field] < 0 || p[field] > 1) throw new Error(`Invalid pointer ${field}`);
      }
      if (!['mouse_move', 'mouse_wheel'].includes(p.kind) && !['left', 'right', 'middle'].includes(p.button)) throw new Error('Invalid pointer button');
      if (seconds === undefined || Number(seconds) < .1 || Number(seconds) > 6) throw new Error('Invalid pointer duration');
      if ((item.keys?.length || item.taps?.length || item.mouse || item.click)) throw new Error('Pointer gestures cannot mix legacy keyboard/mouse actions');
      if (p.kind === 'mouse_wheel' && (!Number.isInteger(p.delta_x) || !Number.isInteger(p.delta_y) || Math.abs(p.delta_x) > 1200 || Math.abs(p.delta_y) > 1200 || (!p.delta_x && !p.delta_y))) throw new Error('Invalid wheel delta');
      pointer = { kind: p.kind, x: p.x, y: p.y,
        ...(!['mouse_move', 'mouse_wheel'].includes(p.kind) ? { button: p.button } : {}),
        ...(p.kind === 'mouse_wheel' ? { delta_x: p.delta_x, delta_y: p.delta_y } : {}),
        ...(p.kind === 'mouse_drag' ? { to_x: p.to_x, to_y: p.to_y } : {}) };
    }
    const keys = codes(item.keys, 'keys');
    const taps = codes(item.taps, 'taps');
    if (keys.some((code) => taps.includes(code))) throw new Error(`Action ${index} both holds and taps a key`);
    return {
      ...actionMetadata(item),
      id: String(item.id ?? item.name ?? `${source}_${index + 1}`),
      label: String(item.label ?? item.id ?? ''), keys, taps,
      ...(pointer ? { pointer } : {}),
      mouse: Boolean(item.mouse), hold: Boolean(item.hold),
      click: typeof item.click === 'string' ? item.click : '',
      seconds: seconds === undefined ? null : Number(seconds), source,
    };
  });
  const fixedSeconds = actions.reduce((sum, action) => sum + (action.seconds ?? 0), 0);
  const unspecified = actions.filter((action) => action.seconds === null).length;
  const share = unspecified ? Math.max(1 / fps, (budgetSeconds - fixedSeconds) / unspecified) : 0;
  let elapsed = 0;
  let endFrame = 0;
  for (const action of actions) {
    action.seconds ??= share;
    action.start_frame = endFrame;
    elapsed += action.seconds;
    endFrame = Math.round(elapsed * fps);
    action.planned_frames = endFrame - action.start_frame;
    if (action.planned_frames < 1) {
      // a sub-frame action (a frozen 0.1 s key tap at 5 fps, say) still gets
      // its frame — dropping it would silently skip a frozen-plan action
      // and throwing would kill the whole take; the bump is recorded so
      // the report shows the real capture cadence
      action.planned_frames = 1;
      endFrame = action.start_frame + 1;
      action.sub_frame_bumped = true;
    }
  }
  const budgetFrames = Math.max(1, Math.round(budgetSeconds * fps));
  if (endFrame > budgetFrames && !allowPartial) {
    throw new Error(`Plan needs ${endFrame} frames (${endFrame / fps}s); increase --duration or use --allow-partial-plan for an explicit probe`);
  }
  for (const action of actions) {
    action.frames = Math.max(0, Math.min(action.planned_frames, budgetFrames - action.start_frame));
  }
  return { actions, targetFrames: budgetFrames, planFrames: endFrame, partial: endFrame > budgetFrames };
}

function lookMode(requested, runtimeMode) {
  if (requested === false || requested === 'false') requested = 'off';
  if (!['auto', 'off', 'pan'].includes(requested)) throw new Error('--look must be auto, off, or pan');
  return requested === 'auto' ? (runtimeMode && runtimeMode !== 'drag' ? 'pan' : 'off') : requested;
}

function substeps(dt, maximum = 1 / 60) {
  const count = Math.max(1, Math.ceil(dt / maximum - 1e-9));
  return { count, dt: dt / count };
}

function safeSnapshot() {
  const seen = new WeakSet();
  let budget = 2048;
  const copy = (value, depth = 0) => {
    if (--budget < 0 || depth > 8) return '[truncated]';
    if (value == null || typeof value === 'boolean') return value ?? null;
    if (typeof value === 'number') return Number.isFinite(value) ? value : null;
    if (typeof value === 'string') return value.slice(0, 512);
    if (typeof value !== 'object') return null;
    if (seen.has(value)) return '[circular]';
    if (value.isObject3D || value.isMaterial || value.isBufferGeometry || value.isTexture ||
        value.isWebGLRenderer || (value.tick && value.renderer)) return '[runtime object]';
    if (!Array.isArray(value) && ![Object.prototype, null].includes(Object.getPrototypeOf(value))) return '[non-plain object]';
    seen.add(value);
    try {
      if (Array.isArray(value)) return value.slice(0, 128).map((item) => copy(item, depth + 1));
      const result = {};
      for (const key of Object.keys(value).slice(0, 128)) {
        const descriptor = Object.getOwnPropertyDescriptor(value, key);
        if (descriptor && 'value' in descriptor) result[key] = copy(descriptor.value, depth + 1);
      }
      return result;
    } finally {
      seen.delete(value);
    }
  };
  return copy(globalThis.__A3GAME_GAME__?.getState?.() ?? null);
}

function validateVideo(metadata, frames, fps, width, height) {
  const stream = metadata.streams?.[0];
  const seconds = Number(stream?.duration ?? metadata.format?.duration);
  const [numerator, denominator = 1] = String(stream?.avg_frame_rate ?? '0').split('/').map(Number);
  if (Number(stream?.nb_read_frames) !== frames || stream?.width !== width || stream?.height !== height ||
      Math.abs(numerator / denominator - fps) > 1e-6 || !Number.isFinite(seconds) ||
      Math.abs(seconds - frames / fps) > 0.002) throw new Error('Encoded video frame count, duration, fps, or dimensions do not match the capture');
  return { frames: Number(stream.nb_read_frames), seconds, fps: numerator / denominator, width, height };
}

async function browserAdvance({ dt, maximum, mode, reviewTime, frame, duration, look, yaw, pitch }) {
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('Fixed tick/compositor timed out')), 30_000);
    requestAnimationFrame(() => {
      try {
        const game = globalThis.__A3GAME_GAME__;
        const host = game.host;
        if (look === 'pan' && reviewTime !== null) {
          game.input.setLook(yaw + Math.sin(reviewTime * 0.35) * 0.28, pitch + Math.sin(reviewTime * 0.6) * 0.06);
        }
        if (dt > 0) {
          const internal = Number(host.options?.fixedTimeStep ?? 0);
          const canAccumulate = internal > 0 && Number(host.options.maxFrameDelta) >= dt &&
            Number(host.options.maxSubSteps) >= Math.ceil(dt / internal) + 1;
          const count = canAccumulate ? 1 : Math.max(1, Math.ceil(dt / maximum - 1e-9));
          for (let i = 0; i < count; i += 1) host.tick(dt / count);
        }
        if (mode === 'overview' && reviewTime !== null) {
          if (typeof globalThis.__A3GAME_REVIEW__ === 'function') globalThis.__A3GAME_REVIEW__({ mode, time: reviewTime, frame, dt, duration });
          host.renderer.render(host.scene, host.camera);
        } else if (dt === 0) host.renderer.render(host.scene, host.camera);
        requestAnimationFrame(() => { clearTimeout(timer); resolve(); });
      } catch (error) { clearTimeout(timer); reject(error); }
    });
  });
}

async function selfTest() {
  const test = (name, run) => { run(); console.log(`ok - ${name}`); };
  test('CLI defaults and flag validation', () => {
    assert.equal(parseArgs(['node', 'record', '--self-test'])['self-test'], 'true');
    assert.equal(parseArgs(['node', 'record', '--preview']).preview, 'true');
    assert.equal(parseArgs(['node', 'record', '--poster', '--width', '1280']).poster, 'true');
    assert.equal(parseArgs(['node', 'record', '--source-hash', 'AbC0123'])['source-hash'], 'AbC0123');
    assert.equal(parseArgs(['node', 'record', '--software-renderer'])['software-renderer'], 'true');
    assert.throws(() => parseArgs(['node', 'record', '--look']), /Missing value/);
    assert.throws(() => parseArgs(['node', 'record', '--typo', 'x']), /Unknown option/);
  });
  test('cumulative boundaries preserve exact total frames', () => {
    const plan = normalize(Array.from({ length: 3 }, (_, id) => ({ id, seconds: 0.075 })), 'plan', 0.225, 20);
    assert.deepEqual(plan.actions.map((action) => action.frames), [2, 1, 2]);
    assert.equal(plan.targetFrames, 5);
  });
  test('probe origins survive plan normalization and durable action traces', () => {
    const metadata = { action_id: 'probe-03/step-02', probe_id: 'probe-03', step_id: 'step-02',
      criterion_ids: ['C2.03'], purpose: 'Attack target', expected_observation: 'HP decreases',
      planned_t_ms: 100, planned_end_t_ms: 200 };
    const plan = normalize([{ ...metadata, seconds: .1, keys: ['Space'] }], 'plan', .1, 20);
    assert.deepEqual(actionMetadata(plan.actions[0]), metadata);
    const dir = mkdtempSync(path.join(tmpdir(), 'a3game-provenance-'));
    try {
      const writer = makeTraceWriter(dir, { fps: 20, requestedSeconds: .1, startedAt: Date.now(),
        targetFrames: () => 2, frames: () => 2, simulatedSeconds: () => .1, lastFrameFile: () => '' });
      writer.action({ ...plan.actions[0], index: 0, ok: true });
      writer.flush();
      const row = JSON.parse(readFileSync(path.join(dir, 'actions.jsonl'), 'utf8').trim());
      assert.deepEqual(actionMetadata(row), metadata);
    } finally { rmSync(dir, { recursive: true, force: true }); }
  });
  test('explicit plans are never silently truncated or reordered', () => {
    const raw = [{ id: 'restart', seconds: 1 }, { id: 'brake', seconds: 1 }];
    assert.throws(() => normalize(raw, 'declared', 1, 20), /Plan needs/);
    const plan = normalize(raw, 'declared', 1, 20, true);
    assert.deepEqual(plan.actions.map((action) => action.id), ['restart', 'brake']);
    assert.deepEqual(plan.actions.map((action) => action.frames), [20, 0]);
    assert.equal(plan.partial, true);
  });
  test('idle tails and single frame takes retain requested duration', () => {
    assert.equal(normalize([], 'overview', 0.01, 20).targetFrames, 1);
    assert.equal(normalize([{ seconds: 1 }], 'plan', 3, 20).targetFrames, 60);
    assert.throws(() => normalize([{ seconds: 1.5 }], 'plan', 1, 20), /Plan needs/);
    assert.throws(() => normalize([{ keys: ['KeyW'], taps: ['KeyW'] }], 'plan', 1, 20), /both holds and taps/);
  });
  test('sub-frame actions bump to one frame instead of dying or vanishing', () => {
    // a frozen 0.1 s tap at 5 fps can round to zero frames — it must still
    // execute (one frame, recorded), never throw away the take or skip
    // the frozen action
    const plan = normalize([{ id: 'wait', seconds: 7.32 },
                             { id: 'jump', seconds: 0.1 },
                             { id: 'wait', seconds: 1 }], 'plan', 10, 5);
    const jump = plan.actions[1];
    assert.equal(jump.planned_frames, 1);
    assert.equal(jump.sub_frame_bumped, true);
    // the bump keeps the plan contiguous: the next action starts right after
    assert.equal(plan.actions[2].start_frame, jump.start_frame + 1);
    assert.ok(plan.actions[2].planned_frames >= 1);
    // an exactly-one-frame action is not flagged
    const exact = normalize([{ id: 'tap', seconds: 0.2 }], 'plan', 1, 5);
    assert.equal(exact.actions[0].planned_frames, 1);
    assert.notEqual(exact.actions[0].sub_frame_bumped, true);
  });
  test('look off preserves camera; pan is explicit and validated', () => {
    assert.equal(lookMode('off', 'pointerlock'), 'off');
    assert.equal(lookMode(false, 'pointerlock'), 'off');
    assert.equal(lookMode('false', 'pointerlock'), 'off');
    assert.equal(lookMode('auto', 'drag'), 'off');
    assert.equal(lookMode('pan', ''), 'pan');
    assert.throws(() => lookMode('orbit', 'drag'), /--look/);
  });
  test('20 and 30fps advance full simulation time without delta clamps', () => {
    for (const fps of [1, 20, 30, 60]) {
      const step = substeps(1 / fps);
      assert.ok(step.dt <= 1 / 60 + 1e-12);
      assert.ok(Math.abs(step.count * step.dt * fps - 1) < 1e-12);
    }
    assert.equal(substeps(1 / 20).count, 3);
  });
  test('a plan keeps the same action seconds at any capture fps', () => {
    const raw = [{ id: 'wait', seconds: 2 }, { id: 'tap', seconds: 0.5 }];
    const plan20 = normalize(raw, 'plan', 4, 20);
    const plan5 = normalize(raw, 'plan', 4, 5);
    for (const [index, seconds] of [[0, 2], [1, 0.5]]) {
      assert.ok(Math.abs(plan20.actions[index].seconds - seconds) < 1e-9);
      assert.ok(Math.abs(plan5.actions[index].seconds - seconds) < 1e-9);
    }
    assert.equal(plan20.actions[0].frames, 40);
    assert.equal(plan5.actions[0].frames, 10);
    assert.equal(plan5.targetFrames, 20);
  });
  test('trace writer flushes bounded batches and stays durable mid-take', () => {
    const dir = mkdtempSync(path.join(tmpdir(), 'a3game-trace-'));
    try {
      const progress = { fps: 5, requestedSeconds: 4, startedAt: Date.now(),
        targetFrames: () => 20, frames: () => 10, simulatedSeconds: () => 2,
        lastFrameFile: () => 'f000009.jpg' };
      const writer = makeTraceWriter(dir, progress);
      // lazy creation: a channel with no rows stays absent, never empty
      assert.equal(existsSync(path.join(dir, 'state_trace.jsonl')), false);
      writer.push('states', { t_ms: 0, state: { a: 1 } });
      writer.push('events', { t_ms: 200, event: 'jump_takeoff', payload: {} });
      writer.action({ index: 0, id: 'wait_1', start_frame: 0, frames: 10, ok: true });
      const live = writer.flush();
      assert.equal(live.status, 'recording');
      assert.equal(live.channels_written.actions, 1);
      assert.equal(live.channels_written.states, 1);
      assert.equal(live.channels_written.events, 1);
      assert.equal(live.recorded_seconds, 2);
      assert.equal(live.last_frame, 'f000009.jpg');
      const states = readFileSync(path.join(dir, 'state_trace.jsonl'), 'utf8').trim().split('\n').map(JSON.parse);
      assert.equal(states[0].state.a, 1);
      // the next flush writes only the new tail — rows are never duplicated
      writer.push('states', { t_ms: 1000, state: { a: 2 } });
      writer.flush();
      const rows = readFileSync(path.join(dir, 'state_trace.jsonl'), 'utf8').trim().split('\n');
      assert.equal(rows.length, 2);
      assert.equal(writer.counts.states, 2);
      // a failed action carries its honest send verdict
      writer.action({ index: 1, id: 'jump_2', start_frame: 10, frames: 2, ok: false, error: 'boom' });
      writer.flush('terminated', { reason: 'SIGTERM' });
      const actions = readFileSync(path.join(dir, 'actions.jsonl'), 'utf8').trim().split('\n').map(JSON.parse);
      assert.equal(actions[0].sent, true);
      assert.equal(actions[1].sent, false);
      assert.ok(actions[1].error.includes('boom'));
      const final = JSON.parse(readFileSync(path.join(dir, 'recording_progress.json'), 'utf8'));
      assert.equal(final.status, 'terminated');
      assert.equal(final.reason, 'SIGTERM');
      assert.equal(final.channels_written.actions, 2);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
  test('state serialization is bounded and rejects THREE graphs', () => {
    const previous = globalThis.__A3GAME_GAME__;
    try {
      const state = { score: 2, object: { isObject3D: true }, huge: Array(10000).fill('a'.repeat(1000)) };
      state.self = state;
      globalThis.__A3GAME_GAME__ = { getState: () => state };
      const result = safeSnapshot();
      assert.equal(result.score, 2);
      assert.equal(result.object, '[runtime object]');
      assert.equal(result.self, '[circular]');
      assert.ok(JSON.stringify(result).length < 70000);
    } finally { globalThis.__A3GAME_GAME__ = previous; }
  });
  test('shared player aliases are copied while actual recursion cycles stay bounded', () => {
    const previous = globalThis.__A3GAME_GAME__;
    try {
      const player = { isPlayer: true, checkpointsPassed: 8, speedKph: 40 };
      const standings = [player];
      const state = { racers: standings, standings, player, shared: [player, player] };
      player.self = player;
      globalThis.__A3GAME_GAME__ = { getState: () => state };
      const result = safeSnapshot();
      assert.equal(result.player.checkpointsPassed, 8);
      assert.deepEqual(result.player, result.racers[0]);
      assert.deepEqual(result.standings, result.racers);
      assert.deepEqual(result.shared[0], result.shared[1]);
      assert.equal(result.player.self, '[circular]');
      assert.notEqual(result.player, result.racers[0]);
      assert.ok(JSON.stringify(result).length < 2048);
    } finally { globalThis.__A3GAME_GAME__ = previous; }
  });
  test('completion requires verified MP4, including single frame takes', () => {
    const metadata = { streams: [{ nb_read_frames: '1', duration: '0.05', avg_frame_rate: '20/1', width: 1280, height: 720 }] };
    assert.equal(validateVideo(metadata, 1, 20, 1280, 720).seconds, 0.05);
    assert.throws(() => validateVideo(metadata, 2, 20, 1280, 720), /do not match/);
    assert.throws(() => validateVideo({}, 1, 20, 1280, 720), /do not match/);
  });
  const previous = { game: globalThis.__A3GAME_GAME__, review: globalThis.__A3GAME_REVIEW__, raf: globalThis.requestAnimationFrame };
  try {
    const ticks = [];
    let lookCalls = 0;
    let renders = 0;
    const host = { options: {}, renderer: { render() { renders += 1; return host; } }, tick(dt) { ticks.push(dt); return this; } };
    host.self = host;
    globalThis.__A3GAME_GAME__ = { host, input: { setLook(yaw, pitch) {
      lookCalls += 1;
      assert.ok(Math.abs(yaw - 1) <= 0.28 + 1e-12);
      assert.ok(Math.abs(pitch - 0.1) <= 0.06 + 1e-12);
      return this;
    } } };
    globalThis.requestAnimationFrame = (callback) => queueMicrotask(() => callback(0));
    const frame = { dt: 0.05, maximum: 1 / 60, mode: 'gameplay', reviewTime: 0.05, frame: 0, duration: 1, look: 'off', yaw: 1, pitch: 0.1 };
    assert.equal(await browserAdvance(frame), undefined);
    assert.equal(ticks.length, 3);
    assert.ok(Math.abs(ticks.reduce((a, b) => a + b, 0) - 0.05) < 1e-12);
    assert.equal(lookCalls, 0);
    host.options = { fixedTimeStep: 1 / 60, maxFrameDelta: 0.1, maxSubSteps: 6 };
    ticks.length = 0;
    await browserAdvance({ ...frame, look: 'pan' });
    assert.equal(ticks.length, 1);
    assert.equal(ticks[0], 0.05);
    assert.equal(lookCalls, 1);
    for (const time of [0, 4.5, 9, 14, 60, 3600]) await browserAdvance({ ...frame, look: 'pan', reviewTime: time });
    console.log('ok - browser ticks return no host graph, preserve off, bound long-take pan, and use internal substeps');
    let reviewTime;
    globalThis.__A3GAME_REVIEW__ = ({ time }) => { reviewTime = time; return host; };
    assert.equal(await browserAdvance({ ...frame, dt: 0, mode: 'overview', reviewTime: 0 }), undefined);
    assert.equal(reviewTime, 0);
    assert.equal(renders, 1);
    host.tick = () => { throw new Error('deliberate tick failure'); };
    await assert.rejects(browserAdvance(frame), /deliberate tick failure/);
    console.log('ok - overview hook return is not serialized and tick errors reject instead of hanging');
  } finally {
    globalThis.__A3GAME_GAME__ = previous.game;
    globalThis.__A3GAME_REVIEW__ = previous.review;
    globalThis.requestAnimationFrame = previous.raf;
  }
}

/**
 * Incremental persistence for the runtime observation channels.
 *
 * Rows append to `actions.jsonl` / `state_trace.jsonl` / `event_trace.jsonl`
 * in bounded batches (never one synchronous write per frame): a hard kill —
 * the Python timeout SIGKILLs this process mid-take — can then only lose the
 * rows still buffered in memory, never the whole channel. Channel files are
 * created lazily on the first flushed row, so a channel with no rows stays
 * absent exactly as before (absent ≠ captured-empty).
 *
 * The same bounded batches update `recording_progress.json` (atomic
 * tmp+rename) so a killed take still reports how far it got: frames,
 * recorded seconds, per-channel written rows, and the take's live status.
 */
function makeTraceWriter(outputDir, progress) {
  const channels = {
    actions: { file: path.join(outputDir, 'actions.jsonl'), pending: [], written: 0 },
    states: { file: path.join(outputDir, 'state_trace.jsonl'), pending: [], written: 0 },
    events: { file: path.join(outputDir, 'event_trace.jsonl'), pending: [], written: 0 },
  };
  const progressPath = path.join(outputDir, 'recording_progress.json');
  const appendRows = (channel, rows) => {
    if (!rows.length) return;
    appendFileSync(channel.file, rows.map((row) => JSON.stringify(row)).join('\n') + '\n');
    channel.written += rows.length;
  };
  const writeProgressFile = (status, extra = {}) => {
    const payload = {
      schema_version: 'a3game.recording_progress.v1', status,
      fps: progress.fps, requested_seconds: progress.requestedSeconds,
      target_frames: progress.targetFrames(), frames: progress.frames(),
      recorded_seconds: progress.frames() / progress.fps,
      simulated_seconds: progress.simulatedSeconds(),
      wall_elapsed_ms: Date.now() - progress.startedAt,
      channels_written: { actions: channels.actions.written,
                          states: channels.states.written,
                          events: channels.events.written },
      last_frame: progress.lastFrameFile(),
      updated_at: new Date().toISOString(), ...extra,
    };
    const pending = progressPath + '.tmp';
    writeFileSync(pending, `${JSON.stringify(payload, null, 2)}\n`);
    renameSync(pending, progressPath);
    return payload;
  };
  return {
    push(channel, row) { channels[channel].pending.push(row); },
    action(record) {
      // the actions channel records real injections (send verdict per step)
      // as each action finishes — never the requested plan
      this.push('actions', {
        ...actionMetadata(record),
        seq: record.index + 1,
        t_ms: Math.round((record.start_frame / progress.fps) * 1000),
        action: record.id,
        duration_s: Number(((record.frames ?? 0) / progress.fps).toFixed(3)),
        frames: record.frames ?? 0,
        sent: record.ok === true,
        ...(record.error ? { error: String(record.error).slice(0, 300) } : {}),
      });
    },
    flush(status = 'recording', extra = {}) {
      for (const channel of Object.values(channels)) {
        appendRows(channel, channel.pending);
        channel.pending.length = 0;
      }
      return writeProgressFile(status, extra);
    },
    writeProgress: writeProgressFile,
    counts: { get actions() { return channels.actions.written; },
              get states() { return channels.states.written; },
              get events() { return channels.events.written; } },
  };
}

async function main(args) {
  for (const key of ['url', 'output-dir']) if (!args[key]) throw new Error(`Missing --${key}`);
  const FPS = Number(args.fps ?? 20);
  const duration = Number(args.duration ?? 14);
  const width = Number(args.width ?? 1280);
  const height = Number(args.height ?? 720);
  const mode = args.mode ?? 'gameplay';
  const realtime = args.clock === 'realtime';
  const sparse = args['capture-schedule'] ? JSON.parse(await readFile(path.resolve(args['capture-schedule']), 'utf8')) : null;
  if (sparse && (!realtime || !['whitebox-endpoint-gameness-sparse.v1', 'whitebox-endpoint-gameness-sparse.v2'].includes(sparse.version)
      || sparse.warmup_ms !== 0 || !Array.isArray(sparse.points) || sparse.points.length > 360
      || sparse.tolerance_ms !== 350 || sparse.interval_ms !== 100
      || sparse.points.some((p, i) => !Number.isInteger(p.at_ms) || p.at_ms < 0 || p.at_ms >= duration * 1000
        || (i > 0 && p.at_ms <= sparse.points[i-1].at_ms) || !Array.isArray(p.capture_ids) || !p.capture_ids.length))) {
    throw new Error('Invalid native sparse schedule');
  }
  if (args.clock && !['fixed', 'realtime'].includes(args.clock)) throw new Error('Invalid clock');
  const preview = args.preview === 'true' || args.poster === 'true';
  const allowPartial = args['allow-partial-plan'] === 'true';
  if (![FPS, duration, width, height].every((n) => Number.isFinite(n) && n > 0)) throw new Error('duration, fps, width, and height must be positive');
  if (![width, height].every((n) => Number.isInteger(n) && n % 2 === 0)) throw new Error('width and height must be even integers');
  if (!['gameplay', 'overview'].includes(mode)) throw new Error('--mode must be gameplay or overview');
  if (args['allow-partial-plan'] && !['true', 'false'].includes(args['allow-partial-plan'])) throw new Error('--allow-partial-plan must be true or false');
  const DT = 1 / FPS;
  const baseDir = path.resolve(args['output-dir']);
  await mkdir(baseDir, { recursive: true });
  const outputDir = await mkdtemp(path.join(baseDir, `${mode}-${new Date().toISOString().replace(/[:.]/g, '-')}-`));
  const framesDir = path.join(outputDir, 'frames');
  await mkdir(framesDir);
  const report = {
    schema_version: 'a3game.playtest_report.v1', engine: 'three_js', status: 'failed',
    url: args.url, output_dir: outputDir, source_hash: args['source-hash'] ?? null,
    mode, fps: FPS, requested_seconds: duration,
    viewport: { width, height }, action_source: '', look_mode: '', warmup_seconds: 0,
    sustained: [], excluded_actions: [], actions: [], executed_actions: [], unexecuted_actions: [],
    frames: 0, recorded_seconds: 0, simulated_seconds: 0, fixed_tick: false,
    renderer_policy: args['software-renderer'] === 'true' ? 'swiftshader-explicit' : 'native-gpu-preferred',
    crash: '', page_errors: [], console_errors: [], warnings: [], video: null,
    init: null, poster: null, game_state: null, created_at: new Date().toISOString(),
  };
  let browser;
  let page;
  let mouseDown = false;
  const held = new Set();
  // runtime observation channels, filled only by the gameplay take; absent
  // channels stay unwritten so the evidence loader reports UNKNOWN, never a
  // fabricated empty observation
  const stateRows = [];
  const eventRows = [];
  let eventCursor = 0; // Fixed-tick trace cursor retains its separate protocol.
  const eventSnapshots = new EventSnapshots();
  let stateChannelAvailable = null;
  let eventsChannelAvailable = null;
  const started = Date.now();
  const progress = {
    fps: FPS, requestedSeconds: duration, startedAt: started,
    targetFrames: () => report.target_frames ?? null,
    frames: () => report.frames,
    simulatedSeconds: () => report.simulated_seconds,
    lastFrameFile: () => (report.frames
      ? `f${String(report.frames - 1).padStart(6, '0')}.jpg` : null),
  };
  const writer = makeTraceWriter(outputDir, progress);
  if (!preview) {
    writer.writeProgress('starting');
    // a graceful termination signal still gets a flushed, marked take —
    // the hard SIGKILL path is covered by the bounded in-loop flushes
    const terminate = (signal) => {
      try { writer.flush('terminated', { reason: signal }); } catch { /* best effort */ }
      process.exit(1);
    };
    process.once('SIGTERM', () => terminate('SIGTERM'));
    process.once('SIGINT', () => terminate('SIGINT'));
  }
  const failOnPageErrors = () => {
    // page errors (uncaught JS exceptions) and renderer crashes end the
    // take; console errors — including benign resource-load noise like the
    // browser's automatic /favicon.ico 404 against the dev server — are
    // recorded and carried into warnings so the metrics can judge them,
    // instead of killing the whole capture.
    if (report.crash || report.page_errors.length) {
      throw new Error(report.crash || report.page_errors[0]);
    }
  };

  let captureCdp;
  async function screenshot(file, format = 'png') {
    failOnPageErrors();
    if (!captureCdp) {
      captureCdp = await page.context().newCDPSession(page);
      captureCdp.setDefaultTimeout?.(30_000);
    }
    const shot = await captureCdp.send('Page.captureScreenshot', { format, ...(format === 'jpeg' ? { quality: 94 } : {}) });
    await writeFile(file, Buffer.from(shot.data, 'base64'), { flag: 'wx' });
    // Publish successful pixels before surfacing a later page error.

  }

  async function captureRealtime() {
    if (preview || mode !== 'gameplay' || !args['action-plan']) throw new Error('Realtime capture requires an explicit gameplay plan');
    report.clock = 'realtime';
    report.fixed_tick = false;
    report.look_mode = 'off';
    report.action_source = 'plan';
    report.environment_diagnostics = [];
    await navigateWithRetry(page, args.url, report.environment_diagnostics);
    await ensureInputFocus(page, report.environment_diagnostics);
    const parsed = JSON.parse(await readFile(path.resolve(args['action-plan']), 'utf8'));
    const normalized = normalize(Array.isArray(parsed) ? parsed : parsed.actions, 'plan', duration, FPS, false);
    report.actions = normalized.actions;
    report.target_frames = normalized.targetFrames;
    report.action_plan = path.resolve(args['action-plan']);
    report.init = path.join(outputDir, 'init.png');
    if (!sparse) await screenshot(report.init);
    const origin = performance.now();
    if (sparse) {
      report.sparse_capture = true;
      await writeFile(path.join(outputDir, 'capture_schedule.json'), JSON.stringify(sparse, null, 2), {flag:'wx'});
      await writeFile(path.join(outputDir, 'play_started.json'), JSON.stringify({recorder_elapsed_ms:0, clock:'monotonic_session_ms'}), {flag:'wx'});
    }
    const elapsed = () => Math.round(performance.now() - origin);
    const until = async (ms) => { const delay = ms - elapsed(); if (delay > 0) await page.waitForTimeout(delay); };
    let cancelled = false;
    let inputFailure;
    const heldButtons = new Set();
    const release = async (all = true) => {
      for (const key of [...held]) { await page.keyboard.up(key); held.delete(key); }
      for (const button of all ? [...heldButtons] : []) { await page.mouse.up({ button }); heldButtons.delete(button); }
    };
    const point = (x, y) => ({ x: x * (width - 1), y: y * (height - 1) });
    const executeInputs = async () => {
      for (const [index, action] of report.actions.entries()) {
        await until(action.start_frame * 1000 / FPS);
        if (cancelled) return;
        failOnPageErrors();
        await ensureInputFocus(page, report.environment_diagnostics);
        // Each declared step begins a new physical press, even for repeated keys.
        await release(false);
        const record = { ...actionMetadata(action), index, id: action.id, start_frame: action.start_frame, frames: 0, ok: false, t_ms: elapsed() };
        report.executed_actions.push(record);
        try {
          if (action.click || action.mouse) throw new Error('Realtime plan only supports explicit physical keyboard inputs');
          if (action.pointer) {
            const p = action.pointer;
            const start = point(p.x, p.y);
            record.pointer = p;
            record.viewport = [width, height];
            record.start_position = start;
            await page.mouse.move(start.x, start.y);
            if (['mouse_click', 'mouse_drag', 'mouse_down', 'mouse_hold'].includes(p.kind)) {
              if (!heldButtons.has(p.button)) await page.mouse.down({ button: p.button });
              heldButtons.add(p.button);
            }
            if (p.kind === 'mouse_up') { await page.mouse.up({ button: p.button }); heldButtons.delete(p.button); }
            if (p.kind === 'mouse_wheel') await page.mouse.wheel(p.delta_x, p.delta_y);
            if (p.kind === 'mouse_drag') {
              const end = point(p.to_x, p.to_y);
              record.end_position = end;
              const from = elapsed();
              const count = Math.max(2, Math.ceil(action.seconds * 60));
              for (let n = 1; n <= count; n++) {
                await until(from + n * action.seconds * 1000 / count);
                if (cancelled) throw new Error('Mouse drag cancelled');
                await page.mouse.move(start.x + (end.x - start.x) * n / count,
                                      start.y + (end.y - start.y) * n / count);
              }
            }
          }
          for (const key of [...new Set([...action.keys, ...action.taps])]) { await page.keyboard.down(key); held.add(key); }
          record.input_completed_t_ms = elapsed();
          await until(action.start_frame * 1000 / FPS + action.frames * 1000 / FPS);
          await release(false);
          if (action.pointer && ['mouse_click', 'mouse_drag', 'mouse_hold'].includes(action.pointer.kind)) {
            await page.mouse.up({ button: action.pointer.button }); heldButtons.delete(action.pointer.button);
            writer.push('actions', { ...actionMetadata(action), t_ms: elapsed(), kind: 'release', button: action.pointer.button, sent: true });
          }
          record.end_t_ms = elapsed();
          record.frames = action.frames;
          record.ok = true;
        } catch (error) { record.error = String(error.message || error); throw error; }
        finally {
          writer.push('actions', { ...actionMetadata(action), seq: index + 1, t_ms: record.t_ms, end_t_ms: elapsed(), action: action.id,
            keys: action.keys, taps: action.taps, ...(record.pointer ? { pointer: record.pointer, viewport: record.viewport, start_position: record.start_position, end_position: record.end_position } : {}), sent: record.ok, input_completed_t_ms: record.input_completed_t_ms,
            ...(record.error ? { error: record.error } : {}) });
          writer.flush();
        }
      }
    };
    const inputs = executeInputs().catch((error) => { inputFailure = error; });
    const observe = async () => {
    const observation = await page.evaluate(() => {
      const game = globalThis.__A3GAME_GAME__;
      return { hasState: typeof game?.getState === 'function', hasEvents: typeof game?.getEvents === 'function',
        events: typeof game?.getEvents === 'function' ? game.getEvents() : [] };
    });
    stateChannelAvailable = observation.hasState;
    eventsChannelAvailable = observation.hasEvents;
    if (observation.hasState) {
      const row = { t_ms: elapsed(), state: await page.evaluate(safeSnapshot) };
      stateRows.push(row); writer.push('states', row);
    }
    if (observation.hasEvents) {
      for (const row of eventSnapshots.observe(observation.events, elapsed())) {
        eventRows.push(row); writer.push('events', row);
      }
    }
    };
    const frameIndex = [];
    let sparseCursor = 0;
    try {
      for (let slot = 0; slot < report.target_frames;) {
        await until(slot * 1000 / FPS);
        if (elapsed() >= duration * 1000 && report.frames > 0) break;
        const frame = report.frames;
        if (inputFailure) throw inputFailure;
        failOnPageErrors();
        await observe();
        let capturePoint;
        if (sparse) {
          while (sparseCursor < sparse.points.length && elapsed() - sparse.points[sparseCursor].at_ms > sparse.tolerance_ms) sparseCursor += 1;
          capturePoint = report.frames === 0 ? {at_ms:-1, capture_ids:['readiness'], criterion_ids:[]}
            : sparse.points[sparseCursor]?.at_ms <= elapsed() ? sparse.points[sparseCursor] : null;
          if (!capturePoint) { slot = Math.max(slot + 1, Math.ceil(elapsed() * FPS / 1000)); continue; }
        }
        const filename = `f${String(frame).padStart(6, '0')}.jpg`;
        const before = elapsed();
        await screenshot(path.join(framesDir, filename), 'jpeg');
        frameIndex.push({ frame_id: `FRAME_${String(frame).padStart(6, '0')}`, id: `FRAME_${String(frame).padStart(6, '0')}`, t_ms: before, capture_end_t_ms: elapsed(),
          timestamp_ms: before, source_path: `frames/${filename}`, raw_path: `frames/${filename}`,
          delivered_path: null, delivery_status: 'pending_manifest', capture_status: 'captured',
          engine: 'three_js', viewport: [width, height], window: 'browser_page',
          clock: 'monotonic_session_ms', video_t_ms: sparse ? null : Math.round(frame * 1000 / FPS), path: `frames/${filename}`,
          ...(sparse ? {sample_at_ms:capturePoint.at_ms, capture_ids:capturePoint.capture_ids, criterion_ids:capturePoint.criterion_ids} : {}) });
        if (sparse) {
          if (capturePoint.at_ms < 0) report.init = path.join(framesDir, filename);
          else sparseCursor += 1;
        }
        report.frames += 1;
        // Sampling must follow the real clock: slow screenshots never extend
        // gameplay to manufacture all nominal frames after the input window.
        slot = Math.max(slot + 1, Math.ceil(elapsed() * FPS / 1000));
        if (frame % 10 === 0) { writer.flush(); await writeFile(path.join(outputDir, 'frame_index.jsonl'), frameIndex.map(row => JSON.stringify(row)).join('\n') + '\n'); }
      }
      await inputs;
      if (inputFailure) throw inputFailure;
      await until(duration * 1000);
      await observe();
      report.wallclock_seconds = elapsed() / 1000;
      report.sampling_complete = true;
      report.dropped_sample_slots = report.target_frames - report.frames;
      report.video_timing = 'Fixed-rate video samples; frame_index t_ms records actual wallclock capture, video_t_ms records encoded position.';
      report.poster = sparse ? path.join(outputDir, frameIndex.at(-1).path) : path.join(outputDir, 'poster.png');
      if (!sparse) await screenshot(report.poster);
      report.game_state = await page.evaluate(safeSnapshot);
    } finally {
      report.wallclock_seconds ??= elapsed() / 1000;
      report.planned_fps = FPS;
      report.actual_fps = report.frames / Math.max(.001, report.wallclock_seconds);
      report.sampling_intervals_ms = frameIndex.slice(1).map((row, i) => row.t_ms-frameIndex[i].t_ms);
      report.screenshot_durations_ms = frameIndex.map(row => row.capture_end_t_ms-row.t_ms);
      report.dropped_sample_slots = Math.max(0, report.target_frames-report.frames);
      report.capture_deadline_ms = duration*1000;
      report.capture_overrun_ms = Math.max(0, report.wallclock_seconds*1000-duration*1000);
      report.video_timing = 'Fixed-rate auxiliary video; frame_index maps real capture/completion times to encoded video_t_ms.';
      cancelled = true;
      await inputs;
      await release();
      if (sparse) {
        report.input_cleanup = held.size === 0 && heldButtons.size === 0;
        await writeFile(path.join(outputDir, 'input_view_cleanup.json'), JSON.stringify({input_cleanup:report.input_cleanup,
          held_keys_after_release:held.size, held_buttons_after_release:heldButtons.size, t_ms:elapsed()}));
      }
      await writeFile(path.join(outputDir, 'frame_index.jsonl'), frameIndex.map(row => JSON.stringify(row)).join('\n') + '\n');
      await writeFile(path.join(outputDir, 'browser.log'), [...report.page_errors.map(x => `PAGE_ERROR: ${x}`), ...report.console_errors.map(x => `CONSOLE_ERROR: ${x}`)].join('\n'));
    }
  }
  try {
    const require_ = createRequire(path.join(path.resolve(args['playwright-root'] || process.cwd()), 'package.json'));
    const { chromium } = require_('playwright');
    const browserArgs = ['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu-watchdog',
      '--disable-features=CDPScreenshotNewSurface'];
    if (args['software-renderer'] === 'true') {
      browserArgs.push('--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--in-process-gpu',
        '--override-use-software-gl-for-tests');
    }
    browser = await chromium.launch({
      executablePath: args['browser-executable'] || undefined,
      ignoreDefaultArgs: ['--mute-audio'],
      args: browserArgs,
    });
    page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 1 });
    page.setDefaultTimeout(30_000);
    const appendError = (list, value) => { if (list.length < 100) list.push(String(value).slice(0, 500)); };
    page.on('pageerror', (error) => appendError(report.page_errors, error.message || error));
    page.on('console', (message) => { if (message.type() === 'error') appendError(report.console_errors, message.text()); });
    report.network_failures = [];
    page.on('requestfailed', (request) => { if (report.network_failures.length < 100) report.network_failures.push({url: request.url(), failure: request.failure()?.errorText}); });
    page.on('response', (response) => { if (response.status() >= 400 && report.network_failures.length < 100) report.network_failures.push({url: response.url(), status: response.status()}); });
    page.on('crash', () => { report.crash = 'Page renderer crashed'; });
    await page.addInitScript(installAudioCapture);
    if (!realtime) {
    await page.addInitScript(() => {
      globalThis.__A3GAME_RECORDING__ = true;
      let game;
      Object.defineProperty(globalThis, '__A3GAME_GAME__', {
        configurable: true, enumerable: true,
        get() { return game; },
        set(value) { game = value; value?.host?.stop?.(); },
      });
    });
    await page.goto(args.url, { waitUntil: 'load', timeout: 120_000 });
    await page.waitForFunction(() => typeof globalThis.__A3GAME_GAME__?.host?.tick === 'function', null, { timeout: 120_000, polling: 100 });
    const runtime = await page.evaluate(() => {
      const game = globalThis.__A3GAME_GAME__;
      const host = game.host;
      host.stop();
      return {
        lookMode: String(game.input?.lookMode ?? ''), yaw: Number(game.input?.yaw ?? 0),
        pitch: Number(game.input?.pitch ?? 0), canLook: typeof game.input?.setLook === 'function',
        review: typeof globalThis.__A3GAME_REVIEW__ === 'function',
        maxDelta: Number(host.options?.maxFrameDelta ?? 1 / 60),
        fixedStep: Number(host.options?.fixedTimeStep ?? 0),
        simulationTime: Number(host.elapsedSeconds ?? 0), droppedSeconds: Number(host.droppedSeconds ?? 0),
        hasGetState: typeof globalThis.__A3GAME_GAME__?.getState === 'function',
      };
    });
    report.fixed_tick = true;
    report.initial_simulated_seconds = runtime.simulationTime;
    failOnPageErrors();
    if (mode === 'overview' && !runtime.review) report.warnings.push('No review hook; using the game\'s own camera');
    if (preview) {
      const warmup = Number(args.warmup ?? 0);
      if (!Number.isFinite(warmup) || warmup < 0) throw new Error('warmup must be finite and non-negative');
      const maximum = Math.min(1 / 60, runtime.maxDelta > 0 ? runtime.maxDelta : 1 / 60,
        runtime.fixedStep > 0 ? runtime.fixedStep : 1 / 60);
      const warmupFrames = Math.round(warmup * FPS);
      const frame = { maximum, mode, duration: warmupFrames / FPS, look: 'off', yaw: runtime.yaw, pitch: runtime.pitch };
      for (let i = 0; i < warmupFrames; i += 1) {
        await page.evaluate(browserAdvance, { ...frame, dt: DT, reviewTime: (i + 1) / FPS, frame: i });
        failOnPageErrors();
      }
      await page.evaluate(browserAdvance, { ...frame, dt: 0, reviewTime: warmupFrames / FPS, frame: warmupFrames });
      const cdp = await page.context().newCDPSession(page);
      const shot = await cdp.send('Page.captureScreenshot', { format: 'png' });
      report.poster = path.join(outputDir, 'poster.png');
      await writeFile(report.poster, Buffer.from(shot.data, 'base64'), { flag: 'wx' });
      report.init = report.poster;
      report.game_state = await page.evaluate(safeSnapshot);
      failOnPageErrors();
      report.preview = true;
      report.png_frames = 1;
      report.action_source = 'preview';
      report.look_mode = 'off';
      report.warmup_seconds = warmupFrames / FPS;
      report.simulated_seconds = report.warmup_seconds;
      report.status = 'preview_completed';
      report.completed_at = new Date().toISOString();
    } else {
    await page.waitForTimeout(3_000);
    failOnPageErrors();
    let discovered = { source: 'overview', actions: [], look: 'off', warmup: 0, sustained: [] };
    if (mode === 'gameplay') {
      if (args['action-plan']) {
        report.action_plan = path.resolve(args['action-plan']);
        const parsed = JSON.parse(await readFile(report.action_plan, 'utf8'));
        discovered = Array.isArray(parsed) ? { source: 'plan', actions: parsed } : { ...parsed, source: 'plan' };
      } else discovered = await page.evaluate(DISCOVERY);
    }
    report.action_source = discovered.source;
    report.look_mode = lookMode(String(args.look ?? discovered.look ?? 'auto').toLowerCase(), runtime.lookMode);
    if (mode === 'overview' && report.look_mode !== 'off') throw new Error('overview owns its camera; use --look off');
    if (report.look_mode === 'pan' && !runtime.canLook) throw new Error('pan requires input.setLook');
    const warmup = Number(args.warmup ?? discovered.warmup ?? 0);
    if (!Number.isFinite(warmup) || warmup < 0) throw new Error('warmup must be finite and non-negative');
    const sustainedNames = args.hold ? args.hold.split(',') : discovered.sustained ?? [];
    if (!Array.isArray(sustainedNames)) throw new Error('sustained must be an array');
    const sustained = sustainedNames.length ? await page.evaluate(RESOLVE, sustainedNames) : [];
    for (const item of sustained) if (!item.code) throw new Error(`Cannot hold "${item.name}": no keyboard binding`);
    const sustainedCodes = [...new Set(sustained.map((item) => item.code))];
    report.sustained = sustainedCodes;
    const plan = normalize(discovered.actions, discovered.source, duration, FPS, allowPartial);
    report.actions = plan.actions;
    report.target_frames = plan.targetFrames;
    report.plan_frames = plan.planFrames;
    report.partial_plan = plan.partial;
    if (plan.partial) report.warnings.push('Explicit partial-plan probe: see unexecuted_actions for omitted frames');
    for (const action of plan.actions) {
      if (action.sub_frame_bumped) report.warnings.push(
        `${action.id}: shorter than one frame at ${FPS} fps; bumped to 1 frame (action still executed)`);
    }
    for (const action of report.actions) {
      if (action.taps.some((code) => sustainedCodes.includes(code))) throw new Error(`Action ${action.id} taps a sustained key`);
    }
    const maximum = Math.min(1 / 60, runtime.maxDelta > 0 ? runtime.maxDelta : 1 / 60,
      runtime.fixedStep > 0 ? runtime.fixedStep : 1 / 60);
    const fixed = substeps(DT, maximum);
    report.substeps_per_frame = fixed.count;
    report.substep_seconds = fixed.dt;
    stateChannelAvailable = runtime.hasGetState === true;
    // state sampling keeps the trace bounded: ~600 rows per take at most,
    // evenly spaced, which still lands multiple rows inside any ~750ms
    // input-response window at every supported fps
    const stateInterval = Math.max(1, Math.ceil(plan.targetFrames / 600));
    const sampleState = async () => {
      const snapshot = await page.evaluate(safeSnapshot);
      if (snapshot !== null) {
        const row = { t_ms: Math.round(report.frames * 1000 / FPS), state: snapshot };
        stateRows.push(row);
        writer.push('states', row);
      }
    };
    // events come from the game runtime adapter's own event record (trace
    // array) — the recorder only observes, never injects or infers them
    const drainEvents = async () => {
      const drained = await page.evaluate((cursor) => {
        const game = globalThis.__A3GAME_GAME__;
        let trace = null;
        if (typeof game?.trace === 'function') {
          try {
            const value = game.trace();
            if (Array.isArray(value)) trace = value;
          } catch { trace = null; }
        }
        if (trace === null) {
          const adapter = game?.game ?? game;
          if (Array.isArray(adapter?.trace)) trace = adapter.trace;
        }
        if (trace === null) return { available: false, cursor: 0, rows: [] };
        const rows = [];
        for (const event of trace.slice(cursor)) {
          if (event == null || typeof event !== 'object') continue;
          let payload;
          try {
            const text = JSON.stringify(event);
            if (text && text.length <= 65536) payload = JSON.parse(text);
          } catch { payload = null; }
          if (payload === null) continue;
          rows.push({ event: String(payload.type ?? ''), payload });
        }
        return { available: true, cursor: trace.length, rows: rows.filter((row) => row.event) };
      }, eventCursor);
      eventsChannelAvailable = drained.available;
      eventCursor = drained.cursor;
      const tMs = Math.round(report.frames * 1000 / FPS);
      for (const row of drained.rows) {
        const eventRow = { t_ms: tMs, event: row.event, payload: row.payload };
        eventRows.push(eventRow);
        writer.push('events', eventRow);
      }
    };

    async function setKeys(wanted) {
      const target = new Set([...wanted, ...sustainedCodes]);
      for (const key of [...held]) {
        if (!target.has(key)) { await page.keyboard.up(key); held.delete(key); }
      }
      for (const key of target) {
        if (!held.has(key)) { await page.keyboard.down(key); held.add(key); }
      }
    }
    const setMouse = async (down) => {
      if (mouseDown === down) return;
      await page.evaluate((isDown) => {
        const element = globalThis.__A3GAME_GAME__.host.container;
        const rect = element.getBoundingClientRect();
        element.dispatchEvent(new PointerEvent(isDown ? 'pointerdown' : 'pointerup', {
          bubbles: true, button: 0, buttons: isDown ? 1 : 0, isPrimary: true,
          pointerId: 1, pointerType: 'mouse', clientX: rect.x + rect.width / 2, clientY: rect.y + rect.height / 2,
        }));
      }, down);
      mouseDown = down;
    };
    async function advance(dt, reviewTime = null) {
      failOnPageErrors();
      await page.evaluate(browserAdvance, { dt, maximum, mode, reviewTime, frame: report.frames, duration: report.target_frames / FPS,
        look: report.look_mode, yaw: runtime.yaw, pitch: runtime.pitch });
      report.simulated_seconds += dt;
      failOnPageErrors();
    }
    async function capture() {
      await advance(DT, (report.frames + 1) / FPS);
      if (report.frames % stateInterval === 0) await sampleState();
      await drainEvents();
      await page.evaluate(sampleAudioClock, report.frames * 1000 / FPS);
      await screenshot(path.join(framesDir, `f${String(report.frames).padStart(6, '0')}.jpg`), 'jpeg');
      report.frames += 1;
      // bounded incremental persistence: a hard kill can only lose the
      // rows still buffered since the last flush, never the channel
      if (report.frames % 25 === 0) writer.flush();
    }
    await advance(0, 0);
    report.init = path.join(outputDir, 'init.png');
    await screenshot(report.init);
    await setKeys([]);
    const warmupFrames = Math.round(warmup * FPS);
    for (let i = 0; i < warmupFrames; i += 1) await advance(DT);
    report.warmup_seconds = warmupFrames / FPS;
    for (const [index, action] of report.actions.entries()) {
      if (!action.frames) continue;
      const record = { ...actionMetadata(action), index, id: action.id, source: action.source, start_frame: report.frames, frames: 0, ok: false };
      report.executed_actions.push(record);
      try {
        if (action.click) await page.locator(action.click).first().click({ timeout: 2_000 });
        await setKeys(action.keys);
        for (const key of action.taps) { await page.keyboard.down(key); held.add(key); }
        if (action.pointer) throw new Error('Pointer gestures require realtime capture');
        if (action.mouse) await setMouse(true);
        for (let i = 0; i < action.frames; i += 1) {
          await capture();
          record.frames += 1;
          if (i === 0 && !action.hold) {
            for (const key of action.taps) { await page.keyboard.up(key); held.delete(key); }
            if (action.mouse) await setMouse(false);
          }
        }
        if (action.hold) {
          for (const key of action.taps) { await page.keyboard.up(key); held.delete(key); }
        }
        if (action.mouse) await setMouse(false);
        record.ok = true;
      } catch (error) {
        record.error = String(error.message || error).slice(0, 500);
        throw error;
      } finally {
        // the executed-action row (real send verdict) is durable the
        // moment the action finishes — a later kill cannot erase it; a
        // persistence hiccup must never mask the take's own error
        try {
          writer.action(record);
          writer.flush();
        } catch { /* best effort while an error is propagating */ }
      }
    }
    await setKeys([]);
    while (report.frames < report.target_frames) await capture();
    await advance(0, report.frames / FPS);
    report.poster = path.join(outputDir, 'poster.png');
    await screenshot(report.poster);
    report.game_state = await page.evaluate(safeSnapshot);
    const timing = await page.evaluate(() => {
      const host = globalThis.__A3GAME_GAME__.host;
      return { simulationTime: Number(host.elapsedSeconds ?? 0), droppedSeconds: Number(host.droppedSeconds ?? 0) };
    });
    report.host_simulated_seconds = timing.simulationTime - runtime.simulationTime;
    report.dropped_seconds = timing.droppedSeconds - runtime.droppedSeconds;
    if (report.dropped_seconds > 1e-8) throw new Error('Host dropped simulation time during fixed capture');
    if (runtime.fixedStep > 0 && Math.abs(report.host_simulated_seconds - report.simulated_seconds) > runtime.fixedStep + 1e-7) {
      throw new Error('Host simulation time differs from requested fixed ticks');
    }
    failOnPageErrors();
    }
    } else {
      await captureRealtime();
    }
  } catch (error) {
    report.status = 'failed';
    const errorMsg = String(error.message || error);
    report.crash ||= errorMsg.slice(0, 1000);

    // Classify known error types for better diagnostics
    if (/Browser lost focus/i.test(errorMsg)) {
      report.error_classification = 'INPUT_FOCUS_LOST';
      report.error_category = 'environment';
    } else if (/Failed to load resource/i.test(errorMsg)) {
      report.error_classification = 'RESOURCE_LOAD_FAILED';
      report.error_category = 'product';
    } else if (/Page renderer crashed/i.test(errorMsg)) {
      report.error_classification = 'RENDERER_CRASH';
      report.error_category = 'environment';
    }
  } finally {
    if (page) {
      for (const key of held) await page.keyboard.up(key).catch(() => {});
      if (mouseDown) await page.evaluate(() => {
        globalThis.__A3GAME_GAME__?.host?.container?.dispatchEvent(new PointerEvent('pointerup', {
          bubbles: true, button: 0, buttons: 0, isPrimary: true, pointerId: 1, pointerType: 'mouse',
        }));
      }).catch(() => {});
      if (!report.game_state && !page.isClosed() && !report.crash) report.game_state = await page.evaluate(safeSnapshot).catch(() => null);
    }
    if (page && !page.isClosed()) {
      try {
        const audio = await page.evaluate(exportAudioCapture);
        if (audio.pcm_base64) await writeFile(path.join(outputDir, 'audio.wav'),
          pcmWav(Buffer.from(audio.pcm_base64, 'base64'), audio.sample_rate));
        await writeFile(path.join(outputDir, 'audio_capture.json'), JSON.stringify(audio.metadata, null, 2));
        report.audio_capture = audio.metadata;
      } catch (error) {
        const metadata = { status: 'capture_failed', source: 'game_output', error: String(error.message || error).slice(0, 200) };
        await writeFile(path.join(outputDir, 'audio_capture.json'), JSON.stringify(metadata));
        report.audio_capture = metadata;
      }
    }
    if (sparse && browser) {
      try {
        await browser.close();
        report.view_cleanup = page?.isClosed() === true;
        report.browser_cleanup = browser.isConnected() === false;
      } catch (error) { report.cleanup_error = String(error.message || error); }
      await writeFile(path.join(outputDir, 'browser_cleanup.json'), JSON.stringify({view_cleanup:report.view_cleanup === true,
        browser_cleanup:report.browser_cleanup === true, input_cleanup:report.input_cleanup === true, error:report.cleanup_error ?? null}));
    } else await browser?.close().catch(() => {});
  }
  report.recorded_seconds = report.frames / FPS;
  report.ms_per_frame = report.frames ? Math.round((Date.now() - started) / report.frames) : 0;
  report.unexecuted_actions = report.actions.flatMap((action, index) => {
    const recorded = report.executed_actions.find((item) => item.index === index)?.frames ?? 0;
    return recorded < action.planned_frames ? [{ id: action.id, index, missing_frames: action.planned_frames - recorded }] : [];
  });
  if (!preview) {
    // the actions channel records what was actually injected this take (send
    // verdict per step), not the requested plan; the game_state snapshot
    // stays the final-state summary and the traces carry the timeline.
    // Every row was already persisted incrementally by the trace writer —
    // this flush only drains the tail buffered since the last batch; a
    // persistence failure is recorded honestly instead of killing the
    // report itself
    try {
      writer.flush();
    } catch (error) {
      report.warnings.push(`trace flush failed: ${String(error.message || error).slice(0, 300)}`);
    }
    const actionRows = report.executed_actions.map((record) => ({
      ...actionMetadata(record),
      seq: record.index + 1,
      t_ms: Math.round((record.start_frame / FPS) * 1000),
      action: record.id,
      duration_s: Number(((record.frames ?? 0) / FPS).toFixed(3)),
      frames: record.frames ?? 0,
      sent: record.ok === true,
      ...(record.error ? { error: String(record.error).slice(0, 300) } : {}),
    }));
    report.channel_coverage = {
      actions: { available: actionRows.length > 0, rows: actionRows.length },
      states: { available: stateChannelAvailable === true, rows: stateRows.length,
                capture_error: stateChannelAvailable === true && stateRows.length === 0
                  ? 'state channel declared but no sample was captured' : null },
      events: { available: eventsChannelAvailable === true, rows: eventRows.length,
        ...(realtime && eventsChannelAvailable === true ? eventSnapshots.summary() : {}) },
      frames: { available: report.frames > 0, rows: report.frames },
      video: { available: null, rows: null },
    };
  }
  try {
    if (sparse) {
      if (!report.crash && !report.page_errors.length && report.sampling_complete && report.frames > 0
          && report.executed_actions.length === report.actions.filter(a => a.frames > 0).length
          && report.executed_actions.every(a => a.ok) && report.input_cleanup && report.view_cleanup && report.browser_cleanup) {
        report.status = 'completed';
        report.completed_at = new Date().toISOString();
        report.video_timing = 'Sparse native pixels only; no auxiliary video or route-wide screenshots.';
      } else throw new Error('Sparse native capture or cleanup incomplete');
    } else if (!preview) {
    if (!report.frames) throw new Error('No captured frames to encode');
    const video = path.join(outputDir, 'video.mp4');
    const ffmpeg = process.env.A3GAME_PLAYTEST_FFMPEG || process.env.FFMPEG || 'ffmpeg';
    const encode = (codec) => spawnSync(ffmpeg,
      ['-n', '-loglevel', 'error', '-framerate', String(FPS), '-start_number', '0',
        '-i', path.join(framesDir, 'f%06d.jpg'), '-frames:v', String(report.frames),
        '-c:v', codec, '-b:v', process.env.A3GAME_PLAYTEST_BITRATE || '6000k',
        '-pix_fmt', 'yuv420p', '-movflags', '+faststart', video],
      { encoding: 'utf8', timeout: 120_000, maxBuffer: 2 * 1024 * 1024 });
    // the configured/default codec may be missing from the local ffmpeg
    // build (e.g. libopenh264 in homebrew) — retry once with the universal
    // libx264 and record which encoder actually ran
    let encoded = encode(process.env.A3GAME_PLAYTEST_CODEC || 'libopenh264');
    if (encoded.status !== 0) {
      encoded = encode('libx264');
      if (encoded.status === 0) report.warnings.push('encoded with libx264 fallback codec');
    }
    if (encoded.status !== 0) throw new Error(`Video encoding failed: ${encoded.error?.message || encoded.stderr?.trim() || encoded.status}`);
    if ((await stat(video)).size <= 0) throw new Error('Encoded video is empty');
    const ffprobe = process.env.A3GAME_PLAYTEST_FFPROBE || (ffmpeg.includes('/') ? path.join(path.dirname(ffmpeg), 'ffprobe') : 'ffprobe');
    const probed = spawnSync(ffprobe, ['-v', 'error', '-select_streams', 'v:0', '-count_frames',
      '-show_entries', 'stream=nb_read_frames,width,height,avg_frame_rate,duration:format=duration', '-of', 'json', video],
    { encoding: 'utf8', timeout: 120_000, maxBuffer: 2 * 1024 * 1024 });
    if (probed.status !== 0) throw new Error(`Video validation failed: ${probed.error?.message || probed.stderr?.trim() || probed.status}`);
    report.video_metadata = validateVideo(JSON.parse(probed.stdout), report.frames, FPS, width, height);
    report.video = video;
    if (!report.crash && !report.page_errors.length &&
        (realtime && report.target_frames > 1 ? report.sampling_complete && report.frames > 1 && report.frames <= report.target_frames
          : realtime ? report.sampling_complete && report.frames > 0 && report.frames <= report.target_frames
          : report.frames === report.target_frames) && report.init && report.poster && report.executed_actions.every((action) => action.ok)) {
      report.status = 'completed';
      report.completed_at = new Date().toISOString();
    }
    // console errors never block completion — they are captured evidence
    // the downstream metrics judge (a missing favicon is not a game FAIL,
    // and a missing asset must be visible to the judge, not to a crashed
    // recorder)
    if (report.console_errors.length) {
      report.warnings.push(...report.console_errors.map((text) => `console: ${text}`));
    }
    }
  } catch (error) {
    report.warnings.push(String(error.message || error).slice(0, 1000));
    report.crash ||= report.warnings.at(-1);
  }
  if (report.channel_coverage) {
    report.channel_coverage.video = {
      available: Boolean(report.video),
      rows: report.video_metadata ? Number(report.video_metadata.frames) : null,
    };
  }
  const reportPath = path.join(outputDir, 'report.json');
  const manifest = {
    schema_version: 'a3game.playtest_manifest.v1', status: report.status, mode, url: args.url,
    source_hash: report.source_hash,
    output_dir: outputDir, created_at: report.created_at, completed_at: report.completed_at ?? null,
    fps: FPS, frames: report.frames, seconds: report.recorded_seconds, viewport: report.viewport,
    partial_plan: report.partial_plan ?? false, report: path.relative(baseDir, reportPath),
    video: report.video ? path.relative(baseDir, report.video) : null,
    poster: report.poster ? path.relative(baseDir, report.poster) : null,
    init: report.init ? path.relative(baseDir, report.init) : null,
  };
  await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, { flag: 'wx' });
  await writeFile(path.join(outputDir, 'manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`, { flag: 'wx' });
  if (!preview) {
    // terminal progress: the take reached its own end (completed or failed)
    // — a take killed mid-run keeps its last in-loop progress instead
    writer.writeProgress(report.status, { reason: report.crash || null,
                                          completed_at: report.completed_at ?? null });
  }
  if (report.status === 'completed') {
    const pending = path.join(baseDir, `.manifest-${path.basename(outputDir)}.tmp`);
    await writeFile(pending, `${JSON.stringify(manifest, null, 2)}\n`, { flag: 'wx' });
    await rename(pending, path.join(baseDir, 'manifest.json'));
  }
  console.log(JSON.stringify({ status: report.status, source_hash: report.source_hash, report: reportPath, output_dir: outputDir, poster: report.poster }));
  if (!['completed', 'preview_completed'].includes(report.status)) process.exitCode = 1;
}

const args = parseArgs(process.argv);
if (args['self-test'] === 'true') await selfTest();
else await main(args);
