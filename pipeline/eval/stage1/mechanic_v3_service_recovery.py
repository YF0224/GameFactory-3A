"""One bound continuation after a terminal quota error and newer service success.

No product response may be replaced. The accepted sibling and full original
source/native-image admissions remain immutable; the original validator runs.
"""
from datetime import datetime
from pathlib import Path
import hashlib
import json
from .protocol import sha
from .mechanic_v3_runner import read, exclusive_json, stamp
from . import mechanic_v3_judge_transport as transport
from . import mechanic_v3_source_delivery as sources
from . import mechanic_v3_image_transport as images

VERSION = 'mechanic-terminal-quota-continuation.v1'


def qualify(root, task, success, repair_path=None):
    root = Path(root).resolve(); success = Path(success).resolve()
    folder = root/'model_calls'/task
    if '_service_' in task or (folder/'response.json').exists() or (folder/'accepted_response.json').exists():
        raise ValueError('Service continuation requires an original failed call without any response')
    inv = read(folder/'invocation.json')
    from . import evaluation_model_profile as models
    if models.profile_for(root) is not None or inv.get('model_requested') != models.DEFAULT:
        raise ValueError('Legacy service continuation is limited to the unchanged Sol evaluator')
    if inv.get('exit_code') != 1 or inv.get('response_present') is not False or inv.get('attempt') != 1:
        raise ValueError('Original terminal invocation required')
    events = [json.loads(line) for line in (folder/'events.jsonl').read_text().splitlines() if line.strip()]
    terminal = [e for e in events if e.get('type') == 'turn.failed']
    message = terminal[-1].get('error', {}).get('message', '') if terminal else ''
    if '403 Forbidden' not in message or 'token quota is not enough' not in message:
        raise ValueError('Terminal events do not prove quota exhaustion')
    if any(e.get('type') == 'turn.completed' for e in events):
        raise ValueError('Completed product turn cannot be continued')
    failure = root/'failures'/(task+'.json'); fail = read(failure)
    ok = read(success/'invocation.json'); accepted = read(success/'accepted_response.json')
    proof = read(success/'v3_delivery_verified.json')
    response = success/accepted['path']
    if response.resolve().parent != success or sha(response) != accepted['sha256']:
        raise ValueError('Successful response binding differs')
    if (ok.get('exit_code') != 0 or ok.get('response_present') is not True
            or ok.get('model_requested') != inv.get('model_requested')
            or not inv.get('cli_runtime') or ok.get('cli_runtime') != inv['cli_runtime']):
        raise ValueError('Newer success must use the same model and qualified CLI')
    if (proof.get('valid') is not True or proof.get('invocation_sha256') != sha(success/'invocation.json')
            or proof.get('prompt_sha256') != sha(success/'prompt.txt')
            or datetime.fromisoformat(proof['time']) <= datetime.fromisoformat(fail['time'])):
        raise ValueError('Verified successful delivery must be newer than terminal failure')
    if not any(json.loads(line).get('type') == 'turn.completed'
               for line in (success/'events.jsonl').read_text().splitlines() if line.strip()):
        raise ValueError('Successful terminal service event missing')
    actual_path = root/'requests'/task/'actual_delivery.json'; actual = read(actual_path)
    if actual.get('prompt_sha256') != sha(folder/'prompt.txt'):
        raise ValueError('Original request prompt binding differs')
    paths = list(p for p in folder.iterdir() if p.is_file()) + [failure, actual_path]
    paths += [success/n for n in ('invocation.json','accepted_response.json','v3_delivery_verified.json','prompt.txt','events.jsonl')]
    paths += [response, root/'input_manifest.json',root/'source_qualification.json',root/'evidence_manifest.json']
    for image in actual['images']:
        p = root/image['path']
        if sha(p) != image['sha256']: raise ValueError('Original native image drift')
        paths.append(p)
    source_path = sources._path(root,task); source = read(source_path); source = current_admission(source, repair_path)
    image_path = root/'engineering/judge_image_transport'/(task+'.json'); image = read(image_path)
    if (image.get('version') != images.NATIVE_VERSION
            or image.get('parent_evidence_set') != actual['parent_evidence_set']):
        raise ValueError('Original complete native-frame admission required')
    current_image = current_admission(dict(bindings=image['source_bindings']), repair_path)
    image = dict(image, source_bindings=current_image['bindings'])
    if source.get('parent') != actual['parent_evidence_set'] or source.get('recovery_task') != task:
        raise ValueError('Complete source parent differs')
    paths += [source_path,image_path,Path(__file__)]
    if repair_path: paths.append(Path(repair_path))
    # Accepted siblings remain explicitly bound, with no new model call.
    siblings = sorted(p for p in (root/'model_calls').glob('mechanic_v3*/accepted_response.json') if p.parent != folder)
    if not siblings: raise ValueError('An accepted sibling is required for partial-judge continuation')
    for p in siblings:
        a = read(p); resp = p.parent/a['path']
        if sha(resp) != a['sha256']: raise ValueError('Accepted sibling response drift')
        paths += [p,resp]
        paths += [f for f in p.parent.iterdir() if f.is_file()]
        paths += [f for f in (root/'requests'/p.parent.name).rglob('*') if f.is_file()]
        artifact=root/'judgments'/(p.parent.name+'.json')
        if artifact.exists(): paths.append(artifact)
    bindings = {str(p.resolve()):sha(p) for p in paths}
    return bindings, source, image


