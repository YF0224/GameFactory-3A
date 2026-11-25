"""Failure-bound complete runtime reads with explicit bounded shell commands.

The v1 call and every input remain immutable. Only its observed incomplete-read
failure can admit a child; no runtime judgment is accepted without exact ordered
real outputs of every original text byte. Legacy request bytes are unchanged.
"""
import json
import shlex
from pathlib import Path
from . import mechanic_v3_runner as runner
from . import gameness_v4_runtime_chunks as prior
from . import gameness_v4_bounded_text as legacy
from .protocol import sha

VERSION = 'gameness-v4-complete-runtime-read-manifest.v1'
AUTH = 'engineering/gameness_runtime_read_manifest.json'
ERROR = 'HARNESS_ERROR: model did not receive every complete source chunk in order'
MAX_GROUP_BYTES = 150000


def commands(folder, chunks):
    groups=[];group=[];size=0
    for n,text in enumerate(chunks):
        count=len(text.encode())
        if count>MAX_GROUP_BYTES:raise ValueError('Runtime chunk exceeds bounded output size')
        if group and (size+count>MAX_GROUP_BYTES or len(group)==8):
            groups.append(group);group=[];size=0
        group.append(folder/'chunks'/('%04d.txt'%n));size+=count
    if group:groups.append(group)
    return ['cat '+' '.join(shlex.quote(str(p.resolve())) for p in group) for group in groups]


def wire(folder,body):
    reads=commands(folder,prior.payloads(body))
    return ('COMPLETE ORIGINAL RUNTIME TEXT, MANDATORY BEFORE JSON. The earlier invocation '
        'stopped after its first read and is INVALID. All original author source and native '
        'textual context bytes are in the immutable ordered chunks below. Execute EVERY '
        'numbered read-only shell command in order, each with its own complete output and '
        'max_output_tokens=60000. Each emits at most 150000 UTF-8 bytes. Do not combine commands '
        'into a loop or one output. Do not stop after the first read. If an output is clipped, '
        'read those original chunks individually, then continue with the remaining commands. '
        'All bytes must actually appear in successful completed tool outputs; the validator '
        'independently checks exact content and order. Manifests, hashes, summaries and selected '
        'excerpts do not count. The original physical source/log lines and evidence IDs remain '
        'unchanged; wrappers are not evidence. Inspect ALL native images attached to THIS '
        'invocation using the unchanged IMAGE MAP; text cannot establish unseen image content. '
        'Apply exactly the frozen criteria and schema. Return JSON only after all commands.\n'
        'COMPLETE_BODY_SHA256 '+prior.digest(body)+' BYTES '+str(len(body.encode()))+'\n'
        +'\n'.join(str(n+1)+'. '+cmd for n,cmd in enumerate(reads))+'\n')


def authorization(root):
    root=Path(root);path=root/AUTH
    if not path.exists():return None
    value=runner.read(path)
    if (value.get('version')!=VERSION or value.get('identity')!=root.name
            or value.get('maximum_prompt_bytes')!=1000000
            or value.get('maximum_group_bytes')!=MAX_GROUP_BYTES):
        raise ValueError('Invalid runtime read manifest identity or limits')
    for file,digest in value['bindings'].items():
        if sha(Path(file))!=digest:raise ValueError('Runtime manifest binding changed: '+file)
    for task in value['recovery_tasks']:
        if (root/'model_calls'/task/'accepted_response.json').exists():
            raise ValueError('An accepted runtime cannot be replaced')
    prior.verify_authorization(root)
    return value


