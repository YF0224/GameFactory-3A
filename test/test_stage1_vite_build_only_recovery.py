"""No browser/model launches; exercise launch routing and recovery fail-closed boundaries."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from engine_adapters.three_js.playtest import launch
from pipeline.eval.repair import vite_build_only_recovery as recovery


def project(tmp_path, *, script='vite build', dep=True, extra=None):
    package = {'scripts': {'build': script}, 'devDependencies': {'vite': '6.2.6'} if dep else {}}
    package['scripts'].update(extra or {})
    (tmp_path/'package.json').write_text(json.dumps(package))
    (tmp_path/'index.html').write_text('<script type="module" src="/src/main.js"></script>')
    return package


def test_build_only_uses_existing_bounded_build_then_static_dist(tmp_path, monkeypatch):
    monkeypatch.delenv('A3GAME_WEB_ENV', raising=False)
    project(tmp_path)
    before = (tmp_path/'package.json').read_bytes()
    selected = launch.resolve_launch(tmp_path)
    assert selected['mode'] == 'build_preview' and selected['build_script'] == 'build'
    assert selected['script'] is None and selected['preview_provider'] == 'python_http_server'
    command = launch.launch_command(selected, 'npm', '127.0.0.1', 1234)
    assert command[1:3] == ['-m', 'http.server']
    assert command[-1] == str(tmp_path/'dist')
    assert selected['entry'] == str(tmp_path/'dist/index.html')
    assert (tmp_path/'package.json').read_bytes() == before


@pytest.mark.parametrize('script', ['webpack build', 'echo vite build', 'vite build && echo done',
    'npx vite build', 'vite build --outDir other', 'vite build app', 'vite build; true',
    'vite build\nnode other.js', 'cross-env X=1 vite build', 'node vite build'])
def test_non_vite_or_ambiguous_shell_commands_never_selected(tmp_path, script):
    package = project(tmp_path, script=script)
    assert not launch.build_only_vite(package)
    assert launch.resolve_launch(tmp_path)['mode'] == 'static'


def test_vite_dependency_required(tmp_path):
    project(tmp_path, dep=False)
    assert launch.resolve_launch(tmp_path)['mode'] == 'static'


@pytest.mark.parametrize('extra,mode,script', [({'dev': 'vite'}, 'script', 'dev'),
    ({'start': 'node server.js'}, 'script', 'start'), ({'preview': 'vite preview'}, 'build_preview', 'preview')])
def test_existing_launch_routes_preserved(tmp_path, extra, mode, script):
    project(tmp_path, extra=extra)
    selection = launch.resolve_launch(tmp_path)
    assert selection['mode'] == mode and selection['script'] == script
    assert 'preview_provider' not in selection


@pytest.mark.parametrize('config', ["export default {root:'app'}", "export default {build:{outDir:'../else'}}",
    'export default {build:{outDir:process.env.OUT}}'])
def test_custom_build_roots_fail_closed(tmp_path, config):
    project(tmp_path); (tmp_path/'vite.config.js').write_text(config)
    with pytest.raises(ValueError, match='root|dist'):
        launch.resolve_launch(tmp_path)


def test_author_config_env_required_before_npm_build(tmp_path, monkeypatch):
    project(tmp_path); (tmp_path/'vite.config.js').write_text('const env=process.env.A3GAME_WEB_ENV;')
    monkeypatch.delenv('A3GAME_WEB_ENV', raising=False)
    with pytest.raises(ValueError, match='before build'):
        launch.resolve_launch(tmp_path)


def test_invalid_explicit_env_rejected_before_build(tmp_path, monkeypatch):
    project(tmp_path); monkeypatch.setenv('A3GAME_WEB_ENV', str(tmp_path/'missing'))
    with pytest.raises(ValueError, match='complete'):
        launch.resolve_launch(tmp_path)


def test_owned_env_restores_caller_and_is_inherited_at_selection(tmp_path, monkeypatch):
    project(tmp_path)
    from engine_adapters.three_js.playtest import dependencies
    monkeypatch.setattr(dependencies, 'verify_critical_packages', lambda *a: [])
    (tmp_path/'node_modules/.bin').mkdir(parents=True)
    (tmp_path/'node_modules/.bin/vite').touch()
    monkeypatch.setenv('A3GAME_WEB_ENV', '/original')
    import os
    with recovery.environment(tmp_path):
        assert os.environ['A3GAME_WEB_ENV'] == str(tmp_path)
        assert launch.resolve_launch(tmp_path)['build_kind'] == 'vite_build_only'
    assert os.environ['A3GAME_WEB_ENV'] == '/original'


def test_dist_link_rejected(tmp_path, monkeypatch):
    monkeypatch.delenv('A3GAME_WEB_ENV', raising=False)
    project(tmp_path); (tmp_path/'dist').symlink_to(tmp_path.parent, target_is_directory=True)
    with pytest.raises(ValueError, match='symlink'):
        launch.resolve_launch(tmp_path)


def test_retained_hash_excludes_only_copies_and_lineage(tmp_path):
    for rel in ['input/project/a', 'runtime/project/b', 'recovery/old/x', 'takes/1/native/frame.png',
                'model_calls/a.json', 'input/criteria.json', 'playable_score.json', 'qualification_hold.json']:
        p=tmp_path/rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(rel)
    assert set(recovery.retained(tmp_path)) == {'takes/1/native/frame.png', 'model_calls/a.json',
        'input/criteria.json', 'playable_score.json', 'qualification_hold.json'}


def test_accepted_response_hash_and_plan_equality(tmp_path):
    p=tmp_path/'model_calls/plan_t1'; p.mkdir(parents=True)
    r=p/'response.json'; r.write_text('{"summary":"accepted"}')
    (p/'accepted_response.json').write_text(json.dumps({'path':'response.json','sha256':recovery.sha256(r)}))
    q=tmp_path/'takes/1'; q.mkdir(parents=True); (q/'plan.json').write_bytes(r.read_bytes())
    assert recovery.accepted(tmp_path)['plan_sha256'] == recovery.sha256(r)
    (q/'plan.json').write_text('{"summary":"changed"}')
    with pytest.raises(ValueError, match='differs'):
        recovery.accepted(tmp_path)


def test_space_guard_reserves_8gib_in_addition_to_work(tmp_path, monkeypatch):
    monkeypatch.setattr(recovery.shutil, 'disk_usage', lambda p: SimpleNamespace(free=recovery.RESERVE+1))
    with pytest.raises(ValueError, match='8GiB'):
        recovery.check_space(tmp_path, size=2)


def test_missing_or_flag_only_replacement_not_qualified(tmp_path):
    p=tmp_path/recovery.LINEAGE; p.mkdir(parents=True)
    (p/'replacement.json').write_text('{"qualified":true,"complete":true}')
    assert recovery.qualified_replacement_score(tmp_path) is None


def test_existing_record_claim_cannot_be_rewritten(tmp_path):
    claim=tmp_path/'record_t1_claim.json'; claim.write_text('old failure')
    with pytest.raises(FileExistsError):
        with claim.open('x'):
            pass
    assert claim.read_text() == 'old failure'


def test_sparse_capture_requires_wallclock_not_frames_divided_by_fps(tmp_path):
    r=tmp_path/'takes/1/record'; n=r/'native/take'; n.mkdir(parents=True)
    def write(p, data): p.write_text(json.dumps(data))
    write(r/'record_result.json', {'frames':100})
    write(r/'adapter_result.json', {'ok':True,'payload':{'delivered_build_completed':True}})
    write(r/'launch_selection.json', {'build_kind':'vite_build_only',
        'preview_provider':'python_http_server','serve_root':str(tmp_path/'dist')})
    (r/'delivered_build.log').write_text('build complete')
    write(n/'recording_progress.json', {'status':'completed','requested_seconds':75,
        'frames':100,'recorded_seconds':10,'channels_written':{'actions':4}})
    write(n/'report.json', {'sampling_complete':True,'wallclock_seconds':75.01,'capture_deadline_ms':75000})
    write(n/'input_view_cleanup.json', {'input_cleanup':True,'held_keys_after_release':0,'held_buttons_after_release':0})
    write(n/'browser_cleanup.json', {'input_cleanup':True,'view_cleanup':True,'browser_cleanup':True})
    write(n/'host_process_cleanup.json', {'process_cleanup':True,'server_group_alive':False,
        'recorder':{'process_cleanup':True,'group_alive':False}})
    assert recovery.qualified_record(tmp_path,1)['wallclock_seconds']==75.01
    write(n/'report.json', {'sampling_complete':True,'wallclock_seconds':2,'capture_deadline_ms':75000})
    with pytest.raises(ValueError, match='75s'):
        recovery.qualified_record(tmp_path,1)
