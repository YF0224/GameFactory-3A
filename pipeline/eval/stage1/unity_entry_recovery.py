"""One bounded recovery of a diagnostic-only Unity plan using native component facts."""
import argparse
import os
import shutil
import time
from pathlib import Path
from types import SimpleNamespace

from . import batch, core12, static_existence, unity_admission, unity_native_entry, unity_queue, unity_safety, unity_single
from .protocol import dump, sha

VERSION = 'whitebox-native-entry-plan-recovery.v1'
RECEIPT = 'native_entry_recovery.json'


def qualify(source, batch_root):
    source = Path(source).resolve()
    batch.verify_inputs(source)
    protocol = core12.verify_attempt(source, 'unity3d')
    static_existence.load(source, protocol)
    ident = batch.read(source/'input_manifest.json')['entry']['id']
    if unity_queue.published(batch_root, ident):
        raise ValueError('Existing score protected; no entry recovery')
    if (source/RECEIPT).exists() or (source/'background_record').exists():
        raise ValueError('Recovery/capture already exists; preserve it')
    plan = batch.read(source/'sol_plan.json')
    if not plan.get('summary', '').startswith('[STARTUP_DIAGNOSTIC]'):
        raise ValueError('Recovery requires the preserved diagnostic-only plan')
    if protocol['runtime_budget']['plan_timeout_seconds'] != 1800:
        raise ValueError('Frozen plan budget must already be 1800 seconds')
    return ident


def prepare(source, batch_root):
    source = Path(source).resolve()
    ident = qualify(source, batch_root)
    for path in source.parent.glob(ident+'__native_entry_v1_*/'+RECEIPT):
        if batch.read(path)['source_attempt'] == str(source):
            raise ValueError('One native entry recovery already exists; resume its saved output')
    root = source.parent/(ident+'__native_entry_v1_'+str(time.time_ns()))
    root.mkdir()
    copied = []
    shutil.copytree(source/'input', root/'input')
    for name in ('input_manifest.json', 'attempt_manifest.json', 'static_existence.json',
                 'static_code_scores.json', 'static_source_scores.json', 'selection_provenance.json'):
        if (source/name).exists():
            shutil.copy2(source/name, root/name)
            copied.append(name)
    attempt_manifest = batch.read(root/'attempt_manifest.json')
    attempt_manifest.update(attempt_id=root.name, previous_attempt=str(source))
    dump(root/'attempt_manifest.json', attempt_manifest)
    copied.remove('attempt_manifest.json')
    for folder in (source/'model_calls').iterdir():
        if folder.is_dir() and folder.name.startswith(('static_existence', 'source_code_scores')):
            shutil.copytree(folder, root/'model_calls'/folder.name)
            copied.extend(str(p.relative_to(source)) for p in folder.rglob('*') if p.is_file())
    from .route_first_capture import install_compact_policy
    install_compact_policy(root)
    dump(root/RECEIPT, {'version':VERSION, 'source_attempt':str(source),
        'source_plan_sha256':sha(source/'sol_plan.json'),
        'source_manifest_sha256':sha(source/'input_manifest.json'),
        'copied_files_sha256':{name:sha(root/name) for name in copied},
        'authorization':'User 2026-10-29: 修复一下 — native entry diagnosis and one bounded G048 recovery',
        'maximum_recoveries':1, 'plan_timeout_seconds':1800, 'static_model_calls_added':0,
        'frozen_protocol_unchanged':True})
    batch.verify_inputs(root)
    if core12.verify_attempt(root, 'unity3d') != core12.verify_attempt(source, 'unity3d'):
        raise ValueError('Entry recovery changed frozen protocol')
    verify(root)
    return root


def verify(root):
    root=Path(root)
    value=batch.read(root/RECEIPT)
    source=Path(value['source_attempt'])
    if (value.get('version')!=VERSION or source==root or source.parent!=root.parent
            or value.get('maximum_recoveries')!=1 or value.get('static_model_calls_added')!=0):
        raise ValueError('Invalid native entry recovery lineage')
    for folder in (root,source):batch.verify_inputs(folder)
    if (sha(source/'sol_plan.json')!=value['source_plan_sha256']
            or sha(source/'input_manifest.json')!=value['source_manifest_sha256']
            or core12.verify_attempt(root,'unity3d')!=core12.verify_attempt(source,'unity3d')):
        raise ValueError('Native entry recovery source/protocol changed')
    for name,digest in value['copied_files_sha256'].items():
        relative=Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Invalid native entry recovery binding path')
        if sha(source/relative)!=digest or sha(root/relative)!=digest:
            raise ValueError('Native entry recovery changed frozen/static evidence: '+name)
    return True


