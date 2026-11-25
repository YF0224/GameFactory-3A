"""Lossless common-contract source transport with proved model tool delivery.

The complete original source is included as deterministic gzip/base64, and also
exposed as ordered, bounded, immutable UTF-8 chunks. A response cannot be accepted
until actual completed model shell outputs contain every chunk byte in order.
This transports source data only; it supplies no runtime observations or credit.
"""
import base64
import gzip
import hashlib
import json
from pathlib import Path
from . import mechanic_v3_runner as runner
from .protocol import sha

VERSION = 'gameness-v4-lossless-contract-chunks.v1'
AUTH = 'engineering/complete_contract_chunks/authorization.json'
MAX_BYTES = 1000000
CHUNK_CHARS = 16000


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def ordered_source_outputs(events, chunks):
    """Require exact untruncated real outputs, not a model's self-report."""
    remaining = ''.join(chunks)
    accepted = []
    for line in events.splitlines():
        value = json.loads(line)
        item = value.get('item', {})
        if (value.get('type') != 'item.completed' or item.get('type') != 'command_execution'
                or item.get('exit_code') != 0):
            continue
        output = item.get('aggregated_output', '')
        if not output or not remaining.startswith(output):
            continue
        remaining = remaining[len(output):]
        accepted.append(dict(item_id=item.get('id'), output_sha256=digest(output.encode()),
            output_bytes=len(output.encode())))
        if not remaining:
            return accepted
    raise ValueError('HARNESS_ERROR: model did not receive every complete source chunk in order')


def make_payloads(text):
    payloads = []
    for index, start in enumerate(range(0, len(text), CHUNK_CHARS)):
        body = text[start:start+CHUNK_CHARS]
        payloads.append('SOURCE_CHUNK '+str(index)+' SHA256 '+digest(body.encode())+'\n'
            +body+'\nEND_SOURCE_CHUNK '+str(index)+'\n')
    if not payloads:
        raise ValueError('Empty source container cannot opt in')
    return payloads


def wire_prompt(original, text, folder, chunks):
    marker = '\nAUTHOR SOURCES\n'+text+'\nEXACT SCHEMA FILE '
    if original.count(marker) != 1:
        raise ValueError('Complete original author-source boundary differs')
    raw = text.encode()
    envelope = dict(encoding='gzip-base64-exact-utf8.v1', source_sha256=digest(raw),
        byte_count=len(raw), physical_line_count=len(text.splitlines()),
        data=base64.b64encode(gzip.compress(raw, mtime=0)).decode())
    paths = [str((folder/'chunks'/('%04d.txt'%n)).resolve()) for n in range(len(chunks))]
    notice = ('COMPLETE LOSSLESS ORIGINAL AUTHOR SOURCE TRANSPORT. The gzip/base64 envelope below '
        'contains every original source byte. The bounded decoded chunk files are exact slices of '
        'the same source, in the listed order, with transport header/footer wrappers only. '
        'Before forming the contract, use read-only shell cat to read EVERY listed chunk in order; '
        'use max_output_tokens at least 16000 per chunk and avoid truncation. You may concatenate '
        'adjacent chunks in one read only if the full output fits. Do not merely inspect a manifest, '
        'SHA, compressed text, summary or selected ranges. Every chunk must actually appear in '
        'completed shell output; acceptance independently checks every byte and order. '
        'Read each chunk once. These chunk IDs and source-container wrappers are not citable evidence. '
        'Cite original AUTHOR/model/path headers and original numbered physical source lines. '
        'Retain every source, occurrence and requirement; source data establishes no runtime success.\n'
        'ORDERED READ-ONLY SOURCE CHUNK PATHS\n'+json.dumps(paths,ensure_ascii=False)+'\n'
        'COMPLETE ORIGINAL SOURCE ENVELOPE\n'+json.dumps(envelope,separators=(',',':'))+'\n')
    return original.replace(marker, '\nAUTHOR SOURCES\n'+notice+'\nEXACT SCHEMA FILE ', 1)


