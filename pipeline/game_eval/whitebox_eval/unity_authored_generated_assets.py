"""Declare reviewed authored outputs already present in a qualified G039 recording.

This only binds native-produced files to their unchanged creator and captured SHA.
It never creates assets or alters frozen source, scoring denominators or verdicts.
"""
from pathlib import Path
from . import batch
from .protocol import sha, dump
from . import unity_authored_settings_import as settings

REVIEW = {'case': 'Astra__G039_sky_ring_flight', 'recorded_name': 'Astra__G039_sky_ring_flight__single_endpoint_v2_1793429662250961000', 'recorded_attempt': 'test_data/outputs/eval/playtest/whitebox_eval_godot_threejs_5models_20261023_retry/recovery_runs/Astra__G039_sky_ring_flight__single_endpoint_v2_1793429662250961000', 'generated_files': {'Assets/Resources/LitBase.mat': 'ca8deae78b3dd9db0010130ef0a65903711b41000c6f45a599f8bd10f3a4f07f', 'Assets/Resources/UnlitBase.mat': 'dfd82ae072c7566171b5a21b6ab7d25dd0faf9274e45846e98c4ce72c7281f0f', 'Assets/Resources/SkyRenderer.asset': 'd54f73635b9750f36757dab7c4a5b831e544ef2e3f644d524333853f79fb05e5', 'Assets/Resources/SkyURP.asset': '226d355e5d253cb20a355f95778e11106009de4c75ecd3216905a8a5a08ea88a'}, 'metadata': {'Assets/Resources/LitBase.mat.meta': 'b1e809197c69550696909bdb805e10f704bf387f1a531378d8c63657c92ab8b7', 'Assets/Resources/UnlitBase.mat.meta': 'ff975fd90868436f30f75f0d1e16ebe409b174431bfc6227f789dba6b66b1bb3', 'Assets/Resources/SkyRenderer.asset.meta': '41f38f43f6494bc37283756de4ef4e67bec2f938f791be966c157e8bdd13004a', 'Assets/Resources/SkyURP.asset.meta': 'd93ff3fad95e13f001fb46be1714f297345e4162825148da106478825764d5e7'}, 'package_bindings': {'Library/PackageCache/com.unity.render-pipelines.universal@14.2.0-t1/Runtime/UniversalRendererData.cs': '147a8a551de8013be1e085c3d6bbfff27f0b0d9052e980d8c190e42436cb36ef', 'Library/PackageCache/com.unity.render-pipelines.universal@14.2.0-t1/Runtime/UniversalRendererData.cs.meta': '65bb0c3e6416b350ae0e3c0d175181217618032a0f0c429ddce0ad82a930bf88', 'Library/PackageCache/com.unity.render-pipelines.universal@14.2.0-t1/Runtime/Data/UniversalRenderPipelineAsset.cs': '1d2ebc19a9441070c241bc401d02cae06ac1970530ef0619f6c0ba74b5a96df3', 'Library/PackageCache/com.unity.render-pipelines.universal@14.2.0-t1/Runtime/Data/UniversalRenderPipelineAsset.cs.meta': 'f023b0f31acc4b3cd7530fc27bdc0fcdd550afe1f93f077e49556bea64a7995a', 'Library/PackageCache/com.unity.render-pipelines.universal@14.2.0-t1/Shaders/Lit.shader': '45014f4a9d09f2e43ad456710daaecb751a275c0658280c01f34dd013daae8f3', 'Library/PackageCache/com.unity.render-pipelines.universal@14.2.0-t1/Shaders/Lit.shader.meta': 'f0db005307ffe5480c40a402ca5bfb0b3726259031a86e255e49626228ceb008', 'Library/PackageCache/com.unity.render-pipelines.universal@14.2.0-t1/Shaders/Unlit.shader': '17f55b0daf4c981a3ceb5c34536d3037c9247993f026b7faa6f43edb34549ed6', 'Library/PackageCache/com.unity.render-pipelines.universal@14.2.0-t1/Shaders/Unlit.shader.meta': '367956a85cb4183e5f8afd33b78f3a048fe08d5767e42e11b4b127b780acfaf2'}, 'script_sha256': '212f53a068ebb487433d8b14df33dec842a786de4e6616112940177b8599e76b', 'script_physical_lines': {'renderer': 13, 'pipeline': 14, 'materials': 16}, 'source_manifest_sha256': 'c44b5e15774e1e2dc1aa24c2a311c5db4ce7d23dbc2595470d2f123a83bd56b2', 'source_snapshot_sha256': '47b2e309a946a5b9c51abc283889d310b99d6e1340e2c0277e65df3f9141b881', 'capture_verification_sha256': '789c8abbe3d74b8fef110d19e53a4943ff212e5dbe9cf72e6e94a70ada71060f', 'review': 'Exact unchanged InitializeOnLoad Configure creates missing renderer/pipeline and Lit/Unlit materials. Actual captured YAML kept byte-for-byte. Frozen input lacks these four files; declaration only records their existing captured outputs and package source GUID bindings; asset denominator and frozen rubric unchanged.'}
RECEIPT = 'authored_generated_assets.json'


