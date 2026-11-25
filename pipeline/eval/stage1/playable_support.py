"""Reusable recovery/qualification helpers extracted from legacy batch runners.

No batch dispatcher, target enumeration, or CLI is migrated here.
"""
from __future__ import annotations

import argparse

import os

import shutil

import sys

from pathlib import Path

from . import paths as common

from pipeline.eval.stage1 import pipeline

from pipeline.eval.stage1.paths import DELIVERY_SCHEMA, read_json, write_json, sha256

BASE = common.OUTPUTS / 'eval' / 'whitebox'

TARGETS = BASE / '_playable_retest' / 'targets.json'

SHIMS = common.OUTPUTS / 'legacy_deliveries' / 'stage1_playable'

MODEL_DIRS = {'Sol': 'gpt_sol6p1', 'Astra': 'gpt_astra6', 'Opus': 'claude_ops5p5', 'GLM': 'glm_5p3', 'Kimi': 'kimi_k3'}

MIN_FREE = 8 * 1024 ** 3

def result_dir(root: Path, t: dict) -> Path:
    variant = 'retest_dual_client_v1' if t.get('required_real_clients', 1) > 1 else 'retest'
    return root / MODEL_DIRS[t['model']] / t['game_id'] / variant

def _kimi_pair_gate(out: Path, t: dict) -> tuple[bool, dict | None]:
    """Route only the new Kimi pair protocol; malformed evidence fails closed."""
    exact = t.get('model') == 'Kimi' and (t.get('case') == 'G043' or t.get('game_id') == 'G043_airship_kitchen')
    marker = (out / 'kimi_pair_completion.json').exists()
    # The retained hold also identifies unfinished pairs for legacy completed_score(out, {}).
    hold_path = out / 'qualification_hold.json'
    try:
        hold = read_json(hold_path) if hold_path.is_file() else {}
        marker = marker or hold.get('schema') == 'stage1-kimi-pair-hold.v1'
    except (OSError, ValueError, TypeError, AttributeError):
        return True, None
    if not (exact or marker):
        return False, None
    expected = {'model': 'Kimi', 'case': 'G043', 'game_id': 'G043_airship_kitchen',
                'engine': 'godot', 'required_real_clients': 2}
    if any(key in t and t[key] != value for key, value in expected.items()):
        return True, None
    try:
        from pipeline.eval.stage1.dual_client_kimi import qualified_completion_score
        return True, qualified_completion_score(out)
    except (ImportError, OSError, ValueError, TypeError, KeyError, RuntimeError):
        return True, None

def _candidate_score(out: Path, t: dict) -> dict | None:
    applies, score = _kimi_pair_gate(out, t)
    if applies:
        return score
    if (out / 'recovery/natural_entry_v1').is_dir():
        # A released natural-entry recovery must retain its source/native/cleanup
        # proof. A rejected verifier never falls back to the canonical score.
        if target_engine(out, t) != 'unity3d' or t.get('required_real_clients', 1) != 1:
            return None
        try:
            from pipeline.eval.repair.unity_natural_entry_recovery import qualified_completion_score
            return qualified_completion_score(out)
        except (OSError, ValueError, TypeError, KeyError, RuntimeError):
            return None
    if (out / 'recovery/web_readiness_v1/replacement.json').is_file():
        from pipeline.eval.repair.web_readiness_recovery import qualified_replacement_score
        return qualified_replacement_score(out)
    if (out / 'recovery/godot_import_log_v1/replacement.json').is_file():
        from pipeline.eval.repair.godot_import_log_recovery import qualified_replacement_score
        return qualified_replacement_score(out)
    if (out / 'recovery/vite_build_only_v1/replacement.json').is_file():
        from pipeline.eval.repair.vite_build_only_recovery import qualified_replacement_score
        return qualified_replacement_score(out)
    if (out / 'qualification_hold.json').is_file():
        # A bounded recovery may qualify a separate result while preserving both
        # the original diagnostic score and its hold byte-for-byte.
        try:
            from pipeline.eval.repair.unity_imgui_transport_recovery import qualified_replacement_score
            return qualified_replacement_score(out)
        except (ImportError, OSError, ValueError, TypeError, KeyError):
            return None
    path = out / 'playable_score.json'
    if not path.is_file():
        return None
    result = read_json(path)
    if result.get('complete') is not True:
        return None
    if t.get('required_real_clients', 1) > 1:
        if t['required_real_clients'] != 2 or result.get('required_real_clients') != t['required_real_clients']:
            return None
        try:
            relative = Path(result['pair_evidence_receipt'])
            receipt_path = (out / relative).resolve()
            if relative.is_absolute() or not receipt_path.is_relative_to(out.resolve()):
                return None
            if sha256(receipt_path) != result['pair_evidence_sha256']:
                return None
            receipt = read_json(receipt_path)
            if receipt.get('qualified') is not True or receipt.get('required_real_clients') != 2:
                return None
            if t.get('engine') == 'unity3d':
                from pipeline.eval.stage1.dual_client_unity import verify_receipt
                verify_receipt(out, result)
            elif t.get('engine') == 'godot':
                from pipeline.eval.stage1.dual_client import verify_pair
                if not verify_pair(receipt_path.parent, Path(t['project']))['qualified']:
                    return None
            else:
                return None
        except (OSError, ValueError, TypeError, KeyError, RuntimeError):
            return None
    return result

def target_engine(out: Path, t: dict) -> str | None:
    if t.get('engine'):
        return t['engine']
    manifest = out / 'manifest.json'
    return read_json(manifest).get('engine') if manifest.is_file() else None

