"""Source-bound recovery of native evidence with unchanged per-parent context."""
import argparse
import copy
import json
import os
from pathlib import Path
import shutil
import threading
import time

from . import batch, frame_budget, static_existence, unity_queue, unity_safety
from .protocol import dump, sha

VERSION = 'unity-judge-context-preserving-partition.v1'


def partition(manifest, protocol, maximum=4):
    """Partition questions; duplicate each parent's entire delivered evidence set."""
    if type(maximum) is not int or not 1 <= maximum <= 4:
        raise ValueError('Recovery partitions require one to four questions')
    original = copy.deepcopy(manifest)
    result = copy.deepcopy(manifest)
    result['evidence_sets'] = {}
    result['judge_transport_partition'] = {}
    counter = 0
    for name, specs, is_static in frame_budget.tasks(protocol, original):
        if is_static:
            continue
        for start in range(0, len(specs), maximum):
            counter += 1
            child = f'evidence_{counter:02d}'
            subset = copy.deepcopy(original['evidence_sets'][name])
            subset['criterion_ids'] = [row['id'] for row in specs[start:start+maximum]]
            result['evidence_sets'][child] = subset
            result['judge_transport_partition'][child] = {
                'version': VERSION, 'parent_name': name, 'parent_specs': specs,
                'parent_criterion_ids': original['evidence_sets'][name]['criterion_ids']}
            before = {k:v for k,v in original['evidence_sets'][name].items() if k != 'criterion_ids'}
            after = {k:v for k,v in subset.items() if k != 'criterion_ids'}
            if before != after:
                raise ValueError('Partition changed parent evidence context')
    # This enforces exact once-only coverage of the original frozen criterion IDs.
    frame_budget.tasks(protocol, result)
    return result


def validate_partition(root, protocol, manifest):
    """Validate the entire original bundle, then exact context-copy equivalence."""
    root = Path(root)
    from .native_context_judge_recovery import RECEIPT as native_context_receipt
    if (root/native_context_receipt).is_file():
        from .native_context_judge_recovery import validate_partition as validate_native_partition
        return validate_native_partition(root, protocol, manifest)
    if (root/'frozen_delivery_source.json').is_file():
        verify_frozen_delivery(root)
    if (root/'complete_native_log_delivery_recovery.json').is_file():
        from .unity_complete_log_recovery import verify as verify_complete_log
        verify_complete_log(root)
    if (root/'observer_metadata_delivery_recovery.json').is_file():
        from .unity_observer_delivery_recovery import verify as verify_observer_delivery
        verify_observer_delivery(root)
    receipt = batch.read(root/'judge_transport_recovery.json')
    before_path = root/'evidence_manifest.before_partition.json'
    original = batch.read(before_path)
    expected = partition(original, protocol)
    for refinement in receipt.get('output_refinements', []):
        for relative, digest in refinement['failure_bindings'].items():
            if sha(root/relative) != digest:
                raise ValueError('Output refinement failure evidence changed')
        expected = refine_manifest(expected, protocol, refinement['failed_name'], refinement['child_names'])
    if (receipt.get('version') != VERSION
            or receipt.get('original_manifest_sha256') != sha(before_path)
            or receipt.get('partition_manifest_sha256') != sha(root/'evidence_manifest.json')
            or manifest != expected):
        raise ValueError('Context-preserving judge partition differs from bound original')
    replacement = receipt.get('replacement_recording_bindings', {})
    if replacement:
        from .unity_public_field_recovery import audit_binding
        recorded = Path(batch.read(root/'recorded_capture_provenance.json')['source_attempt'])
        if audit_binding(recorded) != replacement:
            raise ValueError('Replacement recording observer lineage changed')
    parent = Path(receipt['parent_attempt'])
    if sha(parent/'evidence_manifest.json') != receipt['parent_manifest_sha256']:
        raise ValueError('Partition parent provenance changed')
    if receipt.get('static_delivery_equivalence') is not None:
        if static_equivalence(parent, root) != receipt['static_delivery_equivalence']:
            raise ValueError('Accepted static delivery binding changed')
    elif replacement:
        raise ValueError('Replacement recording lacks exact static delivery binding')
    for path,digest in receipt['preserved_static_files'].items():
        if sha(Path(path)) != digest:
            raise ValueError('Preserved parent static response changed')
    return original


