"""Action-anchored capture: frames are scheduled from the plan's actions.

No recorder can fire on an input event, but all of them accept a schedule of
capture points (``at_ms`` from the recorder origin). Every input action gets:

    pre/<action_id>        100 ms before it starts
    end/<action_id>        when it ends
    post300/<action_id>    300 ms after it ends
    post1000/<action_id>   1000 ms after it ends

plus ``baseline/<ms>`` context points (every second, or sparser so the
action points always fit the recorder limit). Points are snapped to
the recorder's 100 ms grid and merged (one point can serve several ids), and
the ids carry the action's criterion ids, so the judge sees exactly the frames
of each action. Observation holds (waits that name criteria, e.g. motion strips)
get ``hold<k>/<id>`` points every 250 ms (at most 10) and ``holdend/<id>``. On Unity, end/post points are additionally held until the
adapter reports the action finished (``endpoint_settle_guards``).

Used where action timing is deterministic: three_js, unity3d, and Godot plans
without condition waits. Otherwise (Godot ``wait_until`` / ``move_until``, UE5
whose public recorder takes no schedule) the take is dense (10 fps) and frames
are chosen around each action's *recorded* timestamp — see evidence.py.
"""
from __future__ import annotations

from collections import defaultdict

VERSION = 'whitebox-endpoint-gameness-sparse.v2'    # schedule format accepted by the recorders
AUDIT_PROTOCOL = 'stage1-action-anchored.v1'
INTERVAL_MS = 100
TOLERANCE_MS = 350
MAX_POINTS = 360
OFFSETS = (('pre', 'start', -100), ('end', 'end', 0), ('post300', 'end', 300), ('post1000', 'end', 1000))
BASELINE_MS = 250       # baseline context frames fill unused recorder slots (~4 fps); was 1000 (2026-11-11)
BASELINE_MS_BY_ENGINE = {'ue5': 1000}   # UE capture falls behind at 250 ms (G030); event frames cover events
HOLD_STEP_MS = 250
HOLD_MAX = 10


def supported(engine: str, plan: dict) -> bool:
    if engine in ('three_js', 'unity3d'):
        return True
    if engine == 'godot':
        return not any(s['kind'] in ('wait_until', 'move_until') for p in plan['probes'] for s in p['steps'])
    return False


def godot_actions(plan: dict) -> list[dict]:
    """Planned timeline of a condition-free Godot plan (the recorder runs it after the startup wait)."""
    from .plan import STARTUP_WAIT_MS
    t, rows = STARTUP_WAIT_MS, []
    for probe in plan['probes']:
        for step in probe['steps']:
            end = t + step.get('duration_ms', 0)
            rows.append({'action': 'wait' if step['kind'] == 'wait' else 'input',
                         'action_id': f'{probe["id"]}/{step["id"]}', 'criterion_ids': probe['criterion_ids'],
                         'planned_t_ms': t, 'planned_end_t_ms': end})
            t = end
    return rows


