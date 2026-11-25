"""Exact-path, post-publication Godot/Three.js cache reclamation.

This deliberately supports the explicit native v2 pending-publication contract,
not arbitrary historical scores. No author/input copy, complete project, evidence,
or cache used by a saved reference is removed. Audit is NOT a prerequisite.
Call run(..., apply=True) immediately after publication; all seven locks and all
source/process/reference checks are acquired here, never inherited by assumption.
"""
from contextlib import ExitStack
from pathlib import Path
import argparse
import fcntl
import json
import math
import os
import re
import shutil
import stat
import time

from .protocol import COLUMNS, checked_path, dump, sha

VERSION = 'whitebox-native-scored-cache.v1'
TABLES = ('scores.md', 'score_new.md', 'score_verify.md', 'final_report.md')
INVENTORY_VERSION = VERSION + '.file-inventory'
# Scheduling bounds only: exceeding any bound keeps every candidate intact.
# Oversized metadata is an explicit incomplete scan, never an exempt source.
MAX_REFERENCE_FILE_BYTES = 64 * 1024**2
MAX_REFERENCE_LINE_CHARS = 8 * 1024**2
REFERENCE_SCAN_SECONDS = 60


class ReferenceScanDeferred(ValueError):
    pass

CACHE_NAMES = {'godot': ('.godot/imported', '.godot/shader_cache'),
               'three_js': ('node_modules',)}
FORBIDDEN = {'gamefactory3a', 'evidence', 'frames', 'model_calls', 'train_data',
             'validation', 'editor.log', 'player.log', 'frame_index.json',
             'frame_index.jsonl', 'action_frame_links.json', 'state.jsonl',
             'events.jsonl', 'actions.jsonl', 'verification.json', 'runner_exit.json'}


def read(path):
    return json.loads(Path(path).read_text())


def locks(batch):
    config = read(batch/'native_capture_configuration.json')
    control = Path(config['control_root']).resolve()
    expected = [control/'whitebox_production_queue.lock',
                *[control/f'serial_{i}.lock' for i in range(3)],
                Path('/tmp/gamefactory-native-playtest-gui.lock')]
    if (config['outer_execution_locks'] != list(map(str, expected))
            or config['runtime_owned_gui_lock'] != '/tmp/gamefactory-sol-whitebox-gui.lock'):
        raise ValueError('Unrecognized native seven-lock configuration')
    return control, expected + [Path(config['runtime_owned_gui_lock']), batch/'.targeted_publication.lock']


def qualified_score(batch, attempt):
    from . import batch as evaluator, core12, pending_publication as publication
    batch, attempt = Path(batch).resolve(), Path(attempt).resolve()
    if attempt.parent.name not in {'runs', 'recovery_runs'} or attempt.parent.parent != batch:
        raise ValueError('Exact native batch attempt required')
    manifest = read(attempt/'input_manifest.json')
    entry = manifest['entry']; engine = entry.get('actual_engine')
    if engine not in CACHE_NAMES:
        raise ValueError('Not a supported native engine')
    evaluator.verify_inputs(attempt)
    proto = core12.verify_attempt(attempt, engine)
    if proto.get('scoring_policy', {}).get('version') != 'whitebox-mechanic10-50-100.v2':
        raise ValueError('Frozen native v2 scoring protocol required')
    if publication.authorized_native_scope(batch, entry, proto, attempt=attempt) is None:
        raise ValueError('Explicit frozen native publication scope required')
    score = read(attempt/'scores.json')
    numeric = lambda v: type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 100
    values = [score.get('columns', {}).get(c, {}).get('score') for c in COLUMNS]
    if (score.get('valid') is not True or set(score.get('columns', {})) != set(COLUMNS)
            or score.get('scoring_protocol') != 'whitebox-mechanic10-50-100.v2'
            or not all(numeric(v) for v in values) or not numeric(score.get('overall_score'))
            or abs(sum(values)/8 - score['overall_score']) > .011
            or read(attempt/'status.json').get('status') not in {'JUDGED', 'COMPLETE'}
            or any((attempt/name).exists() for name in ('harness_error.json', 'take_invalidated.json'))):
        raise ValueError('Complete valid eight-column native judgment required')
    record = publication.authorized_pending(attempt, batch, score, entry)
    if (not record or record.get('columns') != score['columns']
            or set(record.get('rows', {})) != set(TABLES)
            or read(attempt/'pending_publication_receipt.json') != record):
        raise ValueError('All four persisted publication rows and exact source receipt required')
    for name, digest in record.get('source_bindings', {}).items():
        if sha(checked_path(attempt, name)) != digest:
            raise ValueError('Publication source binding changed: '+name)
    required = {'input_manifest.json', 'input/pilot_rubric.json', 'rubric_verdicts.json',
                'evidence_manifest.json', 'status.json'}
    if not required <= record.get('source_bindings', {}).keys():
        raise ValueError('Incomplete publication source bindings')
    cleanup, origin = publication.cleanup_source(attempt)
    if (not cleanup or any(record['source_bindings'].get(k) != v for k, v in cleanup.items())
            or record.get('cleanup_source') != origin):
        raise ValueError('Unchanged real input/view/process cleanup required')
    return {'case': entry['id'], 'engine': engine, 'attempt': str(attempt),
            'score_sha256': sha(attempt/'scores.json'),
            'publication_sha256': sha(attempt/'pending_publication_receipt.json'),
            'source_bindings': record['source_bindings'], 'cleanup_bindings': cleanup,
            'table_sha256': {name: sha(batch/name) for name in TABLES}}


