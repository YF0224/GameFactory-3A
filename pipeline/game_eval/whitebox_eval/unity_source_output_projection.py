"""Source-bound omission of reviewed historical outputs from a new admission copy.

Original output/evidence trees remain in place. This policy cannot omit imported
Unity source, change authored bytes or alter a recorder capability/accepted pin.
"""
from pathlib import Path
import json
import os
import shutil
from .protocol import dump, sha

VERSION = 'unity-generated-output-source-projection.v1'
POLICY = 'unity_source_output_projection.json'
ROOT = 'validation'
OUTPUT_CHILDREN = {'smoke', 'launch', 'frames', 'playtest', 'build'}


def source_files(source, excluded=None):
    from engine_adapters.unity3d.playtest.project_snapshot import EXCLUDED
    source = Path(source)
    if source.is_symlink() or not source.is_dir():
        raise ValueError('Generated-output projection source must be a real project')
    for folder, dirs, files in os.walk(source, followlinks=False):
        base = Path(folder)
        removed = [name for name in dirs if name in EXCLUDED
                   or (base == source and name == ROOT)]
        if excluded is not None:
            excluded.extend(str((base/name).relative_to(source)) for name in removed)
        dirs[:] = sorted(name for name in dirs if name not in removed)
        for name in sorted(files):
            path = base/name
            if path.is_symlink():
                raise ValueError('Snapshot refuses symlink: '+str(path))
            yield path


def facts(source):
    source = Path(source)
    output = source/ROOT
    if output.is_symlink() or not output.is_dir():
        raise ValueError('Reviewed historical output root missing or symlinked')
    children = list(output.iterdir())
    if ({p.name for p in children} != OUTPUT_CHILDREN
            or any(p.is_symlink() or not p.is_dir() for p in children)):
        raise ValueError('Historical output children differ from reviewed delivery')
    files = {str(p.relative_to(source)): sha(p) for p in source_files(source)}
    if not all(any(name.startswith(root+'/') for name in files)
               for root in ('Assets', 'Packages', 'ProjectSettings')):
        raise ValueError('Reviewed projection lacks authored Unity project inputs')
    return files


def load(batch, ident, source):
    path = Path(batch)/POLICY
    if not path.is_file():
        return None
    value = json.loads(path.read_text())
    if value.get('version') != VERSION:
        raise ValueError('Unknown generated-output projection policy')
    entry = value.get('entries', {}).get(ident)
    if entry is None:
        return None
    if (entry.get('reviewed') is not True or entry.get('id') != ident
            or Path(entry['project']).resolve() != Path(source).resolve()
            or entry.get('excluded_roots') != [ROOT]
            or entry.get('generated_output_children') != sorted(OUTPUT_CHILDREN)
            or entry.get('original_outputs_retained') is not True
            or entry.get('source_read_dependencies_in_excluded_root') != []):
        raise ValueError('Generated-output projection review/source mismatch')
    review = Path(entry['review_receipt'])
    if review.is_symlink() or sha(review) != entry['review_receipt_sha256']:
        raise ValueError('Generated-output projection review receipt changed')
    if facts(Path(source)) != entry['copied_source_sha256']:
        raise ValueError('Generated-output projection authored source drift')
    return dict(entry, policy_path=str(path.resolve()), policy_sha256=sha(path))


def verify(entry, ident, source):
    policy = Path(entry['policy_path'])
    if (sha(policy) != entry['policy_sha256']
            or load(policy.parent, ident, source) != entry):
        raise ValueError('Generated-output projection binding changed')


def measure(entry, ident, source):
    verify(entry, ident, source)
    paths = list(source_files(Path(source)))
    return {'source_bytes': sum(p.stat().st_size for p in paths),
            'source_file_count': len(paths), 'policy_path': entry['policy_path'],
            'policy_sha256': entry['policy_sha256'], 'excluded_roots': [ROOT],
            'original_outputs_retained': True}


def snapshot(entry, ident, source, destination):
    from engine_adapters.unity3d.playtest import project_snapshot
    from engine_adapters.unity3d.playtest.input_axis_serialization import normalize_snapshot
    source, destination = Path(source), Path(destination)
    verify(entry, ident, source)
    if destination.exists():
        raise ValueError('Projection snapshot destination already exists')
    output_stat = (source/ROOT).stat()
    manifest = {}
    excluded = []
    for path in source_files(source, excluded):
        relative = str(path.relative_to(source))
        expected = entry['copied_source_sha256'].get(relative)
        if expected is None or sha(path) != expected:
            raise ValueError('Projection source changed while copying: '+relative)
        target = destination/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        if sha(target) != expected:
            raise ValueError('Projection copy SHA mismatch: '+relative)
        manifest[relative] = expected
    if manifest != entry['copied_source_sha256']:
        raise ValueError('Projection copy source set changed')
    verify(entry, ident, source)
    current = (source/ROOT).stat()
    if (output_stat.st_dev, output_stat.st_ino, output_stat.st_mtime_ns) != (
            current.st_dev, current.st_ino, current.st_mtime_ns):
        raise ValueError('Historical output root changed during projection')
    normalization = normalize_snapshot(source, destination)
    receipt = {'version': VERSION, 'policy_path': entry['policy_path'],
               'policy_sha256': entry['policy_sha256'], 'id': ident,
               'source': str(source), 'excluded_roots': [ROOT],
               'original_outputs_retained': True, 'authored_source_unchanged': True,
               'review_receipt': entry['review_receipt'],
               'review_receipt_sha256': entry['review_receipt_sha256']}
    dump(destination.parent/'generated_output_projection.json', receipt)
    return {'policy': project_snapshot.SNAPSHOT_POLICY, 'source': str(source),
            'files_sha256': manifest, 'excluded_artifacts': excluded,
            'fixture_injection_excluded': False, 'input_axis_normalization': normalization,
            'generated_output_projection': receipt}
