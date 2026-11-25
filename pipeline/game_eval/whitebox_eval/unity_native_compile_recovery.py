"""Evidence-bound compilation repairs in isolated native-admission snapshots."""
from pathlib import Path
import re
import time

from .protocol import dump, sha

VERSION = 'whitebox-unity-native-compile-recovery.v1'
POLICY = 'unity_native_compile_recovery_policy.json'
BUILTIN_NAMES = {'ScreenCapture': ('com.unity.modules.screencapture', 'CaptureScreenshot')}
BUILTIN_TYPES = {
    'VideoPlayer': ('com.unity.modules.video', 'UnityEngine.VideoModule'),
    'ParticleSystem': ('com.unity.modules.particlesystem', 'UnityEngine.ParticleSystemModule'),
}


def reviewed_builtin_errors(entry, errors):
    """Require the exact reviewed missing-module errors and authored source bytes."""
    modules = entry.get('modules')
    if (not isinstance(modules, list) or not modules or any(not isinstance(m, str) for m in modules) or len(set(modules)) != len(modules)
            or any(m not in {v[0] for v in (*BUILTIN_TYPES.values(), *BUILTIN_NAMES.values())} for m in modules)):
        raise ValueError('Unknown or repeated reviewed built-in module')
    bindings = entry.get('compiler_sources', {})
    if not isinstance(bindings, dict) or not bindings or any(not isinstance(k, str) or not isinstance(v, str) for k, v in bindings.items()):
        raise ValueError('Missing authored compiler source bindings')
    seen_sources, seen_modules = set(), set()
    for line in errors:
        match = re.match(r"^(Assets/[^:\n]+\.cs)\(\d+,\d+\): error CS1069: The type name '([^']+)'", line)
        if match and match[2] in BUILTIN_TYPES:
            source, kind = match.groups()
            module, assembly = BUILTIN_TYPES[kind]
            if "assembly '" + assembly + "," not in line:
                raise ValueError('Compiler error does not bind reviewed module assembly')
        else:
            missing = re.fullmatch(r"(Assets/[^:\n]+\.cs)\((\d+),(\d+)\): error CS0103: The name '([^']+)' does not exist in the current context", line)
            if not missing or missing[4] not in BUILTIN_NAMES:
                raise ValueError('Unexpected compiler error in built-in module review')
            source, row, column, kind = missing.groups()
            module, method = BUILTIN_NAMES[kind]
            origin = Path(entry['project']).resolve()
            authored = origin/source
            if (source not in bindings or authored.is_symlink()
                    or not authored.resolve().is_relative_to(origin/'Assets') or sha(authored) != bindings[source]):
                raise ValueError('Missing built-in name source changed or escaped')
            text = authored.read_text(); lines = text.splitlines()
            if (not 1 <= int(row) <= len(lines) or int(column) < 1
                    or not lines[int(row)-1][int(column)-1:].startswith(kind+'.'+method+'(')
                    or not re.search(r'\busing UnityEngine\s*;', text)):
                raise ValueError('Missing built-in name must bind the exact authored Unity API call')
        if module not in modules or source not in bindings:
            raise ValueError('Compiler error does not bind reviewed module/source')
        seen_sources.add(source); seen_modules.add(module)
    if not errors or set(modules) != seen_modules or set(bindings) != seen_sources:
        raise ValueError('Reviewed built-ins must exactly cover actual compiler failures')
    origin = Path(entry['project']).resolve()
    for relative, digest in bindings.items():
        source = origin/relative
        if source.is_symlink() or not source.resolve().is_relative_to(origin/'Assets') or sha(source) != digest:
            raise ValueError('Reviewed compiler source changed or escaped')
    return True