def candidate_paths(attempt, engine):
    """Only the published attempt's isolated runtime caches, never its input."""
    project = Path(attempt)/'runtime/project'
    result = []
    for name in CACHE_NAMES[engine]:
        path = project/name
        if path.exists() or path.is_symlink():
            if path.is_symlink() or path.resolve() != path.absolute() or not path.is_dir():
                raise ValueError('Noncanonical/symlink cache path: '+str(path))
            result.append(path)
    return result


def regeneration_proof(attempt, path, engine):
    from . import batch as evaluator
    project = Path(attempt)/'runtime/project'
    # Cache deletion must not hide any changed or missing delivered source.
    frozen = read(Path(attempt)/'input_manifest.json')['snapshot_hashes']
    if not isinstance(frozen, dict) or not frozen:
        raise ValueError('Nonempty frozen authored source inventory required')
    current = evaluator.hashes(project)
    if any(current.get(name) != digest for name, digest in frozen.items()):
        raise ValueError('Runtime authored sources changed; retain cache')
    if engine == 'godot':
        marker = project/'project.godot'
        if not marker.is_file() or path.relative_to(project).as_posix() not in CACHE_NAMES[engine]:
            raise ValueError('Godot imported/shader cache is not bound to its source project')
        return {'generator': 'Godot native import/shader regeneration',
                'project_marker_sha256': sha(marker), 'unchanged_source_count': len(frozen)}
    package, lock = project/'package.json', project/'package-lock.json'
    package_value, lock_value = read(package), read(lock)
    if lock_value.get('lockfileVersion') not in (2, 3) or not isinstance(lock_value.get('packages'), dict):
        raise ValueError('Reproducible npm package lock required')
    packages = lock_value['packages']; root = packages.get('', {})
    if not packages or not isinstance(root, dict):
        raise ValueError('Nonempty npm packages/root lock required')
    for kind in ('dependencies', 'devDependencies', 'optionalDependencies'):
        if package_value.get(kind, {}) != root.get(kind, {}):
            raise ValueError('npm root dependencies differ from retained lock')
    installed = []
    for name, spec in packages.items():
        if not name:
            continue
        if (not isinstance(spec, dict) or not name.startswith('node_modules/') or '..' in Path(name).parts
                or spec.get('link') or not spec.get('version')
                or not spec.get('integrity') or not str(spec.get('resolved', '')).startswith('https://')):
            raise ValueError('Unreproducible/local dependency in npm lock: '+name)
        marker = project/name/'package.json'
        if marker.exists():
            if read(marker).get('version') != spec['version']:
                raise ValueError('Installed dependency differs from retained lock: '+name)
            installed.append(name)
    # Unlocked injected packages are not regenerable under this proof.
    for folder, dirs, files in os.walk(path, followlinks=False, onerror=walk_error):
        dirs.sort(); files.sort()
        dirs[:] = [d for d in dirs if not (Path(folder)/d).is_symlink()]
        if Path(folder).name == 'node_modules':
            for item in Path(folder).iterdir():
                if item.name == '.package-lock.json' and item.is_file() and not item.is_symlink():
                    continue
                if item.name == '.bin' and item.is_dir() and not item.is_symlink():
                    if any(not executable.is_symlink() for executable in item.iterdir()):
                        raise ValueError('Unproven npm executable/cache contents')
                    continue
                members = list(item.iterdir()) if item.name.startswith('@') and item.is_dir() else [item]
                if not members:
                    raise ValueError('Unproven empty npm scope')
                for member in members:
                    relative = member.relative_to(project).as_posix()
                    if (relative not in packages or not member.is_dir() or member.is_symlink()
                            or not (member/'package.json').is_file()):
                        raise ValueError('Unproven/unlocked npm package root: '+str(member))
        if 'package.json' in files and (Path(folder)/'package.json').is_file():
            relative = Path(folder).relative_to(project).as_posix()
            # Package source trees can contain fixture package.json files. Only
            # actual package roots (node_modules/name or @scope/name) are bound.
            is_root = Path(folder).parent.name == 'node_modules' or (
                Path(folder).parent.name.startswith('@') and Path(folder).parent.parent.name == 'node_modules')
            if is_root and relative not in packages:
                raise ValueError('Installed package missing from npm lock: '+relative)
    return {'generator': 'npm ci from retained package-lock.json',
            'package_sha256': sha(package), 'lock_sha256': sha(lock), 'installed_packages': installed}