def authorize(root,task,repair_path):
    root=Path(root).resolve();repair_path=Path(repair_path).resolve()
    if (root/AUTH).exists():
        value=authorization(root)
        if value['parent_task']!=task or value['repair']!=str(repair_path):
            raise ValueError('Runtime manifest authorization is immutable')
        return value
    repair=runner.read(repair_path)
    if repair.get('classification')!='NON_SCORING_RUNTIME_READ_MANIFEST':
        raise ValueError('Substantive diagnosed runtime read repair required')
    if any((root/p).exists() for p in [legacy.AUTH,'engineering/gameness_inline_text_recovery.json']):
        raise ValueError('Other attempted recovery requires its own diagnosed continuation')
    call=root/'model_calls'/task
    inv=runner.read(call/'invocation.json');err=runner.read(call/'validation_error.json')
    raw=runner.read(call/'response.json');events=(call/'events.jsonl').read_text()
    parsed=[json.loads(s) for s in events.splitlines() if s.strip()]
    if (inv.get('exit_code')!=0 or inv.get('response_present') is not True or inv.get('attempt')!=1
            or err.get('exception')!=ERROR or err.get('response_sha256')!=sha(call/'response.json')
            or not parsed or parsed[-1].get('type')!='turn.completed'
            or (call/'accepted_response.json').exists() or not raw.get('checks')
            or any(c.get(k,{}).get('status')!='HARNESS_ERROR' for c in raw['checks'].values()
                   for k in ('basic_function','result_outcome'))):
        raise ValueError('Exact completed incomplete-text tool failure required')
    prior.verify_authorization(root)
    actual_path=root/'requests'/task/'actual_delivery.json';actual=runner.read(actual_path)
    ref=actual['runtime_text_chunks'];proof_path=root/ref['path'];proof=runner.read(proof_path)
    if (ref.get('version')!=prior.VERSION or sha(proof_path)!=ref['sha256']
            or not proof_path.resolve().is_relative_to((root/'requests'/task).resolve())
            or actual.get('scoring_protocol')!='whitebox-gameness10-50-100.v4'
            or actual.get('all_predeclared_frames_delivered') is not True
            or actual.get('prompt_sha256')!=sha(call/'prompt.txt')):
        raise ValueError('Complete original v4 parent request required')
    body_path=proof_path.parent/'original_body.txt';body=body_path.read_bytes().decode()
    texts=prior.payloads(body)
    if (sha(body_path)!=proof['original_body_sha256']
            or [p.read_bytes().decode() for p in sorted((proof_path.parent/'chunks').glob('*.txt'))]!=texts):
        raise ValueError('Parent complete runtime bytes changed')
    try:prior.ordered_source_outputs(events,texts)
    except ValueError:pass
    else:raise ValueError('Parent already received every byte')
    outputs=[e['item'].get('aggregated_output','') for e in parsed if e.get('type')=='item.completed'
        and e.get('item',{}).get('type')=='command_execution' and e['item'].get('exit_code')==0]
    if len(outputs)!=1 or outputs[0]!=''.join(texts[:2]):
        raise ValueError('Only diagnosed complete-first-pair then stopped failure is eligible')
    from . import gameness_v3_runtime as runtime
    ws=root.parent.parent;proto=runtime.authored_rubric.protocol_for_run(root)
    manifest=runner.read(root/'evidence_manifest.json');native=runner.read(root/'input/pilot_rubric.json')
    tasks=runtime.authored_rubric.runtime_tasks(proto,manifest,native)
    if tasks is None:
        tasks=[]
        for parent,subset in manifest['evidence_sets'].items():
            specs=[s for s in runtime.workspace_policy(ws).criteria(proto) if s['id'] in subset['criterion_ids']]
            for n in range(0,len(specs),5):tasks.append((f'gameness_v4_of1_{len(tasks)+1:02d}',parent,specs[n:n+5]))
    parents={n:p for n,p,_ in tasks}
    if task not in parents:raise ValueError('Parent task outside original frozen tasks')
    admitted=[n for n,p,_ in tasks if p==parents[task]]
    if any((root/'model_calls'/n).exists() for n in admitted if n!=task):
        raise ValueError('Never replace an attempted sibling')
    files=[repair_path,actual_path,proof_path,root/prior.AUTH,root/'evidence_manifest.json',
        root/'input_manifest.json',root/'source_qualification.json',root/'gameness_source_review.json',
        Path(__file__).resolve(),body_path]+[p for p in call.iterdir() if p.is_file()]
    files += [Path(p) for p in proof['bindings']]
    for item in actual['images']+actual['complete_author_sources']:
        p=root/item['path']
        if sha(p)!=item['sha256']:raise ValueError('Original native image or source changed')
        files.append(p)
    for file,digest in repair['after_source_bindings'].items():
        if sha(Path(file))!=digest:raise ValueError('Runtime read repair production drift')
        files.append(Path(file))
    value=dict(version=VERSION,identity=root.name,parent_task=task,repair=str(repair_path),
        original_body=str(body_path),original_body_sha256=sha(body_path),
        recovery_tasks={n:n+'_read_manifest_'+sha(repair_path)[:12] for n in admitted},
        maximum_prompt_bytes=1000000,maximum_group_bytes=MAX_GROUP_BYTES,
        original_failure_claims_and_counts_preserved=True,scoring_semantics_unchanged=True,
        bindings={str(p):sha(p) for p in files})
    runner.exclusive_json(root/AUTH,value)
    return value


