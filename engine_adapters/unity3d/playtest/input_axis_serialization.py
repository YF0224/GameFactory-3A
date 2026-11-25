"""Lossless correction of a generated legacy-axis resource's name field."""
import copy
import hashlib
import json
import re
from pathlib import Path

RESOURCE = 'Assets/Resources/GameFactoryInputAxes.json'
SETTINGS = 'ProjectSettings/InputManager.asset'
VERSION = 'unity-generated-axis-name-serialization.v1'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical_axes(axes):
    result = copy.deepcopy(axes)
    if not isinstance(result, list):
        raise ValueError('Input axes must be a list')
    for axis in result:
        if not isinstance(axis, dict) or not isinstance(axis.get('m_Name'), str):
            raise ValueError('Missing authored input axis name')
        if 'name' in axis:
            raise ValueError('Conflicting input axis name fields')
        axis['name'] = axis.pop('m_Name')
    return result


def projection(source):
    """Qualify only our generated resource, against the actual authored settings."""
    source = Path(source)
    resource = source / RESOURCE
    if not resource.exists():
        return None
    original = json.loads(resource.read_text())
    axes = original.get('axes')
    if not isinstance(axes, list):
        raise ValueError('Malformed generated input axis resource')
    if not any(isinstance(a, dict) and 'm_Name' in a for a in axes):
        return None
    import yaml
    text = (source / SETTINGS).read_text()
    text = '\n'.join(line for line in text.splitlines() if not line.startswith('%'))
    text = re.sub(r'--- !u!\d+ &\d+', '---', text)
    authored = yaml.safe_load(text)['InputManager']['m_Axes']
    if original != {'axes': authored}:
        raise ValueError('Generated axes differ from authored InputManager; refuse correction')
    from .project_snapshot import input_shim
    accepted_shim = input_shim()
    candidates = [source/'Assets/GameFactoryInputMigration/GameFactoryInput.cs', source/'Assets/GameFactoryInput.cs']
    matches = [p for p in candidates if p.is_file() and digest(p) == digest(accepted_shim)]
    if len(matches) != 1:
        raise ValueError('Axis correction requires the exact accepted input shim')
    payload = (json.dumps({'axes':canonical_axes(authored)}, ensure_ascii=False, indent=2)+'\n').encode()
    proof = {'version':VERSION, 'path':RESOURCE, 'before_sha256':digest(resource),
             'after_sha256':hashlib.sha256(payload).hexdigest(),
             'settings_path':SETTINGS, 'settings_sha256':digest(source/SETTINGS),
             'shim_path':str(matches[0].relative_to(source)), 'shim_sha256':digest(matches[0]),
             'axis_count':len(authored), 'only_axis_name_field_changed':True, 'gameplay_changes':[]}
    return payload, proof


def normalize_snapshot(source, destination):
    qualified = projection(source)
    if qualified is None:
        return None
    payload, proof = qualified
    target = Path(destination)/RESOURCE
    if digest(target) != proof['before_sha256']:
        raise ValueError('Snapshot axis resource differs before normalization')
    target.write_bytes(payload)
    return proof


def verify_snapshot(source, destination, proof):
    qualified = projection(source)
    if qualified is None or qualified[1] != proof:
        raise ValueError('Axis normalization proof differs from authored source')
    if (Path(destination)/RESOURCE).read_bytes() != qualified[0]:
        raise ValueError('Normalized input axes changed after recording')
    return RESOURCE
