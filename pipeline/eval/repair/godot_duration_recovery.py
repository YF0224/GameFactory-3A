"""Bounded Godot recording-window recovery. Audit/qualification never record.

A short completed native consumes its take. Only one such parent may receive
one isolated child using the exact accepted plan. Two consumed takes are final.
No planner, author edits, parent evidence replacement, or implicit retry.
"""
from __future__ import annotations

from ..model_config import PLANNER_MODEL

import argparse
import ast
from contextlib import ExitStack, contextmanager
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess

from ..stage1 import prepare
from ..stage1.paths import read_json, sha256, write_json

VERSION = 'stage1-godot-duration-recovery.v1'
LINEAGE = Path('recovery/godot_duration_v1')
HOLD_KIND = 'GODOT_RECORDING_WINDOW_SHORT'
ROOT = Path(__file__).resolve().parents[3]
MAX_TAKES = 2
REQUIRED_MS = 75000
TERMINAL = {'done', 'ERROR', 'HARNESS_ERROR'}
_OWNED_LOCKS = set()


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def plain(path):
    path = Path(path).absolute()
    require(not any(p.is_symlink() for p in (path, *path.parents)), f'symlink: {path}')


def tree(root, *, skip=()):
    root = Path(root)
    plain(root)
    require(root.is_dir(), f'missing tree: {root}')
    result = {}
    for directory, dirs, names in os.walk(root, followlinks=False):
        base = Path(directory)
        for name in dirs + names:
            require(not (base/name).is_symlink(), f'symlink: {base/name}')
        dirs[:] = [d for d in dirs if str((base/d).relative_to(root)) not in skip]
        for name in names:
            if name.endswith('.lock') or name.endswith('.pyc'):
                continue
            p = base/name
            require(p.is_file(), f'non-regular file: {p}')
            result[str(p.relative_to(root))] = sha256(p)
    return result


def parent_files(out):
    return tree(out, skip=(str(LINEAGE),))


def production():
    roots = ('engine_adapters/godot', 'engine_adapters/common')
    files = {}
    for name in roots:
        for p in (ROOT/name).rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts and p.suffix in {'.py', '.gd', '.json', '.js'}:
                files[str(p.relative_to(ROOT))] = sha256(p)
    for name in ('__init__.py', 'godot_duration_recovery.py', 'record.py', 'plan.py', 'pipeline.py',
                 'prepare.py', 'paths.py', 'llm.py', 'playable_rules.py', 'native_log.py', 'capture.py',
                 'budgets.py', 'suites.py', 'delivery.py', 'criteria.py', 'standards.py'):
        p = Path(__file__).with_name(name)
        files[str(p.relative_to(ROOT))] = sha256(p)
    for name in ('engine_adapters/__init__.py', 'engine_adapters/_input_capabilities.py', 'engine_adapters/_mouse_plan.py'):
        if (ROOT/name).is_file():
            files[name] = sha256(ROOT/name)
    return files


