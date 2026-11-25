"""Admit only source-bound, naturally observed authored Unity initializers.

This is an import/startup diagnostic, not a recording or gameplay success claim.
The adapter must separately pass native runtime-entry capture acceptance.
"""
from pathlib import Path
import json
import re
import time

from . import batch, unity_runtime_initializer_entry as initializer
from .protocol import dump, sha

VERSION = 'whitebox-native-runtime-initializer-admission.v1'
CLEANUP = ('input_cleanup', 'view_cleanup', 'process_cleanup')


def prepare_source(candidate, review, runner, output):
    from .unity_admission import VERSION as ADMISSION, capture_locks
    from engine_adapters.unity3d.playtest import background_record as background
    from . import runtime
    entry = candidate['runtime_initializer_entry']
    source = Path(candidate['selected_project']).resolve()
    if (candidate.get('scenes') or candidate.get('authored_scene_entry')
            or entry.get('case') != candidate['id'] or Path(entry['project']).resolve() != source):
        raise ValueError('Runtime initializer candidate identity/entry differs')
    initializer.verify(entry, source)
    output = Path(output)/'native_admission'/candidate['id']/str(time.time_ns())
    output.mkdir(parents=True, exist_ok=False)
    with capture_locks(runner):
        if runtime.active_gui_engines():
            raise RuntimeError('Native runtime admission requires idle Unity execution')
        snapshot = background.snapshot_project(source, output/'project', runner.MIGRATION)
        dump(output/'source_snapshot.json', snapshot)
        sandbox = output/'project'
        # Scene admission's compatibility order is mandatory here too.
        compatibility = None
        if candidate.get('import_compatibility'):
            from .unity_compile_compatibility import apply
            compatibility = apply(candidate['import_compatibility'], candidate['id'], sandbox,
                                  output/'import_compatibility.json')
        editor_compatibility = None
        if candidate.get('editor_compile_compatibility'):
            from .unity_editor_compile_compatibility import apply
            editor_compatibility = apply(candidate['editor_compile_compatibility'], candidate['id'], sandbox,
                                         output/'editor_compile_compatibility.json')
        compile_result = None
        compile_policy = candidate.get('native_compile_recovery')
        if compile_policy:
            from .unity_native_compile_recovery import apply
            compile_result = apply(compile_policy, candidate, sandbox, output/'native_compile_recovery.json')
        migration = None
        settings = sandbox/'ProjectSettings/ProjectSettings.asset'
        text = settings.read_text(errors='replace') if settings.is_file() else ''
        if not re.search(r'(?m)^[ \t]*activeInputHandler:[ \t]*1[ \t]*$', text):
            from .unity_input_migration import migrate_input
            migration_path = output/'input_migration.json'
            migrate_input(sandbox, migration_path,
                          package_root=getattr(runner, 'input_system_package_root', None))
            migration = {'path':str(migration_path), 'sha256':sha(migration_path)}
        from .unity_runtime_dependencies import prepare
        dependencies = output/'observer_runtime_dependencies.json'
        prepare(sandbox, candidate['selected_editor'], dependencies)
        result = initializer.probe(entry, sandbox, candidate['selected_editor'], output/'runtime_probe',
                                   timeout=getattr(runner, 'open_timeout_seconds', 240),
                                   compatibility=compile_policy, input_migration=migration)
        original = background.check_original(snapshot)
        record = {'schema':ADMISSION, 'id':candidate['id'], 'source_project':str(source),
            'project':str(sandbox), 'editor':candidate['selected_editor'],
            'source_snapshot':str(output/'source_snapshot.json'), 'source_unchanged':original,
            'runtime_initializer_entry':entry, 'opened_runtime_initializer':{
                'version':VERSION, 'probe':str(output/'runtime_probe/result.json'),
                'probe_sha256':sha(output/'runtime_probe/result.json')},
            'import_compatibility':compatibility, 'editor_compile_compatibility':editor_compatibility,
            'native_compile_recovery':compile_result, 'observer_runtime_dependencies':{
                'path':str(dependencies),'sha256':sha(dependencies)},
            'execution':result['execution'], 'native_editor_acceptance':candidate.get('native_editor_acceptance'),
            'notices':candidate.get('admission_notices', []), 'delivery_format':candidate.get('delivery_format'),
            'product_status':'OPENED' if result.get('native_entry_observed') is True else 'NATIVE_OPEN_FAILED',
            'model_calls':0, 'recordings':0, 'cleanup':result['cleanup'],
            'project_hashes':batch.hashes(sandbox)}
        dump(output/'result.json', record)
        if original.get('ok') is not True:
            raise RuntimeError('Original delivery changed during runtime initializer admission')
        if record['product_status'] != 'OPENED':
            from .unity_editor_selection import NativeAdmissionError, failure_classification
            log = output/'runtime_probe/editor.log'
            failure = failure_classification(log.read_text(errors='replace')) if log.is_file() else 'HARNESS'
            raise NativeAdmissionError('Natural runtime initializer admission failed; see '+str(output/'result.json'), failure)
    runner.locks_clear()
    return dict(candidate, selected_project=str(sandbox), native_open_receipt=str(output/'result.json'),
                native_open_receipt_sha256=sha(output/'result.json'), native_open_check_required=False)


