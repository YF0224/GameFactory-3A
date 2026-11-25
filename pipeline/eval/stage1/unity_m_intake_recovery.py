"""One receipt-only correction retaining the complete original source and pixels."""
from pathlib import Path
from . import batch, codex
from .protocol import sha

ACK = ('Non-scoring intake receipt-format correction only. Your complete original source and '
       'native images remain in this same conversation. Preserve them without compaction or '
       'summarization. Do not repeat source, images or metadata, do not judge and do not use tools. '
       'Return exactly this one-field JSON object, with no additional fields: '
       '{"receipt":"COMPLETE_ORIGINAL_SOURCE_AND_NATIVE_FRAME_INTAKE"}.')


def failure(response, schema):
    """Only the observed intake acknowledgement with extra keys may be corrected."""
    expected = {'receipt': 'COMPLETE_ORIGINAL_SOURCE_AND_NATIVE_FRAME_INTAKE'}
    if (type(response) is not dict or response.get('receipt') not in {expected['receipt'], 'INTAKE_RECEIVED'}
            or not set(response)-{'receipt'}):
        raise ValueError('Only a preserved intake extra-field failure is recoverable')
    codex.validate_schema(expected, schema)
    try:
        codex.validate_schema(response, schema)
    except ValueError as error:
        if 'missing or unexpected keys; missing=[]' not in str(error):
            raise ValueError('Exact closed intake schema failure required') from error
    else:
        raise ValueError('Valid original intake must be reused')


