"""Portable Unity/Tuanjie discovery. Explicit configuration never silently falls back."""
from __future__ import annotations

import glob
import os
from pathlib import Path
import re
import shutil


class EditorUnavailable(RuntimeError):
    """The requested editor is not installed or its configured path is invalid."""


def family_of(text):
    return 'tuanjie' if re.search(r'tuanjie|\d+t\d+', str(text), re.I) else 'unity'


def version_of(path):
    pattern = r'\d+\.\d+\.\d+[a-z]\d+(?:c\d+)?'
    return next((part for part in reversed(Path(path).parts) if re.fullmatch(pattern, part)), '')


def version_key(version):
    return tuple((0, int(x)) if x.isdigit() else (1, x) for x in re.findall(r'\d+|[a-z]', version))


def _binary(value, family):
    path = Path(value).expanduser()
    if not path.exists():
        command = shutil.which(str(value))
        if command:
            path = Path(command)
    if path.is_dir():
        name = 'Tuanjie' if family == 'tuanjie' else 'Unity'
        candidates = [path / (name + '.app') / 'Contents/MacOS' / name,
                      path / 'Contents/MacOS' / name, path / 'Editor' / (name + '.exe'),
                      path / (name + '.exe'), path / 'Editor' / name, path / name]
        path = next((p for p in candidates if p.is_file()), path)
    if not path.is_file() or not os.access(path, os.X_OK):
        raise EditorUnavailable(f'Editor is not an executable file: {value}. '
                                'Set A3GAME_UNITY_BINARY or A3GAME_TUANJIE_BINARY to an installed editor.')
    return path.resolve()


def installed_editors():
    found = {}

    def add(value, family, configured):
        binary = _binary(value, family)
        found[str(binary)] = dict(binary=str(binary), family=family, version=version_of(binary),
                                  configured=configured)

    # Environment paths have priority over automatically discovered versions.
    for family, variables in [('unity', ('A3GAME_UNITY_BINARY', 'A3GAME_UNITY_ROOT', 'AAAGF_UNITY')),
                              ('tuanjie', ('A3GAME_TUANJIE_BINARY',))]:
        for variable in variables:
            if os.environ.get(variable):
                add(os.environ[variable], family, True)
                break
    for value in filter(None, os.environ.get('A3GAME_UNITY_EDITORS', '').split(os.pathsep)):
        add(value, family_of(value), True)

    for family, product in [('unity', 'Unity'), ('tuanjie', 'Tuanjie')]:
        patterns = [str(base / product / 'Hub/Editor/*' / (product + '.app') / 'Contents/MacOS' / product)
                    for base in (Path('/Applications'), Path.home() / 'Applications')]
        patterns += [f'C:/Program Files/{product}/Hub/Editor/*/Editor/{product}.exe',
                     str(Path.home() / product / 'Hub/Editor/*/Editor' / product),
                     f'/opt/{product}/Hub/Editor/*/Editor/{product}']
        for pattern in patterns:
            for value in glob.glob(pattern):
                if str(Path(value).resolve()) not in found:
                    add(value, family, False)
        command = shutil.which(product) or shutil.which(product.lower())
        if command and str(Path(command).resolve()) not in found:
            add(command, family, False)
    return sorted(found.values(), key=lambda row: version_key(row['version']))


def resolve_editor(*, family='unity', explicit=None):
    if explicit:
        return _binary(explicit, family)
    candidates = [row for row in installed_editors() if row['family'] == family]
    preferred = [row for row in candidates if row['configured']] or candidates
    if not preferred:
        variable = 'A3GAME_TUANJIE_BINARY' if family == 'tuanjie' else 'A3GAME_UNITY_BINARY'
        raise EditorUnavailable(f'No {family} editor found. Install it or set {variable} to its executable.')
    return Path(preferred[-1]['binary'])