def prepare(root, task, success, *, repair_path=None):
    root=Path(root).resolve(); mapping=root/'engineering/judge_transport_recovery'/(task+'.json')
    if mapping.exists():
        old=read(mapping)
        if old.get('service_version') == NETWORK_VERSION:
            return prepare_network(root,task,success)
        if old.get('service_version') != VERSION: raise ValueError('Other retained recovery must be preserved')
        transport.selected_task(root,(task,'',[]))
        if old.get('success_evidence') != str(Path(success).resolve()):
            raise ValueError('Service success evidence changed')
        if read(root/'engineering/service_continuation.json') != old:
            raise ValueError('Service execution pointer differs')
        return old
    if read(root/'model_calls'/task/'invocation.json').get('status') == 'TIMEOUT':
        return prepare_network(root,task,success)
    bindings,source,image=qualify(root,task,success,repair_path)
    fingerprint=hashlib.sha256(transport.key(bindings).encode()).hexdigest()
    name=task+'_service_'+fingerprint[:12]
    if (root/'model_calls'/name).exists(): raise ValueError('Retained service attempt cannot be repeated')
    receipt=dict(time=stamp(),transport_version=transport.VERSION,service_version=VERSION,
        original_task=task,recovery_task=name,bindings=bindings,success_evidence=str(Path(success).resolve()),
        reason='Terminal HTTP403 quota failure; later same-model completed verified delivery establishes service recovery',
        max_new_calls=1,original_failure_preserved=True,accepted_siblings_preserved=True,
        scoring_semantics_unchanged=True,all_sources_and_native_frames_preserved=True,
        repair_path=str(Path(repair_path).resolve()) if repair_path else None,
        accepted_siblings=[p.parent.name for p in (root/'model_calls').glob('mechanic_v3*/accepted_response.json')])
    childsource=dict(source,canonical_task=name,recovery_task=name,bindings={**source['bindings'],**bindings},
        service_continuation=VERSION,prior_pending_claim_preserved=True)
    childimage=dict(image,source_bindings={**image['source_bindings'],**bindings},original_request=task,
        service_continuation=VERSION)
    for path,value in [(sources._path(root,name),childsource),
                       (root/'engineering/judge_image_transport'/(name+'.json'),childimage)]:
        if path.exists():
            if read(path)!=value: raise ValueError('Preserved service child claim differs')
        else: exclusive_json(path,value)
    exclusive_json(mapping,receipt)
    exclusive_json(root/'engineering/service_continuation.json',receipt)
    return receipt