def file_inventory(path):
    """Keep diagnostics/evidence, external links, special files and hardlinks."""
    rows = []
    for folder, dirs, files in os.walk(path, followlinks=False, onerror=walk_error):
        dirs.sort(); files.sort()
        for name in sorted(dirs + files):
            p = Path(folder)/name; st = p.lstat()
            if (name.casefold() in FORBIDDEN
                    or p.suffix.lower() in {'.log', '.jsonl', '.mp4', '.mov', '.webm'}):
                raise ValueError('Potential evidence/diagnostic in cache: '+str(p))
            if stat.S_ISLNK(st.st_mode):
                if not p.resolve().is_relative_to(path):
                    raise ValueError('External/special symlink in cache: '+str(p))
            elif not (stat.S_ISREG(st.st_mode) or stat.S_ISDIR(st.st_mode)):
                raise ValueError('Special file in cache: '+str(p))
            if not stat.S_ISDIR(st.st_mode) and st.st_nlink != 1:
                raise ValueError('Shared hardlink in cache: '+str(p))
            rows.append({'path': str(p), 'bytes': st.st_size, 'allocated_bytes': 0 if stat.S_ISDIR(st.st_mode) else st.st_blocks*512,
                         'inode': st.st_ino, 'mtime_ns': st.st_mtime_ns,
                         'directory': stat.S_ISDIR(st.st_mode),
                         'symlink': os.readlink(p) if p.is_symlink() else None})
    return sorted(rows, key=lambda row: row['path'])


def idle_snapshot(attempt):
    from . import runtime, unity_scored_cache
    if runtime.active_gui_engines():
        raise BlockingIOError('Native engine active; cache reclamation deferred')
    snapshot = unity_scored_cache.idle_snapshot()
    # Protect browser/server/capture children even if no cache file is open yet.
    for line in snapshot['processes'].splitlines():
        fields = line.strip().split(None, 2)
        if len(fields) != 3:
            continue
        command = fields[2]
        if (str(attempt) in command and any(x in command for x in
                ('record.mjs', 'playwright', 'Chromium.app/', 'bounded_recorder', 'vite ', 'npm run'))):
            raise BlockingIOError('Owned native capture/browser/server still active')
    return snapshot


