"""Bounded original-recipe Unity preflight. Never plans, records gameplay or scores.

CLI --execute consumes the single native allowance even if startup fails.
verify_receipt(out) is read-only and verifies archived execution dependencies;
it does not require today's unrelated production files to equal the producer.
"""
from __future__ import annotations

from ..model_config import PLANNER_MODEL

import ast
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time

from . import prepare, record, unity_editor
from .llm import HarnessError
from .paths import BENCH, FRAMEWORK, read_json, sha256

VERSION = 'stage1-unity-original-scene-job-preflight.v1'
REL = Path('recovery/original_scene_job_preflight_v1')
from pipeline.eval.stage1.paths import DATA_ROOT
TARGETS = DATA_ROOT / 'outputs/eval/whitebox/_playable_retest/targets.json'
OUTPUT_ROOT = DATA_ROOT / 'outputs/eval/whitebox/stage1_playable_v1__plan-gpt-6-astra'
RUNNER = BENCH / 'pipeline/eval/stage1/playable_support.py'
RESERVE = 8 * 1024 ** 3
IMPORT_RESERVE = 2 * 1024 ** 3
METHOD = 'ComposeScene.RunFromCLI'
ENTRIES = {}  # Exact reviewed identities are populated below, never inferred by filename.


def require(ok, reason):
    if not ok:
        raise HarnessError(reason)


def exclusive(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def no_links(root):
    require(not root.is_symlink(), f'symlink forbidden: {root}')
    require(not any(p.is_symlink() for p in root.rglob('*')), f'symlink in {root}')


def official_result_dir(target):
    # Evaluate only the official pure routing function and its literal mapping.
    # Importing the full runner would change process-wide native slot settings.
    tree = ast.parse(RUNNER.read_text())
    nodes = [n for n in tree.body if
             (isinstance(n, ast.FunctionDef) and n.name == 'result_dir') or
             (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and
                                               t.id == 'MODEL_DIRS' for t in n.targets))]
    require(len(nodes) == 2, 'official result_dir definition is ambiguous')
    scope = {'Path': Path}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(RUNNER), 'exec'), scope)
    return scope['result_dir'](OUTPUT_ROOT, target).resolve(), digest(ast.dump(ast.Module(body=nodes, type_ignores=[])))


def parent_files(out):
    result = {}
    for path in sorted(out.rglob('*')):
        rel = path.relative_to(out)
        if rel.parts[0] == 'recovery' or rel.parts[:2] in [('input', 'project'), ('runtime', 'project')]:
            continue
        if path.name.endswith('.lock') or not path.is_file():
            continue
        require(not path.is_symlink(), f'parent evidence symlink: {path}')
        result[str(rel)] = sha256(path)
    return result


def unused(out, *, claimed=False):
    status = read_json(out / 'status.json')
    require(status.get('step') == 'plan_t1' and status.get('state') == 'HARNESS_ERROR',
            'requires terminal plan_t1 HARNESS_ERROR')
    for path in out.rglob('*'):
        rel = path.relative_to(out)
        if rel.parts[0] in ('input', 'runtime') or path.is_dir():
            continue
        if rel.parts[:len(REL.parts)] == REL.parts:
            continue
        name = path.name.lower()
        require(not ('accepted' in name or name in ('plan.json', 'playable_score.json',
                    'record_result.json', 'execution.json', 'native.claim.json') or
                    (rel.parts[0] == 'takes' and name != '.postprocess.lock')),
                f'existing accepted/native/score evidence: {rel}')
    if not claimed:
        require(not (out / REL / 'native.claim.json').exists(), 'BLOCKED_MAX1_NATIVE_PREFLIGHT')


