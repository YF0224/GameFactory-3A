"""Pick a Unity or Tuanjie editor for any delivered project version.

1. Family from the actual serialized delivery, not ProjectVersion alone: a
   Tuanjie version marker, Tuanjie YAML namespace in a scene, an encoded
   (non-hex) asset GUID, or a Tuanjie package dependency => ``tuanjie``.
2. Installed editors are discovered from Unity Hub / Tuanjie Hub (plus any
   paths in ``A3GAME_UNITY_EDITORS``, ``:``-separated).
3. Same family only (a Tuanjie project never opens in Unity and vice versa);
   prefer the exact version, else the same major.minor with the closest patch,
   else the newest of that family. The choice and any version gap are recorded.

Opening a project with a different editor version is done on the run's
``runtime/project`` copy only (Unity upgrades it on import); the author's
original delivery is never touched.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

VERSION = 'stage1-unity-editor.v1'
VERSION_RE = re.compile(r'\d+\.\d+\.\d+[a-z]\d+(?:c\d+)?')

from engine_adapters.unity3d.editor_paths import EditorUnavailable, installed_editors


def family_of(text: str) -> str:
    return 'tuanjie' if re.search(r'tuanjie|\d+t\d+', text, re.I) else 'unity'


def version_of(path: str) -> str:
    return next((p for p in reversed(Path(path).parts) if VERSION_RE.fullmatch(p)), '')


def installed() -> list[dict]:
    return installed_editors()


def _key(version: str) -> tuple:
    return tuple(int(x) if x.isdigit() else x for x in re.findall(r'\d+|[a-z]', version))


def delivery_format(project: Path) -> dict:
    project = Path(project)
    evidence = []
    marker = project / 'ProjectSettings' / 'ProjectVersion.txt'
    text = marker.read_text(errors='replace') if marker.is_file() else ''
    match = re.search(r'(?m)^m_EditorVersion:\s*(\S+)', text)
    version = match[1].strip() if match else None
    if version and family_of(version) == 'tuanjie':
        evidence.append('Tuanjie editor version marker')
    for scene in sorted((project / 'Assets').rglob('*.unity'))[:8] if (project / 'Assets').is_dir() else []:
        with scene.open('rb') as fh:
            if b'tag:yousandi.cn,' in fh.read(512):
                evidence.append(f'Tuanjie YAML namespace: {scene.relative_to(project)}')
        meta = scene.with_suffix(scene.suffix + '.meta')
        if meta.is_file():
            guid = re.search(r'(?m)^guid:\s*(\S+)', meta.read_text(errors='replace'))
            if guid and re.fullmatch(r'[A-Za-z0-9+/]{40,}={0,2}', guid[1]) and not re.fullmatch(r'[a-fA-F0-9]{32}', guid[1]):
                evidence.append(f'encoded Tuanjie asset GUID: {meta.relative_to(project)}')
    manifest = project / 'Packages' / 'manifest.json'
    if manifest.is_file():
        try:
            deps = json.loads(manifest.read_text()).get('dependencies', {})
        except ValueError:
            deps = {}
        if any('tuanjie' in k or k == 'com.unity.modules.infinity' or
               (isinstance(v, str) and re.search(r'-t\d+$', v)) for k, v in deps.items()):
            evidence.append('Tuanjie package dependency')
    return {'family': 'tuanjie' if evidence else 'unity', 'project_version': version, 'evidence': evidence}


def choose(project: Path) -> dict:
    fmt = delivery_format(project)
    same = [e for e in installed() if e['family'] == fmt['family']]
    if not same:
        raise EditorUnavailable(f'No installed {fmt["family"]} editor for project version {fmt["project_version"]}; '
                                'set A3GAME_UNITY_BINARY or A3GAME_TUANJIE_BINARY to its executable')
    configured = [e for e in same if e.get('configured')]
    same = configured or same
    want = fmt['project_version'] or ''
    exact = [e for e in same if e['version'] == want]
    minor = [e for e in same if e['version'].split('.')[:2] == want.split('.')[:2]]
    if exact:
        pick, rule = exact[-1], 'exact_version'
    elif minor and want and family_of(want) != fmt['family']:
        # the marker names the other family (e.g. a Tuanjie project saying 62f1): its patch
        # number is meaningless here, so take the newest editor of the same major.minor
        pick, rule = minor[-1], 'same_minor_newest_cross_marker'
    elif minor:
        target = _key(want)
        pick, rule = min(minor, key=lambda e: abs(_distance(_key(e['version']), target))), 'same_minor_closest'
    else:
        pick, rule = same[-1], 'newest_same_family'
    return {'version': VERSION, 'delivery': fmt, 'editor': pick, 'rule': rule,
            'version_gap': pick['version'] != want, 'candidates': same}


def _distance(a: tuple, b: tuple) -> int:
    nums = lambda t: [x for x in t if isinstance(x, int)]
    a, b = nums(a), nums(b)
    return sum(abs(x - y) * 1000 ** (len(a) - i) for i, (x, y) in enumerate(zip(a, b)))