def selected_task(root,task):
    child=permission_authorization(root)
    if child is not None and task[0] in child['recovery_tasks']:
        return child['recovery_tasks'][task[0]],task[1],task[2]
    value=authorization(root)
    if value is None or task[0] not in value['recovery_tasks']:return legacy.selected_task(root,task)
    return value['recovery_tasks'][task[0]],task[1],task[2]


def apply(root,name,body):
    child=permission_authorization(root)
    if child is not None and name in child['recovery_tasks'].values():
        return permission_packet(Path(root),name,body,child)
    root=Path(root);value=authorization(root)
    if value is None or name not in value['recovery_tasks'].values():return legacy.apply(root,name,body)
    if prior.digest(body)!=value['original_body_sha256']:raise ValueError('Complete runtime body differs from parent')
    folder=root/'requests'/name/'complete_runtime_read_manifest'
    texts=prior.payloads(body);submitted=wire(folder,body)
    files=[(folder/'original_body.txt',body),(folder/'submitted_body.txt',submitted)]
    files += [(folder/'chunks'/('%04d.txt'%n),text) for n,text in enumerate(texts)]
    for path,text in files:prior.save_bytes(path,text.encode())
    proof=dict(version=VERSION,authorization=dict(path=str(root/AUTH),sha256=sha(root/AUTH)),
        original_body_sha256=prior.digest(body),chunk_count=len(texts),
        all_original_text_retained=True,native_images_unchanged=True,
        bindings={str(p):sha(p) for p,_ in files})
    path=folder/'equivalence.json'
    if path.exists():
        if runner.read(path)!=proof:raise ValueError('Runtime manifest proof changed')
    else:runner.exclusive_json(path,proof)
    return submitted,dict(path=str(path.relative_to(root)),sha256=sha(path),version=VERSION)


def allow_reads(prompt):
    prompt=legacy.allow_reads(prompt)
    if PERMISSION_MARKER not in prompt:return prompt
    if prompt.count(SCHEMA_ONLY)!=1:raise ValueError('Expected exact source-read permission conflict')
    return prompt.replace(SCHEMA_ONLY,EXACT_READS,1)


