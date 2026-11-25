"""Bounded Sol G005 IMGUI transport recovery; preview is read-only.

This helper never plans, calls a model, changes the parent score/hold, or edits an
original. After approval it archives the diagnostic parent, creates a fixed child
with exact source copies and both accepted plans, and records at most once per
saved plan. Partial attempts consume their claim and require separate review.
A separate finalize command runs official cached scoring and seals a qualified
replacement. The parent score and qualification hold remain untouched.
"""
from __future__ import annotations

from ..model_config import PLANNER_MODEL

import argparse
from contextlib import ExitStack, contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import time

from ..stage1 import plan, prepare
from ..stage1.paths import read_json, sha256, write_json

VERSION = 'stage1-unity-imgui-transport-recovery.v1'
LINEAGE = 'recovery/unity_imgui_forward_v1'
CASE = 'G005_broken_realm_echo'
SOURCE_SHA = '0174ea0634222c2801f2108290981e4c02c4afccbd653da076213b11af1cffbf'
ACCEPTED = {
    1: '440078e634f349a6159c742d4ed9193a8cf167c018fe4c989378d20eab680f1e',
    2: '2d01b4dd99d3efaed636e37d83f116b9a62e635ba3751adcfd5b43c382454224',
}
RESERVE = 8 * 1024 ** 3
ENV_KEY = 'GAMEFACTORY_UNITY_IMGUI_FORWARD'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def files(root: Path, *, parent=False):
    """Hash every retained byte, refusing symlinks; exclude only our lineage/locks."""
    require(root.is_dir() and not root.is_symlink(), f'not a plain directory: {root}')
    result = {}
    for directory, dirs, names in os.walk(root, followlinks=False):
        base = Path(directory)
        if parent and base == root:
            dirs[:] = [d for d in dirs if d != 'recovery']
        for name in dirs + names:
            require(not (base / name).is_symlink(), f'symlink rejected: {base / name}')
        for name in names:
            p = base / name
            if name in {'.postprocess.lock', '.imgui-recovery.lock'}:
                continue
            require(p.is_file(), f'non-file artifact: {p}')
            result[str(p.relative_to(root))] = sha256(p)
    return result


def production():
    """Current producer binding, never an attestation of historical production."""
    root = Path(__file__).resolve().parents[3]
    roots = [root / 'pipeline/eval/stage1', root / 'pipeline/eval/model_config.py', root / 'engine_adapters/unity3d',
             root / 'engine_adapters/common']
    return {str(p.relative_to(root)): sha256(p) for folder in roots for p in ([folder] if folder.is_file() else sorted(folder.rglob('*')))
            if p.is_file() and p.suffix in {'.py', '.cs', '.json'}
            and '__pycache__' not in p.parts}


def short_manifest(manifest):
    budget = dict(manifest['budget'])
    extra = 75000 - budget['gameplay_ms']
    for key in ('gameplay_ms', 'recording_ms', 'total_wall_clock_ms'):
        budget[key] += extra
    budget['engine_call_ms'] = max(budget['engine_call_ms'] + extra, budget['total_wall_clock_ms'])
    return {**manifest, 'budget': budget}


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def cleanup_ok(record_dir):
    native = record_dir / 'native'
    editor = read_json(native / 'editor_cleanup.json')
    require(all(editor.get(k) is True for k in ('ok', 'process_exit_verified',
            'group_exit_verified', 'detached_exit_verified')), 'editor cleanup not proven')
    require(read_json(record_dir / 'editor_cleanup.json') == editor, 'editor cleanup differs')
    inputs = read_json(native / 'background_input_cleanup.json')
    require(all(inputs.get(k) is True for k in ('ok', 'keys_and_buttons_released',
            'virtual_devices_removed', 'settings_restored', 'muted_devices_restored',
            'input_filter_removed')), 'input cleanup not proven')
    require(read_json(native / 'background_view_cleanup.json').get('ok') is True,
            'view cleanup not proven')


