"""Freeze eligible deliveries without score-based retry or eval-copy selection."""
from __future__ import annotations

import json
import os
import re
from collections import Counter
from pathlib import Path

from .protocol import dump, sha

METHODS = {'Opus': 'claude_ops5p5', 'Kimi': 'kimi-k3', 'Sol': 'gpt_sol6p1',
           'GLM': 'glm_5p3', 'Astra': 'gpt_astra6'}
SKIP = {'.git', '.godot', '__pycache__', 'eval', 'Library', 'Temp', 'Logs',
        'node_modules', 'Intermediate', 'Binaries', 'Saved', 'obj'}
# Explicitly authorized selected submissions, not permission for arbitrary retries.
APPROVED_DELIVERY_RUNS = {
    ('gpt_sol6p1', 'G002_mountain_ritual_duel'): 'retry4_20261016_122222',
    ('gpt_sol6p1', 'G003_gggame_courtyard_rps'): 'retry9_20261015_063356',
    ('gpt_sol6p1', 'G004_desert_observatory'): 'retry5_20261016_035155',
    ('gpt_sol6p1', 'G005_broken_realm_echo'): 'retry2_20261016_043108',
    ('gpt_sol6p1', 'G006_polar_radar_defense'): 'retry3_20261015_072521',
    ('gpt_sol6p1', 'G007_crystal_probe_run'): 'retry1_20261014_215727',
    ('gpt_sol6p1', 'G008_dock_beacon_cs'): 'retry15_20261015_154525',
    ('gpt_sol6p1', 'G009_blackout_stealth'): 'retry3_20261016_014652',
    ('gpt_sol6p1', 'G010_orbital_extraction'): 'retry1_20261016_005746',
}
APPROVED_DELIVERY_REASON = (
    'Explicit user authorization on 2026-10-23 to include these nine selected Sol deliveries; '
    'retry origin is preserved and does not establish build, launch, or scoring success.')
SELECTION = ('Enumerate every original generation run and explicitly user-approved delivered run; '
             'do not treat latest as the only delivery. '
             'Prefer a candidate whose engine matches the frozen requirement, then pipeline over '
             'mechanic, launch entry existence, shallow depth, generation name descending lexically, then marker path. Preserve '
             'the latest pointer and all candidates as provenance. Never select by build success '
             'or score; exclude unapproved retry/repair runs and all eval/workspace repair copies.')


def excluded_directory(name):
    """Prune evaluation/workspace/repair/retry trees at every depth."""
    return name.casefold() in {n.casefold() for n in SKIP} or bool(re.search(
        r'(?:^|[^a-z0-9])(?:eval(?:uation)?|workspaces?|repair(?:s|ed)?|retries|retry)[0-9]*(?:$|[^a-z0-9])',
        name, re.I))


def walk_files(base):
    for root, dirs, files in os.walk(base, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not excluded_directory(d) and not (Path(root)/d).is_symlink())
        for name in sorted(files):
            p = Path(root)/name
            if not p.is_symlink():
                yield p


def three_project_evidence(project, package):
    """Locate delivered Three sources even when their manifest is incomplete.

    This is engine identification only, not dependency or build validation.
    Some deliveries explicitly use a shared toolchain instead of declaring
    dependencies in their own package.json. Keep the authored files unchanged.
    """
    if 'three' in {**(package.get('dependencies') or {}), **(package.get('devDependencies') or {})}:
        return {'kind': 'declared_dependency', 'path': str(project/'package.json')}
    pattern = re.compile(r"(?:\bfrom\s*|\bimport\s*\(\s*|\brequire\s*\(\s*)['\"]three(?:/[^'\"]*)?['\"]")
    for source in delivery_files(project):
        if source.relative_to(project).parts[0] == 'dist' or source.suffix not in {'.js', '.mjs', '.ts', '.jsx', '.tsx', '.html'}:
            continue
        if source.stat().st_size > 1_000_000:
            continue
        text = source.read_text(errors='replace')
        match = pattern.search(text)
        if match:
            return {'kind': 'source_import', 'path': str(source.resolve()),
                    'line': text.count('\n', 0, match.start())+1, 'sha256': sha(source)}
    return None