def recipe(entry, source):
    if entry['mode'] == 'import_only':
        return None, None
    path = source.parent / entry['recipe_rel']
    require(path.is_file() and not path.is_symlink() and sha256(path) == entry['recipe_sha256'],
            'original recipe bytes changed')
    raw = path.read_bytes()
    obj = json.loads(raw)
    if entry['recipe_kind'] == 'report_payload':
        require(obj['payload']['class_method'] == METHOD and
                obj['payload']['project_path'] == str(source), 'original report method/source mismatch')
        spec = obj['payload']['spec']
    else:
        spec = obj
    require(isinstance(spec, dict) and spec.get('output_scene') == entry['scene'],
            'reviewed output scene mismatch')
    require(Path(entry['scene']).parts[0] == 'Assets' and '..' not in Path(entry['scene']).parts,
            'unsafe authored scene output')
    return raw, spec


def qualification(out, *, claimed=False):
    """Strict read-only admission. Raises HarnessError on ineligible identities/evidence."""
    out = Path(out).resolve()
    manifest = prepare.verify(out)
    key = manifest['delivery']['model'].capitalize() + ':' + manifest['game_id'][:4]
    require(key in ENTRIES, 'not one of the four reviewed original identities')
    entry = ENTRIES[key]
    targets = read_json(TARGETS)['targets']
    matches = [t for t in targets if t['model'] == entry['model'] and t['game_id'] == entry['game_id']]
    require(len(matches) == 1, 'target identity missing or ambiguous')
    target = matches[0]
    require(target.get('required_real_clients', 1) == 1 and target['engine'] == 'unity3d',
            'only single-client Unity is authorized')
    expected, routing_sha = official_result_dir(target)
    source = Path(entry['project']).resolve()
    require(out == expected and str(source) == target['project'] == manifest['project_source'],
            'exact target/source/result_dir mismatch')
    require(manifest['game_id'] == entry['game_id'] and manifest['engine'] == 'unity3d' and
            manifest['delivery']['project_root'] == str(source) and
            manifest['delivery'].get('required_real_clients', 1) == 1 and
            manifest['models'] == {'planner': PLANNER_MODEL, 'judge': 'none'}, 'manifest identity mismatch')
    require(manifest['project_digest'] == entry['project_digest'] and
            manifest['snapshot_digest'] == entry['snapshot_digest'], 'reviewed tree binding changed')
    frozen, runtime = out / 'input/project', out / 'runtime/project'
    for path in (source, frozen, runtime):
        no_links(path)
    original = prepare.tree_hashes(source)
    require(prepare.tree_digest(original) == manifest['project_digest'], 'original tree changed')
    require(prepare.tree_digest(prepare.tree_hashes(runtime)) == manifest['snapshot_digest'],
            'parent runtime changed or already imported')
    for root in (source, frozen):
        require(sha256(root / entry['code']) == entry['code_sha256'], 'reviewed author method changed')
    raw, spec = recipe(entry, source)
    unused(out, claimed=claimed)
    return {'version': VERSION, 'key': key, 'entry': entry, 'target': target,
            'routing_sha256': routing_sha, 'manifest_sha256': sha256(out / 'manifest.json'),
            'recipe_path': str(source.parent / entry['recipe_rel']) if raw is not None else None,
            'spec_structural_sha256': digest(spec) if spec is not None else None,
            'parent_files': parent_files(out), 'original_hashes': original,
            'frozen_hashes': prepare.tree_hashes(frozen), 'mode': entry['mode']}


@contextmanager
def locked(out):
    folder = out / REL
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / '.lock').open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise HarnessError('preflight is already active') from exc
        yield folder


def producer():
    # All actually imported repository Python dependencies, including record's
    # imported plan helpers. Archive bytes; never execute archive snapshots.
    files = {Path(__file__).resolve()}
    for module in tuple(sys.modules.values()):
        filename = getattr(module, '__file__', None)
        if filename:
            p = Path(filename).resolve()
            if p.is_relative_to(FRAMEWORK) and p.suffix == '.py' and p.is_file():
                files.add(p)
    return {str(p.relative_to(FRAMEWORK)): sha256(p) for p in sorted(files)}