def transport(record_dir, executable, *, queued):
    trace = rows(record_dir / 'actions.jsonl')
    require(trace == rows(record_dir / 'native/actions.jsonl'), 'canonical/native actions differ')
    expected = plan.native_actions(executable, 'unity3d')
    require(read_json(record_dir / 'action_schedule.json')['actions'] == expected,
            'action schedule differs from accepted plan')
    clicks = [a for a in expected if a['action'] == 'mouse_click']
    require(clicks, 'accepted plan has no mouse click')
    for action in clicks:
        actual = [r for r in trace if r.get('action_id') == action['action_id']
                  and not r.get('cleanup_release')]
        require(len(actual) == 2 and {r.get('phase') for r in actual} == {'down', 'up'},
                'mouse down/up delivery incomplete')
        require(all(r.get('sent') is True and r.get('imgui_queued') is queued
                    and r.get('source') == 'internal_driver'
                    and r.get('transport') == 'InputSystem.QueueStateEvent'
                    and not r.get('error') and r.get('action') == 'mouse_click'
                    and r.get('button') == action.get('button')
                    and all(r.get(k) == struct.unpack('<f', struct.pack('<f', action[k]))[0]
                            for k in ('x', 'y'))
                    for r in actual), 'mouse transport is not the required state')
    require(not any(r.get('sent') is False or r.get('ok') is False for r in trace),
            'native input failed')
    return len(clicks)


def accepted_plans(out, manifest):
    for take in (1, 2):
        folder = out / f'model_calls/plan_t{take}'
        accepted = read_json(folder / 'accepted_response.json')
        require(accepted.get('path') == 'response.json'
                and accepted.get('sha256') == ACCEPTED[take] == sha256(folder / 'response.json'),
                'accepted response identity changed')
        invocation = read_json(folder / 'invocation.json')
        require(invocation.get('model_requested') == PLANNER_MODEL
                and invocation.get('exit_code') == 0, 'accepted planner provenance missing')
        executable = read_json(out / f'takes/{take}/plan.json')
        require(executable == read_json(folder / 'response.json'), 'saved/accepted plan mismatch')
        require(executable['max_duration_ms'] == 75000, 'plan duration changed')
        plan.validate(executable, short_manifest(manifest), Path(manifest['project_source']))


def preview(out: Path):
    out = Path(out).absolute()
    require(out.resolve() == out, 'parent path traverses a symlink')
    recovery = out / 'recovery'
    require(not recovery.is_symlink(), 'recovery directory symlink rejected')
    require(not recovery.exists() or {p.name for p in recovery.iterdir()} <= {'unity_imgui_forward_v1'},
            'another recovery lineage exists; coordinate before proceeding')
    require({p.name for p in (out / 'takes').iterdir()} == {'1', '2'}, 'unexpected diagnostic takes')
    manifest = read_json(out / 'manifest.json')
    require(manifest['game_id'] == CASE and manifest['engine'] == 'unity3d'
            and manifest['delivery']['model'] == 'sol' and manifest['suite'] == 'stage1'
            and manifest['models'] == {'planner': PLANNER_MODEL, 'judge': 'none'},
            'not the authorized Sol G005 identity')
    source = Path(manifest['project_source'])
    require(source.resolve() == source and source == Path(manifest['delivery']['project_root']),
            'original path identity mismatch')
    require(not out.is_relative_to(source) and not source.is_relative_to(out), 'source overlaps output')
    files(source)  # refuse source symlinks even though prepare.tree_hashes ignores them
    require(manifest['project_digest'] == manifest['snapshot_digest'] == SOURCE_SHA
            == prepare.tree_digest(prepare.tree_hashes(source)), 'original source digest mismatch')
    require(not (out / 'input/project').exists() and not (out / 'runtime/project').exists(),
            'parent project copies present: possible running/restored identity')
    hold = read_json(out / 'qualification_hold.json')
    require(hold.get('kind') == 'HARNESS_UI_INPUT_NOT_DELIVERED'
            and hold.get('affected_takes') == [1, 2], 'qualification hold mismatch')
    require(set(read_json(out / 'cleanup.json')['removed']) == {'input/project', 'runtime/project'},
            'deleted-copy provenance missing')
    require(prepare.tree_hashes(out / 'input') == manifest['input_hashes']
            and sha256(out / 'input/criteria.json') == manifest['criteria_sha256'],
            'frozen input metadata changed')
    accepted_plans(out, manifest)
    for take in (1, 2):
        record_dir = out / f'takes/{take}/record'
        cleanup_ok(record_dir)
        transport(record_dir, read_json(out / f'takes/{take}/plan.json'), queued=False)
        result = read_json(record_dir / 'record_result.json')
        require(result['plan_sha256'] == sha256(out / f'takes/{take}/plan.json')
                and result['engine'] == 'unity3d' and result['take'] == take,
                'old record identity mismatch')
    inventory = files(out, parent=True)
    source_bytes = sum((source / p).stat().st_size for p in prepare.tree_hashes(source))
    archive_bytes = sum((out / p).stat().st_size for p in inventory)
    # Two exact-source copies, another historical working-copy allowance, and evidence.
    required = archive_bytes * 2 + source_bytes * 2 + max(
        int(read_json(out / 'cleanup.json')['freed_bytes']), 2 * 1024 ** 3) + RESERVE
    binding = {'version': VERSION, 'parent': str(out), 'manifest_sha256': sha256(out / 'manifest.json'),
               'parent_files': inventory, 'source_sha256': SOURCE_SHA, 'production': production(),
               'max_native_calls': 2, 'accepted_responses': ACCEPTED}
    return {'review_sha256': digest(binding), 'binding': binding,
            'required_free_bytes': required, 'free_bytes': shutil.disk_usage(out).free,
            'child': str(out / LINEAGE / 'run'), 'state': 'PREVIEW_ONLY'}


