"""Freeze all original S deliveries for an independent outcome-frame reassessment.

The legacy paired and uploader selections remain immutable. This scope enumerates
all engines before eligibility checks and binds original bytes, Git upload facts,
shared contracts and historical record candidates before any runtime judgment.
"""
from __future__ import annotations
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from . import batch, inventory as deliveries, mechanic_v3_revision as revisions
from .mechanic_v3_runner import read, stamp, exclusive_json, disk
from .protocol import sha, dump

VERSION = 'mechanic-v3-all-s-original-scope.v1'
FIELDS = ('id', 'method', 'case_id', 'tier', 'actual_engine', 'project',
          'requirement_sha256', 'frozen_sha256', 'marker_sha256')


def git(repo, *args):
    result = subprocess.run(['git', '-C', str(repo), *args], capture_output=True, check=True)
    return result.stdout


def upload_provenance(repo, entry, ref, linkage):
    """Tie the chosen project, rather than just its case name, to Git objects."""
    base = repo/'test_data/outputs/initial_game_gen'/entry['method_directory']/entry['case_id']
    relative = base.relative_to(repo).as_posix()
    log = git(repo, 'log', '--reverse', '--format=%H%x09%an%x09%ae%x09%s', ref, '--', relative).decode().splitlines()
    proof = dict(repository=git(repo, 'remote', 'get-url', 'origin').decode().strip(),
                 ref=ref, ref_commit=git(repo, 'rev-parse', ref).decode().strip(),
                 case_path=relative, history=log, local_project=entry.get('project'),
                 uploader_linkage=linkage, verified=False)
    if not log:
        return dict(proof, reason='No upload history for original case subtree')
    first = log[0].split('\t', 3)
    proof.update(first_upload_commit=first[0], first_upload_author=first[1], first_upload_email=first[2])
    if first[1] != linkage['git_author']:
        return dict(proof, reason='First uploader is outside the authorized zengbohan identity')
    if not entry.get('project'):
        return dict(proof, reason='No selected original project to match to uploaded bytes')
    project = Path(entry['project']); project_path = project.relative_to(repo).as_posix()
    files = git(repo, 'ls-tree', '-r', '-z', ref, '--', project_path).split(b'\0')
    matches, missing, different = [], [], []
    for item in files:
        if not item:
            continue
        meta, name = item.split(b'\t', 1); mode, kind, blob = meta.decode().split()
        if kind != 'blob':
            continue
        path = repo/os.fsdecode(name)
        if not path.is_file():
            missing.append(str(path)); continue
        content = path.read_bytes()
        digest = hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest()
        row = dict(path=str(path), git_blob=blob, local_git_blob=digest, sha256=sha(path))
        (matches if digest == blob else different).append(row)
    proof.update(project_path=project_path, matched_files=matches, missing_files=missing, changed_files=different)
    marker = str(Path(entry['project_marker']))
    if not matches or marker not in {x['path'] for x in matches} or missing or different:
        return dict(proof, reason='Selected original does not exactly match uploaded tracked project bytes')
    # Recheck who introduced this actual project, as case subtrees may contain
    # later deliveries by a different author.
    project_log = git(repo, 'log', '--reverse', '--format=%H%x09%an%x09%ae%x09%s', ref, '--', project_path).decode().splitlines()
    proof['project_history'] = project_log
    if not project_log or project_log[0].split('\t')[1] != linkage['git_author']:
        return dict(proof, reason='Selected project uploader differs from case uploader')
    proof.update(verified=True, reason='Git uploader and exact original project bytes verified')
    return proof


def discover_records(roots):
    """Index data only; never import or execute historical workspace tools."""
    result = {}
    prune = {'input', 'runtime', 'model_calls', 'delivery', 'node_modules', '.git',
             'Library', '.godot', 'frames', 'engineering', 'plan_archive', 'reevaluations'}
    for base in roots:
        for folder, dirs, files in os.walk(base, followlinks=False):
            dirs[:] = sorted(d for d in dirs if d not in prune)
            if 'input_manifest.json' not in files or 'evidence_manifest.json' not in files:
                continue
            root = Path(folder)
            if not (root/'runtime/frame_index.jsonl').is_file():
                continue
            try:
                entry = read(root/'input_manifest.json')['entry']
            except (KeyError, ValueError, OSError):
                continue
            result.setdefault(entry['id'], []).append((root, entry))
    return result