def walk_error(error):
    raise error


def reference_roots(batch, control):
    # Scan sibling batches too: a different recovery identity may bind to this
    # runtime project. Do not assume one publication batch owns every reference.
    return [batch.parent, control, Path(__file__).resolve().parents[3]/'docs']


def npm_structural_keys_only(source, path):
    """Only package-map KEYS are regeneration layout, never evidence references.

    Retain any marker in values/other keys, invalid/duplicate JSON, or unknown
    lock format. The original lock and physical lines remain unchanged.
    """
    if path.name != 'node_modules' or source.name != 'package-lock.json':
        return False
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate npm lock key')
            result[key] = value
        return result
    try:
        value = json.loads(source.read_text(), object_pairs_hook=unique_pairs)
        if value.get('lockfileVersion') not in (2, 3) or not isinstance(value.get('packages'), dict):
            return False
        packages = value['packages']
        # Replace only known layout keys in a separate in-memory view. Any
        # evidence value mentioning a cache still blocks the original file.
        value['packages'] = {('package-layout-'+str(i) if key.startswith('node_modules/') else key): spec
                             for i, (key, spec) in enumerate(packages.items())}
        remainder = json.dumps(value, ensure_ascii=False)
        return 'node_modules' not in remainder.casefold() and str(path).casefold() not in remainder.casefold()
    except (OSError, ValueError, AttributeError):
        return False



def reference_role(source, line, path, digest):
    """Classify path ownership, retaining every unresolved/explicit dependency.

    Return proof only for a demonstrably unrelated path, frozen negative author
    statement, byte-identical official tool documentation, or a completed
    zero-deletion scan's own path enumeration. Never exempt a whole directory.
    """
    marker = '.godot/'+path.name if path.parent.name == '.godot' else 'node_modules'
    tokens = [t.rstrip(':;') for t in re.findall(r'[^\s"\x27`{}\[\],]+', line) if marker in t.casefold()]
    workspace = Path(__file__).resolve().parents[3]
    own = str(path)
    project = path.parent.parent if path.parent.name == '.godot' else path.parent
    attempt = project.parent.parent
    exact = own.casefold() in line.casefold()
    if not exact and tokens:
        # node_modules.asar is a different directory component, not npm cache.
        if marker == 'node_modules' and all('node_modules' not in re.sub(r'node_modules\.asar(?:\.unpacked)?(?=/|$)', '', t)
                for t in tokens):
            return {'role': 'different_directory_component'}
        resolved = []
        for token in tokens:
            if token.startswith('/'):
                resolved.append(Path(token).resolve())
            elif token.startswith(('test_data/', 'workspaces/', 'docs/', 'GameFactory-3A/')):
                resolved.append((workspace/token).resolve())
            else:
                break
        if len(resolved) == len(tokens) and all(
                str(p).casefold() != own.casefold() and not str(p).casefold().startswith(own.casefold()+'/')
                for p in resolved):
            return {'role': 'resolved_path_to_other_project', 'resolved': list(map(str, resolved))}
        # Only this exact negative claim, SHA-bound to another author's frozen
        # document, is exempt. Merely residing in another attempt is insufficient.
        negative = 'The project has no `'+marker+'/` cache.'
        if negative in line and len(tokens) == 1:
            for parent in source.parents:
                manifest_path = parent/'input_manifest.json'
                if parent.parent.name not in {'runs', 'recovery_runs'} or not manifest_path.is_file():
                    continue
                try:
                    manifest = read(manifest_path)
                    if parent == attempt or Path(manifest['entry']['project']).resolve() == project:
                        break
                    for name, expected in manifest.get('input_hashes', {}).items():
                        if not name.endswith('/build_evidence.md'):
                            continue
                        original = checked_path(parent/'input', name)
                        if original.stat().st_size > 1024*1024 or sha(original) != expected:
                            continue
                        for author_line in original.read_text().splitlines():
                            if negative in author_line and (line.strip() == author_line.strip() or
                                    re.sub(r'^\d+:\s*', '', line.strip()) == author_line.strip()):
                                return {'role': 'frozen_foreign_project_cache_absence',
                                        'manifest': str(manifest_path), 'manifest_sha256': sha(manifest_path),
                                        'author_document': str(original), 'author_document_sha256': expected}
                except (OSError, ValueError, KeyError, TypeError):
                    pass
                break
        for relative in ('engine_adapters/godot/README.md', 'engine_adapters/godot/import_generated/README.md'):
            official = workspace/relative
            if source.as_posix().endswith('/'+relative) and official.is_file() and digest == sha(official):
                return {'role': 'byte_identical_official_adapter_documentation',
                        'official': str(official), 'official_sha256': digest}
    # A completed failed-to-delete scan records a candidate, not an input.
    # Prior SAFE_PREVIEW inventories and arbitrary embedded references stay live.
    if source.parent.parent.name == 'native_cache_reclamation':
        try:
            receipt_path = source.parent/'receipt.json'; receipt = read(receipt_path)
            same = (receipt.get('version') == VERSION and receipt.get('apply') is True
                    and receipt.get('status') == 'COMPLETE' and receipt.get('tables_unchanged') is True
                    and receipt.get('deleted_allocated_bytes') == 0
                    and receipt.get('attempt') == str(attempt)
                    and receipt.get('results') and all(r.get('status') == 'PRESERVED'
                        and r.get('deleted_allocated_bytes') == 0 for r in receipt['results']))
            if same:
                non_paths = dict(receipt, results=[{k: v for k, v in r.items() if k != 'path'}
                                                  for r in receipt['results']])
                enumeration = (source.name == 'receipt.json' and own not in json.dumps(non_paths) and
                    re.fullmatch(r'\s*"path"\s*:\s*'+re.escape(json.dumps(own))+r',?\s*', line))
                scan_key = (source.name == 'reference_scan.json' and
                    receipt.get('reference_scan_sha256') == digest and
                    re.fullmatch(r'\s*'+re.escape(json.dumps(own))+r'\s*:\s*\[\s*', line))
                if enumeration or scan_key:
                    return {'role': 'completed_zero_deletion_candidate_enumeration',
                            'receipt': str(receipt_path), 'receipt_sha256': sha(receipt_path)}
        except (OSError, ValueError, KeyError, TypeError):
            pass
    return None