def plan_dependency(path):
    """Godot replay/rules use take_dir only; archive all planner bytes separately.

    Parse historical source as data. Require its only global dependency Path to
    retain the pathlib import, and reject reassignment of either binding.
    """
    module = ast.parse(Path(path).read_text())
    functions = [n for n in module.body if isinstance(n, ast.FunctionDef) and n.name == 'take_dir']
    require(len(functions) == 1, 'ambiguous plan.take_dir')
    fn = functions[0]
    expected = ast.parse("def take_dir(out: Path, take: int) -> Path:\n    return Path(out) / 'takes' / str(take)\n").body[0]
    require(ast.dump(fn) == ast.dump(expected), 'plan.take_dir dependency changed')
    bindings = []
    for n in module.body:
        if isinstance(n, ast.ImportFrom) and n.module == 'pathlib':
            bindings.extend(a for a in n.names if (a.asname or a.name) == 'Path')
        if isinstance(n, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = n.targets if isinstance(n, ast.Assign) else [n.target]
            require(not any(isinstance(t, ast.Name) and t.id in {'Path','take_dir','str'}
                            for target in targets for t in ast.walk(target)), 'planner dependency rebound')
    require(len(bindings) == 1 and bindings[0].name == 'Path', 'planner Path import changed')
    return digest(ast.dump(fn))


def accepted(out):
    p = out/'model_calls/plan_t1/accepted_response.json'
    receipt = read_json(p)
    response = (p.parent/receipt['path']).absolute()
    plain(response)
    require(response.resolve().is_relative_to((out/'model_calls').resolve()), 'accepted response escapes model_calls')
    require(sha256(response) == receipt['sha256'], 'accepted response hash mismatch')
    plan = out/'takes/1/plan.json'
    require(read_json(plan) == read_json(response), 'plan differs from accepted response')
    return {'plan_path': str(plan), 'plan_sha256': sha256(plan),
            'accepted_receipt_sha256': sha256(p), 'accepted_response_path': str(response),
            'accepted_response_sha256': sha256(response),
            'max_duration_ms': read_json(plan)['max_duration_ms']}


def source_proof(out, manifest):
    source = Path(manifest['project_source'])
    source_files = tree(source)
    original = prepare.tree_hashes(source)
    require(prepare.tree_digest(original) == manifest['project_digest'], 'original source drift')
    # Reproduce prepare's copytree(ignore=IGNORE), including directory pruning.
    snapshot = {}
    for directory, dirs, names in os.walk(source):
        ignored = prepare.IGNORE(directory, dirs + names)
        dirs[:] = [d for d in dirs if d not in ignored]
        for name in names:
            if name not in ignored:
                p = Path(directory)/name
                snapshot[str(p.relative_to(source))] = sha256(p)
    require(prepare.tree_digest(snapshot) == manifest['snapshot_digest'], 'source cannot reproduce frozen snapshot')
    frozen = out/'input/project'
    if frozen.exists():
        require(prepare.tree_hashes(frozen) == snapshot, 'parent snapshot drift')
    else:
        cleanup = read_json(out/'cleanup.json')
        require('input/project' in cleanup.get('removed', []), 'snapshot missing without cleanup receipt')
    current = {k: v for k, v in prepare.tree_hashes(out/'input').items() if not k.startswith('project/')}
    require(current == manifest['input_hashes'], 'frozen non-project inputs drift')
    runtime = out/'runtime/project'
    if runtime.exists():
        files = prepare.tree_hashes(runtime)
        require(all(files.get(k) == v for k, v in snapshot.items()), 'runtime author drift')
        require(all(p.startswith('.godot/') for p in files.keys() - snapshot.keys()), 'unexpected runtime additions')
    return {'path': str(source), 'files': source_files, 'project_digest': manifest['project_digest'],
            'snapshot_files': snapshot, 'snapshot_digest': manifest['snapshot_digest']}


def rows(p):
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]