def refine_manifest(manifest, protocol, failed_name, child_names):
    """Split only one failed multi-check task; keep every parent evidence field."""
    result = copy.deepcopy(manifest)
    subset = result['evidence_sets'].pop(failed_name)
    parent = result['judge_transport_partition'].pop(failed_name)
    ids = subset['criterion_ids']
    if (len(ids) <= 1 or len(child_names) != len(ids)
            or len(set(child_names)) != len(child_names)
            or any(n in result['evidence_sets'] for n in child_names)):
        raise ValueError('Output refinement must use unique single-check children')
    for name, ident in zip(child_names, ids):
        result['evidence_sets'][name] = dict(copy.deepcopy(subset), criterion_ids=[ident])
        result['judge_transport_partition'][name] = copy.deepcopy(parent)
    frame_budget.tasks(protocol, result)
    return result


def refine_output_failure(root, failed_name):
    """One source-bound refinement per actual output-truncated multi-check task."""
    root = Path(root).resolve()
    protocol = batch.read(root/'input/pilot_rubric.json')
    manifest = batch.read(root/'evidence_manifest.json')
    validate_partition(root, protocol, manifest)
    folder = root/'model_calls'/failed_name
    events = folder/'events.jsonl'
    invocation = batch.read(folder/'invocation.json')
    if (invocation.get('exit_code') == 0 or not events.is_file()
            or 'max_output_tokens' not in events.read_text()
            or (folder/'accepted_response.json').exists()
            or (root/'judgments'/(failed_name+'.json')).exists()):
        raise ValueError('No unaccepted output-truncated invocation')
    receipt = batch.read(root/'judge_transport_recovery.json')
    if any(r['failed_name'] == failed_name for r in receipt.get('output_refinements', [])):
        raise ValueError('Output failure already refined')
    counter = max(int(n.split('_')[1]) for n in manifest['evidence_sets'])
    names = [f'evidence_{counter+i+1:02d}' for i in range(
        len(manifest['evidence_sets'][failed_name]['criterion_ids']))]
    refined = refine_manifest(manifest, protocol, failed_name, names)
    bindings = {str(f.relative_to(root)):sha(f) for f in folder.iterdir() if f.is_file()}
    record = {'failed_name':failed_name,'child_names':names,'failure_bindings':bindings,
              'failure_classification':'OUTPUT_MAX_OUTPUT_TOKENS',
              'question_count_before':len(names),'question_count_after':1,
              'created_unix':time.time(),'original_call_preserved':True}
    history = root/'output_refinement_history'/failed_name
    history.mkdir(parents=True,exist_ok=False)
    shutil.copy2(root/'evidence_manifest.json',history/'evidence_manifest.before.json')
    shutil.copy2(root/'judge_transport_recovery.json',history/'recovery.before.json')
    dump(history/'refinement.json',record)
    receipt.setdefault('output_refinements',[]).append(record)
    dump(root/'evidence_manifest.json',refined)
    receipt['partition_manifest_sha256']=sha(root/'evidence_manifest.json')
    dump(root/'judge_transport_recovery.json',receipt)
    validate_partition(root, protocol, refined)
    return record


