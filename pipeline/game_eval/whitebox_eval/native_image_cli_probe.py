"""Bounded, non-scoring native-image transport qualification through pinned Codex.

The app-server protocol exposes per-image `original` detail, which exec's --image
argument cannot express. Qualification requires the actual retained model input,
not a command-line filename or a model's assertion about image dimensions.
"""
from pathlib import Path
import argparse
import base64
import hashlib
import io
import json
import os
import selectors
import shutil
import subprocess
import time
from PIL import Image
from . import codex, mechanic_v3_runner as runner
from .protocol import dump, sha

VERSION = 'whitebox-native-image-original-detail-probe.v1'


def retained_images(session_path, prompt, originals):
    """Prove ordered actual image bytes or decoded pixels, without resizing."""
    users = []
    for line in Path(session_path).read_text().split('\n'):
        if not line.strip():
            continue
        row = json.loads(line); p = row.get('payload', {})
        if 'compact' in (str(row.get('type', ''))+' '+str(p.get('type', ''))).lower():
            raise ValueError('Native-pixel qualification forbids compaction')
        if row.get('type') == 'response_item' and p.get('type') == 'message' and p.get('role') == 'user':
            texts = [v.get('text') for v in p.get('content', []) if v.get('type') in {'input_text', 'text'}]
            if prompt in texts:
                users.append(p)
    if len(users) != 1:
        raise ValueError('Exactly one complete actual input prompt required')
    images = [v['image_url'] for v in users[0]['content'] if v.get('type') == 'input_image']
    if len(images) != len(originals):
        raise ValueError('Every declared original image must actually occur in order')
    proof = []
    for encoded, path in zip(images, originals):
        if not encoded.startswith('data:image/') or ';base64,' not in encoded:
            raise ValueError('Actual original image bytes are unavailable')
        raw = base64.b64decode(encoded.split(';base64,', 1)[1], validate=True)
        with Image.open(io.BytesIO(raw)) as delivered, Image.open(path) as original:
            delivered.load(); original.load()
            if delivered.size != original.size or delivered.convert('RGB').tobytes() != original.convert('RGB').tobytes():
                raise ValueError('CLI changed original native pixels: '+str(path))
            proof.append(dict(path=str(Path(path).resolve()), sha256=sha(Path(path)),
                dimensions=list(original.size), retained_bytes_sha256=hashlib.sha256(raw).hexdigest(),
                byte_identical=raw == Path(path).read_bytes(), rgb_pixels_identical=True))
    return proof


def rpc_invoke(folder, root, prompt, schema, images, *, model, session=None, fork_through=None, context_window=None):
    """One bounded turn; exact protocol I/O is retained, no implicit retry."""
    if model != 'gpt-6.1-sol' or len(prompt.encode()) > 1000000 or len(images) > 100:
        raise ValueError('Frozen model and per-turn byte/image limits required')
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=False)
    dump(folder/'schema.json', schema); (folder/'prompt.txt').write_text(prompt)
    executable, runtime = codex.evaluation_executable('codex')
    executable = str(Path(shutil.which(executable) or executable).resolve())
    command = [executable, '--ask-for-approval', 'never', 'app-server', '--listen', 'stdio://']
    dump(folder/'cli_runtime.json', runtime or dict(path=executable, sha256=sha(Path(executable))))
    if context_window is not None and (type(context_window) is not int or not 0<context_window<=828400):
        raise ValueError('Fresh native transport context window must remain bounded')
    config = dict(model_auto_compact_token_limit=100000000, model_context_window=context_window or 1050000)
    requests = open(folder/'rpc_requests.jsonl', 'x'); events = open(folder/'rpc_events.jsonl', 'x')
    stderr = open(folder/'stderr.log', 'x')
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=stderr, text=False, start_new_session=True)
    selector = selectors.DefaultSelector(); selector.register(process.stdout, selectors.EVENT_READ)
    deadline = time.monotonic()+900; pending=b''; serial=0; messages=[]
    def send(method, params=None, notification=False):
        nonlocal serial
        value=dict(method=method)
        if params is not None: value['params']=params
        if not notification: serial+=1; value['id']=serial
        raw=json.dumps(value, ensure_ascii=False)+'\n'; requests.write(raw); requests.flush()
        process.stdin.write(raw.encode()); process.stdin.flush()
        return value.get('id')
    def receive(predicate):
        nonlocal pending
        while time.monotonic()<deadline:
            while b'\n' in pending:
                line,pending=pending.split(b'\n',1)
                if not line.strip(): continue
                text=line.decode();events.write(text+'\n');events.flush();value=json.loads(text);messages.append(value)
                if 'id' in value and 'method' in value:
                    raise ValueError('Unexpected model tool/approval request during read-only evaluation')
                if predicate(value): return value
            if process.poll() is not None: raise ValueError('App-server exited before complete turn')
            if selector.select(min(1,max(0,deadline-time.monotonic()))):
                raw=os.read(process.stdout.fileno(),1048576)
                if not raw: raise ValueError('App-server closed output')
                pending+=raw
        raise TimeoutError('Bounded original-detail turn timed out')
    def request(method, params):
        ident=send(method, params);value=receive(lambda v:v.get('id')==ident)
        if 'error' in value: raise ValueError('App-server '+method+' rejected: '+json.dumps(value['error']))
        return value['result']
    thread=None;turn=None
    try:
        request('initialize', dict(clientInfo=dict(name='whitebox_native_pixel_qualification',version=VERSION),
            capabilities=dict(experimentalApi=True)))
        send('initialized', notification=True)
        parameters=dict(model=model,cwd=str(Path(root).resolve()),approvalPolicy='never',sandbox='read-only',config=config)
        if session: parameters['threadId']=session
        if fork_through:
            if not session: raise ValueError('A retained parent thread is required for an exact fork')
            parameters['lastTurnId']=fork_through
        method='thread/fork' if fork_through else ('thread/resume' if session else 'thread/start')
        thread=request(method,parameters)['thread']['id']
        inputs=[dict(type='text', text=prompt)]+[dict(type='localImage',path=str(Path(p).resolve()),detail='original') for p in images]
        result=request('turn/start',dict(threadId=thread,input=inputs,model=model,
            effort='medium',outputSchema=schema,approvalPolicy='never',sandboxPolicy=dict(type='readOnly')))
        turn=result['turn']['id']
        finished=receive(lambda v:v.get('method')=='turn/completed' and v.get('params',{}).get('turn',{}).get('id')==turn)
        status=finished['params']['turn']['status']
        if status!='completed': raise ValueError('Original-detail turn failed: '+json.dumps(finished))
        answers=[v['params']['item']['text'] for v in messages if v.get('method')=='item/completed'
            and v.get('params',{}).get('item',{}).get('type')=='agentMessage']
        if not answers: raise ValueError('No complete structured model response')
        response=json.loads(answers[-1]);dump(folder/'response.json',response)
        dump(folder/'invocation.json',dict(command=command,model_requested=model,attempt=1,exit_code=0,
            thread=thread,turn=turn,transport='app-server-original-detail',input_count=len(images),
            maximum_prompt_bytes=1000000,maximum_images=100))
        return response,thread
    except Exception as error:
        dump(folder/'invocation.json',dict(command=command,model_requested=model,attempt=1,
            status='HARNESS_ERROR',error=repr(error),product_score=None,thread=thread,turn=turn,
            transport='app-server-original-detail',parent_session=session,fork_through=fork_through))
        raise
    finally:
        # Close this task's private app-server only. No shared daemon is used.
        if process.poll() is None:
            process.terminate()
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired: process.kill();process.wait(timeout=10)
        requests.close();events.close();stderr.close();selector.close()