def native_evidence(out, take, *, full_window=False, required_ms=REQUIRED_MS):
    rec = out/f'takes/{take}/record'
    native = rec/'native'
    names = ('execution.json', 'actions.jsonl', 'state_trace.jsonl', 'frame_index.jsonl',
             'input_view_cleanup.json', 'process_cleanup.json', 'engine.log')
    for name in names:
        require(sha256(rec/name) == sha256(native/name), f'canonical/native mismatch: {take}/{name}')
    ex = read_json(native/'execution.json')
    require(ex.get('complete') is True and ex.get('status') == 'CAPTURED'
            and ex.get('clock') == 'session_monotonic' and ex.get('no_state_injection') is True
            and ex.get('capture_errors') == [], 'capture not normally completed')
    duration = ex.get('duration_ms')
    require(type(duration) in (int, float) and math.isfinite(duration) and duration > 0, 'invalid duration')
    if full_window:
        require(duration >= required_ms, 'native recording shorter than required window')
    frames, actions = rows(native/'frame_index.jsonl'), rows(native/'actions.jsonl')
    require(len(frames) == ex['frames'] and len(frames) >= 2, 'frame count mismatch')
    require(len(rows(native/'state_trace.jsonl')) == ex['states'], 'state count mismatch')
    previous = -1
    seen = set()
    for frame in frames:
        t = frame.get('t_ms')
        require(type(t) in (int, float) and math.isfinite(t) and previous < t <= duration, 'frame clock invalid')
        previous = t
        rel = Path(frame['raw_path'])
        require(not rel.is_absolute() and '..' not in rel.parts and rel.parts[0] == 'frames', 'frame escape')
        require(str(rel) not in seen, 'duplicate frame')
        seen.add(str(rel))
        require(frame.get('capture_status') == 'captured' and frame.get('clock') == 'session_monotonic', 'uncaptured frame')
        plain(native/rel)
        plain(rec/rel)
        require(sha256(native/rel) == sha256(rec/rel), 'native pixel mismatch')
    require(not any(a.get('sent') is False or a.get('ok') is False for a in actions), 'failed native input')
    result = read_json(rec/'record_result.json')
    require(result.get('engine') == 'godot' and result.get('take') == take
            and result.get('plan_sha256') == sha256(out/f'takes/{take}/plan.json')
            and result.get('frames') == len(frames) and result.get('actions') == len(actions)
            and result.get('failed_actions') == [], 'record_result mismatch')
    inputs, process = read_json(native/'input_view_cleanup.json'), read_json(native/'process_cleanup.json')
    require(inputs.get('input_cleanup') is True and inputs.get('held_keys_after_release') == 0
            and inputs.get('capture_callback_disconnected') is True, 'input cleanup unverified')
    require(process.get('process_cleanup') is True and process.get('view_cleanup') is True
            and process.get('group_alive_after_wait') is False and process.get('timeout') is False
            and process.get('returncode') == 0, 'process/view cleanup unverified')
    adapter = read_json(rec/'adapter_result.json')
    require(adapter.get('ok') is True and adapter['payload'].get('exit_code') == 0
            and adapter['payload'].get('timeout') is False
            and adapter['payload'].get('process_cleanup') == process, 'adapter cleanup mismatch')
    require(result.get('cleanup') == {'input_view_cleanup.json': inputs, 'process_cleanup.json': process}, 'result cleanup mismatch')
    require(adapter['payload']['launch_diagnostics']['project_root'] == str(out/'runtime/project'), 'native runtime binding mismatch')
    observed = Path(adapter['payload']['observation_plan'])
    require(observed in (out/f'takes/{take}/plan.json', rec/'recording_plan.json'), 'foreign observation plan')
    config = read_json(observed)
    plan = read_json(out/f'takes/{take}/plan.json')
    require({k:v for k,v in config.items() if k not in ('recording_ms', 'native_capture_schedule')} == plan,
            'native configuration changed accepted plan')
    if full_window:
        require(config.get('recording_ms') == required_ms, 'native recording window not pinned')
    return {'take': take, 'duration_ms': duration, 'adapter_elapsed_ms': result.get('elapsed_ms'),
            'frames': len(frames), 'first_frame_ms': frames[0]['t_ms'], 'last_frame_ms': frames[-1]['t_ms'],
            'complete': True, 'input_cleanup': inputs, 'process_cleanup': process,
            'observation_plan': str(observed), 'observation_plan_sha256': sha256(observed),
            'recording_ms': config.get('recording_ms'), 'plan_max_duration_ms': plan['max_duration_ms']}


def inventory(out):
    takes = []
    for p in sorted((out/'takes').glob('*')):
        require(p.is_dir() and p.name.isdigit(), 'unexpected take entry')
        record = p/'record'
        ex_path = record/'execution.json'
        ex = read_json(ex_path) if ex_path.is_file() else {}
        # A partial native reservation is conservatively consumed too.
        consumed = (record/'native').exists() or bool(ex) or (record/'record_result.json').exists()
        takes.append({'take': int(p.name), 'consumed': consumed, 'duration_ms': ex.get('duration_ms'),
                      'complete': ex.get('complete'), 'status': ex.get('status'),
                      'record_result': (record/'record_result.json').exists()})
    return takes


@contextmanager
def existing_locks(out):
    with ExitStack() as stack:
        for p in sorted(out.rglob('*.lock')):
            if p in _OWNED_LOCKS:
                continue
            if LINEAGE.as_posix() in str(p.relative_to(out)):
                continue
            plain(p)
            handle = stack.enter_context(p.open('r'))
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def effective_budget(manifest):
    """Exactly run_playable's existing short-budget transform; never infer plan duration."""
    budget = dict(manifest['budget'])
    extra = REQUIRED_MS - budget['gameplay_ms']
    for name in ('gameplay_ms', 'recording_ms', 'total_wall_clock_ms'):
        budget[name] += extra
    budget['engine_call_ms'] = max(budget['engine_call_ms'] + extra, budget['total_wall_clock_ms'])
    require(budget['recording_ms'] == REQUIRED_MS, 'unexpected effective recording window')
    return budget


