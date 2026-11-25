"""Opt-in outcome evidence transport; original recording/manifest stays immutable.

All preregistered windows are delivered uniformly, independent of observed results.
This is additional native-pixel context, not a change to credits or source truth.
"""
from pathlib import Path
import copy
import json
from PIL import Image, ImageDraw
from .protocol import dump, sha, checked_path, load_lines
from .action_links import frame_id
from . import sparse_evidence

VERSION = 'mechanic-outcome-native-context.v1'
POLICY_FILE = 'mechanic_outcome_evidence_policy.json'


def source_rank(item):
    path = item.get('path', '').lower()
    parts = set(path.split('/'))
    code = item.get('type') == 'source' and Path(path).suffix in {
        '.gd', '.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx', '.html', '.cs'}
    auxiliary = bool(parts & {'dist', 'build', 'tools', 'tests', 'test', 'node_modules',
                             'vendor', 'thirdparty', 'framework', 'a3gameruntime'})
    # Nested packages can contain the author's game; do not classify every
    # packages/ directory as a framework.
    framework = any(x in path for x in ('gamefactory', 'a3game', '/engine/'))
    return (0 if code and not auxiliary and not framework else 1 if code else 2, path)


def freeze(root, contract_sha256):
    root = Path(root)
    path = root/POLICY_FILE
    value = dict(version=VERSION, revision='outcome_frame_v1',
        contract_sha256=contract_sha256, window_selection='all_predeclared_windows',
        source_order='authored_code_first_then_other_sources_then_documents',
        original_manifest_unchanged=True, scoring_semantics_unchanged=True)
    if path.exists():
        if json.loads(path.read_text()) != value:
            raise ValueError('Outcome evidence transport policy changed')
        return value
    if any((root/'model_calls').glob('mechanic_v3_*')):
        raise ValueError('Freeze transport before the first runtime judgment')
    dump(path, value)
    return value


def selected_ids(manifest, parent):
    subset = manifest['evidence_sets'][parent]
    ids = set(subset['frames'])
    for window in manifest['sparse_capture_audit']['windows'].values():
        ids.update(window['frame_ids'])
    return ids