def current_admission(value, repair_path):
    """Resolve only the measured model-routing producer drift via exact snapshots."""
    bindings=dict(value['bindings'])
    drift={p:d for p,d in bindings.items() if sha(Path(p))!=d}
    if not drift: return value
    execution=Path(__file__).with_name('mechanic_v3_execution.py').resolve()
    if set(drift)!={str(execution)} or repair_path is None:
        raise ValueError('Unqualified original source admission drift')
    repair_path=Path(repair_path).resolve();repair=read(repair_path)
    if repair.get('classification')!='NON_SCORING_SERVICE_CONTINUATION':
        raise ValueError('Explicit service producer repair required')
    snapshot=Path(repair['before_snapshots'][str(execution)])
    if sha(snapshot)!=drift[str(execution)]: raise ValueError('Original execution snapshot differs')
    for p,digest in repair['after_source_bindings'].items():
        if sha(Path(p))!=digest: raise ValueError('Service repair implementation drift')
    # Byte comparison proves the original request/scoring implementation is
    # unchanged apart from explicit model routing and this scoped continuation.
    old=snapshot.read_text();new=execution.read_text()
    hook='''    from . import mechanic_v3_service_recovery as service_recovery
    service_task = service_recovery.select(root, task)
    if service_task is not None:
        if service_task[0] == task[0]:
            return service_recovery.reuse_accepted(root, protocol, contract, frozen, task)
        task = service_task
'''
    replacements=[('from . import evaluation_model_profile as eval_models\n',''),
        (hook,''),('    eval_models.verify_call(root, name, \'judge\')\n',''),
        ('model=eval_models.model_for(root, "judge")','model=v3.MODEL'),
        ('    bindings.update(eval_models.binding(root))\n',''),
        ("    profile=eval_models.publication_profile(root, 'Mechanic')\n    if profile is not None: publication['evaluation_model_profile']=profile\n",'')]
    for a,b in replacements:
        if a not in new: raise ValueError('Expected producer continuation shape differs')
        new=new.replace(a,b)
    if old!=new: raise ValueError('Producer changed beyond the reviewed model routing/continuation')
    bindings[str(snapshot.resolve())]=drift[str(execution)]
    bindings[str(execution)]=sha(execution);bindings[str(repair_path)]=sha(repair_path)
    bindings.update(repair['after_source_bindings'])
    return dict(value,bindings=bindings)


def select(root, task):
    """Route only the explicitly bound failed shard and its accepted siblings."""
    root=Path(root);pointer=root/'engineering/service_continuation.json'
    if not pointer.exists(): return None
    receipt=read(pointer)
    if receipt.get('service_version')!=VERSION: raise ValueError('Unknown service continuation')
    for p,digest in receipt['bindings'].items():
        if sha(Path(p))!=digest: raise ValueError('Service continuation evidence drift: '+p)
    name,parent,specs=task
    if name==receipt['original_task']:return receipt['recovery_task'],parent,specs
    if name in receipt['accepted_siblings']:return task
    return None


def reuse_accepted(root, protocol, contract, frozen, task):
    """Revalidate the exact accepted request; never regenerate or recall it."""
    from . import mechanic_v3_execution as execution
    from . import evaluation_model_profile as models
    from .codex import saved_model_response
    root=Path(root);name,parent,specs=task
    receipt=read(root/'engineering/service_continuation.json')
    if name not in receipt['accepted_siblings']:raise ValueError('Unbound accepted sibling')
    current_admission(read(sources._path(root,name)),receipt['repair_path'])
    folder=root/'model_calls'/name;req=root/'requests'/name
    models.verify_call(root,name,'judge')
    actual=read(req/'actual_delivery.json')
    if actual['contract_sha256']!=frozen['contract_sha256'] or actual['parent_evidence_set']!=parent:
        raise ValueError('Accepted sibling frozen contract/parent differs')
    source=read(req/'complete_source_delivery.json')
    if source.get('all_source_bytes_delivered') is not True:
        raise ValueError('Accepted sibling lacks full original source delivery')
    # Existing raw response, submitted images and citations remain the input.
    invocation=read(folder/'invocation.json');cmd=invocation['command']
    submitted=[str(Path(cmd[i+1]).resolve()) for i,x in enumerate(cmd[:-1]) if x=='--image']
    if (invocation.get('exit_code')!=0 or sha(folder/'prompt.txt')!=actual['prompt_sha256']
            or submitted!=[str((root/x['path']).resolve()) for x in actual['images']]):
        raise ValueError('Accepted sibling actual delivery differs')
    for item in actual['images']:
        if sha(root/item['path'])!=item['sha256']: raise ValueError('Accepted sibling native image drift')
    selected=read(req/'selected_manifest.json');rules=read(req/'citation_rules.json')
    raw=read(saved_model_response(root,name))
    checks=execution.v3.evaluate(root,protocol,selected,rules,contract,raw,specs)
    artifact=read(root/'judgments'/(name+'.json'))
    if artifact['raw']!=raw or artifact['checks']!=checks:
        raise ValueError('Accepted sibling judgment changed on original validator')
    return checks