def static_equivalence(source, root):
    """Reuse accepted static replies only for the exact same delivered data/checks."""
    import hashlib
    source, root = Path(source), Path(root)
    packets = []
    tasks = []
    for attempt in (source, root):
        manifest = batch.read(attempt/'evidence_manifest.json')
        protocol = batch.read(attempt/'input/pilot_rubric.json')
        tasks.append([(name, specs) for name, specs, is_static
                      in frame_budget.tasks(protocol, manifest) if is_static])
        body, omitted = batch.packet(attempt, manifest, True)
        packets.append((body, omitted))
    if packets[0] != packets[1]:
        raise ValueError('Accepted static response reuse changed delivered input or checks')
    if tasks[0] != tasks[1]:
        # There is no accepted reply to reuse when the original monolithic task
        # exhausted its budget. Prove the full static context and exact ordered
        # checks are unchanged, and preserve every original timeout/claim.
        old_specs = [spec for _, specs in tasks[0] for spec in specs]
        new_specs = [spec for _, specs in tasks[1] for spec in specs]
        if old_specs != new_specs or len(tasks[0]) != 1 or tasks[0][0][0] != 'static':
            raise ValueError('Static partition changed frozen checks')
        folder=source/'model_calls/static'
        inv=batch.read(folder/'invocation.json')
        if (inv.get('status')!='TIMEOUT' or inv.get('seconds',0)<899
                or inv.get('model_requested')!=static_existence.MODEL
                or any((folder/n).exists() for n in ('response.json','accepted_response.json'))
                or list((source/'judgments').glob('static*.json'))):
            raise ValueError('Static regrouping requires an unaccepted full-budget timeout')
        from .static_judge_recovery import prior_static_retry
        prior=prior_static_retry(source)
        bindings={str(f.relative_to(source)):sha(f) for f in folder.iterdir() if f.is_file()}
        bindings.update(prior.get('bindings',{}))
        return {'version':'exact-static-context-unaccepted-partition.v1',
            'packet_sha256':hashlib.sha256(packets[0][0].encode()).hexdigest(),
            'omitted':packets[0][1], 'unaccepted_parent_tasks':['static'],
            'parent_tasks_sha256':hashlib.sha256(json.dumps(tasks[0],ensure_ascii=False,sort_keys=True).encode()).hexdigest(),
            'new_tasks_sha256':hashlib.sha256(json.dumps(tasks[1],ensure_ascii=False,sort_keys=True).encode()).hexdigest(),
            'failure_bindings':bindings,'prior_exhausted_static_retry':prior,
            'accepted_responses_reused':0,'full_parent_context_unchanged':True}

    body, omitted = packets[0]
    return {'version':'exact-static-delivery-equivalence.v1',
            'packet_sha256':hashlib.sha256(body.encode()).hexdigest(),
            'characters':len(body), 'omitted':omitted,
            'tasks_sha256':hashlib.sha256(json.dumps(tasks[0],ensure_ascii=False,
                sort_keys=True,separators=(',',':')).encode()).hexdigest()}


def verify_frozen_delivery(root):
    root = Path(root).resolve()
    receipt = batch.read(root/'frozen_delivery_source.json')
    source = Path(receipt['source_attempt']).resolve()
    if (receipt.get('version') != 'exact-saved-evidence-copy.v1' or source == root
            or source.parent != root.parent or receipt.get('recordings_added') != 0
            or receipt.get('static_calls_added') != 0):
        raise ValueError('Frozen evidence lineage changed')
    for relative,digest in receipt['bindings'].items():
        original,copied = (source/relative).resolve(),(root/relative).resolve()
        if (not original.is_relative_to(source) or not copied.is_relative_to(root)
                or sha(original) != digest):
            raise ValueError('Original frozen evidence changed: '+relative)
        # The immutable baseline retains the original manifest; runtime partitions
        # intentionally change only its delivery instructions after this copy.
        if relative != 'evidence_manifest.json' and sha(copied) != digest:
            raise ValueError('Copied frozen evidence changed: '+relative)
    return receipt