def schedule(actions: list[dict], recording_ms: int, engine: str | None = None) -> tuple[dict, dict]:
    """Return (capture schedule, settle guards). Raises if it cannot fit the recorder limits."""
    slots: dict[int, dict] = defaultdict(lambda: {'capture_ids': [], 'criterion_ids': []})
    guards = []
    last = recording_ms - INTERVAL_MS

    def put(at, ident, criteria):
        at = max(0, min(last, round(at / INTERVAL_MS) * INTERVAL_MS))
        slot = slots[at]
        slot['capture_ids'].append(ident)
        slot['criterion_ids'] += [c for c in criteria if c not in slot['criterion_ids']]

    for a in actions:
        if a.get('action_id') == 'system/startup':
            continue
        if a.get('action') == 'wait':
            # An observation hold (a wait that names criteria, e.g. a texture close-up) is
            # captured in its middle and at its end.
            if a.get('criterion_ids'):
                # Same-view strip every HOLD_STEP_MS from the hold's start (motion), at most HOLD_MAX points.
                start, end = a['planned_t_ms'], a['planned_end_t_ms'] - INTERVAL_MS
                n = max(1, min(HOLD_MAX, int((end - start) // HOLD_STEP_MS)))
                for k in range(n):
                    put(start + k * HOLD_STEP_MS, f'hold{k}/{a["action_id"]}', a['criterion_ids'])
                put(end, f'holdend/{a["action_id"]}', a['criterion_ids'])
            continue
        for label, anchor, offset in OFFSETS:
            base = a['planned_t_ms'] if anchor == 'start' else a['planned_end_t_ms']
            ident = f'{label}/{a["action_id"]}'
            put(base + offset, ident, a.get('criterion_ids', []))
            if anchor == 'end':
                guards.append({'capture_id': ident, 'action_id': a['action_id'], 'stable_after_ms': offset})
    if len(slots) > MAX_POINTS:
        raise ValueError(f'{len(slots)} action capture points exceed the recorder limit {MAX_POINTS}')
    # Baseline context fills only the remaining budget (action frames always take priority).
    spare = MAX_POINTS - len(slots)
    step = max(BASELINE_MS_BY_ENGINE.get(engine, BASELINE_MS),
               -(-recording_ms // max(1, spare)) // INTERVAL_MS * INTERVAL_MS + INTERVAL_MS)
    for at in range(0, recording_ms, step):
        if len(slots) >= MAX_POINTS and round(at / INTERVAL_MS) * INTERVAL_MS not in slots:
            break
        put(at, f'baseline/{at}', [])
    points = [{'at_ms': at, **slots[at]} for at in sorted(slots)]
    if len(points) > MAX_POINTS:
        raise ValueError(f'{len(points)} capture points exceed the recorder limit {MAX_POINTS}')
    sched = {'version': VERSION, 'interval_ms': INTERVAL_MS, 'tolerance_ms': TOLERANCE_MS, 'warmup_ms': 0,
             'points': points}
    return sched, {'schema': 'whitebox-native-endpoint-settle.v1', 'endpoints': guards}


def audit_capture(folder, expected: dict) -> dict:
    """Audit Stage1 slots without interpreting them as whitebox plan.windows.

    Missing slots remain explicit evidence gaps, as in the native sparse audit.
    No frames are synthesized or selected by proximity.
    """
    import math
    from pathlib import Path
    from .paths import read_json, sha256
    import json

    folder = Path(folder).resolve()
    frozen = read_json(folder / 'capture_schedule.json')
    if frozen != expected or frozen.get('version') != VERSION:
        raise ValueError('native Stage1 schedule differs from the declared schedule')
    if frozen.get('audit_protocol', AUDIT_PROTOCOL) != AUDIT_PROTOCOL or 'plan' in frozen:
        raise ValueError('not a Stage1 action capture schedule')
    if frozen.get('tolerance_ms') != TOLERANCE_MS or frozen.get('interval_ms') != INTERVAL_MS:
        raise ValueError('Stage1 capture timing policy changed')
    points = {p['at_ms']: p for p in frozen['points']}
    if not points or len(points) != len(frozen['points']) or len(points) > MAX_POINTS:
        raise ValueError('invalid Stage1 capture slots')
    ready = read_json(folder / 'play_started.json')
    offset = ready['recorder_elapsed_ms'] + frozen['warmup_ms']
    frames = [json.loads(line) for line in (folder / 'frame_index.jsonl').read_text().splitlines() if line.strip()]
    observed, images, ids = {}, {}, set()
    previous = -1
    for number, row in enumerate(frames):
        stamp = row['t_ms']
        if not isinstance(stamp, (int, float)) or not math.isfinite(stamp) or stamp <= previous:
            raise ValueError('non-increasing native Stage1 frame clock')
        previous = stamp
        ident = row['frame_id']
        if ident in ids:
            raise ValueError('duplicate native Stage1 frame id')
        ids.add(ident)
        path = (folder / row['path']).resolve()
        if not path.is_relative_to(folder) or not path.is_file() or not path.stat().st_size:
            raise ValueError('native Stage1 screenshot missing or outside take')
        images[row['path']] = sha256(path)
        point = row.get('sample_at_ms', -1)
        if point < 0:
            if number != 0 or row.get('capture_ids') != ['readiness']:
                raise ValueError('unscheduled Stage1 screenshot outside readiness')
            continue
        if point in observed or point not in points:
            raise ValueError('duplicate or undeclared Stage1 screenshot')
        expected_point = points[point]
        if any(row.get(k) != expected_point[k] for k in ('capture_ids', 'criterion_ids')):
            raise ValueError('Stage1 screenshot action/criterion mapping mismatch')
        if abs(stamp - offset - point) > frozen['tolerance_ms']:
            raise ValueError('native Stage1 screenshot missed its declared slot')
        observed[point] = ident
    if not observed:
        raise ValueError('no scheduled native Stage1 screenshots')
    return {'audit_protocol': AUDIT_PROTOCOL, 'version': frozen['version'],
            'schedule_sha256': sha256(folder / 'capture_schedule.json'),
            'planned_screenshots': len(points) + 1, 'actual_screenshots': len(frames),
            'missing_slots_ms': [p for p in points if p not in observed],
            'slot_frames': {str(k): v for k, v in observed.items()},
            'frame_sha256': images, 'continuous_full_route': False}