def processes():
    text = subprocess.check_output(['ps', '-axo', 'pid=,ppid=,pgid=,lstart=,stat=,command='], text=True)
    result = {}
    for line in text.splitlines():
        parts = line.split(None, 9)
        if len(parts) == 10:
            pid, ppid, pgid = map(int, parts[:3])
            result[pid] = {'pid': pid, 'ppid': ppid, 'pgid': pgid, 'start': ' '.join(parts[3:8]),
                           'stat': parts[8], 'command': parts[9]}
    return result


def windows(pids):
    import Quartz
    rows = Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionAll, Quartz.kCGNullWindowID)
    require(rows is not None, 'native window enumeration unavailable')
    return [{'pid': int(row.get('kCGWindowOwnerPID', -1)),
             'window_id': int(row.get('kCGWindowNumber', -1))}
            for row in rows if int(row.get('kCGWindowOwnerPID', -1)) in pids]


def native(command, folder, timeout=600):
    """Own process group only. Capture actual exit, descendant identities and windows."""
    observed, actions = {}, []
    begin = time.monotonic()
    expired, spawn_error = False, None
    process = None
    with (folder / 'console.log').open('x') as stream:
        try:
            process = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
            exclusive(folder / 'process_started.json', {'pid': process.pid, 'pgid': process.pid,
                      'cmd': command, 'started_unix': time.time()})
            while True:
                current = processes()
                owned = {process.pid} | set(observed)
                for _ in range(len(current) + 1):
                    added = {pid for pid, p in current.items() if p['ppid'] in owned or p['pgid'] == process.pid}
                    if added <= owned:
                        break
                    owned |= added
                observed.update({pid: p for pid, p in current.items() if pid in owned})
                if process.poll() is not None:
                    break
                if time.monotonic() - begin > timeout:
                    expired = True
                    break
                time.sleep(0.5)
        except Exception as exc:
            spawn_error = repr(exc)
        finally:
            if process is not None:
                # On normal exit allow worker processes to terminate naturally.
                for sig, grace in [(None, 5), (signal.SIGTERM, 5), (signal.SIGKILL, 3)]:
                    group = [p for p in processes().values() if p['pgid'] == process.pid and not p['stat'].startswith('Z')]
                    if not group:
                        break
                    if sig is not None:
                        try:
                            os.killpg(process.pid, sig)
                            actions.append({'signal': int(sig), 'pgid': process.pid, 'members': group})
                        except ProcessLookupError:
                            pass
                    deadline = time.monotonic() + grace
                    while time.monotonic() < deadline:
                        process.poll()
                        if not any(p['pgid'] == process.pid and not p['stat'].startswith('Z') for p in processes().values()):
                            break
                        time.sleep(0.25)
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
    current = processes()
    alive = [p for pid, p in current.items() if
             (pid in observed and p['start'] == observed[pid]['start'] or
              process is not None and p['pgid'] == process.pid) and not p['stat'].startswith('Z')]
    view_error = None
    try:
        remaining_windows = windows(set(observed) | ({process.pid} if process else set()))
    except Exception as exc:
        remaining_windows, view_error = [], repr(exc)
    cleanup = {'process_cleanup_verified': process is not None and process.returncode is not None and not alive,
               'view_cleanup_verified': view_error is None and not remaining_windows,
               'input_cleanup': 'NOT_APPLICABLE_NO_GAMEPLAY_OR_INPUT',
               'owned_processes_observed': list(observed.values()), 'owned_processes_alive': alive,
               'remaining_windows': remaining_windows, 'window_query_error': view_error,
               'signals': actions}
    exclusive(folder / 'cleanup.json', cleanup)
    return {'cmd': command, 'pid': process.pid if process else None,
            'pgid': process.pid if process else None, 'exit_code': process.returncode if process else None,
            'timeout': expired, 'spawn_error': spawn_error, 'elapsed_ms': round((time.monotonic() - begin)*1000)}


