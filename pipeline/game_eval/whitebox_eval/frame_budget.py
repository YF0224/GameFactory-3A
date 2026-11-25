"""Versioned atom budgets and actual per-shard native-pixel image deliveries."""
import copy
import json
from pathlib import Path

from .protocol import checked_path, dump, load_lines, sha

VERSION = 'whitebox-evidence-frames-by-atoms.v1'
REQUEST_TRANSPORT_VERSION = 'whitebox-judge-request-transport.images100.v1'


def runtime_ids(protocol):
    ids = [row['id'] for row in protocol['criteria']
           if row.get('mode') != 'static' and row.get('scoring_role', 'scored') == 'scored']
    if len(ids) != len(set(ids)):
        raise ValueError('duplicate scored runtime atoms; aliases cannot increase frame budget')
    return sorted(ids)


def policy(protocol):
    from . import endpoint_sparse
    if endpoint_sparse.enabled(protocol):
        return endpoint_sparse.capture_policy(protocol)
    ids = runtime_ids(protocol)
    return {'version': VERSION, 'runtime_atom_count': len(ids), 'runtime_atom_ids': ids,
            'formula': 'min(240,max(96,6*N))', 'minimum': 96, 'per_atom': 6, 'maximum': 240,
            'frame_budget': min(240, max(96, 6 * len(ids))),
            'scope': 'Per actual evidence shard; original raw frames are retained.',
            'transport': {'maximum_images': 64, 'maximum_prompt_bytes': 1000000,
                          'pixels': 'four native-resolution frames per image; no rescaling'},
            'selection': 'All before/during/after action stages first; uniform full-route samples second. Split criteria before clipping.'}


def enabled(protocol):
    record = protocol.get('evidence_frame_policy')
    if record is None:
        return False
    if record != policy(protocol):
        raise ValueError('unknown or altered atom-based evidence frame policy')
    return True


