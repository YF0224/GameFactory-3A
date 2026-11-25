"""Explicit child of a failed complete-text delivery, with bounded UTF-8 reads.

The v1 transport and its failed invocation remain immutable. This transport only
changes text delivery granularity; every source/context byte and native image is
retained. An accepted response requires actual ordered successful shell outputs.
"""
import hashlib
import json
from pathlib import Path
from . import gameness_v4_runtime_chunks as prior
from . import mechanic_v3_runner as runner
from .protocol import sha

VERSION = 'gameness-v4-bounded-utf8-runtime-text.v2'
AUTH = 'engineering/gameness_bounded_text_recovery.json'
BYTES = 4096
BATCH = 2


def payloads(body):
    if not body:
        raise ValueError('Empty complete runtime text')
    raw = body.encode('utf-8'); parts = []
    while raw:
        end = min(BYTES, len(raw))
        while end < len(raw) and raw[end] & 0xc0 == 0x80:
            end -= 1
        part, raw = raw[:end], raw[end:]
        part.decode('utf-8')
        n = len(parts)
        parts.append('RUNTIME_TEXT_CHUNK '+str(n)+' SHA256 '+hashlib.sha256(part).hexdigest()
            +'\n'+part.decode('utf-8')+'\nEND_RUNTIME_TEXT_CHUNK '+str(n)+'\n')
    return parts


def wire(folder, body):
    paths = [str((folder/'chunks'/('%04d.txt'%n)).resolve()) for n in range(len(payloads(body)))]
    return ('COMPLETE RUNTIME TEXT DELIVERY V2: All original author source and native textual '
        'context are retained byte for byte in the ordered files below. Read EVERY file before '
        'judging. Each file contains at most 4096 UTF-8 payload bytes plus its header/footer. '
        'Use read-only shell cat with AT MOST TWO adjacent files per command and '
        'max_output_tokens=16000. Continue in order until the final footer; do not stop after '
        'the first command. Do not use a broad glob or one command for all files. Multiple '
        'independent bounded commands may run in one tool call if their outputs retain order. '
        'Every complete file must occur in successful completed tool output. Manifests, hashes, '
        'summaries, compressed bytes and excerpts do not count. If a command output is truncated, '
        'read that pair one file at a time and then continue. Never infer success from these '
        'instructions. The wrappers are transport metadata; all original evidence IDs and '
        'physical line numbers remain unchanged. All native images are attached to THIS '
        'invocation: inspect those images directly using their original map and citations. '
        'Apply exactly the frozen checks and schema.\n'
        'COMPLETE_BODY_SHA256 '+prior.digest(body)+' BYTES '+str(len(body.encode()))+'\n'
        'ORDERED_READ_ONLY_CHUNKS '+json.dumps(paths,ensure_ascii=False)+'\n')


def authorization(root):
    root = Path(root); path = root/AUTH
    if not path.exists():
        return None
    value = runner.read(path)
    if (value.get('version') != VERSION or value.get('identity') != root.name
            or value.get('payload_bytes') != BYTES or value.get('batch_files') != BATCH
            or value.get('maximum_prompt_bytes') != 1000000):
        raise ValueError('Invalid bounded text recovery identity/limits')
    for file, digest in value['bindings'].items():
        if sha(Path(file)) != digest:
            raise ValueError('Bounded text recovery binding changed: '+file)
    if (root/'model_calls'/value['parent_task']/'accepted_response.json').exists():
        raise ValueError('A subsequently accepted parent cannot be replaced')
    return value


