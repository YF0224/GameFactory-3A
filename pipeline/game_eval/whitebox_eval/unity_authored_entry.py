"""Explicitly reviewed, SHA-bound delivery scene builders; never synthesize gameplay."""
from pathlib import Path
import re
import time

from .protocol import dump, sha

POLICY = 'unity_authored_entry_policy.json'
VERSION = 'whitebox-authored-scene-entry.v1'


def load(batch_root, ident, project):
    from .batch import read
    path = Path(batch_root)/POLICY
    if not path.is_file():
        return None
    value = read(path)
    if value.get('version') != VERSION:
        raise ValueError('Unknown authored entry policy')
    entry = value.get('entries', {}).get(ident)
    if entry is None:
        return None
    if entry.get('reviewed') is not True or Path(entry['project']).resolve() != Path(project).resolve():
        raise ValueError('Authored scene entry source review mismatch')
    for key in ('source', 'scene'):
        rel = Path(entry[key])
        if rel.is_absolute() or '..' in rel.parts or not rel.parts or rel.parts[0] != 'Assets':
            raise ValueError('Unsafe authored entry '+key)
    if (not entry['source'].endswith('.cs') or not entry['scene'].endswith('.unity')
            or not re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+', entry['method'])
            or entry['method'].split('.')[-1] in {'BuildPlayer', 'ValidateStatic'}):
        raise ValueError('Only a reviewed authored scene creation method is allowed')
    if entry['method'].split('.')[-1] == 'RunFromCLI':
        if (entry['method'] != 'ComposeScene.RunFromCLI'
                or entry['source'] != 'Assets/Editor/ComposeScene.cs'
                or entry.get('job_mode') not in {'original-authored-compose-job.v1',
                                               'literal-authored-compose-job.v1'}):
            raise ValueError('Only the original authored ComposeScene CLI job is allowed')
        if entry['job_mode'] == 'literal-authored-compose-job.v1':
            from .unity_authored_compose_literal import verify
            spec = verify(entry, project)
        else:
            job = Path(entry['job_source'])
            project_parent = Path(project).resolve().parent
            if (job.is_symlink() or not job.resolve().is_relative_to(project_parent)
                    or sha(job) != entry['job_sha256']):
                raise ValueError('Authored compose job path or SHA changed')
            spec = read(job)
        if (not isinstance(spec, dict) or spec.get('output_scene') != entry['scene']
                or not isinstance(spec.get('objects'), list) or not spec['objects']):
            raise ValueError('Authored compose job does not bind the reviewed scene and objects')
        if 'component_type_transport' in entry:
            from .unity_compose_type_transport import review
            review(entry,spec,project)
    elif 'component_type_transport' in entry:
        raise ValueError('Component type transport requires the reviewed authored CLI job')
    elif any(k in entry for k in ('job_source','job_sha256','job_mode')):
        raise ValueError('Unexpected job on a no-argument authored builder')
    if sha(Path(project)/entry['source']) != entry['source_sha256']:
        raise ValueError('Authored scene builder SHA changed')
    return dict(entry, policy_path=str(path.resolve()), policy_sha256=sha(path))


def prepare_scene_output_directory(sandbox, scene):
    """Prepare the reviewed builder's output parent, without writing scene content."""
    sandbox = Path(sandbox).resolve()
    relative = Path(scene)
    if (relative.is_absolute() or '..' in relative.parts or len(relative.parts) < 2
            or relative.parts[0] != 'Assets' or relative.suffix != '.unity'):
        raise ValueError('Unsafe authored scene output')
    target = sandbox
    created = []
    for part in relative.parent.parts:
        target = target / part
        if target.is_symlink() or not target.resolve().is_relative_to(sandbox):
            raise ValueError('Authored scene output parent escaped snapshot')
        if target.exists():
            if not target.is_dir():
                raise ValueError('Authored scene output parent is not a directory')
        else:
            target.mkdir()
            created.append(str(target.relative_to(sandbox)))
    return created


