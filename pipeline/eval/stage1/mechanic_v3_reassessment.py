"""Freeze the user's explicit Astra reassessment without changing parent scopes."""
from pathlib import Path
import copy
import json
import shutil
from . import mechanic_v3_full_scope as scope, mechanic_v3_revision as revisions
from . import mechanic_v3_runner as runner, evaluation_model_profile as models
from .protocol import dump, sha


def freeze(workspace, source_workspace):
    from . import two_column_sync
    workspace, source_workspace = Path(workspace).resolve(), Path(source_workspace).resolve()
    if (workspace / models.LOCK).exists():
        models.profile_for(workspace)
        return scope.load(workspace)
    if workspace.exists() and any(workspace.iterdir()):
        raise ValueError('Partial reassessment initialization must be inspected and preserved')
    inventory = scope.load(source_workspace)
    registry = two_column_sync.TARGET.with_name('mechanic_v3_gameness_v4_publications.json')
    baseline_bytes = registry.read_bytes()
    ledger = json.loads(baseline_bytes)
    baselines = {}
    for row in ledger['rows'].values():
        identity = row['identity']
        if identity not in inventory['active_selection'] or row['method'] != 'Opus':
            continue
        for column, pub in row['columns'].items():
            if pub['score'] >= 60:
                continue
            _, verified, _ = two_column_sync.verified(Path(pub['workspace']), identity, column)
            if verified['source_sha256'] != row['source_sha256'] or verified['columns'][column] != pub:
                raise ValueError('Current below60 baseline is not exactly source-qualified')
            baselines.setdefault(identity, {})[column] = copy.deepcopy(pub)
    if not baselines:
        raise ValueError('No complete source-qualified Opus scores below60')
    selected = sorted(baselines)
    entries = []
    for row in inventory['entries']:
        if row['entry']['id'] in selected:
            row = copy.deepcopy(row)
            row['preferred_record'] = None
            row['record_candidates'] = []
            row['initial_stage'] = 'USER_AUTHORIZED_ASTRA_NEW_PLAN'
            entries.append(row)
    if len(entries) != len(selected) or any(not row['in_scope'] for row in entries):
        raise ValueError('Reassessment cannot introduce an excluded original')
    workspace.mkdir(parents=True)
    snapshot = workspace / 'lineage/baseline_registry.json'
    snapshot.parent.mkdir(); snapshot.write_bytes(baseline_bytes)
    dump(workspace / 'inventory.json', dict(version=scope.VERSION, created=runner.stamp(),
         entries=entries, cases=sorted({r['entry']['case_id'] for r in entries}),
         independent_reassessment=True, original_candidates_unchanged=True))
    shutil.copy2(source_workspace / 'assessment_revision.json', workspace / 'assessment_revision.json')
    parent_scope = Path(inventory['full_scope_binding']['path'])
    bindings = {str(parent_scope): sha(parent_scope), str(snapshot): sha(snapshot),
                str(source_workspace / 'inventory.json'): sha(source_workspace / 'inventory.json')}
    parent_value = runner.read(parent_scope)
    bindings.update(parent_value['bindings'])
    for case in sorted({r['entry']['case_id'] for r in entries}):
        src = revisions.contract_dir(source_workspace, case)
        dst = revisions.contract_dir(workspace, case)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dst)
        for path in src.rglob('*'):
            if path.is_file(): bindings[str(path)] = sha(path)
        for path in dst.rglob('*'):
            if path.is_file(): bindings[str(path)] = sha(path)
    from .mechanic_v3_native import configuration
    configuration(workspace, source_workspace)
    frozen = dict(version=scope.VERSION, revision='outcome_frame_v1', created=runner.stamp(),
        inventory_sha256=sha(workspace / 'inventory.json'), bindings=bindings,
        selected_identities=selected, all_discovered_identities=selected,
        source_workspace=str(source_workspace), old_results_preserved=True,
        authorized_columns=['Mechanic', 'Gameness'], model=models.DEFAULT,
        authorized_models=['Opus'], authorized_engines=['godot', 'three_js'],
        parent_scope_binding=inventory['full_scope_binding'])
    path = workspace / 'scopes/all_s_original/scope.json'
    dump(path, frozen)
    dump(workspace / 'full_s_scope.json', dict(version=scope.VERSION, scope_sha256=sha(path)))
    profile = dict(version=models.VERSION, purpose='user_authorized_opus_below60_reassessment',
        authorization='2026-11-04 direct user instruction: Astra planner/judge for all original Opus below60; Sol remaining; parallel respecting formal resource leases',
        roles=dict(static=models.DEFAULT, planner=models.ASTRA, judge=models.ASTRA),
        baselines=baselines, bindings={str(path): sha(path), str(snapshot): sha(snapshot)},
        scoring_semantics_unchanged=True, baseline_not_supplied_to_models=True)
    dump(workspace / models.FILE, profile)
    dump(workspace / models.LOCK, dict(profile_sha256=sha(workspace / models.FILE)))
    sync_config = runner.read(source_workspace / 'two_column_sync.json')
    dump(workspace / 'two_column_sync.json', sync_config)
    scope.bind_observation_conditions(workspace)
    return scope.load(workspace)