def _legacy_markers(run):
    found = []
    for p in walk_files(run):
        if p.name == 'project.godot':
            engine, project = 'godot', p.parent
        elif p.suffix == '.uproject':
            engine, project = 'ue5', p.parent
        elif p.name == 'package.json' and (p.parent/'index.html').is_file():
            try:
                package = json.loads(p.read_text())
            except (OSError, ValueError):
                continue
            if not three_project_evidence(p.parent, package):
                continue
            engine, project = 'three_js', p.parent
        elif p.name == 'ProjectVersion.txt' and p.parent.name == 'ProjectSettings':
            engine, project = 'unity3d', p.parent.parent
        else:
            continue
        parts = p.relative_to(run).parts
        if not parts or parts[0] not in {'pipeline', 'mechanic'}:
            continue
        found.append({'engine':engine, 'project':str(project.resolve()), 'marker':str(p.resolve()),
                      'marker_sha256':sha(p), 'stage':parts[0], 'depth':len(parts),
                      **launch_entry(project, engine)})
    return sorted(found, key=lambda x:(x['stage'] != 'pipeline', x['depth'], x['marker']))


def delivery_files(base):
    """Target-engine delivery trees: only cache/generated directories are pruned.

    Retry/repair provenance is checked at the generation-run boundary. A ui/
    directory or authored nested folder called repair is not itself an eval copy.
    """
    caches=(SKIP-{'eval'}) | {'.cache','.vite','.import'}
    for folder,dirs,files in os.walk(base,followlinks=False):
        dirs[:]=sorted(d for d in dirs if d not in caches and not (Path(folder)/d).is_symlink())
        for name in sorted(files):
            p=Path(folder)/name
            if not p.is_symlink() and p.resolve().is_relative_to(Path(base).resolve()):yield p


def markers(run):
    # Retain the existing discovery and selection behavior for out-of-scope engines.
    found=[r for r in _legacy_markers(run) if r['engine'] not in {'godot','three_js'}]
    package_roots=set()
    files=list(delivery_files(run))
    for p in files:
        evidence=None
        if p.name=='project.godot':engine='godot'
        elif p.name=='package.json':
            try:package=json.loads(p.read_text())
            except (OSError,ValueError):continue
            evidence=three_project_evidence(p.parent,package)
            if not evidence:continue
            engine='three_js';package_roots.add(p.parent)
        else:continue
        parts=p.relative_to(run).parts
        found.append({'engine':engine,'project':str(p.parent.resolve()),'marker':str(p.resolve()),'marker_sha256':sha(p),'stage':parts[0] if len(parts)>1 else 'run_root','depth':len(parts),'identification_evidence':evidence or {'kind':'project.godot'},**launch_entry(p.parent,engine)})
    for p in files:
        if p.suffix.lower()!='.html' or any(root==p.parent or root in p.parents for root in package_roots):continue
        text=p.read_text(errors='replace') if p.stat().st_size<1_000_000 else ''
        if not re.search(r"three(?:\.module|\.min)?\.js|['\"]three['\"]\s*:",text):continue
        parts=p.relative_to(run).parts
        found.append({'engine':'three_js','project':str(p.parent.resolve()),'marker':str(p.resolve()),'marker_sha256':sha(p),'stage':parts[0] if len(parts)>1 else 'run_root','depth':len(parts),'identification_evidence':{'kind':'standalone_html_three_reference'},**launch_entry(p.parent,'three_js')})
    return sorted(found,key=lambda r:(r['stage']!='pipeline',r['depth'],r['marker']))


