"""Continue current native acceptance after a missing historical fixture wrapper.

Scene receipts are immutable. Rebinding preserves an independently admitted
fixture's exact source bytes and never creates a product score or new gameplay.
"""
from pathlib import Path
import copy
import time
from . import batch, unity_disk_guard
from .protocol import dump, sha
from engine_adapters.unity3d.playtest import background_record as rec
from engine_adapters.unity3d.playtest import native_acceptance, runtime_initializer


def verify_scene_parent(path, adapter, editor):
    value = batch.read(path)
    if (value.get('schema') != native_acceptance.VERSION or value.get('accepted') is not False
            or value.get('runtime_stages') or [s['duration'] for s in value['stages']] != [20, 180]):
        raise ValueError('Only completed scene fixtures before any runtime capture may continue')
    if value['editor'] != str(editor.resolve()) or sha(editor) != value['editor_sha256']:
        raise ValueError('Parent Editor changed')
    rec.verify_pin(adapter, value['pin'])
    for name, digest in value['module_hashes'].items():
        if sha(adapter/name) != digest:
            raise ValueError('Parent native production changed: '+name)
    for stage in value['stages']:
        for name in ('verification', 'runner_exit'):
            receipt = Path(stage[name]['path'])
            if sha(receipt) != stage[name]['sha256']:
                raise ValueError('Parent native receipt changed')
        verification = batch.read(Path(stage['verification']['path']))
        cleanup = batch.read(Path(stage['runner_exit']['path']))
        if (stage['exit_code'] != 0 or not verification.get('ok') or not all(verification['checks'].values())
                or not cleanup.get('cleanup_verified') or cleanup.get('policy_violations')):
            raise ValueError('Parent scene fixture or cleanup failed')
    return value


def rebind_fixture(workspace, candidate_path, source_batch, output):
    candidate = batch.read(candidate_path)
    receipt_path = Path(candidate['native_open_receipt'])
    if sha(receipt_path) != candidate['native_open_receipt_sha256']:
        raise ValueError('Preserved native admission receipt changed')
    receipt = batch.read(receipt_path)
    selected = Path(candidate['selected_project'])
    if (receipt.get('product_status') != 'OPENED' or not receipt.get('source_unchanged', {}).get('ok')
            or batch.hashes(selected) != receipt['project_hashes']
            or not all(receipt['cleanup'].get(k) is True for k in
                       ('input_cleanup', 'view_cleanup', 'process_cleanup'))):
        raise ValueError('Preserved runtime source/admission/cleanup changed')
    entry = copy.deepcopy(batch.read(Path(candidate['review_path']))['entry'])
    marker = selected/'ProjectSettings/ProjectVersion.txt'
    if not marker.is_file(): marker = selected/candidate['runtime_initializer_entry']['source']
    from . import tiered_core, endpoint_sparse
    entry.update(project=str(selected), project_marker=str(marker), marker_sha256=sha(marker),
                 planning_policy=tiered_core.VERSION, evaluation_policy=endpoint_sparse.VERSION,
                 runtime_initializer_entry=candidate['runtime_initializer_entry'],
                 native_open_admission={'version':candidate['admission_policy'],
                     'receipt':str(receipt_path), 'sha256':sha(receipt_path),
                     'original_project':receipt['source_project']})
    migration = receipt_path.parent/'input_migration.json'
    if migration.is_file():
        entry['input_migration'] = {'manifest':str(migration), 'sha256':sha(migration),
            'original_project':receipt['source_project'], 'version':'unity-inputsystem-migration.v1',
            'user_authorized':True, 'evaluation_version':'original_delivery_with_inputsystem_migration'}
    unity_disk_guard.check(output.parent, 'native_acceptance', selected)
    batch.prepare(source_batch, entry, output, prefer_explicit_endpoint_conditions=True)
    # Checks probe, exact helper source, naturally observed lifecycle and cleanup.
    runtime_initializer.write(output, output/'runtime_fixture_entry.json')
    dump(output/'fixture_rebind.json', {'version':'unity-native-fixture-rebind.v1',
        'candidate':str(candidate_path), 'candidate_sha256':sha(candidate_path),
        'admission':str(receipt_path), 'admission_sha256':sha(receipt_path),
        'project_hashes':receipt['project_hashes'], 'score_admission':False,
        'historical_attempt_recreated':False})
    return output


