"""Strict frozen-admission binding for naturally started runtime entry captures."""
from pathlib import Path
import json
import re
from hashlib import sha256

VERSION = 'unity-runtime-initializer-record-entry.v1'
METHOD = 'GameFactory3ARuntimeInitializerRecorder.Enter'
FIELDS = {'version','attempt','input_manifest_sha256','case','source','source_sha256',
          'type','method','admission_receipt','admission_receipt_sha256'}

def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()

def _facts(attempt):
    from pipeline.game_eval.whitebox_eval import batch, unity_native_entry
    root = Path(attempt).resolve()
    batch.verify_inputs(root)
    manifest = batch.read(root/'input_manifest.json')
    facts = unity_native_entry.load(root)
    if not facts or not facts.get('runtime_initializer_entry') or facts.get('natural_startup_observed') is not True:
        raise ValueError('Verified natural runtime admission required')
    return root, manifest, facts

def write(attempt, output):
    from pipeline.game_eval.whitebox_eval.protocol import dump
    root, manifest, facts = _facts(attempt)
    entry = facts['runtime_initializer_entry']
    value = {'version':VERSION,'attempt':str(root),
             'input_manifest_sha256':digest(root/'input_manifest.json'),
             'case':manifest['entry']['id'],'source':facts['source'],
             'source_sha256':facts['source_sha256'],'type':entry['type'],'method':entry['method'],
             'admission_receipt':facts['receipt'],'admission_receipt_sha256':facts['receipt_sha256']}
    dump(output,value)
    return value

def _binding(path):
    from pipeline.game_eval.whitebox_eval import batch
    value = json.loads(Path(path).read_text())
    if not isinstance(value,dict) or set(value) != FIELDS or value.get('version') != VERSION:
        raise ValueError('Unknown runtime recorder entry binding')
    root, manifest, facts = _facts(value['attempt'])
    entry = facts['runtime_initializer_entry']
    if (value['attempt'] != str(root)
            or value['input_manifest_sha256'] != digest(root/'input_manifest.json')
            or value['case'] != manifest['entry']['id']
            or value['source'] != facts['source'] or value['source_sha256'] != facts['source_sha256']
            or value['type'] != entry['type'] or value['method'] != entry['method']
            or value['admission_receipt'] != facts['receipt']
            or value['admission_receipt_sha256'] != facts['receipt_sha256']
            or Path(value['source']).is_absolute() or '..' in Path(value['source']).parts):
        raise ValueError('Runtime recorder entry differs from verified frozen admission')
    if batch.hashes(root/'input/project') != manifest['snapshot_hashes']:
        raise ValueError('Frozen runtime project bytes changed')
    return value, root, manifest


def load(path, project):
    """Prelaunch copy must match every frozen source byte, except exact policy exclusions and proven axis names."""
    value = json.loads(Path(path).read_text())
    if isinstance(value, dict) and value.get('version') == 'stage1-unity-runtime-initializer-record-entry.v1':
        from pipeline.eval.stage1.unity_natural_entry import load_record_binding
        return load_record_binding(path, project)
    from pipeline.game_eval.whitebox_eval import batch
    value, root, manifest = _binding(path)
    project = Path(project).resolve()
    expected = dict(manifest['snapshot_hashes'])
    current = batch.hashes(project)
    if current != expected:
        # The recorder applies the existing authored-project snapshot policy.
        # Check the exact source, exclusions and projected hashes before allowing
        # those policy-defined non-source omissions; never ignore arbitrary files.
        from . import project_snapshot
        snapshot_path = project.parent/'source_snapshot.json'
        if not snapshot_path.is_file():
            raise ValueError('Runtime recorder project differs from frozen source')
        source = Path(manifest['entry']['project']).resolve()
        if batch.hashes(source) != expected:
            raise ValueError('Runtime recorder project differs from frozen source')
        snapshot = json.loads(snapshot_path.read_text())
        excluded = []
        projected = {str(p.relative_to(source)):digest(p)
                     for p in project_snapshot.snapshot_files(source,excluded)}
        if (snapshot.get('policy') != project_snapshot.SNAPSHOT_POLICY
                or snapshot.get('source') != str(source)
                or snapshot.get('files_sha256') != projected
                or sorted(snapshot.get('excluded_artifacts',[])) != sorted(excluded)
                or snapshot.get('fixture_injection_excluded') is not False):
            raise ValueError('Runtime recorder snapshot policy/source binding differs')
        expected = projected
        package_proof = snapshot.get('package_path_relocation')
        if package_proof is not None:
            relative = project_snapshot.verify_package_relocation(source, project, package_proof)
            if expected.get(relative) != package_proof['manifest_before_sha256']:
                raise ValueError('Package relocation is not bound to original source')
            expected[relative] = package_proof['manifest_after_sha256']
        proof = snapshot.get('input_axis_normalization')
        if proof is not None:
            if proof.get('before_sha256') != expected.get(proof.get('path')):
                raise ValueError('Runtime snapshot has no exact axis normalization binding')
            from .input_axis_serialization import verify_snapshot
            relative = verify_snapshot(root/'input/project', project, proof)
            expected[relative] = proof['after_sha256']
    if current != expected or any((project/'Assets').rglob('*.unity')):
        raise ValueError('Runtime recorder project differs from scene-less frozen source')
    return value