@contextmanager
def locked(path):
    require(not path.is_symlink(), 'lock symlink rejected')
    with path.open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError(f'identity already active: {path}') from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def exclusive_json(path, value):
    with path.open('x') as handle:
        json.dump(value, handle, indent=2)
        handle.flush()
        os.fsync(handle.fileno())


def verify_child(child, manifest):
    require(read_json(child / 'manifest.json') == manifest, 'child manifest changed')
    prepare.verify(child)
    require(prepare.tree_digest(prepare.tree_hashes(Path(manifest['project_source']))) == SOURCE_SHA,
            'original changed after restore')
    accepted_plans(child, manifest)


def restore(out, checked):
    """Called only with identity locks and an approved review binding."""
    lineage, child = out / LINEAGE, out / LINEAGE / 'run'
    require(lineage.resolve() == lineage and child.resolve() == child, 'lineage path symlink')
    receipt = lineage / 'prepared.json'
    require(not receipt.is_symlink(), 'prepared receipt symlink')
    manifest = read_json(out / 'manifest.json')
    if lineage.exists():
        require(receipt.is_file(), 'partial preparation retained; separate review required')
        require(read_json(receipt)['review_sha256'] == checked['review_sha256'],
                'existing lineage belongs to different review/producer')
        require(files(lineage / 'archive') == checked['binding']['parent_files'], 'archive changed')
        verify_child(child, manifest)
        return child
    require(checked['free_bytes'] >= checked['required_free_bytes'], 'insufficient disk reserve')
    lineage.mkdir(parents=True)
    archive = lineage / 'archive'
    archive.mkdir()
    for name in checked['binding']['parent_files']:
        target = archive / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(out / name, target)
    require(files(archive) == checked['binding']['parent_files'] == files(out, parent=True),
            'parent changed during archive')
    child.mkdir()
    shutil.copy2(archive / 'manifest.json', child / 'manifest.json')
    shutil.copytree(archive / 'input', child / 'input')
    shutil.copytree(archive / 'model_calls', child / 'model_calls')
    for take in (1, 2):
        folder = child / f'takes/{take}'
        folder.mkdir(parents=True)
        shutil.copy2(archive / f'takes/{take}/plan.json', folder / 'plan.json')
    source = Path(manifest['project_source'])
    for name in ('input/project', 'runtime/project'):
        shutil.copytree(source, child / name, ignore=prepare.IGNORE)
        require(prepare.tree_digest(prepare.tree_hashes(child / name)) == manifest['snapshot_digest'],
                'restored copy differs from frozen source')
    verify_child(child, manifest)
    exclusive_json(receipt, checked)
    return child