def evaluated_failure_score(out):
    """Existing canonical/strict ANSI correction only, checked against current rules.

    A diagnosed product failure does not become a 75s-qualified recording.
    """
    try:
        import tempfile
        from ..stage1 import playable_rules
        from .godot_import_log_recovery import qualified_replacement_score as ansi_score
        score = ansi_score(out) or read_json(out/'playable_score.json')
        require(score.get('complete') is True, 'no complete existing score')
        takes = inventory(out)
        require(takes and max(t['take'] for t in takes) <= MAX_TAKES, 'unexpected failure take count')
        with tempfile.TemporaryDirectory(prefix='godot-product-failure-') as temp:
            verdicts = playable_rules.evaluate(out,read_json(out/'manifest.json'),max(t['take'] for t in takes),report_dir=Path(temp))
        checks = {i: verdicts.get(i,{}).get('status','HARNESS_ERROR') for i in playable_rules.IDS}
        require(checks == score['checks'] and checks['play.import'] == 'FAIL'
                and checks['play.launch'] == 'FAIL' and checks['play.operate'] != 'PASS'
                and 'HARNESS_ERROR' not in checks.values(), 'not verified evaluated product failure')
        require(score['playable'] == round(100*sum(v=='PASS' for v in checks.values())/3,2), 'failure score mismatch')
        return score
    except (OSError,ValueError,KeyError,TypeError,RuntimeError):
        return None