def verify_delivery(root,name,actual=None):
    root=Path(root);actual=actual if actual is not None else runner.read(root/'requests'/name/'actual_delivery.json')
    ref=actual.get('runtime_text_chunks')
    if ref is not None and ref.get('version')==PERMISSION_VERSION:
        return verify_permission_delivery(root,name,actual)
    if ref is None or ref.get('version')!=VERSION:return legacy.verify_delivery(root,name,actual)
    value=authorization(root)
    if value is None or name not in value['recovery_tasks'].values():raise ValueError('No exact runtime manifest authorization')
    path=root/ref['path']
    if not path.resolve().is_relative_to((root/'requests'/name).resolve()) or sha(path)!=ref['sha256']:
        raise ValueError('Runtime manifest equivalence changed')
    proof=runner.read(path)
    if proof['authorization']!=dict(path=str(root/AUTH),sha256=sha(root/AUTH)):
        raise ValueError('Runtime manifest parent changed')
    for file,digest in proof['bindings'].items():
        if sha(Path(file))!=digest:raise ValueError('Runtime read bytes changed')
    body=(path.parent/'original_body.txt').read_bytes().decode();texts=prior.payloads(body)
    if (prior.digest(body)!=value['original_body_sha256']
            or [p.read_bytes().decode() for p in sorted((path.parent/'chunks').glob('*.txt'))]!=texts
            or (path.parent/'submitted_body.txt').read_bytes().decode()!=wire(path.parent,body)
            or sha(root/'model_calls'/name/'prompt.txt')!=actual['prompt_sha256']
            or (root/'model_calls'/name/'prompt.txt').read_bytes().decode().count(wire(path.parent,body))!=1):
        raise ValueError('Actual runtime manifest request changed')
    events=root/'model_calls'/name/'events.jsonl';raw=events.read_text()
    outputs=[e['item'].get('aggregated_output','') for line in raw.splitlines() for e in [json.loads(line)]
        if e.get('type')=='item.completed' and e.get('item',{}).get('type')=='command_execution'
        and e['item'].get('exit_code')==0]
    if any(len(text.encode())>MAX_GROUP_BYTES for text in outputs):raise ValueError('Runtime read exceeded bounded output size')
    delivered=prior.ordered_source_outputs(raw,texts)
    receipt=dict(version=VERSION,task=name,all_original_text_actually_delivered=True,
        original_body_sha256=prior.digest(body),chunk_count=len(texts),ordered_output_proof=delivered,
        events_sha256=sha(events),prompt_sha256=actual['prompt_sha256'],native_images_attached_unchanged=True)
    dest=path.parent/'actual_text_delivery.json'
    if dest.exists():
        if runner.read(dest)!=receipt:raise ValueError('Runtime actual delivery changed')
    else:runner.exclusive_json(dest,receipt)
    return receipt


PERMISSION_VERSION = 'gameness-v4-complete-runtime-read-permissions.v1'
PERMISSION_AUTH = 'engineering/gameness_runtime_read_permissions.json'
PERMISSION_MARKER = 'EXACT_RUNTIME_TEXT_READ_PERMISSION_V1'
SCHEMA_ONLY = '只允许读明确指定schema；不查看其他文件、历史分数/旧判词，不运行/修复游戏。'
EXACT_READS = '只允许按下文编号命令完整读取本次指定源码/原生文本分块；schema已完整内联，不读历史分数/旧判词或其他文件，不运行/修复游戏。'


def permission_authorization(root):
    root=Path(root);path=root/PERMISSION_AUTH
    if not path.exists():return None
    value=runner.read(path)
    if (value.get('version')!=PERMISSION_VERSION or value.get('identity')!=root.name
            or value.get('maximum_prompt_bytes')!=1000000
            or value.get('maximum_group_bytes')!=MAX_GROUP_BYTES):
        raise ValueError('Invalid runtime read permission authorization')
    for file,digest in value['bindings'].items():
        if sha(Path(file))!=digest:raise ValueError('Permission continuation bound bytes changed: '+file)
    for name in value['superseded_tasks']:
        if (root/'model_calls'/name/'accepted_response.json').exists():
            raise ValueError('Accepted runtime cannot be replaced by permission recovery')
    prior.verify_authorization(root)
    return value


