"""Review exact duplicate and unused Editor units before isolated compile exclusion."""
from pathlib import Path
import hashlib
import re

from .protocol import sha

PREFIX = b'#if false // isolated native compatibility; original compilation unit follows\n'
SUFFIX = b'\n#endif // end preserved original compilation unit\n'


def source_path(project, relative):
    project = Path(project).resolve()
    relative = Path(relative)
    path = project / relative
    if (relative.is_absolute() or '..' in relative.parts or relative.parts[:1] != ('Assets',)
            or path.is_symlink() or not path.resolve().is_relative_to(project) or not path.is_file()):
        raise ValueError('Unsafe reviewed compilation unit path')
    return path


def assembly(project, source):
    project = Path(project).resolve()
    folder = source_path(project, source).parent
    while folder.is_relative_to(project / 'Assets'):
        boundaries = sorted(list(folder.glob('*.asmdef')) + list(folder.glob('*.asmref')))
        if boundaries:
            if len(boundaries) != 1 or boundaries[0].suffix != '.asmdef':
                raise ValueError('Ambiguous or referenced compilation boundary')
            return boundaries[0]
        if folder.name in ('Editor', 'Plugins', 'Standard Assets', 'Pro Standard Assets'):
            raise ValueError('Special compilation folder requires separate review')
        folder = folder.parent
    raise ValueError('Explicit matching assembly definition required')


def review(entry):
    """Recompute assembly and unreferenced-source proof; never trust a flag alone."""
    project = Path(entry['project']).resolve()
    duplicate = source_path(project, entry['source'])
    canonical = source_path(project, entry['canonical_source'])
    optional = source_path(project, entry['optional_editor_source'])
    if (duplicate == canonical or duplicate.suffix != '.cs' or canonical.suffix != '.cs'
            or sha(duplicate) != entry['source_sha256'] or sha(canonical) != entry['canonical_sha256']
            or duplicate.read_bytes() != canonical.read_bytes()):
        raise ValueError('Compilation units must be byte-identical and source-bound')
    boundary = assembly(project, entry['source'])
    if (assembly(project, entry['canonical_source']) != boundary
            or boundary != source_path(project, entry['assembly_definition'])
            or sha(boundary) != entry['assembly_sha256']):
        raise ValueError('Duplicate compilation units are not in the same reviewed assembly')
    text = duplicate.read_text(encoding='utf-8-sig')
    if re.search(r'CallerFilePath|#\s*(line|pragma|if|elif|else|endif|define|undef)\b', text):
        raise ValueError('Path-sensitive or conditional duplicate requires further review')
    optional_text = optional.read_text(encoding='utf-8-sig')
    name = entry['optional_editor_class']
    if (optional.suffix != '.cs' or 'Editor' not in optional.relative_to(project).parts
            or not re.fullmatch(r'[A-Za-z_]\w*', name) or sha(optional) != entry['optional_editor_sha256']
            or len(re.findall(r'\b(?:class|struct|interface|enum|record)\s+\w+', optional_text)) != 1
            or not re.search(r'public\s+static\s+class\s+' + re.escape(name) + r'\b', optional_text)
            or re.search(r'(?m)^\s*\[', optional_text)
            or re.search(r'InitializeOnLoad|RuntimeInitializeOnLoad|ModuleInitializer|MenuItem|#\s*(if|elif|else|endif|define|undef)\b', optional_text)
            or re.search(r'\bstatic\s+' + re.escape(name) + r'\s*\(', optional_text)
            or re.search(r'\bstatic\s+(?!(?:class|void)\b)(?:readonly\s+)?[\w.<>\[\],]+\s+\w+\s*(?:=|;|\{)', optional_text)):
        raise ValueError('Only an unreferenced optional Editor helper without startup hooks is allowed')
    meta = duplicate.with_name(duplicate.name + '.meta')
    optional_meta = optional.with_name(optional.name + '.meta')
    tokens = [entry['source'], str(duplicate).replace('\\', '/')]
    for path in (meta, optional_meta):
        if path.exists():
            match = re.search(r'(?m)^guid:\s*(\S+)\s*$', path.read_text())
            if not match:raise ValueError('Reviewed source meta GUID unavailable')
            tokens.append(match.group(1))
    bindings = {str(p): sha(p) for p in (duplicate, canonical, optional, boundary, meta, optional_meta) if p.exists()}
    for path in (project / 'Assets').rglob('*'):
        if not path.is_file():continue
        if path.is_symlink() or not path.resolve().is_relative_to(project):
            raise ValueError('Asset reference proof cannot follow symlinks')
        if path in (duplicate, canonical, optional, meta, optional_meta):continue
        raw = path.read_bytes()
        bindings[str(path)] = sha(path)
        if any(token.encode() in raw for token in tokens):
            raise ValueError('Excluded compilation unit has an asset/path reference: ' + str(path))
        if b'\0' in raw:continue
        try:content = raw.decode('utf-8-sig')
        except UnicodeDecodeError:continue
        if any(token in content for token in tokens):
            raise ValueError('Excluded compilation unit has an asset/path reference: ' + str(path))
        if path.suffix == '.cs' and re.search(r'\b' + re.escape(name) + r'\b', content):
            raise ValueError('Optional Editor helper is referenced by authored code: ' + str(path))
        bindings[str(path)] = sha(path)
    return bindings


