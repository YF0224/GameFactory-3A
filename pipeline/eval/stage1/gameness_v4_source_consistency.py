"""Reconcile immutable reviewed authors with additional delivered generated files.

No author source is omitted or reclassified, and supplemental bytes stay delivered.
This is not a static review of generated files or a product credit decision.
"""
from pathlib import Path
from .protocol import sha, dump, checked_path
from . import mechanic_v3_runner as runner

VERSION = 'gameness-v4-reviewed-authors-generated-supplement.v1'
PROOF = 'engineering/gameness_runtime_source_consistency.json'
GENERATED = {'dist', 'build'}


def verify(root, manifest, review):
    from .gameness_v3_runtime import source_files
    root = Path(root).resolve()
    entry = runner.read(root/'input_manifest.json')['entry']
    project = Path(entry['project']).resolve()
    expected = {'SRC:'+str(p.relative_to(project)): sha(p) for p in source_files(project)}
    reviewed = review['source_binding']['source_sha256_by_id']
    if not expected or reviewed != expected:
        raise ValueError('First-stage review does not cover every immutable original author source')
    sources = [i for i in manifest['items'] if i['type'] == 'source']
    delivered = {i['id']: i['sha256'] for i in sources}
    if len(delivered) != len(sources) or not expected.keys() <= delivered.keys():
        raise ValueError('Runtime source IDs are duplicated or reviewed author source is missing')
    supplementary = []
    bindings = {}
    for item in sources:
        ident = item['id']
        if not ident.startswith('SRC:'):
            raise ValueError('Runtime author source identity is not canonical')
        relative = Path(ident[4:])
        if not relative.parts or relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Runtime source path is not a relative author path')
        if item['path'] != str(Path('input/project')/relative):
            raise ValueError('Runtime source path differs from its author identity')
        frozen = checked_path(root, item['path'])
        original = checked_path(project, str(relative))
        if sha(frozen) != item['sha256'] or sha(original) != item['sha256']:
            raise ValueError('Original or delivered source SHA differs')
        bindings[str(frozen)] = sha(frozen)
        bindings[str(original)] = sha(original)
        if ident in expected:
            if delivered[ident] != expected[ident]:
                raise ValueError('Runtime reviewed author source SHA changed')
        else:
            if not (set(relative.parts[:-1]) & GENERATED):
                raise ValueError('Unreviewed non-generated author source is not supplemental')
            supplementary.append(dict(id=ident, path=item['path'], sha256=item['sha256'],
                role='additional_generated_context_fully_delivered_not_a_replacement_for_reviewed_authors'))
    proof = dict(version=VERSION, identity=entry['id'], project=str(project),
                 reviewed_author_sha256_by_id=expected, delivered_source_sha256_by_id=delivered,
                 supplemental_generated_sources=supplementary, source_bindings=bindings,
                 complete_reviewed_authors_unchanged=True, supplemental_bytes_still_delivered=True,
                 source_existence_judgments_unchanged=True, scoring_semantics_unchanged=True)
    path = root/PROOF
    if path.exists() and runner.read(path) != proof:
        raise ValueError('Retained source consistency proof differs')
    if not path.exists():
        dump(path, proof)
    return proof