def same_original(left, right):
    return all(left.get(k) == right.get(k) for k in FIELDS)


def load(workspace):
    workspace = Path(workspace).resolve()
    pointer = read(workspace/'full_s_scope.json')
    scope_path = workspace/'scopes/all_s_original/scope.json'
    if pointer.get('version') != VERSION or pointer.get('scope_sha256') != sha(scope_path):
        raise ValueError('Full S scope pointer or SHA changed')
    value = read(scope_path)
    if value.get('version') != VERSION or value.get('revision') != 'outcome_frame_v1':
        raise ValueError('Unknown full S scope protocol')
    for name, digest in value['bindings'].items():
        if sha(Path(name)) != digest:
            raise ValueError('Full S frozen source changed: '+name)
    if sha(workspace/'inventory.json') != value['inventory_sha256']:
        raise ValueError('Full S frozen inventory changed')
    inv = read(workspace/'inventory.json')
    for row in inv['entries']:
        if row['entry']['tier'] != 'S' or row['entry']['method'] not in set(value.get('authorized_models', ['Astra', 'Opus', 'Sol'])):
            raise ValueError('Unexpected model or non-S identity in full scope')
        if row['entry']['method'] == 'Opus' and row['in_scope'] and not row['upload_provenance']['verified']:
            raise ValueError('Unverified Opus uploader cannot enter reassessment')
    inv['active_selection'] = value['selected_identities']
    inv['full_scope_binding'] = dict(path=str(scope_path), sha256=sha(scope_path))
    return inv