def frozen_delivery_root(source, *, existing_root=None):
    """Preserve the exact saved evidence bytes when only delivery needs repair."""
    source = Path(source).resolve()
    batch.verify_inputs(source)
    batch.verify_runtime_sources(source)
    original = batch.read(source/'evidence_manifest.json')
    bundle = batch.validate_capture_bundle(source, original)
    if not bundle['valid']:
        raise ValueError('Saved frozen evidence is invalid: '+str(bundle))
    if (source/'scores.json').exists() or original.get('judge_transport_partition'):
        raise ValueError('Frozen delivery requires the original unscored, unpartitioned source')
    ident = batch.read(source/'input_manifest.json')['entry']['id']
    root = Path(existing_root).resolve() if existing_root else source.parent/(ident+'__recorded_judge_v1_'+str(time.time_ns()))
    if root == source or root.parent != source.parent:
        raise ValueError('Frozen delivery root escapes original recovery scope')
    if existing_root:
        # An interrupted preparation may be continued only before judge calls.
        if (root/'scores.json').exists() or (root/'judgments').exists():
            raise ValueError('Existing judgments or result protected during preparation')
        if any(not p.name.startswith('static_existence') for p in (root/'model_calls').iterdir()):
            raise ValueError('Existing model invocations protected during preparation')
        lineage = batch.read(root/'recorded_capture_provenance.json')
        if lineage['source_attempt'] != batch.read(source/'recorded_capture_provenance.json')['source_attempt']:
            raise ValueError('Interrupted preparation belongs to another recording')
        history = root/'preparation_history'/str(time.time_ns())
        history.mkdir(parents=True)
        for path in list(root.iterdir()):
            if path.name != 'preparation_history':
                shutil.move(str(path),str(history/path.name))
    else:
        root.mkdir()
    excluded = {'status.json','error.json','scores.json','attempt_manifest.json'}
    bindings = {}
    for path in source.iterdir():
        if path.is_file() and path.name not in excluded:
            shutil.copy2(path,root/path.name)
            bindings[path.name] = sha(path)
    for name in ('input','runtime','recovery_source','delivery'):
        if (source/name).is_dir():
            shutil.copytree(source/name,root/name)
            bindings.update({str(p.relative_to(source)):sha(p) for p in (source/name).rglob('*') if p.is_file()})
    (root/'model_calls').mkdir(exist_ok=True)
    for path in (source/'model_calls').glob('static_existence*'):
        if path.is_dir():
            shutil.copytree(path,root/'model_calls'/path.name)
    for item in original['items']:
        relative = Path(item['path'])
        src,dst = (source/relative).resolve(),(root/relative).resolve()
        if not src.is_relative_to(source) or not dst.is_relative_to(root):
            raise ValueError('Frozen evidence path escapes bound source')
        if not dst.exists():
            dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)
        if sha(src) != item['sha256'] or sha(dst) != item['sha256']:
            raise ValueError('Frozen evidence bytes changed: '+str(relative))
        bindings[str(relative)] = sha(src)
    attempt = batch.read(source/'attempt_manifest.json')
    attempt.update(attempt_id=root.name,previous_attempt=str(source),created_unix=time.time())
    dump(root/'attempt_manifest.json',attempt)
    dump(root/'frozen_delivery_source.json',{'version':'exact-saved-evidence-copy.v1','source_attempt':str(source),
        'bindings':bindings,'recordings_added':0,'static_calls_added':0,
        'reason':'Preserve original static context and raw capture metadata across delivery-only repair'})
    dump(root/'status.json',{'status':'PREPARED','phase':'frozen_delivery','updated_unix':time.time()})
    batch.verify_inputs(root)
    verify_frozen_delivery(root)
    return root


def complete_frozen_delivery_assets(root):
    """Restore original SHA-bound contact sheets omitted by interrupted copying."""
    root = Path(root).resolve()
    receipt = verify_frozen_delivery(root)
    source = Path(receipt['source_attempt'])
    if (root/'scores.json').exists() or any((root/'model_calls').glob('evidence_*')):
        raise ValueError('Judge work already started; preserve its original delivery')
    manifest = batch.read(root/'evidence_manifest.json')
    copied = {}
    for subset in manifest['evidence_sets'].values():
        for sheet in subset.get('delivery_sheets',[]):
            relative = sheet['path']
            src,dst = (source/relative).resolve(),(root/relative).resolve()
            if (not src.is_relative_to(source/'delivery') or not dst.is_relative_to(root/'delivery')
                    or sha(src) != sheet['sha256']):
                raise ValueError('Original delivery sheet binding changed: '+relative)
            if not dst.exists():
                dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)
            if sha(dst) != sha(src):
                raise ValueError('Original delivery image differs: '+relative)
            copied[relative] = sha(src)
    history = root/'preparation_history'/str(time.time_ns())
    history.mkdir(parents=True)
    shutil.copy2(root/'frozen_delivery_source.json',history/'frozen_delivery_source.before_assets.json')
    receipt['bindings'].update(copied)
    dump(root/'frozen_delivery_source.json',receipt)
    verify_frozen_delivery(root)
    return copied


