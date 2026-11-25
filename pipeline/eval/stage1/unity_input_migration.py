"""Portable isolated input migration; preserves authored control paths.

The accepted adapter/shim files stay unchanged. Only the package location is
configuration data; the actual import and later native capture qualify the copy.
"""
from pathlib import Path
import hashlib
import json
import os
import re
import shutil

# Only the accepted native-device shim's actual API. An authored GameInput
# property also named Input is not UnityEngine.Input (e.g. ConsumeEdges).
DEVICE_MEMBERS = frozenset({
    'GetKey', 'GetKeyDown', 'GetKeyUp', 'GetMouseButton', 'GetMouseButtonDown',
    'GetMouseButtonUp', 'mousePosition', 'mouseScrollDelta', 'anyKeyDown',
    'GetAxis', 'GetAxisRaw', 'GetButton', 'GetButtonDown', 'GetButtonUp'})


def migrate_device_reads(text):
    members = '|'.join(sorted(DEVICE_MEMBERS, key=lambda x: (-len(x), x)))
    return re.sub(r'(?<![\w.])(?:UnityEngine\.)?Input\.(?=(?:'+members+r')\b)',
                  'global::GameFactoryInput.', text)


def migrate_input(project, output, *, package_root=None):
    """Keep authored control paths; replace only their input device reads."""
    project, output = Path(project), Path(output)
    # Unity's serialized property is activeInputHandler. A delivered legacy
    # m_ActiveInputHandler spelling is not recognized by the current Editors:
    # the native reader then reports -1 and neither backend define is emitted.
    settings = project/'ProjectSettings/ProjectSettings.asset'
    settings_before = settings.read_text()
    pattern = r'(?m)^([ \t]*)(m_ActiveInputHandler|activeInputHandler):[ \t]*(-?\d+)[ \t]*$'
    matches = list(re.finditer(pattern, settings_before))
    if len(matches) != 1:
        raise ValueError('Cannot uniquely bind input handler setting')
    settings_after = re.sub(pattern, r'\g<1>activeInputHandler: 1', settings_before)
    original_handler = matches[0]
    changes = []
    for path in sorted((project/'Assets').rglob('*.cs')):
        if 'GameFactoryInput' in path.name:
            continue
        before = path.read_text()
        after = migrate_device_reads(before)
        if after != before:
            path.write_text(after)
            changes.append({'path':str(path.relative_to(project)),
                'before_sha256':hashlib.sha256(before.encode()).hexdigest(),
                'after_sha256':hashlib.sha256(after.encode()).hexdigest(),
                'kind':'native_input_device_reads_only'})
    from engine_adapters.unity3d.playtest import project_snapshot
    shim = Path(project_snapshot.__file__).parent/'resources/GameFactoryInput.cs'
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
    settings.write_text(settings_after)
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
    configured=package_root or os.environ.get('GAMEFACTORY_UNITY_INPUT_SYSTEM_PACKAGE')
    if configured:
        cache=Path(configured).expanduser().resolve()
    else:
        cache=Path.home()/'Library/Unity/cache/packages/packages.unity.cn/com.unity.inputsystem@1.14.0'
    if not cache.is_dir():
        raise ValueError('Input System package absent; configure input_system_package_root explicitly')
    package=json.loads((cache/'package.json').read_text())
    if package.get('name')!='com.unity.inputsystem' or package.get('version')!='1.14.0':
        raise ValueError('The accepted input shim requires com.unity.inputsystem 1.14.0')
    packages['dependencies']['com.unity.inputsystem'] = 'file:'+str(cache)
    manifest.write_text(json.dumps(packages,indent=2)+'\n')
    receipt = {'version':'unity-inputsystem-migration.v1','user_authorized':True,
               'project':str(project.resolve()),'changes':changes,
               'shim_sha256':hashlib.sha256(shim.read_bytes()).hexdigest(),
               'axis_source':str(axis_file),'axis_count':len(axes),'gameplay_changes':[],
               'input_handler_setting':{'path':'ProjectSettings/ProjectSettings.asset',
                   'before_sha256':hashlib.sha256(settings_before.encode()).hexdigest(),
                   'after_sha256':hashlib.sha256(settings_after.encode()).hexdigest(),
                   'before':original_handler[3],
                   'before_key':original_handler[2], 'after_key':'activeInputHandler',
                   'after':1,'scope':'isolated snapshot; original delivery unchanged'},
               'input_system_package':str(cache),'package_manifest_sha256':hashlib.sha256((cache/'package.json').read_bytes()).hexdigest()}
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
    return receipt
