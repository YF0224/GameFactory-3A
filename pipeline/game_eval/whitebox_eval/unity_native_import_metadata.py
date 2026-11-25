"""Prove exact non-gameplay native Tuanjie import metadata in captured sources.

This does not claim rendering equivalence: the actual imported project is copied
and bound to its own static review identity by prepare_unity_recorded_judge.
"""
from pathlib import Path
import json
import re
from .protocol import sha

VERSION='unity-recorded-native-editor-import.v1'
FIELD='native_editor_import_metadata'
TAG_OLD='%TAG !u! tag:unity3d.com,2011:'
TAG_NEW='%TAG !u! tag:yousandi.cn,2023:'
PATHS={'Packages/manifest.json','ProjectSettings/ShaderGraphSettings.asset',
       'ProjectSettings/UnityConnectSettings.asset','UserSettings/EditorUserSettings.asset',
       'Assets/Settings/M_berth.mat','Assets/Settings/URP-Asset.asset'}

URP_PACKAGE='com.unity.render-pipelines.universal'
URP_VERSION='14.2.0-t1'
URP_RESOURCES={
    'Textures/BlueNoise64/L/LDR_LLL1_0.png': 'e3d24661c1e055f45a7560c033dbb837',
    'Textures/BayerMatrix.png': 'f9ee4ed84c1d10c49aabb9b210b0fc44',
}

def editor_recent_scene(before, after):
    """Invert one native recent-scene insertion; every other byte is retained."""
    if (before.count(TAG_NEW+'\n') != 1 or TAG_OLD in before
            or before.count('EditorUserSettings:\n') != 1
            or before.count('  serializedVersion: 6\n') != 1
            or before.count('  m_ConfigSettings:\n') != 1
            or 'RecentlyUsedSceneGuid' in before):
        raise ValueError('Exact original schema-6 Editor settings required')
    pattern = r'(?m)^    RecentlyUsedSceneGuid-0:\n      value: [0-9a-f]+\n      flags: 0\n'
    blocks = list(re.finditer(pattern, after))
    if len(blocks) != 1 or after.count('RecentlyUsedSceneGuid') != 1:
        raise ValueError('Only one native recent-scene entry permitted')
    block = blocks[0]
    prefix = '  m_ConfigSettings:\n'
    if (after[:block.start()] != before[:before.index(prefix)+len(prefix)]
            or after[:block.start()]+after[block.end():] != before):
        raise ValueError('Editor preferences changed beyond recent-scene insertion')
    return {'kind':'editor_recent_scene_guid_0_only',
            'inverse_restores_original_bytes':True,'gameplay_settings_changed':False}


def _urp_resource_proof(recorded_project, log):
    project=Path(recorded_project)
    package=project/'Library/PackageCache'/(URP_PACKAGE+'@'+URP_VERSION)
    package_json=package/'package.json'
    lock=project/'Packages/packages-lock.json'
    if package.is_symlink() or package_json.is_symlink() or lock.is_symlink():
        raise ValueError('Captured URP package provenance must not use symlinks')
    package_data=json.loads(package_json.read_text())
    lock_data=json.loads(lock.read_text())
    if package_data.get('name')!=URP_PACKAGE or package_data.get('version')!=URP_VERSION:
        raise ValueError('Captured URP package version differs')
    lock_entry=lock_data.get('dependencies',{}).get(URP_PACKAGE)
    if (not isinstance(lock_entry,dict) or lock_entry.get('version')!='12.1.15'
            or lock_entry.get('source')!='builtin'
            or lock_entry.get('dependencies',{}).get('com.unity.render-pipelines.core')!=URP_VERSION
            or lock_entry.get('dependencies',{}).get('com.unity.shadergraph')!=URP_VERSION
            or lock_entry.get('dependencies',{}).get('com.unity.render-pipelines.universal-config')!=URP_VERSION):
        raise ValueError('Captured packages-lock URP dependency resolution differs')
    resources=[]
    log_lines=log.splitlines()
    for relative,guid in URP_RESOURCES.items():
        asset=package/relative
        meta=Path(str(asset)+'.meta')
        if (asset.is_symlink() or meta.is_symlink() or not asset.is_file()
                or not meta.is_file()):
            raise ValueError('Captured URP package resource missing or symlinked: '+relative)
        meta_text=meta.read_text()
        if re.findall(r'(?m)^guid: ([0-9a-f]+)$',meta_text)!=[guid]:
            raise ValueError('Captured URP resource GUID differs: '+relative)
        package_log_path='Packages/'+URP_PACKAGE+'/'+relative
        matches=[n for n,line in enumerate(log_lines,1)
                 if line.startswith(('Start importing '+package_log_path+' using Guid('+guid+') ').encode())]
        if len(matches)!=1:
            raise ValueError('Native URP resource import log is not unique: '+relative)
        resources.append({'path':relative,'guid':guid,
                          'asset':str(asset),'asset_sha256':sha(asset),
                          'meta':str(meta),'meta_sha256':sha(meta),
                          'log_physical_line':matches[0]})
    return {'package':str(package),'package_json':str(package_json),
            'package_sha256':sha(package_json),'package_version':URP_VERSION,
            'lock':str(lock),'lock_sha256':sha(lock),
            'lock_urp_entry':lock_entry,'resources':resources,
            'rendering_equivalence_claimed':False}