def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('--phase',choices=['native-image-delivery-acceptance'],required=True)
    parser.add_argument('--workspace',type=Path,required=True);parser.add_argument('--probe-spec',type=Path,required=True)
    args=parser.parse_args(argv);spec=runner.read(args.probe_spec);workspace=args.workspace.resolve()
    if spec.get('classification')!='NON_SCORING_NATIVE_PIXEL_TRANSPORT' or spec.get('maximum_model_calls')!=1:
        raise ValueError('One explicit non-scoring pixel qualification required')
    from .mechanic_v3_cli import production_source_bindings
    if production_source_bindings()!=spec['after_source_bindings']:
        raise ValueError('Qualification requires exact complete production')
    images=[Path(p).resolve() for p in spec['images']]
    for p,digest in spec['image_bindings'].items():
        if sha(Path(p))!=digest: raise ValueError('Original image binding changed')
    if {str(p) for p in images}!=set(spec['image_bindings']): raise ValueError('Complete image list binding required')
    folder=workspace/'engineering/native_image_delivery_acceptance'
    runner.disk(workspace,'original_native_pixel_probe',128*1024**2)
    prompt='Native image transport calibration only. Do not evaluate any game, rubric or score. Do not call tools. Return only {"receipt":"ORIGINAL_IMAGE_TRANSPORT_ONLY"}.'
    schema=codex.obj({'receipt':{'type':'string','enum':['ORIGINAL_IMAGE_TRANSPORT_ONLY']}})
    response,thread=rpc_invoke(folder,workspace,prompt,schema,images,model='gpt-6.1-sol')
    if response!={'receipt':'ORIGINAL_IMAGE_TRANSPORT_ONLY'}: raise ValueError('Non-scoring acknowledgment changed')
    from .gameness_v4_persistent_text import session_path
    source=session_path(thread);snapshot=folder/'retained_session.jsonl';snapshot.write_bytes(source.read_bytes())
    proof=retained_images(snapshot,prompt,images)
    dump(folder/'pixel_acceptance.json',dict(version=VERSION,capability='NON_SCORING_ORIGINAL_PIXEL_TRANSPORT',
        all_original_pixels_delivered=True,score_or_judgment=False,maximum_model_calls=1,images=proof,
        session=thread,session_sha256=sha(snapshot),production_bindings=production_source_bindings()))
    print(json.dumps(dict(stage='ORIGINAL_NATIVE_PIXELS_ACCEPTED',images=len(proof),scoring_calls=0)),flush=True)
    return 0