def command_for(editor, folder, entry):
    cmd = [editor, '-batchmode', '-nographics', '-quit', '-projectPath', str(folder / 'project'),
           '-logFile', str(folder / 'builder.log')]
    if entry['mode'] == 'compose':
        cmd += ['-executeMethod', METHOD, '--job', str(folder / 'scene_spec.json'),
                '--report', str(folder / 'compose_report.json')]
    return cmd


def classify(folder, entry, execution, cleanup):
    text = '\n'.join(p.read_text(errors='replace') for p in [folder / 'builder.log', folder / 'console.log'] if p.is_file())
    errors = sorted(set(line for line in text.splitlines() if re.search(r'\berror CS\d+\b', line)))
    clean = cleanup['process_cleanup_verified'] and cleanup['view_cleanup_verified']
    if execution.get('spawn_error') or execution['timeout'] or not clean:
        return 'HARNESS_ERROR', errors
    if execution['exit_code'] != 0:
        if errors:
            return 'PRODUCT_COMPILE_FAILURE', errors
        # Only a freshly emitted author report can establish compose failure.
        report = folder / 'compose_report.json'
        if entry['mode'] == 'compose' and report.is_file():
            try:
                obj = read_json(report)
                if obj.get('ok') is False and obj.get('error'):
                    return 'PRODUCT_COMPOSE_FAILURE', errors
            except (ValueError, TypeError):
                pass
        return 'HARNESS_ERROR', errors
    if errors:
        return 'HARNESS_ERROR', errors
    if entry['mode'] == 'import_only':
        return 'IMPORT_FINISHED_REQUIRES_ADMISSION', errors
    try:
        report = read_json(folder / 'compose_report.json')
        if report.get('ok') is True and report.get('scenePath') == entry['scene'] and (folder / 'project' / entry['scene']).is_file():
            return 'BUILDER_FINISHED_REQUIRES_ADMISSION', errors
    except (OSError, ValueError, TypeError):
        pass
    return 'HARNESS_ERROR', errors


def verify_archives(folder, binding):
    for rel, expected in binding['parent_files'].items():
        require(sha256(folder / 'parent_archive' / rel) == expected, 'parent archive changed')
    for rel, expected in binding['production'].items():
        require(sha256(folder / 'production' / rel) == expected, 'producer archive changed')
    require(sha256(folder / 'targets.before.json') == binding['targets_sha256'], 'targets archive changed')
    require(sha256(folder / 'runner.before.py') == binding['runner_sha256'], 'runner archive changed')
    entry = binding['entry']
    if entry['mode'] == 'compose':
        raw = (folder / 'original_recipe.json').read_bytes()
        require(hashlib.sha256(raw).hexdigest() == entry['recipe_sha256'], 'archived recipe changed')
        spec = json.loads(raw)
        if entry['recipe_kind'] == 'report_payload':
            spec = spec['payload']['spec']
        require(digest(spec) == binding['spec_structural_sha256'] and
                read_json(folder / 'scene_spec.json') == spec and
                sha256(folder / 'scene_spec.json') == binding['job_sha256'], 'job changed')
        if entry['recipe_kind'] == 'direct':
            require((folder / 'scene_spec.json').read_bytes() == raw, 'direct spec not byte exact')


