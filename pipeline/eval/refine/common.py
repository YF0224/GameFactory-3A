"""Small immutable-input and checkpoint primitives (no global training-data writes)."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import time


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def dump(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f'.{os.getpid()}.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temp.replace(path)


def resolve(root, value):
    path = Path(value).expanduser()
    return (path if path.is_absolute() else Path(root) / path).resolve()


def inside(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f'Path escapes evidence root: {relative}')
    return path


def jsonl(path):
    return [(number, json.loads(line)) for number, line in
            enumerate(Path(path).read_text(encoding='utf-8-sig').splitlines(), 1) if line.strip()]


def once(root, name, operation):
    """Never silently rerun a failed/interrupted session, model call, or recorder."""
    marker = Path(root) / 'stages' / (name + '.json')
    if marker.exists():
        state = read(marker)
        if state['status'] == 'COMPLETE':
            return state['result']
        raise RuntimeError(f'{name}: saved {state["status"]}; preserve attempt; use a new output for explicit retry')
    started = time.time()
    dump(marker, {'status': 'STARTED', 'started_unix': started})
    try:
        result = operation()
        dump(marker, {'status': 'COMPLETE', 'started_unix': started,
                      'elapsed_seconds': time.time() - started, 'result': result})
        return result
    except BaseException as exc:
        dump(marker, {'status': 'ERROR', 'started_unix': started,
                      'elapsed_seconds': time.time() - started,
                      'error': f'{type(exc).__name__}: {exc}'})
        raise
