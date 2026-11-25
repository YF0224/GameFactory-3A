"""Audit reused model requests against their actual original image paths."""
from pathlib import Path
import re

from . import frame_budget
from .protocol import sha


def receipt_path(root):
    root = Path(root)
    for name in ('channel_transport_recovery.json', 'static_delivery_recovery.json'):
        if (root/name).is_file():
            return root/name
    raise ValueError('Missing explicit request reuse receipt')


def load_receipt(root):
    from .batch import read
    path = receipt_path(root)
    receipt = read(path)
    if path.name == 'static_delivery_recovery.json':
        if (receipt.get('schema') != 'whitebox-static-transport-recovery.v1'
                or receipt.get('new_model_calls_allowed') != ['static']
                or receipt.get('execution_allowed') is not False):
            raise ValueError('Unsupported static request reuse receipt')
        source = Path(receipt['source_attempt']).resolve()
        for key, relative in [('source_score_sha256', 'scores.json'),
                              ('source_static_sha256', 'judgments/static.json'),
                              ('source_model_prompt_sha256', 'model_calls/static/prompt.txt')]:
            if receipt.get(key) != sha(source/relative):
                raise ValueError('Static recovery source binding changed: '+key)
        if receipt.get('policy_sha256') != sha(Path(root)/'static_packet_policy.json'):
            raise ValueError('Static recovery packet policy changed')
        receipt = dict(receipt, reused_judge_shards=receipt['preserved_dynamic_shards'])
        if 'static' in receipt['reused_judge_shards']:
            raise ValueError('Static recovery must freshly judge static sources')
    elif receipt.get('schema') != 'whitebox-endpoint-channel-recovery.v1':
        raise ValueError('Unsupported explicit request reuse receipt')
    return receipt


def has_receipt(root):
    return any((Path(root)/name).is_file() for name in
               ('channel_transport_recovery.json', 'static_delivery_recovery.json'))


def audit_one(root, name, protocol, manifest):
    from .codex import saved_model_response, load_plan_json
    root = Path(root)
    folder = saved_model_response(root,name).parent
    recorded = load_plan_json(folder/'actual_delivery.json')
    images = [root/row['path'] for row in recorded['images']]
    expected = frame_budget.validate_request(root,name,protocol,manifest,images,(folder/'prompt.txt').read_text(),
        recorded_transport=recorded.get('request_transport_policy','legacy'))
    if recorded != expected:
        raise ValueError('Preserved actual model request differs from per-shard delivery: '+name)
    invocation = load_plan_json(folder/'invocation.json')
    command = invocation.get('command',[])
    submitted = [command[index+1] for index,value in enumerate(command[:-1]) if value == '--image']
    if invocation.get('exit_code') != 0 or [Path(path).resolve() for path in submitted] != [path.resolve() for path in images]:
        raise ValueError('Actual original model process did not receive frozen images: '+name)
    return folder


