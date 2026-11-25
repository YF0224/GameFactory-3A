"""Reviewed import-only repairs in isolated snapshots; originals never edited."""
from pathlib import Path
import re
import time

from .protocol import dump, sha

VERSION = 'whitebox-unity-import-compatibility.v1'
POLICY = 'unity_import_compatibility_policy.json'
# This is deliberately not an arbitrary text replacement facility.
NAMESPACES = {'System', 'A3Game.EngineAdapters', 'UnityEditor.SceneManagement', 'System.Linq', 'UnityEngine', 'G009Mechanic', 'GameFactory.Whitebox.Mechanics'}


def tool_repair_eligible(output, case):
    """Allow one bounded retry after the migration-order bug was repaired.

    The original import retry was consumed by the evaluator itself: input
    migration changed the isolated copy before this policy validated it. Keep
    that attempt in history and grant a separate, explicitly classified retry
    only for that exact failure, without resetting any counters.
    """
    return (case.get('status') == 'BOUNDED_FAILURE'
        and case.get('phase') == 'admission'
        and case.get('error') == 'Import compatibility snapshot SHA changed'
        and case.get('import_compatibility_recovery_count') == 1
        and not case.get('import_compatibility_tool_repair_count')
        and not (Path(output)/'single_state.json').exists()
        and not (Path(output)/'opened_candidate.json').exists())


def load(root, ident, project):
    from .batch import read
    policy = Path(root)/POLICY
    if not policy.is_file():
        return None
    value = read(policy)
    if value.get('version') != VERSION:
        raise ValueError('Unknown import compatibility policy')
    entry = value.get('entries', {}).get(ident)
    if entry is None:
        return None
    if entry.get('reviewed') is not True or Path(entry['project']).resolve() != Path(project).resolve():
        raise ValueError('Import compatibility source review mismatch')
    if not entry.get('files'):
        raise ValueError('Empty import compatibility review')
    for item in entry['files']:
        relative = Path(item['source'])
        if (relative.is_absolute() or '..' in relative.parts or relative.parts[0] != 'Assets'
                or relative.suffix != '.cs'):
            raise ValueError('Unsafe import compatibility source')
        source = Path(project)/relative
        if not source.resolve().is_relative_to(Path(project).resolve()) or source.is_symlink():
            raise ValueError('Import compatibility source escaped project')
        namespaces = item.get('namespaces', [])
        if (not namespaces or len(set(namespaces)) != len(namespaces)
                or not set(namespaces).issubset(NAMESPACES)):
            raise ValueError('Only explicitly allowed namespace imports may be added')
        if sha(source) != item['source_sha256']:
            raise ValueError('Import compatibility source SHA changed')
    return dict(entry, policy_path=str(policy.resolve()), policy_sha256=sha(policy))


def apply(entry, ident, sandbox, receipt):
    """Prefix using directives only; refuse source drift and retain exact diff."""
    if load(Path(entry['policy_path']).parent, ident, entry['project']) != entry:
        raise ValueError('Import compatibility policy changed')
    sandbox = Path(sandbox).resolve()
    changes = []
    # Validate every file before modifying any file.
    for item in entry['files']:
        path = sandbox/item['source']
        if path.is_symlink() or not path.resolve().is_relative_to(sandbox) or sha(path) != item['source_sha256']:
            raise ValueError('Import compatibility snapshot SHA changed')
        before = path.read_bytes()
        text = before.decode('utf-8-sig')
        for namespace in item['namespaces']:
            if re.search(r'(?m)^\s*using\s+'+re.escape(namespace)+r'\s*;', text):
                raise ValueError('Reviewed import already exists')
        prefix = ''.join('using '+ns+';\n' for ns in item['namespaces']).encode()
        after = (b'\xef\xbb\xbf'+prefix+before[3:]) if before.startswith(b'\xef\xbb\xbf') else prefix+before
        changes.append((path, before, after, item))
    records = []
    for path, before, after, item in changes:
        path.write_bytes(after)
        records.append({'source':item['source'], 'before_sha256':item['source_sha256'],
            'after_sha256':sha(path), 'added_imports':item['namespaces'],
            'diff':''.join('+'+'using '+ns+';\n' for ns in item['namespaces']),
            'original_body_byte_identical':after.endswith(before[3:]) if before.startswith(b'\xef\xbb\xbf') else after.endswith(before)})
    result = {'version':VERSION, 'entry':entry, 'changes':records, 'created_unix':time.time(),
        'scope':'Namespace imports only in isolated snapshot. No runtime logic, scenes, events or evidence edited.',
        'source_project_unchanged':all(sha(Path(entry['project'])/item['source'])==item['source_sha256'] for item in entry['files'])}
    dump(receipt, result)
    if result['source_project_unchanged'] is not True:
        raise ValueError('Original source changed during import compatibility')
    return {'path':str(receipt), 'sha256':sha(Path(receipt))}


def eligible(config, output, case, row):
    return (case.get('status') == 'BOUNDED_FAILURE' and case.get('phase') == 'admission'
        and not case.get('import_compatibility_recovery_count')
        and not (Path(output)/'single_state.json').exists()
        and not (Path(output)/'opened_candidate.json').exists()
        and bool(row.get('project')) and bool(config.get('batch'))
        and load(config['batch'], row['id'], row['project']) is not None)


def verified_builder_import(entry, ident, sandbox, source):
    """An original authored builder may only differ by its reviewed using prefix."""
    if load(Path(entry['policy_path']).parent, ident, entry['project']) != entry:
        raise ValueError('Import compatibility policy changed')
    item = next((item for item in entry['files'] if item['source'] == source), None)
    if item is None:
        return False
    original = (Path(entry['project'])/source).read_bytes()
    prefix = ''.join('using '+ns+';\n' for ns in item['namespaces']).encode()
    expected = b'\xef\xbb\xbf'+prefix+original[3:] if original.startswith(b'\xef\xbb\xbf') else prefix+original
    return (Path(sandbox)/source).read_bytes() == expected
