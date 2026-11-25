"""Immutable mechanism tiers and predeclared endpoint/Gameness observations."""
import copy
import json
from pathlib import Path

from .protocol import COLUMNS, checked_path, dump, sha

LEGACY_VERSION = 'whitebox-mechanic10-50-100.v1'
VERSION = 'whitebox-mechanic10-50-100.v2'
VERSIONS = {LEGACY_VERSION, VERSION}
LEGACY_CAPTURE_VERSION = 'whitebox-endpoint-gameness-sparse.v1'
CAPTURE_VERSION = 'whitebox-endpoint-gameness-sparse.v2'
CAPTURE_VERSIONS = {LEGACY_CAPTURE_VERSION, CAPTURE_VERSION}
MECHANIC = COLUMNS[1]


def enabled(protocol):
    return protocol.get('scoring_policy', {}).get('version') in VERSIONS


def closed_endpoints(protocol):
    return protocol.get('scoring_policy', {}).get('version') == VERSION


def mechanisms(protocol):
    return [row for row in protocol['criteria'] if row['column'] == MECHANIC]


def gameness_mapping(protocol):
    return [{'criterion_id': row['id'], 'group': row['group'], 'requirement': row['requirement'],
             'visual_window': 'short native sequence for temporal claims; endpoint for static claims'}
            for row in protocol['criteria'] if row['column'] == 'Gameness']


def scoring_policy(protocol):
    return {'version': protocol.get('scoring_policy', {}).get('version', VERSION), 'model': 'gpt-6.1-sol', 'columns': [MECHANIC],
            'criterion_ids': [row['id'] for row in mechanisms(protocol)],
            'tiers': [0, .1, .5, 1], 'aggregation': 'maximum achieved tier, never additive',
            'formula': '1 if executed and complete endpoint PASS; else .5 if observed normal execution; else .1 if source EXISTS; else 0',
            'verified_only': 'Only original complete rubric PASS/FAIL; partial credits do not change status.',
            'indicator_weights': {name: 1/8 for name in COLUMNS},
            'gameness_mapping': gameness_mapping(protocol),
            'gameness_groups': ['layout', 'guidance', 'feedback']}


def capture_policy(protocol):
    return {'version': CAPTURE_VERSION if closed_endpoints(protocol) else LEGACY_CAPTURE_VERSION, 'frame_budget': 360,
            'endpoint_ids': [row['id'] for row in mechanisms(protocol)],
            'gameness_mapping': gameness_mapping(protocol),
            'sample_interval_ms': 100, 'sample_tolerance_ms': 350,
            'maximum_windows': 16, 'maximum_window_ms': 2000,
            'transport': {'maximum_images': 100, 'maximum_prompt_bytes': 1000000,
                          'pixels': 'four native-resolution frames per image; no rescaling'},
            'selection': 'Only predeclared endpoints and short windows; no route-wide fill or best-frame selection.'}


def freeze(protocol):
    from . import tiered_core
    tiered_core.targets(protocol)
    for row in mechanisms(protocol):
        row['execution_tiers'] = VERSION
    protocol['scoring_policy'] = {'version': VERSION}
    protocol['scoring_policy'] = scoring_policy(protocol)
    protocol['evidence_frame_policy'] = capture_policy(protocol)
    return protocol


def validate_policy(protocol):
    if not enabled(protocol) or protocol['scoring_policy'] != scoring_policy(protocol):
        raise ValueError('unknown or altered mechanism tier policy')
    if protocol.get('evidence_frame_policy') != capture_policy(protocol):
        raise ValueError('mechanism tiers require the matching sparse capture policy')


def shared_conditions_path(batch, protocol):
    return Path(batch)/'endpoint_conditions'/(protocol['case_id']+'.'+CAPTURE_VERSION+'.json')


def freeze_conditions(root, protocol, plan):
    if not closed_endpoints(protocol):
        return
    import fcntl
    root = Path(root)
    path = shared_conditions_path(root.parent.parent, protocol)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {'version':CAPTURE_VERSION, 'case_id':protocol['case_id'],
              'endpoints':{ident:copy.deepcopy(value['rubric']) for ident,value in plan['capture_plan']['endpoints'].items()}}
    with path.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if path.exists():
            if json.loads(path.read_text()) != record:
                raise ValueError('Sol changed the shared frozen game endpoint conditions')
        else:
            dump(path, record)
    dump(root/'endpoint_conditions_receipt.json', {'path':str(path.resolve()), 'sha256':sha(path),
         'sol_plan_sha256':sha(root/'sol_plan.json'), 'frozen_before_actions':True})


