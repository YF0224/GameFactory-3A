"""Time-based evidence indexes. Associations never assert gameplay causality."""
from bisect import bisect_left
import hashlib
import json
import math
from pathlib import Path

from engine_adapters.action_provenance import action_metadata

VERSION = 'whitebox-action-frame-links.v1'
CHANNELS = ('actions.jsonl', 'frame_index.jsonl', 'state_trace.jsonl', 'event_trace.jsonl')


def physical_rows(path):
    if not path.is_file():
        return []
    return [(line, json.loads(text)) for line, text in enumerate(path.read_text().splitlines(), 1)
            if text.strip()]


def timestamp(row):
    value = row.get('t_ms', row.get('timestamp_ms'))
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return value


def frame_id(row, position):
    return row.get('frame_id') or row.get('id') or f'FRAME:{position:05d}'


def observation_policy(action):
    text = (action.get('purpose', '') + ' ' + action.get('expected_observation', '')).lower()
    policies = [
        ('transition', ('phase', 'stage', 'respawn', 'restart', 'result', 'victory', '结算', '重生', '重开', '阶段', '胜利'), [180, 500, 1500, 3000]),
        ('pause', ('pause', 'resume', '暂停', '恢复'), [180, 500, 1000]),
        ('combat', ('attack', 'fire', 'dodge', 'cooldown', '攻击', '开火', '闪避', '冷却'), [180, 500, 1000]),
    ]
    for name, words, offsets in policies:
        if any(word in text for word in words):
            return name, offsets
    return 'input', [180, 500]


