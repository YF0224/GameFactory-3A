"""Bind built-in dependencies needed by injected observers in isolated projects."""
from __future__ import annotations

import json
from pathlib import Path

from .protocol import dump, sha

VERSION = 'whitebox-observer-runtime-dependencies.v1'
AUDIO = 'com.unity.modules.audio'


def prepare(project, editor, receipt):
    """Enable the editor's own Audio module without touching authored gameplay.

    The recorder injects GameFactory3AAudioTap even when the delivered project
    has no audio. Native admission must compile that dependency before planning.
    Only a missing built-in module is added; existing pins are never replaced.
    """
    project, editor, receipt = Path(project).resolve(), Path(editor).resolve(), Path(receipt)
    manifest = project/'Packages/manifest.json'
    data = json.loads(manifest.read_text())
    dependencies = data.get('dependencies')
    if not isinstance(dependencies, dict):
        raise ValueError('Unity package manifest must contain dependencies')
    package = editor.parent.parent/'Resources/PackageManager/BuiltInPackages'/AUDIO/'package.json'
    definition = json.loads(package.read_text())
    if (definition.get('name') != AUDIO or definition.get('version') != '1.0.0'
            or definition.get('type') != 'module'):
        raise ValueError('Selected editor does not bind the expected built-in Audio module')
    before = sha(manifest)
    changed = AUDIO not in dependencies
    if changed:
        dependencies[AUDIO] = definition['version']
        dump(manifest, data)
    result = {'version': VERSION, 'project': str(project), 'editor': str(editor),
              'scope': 'isolated native-admission snapshot; original delivery unchanged',
              'manifest': str(manifest), 'before_sha256': before,
              'after_sha256': sha(manifest), 'gameplay_changes': [],
              'changes': ([{'package': AUDIO, 'before': None, 'after': '1.0.0',
                           'reason': 'Injected GameFactory3AAudioTap requires UnityEngine.AudioSettings'}]
                          if changed else []),
              'builtin_package': str(package), 'builtin_package_sha256': sha(package)}
    dump(receipt, result)
    return result


def audit_binding(root):
    """Follow the frozen admission receipt; old admissions without this stay valid."""
    root = Path(root)
    meta = json.loads((root/'input_manifest.json').read_text())
    admission = meta['entry'].get('native_open_admission')
    if not admission:
        return {}
    native_path = Path(admission['receipt'])
    if sha(native_path) != admission['sha256']:
        raise ValueError('Observer dependency admission receipt changed')
    native = json.loads(native_path.read_text())
    binding = native.get('observer_runtime_dependencies')
    if binding is None:
        return {}
    receipt = Path(binding['path'])
    if (sha(native_path) != admission['sha256']
            or receipt.resolve() != (native_path.parent/'observer_runtime_dependencies.json').resolve()
            or sha(receipt) != binding['sha256']):
        raise ValueError('Observer dependency admission binding changed')
    value = json.loads(receipt.read_text())
    if (value.get('version') != VERSION or value.get('gameplay_changes') != []
            or Path(value['project']).resolve() != Path(native['project']).resolve()
            or Path(value['editor']).resolve() != Path(native['editor']).resolve()
            or value['after_sha256'] != meta['snapshot_hashes'].get('Packages/manifest.json')):
        raise ValueError('Observer dependency receipt does not bind frozen input')
    expected_changes = [{'package': AUDIO, 'before': None, 'after': '1.0.0',
                         'reason': 'Injected GameFactory3AAudioTap requires UnityEngine.AudioSettings'}]
    if value['changes'] not in ([], expected_changes):
        raise ValueError('Unexpected observer dependency mutation')
    package = Path(value['builtin_package'])
    expected = Path(value['editor']).parent.parent/'Resources/PackageManager/BuiltInPackages'/AUDIO/'package.json'
    if package.resolve() != expected.resolve() or sha(package) != value['builtin_package_sha256']:
        raise ValueError('Selected editor built-in module changed')
    return {str(native_path): sha(native_path), str(receipt): sha(receipt), str(package): sha(package)}