def exact_text(relative,before,after,recorded_project=None,log=None):
    """Return the reviewed transform only when every byte is accounted for."""
    if before == after:
        raise ValueError('No native metadata change')
    if relative == 'ProjectSettings/ShaderGraphSettings.asset':
        if before.count(TAG_OLD)!=1 or after!=before.replace(TAG_OLD,TAG_NEW):
            raise ValueError('ShaderGraph settings changed beyond the native YAML tag')
        return {'kind':'native_yaml_vendor_tag'}
    if relative == 'ProjectSettings/UnityConnectSettings.asset':
        for flag in ('m_Enabled','m_TestMode','m_TestInitMode'):
            if len(re.findall(r'(?m)^  '+flag+r': 0$',before))!=1:
                raise ValueError('Native cloud services were not disabled')
        mapping={'https://api.uca.cloud.unity3d.com/v1/events':'https://api.uca.cloud.tuanjie.cn/v1/events',
                 'https://cdp.cloud.unity3d.com/v1/events':'https://cdp.tuanjie.cn/v1/events',
                 'https://config.uca.cloud.unity3d.com':'https://config.uca.cloud.tuanjie.cn',
                 'https://dashboard.unity3d.com':'https://dashboard.tuanjie.cn'}
        expected=before
        for old,new in [(TAG_OLD,TAG_NEW),*mapping.items()]:
            if expected.count(old)!=1:raise ValueError('Unknown disabled native cloud metadata')
            expected=expected.replace(old,new)
        if after!=expected:raise ValueError('Native cloud metadata changed beyond disabled vendor URLs/tag')
        return {'kind':'disabled_native_cloud_vendor_metadata','services_enabled':False,'replacements':mapping}
    if relative == 'UserSettings/EditorUserSettings.asset':
        if 'RecentlyUsedSceneGuid' in after and 'RecentlyUsedSceneGuid' not in before:
            return editor_recent_scene(before,after)
        # Only native Editor schema migration and its two default preferences.
        expected=before
        for old,new in [(TAG_OLD,TAG_NEW),('  serializedVersion: 4\n','  serializedVersion: 6\n'),
                        ('  m_IdleImportWorkerShutdownDelay: 60000\n','  m_IdleImportWorkerShutdownDelay: 60000\n  m_DesiredBuildWorkerCount: 2\n'),
                        ('  m_ArtifactGarbageCollection: 1\n','  m_ArtifactGarbageCollection: 1\n  m_RemoveUnusedReferencesFromMaterial: 0\n')]:
            if expected.count(old)!=1:raise ValueError('Unknown native Editor preference migration')
            expected=expected.replace(old,new)
        if 'm_DesiredBuildWorkerCount:' in before or 'm_RemoveUnusedReferencesFromMaterial:' in before or after!=expected:
            raise ValueError('Other native Editor preferences changed')
        return {'kind':'editor_preferences_schema_4_to_6','gameplay_settings_changed':False}
    if relative == 'Assets/Settings/M_berth.mat':
        old='    - _Color: {r: 0.20784314, g: 0.8156863, b: 0.41568628, a: 1}\n'
        new='    - _Color: {r: 0.2078431, g: 0.8156863, b: 0.41568625, a: 1}\n'
        if before.count(old)!=1 or after!=before.replace(old,new):
            raise ValueError('M_berth material changed beyond native float serialization')
        return {'kind':'native_material_float_serialization',
                'property':'_Color','before':old.rstrip('\n'),'after':new.rstrip('\n'),
                'gameplay_settings_changed':False}
    if relative == 'Assets/Settings/URP-Asset.asset':
        if recorded_project is None or log is None:
            raise ValueError('URP asset proof requires captured project and Editor log')
        old_blue='    blueNoise64LTex: {fileID: 0}\n'
        old_bayer='    bayerMatrixTex: {fileID: 0}\n'
        new_blue='    blueNoise64LTex: {fileID: 2800000, guid: e3d24661c1e055f45a7560c033dbb837, type: 3}\n'
        new_bayer='    bayerMatrixTex: {fileID: 2800000, guid: f9ee4ed84c1d10c49aabb9b210b0fc44, type: 3}\n'
        if (before.count(old_blue)!=1 or before.count(old_bayer)!=1
                or after!=before.replace(old_blue,new_blue).replace(old_bayer,new_bayer)):
            raise ValueError('URP asset changed beyond fixed package resource references')
        return {'kind':'native_urp_asset_resource_references',
                'before_sha256':sha_bytes(before.encode()),
                'after_sha256':sha_bytes(after.encode()),
                'references':_urp_resource_proof(recorded_project,log)}
    raise ValueError('Unreviewed native metadata path')