NETWORK_VERSION = 'complete-judge-network-timeout-continuation.v1'


def network_timeout(root, task):
    """Qualify an empty interrupted stream, never a slow or rejected verdict."""
    root = Path(root).resolve(); folder = root/'model_calls'/task
    invocation = read(folder/'invocation.json')
    if invocation.get('status') != 'TIMEOUT':
        raise ValueError('Retained invocation is not a network timeout')
    if '_network_' in task or any(folder.glob('*response*.json')):
        raise ValueError('A response or a retained network child cannot be replaced')
    events = [json.loads(s) for s in (folder/'events.jsonl').read_text().splitlines() if s.strip()]
    messages = []
    for event in events:
        kind = event.get('type')
        if kind == 'error':
            messages.append(event.get('message', ''))
        elif kind == 'item.completed' and event.get('item', {}).get('type') == 'error':
            continue  # CLI configuration notices are not a product response.
        elif kind not in {'thread.started', 'turn.started'}:
            raise ValueError('Stream contains product activity or a completed turn')
    if not any('stream disconnected before completion' in s and
               any(reason in s for reason in ('idle timeout waiting for SSE',
                   'network error: error decoding response body')) for s in messages):
        raise ValueError('Raw stream does not establish the diagnosed network failure')
    failure = root/'failures'/(task+'.json')
    value = read(failure)
    if value.get('product_score', 'missing') is not None:
        raise ValueError('Network failure must not carry a product score')
    datetime.fromisoformat(value['time'])
    return folder, failure


def network_success(root, task, success):
    """Require a later real, fully delivered judge on the identical model/CLI."""
    folder, failure = network_timeout(root, task)
    success = Path(success).resolve()
    inv = read(folder/'invocation.json'); ok = read(success/'invocation.json')
    accepted = read(success/'accepted_response.json')
    response = success/accepted['path']
    proof = read(success/'v3_delivery_verified.json')
    failed_at = datetime.fromisoformat(read(failure)['time']).timestamp()
    if (min((success/n).stat().st_mtime for n in ('invocation.json','events.jsonl')) <= failed_at
            or response.resolve().parent != success or sha(response) != accepted['sha256']
            or ok.get('exit_code') != 0 or ok.get('response_present') is not True
            or ok.get('model_requested') != inv.get('model_requested')
            or read(success/'cli_runtime.json') != read(folder/'cli_runtime.json')
            or proof.get('valid') is not True
            or proof.get('invocation_sha256') != sha(success/'invocation.json')
            or proof.get('prompt_sha256') != sha(success/'prompt.txt')
            or datetime.fromisoformat(proof['time']) <= datetime.fromisoformat(read(failure)['time'])):
        raise ValueError('Later verified same-model/CLI delivery is required')
    if not any(json.loads(s).get('type') == 'turn.completed'
               for s in (success/'events.jsonl').read_text().splitlines() if s.strip()):
        raise ValueError('Successful terminal judge event is required')
    # Verify actual image arguments, not a health message or model acknowledgement.
    actual = read(success/'actual_delivery.json')
    command = ok.get('command', [])
    submitted = [str(Path(command[i+1]).resolve()) for i,x in enumerate(command[:-1]) if x == '--image']
    success_root = success.parent.parent
    if (submitted != [str((success_root/x['path']).resolve()) for x in actual['images']]
            or actual.get('prompt_sha256') != sha(success/'prompt.txt')):
        raise ValueError('Successful complete image/prompt delivery differs')
    for item in actual['images']:
        if sha(success_root/item['path']) != item['sha256']:
            raise ValueError('Successful native image changed')
    return proof


