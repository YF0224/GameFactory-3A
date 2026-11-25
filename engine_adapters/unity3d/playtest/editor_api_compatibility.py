"""Fail-closed, source-proven Editor API migration in isolated project copies.

This does not change runtime gameplay or evaluator rules. A reviewed URP getter
and internal setter must demonstrably access the same serialized enum field.
"""
from pathlib import Path
import difflib
import hashlib
import json
import re


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def apply_additional_lights_mode(project, original, source, package_source, *,
                                 expected_source_sha256, expected_package_sha256,
                                 output):
    """Replace exactly one reviewed Editor assignment, preserving its value.

    ``project`` must be a separate isolated copy, never the original delivery.
    All proof inputs and before/after bytes are retained with the patch.
    """
    project, original = Path(project).resolve(), Path(original).resolve()
    relative, package = Path(source), Path(package_source).resolve()
    output = Path(output)
    if (project == original or project.is_relative_to(original)
            or original.is_relative_to(project)):
        raise ValueError('Compatibility requires a separate isolated project')
    if (relative.is_absolute() or '..' in relative.parts
            or relative.parts[:2] != ('Assets', 'Editor') or relative.suffix != '.cs'):
        raise ValueError('Compatibility is restricted to an Editor C# source')
    target = project / relative
    if (target.is_symlink() or not target.resolve().is_relative_to(project)
            or _sha(target) != expected_source_sha256):
        raise ValueError('Reviewed isolated Editor source changed')
    if package.is_symlink() or _sha(package) != expected_package_sha256:
        raise ValueError('Reviewed URP package source changed')
    package_bytes = package.read_bytes()
    package_text = package_bytes.decode('utf-8-sig')
    field = r'\[SerializeField\]\s+LightRenderingMode\s+m_AdditionalLightsRenderingMode\s*='
    setter = (r'public\s+LightRenderingMode\s+additionalLightsRenderingMode\s*\{\s*'
              r'get\s*\{\s*return\s+m_AdditionalLightsRenderingMode\s*;\s*\}\s*'
              r'internal\s+set\s*\{\s*m_AdditionalLightsRenderingMode\s*=\s*value\s*;\s*\}\s*\}')
    if len(re.findall(field, package_text)) != 1 or len(re.findall(setter, package_text)) != 1:
        raise ValueError('URP source does not prove an equivalent serialized field setter')
    before = target.read_bytes()
    # Keep all bytes outside the one exact, non-gameplay assignment untouched.
    assignment = b'asset.additionalLightsRenderingMode=LightRenderingMode.PerPixel;'
    if before.count(assignment) != 1:
        raise ValueError('Expected exactly one reviewed additional-light assignment')
    replacement = (b'{var gf3aUrpSerialized = new UnityEditor.SerializedObject(asset);'
        b'var gf3aUrpMode = gf3aUrpSerialized.FindProperty("m_AdditionalLightsRenderingMode");'
        b'if(gf3aUrpMode == null) throw new System.InvalidOperationException("URP serialized field missing");'
        b'gf3aUrpMode.intValue=(int)LightRenderingMode.PerPixel;'
        b'gf3aUrpSerialized.ApplyModifiedPropertiesWithoutUndo();}')
    if b'gf3aUrp' in before:
        raise ValueError('Compatibility local name collision')
    after = before.replace(assignment, replacement)
    output.mkdir(parents=True, exist_ok=False)
    (output/'source.before.cs').write_bytes(before)
    (output/'source.after.cs').write_bytes(after)
    (output/'UniversalRenderPipelineAsset.proof.cs').write_bytes(package_bytes)
    (output/'source.patch').write_text(''.join(difflib.unified_diff(
        before.decode('utf-8-sig').splitlines(keepends=True),
        after.decode('utf-8-sig').splitlines(keepends=True),
        fromfile=str(relative), tofile=str(relative))))
    target.write_bytes(after)
    receipt = {'schema':'unity-editor-urp-serialized-setter.v1',
        'project':str(project), 'original_project':str(original), 'source':str(relative),
        'before_sha256':expected_source_sha256, 'after_sha256':_sha(target),
        'package_source':str(package), 'package_source_sha256':expected_package_sha256,
        'assignment_count':1, 'field':'m_AdditionalLightsRenderingMode',
        'value':'LightRenderingMode.PerPixel', 'scope':'Editor API equivalence only',
        'proof':'Package getter and internal setter directly access this serialized enum field.',
        'gameplay_modified':False}
    (output/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
    return receipt