def continue_runtime(workspace, config):
    adapter = Path(config['adapter_root']); editor = Path(config['editor'])
    parent = Path(config['continue_scene_acceptance'])
    parent.resolve().relative_to(workspace.resolve())
    value = verify_scene_parent(parent, adapter, editor)
    out = Path(config['output']); out.mkdir(parents=True, exist_ok=False)
    claim = parent.parent/'runtime_continuation_claim.json'
    with claim.open('x') as f:
        import json
        json.dump({'output':str(out), 'parent_sha256':sha(parent), 'created':time.time()}, f)
    value = copy.deepcopy(value)
    value.update(continued_from={'path':str(parent), 'sha256':sha(parent)},
                 runtime_stages=[], updated=time.time())
    for name in ('unity_m_native_acceptance.py', 'unity_m_runtime.py'):
        relative = 'pipeline/eval/stage1/'+name
        value['module_hashes'][relative] = sha(adapter/relative)
    dump(out/'acceptance.json', value); dump(out/'candidate_pin.json', value['pin'])
    try:
        attempt = rebind_fixture(workspace, Path(config['runtime_fixture_candidate']),
                                 Path(config['runtime_fixture_source_batch']), out/'runtime_fixture_attempt')
        entry_path = out/'runtime_initializer_entry.json'
        binding = runtime_initializer.write(attempt, entry_path)
        source = Path(batch.read(attempt/'input_manifest.json')['entry']['project'])
        runtime_initializer.load(entry_path, source)
        rec.KNOWN_EDITOR = editor.resolve()
        for duration in (20, 180):
            action_source = Path(config['runtime_actions_'+str(duration)])
            actions = rec.load_actions(action_source, duration)
            if rec.recording_duration(actions, duration) != duration:
                raise ValueError('Runtime fixture actions must cover exact duration')
            action_file = out/f'runtime_actions_{duration}s.json'
            dump(action_file, {'actions':actions})
            destination = out/f'runtime_fixture_{duration}s'
            unity_disk_guard.check(out, 'capture', source, duration=duration,
                                   frames=duration*10, width=960, height=540)
            args = ['record', '--adapter-root', str(adapter), '--adapter-pin',str(out/'candidate_pin.json'),
                    '--control-root', config['control_root'], '--unity',str(editor), '--project',str(source),
                    '--scene',binding['source'], '--runtime-entry',str(entry_path), '--actions',str(action_file),
                    '--duration',str(duration), '--output',str(destination)]
            code = rec.main(args, validation_pin=value['pin'])
            stage = {'duration':duration, 'exit_code':code}
            for name, path in {'verification':destination/'verification.json',
                    'runner_exit':destination/'runner_exit.json',
                    'native_entry':destination/'take/runtime_initializer_native.json',
                    'entry_binding':destination/'take/runtime_initializer_entry.json', 'actions':action_file}.items():
                stage[name] = {'path':str(path), 'sha256':sha(path)} if path.is_file() else {'path':str(path),'missing':True}
            value['runtime_stages'].append(stage); value['updated']=time.time()
            dump(out/'acceptance.json', value)
            if code: raise RuntimeError('Runtime native fixture failed: '+str(duration))
        value['accepted']=True; dump(out/'acceptance.json',value)
        native_acceptance.verify(out/'acceptance.json',adapter,editor)
        print('CURRENT_NATIVE_ACCEPTANCE_PASSED_NOT_TWO_COLUMN_E2E '+str(out/'acceptance.json'),flush=True)
        return 0
    except Exception as exc:
        value['accepted']=False; value['continuation_failure']=str(exc); value['updated']=time.time()
        dump(out/'acceptance.json',value)
        raise
