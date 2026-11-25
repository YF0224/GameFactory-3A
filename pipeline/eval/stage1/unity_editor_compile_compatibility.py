"""Reviewed, isolated compatibility edits for optional authored Editor helpers."""
from pathlib import Path
import hashlib
import time

from .protocol import dump, sha

VERSION = 'whitebox-unity-editor-compile-compatibility.v1'
POLICY = 'unity_editor_compile_compatibility_policy.json'


def _entry(batch_root, ident, project):
    from .batch import read
    path = Path(batch_root) / POLICY
    if not path.is_file():
        return None
    policy = read(path)
    if policy.get('version') != VERSION:
        raise ValueError('Unknown editor compile compatibility policy')
    entry = policy.get('entries', {}).get(ident)
    if entry is None:
        return None
    if entry.get('reviewed') is not True or Path(entry['project']).resolve() != Path(project).resolve():
        raise ValueError('Editor compile compatibility source review mismatch')
    source = Path(entry['source'])
    if source.is_absolute() or '..' in source.parts or source.parts[:1] != ('Assets',) or source.suffix != '.cs':
        raise ValueError('Unsafe editor compile compatibility source')
    if entry.get('operation') != 'disable_optional_method':
        raise ValueError('Unsupported editor compile compatibility operation')
    original = Path(project) / source
    if not original.resolve().is_relative_to(Path(project).resolve()) or original.is_symlink():
        raise ValueError('Editor compile compatibility source escaped project')
    if sha(original) != entry['source_sha256']:
        raise ValueError('Editor compile compatibility source SHA changed')
    if entry.get('method_signature') != 'public static void BuildPlayer(string outputDir)':
        raise ValueError('Only the unused optional BuildPlayer helper is reviewed')
    if 'Editor' not in source.parts and not source.name.endswith('Editor.cs'):
        raise ValueError('Optional helper must be an Editor source')
    return dict(entry, ident=ident, policy_path=str(path.resolve()), policy_sha256=sha(path))


def load(batch_root, ident, project):
    return _entry(batch_root, ident, project)


def _disable_method(text, signature):
    start = text.find(signature)
    if text.count(signature) != 1:
        raise ValueError('Optional editor method signature not found')
    brace = text.find('{', start)
    if brace < 0:
        raise ValueError('Optional editor method body not found')
    depth = 0
    in_string = None
    escaped = False
    for index in range(brace, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == in_string:
                in_string = None
            continue
        if char in ('"', "'"):
            in_string = char
        elif char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                body = '{\n        throw new System.NotSupportedException("Optional build helper disabled for native scene admission");\n    }'
                return text[:brace] + body + text[index + 1:]
    raise ValueError('Optional editor method body is unbalanced')


def apply(entry, ident, sandbox, receipt):
    if _entry(Path(entry['policy_path']).parent, ident, entry['project']) != entry:
        raise ValueError('Editor compile compatibility policy changed')
    sandbox = Path(sandbox).resolve()
    path = sandbox / entry['source']
    if path.is_symlink() or not path.resolve().is_relative_to(sandbox) or sha(path) != entry['source_sha256']:
        raise ValueError('Editor compile compatibility snapshot SHA changed')
    before = path.read_bytes()
    text = before.decode('utf-8-sig')
    after_text = _disable_method(text, entry['method_signature'])
    if after_text == text:
        raise ValueError('Editor compile compatibility made no change')
    after = (b'\xef\xbb\xbf' + after_text.encode('utf-8')) if before.startswith(b'\xef\xbb\xbf') else after_text.encode('utf-8')
    path.write_bytes(after)
    result = {
        'version': VERSION, 'entry': entry,
        'source': entry['source'], 'before_sha256': sha_bytes(before), 'after_sha256': sha(path),
        'operation': entry['operation'], 'method_signature': entry['method_signature'],
        'scope': 'Isolated authored Editor helper only; BuildScene and runtime gameplay untouched.',
        'source_project_unchanged': sha(Path(entry['project']) / entry['source']) == entry['source_sha256'],
        'created_unix': time.time(),
    }
    dump(receipt, result)
    if result['source_project_unchanged'] is not True:
        raise ValueError('Original source changed during editor compile compatibility')
    return {'path': str(Path(receipt)), 'sha256': sha(Path(receipt))}


def sha_bytes(value):
    return hashlib.sha256(value).hexdigest()


def verified(entry, sandbox):
    if not entry:
        return False
    try:
        loaded = _entry(Path(entry['policy_path']).parent, entry['ident'], entry['project'])
    except (ValueError, OSError, KeyError):
        return False
    if loaded != entry:
        return False
    sandbox = Path(sandbox).resolve()
    path = sandbox / entry['source']
    if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(sandbox):
        return False
    before = Path(entry['project']) / entry['source']
    if not before.is_file():
        return False
    try:
        expected = _disable_method(before.read_text(encoding='utf-8-sig'), entry['method_signature'])
    except ValueError:
        return False
    actual = path.read_text(encoding='utf-8-sig')
    return actual == expected


def eligible(batch_root, output, case, row):
    error = str(case.get('error', ''))
    receipt = Path(error.split('see ', 1)[1]) if 'see ' in error else None
    return (case.get('status') == 'BOUNDED_FAILURE'
        and case.get('phase') == 'admission'
        and error.startswith('Authored scene builder failed; see ')
        and receipt is not None and receipt.is_file()
        and case.get('import_compatibility_tool_repair_count') == 1
        and not case.get('authored_entry_compile_compatibility_recovery_count')
        and not (Path(output) / 'single_state.json').exists()
        and not (Path(output) / 'opened_candidate.json').exists()
        and bool(row.get('project'))
        and load(batch_root, row['id'], row['project']) is not None)
