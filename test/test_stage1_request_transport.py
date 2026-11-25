import gzip
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

from pipeline.eval.stage1.request_transport import compressed_request, gzip_proxy


def test_gzip_preserves_full_body():
    raw = json.dumps({'images': ['whole-pixel-payload' * 10000], 'model': 'gpt-6.1-sol'}).encode()
    encoded, receipt = compressed_request(raw)
    assert gzip.decompress(encoded) == raw
    assert receipt['roundtrip_equal'] and len(encoded) < len(raw)


def test_proxy_preserves_request_auth_response_and_records(tmp_path):
    seen = []
    class Upstream(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_POST(self):
            seen.append((self.path, self.headers['Authorization'],
                         gzip.decompress(self.rfile.read(int(self.headers['Content-Length'])))))
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            self.wfile.write(b'data: {"model":"gpt-6.1-sol"}\n\n')
    server = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    raw = b'{"all_source":"complete","images":["every-pixel"]}'
    try:
        with gzip_proxy(tmp_path, upstream=f'http://127.0.0.1:{server.server_port}/v1', timeout=10) as url:
            reply = requests.post(url + '/responses', data=raw, headers={'Authorization': 'Bearer test-secret'}, timeout=10)
        assert reply.status_code == 200 and reply.content == b'data: {"model":"gpt-6.1-sol"}\n\n'
        assert seen == [('/v1/responses', 'Bearer test-secret', raw)]
        receipt = json.loads((tmp_path / 'request_001/receipt.json').read_text())
        assert receipt['state'] == 'complete' and receipt['roundtrip_equal']
        assert gzip.decompress((tmp_path / 'request_001/body.json.gz').read_bytes()) == raw
        assert 'test-secret' not in (tmp_path / 'request_001/receipt.json').read_text()
    finally:
        server.shutdown(); server.server_close(); thread.join()