def prepare_network(root, task, success):
    """One restored-service continuation; original failures and siblings stay put."""
    root = Path(root).resolve(); success = Path(success).resolve()
    mapping = root/'engineering/judge_transport_recovery'/(task+'.json')
    if mapping.exists():
        old = read(mapping)
        if old.get('service_version') != NETWORK_VERSION:
            raise ValueError('Another retained recovery must be preserved')
        transport.selected_task(root, (task, '', []))
        return old
    folder, failure = network_timeout(root, task)
    proof = network_success(root, task, success)
    actual_path = root/'requests'/task/'actual_delivery.json'; actual = read(actual_path)
    if actual.get('prompt_sha256') != sha(folder/'prompt.txt'):
        raise ValueError('Original complete prompt changed')
    if (actual.get('all_predeclared_frames_delivered') is not True
            and actual.get('full_parent_context_preserved') is not True):
        raise ValueError('Original complete native delivery is required')
    paths = [p for p in folder.iterdir() if p.is_file()] + [failure, actual_path, Path(__file__).resolve()]
    paths += [p for p in (root/'requests'/task).rglob('*') if p.is_file()]
    paths += [root/n for n in ('input_manifest.json','source_qualification.json','evidence_manifest.json')]
    for item in actual['images']:
        p = root/item['path']
        if sha(p) != item['sha256']: raise ValueError('Original native image changed')
        paths.append(p)
    for item in read(root/'evidence_manifest.json')['items']:
        if item['type'] == 'source':
            p = root/item['path']
            if sha(p) != item['sha256']: raise ValueError('Original author source changed')
            paths.append(p)
    source_path = sources._path(root,task)
    source = None
    if task.startswith('mechanic_v3'):
        source = read(source_path); sources.verify(source)
        complete = read(root/'requests'/task/'complete_source_delivery.json')
        if complete.get('all_source_bytes_delivered') is not True:
            raise ValueError('Complete original Mechanic source proof required')
        paths.append(source_path)
    paths += [success/n for n in ('invocation.json','cli_runtime.json','accepted_response.json',
        'prompt.txt','schema.json','events.jsonl','actual_delivery.json')]
    paths.append(success/read(success/'accepted_response.json')['path'])
    # Delivery audits can be revalidated later; retain this success's original
    # timestamp as immutable evidence instead of binding its mutable audit file.
    proof_path = root/'engineering/network_service_proofs'/(task+'.json')
    exclusive_json(proof_path, dict(success=str(success),proof=proof))
    paths.append(proof_path)
    bindings = {str(p.resolve()):sha(p) for p in paths}
    child = task+'_network_'+hashlib.sha256(transport.key(bindings).encode()).hexdigest()[:12]
    if (root/'model_calls'/child).exists():
        raise ValueError('Retained network child cannot be repeated')
    if source is not None:
        childsource = dict(source,canonical_task=child,recovery_task=child,
            first_delivery=False,prior_invocation=task,service_continuation=NETWORK_VERSION,
            bindings={**source['bindings'],**bindings})
        exclusive_json(sources._path(root,child),childsource)
        bindings[str(sources._path(root,child))] = sha(sources._path(root,child))
        image_path = root/'engineering/judge_image_transport'/(task+'.json')
        if image_path.exists():
            image = read(image_path)
            exclusive_json(root/'engineering/judge_image_transport'/(child+'.json'),
                dict(image,source_bindings={**image['source_bindings'],**bindings},original_request=task))
    receipt = dict(time=stamp(),transport_version=transport.VERSION,service_version=NETWORK_VERSION,
        original_task=task,recovery_task=child,success_evidence=str(success),bindings=bindings,
        max_new_calls=1,failed_shard_retry_budget=1,original_failure_preserved=True,
        accepted_siblings_preserved=True,scoring_semantics_unchanged=True,
        all_sources_and_native_frames_preserved=True,
        reason='Empty network/SSE timeout; later complete same-model/CLI judge establishes restored service')
    exclusive_json(mapping,receipt)
    return receipt


def network_tasks(root, tasks):
    """Run never-attempted independent shards before diagnosed empty timeouts."""
    ordinary=[]; deferred=[]
    for task in tasks:
        folder = Path(root)/'model_calls'/task[0]
        if folder.exists() and not (folder/'accepted_response.json').exists():
            network_timeout(root, task[0])
            deferred.append(task)
        else:
            ordinary.append(task)
    if not deferred: raise ValueError('No diagnosed network timeout to continue')
    return ordinary+deferred, {t[0] for t in deferred}


def latest_network_success(root, task):
    candidates=[]
    for accepted in (Path(root)/'model_calls').glob('gameness_v4*/accepted_response.json'):
        try:
            proof=network_success(root,task,accepted.parent)
        except (ValueError,KeyError,FileNotFoundError):
            continue
        candidates.append((proof['time'],str(accepted.parent)))
    if not candidates: raise ValueError('Service restoration is not yet established by a later complete independent judge')
    return Path(max(candidates)[1])