def sha_bytes(value):
    import hashlib
    return hashlib.sha256(value).hexdigest()


def package_manifest(before,after,recorded_project,log):
    original=json.loads(before);observed=json.loads(after)
    key='com.unity.render-pipelines.universal'
    if set(original)!={'dependencies'} or set(observed)!={'dependencies'}:
        raise ValueError('Package manifest has unreviewed top-level changes')
    expected=json.loads(before)
    if expected['dependencies'].get(key)!='14.0.11':raise ValueError('Unknown recorded URP origin')
    expected['dependencies'][key]='14.2.0-t1'
    if observed!=expected:raise ValueError('Package manifest changed beyond native recorded URP resolution')
    message='  '+key+' from version 14.0.11 to 14.2.0-t1'
    physical=[n for n,line in enumerate(log.splitlines(),1) if line==message.encode()]
    if len(physical)!=1:raise ValueError('Native package replacement log not unique')
    project=Path(recorded_project)
    package=project/'Library/PackageCache/com.unity.render-pipelines.universal@14.2.0-t1/package.json'
    lock=project/'Packages/packages-lock.json'
    if package.is_symlink() or json.loads(package.read_text()).get('version')!='14.2.0-t1':
        raise ValueError('Captured URP package version differs')
    if json.loads(lock.read_text())['dependencies'][key]['version']!='14.2.0-t1':
        raise ValueError('Captured URP package lock differs')
    return {'kind':'native_urp_package_resolution','dependency':key,'before':'14.0.11','after':'14.2.0-t1',
            'package':str(package),'package_sha256':sha(package),'lock':str(lock),'lock_sha256':sha(lock),
            'native_log_physical_lines':physical,'native_log_text':message,
            'rendering_equivalence_claimed':False,'requires_actual_imported_static_identity':True}


