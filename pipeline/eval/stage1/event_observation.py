"""Validate sampled event provenance; boundaries are never product events or proof of completeness."""
import math
import re

VERSION = 'whitebox-event-snapshots.v1'
LIMITATION = ('Read-only getEvents snapshots are sampled, not an uninterrupted stream. '
             'Identical-prefix resets may be undetectable. Harness boundaries are observation metadata, '
             'not gameplay events, restart proof or evidence of product failure. Do not infer event counts, '
             'absence, timing, ordering or completeness across a boundary. Use direct action/state/frame evidence '
             'for the required observation window; otherwise UNVERIFIED.')

def validate_event_snapshot_rows(rows):
    tagged = [r for r in rows if r.get('protocol') == VERSION or r.get('record_type') in
              {'harness_event_boundary', 'game_event_observation'}]
    if not tagged:
        return None  # Historical channels keep their own evidence and validation contracts.
    if len(tagged) != len(rows):
        raise ValueError('event snapshot protocol mixed with untagged rows')
    epoch, index, last_time, boundaries, observations = 0, 0, -1, [], 0
    for line, row in enumerate(rows, 1):
        if row.get('protocol') != VERSION or type(row.get('observation_seq')) is not int or row['observation_seq'] != line:
            raise ValueError('event snapshot protocol or observation sequence mismatch')
        t = row.get('t_ms')
        if type(t) not in (int, float) or not math.isfinite(t) or t < max(0, last_time):
            raise ValueError('event snapshot observation time is not monotonic')
        payload = row.get('payload')
        if not isinstance(payload, dict):
            raise ValueError('event snapshot row requires the original object payload')
        if row.get('record_type') == 'harness_event_boundary':
            epoch += 1
            if row.get('event') != 'HARNESS_EVENT_SNAPSHOT_DISCONTINUITY' or payload.get('continuity') != 'UNKNOWN' or payload.get('cause') != 'UNKNOWN' or not payload.get('limitation'):
                raise ValueError('event boundary lacks explicit continuity/cause uncertainty')
            counts = [payload.get(k) for k in ('previous_count', 'current_count', 'common_prefix_count')]
            if not all(type(n) is int and n >= 0 for n in counts) or not counts[0] > counts[2] or counts[2] > counts[1]:
                raise ValueError('event boundary snapshot counts inconsistent')
            kind = 'snapshot_shrank' if counts[1] < counts[0] else 'snapshot_prefix_changed'
            if payload.get('kind') != kind:
                raise ValueError('event boundary classification mismatch')
            previous = payload.get('previous_observed_t_ms')
            if type(previous) not in (int, float) or not math.isfinite(previous) or not max(0, last_time) <= previous <= t or payload.get('current_observed_t_ms') != t:
                raise ValueError('event boundary observation interval mismatch')
            if any(not re.fullmatch('[0-9a-f]{64}', str(payload.get(k, ''))) for k in ('previous_snapshot_sha256', 'current_snapshot_sha256')):
                raise ValueError('event boundary snapshot hashes missing')
            boundaries.append({'line': line, **row})
            index = 0
        elif row.get('record_type') == 'game_event_observation':
            if type(row.get('snapshot_index')) is not int or row['snapshot_index'] != index:
                raise ValueError('event snapshot index mismatch')
            expected = payload.get('type') if isinstance(payload.get('type'), str) else payload.get('event') if isinstance(payload.get('event'), str) else 'game_event'
            if row.get('event') != expected:
                raise ValueError('event observation changed product event type')
            index += 1
            observations += 1
        else:
            raise ValueError('unknown event observation row type')
        if type(row.get('snapshot_epoch')) is not int or row['snapshot_epoch'] != epoch:
            raise ValueError('event snapshot epoch mismatch')
        last_time = t
    # All boundaries remain in the raw channel. Delivery context is bounded independently.
    visible = boundaries if len(boundaries) <= 128 else boundaries[:64] + boundaries[-64:]
    return {'protocol': VERSION, 'continuity_guaranteed': False, 'observed_event_rows': observations,
            'boundary_count': len(boundaries), 'boundary_rows': visible,
            'omitted_boundary_context_rows': max(0, len(boundaries)-len(visible)), 'limitation': LIMITATION}