def verify_recording(take):
    """Bind natural lifecycle and source snapshot without claiming Unity added no files.

    Full runtime tree validation remains in formal recorded import/judge. The
    prelaunch full-tree gate is load(); Unity legitimately installs SHA-owned
    recorder helpers and serializes metadata before this postcapture gate.
    """
    from . import project_snapshot
    from pipeline.game_eval.whitebox_eval import batch
    take = Path(take).resolve()
    value, root, manifest = _binding(take/'runtime_initializer_entry.json')
    snapshot = json.loads((take.parent/'source_snapshot.json').read_text())
    source = Path(manifest['entry']['project']).resolve()
    excluded = []
    expected = {str(p.relative_to(source)):digest(p)
                for p in project_snapshot.snapshot_files(source,excluded)}
    if (snapshot.get('policy') != project_snapshot.SNAPSHOT_POLICY
            or snapshot.get('source') != str(source)
            or snapshot.get('files_sha256') != expected
            or sorted(snapshot.get('excluded_artifacts',[])) != sorted(excluded)
            or snapshot.get('fixture_injection_excluded') is not False
            or batch.hashes(source) != manifest['snapshot_hashes']):
        raise ValueError('Runtime source snapshot differs from frozen original')
    project = take.parent/'project'
    if snapshot.get('package_path_relocation') is not None:
        project_snapshot.verify_package_relocation(source, project, snapshot['package_path_relocation'])
    proof = snapshot.get('input_axis_normalization')
    if proof is not None:
        from .input_axis_serialization import verify_snapshot
        verify_snapshot(root/'input/project', project, proof)
    if (digest(project/value['source']) != value['source_sha256']
            or any((project/'Assets').rglob('*.unity'))):
        raise ValueError('Recorded actual runtime source or scene-less entry changed')
    native = json.loads((take/'runtime_initializer_native.json').read_text())
    if not verify_native(value,native):
        raise ValueError('Runtime initializer native lifecycle/source provenance is invalid')
    return value


def arguments(value, output):
    return [item for key in ('source','source_sha256','type','method')
            for item in ('--gamefactory-runtime-entry-'+key.replace('_','-'), value[key])] + [
                '--gamefactory-runtime-entry-receipt',str(Path(output)/'runtime_initializer_native.json')]

def verify_native(value, native):
    positive = ('after_scene_load_attribute','startup_scene_unsaved','entered_play_mode',
                'exited_play_mode','observed_author_component')
    negative = ('entry_method_invoked_by_wrapper','scene_created_by_wrapper',
                'gameplay_component_added_by_wrapper','view_activated')
    return (native.get('version') == 'unity-runtime-initializer-native-record-entry.v1'
            and native.get('error') == '' and bool(native.get('editor_version'))
            and all(native.get(k) == value[k] for k in ('source','source_sha256','type','method'))
            and all(native.get(k) is True for k in positive)
            and all(native.get(k) is False for k in negative)
            and any(isinstance(row,dict) and row.get('type') == value['type']
                    and row.get('script_path') == value['source']
                    and row.get('active') is True and row.get('enabled') is True
                    and re.fullmatch('[0-9a-f]{32}',row.get('script_guid',''))
                    for row in native.get('objects',[])))
