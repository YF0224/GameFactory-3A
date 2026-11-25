"""Sparse capture and delivery audits, retaining native pixels and source clocks."""
import copy
import json
from pathlib import Path

from . import endpoint_sparse as policy
from .event_wire import enabled as event_wire_enabled, extended_rows as event_extended_rows, for_subset as event_policy_for_subset
from .action_links import frame_id
from .protocol import checked_path, dump, load_lines, sha


def audit_capture(folder, schedule=None):
    folder = Path(folder)
    frozen = json.loads((folder/'capture_schedule.json').read_text())
    if schedule is not None and frozen != schedule:
        root=folder.parent
        source=root/'input_manifest.json'
        version=json.loads(source.read_text()).get('entry',{}).get('recorded_source_version',{}) if source.is_file() else {}
        if 'unity_m_input_materialization' not in version:
            raise ValueError('native sparse schedule differs from the validated plan')
        from .unity_m_input_adapter import verify_derived_schedule
        verify_derived_schedule(folder,frozen,schedule)
    if (folder/'multisession_index.json').is_file():
        from .multiclient import audit_capture as audit_multi
        return audit_multi(folder, frozen)
    if frozen['version'] not in policy.CAPTURE_VERSIONS:
        raise ValueError('unknown native sparse capture schedule')
    ready = json.loads((folder/'play_started.json').read_text(encoding='utf-8-sig'))
    offset = ready['recorder_elapsed_ms'] + frozen['warmup_ms']
    frames = load_lines(folder/'frame_index.jsonl')
    observed = {}
    previous = -1
    for number, row in enumerate(frames, 1):
        if row['t_ms'] <= previous:
            raise ValueError('non-increasing native sparse frame clock')
        previous = row['t_ms']
        point = row.get('sample_at_ms', -1)
        if point < 0:
            if number != 1 or row.get('capture_ids') != ['readiness']:
                raise ValueError('unscheduled screenshot outside readiness')
            continue
        if point in observed or not any(item['at_ms'] == point for item in frozen['points']):
            raise ValueError('duplicate or undeclared native screenshot')
        expected = next(item for item in frozen['points'] if item['at_ms'] == point)
        if row.get('capture_ids') != expected['capture_ids']:
            raise ValueError('screenshot capture/probe mapping mismatch')
        if abs(row['t_ms'] - offset - point) > frozen['tolerance_ms']:
            raise ValueError('native screenshot missed its predeclared capture slot')
        if not checked_path(folder, row['path']).is_file():
            raise ValueError('native screenshot missing')
        observed[point] = frame_id(row, number)
    missing = [item['at_ms'] for item in frozen['points'] if item['at_ms'] not in observed]
    windows = {}
    for window in frozen['plan']['windows']:
        points = [item['at_ms'] for item in frozen['points'] if window['id'] in item['capture_ids']]
        actual = [row['t_ms'] for row in frames if row.get('sample_at_ms') in points]
        complete = all(point in observed for point in points)
        continuous = len(actual) >= 3 and all(0 < right-left <= 450 for left, right in zip(actual, actual[1:]))
        windows[window['id']] = {'complete': complete, 'continuous': continuous,
                                  'frame_ids': [observed[point] for point in points if point in observed]}
    return {'version': frozen['version'], 'schedule_sha256': sha(folder/'capture_schedule.json'),
            'planned_screenshots': len(frozen['points'])+1, 'actual_screenshots': len(frames),
            'missing_slots_ms': missing, 'windows': windows,
            'slot_frames': {str(key): value for key, value in observed.items()},
            'continuous_full_route': False,
            'intentional_gaps': 'Only readiness, endpoint slots and declared short windows are sampled.'}


def selections(protocol, plan, frames, audit):
    from .multiclient import enabled, slot
    result = {}
    # Native JSON clocks may serialize the exact declared integer slot as a
    # float. Match numerical identity, as audit_capture already requires;
    # preserve the original audit and never choose a nearby frame.
    slots = (audit['slot_frames'] if enabled(protocol) else
             {json.loads(stamp): frame for stamp, frame in audit['slot_frames'].items()})
    for ident, endpoint in plan['capture_plan']['endpoints'].items():
        key = slot(endpoint['client_role'], endpoint['at_ms']) if enabled(protocol) else endpoint['at_ms']
        frame = slots.get(key) if endpoint['probe_ids'] else None
        result[ident] = [frame] if frame else []
    return result