def possible_reference_lines(stream, candidates, *, deadline=None):
    """Visit all text in bounded chunks; retain original physical line numbers.

    TextIO performs the same universal-newline and surrogateescape decoding as
    the former per-line loop. Only blocks provably without any cache marker
    skip per-line Python work; SHA checks still cover the complete file.
    """
    needles = tuple({str(p).casefold() for p in candidates} | {
        '.godot/'+p.name if p.parent.name == '.godot' else 'node_modules' for p in candidates})
    pending = ''; line_no = 0
    while True:
        if deadline is not None and time.monotonic() >= deadline:
            raise ReferenceScanDeferred('Reference scan scheduling deadline; all candidates preserved')
        chunk = stream.read(1024*1024)
        if not chunk:
            if pending:
                normalized = pending.replace('\\/', '/')
                if any(n in normalized.casefold() for n in needles):
                    yield line_no+1, normalized
            break
        pending += chunk
        # Bound a single physical line before repeated concatenation/casefold.
        if max(map(len, pending.split('\n'))) > MAX_REFERENCE_LINE_CHARS:
            raise ReferenceScanDeferred('Oversized physical metadata line; all candidates preserved')
        end = pending.rfind('\n')
        if end < 0:
            continue
        complete, pending = pending[:end+1], pending[end+1:]
        normalized = complete.replace('\\/', '/')
        folded = normalized.casefold()
        if not any(n in folded for n in needles):
            line_no += complete.count('\n')
            continue
        for line in normalized.split('\n')[:-1]:
            line_no += 1
            if any(n in line.casefold() for n in needles):
                yield line_no, line


