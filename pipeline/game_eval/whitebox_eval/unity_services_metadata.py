"""Attest only Services Core's empty, editor-created environment settings file."""
from pathlib import Path
import hashlib
import json

NAME = 'ProjectSettings/Packages/com.unity.services.core/Settings.json'
PACKAGE = 'com.unity.services.core'
VERSION = '1.14.0'
# Reviewed LoadEnvironment -> GetOrCreateFileContent -> File.Create -> empty
# string; EnvironmentConfigProvider selects the same default environment when
# no settings exist. This never licenses a populated or authored configuration.
VENDOR_SHA256 = {
    'package.json': 'a4c9fd04ea03921558f87a261568b7810f3359734884f3675e0d11c16128341f',
    'Editor/Core/Environments/Save/EnvironmentSaveSystem.cs': '2c88dedca9388e09a3e0768628267ac2fd4245c88aceb41dbb5934b6d8d516ba',
    'Editor/Core/Utils/FileSystem/FileSystem.cs': '392d13a019e43cb00f5921814a117722bface30c48b3ce920553613de2c379c6',
    'Editor/Core/Environments/Config/EnvironmentConfigProvider.cs': '11aadd9683e9e4fa42a453f6f8e5f2fb13e15e8550d1369d7135bcb02ae6ec4b',
    'Editor/Core/Environments/EnvironmentProvider.cs': 'f4f0d5d540aa1d8819d87af4aa2a116e6d09122cfb0727daa6a8283c4980d38f',
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def proof(original, runtime, name, log):
    """Require an absent input, zero runtime bytes and exact native package proof."""
    original, runtime, log = Path(original), Path(runtime), Path(log)
    if name != NAME or (original/name).exists():
        return None
    try:
        if (runtime/name).read_bytes() != b'':
            return None
        frozen = json.loads((original/'Packages/packages-lock.json').read_text())['dependencies'][PACKAGE]
        if frozen.get('version') != VERSION or frozen.get('source') != 'registry':
            return None
        lines = log.read_text(errors='replace').splitlines()
        prefix = f'{PACKAGE}@{VERSION} (location: '
        locations = [(i, Path(line.strip().split(prefix, 1)[1][:-1]))
                     for i, line in enumerate(lines, 1)
                     if line.strip().startswith(prefix) and line.rstrip().endswith(')')]
        caches = {str(path) for _, path in locations}
        if len(caches) != 1:
            return None
        cache = locations[0][1]
        if (not cache.is_absolute() or cache.name != f'{PACKAGE}@{VERSION}'
                or cache.parent.name != 'PackageCache' or cache.parent.parent.name != 'Library'
                or any(sha(cache/n) != digest for n, digest in VENDOR_SHA256.items())):
            return None
        return {'kind': 'unity_services_empty_environment_metadata', 'path': NAME,
                'package': PACKAGE, 'version': VERSION, 'runtime_sha256': sha(runtime/name),
                'original_absent': True, 'runtime_bytes': 0, 'package_cache': str(cache),
                'reviewed_vendor_sha256': dict(VENDOR_SHA256), 'log_path': str(log),
                'log_sha256': sha(log), 'package_registration_lines': [i for i, _ in locations],
                'frozen_lock_sha256': sha(original/'Packages/packages-lock.json'),
                'note': 'Empty editor environment metadata; not gameplay or execution evidence.'}
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        return None