def choose_run(case):
    pointer = case/'latest'
    if pointer.is_symlink() or pointer.is_file():
        if pointer.is_symlink():
            run = pointer.resolve()
        else:
            raw = Path(pointer.read_text().strip())
            run = raw.resolve() if raw.is_absolute() else (case/raw).resolve()
        if not run.is_relative_to(case.resolve()) or not run.is_dir():
            raise ValueError(f'invalid latest pointer: {pointer}')
        return run, 'latest pointer'
    runs = sorted(p for p in case.iterdir() if p.is_dir() and not p.is_symlink()
                  and p.name not in SKIP and any((p/s).is_dir() for s in ('pipeline','mechanic')))
    return (runs[-1], 'latest run name (no latest pointer)') if runs else (None, 'no generation run')


def launch_entry(project, engine):
    """Read-only launch entry existence, not build/playability validation."""
    entry = None
    if engine == 'godot':
        from engine_adapters.godot.playtest.scene_entry import resolve_scene
        result=resolve_scene(project)
        entry=project/result['expected_path'] if result['resolved'] else None
    elif engine == 'three_js':
        from engine_adapters.three_js.playtest.launch import resolve_launch
        try:
            result=resolve_launch(project)
            entry=Path(result['entry']) if result['entry'] else None
        except (OSError,ValueError):entry=None
    elif engine == 'unity3d':
        config = project/'ProjectSettings/EditorBuildSettings.asset'
        text = config.read_text(errors='replace') if config.is_file() else ''
        scenes = re.findall(r'-\s*enabled:\s*1\s*\n\s*path:\s*([^\n]+)', text)
        entry = project/scenes[0].strip() if scenes else None
    elif engine == 'ue5':
        config = project/'Config/DefaultEngine.ini'
        text = config.read_text(errors='replace') if config.is_file() else ''
        match = re.search(r'^\s*GameDefaultMap\s*=\s*"?(/Game/[^"\s]+)', text, re.M)
        if match:
            entry = project/'Content'/(match.group(1)[6:].split('.')[0]+'.umap')
    exists = bool(entry and entry.is_file() and not entry.is_symlink()
                  and entry.resolve().is_relative_to(project.resolve()))
    return {'launch_entry': str(entry) if entry else None, 'launch_entry_exists': exists}


def generation_runs(case):
    """All non-symlink original and explicitly approved delivered runs.

    Accepts both gamefactory_* names (standard) and any other non-excluded
    non-symlink directory that looks like a timestamped generation run
    (manual_* or a directory containing pipeline/ or mechanic/). Retry names
    require an exact method/case/run approval; nested excluded trees stay excluded.
    """
    case = Path(case)
    if not case.is_dir():
        return []
    approved_run = APPROVED_DELIVERY_RUNS.get((case.parent.name, case.name))
    result = []
    for p in sorted(case.iterdir()):
        if p.is_symlink() or not p.is_dir():
            continue
        if excluded_directory(p.name) and p.name != approved_run:
            continue
        if p.name in {'latest', 'README.md', 'SELECTED_RUN.json'}:
            continue
        # Standard naming: gamefactory_*
        if p.name.startswith('gamefactory_'):
            result.append(p)
            continue
        # Non-standard naming: accept if it contains a pipeline/ or mechanic/
        # subdirectory (delivery tree exists) and is not a plain metadata file.
        if (p / 'pipeline').is_dir() or (p / 'mechanic').is_dir():
            result.append(p)
        elif any(row['engine'] in {'godot','three_js'} for row in markers(p)):
            result.append(p)
    return result