def scoped_links(links, identifiers):
    links = copy.deepcopy(links)
    result = copy.deepcopy(links)
    matching = [row for row in links['links'] if set(row.get('criterion_ids', [])) & set(identifiers)]
    if matching:
        last = max(links['links'].index(row) for row in matching)
        prerequisites = [row for row in links['links'][:last+1] if row not in matching]
        by_probe = {}
        for row in prerequisites:
            by_probe.setdefault(row.get('probe_id'), []).append(row)
        anchors = {row['action_id'] for rows in by_probe.values()
                   for row in (rows[0], rows[len(rows)//2], rows[-1])}
        for row in prerequisites:
            if row['action_id'] not in anchors:
                row['frames'] = {stage: [] for stage in row['frames']}
        result['links'] = matching + prerequisites
        result['context_action_ids'] = [row['action_id'] for row in prerequisites]
    else:
        result['links'] = copy.deepcopy(links['links'])
        result['context_action_ids'] = [row['action_id'] for row in result['links']]
    return result


def desired_frames(links):
    return set(ident for row in links['links'] for ids in row['frames'].values() for ident in ids)


def select_frames(frames, links, maximum):
    from .action_links import select_frames as select_windows, frame_id
    indices, report = select_windows(frames, links, maximum)
    selected = set(indices)
    if frames and len(selected) < min(maximum, len(frames)):
        for position in range(min(maximum, len(frames))):
            selected.add(round(position*(len(frames)-1)/max(1,min(maximum,len(frames))-1)))
            if len(selected) == min(maximum,len(frames)):
                break
        for position in range(len(frames)):
            if len(selected) == min(maximum,len(frames)):
                break
            selected.add(position)
    indices = sorted(selected)
    chosen = {frame_id(frames[index],index+1) for index in indices}
    report['selected_frame_ids'] = [frame_id(frames[index],index+1) for index in indices]
    report['unobserved_criterion_ids'] = [ident for ident in report['criterion_ids']
        if not any(frame in chosen for row in links['links'] if ident in row.get('criterion_ids', [])
                   for stage in row['frames'].values() for frame in stage)]
    report['clipped_windows'] = [dict(row,omitted_frame_ids=[ident for ident in row['omitted_frame_ids'] if ident not in chosen])
                                for row in report['clipped_windows']
                                if any(ident not in chosen for ident in row['omitted_frame_ids'])]
    report['selection_reason'] = 'All action stages before uniform full-route fill; recorded input alone does not prove a result.'
    return indices, report


def groups(protocol, links):
    dynamic = [row for row in protocol['criteria'] if row['mode'] != 'static']
    cap = policy(protocol)['frame_budget']
    result, current = [], []
    for row in dynamic:
        proposed = current + [row]
        ids = [item['id'] for item in proposed]
        direct = [link for link in links['links'] if set(link.get('criterion_ids',[])) & set(ids)]
        if current and (len(proposed) > protocol['judge_shard_size']
                        or len(desired_frames({'links':direct})) > cap):
            result.append(current)
            current = []
        current.append(row)
    if current:
        result.append(current)
    return result


def deliver(root, protocol, manifest):
    from . import endpoint_sparse, sparse_evidence
    if endpoint_sparse.enabled(protocol):
        return sparse_evidence.deliver(root, protocol, manifest)
    from PIL import Image, ImageDraw
    from .action_links import frame_id
    root = Path(root)
    if not enabled(protocol):
        raise ValueError('dynamic delivery requires its frozen evidence policy')
    frozen = policy(protocol)
    frames = load_lines(root / 'runtime/frame_index.jsonl')
    links = json.loads((root / 'runtime/action_frame_links.json').read_text())
    manifest['items'] = [row for row in manifest['items'] if row['type'] != 'frame']
    manifest.update(version=VERSION, evidence_frame_policy=frozen, delivery_sheets=[], evidence_sets={})
    frame_items = {}
    for number, specs in enumerate(groups(protocol, links), 1):
        name = f'evidence_{number:02d}'
        identifiers = [row['id'] for row in specs]
        selected_links = scoped_links(links, identifiers)
        indices, selection = select_frames(frames, selected_links, frozen['frame_budget'])
        selection['selection_reason'] = frozen['selection']
        subset = {'criterion_ids': identifiers, 'frame_selection': selection, 'delivery_sheets': [], 'frames': {}}
        for start in range(0, len(indices), 4):
            block = indices[start:start+4]
            dimensions = []
            for index in block:
                with Image.open(checked_path(root / 'runtime', frames[index]['path'])) as image:
                    dimensions.append(image.size)
            width = max(size[0] for size in dimensions)
            height = max(size[1] for size in dimensions)
            sheet = Image.new('RGB', (width*2, (height+26)*2), '#101010')
            draw = ImageDraw.Draw(sheet)
            relative = f'delivery/{name}/sheet_{start//4+1:03d}.png'
            for tile, index in enumerate(block):
                row = frames[index]
                ident = frame_id(row, index+1)
                path = checked_path(root / 'runtime', row['path'])
                left, top = tile%2*width, tile//2*(height+26)
                draw.text((left+6, top+5), f'{ident} | {row["t_ms"]} ms', fill='white')
                with Image.open(path) as image:
                    source_width, source_height = image.size
                    sheet.paste(image.convert('RGB'), (left, top+26))
                item = {'id': ident, 'path': str(path.relative_to(root)), 'type': 'frame', 'sha256': sha(path),
                        't_ms': row['t_ms'], 'frame_id': ident, 'probe': row.get('probe'),
                        'delivered_to_judge': True, 'delivery_sheet': relative, 'tile': tile,
                        'tile_rect': [left, top+26, source_width, source_height]}
                subset['frames'][ident] = item
                frame_items.setdefault(ident, item)
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            sheet.save(destination)
            page = {'path': relative, 'sha256': sha(destination)}
            subset['delivery_sheets'].append(page)
            manifest['delivery_sheets'].append(page)
        subset['delivered_frame_count'] = len(subset['frames'])
        subset['clipped_windows'] = selection['clipped_windows']
        subset.update(channel_delivery(root, selected_links))
        manifest['evidence_sets'][name] = subset
    manifest['items'].extend(frame_items.values())
    manifest.update(raw_frame_count=len(frames), delivered_frame_count=len(frame_items),
                    frame_selection={'version': VERSION, 'max_frames': frozen['frame_budget'],
                                     'selected_frame_ids': list(frame_items),
                                     'clipped_windows': [dict(row, evidence_set=name)
                                         for name, subset in manifest['evidence_sets'].items()
                                         for row in subset['clipped_windows']]})
    rows = [{**row, 'frame_id': frame_id(row, index+1), 'timestamp_ms': row['t_ms'],
             'source_path': 'runtime/'+row['path'], 'raw_path': 'runtime/'+row['path'],
             'delivered_path': frame_items.get(frame_id(row, index+1), {}).get('delivery_sheet'),
             'tile': frame_items.get(frame_id(row, index+1), {}).get('tile'), 'capture_status': 'captured',
             'delivery_status': 'DELIVERED' if frame_id(row, index+1) in frame_items else 'NOT_SELECTED_BY_FROZEN_SAMPLER'}
            for index, row in enumerate(frames)]
    index_path = root / 'delivery/frame_index.jsonl'
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(''.join(json.dumps(row, ensure_ascii=False)+'\n' for row in rows))
    manifest['frame_delivery_index'] = {'path': str(index_path.relative_to(root)), 'sha256': sha(index_path)}
    return manifest


def for_task(manifest, name):
    if not manifest.get('evidence_sets') and 'static_judge_partition' not in manifest:
        return copy.deepcopy(manifest)
    from .static_judge_shards import is_static
    if is_static(manifest, name):
        result=copy.deepcopy(manifest)
        result['items']=[row for row in result['items'] if row['type'] not in {'frame','reference','action','state','event'}]
        result['delivery_sheets']=[]
        result['frame_selection']={'scope':'Source-only judge; no runtime images or channels delivered.'}
        result['delivered_frame_count']=0
        return result
    subset = manifest['evidence_sets'][name]
    result = copy.deepcopy(manifest)
    result['items'] = [row for row in result['items'] if row['type'] != 'frame'] + list(subset['frames'].values())
    result['delivery_sheets'] = subset['delivery_sheets']
    result['frame_selection'] = subset['frame_selection']
    result['delivered_frame_count'] = subset['delivered_frame_count']
    result['current_evidence_set'] = name
    result['delivered_channel_lines'] = subset['delivered_channel_lines']
    result['channel_clipping'] = subset['channel_clipping']
    result['scoped_action_ids'] = subset['scoped_action_ids']
    for key in ('channel_transport', 'endpoint_frames', 'endpoint_contracts', 'event_wire_transport', 'event_original_row_policy'):
        if key in subset:
            result[key] = copy.deepcopy(subset[key])
    if subset.get('include_references') is False:
        result['items'] = [row for row in result['items'] if row['type'] != 'reference']
    return result


def channel_delivery(root, links):
    from .action_links import physical_rows
    selection, clipping = {}, []
    for ident, filename, field in [('ACTION','actions.jsonl','action_lines'),
                                   ('STATE','state_trace.jsonl','states'),
                                   ('EVENT','event_trace.jsonl','events')]:
        rows = physical_rows(Path(root)/'runtime'/filename)
        by_line = dict(rows)
        priority = list(dict.fromkeys(line for link in links['links'] for line in link[field]))
        if rows:
            priority += [rows[round(index*(len(rows)-1)/max(1,min(24,len(rows))-1))][0]
                         for index in range(min(24,len(rows)))]
        selected, used = [], 0
        for line in dict.fromkeys(priority):
            if line not in by_line:
                continue
            size = len(json.dumps(by_line[line],ensure_ascii=False).encode())
            if used+size <= 160000 and len(selected) < 512:
                selected.append(line)
                used += size
        selection[ident] = sorted(selected)
        for link in links['links']:
            missing = [line for line in link[field] if line not in selected]
            if missing:
                clipping.append({'channel':ident,'action_id':link['action_id'],
                    'criterion_ids':link.get('criterion_ids',[]),'missing_physical_lines':missing,
                    'reason':'Frozen per-channel 160000-byte/512-row transport limit or missing raw row.'})
    return {'delivered_channel_lines':selection,'channel_clipping':clipping,
            'scoped_action_ids':[row['action_id'] for row in links['links']]}


def state_samples(root, manifest):
    if 'delivered_channel_lines' not in manifest:
        return json.loads((Path(root)/'trace_summary.json').read_text())['state_samples']
    from .action_links import physical_rows
    allowed = set(manifest['delivered_channel_lines']['STATE'])
    return [dict(row,line=line) for line,row in physical_rows(Path(root)/'runtime/state_trace.jsonl') if line in allowed]


def tasks(protocol, manifest):
    from .static_judge_shards import tasks as static_tasks
    result = static_tasks(protocol, manifest)
    dynamic = [row for row in protocol['criteria'] if row['mode'] != 'static']
    if not enabled(protocol):
        size = protocol['judge_shard_size']
        return result + [(f'evidence_{index//size+1:02d}', dynamic[index:index+size], False)
                         for index in range(0, len(dynamic), size)]
    if manifest.get('evidence_frame_policy') != policy(protocol):
        raise ValueError('manifest differs from frozen frame policy')
    by_id = {row['id']: row for row in dynamic}
    observed = []
    for name, subset in manifest['evidence_sets'].items():
        identifiers = subset['criterion_ids']
        observed.extend(identifiers)
        result.append((name, [by_id[ident] for ident in identifiers], False))
    if len(observed) != len(set(observed)) or set(observed) != set(by_id):
        raise ValueError('each frozen runtime atom must be judged exactly once across evidence shards')
    return result


def validate(root, protocol, manifest):
    if manifest.get('judge_transport_partition'):
        from .unity_judge_transport_recovery import validate_partition
        original = validate_partition(root, protocol, manifest)
        return validate(root, protocol, original)
    from . import endpoint_sparse, sparse_evidence
    if endpoint_sparse.enabled(protocol):
        return sparse_evidence.validate(root, protocol, manifest)
    from .action_links import frame_id
    root = Path(root)
    frozen = policy(protocol)
    if not enabled(protocol) or manifest.get('evidence_frame_policy') != frozen:
        raise ValueError('frame policy mismatch')
    tasks(protocol, manifest)
    frames = load_lines(root / 'runtime/frame_index.jsonl')
    links = json.loads((root / 'runtime/action_frame_links.json').read_text())
    expected_groups = [[row['id'] for row in specs] for specs in groups(protocol, links)]
    if [subset['criterion_ids'] for subset in manifest['evidence_sets'].values()] != expected_groups:
        raise ValueError('evidence shard targets differ from deterministic window splitting')
    for name, subset in manifest['evidence_sets'].items():
        scoped = scoped_links(links, subset['criterion_ids'])
        _, selection = select_frames(frames, scoped, frozen['frame_budget'])
        selection['selection_reason'] = frozen['selection']
        if (subset['frame_selection'] != selection or subset['clipped_windows'] != selection['clipped_windows']
                or set(subset['frames']) != set(selection['selected_frame_ids'])
                or subset['delivered_frame_count'] != len(subset['frames'])
                or len(subset['frames']) > frozen['frame_budget']):
            raise ValueError('actual delivered windows/count differ from the frozen selection: ' + name)
        for page in subset['delivery_sheets']:
            if sha(checked_path(root, page['path'])) != page['sha256']:
                raise ValueError('evidence image changed after packaging')
        if any(subset[key] != value for key,value in channel_delivery(root, scoped).items()):
            raise ValueError('per-window raw channel delivery differs from its frozen selection')
        from PIL import Image
        pages = {row['path']:row for row in subset['delivery_sheets']}
        for relative in pages:
            with Image.open(checked_path(root, relative)) as sheet:
                for ident,item in subset['frames'].items():
                    if item['delivery_sheet'] != relative:
                        continue
                    raw = next((row for index,row in enumerate(frames,1)
                                if frame_id(row,index) == ident), None)
                    if raw is None or item['path'] != 'runtime/'+raw['path'] or sha(checked_path(root,item['path'])) != item['sha256']:
                        raise ValueError('shard frame source is not the indexed raw observation')
                    left,top,width,height = item['tile_rect']
                    cell_width,cell_height=sheet.width//2,sheet.height//2
                    tile=item['tile']
                    if type(tile) is not int or not 0 <= tile < 4 or [left,top] != [tile%2*cell_width,tile//2*cell_height+26] or item['t_ms'] != raw['t_ms']:
                        raise ValueError('shard tile/time mapping differs from native image layout')
                    with Image.open(checked_path(root,item['path'])) as original:
                        if original.size != (width,height) or sheet.crop((left,top,left+width,top+height)).convert('RGB').tobytes() != original.convert('RGB').tobytes():
                            raise ValueError('shard image does not contain the complete native raw frame')
        if any(item['delivery_sheet'] not in pages for item in subset['frames'].values()):
            raise ValueError('frame tile has no delivered image')
    union = set().union(*(set(subset['frames']) for subset in manifest['evidence_sets'].values()))
    if union != {row['id'] for row in manifest['items'] if row['type'] == 'frame'}:
        raise ValueError('frame manifest differs from the actual evidence set union')
    return True


def request_transport(protocol):
    return dict(policy(protocol)['transport'], version=REQUEST_TRANSPORT_VERSION, maximum_images=100)


def validate_request(root, name, protocol, manifest, images, prompt, *, recorded_transport=None):
    if not enabled(protocol):
        return None
    selected = for_task(manifest, name)
    from .static_judge_shards import is_static
    source_only = is_static(manifest, name)
    event_binding = selected.get('channel_transport', {}).get('event_wire_transport')
    if not source_only and event_binding is not None:
        from .event_wire import enabled as event_enabled, verify_section as verify_event_section, extended_rows as event_extended_rows
        if not event_enabled(selected):
            raise ValueError('EVENT wire delivery lacks explicit transport opt-in')
        verify_event_section(prompt, Path(root)/'runtime/event_trace.jsonl',
            selected['delivered_channel_lines']['EVENT'], event_binding, extended=event_extended_rows(selected))
    expected = [] if source_only else [Path(root)/row['path'] for row in selected['items'] if row['type'] == 'reference'] + [Path(root)/row['path'] for row in selected['delivery_sheets']]
    if [Path(path).resolve() for path in images] != [path.resolve() for path in expected]:
        raise ValueError('judge image arguments do not match this evidence shard')
    for row in ([row for row in selected['items'] if row['type'] == 'reference'] + selected['delivery_sheets']) if not source_only else []:
        if sha(checked_path(root,row['path'])) != row['sha256']:
            raise ValueError('actual judge image SHA differs from the frozen shard')
    legacy = recorded_transport == 'legacy'
    transport = policy(protocol)['transport'] if legacy else request_transport(protocol)
    if recorded_transport is not None and not legacy and recorded_transport != transport:
        raise ValueError('unknown or altered judge request transport policy')
    if len(images) > transport['maximum_images'] or len(prompt.encode()) > transport['maximum_prompt_bytes']:
        raise ValueError('measured judge request exceeds versioned transport limits; do not silently clip images or prompt')
    record = {'version': VERSION, 'evidence_set': name, 'policy': policy(protocol),
              'actual_frame_ids': [row['id'] for row in selected['items'] if row['type'] == 'frame'] if not source_only else [],
              'images': [{'path': str(Path(path).relative_to(root)), 'sha256': sha(path)} for path in images],
              'image_count': len(images), 'prompt_bytes': len(prompt.encode()),
              'delivered_channel_lines':selected.get('delivered_channel_lines',{}),
              'prompt_sha256': __import__('hashlib').sha256(prompt.encode()).hexdigest()}
    if not legacy:
        record['request_transport_policy'] = transport
    dump(Path(root)/'validation_history'/f'{name}.actual_delivery.json', record)
    return record


def audit_requests(root, protocol, manifest):
    from .codex import load_plan_json
    from .judge_invocation import response_for_judgment
    root = Path(root)
    for name,_,_ in tasks(protocol,manifest):
        folder = response_for_judgment(root,name).parent
        recorded = load_plan_json(folder/'actual_delivery.json')
        images = [root/row['path'] for row in recorded['images']]
        expected = validate_request(root,name,protocol,manifest,images,(folder/'prompt.txt').read_text(),
                                    recorded_transport=recorded.get('request_transport_policy', 'legacy'))
        if recorded != expected:
            raise ValueError('preserved actual model request differs from per-shard delivery: '+name)
        invocation = load_plan_json(folder/'invocation.json')
        command = invocation.get('command',[])
        submitted = [command[index+1] for index,value in enumerate(command[:-1]) if value == '--image']
        if invocation.get('exit_code') != 0 or [Path(path).resolve() for path in submitted] != [path.resolve() for path in images]:
            raise ValueError('actual model process did not receive the frozen images: '+name)
    return True
