import json
from pathlib import Path

import pytest

from pipeline.eval.stage1.native_log import godot_product_errors
from pipeline.eval.stage1 import playable_rules
from pipeline.eval.repair import godot_import_log_recovery as recovery
from pipeline.eval.stage1.paths import write_json, read_json, sha256


@pytest.mark.parametrize('line', [
    'SCRIPT ERROR: Parse Error: invalid code',
    '\x1b[1;31mSCRIPT ERROR:\x1b[0m Parse Error: invalid code',
    '\x1b[31mERROR: Failed loading resource\x1b[0m',
    '\x1b[0m\x1b[1mUSER ERROR: bad value',
])
def test_terminal_decoration_does_not_hide_existing_error_policy(line):
    assert godot_product_errors('Godot 4\n' + line)


@pytest.mark.parametrize('line', ['WARNING: harmless', 'text mentioning ERROR: inside line', 'Godot 4'])
def test_no_new_error_categories(line):
    assert not godot_product_errors(line)


def test_raw_log_overrides_old_false_metadata_but_timeout_remains_unknown(tmp_path):
    write_json(tmp_path / 'import_result.json', {'exit_code': 0, 'product_errors': False})
    (tmp_path / 'import.log').write_text('\x1b[31mSCRIPT ERROR: Parse Error: broken\x1b[0m')
    assert playable_rules._import(tmp_path, 'godot', [tmp_path])['status'] == 'FAIL'
    write_json(tmp_path / 'import_result.json', {'timeout': True, 'product_errors': False})
    assert playable_rules._import(tmp_path, 'godot', [tmp_path]) is None


def test_offline_correction_preserves_parent_and_detects_evidence_tamper(tmp_path):
    out = tmp_path / 'out'
    record = out / 'takes/1/record'
    source = tmp_path / 'source'
    source.mkdir()
    write_json(out / 'manifest.json', {'engine': 'godot', 'project_source': str(source),
                                      'project_digest': recovery.prepare.tree_digest({})})
    write_json(out / 'status.json', {'state': 'done'})
    checks = {'play.import': 'PASS', 'play.launch': 'FAIL', 'play.operate': 'UNVERIFIED'}
    old = {'complete': True, 'checks': checks, 'takes': [{'take': 1, 'checks': checks}], 'playable': 33.33}
    write_json(out / 'playable_score.json', old)
    write_json(record / 'import_result.json', {'exit_code': 0, 'product_errors': False})
    (record / 'import.log').write_text('\x1b[31mSCRIPT ERROR: Parse Error: broken\x1b[0m')
    write_json(record / 'record_result.json', {})
    # Real saved pixels, uniformly blank: existing launch rule must still fail.
    from PIL import Image
    Image.new('RGB', (160, 90)).save(record / 'blank.png')
    (record / 'frame_index.jsonl').write_text('{"frame_id":"f1","t_ms":1000,"path":"blank.png"}\n')
    (record / 'frame_index.jsonl').write_text(''.join(json.dumps({'frame_id': f'f{i}', 't_ms': i*500, 'path': 'blank.png'})+'\n' for i in range(5)))
    (record / 'actions.jsonl').write_text(json.dumps({'action_id': 'a1', 'action': 'key', 't_ms': 600, 'end_t_ms': 700})+'\n')
    before = recovery.binding(out)
    result = recovery.correct(out)
    assert result['playable'] == 0
    assert recovery.binding(out) == before
    assert read_json(out / 'playable_score.json') == old
    assert recovery.qualified_replacement_score(out) == result
    assert recovery.correct(out) == result
    (record / 'import.log').write_text('tampered')
    assert recovery.qualified_replacement_score(out) is None
