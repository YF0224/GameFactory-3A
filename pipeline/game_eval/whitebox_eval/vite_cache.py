"""Accept only independently reproduced added Vite 6.2.6 / Three 0.185.0 cache.

Existing authored files are never exempted. Unknown versions and cache formats
remain blocked until a separate reproducibility regression supports them.
"""
from __future__ import annotations
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path

VERSION = 'vite-cache-independent-rebuild.v1'
PREFIX = '.cache/vite/deps/'
OUTPUTS = ('three.js', 'three.js.map', 'package.json')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verified_cache(root, before, current):
    root = Path(root)
    added = {name for name in current if name.startswith(PREFIX) and name not in before}
    if not added:
        return {}
    expected = {PREFIX + name for name in (*OUTPUTS, '_metadata.json')}
    if added != expected or any(name.startswith(PREFIX) for name in before):
        raise ValueError('Vite cache must be a complete, exclusively added known dependency cache')
    project = root / 'runtime/project'
    # Rebuilding dependencies never authorizes changes to delivered code/configuration.
    drift = [name for name, old in before.items() if current.get(name) != old]
    if drift:
        raise ValueError('Vite cache proof requires unchanged authored sources: ' + drift[0])
    package = json.loads((project / 'package.json').read_text())
    required = {'three':'0.185.0', 'vite':'6.2.6'}
    declared = {**package.get('dependencies', {}), **package.get('devDependencies', {})}
    dependencies = {}
    for name, version in required.items():
        installed = project / 'node_modules' / name / 'package.json'
        if declared.get(name) != version or json.loads(installed.read_text())['version'] != version:
            raise ValueError('unsupported Vite cache dependency version: ' + name)
        dependencies[name] = {'version':version, 'package_sha256':digest(installed)}
    metadata = json.loads((project / PREFIX / '_metadata.json').read_text())
    hashes = ('hash', 'configHash', 'lockfileHash', 'browserHash')
    if set(metadata) != {*hashes, 'optimized', 'chunks'} or any(
            not isinstance(metadata[k], str) or not re.fullmatch('[0-9a-f]{8}', metadata[k]) for k in hashes):
        raise ValueError('unexpected Vite dependency metadata shape')
    if metadata['chunks'] != {} or set(metadata['optimized']) != {'three'}:
        raise ValueError('unexpected Vite dependency cache entries')
    item = metadata['optimized']['three']
    if (set(item) != {'src','file','fileHash','needsInterop'}
            or item['src'] != '../../../node_modules/three/build/three.module.js'
            or item['file'] != 'three.js' or item['needsInterop'] is not False
            or not isinstance(item['fileHash'], str) or not re.fullmatch('[0-9a-f]{8}', item['fileHash'])):
        raise ValueError('unexpected Vite dependency mapping')
    helper = Path(__file__).with_name('vite_cache_rebuild.mjs')
    reproduced = {}
    with tempfile.TemporaryDirectory(prefix='whitebox-vite-proof-') as directory:
        result = subprocess.run(['node', str(helper), str(project.resolve()), directory],
            capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise ValueError('independent Vite cache rebuild failed: ' + result.stderr[-1200:])
        for name in OUTPUTS:
            regenerated = Path(directory) / PREFIX / name
            actual = project / PREFIX / name
            if not regenerated.is_file():
                raise ValueError('Vite cache output missing from independent rebuild: ' + name)
            rebuilt_bytes = regenerated.read_bytes()
            actual_bytes = actual.read_bytes()
            # esbuild embeds its isolated node_modules root in two source comments.
            # Normalize only exact module-path comment lines, never source tokens.
            if name == 'three.js':
                for module in ('three.core.js', 'three.module.js'):
                    pattern = rb'(?m)^// [^\n]*/node_modules/three/build/' + module.encode() + rb'$'
                    rebuilt_bytes, count = re.subn(pattern,
                        b'// node_modules/three/build/' + module.encode(), rebuilt_bytes)
                    if count != 1:
                        raise ValueError('unexpected esbuild module provenance comment')
            if rebuilt_bytes != actual_bytes:
                raise ValueError('Vite cache differs from independent rebuild: ' + name)
            reproduced[PREFIX + name] = digest(actual)
    proof = {'version':VERSION, 'generator_sha256':digest(helper),
        'dependencies':dependencies, 'reproduced_sha256':reproduced,
        'metadata_sha256':digest(project / PREFIX / '_metadata.json'),
        'metadata_rule':'strict data-only schema; root-dependent hashes are not executable content'}
    return {name:proof for name in expected}
