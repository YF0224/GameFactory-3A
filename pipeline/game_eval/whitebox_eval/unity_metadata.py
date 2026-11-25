"""Provenance for Unity's default-registry mirror serialization.

This only describes an already-recorded editor side effect. It never writes a
project, resolves packages, changes a dependency, or treats settings as gameplay.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re


PUBLIC_REGISTRY = 'https://packages.unity.com'
CHINA_REGISTRY = 'https://packages.unity.cn'
SETTINGS = 'ProjectSettings/PackageManagerSettings.asset'


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def unity_registry_normalization(root: Path, name: str):
    """Accept exactly the China editor's default mirror plus transient draft IDs.

    Require unchanged package declarations, identical locked releases/dependency
    edges, and the recording's native editor log identifying the matching China
    editor and registry. Custom registries and all other settings remain frozen.
    """
    if name != SETTINGS:
        return None
    original = root / 'input/project'
    runtime = root / 'runtime/project'
    try:
        before = (original / name).read_text()
        after = (runtime / name).read_text()
        # Only a single, unscoped Unity default registry is covered by this rule.
        registry = (
            '  m_Registries:\n'
            '  - m_Id: main\n'
            '    m_Name: \n'
            f'    m_Url: {PUBLIC_REGISTRY}\n'
            '    m_Scopes: []\n'
            '    m_IsDefault: 1\n'
            '    m_Capabilities: 7\n'
            '    m_ConfigSource: 0\n'
            '  m_UserSelectedRegistryName:'
        )
        if before.count(registry) != 1 or before.count('    m_Url:') != 1:
            return None
        expected = before.replace(f'    m_Url: {PUBLIC_REGISTRY}\n',
                                  f'    m_Url: {CHINA_REGISTRY}\n')
        def without_instance_ids(text):
            for field in ('m_UserModificationsInstanceId', 'm_OriginalInstanceId'):
                pattern = rf'(?m)^    {field}: -?\d+$'
                if len(re.findall(pattern, text)) != 1:
                    return None
                text = re.sub(pattern, f'    {field}: TRANSIENT_INSTANCE_ID', text)
            return text
        normalized = without_instance_ids(expected)
        if normalized is None or without_instance_ids(after) != normalized:
            return None

        manifest = 'Packages/manifest.json'
        if (original / manifest).read_bytes() != (runtime / manifest).read_bytes():
            return None
        lock_name = 'Packages/packages-lock.json'
        lock_before = json.loads((original / lock_name).read_text())
        lock_after = json.loads((runtime / lock_name).read_text())
        expected_lock = copy.deepcopy(lock_before)
        mirrored = []
        for package, entry in expected_lock['dependencies'].items():
            if entry.get('source') == 'registry' and entry.get('url') == PUBLIC_REGISTRY:
                entry['url'] = CHINA_REGISTRY
                mirrored.append(package)
        if not mirrored or expected_lock != lock_after:
            return None

        version_path = original / 'ProjectSettings/ProjectVersion.txt'
        declared = re.search(r'(?m)^m_EditorVersion: (\d+\.\d+\.\d+[abfp]\d+)(?:c\d+)?$',
                             version_path.read_text())
        if not declared:
            return None
        log_path = root / 'runtime/unity_editor.log'
        lines = log_path.read_text(errors='replace').splitlines()
        version_pattern = re.compile(r'^Unity Editor version:\s*(' +
                                     re.escape(declared.group(1)) + r'c\d+) \([^()]+\)$')
        versions = [(i + 1, version_pattern.fullmatch(line)) for i, line in enumerate(lines)]
        versions = [(i, match.group(1)) for i, match in versions if match]
        if len(versions) != 1:
            return None
        version_line, installed = versions[0]
        executable = f'/Applications/Unity/Hub/Editor/{installed}/Unity.app/Contents/MacOS/Unity'
        required = {
            'executable': lambda line: line == executable,
            'branch': lambda line: bool(re.fullmatch(r'Branch:\s*\d+\.\d+/china_unity/release', line)),
            'registry': lambda line: line.strip() == f'Packages from [{CHINA_REGISTRY}]:',
        }
        log_lines = {'editor_version': version_line}
        for key, predicate in required.items():
            matches = [i + 1 for i, line in enumerate(lines) if predicate(line)]
            if not matches:
                return None
            log_lines[key] = matches[0]
        return {
            'kind': 'unity_china_default_registry_mirror',
            'source_path': str(log_path), 'source_sha256': _sha(log_path),
            'log_lines': log_lines, 'editor_version': installed,
            'delivered_version_sha256': _sha(version_path),
            'manifest_sha256': _sha(original / manifest),
            'lock_before_sha256': _sha(original / lock_name),
            'lock_after_sha256': _sha(runtime / lock_name),
            'mirrored_packages': sorted(mirrored),
            'note': 'Only the default registry URL and transient draft instance IDs changed; '
                    'package declarations and all locked versions/dependency edges are identical.',
        }
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def unity_urp_msaa_normalization(root: Path, name: str):
    """Attest only active quality's MSAA disable matching the delivered URP asset.

    URP's constructor copies its own sample count to QualitySettings. Unity's
    disabled enum serializes as 0 there and as 1 in URP. No other quality level,
    pipeline, package release, or setting change is covered.
    """
    if name != 'ProjectSettings/QualitySettings.asset':
        return None
    try:
        original = root / 'input/project'
        runtime = root / 'runtime/project'
        before = (original / name).read_text()
        after = (runtime / name).read_text()
        current = re.search(r'(?m)^  m_CurrentQuality: (\d+)$', before)
        if not current:
            return None
        blocks = list(re.finditer(r'(?m)^  - serializedVersion: \d+$', before))
        index = int(current.group(1))
        if index >= len(blocks):
            return None
        start = blocks[index].start()
        end = blocks[index + 1].start() if index + 1 < len(blocks) else len(before)
        block = before[start:end]
        old = '    antiAliasing: 2\n'
        if block.count(old) != 1:
            return None
        expected = before[:start] + block.replace(old, '    antiAliasing: 0\n') + before[end:]
        if expected != after:
            return None
        graphics = (original / 'ProjectSettings/GraphicsSettings.asset').read_text()
        guid = re.search(r'm_CustomRenderPipeline: \{fileID: 11400000, guid: ([a-f0-9]{32}), type: 2\}', graphics)
        if not guid:
            return None
        # Unity may serialize the active quality's antiAliasing change against
        # either the global URP asset or an explicit quality-level reference to
        # that same asset. Accept both forms, but never accept a different
        # pipeline asset or an unverified quality override.
        quality_pipeline = re.search(
            r'(?m)^    customRenderPipeline: \{fileID: 0\}$', block)
        if quality_pipeline is None:
            quality_pipeline = re.search(
                r'(?m)^    customRenderPipeline: \{fileID: 11400000, guid: '
                r'([a-f0-9]{32}), type: 2\}$', block)
            if quality_pipeline is None or quality_pipeline.group(1) != guid.group(1):
                return None
        assets = [meta.with_suffix('') for meta in (original / 'Assets').rglob('*.asset.meta')
                  if re.search(r'(?m)^guid: ' + guid.group(1) + '$', meta.read_text())]
        if len(assets) != 1:
            return None
        asset = assets[0]
        delivered = asset.read_text()
        if not re.search(r'(?m)^  m_MSAA: 1$', delivered):
            return None
        if asset.read_bytes() != (runtime / asset.relative_to(original)).read_bytes():
            return None
        script = re.search(r'm_Script: \{fileID: 11500000, guid: ([a-f0-9]{32}), type: 3\}', delivered)
        if not script:
            return None
        packages = json.loads((original / 'Packages/manifest.json').read_text())['dependencies']
        version = packages.get('com.unity.render-pipelines.universal')
        if not isinstance(version, str) or not re.fullmatch(r'\d+\.\d+\.\d+', version):
            return None
        package = runtime / f'Library/PackageCache/com.unity.render-pipelines.universal@{version}'
        definition = package / 'Runtime/Data/UniversalRenderPipelineAsset.cs.meta'
        if not re.search(r'(?m)^guid: ' + script.group(1) + '$', definition.read_text()):
            return None
        source = package / 'Runtime/UniversalRenderPipeline.cs'
        lines = source.read_text().splitlines()
        assignment = [i + 1 for i, line in enumerate(lines)
                      if line.strip() == 'QualitySettings.antiAliasing = asset.msaaSampleCount;']
        convention = [i + 1 for i, line in enumerate(lines)
                      if line.strip() == '// In QualitySettings.antiAliasing disabled state uses value 0, where in URP 1']
        guard = [i + 1 for i, line in enumerate(lines)
                 if line.strip() == 'bool msaaSampleCountNeedsUpdate = qualitySettingsMsaaSampleCount != asset.msaaSampleCount;']
        if len(assignment) != 1 or len(convention) != 1 or len(guard) != 1:
            return None
        if not convention[0] < guard[0] < assignment[0] <= convention[0] + 12:
            return None
        log = root / 'runtime/unity_editor.log'
        imports = [i + 1 for i, line in enumerate(log.read_text(errors='replace').splitlines())
                   if line.startswith('Start importing ProjectSettings/QualitySettings.asset ')]
        if not imports:
            return None
        return {'kind': 'unity_urp_active_quality_msaa_serialization',
                'source_path': str(source), 'source_sha256': _sha(source),
                'assignment_line': assignment[0], 'disabled_convention_line': convention[0],
                'guard_line': guard[0], 'active_quality_index': index,
                'delivered_pipeline': str(asset.relative_to(original)), 'pipeline_sha256': _sha(asset),
                'log_path': str(log), 'log_sha256': _sha(log), 'log_import_lines': imports,
                'note': 'Exact active-quality 2-to-disabled serialization follows the unchanged delivered URP m_MSAA:1; this is engine provenance, never mechanism PASS evidence.'}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def unity_lock_normalization(root: Path, name: str):
    """Attest lock serialization/mirror changes without changing any resolution.

    Package releases, dependency edges, sources and all other fields stay exact.
    An existing lock is never a blanket exemption from source integrity checks.
    """
    if name != 'Packages/packages-lock.json':
        return None
    original = root / 'input/project' / name
    updated = root / 'runtime/project' / name
    try:
        before = json.loads(original.read_text())
        after = json.loads(updated.read_text())
        normalized = copy.deepcopy(after)
        mirrors = []
        old_packages = before['dependencies']
        new_packages = normalized['dependencies']
        if set(old_packages) != set(new_packages):
            return None
        for package, old in old_packages.items():
            new = new_packages[package]
            if old.get('url') == PUBLIC_REGISTRY and new.get('url') == CHINA_REGISTRY:
                new['url'] = PUBLIC_REGISTRY
                mirrors.append(package)
        if normalized != before:
            return None
        proof = {'kind': 'unity_lock_exact_resolution', 'locked_packages': len(old_packages),
                 'original_sha256': _sha(original), 'runtime_sha256': _sha(updated),
                 'mirrored_packages': sorted(mirrors)}
        if mirrors:
            log = root / 'runtime/unity_editor.log'
            lines = log.read_text(errors='replace').splitlines()
            matched = [i for i, line in enumerate(lines, 1) if 'china_unity' in line or CHINA_REGISTRY in line]
            if not any('china_unity' in line for line in lines) or not any(CHINA_REGISTRY in line for line in lines):
                return None
            proof.update(log_path=str(log), log_sha256=_sha(log), log_lines=matched)
        return proof
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None