def latest_pointer(case):
    """Preserve file/symlink/dangling/escaped/non-run pointer states."""
    pointer = case/'latest'
    result = {'path': str(pointer.absolute()), 'kind': 'absent', 'raw_target': None,
              'resolved_target': None, 'target_exists': False, 'target_is_directory': False,
              'valid': False, 'error': None}
    if not pointer.exists() and not pointer.is_symlink():
        return result
    try:
        if pointer.is_symlink():
            result['kind'] = 'symlink'
            raw = os.readlink(pointer)
        elif pointer.is_file():
            result['kind'] = 'file'
            raw = pointer.read_text().strip()
        else:
            result.update(kind='directory' if pointer.is_dir() else 'other', error='not a pointer file or symlink')
            return result
        result['raw_target'] = raw
        if not raw:
            result['error'] = 'empty latest pointer'
            return result
        target = Path(raw)
        target = (target if target.is_absolute() else case/target).resolve()
        result.update(resolved_target=str(target), target_exists=target.exists(),
                      target_is_directory=target.is_dir())
        if not target.is_relative_to(case.resolve()):
            result['error'] = 'latest target escapes case directory'
        elif not target.is_dir():
            result['error'] = 'latest target is missing or not a directory'
        elif target not in [p.resolve() for p in generation_runs(case)]:
            result['error'] = 'latest target is not an eligible generation run'
        else:
            result['valid'] = True
    except (OSError, RuntimeError, ValueError) as exc:
        result['error'] = str(exc)
    return result


def all_markers(case):
    """Enumerate all eligible markers without changing any delivered project."""
    return [{**candidate, 'generation_run': str(run.resolve())}
            for run in generation_runs(case) for candidate in markers(run)]


def candidate_priority(row, expected_engine=None):
    return (bool(expected_engine and row['engine'] != expected_engine),
            row['stage'] != 'pipeline', not row['launch_entry_exists'], row['depth'])


def choose_project(case, expected_engine=None):
    """Deterministic all-run selection; latest is provenance, never a filter."""
    candidates = all_markers(case)
    if not candidates:
        return None, candidates, 'no project marker in any eligible generation run'
    # Stable sorts express descending generation name without reversing marker ties.
    ranked = sorted(candidates, key=lambda row: row['marker'])
    ranked.sort(key=lambda row: Path(row['generation_run']).name, reverse=True)
    ranked.sort(key=lambda row: candidate_priority(row, expected_engine))
    return ranked[0], candidates, SELECTION


def delivery_selection(case, expected_engine=None):
    case = Path(case)
    selected, candidates, reason = choose_project(case, expected_engine)
    pointer = latest_pointer(case)
    runs = generation_runs(case)
    approved_run = APPROVED_DELIVERY_RUNS.get((case.parent.name, case.name))
    approved = [str(run.resolve()) for run in runs if run.name == approved_run]
    diagnostics = []
    if pointer['error']:
        diagnostics.append('BAD_LATEST_POINTER')
    tied = [row for row in candidates if selected and
            candidate_priority(row, expected_engine) == candidate_priority(selected, expected_engine)]
    if len(tied) > 1:
        diagnostics.append('AMBIGUOUS_CANDIDATES')
    if not selected and case.is_dir():
        diagnostics.append('NO_PROJECT_MARKER')
    return {'selected_candidate': selected, 'all_candidates': candidates,
            'candidates': candidates, 'all_generation_runs': [str(p.resolve()) for p in runs],
            'latest_pointer': pointer, 'selection_reason': reason,
            'selection_provenance': {'rule': SELECTION, 'latest_used_for_selection': False,
                                     'user_approved_delivery_runs': approved,
                                     'approval_reason': APPROVED_DELIVERY_REASON if approved else None,
                                     'diagnostics': diagnostics, 'tied_candidates': [r['marker'] for r in tied],
                                     'selected_priority': list(candidate_priority(selected, expected_engine)) if selected else None}}


def requirement_meta(path):
    text = path.read_text()
    def field(key, default=''):
        m = re.search(r'^'+key+r':\s*([^\n]+)', text[:5000], re.M)
        return m.group(1).strip().strip('"\'') if m else default
    return {'expected_engine':field('engine'), 'tier':field('tier'),
            'required_real_clients':int(field('required_real_clients','1'))}