def frozen_facts(root, manifest, binding, receipt):
    """Validate native startup against frozen bytes before exposing planning facts."""
    root = Path(root)
    admission = receipt.get('opened_runtime_initializer', {})
    entry = receipt.get('runtime_initializer_entry', {})
    expected = manifest['snapshot_hashes']
    if (admission.get('version') != VERSION or receipt.get('product_status') != 'OPENED'
            or receipt.get('source_unchanged', {}).get('ok') is not True
            or receipt.get('project_hashes') != expected
            or manifest['entry'].get('runtime_initializer_entry') != entry
            or manifest['entry'].get('id') != entry.get('case')
            or any(receipt.get('cleanup', {}).get(k) is not True for k in CLEANUP)
            or (root/'native_entry_binding.json').exists()
            or any(name.startswith('Assets/') and name.endswith('.unity') for name in expected)):
        raise ValueError('Runtime admission/source/frozen identity or cleanup changed')
    frozen_source = root/'input/project'/entry['source']
    if (not frozen_source.is_file() or sha(frozen_source) != expected.get(entry['source'])):
        raise ValueError('Frozen runtime initializer source bytes changed')
    probe_path = Path(admission['probe'])
    if sha(probe_path) != admission.get('probe_sha256'):
        raise ValueError('Runtime admission probe changed')
    probe = batch.read(probe_path)
    native_path = Path(probe['native_receipt'])
    if (probe.get('version') != initializer.VERSION or probe.get('contract') != entry
            or probe.get('native_entry_observed') is not True or probe.get('diagnostic_only') is not True
            or probe.get('execution') != receipt.get('execution')
            or any(probe.get('cleanup', {}).get(k) is not True for k in CLEANUP)
            or sha(native_path) != probe.get('native_receipt_sha256')
            or sha(probe_path.parent/'WhiteboxRuntimeInitializerProbe.cs') != probe.get('probe_source_sha256')
            or (probe_path.parent/'WhiteboxRuntimeInitializerProbe.cs').read_text() != initializer.PROBE_SOURCE
            or probe.get('effective_source_sha256') != expected.get(entry.get('source'))):
        raise ValueError('Runtime native probe/source SHA differs from frozen input')
    initializer.verify(entry, Path(receipt['project']), compatibility=probe.get('source_compatibility'),
                       input_migration=probe.get('input_migration'))
    native = batch.read(native_path)
    effective = dict(entry, source_sha256=expected[entry['source']])
    if not initializer.valid_native(effective, native, probe['execution']):
        raise ValueError('Runtime native lifecycle/observed component is invalid')
    return {'receipt':str(binding['receipt']), 'receipt_sha256':binding['sha256'],
        'runtime_initializer_entry':entry, 'source':entry['source'], 'source_sha256':expected[entry['source']],
        'editor_version':native['editor_version'], 'behaviours':[
            dict(row, source_sha256=expected[row['script_path']]) for row in native['objects']
            if row.get('script_path') in expected],
        'natural_startup_observed':True, 'diagnostic_gameplay_input_sent':False,
        'rubric_success_established':False}