def inspect(root, config, output):
    """Import a copy of the exact frozen source and inspect components without running gameplay."""
    acceptance = unity_queue.verify_acceptance(config)
    registered = unity_queue.verified_editors(config)
    entry = batch.read(root/'input_manifest.json')['entry']
    review = {'entry':dict(entry, project=str(root/'input/project')),
              'selected_project':str(root/'input/project')}
    candidate = unity_admission.review_project(review, {'id':entry['id']}, registered, acceptance['editor'])
    if candidate['status'] != 'READY':
        raise ValueError('Native entry inspection admission unavailable: '+str(candidate))
    source = Path(batch.read(root/RECEIPT)['source_attempt'])
    scene = batch.read(source/'sol_plan.json')['launch_scene']
    if scene not in candidate['scenes']:
        raise ValueError('Preserved diagnostic scene is not delivered')
    candidate['scenes'] = [scene]
    runner = SimpleNamespace(batch=batch, sha=sha, dump=dump, MIGRATION=Path(config['snapshot_root']),
        ROOT=Path(config['adapter_root']), open_timeout_seconds=config.get('admission_timeout_seconds',300),
        input_system_package_root=config.get('input_system_package_root'),
        locks_clear=lambda:unity_safety.locks_clear(config))
    candidate = unity_admission.prepare_source(candidate, review, runner, output)
    path = Path(candidate['native_open_receipt'])
    receipt = batch.read(path)
    snapshot = Path(receipt['source_snapshot'])
    dump(root/unity_native_entry.BINDING, {'receipt':str(path),'sha256':sha(path),
        'source_snapshot_sha256':sha(snapshot), 'scene_sha256':batch.read(root/'input_manifest.json')['snapshot_hashes'][scene]})
    return unity_native_entry.load(root)


def run(source, config, output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    state_path = output/'recovery_state.json'
    if state_path.exists():
        raise ValueError('Existing recovery worker protected; inspect its state instead of relaunching')
    def state(phase, **extra):
        dump(state_path, {'version':VERSION,'phase':phase,'pid':os.getpid(),
             'updated_unix':time.time(),'source_attempt':str(source), **extra})
    state('WAITING_SERIAL_LEASE')
    root = None
    with unity_queue.coordinator(config, lambda:state('WAITING_SERIAL_LEASE')):
        try:
            unity_safety.check(config)
            queue_state = Path(config['queue_output'])/'queue_state.json'
            if queue_state.exists() and batch.read(queue_state).get('status') in {
                    'STOPPED_ENVIRONMENT_FAILURES','STOPPED_CLEANUP_UNCERTAIN','STOPPED_ACCEPTANCE'}:
                state('BLOCKED_QUEUE_STOP', queue_state=str(queue_state),
                      reason='Preserve environment/acceptance/cleanup stop; no automatic bypass')
                return
            if unity_queue.published(config['batch'], batch.read(source/'input_manifest.json')['entry']['id']):
                state('SKIP_SCORED'); return
            root = prepare(source, config['batch'])
            state('INSPECTING_NATIVE_ENTRY', attempt=str(root))
            facts = inspect(root, config, output/'inspection')
            dump(output/'native_entry_facts.json', facts)
            if facts is None:
                raise ValueError('Native component facts were not produced')
            # No component is attached to the scene: do not invent a gameplay route.
            if not facts['behaviours']:
                state('ENTRY_UNRESOLVED', attempt=str(root), facts=facts,
                      reason='Native Editor resolved no authored MonoBehaviour; no model retry or fake gameplay')
                return
            dump(output/'configuration.json',config)
            unity_single.phase(output,'static_reused',attempt=str(root),previous_attempt=str(source))
            state('EVALUATING', attempt=str(root))
            verify(root)
            unity_single.continue_stages(output,root)
            state('COMPLETE',attempt=str(root),result=batch.read(output/'single_state.json'))
        except BaseException as exc:
            state('FAILED',error=str(exc))
            raise
        finally:
            if root is not None and (root/'background_record').exists():
                unity_safety.capture_cleanup(root/'background_record')
            dump(output/'cleanup_check.json', unity_safety.check(config))


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--source-attempt',type=Path,required=True)
    parser.add_argument('--configuration',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    run(args.source_attempt.resolve(),batch.read(args.configuration),args.output)


if __name__ == '__main__':
    main()