def qualification(out, *, bind=True):
    """Read-only and fail closed. Missing/running/blocked rows never raise.

    window_qualified only attests the existing native windows, never that a
    historical score has passed all other gates. Product failures stay separate.
    """
    out = Path(out).absolute()
    row = {'version': VERSION, 'out': str(out), 'eligible': False, 'window_qualified': False,
           'disposition': 'MISSING', 'native_count': 0, 'max_native_takes': MAX_TAKES,
           'evaluated_failure_score': None}
    try:
        plain(out)
        if not (out/'manifest.json').is_file():
            return row
        manifest = read_json(out/'manifest.json')
        row.update(game_id=manifest.get('game_id'), engine=manifest.get('engine'), model=manifest.get('delivery', {}).get('model'))
        if manifest.get('engine') != 'godot':
            row['disposition'] = 'NOT_GODOT'
            return row
        require(manifest.get('suite') == 'stage1' and manifest.get('models') == {'planner':PLANNER_MODEL, 'judge':'none'}, 'outside Stage1 playable route')
        required = effective_budget(manifest)['recording_ms']
        row['required_ms'] = required
        row['manifest_recording_ms'] = manifest['budget']['recording_ms']
        row['budget_derivation'] = 'run_playable: recording_ms + (75000 - gameplay_ms)'
        if not (out/'status.json').is_file():
            return row
        state = read_json(out/'status.json')
        row['parent_state'] = state.get('state')
        if state.get('state') not in TERMINAL:
            row['disposition'] = 'ACTIVE'
            return row
        takes = inventory(out)
        row['takes'] = takes
        row['native_count'] = sum(t['consumed'] for t in takes)
        # Recovery descendants cannot be used to reset the attempt counter.
        extra = [p for p in (out/'recovery').glob('**/takes/*/record')
                 if not any(x in {'parent_archive', 'archive'} for x in p.relative_to(out/'recovery').parts)
                 and ((p/'native').exists() or (p/'execution.json').exists())]
        if (out/LINEAGE/'dispatch.json').exists() and not any(p.is_relative_to(out/LINEAGE) for p in extra):
            row.update(native_count=row['native_count']+1, disposition='BLOCKED_MAX_TAKES',
                       reason='child native slot already reserved/consumed; no retry')
            return row
        if extra:
            row['descendant_native_records'] = [str(p.relative_to(out)) for p in extra]
            row['native_count'] += len(extra)
            row['disposition'] = 'BLOCKED_MAX_TAKES' if row['native_count'] >= 2 else 'BLOCKED_OTHER_RECOVERY'
            return row
        if not takes or row['native_count'] == 0:
            row['disposition'] = 'NO_NATIVE_EVIDENCE'
            # Preserve proven product import failure as a separate disposition.
            from .native_log import godot_product_errors
            errors = [str(p.relative_to(out)) for p in (out/'takes').glob('*/record/import.log')
                      if godot_product_errors(p.read_text(errors='replace'))]
            if errors:
                row.update(disposition='PRODUCT_IMPORT_FAILURE', product_failure_logs=errors,
                           evaluated_failure_score=evaluated_failure_score(out))
            return row
        from .native_log import godot_product_errors
        product_logs = [str(p.relative_to(out)) for p in (out/'takes').glob('*/record/import.log')
                        if godot_product_errors(p.read_text(errors='replace'))]
        if product_logs:
            failure_score = evaluated_failure_score(out)
            if failure_score is not None or not any(t['complete'] for t in takes):
                row.update(disposition='PRODUCT_IMPORT_FAILURE', product_failure_logs=product_logs,
                           evaluated_failure_score=failure_score)
                return row
        with existing_locks(out):
            short = [t for t in takes if not t['complete'] or type(t['duration_ms']) not in (int,float) or t['duration_ms'] < required]
            if not short:
                row['native_evidence'] = [native_evidence(out,t['take'],full_window=True,required_ms=required) for t in takes]
                row.update(window_qualified=True, disposition='KEEP_EXISTING_75S')
                return row
            if row['native_count'] >= MAX_TAKES or len(takes) >= MAX_TAKES:
                row['disposition'] = 'BLOCKED_MAX_TAKES'
                return row
            require([t['take'] for t in takes] == [1] and row['native_count'] == 1, 'not exactly one first native take')
            hold = out/'qualification_hold.json'
            if hold.exists():
                h = read_json(hold)
                require(h.get('kind') == HOLD_KIND and h.get('qualified') is False
                        and h.get('recovery') == str(LINEAGE), 'unknown qualification hold')
            proof = native_evidence(out,1)
            require(proof['duration_ms'] < required and proof['recording_ms'] is None, 'not missing recording_ms short take')
            require(proof['observation_plan'] == str(out/'takes/1/plan.json')
                    and not (out/'takes/1/record/recording_plan.json').exists(), 'unexpected recording configuration')
            ex = read_json(out/'takes/1/record/execution.json')
            plan = read_json(out/'takes/1/plan.json')
            require([p['id'] for p in ex['probes']] == [p['id'] for p in plan['probes']]
                    and all(p.get('status') == 'EXECUTED' for p in ex['probes']), 'short take not normal completed plan')
            end = max(p['end_ms'] for p in ex['probes'])
            require(450 <= proof['duration_ms'] - end <= 1500, 'not normal 500ms tail completion')
            require('PILOT_COMPLETE ' in (out/'takes/1/record/engine.log').read_text(), 'normal recorder finish missing')
            row.update(accepted_plan=accepted(out), source=source_proof(out,manifest), native_evidence=[proof])
            if bind:
                before = parent_files(out)
                row['parent_files'] = before
                row['parent_digest'] = digest(before)
                row['production'] = production()
                require(parent_files(out) == before, 'parent changed during qualification')
            row.update(eligible=True, disposition='ELIGIBLE_ONE_SHORT_TAKE')
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        row.update(eligible=False, window_qualified=False, disposition='BLOCKED_QUALIFICATION', reason=f'{type(exc).__name__}: {exc}')
    return row


def audit(root):
    root = Path(root).absolute()
    results = []
    for out in sorted(root.glob('*/*/retest')):
        q = qualification(out)
        if q.get('engine') == 'godot' or q['disposition'] == 'MISSING':
            results.append(q)
    counts = {}
    for q in results:
        counts[q['disposition']] = counts.get(q['disposition'],0) + 1
    return {'version': VERSION, 'root': str(root), 'read_only': True, 'counts': counts, 'results': results}


@contextmanager
def locked(out):
    with (out/'.godot_duration.lock').open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _OWNED_LOCKS.add(out/'.godot_duration.lock')
        try:
            yield
        finally:
            _OWNED_LOCKS.remove(out/'.godot_duration.lock')


def check_space(out, estimated_bytes=0):
    free = shutil.disk_usage(out).free
    require(free >= 8 * 1024**3 + estimated_bytes, 'less than 8GiB reserve plus estimated recovery copies')
    return {'free_bytes': free, 'estimated_bytes': estimated_bytes, 'reserve_bytes': 8 * 1024**3}


