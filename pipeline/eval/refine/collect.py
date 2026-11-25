"""Read frozen JSONL collects; resolve stale project indexes without rewriting them."""
from __future__ import annotations
from collections import defaultdict
from pathlib import Path
import json
import re
from .common import jsonl, resolve, sha

FILES = {'initial': 'repair_initgame_collect.jsonl',
         'repair': 'repair_selected200_simple_v2_collect.jsonl',
         'simple': 'repair_import_simple_collect.json',
         'detailed': 'repair_import_collect.json'}


def project(root, row):
    if not row or not row.get('project_root'):
        return None
    base = resolve(root, row['project_root'])
    entry = resolve(root, row['launch_entry']) if row.get('launch_entry') else None
    engine = row.get('engine', '').lower()
    if engine in ('unity', 'unity3d', 'tuanjie', 'unity/tuanjie'):
        valid = (base / 'ProjectSettings/ProjectVersion.txt').is_file()
        engine = 'unity3d'
    elif engine in ('ue5', 'unreal'):
        valid = entry is not None and entry.suffix == '.uproject' and entry.is_file() and entry.parent == base
        engine = 'ue5'
    elif engine == 'godot':
        valid = (base / 'project.godot').is_file()
        entry = base / 'project.godot'
    elif engine in ('three_js', 'three.js', 'threejs'):
        engine = 'three_js'
        valid = entry is not None and entry.is_file() and entry.is_relative_to(base) and entry.suffix == '.html'
    else:
        return None
    if not valid:
        return None
    return {**row, 'project_root': str(base), 'engine': engine,
            'launch_entry': str(entry) if entry else None}


def assets(root, task, config):
    """Explicit map wins. Otherwise require one unambiguous payload, never best-of."""
    mapped = config.get('asset_map', {}).get(task['import_id'],
                config.get('asset_map', {}).get(task['task_id']))
    paths = [resolve(root, mapped)] if mapped else []
    if not mapped:
        if task.get('asset_path'):
            paths.append(resolve(root, task['asset_path']))
        for base in config.get('asset_roots', []):
            paths.append(resolve(root, base) / task['game_id'] / 'assets' / task['asset_kind'] / task['task_id'])
    geometry = task['asset_kind'] in ('3d_object', '3d_scene')
    suffixes = ({'.glb'} if geometry else
                {'.glb', '.fbx', '.bvh'} if task['asset_kind'] == 'motion' else
                {'.wav', '.mp3', '.ogg', '.flac'} if task['asset_kind'] == 'audio' else
                {'.mp4', '.webm', '.mov'})
    found = set()
    for path in paths:
        if path.is_file() and path.suffix.lower() in suffixes:
            found.add(path.resolve())
        elif path.is_dir():
            found.update(p.resolve() for p in path.rglob('*')
                         if p.is_file() and not p.is_symlink() and p.suffix.lower() in suffixes)
    status = 'READY' if len(found) == 1 else 'MISSING_PAYLOAD' if not found else 'AMBIGUOUS_PAYLOAD'
    selected = next(iter(found)) if len(found) == 1 else None
    return {'status': status, 'path': str(selected) if selected else None,
            'sha256': sha(selected) if selected else None,
            'candidates': sorted(map(str, found)), 'inspected': list(map(str, paths)),
            'selection_method': 'explicit_asset_map' if mapped else 'unique_payload_in_configured_locations'}


