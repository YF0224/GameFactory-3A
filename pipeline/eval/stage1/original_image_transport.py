"""Read-only Stage3 image calls with retained original-pixel delivery proof.

Uses the same configured Codex provider/model and closed output schema. No
fallback, image resizing, frame selection, context compaction or unbounded retry.
"""
from __future__ import annotations

from ..model_config import JUDGE_MODEL

import base64
import hashlib
import io
import json
import mimetypes
import os
from pathlib import Path
import selectors
import shutil
import signal
import subprocess
import time

from PIL import Image
from .paths import sha256, write_json

VERSION = 'stage3-original-image-transport.v1'


def prove_images(session: Path, prompt: str, originals, submitted):
    users, models = [], []
    for line in session.read_text().splitlines():
        row = json.loads(line)
        value = row.get('payload', {})
        if 'compact' in (str(row.get('type', '')) + str(value.get('type', ''))).lower():
            raise ValueError('Image delivery session contains compaction')
        if row.get('type') == 'turn_context':
            models.append(value.get('model'))
        if row.get('type') == 'response_item' and value.get('type') == 'message' and value.get('role') == 'user':
            if prompt in [c.get('text') for c in value.get('content', []) if c.get('type') in ('input_text', 'text')]:
                users.append(value)
    if len(users) != 1:
        raise ValueError('Exactly one complete retained prompt required')
    images = [c for c in users[0]['content'] if c.get('type') == 'input_image']
    if len(images) != len(originals) or len(submitted) != len(originals):
        raise ValueError('Every declared image must occur in original order')
    proofs = []
    for index, (item, original, encoded) in enumerate(zip(images, originals, submitted)):
        url = item['image_url']
        if not url.startswith('data:image/') or ';base64,' not in url:
            raise ValueError('Actual original image bytes unavailable')
        raw = base64.b64decode(url.split(';base64,', 1)[1], validate=True)
        with Image.open(original) as source, Image.open(io.BytesIO(raw)) as delivered:
            mode = 'RGBA' if 'A' in source.getbands() or 'transparency' in source.info else 'RGB'
            pixels = source.convert(mode).tobytes()
            if source.size != delivered.size or pixels != delivered.convert(mode).tobytes():
                raise ValueError('Original image pixels changed: ' + str(original))
            proofs.append(dict(index=index, original=str(original), original_sha256=sha256(original),
                submitted=str(encoded), submitted_sha256=sha256(encoded), dimensions=list(source.size),
                retained_bytes_sha256=hashlib.sha256(raw).hexdigest(),
                pixel_sha256=hashlib.sha256(pixels).hexdigest(), pixel_equal=True,
                detail=item.get('detail')))
    return proofs, models


