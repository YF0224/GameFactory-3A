"""The actual observation config must keep the full frozen recording window."""
import time
from types import SimpleNamespace

import pytest
from pipeline.eval.stage1 import record
from pipeline.eval.stage1.paths import read_json, write_json


@pytest.mark.parametrize('kind,schedule_fails', [('input', False), ('wait_until', False), ('input', True)])
def test_recording_window_survives_each_capture_mode(tmp_path, monkeypatch, kind, schedule_fails):
    project = tmp_path / 'runtime/project'
    project.mkdir(parents=True)
    (project / 'project.godot').write_text('[display]\nwindow/size/viewport_width=1280\nwindow/size/viewport_height=720\n')
    plan_path = tmp_path / 'takes/1/plan.json'
    plan = {'max_duration_ms': 18000, 'probes': [{'id': 'p', 'criterion_ids': ['play.operate'],
             'steps': [{'id': 's', 'kind': kind, 'key': 'Space', 'duration_ms': 100,
                        'timeout_ms': 100}]}]}
    write_json(plan_path, plan)
    original = plan_path.read_bytes()
    native = plan_path.parent / 'record/native'
    native.mkdir(parents=True)
    monkeypatch.setattr(record, 'godot_executable', lambda: '/fixture/godot')
    def imported(cmd, log, timeout):
        log.write_text('fixture import success\n')
        return {'exit_code': 0, 'timeout': False}
    monkeypatch.setattr(record, '_run', imported)
    if schedule_fails:
        def overflow(*args):
            raise ValueError('fixture: too many action points')
        monkeypatch.setattr(record.capture, 'schedule', overflow)
    def captured(**kwargs):
        config = read_json(kwargs['observation_plan'])
        assert kwargs['observation_plan'] != plan_path
        assert config['recording_ms'] == 75000
        assert config['max_duration_ms'] == 18000
        assert config['probes'] == plan['probes']
        assert kwargs['duration'] == 75
        assert (kwargs['width'], kwargs['height']) == (1280, 720)
        assert read_json(native.parent / 'window_size.json')['project_config_sha256'] == record.sha256(project / 'project.godot')
        assert ('native_capture_schedule' in config) == (kind == 'input' and not schedule_fails)
        assert plan_path.read_bytes() == original
        return {'fixture': 'adapter received complete observation window'}
    client = SimpleNamespace(playtest=SimpleNamespace(record=captured))
    result = record._godot(client, project, plan_path, native,
                           {'recording_ms': 75000, 'engine_startup_ms': 90000}, time.monotonic() + 210)
    assert result['fixture'] == 'adapter received complete observation window'


@pytest.mark.parametrize('config,expected', [
    ('config_version=5\n', (960, 540)),
    ('[display]\nwindow/size/viewport_width=1280 ; author width\nwindow/size/viewport_height=720\n', (1280, 720)),
    ('[application]\nwindow/size/viewport_width=2000\n', (960, 540)),
])
def test_authored_window_dimensions(tmp_path, config, expected):
    (tmp_path / 'project.godot').write_text(config)
    assert record._godot_window_size(tmp_path) == expected


@pytest.mark.parametrize('value', ['0', '-1', '"1280"', 'garbage'])
def test_invalid_authored_window_dimensions_fail_closed(tmp_path, value):
    (tmp_path / 'project.godot').write_text('[display]\nwindow/size/viewport_width=' + value + '\n')
    with pytest.raises(record.HarnessError, match='Invalid authored Godot'):
        record._godot_window_size(tmp_path)
