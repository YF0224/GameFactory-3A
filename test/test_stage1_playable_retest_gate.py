"""Runner cannot publish short native evidence or reset consumed attempts."""
import importlib.util
import sys
from pathlib import Path

import pytest

from pipeline.eval.stage1 import playable_support as runner

from pipeline.eval.repair import godot_duration_recovery as duration

SINGLE = {'engine': 'godot'}
SCORE = {'complete': True, 'playable': 100, 'checks': {'play.import': 'PASS', 'play.launch': 'PASS', 'play.operate': 'PASS'}}


def test_short_cannot_publish_even_corrected_score(tmp_path, monkeypatch):
    monkeypatch.setattr(duration, 'qualification', lambda *a, **k: {'window_qualified': False, 'disposition': 'ELIGIBLE_ONE_SHORT_TAKE', 'native_count': 1})
    monkeypatch.setattr(runner, '_candidate_score', lambda *a: SCORE)
    assert runner.completed_score(tmp_path, SINGLE) is None
    with pytest.raises(RuntimeError, match='bounded recovery'):
        runner.ensure_retry_safe(tmp_path, SINGLE)


def test_existing_window_can_publish(tmp_path, monkeypatch):
    monkeypatch.setattr(duration, 'qualification', lambda *a, **k: {'window_qualified': True, 'disposition': 'KEEP_EXISTING_75S', 'native_count': 1})
    monkeypatch.setattr(runner, '_candidate_score', lambda *a: SCORE)
    assert runner.completed_score(tmp_path, SINGLE) == SCORE


def test_duration_replacement_is_verified_before_parent(tmp_path, monkeypatch):
    receipt = tmp_path / 'recovery/godot_duration_v1/replacement.json'
    receipt.parent.mkdir(parents=True)
    receipt.write_text('{}')
    monkeypatch.setattr(duration, 'qualified_replacement_score', lambda *a: SCORE)
    monkeypatch.setattr(duration, 'qualification', lambda *a, **k: pytest.fail('parent gate must not replace child verification'))
    assert runner.completed_score(tmp_path, SINGLE) == SCORE
    monkeypatch.setattr(duration, 'qualified_replacement_score', lambda *a: None)
    assert runner.completed_score(tmp_path, SINGLE) is None


def test_dual_client_route_keeps_own_gate(tmp_path, monkeypatch):
    monkeypatch.setattr(duration, 'qualification', lambda *a, **k: pytest.fail('dual has separate evidence contract'))
    monkeypatch.setattr(runner, '_candidate_score', lambda *a: SCORE)
    assert runner.completed_score(tmp_path, {'engine': 'godot', 'required_real_clients': 2}) == SCORE


def test_import_error_does_not_allow_launch_success_without_window(tmp_path, monkeypatch):
    monkeypatch.setattr(duration, 'qualification', lambda *a, **k: {'window_qualified': False, 'disposition': 'PRODUCT_IMPORT_FAILURE', 'native_count': 0})
    monkeypatch.setattr(runner, '_candidate_score', lambda *a: SCORE)
    assert runner.completed_score(tmp_path, SINGLE) is None


def test_no_new_take_after_two_consumed(tmp_path, monkeypatch):
    monkeypatch.setattr(duration, 'qualification', lambda *a, **k: {'window_qualified': False, 'disposition': 'BLOCKED_MAX_TAKES', 'native_count': 2})
    with pytest.raises(RuntimeError, match='BLOCKED_MAX_TAKES'):
        runner.ensure_retry_safe(tmp_path, SINGLE)


def test_product_failure_requires_independent_rules_verification(tmp_path, monkeypatch):
    score = {'complete': True, 'playable': 0, 'checks': {'play.import': 'FAIL', 'play.launch': 'FAIL', 'play.operate': 'UNVERIFIED'}}
    monkeypatch.setattr(duration, 'qualification', lambda *a, **k: {'window_qualified': False, 'disposition': 'PRODUCT_IMPORT_FAILURE', 'native_count': 0, 'evaluated_failure_score': score})
    monkeypatch.setattr(runner, '_candidate_score', lambda *a: pytest.fail('must use independently verified failure'))
    assert runner.completed_score(tmp_path, SINGLE) == score