def validate_new_record(child, take, executable):
    record_dir = child / f'takes/{take}/record'
    cleanup_ok(record_dir)
    clicks = transport(record_dir, executable, queued=True)
    result = read_json(record_dir / 'record_result.json')
    report = read_json(record_dir / 'native/report.json')
    require(result['plan_sha256'] == sha256(child / f'takes/{take}/plan.json')
            and result['engine'] == 'unity3d' and result['take'] == take
            and not result['failed_actions'], 'repaired record identity/failure mismatch')
    require(report.get('status') == 'passed' and report.get('engine') == 'unity3d'
            and report.get('requested_seconds') == 75 and not report.get('errors')
            and Path(report['url']).resolve() == (child / 'runtime/project').resolve()
            and Path(report['output_dir']).resolve() == (record_dir / 'native').resolve(),
            'native report incomplete or belongs to another run')
    frames = rows(record_dir / 'frame_index.jsonl')
    require(frames == rows(record_dir / 'native/frame_index.jsonl')
            and len(frames) == result['frames'] == report['frames'] and len(frames) > 1,
            'native/canonical frame inventory mismatch')
    for row in frames:
        rel = Path(row['path'])
        require(not rel.is_absolute() and '..' not in rel.parts and rel.parts[0] == 'frames',
                'frame path escapes recording')
        require(sha256(record_dir / rel) == sha256(record_dir / 'native' / rel),
                'native frame pixels changed')
    return {'mouse_clicks_forwarded': clicks, 'native_frames': len(frames)}


def execute(out, expected_review):
    """At most two official record calls, each durably claimed before invocation.

    No scoring/model/pipeline entry point is called here. Existing accepted plans
    are consumed directly. Parent publication and cleanup remain explicit review
    work; the old diagnostic score and qualification hold stay byte-identical.
    """
    from ..stage1 import playable_rules, record
    out = Path(out).absolute()
    require(out.resolve() == out, 'parent path traverses a symlink')
    with ExitStack() as stack:
        stack.enter_context(locked(out / '.imgui-recovery.lock'))
        for take in (1, 2):
            stack.enter_context(locked(out / f'takes/{take}/record/.postprocess.lock'))
        require(not (out / LINEAGE / 'finalization.json').exists(),
                'finalization already started; use qualified replacement or inspect retained failure')
        checked = preview(out)
        require(checked['review_sha256'] == expected_review, 'review binding changed; preview/review again')
        child = restore(out, checked)
        lineage = out / LINEAGE
        manifest = read_json(child / 'manifest.json')
        results = []
        previous_env = os.environ.get(ENV_KEY)
        os.environ[ENV_KEY] = '1'
        try:
            for take in (1, 2):
                verify_child(child, manifest)
                require(production() == checked['binding']['production'], 'producer changed after review')
                require(files(out, parent=True) == checked['binding']['parent_files'], 'parent changed')
                executable = read_json(child / f'takes/{take}/plan.json')
                claim = lineage / f'take{take}.claim.json'
                completed = child / f'takes/{take}/record/record_result.json'
                if claim.exists():
                    old = read_json(claim)
                    require(old['review_sha256'] == expected_review and old['take'] == take
                            and old['plan_sha256'] == sha256(child / f'takes/{take}/plan.json'),
                            'native claim binding changed')
                    require(completed.is_file(), 'consumed native claim is incomplete; no retry allowed')
                else:
                    require(not (child / f'takes/{take}/record').exists(),
                            'unclaimed record artifacts; separate review required')
                    require(shutil.disk_usage(out).free >= RESERVE + 2 * 1024 ** 3,
                            'insufficient native disk reserve')
                    exclusive_json(claim, {'version': VERSION, 'review_sha256': expected_review,
                        'take': take, 'plan_sha256': sha256(child / f'takes/{take}/plan.json'),
                        'at_unix': time.time(), 'pid': os.getpid(), 'environment': {ENV_KEY: '1'},
                        'parent_diagnostic_take': str(out / f'takes/{take}'),
                        'max_native_calls': 2})
                    try:
                        record.record(child, short_manifest(manifest), executable, take)
                    except Exception as exc:
                        exclusive_json(lineage / f'take{take}.failure.json',
                                       {'type': type(exc).__name__, 'error': str(exc)})
                        raise
                files(child / f'takes/{take}/record')  # no evidence symlinks
                proof = validate_new_record(child, take, executable)
                verify_child(child, manifest)
                verdicts = playable_rules.evaluate(child, manifest, take)
                require(all(v.get('status') != 'HARNESS_ERROR' for v in verdicts.values()),
                        'playable rules report a harness failure')
                results.append({'take': take, 'transport': proof, 'verdicts': verdicts})
                if verdicts['play.operate']['status'] == 'PASS' or verdicts['play.launch']['status'] == 'FAIL':
                    break
            require(files(out, parent=True) == checked['binding']['parent_files'], 'parent changed')
            require(production() == checked['binding']['production'], 'producer changed during recording')
            receipt = {'version': VERSION, 'state': 'RECORDED_PENDING_PARENT_REVIEW',
                       'review_sha256': expected_review, 'child': str(child), 'takes': results,
                       'native_calls_consumed': len(list(lineage.glob('take*.claim.json'))),
                       'old_diagnostic_takes_preserved': [1, 2], 'parent_hold_retained': True,
                       'child_evidence': files(child), 'models_invoked': 0, 'cache_deleted_bytes': 0}
            write_json(lineage / 'ready_for_review.json', receipt)
            return receipt
        finally:
            if previous_env is None:
                os.environ.pop(ENV_KEY, None)
            else:
                os.environ[ENV_KEY] = previous_env


