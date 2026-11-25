"""Immutable native evidence delivery and physical action/endpoint provenance gates."""
from __future__ import annotations
from pathlib import Path
import shutil
from .common import dump, read, sha, inside, jsonl
from .scoring import reference
from ..stage1.action_links import build_links, timestamp
from ..stage1.sparse_evidence import audit_capture


def package(folder, schedule):
    folder = Path(folder)
    capture = folder / 'background_record'
    take = capture / 'take'
    audit = audit_capture(take, schedule)
    links = build_links(take)
    if links != read(take / 'action_frame_links.json'):
        raise ValueError('Recorded physical action links changed')
    admitted = read(folder / 'native_admission.json') if (folder / 'native_admission.json').exists() else {}
    log = (take / 'engine.log' if admitted.get('native_acceptance') else
           capture / 'project/Library/GameFactory3A/Editor.log')
    if not log.is_file():
        raise ValueError('Actual engine log is missing')
    log_target = folder / 'evidence/engine.log'
    log_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(log, log_target)
    paths = [p for p in take.rglob('*') if p.is_file()] + [log_target,
            capture / 'verification.json', capture / 'runner_exit.json']
    manifest = {'version': 'refine.native-evidence.v1', 'audit': audit,
                'files': {str(p.relative_to(folder)): sha(p) for p in paths},
                'action_links': links, 'log': 'evidence/engine.log'}
    dump(folder / 'evidence/manifest.json', manifest)
    return manifest


def verify_manifest(folder, manifest):
    for relative, digest in manifest['files'].items():
        if sha(inside(folder, relative)) != digest:
            raise ValueError('Native evidence mutated: ' + relative)


def delivery(folder, tasks, endpoints, manifest, references):
    """Every supplied image is named/hash-bound; no resizing or synthetic frames."""
    folder = Path(folder)
    verify_manifest(folder, manifest)
    take = folder / 'background_record/take'
    ids = {t['task_id'] for t in tasks}
    frame_rows = jsonl(take / 'frame_index.jsonl')
    selected = []
    for number, row in frame_rows:
        relevant = [c for c in row.get('capture_ids', [])
                    if c.removeprefix('endpoint/').removeprefix('window/') in ids]
        if relevant:
            path = inside(take, row['path'])
            selected.append({'path': str(path), 'sha256': sha(path), 'physical_frame_line': number,
                             'capture_ids': relevant, 't_ms': row['t_ms'], 'origin': 'actual_engine'})
    for task in tasks:
        for view in references.get(task['task_id'], {}).get('views', []):
            if sha(view['path']) != view['sha256']:
                raise ValueError('Original GLB render changed')
            selected.append({**view, 'origin': 'original_glb_threejs', 'task_id': task['task_id']})
    if len(selected) > 100:
        raise ValueError('Judge delivery exceeds 100 actual images; split shard, never drop endpoints silently')
    for index, row in enumerate(selected, 1):
        row['image_number'] = index
    links = [r for r in manifest['action_links']['links'] if ids.intersection(r.get('criterion_ids', []))]
    channels = {}
    for name, key in [('actions.jsonl', 'action_lines'), ('state_trace.jsonl', 'states'),
                      ('event_trace.jsonl', 'events')]:
        path = take / name
        physical = dict(jsonl(path)) if path.exists() else {}
        required = {n for link in links for n in link.get(key, [])}
        channels[name] = {'path': str(path.relative_to(folder)),
            'sha256': sha(path) if path.exists() else None,
            'rows': [{'line': n, 'row': physical[n]} for n in sorted(required) if n in physical]}
    log_path = folder / manifest['log']
    lines = log_path.read_text(errors='replace').splitlines()
    # Full immutable log remains readable; send all detected errors plus initial/final context.
    from ..stage1.endpoint_channels import error_lines
    selected_lines, heads = error_lines(lines, 1, len(lines)) if lines else ([], [])
    delivered = sorted(set(selected_lines) | set(range(1, min(20, len(lines)) + 1))
                       | set(range(max(1, len(lines)-19), len(lines)+1)))
    log = {'path': manifest['log'], 'sha256': sha(log_path), 'total_physical_lines': len(lines),
           'error_detection_lines': heads, 'rows': [{'line': n, 'text': lines[n-1]} for n in delivered],
           'full_log_available': True}
    return {'tasks': tasks, 'endpoints': [e for e in endpoints if e['task_id'] in ids],
            'images': selected, 'links': links, 'channels': channels, 'engine_log': log,
            'capture_audit': manifest['audit'],
            'note': 'Time associations are not gameplay causality. Unknown or absent channels are not proof.'}


def proof(folder, row, endpoint, manifest, reference_render, delivered_images):
    folder = Path(folder)
    take = folder / 'background_record/take'
    ident = row['task_id']
    link = next((r for r in manifest['action_links']['links']
                 if r['action_id'] == endpoint.get('last_action_id') and ident in r.get('criterion_ids', [])), {})
    raw_actions = dict(jsonl(take / 'actions.jsonl'))
    physical = [raw_actions[n] for n in link.get('action_lines', []) if n in raw_actions]
    # No unobserved/planned-time inference may stand in for delivered input.
    delivered = bool(link.get('timing_source') == 'recorded_session_time' and physical
                     and all(r.get('sent') is True for r in physical)
                     and all(r.get('action_id') == link.get('action_id') for r in physical))
    allowed = {f'background_record/take/{name}': set(link.get(key, [])) for name, key in
               [('state_trace.jsonl', 'states'), ('event_trace.jsonl', 'events')]}
    refs = row['state_event_refs']
    valid_refs = bool(refs) and all(reference(folder, r) and r['path'] in allowed
                                    and r['line'] in allowed[r['path']] for r in refs)
    # State-only proof needs distinct physical observations; a sole generic heartbeat is insufficient.
    changed = any(r['path'].endswith('event_trace.jsonl') for r in refs) or len({
        (r['path'], r['line']) for r in refs}) >= 2
    logs = row['log_refs']
    log_ok = bool(logs) and all(reference(folder, r) and r['path'] == manifest['log'] for r in logs)
    frame_bound = False
    for _, frame in jsonl(take / 'frame_index.jsonl'):
        if 'endpoint/' + ident in frame.get('capture_ids', []):
            frame_bound = bool(delivered and endpoint.get('executable')
                and frame.get('sample_at_ms') == endpoint.get('at_ms')
                and timestamp(frame) is not None and link.get('action_end_t_ms') is not None
                and timestamp(frame) >= link['action_end_t_ms'] + endpoint['stable_after_ms'])
    cited = [r for r in delivered_images['images'] if r['image_number'] in row['image_numbers']]
    endpoint_cited = any(r.get('origin') == 'actual_engine' and 'endpoint/' + ident in r.get('capture_ids', [])
                         for r in cited)
    reference_cited = any(r.get('origin') == 'original_glb_threejs' and r.get('task_id') == ident for r in cited)
    window = manifest['audit']['windows'].get('window/' + ident, {})
    return {'action_delivered': delivered, 'state_event_refs_valid': bool(valid_refs and changed),
            'log_refs_valid': log_ok, 'endpoint_bound': frame_bound and endpoint_cited,
            'window_complete': window.get('complete') is True and window.get('continuous') is True,
            'original_render_available': bool(reference_cited and reference_render and reference_render.get('views'))}
