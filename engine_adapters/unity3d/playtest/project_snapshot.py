"""Source snapshots and legacy input compatibility in isolated Unity projects."""
from pathlib import Path
import hashlib
import json
import os
import re
import shutil

SNAPSHOT_POLICY = 'unity-authored-project-snapshot.v1'
EXCLUDED = {'Library', 'Temp', 'Logs', 'obj', '.git', '.vs', 'Builds', 'Build', 'UserSettings', 'MemoryCaptures', 'Recordings', 'node_modules'}

def snapshot_files(source, excluded):
    source = Path(source).resolve()
    for folder, dirs, files in os.walk(source, followlinks=False):
        base = Path(folder)
        removed = [name for name in dirs if name in EXCLUDED]
        excluded.extend(str((base/name).relative_to(source)) for name in removed)
        dirs[:] = sorted(name for name in dirs if name not in EXCLUDED)
        for name in sorted(files):
            path = base/name
            if path.is_symlink():
                raise ValueError('Snapshot refuses symlink: '+str(path))
            yield path

def migrate_input(project, output):
    """Keep authored control paths; replace only their input device reads."""
    project, output = Path(project), Path(output)
    changes = []
    for path in sorted((project/'Assets').rglob('*.cs')):
        if 'GameFactoryInput' in path.name:
            continue
        before = path.read_text()
        after = re.sub(r'(?<![\w.])(?:UnityEngine\.)?Input\.', 'global::GameFactoryInput.', before)
        if after != before:
            path.write_text(after)
            changes.append({'path':str(path.relative_to(project)),
                'before_sha256':hashlib.sha256(before.encode()).hexdigest(),
                'after_sha256':hashlib.sha256(after.encode()).hexdigest(),
                'kind':'native_input_device_reads_only'})
    shim = input_shim()
    shim_dir = project/'Assets/GameFactoryInputMigration'
    shim_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(shim, shim_dir/'GameFactoryInput.cs')
    (shim_dir/'GameFactoryInputMigration.asmdef').write_text(json.dumps({
        'name':'GameFactoryInputMigration', 'references':['Unity.InputSystem'],
        'autoReferenced':True}, indent=2)+'\n')
    for change in changes:
        parent = (project/change['path']).parent
        while parent != project:
            definitions = list(parent.glob('*.asmdef'))
            if definitions:
                if len(definitions) != 1:
                    raise ValueError('Ambiguous source assembly')
                definition = definitions[0]
                assembly = json.loads(definition.read_text())
                refs = assembly.setdefault('references', [])
                if 'GameFactoryInputMigration' not in refs:
                    refs.append('GameFactoryInputMigration')
                    definition.write_text(json.dumps(assembly, indent=2)+'\n')
                break
            parent = parent.parent
    settings = project/'ProjectSettings/ProjectSettings.asset'
    before = settings.read_text()
    after, count = re.subn(r'(?m)^(\s*(?:m_ActiveInputHandler|activeInputHandler):)\s*\d+\s*$', r'\g<1> 1', before)
    if count != 1:
        raise ValueError('Cannot uniquely bind input handler setting')
    settings.write_text(after)
    import yaml
    axis_file = project/'ProjectSettings/InputManager.asset'
    text = axis_file.read_text()
    text = '\n'.join(line for line in text.splitlines() if not line.startswith('%'))
    text = re.sub(r'--- !u!\d+ &\d+', '---', text)
    axes = yaml.safe_load(text)['InputManager']['m_Axes']
    from engine_adapters.unity3d.playtest.input_axis_serialization import canonical_axes
    axes = canonical_axes(axes)
    resource = project/'Assets/Resources/GameFactoryInputAxes.json'
    resource.parent.mkdir(parents=True, exist_ok=True)
    resource.write_text(json.dumps({'axes':axes},ensure_ascii=False,indent=2)+'\n')
    manifest = project/'Packages/manifest.json'
    packages = json.loads(manifest.read_text())
    cache, package_files = input_system_package()
    packages['dependencies']['com.unity.inputsystem'] = 'file:'+str(cache)
    manifest.write_text(json.dumps(packages,indent=2)+'\n')
    receipt = {'version':'unity-inputsystem-migration.v1','user_authorized':True,
               'project':str(project.resolve()),'changes':changes,
               'shim_sha256':hashlib.sha256(shim.read_bytes()).hexdigest(),
               'axis_source':str(axis_file),'axis_count':len(axes),'gameplay_changes':[],
               'input_system_package':str(cache),'input_system_files_sha256':package_files}
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
    return receipt