def groups(protocol, manifest=None):
    from .endpoint_judge_partition import FIELD, groups as partition_groups
    if manifest is not None and FIELD in manifest:
        return partition_groups(protocol, manifest)
    mechanisms = policy.mechanisms(protocol)
    others = [row for row in protocol['criteria'] if row['mode'] != 'static'
              and row['column'] not in {policy.MECHANIC, 'Gameness'}]
    gameness = [row for row in protocol['criteria'] if row['mode'] != 'static' and row['column'] == 'Gameness']
    size = protocol['judge_shard_size']
    return ([mechanisms[start:start+size] for start in range(0, len(mechanisms), size)]
            + [others[start:start+size] for start in range(0, len(others), size)] + ([gameness] if gameness else []))


def endpoint_contracts(protocol, plan, endpoints, links):
    if not policy.closed_endpoints(protocol):
        return {}
    indexed = {row['action_id']: row for row in links['links']}
    result = {}
    for ident, endpoint in plan['capture_plan']['endpoints'].items():
        from .multiclient import enabled
        last_id = endpoint['client_role']+':'+endpoint['last_action_id'] if enabled(protocol) else endpoint['last_action_id']
        last = indexed.get(last_id, {})
        result[ident] = {**copy.deepcopy(endpoint), 'frame_ids': endpoints[ident],
                        'last_action': {key:copy.deepcopy(last.get(key)) for key in
                            ('action_id','probe_id','criterion_ids','action_lines','states','events','sent','timing_source','session_id')}}
        if endpoint['reachability'] == 'EXECUTABLE' and (last.get('probe_id') not in endpoint['probe_ids']
                or ident not in last.get('criterion_ids', [])):
            raise ValueError('endpoint final action lost its frozen probe/criterion association')
    return result


def chosen_frames(specs, endpoints, audit, capture):
    selected = set()
    for spec in specs:
        if spec['column'] == policy.MECHANIC:
            selected.update(endpoints[spec['id']])
        elif spec['column'] == 'Gameness':
            for window in capture['gameness'][spec['id']]['window_ids']:
                selected.update(audit['windows'][window]['frame_ids'])
        else:
            selected.update(frame for window in audit['windows'].values() for frame in window['frame_ids'])
            selected.update(frame for values in endpoints.values() for frame in values)
    return selected