def process_check(out):
    ps = subprocess.run(['ps', '-axo', 'pid,ppid,command'], capture_output=True, text=True, check=True)
    paths = [str(out/'runtime/project'), str(out/LINEAGE/'child/runtime/project')]
    matching = [line for line in ps.stdout.splitlines() if any(path in line for path in paths)]
    require(not matching, 'parent/child runtime process still exists; preserve and inspect')
    return {'runtime_processes': [], 'external_processes_modified': False}


def archive(files, source, target):
    for name, expected in files.items():
        src, dst = source/name, target/name
        require(sha256(src) == expected, f'archive source drift: {src}')
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        require(sha256(dst) == expected, f'archive mismatch: {dst}')


def _prepared(out):
    target = out/LINEAGE
    saved = read_json(target/'prepared.json')
    require(saved['version'] == VERSION and saved['parent'] == str(out), 'wrong prepared lineage')
    require(parent_files(out) == saved['parent_files'], 'parent or hold drift')
    require(tree(target/'parent_archive') == saved['parent_files'], 'parent archive drift')
    manifest = read_json(out/'manifest.json')
    require(source_proof(out, manifest) == saved['source'], 'source drift since preparation')
    require(accepted(out) == saved['accepted_plan'], 'accepted plan drift since preparation')
    child = target/'child'
    require(read_json(child/'manifest.json') == manifest, 'child manifest differs')
    prepare.verify(child)
    require(sha256(child/'takes/1/plan.json') == saved['accepted_plan']['plan_sha256'], 'child plan bytes changed')
    require(tree(child/'model_calls') == tree(out/'model_calls'), 'child model calls differ or added')
    require(sorted(p.name for p in (child/'takes').iterdir()) == ['1'], 'extra child take')
    require(tree(target/'production_prepared') == saved['prepared_production'], 'prepared producer archive drift')
    return saved


def prepare_child(out):
    """Prepare only; parent native take + at most one child native take = two."""
    out = Path(out).absolute()
    plain(out)
    with locked(out):
        target = out/LINEAGE
        if (target/'prepared.json').is_file():
            return _prepared(out)
        require(not target.exists(), 'partial recovery exists; no reset/retry')
        q = qualification(out)
        require(q['eligible'], f"not eligible: {q['disposition']}: {q.get('reason','')}")
        process = process_check(out)
        estimate = sum((out/name).stat().st_size for name in q['parent_files']) + 3 * sum(
            (Path(q['source']['path'])/name).stat().st_size for name in q['source']['files'])
        space = check_space(out, estimate)
        hold = out/'qualification_hold.json'
        if not hold.exists():
            write_json(hold, {'kind': HOLD_KIND, 'qualified': False,
                             'reason': 'one consumed native ended before effective75s; replacement requires verified real child',
                             'recovery': str(LINEAGE)})
        q = qualification(out)
        require(q['eligible'], 'qualification changed before preparation')
        target.mkdir(parents=True)
        archive(q['parent_files'], out, target/'parent_archive')
        producer = production()
        archive(producer, ROOT, target/'production_prepared')
        child = target/'child'
        child.mkdir()
        shutil.copy2(out/'manifest.json', child/'manifest.json')
        shutil.copytree(out/'input', child/'input', ignore=lambda directory,names:
                        ['project'] if Path(directory) == out/'input' else [])
        shutil.copytree(Path(q['source']['path']), child/'input/project', ignore=prepare.IGNORE)
        shutil.copytree(child/'input/project', child/'runtime/project')
        shutil.copytree(out/'model_calls', child/'model_calls')
        (child/'takes/1').mkdir(parents=True)
        for name in ('plan.json','plan_coverage.json'):
            src = out/'takes/1'/name
            if src.is_file(): shutil.copy2(src,child/'takes/1'/name)
        prepare.verify(child)
        require(parent_files(out) == q['parent_files'], 'parent changed while preparing child')
        saved = {'version': VERSION, 'parent': str(out), 'parent_files': q['parent_files'],
                 'parent_digest': q['parent_digest'], 'source': q['source'],
                 'accepted_plan': q['accepted_plan'], 'parent_native_evidence': q['native_evidence'],
                 'prepared_production': producer, 'space': space, 'process_check': process,
                 'native_takes_before': 1, 'remaining_native_takes': 1, 'model_calls_allowed': 0}
        write_json(target/'prepared.json',saved)
        _prepared(out)
        return saved