def input_system_package():
    """Resolve the unchanged pinned package version, never a newer fallback."""
    candidates=[Path.home()/'Library/Unity/cache/packages/packages.unity.cn/com.unity.inputsystem@1.14.0',
        Path.home()/'Library/Tuanjie/cache/packages/packages.tuanjie.cn/com.unity.inputsystem@1.14.0']
    for package in candidates:
        manifest=package/'package.json'
        if not manifest.is_file():continue
        value=json.loads(manifest.read_text())
        if value.get('name')!='com.unity.inputsystem' or value.get('version')!='1.14.0':
            raise ValueError('Pinned Input System package identity differs')
        files={}
        for folder,dirs,names in os.walk(package,followlinks=False):
            for name in dirs+names:
                if (Path(folder)/name).is_symlink():raise ValueError('Package symlink requires provenance')
            for name in names:
                path=Path(folder)/name
                files[str(path.relative_to(package))]=hashlib.sha256(path.read_bytes()).hexdigest()
        return package,files
    raise ValueError('Preserved validated Input System 1.14.0 package absent')


def _pinned_input_uri(uri):
    if not isinstance(uri, str) or not uri.startswith('file:/'):
        return False
    path = Path(uri[5:])
    return path.is_absolute() and path.name == 'com.unity.inputsystem@1.14.0' and '..' not in path.parts


def relocate_missing_input_package(project):
    """Relocate only a missing absolute URI for the unchanged pinned package."""
    manifest = Path(project)/'Packages/manifest.json'
    value = json.loads(manifest.read_text())
    old = value.get('dependencies', {}).get('com.unity.inputsystem')
    if not _pinned_input_uri(old) or Path(old[5:], 'package.json').is_file():
        return None
    package, files = input_system_package()
    expected_uri = 'file:' + str(package)
    before = hashlib.sha256(manifest.read_bytes()).hexdigest()
    value['dependencies']['com.unity.inputsystem'] = expected_uri
    manifest.write_text(json.dumps(value, indent=2)+'\n')
    return dict(version='unity-exact-package-path-relocation.v1', package='com.unity.inputsystem', package_version='1.14.0',
        from_uri=old, to_uri=expected_uri, package_files_sha256=files,
        manifest_before_sha256=before, manifest_after_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(), gameplay_changes=[])


def verify_package_relocation(source, project, proof):
    """Accept only the same-version package URI relocation and exact file hashes."""
    relative = 'Packages/manifest.json'
    before = (Path(source)/relative).read_bytes()
    after = (Path(project)/relative).read_bytes()
    value = json.loads(before)
    original_uri = value.get('dependencies', {}).get('com.unity.inputsystem')
    package, files = input_system_package()
    expected_uri = 'file:' + str(package)
    if (not _pinned_input_uri(original_uri)
            or proof.get('version') != 'unity-exact-package-path-relocation.v1'
            or proof.get('package') != 'com.unity.inputsystem' or proof.get('package_version') != '1.14.0'
            or proof.get('from_uri') != original_uri or proof.get('to_uri') != expected_uri
            or proof.get('package_files_sha256') != files or proof.get('gameplay_changes') != []
            or proof.get('manifest_before_sha256') != hashlib.sha256(before).hexdigest()
            or proof.get('manifest_after_sha256') != hashlib.sha256(after).hexdigest()):
        raise ValueError('Exact package relocation proof changed')
    value['dependencies']['com.unity.inputsystem'] = expected_uri
    if after != (json.dumps(value, indent=2)+'\n').encode():
        raise ValueError('Package relocation contains unrelated manifest edits')
    return relative


def input_shim():
    """Validate the bundled shim without requiring the historical source checkout."""
    resource = Path(__file__).parent / 'resources/GameFactoryInput.cs'
    proof = json.loads(resource.with_suffix('.provenance.json').read_text())
    source = Path(proof['source'])
    if (proof.get('source_root') != 'bench' or source.is_absolute() or '..' in source.parts
            or not source.parts or hashlib.sha256(resource.read_bytes()).hexdigest() != proof['sha256']):
        raise ValueError('Input shim provenance differs')
    return resource
