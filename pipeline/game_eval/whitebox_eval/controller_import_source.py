"""Bind native pair admission to the existing controller import evidence.

A pair recorder has no single runtime importer. Its original, SHA-bound native
admission already contains the real import/compile/scene-open result. Preserve
that result verbatim and project only its proven import facts into the ordinary
controller format. Model packets, accepted replies and scoring stay unchanged.
"""
from pathlib import Path
import json
from .protocol import dump, sha

VERSION = 'whitebox-native-admission-controller-import.v1'


def projection(root):
    root = Path(root)
    read = lambda path: json.loads(Path(path).read_text())
    manifest = read(root/'input_manifest.json')
    entry = manifest['entry']
    sessions = entry.get('native_sessions', {})
    if (entry.get('actual_engine') != 'unity3d'
            or sessions.get('version') != 'whitebox-native-multisession.v1'
            or sessions.get('roles') != ['A', 'B']):
        raise ValueError('Missing import evidence requires a bound native pair admission')
    binding = entry['native_open_admission']
    source = Path(binding['receipt'])
    if sha(source) != binding['sha256']:
        raise ValueError('Controller import admission SHA changed')
    receipt = read(source)
    execution = receipt.get('execution', {})
    opened = receipt.get('opened_scene', {})
    command = execution.get('command')
    if (binding.get('version') != 'whitebox-openable-delivery.v1'
            or receipt.get('schema') != binding['version']
            or receipt.get('id') != entry['id']
            or Path(receipt['project']).resolve() != Path(entry['project']).resolve()
            or Path(receipt['source_project']).resolve() != Path(binding['original_project']).resolve()
            or receipt.get('project_hashes') != manifest['snapshot_hashes']
            or not isinstance(command, list) or not command
            or receipt.get('editor') != command[0]
            or receipt.get('product_status') != 'OPENED'
            or opened.get('opened') is not True
            or execution.get('exit_code') != 0
            or execution.get('timed_out') is not False
            or execution.get('owned_process_exited') is not True
            or receipt.get('source_unchanged', {}).get('ok') is not True
            or any(receipt.get('cleanup', {}).get(key) is not True
                   for key in ('input_cleanup', 'view_cleanup', 'process_cleanup'))):
        raise ValueError('Controller import admission lacks matching native completion/source/cleanup')
    if opened.get('scene') not in manifest['snapshot_hashes']:
        raise ValueError('Controller import admission scene is outside frozen source')
    # This is a deterministic adapter projection of a real controller receipt,
    # never a new editor invocation or a model/product verdict.
    return {'schema': VERSION, 'engine': 'unity3d',
            'completed': opened['opened'] and execution['exit_code'] == 0,
            'product_errors': receipt['product_status'] != 'OPENED',
            'note': 'Real native admission import/compile/scene-open; native export NOT tested.',
            'source_receipt': str(source), 'source_sha256': sha(source),
            'source_physical_lines': len(source.read_text().splitlines()),
            'source_result': receipt}


def ensure(root):
    root = Path(root)
    canonical = root/'runtime/import_result.json'
    path = canonical if canonical.exists() else root/'controller_evidence/import_result.json'
    if path.exists():
        saved = json.loads(path.read_text())
        # Existing canonical results, including errors, never use a fallback.
        if saved.get('schema') != VERSION:
            return path
        if saved != projection(root):
            raise ValueError('Controller import projection or original admission changed')
    else:
        dump(path, projection(root))
    return path


def audit_bindings(root):
    root = Path(root)
    canonical = root/'runtime/import_result.json'
    path = canonical if canonical.exists() else root/'controller_evidence/import_result.json'
    if not path.exists():
        return {}
    saved = json.loads(path.read_text())
    if saved.get('schema') != VERSION:
        return {}
    ensure(root)
    source = Path(saved['source_receipt'])
    return {str(path): sha(path), str(source): sha(source)}