def proof(recorded):
    recorded = Path(recorded).resolve()
    if recorded.name != REVIEW['recorded_name']:
        return []
    manifest = batch.read(recorded/'input_manifest.json')
    if manifest['entry']['id'] != REVIEW['case']:
        raise ValueError('Generated asset case identity differs')
    for name, key in [('input_manifest.json','source_manifest_sha256'),
                      ('background_record/source_snapshot.json','source_snapshot_sha256'),
                      ('background_record/verification.json','capture_verification_sha256')]:
        if sha(recorded/name) != REVIEW[key]:
            raise ValueError('Generated asset capture/source binding differs: '+name)
    if not settings.proof(recorded):
        raise ValueError('Unchanged authored Configure and qualified capture required')
    captured = recorded/'background_record/project'
    for name,digest in {**REVIEW['generated_files'], **REVIEW['metadata'], **REVIEW['package_bindings']}.items():
        if sha(captured/name) != digest:
            raise ValueError('Reviewed generated/package bytes differ: '+name)
    rows=[]
    source_snapshot=batch.read(recorded/'background_record/source_snapshot.json')['files_sha256']
    for name,digest in REVIEW['generated_files'].items():
        if (name in manifest['snapshot_hashes'] or name in source_snapshot
                or (recorded/'input/project'/name).exists()):
            raise ValueError('Generated asset was already in original input: '+name)
        rows.append({'path':name,'sha256':digest,'source':str(captured/name),
            'kind':'authored_editor_generated_asset.v1','author_script':settings.SCRIPT,
            'author_script_sha256':settings.SCRIPT_SHA,
            'author_line':REVIEW['script_physical_lines']['materials' if name.endswith('.mat') else 'renderer' if 'SkyRenderer' in name else 'pipeline'],
            'metadata_sha256':REVIEW['metadata'][name+'.meta']})
    return rows


def declare(recorded, attempt):
    """Require captured/runtime byte identity before extending the exact declaration."""
    attempt=Path(attempt); rows=proof(recorded)
    if not rows:
        return []
    path=attempt/'runtime/instrumentation_manifest.json'; manifest=batch.read(path)
    if not isinstance(manifest,dict) or not isinstance(manifest.get('added_files'),list):
        raise ValueError('Expected exact native installation declaration')
    original=manifest['added_files']; existing={row['path']:row for row in original}
    if len(existing)!=len(original):
        raise ValueError('Duplicate native declaration path')
    for row in rows:
        if sha(attempt/'runtime/project'/row['path'])!=row['sha256']:
            raise ValueError('Runtime generated asset differs from native capture')
        if row['path'] in existing and existing[row['path']] != row:
            raise ValueError('Conflicting generated asset declaration')
    receipt={'schema':'unity-authored-generated-assets.v1','source_attempt':str(Path(recorded).resolve()),
        'review':REVIEW,'files':rows,'frozen_input_unchanged':True,
        'semantics':'Declare actual recorded author callback outputs; no generated gameplay, changed rubric, denominator, evidence requirement or rendering equivalence claim.'}
    target=attempt/RECEIPT
    if target.exists() and batch.read(target)!=receipt:
        raise ValueError('Prior authored asset declaration differs')
    for row in rows:
        if row['path'] not in existing:original.append(row)
    dump(path,manifest);dump(target,receipt)
    return rows