def deliver(root, protocol, manifest, *, checkpoint=False):
    from PIL import Image, ImageDraw
    from .frame_budget import channel_delivery
    root = Path(root)
    policy.validate_policy(protocol)
    plan = json.loads((root/'sol_plan.json').read_text())
    schedule = policy.validate_plan(protocol, plan, plan.get('engine', 'godot'), root=root)
    preserved = json.loads((root/'runtime/capture_schedule.json').read_text())
    schedule['warmup_ms'] = preserved['warmup_ms']
    audit = audit_capture(root/'runtime', schedule)
    frames = load_lines(root/'runtime/frame_index.jsonl')
    endpoints = selections(protocol, plan, frames, audit)
    links = json.loads((root/'runtime/action_frame_links.json').read_text())
    manifest['items'] = [row for row in manifest['items'] if row['type'] != 'frame']
    version = policy.capture_policy(protocol)['version']
    manifest.update(version=version, evidence_frame_policy=policy.capture_policy(protocol),
                    endpoint_frames=endpoints, sparse_capture_audit=audit, delivery_sheets=[], evidence_sets={})
    contracts = endpoint_contracts(protocol, plan, endpoints, links)
    if contracts:
        manifest['endpoint_contracts'] = contracts
    from .endpoint_judge_partition import FIELD, partition
    if checkpoint:
        manifest[FIELD] = partition(protocol)
    union = {}
    for number, specs in enumerate(groups(protocol, manifest), 1):
        name = f'evidence_{number:02d}'
        selected = chosen_frames(specs, endpoints, audit, plan['capture_plan'])
        indices = [index for index, row in enumerate(frames, 1) if frame_id(row, index) in selected]
        identifiers = [row['id'] for row in specs]
        subset = {'criterion_ids': identifiers, 'frames': {}, 'delivery_sheets': [],
                  'endpoint_frames': {ident: endpoints[ident] for ident in identifiers if ident in endpoints},
                  'include_references': any(row['mode'] == 'reference' for row in specs),
                  'frame_selection': {'version': version, 'selected_frame_ids': [frame_id(frames[index-1], index) for index in indices],
                                      'selection_reason': policy.capture_policy(protocol)['selection'],
                                      'clipped_windows': [], 'missing_endpoints': [ident for ident in identifiers if ident in endpoints and not endpoints[ident]],
                                      'visual_windows': audit['windows'] if any(row['column'] != policy.MECHANIC for row in specs) else {}},
                  'clipped_windows': []}
        if contracts:
            subset['endpoint_contracts'] = {ident:contracts[ident] for ident in identifiers if ident in contracts}
        for start in range(0, len(indices), 4):
            block = indices[start:start+4]
            sizes = []
            for index in block:
                with Image.open(checked_path(root/'runtime', frames[index-1]['path'])) as image:
                    sizes.append(image.size)
            width, height = max(size[0] for size in sizes), max(size[1] for size in sizes)
            sheet = Image.new('RGB', (width*2, (height+26)*2), '#101010')
            draw = ImageDraw.Draw(sheet)
            relative = f'delivery/{name}/sheet_{start//4+1:03d}.png'
            for tile, index in enumerate(block):
                row = frames[index-1]
                ident = frame_id(row, index)
                path = checked_path(root/'runtime', row['path'])
                left, top = tile%2*width, tile//2*(height+26)
                draw.text((left+6, top+5), f'{ident} | {row["t_ms"]} ms', fill='white')
                with Image.open(path) as image:
                    original_width, original_height = image.size
                    sheet.paste(image.convert('RGB'), (left, top+26))
                item = {'id': ident, 'path': str(path.relative_to(root)), 'type': 'frame', 'sha256': sha(path),
                        't_ms': row['t_ms'], 'frame_id': ident, 'delivered_to_judge': True,
                        'delivery_sheet': relative, 'tile': tile, 'tile_rect': [left, top+26, original_width, original_height]}
                if row.get('session_id'):item.update(session_id=row['session_id'],client_role=row['client_role'])
                subset['frames'][ident] = item
                union.setdefault(ident, item)
            destination = root/relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            sheet.save(destination)
            page = {'path': relative, 'sha256': sha(destination)}
            subset['delivery_sheets'].append(page)
            manifest['delivery_sheets'].append(page)
        subset['delivered_frame_count'] = len(subset['frames'])
        if contracts:
            from .endpoint_channels import select, LOSSLESS_LOG_VERSION
            from .endpoint_channels import EndpointCapacityError
            try:
                subset.update(select(root, links, identifiers, subset.get('endpoint_contracts', {}), version=LOSSLESS_LOG_VERSION, event_wire=event_wire_enabled(event_policy_for_subset(manifest, subset)), extended_event_rows=event_extended_rows(event_policy_for_subset(manifest, subset)), event_encoding=event_policy_for_subset(manifest, subset).get("event_wire_transport")))
            except EndpointCapacityError as exc:
                if not checkpoint:
                    raise
                from .endpoint_judge_partition import blocked
                subset['transport_blocked'] = blocked(exc)
        else:
            subset.update(channel_delivery(root, links))
        manifest['evidence_sets'][name] = subset
    manifest['items'].extend(union.values())
    manifest.update(raw_frame_count=len(frames), delivered_frame_count=len(union),
                    frame_selection={'version': version, 'selected_frame_ids': list(union), 'clipped_windows': []})
    return manifest