def build_links(folder):
    folder = Path(folder)
    schedule_path = folder/'action_schedule.json'
    schedule = json.loads(schedule_path.read_text()).get('actions', []) if schedule_path.is_file() else []
    actions = physical_rows(folder/'actions.jsonl')
    frames = physical_rows(folder/'frame_index.jsonl')
    states = physical_rows(folder/'state_trace.jsonl')
    events = physical_rows(folder/'event_trace.jsonl')
    source_paths = [folder/name for name in CHANNELS] + [schedule_path]
    if (folder/'capture_schedule.json').is_file():
        source_paths.append(folder/'capture_schedule.json')
    sources = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in source_paths if path.is_file()}
    known = {}
    for action in schedule:
        ident = action.get('action_id')
        if not ident or ident in known:
            raise ValueError('Missing or duplicate scheduled action_id')
        known[ident] = action
    grouped = {}
    unassociated = []
    for line, row in actions:
        ident = row.get('action_id')
        if not ident:
            if schedule and isinstance(row.get('index'), int) and row['index'] >= 0 and not row.get('cleanup_release'):
                raise ValueError('Recorded scheduled input has lost action provenance at line '+str(line))
            unassociated.append(line)
            continue
        if schedule and ident not in known:
            raise ValueError('Recorded action_id outside frozen schedule: '+str(ident))
        if ident in known:
            for field in ('probe_id', 'step_id', 'criterion_ids', 'purpose', 'expected_observation'):
                if row.get(field) != known[ident].get(field):
                    raise ValueError(f'Recorded action metadata mismatch: {ident}/{field}')
        else:
            known[ident] = action_metadata(row)
        grouped.setdefault(ident, []).append((line, row))
    indexed_frames = [(line, row, frame_id(row, pos)) for pos, (line, row) in enumerate(frames, 1)
                      if timestamp(row) is not None]
    indexed_frames.sort(key=lambda item: timestamp(item[1]))
    times = [timestamp(row) for _, row, _ in indexed_frames]
    links = []
    anchors = [(timestamp(row)-known[ident].get('planned_t_ms', 0))
               for ident, recorded in grouped.items() for _, row in recorded[:1]
               if timestamp(row) is not None and 'planned_t_ms' in known[ident]]
    all_indexed_frames, all_times = indexed_frames, times
    for ident, action in known.items():
        session = action.get('session_id')
        indexed_frames = ([item for item in all_indexed_frames if item[1].get('session_id') == session]
                          if session else all_indexed_frames)
        times = [timestamp(item[1]) for item in indexed_frames]
        recorded = grouped.get(ident, [])
        timed = [row for _, row in recorded if timestamp(row) is not None]
        policy, offsets = observation_policy(action)
        link = {**action_metadata(action), 'policy': policy, 'action_lines': [line for line, _ in recorded],
                'frames': {'before': [], 'during': [], 'after': []}, 'states': [], 'events': [],
                'missing_windows': [], 'gameplay_outcome': 'UNVERIFIED',
                'timing_source': 'unobserved', 'sent': any(row.get('sent') is True for _, row in recorded)}
        if session:
            link.update(session_id=session, plan_action_id=action.get('plan_action_id'))
            anchors = [timestamp(row)-known[key].get('planned_t_ms', 0)
                       for key, recorded_rows in grouped.items() if known[key].get('session_id') == session
                       for _, row in recorded_rows[:1] if timestamp(row) is not None]
        estimated_wait = not timed and action.get('action') == 'wait' and bool(anchors)
        if not timed and not estimated_wait:
            link['missing_windows'] = ['before', 'during', 'after']
            link['limitation'] = 'No recorded action time; scheduled times are not execution evidence.'
            links.append(link)
            continue
        if estimated_wait:
            start = action['planned_t_ms']+anchors[0]
            end = action['planned_end_t_ms']+anchors[0]
            link['limitation'] = 'Scheduled observation interval aligned to first recorded input; wait execution is not independently attested.'
        else:
            start = min(row.get('send_start_t_ms', timestamp(row)) for row in timed)
            end = max(row.get('end_t_ms', row.get('end_ms', row.get('completed_t_ms', timestamp(row)))) for row in timed)
        link.update(action_t_ms=start, action_end_t_ms=end, timing_source='recorded_session_time',
                    window_start_t_ms=max(0, start-1000), window_end_t_ms=end+max(offsets))
        if estimated_wait:
            link['timing_source'] = 'schedule_estimate_from_recorded_input'
        before = bisect_left(times, start)-1
        if before >= 0 and start-times[before] <= 1000:
            link['frames']['before'] = [indexed_frames[before][2]]
        overlap = [(line, row, fid) for line, row, fid in indexed_frames
                   if timestamp(row) <= end and row.get('capture_end_t_ms', timestamp(row)) >= start]
        during = list(overlap)
        for target in (start, (start+end)/2, end):
            pos = bisect_left(times, target)
            candidates = [item for item in (pos-1, pos) if 0 <= item < len(times)
                          and start <= times[item] <= end+350 and abs(times[item]-target) <= 350]
            if candidates:
                during.append(indexed_frames[min(candidates, key=lambda item: abs(times[item]-target))])
        if during:
            during.sort(key=lambda item: timestamp(item[1]))
            link['frames']['during'] = list(dict.fromkeys(during[pos][2] for pos in sorted({0, len(during)//2, len(during)-1})))
        missing_after = []
        for offset in offsets:
            target = end+offset
            pos = bisect_left(times, target)
            candidates = [item for item in (pos-1, pos) if 0 <= item < len(times)
                          and times[item] > end and abs(times[item]-target) <= 350]
            if candidates:
                chosen = min(candidates, key=lambda item: abs(times[item]-target))
                link['frames']['after'].append(indexed_frames[chosen][2])
            else:
                missing_after.append(offset)
        link['frames']['after'] = list(dict.fromkeys(link['frames']['after']))
        link['missing_after_offsets_ms'] = missing_after
        link['missing_windows'] = [role for role, selected in link['frames'].items() if not selected]
        targets = [start-120, start, (start+end)/2, end] + [end+offset for offset in offsets]
        timed_states = [(line, row) for line, row in states if timestamp(row) is not None
                        and (not session or row.get('session_id') == session)
                        and link['window_start_t_ms'] <= timestamp(row) <= link['window_end_t_ms']]
        if timed_states:
            link['states'] = sorted({min(timed_states, key=lambda item: abs(timestamp(item[1])-target))[0]
                                     for target in targets})
        link['events'] = [line for line, row in events if timestamp(row) is not None
                          and (not session or row.get('session_id') == session)
                          and link['window_start_t_ms'] <= timestamp(row) <= link['window_end_t_ms']]
        links.append(link)
    return {'version': VERSION, 'clock': 'session_monotonic', 'sources': sources, 'links': links,
            'unassociated_action_lines': unassociated,
            'note': 'Time association is an evidence index, not causality or gameplay success. '
                    'sent only proves dispatch. Missing/unsampled observations remain UNVERIFIED.'}


def write_links(folder):
    folder = Path(folder)
    result = build_links(folder)
    path = folder/'action_frame_links.json'
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    return result


def select_frames(frames, links, max_frames):
    if max_frames < 1:
        raise ValueError('Frame budget must be positive')
    positions = {frame_id(row, pos+1): pos for pos, row in enumerate(frames)}
    targets = {}
    for link in links['links']:
        for criterion in link.get('criterion_ids', []):
            targets.setdefault(criterion, []).append(link)
    selected = []
    def choose(ident):
        if ident in positions and ident not in selected and len(selected) < max_frames:
            selected.append(ident)
    for role in ('during', 'before', 'after'):
        for criterion_links in targets.values():
            candidates = [fid for link in criterion_links for fid in link['frames'][role]]
            if candidates:
                choose(candidates[0])
    queues = {criterion: list(dict.fromkeys(fid for link in criterion_links
               for role in ('during', 'before', 'after') for fid in link['frames'][role]))
              for criterion, criterion_links in targets.items()}
    for turn in range(max((len(queue) for queue in queues.values()), default=0)):
        for queue in queues.values():
            if turn < len(queue):
                choose(queue[turn])
    for link in links['links']:
        for role in ('during', 'before', 'after'):
            for ident in link['frames'][role]:
                choose(ident)
    if frames:
        for pos in range(min(12, max_frames)):
            choose(frame_id(frames[round(pos*(len(frames)-1)/max(1, min(12, max_frames)-1))],
                            round(pos*(len(frames)-1)/max(1, min(12, max_frames)-1))+1))
    selected_set = set(selected)
    clipped = [{'action_id': link['action_id'], 'probe_id': link.get('probe_id'),
                'criterion_ids': link.get('criterion_ids', []), 'role': role,
                'omitted_frame_ids': [fid for fid in ids if fid not in selected_set]}
               for link in links['links'] for role, ids in link['frames'].items()
               if any(fid not in selected_set for fid in ids)]
    report = {'version': VERSION, 'max_frames': max_frames, 'criterion_ids': list(targets),
              'selected_frame_ids': sorted(selected, key=positions.get), 'clipped_windows': clipped,
              'unobserved_criterion_ids': [criterion for criterion, rows in targets.items()
                  if not any(fid in selected_set for row in rows for ids in row['frames'].values() for fid in ids)]}
    return sorted(positions[ident] for ident in selected), report


def judge_context(links, manifest, state_lines, event_limit):
    delivered = {item['id'] for item in manifest['items'] if item['type'] == 'frame'}
    context = []
    for link in links['links']:
        context.append({**link, 'frames': {role: [fid for fid in ids if fid in delivered]
                       for role, ids in link['frames'].items()},
                       'states': [line for line in link['states'] if line in state_lines],
                       'events': [line for line in link['events'] if line <= event_limit],
                       'undelivered_state_lines': [line for line in link['states'] if line not in state_lines],
                       'undelivered_event_lines': [line for line in link['events'] if line > event_limit]})
    return {'version': VERSION, 'note': links['note'], 'links': context,
            'frame_selection': manifest.get('frame_selection', {})}