REPLACEMENT_SCHEMA = 'stage1-playable-qualified-replacement.v1'
FINALIZATION_SCHEMA = 'stage1-playable-cached-finalization.v1'
CACHE_PARTS = ('input/project', 'runtime/project')


def retained_files(child):
    return {k: v for k, v in files(child).items()
            if k != 'cleanup.json' and not any(k.startswith(part + '/') for part in CACHE_PARTS)}


def _parent_and_archive(out, prepared):
    binding = prepared['binding']
    require(binding['version'] == VERSION and binding['parent'] == str(out)
            and digest(binding) == prepared['review_sha256'], 'prepared binding is invalid')
    require(files(out, parent=True) == binding['parent_files'], 'parent diagnostic evidence changed')
    require(files(out / LINEAGE / 'archive') == binding['parent_files'], 'parent archive changed')
    manifest = read_json(out / 'manifest.json')
    require(sha256(out / 'manifest.json') == binding['manifest_sha256']
            and manifest['game_id'] == CASE and manifest['engine'] == 'unity3d'
            and manifest['delivery']['model'] == 'sol'
            and manifest['models'] == {'planner': PLANNER_MODEL, 'judge': 'none'}
            and manifest['project_digest'] == manifest['snapshot_digest'] == SOURCE_SHA
            == binding['source_sha256'], 'replacement source identity changed')
    source = Path(manifest['project_source'])
    require(source.resolve() == source and source == Path(manifest['delivery']['project_root']),
            'original source path identity changed')
    files(source)
    require(prepare.tree_digest(prepare.tree_hashes(source)) == SOURCE_SHA,
            'original source changed after recording')
    return manifest


def _ready(out, prepared, *, check_child=True):
    lineage, child = out / LINEAGE, out / LINEAGE / 'run'
    ready = read_json(lineage / 'ready_for_review.json')
    require(ready['version'] == VERSION and ready['state'] == 'RECORDED_PENDING_PARENT_REVIEW'
            and ready['review_sha256'] == prepared['review_sha256'] and ready['child'] == str(child)
            and ready['models_invoked'] == 0 and ready['parent_hold_retained'] is True
            and ready['old_diagnostic_takes_preserved'] == [1, 2], 'ready receipt identity mismatch')
    takes = [t['take'] for t in ready['takes']]
    require(takes in ([1], [1, 2]) and ready['native_calls_consumed'] == len(takes),
            'ready receipt exceeds native take bound')
    require({p.name for p in lineage.glob('take*.claim.json')}
            == {f'take{t}.claim.json' for t in takes}, 'native claims differ from ready receipt')
    require(not list(lineage.glob('take*.failure.json')), 'native failure claims remain unresolved')
    for take in takes:
        claim = read_json(lineage / f'take{take}.claim.json')
        require(claim['review_sha256'] == prepared['review_sha256'] and claim['take'] == take
                and claim['plan_sha256'] == sha256(child / f'takes/{take}/plan.json')
                and claim['environment'] == {ENV_KEY: '1'}, 'native claim provenance changed')
    if check_child:
        require(files(child) == ready['child_evidence'], 'ready child evidence changed')
    return ready