def verify_compiler_errors(entry, errors):
    duplicate = entry['source']
    canonical = entry['canonical_source']
    optional = entry['optional_editor_source']
    duplicate_errors = [line for line in errors if any(line.startswith(p + '(') for p in (duplicate, canonical))]
    if (not duplicate_errors or not any('CS0101:' in line for line in duplicate_errors)
            or not any('CS0111:' in line for line in duplicate_errors)):
        raise ValueError('No completed duplicate-definition compiler failure')
    for line in errors:
        if (line in duplicate_errors or any(full.endswith(line) and len(full)>len(line) for full in duplicate_errors)) and ('CS0101:' in line or 'CS0111:' in line):continue
        if line.startswith(optional + '(') and any(code in line for code in ('CS0234:', 'CS0103:', 'CS1503:')):continue
        raise ValueError('Additional compiler failure needs its own source review: ' + line)


def apply_exclusions(entry, sandbox):
    bindings = review(entry)
    sandbox = Path(sandbox).resolve()
    changes = []
    # Prevalidate all paths and bytes before applying either reversible wrapper.
    for name, digest in ((entry['source'], entry['source_sha256']),
                         (entry['optional_editor_source'], entry['optional_editor_sha256'])):
        path = source_path(sandbox, name)
        if sha(path) != digest:raise ValueError('Reviewed compilation unit snapshot changed')
        before = path.read_bytes()
        bom = b'\xef\xbb\xbf' if before.startswith(b'\xef\xbb\xbf') else b''
        body = before[len(bom):]
        changes.append((path, before, bom + PREFIX + body + SUFFIX, bom))
    canonical = source_path(sandbox, entry['canonical_source'])
    if sha(canonical) != entry['canonical_sha256']:
        raise ValueError('Canonical compiled unit snapshot changed')
    receipts = []
    for path, before, after, bom in changes:
        path.write_bytes(after)
        recovered = bom + after[len(bom) + len(PREFIX):-len(SUFFIX)]
        if recovered != before:raise ValueError('Compilation exclusion was not byte-reversible')
        receipts.append({'source':str(path.relative_to(sandbox)), 'before_sha256':hashlib.sha256(before).hexdigest(),
                         'after_sha256':sha(path),'original_body_byte_identical':True,
                         'prefix_utf8':PREFIX.decode(),'suffix_utf8':SUFFIX.decode(),
                         'original_physical_line_offset':1,'original_text_retained_in_cs_file':True})
    return {'changes':receipts,'qualification_sha256':bindings,
            'canonical_source':entry['canonical_source'],'canonical_unchanged':sha(canonical)==entry['canonical_sha256'],
            'originals_unchanged':all(sha(Path(entry['project'])/name)==digest for name,digest in
                ((entry['source'],entry['source_sha256']),(entry['canonical_source'],entry['canonical_sha256']),
                 (entry['optional_editor_source'],entry['optional_editor_sha256'])))}
