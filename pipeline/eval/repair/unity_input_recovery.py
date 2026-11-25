"""Bounded recovery of the harness-added incompatible Input System import.

No recorded take can enter this path. Preserve failed import artifacts, accepted
plan and input migration; change only the harness-added package in the eval copy.
"""
from __future__ import annotations
import fcntl
from pathlib import Path
import shutil

from ..stage1 import prepare, unity_input
from ..stage1.llm import HarnessError
from ..stage1.paths import read_json, write_json, sha256

VERSION = 'stage1-unity-input-import-recovery.v1'
OLD_PACKAGE = 'com.unity.inputsystem@1.14.0'
ALLOWED_NATIVE = {'_scenario.json', 'capture_schedule.json', 'editor_cleanup.json',
                  'editor_failure.json', 'endpoint_settle_guards.json'}


def recover(out: Path) -> dict:
    out = Path(out).resolve()
    status = read_json(out / 'status.json')
    if status.get('state') != 'HARNESS_ERROR' or status.get('step') != 'record_t1':
        raise HarnessError('not a terminal first-import harness failure')
    record = out / 'takes/1/record'
    archive = out / 'takes/1/input_import_recovery_v1'
    with (record / '.postprocess.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if archive.exists():
            raise HarnessError('input import recovery already attempted; inspect preserved lineage')
        manifest = prepare.verify(out)
        if manifest['engine'] != 'unity3d':
            raise HarnessError('recovery requires Unity')
        source = Path(manifest['project_source'])
        if prepare.tree_digest(prepare.tree_hashes(source)) != manifest['project_digest']:
            raise HarnessError('original delivery changed')
        if (out / 'playable_score.json').exists() or (record / 'record_result.json').exists():
            raise HarnessError('cannot recover an existing scored or recorded take')
        log = (record / 'import.log').read_text(errors='replace')
        if OLD_PACKAGE not in log or 'INavigationEventData' not in log or 'error CS0246' not in log:
            raise HarnessError('not the known injected package compilation error')
        result = read_json(record / 'import_result.json')
        if result.get('exit_code') != 1 or result.get('timeout'):
            raise HarnessError('import did not finish with the known compiler failure')
        native = record / 'native'
        if not native.is_dir() or any(p.is_dir() or p.name not in ALLOWED_NATIVE for p in native.iterdir()):
            raise HarnessError('native gameplay or unfamiliar artifacts exist; recovery forbidden')
        cleanup = read_json(native / 'editor_cleanup.json')
        if any(cleanup.get(k) is not True for k in ('ok', 'process_exit_verified', 'group_exit_verified', 'detached_exit_verified')):
            raise HarnessError('owned editor cleanup is not verified')
        project = out / 'runtime/project'
        original_packages = read_json(out / 'input/project/Packages/manifest.json')
        if 'com.unity.inputsystem' in original_packages.get('dependencies', {}):
            raise HarnessError('authored Input System dependency must not be replaced')
        receipt_path = out / 'runtime/unity_input_migration.json'
        receipt = read_json(receipt_path)
        old_cache = receipt.get('input_system_package', '')
        if not receipt.get('migrated') or not old_cache.endswith('/' + OLD_PACKAGE):
            raise HarnessError('failure is not bound to the old harness migration')
        package_manifest = project / 'Packages/manifest.json'
        packages = read_json(package_manifest)
        if packages.get('dependencies', {}).get('com.unity.inputsystem') != 'file:' + old_cache:
            raise HarnessError('eval package binding differs from failed migration')
        for change in receipt['changes']:
            if sha256(project / change['path']) != change['after_sha256']:
                raise HarnessError('migrated source changed after failed import')
        cache = unity_input.package_root()
        archive.mkdir()
        files = {str(p.relative_to(record)): sha256(p) for p in record.rglob('*') if p.is_file() and p.name != '.postprocess.lock'}
        lineage = {'version': VERSION, 'state': 'PREPARING', 'parent_status': status,
                   'source_digest': manifest['project_digest'], 'plan_sha256': sha256(out / 'takes/1/plan.json'),
                   'prior_artifacts': files, 'native_recordings_reused': 0, 'prior_gameplay_recordings': 0,
                   'old_package': old_cache, 'new_package': str(cache),
                   'production': {p.name: sha256(p) for p in (Path(__file__), Path(unity_input.__file__))}}
        write_json(archive / 'recovery.json', lineage)
        shutil.copy2(receipt_path, archive / 'old_migration.json')
        shutil.copy2(package_manifest, archive / 'old_manifest.json')
        lockfile = project / 'Packages/packages-lock.json'
        if lockfile.exists():
            shutil.copy2(lockfile, archive / 'old_packages-lock.json')
        old_record = archive / 'record'
        old_record.mkdir()
        for p in list(record.iterdir()):
            if p.name != '.postprocess.lock':
                shutil.move(str(p), old_record / p.name)
        packages['dependencies']['com.unity.inputsystem'] = 'file:' + str(cache)
        write_json(package_manifest, packages)
        receipt.update(version=unity_input.VERSION, input_system_package=str(cache),
                       input_system_package_origin='harness_added', input_system_package_version=unity_input.PACKAGE[1],
                       input_system_package_manifest_sha256=sha256(cache / 'package.json'),
                       parent_migration_sha256=sha256(archive / 'old_migration.json'),
                       recovery_receipt=str(archive / 'recovery.json'))
        write_json(receipt_path, receipt)
        lineage['state'] = 'READY_FOR_NATIVE_IMPORT'
        write_json(archive / 'recovery.json', lineage)
        return lineage


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('out', type=Path)
    print(recover(parser.parse_args().out))
