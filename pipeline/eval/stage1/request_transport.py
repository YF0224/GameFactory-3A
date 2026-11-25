"""Opt-in HTTP gzip transport; forwards the exact CLI request without changes."""
from __future__ import annotations

import gzip
import hashlib
import json
import threading
import tomllib
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import requests

from .paths import write_json


def compressed_request(raw: bytes) -> tuple[bytes, dict]:
    encoded = gzip.compress(raw, mtime=0)
    if gzip.decompress(encoded) != raw:
        raise ValueError('HTTP request compression round-trip mismatch')
    return encoded, {'raw_bytes': len(raw), 'gzip_bytes': len(encoded),
                     'raw_sha256': hashlib.sha256(raw).hexdigest(),
                     'gzip_sha256': hashlib.sha256(encoded).hexdigest(), 'roundtrip_equal': True}


@contextmanager
def gzip_proxy(folder: Path, *, upstream: str, timeout: float):
    """Loopback-only proxy, retaining compressed request bytes and SHA receipts.

    Authorization is forwarded in memory and never persisted in receipts. No
    retries, model changes, request JSON edits, or response edits are performed.
    """
    upstream = upstream.rstrip('/')
    parsed = urlsplit(upstream)
    if parsed.scheme not in ('http', 'https') or parsed.query or parsed.fragment:
        raise ValueError('Unsupported upstream URL')
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    counter = iter(range(1, 10000))
    guard = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            with guard:
                index = next(counter)
            dest = folder / f'request_{index:03d}'
            dest.mkdir()
            if self.path.split('?', 1)[0] != parsed.path.rstrip('/') + '/responses':
                self.send_error(404)
                return
            raw = self.rfile.read(int(self.headers['Content-Length']))
            encoded, meta = compressed_request(raw)
            (dest / 'body.json.gz').write_bytes(encoded)
            headers = {k: v for k, v in self.headers.items()
                       if k.lower() not in ('host', 'content-length', 'connection', 'content-encoding', 'transfer-encoding')}
            headers['Content-Encoding'] = 'gzip'
            headers['Content-Length'] = str(len(encoded))
            write_json(dest / 'receipt.json', {**meta, 'state': 'sending'})
            try:
                with requests.post(upstream + self.path[len(parsed.path.rstrip('/')):], data=encoded,
                                   headers=headers, stream=True, timeout=(20, max(1, timeout))) as response:
                    meta['upstream_status'] = response.status_code
                    write_json(dest / 'receipt.json', {**meta, 'state': 'streaming'})
                    self.send_response(response.status_code)
                    for key, value in response.headers.items():
                        if key.lower() not in ('connection', 'content-length', 'transfer-encoding'):
                            self.send_header(key, value)
                    self.send_header('Connection', 'close')
                    self.end_headers()
                    with (dest / 'response.bin').open('wb') as saved:
                        for chunk in response.raw.stream(8192, decode_content=False):
                            saved.write(chunk)
                            self.wfile.write(chunk)
                            self.wfile.flush()
                write_json(dest / 'receipt.json', {**meta, 'state': 'complete'})
            except Exception as exc:
                write_json(dest / 'receipt.json', {**meta, 'state': 'transport_error', 'error': str(exc)})
                self.close_connection = True

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}{parsed.path.rstrip("/")}'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def configured_upstream(env: dict) -> tuple[str, str]:
    import os
    home = Path(env.get('CODEX_HOME', str(Path.home() / '.codex')))
    config = tomllib.loads((home / 'config.toml').read_text())
    provider = config.get('model_provider', 'openai')
    return provider, config['model_providers'][provider]['base_url']