def freeze(workspace, source_workspace, *, git_ref='origin/main', methods=None, engines=None, parent_workspace=None):
    workspace, source_workspace = Path(workspace).resolve(), Path(source_workspace).resolve()
    methods = list(methods or ['Astra', 'Opus', 'Sol'])
    if len(set(methods)) != len(methods) or set(methods)-{'Astra','Opus','Sol','GLM'}:
        raise ValueError('Unauthorized/duplicate source-scope model')
    if engines is not None and (not engines or set(engines)-{'godot','three_js'}):
        raise ValueError('Explicit supplement supports Godot/Three.js only')
    if (workspace/'full_s_scope.json').exists():
        bind_observation_conditions(workspace)
        return load(workspace)
    if workspace.exists() and any(workspace.iterdir()):
        raise ValueError('Preserve partial batch; inspect its specific failure before recovery')
    workspace.mkdir(parents=True, exist_ok=True)
    disk(workspace, 'freeze_all_s', 128*1024**2)
    framework = Path(__file__).resolve().parents[3]; repo = framework.parent
    cases = [p.name for p in sorted((repo/'test_data/test_samples').glob('G*'))
             if p.is_dir() and deliveries.requirement_meta(p/'general_requirement.txt')['tier'] == 'S']
    raw = deliveries.build_inventory(repo, framework, case_ids=cases, methods=methods)
    original = read(source_workspace/'inventory.json')
    fixed = {r['entry']['id']: r for r in original['entries']}
    # Existing diagnostic identities are frozen even if today's discovery order differs.
    for path in sorted((source_workspace/'scopes').glob('*/scope.json')):
        data = read(path)
        for row in data.get('entries', []) + data.get('supplemental_entries', []):
            if row['entry'].get('method') in {'Astra', 'Opus', 'Sol'}:
                ident = row['entry']['id']
                if ident in fixed and not same_original(fixed[ident]['entry'], row['entry']):
                    raise ValueError('Existing frozen original identities disagree: '+ident)
                fixed[ident] = row
    parent_inventory = load(Path(parent_workspace).resolve()) if parent_workspace else None
    if parent_inventory:
        for row in parent_inventory['entries']:
            fixed[row['entry']['id']] = row
    audit_path = source_workspace/'engineering/outcome_frame_v1/github_opus_G020_G060_uploader_audit_20261102.json'
    audit = read(audit_path); linkage = audit['github_login_linkage']
    if linkage['git_author'] != 'bohanzeng' or not linkage['login'].startswith('zengbohan'):
        raise ValueError('Unrecognized uploader identity linkage')
    for commit in linkage['merge_commits']:
        text = git(repo, 'show', '-s', '--format=%s', commit).decode()
        if linkage['login']+'/' not in text:
            raise ValueError('Git merge does not prove uploader login linkage')
    records = discover_records([repo/'test_data/outputs/eval/playtest', source_workspace] + ([Path(parent_workspace)] if parent_workspace else []))
    default_batch = Path(next(r['source_batch'] for r in original['entries'] if r['entry']['method'] == 'Opus'))
    bindings = {str(audit_path): sha(audit_path), str(source_workspace/'inventory.json'):sha(source_workspace/'inventory.json')}
    rows = []; changes = []
    for found in raw['entries']:
        previous = fixed.get(found['id']); entry = copy.deepcopy(previous['entry'] if previous else found)
        if previous and not same_original(entry, found):
            changes.append(dict(identity=entry['id'], frozen=entry, newly_discovered=found,
                                action='Preserve existing original identity; do not reselect'))
        hashes = batch.hashes(Path(entry['project'])) if entry.get('project') else {}
        for name, digest in hashes.items():
            bindings[str(Path(entry['project'])/name)] = digest
        for key in ('requirement', 'frozen_rubric'):
            bindings[entry[key]] = sha(Path(entry[key]))
        upload = upload_provenance(repo, entry, git_ref, linkage) if entry['method'] == 'Opus' else None
        selected = (entry['method'] != 'Opus' or upload['verified']) and (engines is None or entry.get('actual_engine') in engines)
        candidates = [str(root) for root, old in records.get(entry['id'], []) if same_original(entry, old)]
        # Preference is a source rule, never a score rule. The current task's
        # accepted native take precedes older batches; remaining paths sort.
        candidates.sort(key=lambda p: (not Path(p).is_relative_to(source_workspace), p))
        row = dict(entry=entry, source_batch=previous['source_batch'] if previous else str(default_batch),
                   in_scope=selected, historical_attempts=copy.deepcopy(previous.get('historical_attempts', [])) if previous else [],
                   record_candidates=candidates, preferred_record=None, source_hashes=hashes,
                   initial_stage='NEEDS_RECORD_QUALIFICATION' if candidates else 'NEEDS_ENTRY_PLAN_RECORD',
                   upload_provenance=upload, exclusion_reason=None if selected else (upload['reason'] if upload and not upload['verified'] else 'Actual original engine outside authorized Godot/Three.js scope'))
        if not entry.get('project'):
            row['initial_stage'] = 'BLOCKED_MISSING_DELIVERY'
        if entry.get('actual_engine') not in {'godot','three_js'} and entry.get('project'):
            row['initial_stage'] = 'NEEDS_ENGINE_NATIVE_ADAPTER_ACCEPTANCE'
        rows.append(row)
    exclusive_json(workspace/'inventory.json', dict(version=VERSION, created=stamp(), cases=cases,
        selection=deliveries.SELECTION, entries=rows, discovery_differences=changes,
        all_engines_enumerated_before_eligibility=True, independent_reassessment=True))
    shutil.copy2(source_workspace/'assessment_revision.json', workspace/'assessment_revision.json')
    # Contract goals are reused, verdicts are not. Original model calls stay at
    # their immutable audit location and are referenced by SHA.
    for case in cases:
        source = revisions.contract_dir(source_workspace, case)
        dest = revisions.contract_dir(workspace, case); dest.mkdir(parents=True)
        for name in ('contract.json', 'frozen.json', 'source_binding.json'):
            shutil.copy2(source/name, dest/name); bindings[str(source/name)] = sha(source/name)
            bindings[str(dest/name)] = sha(dest/name)
        frozen = read(dest/'frozen.json')
        if sha(dest/'contract.json') != frozen['contract_sha256']:
            raise ValueError('Original outcome contract changed')
        for name, digest in read(dest/'source_binding.json')['bindings'].items():
            if sha(Path(name)) != digest:
                raise ValueError('Original contract source changed: '+name)
        dump(dest/'contract_origin.json', dict(path=str(source), contract_sha256=sha(source/'contract.json'),
            same_visible_goals_for_all_models=True, old_verdict_reused=False,
            notice='按既有结果导向契约重新评价历史实录；新批次产生新判词'))
    from .mechanic_v3_native import configuration
    configuration(workspace, default_batch)
    scope = dict(version=VERSION, revision='outcome_frame_v1', created=stamp(),
        inventory_sha256=sha(workspace/'inventory.json'), bindings=bindings,
        selected_identities=[r['entry']['id'] for r in rows if r['in_scope']],
        all_discovered_identities=[r['entry']['id'] for r in rows],
        source_workspace=str(source_workspace), old_results_preserved=True,
        authorized_columns=['Mechanic'], model='gpt-6.1-sol',
        authorized_models=methods, authorized_engines=engines,
        parent_scope_binding=parent_inventory['full_scope_binding'] if parent_inventory else None)
    path=workspace/'scopes/all_s_original/scope.json'; exclusive_json(path, scope)
    exclusive_json(workspace/'full_s_scope.json',dict(version=VERSION, scope_sha256=sha(path)))
    bind_observation_conditions(workspace)
    return load(workspace)