def _score(out, verdicts, evidence):
    from ..stage1 import playable_rules
    manifest = read_json(out/'manifest.json')
    checks = {k: verdicts.get(k,{}).get('status','HARNESS_ERROR') for k in playable_rules.IDS}
    require('HARNESS_ERROR' not in checks.values(), 'rules did not reach complete determinate outcome')
    return {'version': playable_rules.VERSION, 'game_id': manifest['game_id'], 'engine': 'godot',
            'planner': manifest['models']['planner'], 'checks': checks, 'complete': True,
            'playable': round(100 * sum(v == 'PASS' for v in checks.values()) / 3, 2),
            'takes': [{'take': 1, 'origin': 'parent', 'qualified_75s': False,
                       'duration_ms': read_json(out/'takes/1/record/execution.json')['duration_ms'], 'consumed': True},
                      {'take': 2, 'origin': str(LINEAGE/'child/takes/1'), 'qualified_75s': True,
                       'duration_ms': evidence['duration_ms'], 'consumed': True, 'checks': checks}],
            'native_takes_consumed': 2, 'max_native_takes': 2, 'model_calls_added': 0,
            'window_qualified': True, 'publication_status': 'SCORED_PENDING_AUDIT'}


def _verify_child(out):
    target = out/LINEAGE
    saved = _prepared(out)
    child = target/'child'
    dispatch = read_json(target/'dispatch.json')
    require(dispatch['prepared_sha256'] == sha256(target/'prepared.json'), 'dispatch/prepared mismatch')
    require(tree(target/'production_dispatch') == dispatch['production'], 'dispatch producer archive drift')
    require(dispatch['production'] == read_json(target/'finished.json')['production_after'], 'producer changed during native')
    # Verify with the actual rules/verifier version; unrelated producer evolution is archived.
    for name in ('godot_duration_recovery.py','playable_rules.py','native_log.py','prepare.py','paths.py'):
        key = 'pipeline/eval/stage1/'+name
        require(sha256(Path(__file__).with_name(name)) == dispatch['production'][key], 'offline verifier/rules producer drift')
    require(plan_dependency(Path(__file__).with_name('plan.py')) ==
            plan_dependency(target/'production_dispatch/pipeline/eval/stage1/plan.py'),
            'offline plan dependency drift')
    require(read_json(target/'finished.json')['success'] is True, 'native failed')
    live = [p for p in target.glob('**/takes/*/record') if 'parent_archive' not in p.relative_to(target).parts
            and ((p/'native').exists() or (p/'execution.json').exists())]
    require(live == [child/'takes/1/record'], 'extra native descendant; max2 exhausted')
    authored = prepare.tree_hashes(child/'runtime/project')
    frozen = saved['source']['snapshot_files']
    require(all(authored.get(k) == v for k,v in frozen.items())
            and all(k.startswith('.godot/') for k in authored.keys()-frozen.keys()), 'child runtime author drift')
    q = inventory(child)
    require(len(q) == 1 and q[0]['consumed'], 'wrong child native count')
    proof = native_evidence(child,1,full_window=True)
    require(proof['observation_plan'] == str(child/'takes/1/record/recording_plan.json'), 'child did not use fixed recording configuration')
    require(proof['plan_max_duration_ms'] == saved['accepted_plan']['max_duration_ms'], 'child plan ceiling changed')
    require(tree(child/'model_calls') == tree(out/'model_calls'), 'new model call detected')
    return proof


