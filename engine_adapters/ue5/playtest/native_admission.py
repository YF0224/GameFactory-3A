"""Install only the formal adapter hook in a source-bound validation copy."""
import re
import json
import os
import shutil
from pathlib import Path

from pipeline.eval.refine.common import dump, sha

DEPENDENCIES = ('ApplicationCore', 'AudioMixer', 'InputCore', 'Json', 'Networking', 'RenderCore', 'Sockets', 'Slate', 'SlateCore')
SKIP = {'Binaries', 'Intermediate', 'Saved', 'DerivedDataCache', '.git', '__pycache__'}
MODULE = Path('Plugins/A3GamePlayable/Source/A3GamePlayable')


def source_manifest(root):
    """Bind authored source, configuration, content and plugin descriptors/assets."""
    root = Path(root).resolve(strict=True)
    files = {}
    for folder in ('Source', 'Config', 'Content', 'Plugins'):
        base = root / folder
        if not base.exists():
            continue
        if not base.resolve().is_relative_to(root):
            raise ValueError('Validation copy cannot use external authored directories: '+str(base))
        for path in base.rglob('*'):
            relative = path.relative_to(root)
            if any(part in SKIP for part in relative.parts):
                continue
            if not path.resolve().is_relative_to(root):
                raise ValueError('Validation copy cannot use external authored files: '+str(path))
            if path.is_file():
                files[str(relative)] = sha(path)
    for path in root.glob('*.uproject'):
        if not path.resolve().is_relative_to(root):
            raise ValueError('External project marker is not a validation copy')
        files[path.name] = sha(path)
    return files


def dependency_overlay(text):
    """Append dependencies inside ModuleRules' constructor, preserving user code."""
    missing = [name for name in DEPENDENCIES if not re.search(r'"'+name+r'"', text)]
    if not missing:
        return text
    match = re.search(r'public\s+A3GamePlayable\s*\(\s*ReadOnlyTargetRules\s+\w+\s*\)\s*:\s*base\([^)]*\)\s*\{', text)
    if not match:
        raise ValueError('Unrecognized A3GamePlayable Build.cs constructor; refusing replacement')
    addition = '\n        PrivateDependencyModuleNames.AddRange(new string[] { ' + ', '.join('"'+n+'"' for n in missing) + ' });\n'
    return text[:match.end()] + addition + text[match.end():]


def _install_absent_recorder(project, source, out, formal, recorder_files, original):
    """Install the formal capture/input module only; never the gameplay framework.

    Called only after exact-source and independent-file checks. An existing or
    author-referenced framework cannot be replaced/reconstructed by this path.
    """
    plugin = MODULE.parents[1]
    if (project / plugin).exists():
        raise ValueError('Partial existing A3GamePlayable plugin cannot be reconstructed')
    markers = list(project.glob('*.uproject'))
    if len(markers) != 1:
        raise ValueError('Recorder-only installation requires exactly one project marker')
    marker = markers[0]
    payload = json.loads(marker.read_text(encoding='utf-8'))
    if not isinstance(payload, dict) or not isinstance(payload.get('Plugins', []), list):
        raise ValueError('Malformed project plugin declaration')
    # Missing author dependencies remain product defects, not recorder installs.
    for relative in original:
        path = source / relative
        if path.suffix.lower() in {'.uproject', '.uplugin', '.cs', '.cpp', '.h', '.ini'}:
            if 'A3GamePlayable' in path.read_text(encoding='utf-8'):
                raise ValueError('Author references missing A3GamePlayable; refusing dependency repair')
    formal = Path(formal).resolve(strict=True)
    plugin_source = formal.parents[1]
    if list(recorder_files) != [
            'Public/Playtest/A3GamePlaytestRecorderSubsystem.h',
            'Private/Playtest/A3GamePlaytestRecorderSubsystem.cpp', 'A3GamePlayable.Build.cs']:
        raise ValueError('Unexpected recorder file contract')
    names = ['A3GamePlayable.uplugin'] + [
        'Source/A3GamePlayable/' + name for name in
        ['A3GamePlayable.Build.cs', 'Public/A3GamePlayableModule.h',
         'Private/A3GamePlayableModule.cpp'] + recorder_files[:2]]
    sources = {}
    for name in names:
        path = plugin_source / name
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(plugin_source):
            raise ValueError('Missing or linked formal recorder scaffold: ' + str(path))
        sources[name] = sha(path)
    descriptor = json.loads((plugin_source / names[0]).read_text(encoding='utf-8'))
    if (descriptor.get('Modules') != [{'Name': 'A3GamePlayable', 'Type': 'Runtime', 'LoadingPhase': 'Default'}]
            or descriptor.get('CanContainContent') is not False or descriptor.get('Plugins')):
        raise ValueError('Formal recorder descriptor contract changed')
    if dependency_overlay((formal / 'A3GamePlayable.Build.cs').read_text(encoding='utf-8')) != (
            formal / 'A3GamePlayable.Build.cs').read_text(encoding='utf-8'):
        raise ValueError('Formal recorder scaffold dependencies incomplete')
    out = Path(out)
    dump(out/'source_binding.json', {'source_project': str(source), 'validation_project': str(project),
         'files': original, 'status': 'SOURCE_BOUND_BEFORE_ADAPTER_OVERLAY'})
    archive = out/'before'/marker.name
    archive.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(marker, archive)
    overlays = []
    for name, digest in sources.items():
        target = project / plugin / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as handle:
            handle.write((plugin_source / name).read_bytes())
        if sha(target) != digest:
            raise RuntimeError('Formal recorder scaffold changed during copy')
        overlays.append({'path': str(target.relative_to(project)), 'before_sha256': None,
                         'after_sha256': digest, 'before_archive': None,
                         'formal_source': str(plugin_source/name), 'formal_source_sha256': digest})
    payload['Plugins'] = payload.get('Plugins', []) + [{'Name': 'A3GamePlayable', 'Enabled': True}]
    marker.write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')
    overlays.append({'path': marker.name, 'before_sha256': original[marker.name],
                     'after_sha256': sha(marker), 'before_archive': str(archive)})
    after = source_manifest(project)
    allowed = {row['path'] for row in overlays}
    if ({p:h for p,h in original.items() if p not in allowed} !=
            {p:h for p,h in after.items() if p not in allowed} or source_manifest(source) != original):
        raise RuntimeError('Authored source changed during recorder installation')
    dump(out/'overlay.json', {'source_binding': str(out/'source_binding.json'), 'overlays': overlays,
         'mode': 'absent_plugin_recorder_only.v1',
         'semantic_change': 'Formal native viewport input/capture only; no framework gameplay subsystems'})
    return {'source_project': str(source), 'source_binding': str(out/'source_binding.json'),
            'overlay': str(out/'overlay.json')}