def plan_schema(protocol):
    from .codex import obj, arr, S, I
    endpoint = obj({'at_ms': I, 'condition': S, 'probe_ids': arr(S), 'limitation': S})
    if closed_endpoints(protocol):
        endpoint = obj({**endpoint['properties'],
            'reachability': {'type':'string', 'enum':['EXECUTABLE','UNREACHABLE']},
            'legal_route': S, 'last_action_id': S, 'stable_after_ms': I, 'stable_condition': S,
            'source_evidence': arr(obj({'path':S, 'line_start':I, 'line_end':I, 'sha256':S, 'reason':S})),
            'rubric': obj({'requirement':S, 'visible_conditions':arr(S),
                          'state_event_conditions':arr(S), 'rubric_basis':arr(S)})})
    from . import multiclient
    if multiclient.enabled(protocol):
        multiclient.role_field(endpoint)
    window = obj({'id': S, 'start_ms': I, 'end_ms': I, 'probe_ids': arr(S), 'reason': S})
    if multiclient.enabled(protocol):
        multiclient.role_field(window)
    mapping = obj({'window_ids': arr(S), 'reason': S})
    return obj({'version': {'type': 'string', 'enum': [capture_policy(protocol)['version']]},
                'endpoints': obj({row['id']: copy.deepcopy(endpoint) for row in mechanisms(protocol)}),
                'windows': dict(arr(window), maxItems=16),
                'gameness': obj({row['criterion_id']: copy.deepcopy(mapping) for row in gameness_mapping(protocol)})})


def plan_prompt(protocol):
    legacy = '''
SPARSE CAPTURE POLICY: supply capture_plan, version whitebox-endpoint-gameness-sparse.v1.
endpoints keys are the full scored atom IDs below, including on Unity's endpoint-keyed wire.
For each PLANNED target declare one stable final observation at_ms inside its coverage window,
condition describing the complete original rubric endpoint, and the same probe_ids as coverage.
Use the last observation near the end of the probe, at least 150ms before its end to allow capture;
include necessary settling waits in the actual route. Never choose a best-looking frame afterwards.
For UNVERIFIED targets use at_ms=0, probe_ids=[], condition and limitation explain missing evidence.
windows: at most 16 short continuous native sequences, each 200..2000ms at 10fps. Reuse necessary
movement, turning, hits, camera changes and feedback in the existing route, without new objectives.
Declare unique id, start_ms, end_ms, probe_ids and source-based reason; keep within actual probes.
gameness has exactly the frozen criterion IDs, each with window_ids and reason. All three original
groups remain intact. Share windows; if the route cannot observe a check, use [] and state why.
Static visual checks can share a short existing window. Do not add unrelated gameplay, full endings,
death/restart sequences, or waits merely for screenshots. Other six columns retain their rubric.
Action/state/event/error logs remain continuous even where screenshots are intentionally absent.
'''
    if closed_endpoints(protocol):
        legacy = legacy.replace(LEGACY_CAPTURE_VERSION, CAPTURE_VERSION).replace(
            'For UNVERIFIED targets use at_ms=0, probe_ids=[], condition and limitation explain missing evidence.',
            '''For EVERY executable endpoint use PLANNED coverage and real legal input probes, even if the
complete rubric is difficult or cannot all be proved. UNVERIFIED is a verification status, NOT
a reason to omit actions/endpoints. All frozen endpoints must be considered individually.
Only a source-proven unavailable implementation/entry/prerequisite permits UNREACHABLE with
at_ms=0, probe_ids=[], last_action_id="", stable_after_ms=0, and a concrete limitation.
Missing controlled comparisons or insufficient proof of the full rubric do NOT mean unreachable.
For each endpoint extract rubric.requirement verbatim from its frozen requirement. rubric_basis
quotes exact original rubric/requirement text; visible_conditions describes the stable last-frame
result; state_event_conditions preserves all quantitative/timer/order/threshold/counter conditions
that a single frame cannot prove. These are evidence obligations within ONE endpoint, no new atoms.
Reuse shared frozen endpoint_conditions.json when present, verbatim. Never relax original rubric.
reachability=EXECUTABLE: legal_route explains source-derived prerequisites and physical input route.
last_action_id is probe_id/step_id of the last NON-WAIT action exercising this endpoint before its
capture (not a later shared action). Follow that action with a settling wait. stable_after_ms>=150;
at_ms must follow action completion plus stable_after_ms and remain >=150ms before coverage end.
stable_condition names the observed final state; schedule time alone does not assert stability.
source_evidence cites actual input/project-relative files, physical line ranges, SHA256 and reason
establishing bindings/routes or the specific unreachable cause. No invented state or direct calls.
Use actual endpoint probe assignments even for shared setup, movement and passive light cycles.
Bind every relevant physical action to the endpoint so partial normal execution is auditable.''')
        legacy += '''
WIRE/TIMELINE CHECKLIST: All probe IDs and ALL step IDs are globally unique, including across
different probes: prefix each step ID with its probe ID (e.g. p1_start, p2_start). This does not
change action_id syntax, which remains probe_id/step_id. source_evidence.path is relative to
input/project: use Assets/... or Scripts/...; NEVER prefix it with project/ or input/project/.
Compute the timeline with startup=1800ms, then sum actual step durations (input minimum 100ms).
Set coverage.start_ms to the actual first referenced probe start, coverage.end_ms to the actual
last referenced probe end. Never subtract a capture margin from coverage.start_ms. The capture
itself is near coverage.end_ms-200; add a genuine settling wait after the last relevant input.
If an endpoint's coverage crosses intervening probes, include EVERY intervening probe and bind
that endpoint in each probe. Do not list a remote later probe outside the coverage interval.
If observing an earlier partial result, use a shorter coverage and omit later probes for that
endpoint; do not claim a later recovery probe is covered by an earlier checkpoint snapshot.
Keep prose concise: one or two source references per endpoint, short source-based route, and
compact complete visible/state-event conditions. Preserve every original numeric/timer/order
obligation while avoiding repeated source explanations. Do not add independent scoring items.
'''
    return legacy + '\nCAPTURE ATOM IDS: ' + json.dumps([row['id'] for row in mechanisms(protocol)]) + '\nGAMENESS MAPPING: ' + json.dumps(gameness_mapping(protocol), ensure_ascii=False)