def load(config):
    root = Path(config['bench_root'])
    motion_sources = {}
    if config.get('motion_sources'):
        from .motion_delivery import load_sources
        motion_sources = load_sources(config)
    folder = resolve(root, config.get('collect_dir', 'test_data/outputs/game_refine'))
    rows = {}
    sources = {}
    files = dict(FILES)
    if config.get("include_vfx", False):
        files["vfx"] = "repair_vfx_collect.jsonl"
    for key, name in files.items():
        path = folder / name
        sources[key] = {'path': str(path), 'sha256': sha(path)}
        if not config.get('case_inputs') or key == 'detailed':
            rows[key] = [(r, {**sources[key], 'line': n}) for n, r in jsonl(path)]
    if 'frozen_collect_sources' in config and sources != config['frozen_collect_sources']:
        raise ValueError('Frozen matrix collect inputs changed; do not substitute task materials')
    case_bindings = {}
    if config.get('case_inputs'):
        from .case_inputs import load as load_cases
        case_rows, case_bindings = load_cases(config)
        rows.update(case_rows)
        # The detailed collect is a shared reference; only this game's details enter its task packet.
        rows['detailed'] = [(row, ref) for row, ref in rows['detailed']
                            if row['game_id'] in case_bindings]
        for gid, binding in case_bindings.items():
            for n, ref in enumerate(binding['sources']):
                sources[f'case:{gid}:{n}'] = ref
    initial = {r['game_id']: (r, ref) for r, ref in rows['initial']}
    if len(initial) != len(rows['initial']):
        raise ValueError('Duplicate initial game')
    detailed = {r['import_id']: (r, ref) for r, ref in rows['detailed']}
    if len(detailed) != len(rows['detailed']):
        raise ValueError('Duplicate detailed import ID')
    repairs, imports = defaultdict(list), defaultdict(list)
    ids = set()
    for row, ref in rows['repair']:
        ident = row['selection_id']
        if ident in ids or row['selection_kind'] not in ('mechanic', 'gamefeel'):
            raise ValueError(f'Duplicate/unsupported repair: {ident}')
        ids.add(ident)
        repairs[row['game_id']].append({**row, 'collect_source': ref})
    for row, ref in rows.get('vfx', []):
        ident = row['selection_id']
        if ident in ids or row.get('selection_kind') != 'vfx':
            raise ValueError(f'Duplicate/unsupported VFX repair: {ident}')
        ids.add(ident)
        # Keep the complete frozen row and original physical-line provenance.
        # The runtime task view requires strings; serialize structured acceptance
        # without dropping conditions or replacing them with agent-written goals.
        acceptance = row['acceptance_criteria']
        if not isinstance(acceptance, str):
            acceptance = json.dumps(acceptance, ensure_ascii=False)
        repairs[row['game_id']].append({**row, 'collect_source': ref,
            'test_action': row.get('test_action') or json.dumps({
                'trigger': row.get('trigger'), 'stop_condition': row.get('stop_condition'),
                'runtime_evidence_required': row.get('runtime_evidence_required')}, ensure_ascii=False),
            'pass_condition': acceptance})
    for row, ref in rows['simple']:
        ident = row['import_id']
        if ident in ids or ident not in detailed:
            raise ValueError(f'Duplicate/missing import: {ident}')
        ids.add(ident)
        detail, dref = detailed[ident]
        if row['game_id'] != detail['game_id'] or row['task_id'] != detail['task_id']:
            raise ValueError(f'Import pairing mismatch: {ident}')
        if row['asset_kind'] == 'motion' and config.get('motion_sources'):
            identity = (row['game_id'], row['task_id'], row['import_id'])
            if identity not in motion_sources:
                raise ValueError('Motion task absent from frozen acquisition: ' + ident)
            payload = motion_sources[identity]
        else:
            payload = assets(root, row, config)
        imports[row['game_id']].append({'simple': row, 'detail': detail,
                'collect_source': ref, 'detailed_source': dref, 'payload': payload})
    if {r['import_id'] for r, _ in rows['simple']} != set(detailed):
        raise ValueError('Simple and detailed import ID sets differ')
    games = []
    wanted = set(config.get('games', []))
    all_ids = set(initial) | set(repairs) | set(imports)
    if wanted - all_ids:
        raise ValueError(f'Unknown games: {wanted - all_ids}')
    for ident in all_ids | ids | {r['task_id'] for r, _ in rows['simple']}:
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', ident) or ident in ('.', '..'):
            raise ValueError('Unsafe collect identifier: ' + str(ident))
    for gid in sorted(all_ids):
        if wanted and gid not in wanted:
            continue
        first, iref = initial.get(gid, ({}, {}))
        candidates = []
        override = config.get('project_overrides', {}).get(gid)
        if override:
            selected = project(root, override)
            if selected is None:
                raise ValueError(f'Invalid explicit project override: {gid}')
            candidates = [(selected, {'kind': 'explicit_config_override'})]
        else:
            for raw, ref in [(first.get('selected_project'), iref)] + [
                    (v['simple'].get('selected_project'), v['collect_source']) for v in imports[gid]]:
                verified = project(root, raw)
                if verified:
                    candidates.append((verified, ref))
        unique = {p['project_root'] for p, _ in candidates}
        if len(unique) > 1:
            raise ValueError(f'Conflicting real project roots for {gid}; explicit override required: {unique}')
        selected = candidates[0][0] if candidates else None
        games.append({'game_id': gid, 'project': selected,
            'status': 'READY' if selected else 'BLOCKED_NO_PROJECT',
            'project_resolution': {'original_index_status': first.get('status'),
                'stale_initial_index': selected is not None and project(root, first.get('selected_project')) is None,
                'bindings': [ref for _, ref in candidates]},
            'repairs': repairs[gid], 'imports': imports[gid], 'initial': first,
            'requirement_binding': first.get('requirement_binding')})
    for game in games:
        if game['game_id'] in case_bindings:
            game['case_input'] = case_bindings[game['game_id']]
    return {'version': 'refine.collect.v1', 'sources': sources, 'games': games}