def proof(recorded, *, native_input_baseline=False):
    recorded=Path(recorded).resolve();original=recorded/'input/project';project=recorded/'background_record/project'
    manifest=recorded/'input_manifest.json';snapshot=json.loads(manifest.read_text())['snapshot_hashes']
    migration=None
    if native_input_baseline:
        from .unity_m_input_adapter import materialization_proof
        migration=materialization_proof(recorded)
        original=Path(migration['isolated_project'])
    changed=[name for name in sorted(PATHS) if name in snapshot and (project/name).is_file()
             and sha(project/name)!=snapshot[name]
             # The migration is separately proven. Only subsequent native changes
             # belong here; never reinterpret an unchanged migrated package as URP.
             and not (native_input_baseline and (original/name).is_file()
                      and not (original/name).is_symlink()
                      and sha(original/name)==sha(project/name))]
    if not changed:return []
    verification=recorded/'background_record/verification.json';checked=json.loads(verification.read_text())
    if checked.get('status')!='CAPTURE_VERIFIED' or checked.get('ok') is not True or not all(
            checked.get('checks',{}).get(k) is True for k in ('input_cleanup','view_cleanup','process_cleanup','original_unchanged')):
        raise ValueError('Qualified native capture and cleanup required')
    log_path=project/'Library/GameFactory3A/Editor.log';log=log_path.read_bytes()
    version_path=project/'ProjectSettings/ProjectVersion.txt';version=version_path.read_text()
    version_match=re.search(r'(?m)^m_EditorVersion: (2022\.3\.62t13)$',version)
    if not version_match or ('Initialize engine version: '+version_match[1]).encode() not in log:
        raise ValueError('Exact captured Tuanjie Editor/version log required')
    result=[]
    for name in changed:
        before=original/name;after=project/name
        omitted = next((row for row in (migration or {}).get('editor_local_snapshot_exclusions',[])
                        if row['path']==name and row.get('native_editor_transform')),None)
        if omitted:
            if before.exists() or before.is_symlink():
                raise ValueError('Editor-local isolated omission changed')
            before=recorded/'input/project'/name
            if (name!='UserSettings/EditorUserSettings.asset' or before.is_symlink()
                    or sha(before)!=snapshot[name] or sha(before)!=omitted['original_sha256']
                    or sha(after)!=omitted['recorded_sha256']):
                raise ValueError('Frozen omitted Editor metadata identity changed')
        if before.is_symlink() or after.is_symlink() or (not native_input_baseline and sha(before)!=snapshot[name]):
            raise ValueError('Frozen native metadata identity changed')
        transform=(package_manifest(before.read_bytes().decode('utf-8'),after.read_bytes().decode('utf-8'),project,log) if name=='Packages/manifest.json'
                   else exact_text(name,before.read_bytes().decode('utf-8'),after.read_bytes().decode('utf-8'),project,log))
        result.append({'version':VERSION,'path':name,'before_sha256':snapshot[name],'recorded_sha256':sha(after),
                       'input_manifest_sha256':sha(manifest),'capture_verification_sha256':sha(verification),
                       'native_log':str(log_path),'native_log_sha256':sha(log_path),
                       'native_editor_version':version_match[1],'native_version_sha256':sha(version_path),
                       'transform':transform,'original_preserved':True,
                       **({'input_migration':migration,('original_editor_before_sha256' if omitted else 'isolated_before_sha256'):sha(before)} if migration else {})})
    return result


def plan_paths(root, recorded, before, after):
    """Recompute source-bound native metadata proof for the derived judge plan."""
    root = Path(root)
    version = json.loads((root/'input_manifest.json').read_text())['entry'].get('recorded_source_version',{})
    expected = proof(recorded, native_input_baseline='unity_m_input_materialization' in version)
    if version.get(FIELD,[]) != expected:
        raise ValueError('Recorded plan native import provenance changed')
    migration = {}
    if 'unity_m_input_materialization' in version:
        from .unity_m_input_adapter import materialization_proof
        migration = materialization_proof(recorded)
        if version['unity_m_input_materialization'] != migration:
            raise ValueError('Recorded plan input migration provenance changed')
    exclusions = {
        row['path']: row
        for row in migration.get('editor_local_snapshot_exclusions', [])
        if row.get('native_editor_transform', {}).get('inverse_restores_original_bytes') is True
    }
    for row in expected:
        path = row['path']
        excluded = exclusions.get(path)
        if excluded:
            if (path != 'UserSettings/EditorUserSettings.asset'
                    or excluded.get('original_sha256') != row['before_sha256']
                    or excluded.get('recorded_sha256') != row['recorded_sha256']
                    or before.get(path) != row['before_sha256']
                    or after.get(path) != row['before_sha256']
                    or sha(root/'input/project'/path) != row['before_sha256']):
                raise ValueError('Recorded plan native import exclusion differs')
            continue
        if (before.get(path) != row['before_sha256']
                or after.get(path) != row['recorded_sha256']
                or sha(root/'input/project'/path) != row['recorded_sha256']):
            raise ValueError('Recorded plan native import bytes differ')
    return {row['path'] for row in expected}