def execute(out):
    out = Path(out).resolve()
    with locked(out) as folder, record._record_lock(out, 1):
        before = qualification(out)
        require(not any(p.name != '.lock' for p in folder.iterdir()),
                'partial preflight retained; no automatic redispatch or overwrite')
        frozen = out / 'input/project'
        size = sum(p.stat().st_size for p in frozen.rglob('*') if p.is_file())
        free = shutil.disk_usage(out).free
        require(free >= RESERVE + IMPORT_RESERVE + size, 'insufficient 8GiB + import/copy reserve')
        binding = {**before, 'production': producer(), 'targets_sha256': sha256(TARGETS),
                   'runner_sha256': sha256(RUNNER), 'free_bytes_before_copy': free,
                   'project_copy_bytes': size, 'import_reserve_bytes': IMPORT_RESERVE, 'reserve_bytes': RESERVE}
        for rel in before['parent_files']:
            dest = folder / 'parent_archive' / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(out / rel, dest)
        for rel in binding['production']:
            dest = folder / 'production' / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(FRAMEWORK / rel, dest)
        shutil.copyfile(TARGETS, folder / 'targets.before.json')
        shutil.copyfile(RUNNER, folder / 'runner.before.py')
        shutil.copytree(frozen, folder / 'project')
        entry = before['entry']
        raw, spec = recipe(entry, Path(entry['project']))
        if raw is not None:
            (folder / 'original_recipe.json').write_bytes(raw)
            job = raw if entry['recipe_kind'] == 'direct' else json.dumps(spec, ensure_ascii=False, indent=2).encode() + b'\n'
            (folder / 'scene_spec.json').write_bytes(job)
            binding['job_sha256'] = sha256(folder / 'scene_spec.json')
        choice = unity_editor.choose(folder / 'project')
        binding['editor'] = choice
        binding['editor_binary_sha256'] = sha256(Path(choice['editor']['binary']))
        exclusive(folder / 'binding.json', binding)
        verify_archives(folder, binding)
        require(prepare.tree_hashes(folder / 'project') == before['frozen_hashes'], 'isolated copy differs')
        cmd = command_for(choice['editor']['binary'], folder, entry)
        with record.gui_slot() as slot:
            require(qualification(out) == before, 'source/parent/identity changed before native')
            require(producer() == binding['production'], 'producer changed before dispatch')
            require(sha256(Path(choice['editor']['binary'])) == binding['editor_binary_sha256'], 'editor changed')
            require(shutil.disk_usage(out).free >= RESERVE + IMPORT_RESERVE, 'insufficient native reserve')
            require(not any(str(folder / 'project') in p['command'] for p in processes().values()),
                    'isolated project already active')
            windows(set())  # Fail before consuming native if actual view checks are unavailable.
            exclusive(folder / 'native.claim.json', {'version': VERSION, 'cmd': cmd, 'max_native_invocations': 1,
                      'binding_sha256': sha256(folder / 'binding.json'), 'gui_slot': str(slot),
                      'record_lock': str(out / 'takes/1/record/.postprocess.lock'),
                      'additional_model_calls': 0, 'gameplay_takes': 0, 'mode': entry['mode'],
                      'free_bytes_at_dispatch': shutil.disk_usage(out).free})
            execution = native(cmd, folder)
            exclusive(folder / 'execution.json', execution)
        after = qualification(out, claimed=True)
        require(after == before, 'original/frozen/parent changed during native')
        verify_archives(folder, binding)
        cleanup = read_json(folder / 'cleanup.json')
        classification, errors = classify(folder, entry, execution, cleanup)
        after_tree = prepare.tree_hashes(folder / 'project')
        changed = {p: {'before': before['frozen_hashes'].get(p), 'after': after_tree.get(p)}
                   for p in sorted(set(before['frozen_hashes']) | set(after_tree))
                   if before['frozen_hashes'].get(p) != after_tree.get(p)}
        exclusive(folder / 'project_after.json', {'hashes': after_tree, 'changes': changed})
        artifacts = {str(p.relative_to(folder)): sha256(p) for p in folder.iterdir()
                     if p.is_file() and p.name != '.lock'}
        result = {'version': VERSION, 'key': before['key'], 'mode': entry['mode'],
                  'classification': classification, 'complete': False, 'score_written': False,
                  'native_invocations': 1, 'additional_model_calls': 0, 'gameplay_takes': 0,
                  'original_and_frozen_verified': True, 'parent_unchanged': True,
                  'process_cleanup_verified': cleanup['process_cleanup_verified'],
                  'view_cleanup_verified': cleanup['view_cleanup_verified'], 'errors': errors,
                  'artifacts': artifacts, 'retained_dependencies_deleted_bytes': 0,
                  'production_drift_after': {k: v for k, v in producer().items() if binding['production'].get(k) != v}}
        exclusive(folder / 'result.json', result)
        return verify_receipt(out)