def invoke(folder: Path, *, prompt: str, schema: dict, cwd: Path, model: str,
           originals, images, executable: str, env: dict, timeout: float, effort: str):
    """One bounded call. Retain protocol/session and prove actual pixels before return."""
    if model != JUDGE_MODEL or len(images) > 100:
        raise ValueError('Stage3 original-image transport requires Sol and at most 100 images')
    folder = Path(folder)
    # This configured gateway rejects the decompressed body above 50 MiB.
    # A lower bound is enough to reject impossible submissions before dispatch.
    image_wire_bytes = sum(4 * ((Path(p).stat().st_size + 2) // 3) for p in images)
    lower_bound = image_wire_bytes + len(prompt.encode()) + len(json.dumps(schema).encode())
    write_json(folder / 'transport_preflight.json', dict(version=VERSION,
        image_count=len(images), minimum_request_bytes=lower_bound,
        gateway_limit_bytes=50 * 1024**2, original_pixels_required=True))
    if lower_bound > 50 * 1024**2:
        write_json(folder / 'invocation.json', dict(version=VERSION, model_requested=model,
            status='BLOCKED_GATEWAY_BODY_LIMIT', model_dispatched=False,
            minimum_request_bytes=lower_bound, gateway_limit_bytes=50 * 1024**2))
        raise ValueError('Complete original-image packet exceeds the configured gateway 50 MiB limit')
    executable = str(Path(shutil.which(executable) or executable).resolve())
    command = [executable, '--ask-for-approval', 'never', 'app-server', '--listen', 'stdio://']
    deadline = time.monotonic() + timeout
    thread = turn = session_file = None
    meta = dict(version=VERSION, model_requested=model, command=command,
                cli_sha256=sha256(Path(executable)), transport='app-server-original-bytes', image_detail_policy='provider_auto_no_client_resize',
                tools_policy='shell_disabled_complete_packet_only')
    with (folder / 'rpc_requests.jsonl').open('x') as requests, (folder / 'events.jsonl').open('w') as events, (folder / 'stderr.log').open('w') as stderr:
        proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr,
                                cwd=cwd, env=env, start_new_session=True)
        selector = selectors.DefaultSelector()
        selector.register(proc.stdout, selectors.EVENT_READ)
        buffer, serial, messages = b'', 0, []
        def send(method, params=None, notification=False):
            nonlocal serial
            value = dict(method=method)
            if params is not None:
                value['params'] = params
            if not notification:
                serial += 1
                value['id'] = serial
            raw = json.dumps(value, ensure_ascii=False) + '\n'
            requests.write(raw); requests.flush()
            proc.stdin.write(raw.encode()); proc.stdin.flush()
            return value.get('id')
        def receive(predicate):
            nonlocal buffer
            while time.monotonic() < deadline:
                while b'\n' in buffer:
                    line, buffer = buffer.split(b'\n', 1)
                    if not line.strip():
                        continue
                    text = line.decode()
                    events.write(text + '\n'); events.flush()
                    value = json.loads(text); messages.append(value)
                    if 'id' in value and 'method' in value:
                        raise ValueError('Unexpected approval/tool request in read-only judge')
                    if predicate(value):
                        return value
                if proc.poll() is not None:
                    raise RuntimeError('App-server exited before turn completed')
                if selector.select(min(1, max(0, deadline-time.monotonic()))):
                    raw = os.read(proc.stdout.fileno(), 1048576)
                    if not raw:
                        raise RuntimeError('App-server closed output')
                    buffer += raw
            raise TimeoutError('Original image call exhausted its original deadline')
        def request(method, params):
            ident = send(method, params)
            value = receive(lambda v: v.get('id') == ident)
            if 'error' in value:
                raise RuntimeError(method + ': ' + json.dumps(value['error']))
            return value['result']
        try:
            request('initialize', dict(clientInfo=dict(name='stage3_original_images', version=VERSION),
                                       capabilities=dict(experimentalApi=True)))
            send('initialized', notification=True)
            result = request('thread/start', dict(model=model, cwd=str(cwd.resolve()),
                approvalPolicy='never', sandbox='read-only', ephemeral=False,
                config={'ignore_rules': True, 'features.shell_tool': False}))
            thread = result['thread']['id']
            session_file = result['thread'].get('path')
            # An image URL containing the exact original bytes bypasses the local
            # image loader's resize path. Keep the provider's normal detail
            # policy instead of 'original', whose vision token cost can itself
            # trigger CLI compaction. Delivery must still prove native pixels.
            inputs = [dict(type='text', text=prompt)] + [dict(type='image', url=
                'data:' + (mimetypes.guess_type(str(p))[0] or 'image/png') + ';base64,'
                + base64.b64encode(Path(p).read_bytes()).decode()) for p in images]
            result = request('turn/start', dict(threadId=thread, input=inputs, model=model,
                effort=effort, outputSchema=schema, approvalPolicy='never', sandboxPolicy=dict(type='readOnly')))
            turn = result['turn']['id']
            finished = receive(lambda v: v.get('method') == 'turn/completed' and v.get('params', {}).get('turn', {}).get('id') == turn)
            if finished['params']['turn']['status'] != 'completed':
                raise RuntimeError('Original-detail turn failed: ' + json.dumps(finished))
            answers = [v['params']['item']['text'] for v in messages if v.get('method') == 'item/completed' and v.get('params', {}).get('item', {}).get('type') == 'agentMessage']
            if not answers:
                raise RuntimeError('No complete structured response')
            (folder / 'response.json').write_text(answers[-1])
            if not session_file:
                home = Path(env.get('CODEX_HOME', str(Path.home() / '.codex')))
                found = list((home / 'sessions').glob('**/*' + thread + '*.jsonl'))
                if len(found) != 1:
                    raise ValueError('Exactly one retained session required')
                session_file = found[0]
            snapshot = folder / 'retained_session.jsonl'
            shutil.copyfile(session_file, snapshot)
            proof, models = prove_images(snapshot, prompt, originals, images)
            if not models or any(m != model for m in models):
                raise ValueError('Retained model differs from requested model')
            write_json(folder / 'actual_delivery.json', dict(version=VERSION, thread=thread, turn=turn,
                session_sha256=sha256(snapshot), prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
                models=models, images=proof, all_original_pixels_delivered=True))
            meta.update(exit_code=0, thread=thread, turn=turn, response_present=True,
                        actual_delivery_sha256=sha256(folder / 'actual_delivery.json'))
        except Exception as exc:
            meta.update(exit_code=None, status='HARNESS_ERROR', thread=thread, turn=turn, error=str(exc))
            raise
        finally:
            meta['seconds'] = round(timeout - max(0, deadline - time.monotonic()), 2)
            write_json(folder / 'invocation.json', meta)
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL); proc.wait(timeout=5)
            selector.close()
