"""Explicit roles for exact Godot-generated texture metadata additions.

Never ignore a suffix or modify an original manifest. An immutable authorization
names every generated file and its unchanged original PNG. All other original
files and all unlisted additions remain strict. Historical judge views inherit
only their exact accepted source run's authorization.
"""
from pathlib import Path, PurePosixPath
import re
from .protocol import sha
from . import mechanic_v3_runner as runner

VERSION = 'whitebox-exact-godot-generated-sidecars.v1'
AUTH = 'engineering/exact_godot_generated_sidecars.json'


def roles(project, expected, current, additions):
    if not additions or set(current) != set(expected) | set(additions):
        raise ValueError('Only the exact explicitly declared additions may differ')
    if any(current.get(p) != digest for p, digest in expected.items()):
        raise ValueError('Original author bytes changed')
    result = {}
    for name, digest in additions.items():
        rel = PurePosixPath(name)
        if (rel.is_absolute() or '..' in rel.parts or not name.endswith('.png.import')
                or name in expected or current.get(name) != digest):
            raise ValueError('Generated sidecar path or digest differs')
        path = Path(project)/name
        if path.is_symlink() or sha(path) != digest:
            raise ValueError('Generated metadata bytes changed')
        image = name.removesuffix('.import')
        if image not in expected or current.get(image) != expected[image]:
            raise ValueError('Sidecar must describe an unchanged original PNG')
        text = path.read_text()
        def one(pattern):
            found = re.findall(pattern, text, flags=re.M)
            if len(found) != 1:
                raise ValueError('Ambiguous or missing Godot texture metadata')
            return found[0]
        if (one(r'^importer="([^"]+)"$') != 'texture'
                or one(r'^type="([^"]+)"$') != 'CompressedTexture2D'
                or one(r'^source_file="([^"]+)"$') != 'res://'+image):
            raise ValueError('Sidecar is not the declared texture importer output')
        target = one(r'^path="([^"]+)"$')
        destination = one(r'^dest_files=\["([^"]+)"\]$')
        if (target != destination or not target.startswith('res://.godot/imported/')
                or not target.endswith('.ctex') or '..' in PurePosixPath(target[6:]).parts):
            raise ValueError('Sidecar has an external or nontexture output')
        result[name] = dict(sha256=digest,role='GODOT_GENERATED_TEXTURE_IMPORT_METADATA',
            original_png=image,original_png_sha256=expected[image],cache_target=target)
    return result


def authorize(source, diagnosis, repair):
    from . import batch
    source, diagnosis, repair = map(lambda x: Path(x).resolve(), (source, diagnosis, repair))
    original = runner.read(source/'input_manifest.json')
    data = runner.read(diagnosis)
    if (original['entry']['actual_engine'] != 'godot' or data['source_run'] != str(source)
            or data['project'] != original['entry']['project'] or data['changed_originals']):
        raise ValueError('Exact original Godot diagnosis required')
    project = Path(original['entry']['project'])
    current = batch.hashes(project)
    role_map = roles(project,original['source_hashes_before'],current,data['added_files'])
    if batch.hashes(source/'input') != original['input_hashes']:
        raise ValueError('Frozen evaluator input changed')
    q = runner.read(source/'source_qualification.json')
    if q.get('new_recording') is not True or q.get('raw_record_reused') is not False:
        raise ValueError('Existing accepted native recording required')
    for path,digest in q['source_bindings'].items():
        if sha(Path(path)) != digest:
            raise ValueError('Accepted recording binding changed')
    files = [source/'input_manifest.json',source/'source_qualification.json',diagnosis,repair,
             Path(__file__).resolve(),Path(batch.__file__).resolve()]
    value = dict(version=VERSION,source=str(source),identity=source.name,project=str(project),
        roles=role_map,original_source_hashes=original['source_hashes_before'],
        input_manifest_sha256=sha(source/'input_manifest.json'),
        original_manifest_unchanged=True,original_author_files_unchanged=True,
        generated_metadata_is_not_source_or_runtime_evidence=True,
        bindings={str(p):sha(p) for p in files})
    dest = source/AUTH
    if dest.exists():
        if runner.read(dest) != value:
            raise ValueError('Immutable generated-role authorization differs')
    else:
        runner.exclusive_json(dest,value)
    return dict(path=str(dest),sha256=sha(dest))


def verify(root, original, current):
    root = Path(root).resolve()
    source = root
    reuse = root/'qualified_record_reuse.json'
    if reuse.exists():
        proof = runner.read(reuse)
        if proof.get('execution_allowed') is not False:
            raise ValueError('Generated metadata cannot authorize native execution')
        source = Path(proof['source']).resolve()
        if (sha(source/'source_qualification.json') != proof['qualification_sha256']
                or root.name != source.name):
            raise ValueError('Historical source role inheritance changed')
    path = source/AUTH
    if not path.exists():
        return False
    value = runner.read(path)
    if (value.get('version') != VERSION or value.get('source') != str(source)
            or value.get('identity') != root.name or original['entry']['actual_engine'] != 'godot'
            or value.get('project') != original['entry']['project']
            or value.get('original_source_hashes') != original['source_hashes_before']
            or value.get('input_manifest_sha256') != sha(root/'input_manifest.json')):
        raise ValueError('Exact generated-role identity or original binding changed')
    for name,digest in value['bindings'].items():
        if sha(Path(name)) != digest:
            raise ValueError('Generated-role authorization binding changed: '+name)
    additions = {name:role['sha256'] for name,role in value['roles'].items()}
    actual = roles(Path(value['project']),original['source_hashes_before'],current,additions)
    if actual != value['roles']:
        raise ValueError('Generated metadata role changed')
    return True