def stable_reference_recheck(candidates, roots, output, previous, target, max_passes=3):
    """Rehash every file; strictly parse changed/new content until stable.

    Unchanged SHA-bound parse results are reused. Membership and both digests
    for every changed/deleted source are persisted. No true or unresolved new
    reference is accepted, and continuing unrelated churn fails closed.
    """
    changes = []
    cycle = len(list(output.glob('reference_recheck_cycle_*.json')))+1
    trace = output/f'reference_recheck_cycle_{cycle:03d}.json'
    for index in range(1, max_passes+1):
        fresh = reference_scan(candidates, roots, output, previous)
        before, after = previous['scanned_source_sha256'], fresh['scanned_source_sha256']
        changed = [{'source': name, 'sha256_before': before.get(name), 'sha256_after': after.get(name)}
                   for name in sorted(before.keys() | after.keys()) if before.get(name) != after.get(name)]
        changes.append({'pass': index, 'changed_sources': changed})
        dump(trace, changes)
        dump(output/'reference_recheck_changes.json', changes)
        snapshot = output/f'reference_recheck_{cycle:03d}_{index:02d}.json'
        dump(snapshot, fresh)
        if fresh['errors'] or fresh['hits'][str(target)]:
            raise ValueError('Fresh metadata contains real/unresolved reference or scan error; see '+str(snapshot))
        if not changed:
            return fresh, trace
        previous = fresh
    raise ValueError('Reference metadata did not stabilize after bounded recheck; see '+str(output/'reference_recheck_changes.json'))


def reference_scan(candidates, roots, output, previous=None):
    """Fail closed on every explicit reference and incomplete metadata scan.

    Only this run's new inventories are excluded. Prior previews remain live
    dependencies. Completed zero-deletion bookkeeping is classified per exact
    field with its original receipt/SHA retained; directories are never exempt. Full scanned
    metadata digests and membership are retained, not just files with hits.
    """
    from .unity_scored_cache import PRUNE_NAMES, TEXT_EXTENSIONS
    hits = {str(p): [] for p in candidates}; errors = []; scanned = {}; classified = []
    started = time.monotonic(); last_progress = started; scanned_bytes = 0
    old_hits = {}; old_classified = {}
    def result(complete):
        return {'reference_policy': 'source-scoped-reference-v2', 'hits': hits,
                'errors': errors, 'scanned_source_sha256': scanned,
                'reference_classifications': classified, 'scan_complete': complete}
    if not candidates:
        return result(True)
    if previous is not None and previous.get('reference_policy') != 'source-scoped-reference-v2':
        raise ValueError('Cannot reuse a different reference parser policy')
    if previous is not None:
        for candidate, rows in previous['hits'].items():
            for row in rows:
                old_hits.setdefault(row['source'], []).append((candidate, row))
        for row in previous['reference_classifications']:
            old_classified.setdefault(row['source'], []).append(row)
    for base in roots:
        try:
            if not base.is_dir() or base.is_symlink():
                raise ValueError('Missing/noncanonical reference root: '+str(base))
            for folder, dirs, files in os.walk(base, followlinks=False, onerror=walk_error):
                dirs[:] = sorted(d for d in dirs if d not in PRUNE_NAMES
                    and Path(folder)/d != output and Path(folder)/d not in candidates
                    and not (Path(folder)/d).is_symlink())
                for name in sorted(files):
                    source = Path(folder)/name
                    if time.monotonic()-started >= REFERENCE_SCAN_SECONDS:
                        errors.append({'source': str(source), 'error': 'Reference scan scheduling deadline; no deletion authorized'})
                        return result(False)
                    if source.suffix.lower() not in TEXT_EXTENSIONS:
                        continue
                    try:
                        if source.is_symlink():
                            raise ValueError('Linked metadata cannot be safely scanned')
                        if source.stat().st_size > MAX_REFERENCE_FILE_BYTES:
                            raise ReferenceScanDeferred('Metadata exceeds bounded scan size; no deletion authorized')
                        digest = sha(source)
                        scanned[str(source)] = digest
                        if (previous is not None and previous['scanned_source_sha256'].get(str(source)) == digest
                                and not old_classified.get(str(source))):
                            for candidate, row in old_hits.get(str(source), []):
                                hits[candidate].append(row)
                            classified.extend(old_classified.get(str(source), []))
                        else:
                            structural = {str(path): npm_structural_keys_only(source, path) for path in candidates}
                            with source.open('r', errors='surrogateescape') as stream:
                                for line_no, normalized in possible_reference_lines(stream, candidates, deadline=started+REFERENCE_SCAN_SECONDS):
                                    folded = normalized.casefold()
                                    for path in candidates:
                                        marker = '.godot/'+path.name if path.parent.name == '.godot' else 'node_modules'
                                        if (str(path).casefold() in folded or marker in folded) and not structural[str(path)]:
                                            row = {'source': str(source), 'sha256': digest, 'physical_line': line_no}
                                            role = reference_role(source, normalized, path, digest)
                                            if role:
                                                classified.append(dict(row, candidate=str(path), **role))
                                            else:
                                                hits[str(path)].append(row)
                        if sha(source) != digest:
                            raise ValueError('Metadata changed during reference scan')
                        scanned_bytes += source.stat().st_size
                        if time.monotonic()-last_progress >= 15:
                            dump(output/'scan_progress.json', {'scanned_files': len(scanned),
                                'scanned_bytes': scanned_bytes, 'current_source': str(source),
                                'elapsed_seconds': time.monotonic()-started, 'updated_unix': time.time()})
                            last_progress = time.monotonic()
                    except ReferenceScanDeferred as exc:
                        errors.append({'source': str(source), 'error': repr(exc)})
                        return result(False)
                    except (OSError, UnicodeError, ValueError) as exc:
                        errors.append({'source': str(source), 'error': repr(exc)})
        except (OSError, ValueError) as exc:
            errors.append({'root': str(base), 'error': repr(exc)})
    return result(not errors)


