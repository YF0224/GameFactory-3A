"""Narrow provenance proof for Unity IAP's default editor-generated store config."""
from pathlib import Path
import hashlib
import json

NAME = 'Assets/Resources/BillingMode.json'
PACKAGE = 'com.unity.purchasing'
VERSION = '4.11.0'
# Reviewed vendor implementation: InitializeOnLoad -> missing ModePath ->
# CreateDefaultBillingModeFile -> GooglePlay -> SaveConfig -> Serialize.
VENDOR_SHA256 = {
    'Editor/UnityPurchasingEditor.cs': 'cec62838db272a4cfcba37b07f4cf81c41c173846fb44a92e26c6e941bd4f4cc',
    'Runtime/Stores/StoreConfiguration.cs': 'a2a14a28beb450eccceb9c091e487bbc18569482e3fae21cd647f7d82223d9f5',
    'package.json': '1efa4acf223ed6a3a6b18c6491ce7909a3a16066625aa8e1b229f25a17a2e9bf',
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def proof(original, runtime, name, log):
    """Accept only an added exact default with frozen package and native import proof.

    The cache can be in the runtime project or its original recorded source.
    Authored configs and nondefault settings are never exempted.
    """
    original, runtime, log = Path(original), Path(runtime), Path(log)
    if name != NAME or (original/name).exists():
        return None
    try:
        if (runtime/name).read_bytes() != b'{"androidStore":"GooglePlay"}':
            return None
        manifest = json.loads((original/'Packages/manifest.json').read_text())
        lock = json.loads((original/'Packages/packages-lock.json').read_text())['dependencies'][PACKAGE]
        if manifest['dependencies'].get(PACKAGE) != VERSION or lock.get('version') != VERSION or lock.get('source') != 'registry':
            return None
        lines = log.read_text(errors='replace').splitlines()
        imports = [i for i, line in enumerate(lines, 1) if line.startswith('Start importing '+NAME+' ')]
        prefix = f'{PACKAGE}@{VERSION} (location: '
        cache_paths = [Path(line.strip().split(prefix, 1)[1][:-1]) for line in lines
                       if prefix in line and line.rstrip().endswith(')')]
        if len(set(cache_paths)) != 1 or not imports:
            return None
        cache = cache_paths[0]
        if cache.name != f'{PACKAGE}@{VERSION}' or cache.parent.name != 'PackageCache':
            return None
        if any(sha(cache/n) != digest for n, digest in VENDOR_SHA256.items()):
            return None
        return {'kind': 'unity_iap_default_store_metadata', 'package': PACKAGE, 'version': VERSION,
                'runtime_sha256': sha(runtime/name), 'package_cache': str(cache),
                'reviewed_vendor_sha256': VENDOR_SHA256, 'log_path': str(log),
                'log_sha256': sha(log), 'import_lines': imports,
                'note': 'Default editor-generated Android store selection; never gameplay execution evidence.'}
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        return None