def godot_window(out: Path, t: dict) -> dict | None:
    if target_engine(out, t) != 'godot' or t.get('required_real_clients', 1) > 1:
        return None
    from pipeline.eval.repair.godot_duration_recovery import qualification
    return qualification(out, bind=False)

def completed_score(out: Path, t: dict) -> dict | None:
    applies, score = _kimi_pair_gate(out, t)
    if applies:
        return score
    if target_engine(out, t) == 'godot' and t.get('required_real_clients', 1) == 1:
        if (out / 'recovery/godot_existing_window_v1/replacement.json').is_file():
            from pipeline.eval.repair.godot_existing_window_recovery import qualified_replacement_score
            return qualified_replacement_score(out)
        if (out / 'recovery/godot_duration_v1/audio_metadata_finalization_v1/replacement.json').is_file():
            from pipeline.eval.repair.godot_duration_audio_metadata_recovery import qualified_replacement_score
            return qualified_replacement_score(out)
        if (out / 'recovery/godot_duration_v1/metadata_finalization_v1/replacement.json').is_file():
            from pipeline.eval.repair.godot_duration_metadata_recovery import qualified_replacement_score
            return qualified_replacement_score(out)
        from pipeline.eval.repair.godot_duration_recovery import qualified_replacement_score
        if (out / 'recovery/godot_duration_v1/replacement.json').is_file():
            return qualified_replacement_score(out)
        if (out / 'qualification_hold.json').is_file():
            # Only the strict replacement paths above may resolve a held Godot result.
            return None
        window = godot_window(out, t)
        if not window['window_qualified']:
            # A proven failed import/start is an evaluated product failure,
            # never evidence of a successful 75-second gameplay recording.
            if window['disposition'] == 'PRODUCT_IMPORT_FAILURE':
                return window.get('evaluated_failure_score')
            return None
    return _candidate_score(out, t)

def ensure_retry_safe(out: Path, t: dict) -> None:
    if t.get('required_real_clients', 1) not in (1, 2):
        raise RuntimeError('no qualified native implementation for the required isolated client count')
    window = godot_window(out, t)
    if window and (window.get('native_count', 0) or (out / 'playable_score.json').is_file()):
        raise RuntimeError('existing Godot evidence requires bounded recovery: ' + window['disposition'])
    if (out / 'qualification_hold.json').is_file():
        raise RuntimeError('qualified recovery required; inspect qualification_hold.json before retry')

def shim(t: dict) -> Path:
    run = SHIMS / MODEL_DIRS[t['model']] / t['game_id'] / 'retest'
    run.mkdir(parents=True, exist_ok=True)
    write_json(run / 'delivery.json', {'schema': DELIVERY_SCHEMA, 'stage': 'stage1', 'game_id': t['game_id'],
                                       'model': t['model'].lower(), 'run_id': 'retest', 'engine': t['engine'],
                                       'project_root': t['project'], 'entry': t['entry'],
                                       'required_real_clients': t.get('required_real_clients', 1),
                                       'created_at': '1970-01-01T00:00:00+00:00',
                                       'generator': {'kind': 'legacy', 'agent': t['model'], 'framework_used': True},
                                       'legacy': True, 'source_of_selection': t['source']})
    from pipeline.eval.stage1.delivery import validate
    problems = validate(run)
    if problems:
        raise ValueError(f'shim delivery not admissible: {problems}')
    return run

def cleanup(out: Path) -> dict:
    """Drop the two project copies (regenerable from the read-only original); keep every recording."""
    freed = 0
    for d in (out / 'runtime' / 'project', out / 'input' / 'project'):
        if d.is_dir():
            freed += sum(f.stat().st_size for f in d.rglob('*') if f.is_file() and not f.is_symlink())
            shutil.rmtree(d)
    receipt = {'removed': ['runtime/project', 'input/project'], 'freed_bytes': freed,
               'kept': 'takes/*/record (frames, actions, logs), playable_rules.json, verdicts, model_calls'}
    write_json(out / 'cleanup.json', receipt)
    return receipt

def restore_cleaned_copies(out: Path) -> None:
    """Restore only tool-deleted copies, from the exact frozen original."""
    if not (out / 'manifest.json').is_file() or not (out / 'cleanup.json').is_file():
        return
    from pipeline.eval.stage1.prepare import IGNORE, tree_digest, tree_hashes, verify
    manifest = read_json(out / 'manifest.json')
    source = Path(manifest['project_source'])
    missing = [out / part for part in ('input/project', 'runtime/project') if not (out / part).exists()]
    if not missing:
        return
    if tree_digest(tree_hashes(source)) != manifest['project_digest']:
        raise ValueError('original changed; cannot restore cleaned evaluation copies')
    restored = []
    for dest in missing:
        shutil.copytree(source, dest, ignore=IGNORE)
        if tree_digest(tree_hashes(dest)) != manifest['snapshot_digest']:
            raise ValueError(f'restored snapshot does not match frozen source: {dest}')
        restored.append(str(dest.relative_to(out)))
    verify(out)
    receipts = out / 'recovery'
    receipts.mkdir(exist_ok=True)
    index = len(list(receipts.glob('restore_*.json'))) + 1
    write_json(receipts / f'restore_{index:03d}.json', {
        'restored': restored, 'project_digest': manifest['project_digest'],
        'parent_status': read_json(out / 'status.json') if (out / 'status.json').is_file() else None,
        'parent_cleanup': read_json(out / 'cleanup.json'),
    })