def original_inputs(data, prompt):
    """Separate the actual intake from retained environment and image envelopes."""
    from .unity_m_delivery import text_inputs
    users = [row['payload'] for row in data if row.get('type') == 'response_item'
             and row.get('payload', {}).get('role') == 'user']
    if not users:
        raise ValueError('Complete original intake user message required')
    for user in users[:-1]:
        contents = user.get('content', [])
        if not contents or any(item.get('type') not in {'text', 'input_text'} for item in contents):
            raise ValueError('Only retained environment envelopes may precede intake')
        for item in contents:
            text = item['text']
            if not ((text.startswith('# AGENTS.md instructions for ') and text.endswith('</INSTRUCTIONS>'))
                    or (text.startswith('<environment_context>') and text.endswith('</environment_context>'))):
                raise ValueError('Unexpected task text precedes original intake')
    content = users[-1].get('content', [])
    if not content or content[0].get('type') not in {'text', 'input_text'} or content[0].get('text') != prompt:
        raise ValueError('Exact complete original intake prompt required')
    rest = content[1:]
    if len(rest) % 3:
        raise ValueError('Complete original image envelopes required')
    import re
    for n in range(0, len(rest), 3):
        opening, image, closing = rest[n:n+3]
        if (opening.get('type') not in {'text', 'input_text'}
                or not re.fullmatch(r'<image name=\[Image #'+str(n//3+1)+r'\] path="[^"\n]+">', opening.get('text', ''))
                or image.get('type') != 'input_image'
                or closing.get('type') not in {'text', 'input_text'} or closing.get('text') != '</image>'):
            raise ValueError('Original image envelope order or content changed')
    return text_inputs(data)


def parent(original):
    """Return a verified actual parent snapshot and its complete turn sequence."""
    from .unity_m_delivery import rows, text_inputs
    original = Path(original)
    invocation = batch.read(original/'invocation.json')
    prompts = [(original/'prompt.txt').read_text()]
    turns = [invocation['turn']]
    pointer = original/'receipt_correction.json'
    if not pointer.exists():
        return original, prompts, turns
    descriptor = batch.read(pointer)
    folder = original.parent/(original.name+'_receipt_01')
    if (descriptor.get('version') != 'unity-m-original-intake-receipt-correction.v1'
            or descriptor.get('maximum_new_calls') != 1 or descriptor.get('prompt') != ACK
            or descriptor.get('folder') != str(folder)):
        raise ValueError('Exact bounded intake correction descriptor required')
    for path, digest in descriptor['bindings'].items():
        if sha(Path(path)) != digest:
            raise ValueError('Original failed intake binding changed')
    failure(batch.read(original/'response.json'), batch.read(original/'schema.json'))
    if not (folder/'response.json').exists() or not (folder/'retained_session.jsonl').exists():
        raise ValueError('Preserved intake correction incomplete; no unchanged repeat')
    corrected = batch.read(folder/'invocation.json')
    if ((folder/'prompt.txt').read_text() != ACK
            or batch.read(folder/'schema.json') != batch.read(original/'schema.json')
            or corrected['thread'] != invocation['thread'] or corrected['turn'] == invocation['turn']):
        raise ValueError('Intake correction must retain the original conversation and schema')
    codex.validate_schema(batch.read(folder/'response.json'), batch.read(original/'schema.json'))
    raw = (original/'retained_session.jsonl').read_bytes()
    snapshot = (folder/'retained_session.jsonl').read_bytes()
    if not raw.endswith(b'\n') or not snapshot.startswith(raw):
        raise ValueError('Complete original intake snapshot must be an unchanged prefix')
    data = rows(folder/'retained_session.jsonl')
    prompts += [ACK]; turns += [corrected['turn']]
    complete = [r['payload'].get('turn_id') for r in data
                if r.get('payload', {}).get('type') == 'task_complete']
    original_data = rows(original/'retained_session.jsonl')
    original_text = original_inputs(original_data, prompts[0])
    if text_inputs(data) != original_text+[ACK] or complete != turns:
        raise ValueError('Exactly the original intake and one receipt correction required')
    for item in data:
        value = item.get('payload', {})
        if 'compact' in (str(item.get('type'))+' '+str(value.get('type'))).lower():
            raise ValueError('Compacted intake forbidden')
        if item.get('type') == 'turn_context' and value.get('model') != 'gpt-6.1-sol':
            raise ValueError('Original intake model changed')
    return folder, prompts, turns


def recover(root, original, common):
    from .unity_m_judge import retained, exact_json, WINDOW, RESERVE, MARGIN
    from .native_image_cli_probe import rpc_invoke
    from .gameness_v4_persistent_text import session_path
    import json
    root, original = Path(root), Path(original)
    if (original/'receipt_correction.json').exists():
        return parent(original)[0]
    schema = batch.read(original/'schema.json')
    failure(batch.read(original/'response.json'), schema)
    inv = batch.read(original/'invocation.json')
    proof = retained(original, inv['thread'], common['prompt'], [Path(p) for p in common['images']])
    from .unity_m_delivery import rows, text_inputs
    data = rows(original/'retained_session.jsonl')
    completed = [r['payload'].get('turn_id') for r in data
                 if r.get('payload', {}).get('type') == 'task_complete']
    original_inputs(data, common['prompt'])
    if completed != [inv['turn']]:
        raise ValueError('Exact completed original intake required before correction')
    required = proof['usage']['input_tokens']+proof['usage']['output_tokens']+len(ACK.encode())+len(json.dumps(schema).encode())+RESERVE+MARGIN
    if required > min(WINDOW, proof['usage']['window']):
        raise ValueError('Retained intake correction capacity exceeded')
    folder = original.parent/(original.name+'_receipt_01')
    if folder.exists():
        raise ValueError('Preserve unqualified intake correction; no duplicate call')
    files = ('prompt.txt','schema.json','response.json','invocation.json',
             'rpc_requests.jsonl','rpc_events.jsonl','retained_session.jsonl')
    exact_json(original/'receipt_correction.json', dict(
        version='unity-m-original-intake-receipt-correction.v1', maximum_new_calls=1,
        prompt=ACK, folder=str(folder), required=required,
        bindings={str(original/n):sha(original/n) for n in files}))
    _, thread = rpc_invoke(folder, root, ACK, schema, [], model='gpt-6.1-sol',
                          session=inv['thread'], context_window=WINDOW)
    (folder/'retained_session.jsonl').write_bytes(session_path(thread).read_bytes())
    return parent(original)[0]
