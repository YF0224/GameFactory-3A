"""Offline correction of ANSI-hidden Godot import errors; never records or overwrites evidence."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import fcntl
from pathlib import Path

from ..stage1 import playable_rules, prepare
from ..stage1.native_log import godot_product_errors
from ..stage1.paths import read_json, sha256, write_json

RELATIVE = Path('recovery/godot_import_log_v1')


def require(value, message):
    if not value:
        raise ValueError(message)


def missed_errors(out):
    found = []
    for result in sorted((out / 'takes').glob('*/record/import_result.json')):
        log = result.with_name('import.log')
        data = read_json(result)
        if (not data.get('timeout') and not data.get('product_errors') and log.is_file()
                and godot_product_errors(log.read_text(errors='replace'))):
            found.append(str(log.relative_to(out)))
    return found


def binding(out):
    paths = [out / n for n in ('manifest.json', 'status.json', 'playable_score.json',
                               'playable_rules.json', 'verdicts_playable_rules.json')]
    paths.extend(p for p in (out / 'takes').rglob('*')
                 if p.is_file() and p.name != '.postprocess.lock')
    return {str(p.relative_to(out)): sha256(p) for p in paths if p.is_file()}


def correct(out):
    out = Path(out).resolve()
    manifest = read_json(out / 'manifest.json')
    require(manifest['engine'] == 'godot', 'Godot only')
    if (out / RELATIVE / 'replacement.json').is_file():
        result = qualified_replacement_score(out)
        require(result is not None, 'existing correction does not verify')
        return result
    require(not (out / 'qualification_hold.json').exists(), 'unrelated qualification hold')
    old = read_json(out / 'playable_score.json')
    require(old.get('complete') is True, 'requires complete existing native evidence')
    require(missed_errors(out), 'no ANSI-hidden import error')
    require(read_json(out / 'status.json').get('state') == 'done', 'parent still active or failed')
    source = Path(manifest['project_source'])
    require(prepare.tree_digest(prepare.tree_hashes(source)) == manifest['project_digest'], 'original source drift')
    with ExitStack() as stack:
        for record in sorted((out / 'takes').glob('*/record')):
            handle = stack.enter_context((record / '.postprocess.lock').open('a'))
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        target = out / RELATIVE
        require(not target.exists(), 'partial correction retained; inspect before continuation')
        target.mkdir(parents=True)
        before = binding(out)
        write_json(target / 'parent_binding.json', before)
        history = []
        for row in old['takes']:
            take = row['take']
            verdicts = playable_rules.evaluate(out, manifest, take, report_dir=target / f'take{take}')
            checks = {i: verdicts.get(i, {}).get('status', 'HARNESS_ERROR') for i in playable_rules.IDS}
            require('HARNESS_ERROR' not in checks.values(), 'incomplete evidence')
            for ident in ('play.launch', 'play.operate'):
                require(checks[ident] == row['checks'][ident], 'unrelated verdict drift')
            history.append({'take': take, 'checks': checks})
        require(checks['play.import'] == 'FAIL', 'expected diagnosed import error')
        result = {**old, 'checks': checks, 'takes': history,
                  'playable': round(100 * sum(v == 'PASS' for v in checks.values()) / 3, 2),
                  'import_parser_revision': 'ansi_terminal_normalization.v1'}
        write_json(target / 'playable_score.json', result)
        require(binding(out) == before, 'parent evidence changed during evaluation')
        producer = {}
        for name in ('native_log.py', 'playable_rules.py', 'godot_import_log_recovery.py'):
            src = Path(__file__).with_name(name)               # this repair, or its stage1 dependency
            if not src.is_file():
                src = Path(__file__).resolve().parents[1] / 'stage1' / name
            dest = target / 'producer' / name
            dest.parent.mkdir(exist_ok=True)
            dest.write_bytes(src.read_bytes())
            producer[name] = sha256(dest)
        write_json(target / 'replacement.json', {
            'version': 'stage1-godot-import-log-correction.v1', 'qualified': True,
            'parent_binding_sha256': sha256(target / 'parent_binding.json'),
            'score_sha256': sha256(target / 'playable_score.json'),
            'producer': producer, 'missed_error_logs': missed_errors(out),
            'native_recordings_added': 0, 'model_calls_added': 0,
            'original_project_digest': manifest['project_digest']})
        return result


def qualified_replacement_score(out):
    out = Path(out).resolve()
    try:
        target = out / RELATIVE
        receipt = read_json(target / 'replacement.json')
        require(receipt['version'] == 'stage1-godot-import-log-correction.v1'
                and receipt['qualified'] is True, 'invalid correction receipt')
        require(sha256(target / 'parent_binding.json') == receipt['parent_binding_sha256'], 'binding drift')
        for relative, digest in read_json(target / 'parent_binding.json').items():
            p = (out / relative).resolve()
            require(p.is_relative_to(out) and sha256(p) == digest, 'parent evidence drift')
        for name, digest in receipt['producer'].items():
            p = (target / 'producer' / name).resolve()
            require(p.is_relative_to(target / 'producer') and sha256(p) == digest, 'producer archive drift')
        require(sha256(target / 'playable_score.json') == receipt['score_sha256'], 'corrected score drift')
        result = read_json(target / 'playable_score.json')
        require(result['complete'] is True and result['checks']['play.import'] == 'FAIL', 'invalid correction')
        return result
    except (OSError, ValueError, TypeError, KeyError):
        return None


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('out', type=Path)
    print(correct(parser.parse_args().out))