def bind_observation_conditions(workspace):
    """Bind inherited native observation data before any new plan, without rewriting scope.

    Active outcome-workspace observers take precedence, matching prepared_entry.
    Older source batches are a deterministic fallback; differences remain auditable.
    These sampler rubrics do not change the separate outcome scoring contract.
    """
    from . import endpoint_sparse
    workspace = Path(workspace).resolve()
    inventory = load(workspace)
    receipt_path = workspace/'engineering/shared_observation_binding.json'
    if receipt_path.exists():
        receipt = read(receipt_path)
        if receipt['scope_binding'] != inventory['full_scope_binding']:
            raise ValueError('Observation binding belongs to another scope')
        for name, digest in receipt['bindings'].items():
            if sha(Path(name)) != digest:
                raise ValueError('Shared observation source changed: '+name)
        return receipt
    scope = read(Path(inventory['full_scope_binding']['path']))
    parent = Path(scope['source_workspace'])
    entries = inventory['entries']
    cases = sorted({r['entry']['case_id'] for r in entries if r['in_scope']})
    bindings, selections = {}, []
    for case in cases:
        bases = [parent] + sorted({Path(r['source_batch']) for r in entries
                                  if r['entry']['case_id'] == case}, key=str)
        candidates = []
        for base in bases:
            source = base/'endpoint_conditions'/(case+'.'+endpoint_sparse.CAPTURE_VERSION+'.json')
            if source.is_file():
                value = read(source)
                if value['case_id'] != case or value['version'] != endpoint_sparse.CAPTURE_VERSION:
                    raise ValueError('Invalid inherited observation identity: '+str(source))
                candidates.append(dict(path=str(source.resolve()), sha256=sha(source)))
        if not candidates:
            selections.append(dict(case_id=case, source=None,
                next_action='First native plan freezes shared observers before any native actions'))
            continue
        chosen = candidates[0]
        target = workspace/'endpoint_conditions'/Path(chosen['path']).name
        if target.exists() and sha(target) != chosen['sha256']:
            raise ValueError('Preserve conflicting batch observers: '+str(target))
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(chosen['path'], target)
        bindings[chosen['path']] = chosen['sha256']
        bindings[str(target)] = sha(target)
        selections.append(dict(case_id=case, source=chosen, target=str(target),
            historical_alternatives=candidates[1:]))
    receipt = dict(version='mechanic-v3-shared-observation-binding.v1', time=stamp(),
        scope_binding=inventory['full_scope_binding'], bindings=bindings, selections=selections,
        precedence='Active outcome workspace, then original source batches in path order',
        scoring_contract_unchanged=True, original_scope_unchanged=True,
        goals_actions_windows_weights_unchanged=True)
    exclusive_json(receipt_path, receipt)
    return receipt
