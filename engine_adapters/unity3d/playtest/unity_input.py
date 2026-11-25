"""Unity legacy-input projects: isolated Input System migration of the eval copy.

The adapter's in-engine driver (``internal`` transport) injects through the Unity
Input System, which legacy ``UnityEngine.Input`` reads never see; the adapter would
then fall back to OS keyboard injection, which is forbidden. So, on the run's
``runtime/project`` copy only (the author's delivery is never touched), and only
when the project is not already on the Input System backend:

* ``UnityEngine.Input.<device read>`` -> ``global::GameFactoryInput.<same read>``
  (the adapter's shim, ``engine_adapters/unity3d/playtest/resources/GameFactoryInput.cs``);
  authored control paths, key bindings and gameplay code are otherwise unchanged;
* ``activeInputHandler: 1`` and a compatible cached ``com.unity.inputsystem`` when the author did not declare one;
* the authored InputManager axes are exported verbatim so axis reads keep their bindings.

Same rules as the historical evaluator's user-authorized migration; every changed
file is listed with before/after SHA256 in the receipt.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from pathlib import Path

VERSION = 'stage1-unity-inputsystem-migration.v3'
# The cached Tuanjie 1.14.0 fork requires an INavigationEventData interface
# absent from these Unity 2022/UGUI 1 projects. 1.7.0 supports their native API.
PACKAGE = ('com.unity.inputsystem', '1.7.0')
DEVICE_MEMBERS = ('GetKey', 'GetKeyDown', 'GetKeyUp', 'GetMouseButton', 'GetMouseButtonDown', 'GetMouseButtonUp',
                  'mousePosition', 'mouseScrollDelta', 'anyKeyDown', 'GetAxis', 'GetAxisRaw', 'GetButton',
                  'GetButtonDown', 'GetButtonUp')
HANDLER = re.compile(r'(?m)^([ \t]*)(m_ActiveInputHandler|activeInputHandler):[ \t]*(-?\d+)[ \t]*(?=\r?$)')


def _sha(data: str) -> str:
    return hashlib.sha256(data.encode()).hexdigest()


def needs_migration(project: Path) -> bool:
    text = (Path(project) / 'ProjectSettings/ProjectSettings.asset').read_bytes().decode('utf-8')
    _, binding = _handler_update(text)
    return not (binding['before_key'] == 'activeInputHandler' and binding['before'] == '1')


def _handler_update(text: str) -> tuple[str, dict]:
    """Bind an explicit setting, or insert only into a validated absent-field document.

    Absence is not a legacy/default value. The inserted value selects the already
    authorized recorder backend; it does not describe the author's original mode.
    """
    found = list(HANDLER.finditer(text))
    candidates = re.findall(r'(?m)^[ \t]*[\"\']?(?:m_ActiveInputHandler|activeInputHandler)\b', text)
    if found or candidates:
        if len(found) != 1 or len(candidates) != 1 or found[0].group(3) not in ('0', '1', '2'):
            raise ValueError('cannot uniquely bind the input handler setting')

    def explicit_update():
        match = found[0]
        return HANDLER.sub(r'\g<1>activeInputHandler: 1', text), {
            'before': match.group(3), 'before_key': match.group(2),
            'before_present': True, 'before_state': 'present', 'after': 1,
            'operation': 'normalize_explicit_handler',
        }

    # Preserve the existing explicit-field path, including native fork tags.
    # Strict document validation is required only for absent-field insertion.
    if found:
        return explicit_update()

    import yaml
    # Accept the known Unity document envelope, not arbitrary YAML that happens
    # to contain PlayerSettings. Keep every original byte outside the insertion.
    header = re.match(r'\A%YAML 1\.1(?P<nl>\r?\n)%TAG !u! tag:unity3d\.com,2011:(?P=nl)'
                      r'--- !u!129 &1(?P=nl)(?P<body>PlayerSettings:(?P=nl))', text)
    if header is None:
        raise ValueError('absent input handler requires one canonical PlayerSettings document')
    newline = header.group('nl')
    if ('\r' in text.replace('\r\n', '') or
            (newline == '\r\n' and '\n' in text.replace('\r\n', '')) or
            (newline == '\n' and '\r' in text)):
        raise ValueError('mixed or unsupported PlayerSettings line endings')
    body = text[header.start('body'):]
    try:
        # Do not accept aliases, merge keys, nested tags or custom constructors.
        if any(isinstance(token, (yaml.tokens.AliasToken, yaml.tokens.AnchorToken,
                                  yaml.tokens.TagToken)) for token in yaml.scan(body)):
            raise ValueError('aliases, anchors and tags are unsupported in PlayerSettings')
        documents = list(yaml.compose_all(body, Loader=yaml.SafeLoader))
    except yaml.YAMLError as exc:
        raise ValueError('invalid PlayerSettings YAML') from exc
    if len(documents) != 1 or not isinstance(documents[0], yaml.MappingNode):
        raise ValueError('expected exactly one PlayerSettings mapping document')

    handler_nodes = []

    def validate(node):
        if isinstance(node, yaml.MappingNode):
            keys = set()
            for key, value in node.value:
                if not isinstance(key, yaml.ScalarNode) or key.tag != 'tag:yaml.org,2002:str':
                    raise ValueError('unsupported PlayerSettings mapping key')
                if key.value in keys:
                    raise ValueError('duplicate PlayerSettings YAML key')
                keys.add(key.value)
                if key.value in ('activeInputHandler', 'm_ActiveInputHandler'):
                    handler_nodes.append((node, key, value))
                validate(value)
        elif isinstance(node, yaml.SequenceNode):
            for item in node.value:
                validate(item)

    document = documents[0]
    validate(document)
    if len(document.value) != 1 or document.value[0][0].value != 'PlayerSettings':
        raise ValueError('PlayerSettings must be the only root mapping')
    player = document.value[0][1]
    if not isinstance(player, yaml.MappingNode) or player.flow_style:
        raise ValueError('PlayerSettings must be a block mapping')
    version = dict((key.value, value) for key, value in player.value).get('serializedVersion')
    if (not isinstance(version, yaml.ScalarNode) or version.tag != 'tag:yaml.org,2002:int'
            or not version.value.isdecimal() or int(version.value) <= 0):
        raise ValueError('PlayerSettings requires a positive integer serializedVersion')
    # Inserting a two-space child requires all existing direct keys at that level.
    if any(key.start_mark.column != 2 for key, _ in player.value):
        raise ValueError('unsupported PlayerSettings child indentation')
    if handler_nodes:
        raise ValueError('input handler exists outside the supported explicit-field format')
    after = text[:header.end()] + '  activeInputHandler: 1' + newline + text[header.end():]
    return after, {'before': None, 'before_key': None, 'before_present': False,
                   'before_state': 'absent', 'after': 1, 'operation': 'insert_absent_handler',
                   'yaml_class_id': 129, 'yaml_root': 'PlayerSettings',
                   'insertion_byte_offset': len(text[:header.end()].encode('utf-8'))}


def package_root() -> Path:
    name = '@'.join(PACKAGE)
    candidates = [os.environ.get('GAMEFACTORY_UNITY_INPUT_SYSTEM_PACKAGE', ''),
                  str(Path.home() / 'Library/Tuanjie/cache/packages/packages.tuanjie.cn' / name),
                  str(Path.home() / 'Library/Unity/cache/packages/packages.unity.cn' / name),
                  str(Path.home() / 'Library/Unity/cache/packages/packages.unity.com' / name)]
    for c in filter(None, candidates):
        p = Path(c).expanduser()
        meta = p / 'package.json'
        if meta.is_file() and json.loads(meta.read_text()).get('version') == PACKAGE[1]:
            return p.resolve()
    raise ValueError(f'{name} not found in the local package caches; set GAMEFACTORY_UNITY_INPUT_SYSTEM_PACKAGE')


def migrate_device_reads(text: str) -> str:
    members = '|'.join(sorted(DEVICE_MEMBERS, key=lambda x: (-len(x), x)))
    return re.sub(r'(?<![\w.])(?:UnityEngine\.)?Input\.(?=(?:' + members + r')\b)', 'global::GameFactoryInput.', text)


def _input_axes(project: Path) -> list:
    """Read and validate all axes before the migration writes any runtime file."""
    import yaml
    from engine_adapters.unity3d.playtest.input_axis_serialization import canonical_axes

    text = '\n'.join(line for line in (Path(project) / 'ProjectSettings/InputManager.asset').read_text().splitlines()
                     if not line.startswith('%'))
    try:
        data = yaml.safe_load(re.sub(r'--- !u!\d+ &\d+', '---', text))
    except yaml.YAMLError as exc:
        raise ValueError('invalid InputManager YAML') from exc
    manager = data.get('InputManager') if isinstance(data, dict) else None
    if not isinstance(manager, dict) or 'm_Axes' not in manager:
        raise ValueError('InputManager requires m_Axes')
    return canonical_axes(manager['m_Axes'])


def migrate(project: Path, receipt_path: Path) -> dict:
    """Migrate the isolated copy once; return (and persist) the receipt."""
    project, receipt_path = Path(project), Path(receipt_path)
    if receipt_path.is_file():
        return json.loads(receipt_path.read_text())
    if not needs_migration(project):
        receipt = {'version': VERSION, 'migrated': False, 'reason': 'already on the Input System backend'}
        receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
        return receipt
    from engine_adapters.unity3d.playtest import project_snapshot

    settings = project / 'ProjectSettings/ProjectSettings.asset'
    before_settings = settings.read_bytes().decode('utf-8')
    after_settings, handler_receipt = _handler_update(before_settings)
    axes = _input_axes(project)
    manifest = project / 'Packages/manifest.json'
    packages = json.loads(manifest.read_text())
    authored_package = packages.get('dependencies', {}).get(PACKAGE[0])
    # Preserve an authored package/version; only supply the missing dependency.
    cache = None if authored_package else package_root()
    changes = []
    for path in sorted((project / 'Assets').rglob('*.cs')):
        if 'GameFactoryInput' in path.name:
            continue
        before = path.read_text(errors='replace')
        after = migrate_device_reads(before)
        if after != before:
            path.write_text(after)
            changes.append({'path': str(path.relative_to(project)), 'before_sha256': _sha(before),
                            'after_sha256': _sha(after), 'kind': 'input_device_reads_only'})
    shim = project_snapshot.input_shim()
    shim_dir = project / 'Assets/GameFactoryInputMigration'
    shim_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(shim, shim_dir / 'GameFactoryInput.cs')
    (shim_dir / 'GameFactoryInputMigration.asmdef').write_text(json.dumps(
        {'name': 'GameFactoryInputMigration', 'references': ['Unity.InputSystem'], 'autoReferenced': True},
        indent=2) + '\n')
    for change in changes:                      # authored assembly definitions must see the shim
        parent = (project / change['path']).parent
        while parent != project:
            defs = list(parent.glob('*.asmdef'))
            if defs:
                if len(defs) != 1:
                    raise ValueError(f'ambiguous assembly definition near {change["path"]}')
                data = json.loads(defs[0].read_text())
                refs = data.setdefault('references', [])
                if 'GameFactoryInputMigration' not in refs:
                    refs.append('GameFactoryInputMigration')
                    defs[0].write_text(json.dumps(data, indent=2) + '\n')
                break
            parent = parent.parent
    settings.write_bytes(after_settings.encode('utf-8'))
    resource = project / 'Assets/Resources/GameFactoryInputAxes.json'
    resource.parent.mkdir(parents=True, exist_ok=True)
    resource.write_text(json.dumps({'axes': axes}, ensure_ascii=False, indent=2) + '\n')
    if cache is not None:
        packages.setdefault('dependencies', {})[PACKAGE[0]] = 'file:' + str(cache)
        manifest.write_text(json.dumps(packages, indent=2) + '\n')
    receipt = {'version': VERSION, 'migrated': True, 'scope': 'isolated eval copy; original delivery unchanged',
               'project': str(project.resolve()), 'changes': changes, 'gameplay_changes': [],
               'shim_sha256': hashlib.sha256(shim.read_bytes()).hexdigest(), 'axis_count': len(axes),
               'input_handler': {**handler_receipt, 'before_sha256': _sha(before_settings),
                                 'after_sha256': _sha(after_settings)},
               'input_system_package': str(cache) if cache else authored_package,
               'input_system_package_origin': 'harness_added' if cache else 'author_preserved',
               'input_system_package_version': PACKAGE[1] if cache else authored_package,
               'input_system_package_manifest_sha256': hashlib.sha256((cache / 'package.json').read_bytes()).hexdigest() if cache else None}
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
    return receipt
