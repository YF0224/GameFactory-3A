"""Offline contracts for migrated paths, source binding and playtest inputs."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline.eval.stage1 import budgets, delivery, prepare
from pipeline.eval.stage1.paths import DELIVERY_SCHEMA, sha256, write_json
from pipeline.eval.stage3 import criteria, inputs


@pytest.fixture
def bound_delivery(tmp_path):
    case = tmp_path / 'inputs'
    case.mkdir()
    requirement = case / 'three_js.txt'
    requirement.write_text('engine: three_js\ntier: M\nSelected requirement\n')
    ref = case / 'ref_images' / 'reference.png'
    ref.parent.mkdir()
    ref.write_bytes(b'reference fixture')
    run = tmp_path / 'G001_fixture' / 'three_js_run'
    project = run / 'project'
    project.mkdir(parents=True)
    (project / 'index.html').write_text('<html>authored project</html>')
    d = dict(schema=DELIVERY_SCHEMA, stage='stage1', model='sol',
             game_id=run.parent.name, run_id=run.name, engine='three_js',
             project_root='project', entry='index.html', created_at='2026-11-25T00:00:00Z',
             generator={'kind': 'external_agent'},
             requirement={'path': str(requirement), 'sha256': sha256(requirement)})
    write_json(run / 'delivery.json', d)
    write_json(run / '.generation/job.json', {'notes': {
        'requirement': str(requirement), 'requirement_sha256': sha256(requirement),
        'engine': 'three_js'}})
    return run, requirement, d


def test_selected_requirement_drives_snapshot_engine_and_budget(bound_delivery, tmp_path, monkeypatch):
    run, requirement, d = bound_delivery
    assert delivery.validate(run) == []
    assert budgets.budget_for(d['game_id'], requirement)['gameplay_ms'] == 180000
    monkeypatch.setattr(prepare.suites, 'get', lambda name: SimpleNamespace(
        build=lambda gid: {'game_id': gid, 'criteria': []}))
    before = (run / 'project/index.html').read_bytes()
    out = tmp_path / 'evaluation'
    manifest = prepare.prepare(run, out, models={'planner': 'fixture', 'judge': 'fixture'})
    assert (out / 'input/requirement.txt').read_bytes() == requirement.read_bytes()
    assert (out / 'input/references/1_reference.png').read_bytes() == b'reference fixture'
    assert manifest['budget']['gameplay_ms'] == 180000
    assert (run / 'project/index.html').read_bytes() == before
    prepare.verify(out)
    (out / 'input/requirement.txt').write_text('modified frozen requirement')
    with pytest.raises(RuntimeError, match='frozen inputs changed'):
        prepare.verify(out)


@pytest.mark.parametrize('tamper', ['requirement', 'engine', 'job'])
def test_selected_requirement_binding_fails_closed(bound_delivery, tamper):
    run, requirement, d = bound_delivery
    if tamper == 'requirement':
        requirement.write_text('engine: three_js\ntier: S\nchanged')
    elif tamper == 'engine':
        d['engine'] = 'godot'
        write_json(run / 'delivery.json', d)
    else:
        write_json(run / '.generation/job.json', {'notes': {
            'requirement': str(requirement), 'requirement_sha256': 'wrong', 'engine': 'three_js'}})
    assert delivery.validate(run)


def test_delivery_requires_json_object(tmp_path):
    write_json(tmp_path / 'delivery.json', [])
    assert delivery.validate(tmp_path) == ['delivery.json must contain a JSON object']


@pytest.fixture
def playtest(tmp_path, monkeypatch):
    root = tmp_path / 'playtest'
    case = root / 'g8'
    case.mkdir(parents=True)
    (root / 'sources').mkdir()
    gid = 'G008_fixture'
    groups = {
        'mechanic_gamefeel': [{'game_id': gid, 'selection_id': 'M1', 'selection_kind': 'mechanic',
                              'repair_goal': 'Goal', 'test_action': 'Input', 'pass_condition': 'Outcome'}],
        'vfx': [], 'import': [],
        'initgame': [{'game_id': gid, 'selected_project': {'engine': 'UE5', 'project_root': 'original'},
                      'source_model': 'sol'}]}
    index = {'schema_version': 'playtest.case_inputs.v1', 'game_id': gid, 'game_directory': 'g8',
             'inputs': {}, 'max_repair_attempts_per_game_model': 10,
             'task_counts': {'mechanic': 1, 'gamefeel': 0, 'vfx': 0, 'import': 0}, 'task_total': 1,
             'selected_project': groups['initgame'][0]['selected_project'], 'source_model': 'sol'}
    sources = []
    for family, rows in groups.items():
        path = case / f'{family}.json'
        write_json(path, rows)
        snapshot = root / 'sources' / f'{family}.jsonl'
        # Blank physical lines must remain represented in source_record metadata.
        snapshot.write_text('\n' + '\n'.join(json.dumps(r) for r in rows) + '\n')
        sources.append({'family': family, 'sha256': sha256(snapshot), 'record_count': len(rows)})
        index['inputs'][family] = dict(path=path.name, sha256=sha256(path), record_count=len(rows),
                                      source_snapshot=f'../sources/{snapshot.name}',
                                      source_records=[{'source_record_index': i + 1, 'physical_line': i + 2}
                                                      for i in range(len(rows))])
    write_json(root / 'manifest.json', {'sources': sources})
    write_json(case / 'refine.json', index)
    monkeypatch.setattr(inputs, 'ROOT', root)
    monkeypatch.setattr(criteria, 'INPUTS', tmp_path / 'absent_legacy')
    monkeypatch.setattr(criteria, 'IMPORT_DETAIL', tmp_path / 'absent_import_details')
    return case, index


def test_stage3_criteria_resolves_playtest_alias_and_full_id(playtest):
    case, index = playtest
    assert inputs.load(index['game_id'])[0] == case
    alias = criteria.build('g8')
    full = criteria.build(index['game_id'])
    assert alias == full
    assert [r['id'] for r in full['criteria']] == ['M1']


@pytest.mark.parametrize('tamper', ['task', 'resealed_task', 'source', 'line', 'count', 'budget'])
def test_stage3_rejects_changed_frozen_inputs(playtest, tamper):
    case, index = playtest
    ref = index['inputs']['mechanic_gamefeel']
    if tamper in ('task', 'resealed_task'):
        path = case / ref['path']
        rows = json.loads(path.read_text())
        rows[0]['repair_goal'] = 'Modified task'
        write_json(path, rows)
        if tamper == 'resealed_task':
            ref['sha256'] = sha256(path)
    elif tamper == 'source':
        (case / ref['source_snapshot']).write_text('changed frozen source')
    elif tamper == 'line':
        ref['source_records'][0]['physical_line'] = 1
    elif tamper == 'count':
        index['task_total'] = 99
    else:
        index['max_repair_attempts_per_game_model'] = 11
    write_json(case / 'refine.json', index)
    with pytest.raises((ValueError, json.JSONDecodeError)):
        criteria.build(index['game_id'])


def test_stage3_delivery_binds_new_layout_to_generation_job(playtest, tmp_path, monkeypatch):
    case, index = playtest
    run = case / 'sol'
    (run / 'project').mkdir(parents=True)
    (run / 'project/main.uproject').write_text('{}')
    monkeypatch.setattr(delivery, 'SAMPLES', tmp_path / 'absent_samples')
    d = dict(schema=DELIVERY_SCHEMA, stage='stage3', model='sol', game_id=index['game_id'],
             run_id='sol_refine_fixture', engine='ue5', project_root='project', entry='main.uproject',
             created_at='2026-11-25T00:00:00Z', generator={}, source={}, rounds_used=10)
    write_json(run / 'delivery.json', d)
    write_json(run / '.generation/job.json', {k: d[k] for k in ('stage', 'model', 'game_id', 'run_id')})
    assert delivery.validate(run) == []
    for key, value in [('run_id', 'different_run'), ('rounds_used', 11), ('model', 'glm')]:
        write_json(run / 'delivery.json', dict(d, **{key: value}))
        assert delivery.validate(run)


def test_assets_bridge_forwards_arguments(monkeypatch):
    from pipeline.eval import assets
    from pipeline.game_eval.asset_eval import run
    calls = []
    monkeypatch.setattr(run, 'main', lambda argv: calls.append(argv) or 7)
    args = ['--scope', 'obj', '--mode', 'preflight', '--games', 'G001', '--no-sol']
    assert assets.run(args) == 7
    assert calls == [args]


def test_data_root_and_relative_profiles_ignore_cwd(tmp_path):
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, GF3A_DATA_ROOT=str(tmp_path / 'data'), PYTHONPATH=str(root),
               A3GAME_PLANNER_MODEL='planner-fixture', A3GAME_JUDGE_MODEL='judge-fixture')
    code = '''
import json
from pipeline.eval.stage1.paths import DATA_ROOT, OUTPUTS, SAMPLES, resolve_input
from pipeline.game_eval.asset_eval.common import OUTPUTS as ASSET_OUTPUTS
from pipeline.eval.model_config import PLANNER_MODEL, JUDGE_MODEL
print(json.dumps([str(DATA_ROOT), str(OUTPUTS), str(SAMPLES), str(ASSET_OUTPUTS),
                  str(resolve_input('test_data/inputs.json')), PLANNER_MODEL, JUDGE_MODEL]))
'''
    result = subprocess.run([sys.executable, '-B', '-c', code], cwd=tmp_path, env=env,
                            capture_output=True, text=True, check=True)
    data = tmp_path / 'data'
    assert json.loads(result.stdout) == [str(data), str(data / 'outputs'), str(data / 'test_samples'),
                                         str(data / 'outputs/eval/asset_eval'), str(data / 'inputs.json'),
                                         'planner-fixture', 'judge-fixture']
