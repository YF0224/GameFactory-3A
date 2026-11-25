"""Input adaptation must not replace authored packages or select the broken fork."""
import json
from pathlib import Path
from unittest.mock import patch

from pipeline.eval.stage1 import unity_input


def project(tmp_path, dependency=None):
    for name in ('Assets', 'Packages', 'ProjectSettings'):
        (tmp_path / name).mkdir()
    (tmp_path / 'ProjectSettings/ProjectSettings.asset').write_text('activeInputHandler: 0\n')
    (tmp_path / 'ProjectSettings/InputManager.asset').write_text('InputManager:\n  m_Axes: []\n')
    (tmp_path / 'Assets/Game.cs').write_text('if (Input.GetKeyDown(KeyCode.Space)) Jump();')
    deps = {'com.unity.ugui': '1.0.0'}
    if dependency:
        deps['com.unity.inputsystem'] = dependency
    (tmp_path / 'Packages/manifest.json').write_text(json.dumps({'dependencies': deps}))
    return tmp_path


def test_missing_dependency_gets_compatible_cached_package(tmp_path):
    root = project(tmp_path)
    cache = tmp_path / 'cache'
    cache.mkdir()
    (cache / 'package.json').write_text('{"version":"1.7.0"}')
    with patch.object(unity_input, 'package_root', return_value=cache):
        receipt = unity_input.migrate(root, root / 'receipt.json')
    assert receipt['input_system_package_origin'] == 'harness_added'
    assert receipt['input_system_package_version'] == '1.7.0'
    assert json.loads((root / 'Packages/manifest.json').read_text())['dependencies']['com.unity.ugui'] == '1.0.0'
    assert (root / 'Assets/Game.cs').read_text() == 'if (global::GameFactoryInput.GetKeyDown(KeyCode.Space)) Jump();'
    assert receipt['gameplay_changes'] == []


def test_author_dependency_preserved_byte_for_byte(tmp_path):
    root = project(tmp_path, '1.8.2')
    manifest = root / 'Packages/manifest.json'
    before = manifest.read_bytes()
    with patch.object(unity_input, 'package_root', side_effect=AssertionError('must not select a replacement')):
        receipt = unity_input.migrate(root, root / 'receipt.json')
    assert manifest.read_bytes() == before
    assert receipt['input_system_package_origin'] == 'author_preserved'
    assert receipt['input_system_package'] == '1.8.2'


def test_cache_version_mismatch_is_rejected(tmp_path, monkeypatch):
    (tmp_path / 'package.json').write_text('{"version":"1.14.0"}')
    monkeypatch.setenv('GAMEFACTORY_UNITY_INPUT_SYSTEM_PACKAGE', str(tmp_path))
    with patch.object(Path, 'home', return_value=tmp_path):
        import pytest
        with pytest.raises(ValueError, match='1.7.0'):
            unity_input.package_root()