def verify_receipt(out):
    """Read-only diagnostic receipt, NEVER a score/replacement/admission API."""
    out = Path(out).resolve()
    folder = out / REL
    result, binding = read_json(folder / 'result.json'), read_json(folder / 'binding.json')
    require(result['version'] == VERSION and result['complete'] is False and result['score_written'] is False
            and result['native_invocations'] == 1 and result['additional_model_calls'] == 0
            and result['gameplay_takes'] == 0, 'invalid preflight-only result')
    require(binding['production'][str(Path(__file__).resolve().relative_to(FRAMEWORK))] == sha256(Path(__file__)),
            'preflight verifier differs from executed producer')
    current = qualification(out, claimed=True)
    require(all(binding[k] == v for k, v in current.items()), 'live parent/source binding changed')
    verify_archives(folder, binding)
    for rel, expected in result['artifacts'].items():
        require(Path(rel).name == rel and sha256(folder / rel) == expected, 'native artifact changed')
    required = {'binding.json', 'native.claim.json', 'execution.json', 'cleanup.json',
                'console.log', 'project_after.json', 'targets.before.json', 'runner.before.py'}
    require(required <= set(result['artifacts']), 'missing required artifact binding')
    claim, execution = read_json(folder / 'native.claim.json'), read_json(folder / 'execution.json')
    if execution['pid'] is not None:
        require('process_started.json' in result['artifacts'], 'missing process start proof')
        started = read_json(folder / 'process_started.json')
        require(started['pid'] == started['pgid'] == execution['pid'] == execution['pgid']
                and started['cmd'] == execution['cmd'], 'PID/command binding mismatch')
    require(claim['binding_sha256'] == sha256(folder / 'binding.json') and claim['max_native_invocations'] == 1,
            'claim binding changed')
    expected_cmd = command_for(binding['editor']['editor']['binary'], folder, binding['entry'])
    require(claim['cmd'] == execution['cmd'] == expected_cmd, 'native command changed')
    after = read_json(folder / 'project_after.json')
    require(prepare.tree_hashes(folder / 'project') == after['hashes'], 'isolated native project changed')
    cleanup = read_json(folder / 'cleanup.json')
    classification, errors = classify(folder, binding['entry'], execution, cleanup)
    require(result['classification'] == classification and result['errors'] == errors and
            result['process_cleanup_verified'] == cleanup['process_cleanup_verified'] and
            result['view_cleanup_verified'] == cleanup['view_cleanup_verified'], 'native disposition mismatch')
    return result


def main():
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument('--execute', action='store_true')
    mode.add_argument('--verify', action='store_true')
    args = p.parse_args()
    result = execute(args.out) if args.execute else verify_receipt(args.out) if args.verify else qualification(args.out)
    print(json.dumps(result, ensure_ascii=False, indent=2))


