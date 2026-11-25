"""Reusable recovery/qualification helpers extracted from legacy batch runners.

No batch dispatcher, target enumeration, or CLI is migrated here.
"""
from __future__ import annotations

import argparse

import ast

from contextlib import contextmanager

from datetime import datetime, timezone

import fcntl

import hashlib

import json

import os

from pathlib import Path

import re

import shutil

import sys

import tempfile

import traceback

from . import paths as common
from .paths import BENCH

from . import playable_support as formal

from pipeline.eval.stage1 import prepare

from pipeline.eval.stage1.paths import DELIVERY_SCHEMA, read_json, sha256

VERSION = 'kimi-playable-new-round.v1'

QUOTE = 'kimi的所有项目的playable都跑一下'

DATE = '2026-11-09'

ROOT = formal.BASE / 'stage1_playable_kimi_all_20261109__plan-gpt-6-astra'

OLD_ROOT = formal.BASE / 'stage1_playable_v1__plan-gpt-6-astra'

PRIORITY_SHA = '0780a872145017021e8a7eead5ff97a8910c0fef484f0d8fd13a19e614ac84e3'

FULL_SHA = 'd482ec268038a8a19bfa20f961fa2c7f83c38d9f7227431b21e8923047c2ab60'

FULL_SCOPE_SHA = 'f802b1b19cdb736d50050c69396a743bffecb0dd90224c9012084c87ebf7a941'

PRIORITY_RECEIPT_SHA = 'cb6669b47afbc28dd29599601d1298890d8bd19fd15c006d408fcce0e691f322'

PRODUCER_POLICY = 'stage1-all-formal-except-lazy-eval-stage3.v1'

STAGE3_PREFIX = 'pipeline/eval/stage3/'

RECOVERY = 'recovery/stage3_producer_drift_v1'

from ..model_config import PLANNER_MODEL
MODELS = {'planner': PLANNER_MODEL, 'judge': 'none'}

MIN_FREE = 8 * 1024 ** 3

META = '_kimi_batch'

PAIR_CASES = {'G003', 'G008', 'G014', 'G038', 'G043'}

PAIR_PENDING_REASON = 'PAIR_SUPPORT_PENDING: two independent clients in one authored session require source proof and matching adapter'

G043_BLOCK_SHA = '47153723a88c248ffdaf089e93c3e0642563bac922db2bd59188fbcf8e997d0c'

G043_IDENTITY = {'model': 'Kimi', 'case': 'G043', 'game_id': 'G043_airship_kitchen',
                 'engine': 'godot', 'required_real_clients': 2}

GIB = 1024 ** 3