def prepare(root, protocol, manifest, parent, *, revision, contract_sha256):
    root = Path(root)
    if revision != 'outcome_frame_v1':
        raise ValueError('Outcome evidence transport requires explicit outcome revision')
    policy = json.loads((root/POLICY_FILE).read_text())
    if (policy.get('version') != VERSION or policy.get('revision') != revision
            or policy.get('contract_sha256') != contract_sha256
            or policy.get('window_selection') != 'all_predeclared_windows'):
        raise ValueError('Unbound outcome evidence transport')
    sparse_evidence.validate(root, protocol, manifest)
    result = copy.deepcopy(manifest)
    subset = result['evidence_sets'][parent]
    wanted = selected_ids(manifest, parent)
    frames = load_lines(root/'runtime/frame_index.jsonl')
    indexed = {frame_id(row, index): row for index, row in enumerate(frames, 1)}
    if not wanted <= set(indexed):
        raise ValueError('Declared window refers to missing raw frame')
    identifiers = [frame_id(row, index) for index, row in enumerate(frames, 1)
                   if frame_id(row, index) in wanted]
    subset['frames'] = {}; subset['delivery_sheets'] = []
    directory = Path('delivery')/'mechanic_outcome_context_v1'/parent
    for start in range(0, len(identifiers), 4):
        block = identifiers[start:start+4]
        sizes = []
        for ident in block:
            with Image.open(checked_path(root/'runtime', indexed[ident]['path'])) as image:
                sizes.append(image.size)
        width = max(s[0] for s in sizes); height = max(s[1] for s in sizes)
        sheet = Image.new('RGB', (2*width, 2*(height+26)), '#101010')
        draw = ImageDraw.Draw(sheet)
        relative = directory/f'sheet_{start//4+1:03d}.png'
        for tile, ident in enumerate(block):
            row = indexed[ident]; path = checked_path(root/'runtime', row['path'])
            left, top = tile%2*width, tile//2*(height+26)
            draw.text((left+6, top+5), f'{ident} | {row["t_ms"]} ms', fill='white')
            with Image.open(path) as image:
                iw, ih = image.size; sheet.paste(image.convert('RGB'), (left, top+26))
            item = dict(id=ident, path=str(path.relative_to(root)), type='frame',
                sha256=sha(path), t_ms=row['t_ms'], frame_id=ident, delivered_to_judge=True,
                delivery_sheet=str(relative), tile=tile, tile_rect=[left,top+26,iw,ih])
            for key in ('session_id','client_role'):
                if key in row:item[key]=row[key]
            subset['frames'][ident] = item
        destination = root/relative; destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            with Image.open(destination) as old:
                if old.size != sheet.size or old.convert('RGB').tobytes() != sheet.tobytes():
                    raise ValueError('Preserved outcome image pixels changed')
        else:sheet.save(destination)
        subset['delivery_sheets'].append(dict(path=str(relative),sha256=sha(destination)))
    subset['delivered_frame_count'] = len(identifiers)
    subset['frame_selection'] = dict(version=VERSION, selected_frame_ids=identifiers,
        selection_reason='Original endpoint context plus every predeclared short window; no result-based selection',
        visual_windows=copy.deepcopy(manifest['sparse_capture_audit']['windows']), clipped_windows=[])
    subset['outcome_evidence_transport'] = dict(version=VERSION, policy_sha256=sha(root/POLICY_FILE))
    # Runtime channels/endpoint contracts remain exactly the original parent.
    result['items'] = sorted([i for i in result['items'] if i['type'] != 'frame'], key=source_rank)
    union = {i['id']:i for s in result['evidence_sets'].values() for i in s['frames'].values()}
    result['items'].extend(union.values())
    validate_pixels(root, subset, indexed, wanted)
    proof = root/'requests'/'outcome_context'/parent
    proof.mkdir(parents=True,exist_ok=True)
    dump(proof/'transport.json',dict(version=VERSION, policy_sha256=sha(root/POLICY_FILE),
        original_manifest_sha256=sha(root/'evidence_manifest.json'),
        original_endpoint_frame_ids=list(manifest['evidence_sets'][parent]['frames']),
        added_frame_ids=[i for i in identifiers if i not in manifest['evidence_sets'][parent]['frames']],
        all_predeclared_window_frame_ids=sorted(wanted-set(manifest['evidence_sets'][parent]['frames'])),
        raw_index_sha256=sha(root/'runtime/frame_index.jsonl'),
        sheets=subset['delivery_sheets'], native_pixels_verified=True,
        source_order=[i['id'] for i in result['items'] if i['type'] in {'source','document'}],
        original_channels_unchanged=True, credits_unchanged=True))
    return result


def validate_pixels(root, subset, indexed, wanted):
    if set(subset['frames']) != wanted:
        raise ValueError('Outcome window selection mismatch')
    pages = {p['path']:p for p in subset['delivery_sheets']}
    for ident, item in subset['frames'].items():
        row = indexed[ident]; raw = checked_path(root/'runtime',row['path'])
        if item['path'] != str(raw.relative_to(root)) or item['sha256'] != sha(raw) or item['t_ms'] != row['t_ms']:
            raise ValueError('Outcome raw frame binding changed')
        page = pages[item['delivery_sheet']]; path = checked_path(root,page['path'])
        if sha(path) != page['sha256']:raise ValueError('Outcome image SHA changed')
        with Image.open(path) as sheet, Image.open(raw) as original:
            left,top,width,height = item['tile_rect']; tile=item['tile']
            if (type(tile) is not int or tile not in range(4)
                    or [left,top] != [tile%2*(sheet.width//2),tile//2*(sheet.height//2)+26]
                    or original.size != (width,height)
                    or original.convert('RGB').tobytes() != sheet.crop((left,top,left+width,top+height)).convert('RGB').tobytes()):
                raise ValueError('Outcome sheet does not preserve complete native pixels')
