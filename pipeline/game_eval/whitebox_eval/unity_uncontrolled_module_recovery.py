"""Reviewed phantom TextRendering package pin; Editor module remains unchanged.

Only an isolated manifest may change, after a failed native package resolution
and exact Editor module metadata prove that this API is not package-controlled.
This is not permission to remove arbitrary missing dependencies.
"""
from pathlib import Path
import json
import re

from .protocol import dump, sha

PACKAGE = 'com.unity.modules.textrendering'
MODULE = 'TextRendering'
SOURCE = 'Packages/manifest.json'
ERROR = PACKAGE + ': Package [' + PACKAGE + '@1.0.0] cannot be found'


def checked(root, relative, digest):
    root = Path(root).resolve()
    rel = Path(relative)
    path = root/rel
    if (rel.is_absolute() or '..' in rel.parts or not path.is_file()
            or not path.resolve().is_relative_to(root)
            or any(p.is_symlink() for p in (path, *path.parents)
                   if p != root and root in p.parents)
            or sha(path) != digest):
        raise ValueError('Uncontrolled module source missing, escaped, or changed')
    return path


def editor_sources(entry, selected_editor):
    editor = Path(selected_editor)
    if editor.is_symlink() or str(editor.resolve()) != entry.get('selected_editor'):
        raise ValueError('Selected Editor differs from uncontrolled module review')
    contents = editor.parent.parent
    checked(contents, 'MacOS/'+editor.name, entry['editor_sha256'])
    modules = checked(contents, 'Resources/modules.asset', entry['editor_modules_sha256'])
    assembly = checked(contents, 'Managed/UnityEngine/UnityEngine.TextRenderingModule.dll',
                       entry['editor_assembly_sha256'])
    # Unlike Audio/Physics, this Editor explicitly does not let a package pin
    # control TextRendering. Its native assembly and all API callers stay intact.
    text = modules.read_text()
    blocks = re.findall(r'(?m)^  - name: TextRendering\r?\n(?:(?!  - name:)[\s\S])*?(?=^  - name:|\Z)', text)
    if (len(blocks) != 1
            or len(re.findall(r'(?m)^    controlledByBuiltinPackage: 0\s*$', blocks[0])) != 1
            or re.search(r'(?m)^    controlledByBuiltinPackage: (?!0\s*$)', blocks[0])):
        raise ValueError('Editor does not prove TextRendering is package-uncontrolled')
    builtin = contents/'Resources/PackageManager/BuiltInPackages'
    if not builtin.is_dir() or (builtin/PACKAGE).exists() or (builtin/PACKAGE).is_symlink():
        raise ValueError('Refuse removal of an existing built-in package')
    return {'editor': str(editor), 'editor_sha256': sha(editor),
            'module_definition': str(modules), 'module_definition_sha256': sha(modules),
            'module_block_utf8': blocks[0],
            'module_block_first_physical_line': text[:text.index(blocks[0])].count('\n')+1,
            'assembly': str(assembly), 'assembly_sha256': sha(assembly),
            'builtin_package_absent': str(builtin/PACKAGE)}


def review(entry):
    if (entry.get('source') != SOURCE or entry.get('package') != PACKAGE
            or entry.get('package_version') != '1.0.0' or entry.get('module') != MODULE):
        raise ValueError('Only the reviewed phantom TextRendering 1.0.0 pin is supported')
    path = checked(entry['project'], SOURCE, entry['source_sha256'])
    data = json.loads(path.read_text())
    dependencies = data.get('dependencies')
    if not isinstance(dependencies, dict) or dependencies.get(PACKAGE) != '1.0.0':
        raise ValueError('Reviewed phantom package pin is missing or changed')
    # Embedded/locked package implementations cannot be silently discarded.
    root = Path(entry['project'])
    if (root/'Packages'/PACKAGE).exists() or (root/'Packages'/PACKAGE).is_symlink():
        raise ValueError('Refuse removal of an embedded package')
    lock = root/'Packages/packages-lock.json'
    expected = entry.get('package_lock_sha256')
    if lock.exists():
        if not expected or lock.is_symlink() or sha(lock) != expected:
            raise ValueError('Authored package lock changed or lacks binding')
        locked = json.loads(lock.read_text()).get('dependencies', {})
        if PACKAGE in locked:
            raise ValueError('Refuse removal of a resolved package implementation')
    elif expected is not None:
        raise ValueError('Authored package lock disappeared')
    editor_sources(entry, entry['selected_editor'])
    return True


def review_failure(entry, errors):
    if errors:
        raise ValueError('Unexpected compiler errors require a separate review')
    failed = json.loads(Path(entry['prior_receipt']).read_text()).get('execution', {})
    if (failed.get('owned_process_exited') is not True
            or failed.get('exit_code') in (None, 0) or failed.get('timed_out') is not False
            or not failed.get('command') or failed['command'][0] != entry['selected_editor']):
        raise ValueError('Phantom pin requires a completed matching Editor package failure')
    lines = Path(entry['compiler_log']).read_text(errors='replace').splitlines()
    hits = [(i+1, line.strip()) for i, line in enumerate(lines) if 'Package [' in line and 'cannot be found' in line]
    if hits != [(entry.get('package_error_physical_line'), ERROR)]:
        raise ValueError('Package failure must bind exactly the reviewed missing pin and line')
    if not any(line.strip() == 'Project has invalid dependencies:' for line in lines):
        raise ValueError('Native package resolver failure context missing')
    return True


def apply_pin(entry, candidate, sandbox):
    review(entry)
    proof = editor_sources(entry, candidate['selected_editor'])
    sandbox = Path(sandbox).resolve()
    if sandbox.is_relative_to(Path(entry['project']).resolve()):
        raise ValueError('Author delivery must remain read-only')
    path = checked(sandbox, SOURCE, entry['source_sha256'])
    if (sandbox/'Packages'/PACKAGE).exists() or (sandbox/'Packages'/PACKAGE).is_symlink():
        raise ValueError('Isolated package implementation exists')
    lock = sandbox/'Packages/packages-lock.json'
    expected_lock = entry.get('package_lock_sha256')
    if expected_lock is not None:
        checked(sandbox, 'Packages/packages-lock.json', expected_lock)
    elif lock.exists() or lock.is_symlink():
        raise ValueError('Unreviewed isolated package lock')
    before = path.read_bytes()
    data = json.loads(before)
    after = json.loads(before)
    del after['dependencies'][PACKAGE]
    # Save full before/after and an explicit inverse; every other value is exact.
    inverse = json.loads(json.dumps(after))
    inverse['dependencies'][PACKAGE] = '1.0.0'
    if inverse != data:
        raise ValueError('Manifest inverse equivalence failed')
    dump(path, after)
    return {'removed_phantom_pin': {'name': PACKAGE, 'version': '1.0.0'},
            'manifest_before_utf8': before.decode('utf-8'),
            'manifest_after_utf8': path.read_text(),
            'inverse_json_equal': True, 'all_other_manifest_values_equal': True,
            'editor_module_proof': proof, 'gameplay_changes': [],
            'module_assembly_unchanged': sha(Path(proof['assembly'])) == proof['assembly_sha256'],
            'native_admission_required': True, 'native_adapter_unchanged': True}