def authorize(root, task, repair_path):
    root = Path(root).resolve(); repair_path = Path(repair_path).resolve()
    if (root/AUTH).exists():
        value = authorization(root)
        if value['parent_task'] != task or value['repair'] != str(repair_path):
            raise ValueError('Existing bounded recovery is immutable')
        return value
    repair = runner.read(repair_path)
    if repair.get('classification') != 'NON_SCORING_BOUNDED_TEXT_DELIVERY':
        raise ValueError('Substantive measured delivery repair required')
    call = root/'model_calls'/task
    if (call/'accepted_response.json').exists():
        raise ValueError('Accepted runtime judgment cannot be replaced')
    error = runner.read(call/'validation_error.json'); raw = runner.read(call/'response.json')
    if (error.get('exception') != 'HARNESS_ERROR: model did not receive every complete source chunk in order'
            or error.get('response_sha256') != sha(call/'response.json')
            or not raw.get('checks') or any(
                c.get(k,{}).get('status') != 'HARNESS_ERROR'
                for c in raw['checks'].values() for k in ('basic_function','result_outcome'))):
        raise ValueError('Only a retained incomplete-text HARNESS_ERROR can continue')
    actual_path = root/'requests'/task/'actual_delivery.json'; actual = runner.read(actual_path)
    if (actual.get('scoring_protocol') != 'whitebox-gameness10-50-100.v4'
            or not actual.get('all_predeclared_frames_delivered') or not actual.get('complete_author_sources')):
        raise ValueError('Complete original v4 source/frame request required')
    reference = actual['runtime_text_chunks']; proof_path = root/reference['path']
    if sha(proof_path) != reference['sha256'] or not proof_path.resolve().is_relative_to((root/'requests'/task).resolve()):
        raise ValueError('Parent text proof changed')
    proof = runner.read(proof_path)
    if proof.get('version') != prior.VERSION:
        raise ValueError('Only the preserved v1 failure is eligible')
    prior.verify_authorization(root)
    body_path = proof_path.parent/'original_body.txt'; body = body_path.read_bytes().decode()
    if (sha(body_path) != proof['original_body_sha256'] or body_path.stat().st_size != proof['original_body_bytes']
            or [p.read_bytes().decode() for p in sorted((proof_path.parent/'chunks').glob('*.txt'))] != prior.payloads(body)):
        raise ValueError('Original full text no longer reconstructs')
    try:
        prior.ordered_source_outputs((call/'events.jsonl').read_text(), prior.payloads(body))
    except ValueError:
        pass
    else:
        raise ValueError('Parent already received every text byte')
    files = [repair_path, proof_path, actual_path, root/prior.AUTH,
        root/'input_manifest.json',root/'source_qualification.json',root/'evidence_manifest.json',
        root/'gameness_source_review.json',Path(__file__).resolve()]
    files += [p for p in call.iterdir() if p.is_file()]
    files += [Path(p) for p in proof['bindings']]
    for item in actual['images']+actual['complete_author_sources']:
        path = root/item['path']
        if sha(path) != item['sha256']:
            raise ValueError('Parent source/image changed')
        files.append(path)
    for file, digest in repair['after_source_bindings'].items():
        if sha(Path(file)) != digest:
            raise ValueError('Repaired production bytes changed')
        files.append(Path(file))
    # Exact old producer bytes are mandatory; a current hash alone is insufficient.
    for file, value in repair['producer_changes'].items():
        archive = Path(value['archive'])
        if (sha(archive) != value['before_sha256'] or sha(Path(file)) != value['after_sha256']
                or repair['after_source_bindings'].get(file) != value['after_sha256']):
            raise ValueError('Missing before/after producer proof')
        files.append(archive)
    fresh = repair.get('fresh_tasks', [])
    if fresh:
        from . import gameness_v3_runtime as runtime, gameness_v4 as policy
        protocol = runtime.authored_rubric.protocol_for_run(root)
        manifest = runner.read(root/'evidence_manifest.json')
        native = runner.read(root/'input/pilot_rubric.json')
        tasks = runtime.authored_rubric.runtime_tasks(protocol,manifest,native)
        if tasks is None:
            tasks=[]
            for parent,subset in manifest['evidence_sets'].items():
                specs=[s for s in policy.criteria(protocol) if s['id'] in subset['criterion_ids']]
                for n in range(0,len(specs),5):
                    tasks.append(('gameness_v4_of1_'+('%02d'%(len(tasks)+1)),parent,specs[n:n+5]))
        eligible=[name for name,parent,_ in tasks if parent==actual['evidence_set'] and name!=task]
        if fresh != eligible or any((root/'model_calls'/name).exists() for name in fresh):
            raise ValueError('Fresh text admission must match the untouched frozen sibling tasks')
    name = task+'_bounded_text_'+sha(repair_path)[:12]
    if (root/'model_calls'/name).exists():
        raise ValueError('Cannot admit a child after invocation')
    value = dict(version=VERSION,identity=root.name,parent_task=task,recovery_task=name,
        repair=str(repair_path),original_body=str(body_path),original_body_sha256=sha(body_path),
        recovery_tasks={canonical:canonical+'_bounded_text_'+sha(repair_path)[:12] for canonical in [task]+fresh},
        payload_bytes=BYTES,batch_files=BATCH,maximum_prompt_bytes=1000000,
        old_failure_claim_and_count_preserved=True,all_sources_context_frames_preserved=True,
        scoring_semantics_unchanged=True,bindings={str(p):sha(p) for p in files})
    runner.exclusive_json(root/AUTH,value)
    return value


def selected_task(root, task):
    from . import gameness_v4_inline_text_recovery as inline
    child = inline.selected_task(root, task)
    if child is not None:
        return child
    value = authorization(root)
    if value is None or task[0] not in value['recovery_tasks']:
        return task
    return value['recovery_tasks'][task[0]],task[1],task[2]


