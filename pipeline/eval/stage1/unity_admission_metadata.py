"""Prove removal of an inert, generated native-admission helper sidecar.

Only derived judge inputs are normalized. Original author, frozen admission,
and captured projects remain untouched; runtime source validation stays strict.
"""
from pathlib import Path
import re
from . import batch
from .protocol import sha

PATH = 'Assets/GameFactory3AEvaluation/Editor/WhiteboxNativeOpen.cs.meta'
SCRIPT = PATH[:-5]
FIELD = 'orphan_admission_metadata'
SHAPE = re.compile(r'fileFormatVersion: 2\nguid: ([A-Za-z0-9+/=]+)\nMonoImporter:\n  externalObjects: \{\}\n  serializedVersion: 2\n  defaultReferences: \[\]\n  executionOrder: 0\n  icon: \{instanceID: 0\}\n  userData: *\n  assetBundleName: *\n  assetBundleVariant: *\n')


def proof(recorded, relative):
    if relative != PATH:
        return None
    recorded = Path(recorded).resolve()
    manifest = batch.read(recorded/'input_manifest.json')
    binding = manifest['entry'].get('native_open_admission')
    if not binding:
        raise ValueError('Orphan helper metadata lacks native admission binding')
    native = Path(binding['receipt'])
    if sha(native) != binding['sha256']:
        raise ValueError('Native admission receipt SHA changed')
    receipt = batch.read(native)
    snapshot_path = Path(receipt['source_snapshot'])
    snapshot = batch.read(snapshot_path)
    original = Path(binding['original_project']).resolve()
    frozen = recorded/'input/project'
    captured = recorded/'background_record/project'
    if (receipt.get('schema') != 'whitebox-openable-delivery.v1'
            or receipt.get('id') != manifest['entry']['id']
            or Path(receipt['source_project']).resolve() != original
            or Path(snapshot['source']).resolve() != original
            or Path(receipt['project']).resolve() != Path(manifest['entry']['project']).resolve()
            or receipt.get('product_status') != 'OPENED'
            or receipt.get('source_unchanged', {}).get('ok') is not True
            or receipt.get('execution', {}).get('owned_process_exited') is not True
            or receipt.get('execution', {}).get('exit_code') != 0
            or receipt.get('execution', {}).get('timed_out') is not False
            or any(receipt.get('cleanup', {}).get(k) is not True
                   for k in ('input_cleanup','view_cleanup','process_cleanup'))):
        raise ValueError('Orphan helper metadata admission provenance is incomplete')
    if snapshot.get('policy') != 'unity-authored-project-snapshot.v1':
        raise ValueError('Unknown authored source snapshot')
    authored = snapshot['files_sha256']
    expected = manifest['snapshot_hashes']
    if receipt['project_hashes'] != expected or batch.hashes(frozen) != expected:
        raise ValueError('Admission helper metadata does not bind frozen source')
    if any(p in authored for p in (PATH, SCRIPT)):
        raise ValueError('Refuse to normalize authored helper metadata')
    from engine_adapters.unity3d.playtest.project_snapshot import snapshot_files
    actual_authored = {str(p.relative_to(original)):sha(p) for p in snapshot_files(original, [])}
    if actual_authored != authored:
        raise ValueError('Original author source file set or SHA changed')
    for name, digest in authored.items():
        if not (original/name).is_file() or sha(original/name) != digest:
            raise ValueError('Original author source changed: '+name)
    for project, names in ((original,(PATH,SCRIPT)),(frozen,(SCRIPT,)),(captured,(PATH,SCRIPT))):
        if any((project/name).exists() for name in names):
            raise ValueError('Helper source or captured metadata is present')
    raw = (frozen/PATH).read_bytes()
    match = SHAPE.fullmatch(raw.decode('utf-8'))
    if not match or sha(frozen/PATH) != expected.get(PATH):
        raise ValueError('Helper metadata is not an inert default MonoImporter')
    guid = match[1].encode()
    checked = {}
    for label,project,files in (('author',original,authored),('frozen',frozen,expected),
                                ('captured',captured,batch.hashes(captured))):
        for name in files:
            if name != PATH and guid in (project/name).read_bytes():
                raise ValueError('Helper metadata GUID is referenced: '+label+'/'+name)
        checked[label] = len(files) - int(PATH in files)
    return {'kind':'generated_orphan_native_admission_metadata','path':PATH,
        'before_sha256':sha(frozen/PATH),'after_sha256':None,
        'raw_metadata_utf8':raw.decode(), 'guid':match[1],
        'recorded_attempt':str(recorded), 'native_receipt':str(native),
        'native_receipt_sha256':sha(native),'source_snapshot':str(snapshot_path),
        'source_snapshot_sha256':sha(snapshot_path),'source_manifest_sha256':sha(recorded/'input_manifest.json'),
        'unreferenced_files_checked':checked,
        'policy':'Remove only this proven generated orphan sidecar from the derived judge input. Preserve author, frozen admission, capture, source checks and scoring rules.'}


def audit_binding(root):
    root = Path(root)
    version = batch.read(root/'input_manifest.json')['entry'].get('recorded_source_version', {})
    rows = version.get(FIELD, [])
    if not rows:
        return {}
    if len(rows) != 1 or rows[0].get('path') != PATH:
        raise ValueError('Unexpected orphan admission metadata normalization')
    row = rows[0]
    expected = proof(Path(row['recorded_attempt']), PATH)
    if row != expected:
        raise ValueError('Orphan admission metadata proof changed')
    for project in (root/'input/project',root/'runtime/project',Path(version['version_project'])):
        if (project/PATH).exists() or (project/SCRIPT).exists():
            raise ValueError('Derived judge helper artifact unexpectedly present')
    paths = [Path(row['native_receipt']),Path(row['source_snapshot']),
             Path(row['recorded_attempt'])/'input_manifest.json',
             Path(row['recorded_attempt'])/'input/project'/PATH]
    return {str(p):sha(p) for p in paths}


def plan_paths(root, source, before, after):
    """The same provenance check at preparation and independent plan validation."""
    root, source = Path(root), Path(source).resolve()
    rows = batch.read(root/'input_manifest.json')['entry'].get('recorded_source_version', {}).get(FIELD, [])
    if not rows:
        return set()
    audit_binding(root)
    for row in rows:
        if (Path(row['recorded_attempt']).resolve() != source
                or before.get(row['path']) != row['before_sha256']
                or row['path'] in after):
            raise ValueError('Recorded plan orphan metadata source proof differs')
    return {row['path'] for row in rows}