def validate_plan(protocol, plan, engine, root=None):
    from .codex import validate_schema
    from .runtime import native_actions
    validate_policy(protocol)
    capture = plan.get('capture_plan')
    validate_schema(capture, plan_schema(protocol))
    coverage = {row['atom_id']: row for row in plan['coverage']}
    if engine == 'godot':
        # Godot now records this same native sparse schedule. Require the real
        # engine acceptance and pinned adapter before using its action timeline.
        if root is None:
            raise ValueError('Godot sparse schedule requires a source-bound native acceptance')
        from .qualified_history import native_acceptance
        native_acceptance(root)
    actions = native_actions(plan)
    from . import multiclient
    multiclient.validate(protocol, plan, actions)
    spans = {}
    for action in actions:
        probe = action['probe_id']
        if probe not in spans:
            spans[probe] = [action['planned_t_ms'], action['planned_end_t_ms']]
        spans[probe][1] = action['planned_end_t_ms']
    points = []
    specs = {row['id']: row for row in mechanisms(protocol)}
    for ident, endpoint in capture['endpoints'].items():
        window = coverage[ident]
        if not endpoint['condition'].strip():
            raise ValueError('endpoint must declare its final condition')
        if closed_endpoints(protocol):
            rubric = endpoint['rubric']
            if (rubric['requirement'] != specs[ident]['requirement'] or not rubric['visible_conditions']
                    or not rubric['rubric_basis'] or any(not text.strip() for values in
                    (rubric['visible_conditions'], rubric['state_event_conditions'], rubric['rubric_basis']) for text in values)
                    or not endpoint['legal_route'].strip()
                    or (endpoint['reachability'] != 'UNREACHABLE' and not endpoint['source_evidence'])):
                fields = []
                if rubric['requirement'] != specs[ident]['requirement']:fields.append('rubric.requirement differs from frozen check')
                if not rubric['visible_conditions']:fields.append('rubric.visible_conditions is empty')
                if not rubric['rubric_basis']:fields.append('rubric.rubric_basis is empty')
                for key in ('visible_conditions','state_event_conditions','rubric_basis'):
                    if any(not text.strip() for text in rubric[key]):fields.append('rubric.'+key+' contains blank text')
                if not endpoint['legal_route'].strip():fields.append('legal_route is blank')
                if endpoint['reachability'] != 'UNREACHABLE' and not endpoint['source_evidence']:fields.append('source_evidence is empty')
                raise ValueError('endpoint requires original rubric, visible/state obligations and a source-grounded route; '
                    + 'capture_plan.endpoints.' + ident + ': ' + '; '.join(fields))
            if root is not None:
                rubric_context = (Path(root)/'input/requirement.txt').read_text() + '\n' + (Path(root)/'input/frozen_rubric.json').read_text()
                if any(text not in rubric_context and text != specs[ident]['requirement'] for text in rubric['rubric_basis']):
                    raise ValueError('endpoint rubric basis must quote the original frozen rubric or requirement')
                for reference in endpoint['source_evidence']:
                    path = checked_path(Path(root)/'input/project', reference['path'])
                    if (sha(path) != reference['sha256'] or not reference['reason'].strip()
                            or not 1 <= reference['line_start'] <= reference['line_end'] <= len(path.read_text().splitlines())):
                        raise ValueError('endpoint route/source evidence differs from frozen source')
                shared = Path(root)/'input/endpoint_conditions.json'
                if shared.is_file() and json.loads(shared.read_text())['endpoints'][ident] != rubric:
                    raise ValueError('endpoint rubric conditions differ from shared game contract')
            if (window['status'] == 'UNVERIFIED') != (endpoint['reachability'] == 'UNREACHABLE'):
                raise ValueError('executable endpoint cannot omit real probe/action coverage')
            if endpoint['reachability'] == 'UNREACHABLE' and (endpoint['last_action_id'] or endpoint['stable_after_ms']):
                raise ValueError('unreachable endpoint cannot invent a final action')
        if window['status'] == 'UNVERIFIED':
            if endpoint['at_ms'] != 0 or endpoint['probe_ids'] or not endpoint['limitation'].strip():
                raise ValueError('unreachable endpoint must retain its limitation without a fake frame')
            continue
        stamp = endpoint['at_ms']
        if (endpoint['probe_ids'] != window['probe_ids'] or not window['start_ms'] <= stamp < window['end_ms']
                or not window['end_ms']-500 <= stamp <= window['end_ms']-150):
            raise ValueError('endpoint is not the declared final observation in its coverage window: '+ident)
        if closed_endpoints(protocol):
            inputs = [action for action in actions if action['probe_id'] in endpoint['probe_ids']
                      and ident in action['criterion_ids'] and action['action'] != 'wait'
                      and (not multiclient.enabled(protocol) or action.get('client_role') in {endpoint['client_role'], 'BOTH'})
                      and window['start_ms'] <= action['planned_t_ms'] < stamp]
            if (not inputs or inputs[-1]['action_id'] != endpoint['last_action_id']
                    or endpoint['stable_after_ms'] < 150 or not endpoint['stable_condition'].strip()
                    or inputs[-1]['planned_end_t_ms'] + endpoint['stable_after_ms'] > stamp
                    or any(action['planned_t_ms'] >= stamp and action['planned_t_ms'] < window['end_ms']
                           for action in actions if action['action'] != 'wait' and ident in action['criterion_ids']
                           and (not multiclient.enabled(protocol) or action.get('client_role') in {endpoint['client_role'], 'BOTH'})
                           and action['probe_id'] in endpoint['probe_ids'])):
                raise ValueError('endpoint must follow its actual last input and declared settling observation: '+ident+'; '+json.dumps({'endpoint_at_ms': stamp, 'declared_last_action_id': endpoint['last_action_id'], 'actual_last_action_id': inputs[-1]['action_id'] if inputs else None, 'actual_last_input_end_ms': inputs[-1]['planned_end_t_ms'] if inputs else None, 'stable_after_ms': endpoint['stable_after_ms'], 'stable_condition_blank': not endpoint['stable_condition'].strip(), 'coverage_end_ms': window['end_ms']}, sort_keys=True))
        points.append({'id': 'endpoint/'+ident, 'at_ms': stamp, 'criterion_ids': [ident],
                       **({'client_role':endpoint['client_role']} if multiclient.enabled(protocol) else {})})
    windows = capture['windows']
    if len({row['id'] for row in windows}) != len(windows):
        raise ValueError('duplicate visual window')
    for window in windows:
        if (not window['id'] or not window['reason'].strip() or not window['probe_ids']
                or any(probe not in spans for probe in window['probe_ids'])
                or not 200 <= window['end_ms']-window['start_ms'] <= 2000
                or window['start_ms'] < min(spans[probe][0] for probe in window['probe_ids'])
                or window['end_ms'] > max(spans[probe][1] for probe in window['probe_ids'])):
            raise ValueError('visual window lies outside actual probes or its frozen sampling bounds')
    known = {window['id'] for window in windows}
    used = set()
    for mapping in capture['gameness'].values():
        if not mapping['reason'].strip() or len(set(mapping['window_ids'])) != len(mapping['window_ids']) or not set(mapping['window_ids']) <= known:
            raise ValueError('Gameness mapping must explain exactly the declared visual windows')
        used.update(mapping['window_ids'])
    if used != known:
        raise ValueError('visual window has no frozen Gameness purpose; unmapped_window_ids='+json.dumps(sorted(known-used)))
    for window in windows:
        for stamp in range(window['start_ms'], window['end_ms']+1, 100):
            points.append({'id': window['id'], 'at_ms': stamp,
                           **({'client_role':window['client_role']} if multiclient.enabled(protocol) else {}),
                           'criterion_ids': [ident for ident, mapping in capture['gameness'].items() if window['id'] in mapping['window_ids']]})
    by_time = {}
    for point in points:
        key = (point.get('client_role', ''), point['at_ms'])
        merged = by_time.setdefault(key, {'at_ms': point['at_ms'], 'capture_ids': [], 'criterion_ids': [],
                 **({'client_role':point['client_role']} if 'client_role' in point else {})})
        merged['capture_ids'].append(point['id'])
        merged['criterion_ids'] = sorted(set(merged['criterion_ids']) | set(point['criterion_ids']))
    if len(by_time) > capture_policy(protocol)['frame_budget']:
        raise ValueError('predeclared sparse schedule exceeds its bounded capture budget')
    return {'version': capture_policy(protocol)['version'], 'interval_ms': 100, 'tolerance_ms': 350,
            'points': [by_time[key] for key in sorted(by_time)], 'plan': capture}