def apply(root, name, body):
    from . import gameness_v4_inline_text_recovery as inline
    child = inline.apply(root, name, body)
    if child is not None:
        return child
    root = Path(root); value = authorization(root)
    if value is None or name not in value['recovery_tasks'].values():
        return prior.apply(root,name,body)
    if hashlib.sha256(body.encode()).hexdigest() != value['original_body_sha256']:
        raise ValueError('Recovered complete runtime body differs from parent')
    folder = root/'requests'/name/'complete_runtime_chunks_v2'
    texts = payloads(body); submitted = wire(folder,body)
    files = [(folder/'original_body.txt',body),(folder/'submitted_body.txt',submitted)]
    files += [(folder/'chunks'/('%04d.txt'%n),text) for n,text in enumerate(texts)]
    for path,text in files:
        prior.save_bytes(path,text.encode())
    proof = dict(version=VERSION,authorization=dict(path=str(root/AUTH),sha256=sha(root/AUTH)),
        original_body_sha256=value['original_body_sha256'],original_body_bytes=len(body.encode()),
        chunk_count=len(texts),payload_bytes=BYTES,batch_files=BATCH,
        bindings={str(p):sha(p) for p,_ in files},all_original_text_retained=True,
        native_images_unchanged=True,actual_tool_output_required=True)
    path = folder/'equivalence.json'
    if path.exists():
        if runner.read(path) != proof:
            raise ValueError('Preserved v2 equivalence differs')
    else:
        runner.exclusive_json(path,proof)
    return submitted,dict(path=str(path.relative_to(root)),sha256=sha(path),version=VERSION)


def allow_reads(prompt):
    from .gameness_v4_literal_container import NOTICE
    return prompt if NOTICE in prompt else prior.allow_reads(prompt)


def verify_delivery(root, name, actual=None):
    root = Path(root)
    actual = actual if actual is not None else runner.read(root/'requests'/name/'actual_delivery.json')
    if actual.get('persistent_original_pixel_recovery'):
        from .persistent_original_pixel_recovery import verify_delivery as verify_original
        return verify_original(root,name,actual)
    reference = actual.get('runtime_text_chunks')
    from . import gameness_v4_sequential_recovery as sequential
    if reference is not None and reference.get('version') == sequential.VERSION:
        return sequential.verify_delivery(root, name, actual)
    from . import gameness_v4_persistent_capacity as capacity
    if reference is not None and reference.get('version') == capacity.VERSION:
        return capacity.verify_delivery(root, name, actual)
    from . import gameness_v4_persistent_text as persistent
    if reference is not None and reference.get('version') == persistent.VERSION:
        return persistent.verify_delivery(root, name, actual)
    from . import gameness_v4_inline_text_recovery as inline
    if reference is not None and reference.get('version') == inline.VERSION:
        return inline.verify_delivery(root, name, actual)
    if reference is None or reference.get('version') != VERSION:
        return prior.verify_delivery(root,name,actual)
    value = authorization(root)
    if value is None or name not in value['recovery_tasks'].values():
        raise ValueError('No exact child delivery authorization')
    path = root/reference['path']
    if not path.resolve().is_relative_to((root/'requests'/name).resolve()) or sha(path) != reference['sha256']:
        raise ValueError('V2 text equivalence reference changed')
    proof = runner.read(path)
    if proof['authorization'] != dict(path=str(root/AUTH),sha256=sha(root/AUTH)):
        raise ValueError('V2 text authorization changed')
    for file,digest in proof['bindings'].items():
        if sha(Path(file)) != digest:
            raise ValueError('V2 text bytes changed')
    body = (path.parent/'original_body.txt').read_bytes().decode(); texts = payloads(body)
    if (sha(path.parent/'original_body.txt') != value['original_body_sha256']
            or [p.read_bytes().decode() for p in sorted((path.parent/'chunks').glob('*.txt'))] != texts
            or (path.parent/'submitted_body.txt').read_bytes().decode() != wire(path.parent,body)):
        raise ValueError('V2 text does not reconstruct every original byte')
    call = root/'model_calls'/name
    prompt = (call/'prompt.txt').read_bytes().decode()
    if sha(call/'prompt.txt') != actual['prompt_sha256'] or prompt.count(wire(path.parent,body)) != 1:
        raise ValueError('Actual bounded-text prompt differs')
    events = call/'events.jsonl'
    delivered = prior.ordered_source_outputs(events.read_text(),texts)
    max_output = max(len(''.join(texts[n:n+BATCH]).encode()) for n in range(0,len(texts),BATCH))
    if any(row['output_bytes'] > max_output for row in delivered):
        raise ValueError('Model bypassed bounded tool-output batches')
    receipt = dict(version=VERSION,task=name,all_original_text_actually_delivered=True,
        original_body_sha256=prior.digest(body),chunk_count=len(texts),ordered_output_proof=delivered,
        events_sha256=sha(events),prompt_sha256=sha(call/'prompt.txt'),equivalence_sha256=sha(path),
        native_images_attached_unchanged=True)
    target = path.parent/'actual_text_delivery.json'
    if target.exists():
        if runner.read(target) != receipt:
            raise ValueError('Preserved v2 actual text delivery differs')
    else:
        runner.exclusive_json(target,receipt)
    return receipt
