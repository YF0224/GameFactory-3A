"""Place a Stage3 candidate in a sibling run of its original Sol game."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re

from pipeline.game_eval.refine.common import dump


def candidate_location(game, folder, config):
    """Keep the original task-relative path, changing only the run directory."""
    game_id = game['game_id']
    root = (Path(config['bench_root']) / 'test_data/outputs/initial_game_gen/gpt_sol6p1').resolve()
    game_root = root / game_id
    source = Path(game['project']['project_root']).resolve()
    if not source.is_relative_to(game_root):
        raise ValueError('Stage3 source must belong to the original Sol game: ' + str(source))
    relative = source.relative_to(game_root)
    if len(relative.parts) < 2:
        raise ValueError('Original game requires a run_id and task-relative project path')
    # A frozen batch name gives all turns of one game/model a stable run identity.
    model = re.sub(r'[^A-Za-z0-9_-]+', '_', config['agent']['model']).strip('_')
    batch_id = Path(folder).parents[1].name
    batch_id = re.sub(r'[^A-Za-z0-9_-]+', '_', batch_id).strip('_')
    stamp = re.search(r'(\d{8}_\d{6})$', batch_id)
    run_id = f'{model}_refine_{stamp.group(1) if stamp else batch_id}'
    if config.get('authorized_new_experiment'):
        run_id += '_experiment_' + config['authorized_new_experiment']['sha256'][:16]
    run_root = game_root / run_id
    if run_id == relative.parts[0] or not run_root.resolve().is_relative_to(game_root):
        raise ValueError('Candidate run would overwrite or escape original game')
    return run_root, run_root.joinpath(*relative.parts[1:])


def bind_candidate_run(game, folder, config, *, existing=False):
    """Create a run-owned project and a compatibility alias for the agent/ledger.

    Existing active sessions retain their prompt paths; the actual project moves
    to the sibling run without another provider call or repair-budget change.
    The caller must quiesce all owned processes before migrating an active run.
    """
    folder = Path(folder).resolve()
    workspace = folder / 'workspace'
    alias = workspace / 'project'
    run_root, target = candidate_location(game, folder, config)
    if run_root.exists() or run_root.is_symlink():
        raise FileExistsError('Refusing to overwrite a run: ' + str(run_root))
    if existing:
        if alias.is_symlink() or not alias.is_dir():
            raise ValueError('Migration requires an existing real candidate directory')
    elif alias.exists() or alias.is_symlink():
        raise FileExistsError(alias)
    run_root.mkdir(parents=True, exist_ok=False)
    target.parent.mkdir(parents=True, exist_ok=True)
    workspace.mkdir(parents=True, exist_ok=True)
    if existing:
        alias.rename(target)
    # snapshot() resolves this alias before creating the actual new project.
    try:
        alias.symlink_to(target, target_is_directory=True)
    except BaseException:
        if existing:
            target.rename(alias)
        raise
    origin = Path(game['project']['project_root']).resolve()
    binding = {
        'schema': 'stage3.original_game_sibling_run.v1',
        'game_id': game['game_id'], 'run_id': run_root.name,
        'run_root': str(run_root), 'project_root': str(target),
        'original_project_root': str(origin),
        'source_run_id': origin.relative_to(run_root.parent).parts[0],
        'agent_model': config['agent']['model'],
        'control_folder': str(folder), 'workspace_project_alias': str(alias),
        'created_at': datetime.now().astimezone().isoformat(),
        'migrated_existing_candidate': existing,
        'repair_round_limit': config['repair_rounds'],
        'prior_counted_attempts': config.get('explicit_restart', {}).get('prior_counted_attempts', 0),
        'evaluation_started': False,
        **({'authorized_new_experiment': config['authorized_new_experiment']}
           if config.get('authorized_new_experiment') else {}),
    }
    dump(run_root / 'run_meta.json', binding)
    dump(folder / 'candidate_run.json', binding)
    # Make the original run's task contracts available at the same relative path.
    import shutil
    for name in ('mechanic_contract.json', 'ui_contract.json', 'scene_manifest.json',
                 'asset_slots.json', 'placeholder_registry.json'):
        src = origin.parent / name
        if src.is_file():
            shutil.copy2(src, target.parent / name)
    (run_root / 'refine').symlink_to(folder, target_is_directory=True)
    for name in ('repair_report.md', 'repair_status.json'):
        (run_root / name).symlink_to(workspace / name)
    return binding
