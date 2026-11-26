"""Resume one pre-gameplay failure caused by the injected Audio observer.

Preserve the complete failed import/record output and accepted plan. The normal
Stage1 recorder then binds the selected editor's built-in Audio module in the
isolated runtime project. No recorded gameplay may enter this recovery.
"""
from __future__ import annotations

import fcntl
import json
from pathlib import Path
import shutil

from pipeline.eval.whitebox.core import prepare
from pipeline.eval.whitebox.core.llm import HarnessError
from pipeline.eval.whitebox.core.paths import read_json, write_json, sha256

VERSION = 'stage1-unity-audio-import-recovery.v1'
ALLOWED_NATIVE = {'_scenario.json', 'capture_schedule.json', 'editor_cleanup.json',
                  'editor_failure.json', 'endpoint_settle_guards.json'}
ERROR = "GameFactory3AAudioTap.cs(36,40): error CS0103: The name 'AudioSettings' does not exist in the current context"


def recover(out: Path) -> dict:
    out = Path(out).resolve()
    status = read_json(out / 'status.json')
    if status.get('state') != 'HARNESS_ERROR' or status.get('step') != 'record_t1':
        raise HarnessError('not a terminal first-take observer compilation failure')
    record = out / 'takes/1/record'
    archive = out / 'takes/1/audio_import_recovery_v1'
    with (record / '.postprocess.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if archive.exists():
            raise HarnessError('Audio recovery already attempted; inspect preserved lineage')
        manifest = prepare.verify(out)
        if manifest['engine'] != 'unity3d':
            raise HarnessError('Audio recovery requires Unity')
        source = Path(manifest['project_source'])
        if prepare.tree_digest(prepare.tree_hashes(source)) != manifest['project_digest']:
            raise HarnessError('original delivery changed')
        if (out / 'playable_score.json').exists() or (record / 'record_result.json').exists():
            raise HarnessError('cannot recover an existing scored or recorded take')
        result = read_json(record / 'adapter_result.json')
        if result.get('ok') is not False or not any(
                'injected Unity evaluation driver/recorder failed compilation' in e
                for e in result.get('errors', [])):
            raise HarnessError('not an injected observer compilation failure')
        failure = read_json(record / 'native/editor_failure.json')
        if ERROR not in json.dumps(failure):
            raise HarnessError('not the known missing Audio module compilation error')
        native = record / 'native'
        if any(p.is_dir() or p.name not in ALLOWED_NATIVE for p in native.iterdir()):
            raise HarnessError('native gameplay or unfamiliar artifacts exist; recovery forbidden')
        cleanup = read_json(native / 'editor_cleanup.json')
        if any(cleanup.get(k) is not True for k in
               ('ok', 'process_exit_verified', 'group_exit_verified', 'detached_exit_verified')):
            raise HarnessError('owned editor cleanup is not verified')
        project = out / 'runtime/project'
        choice = read_json(record / 'unity_editor.json')
        editor = Path(choice['editor']['binary']).resolve()
        if Path(cleanup['command'][0]).resolve() != editor:
            raise HarnessError('cleanup is bound to a different editor')
        command = cleanup['command']
        if Path(command[command.index('-projectPath') + 1]).resolve() != project.resolve():
            raise HarnessError('cleanup is bound to a different project')
        package_manifest = project / 'Packages/manifest.json'
        packages = read_json(package_manifest)
        original_packages = read_json(out / 'input/project/Packages/manifest.json')
        audio = 'com.unity.modules.audio'
        if audio in packages['dependencies'] or audio in original_packages['dependencies']:
            raise HarnessError('Audio module is already declared; this recovery is inapplicable')
        builtin = editor.parent.parent / 'Resources/PackageManager/BuiltInPackages' / audio / 'package.json'
        definition = read_json(builtin)
        if (definition.get('name'), definition.get('version'), definition.get('type')) != (audio, '1.0.0', 'module'):
            raise HarnessError('selected editor built-in Audio package is not bound')
        migration = read_json(out / 'runtime/unity_input_migration.json')
        for change in migration.get('changes', []):
            if sha256(project / change['path']) != change['after_sha256']:
                raise HarnessError('migrated source changed after failed import')
        plan = out / 'takes/1/plan.json'
        if not plan.is_file():
            raise HarnessError('accepted plan missing')
        files = {str(p.relative_to(record)): sha256(p) for p in record.rglob('*')
                 if p.is_file() and p.name != '.postprocess.lock'}
        archive.mkdir()
        lineage = {'version': VERSION, 'state': 'PREPARING', 'parent_status': status,
                   'source_digest': manifest['project_digest'], 'plan_sha256': sha256(plan),
                   'prior_artifacts': files, 'prior_gameplay_recordings': 0,
                   'builtin_package': str(builtin), 'builtin_package_sha256': sha256(builtin),
                   'editor': str(editor), 'production_sha256': sha256(Path(__file__))}
        write_json(archive / 'recovery.json', lineage)
        shutil.copy2(out / 'status.json', archive / 'parent_status.json')
        shutil.copy2(package_manifest, archive / 'old_manifest.json')
        shutil.copy2(out / 'runtime/unity_input_migration.json', archive / 'input_migration.json')
        old_record = archive / 'record'
        old_record.mkdir()
        for p in list(record.iterdir()):
            if p.name != '.postprocess.lock':
                shutil.move(str(p), old_record / p.name)
        if any(sha256(old_record / rel) != digest for rel, digest in files.items()):
            raise HarnessError('failed artifact preservation mismatch')
        lineage['state'] = 'READY_FOR_NATIVE_IMPORT'
        write_json(archive / 'recovery.json', lineage)
        return lineage


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('out', type=Path)
    print(recover(parser.parse_args().out))