# REVIEWED_ENTRIES
ENTRIES = {'Astra:G045': {'model': 'Astra',
                'game_id': 'G045_daily_street_lightlane',
                'project': str(DATA_ROOT / 'outputs/initial_game_gen/gpt_astra6/G045_daily_street_lightlane/gamefactory_G045_daily_street_lightlane_20261018_174508/pipeline/G045_daily_street_lightlane_whitebox/project'),
                'mode': 'compose',
                'recipe_rel': 'scene_spec.json',
                'recipe_kind': 'direct',
                'recipe_sha256': '3b4378dfa534d501f5a44230531af2003a1b80ce952dcdf91f9b43b89aa9c8b3',
                'scene': 'Assets/Scenes/Lightlane.unity',
                'code': 'Assets/Editor/ComposeScene.cs',
                'code_sha256': '467747f422ba568fe56252b3a6aa1ff7b74bb80dab99fd627566ed01a3be9606',
                'project_digest': 'aacbff9b89a56f15989e2fad5eb86d2d48e73d47f505cd8b0f886022d2e7b0aa',
                'snapshot_digest': '62295076610babacbd53f482dbb4d500750cab85fbcf7a079d4589b7f43f491e'},
 'Astra:G058': {'model': 'Astra',
                'game_id': 'G058_pitch_dreams_football',
                'project': str(DATA_ROOT / 'outputs/initial_game_gen/gpt_astra6/G058_pitch_dreams_football/gamefactory_G058_pitch_dreams_football_20261017_100506/pipeline/G058_pitch_dreams_football_whitebox/UnityProject'),
                'mode': 'compose',
                'recipe_rel': 'scene_spec.json',
                'recipe_kind': 'direct',
                'recipe_sha256': '9073226b443dde82028ab52461d49bf828525b137880011220804d4fa1fe365c',
                'scene': 'Assets/Scenes/PitchDreams.unity',
                'code': 'Assets/Editor/ComposeScene.cs',
                'code_sha256': '467747f422ba568fe56252b3a6aa1ff7b74bb80dab99fd627566ed01a3be9606',
                'project_digest': '7586f06a73a3e952f2159529b027640a1891a1d4da060d83d83483485508a9ab',
                'snapshot_digest': '8757173c54a437c2eda82ad7a5cc958ff60aadb086ffbca99ea423359556cce7'},
 'Sol:G047': {'model': 'Sol',
              'game_id': 'G047_oldtown_fire_rescue',
              'project': str(DATA_ROOT / 'outputs/initial_game_gen/gpt_sol6p1/G047_oldtown_fire_rescue/gamefactory_G047_oldtown_fire_rescue_20261019_041626/pipeline/G047_oldtown_fire_rescue_whitebox/project'),
              'mode': 'compose',
              'recipe_rel': 'validation/scene_compose.json',
              'recipe_kind': 'report_payload',
              'recipe_sha256': '48f8690bafc1ad49daa123e554cf0cf0d02be8b0ffcd2f1ace99942469a70c77',
              'scene': 'Assets/Scenes/OldtownRescue.unity',
              'code': 'Assets/Editor/ComposeScene.cs',
              'code_sha256': '467747f422ba568fe56252b3a6aa1ff7b74bb80dab99fd627566ed01a3be9606',
              'project_digest': '8b1a2769b14c6316b05e5011f053d68b457bd288cfe773f322377c3e249795d6',
              'snapshot_digest': 'badad255c074543b29295395f8346a858cf279a64aab717e61fae1bf6261d09a'},
 'Sol:G049': {'model': 'Sol',
              'game_id': 'G049_underwater_salvage',
              'project': str(DATA_ROOT / 'outputs/initial_game_gen/gpt_sol6p1/G049_underwater_salvage/gamefactory_G049_underwater_salvage_20261018_205208/mechanic/G049_underwater_salvage_whitebox'),
              'mode': 'import_only',
              'recipe_rel': None,
              'recipe_kind': None,
              'recipe_sha256': None,
              'scene': None,
              'code': 'Assets/Scripts/SalvageGame.cs',
              'code_sha256': '44adee6c71e61371d5b412d26ec1ceea15b0878c4349937e93537d6a5d4ccc91',
              'project_digest': 'fb264feb725dc7fefdcf2091031f310dec6d76bf2b4ee9cf3e5a6761c32ed396',
              'snapshot_digest': 'b7cf0b0ba7e58bbe1088dcb2763d5b40225475f3edf9f0b5c924a42b93e2a7a4'}}

if __name__ == "__main__":
    main()
