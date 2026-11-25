"""Source-bound recovery for actual native log rows omitted by error-only delivery."""
from pathlib import Path
import copy
import json
import time

from . import batch, endpoint_channels, frame_budget
from . import unity_judge_transport_recovery as transport
from .protocol import dump, sha

VERSION = 'unity-complete-native-log-delivery.v1'
CLAIM = 'complete_native_log_delivery_claim'
RECEIPT = 'complete_native_log_delivery_recovery.json'


def upgrade(root, manifest):
    result = copy.deepcopy(manifest)
    links = batch.read(Path(root)/'runtime/action_frame_links.json')
    for subset in result['evidence_sets'].values():
        before = endpoint_channels.select(root,links,subset['criterion_ids'],
            subset.get('endpoint_contracts',{}),version=subset['channel_transport']['version'])
        if any(subset.get(k) != value for k,value in before.items()):
            raise ValueError('Complete log recovery baseline differs from original versioned transport')
        after = endpoint_channels.select(root,links,subset['criterion_ids'],
            subset.get('endpoint_contracts',{}),version=endpoint_channels.COMPLETE_LOG_VERSION)
        # Assert every channel except ENGINE is byte-equivalent in the manifest.
        for channel in ('ACTION','STATE','EVENT'):
            if before['delivered_channel_lines'][channel] != after['delivered_channel_lines'][channel]:
                raise ValueError('Complete log delivery changed another channel')
        if not set(before['delivered_channel_lines']['ENGINE']).issubset(after['delivered_channel_lines']['ENGINE']):
            raise ValueError('Complete log delivery dropped original diagnostics')
        subset.update(after)
    return result


def qualify(source):
    source = Path(source).resolve()
    if any((source/name).exists() for name in ('scores.json',CLAIM,RECEIPT)):
        raise ValueError('Saved score or prior complete log claim protected')
    from .unity_recovery import qualify_capture,attempts,saved_score
    recorded = Path(batch.read(source/'recorded_capture_provenance.json')['source_attempt']).resolve()
    case = batch.read(source/'input_manifest.json')['entry']['id']
    if saved_score(attempts(source.parent.parent,case)):
        raise ValueError('Existing case score protected')
    qualification = qualify_capture(recorded)
    log = source/'runtime/engine.log'
    native = recorded/'background_record/project/Library/GameFactory3A/Editor.log'
    if sha(log) != sha(native):
        raise ValueError('Judge log differs from original native recording')
    lines = log.read_text(errors='replace').splitlines()
    manifest = batch.read(source/'evidence_manifest.json')
    missing = set()
    for subset in manifest['evidence_sets'].values():
        scope = subset.get('channel_transport',{}).get('runtime_log_scope',{})
        if scope.get('filter') != 'errors-and-stacks.v1':
            raise ValueError('No original error-only native log delivery')
        physical = set(range(scope['line_start'],scope['line_end']+1))
        selected = set(subset['delivered_channel_lines']['ENGINE'])
        missing.update(physical-selected)
        endpoint_channels.lossless_log_wire(log,sorted(physical))
    if not any(lines[n-1].strip() for n in missing):
        raise ValueError('No omitted original runtime content')
    from .judge_invocation import response_for_judgment,_same_judgment
    failures = []
    for path in sorted((source/'judgments').glob('evidence_*.json')):
        judgment = batch.read(path)
        if not any(row.get('execution',{}).get('status') == 'HARNESS_ERROR' for row in judgment['rows']):
            continue
        response = response_for_judgment(source,path.stem)
        if not _same_judgment(batch.read(response),judgment['raw']):
            raise ValueError('Harness failure differs from accepted original response')
        call = source/'model_calls'/path.stem
        failures.extend([path,response,*[call/name for name in ('accepted_response.json','prompt.txt','schema.json','invocation.json')]])
    if not failures:
        raise ValueError('No accepted runtime observer failure supports delivery repair')
    paths = [source/'evidence_manifest.json',source/'recorded_capture_provenance.json',log,native,*failures]
    paths.extend(recorded/name for name in qualification['bindings'])
    return recorded,{str(p):sha(p) for p in paths}


def verify_delivery(root):
    root = Path(root)
    manifest = batch.read(root/'evidence_manifest.json')
    protocol = batch.read(root/'input/pilot_rubric.json')
    log = root/'runtime/engine.log'
    raw = log.read_text(errors='replace').splitlines()
    result = {}
    for name,specs,is_static in frame_budget.tasks(protocol,manifest):
        if is_static:
            continue
        subset = frame_budget.for_task(manifest,name)
        selected = subset['delivered_channel_lines']['ENGINE']
        wire = endpoint_channels.lossless_log_wire(log,selected)
        decoded = endpoint_channels.decode_log_wire(wire)
        if decoded != [(n,raw[n-1]) for n in selected]:
            raise ValueError('Original physical log rows do not reconstruct exactly')
        text,omitted = batch.packet(root,subset,False)
        actual = json.dumps(wire,ensure_ascii=False,separators=(',',':'))
        if actual not in text or any(row['id']=='ENGINE' for row in omitted):
            raise ValueError('Complete original native log missing from actual packet')
        result[name] = {'raw_log_sha256':sha(log),'wire_sha256':__import__('hashlib').sha256(actual.encode()).hexdigest(),
            'physical_line_count':len(selected),'first_line':selected[0],'last_line':selected[-1],
            'wire_bytes':len(actual.encode()),'packet_sha256':__import__('hashlib').sha256(text.encode()).hexdigest()}
    if not result:
        raise ValueError('No runtime log packets')
    return result