@contextmanager
def _cached_pipeline(pipeline, child, manifest, ready):
    """Process-local adapters forbid planner/native fallback in official pipeline.

    This CLI owns its Python process. No production file or other worker is changed;
    references are restored even on exceptions. A request outside the ready receipt
    is a hard error, never permission for another plan or recording.
    """
    from types import SimpleNamespace
    permitted = {t['take'] for t in ready['takes']}
    old_plan, old_record = pipeline.plan, pipeline.record

    def cached_plan(out, short, take=1, *args, **kwargs):
        require(Path(out).resolve() == child and short == short_manifest(manifest)
                and take in permitted, 'pipeline requested an unqualified cached take')
        path = child / f'takes/{take}/plan.json'
        require(sha256(path) == ready['child_evidence'][str(path.relative_to(child))],
                'cached plan changed during finalization')
        return read_json(path)

    def cached_record(out, short, executable, take=1):
        require(executable == cached_plan(out, short, take), 'cached record plan mismatch')
        path = child / f'takes/{take}/record/record_result.json'
        require(sha256(path) == ready['child_evidence'][str(path.relative_to(child))],
                'cached record changed during finalization')
        return read_json(path)

    pipeline.plan = SimpleNamespace(make_plan=cached_plan, take_dir=plan.take_dir)
    pipeline.record = SimpleNamespace(record=cached_record)
    try:
        yield
    finally:
        pipeline.plan, pipeline.record = old_plan, old_record