def execution_schema():
    from .codex import obj, arr, S, B
    return obj({'status': {'type': 'string', 'enum': ['NORMAL', 'BUG', 'UNOBSERVED', 'HARNESS_ERROR']},
                'triggered': B, 'completion_observed': B, 'observable_change': B,
                'observed_state_paths': arr(S), 'observed_event_names': arr(S), 'reason': S})


def endpoint_verification_schema():
    from .codex import obj, arr, S, B
    return obj({'last_action_completed':B, 'stable_result':B, 'visible_conditions':arr(B),
                'state_event_conditions':arr(B), 'reason':S})


def execution_credit(row, static_row, *, evidence_valid=False, endpoint_valid=False):
    exists = static_row.get('static_existence') == 'EXISTS'
    execution = row.get('execution', {})
    if execution.get('status') == 'HARNESS_ERROR':
        raise ValueError('execution observer/harness failed; cannot publish a score')
    normal = (execution.get('status') == 'NORMAL' and execution.get('triggered') is True
              and execution.get('completion_observed') is True and execution.get('observable_change') is True
              and bool(execution.get('reason', '').strip()) and row['status'] != 'FAIL' and evidence_valid)
    complete = normal and row['status'] == 'PASS' and not row.get('validation_issues') and endpoint_valid
    return 1.0 if complete else .5 if normal else .1 if exists else 0.0