def preserve_accepted_static_grouping(source, root, manifest, protocol):
    """Keep accepted static tasks intact when rebuilding runtime evidence."""
    from . import static_judge_shards
    from .judge_artifacts import validate_saved_shard
    from .judge_invocation import response_for_judgment
    source=Path(source);root=Path(root)
    old=batch.read(source/'evidence_manifest.json')
    old_tasks=[t for t in frame_budget.tasks(protocol,old) if t[2]]
    new_tasks=[t for t in frame_budget.tasks(protocol,manifest) if t[2]]
    if old_tasks==new_tasks or not all((source/'judgments'/(n+'.json')).is_file() for n,_,_ in old_tasks):
        return manifest
    if ([s for _,specs,_ in old_tasks for s in specs]!=[s for _,specs,_ in new_tasks for s in specs]
            or batch.packet(source,old,True)!=batch.packet(root,manifest,True)):
        raise ValueError('Accepted static task grouping changed frozen checks or full context')
    for name,specs,_ in old_tasks:
        validate_saved_shard(batch.read(source/'judgments'/(name+'.json')),specs)
        response=response_for_judgment(source,name)
        if not (response.parent/'accepted_response.json').is_file():
            raise ValueError('Original static task has no accepted response')
    result=copy.deepcopy(manifest)
    result.pop(static_judge_shards.FIELD,None)
    if static_judge_shards.FIELD in old:
        result[static_judge_shards.FIELD]=copy.deepcopy(old[static_judge_shards.FIELD])
    if [t for t in frame_budget.tasks(protocol,result) if t[2]]!=old_tasks:
        raise ValueError('Accepted static grouping was not preserved exactly')
    return result