def finalize(out, expected_review):
    """Official cached scoring, then immutable replacement receipt; no cache deletion.

    The parent runner may call its existing cleanup(child) after qualification.
    qualified_replacement_score supports either exact copies or that exact cleanup.
    """
    from ..stage1 import pipeline
    out = Path(out).absolute()
    require(out.resolve() == out, 'parent path traverses a symlink')
    lineage, child = out / LINEAGE, out / LINEAGE / 'run'
    with ExitStack() as stack:
        stack.enter_context(locked(out / '.imgui-recovery.lock'))
        for take in (1, 2):
            stack.enter_context(locked(out / f'takes/{take}/record/.postprocess.lock'))
        require(lineage.resolve() == lineage and child.resolve() == child, 'lineage path symlink')
        for name in ('prepared.json', 'ready_for_review.json', 'finalization.json', 'replacement.json'):
            require(not (lineage / name).is_symlink(), 'receipt symlink rejected')
        prepared = read_json(lineage / 'prepared.json')
        require(prepared['review_sha256'] == expected_review, 'finalization review mismatch')
        if (lineage / 'replacement.json').exists():
            score = qualified_replacement_score(out)
            require(score is not None, 'existing qualified replacement failed validation')
            return read_json(lineage / 'replacement.json')
        require(not (lineage / 'finalization.json').exists(),
                'partial finalization retained; inspect before resuming')
        manifest = _parent_and_archive(out, prepared)
        require(production() == prepared['binding']['production'], 'producer changed before finalization')
        ready = _ready(out, prepared)
        verify_child(child, manifest)
        for row in ready['takes']:
            take = row['take']
            stack.enter_context(locked(child / f'takes/{take}/record/.postprocess.lock'))
            proof = validate_new_record(child, take, read_json(child / f'takes/{take}/plan.json'))
            require(proof == row['transport'], 'transport proof differs from ready receipt')
        delivery_dir = Path(manifest['delivery_dir'])
        delivery = read_json(delivery_dir / 'delivery.json')
        require(all(delivery.get(k) == manifest['delivery'].get(k) for k in (
            'game_id', 'model', 'engine', 'project_root', 'entry', 'run_id', 'stage'))
            and delivery.get('required_real_clients', 1) == 1, 'delivery shim identity changed')
        before = files(child)
        with _cached_pipeline(pipeline, child, manifest, ready):
            score = pipeline.run_playable(delivery_dir, child, models=manifest['models'], takes=2)
        require(score.get('complete') is True and score['game_id'] == CASE
                and score['engine'] == 'unity3d' and score['planner'] == PLANNER_MODEL,
                'official cached pipeline did not complete')
        require([t['take'] for t in score['takes']] == [t['take'] for t in ready['takes']]
                and score['checks'] == {k: v['status'] for k, v in ready['takes'][-1]['verdicts'].items()},
                'cached pipeline outcomes differ from reviewed native rules')
        after = files(child)
        allowed = {'playable_score.json', 'status.json', 'playable_rules.json',
                   'verdicts_playable_rules.json'}
        require({k: v for k, v in before.items() if k not in allowed}
                == {k: v for k, v in after.items() if k not in allowed},
                'cached scoring changed non-score evidence')
        _parent_and_archive(out, prepared)
        verify_child(child, manifest)
        require(production() == prepared['binding']['production'], 'producer changed during finalization')
        cache_files = {k: v for k, v in after.items()
                       if any(k.startswith(part + '/') for part in CACHE_PARTS)}
        final = {'schema': FINALIZATION_SCHEMA, 'review_sha256': expected_review,
                 'parent': str(out), 'child': str(child),
                 'prepared_sha256': sha256(lineage / 'prepared.json'),
                 'ready_sha256': sha256(lineage / 'ready_for_review.json'),
                 'source_sha256': SOURCE_SHA, 'production_sha256': digest(prepared['binding']['production']),
                 'score_sha256': sha256(child / 'playable_score.json'),
                 'retained_evidence': retained_files(child), 'cache_files': cache_files,
                 'cache_bytes': sum((child / k).stat().st_size for k in cache_files),
                 'native_calls': 0, 'model_calls': 0,
                 'scoring_entry': 'pipeline.eval.whitebox.pipeline.run_playable',
                 'parent_diagnostics_preserved': True}
        exclusive_json(lineage / 'finalization.json', final)
        replacement = {'schema': REPLACEMENT_SCHEMA, 'status': 'QUALIFIED_REPLACEMENT',
                       'parent': str(out), 'child': str(child), 'review_sha256': expected_review,
                       'game_id': CASE, 'engine': 'unity3d', 'model': 'sol',
                       'source_sha256': SOURCE_SHA, 'child_score': 'run/playable_score.json',
                       'child_score_sha256': final['score_sha256'],
                       'finalization': 'finalization.json',
                       'finalization_sha256': sha256(lineage / 'finalization.json'),
                       'parent_score_sha256': sha256(out / 'playable_score.json'),
                       'parent_hold_sha256': sha256(out / 'qualification_hold.json'),
                       'qualification': 'replacement_only_parent_hold_retained'}
        exclusive_json(lineage / 'replacement.json', replacement)
        require(qualified_replacement_score(out) == score, 'replacement verification failed')
        return replacement