def authorize_permissions(root,repair_path):
    root=Path(root).resolve();repair_path=Path(repair_path).resolve()
    repair=runner.read(repair_path)
    if repair.get('classification')!='NON_SCORING_DIAGNOSED_READ_PERMISSIONS':
        raise ValueError('Diagnosed substantive permission repair required')
    parent_path=root/AUTH;parent=runner.read(parent_path)
    task=parent['recovery_tasks'][parent['parent_task']];call=root/'model_calls'/task
    inv=runner.read(call/'invocation.json');err=runner.read(call/'validation_error.json')
    actual_path=root/'requests'/task/'actual_delivery.json';actual=runner.read(actual_path)
    prompt=(call/'prompt.txt').read_bytes().decode();events=(call/'events.jsonl').read_text()
    parsed=[json.loads(line) for line in events.splitlines() if line.strip()]
    raw=runner.read(call/'response.json')
    if (inv.get('exit_code')!=0 or inv.get('model_requested')!='gpt-6.1-sol'
            or inv.get('attempt')!=1 or inv.get('response_present') is not True
            or not parsed or parsed[-1].get('type')!='turn.completed'
            or err.get('exception')!=ERROR or err.get('response_sha256')!=sha(call/'response.json')
            or prompt.count(SCHEMA_ONLY)!=1 or actual['prompt_sha256']!=sha(call/'prompt.txt')
            or actual.get('scoring_protocol')!='whitebox-gameness10-50-100.v4'
            or actual.get('all_predeclared_frames_delivered') is not True
            or not raw.get('checks') or any(c.get(k,{}).get('status')!='HARNESS_ERROR'
                for c in raw['checks'].values() for k in ('basic_function','result_outcome'))):
        raise ValueError('Exact completed conflicting-permission tool failure required')
    ref=actual['runtime_text_chunks'];proof_path=root/ref['path'];proof=runner.read(proof_path)
    body_path=Path(parent['original_body']);body=body_path.read_bytes().decode()
    if (ref.get('version')!=VERSION or sha(proof_path)!=ref['sha256']
            or sha(body_path)!=parent['original_body_sha256']
            or proof['original_body_sha256']!=sha(body_path)
            or prompt.count(wire(proof_path.parent,body))!=1):
        raise ValueError('Parent original complete runtime bytes differ')
    try:prior.ordered_source_outputs(events,prior.payloads(body))
    except ValueError:pass
    else:raise ValueError('Complete parent cannot use incomplete-read recovery')
    bindings={}
    for file,digest in parent['bindings'].items():
        if sha(Path(file))==digest:bindings[file]=digest
        else:
            change=repair.get('producer_changes',{}).get(file,{})
            archive=Path(change.get('archive',''))
            if (Path(file).resolve() not in {Path(__file__).resolve(),Path(__file__).with_name('gameness_v3_runtime.py').resolve()} or not archive.is_file()
                    or sha(archive)!=digest or change.get('before_sha256')!=digest
                    or change.get('after_sha256')!=sha(Path(file))):
                raise ValueError('Unrelated permission parent drift: '+file)
            if Path(file).name=='gameness_v3_runtime.py':
                old=archive.read_text()
                old=old.replace('from .gameness_v4_contract_read_manifest_recovery import verify_frozen_delivery',
                    'from .gameness_v4_frozen_manifest import verify_frozen_delivery, verify_accepted_contract',1)
                old=old.replace("            verify_frozen_delivery(folder, frozen['contract_chunk_transport'])\n",
                    "            verify_frozen_delivery(folder, frozen['contract_chunk_transport'])\n            verify_accepted_contract(folder)\n",1)
                if old!=Path(file).read_text():raise ValueError('Unreviewed runtime producer change')
            bindings[str(archive.resolve())]=digest
    tasks={canonical:canonical+'_read_permissions_'+sha(repair_path)[:12]
        for canonical in parent['recovery_tasks']}
    for name in parent['recovery_tasks'].values():
        if name!=task and (root/'model_calls'/name).exists():
            raise ValueError('Attempted sibling requires separate diagnosed continuation')
    for name in tasks.values():
        if (root/'model_calls'/name).exists():raise ValueError('Permission child already attempted')
    files=[parent_path,repair_path,actual_path,proof_path,body_path,Path(__file__).resolve()]
    files += [p for p in call.iterdir() if p.is_file()]
    files += [Path(p) for p in proof['bindings']]
    for item in actual['images']+actual['complete_author_sources']:
        path=root/item['path']
        if sha(path)!=item['sha256']:raise ValueError('Parent native image/source changed')
        files.append(path)
    for file,digest in repair['after_source_bindings'].items():
        if sha(Path(file))!=digest:raise ValueError('Permission repair production changed')
        files.append(Path(file))
    bindings.update({str(p.resolve()):sha(p) for p in files})
    value=dict(version=PERMISSION_VERSION,identity=root.name,parent_task=task,
        superseded_tasks=list(parent['recovery_tasks'].values()),recovery_tasks=tasks,
        original_body_sha256=sha(body_path),maximum_prompt_bytes=1000000,
        maximum_group_bytes=MAX_GROUP_BYTES,bindings=bindings,
        original_failures_claims_counts_preserved=True,scoring_semantics_unchanged=True,
        max_new_calls_per_task=1)
    path=root/PERMISSION_AUTH
    if path.exists():
        if runner.read(path)!=value:raise ValueError('Permission authorization immutable')
    else:runner.exclusive_json(path,value)
    return value