def run(batch, attempt, output, apply=False):
    batch, attempt, output = map(lambda p: Path(p).absolute(), (batch, attempt, output))
    if any(p.resolve() != p for p in (batch, attempt, output)):
        raise ValueError('Canonical batch/attempt/output paths required')
    if output.parent != batch/'native_cache_reclamation':
        raise ValueError('Store native cache receipts under the dedicated batch directory')
    output.mkdir(parents=True, exist_ok=False)
    receipt = {'version': VERSION, 'apply': bool(apply), 'attempt': str(attempt),
               'started_unix': time.time(), 'status': 'PRECHECK', 'results': [],
               'deleted_allocated_bytes': 0, 'free_bytes_before': shutil.disk_usage(batch).free}
    def save():
        dump(output/'receipt.json', receipt)
    save()
    try:
        control, lock_paths = locks(batch)
        with ExitStack() as stack:
            for path in lock_paths:
                # /tmp is the prescribed macOS alias of /private/tmp; reject
                # a linked lock FILE, not that expected system-directory alias.
                if path.is_symlink():
                    raise ValueError('Noncanonical execution lock')
                handle = stack.enter_context(path.open('a+'))
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            receipt['locks'] = list(map(str, lock_paths))
            source = qualified_score(batch, attempt); receipt['source'] = source
            snapshot = idle_snapshot(attempt)
            (output/'processes.txt').write_text(snapshot['processes'])
            (output/'open_files.txt').write_text(snapshot['open_files'])
            paths = candidate_paths(attempt, source['engine'])
            roots = reference_roots(batch, control)
            refs = reference_scan(paths, roots, output)
            remaining = list(paths)
            dump(output/'reference_scan.json', refs)
            receipt['reference_scan_sha256'] = sha(output/'reference_scan.json')
            for i, path in enumerate(paths):
                row = {'path': str(path), 'status': 'PRESERVED', 'deleted_allocated_bytes': 0}
                receipt['results'].append(row)
                files = []; deletion_started = False
                try:
                    if refs['errors']:
                        raise ValueError('Reference scan incomplete; no deletion authorized; see '+str(output/'reference_scan.json'))
                    if refs['hits'][str(path)]:
                        row['references'] = refs['hits'][str(path)]
                        raise ValueError('Explicit evidence/recovery/cache reference')
                    if str(path) in snapshot['open_files']:
                        raise ValueError('Open-file/cwd dependency')
                    row['regeneration_proof'] = regeneration_proof(attempt, path, source['engine'])
                    identity = (path.stat().st_dev, path.stat().st_ino)
                    files = file_inventory(path)
                    listing = output/f'files_{i:03d}.json'
                    dump(listing, {'version': INVENTORY_VERSION, 'cache': str(path), 'files': files})
                    row.update(file_list=str(listing), file_list_sha256=sha(listing), file_count=len(files),
                               allocated_bytes=sum(f['allocated_bytes'] for f in files))
                    # Recheck every publication binding and actual process/open handles.
                    if qualified_score(batch, attempt) != source:
                        raise ValueError('Published score/source/four tables changed')
                    fresh = idle_snapshot(attempt)
                    if str(path) in fresh['open_files']:
                        raise ValueError('New open-file/cwd dependency')
                    if candidate_paths(attempt, source['engine']) != remaining:
                        raise ValueError('Cache candidate identity changed')
                    if ((path.stat().st_dev, path.stat().st_ino) != identity
                            or file_inventory(path) != files):
                        raise ValueError('Cache changed after inventory')
                    # A reference created after the scan cannot silently authorize deletion.
                    fresh_refs, trace = stable_reference_recheck(paths, roots, output, refs, path)
                    row['stable_reference_trace'] = str(trace)
                    row['stable_reference_trace_sha256'] = sha(trace)
                    refs = fresh_refs
                    if qualified_score(batch, attempt) != source:
                        raise ValueError('Published score/source changed during reference recheck')
                    fresh = idle_snapshot(attempt)
                    if str(path) in fresh['open_files'] or file_inventory(path) != files:
                        raise ValueError('Cache process/files changed during reference recheck')
                    if regeneration_proof(attempt, path, source['engine']) != row['regeneration_proof']:
                        raise ValueError('Regeneration proof changed during cleanup')
                    from .unity_scored_cache import deletion_pause
                    pause = deletion_pause(control, source['case']) if apply else None
                    if pause:
                        raise ValueError(pause['reason'])
                    row['status'] = 'SAFE_PREVIEW'; save()
                    if apply:
                        deletion_started = True
                        shutil.rmtree(path)
                        if path.exists():
                            raise RuntimeError('Cache remains after removal')
                        remaining.remove(path)
                        row['status'] = 'DELETED'
                        row['deleted_allocated_bytes'] = row['allocated_bytes']
                        receipt['deleted_allocated_bytes'] += row['deleted_allocated_bytes']
                        save()
                except Exception as exc:
                    if deletion_started:
                        removed = [f for f in files if not f['directory'] and not os.path.lexists(f['path'])]
                        row['deleted_file_paths'] = [f['path'] for f in removed]
                        row['deleted_allocated_bytes'] = sum(f['allocated_bytes'] for f in removed)
                        receipt['deleted_allocated_bytes'] += row['deleted_allocated_bytes']
                    row.update(status='DELETE_FAILED' if row['status'] == 'SAFE_PREVIEW' and apply else 'PRESERVED',
                               reason=repr(exc))
                save()
            receipt['status'] = 'COMPLETE'
            receipt['table_sha256_after'] = {name: sha(batch/name) for name in TABLES}
            receipt['tables_unchanged'] = receipt['table_sha256_after'] == source['table_sha256']
    except BaseException as exc:
        receipt.update(status='BLOCKED_LOCK' if isinstance(exc, BlockingIOError) else 'FAILED', error=repr(exc))
        raise
    finally:
        receipt['free_bytes_after'] = shutil.disk_usage(batch).free
        receipt['free_bytes_delta'] = receipt['free_bytes_after'] - receipt['free_bytes_before']
        receipt['finished_unix'] = time.time(); save()
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch', type=Path, required=True)
    parser.add_argument('--attempt', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args(argv)
    print(json.dumps(run(args.batch, args.attempt, args.output, args.apply), ensure_ascii=False))


if __name__ == '__main__':
    main()