def prepare(source, output, *, recorded_override=None, frozen_source=False, existing_root=None, preparation_failure=None):
    source = Path(source).resolve()
    from .prepare_unity_recorded_judge import prepare as prepare_recorded
    recorded = Path(batch.read(source/'recorded_capture_provenance.json')['source_attempt'])
    replacement_binding = {}
    if recorded_override is not None:
        from .unity_public_field_recovery import audit_binding
        replacement = Path(recorded_override).resolve()
        replacement_binding = audit_binding(replacement)
        if not replacement_binding:
            raise ValueError('Replacement take requires source-bound public observer repair')
        from .unity_public_field_recovery import RECEIPT
        lineage = batch.read(replacement/RECEIPT)
        if Path(lineage['source_attempt']).resolve() != recorded.resolve():
            raise ValueError('Replacement take belongs to another native source')
        for relative in ('input_manifest.json','input/pilot_rubric.json','sol_plan.json'):
            if sha(replacement/relative) != sha(recorded/relative):
                raise ValueError('Replacement take changed static input or physical plan')
        recorded = replacement
    from .unity_recovery import qualify_capture
    qualification = qualify_capture(recorded)
    if frozen_source and recorded_override is not None:
        raise ValueError('Frozen source cannot replace a recording')
    if existing_root is not None and not frozen_source:
        if recorded_override is None or preparation_failure is None:
            raise ValueError('Observer preparation continuation requires a bound failure')
        root=Path(existing_root).resolve();failure=Path(preparation_failure).resolve()
        failure_value=batch.read(failure)
        if (failure_value.get('error')!='Accepted static response reuse changed delivered input or checks'
                or not (failure.parent/'exit.json').is_file()
                or Path(batch.read(recorded/'active_background_judge_attempt.json')['attempt']).resolve()!=root
                or Path(batch.read(root/'recorded_capture_provenance.json')['source_attempt']).resolve()!=recorded
                or (root/'judge_transport_recovery.json').exists()
                or list((root/'judgments').glob('*.json'))
                or any(p.name!='static_existence' for p in (root/'model_calls').iterdir())):
            raise ValueError('Interrupted observer preparation identity changed')
        continuation=root/'observer_preparation_continuation.json'
        if continuation.exists():raise ValueError('Observer preparation continuation already consumed')
        before=batch.read(root/'evidence_manifest.before_partition.json')
        if partition(before,batch.read(root/'input/pilot_rubric.json'))!=batch.read(root/'evidence_manifest.json'):
            raise ValueError('Interrupted observer partition changed')
        batch.verify_inputs(root);batch.verify_runtime_sources(root)
        dump(continuation,{'failure':str(failure),'failure_sha256':sha(failure),
            'previous_exit_sha256':sha(failure.parent/'exit.json'),
            'original_manifest_sha256':sha(root/'evidence_manifest.before_partition.json'),
            'root':str(root),'recorded_attempt':str(recorded),'created_unix':time.time(),
            'reason':'Reuse the same qualified recording and interrupted preparation after binding original static response state; preserve full static context and accepted task grouping',
            'recordings_added':0,'prior_attempts_and_counts_preserved':True})
    else:
        if preparation_failure is not None:raise ValueError('Unexpected preparation failure')
        root = frozen_delivery_root(source, existing_root=existing_root) if frozen_source else prepare_recorded(recorded)
        before = batch.read(root/'evidence_manifest.json')
    protocol = batch.read(root/'input/pilot_rubric.json')
    aligned = preserve_accepted_static_grouping(source, root, before, protocol)
    if aligned != before:
        history=root/'preparation_history'/'accepted_static_grouping'
        history.mkdir(parents=True,exist_ok=False)
        dump(history/'evidence_manifest.before.json',before)
        dump(history/'binding.json',{'source':str(source),'source_manifest_sha256':sha(source/'evidence_manifest.json'),
            'reason':'Preserve original accepted static tasks verbatim; only runtime evidence is replaced',
            'accepted_responses_redistributed':False,'created_unix':time.time()})
        before=aligned
    cleanup_path = root/'runtime/native_cleanup.json'
    cleanup = unity_safety.capture_cleanup(recorded/'background_record')
    dump(cleanup_path, {key:cleanup[key] for key in unity_safety.CLEANUP_KEYS})
    if not any(row['id']=='NATIVE_CLEANUP' for row in before['items']):
        before['items'].append({'id':'NATIVE_CLEANUP','path':'runtime/native_cleanup.json',
            'type':'document','sha256':sha(cleanup_path)})
    manifest = partition(before, protocol)
    dump(root/'evidence_manifest.before_partition.json', before)
    dump(root/'evidence_manifest.json', manifest)
    static_binding = static_equivalence(source, root)
    bindings = {}
    for name, specs, is_static in frame_budget.tasks(protocol, batch.read(source/'evidence_manifest.json')):
        if not is_static:
            continue
        if name in static_binding.get('unaccepted_parent_tasks', []):
            continue
        judgment = source/'judgments'/(name+'.json')
        from .judge_artifacts import validate_saved_shard
        validate_saved_shard(batch.read(judgment), specs)
        from .judge_invocation import response_for_judgment
        response = response_for_judgment(source, name)
        if not (response.parent/'accepted_response.json').is_file():
            raise ValueError('No accepted static response: '+name)
        shutil.copytree(source/'model_calls'/name, root/'model_calls'/name, dirs_exist_ok=False)
        (root/'judgments').mkdir(exist_ok=True)
        shutil.copy2(judgment, root/'judgments'/judgment.name)
        bindings[str(judgment)] = sha(judgment)
        for file in (source/'model_calls'/name).iterdir():
            if file.is_file():
                bindings[str(file)] = sha(file)
                if sha(root/'model_calls'/name/file.name) != sha(file):
                    raise ValueError('Static invocation copy differs')
    dump(root/'judge_transport_recovery.json', {
        'version': VERSION, 'parent_attempt':str(source),
        'parent_manifest_sha256':sha(source/'evidence_manifest.json'),
        'original_manifest_sha256':sha(root/'evidence_manifest.before_partition.json'),
        'partition_manifest_sha256':sha(root/'evidence_manifest.json'),
        'preserved_static_files':bindings, 'capture_qualification':qualification,
        'static_delivery_equivalence':static_binding,
        'recordings_added':0, 'static_calls_added':0,
        'replacement_recording_bindings':replacement_binding,
        'root_cause_input':'Nested physical line ranges expanded in metadata; exact integer-column encoding',
        'root_cause_output':'Preserved max_output_tokens response; smaller closed question sets with full parent context',
        'unchanged':['rubric','images','raw evidence','physical lines','citation rules','weights','audit rules']})
    dump(output/'prepared.json', {'attempt':str(root),'parent_attempt':str(source)})
    return root