CACHE_ALLOWANCE = {
    'godot': (GIB // 4, 2),
    'three_js': (GIB // 2, 4),
    'unity3d': (8 * GIB, 4),
    'ue5': (8 * GIB, 8),
}

class DiskReserveStop(RuntimeError):
    def __init__(self, receipt):
        self.receipt = receipt
        super().__init__(f"disk reserve: {receipt['free_bytes']} < {receipt['required_free_bytes']}; stop lane")

def disk_estimate(t, source):
    source_bytes = source['source_bytes']
    require(type(source_bytes) is int and source_bytes >= 0, 'invalid source byte estimate')
    clients = t['required_real_clients']
    require(clients in (1, 2), 'unsupported client count in disk estimate')
    require(t['engine'] in CACHE_ALLOWANCE, 'engine has no cache allowance')
    copy_bytes = source_bytes * (6 if clients == 2 else 2)
    floor, multiplier = CACHE_ALLOWANCE[t['engine']]
    cache_bytes = clients * max(floor, multiplier * source_bytes)
    return {'source_bytes': source_bytes, 'copy_estimate_bytes': copy_bytes,
            'engine_cache_allowance_bytes': cache_bytes, 'reserve_bytes': MIN_FREE,
            'required_free_bytes': copy_bytes + cache_bytes + MIN_FREE,
            'estimate_policy': 'copies+per-client-cache-floor-or-source-multiplier.v1',
            'cache_floor_bytes_per_client': floor, 'cache_source_multiplier': multiplier}

def check_disk(root, t, source):
    estimate = disk_estimate(t, source)
    estimate['free_bytes'] = shutil.disk_usage(root).free
    if estimate['free_bytes'] < estimate['required_free_bytes']:
        raise DiskReserveStop({'state': 'LANE_STOP_LOW_DISK', 'at': now(),
                               'pid': os.getpid(), 'target': t, **estimate,
                               'native_dispatched_for_target': False,
                               'attempt_created_for_target': False})
    return estimate

def require(ok, message):
    if not ok:
        raise RuntimeError(message)

def now():
    return datetime.now(timezone.utc).isoformat()

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

def write(path, value, *, exclusive=False):
    """Durable receipts; callers hold the corresponding target/batch lock."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()
    if exclusive:
        with path.open('xb') as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
    else:
        tmp = path.with_name(path.name + f'.{os.getpid()}.tmp')
        with tmp.open('xb') as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)

def locked(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(f'BUSY: {path}; owner and lock unchanged') from exc
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)

def files(root, *, skip=()):
    """Hash bytes, including malformed JSON. Never follow a source symlink."""
    root = Path(root)
    require(root.is_dir() and not root.is_symlink(), f'missing/linked tree: {root}')
    result = {}
    for directory, dirs, names in os.walk(root, followlinks=False):
        base = Path(directory)
        for name in list(dirs):
            p = base / name
            rel = p.relative_to(root).as_posix()
            if rel in skip or name == '__pycache__':
                dirs.remove(name)
            else:
                require(not p.is_symlink(), f'symlink forbidden: {p}')
        for name in sorted(names):
            p = base / name
            rel = p.relative_to(root).as_posix()
            if rel in skip or name.endswith(('.lock', '.pyc')):
                continue
            require(not p.is_symlink(), f'symlink forbidden: {p}')
            result[rel] = sha256(p)
    return dict(sorted(result.items()))

def source_inventory(root):
    """All authored regular files plus literal links; never traverse symlink targets."""
    regular, links = {}, {}
    root = Path(root)
    require(root.is_dir() and not root.is_symlink(), f'missing/linked source: {root}')
    for directory, dirs, names in os.walk(root, followlinks=False):
        for name in dirs + names:
            p = Path(directory) / name
            rel = p.relative_to(root).as_posix()
            if p.is_symlink():
                links[rel] = os.readlink(p)
                if name in dirs:
                    dirs.remove(name)
            elif p.is_file():
                regular[rel] = sha256(p)
    return {'files': dict(sorted(regular.items())), 'symlinks': dict(sorted(links.items()))}

def source_files(root):
    inventory = source_inventory(root)
    require(not inventory['symlinks'], 'priority source unexpectedly contains symlinks')
    return inventory['files']

def producer_closure(values):
    # run_playable explicitly prepares suite='stage1'. suites.get imports stage3
    # only in the distinct name == 'stage3' branch. Keep every other producer file.
    return {k: v for k, v in values.items() if not k.startswith(STAGE3_PREFIX)}

def producer_drift(before, after):
    return {k: {'before': before.get(k), 'after': after.get(k)}
            for k in sorted(set(before) | set(after)) if before.get(k) != after.get(k)}

def production():
    """Full formal Python pipeline and adapters, including native driver assets."""
    result = {}
    for rel in ('pipeline', 'engine_adapters'):
        for name, value in files(BENCH / rel).items():
            result[f'{rel}/{name}'] = value
    for rel in ('pipeline/eval/stage1/recovery_support.py', 'pipeline/eval/stage1/playable_support.py',
                'scripts/eval/_common.py', 'scripts/eval/config/models.json'):
        result[rel] = sha256(BENCH / rel)
    return result

def archive_producer(root, values):
    blobs = root / META / 'producer_blobs'
    blobs.mkdir(parents=True, exist_ok=True)
    for rel, expected in values.items():
        dest = blobs / expected
        if not dest.exists():
            raw = (BENCH / rel).read_bytes()
            require(hashlib.sha256(raw).hexdigest() == expected, f'producer changed during archive: {rel}')
            # Publish complete bytes atomically: another lane must never observe
            # a destination created by open('xb') before its write finishes.
            fd, temporary = tempfile.mkstemp(prefix='.producer-', dir=blobs)
            try:
                with os.fdopen(fd, 'wb') as f:
                    f.write(raw)
                    f.flush()
                    os.fsync(f.fileno())
                try:
                    os.link(temporary, dest)
                except FileExistsError:
                    pass  # A competing writer published; verify its exact hash below.
            finally:
                Path(temporary).unlink()
        require(sha256(dest) == expected, f'producer archive corrupt: {rel}')

def selection(t):
    path = Path(t['source'])
    require(path.is_absolute() and path.is_file(), 'selection receipt missing')
    s = read_json(path)
    require(s['target'] == t, 'scope / selection identity mismatch')
    if 'full_project_manifest' in s:
        receipt = path.parent / 'receipt.json'
        require(sha256(receipt) == PRIORITY_RECEIPT_SHA, 'priority receipt SHA changed')
        refs = read_json(receipt)['selected']
        require(any(x['case'] == t['case'] and x['receipt'] == str(path)
                    and x['sha256'] == sha256(path) for x in refs), 'priority selection SHA changed')
    else:
        scope = path.parent.parent / 'scope.json'
        require(sha256(scope) == FULL_SCOPE_SHA, 'full60 scope SHA changed')
        data = read_json(scope)
        require(data['targets']['sha256'] == FULL_SHA, 'full60 targets binding mismatch')
        require(any(x['case'] == t['case'] and x['path'] == str(path)
                    and x['sha256'] == sha256(path) for x in data['selections']), 'full60 selection SHA changed')
    return s

def is_exact_g043(t):
    return all(t.get(k) == v for k, v in G043_IDENTITY.items())

def blocked_reason(t, s):
    selected = {'SELECTED', 'SELECTED_ORIGINAL_PROJECT',
                'SELECTED_ORIGINAL_PROJECT_DECLARED_SCENE_MISSING',
                'SELECTED_INCOMPLETE_ORIGINAL_PROJECT'}
    if s.get('status') not in selected:
        return f'SOURCE_BLOCKED: {s.get("status")}: see immutable selection receipt'
    if not t.get('project') or not Path(t['project']).is_dir():
        return 'SOURCE_BLOCKED: selected original project unavailable; no older fallback'
    # Only the frozen G043 source has a reviewed native two-client adapter.
    # Every other pair remains fail-closed; a generic pair API or two windows
    # cannot qualify the authored multiplayer requirement.
    if t['required_real_clients'] > 1:
        if is_exact_g043(t):
            from pipeline.eval.stage1 import dual_client_kimi
            dual_client_kimi.review_target(t)
        else:
            return PAIR_PENDING_REASON
    if t.get('blocked_reason') or s.get('blocked_reason'):
        return str(t.get('blocked_reason') or s['blocked_reason'])
    return None

def requirement_fields(path):
    result = {}
    for line in Path(path).read_text().splitlines():
        key, sep, value = line.partition(':')
        if sep and key.strip() in ('engine', 'required_real_clients'):
            result[key.strip()] = value.strip()
    return result

def engine_deviation(t, s):
    req = s.get('requirements', {}).get('current', s.get('requirement'))
    actual = requirement_fields(req['path'])['engine'].replace('-', '_')
    if actual == t['engine']:
        return None
    require(t['case'] == 'G010' and t['engine'] == 'godot' and actual == 'unity3d',
            'unapproved actual/required engine mismatch')
    require(any(x.get('kind') == 'ACTUAL_ENGINE_DIFFERS_FROM_REQUIREMENT'
                and x.get('actual') == 'godot' and x.get('required') == 'unity3d'
                for x in s.get('diagnostics', [])), 'missing frozen engine deviation evidence')
    return {'policy': 'authored_engine_playable_only.v1', 'expected': 'unity3d', 'actual': 'godot',
            'selection_path': t['source'], 'selection_sha256': sha256(Path(t['source']))}

def source_binding(t, s):
    priority = 'full_project_manifest' in s
    ref = ({'path': s['full_project_manifest'], 'sha256': s['full_project_manifest_sha256']}
           if priority else s['source_manifest'])
    path = Path(ref['path'])
    require(sha256(path) == ref['sha256'], 'source manifest SHA mismatch')
    m = read_json(path)
    require(m.get('all_project_files_no_exclusion') is True if priority else
            m.get('schema') == 'kimi-selected-source-manifest.v1' and m.get('exclusions') == [],
            'incomplete source manifest')
    require(m.get('hash_algorithm') == 'sha256', 'unsupported source hash algorithm')
    require(priority or m.get('file_count') == len(m['files']), 'source manifest file count mismatch')
    require(Path(m['project']).resolve() == Path(t['project']).resolve(), 'source project mismatch')
    inventory = source_inventory(Path(t['project']))
    require(inventory == {'files': m['files'], 'symlinks': m.get('symlinks', {})}, 'frozen original source SHA drift')
    # Formal prepare ignores node_modules. Other source links need an explicit
    # runtime policy; copying through them could open external author content.
    require(all(Path(x).parts[0] == 'node_modules' for x in inventory['symlinks']),
            'source symlink outside excluded node_modules requires explicit runtime binding')
    req = s['requirement'] if priority else s['requirements']['current']
    require(sha256(Path(req['path'])) == req['sha256'], 'selected requirement changed')
    require(sha256(common.SAMPLES / t['game_id'] / 'general_requirement.txt') == req['sha256'],
            'formal requirement differs from selection')
    fields = requirement_fields(req['path'])
    require(int(fields['required_real_clients']) == t['required_real_clients'], 'requirement client mismatch')
    original = req if priority else s['requirements']['original_case_input']
    if original is not None:
        require(sha256(Path(original['path'])) == original['sha256'], 'original requirement changed')
        require(original['sha256'] == req['sha256'], 'original/current requirement drift')
    for p in s.get('provenance_files', []):
        require(sha256(Path(p['path'])) == p['sha256'], 'original provenance changed')
    entry = Path(t['entry'])
    require(not entry.is_absolute() and '..' not in entry.parts and (Path(t['project']) / entry).is_file(), 'invalid author entry')
    binding = {'selection_path': t['source'], 'selection_sha256': sha256(Path(t['source'])),
               'manifest_path': str(path), 'manifest_sha256': sha256(path),
               'source_digest': digest(m['files']), 'requirement_sha256': req['sha256'],
               'source_bytes': sum((Path(t['project']) / p).stat().st_size for p in m['files'])}
    if not priority:
        binding.update(selection_status=s['status'], original_requirement=original,
                       source_symlinks=inventory['symlinks'], engine_deviation=engine_deviation(t, s),
                       source_links_policy='literal-readlink; node_modules excluded by formal prepare; shared adapter bound in producer')
    return binding

def legacy_lineage(t):
    """Retain the old173 scope and this identity's old evidence without parsing it."""
    old = formal.result_dir(OLD_ROOT, t)
    return {'old173_targets_path': str(formal.TARGETS), 'old173_targets_sha256': sha256(formal.TARGETS),
            'old_out': str(old), 'old_files': files(old, skip=('input/project', 'runtime/project')) if old.is_dir() else {},
            'reuse_old_score': False}

def evidence_files(out):
    return files(out, skip=('input/project', 'runtime/project', META))

def isolation_proof(pipeline_bytes, suites_bytes):
    """Parse historical producers as data; never execute their snapshots."""
    pipeline_ast = ast.parse(pipeline_bytes)
    functions = [n for n in pipeline_ast.body if isinstance(n, ast.FunctionDef) and n.name == 'run_playable']
    require(len(functions) == 1, 'ambiguous playable entry')
    calls = [n for n in ast.walk(functions[0]) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute) and n.func.attr == 'prepare']
    require(len(calls) == 1 and any(k.arg == 'suite' and isinstance(k.value, ast.Constant)
            and k.value.value == 'stage1' for k in calls[0].keywords), 'playable suite is not fixed stage1')
    suites_ast = ast.parse(suites_bytes)
    branches = [n for n in ast.walk(suites_ast) if isinstance(n, ast.If)
                and ast.dump(n.test) == ast.dump(ast.parse("name == 'stage3'", mode='eval').body)]
    imports = [n for n in ast.walk(suites_ast) if isinstance(n, ast.ImportFrom)
               and 'stage3' in (n.module or '').split('.')]
    require(len(branches) == 1 and len(imports) == 1 and imports[0] in list(ast.walk(branches[0])),
            'Stage3 dependency not isolated to lazy branch')
    require(not any(isinstance(n, ast.Import) and any('stage3' in a.name.split('.') for a in n.names)
                    for n in ast.walk(suites_ast)), 'eager Stage3 dependency')
    return {'suite': 'stage1', 'pipeline_sha256': hashlib.sha256(pipeline_bytes).hexdigest(),
            'suites_sha256': hashlib.sha256(suites_bytes).hexdigest(),
            'policy': 'run_playable fixed stage1; suites stage3 import only in name==stage3 branch'}

def _g022_record_ast_compatibility(recorded_bytes, current_bytes):
    """Data-only comparison of the entire module after two reviewed Unity additions.

    This structural check is used only behind exact byte/receipt pins below.
    It does not import or execute either historical or current record.py.
    """
    old, new = ast.parse(recorded_bytes), ast.parse(current_bytes)
    dump = lambda node: ast.dump(node, include_attributes=False)
    helpers = [n for n in new.body if isinstance(n, ast.FunctionDef)
               and n.name == '_unity_input_metadata']
    require(len(helpers) == 1 and not any(isinstance(n, ast.FunctionDef)
            and n.name == '_unity_input_metadata' for n in old.body),
            'G022 compatibility: unexpected Unity helper set')
    helper = helpers[0]
    require(not helper.decorator_list and not helper.args.defaults
            and not any(helper.args.kw_defaults),
            'G022 compatibility: helper has import-time execution')
    new.body.remove(helper)
    records = [n for n in new.body if isinstance(n, ast.FunctionDef) and n.name == '_record']
    require(len(records) == 1, 'G022 compatibility: ambiguous record entry')
    unity_test = dump(ast.parse("engine == 'unity3d'", mode='eval').body)
    branches = [n for n in records[0].body if isinstance(n, ast.If) and dump(n.test) == unity_test]
    require(len(branches) == 1, 'G022 compatibility: missing exact Unity guard')
    expected = ast.parse(
        "metadata = _unity_input_metadata(out, manifest, choice, prep_deadline)\n"
        "if metadata is not None:\n"
        "    write_json(runtime / 'unity_input_metadata.json', metadata)\n").body
    tries = [n for n in branches[0].body if isinstance(n, ast.Try)
             and [dump(s) for s in n.body[:2]] == [dump(s) for s in expected]]
    require(len(tries) == 1, 'G022 compatibility: metadata call escaped reviewed guard')
    del tries[0].body[:2]
    require(dump(old) == dump(new), 'G022 compatibility: other module/Godot path drift')
    return {'policy': 'g022-exact-unity-metadata-addition-ast.v1',
            'normalized_module_ast_sha256': hashlib.sha256(dump(old).encode()).hexdigest(),
            'scope': 'whole module equality after only added helper and Unity-guarded statements removed'}

def _g022_record_metadata_compatibility(recorded_bytes, current_bytes, receipt_bytes):
    """Sealed G022 proof only; no general permission for subsequent producer drift."""
    require(hashlib.sha256(recorded_bytes).hexdigest() ==
            '3d61db64d19f3123d65cca561944052a3ef33d6b416526edd6fd5deefdbdedfb',
            'G022 compatibility: unreviewed recorded record.py')
    require(hashlib.sha256(current_bytes).hexdigest() ==
            '261cc9dbb445564df303c197734aa4d640b3ae639e145c8a585b3d15fb30f7bf',
            'G022 compatibility: unreviewed current record.py')
    require(hashlib.sha256(receipt_bytes).hexdigest() ==
            'a3ea61cedd595456c4cc9d29f69be49e80f339dd8838397338f47ca21fbe0271',
            'G022 compatibility: sealed receipt changed or absent')
    return _g022_record_ast_compatibility(recorded_bytes, current_bytes)

def stage3_recovery_proof(out, t):
    """Only the already recorded G022 smoke, with its one exact unrelated drift."""
    from pipeline.eval.repair.godot_duration_recovery import native_evidence
    root, m = out.parents[2], out / META
    require(root.resolve() == ROOT.resolve() and t['case'] == 'G022'
            and t['game_id'] == 'G022_isle_comm_nodes' and t['required_real_clients'] == 1,
            'offline recovery restricted to original G022 smoke')
    claim = read_json(m / 'attempt.json')
    require(claim['target'] == t and claim['scope_sha256'] == PRIORITY_SHA, 'wrong original smoke claim')
    require(claim['max_takes'] == 2 and claim['models'] == MODELS, 'original limits changed')
    auth = root / META / 'authorization.json'
    require(read_json(auth) == authorization() and sha256(auth) == claim['authorization_sha256'], 'authorization drift')
    frozen = root / META / 'scopes' / (claim['scope_sha256'] + '.json')
    require(sha256(frozen) == claim['scope_sha256'] and t in read_json(frozen)['targets'], 'scope drift')
    require(source_binding(t, selection(t)) == claim['source'], 'original source drift')
    require(read_json(m / 'failure.json')['error'] ==
            'producer drift during formal run; evidence retained, qualification held', 'different failure')
    require(read_json(m / 'status.json')['state'] == 'FAILED_NO_AUTOMATIC_RETRY', 'parent status changed')
    manifest = read_json(out / 'manifest.json')
    require(manifest['suite'] == 'stage1' and manifest['delivery']['stage'] == 'stage1'
            and manifest['game_id'] == t['game_id'] and manifest['engine'] == 'godot'
            and manifest['delivery']['project_root'] == t['project'], 'recorded manifest identity/suite mismatch')
    before = read_json(m / 'producer_start.json')['files']
    after = read_json(m / 'producer_end.json')['files']
    drift = producer_drift(before, after)
    expected = {STAGE3_PREFIX + 'metrics.py': {
        'before': 'c4272befa9e97bd51c77cd1599bd1649d710ff450e487d254d94c388bb2bd0b5',
        'after': 'bf87a10325f4e04b3918f8019ac9b7e2a269b84fa38a75329f2d96b1bed64c6a'}}
    require(drift == expected and producer_closure(before) == producer_closure(after), 'not exact isolated Stage3 drift')
    blobs = root / META / 'producer_blobs'
    for value in set(before.values()) | set(after.values()):
        require(sha256(blobs / value) == value, 'recorded producer archive corrupt')
    prefix = 'pipeline/eval/stage1/'
    isolation = isolation_proof((blobs / before[prefix + 'pipeline.py']).read_bytes(),
                                (blobs / before[prefix + 'suites.py']).read_bytes())
    # Scoring and native verification dependencies retain the actual recorded bytes.
    stable = [prefix + name for name in ('playable_rules.py', 'record.py', 'native_log.py',
                                        'godot_duration_recovery.py', 'paths.py')]
    for name in stable:
        if name == prefix + 'record.py' and sha256(BENCH / name) != before[name]:
            # Only the already sealed G022 receipt and reviewed Unity-only delta.
            # The native provenance and returned proof remain byte-for-byte bound.
            _g022_record_metadata_compatibility(
                (blobs / before[name]).read_bytes(), (BENCH / name).read_bytes(),
                (m / RECOVERY / 'receipt.json').read_bytes())
        else:
            require(sha256(BENCH / name) == before[name], f'record/scoring dependency changed: {name}')
    require({p.name for p in (out / 'takes').iterdir() if p.is_dir()} == {'1', '2'}, 'unexpected take set')
    native = [native_evidence(out, i, full_window=True) for i in (1, 2)]
    score = formal.completed_score(out, t)
    require(score is not None, 'formal scoring rejected recorded evidence')
    return {'target': t, 'parent_files': files(m, skip=('recovery',)),
            'evidence_files': evidence_files(out), 'source': claim['source'],
            'recorded_producer_drift': drift, 'isolation': isolation, 'native': native,
            'score': score, 'native_calls': 0, 'model_calls': 0, 'additional_takes': 0}

def qualified_stage3_recovery(out, t):
    try:
        receipt = read_json(out / META / RECOVERY / 'receipt.json')
        require(receipt['qualified'] is True and receipt['proof'] == stage3_recovery_proof(out, t),
                'offline recovery proof changed')
        for value in set(receipt['finalization_producer_files'].values()):
            require(sha256(out.parents[2] / META / 'producer_blobs' / value) == value,
                    'finalization producer archive corrupt')
        return receipt['proof']['score']
    except (OSError, ValueError, KeyError, TypeError, RuntimeError):
        return None

def finalize_stage3_drift(out):
    out = Path(out).resolve()
    require(out.parents[2] == ROOT.resolve(), 'foreign finalization root')
    t = read_json(out / META / 'attempt.json')['target']
    with locked(ROOT / META / 'locks' / (t['case'] + '.lock')):
        path = out / META / RECOVERY / 'receipt.json'
        if path.exists():
            score = qualified_stage3_recovery(out, t)
            require(score is not None, 'existing offline receipt rejected; do not overwrite')
            return score
        producer = production()
        archive_producer(ROOT, producer)
        proof = stage3_recovery_proof(out, t)
        require(production() == producer, 'finalization producer changed during offline verification')
        write(path, {'version': 'kimi-stage3-drift-offline-finalization.v1', 'qualified': True,
                     'at': now(), 'proof': proof, 'finalization_producer_files': producer,
                     'producer_roles': 'recorded producer_start/end are native provenance; current producer is offline finalizer only'},
              exclusive=True)
        score = qualified_stage3_recovery(out, t)
        require(score is not None, 'offline receipt verification rejected')
        return score

G043_EPOCH_FAILURE_SHA = '85655557b34bf294a70ca4a6ea12f1a886ae7c65baf0f8c91c3626affdb877f5'

def qualified_g043_epoch_recovery(out, t):
    """Read-only batch admission for the exact preserved G043 take1 failure.

    Historical full producer bytes remain authoritative for the original run;
    the formal pair gate independently verifies the narrow finalizer closure.
    Neither canonical score nor a recovery receipt alone establishes completion.
    """
    require(is_exact_g043(t), 'epoch recovery is only authorized for Kimi G043')
    root, m = out.parents[2], out / META
    require(out.resolve() == formal.result_dir(root, t).resolve(), 'foreign pair result path')
    recovery = out / 'recovery/epoch_serialization_v1'
    require(not recovery.is_symlink(), 'linked recovery')
    receipt = read_json(recovery / 'receipt.json')
    archive = receipt['archive_sha256']
    required = ('attempt.json', 'failure.json', 'producer_start.json', 'producer_end.json',
                'blocked.json', 'pair_preflight_release.json')
    for name in required:
        rel = META + '/' + name
        saved = recovery / 'before' / rel
        require(not saved.is_symlink() and not (m / name).is_symlink()
                and sha256(saved) == sha256(m / name) == archive[rel], 'parent batch archive changed')
    require(sha256(m / 'failure.json') == G043_EPOCH_FAILURE_SHA,
            'not the reviewed G043 epoch failure')
    require(receipt['parent_pair_sha256'] ==
            '8d235c65e1c22d889b5a0c6d2f5acfbd4e45b209678a318ec629b1e105b2a4c9',
            'not the reviewed G043 native pair')
    claim = read_json(m / 'attempt.json')
    require(claim['version'] == VERSION and claim['target'] == t
            and claim['scope_sha256'] == FULL_SHA and claim['models'] == MODELS
            and claim['max_takes'] == 2, 'original pair claim changed')
    auth = root / META / 'authorization.json'
    require(read_json(auth) == authorization()
            and sha256(auth) == claim['authorization_sha256'], 'authorization changed')
    frozen = root / META / 'scopes' / (FULL_SHA + '.json')
    require(sha256(frozen) == FULL_SHA and t in read_json(frozen)['targets'], 'scope changed')
    require(source_binding(t, selection(t)) == claim['source'], 'source binding changed')
    start = read_json(m / 'producer_start.json')['files']
    end = read_json(m / 'producer_end.json')['files']
    require(start and start == end, 'original pair producer drift')
    for digest in set(start.values()):
        blob = root / META / 'producer_blobs' / digest
        require(not blob.is_symlink() and sha256(blob) == digest, 'batch producer archive changed')
    release_path = m / 'pair_preflight_release.json'
    release = read_json(release_path)
    require(sha256(release_path) == claim['pair_preflight_release_sha256']
            and release['schema'] == 'stage1-kimi-pair-preflight-release.v1'
            and release['mode'] == 'resume_zero_call_preclaim_admission'
            and release['target'] == t and release['scope_sha256'] == FULL_SHA
            and release['blocked_sha256'] == release['blocked_bytes_sha256']
                == sha256(m / 'blocked.json') == G043_BLOCK_SHA
            and release['blocked_native_calls'] == 0 and release['blocked_model_calls'] == 0
            and release['producer_files'] == start and release['source'] == claim['source'],
            'zero-call preflight release changed')
    pair = out / 'takes/take_01/pair'
    native = read_json(pair / 'producer_start.json')
    require(native and native == read_json(pair / 'producer_end.json')
            and all(start.get(name) == digest for name, digest in native.items()),
            'native producer differs from original batch')
    key = 'pipeline/eval/stage1/dual_client_kimi.py'
    require(release['reviewed_adapter_sha256'] == native[key]
            and receipt['producer'][key] ==
                'd2c0a6943c1434cabeb4a28cc3a42faeff287fe8bb324cf974684d8d81283ffb',
            'unreviewed pair finalizer')
    from pipeline.eval.stage1 import dual_client_kimi
    # Checks recovery claim/budgets/archive, original source, both native clients,
    # retained evidence, KEEP_PROJECTS cleanup and the final completion seal.
    return dual_client_kimi.qualified_completion_score(out)

def completed_score(out, t):
    """Fail closed on lineage, source, producer archive and every retained evidence byte."""
    try:
        root = out.parents[2]
        require(root.resolve() == ROOT.resolve(), 'foreign result root')
        m = out / META
        if (out / 'recovery/kimi_builder_v1').exists() or (out / 'recovery/kimi_builder_v1').is_symlink():
            require(t.get('model') == 'Kimi' and t.get('case') == 'G009'
                    and t.get('game_id') == 'G009_blackout_stealth' and t.get('engine') == 'unity3d'
                    and t.get('required_real_clients') == 1, 'Kimi builder recovery identity differs')
            require(read_json(m / 'attempt.json')['target'] == t, 'Kimi builder recovery target changed')
            from pipeline.eval.repair.unity_g009_builder_recovery import qualified_replacement_score
            return qualified_replacement_score(out)
        g025_recovery = out / 'recovery/ue_ui_take2_v1'
        if g025_recovery.exists() or g025_recovery.is_symlink():
            require(t.get('model') == 'Kimi' and t.get('case') == 'G025'
                    and t.get('game_id') == 'G025_broken_continent_rts' and t.get('engine') == 'ue5'
                    and t.get('entry') == 'BrokenContinentRTS.uproject' and t.get('required_real_clients') == 1,
                    'G025 take2 recovery identity differs')
            require(read_json(m / 'attempt.json')['target'] == t, 'G025 target changed')
            from pipeline.eval.repair.ue_g025_take2_recovery import qualified_replacement_score
            return qualified_replacement_score(out)
        ue_target_recovery = out / 'recovery/ue_editor_target_v1'
        if ue_target_recovery.exists() or ue_target_recovery.is_symlink():
            require(t.get('model') == 'Kimi' and t.get('case') == 'G035'
                    and t.get('game_id') == 'G035_rift_expedition' and t.get('engine') == 'ue5'
                    and t.get('entry') == 'G035RiftExpedition.uproject' and t.get('required_real_clients') == 1,
                    'UE target recovery identity differs')
            require(read_json(m / 'attempt.json')['target'] == t, 'UE target recovery target changed')
            from pipeline.eval.repair.ue_g035_target_recovery import qualified_replacement_score
            return qualified_replacement_score(out)
        ue_recovery = out / 'recovery/ue_missing_recorder_v1'
        if ue_recovery.exists() or ue_recovery.is_symlink():
            require(t.get('model') == 'Kimi' and t.get('case') == 'G020'
                    and t.get('game_id') == 'G020_tidal_glyphs' and t.get('engine') == 'ue5'
                    and t.get('entry') == 'TidalGlyphs.uproject' and t.get('required_real_clients') == 1,
                    'UE admission recovery identity differs')
            require(read_json(m / 'attempt.json')['target'] == t, 'UE recovery target changed')
            from pipeline.eval.repair.ue_g020_admission_recovery import qualified_replacement_score
            return qualified_replacement_score(out)
        if (out / 'recovery/web_readiness_v1').exists():
            require(t.get('model') == 'Kimi' and t.get('case') in {'G041', 'G042'}
                    and t.get('engine') == 'three_js' and t.get('required_real_clients') == 1,
                    'configured Vite recovery identity differs')
            require(read_json(m / 'attempt.json')['target'] == t, 'web recovery target changed')
            from pipeline.eval.repair.web_readiness_recovery import qualified_replacement_score
            return qualified_replacement_score(out)
        if (out / 'recovery/tuanjie_scene_v1').exists():
            require(t['model'] == 'Kimi' and t['case'] == 'G004'
                    and t['game_id'] == 'G004_desert_observatory'
                    and t['engine'] == 'unity3d' and t['required_real_clients'] == 1,
                    'authored-scene recovery identity differs')
            require(read_json(m / 'attempt.json')['target'] == t, 'recovery target changed')
            from pipeline.eval.repair.unity_authored_scene_recovery import qualified_replacement_score
            return qualified_replacement_score(out)
        if (out / 'recovery/epoch_serialization_v1').exists():
            return qualified_g043_epoch_recovery(out, t)
        if (m / RECOVERY / 'receipt.json').is_file():
            return qualified_stage3_recovery(out, t)
        require(not (m / 'failure.json').exists(), 'failed attempt requires explicit recovery')
        receipt = read_json(m / 'completion.json')
        claim = read_json(m / 'attempt.json')
        require(receipt['qualified'] is True and claim['target'] == t, 'unqualified identity')
        require(receipt['attempt_sha256'] == sha256(m / 'attempt.json'), 'attempt changed')
        if 'pair_preflight_release_sha256' in claim:
            release = m / 'pair_preflight_release.json'
            require(sha256(release) == claim['pair_preflight_release_sha256'], 'pair release changed')
            released = read_json(release)
            require(released['target'] == t and released['scope_sha256'] == claim['scope_sha256']
                    and released['blocked_sha256'] == sha256(m / 'blocked.json') == G043_BLOCK_SHA
                    and released['producer_files'] == read_json(m / 'producer_start.json')['files']
                    and released['source'] == claim['source'], 'pair release binding changed')
        require(read_json(root / META / 'authorization.json') == authorization(), 'authorization changed')
        require(claim['authorization_sha256'] == sha256(root / META / 'authorization.json'), 'authorization binding changed')
        frozen = root / META / 'scopes' / (claim['scope_sha256'] + '.json')
        require(sha256(frozen) == claim['scope_sha256'] and t in read_json(frozen)['targets'], 'scope binding changed')
        require(source_binding(t, selection(t)) == claim['source'], 'source binding changed')
        snapshots = {}
        for phase in ('producer_start.json', 'producer_end.json'):
            snapshots[phase] = read_json(m / phase)['files']
            if receipt.get('producer_policy') == PRODUCER_POLICY:
                require(sha256(m / phase) == receipt['producer_snapshot_sha256'][phase], 'producer snapshot changed')
                require(producer_closure(snapshots[phase]) == receipt['producer_closure_files'], 'Stage1 producer drift')
            else:
                require(snapshots[phase] == receipt['producer_files'], 'producer drift during run')
        for value in {v for values in snapshots.values() for v in values.values()}:
            require(sha256(root / META / 'producer_blobs' / value) == value, 'producer archive changed')
        require(evidence_files(out) == receipt['evidence_files'], 'retained evidence changed')
        score = formal.completed_score(out, t)
        require(score is not None and score == receipt['score'], 'formal completion rejected')
        return score
    except (OSError, ValueError, KeyError, TypeError, RuntimeError):
        return None

def shim(root, t):
    run = root / META / 'deliveries' / t['game_id'] / 'kimi_all_20261109'
    deviation = engine_deviation(t, selection(t))
    write(run / 'delivery.json', {
        'schema': DELIVERY_SCHEMA, 'stage': 'stage1', 'game_id': t['game_id'],
        'model': 'kimi', 'run_id': run.name, 'engine': t['engine'], 'project_root': t['project'],
        'entry': t['entry'], 'required_real_clients': t['required_real_clients'], 'created_at': now(),
        'generator': {'kind': 'legacy', 'agent': 'Kimi', 'framework_used': True},
        'legacy': True, 'source_of_selection': t['source'],
        **({'engine_deviation': deviation} if deviation else {}),
    }, exclusive=True)
    return run