def authorize(workspace, case):
    from . import gameness_v3_runtime as runtime
    workspace=Path(workspace).resolve();folder=runtime.contract_dir(workspace,case)
    policy=runtime.workspace_policy(workspace)
    if not policy.VERSION.endswith('.v4') or (folder/'frozen.json').exists() or list((folder/'model_calls').glob('*')):
        raise ValueError('Only never-invoked complete original v4 source contracts may opt in')
    proto=runner.read(folder/'frozen_protocol.json')
    from .gameness_v3_independent import active
    if active(proto):raise ValueError('Reduced independent contracts cannot opt in')
    source=folder/'author_sources.txt';text=source.read_bytes().decode();schema=folder/'planned_schema.json'
    if runner.read(schema)!=policy.contract_schema(proto):raise ValueError('Original output schema changed')
    original=(policy.CONTRACT_PROMPT+'\nCHECKS\n'+json.dumps(policy.criteria(proto),ensure_ascii=False)
        +'\nAUTHOR SOURCES\n'+text+'\nEXACT SCHEMA FILE '+str(schema))
    if len(original.encode())<=MAX_BYTES:raise ValueError('No measured original cap failure')
    output=folder/AUTH;out=output.parent;out.mkdir(parents=True,exist_ok=True)
    payloads=make_payloads(text);(out/'chunks').mkdir(exist_ok=True)
    for index,body in enumerate(payloads):
        p=out/'chunks'/('%04d.txt'%index)
        if p.exists() and p.read_bytes()!=body.encode():raise ValueError('Retained source chunk differs')
        if not p.exists():p.write_bytes(body.encode())
    wire=wire_prompt(original,text,out,payloads)
    from .codex import READ_ONLY_EVAL_INSTRUCTIONS
    if len((READ_ONLY_EVAL_INSTRUCTIONS+wire).encode())>MAX_BYTES:
        raise ValueError('Complete lossless source still exceeds unchanged prompt cap')
    for name,data in [('original_prompt.txt',original),('submitted_prompt.txt',wire)]:
        p=out/name
        if p.exists() and p.read_bytes()!=data.encode():raise ValueError('Retained exact prompt differs')
        if not p.exists():p.write_bytes(data.encode())
    binding=runner.read(folder/'source_binding.json')
    for name,h in binding['bindings'].items():
        if sha(Path(name))!=h:raise ValueError('Original author source changed')
    files=[source,schema,folder/'source_binding.json',folder/'frozen_protocol.json',out/'original_prompt.txt',out/'submitted_prompt.txt']+sorted((out/'chunks').glob('*.txt'))
    value=dict(version=VERSION,classification='NON_SCORING_LOSSLESS_SOURCE_TRANSPORT',
        original_prompt_bytes=len(original.encode()),submitted_prompt_bytes=len((READ_ONLY_EVAL_INSTRUCTIONS+wire).encode()),
        maximum_prompt_bytes=MAX_BYTES,source_path=str(source),source_sha256=sha(source),
        original_author_sources_complete=True,original_physical_lines=True,source_only=True,
        model_recalled=False,no_invocation_at_authorization=True,
        original_source_bindings=binding['bindings'],bindings={str(p):sha(p) for p in files},
        production_bindings={str(p):sha(p) for p in [Path(__file__).resolve(),Path(runtime.__file__).resolve()]})
    if output.exists():
        if runner.read(output)!=value:raise ValueError('Retained source authorization differs')
    else:runner.exclusive_json(output,value)
    return dict(path=str(output),sha256=sha(output))


def verify(reference, *, current_code=False):
    path=Path(reference['path'])
    if sha(path)!=reference['sha256']:raise ValueError('Source authorization changed')
    value=runner.read(path)
    if value.get('version')!=VERSION:raise ValueError('Unknown source transport')
    runner_bindings={**value['bindings'],**value['original_source_bindings']}
    if current_code:runner_bindings.update(value['production_bindings'])
    for p,h in runner_bindings.items():
        if sha(Path(p))!=h:raise ValueError('Source transport bound bytes changed: '+p)
    source=Path(value['source_path']);text=source.read_bytes().decode();payloads=make_payloads(text)
    if [p.read_bytes().decode() for p in sorted((path.parent/'chunks').glob('*.txt'))]!=payloads:
        raise ValueError('Source chunks do not exactly reconstruct original UTF-8')
    original=(path.parent/'original_prompt.txt').read_bytes().decode()
    wire=wire_prompt(original,text,path.parent,payloads)
    if wire.encode()!=(path.parent/'submitted_prompt.txt').read_bytes():raise ValueError('Lossless source wire changed')
    return value


def apply(folder, original, text):
    path=Path(folder)/AUTH
    if not path.exists():return original,None
    reference=dict(path=str(path),sha256=sha(path));verify(reference,current_code=True)
    if (path.parent/'original_prompt.txt').read_bytes()!=original.encode():raise ValueError('Original complete request changed')
    if Path(runner.read(path)['source_path']).read_bytes()!=text.encode():raise ValueError('Original complete source differs')
    return (path.parent/'submitted_prompt.txt').read_bytes().decode(),reference


def verify_delivery(reference, call_folder):
    value=verify(reference);folder=Path(call_folder);path=Path(reference['path'])
    chunks=[p.read_bytes().decode() for p in sorted((path.parent/'chunks').glob('*.txt'))]
    events=folder/'events.jsonl';proof=ordered_source_outputs(events.read_text(),chunks)
    prompt=folder/'prompt.txt'
    from .codex import READ_ONLY_EVAL_INSTRUCTIONS
    expected=READ_ONLY_EVAL_INSTRUCTIONS+(path.parent/'submitted_prompt.txt').read_bytes().decode()
    if prompt.read_bytes()!=expected.encode():raise ValueError('Actual source prompt differs')
    actual=dict(version=VERSION,authorization=reference,source_sha256=value['source_sha256'],
        all_original_author_bytes_actually_delivered=True,original_physical_lines=True,source_only=True,
        chunk_count=len(chunks),ordered_output_proof=proof,prompt_sha256=sha(prompt),events_sha256=sha(events))
    receipt=folder/'actual_delivery.json'
    if receipt.exists():
        if runner.read(receipt)!=actual:raise ValueError('Actual source delivery changed')
    else:runner.exclusive_json(receipt,actual)
    return actual