def observation_support(root, protocol, row):
    from .action_links import physical_rows, timestamp
    root = Path(root)
    manifest = json.loads((root/'evidence_manifest.json').read_text())
    items = {item['id']: item for item in manifest['items']}
    channels = {'action': [], 'state': [], 'event': [], 'log': []}
    frames = []
    linked_action_lines = set()
    links_path = root/'runtime/action_frame_links.json'
    if links_path.is_file():
        links = json.loads(links_path.read_text()).get('links', [])
        linked_action_lines = {
            line for link in links if row['id'] in link.get('criterion_ids', [])
            for line in link.get('action_lines', [])
        }
    for ref in row.get('evidence', []):
        item = items.get(ref['id'])
        if item is None or sha(checked_path(root, item['path'])) != item['sha256']:
            raise ValueError('tier evidence is outside the immutable manifest')
        if item['type'] == 'frame':
            frames.append(item['id'])
        elif item['type'] in channels:
            path = checked_path(root, item['path'])
            start, end = ref['line_start'], ref['line_end']
            if not 1 <= start <= end <= len(path.read_text(errors='replace').splitlines()):
                raise ValueError('invalid tier evidence physical lines')
            if item['type'] == 'log':
                channels['log'].append(ref)
            elif item['type'] == 'action':
                channels['action'].extend(
                    value for line, value in physical_rows(path)
                    if start <= line <= end and (
                        row['id'] in value.get('criterion_ids', []) or line in linked_action_lines))
            else:
                channels[item['type']].extend(value for line, value in physical_rows(path) if start <= line <= end)
    role = manifest.get('endpoint_contracts', {}).get(row['id'], {}).get('client_role')
    if manifest.get('clock') == 'independent_role_local_monotonic':
        if role not in {'A','B'}:raise ValueError('Tier endpoint lacks native client role')
        channels.update({name:[value for value in channels[name] if value.get('session_id')==role]
                         for name in ('action','state','event')})
        frames=[ident for ident in frames if ident.startswith(role+':')]
    actions = [value for value in channels['action'] if value.get('sent') is True
               and not value.get('cleanup_release')
               and value.get('phase') not in {'up', 'release'}]
    states = channels['state']
    events = channels['event']
    def field(value, path):
        if not isinstance(value, dict):
            return None
        original = value
        # Godot native watches serialize under `values`; Unity/Three.js use
        # `state`. Decode the recorded container once, keeping recorder
        # metadata (probe/step/provenance) outside the product-state payload.
        if 'state' in value:
            value = value['state']
        elif 'values' in value:
            value = value['values']
            # Accepted native judgments also name paths as values.watch.field.
            # Strip only that recorder prefix before decoding the watch value.
            if path.startswith('values.'):
                path = path[len('values.'):]
            # A native watch may have a short recorder name while the judge
            # cites the exact source property retained in its provenance.
            # Resolve only one delivered watch; metadata is never state.
            provenance = original.get('provenance', {})
            if isinstance(value, dict) and path not in value and path.split('.')[0] not in value:
                matches = []
                if isinstance(provenance, dict):
                    for alias, origin in provenance.items():
                        prop = origin.get('property') if isinstance(origin, dict) else None
                        if (alias in value and isinstance(prop, str) and prop
                                and (path == prop or path.startswith(prop+'.'))):
                            matches.append(alias+path[len(prop):])
                if len(matches) == 1:
                    path = matches[0]
                elif matches:
                    return None
        if not isinstance(value, dict):
            return None
        # Native public-field observers emit literal dotted property keys too.
        if path in value:
            return value[path]
        parts = path.split('.')
        for index, part in enumerate(parts):
            if not isinstance(value, dict) or part not in value:
                return None
            value = value[part]
            if index == 0 and isinstance(value, str):
                try:
                    value = json.loads(value)
                except json.JSONDecodeError:
                    return None
        return value
    changed = False
    for path in row.get('execution', {}).get('observed_state_paths', []):
        if any(token in path.lower() for token in ('clock', 'timestamp', 'frame', 't_ms', 'elapsed', 'time_since')):
            continue
        values = [field(value, path) for value in states]
        values = [json.dumps(value, sort_keys=True) for value in values if value is not None]
        if len(set(values)) >= 2:
            changed = True
    named = set(row.get('execution', {}).get('observed_event_names', []))
    def event_name(value):
        if not isinstance(value, dict):
            return None
        # Native Action<T> events retain scalar/null/list arguments verbatim.
        # Only object payloads carry named event metadata; a scalar argument
        # does not become an event name or a product-state observation.
        payload = value.get('payload')
        payload = payload if isinstance(payload, dict) else {}
        candidates = (payload.get('key'), payload.get('event'), payload.get('name'),
                      value.get('name'), value.get('event_name'),
                      value.get('event') if value.get('event') != 'OnEvent' else None)
        return next((name for name in candidates if isinstance(name, str) and name), None)

    event_observed = any(event_name(value) in named for value in events)
    times = {timestamp(value) for value in states+events if timestamp(value) is not None}
    from .endpoint_channels import checked_error_screen
    log_supported = bool(channels['log']) or checked_error_screen(root, manifest, row['id'])
    # Native state/event clocks serialize integer milliseconds; action clocks
    # retain fractions. Account only for that sub-millisecond quantization.
    clock_slack_ms = 1 if times and all(isinstance(value, int) for value in times) else 0
    observed = bool(actions and log_supported and (changed or event_observed) and len(times) >= 2
                    and any(min(times)-clock_slack_ms <= timestamp(value) <= max(times)+clock_slack_ms
                            for value in actions if timestamp(value) is not None))
    endpoint_ids = set(manifest.get('endpoint_frames', {}).get(row['id'], []))
    endpoint = bool(endpoint_ids & set(frames))
    if closed_endpoints(protocol) and endpoint:
        contract = manifest.get('endpoint_contracts', {}).get(row['id'], {})
        last = contract.get('last_action', {})
        recorded = dict(physical_rows(root/'runtime/actions.jsonl'))
        last_rows = [recorded[line] for line in last.get('action_lines', []) if line in recorded]
        actual_end = max((timestamp(value) for value in last_rows if timestamp(value) is not None), default=None)
        endpoint = bool(contract.get('reachability') == 'EXECUTABLE' and actual_end is not None
                        and any(value.get('sent') is True and not value.get('cleanup_release')
                                and value.get('phase') not in {'up','release'} for value in last_rows)
                        and any(items[ident].get('t_ms', -1) >= actual_end + contract.get('stable_after_ms', 150)
                                for ident in endpoint_ids & set(frames)))
    return observed, endpoint