def execute(out):
    """Explicit single dispatch. No plan call, loop, retry, or second child take."""
    out = Path(out).absolute()
    prepare_child(out)
    with locked(out):
        target = out/LINEAGE
        if (target/'replacement.json').exists():
            score = qualified_replacement_score(out)
            require(score is not None, 'existing replacement invalid')
            return score
        saved = _prepared(out)
        require(not (target/'dispatch.json').exists(), 'child native slot already consumed/reserved; no retry')
        child = target/'child'
        require(not (child/'takes/1/record').exists(), 'partial child record exists; no retry')
        process, space = process_check(out), check_space(out,256*1024**2)
        from ..stage1 import record, playable_rules
        # This module is invoked in a fresh process; pin disk producer at dispatch.
        producer = production()
        archive(producer,ROOT,target/'production_dispatch')
        binary = record.godot_executable()
        require(binary, 'Godot binary unavailable')
        dispatch = {'version': VERSION, 'prepared_sha256': sha256(target/'prepared.json'),
                    'production': producer, 'binary': str(binary), 'binary_sha256': sha256(Path(binary)),
                    'process_check': process, 'space': space, 'global_native_take': 2,
                    'model_calls_allowed': 0, 'native_slots_remaining_after_dispatch': 0}
        write_json(target/'dispatch.json',dispatch)
        manifest = read_json(child/'manifest.json')
        short = {**manifest, 'budget': effective_budget(manifest)}
        try:
            record.record(child,short,read_json(child/'takes/1/plan.json'),1)
            write_json(target/'finished.json',{'success':True,'production_after':production()})
            proof = _verify_child(out)
            verdicts = playable_rules.evaluate(child,manifest,1)
            result = _score(out,verdicts,proof)
            write_json(child/'playable_score.json',result)
            write_json(target/'native_proof.json',proof)
            require(parent_files(out) == saved['parent_files'], 'parent drift after native/rules')
            write_json(target/'replacement.json',{'version':VERSION,'qualified':True,
                       'prepared_sha256':sha256(target/'prepared.json'),
                       'dispatch_sha256':sha256(target/'dispatch.json'),
                       'finished_sha256':sha256(target/'finished.json'),
                       'proof_sha256':sha256(target/'native_proof.json'),
                       'child_files':tree(child), 'score_sha256':sha256(child/'playable_score.json'),
                       'native_takes_consumed':2, 'model_calls_added':0})
            verified = qualified_replacement_score(out)
            require(verified == result, 'replacement failed independent verification')
            return verified
        except Exception as exc:
            write_json(target/'failure.json', {'type':type(exc).__name__, 'error':str(exc),
                                             'native_slot_consumed':True,'retry_allowed':False})
            raise


def qualified_replacement_score(out):
    """Fail closed; hash binding alone cannot manufacture a duration or score."""
    out = Path(out).absolute()
    try:
        target = out/LINEAGE
        receipt = read_json(target/'replacement.json')
        require(receipt['version'] == VERSION and receipt['qualified'] is True
                and receipt['native_takes_consumed'] == 2 and receipt['model_calls_added'] == 0, 'invalid replacement')
        for name,key in (('prepared.json','prepared_sha256'),('dispatch.json','dispatch_sha256'),
                         ('finished.json','finished_sha256'),('native_proof.json','proof_sha256')):
            require(sha256(target/name) == receipt[key], 'receipt hash mismatch')
        child = target/'child'
        require(tree(child) == receipt['child_files'] and sha256(child/'playable_score.json') == receipt['score_sha256'], 'child evidence/score drift')
        proof = _verify_child(out)
        require(proof == read_json(target/'native_proof.json'), 'native proof changed')
        # Re-run unchanged deterministic rules in temporary output, never child/parent.
        import tempfile
        from ..stage1 import playable_rules
        with tempfile.TemporaryDirectory(prefix='godot-duration-verify-') as temp:
            verdicts = playable_rules.evaluate(child,read_json(child/'manifest.json'),1,report_dir=Path(temp))
            for name in ('verdicts_playable_rules.json','playable_rules.json'):
                require(read_json(Path(temp)/name) == read_json(child/name), 'rules output changed')
        result = _score(out,verdicts,proof)
        require(result == read_json(child/'playable_score.json'), 'score inconsistent with unchanged rules')
        return result
    except (OSError,ValueError,KeyError,TypeError,RuntimeError):
        return None


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('out', type=Path)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--audit', action='store_true')
    actions.add_argument('--prepare', action='store_true')
    actions.add_argument('--execute', action='store_true')
    actions.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    result = (audit(args.out) if args.audit else prepare_child(args.out) if args.prepare
              else execute(args.out) if args.execute else qualified_replacement_score(args.out) if args.verify
              else qualification(args.out))
    print(json.dumps(result,ensure_ascii=False,indent=2))