def permission_wire(folder,body):
    return (PERMISSION_MARKER+'\n'+wire(folder,body)+
        'The numbered original-text reads are explicitly authorized above. Execute every '
        'numbered command before returning JSON; continue after each successful bounded '
        'output until the final command. Do not reread the first chunk instead of continuing.\n')


def permission_packet(root,name,body,value):
    if prior.digest(body)!=value['original_body_sha256']:
        raise ValueError('Permission child complete runtime body differs')
    folder=root/'requests'/name/'complete_runtime_read_permissions'
    submitted=permission_wire(folder,body);texts=prior.payloads(body)
    files=[(folder/'original_body.txt',body),(folder/'submitted_body.txt',submitted)]
    files += [(folder/'chunks'/('%04d.txt'%n),text) for n,text in enumerate(texts)]
    for path,text in files:prior.save_bytes(path,text.encode())
    proof=dict(version=PERMISSION_VERSION,
        authorization=dict(path=str(root/PERMISSION_AUTH),sha256=sha(root/PERMISSION_AUTH)),
        original_body_sha256=value['original_body_sha256'],chunk_count=len(texts),
        all_original_text_retained=True,native_images_unchanged=True,
        bindings={str(p):sha(p) for p,_ in files})
    path=folder/'equivalence.json'
    if path.exists():
        if runner.read(path)!=proof:raise ValueError('Permission child proof changed')
    else:runner.exclusive_json(path,proof)
    return submitted,dict(path=str(path.relative_to(root)),sha256=sha(path),version=PERMISSION_VERSION)


def verify_permission_delivery(root,name,actual):
    value=permission_authorization(root)
    if value is None or name not in value['recovery_tasks'].values():
        raise ValueError('Missing exact permission child authorization')
    ref=actual['runtime_text_chunks'];path=root/ref['path'];proof=runner.read(path)
    if (not path.resolve().is_relative_to((root/'requests'/name).resolve())
            or sha(path)!=ref['sha256'] or proof['authorization']!=dict(
                path=str(root/PERMISSION_AUTH),sha256=sha(root/PERMISSION_AUTH))):
        raise ValueError('Permission delivery reference changed')
    for file,digest in proof['bindings'].items():
        if sha(Path(file))!=digest:raise ValueError('Permission delivered byte changed')
    body=(path.parent/'original_body.txt').read_bytes().decode();texts=prior.payloads(body)
    prompt=(root/'model_calls'/name/'prompt.txt').read_bytes().decode()
    if (prior.digest(body)!=value['original_body_sha256']
            or [p.read_bytes().decode() for p in sorted((path.parent/'chunks').glob('*.txt'))]!=texts
            or (path.parent/'submitted_body.txt').read_bytes().decode()!=permission_wire(path.parent,body)
            or sha(root/'model_calls'/name/'prompt.txt')!=actual['prompt_sha256']
            or prompt.count(permission_wire(path.parent,body))!=1
            or SCHEMA_ONLY in prompt or prompt.count(EXACT_READS)!=1):
        raise ValueError('Permission prompt/text reconstruction differs')
    events=root/'model_calls'/name/'events.jsonl';raw=events.read_text()
    outputs=[e['item'].get('aggregated_output','') for line in raw.splitlines()
        for e in [json.loads(line)] if e.get('type')=='item.completed'
        and e.get('item',{}).get('type')=='command_execution' and e['item'].get('exit_code')==0]
    if any(len(text.encode())>MAX_GROUP_BYTES for text in outputs):
        raise ValueError('Permission read exceeded frozen output bound')
    delivered=prior.ordered_source_outputs(raw,texts)
    receipt=dict(version=PERMISSION_VERSION,task=name,all_original_text_actually_delivered=True,
        original_body_sha256=prior.digest(body),chunk_count=len(texts),ordered_output_proof=delivered,
        events_sha256=sha(events),prompt_sha256=actual['prompt_sha256'],native_images_attached_unchanged=True)
    target=path.parent/'actual_text_delivery.json'
    if target.exists():
        if runner.read(target)!=receipt:raise ValueError('Permission actual delivery changed')
    else:runner.exclusive_json(target,receipt)
    return receipt