def frozen_for(framework, case_id):
    candidates = []
    for p in (framework/'eval/rubric_design/contract_history'/case_id).glob('*/rubric.json'):
        d = json.loads(p.read_text())
        if d.get('status') == 'frozen' and d.get('game_id') == case_id:
            candidates.append(p)
    if len(candidates) != 1:
        raise ValueError(f'{case_id}: expected one frozen final contract, got {len(candidates)}')
    return candidates[0]


def build_inventory(workspace, framework, count=10, *, case_ids=None, methods=None):
    samples = workspace/'test_data/test_samples'
    available = sorted(p for p in samples.glob('G*') if p.is_dir())
    cases = ([p for p in available if p.name.split('_')[0] in case_ids or p.name in case_ids]
             if case_ids is not None else available[:count])
    if case_ids is not None and len(cases) != len(case_ids):
        raise ValueError('Explicit case selection did not resolve exactly once per case')
    selected_methods = {m: f for m, f in METHODS.items() if methods is None or m in methods}
    if methods is not None and set(selected_methods) != set(methods):
        raise ValueError('Unknown selected model')
    result = []
    for method, folder in selected_methods.items():
        for case in cases:
            requirement = case/'general_requirement.txt'
            meta = requirement_meta(requirement)
            frozen = frozen_for(framework, case.name)
            delivery = workspace/'test_data/outputs/initial_game_gen'/folder/case.name
            selection = delivery_selection(delivery, meta['expected_engine'])
            selected = selection['selected_candidate']
            run = Path(selected['generation_run']) if selected else None
            result.append({'id':method+'__'+case.name, 'method':method, 'method_directory':folder,
                'case_id':case.name, **meta, 'requirement':str(requirement.resolve()),
                'requirement_sha256':sha(requirement), 'case_directory':str(case.resolve()),
                'frozen_rubric':str(frozen.resolve()), 'frozen_sha256':sha(frozen),
                'generation_run':str(run) if run else None, **selection,
                'project':selected['project'] if selected else None,
                'actual_engine':selected['engine'] if selected else None,
                'project_marker':selected['marker'] if selected else None,
                'marker_sha256':selected['marker_sha256'] if selected else None,
                'delivery_stage':selected['stage'] if selected else None,
                'engine_mismatch':bool(selected and selected['engine'] != meta['expected_engine']),
                'status':('PENDING' if selected else 'DELIVERY_REVIEW_REQUIRED') if delivery.is_dir()
                         else ('DELIVERY_REVIEW_REQUIRED' if delivery.exists() or delivery.is_symlink()
                               else 'BLOCKED_MISSING_DELIVERY'),
                'score':None})
    return {'version':'whitebox-paired-inventory.v1', 'selection_rule':SELECTION,
            'cases':[c.name for c in cases], 'methods':selected_methods, 'entries':result,
            'scope':'first10' if case_ids is None and count==10 else 'supplemental',
            'counts':dict(Counter(r['actual_engine'] or 'NO_PROJECT_MARKER' for r in result)),
            'warning':'Missing marker is not automatically a zero. Inventory is not a build test.'}


def write_inventory(root, inventory):
    dump(root/'inventory.json',inventory)
    lines=['# 白膜评测：冻结交付清单','',inventory['selection_rule'],'',
        '**清单不是成绩。没有引擎运行证据的行不会填假分；交付缺失与评测器不支持分开。**','',
        '| Method | Case | 需求引擎 | 交付引擎 | 阶段 | 状态 |','|---|---|---|---|---|---|']
    for r in inventory['entries']:
        state='ENGINE_MISMATCH' if r['engine_mismatch'] else r['status']
        lines.append(f"| {r['method']} | {r['case_id']} | {r['expected_engine']} | {r['actual_engine'] or '未找到项目标记'} | {r['delivery_stage'] or '—'} | {state} |")
    (root/'inventory.md').write_text('\n'.join(lines)+'\n')