def apply(report, protocol, static_result, root):
    from .partial_scoring import make_rubric
    validate_policy(protocol)
    expected = {row['id'] for row in protocol['criteria']}
    if len(report['checks']) != len(expected) or {row['id'] for row in report['checks']} != expected:
        raise ValueError('tier scoring needs every frozen verdict exactly once')
    if set(static_result['checks']) != {row['id'] for row in mechanisms(protocol)}:
        raise ValueError('independent source checks must cover exactly C2')
    credits = {}
    for row in report['checks']:
        if row['column'] != MECHANIC:
            continue
        observed, endpoint = observation_support(root, protocol, row)
        value = execution_credit(row, static_result['checks'][row['id']], evidence_valid=observed, endpoint_valid=endpoint)
        credits[row['id']] = {'credit': value, 'static_existence': static_result['checks'][row['id']],
                              'execution': copy.deepcopy(row.get('execution')), 'observed_execution': observed,
                              'endpoint_evidence': endpoint, 'runtime_status': row['status']}
    version = protocol['scoring_policy']['version']
    rubric = make_rubric(protocol, version=version)
    endpoints = {ident: {'score': round(100*sum(credits[atom]['credit'] for atom in atoms)/len(atoms), 2),
                         'weight': rubric['endpoint_weight'], 'atom_ids': atoms}
                 for ident, atoms in rubric['endpoint_atoms'].items()}
    report['columns'][MECHANIC]['score'] = round(sum(row['score']*row['weight'] for row in endpoints.values()), 2)
    report['overall_score'] = round(sum(report['columns'][name]['score']/8 for name in COLUMNS), 2)
    report.update(scoring_protocol=version, scoring_policy=scoring_policy(protocol), mechanism_endpoints=endpoints,
                  indicator_weights={name: 1/8 for name in COLUMNS}, mechanism_tiers=credits,
                  calculation=scoring_policy(protocol)['formula'])
    return {'rubric_version': version, 'endpoints': endpoints, 'total_score': report['overall_score'],
            'indicator_scores': {name: row['score'] for name, row in report['columns'].items()},
            'indicator_weights': report['indicator_weights'], 'calculation': report['calculation'], 'credits': credits}