def validate(root, protocol, manifest, *, allow_incomplete=False):
    from PIL import Image
    from .frame_budget import channel_delivery
    root = Path(root)
    policy.validate_policy(protocol)
    plan = json.loads((root/'sol_plan.json').read_text())
    expected = policy.validate_plan(protocol, plan, plan.get('engine', 'godot'), root=root)
    preserved = json.loads((root/'runtime/capture_schedule.json').read_text())
    expected['warmup_ms'] = preserved['warmup_ms']
    audit = audit_capture(root/'runtime', expected)
    if audit != manifest.get('sparse_capture_audit'):
        raise ValueError('sparse native capture audit changed')
    frames = load_lines(root/'runtime/frame_index.jsonl')
    endpoints = selections(protocol, plan, frames, audit)
    if endpoints != manifest.get('endpoint_frames'):
        raise ValueError('endpoint frames are not the predeclared final observations')
    indexed = {frame_id(row, index): row for index, row in enumerate(frames, 1)}
    links = json.loads((root/'runtime/action_frame_links.json').read_text())
    contracts = endpoint_contracts(protocol, plan, endpoints, links)
    if contracts and contracts != manifest.get('endpoint_contracts'):
        raise ValueError('endpoint rubric/final-action/frame/state/event chain changed')
    expected_groups = groups(protocol, manifest)
    subsets = list(manifest['evidence_sets'].values())
    if [subset['criterion_ids'] for subset in subsets] != [[spec['id'] for spec in specs] for specs in expected_groups]:
        raise ValueError('sparse evidence groups changed')
    union = set()
    for specs, subset in zip(expected_groups, subsets):
        if contracts and subset.get('endpoint_contracts') != {spec['id']:contracts[spec['id']] for spec in specs if spec['id'] in contracts}:
            raise ValueError('delivered endpoint obligations differ from frozen source chain')
        chosen = chosen_frames(specs, endpoints, audit, plan['capture_plan'])
        if set(subset['frames']) != chosen or subset['delivered_frame_count'] != len(chosen):
            raise ValueError('sparse evidence frame selection differs from planned slots')
        from .endpoint_judge_partition import FIELD, blocked
        from .endpoint_channels import select, LOSSLESS_LOG_VERSION, EndpointCapacityError
        if 'transport_blocked' in subset:
            if FIELD not in manifest or any(key in subset for key in
                    ('channel_transport', 'delivered_channel_lines', 'channel_omissions')):
                raise ValueError('Blocked transport cannot claim delivered channels')
            try:
                select(root, links, subset['criterion_ids'], subset.get('endpoint_contracts', {}),
                       version=LOSSLESS_LOG_VERSION, event_wire=event_wire_enabled(event_policy_for_subset(manifest, subset)), extended_event_rows=event_extended_rows(event_policy_for_subset(manifest, subset)), event_encoding=event_policy_for_subset(manifest, subset).get("event_wire_transport"))
            except EndpointCapacityError as exc:
                if subset['transport_blocked'] != blocked(exc):
                    raise ValueError('Blocked transport diagnostic changed') from exc
            else:
                raise ValueError('Transport is deliverable, not blocked')
        else:
            if subset.get('channel_transport'):
                transport = select(root, links, subset['criterion_ids'], subset.get('endpoint_contracts', {}),
                                   version=subset['channel_transport']['version'], event_wire=event_wire_enabled(event_policy_for_subset(manifest, subset)), extended_event_rows=event_extended_rows(event_policy_for_subset(manifest, subset)), event_encoding=event_policy_for_subset(manifest, subset).get("event_wire_transport"))
            else:
                transport = channel_delivery(root, links)
            if any(subset.get(key) != value for key, value in transport.items()):
                raise ValueError('sparse channel delivery differs from raw physical lines')
        union.update(chosen)
        for page in subset['delivery_sheets']:
            path = checked_path(root, page['path'])
            if sha(path) != page['sha256']:
                raise ValueError('sparse delivery sheet changed')
            with Image.open(path) as sheet:
                for ident, item in subset['frames'].items():
                    if item['delivery_sheet'] != page['path']:
                        continue
                    row = indexed[ident]
                    original = checked_path(root/'runtime', row['path'])
                    left, top, width, height = item['tile_rect']
                    tile = item['tile']
                    if (item['path'] != str(original.relative_to(root)) or sha(original) != item['sha256']
                            or item['t_ms'] != row['t_ms'] or tile not in range(4)
                            or [left, top] != [tile%2*(sheet.width//2), tile//2*(sheet.height//2)+26]):
                        raise ValueError('sparse tile/source/time mismatch')
                    with Image.open(original) as image:
                        if image.size != (width, height) or image.convert('RGB').tobytes() != sheet.crop((left, top, left+width, top+height)).convert('RGB').tobytes():
                            raise ValueError('sparse sheet does not preserve native pixels')
    if union != {item['id'] for item in manifest['items'] if item['type'] == 'frame'}:
        raise ValueError('sparse manifest frame union mismatch')
    if any('transport_blocked' in subset for subset in subsets):
        from .endpoint_judge_partition import IncompleteEndpointDelivery, incomplete_message
        if not allow_incomplete:
            raise IncompleteEndpointDelivery(incomplete_message(manifest))
    return True