def install(project, source_project, out, formal, recorder_files):
    """Require an exact authored copy before any adapter modification or build."""
    if source_project is None:
        raise ValueError('install_recorder requires validation_source, an isolated copy of that source')
    source = Path(source_project).expanduser().resolve(strict=True)
    if source.is_file():
        source = source.parent
    project = Path(project).resolve(strict=True)
    if source == project or source.is_relative_to(project) or project.is_relative_to(source):
        raise ValueError('Recorder installation requires a separate validation copy, not the author project')
    original = source_manifest(source)
    copied = source_manifest(project)
    if not original or copied != original:
        raise ValueError('Validation copy authored files must match validation_source before overlay')
    # Check every target before writing any file. Never write through hardlinks
    # or symlinks into the source; builds also operate only on the isolated copy.
    for target in project.rglob('*'):
        if target.is_symlink() or not target.resolve().is_relative_to(project):
            raise ValueError('Validation copy cannot contain symlink aliases: '+str(target))
        if target.is_file():
            source_file = source / target.relative_to(project)
            if target.stat().st_nlink > 1 or (source_file.exists() and target.samefile(source_file)):
                raise ValueError('Validation copy needs independent files: '+str(target))
    if not (project / MODULE.parents[1]).exists():
        return _install_absent_recorder(project, source, out, formal, recorder_files, original)
    build = project / MODULE / 'A3GamePlayable.Build.cs'
    new_build = dependency_overlay(build.read_text(encoding='utf-8'))
    out = Path(out)
    dump(out/'source_binding.json', {'source_project': str(source), 'validation_project': str(project),
         'files': original, 'status': 'SOURCE_BOUND_BEFORE_ADAPTER_OVERLAY'})
    overlays = []
    for relative in recorder_files[:2] + ['A3GamePlayable.Build.cs']:
        target = project / MODULE / relative
        if not target.is_file():
            raise ValueError('Existing A3GamePlayable recorder target missing: '+str(target))
        archive = out/'before'/relative
        archive.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, archive)
        before = sha(target)
        if relative.endswith('.Build.cs'):
            target.write_text(new_build, encoding='utf-8')
        else:
            shutil.copy2(formal/relative, target)
        overlays.append({'path': str(target.relative_to(project)), 'before_sha256': before,
                         'after_sha256': sha(target), 'before_archive': str(archive)})
    # Bind the entire author tree again, excluding exactly the declared overlay.
    after = source_manifest(project)
    allowed = {row['path'] for row in overlays}
    if ({p:h for p,h in copied.items() if p not in allowed} !=
            {p:h for p,h in after.items() if p not in allowed} or source_manifest(source) != original):
        raise RuntimeError('Authored source changed during recorder installation')
    dump(out/'overlay.json', {'source_binding': str(out/'source_binding.json'), 'overlays': overlays,
         'semantic_change': 'Adapter native viewport input/capture only; authored gameplay unchanged'})
    return {'source_project': str(source), 'source_binding': str(out/'source_binding.json'),
            'overlay': str(out/'overlay.json')}


def install_overlay(*, project_path, validation_source, output_dir):
    """Overlay only: no UBT, editor, worker or model execution."""
    from .native_record import PLUGIN, RECORDER_FILES
    project_file = Path(project_path).expanduser().resolve(strict=True)
    if project_file.suffix != '.uproject' or not project_file.is_file():
        raise ValueError('project_path must be the validation copy .uproject')
    leased = os.environ.get('A3GAME_REPAIR_PROJECT_ROOT')
    if leased and project_file.parent != Path(leased).resolve():
        raise ValueError('Overlay project must match the leased validation candidate')
    out = Path(output_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=False)
    result = install(project_file.parent, validation_source, out, PLUGIN, RECORDER_FILES)
    return {'ok': True, 'status': 'OVERLAID_PENDING_BUILD_AND_NATIVE_ACCEPTANCE',
            'project_file': str(project_file), **result}


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True, help='Independent validation-copy .uproject')
    parser.add_argument('--validation-source', required=True, help='Resolved author/source project directory')
    parser.add_argument('--output-dir', required=True, help='New exclusive overlay receipt directory')
    args = parser.parse_args()
    try:
        result = install_overlay(project_path=args.project, validation_source=args.validation_source,
                                 output_dir=args.output_dir)
    except Exception as exc:
        parser.exit(1, f'{type(exc).__name__}: {exc}\n')
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
