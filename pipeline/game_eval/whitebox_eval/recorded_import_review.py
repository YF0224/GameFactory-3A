"""Check explicit receipts for Unity's imported built-in URP shader references."""
import json
from pathlib import Path
import re
import time

from pipeline.game_eval.whitebox_eval.protocol import sha


def shader_reference_changes(before, after, known_guids):
    original = before.splitlines()
    recorded = after.splitlines()
    if len(original) != len(recorded):
        raise ValueError('Renderer import changed its structure')
    section = None
    changes = []
    for previous, current in zip(original, recorded):
        heading = re.fullmatch(r'  ([A-Za-z_][A-Za-z_0-9]*):.*', previous)
        if heading:
            section = heading[1]
        if previous == current:
            continue
        empty = re.fullmatch(r'    ([A-Za-z_][A-Za-z_0-9]*): \{fileID: 0\}', previous)
        filled = re.fullmatch(r'    ([A-Za-z_][A-Za-z_0-9]*): \{fileID: 4800000, guid: ([0-9a-f]{32}), type: 3\}', current)
        if (section not in {'debugShaders','shaders'} or empty is None or filled is None
                or empty[1] != filled[1] or filled[2] not in known_guids):
            raise ValueError('Renderer change is not an empty built-in shader reference')
        changes.append({'field':section+'.'+empty[1], 'guid':filled[2]})
    if not changes:
        raise ValueError('Renderer review has no shader reference changes')
    return changes


def reviewed_axis_paths(recorded):
    from engine_adapters.unity3d.playtest.input_axis_serialization import verify_snapshot
    recorded = Path(recorded).resolve()
    snapshot_path = recorded/'background_record/source_snapshot.json'
    if not snapshot_path.is_file():
        return set()
    snapshot = json.loads(snapshot_path.read_text())
    proof = snapshot.get('input_axis_normalization')
    if proof is None:
        return set()
    if snapshot['source'] != json.loads((recorded/'input_manifest.json').read_text())['entry']['project']:
        raise ValueError('Axis normalization source differs from the frozen project')
    for relative in (proof['path'], proof['settings_path'], proof['shim_path']):
        if sha(recorded/'input/project'/relative) != snapshot['files_sha256'][relative]:
            raise ValueError('Axis normalization frozen source changed')
    relative = verify_snapshot(recorded/'input/project', recorded/'background_record/project', proof)
    return {relative}


def reviewed_import_paths(recorded):
    recorded = Path(recorded).resolve()
    path = recorded/'recorded_import_review.json'
    if not path.is_file():
        return reviewed_axis_paths(recorded)
    receipt = json.loads(path.read_text())
    if receipt.get('schema') == 'unity-recorded-generated-axis-review.v1':
        _verified_capture(recorded)
        if (receipt.get('accepted') is not True or receipt.get('recorded_attempt') != str(recorded)
                or receipt['capture_verification_sha256'] != sha(recorded/'background_record/verification.json')
                or receipt['source_snapshot_sha256'] != sha(recorded/'background_record/source_snapshot.json')):
            raise ValueError('Recorded generated axis review identity changed')
        allowed = reviewed_axis_paths(recorded)
        if not allowed or sorted(allowed) != receipt['reviewed_paths']:
            raise ValueError('Recorded generated axis paths changed')
        return allowed
    if (receipt.get('schema') != 'unity-recorded-urp-import-review.v1' or receipt.get('accepted') is not True
            or receipt.get('recorded_attempt') != str(recorded)
            or receipt.get('capture_verification_sha256') != sha(recorded/'background_record/verification.json')):
        raise ValueError('Recorded import review identity or capture receipt differs')
    cache = (recorded/'background_record/project/Library/PackageCache').resolve()
    renderer = receipt['renderer_type_source']
    renderer_source = Path(renderer['source']).resolve()
    renderer_meta = Path(renderer['metadata']).resolve()
    if (not renderer_source.is_relative_to(cache) or renderer_source.name != 'UniversalRendererData.cs'
            or renderer_meta != Path(str(renderer_source)+'.meta') or sha(renderer_source) != renderer['source_sha256']
            or sha(renderer_meta) != renderer['metadata_sha256']
            or not re.search(r'(?m)^guid: '+re.escape(renderer['guid'])+r'$',renderer_meta.read_text())):
        raise ValueError('Renderer type is not bound to recorded URP package source')
    known = set()
    for proof in receipt['package_shader_sources']:
        source = Path(proof['source']).resolve()
        metadata = Path(proof['metadata']).resolve()
        if (not source.is_relative_to(cache) or source.suffix != '.shader'
                or metadata != Path(str(source)+'.meta') or sha(source) != proof['source_sha256']
                or sha(metadata) != proof['metadata_sha256']
                or not re.search(r'(?m)^guid: '+re.escape(proof['guid'])+r'$',metadata.read_text())):
            raise ValueError('Imported shader is not bound to its recorded package source')
        known.add(proof['guid'])
    allowed = set()
    snapshot = json.loads((recorded/'input_manifest.json').read_text())['snapshot_hashes']
    for change in receipt['changes']:
        relative = Path(change['path'])
        before = (recorded/'input/project'/relative).resolve()
        after = (recorded/'background_record/project'/relative).resolve()
        if (relative.is_absolute() or '..' in relative.parts or relative.parts[:1] != ('Assets',)
                or not before.is_relative_to(recorded/'input/project')
                or not after.is_relative_to(recorded/'background_record/project')
                or relative.suffix != '.asset' or snapshot.get(str(relative)) != change['before_sha256']
                or sha(before) != change['before_sha256'] or sha(after) != change['recorded_sha256']):
            raise ValueError('Reviewed renderer differs from the captured source hashes')
        if not re.search(r'(?m)^  m_Script: \{fileID: 11500000, guid: '+re.escape(renderer['guid'])+r', type: 3\}$',before.read_text()):
            raise ValueError('Reviewed asset is not UniversalRendererData')
        if 'package_serialization' in change:
            from .urp_package_serialization import review as review_package
            if ('shader_reference_changes' in change or review_package(before.read_text(),after.read_text(),cache)
                    != change['package_serialization']):
                raise ValueError('Reviewed package serialization proof differs')
        elif shader_reference_changes(before.read_text(),after.read_text(),known) != change['shader_reference_changes']:
            raise ValueError('Reviewed renderer shader changes differ')
        allowed.add(str(relative))
    if not allowed:
        raise ValueError('Empty import review')
    return allowed | reviewed_axis_paths(recorded)