def run(candidate, sandbox, output, runner, timeout):
    """Use the original delivered method under admission's owned locks/deadline."""
    from . import batch, unity_admission
    entry = candidate['authored_scene_entry']
    sandbox, output = Path(sandbox), Path(output)
    # Revalidate both the immutable policy and the original delivered source.
    current = load(Path(entry['policy_path']).parent, candidate['id'], entry['project'])
    if current != entry:
        raise ValueError('Reviewed authored entry changed before native execution')
    if sha(sandbox/entry['source']) != entry['source_sha256']:
        from .unity_compile_compatibility import verified_builder_import
        import_ok = (candidate.get('import_compatibility') and verified_builder_import(
            candidate['import_compatibility'], candidate['id'], sandbox, entry['source']))
        editor_ok = False
        if candidate.get('editor_compile_compatibility'):
            from .unity_editor_compile_compatibility import verified
            editor_ok = verified(candidate['editor_compile_compatibility'], sandbox)
        if not (import_ok or editor_ok):
            raise ValueError('Authored builder changed in isolated snapshot')
    created_directories = prepare_scene_output_directory(sandbox, entry['scene'])
    dump(output/'authored_scene_output_directory.json', {'scene':entry['scene'],
        'created_directories':created_directories, 'scene_content_written':False,
        'reason':'Reviewed original builder output parent; source snapshot omits empty directories'})
    before = batch.hashes(sandbox)
    command = [candidate['selected_editor'], '-batchmode', '-nographics', '-quit',
        '-projectPath', str(sandbox), '-executeMethod', entry['method'],
        '-logFile', str(output/'authored_scene_editor.log')]
    if entry.get('job_mode'):
        job=entry['job_source']
        if 'component_type_transport' in entry:
            from .unity_compose_type_transport import write
            job=str(write(entry,batch.read(Path(job)),sandbox,output))
        command += ['--job', job, '--report', str(output/'authored_compose_report.json')]
    execution = unity_admission.run_owned(command, output/'authored_scene_process.log', timeout)
    if load(Path(entry['policy_path']).parent, candidate['id'], entry['project']) != entry:
        raise ValueError('Authored entry policy/source/job changed during native execution')
    after = batch.hashes(sandbox)
    changed = {name:{'before':before.get(name), 'after':after.get(name)}
        for name in sorted(set(before)|set(after)) if before.get(name) != after.get(name)}
    code_changed = [name for name in changed if name.endswith(('.cs', '.asmdef', '.asmref'))]
    receipt = {'version':VERSION, 'entry':entry, 'execution':execution, 'diff':changed,
        'scene_exists':(sandbox/entry['scene']).is_file(), 'code_changed':code_changed,
        'gameplay_input_sent':False, 'model_calls':0, 'recordings':0,
        'created_unix':time.time()}
    dump(output/'authored_scene_result.json', receipt)
    if execution['exit_code'] != 0 or execution['timed_out'] or not receipt['scene_exists'] or code_changed:
        raise ValueError('Authored scene builder failed; see '+str(output/'authored_scene_result.json'))
    candidate['scenes'] = [entry['scene']]
    return {'path':str(output/'authored_scene_result.json'), 'sha256':sha(output/'authored_scene_result.json')}


def eligible(config, output, case, row):
    return (case.get('status') == 'SKIPPED_PRODUCT'
        and not case.get('authored_scene_entry_recovery_count')
        and not (Path(output)/'single_state.json').exists()
        and not (Path(output)/'opened_candidate.json').exists()
        and bool(row.get('project'))
        and load(config['batch'], row['id'], row['project']) is not None)


def input_bus_recovery(config, output, case, row):
    """One new native attempt after proven migration damage, not product retry."""
    from .batch import read
    if (case.get('status') != 'BOUNDED_FAILURE' or case.get('phase') != 'admission'
            or case.get('input_bus_migration_recovery_count')
            or (Path(output)/'single_state.json').exists()
            or (Path(output)/'opened_candidate.json').exists()
            or not config.get('batch') or not row.get('project')):
        return False
    path = Path(config['batch'])/'unity_input_bus_recovery_policy.json'
    if not path.is_file():
        return False
    policy = read(path)
    if policy.get('version') != 'whitebox-input-bus-recovery.v1':
        raise ValueError('Unknown input bus recovery policy')
    entry = policy.get('entries', {}).get(row['id'])
    if entry is None:
        return False
    if entry.get('reviewed') is not True or Path(entry['project']).resolve() != Path(row['project']).resolve():
        raise ValueError('Input bus recovery review mismatch')
    original = Path(row['project'])/entry['source']
    if (not original.resolve().is_relative_to(Path(row['project']).resolve())
            or sha(original) != entry['source_sha256']):
        raise ValueError('Input bus recovery source changed')
    prior = Path(entry['prior_receipt'])
    log = Path(entry['compiler_log'])
    if sha(prior) != entry['prior_receipt_sha256'] or sha(log) != entry['compiler_log_sha256']:
        raise ValueError('Input bus recovery native evidence changed')
    receipt = read(prior)
    if receipt.get('scene_exists') or not receipt.get('execution', {}).get('owned_process_exited'):
        return False
    errors = set(line.strip() for line in log.read_text(errors='replace').splitlines() if 'error CS' in line)
    expected = "'GameFactoryInput' does not contain a definition for 'ConsumeEdges'"
    return (bool(errors) and all(expected in line for line in errors)
            and load(config['batch'], row['id'], row['project']) is not None)