def load(root, ident, project):
    from .batch import read
    policy = Path(root) / POLICY
    if not policy.is_file():
        return None
    value = read(policy)
    if value.get('version') != VERSION:
        raise ValueError('Unknown native compile recovery policy')
    entry = value.get('entries', {}).get(ident)
    if entry is None:
        return None
    if entry.get('reviewed') is not True or Path(entry['project']).resolve() != Path(project).resolve():
        raise ValueError('Native compile recovery source review mismatch')
    source = Path(entry['source'])
    if source.is_absolute() or '..' in source.parts:
        raise ValueError('Unsafe native compile recovery source')
    original = Path(project) / source
    if original.is_symlink() or not original.resolve().is_relative_to(Path(project).resolve()):
        raise ValueError('Native compile recovery source escaped project')
    if sha(original) != entry['source_sha256']:
        raise ValueError('Native compile recovery original SHA changed')
    operation = entry.get('operation')
    if operation == 'rename_loop_local':
        if source.parts[:1] != ('Assets',) or source.suffix != '.cs':
            raise ValueError('Loop rename requires a C# asset')
        # Restrict to the reviewed declaration and one-expression for-body.
        old, new, span = entry['old_name'], entry['new_name'], entry['span']
        if not all(re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', x) for x in (old, new)) or old == new:
            raise ValueError('Invalid loop local rename')
        if (not span.startswith('for(int ' + old + '=') or '\n' in span
                or '{' in span or '}' in span or span.count(';') != 3):
            raise ValueError('Only a single-expression for-loop may be renamed')
        if original.read_text().count(span) != 1:
            raise ValueError('Reviewed loop must occur exactly once')
    elif operation == 'enable_builtin_animation':
        if source.as_posix() != 'Packages/manifest.json':
            raise ValueError('Animation repair requires the package manifest')
        if 'com.unity.modules.animation' in read(original).get('dependencies', {}):
            raise ValueError('Animation module is already declared')
    elif operation == 'remove_reviewed_uncontrolled_module_pin':
        from .unity_uncontrolled_module_recovery import review
        review(entry)
    elif operation == 'enable_reviewed_builtin_modules':
        if source.as_posix() != 'Packages/manifest.json':
            raise ValueError('Built-in module repair requires the package manifest')
        dependencies = read(original).get('dependencies')
        if not isinstance(dependencies, dict):
            raise ValueError('Unity package manifest must contain dependencies')
        modules = entry.get('modules')
        if not isinstance(modules, list) or not modules or any(not isinstance(m, str) for m in modules):
            raise ValueError('Invalid reviewed built-in modules')
        if any(module in dependencies for module in modules):
            raise ValueError('Reviewed module already declared; preserve existing pins')
    elif operation == 'add_reviewed_asmdef_reference':
        if source.parts[:1] != ('Assets',) or source.suffix != '.asmdef':
            raise ValueError('Direct assembly reference repair requires an Assets assembly definition')
    elif operation == 'align_reviewed_shadergraph_access':
        if source.as_posix() != 'Packages/manifest.json':
            raise ValueError('ShaderGraph compatibility requires exact manifest binding')
    elif operation == 'exclude_reviewed_compilation_units':
        from .unity_compilation_unit_compatibility import review
        review(entry)
    else:
        raise ValueError('Unsupported native compile recovery operation')
    for key in ('prior_receipt', 'compiler_log'):
        if sha(Path(entry[key])) != entry[key + '_sha256']:
            raise ValueError('Native compile recovery failure evidence changed')
    failed = read(Path(entry['prior_receipt'])).get('execution', {})
    if failed.get('owned_process_exited') is not True or failed.get('exit_code') == 0:
        raise ValueError('Native compile recovery lacks a completed failed native execution')
    errors = {line.strip() for line in Path(entry['compiler_log']).read_text(errors='replace').splitlines()
              if 'error CS' in line}
    if operation == 'remove_reviewed_uncontrolled_module_pin':
        from .unity_uncontrolled_module_recovery import review_failure
        review_failure(entry, errors)
        return dict(entry, ident=ident, policy_path=str(policy.resolve()), policy_sha256=sha(policy))
    if operation == 'align_reviewed_shadergraph_access':
        from .unity_shadergraph_access_recovery import review
        review(entry, errors)
        return dict(entry, ident=ident, policy_path=str(policy.resolve()), policy_sha256=sha(policy))
    if operation == 'add_reviewed_asmdef_reference':
        from .unity_asmdef_reference_recovery import review
        review(entry, errors)
        return dict(entry, ident=ident, policy_path=str(policy.resolve()), policy_sha256=sha(policy))
    if operation == 'enable_reviewed_builtin_modules':
        additional = entry.get('additional_compiler_failures', [])
        if not isinstance(additional, list):
            raise ValueError('Invalid additional native compiler failures')
        seen = {entry['prior_receipt']}
        for failure in additional:
            if not isinstance(failure, dict) or failure.get('prior_receipt') in seen:
                raise ValueError('Repeated or invalid additional native compiler failure')
            seen.add(failure['prior_receipt'])
            for key in ('prior_receipt', 'compiler_log'):
                if sha(Path(failure[key])) != failure[key + '_sha256']:
                    raise ValueError('Additional native compiler failure evidence changed')
            execution = read(Path(failure['prior_receipt'])).get('execution', {})
            if execution.get('owned_process_exited') is not True or execution.get('exit_code') in (None, 0):
                raise ValueError('Additional compiler failure must be a completed failed native execution')
            extra = {line.strip() for line in Path(failure['compiler_log']).read_text(errors='replace').splitlines()
                     if 'error CS' in line}
            if not extra:
                raise ValueError('Additional compiler failure lacks actual compiler errors')
            errors.update(extra)
        reviewed_builtin_errors(entry, errors)
        if 'private_method_rename' in entry:
            from .unity_member_method_recovery import review
            review(entry)
        if 'vector_float_literals' in entry:
            from .unity_vector_float_recovery import review
            review(entry)
        return dict(entry, ident=ident, policy_path=str(policy.resolve()), policy_sha256=sha(policy))
    if operation == 'exclude_reviewed_compilation_units':
        from .unity_compilation_unit_compatibility import verify_compiler_errors
        verify_compiler_errors(entry, errors)
        return dict(entry, ident=ident, policy_path=str(policy.resolve()), policy_sha256=sha(policy))
    expected = ("CS0136:" if operation == 'rename_loop_local' else "CS1069:")
    detail = ("local or parameter named '" + entry['old_name'] + "'" if operation == 'rename_loop_local'
              else "The type name 'Animator'")
    if not errors or not all(expected in line and detail in line for line in errors):
        raise ValueError('Unexpected native compile failure; review required')
    return dict(entry, ident=ident, policy_path=str(policy.resolve()), policy_sha256=sha(policy))


def eligible(root, output, case, row):
    if (case.get('status') != 'BOUNDED_FAILURE' or case.get('phase') != 'admission'
            or case.get('native_compile_recovery_count') or not row.get('project')
            or (Path(output)/'single_state.json').exists() or (Path(output)/'opened_candidate.json').exists()):
        return False
    entry = load(root, row['id'], row['project'])
    return bool(entry and str(case.get('error', '')).endswith(entry['prior_receipt']))


def apply(entry, candidate, sandbox, receipt):
    from .batch import read
    if load(Path(entry['policy_path']).parent, entry['ident'], entry['project']) != entry:
        raise ValueError('Native compile recovery policy changed')
    sandbox = Path(sandbox).resolve()
    path = sandbox / entry['source']
    if path.is_symlink() or not path.resolve().is_relative_to(sandbox):
        raise ValueError('Native compile recovery snapshot escaped project')
    if sha(path) != entry['source_sha256']:
        from .unity_compile_compatibility import verified_builder_import
        if (not candidate.get('import_compatibility') or not entry['source'].startswith('Assets/')
                or not entry['source'].endswith('.cs')
                or not verified_builder_import(candidate['import_compatibility'], candidate['id'], sandbox, entry['source'])):
            raise ValueError('Native compile recovery snapshot SHA changed')
    before = sha(path)
    extra = {}
    if entry['operation'] == 'rename_loop_local':
        before_bytes = path.read_bytes()
        text = before_bytes.decode('utf-8')
        span = entry['span']
        if text.count(span) != 1:
            raise ValueError('Reviewed loop changed')
        replacement = re.sub(r'\b' + re.escape(entry['old_name']) + r'\b', entry['new_name'], span)
        path.write_bytes(text.replace(span, replacement, 1).encode('utf-8'))
        extra = {'before_span': span, 'after_span': replacement}
    elif entry['operation'] == 'add_reviewed_asmdef_reference':
        from .unity_asmdef_reference_recovery import apply_reference
        extra = apply_reference(entry, sandbox)
    elif entry['operation'] == 'align_reviewed_shadergraph_access':
        from .unity_shadergraph_access_recovery import apply_access
        extra = apply_access(entry, candidate, sandbox)
    elif entry['operation'] == 'exclude_reviewed_compilation_units':
        from .unity_compilation_unit_compatibility import apply_exclusions
        extra = apply_exclusions(entry, sandbox)
    elif entry['operation'] == 'remove_reviewed_uncontrolled_module_pin':
        from .unity_uncontrolled_module_recovery import apply_pin
        extra = apply_pin(entry, candidate, sandbox)
    elif entry['operation'] == 'enable_reviewed_builtin_modules':
        literal=None
        if 'vector_float_literals' in entry:
            from .unity_vector_float_recovery import review,prepare
            review(entry);literal=prepare(entry,sandbox)
        member=None
        if 'private_method_rename' in entry:
            from .unity_member_method_recovery import review,prepare
            review(entry);member=prepare(entry,sandbox)
        packages = []
        # Verify every selected Editor definition and sandbox source before mutation.
        for relative, digest in entry['compiler_sources'].items():
            copied = sandbox/relative
            if copied.is_symlink() or not copied.resolve().is_relative_to(sandbox/'Assets') or sha(copied) != digest:
                raise ValueError('Isolated compiler source changed or escaped')
        for module in entry['modules']:
            package = Path(candidate['selected_editor']).parent.parent/'Resources/PackageManager/BuiltInPackages'/module/'package.json'
            definition = read(package)
            if definition.get('name') != module or definition.get('version') != '1.0.0' or definition.get('type') != 'module':
                raise ValueError('Selected Editor built-in module does not match review')
            packages.append({'name': module, 'version': '1.0.0', 'path': str(package), 'sha256': sha(package)})
        manifest = read(path)
        for package in packages:
            if package['name'] in manifest['dependencies']:
                raise ValueError('Refuse to replace existing built-in module pin')
            manifest['dependencies'][package['name']] = package['version']
        before_bytes = path.read_bytes()
        dump(path, manifest)
        if literal:(sandbox/literal['source']).write_bytes(literal['after_utf8'].encode('utf-8'))
        if member:(sandbox/member['source']).write_bytes(member['after_utf8'].encode('utf-8'))
        extra = {'private_method_rename':member,'vector_float_literals':literal,'builtin_packages': packages, 'manifest_before_utf8': before_bytes.decode('utf-8'),
                 'manifest_after_utf8': path.read_text(), 'gameplay_changes': [],
                 'compiler_sources_unchanged': entry['compiler_sources']}
    else:
        package = Path(candidate['selected_editor']).parent.parent / 'Resources/PackageManager/BuiltInPackages/com.unity.modules.animation/package.json'
        definition = read(package)
        if (definition.get('name') != 'com.unity.modules.animation' or definition.get('version') != '1.0.0'
                or definition.get('type') != 'module'):
            raise ValueError('Selected Editor animation module does not match')
        manifest = read(path)
        manifest['dependencies']['com.unity.modules.animation'] = '1.0.0'
        dump(path, manifest)
        extra = {'builtin_package': str(package), 'builtin_package_sha256': sha(package)}
    result = {'version': VERSION, 'entry': entry, 'created_unix': time.time(),
              'before_sha256': before, 'after_sha256': sha(path), 'details': extra,
              'source_project_unchanged': sha(Path(entry['project']) / entry['source']) == entry['source_sha256'],
              'scope': 'Reviewed compilation compatibility in isolated snapshot; no authored gameplay changes.'}
    dump(receipt, result)
    if not result['source_project_unchanged']:
        raise ValueError('Original changed during native compile recovery')
    return {'path': str(Path(receipt)), 'sha256': sha(Path(receipt))}