def prepare(source, output, *, continuation_root=None):
    source = Path(source).resolve()
    claim = source/CLAIM
    if continuation_root is None:
        recorded,bindings = qualify(source)
        claim.mkdir(exist_ok=False)
    else:
        authorization = batch.read(claim/'authorization.json')
        if authorization.get('version') != VERSION or authorization.get('source_attempt') != str(source):
            raise ValueError('Original preparation claim changed')
        bindings = authorization['source_bindings']
        for path,digest in bindings.items():
            if sha(Path(path)) != digest:
                raise ValueError('Original preparation source changed: '+path)
        failure = batch.read(Path(output)/'failure.json')
        if 'Accepted static response reuse changed delivered input or checks' not in failure.get('error',''):
            raise ValueError('Continuation requires the demonstrated static regeneration fault')
        recorded = Path(batch.read(source/'recorded_capture_provenance.json')['source_attempt'])
        pointer = batch.read(recorded/'active_background_judge_attempt.json')
        if Path(pointer['attempt']).resolve() != Path(continuation_root).resolve():
            raise ValueError('Continuation must retain the interrupted preparation identity')
        if not (Path(output)/'exit.json').is_file():
            raise ValueError('Original preparation worker has not exited')
        continuation = claim/'frozen_preparation_continuation.json'
        if continuation.exists():
            raise ValueError('Frozen preparation continuation already consumed')
        recorded = Path(batch.read(source/'recorded_capture_provenance.json')['source_attempt'])
        from .unity_recovery import qualify_capture
        qualify_capture(recorded)
        dump(continuation,{'root':str(Path(continuation_root).resolve()),'source_bindings':bindings,
            'failure_sha256':sha(Path(output)/'failure.json'),'static_calls_added':0,
            'reason':'Continue the same preparation after exact static provenance regeneration fault',
            'created_unix':time.time()})
    if continuation_root is None:
        dump(claim/'authorization.json',{'version':VERSION,'source_attempt':str(source),
        'source_bindings':bindings,'maximum_recoveries':1,'created_unix':time.time(),
        'root_cause':'Error-only ENGINE delivery omitted existing authored informational gameplay logs',
        'original_attempts_claims_and_counts_preserved':True})
    root = transport.prepare(source,Path(output),frozen_source=True,existing_root=continuation_root)
    return complete_prepared_delivery(source,root,bindings)


def complete_prepared_delivery(source,root,bindings):
    source,root = Path(source).resolve(),Path(root).resolve()
    claim = source/CLAIM
    if (root/RECEIPT).exists():
        raise ValueError('Complete log delivery already prepared; use saved result')
    for path,digest in bindings.items():
        if sha(Path(path)) != digest:
            raise ValueError('Original log delivery source changed: '+path)
    transport.verify_frozen_delivery(root)
    baseline = batch.read(root/'evidence_manifest.before_partition.json')
    dump(root/'evidence_manifest.before_complete_log.json',baseline)
    changed = upgrade(root,baseline)
    dump(root/'evidence_manifest.before_partition.json',changed)
    protocol = batch.read(root/'input/pilot_rubric.json')
    dump(root/'evidence_manifest.json',transport.partition(changed,protocol))
    receipt = batch.read(root/'judge_transport_recovery.json')
    dump(root/'judge_transport_recovery.before_complete_log.json',receipt)
    receipt.update(original_manifest_sha256=sha(root/'evidence_manifest.before_partition.json'),
        partition_manifest_sha256=sha(root/'evidence_manifest.json'))
    dump(root/'judge_transport_recovery.json',receipt)
    delivery = verify_delivery(root)
    dump(root/RECEIPT,{'version':VERSION,'source_attempt':str(source),'source_bindings':bindings,
        'claim_sha256':sha(claim/'authorization.json'),
        'baseline_sha256':sha(root/'evidence_manifest.before_complete_log.json'),
        'delivery':delivery,'recordings_added':0,'static_calls_added':0,
        'semantics':'All original runtime rows, physical citations, evidence sufficiency, schema and judge rules retained. No log converted to state/event. No gameplay success inferred.'})
    verify(root)
    transport.validate_partition(root,protocol,batch.read(root/'evidence_manifest.json'))
    return root


def verify(root):
    root = Path(root).resolve()
    receipt = batch.read(root/RECEIPT)
    source = Path(receipt['source_attempt']).resolve()
    if (receipt.get('version') != VERSION or receipt.get('recordings_added') != 0
            or receipt.get('static_calls_added') != 0 or source == root or source.parent != root.parent
            or sha(source/CLAIM/'authorization.json') != receipt['claim_sha256']):
        raise ValueError('Complete native log recovery lineage changed')
    for path,digest in receipt['source_bindings'].items():
        if sha(Path(path)) != digest:
            raise ValueError('Original complete log repair source changed: '+path)
    baseline = root/'evidence_manifest.before_complete_log.json'
    if sha(baseline) != receipt['baseline_sha256']:
        raise ValueError('Complete log baseline changed')
    if upgrade(root,batch.read(baseline)) != batch.read(root/'evidence_manifest.before_partition.json'):
        raise ValueError('Complete log transform differs from exact original scope')
    if verify_delivery(root) != receipt['delivery']:
        raise ValueError('Actual complete log packet changed')
    return receipt
