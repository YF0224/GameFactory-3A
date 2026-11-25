"""Exact-error-bound direct assembly references, confined to isolated manifests."""
from pathlib import Path
import json
import re

from .protocol import sha


def asset(root, relative, suffix):
    relative = Path(relative)
    root = Path(root).resolve()
    if (relative.is_absolute() or '..' in relative.parts or relative.parts[:1] != ('Assets',)
            or relative.suffix != suffix):
        raise ValueError('Unsafe reviewed assembly asset path')
    path = root / relative
    if (not path.is_file() or not path.resolve().is_relative_to(root/'Assets')
            or any(part.is_symlink() for part in (path, *path.parents) if part != root and root in part.parents)):
        raise ValueError('Reviewed assembly asset missing or escaped')
    return path


def owner(root, source):
    root = Path(root).resolve()
    directory = Path(source).parent
    while directory.is_relative_to(root/'Assets'):
        definitions = list(directory.glob('*.asmdef'))
        if list(directory.glob('*.asmref')):
            raise ValueError('Assembly reference indirection requires separate review')
        if definitions:
            if len(definitions) != 1:
                raise ValueError('Ambiguous assembly definition owner')
            return definitions[0].relative_to(root).as_posix()
        directory = directory.parent
    raise ValueError('Reviewed source has no explicit assembly definition')


def verify_assets(entry, root):
    root = Path(root).resolve()
    definition = asset(root, entry['source'], '.asmdef')
    if sha(definition) != entry['source_sha256']:
        raise ValueError('Reviewed source assembly definition changed')
    value = json.loads(definition.read_text())
    references = value.get('references')
    reference = entry.get('reference')
    if (not isinstance(reference, str) or not re.fullmatch(r'[A-Za-z_][\w.]*', reference)
            or not isinstance(references, list) or any(not isinstance(r, str) for r in references)
            or any(r.startswith('GUID:') for r in references) or reference in references):
        raise ValueError('Direct reference review is invalid or already declared')
    target = asset(root, entry['reference_definition'], '.asmdef')
    if sha(target) != entry['reference_definition_sha256'] or json.loads(target.read_text()).get('name') != reference:
        raise ValueError('Referenced assembly definition changed or mismatched')
    if value.get('name') == reference:
        raise ValueError('Self assembly reference is invalid')
    bindings = entry.get('compiler_sources')
    types = entry.get('referenced_types')
    if (not isinstance(bindings, dict) or not bindings or not isinstance(types, dict) or not types
            or any(not isinstance(k, str) or not isinstance(v, str) for k, v in bindings.items())):
        raise ValueError('Exact compiler/type source bindings required')
    for relative, digest in bindings.items():
        source = asset(root, relative, '.cs')
        if sha(source) != digest or owner(root, source) != entry['source']:
            raise ValueError('Compiler source changed or belongs to another assembly')
    for type_name, binding in types.items():
        if (not isinstance(type_name, str) or not re.fullmatch(r'[A-Za-z_]\w*', type_name)
                or not isinstance(binding, dict)):
            raise ValueError('Invalid referenced type binding')
        source = asset(root, binding['source'], '.cs')
        if (sha(source) != binding['sha256'] or owner(root, source) != entry['reference_definition']
                or not re.search(r'\b(?:class|struct|enum|interface)\s+'+re.escape(type_name)+r'\b', source.read_text())):
            raise ValueError('Referenced type changed or belongs to another assembly')
    return value


def review(entry, errors):
    verify_assets(entry, entry['project'])
    sources, types = set(), set()
    for line in errors:
        match = re.match(r"^(Assets/[^:\n]+\.cs)\(\d+,\d+\): error CS0012: The type '([^']+)' is defined in an assembly that is not referenced\. You must add a reference to assembly '([^,']+),", line)
        if not match:
            raise ValueError('Unexpected compiler error in direct reference review')
        source, type_name, reference = match.groups()
        if (source not in entry['compiler_sources'] or type_name not in entry['referenced_types']
                or reference != entry['reference']):
            raise ValueError('Compiler error does not bind the reviewed assembly/type/source')
        sources.add(source); types.add(type_name)
    if not errors or sources != set(entry['compiler_sources']) or types != set(entry['referenced_types']):
        raise ValueError('Reference review must cover exactly all compiler failures')
    if 'array_length_compatibility' in entry:
        from .unity_array_length_recovery import review as review_array
        review_array(entry)
    return True


def apply_reference(entry, sandbox):
    from .protocol import dump
    # Validate original and every sandbox binding before a single manifest mutation.
    verify_assets(entry, entry['project'])
    value = verify_assets(entry, sandbox)
    prepared = None
    if 'array_length_compatibility' in entry:
        from .unity_array_length_recovery import prepare
        prepared = prepare(entry, sandbox)
    path = asset(sandbox, entry['source'], '.asmdef')
    before = path.read_bytes()
    value['references'].append(entry['reference'])
    dump(path, value)
    extra = {}
    if prepared is not None:
        from .unity_array_length_recovery import apply
        extra['array_length_compatibility'] = apply(entry, sandbox, prepared)
    return {**extra, 'assembly_reference_added': entry['reference'], 'before_utf8': before.decode('utf-8'),
            'after_utf8': path.read_text(), 'gameplay_changes': [],
            'compiler_sources_unchanged': entry['compiler_sources'],
            'referenced_types_unchanged': entry['referenced_types'],
            'reference_definition_sha256': entry['reference_definition_sha256']}
