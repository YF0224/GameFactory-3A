/** Read-only, sampled getEvents snapshots. No claim of an uninterrupted event stream. */
import { createHash } from 'node:crypto';
export const EVENT_SNAPSHOT_PROTOCOL = 'whitebox-event-snapshots.v1';
const LIMITATION = 'Sampled snapshots cannot prove an uninterrupted stream. Events may be lost between observations, including an undetectable reset to an identical prefix. Boundary rows are harness metadata, never gameplay events. Do not infer counts or absence across a boundary.';
function canonical(value) {
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return JSON.stringify(value);
  if (typeof value === 'number' && Number.isFinite(value)) return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (typeof value === 'object' && value !== null) return `{${Object.keys(value).sort().map(k => `${JSON.stringify(k)}:${canonical(value[k])}`).join(',')}}`;
  throw new Error('Read-only getEvents returned a non-JSON event value');
}
const digest = (items) => createHash('sha256').update(`[${items.join(',')}]`).digest('hex');
export class EventSnapshots {
  constructor() { this.previous = []; this.lastTMs = null; this.epoch = 0; this.seq = 0; this.boundaries = 0; this.observed = 0; }
  observe(events, tMs) {
    if (!Array.isArray(events)) throw new Error('Read-only getEvents returned a non-array');
    if (!Number.isFinite(tMs) || tMs < 0 || (this.lastTMs !== null && tMs < this.lastTMs)) throw new Error('Event observation clock must be monotonic');
    for (const event of events) if (event === null || typeof event !== 'object' || Array.isArray(event)) throw new Error('Read-only getEvents returned a non-object event');
    // Keep immutable serializations: caller mutation must not rewrite earlier observations.
    const current = events.map(canonical);
    let common = 0;
    while (common < Math.min(current.length, this.previous.length) && current[common] === this.previous[common]) common++;
    const changed = common < this.previous.length;
    const rows = [];
    if (changed) {
      this.epoch++; this.boundaries++;
      rows.push({ t_ms: tMs, record_type: 'harness_event_boundary', protocol: EVENT_SNAPSHOT_PROTOCOL,
        observation_seq: ++this.seq, snapshot_epoch: this.epoch,
        event: 'HARNESS_EVENT_SNAPSHOT_DISCONTINUITY',
        payload: { kind: current.length < this.previous.length ? 'snapshot_shrank' : 'snapshot_prefix_changed',
          previous_observed_t_ms: this.lastTMs, current_observed_t_ms: tMs,
          previous_count: this.previous.length, current_count: current.length, common_prefix_count: common,
          previous_snapshot_sha256: digest(this.previous), current_snapshot_sha256: digest(current),
          continuity: 'UNKNOWN', cause: 'UNKNOWN', limitation: LIMITATION } });
    }
    for (let i = changed ? 0 : this.previous.length; i < current.length; i++) {
      const event = JSON.parse(current[i]); this.observed++;
      rows.push({ t_ms: tMs, record_type: 'game_event_observation', protocol: EVENT_SNAPSHOT_PROTOCOL,
        observation_seq: ++this.seq, snapshot_epoch: this.epoch, snapshot_index: i,
        event: typeof event.type === 'string' ? event.type : typeof event.event === 'string' ? event.event : 'game_event', payload: event });
    }
    this.previous = current; this.lastTMs = tMs;
    return rows;
  }
  summary() { return { protocol: EVENT_SNAPSHOT_PROTOCOL, continuity_guaranteed: false,
    boundaries: this.boundaries, observed_event_rows: this.observed, epochs: this.epoch + 1, limitation: LIMITATION }; }
}
