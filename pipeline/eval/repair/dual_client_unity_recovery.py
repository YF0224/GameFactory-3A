"""One prerecord recovery; original failed attempt and successful host import retained."""
import os
import json
import re
from pathlib import Path
from pipeline.eval.whitebox.core import llm
from pipeline.eval.whitebox.core.paths import read_json, sha256

RECOVERY = 'import_recovery_1'
INPUT = 'pipeline/eval/stage1/unity_input.py'
BACKEND = 'pipeline/eval/stage1/dual_client_unity.py'


def prepare(parent, *, project, hashes, editor, production, observer):
    parent = Path(parent).resolve()
    child = parent / RECOVERY
    if child.exists():
        raise llm.HarnessError('Bounded import recovery already consumed: ' + str(child))
    cleanup = read_json(parent / 'cleanup.json')
    if cleanup.get('ok') is not True or cleanup.get('source_unchanged') is not True:
        raise llm.HarnessError('Recovery requires verified owned cleanup')
    if any(k in cleanup.get('owned_processes', {}) for k in ('HOST', 'A', 'B')):
        raise llm.HarnessError('Cannot recover imports after native gameplay started')
    forbidden = ['pair_receipt.json', 'request_A.json', 'request_B.json',
                 'sessions/HOST/owned_process.json', 'sessions/HOST/observations.jsonl', 'workers']
    if any((parent / n).exists() for n in forbidden):
        raise llm.HarnessError('Cannot recover imports after native gameplay started')
    snapshot = read_json(parent / 'source_snapshot.json')
    if snapshot != {'source': str(project), 'files_sha256': hashes}:
        raise llm.HarnessError('Recovery source binding changed')
    missing_result = not (parent / 'imports/HOST/import_result.json').exists()
    if missing_result:
        # A successful native exit can precede persistence when ps sees a dying
        # leader's transient command. Require independent formal exit evidence.
        exit_receipt = read_json(parent / 'cleanup_import_HOST.json')
        failure = cleanup.get('error', {})
        log = (parent / 'imports/HOST/import.log').read_text(errors='replace')
        if (failure != {'type': 'ValueError', 'error': 'Owned worker PID identity changed'}
                or exit_receipt.get('ok') is not True or exit_receipt.get('exit_code') != 0
                or exit_receipt.get('remaining') != []
                or 'Exiting batchmode successfully now!' not in log):
            raise llm.HarnessError('Missing successful host import exit evidence')
        result = {'exit_code': 0, 'timeout': False,
                  'editor': read_json(parent / 'session.json')['editor'],
                  'recovered_from': ['cleanup_import_HOST.json', 'imports/HOST/import.log'],
                  'parent_import_result_missing': True}
    else:
        result = read_json(parent / 'imports/HOST/import_result.json')
    if result.get('exit_code') != 0 or result.get('timeout') is not False:
        raise llm.HarnessError('No successful host import to reuse')
    for key in ('binary', 'binary_sha256', 'requested_version', 'actual_version', 'version_gap'):
        if result['editor'].get(key) != editor.get(key):
            raise llm.HarnessError('Recovery editor changed: ' + key)
    old = read_json(parent / 'production.json')
    changed = BACKEND if missing_result else INPUT
    if (not old['files'].get(changed) or not production['files'].get(changed)
            or old['files'][changed] == production['files'][changed]):
        raise llm.HarnessError('Recovery requires a changed supported producer: ' + changed)
    host = parent / 'project_HOST'
    metadata = {}
    for name, digest in hashes.items():
        if sha256(host / name) != digest:
            if not missing_result or not imported_metadata_equivalent(project, host, name, editor):
                raise llm.HarnessError('Successful host source changed: ' + name)
            metadata[name] = {'original_sha256': digest, 'imported_sha256': sha256(host / name)}
    if sha256(host / 'Assets/Stage1DualUnityObserver/Editor/Stage1DualUnityObserver.cs') != sha256(observer):
        raise llm.HarnessError('Successful host observer changed')
    # Preserve/bind every prior diagnostic outside the imported project directories.
    prior = {}
    for root, dirs, files in os.walk(parent):
        if Path(root) == parent:
            dirs[:] = [d for d in dirs if not d.startswith('project_') and d != RECOVERY]
        for name in sorted(files):
            path = Path(root) / name
            prior[str(path.relative_to(parent))] = sha256(path)
    binding = {'version': 'stage1-unity-import-recovery.v1', 'parent': str(parent),
            'host_project': str(host), 'parent_evidence_sha256': prior,
            'prior_input_producer_sha256': old['files'][INPUT],
            'input_producer_sha256': production['files'][INPUT],
            'reason': 'Interrupted prerecord client import; repaired harness dependency',
            'gameplay_attempts_consumed': 0, 'recovery_limit': 1}
    if missing_result:
        binding.update(reason='Successful host exit raced ownership observation before result persistence',
                       prior_backend_sha256=old['files'][BACKEND],
                       backend_sha256=production['files'][BACKEND],
                       recovered_import_result=result, native_import_metadata_changes=metadata)
    return binding


def verify(folder):
    """Validate immutable parent evidence, not mutable Unity Library caches."""
    folder = Path(folder).resolve()
    path = folder / 'import_recovery.json'
    if not path.exists():
        return folder / 'project_HOST'
    binding = read_json(path)
    parent = Path(binding['parent']).resolve()
    if folder != parent / RECOVERY or Path(binding['host_project']).resolve() != parent / 'project_HOST':
        raise llm.HarnessError('Foreign import recovery lineage')
    for name, digest in binding['parent_evidence_sha256'].items():
        source = (parent / name).resolve()
        if not source.is_relative_to(parent) or sha256(source) != digest:
            raise llm.HarnessError('Prior import attempt evidence changed: ' + name)
    return parent / 'project_HOST'


def imported_metadata_equivalent(project, host, name, editor):
    """Allow only the observed editor stamp and registry mirror rewrite on copies."""
    before, after = (Path(project) / name).read_text(), (host / name).read_text()
    if name == 'ProjectSettings/ProjectVersion.txt':
        def valid(text, version):
            return re.fullmatch(r'm_EditorVersion: ' + re.escape(version) +
                r'\nm_EditorVersionWithRevision: ' + re.escape(version) +
                r' \([0-9a-f]+\)\n?', text) is not None
        return valid(before, editor['requested_version']) and valid(after, editor['actual_version'])
    if name == 'Packages/packages-lock.json':
        original, imported = json.loads(before), json.loads(after)
        for dependency in original.get('dependencies', {}).values():
            if dependency.get('url') == 'https://packages.unity.com':
                dependency['url'] = 'https://packages.unity.cn'
        return original == imported
    return False
