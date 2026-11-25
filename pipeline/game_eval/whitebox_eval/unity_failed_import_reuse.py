"""Qualify stopped failed-run imports separately from valid recordings.

Only exact engine initialization serialization can differ from frozen source.
The package implementation and its resource GUIDs are source bound; every
other authored byte is still exact. This never qualifies a failed recording.
"""
from pathlib import Path
import re
from . import batch
from .protocol import sha

VERSION = 'unity-stopped-failed-import-only.v1'
PACKAGE = 'Library/PackageCache/com.unity.render-pipelines.universal@14.2.0-t1'
ENGINE = {
 'Runtime/UniversalRenderPipeline.cs':'5d2a688f2c32b001aae56b0deb23b4f07b60da7860ae46a8372d278862b5d19b',
 'Runtime/Data/UniversalRenderPipelineAsset.cs':'1d2ebc19a9441070c241bc401d02cae06ac1970530ef0619f6c0ba74b5a96df3',
 'Textures/BlueNoise64/L/LDR_LLL1_0.png':'140c55bd97c21b9b22008d7054b492333fec67fbfc1a1b266e5b0209b647eed4',
 'Textures/BlueNoise64/L/LDR_LLL1_0.png.meta':'979f79be8dce3792e58e15f20f925615ee7191b535d27fac1be2221c430efd16',
 'Textures/BayerMatrix.png':'ab857985cb2fbbda35a23b55d0da84e26684cf8979ae777341e9dd9b952d940c',
 'Textures/BayerMatrix.png.meta':'6f72db8797ac40573c8b72a8d00b144ff678e5e126045d483300002ebf7b1df9',
}
ASSET = 'Assets/Settings/WaterworksURP.asset'
GRAPHICS = 'ProjectSettings/GraphicsSettings.asset'

def engine_initialization(source, project):
    """Prove exact null->package defaults and false->URP runtime assignment.

    ResourceReloader fills these null fields on asset.textures access; URP
    writes lightsUseColorTemperature=true every rendered frame. Both frozen
    and saved inputs therefore reach the same values before rendering. No
    active-pipeline GUID is decoded, rewritten, inferred or replaced.
    """
    source,project=Path(source),Path(project)
    pkg=project/PACKAGE
    for name,digest in ENGINE.items():
        if not (pkg/name).is_file() or sha(pkg/name)!=digest:
            raise ValueError('Engine implementation/resource identity changed: '+name)
    old=(source/ASSET).read_bytes();expected=old
    for field,name in [('blueNoise64LTex','Textures/BlueNoise64/L/LDR_LLL1_0.png'),
                       ('bayerMatrixTex','Textures/BayerMatrix.png')]:
        guid=re.findall(r'^guid: ([0-9a-f]{32})$',(pkg/(name+'.meta')).read_text(),re.M)
        before=('    '+field+': {fileID: 0}').encode()
        if len(guid)!=1 or expected.count(before)!=1:
            raise ValueError('Expected exact engine null/default field absent')
        after=('    '+field+': {fileID: 2800000, guid: '+guid[0]+', type: 3}').encode()
        expected=expected.replace(before,after)
    actual=(project/ASSET).read_bytes()
    if actual not in (old,expected):raise ValueError('Unproved authored rendering asset change')
    original=(source/GRAPHICS).read_bytes();before=b'  m_LightsUseColorTemperature: 0'
    if original.count(before)!=1:raise ValueError('Original graphics setting differs')
    imported=(project/GRAPHICS).read_bytes()
    if imported not in (original,original.replace(before,b'  m_LightsUseColorTemperature: 1')):
        raise ValueError('Unproved graphics setting change')
    return {n:sha(project/n) for n in (ASSET,GRAPHICS) if sha(project/n)!=sha(source/n)}

def validate_import(source,project,observer):
    """All authored bytes exact except source-proved engine initialization."""
    source,project=Path(source),Path(project)
    before=batch.hashes(source);current=batch.hashes(project)
    allowed=engine_initialization(source,project)
    if any(current.get(n)!=allowed.get(n,d) for n,d in before.items()):
        raise ValueError('Failed import contains authored source drift')
    installation='Assets/GameFactory3AEvaluation/installation.json'
    if batch.read(project/installation)!={'schema':'unity-observer-installation.v1','files':observer}:
        raise ValueError('Imported observer binding changed')
    if any(current.get(n)!=d for n,d in observer.items()):
        raise ValueError('Imported observer source changed')
    extras=set(current)-set(before)-set(observer)-{installation}
    # Only metadata for these exact evaluation additions may be generated.
    allowed_meta={n+'.meta' for n in set(observer)|{installation}}
    for name in observer:
        allowed_meta.update(str(parent)+'.meta' for parent in Path(name).parents
                            if str(parent).startswith('Assets/GameFactory3AEvaluation/'))
    if extras-allowed_meta:raise ValueError('Unreviewed imported source addition')
    return current,allowed

def verify(source,project_root,receipt):
    from .unity_native_pair_record import process_identities
    receipt=Path(receipt);value=batch.read(receipt)
    if (value.get('schema')!=VERSION or value.get('recording_qualified') is not False
            or value.get('import_only') is not True):raise ValueError('Invalid import-only qualification')
    if value['source']!=str(Path(source).resolve()) or value['project_root']!=str(Path(project_root).resolve()):
        raise ValueError('Import-only qualification belongs to other source/root')
    if value['source_hashes']!=batch.hashes(Path(source)):raise ValueError('Frozen import source changed')
    for name,digest in value['bindings'].items():
        if sha(Path(name))!=digest:raise ValueError('Failed import proof changed: '+name)
    original=Path(value['failed_capture']);failed=batch.read(original/'result.json')
    if failed.get('status')!='HARNESS_ERROR' or failed.get('ok') is not False:
        raise ValueError('Original failed recording must remain failed')
    cleanup=batch.read(Path(value['post_exit_cleanup']))
    if (cleanup.get('schema')!='unity-native-pair-post-exit-cleanup.v1'
            or cleanup.get('capture')!=str(original) or cleanup.get('recording_qualified') is not False
            or not all(cleanup.get('checks',{}).get(k) is True for k in
                       ('input_cleanup','view_cleanup','process_cleanup','source_unchanged'))
            or cleanup.get('original_cleanup_sha256')!=sha(original/'cleanup.json')):
        raise ValueError('Independent post-exit cleanup not proved')
    for name,digest in cleanup['worker_cleanup_bindings'].items():
        if sha(Path(name))!=digest:raise ValueError('Worker cleanup proof changed')
    identities=process_identities();owned=set(cleanup['owned_ids'])
    if any(pid in owned or row['pgid'] in owned or
           str(Path(project_root).resolve()) in row['command'] for pid,row in identities.items()):
        raise ValueError('Imported clients still occupied')
    for role in ('A','B'):
        project=Path(project_root)/('project_'+role)
        if project.is_symlink():raise ValueError('Imported project symlink forbidden')
        current,allowed=validate_import(source,project,value['observer'])
        if current!=value['projects'][role] or allowed!=value['engine_serialization'][role]:
            raise ValueError('Imported project changed since qualification')
    return {'receipt':str(receipt),'receipt_sha256':sha(receipt),
            'import_only':True,'recording_qualified':False,
            'failed_capture':str(original),'post_exit_cleanup_sha256':sha(Path(value['post_exit_cleanup']))}
