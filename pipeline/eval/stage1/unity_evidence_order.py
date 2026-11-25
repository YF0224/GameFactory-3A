"""Deterministic source priority for new recorded Unity judge packages."""
import json
from .protocol import dump, sha


def _source_hints(root, manifest):
    """Use saved source references only when their exact path/SHA is in this package."""
    available = {item['path'].removeprefix('input/project/'): item.get('sha256')
                 for item in manifest['items'] if item['type'] == 'source'}
    core, supplemental, bindings = set(), set(), []

    def collect(value, selected):
        if isinstance(value, dict):
            path = value.get('path', '')
            if isinstance(path, str):
                relative = path.removeprefix('input/project/').removeprefix('project/')
                digest = value.get('sha256')
                if digest and available.get(relative) == digest:
                    selected.add('input/project/'+relative)
            for child in value.values():
                collect(child, selected)
        elif isinstance(value, list):
            for child in value:
                collect(child, selected)

    for name, selected in [('static_existence.json', core),
                           ('recovery_source/static_source_scores.json', supplemental)]:
        path = root/name
        if path.is_file():
            collect(json.loads(path.read_text()), selected)
            bindings.append({'path': name, 'sha256': sha(path)})
    return core, supplemental, bindings


def prioritize(root, manifest):
    core, supplemental, bindings = _source_hints(root, manifest)

    def rank(item):
        path = item['path'].lower()
        ident = item['id']
        parts = set(path.split('/'))
        auxiliary = ('editor' in parts or any('test' in part for part in parts))
        framework = bool(parts & {'packages', 'thirdparty', 'plugins', 'a3gameruntime'}) or any(
            token in path for token in ('gamefactory', 'inputmigration'))
        if item['type'] == 'source' and item['path'] in core:
            return (0, path)
        if path.startswith('input/delivery_documents/'):
            return (3, path)
        if item['type'] == 'source' and item['path'] in supplemental:
            return (1, path)
        if ident.startswith('INITIAL_SOURCE_SCORES:') or ident == 'SUPPLEMENTAL_SOURCE_DIAGNOSTIC_STATUS':
            return (4, path)
        if item['type'] == 'source' and not framework and not auxiliary:
            return (2 if path.endswith('.cs') else 5, path)
        if item['type'] == 'source':
            return (7 if auxiliary else 6, path)
        return (8, path)

    before = [row['id'] for row in manifest['items']]
    manifest['items'] = sorted(manifest['items'], key=rank)
    dump(root/'source_delivery_priority.json', {
        'version': 'unity-authored-source-priority.v2',
        'original_ids': before, 'ordered_ids': [row['id'] for row in manifest['items']],
        'source_reference_bindings': bindings,
        'core_source_paths': sorted(core), 'supplemental_source_paths': sorted(supplemental),
        'items_removed': [], 'caps_unchanged': True,
        'omissions_report': 'Each actual judge request preserves batch.packet omitted physical lines'})
    return manifest