def run(args):
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=args.resume)
    config = batch.read(Path(args.configuration).resolve())
    if args.resume:
        if batch.read(output/'configuration.json') != config:
            raise ValueError('Recovery configuration changed')
        history=output/'history'/str(time.time_ns())
        history.mkdir(parents=True)
        for name in ('state.json','failure.json','heartbeat.json'):
            if (output/name).is_file():
                shutil.copy2(output/name,history/name)
    else:
        dump(output/'configuration.json',config)
    state = {'pid':os.getpid(),'phase':'WAITING_SERIAL_LEASE','updated_unix':time.time()}
    stop = threading.Event()
    def phase(name, **kwargs):
        state.update(phase=name, phase_started_unix=time.time(),updated_unix=time.time(), **kwargs)
        dump(output/'state.json',state)
    def heartbeat():
        while not stop.wait(30):
            dump(output/'heartbeat.json',dict(state,updated_unix=time.time()))
    threading.Thread(target=heartbeat,daemon=True).start()
    try:
        with unity_queue.coordinator(config,lambda:phase('WAITING_SERIAL_LEASE')):
            phase('PREFLIGHT')
            unity_safety.check(config)
            unity_queue.verify_acceptance(config)
            parent=Path(args.source).resolve()
            ident=batch.read(parent/'input_manifest.json')['entry']['id']
            from .unity_recovery import attempts, saved_score
            score=saved_score(attempts(config['batch'],ident))
            if score:
                dump(output/'skip_scored.json',score)
                phase('SKIP_SCORED')
                return
            if args.resume:
                root=Path(batch.read(output/'prepared.json')['attempt'])
                retired={r['failed_name'] for r in batch.read(root/'judge_transport_recovery.json').get('output_refinements',[])}
                for call in (root/'model_calls').iterdir():
                    if (call.name.startswith('evidence_') and call.name not in retired
                            and not (root/'judgments'/(call.name+'.json')).is_file()):
                        raise ValueError('Unrepaired failed runtime invocation: '+call.name)
                validate_partition(root,batch.read(root/'input/pilot_rubric.json'),batch.read(root/'evidence_manifest.json'))
            else:
                root=prepare(parent,output)
            phase('JUDGING',attempt=str(root),shard_timeout_seconds=config['judge_timeout_seconds'])
            from .unity_recovery import recover
            result=recover(config,prepared=root,phase=phase)
            dump(output/'result.json',result)
            phase('SCORED_PENDING_AUDIT',result=result)
    except BaseException as exc:
        import traceback
        dump(output/'failure.json',{'error':str(exc),'traceback':traceback.format_exc(),
             'failure_classification':'HARNESS_ERROR','no_product_score':True})
        phase('HARNESS_ERROR',error=str(exc))
        raise
    finally:
        stop.set()
        dump(output/'heartbeat.json',dict(state,updated_unix=time.time()))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',required=True)
    parser.add_argument('--configuration',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--resume',action='store_true')
    run(parser.parse_args(argv))


if __name__ == '__main__':
    main()