def audit_requests(root, protocol, manifest, *, _ancestors=frozenset()):
    from . import batch
    from .codex import decode_keyed_judgment, load_plan_json, saved_model_response
    root = Path(root).resolve()
    if root in _ancestors:
        raise ValueError('Cyclic request reuse provenance')
    ancestors = _ancestors | {root}
    receipt = load_receipt(root)
    source = Path(receipt['source_attempt']).resolve()
    if source == root or source.parent != root.parent:
        raise ValueError('Request reuse source must be another preserved attempt in this batch')
    original_protocol = batch.read(source/'input/pilot_rubric.json')
    original_manifest = batch.read(source/'evidence_manifest.json')
    original_inputs = batch.read(source/'input_manifest.json')
    inputs = batch.read(root/'input_manifest.json')
    if original_inputs['entry']['id'] != inputs['entry']['id']:
        raise ValueError('Request reuse changed source identity')
    asset_migration = receipt.get('recovery_kind') == 'required-asset-slots-only.v1'
    if asset_migration:
        from .asset_reservation import verify_recovery
        verify_recovery(root, protocol, source)
        if 'static' in receipt['reused_judge_shards']:
            raise ValueError('asset migration must freshly judge the required asset inventory')
    elif original_protocol != protocol or original_inputs['input_hashes'] != inputs['input_hashes']:
        raise ValueError('Request reuse changed frozen inputs or source identity')
    if receipt.get('schema') == 'whitebox-endpoint-channel-recovery.v1':
        qualification = Path(receipt['qualification'])
        if sha(qualification) != receipt['qualification_sha256']:
            raise ValueError('Original request qualification changed')
        qualified = batch.read(qualification)
        if qualified['source_attempt'] != str(source) or qualified['source_plan_sha256'] != sha(source/'sol_plan.json'):
            raise ValueError('Request reuse qualification binds a different original plan')
    elif sha(source/'sol_plan.json') != sha(root/'sol_plan.json'):
        raise ValueError('Static recovery changed the original plan')
    names = {name for name,_,_ in frame_budget.tasks(protocol,manifest)}
    reused = receipt['reused_judge_shards']
    if len(reused) != len(set(reused)) or set(reused)-names:
        raise ValueError('Request reuse declares duplicate or foreign shards')
    source_reused = has_receipt(source)
    if source_reused:
        audit_requests(source, original_protocol, original_manifest, _ancestors=ancestors)
    for name,specs,is_static in frame_budget.tasks(protocol,manifest):
        def check_response(attempt):
            response = load_plan_json(saved_model_response(attempt,name))
            artifact = batch.read(attempt/'judgments'/f'{name}.json')
            if artifact['raw'] != decode_keyed_judgment(response,specs):
                raise ValueError('Saved judgment differs from actual original model response: '+name)
        check_response(root)
        if name not in reused:
            audit_one(root,name,protocol,manifest)
            continue
        original_folder = (saved_model_response(source,name).parent if source_reused else
                           audit_one(source,name,original_protocol,original_manifest))
        check_response(source)
        copied_folder = saved_model_response(root,name).parent
        if {path.name:sha(path) for path in original_folder.iterdir() if path.is_file()} != {
                path.name:sha(path) for path in copied_folder.iterdir() if path.is_file()}:
            raise ValueError('Reused original model call was changed: '+name)
        before = frame_budget.for_task(original_manifest,name)
        after = frame_budget.for_task(manifest,name)
        images = lambda subset:[item for item in subset['items'] if item['type'] in {'frame','reference'}]
        if (batch.packet(source,before,is_static) != batch.packet(root,after,is_static)
                or images(before) != images(after) or before['delivery_sheets'] != after['delivery_sheets']):
            raise ValueError('Reused model packet or image provenance changed: '+name)
        recorded = batch.read(copied_folder/'actual_delivery.json')
        current_images = [root/item['path'] for item in recorded['images']]
        expected = frame_budget.validate_request(root,name,protocol,manifest,current_images,
            (copied_folder/'prompt.txt').read_text(),recorded_transport=recorded.get('request_transport_policy','legacy'))
        if recorded != expected:
            raise ValueError('Reused images do not equal the current frozen delivery: '+name)
    return True


def bindings(root, *, _ancestors=frozenset()):
    from . import batch
    from .protocol import checked_path
    root = Path(root).resolve()
    if root in _ancestors:
        raise ValueError('Cyclic request reuse provenance')
    ancestors = _ancestors | {root}
    receipt = load_receipt(root)
    source = Path(receipt['source_attempt']).resolve()
    if source == root or source.parent != root.parent:
        raise ValueError('Request reuse source escapes this batch')
    paths = [receipt_path(root),source/'sol_plan.json',source/'static_existence.json',source/'input_manifest.json',
             source/'input/pilot_rubric.json',source/'evidence_manifest.json']
    if 'qualification' in receipt:
        paths.append(Path(receipt['qualification']))
    else:
        paths += [source/'scores.json', source/'judgments/static.json', source/'model_calls/static/prompt.txt',
                  root/'static_packet_policy.json']
    for name in receipt['reused_judge_shards']:
        if name != 'static' and not re.fullmatch(r'(?:evidence|static)_\d{2}',name):
            raise ValueError('Invalid reused shard identity')
        paths.append(source/'judgments'/f'{name}.json')
        for folder in (source/'model_calls').glob(name+'*'):
            paths.extend(path for path in folder.iterdir() if path.is_file())
        from .codex import saved_model_response
        folder = saved_model_response(source,name).parent
        paths.extend(checked_path(source,item['path']) for item in batch.read(folder/'actual_delivery.json')['images'])
    result = {'reuse_source:'+str(path):sha(path) if path.is_file() else None for path in paths}
    if has_receipt(source):
        result['reuse_source:'+str(receipt_path(source))] = sha(receipt_path(source))
        result.update(bindings(source, _ancestors=ancestors))
    return result
