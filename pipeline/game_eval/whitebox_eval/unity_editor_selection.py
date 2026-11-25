"""Choose a verified Editor from actual serialized delivery format.

ProjectVersion alone is insufficient: some delivered Tuanjie projects have a
Unity version marker but keep Tuanjie YAML namespaces and encoded asset GUIDs.
No source bytes, packages or gameplay are changed by this inspection.
"""
from pathlib import Path
import hashlib
import json
import re


class EditorCompatibilityError(RuntimeError):
    failure_class = 'EDITOR_COMPATIBILITY'


class NativeAdmissionError(RuntimeError):
    def __init__(self, message, failure_class):
        super().__init__(message)
        self.failure_class = failure_class


def editor_family(editor, version=''):
    value = str(editor)+' '+version
    return 'tuanjie' if re.search(r'tuanjie|\d+t\d+', value, re.I) else 'unity'


def editor_version(editor):
    return next((part for part in reversed(Path(editor).parts)
                 if re.fullmatch(r'\d+\.\d+\.\d+[a-z]\d+(?:c\d+)?', part)), '')


def delivery_format(project, scenes):
    project = Path(project)
    evidence = []
    def record(path, reason):
        evidence.append({'path':str(path.relative_to(project)), 'reason':reason,
                         'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    marker = project/'ProjectSettings/ProjectVersion.txt'
    text = marker.read_text(errors='replace') if marker.is_file() else ''
    match = re.search(r'(?m)^m_EditorVersion:\s*(\S+)', text)
    version = match[1] if match else None
    if version and editor_family('', version) == 'tuanjie':
        record(marker, 'Tuanjie Editor version')
    for relative in scenes[:8]:
        scene = project/relative
        with scene.open('rb') as stream:
            head = stream.read(512)
        if b'tag:yousandi.cn,' in head:
            record(scene, 'Tuanjie serialized YAML namespace')
        meta = scene.with_suffix(scene.suffix+'.meta')
        if meta.is_file():
            guid = re.search(r'(?m)^guid:\s*(\S+)', meta.read_text(errors='replace'))
            if guid and re.fullmatch(r'[A-Za-z0-9+/]{40,}={0,2}', guid[1]) and not re.fullmatch(r'[a-fA-F0-9]{32}', guid[1]):
                record(meta, 'Encoded Tuanjie asset GUID; incompatible with ordinary Unity GUID parser')
    manifest = project/'Packages/manifest.json'
    if manifest.is_file():
        dependencies = json.loads(manifest.read_text()).get('dependencies', {})
        if any('tuanjie' in key or key == 'com.unity.modules.infinity'
               or isinstance(value,str) and re.search(r'-t\d+$', value)
               for key,value in dependencies.items()):
            record(manifest, 'Tuanjie-specific package dependency')
    return {'family':'tuanjie' if evidence else 'unity', 'source_editor_version':version,
            'evidence':evidence}


def choose_editor(format_record, acceptances):
    compatible = [value for value in acceptances.values()
                  if editor_family(value['editor'], value.get('editor_version','')) == format_record['family']]
    exact = [value for value in compatible if value.get('editor_version') == format_record['source_editor_version']]
    return next(iter(exact or compatible), None)


def failure_classification(log):
    """Import failure is not proof of a product bug or missing scene."""
    if (any(token in log.lower() for token in ('error when resolving packages', 'error occurred while resolving packages', 'invalid dependencies'))
            or re.search(r'com\.[\w.-]+(?:@[\w.-]+)?.{0,160}(?:cannot|could not) be found', log)):
        return 'DEPENDENCY'
    if any(token in log for token in ('GUID inside', 'Invalid version provided', 'tag:yousandi.cn')):
        return 'EDITOR_COMPATIBILITY'
    if re.search(r'error CS\d+', log):
        return 'PRODUCT'
    return 'HARNESS'