def _qualified_replacement_score(out):
    out = Path(out).absolute()
    require(out.resolve() == out, 'parent path traverses a symlink')
    lineage, child = out / LINEAGE, out / LINEAGE / 'run'
    require(lineage.resolve() == lineage and child.resolve() == child, 'lineage path symlink')
    replacement_path = lineage / 'replacement.json'
    if not replacement_path.exists():
        return None
    for name in ('replacement.json', 'finalization.json', 'prepared.json', 'ready_for_review.json'):
        require(not (lineage / name).is_symlink(), 'receipt symlink rejected')
    replacement = read_json(replacement_path)
    require(replacement['schema'] == REPLACEMENT_SCHEMA
            and replacement['status'] == 'QUALIFIED_REPLACEMENT'
            and replacement['parent'] == str(out) and replacement['child'] == str(child)
            and replacement['game_id'] == CASE and replacement['engine'] == 'unity3d'
            and replacement['model'] == 'sol' and replacement['source_sha256'] == SOURCE_SHA
            and replacement['child_score'] == 'run/playable_score.json'
            and replacement['finalization'] == 'finalization.json'
            and replacement['qualification'] == 'replacement_only_parent_hold_retained',
            'qualified replacement identity mismatch')
    require(replacement['parent_score_sha256'] == sha256(out / 'playable_score.json')
            and replacement['parent_hold_sha256'] == sha256(out / 'qualification_hold.json'),
            'parent score/hold changed')
    require(replacement['finalization_sha256'] == sha256(lineage / 'finalization.json'),
            'finalization receipt changed')
    final = read_json(lineage / 'finalization.json')
    require(final['schema'] == FINALIZATION_SCHEMA and final['parent'] == str(out)
            and final['child'] == str(child) and final['review_sha256'] == replacement['review_sha256']
            and final['source_sha256'] == SOURCE_SHA and final['native_calls'] == final['model_calls'] == 0
            and final['scoring_entry'] == 'pipeline.eval.whitebox.pipeline.run_playable'
            and final['parent_diagnostics_preserved'] is True
            and final['prepared_sha256'] == sha256(lineage / 'prepared.json')
            and final['ready_sha256'] == sha256(lineage / 'ready_for_review.json'),
            'finalization provenance mismatch')
    prepared = read_json(lineage / 'prepared.json')
    require(prepared['review_sha256'] == final['review_sha256']
            and final['production_sha256'] == digest(prepared['binding']['production']),
            'frozen producer identity mismatch')
    manifest = _parent_and_archive(out, prepared)
    ready = _ready(out, prepared, check_child=False)
    require(read_json(child / 'manifest.json') == manifest
            and retained_files(child) == final['retained_evidence'], 'retained child evidence changed')
    accepted_plans(child, manifest)
    current = files(child)
    cache = {k: v for k, v in current.items() if any(k.startswith(p + '/') for p in CACHE_PARTS)}
    present = [(child / p).is_dir() for p in CACHE_PARTS]
    if all(present):
        require(not (child / 'cleanup.json').exists() and cache == final['cache_files'],
                'project copies changed after qualification')
        prepare.verify(child)
    else:
        require(not any(present) and not cache, 'partial project cleanup')
        cleanup = read_json(child / 'cleanup.json')
        require(set(cleanup['removed']) == set(CACHE_PARTS)
                and cleanup['freed_bytes'] == final['cache_bytes'], 'cleanup receipt differs from qualified copies')
        require(prepare.tree_hashes(child / 'input') == manifest['input_hashes'], 'cleaned input metadata changed')
    for row in ready['takes']:
        take = row['take']
        require(validate_new_record(child, take, read_json(child / f'takes/{take}/plan.json'))
                == row['transport'], 'retained transport proof changed')
    require(sha256(child / 'playable_score.json') == replacement['child_score_sha256'] == final['score_sha256'],
            'official child score changed')
    score = read_json(child / 'playable_score.json')
    status = read_json(child / 'status.json')
    require(score.get('complete') is True and score['game_id'] == CASE and score['engine'] == 'unity3d'
            and score['planner'] == PLANNER_MODEL and status.get('state') == 'done'
            and status.get('complete') is True and status.get('step') == 'playable'
            and [t['take'] for t in score['takes']] == [t['take'] for t in ready['takes']]
            and score['checks'] == {k: v['status'] for k, v in ready['takes'][-1]['verdicts'].items()},
            'official score completion mismatch')
    return score


def qualified_replacement_score(out: Path) -> dict | None:
    """Read-only runner hook: malformed/missing/drifted provenance fails closed.

    Uses the fixed lineage replacement.json only. Current production may evolve
    after publication; the completed producer remains bound to its saved hashes.
    Exact cached projects OR the official cleanup(child) receipt are accepted.
    """
    try:
        return _qualified_replacement_score(out)
    except (OSError, ValueError, TypeError, KeyError, IndexError):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--execute', action='store_true', help='only after parent approves this exact review')
    mode.add_argument('--finalize', action='store_true', help='official scoring from qualified cached takes only')
    parser.add_argument('--expect-review', help='review_sha256 from read-only preview')
    args = parser.parse_args()
    if (args.execute or args.finalize) and not args.expect_review:
        parser.error('--execute/--finalize require --expect-review')
    if args.finalize:
        result = finalize(args.out, args.expect_review)
    else:
        result = execute(args.out, args.expect_review) if args.execute else preview(args.out)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