def test_legacy_caller_cannot_bypass_godot_gate(tmp_path, monkeypatch):
    (tmp_path / 'manifest.json').write_text('{"engine": "godot"}')
    monkeypatch.setattr(duration, 'qualification', lambda *a, **k: {'window_qualified': False, 'disposition': 'ELIGIBLE_ONE_SHORT_TAKE', 'native_count': 1})
    monkeypatch.setattr(runner, '_candidate_score', lambda *a: SCORE)
    assert runner.completed_score(tmp_path, {}) is None


def test_legacy_unity_caller_remains_supported(tmp_path, monkeypatch):
    (tmp_path / 'manifest.json').write_text('{"engine": "unity3d"}')
    monkeypatch.setattr(runner, '_candidate_score', lambda *a: SCORE)
    assert runner.completed_score(tmp_path, {}) == SCORE


def test_existing_full_second_take_uses_offline_verifier_first(tmp_path, monkeypatch):
    from pipeline.eval.repair import godot_existing_window_recovery as existing
    receipt = tmp_path / 'recovery/godot_existing_window_v1/replacement.json'
    receipt.parent.mkdir(parents=True)
    receipt.write_text('{}')
    monkeypatch.setattr(existing, 'qualified_replacement_score', lambda *a: SCORE)
    monkeypatch.setattr(duration, 'qualification', lambda *a, **k: pytest.fail('must verify reused full second take'))
    assert runner.completed_score(tmp_path, SINGLE) == SCORE
    monkeypatch.setattr(existing, 'qualified_replacement_score', lambda *a: None)
    assert runner.completed_score(tmp_path, SINGLE) is None


def test_metadata_finalization_precedes_duration_and_fails_closed(tmp_path, monkeypatch):
    from pipeline.eval.repair import godot_duration_metadata_recovery as metadata
    receipt = tmp_path / 'recovery/godot_duration_v1/metadata_finalization_v1/replacement.json'
    receipt.parent.mkdir(parents=True)
    receipt.write_text('{}')
    (receipt.parent.parent / 'replacement.json').write_text('{}')
    monkeypatch.setattr(metadata, 'qualified_replacement_score', lambda *a: SCORE)
    monkeypatch.setattr(duration, 'qualified_replacement_score', lambda *a: pytest.fail('metadata must qualify first'))
    monkeypatch.setattr(duration, 'qualification', lambda *a, **k: pytest.fail('parent cannot bypass metadata qualification'))
    assert runner.completed_score(tmp_path, SINGLE) == SCORE
    monkeypatch.setattr(metadata, 'qualified_replacement_score', lambda *a: None)
    assert runner.completed_score(tmp_path, SINGLE) is None


@pytest.mark.parametrize('window', [
    {'window_qualified': True, 'disposition': 'KEEP_EXISTING_75S', 'native_count': 1},
    {'window_qualified': False, 'disposition': 'PRODUCT_IMPORT_FAILURE', 'native_count': 0, 'evaluated_failure_score': SCORE},
])
def test_unresolved_godot_hold_blocks_window_and_product_failure(tmp_path, monkeypatch, window):
    (tmp_path / 'qualification_hold.json').write_text('{"kind":"unknown_hold"}')
    monkeypatch.setattr(duration, 'qualification', lambda *a, **k: window)
    monkeypatch.setattr(runner, '_candidate_score', lambda *a: pytest.fail('held score must not publish'))
    assert runner.completed_score(tmp_path, SINGLE) is None


def test_more_than_two_clients_cannot_use_dual_result(tmp_path):
    import json
    (tmp_path / 'playable_score.json').write_text(json.dumps({**SCORE, 'required_real_clients': 2}))
    target = {'engine': 'godot', 'required_real_clients': 3}
    assert runner.completed_score(tmp_path, target) is None
    with pytest.raises(RuntimeError, match='required isolated client count'):
        runner.ensure_retry_safe(tmp_path, target)