def _verified_capture(recorded):
    from .unity_capture_policy import qualify
    qualify(recorded)


def _create_axis_review(recorded):
    allowed = reviewed_axis_paths(recorded)
    if not allowed:
        return set()
    _verified_capture(recorded)
    receipt = {'schema':'unity-recorded-generated-axis-review.v1','accepted':True,
        'recorded_attempt':str(recorded), 'reviewed_paths':sorted(allowed),
        'capture_verification_sha256':sha(recorded/'background_record/verification.json'),
        'source_snapshot_sha256':sha(recorded/'background_record/source_snapshot.json'),
        'reason':'Exact authored InputManager projection: generated m_Name becomes runtime name; no gameplay source changed.',
        'at':time.time()}
    with (recorded/'recorded_import_review.json').open('x') as output:
        output.write(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
    return reviewed_import_paths(recorded)


def create_import_review(recorded):
    recorded = Path(recorded).resolve()
    receipt_path = recorded/'recorded_import_review.json'
    if receipt_path.exists():
        return reviewed_import_paths(recorded)
    snapshot = json.loads((recorded/'input_manifest.json').read_text())['snapshot_hashes']
    changed = []
    for relative,digest in snapshot.items():
        if not relative.startswith('Assets/') or not relative.endswith('.asset'):
            continue
        before = recorded/'input/project'/relative
        after = recorded/'background_record/project'/relative
        if after.is_file() and sha(after) != digest:
            if sha(before) != digest:
                raise ValueError('Original renderer snapshot changed')
            changed.append((relative,before,after))
    if not changed:
        return _create_axis_review(recorded)
    cache = recorded/'background_record/project/Library/PackageCache'
    renderers = list(cache.glob('com.unity.render-pipelines.universal@*/Runtime/UniversalRendererData.cs'))
    if len(renderers) != 1:
        return _create_axis_review(recorded)
    renderer = renderers[0]
    def proof(source):
        metadata = Path(str(source)+'.meta')
        matches = re.findall(r'(?m)^guid: ([0-9a-f]{32})$',metadata.read_text())
        if len(matches) != 1:
            raise ValueError('Package source has no unique shader GUID')
        return {'source':str(source.resolve()),'metadata':str(metadata.resolve()),'guid':matches[0],
                'source_sha256':sha(source),'metadata_sha256':sha(metadata)}
    renderer_proof = proof(renderer)
    renderer_assets = [(relative,before,after) for relative,before,after in changed if re.search(
        r'(?m)^  m_Script: \{fileID: 11500000, guid: '+renderer_proof['guid']+r', type: 3\}$',before.read_text())]
    if not renderer_assets:
        return _create_axis_review(recorded)
    _verified_capture(recorded)
    shaders = [proof(source) for source in sorted(renderer.parent.parent.rglob('*.shader'))
               if Path(str(source)+'.meta').is_file()]
    known = {source['guid'] for source in shaders}
    changes = []
    for relative,before,after in renderer_assets:
        row={'path':relative,'before_sha256':sha(before),'recorded_sha256':sha(after)}
        try:
            row['shader_reference_changes']=shader_reference_changes(before.read_text(),after.read_text(),known)
        except ValueError:
            from .urp_package_serialization import review as review_package
            row['package_serialization']=review_package(before.read_text(),after.read_text(),cache)
        changes.append(row)
    used = {change['guid'] for row in changes for change in row.get('shader_reference_changes',[])}
    receipt = {'schema':'unity-recorded-urp-import-review.v1','accepted':True,'recorded_attempt':str(recorded),
        'capture_verification_sha256':sha(recorded/'background_record/verification.json'),
        'renderer_type_source':renderer_proof,'package_shader_sources':[source for source in shaders if source['guid'] in used],
        'changes':changes,'reason':'Only captured URP package Reload resource serialization and exact vendor YAML tag; actual imported source gets its own static identity. No asset parameter or game-code changes accepted.',
        'at':time.time()}
    with receipt_path.open('x') as output:
        output.write(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
    return reviewed_import_paths(recorded)