@pytest.mark.parametrize('engine', ['godot', 'unity3d'])
def test_dual_completion_rechecks_native_evidence(tmp_path, monkeypatch, engine):
    import json
    from pipeline.eval.stage1 import dual_client, dual_client_unity
    receipt = tmp_path / 'pair' / 'pair_receipt.json'
    receipt.parent.mkdir()
    receipt.write_text(json.dumps({'qualified': True, 'required_real_clients': 2}))
    score = {**SCORE, 'required_real_clients': 2, 'pair_evidence_receipt': 'pair/pair_receipt.json',
             'pair_evidence_sha256': runner.sha256(receipt)}
    (tmp_path / 'playable_score.json').write_text(json.dumps(score))
    target = {'engine': engine, 'required_real_clients': 2, 'project': str(tmp_path / 'original')}
    module, function = ((dual_client, 'verify_pair') if engine == 'godot' else (dual_client_unity, 'verify_receipt'))
    monkeypatch.setattr(module, function, lambda *a: {'qualified': True})
    assert runner.completed_score(tmp_path, target) == score
    def changed(*args):
        raise RuntimeError('raw evidence changed')
    monkeypatch.setattr(module, function, changed)
    assert runner.completed_score(tmp_path, target) is None


def test_audio_metadata_finalization_is_verified_before_other_candidates(tmp_path, monkeypatch):
    from pipeline.eval.repair import godot_duration_audio_metadata_recovery as audio
    from pipeline.eval.repair import godot_duration_metadata_recovery as metadata
    receipt = tmp_path / 'recovery/godot_duration_v1/audio_metadata_finalization_v1/replacement.json'
    receipt.parent.mkdir(parents=True)
    receipt.write_text('{}')
    previous = receipt.parent.parent / 'metadata_finalization_v1' / 'replacement.json'
    previous.parent.mkdir()
    previous.write_text('{}')
    monkeypatch.setattr(audio, 'qualified_replacement_score', lambda *a: SCORE)
    monkeypatch.setattr(metadata, 'qualified_replacement_score', lambda *a: pytest.fail('successor must qualify first'))
    assert runner.completed_score(tmp_path, SINGLE) == SCORE
    monkeypatch.setattr(audio, 'qualified_replacement_score', lambda *a: None)
    assert runner.completed_score(tmp_path, SINGLE) is None


def test_natural_entry_completion_requires_released_verified_evidence(tmp_path, monkeypatch):
    import json
    from pipeline.eval.repair import unity_natural_entry_recovery as natural
    (tmp_path / 'recovery/natural_entry_v1').mkdir(parents=True)
    (tmp_path / 'manifest.json').write_text('{"engine":"unity3d"}')
    (tmp_path / 'playable_score.json').write_text(json.dumps(SCORE))
    monkeypatch.setattr(natural, 'qualified_completion_score', lambda *a: SCORE)
    assert runner.completed_score(tmp_path, {}) == SCORE
    monkeypatch.setattr(natural, 'qualified_completion_score', lambda *a: None)
    assert runner.completed_score(tmp_path, {}) is None
    def changed(*args):
        raise RuntimeError('native/source/hold-release evidence changed')
    monkeypatch.setattr(natural, 'qualified_completion_score', changed)
    assert runner.completed_score(tmp_path, {}) is None


@pytest.mark.parametrize('target', [
    {'engine': 'unity3d', 'required_real_clients': 2},
    {'engine': 'three_js', 'required_real_clients': 1},
])
def test_natural_entry_gate_cannot_replace_another_client_or_engine_contract(tmp_path, monkeypatch, target):
    from pipeline.eval.repair import unity_natural_entry_recovery as natural
    (tmp_path / 'recovery/natural_entry_v1').mkdir(parents=True)
    monkeypatch.setattr(natural, 'qualified_completion_score', lambda *a: pytest.fail('wrong entry contract'))
    assert runner.completed_score(tmp_path, target) is None
