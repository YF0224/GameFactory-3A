"""Qualify an existing UE Stage3 take whose fully recorded shutdown timed out.

No engine/model calls, authored-file changes, native-evidence writes or scoring.
This opt-in recovery requires a SHA-bound authorization, the original production
pins, every planned input receipt and capture, and a proven exit request AFTER
the full observation window. It accepts only the rooted media-component teardown
assertion; incomplete recordings and gameplay/startup crashes remain failures.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

from pipeline.eval.whitebox.core import capture, prepare, record
from pipeline.eval.whitebox.core.llm import HarnessError
from pipeline.eval.whitebox.core.paths import FRAMEWORK, read_json, sha256, write_json
from engine_adapters.ue5.playtest import native_client, native_record
from engine_adapters.ue5.playtest.isolation import process_table
from pipeline.eval.whitebox.action_links import build_links
from pipeline.eval.whitebox.sparse_evidence import audit_capture

VERSION = 'stage3-ue-completed-shutdown-recovery.v1'


def _tree(root):
    root = Path(root)
    result = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise ValueError('Linked native evidence cannot be recovered')
        if path.is_file():
            result[str(path.relative_to(root))] = sha256(path)
    return result


def _input_actions(events, requests, receipts, ready, launch, warmup_ms=3000):
    """The ordinary recorder's receipt checks, requiring ALL scheduled inputs."""
    if len(requests) != len(events) or len(receipts) != len(events):
        raise ValueError('Incomplete or duplicate input delivery')
    request_map = {r['seq']: r for r in requests}
    receipt_map = {r['seq']: r for r in receipts}
    expected = {e['seq'] for e in events}
    if set(request_map) != expected or set(receipt_map) != expected:
        raise ValueError('Input sequence differs from the complete accepted plan')
    actions = []
    for event in events:
        kind = event.get('type', 'key')
        if kind not in ('key', 'viewport_pointer') or (kind == 'viewport_pointer' and event['phase'] != 'move'):
            raise ValueError('Recovery supports keys and native pointer movement without held buttons')
        req, got = request_map[event['seq']], receipt_map[event['seq']]
        if any(req.get(k) != event[k] or got.get(k) != event[k] for k in ('key', 'phase')):
            raise ValueError('Input receipt does not match the scheduled event')
        if (req.get('token') != launch['native_input_token']
                or req.get('action_id') != event['action']['action_id']
                or got.get('pid') != launch['pid']
                or got.get('token') != launch['native_input_token']
                or got.get('routed') is not True):
            raise ValueError('Native input token, process or routing proof differs')
        expected_wire = native_record.wire_message(event, launch['native_input_token'])
        if any(req.get(k) != v for k, v in expected_wire.items()):
            raise ValueError('Host request differs from the exact native wire message')
        if kind == 'viewport_pointer':
            native_record.verify_pointer_receipt(got, event, launch['pid'], launch['native_input_token'])
        elif got.get('source') != 'UGameViewportClient::InputKey':
            raise ValueError('Native key was not routed through the viewport')
        host_ms = req.get('host_t_ms')
        if not isinstance(host_ms, (int, float)) or abs(host_ms - event['at_ms'] - warmup_ms) > 500:
            raise ValueError('Input request clock is not bound to its planned event')
        at = got['t_ms'] - ready['native_origin_seconds'] * 1000
        if not 0 <= at <= host_ms + 2000:
            raise ValueError('Native receipt clock is outside the recorded take')
        actions.append({**event['action'], 'phase': got['phase'], 'key': got['key'],
                        'seq': got['seq'], 'sent': True, 't_ms': at, 'end_t_ms': at,
                        'source': 'native_receiver', 'source_t_ms': got['t_ms']})
    return actions


_LOG_TIME = re.compile(r'^\[(\d{4})\.(\d\d)\.(\d\d)-(\d\d)\.(\d\d)\.(\d\d):(\d{3})\]')


def _shutdown_boundary(text, ready, duration_ms, warmup_ms):
    lines = text.splitlines()
    exits = [i for i, line in enumerate(lines) if 'LogCore: Engine exit requested (reason: Mac RequestExit)' in line]
    failures = [i for i, line in enumerate(lines) if 'appError called:' in line or 'Fatal error:' in line]
    if not exits or not failures or min(failures) <= min(exits):
        raise ValueError('Failure is not confined to the requested shutdown')
    if not any('Assertion failed: !IsRooted()' in lines[i] for i in failures):
        raise ValueError('Unknown teardown failure')
    if 'UA3GameMediaSubsystem::Deinitialize()' not in text:
        raise ValueError('Missing delivered media teardown stack')
    match = _LOG_TIME.match(lines[min(exits)])
    if not match:
        raise ValueError('Shutdown has no original native clock')
    y, mo, day, h, minute, second, ms = map(int, match.groups())
    wall = datetime(y, mo, day, h, minute, second, ms * 1000, tzinfo=timezone.utc).timestamp()
    elapsed = (wall - ready['wall_origin_seconds']) * 1000
    if elapsed < duration_ms + warmup_ms + 1000:
        raise ValueError('Shutdown preceded the complete recording and native tail')
    return {'exit_t_ms': elapsed, 'recording_ms': duration_ms, 'warmup_ms': warmup_ms,
            'failure': 'rooted delivered media component during Deinitialize',
            'scope': 'after completed native observation; original failure retained'}


def verify(out, authorization):
    out, authorization = Path(out).resolve(), Path(authorization).resolve()
    auth = read_json(authorization)
    if auth.get('version') != VERSION or auth.get('run') != str(out) or auth.get('identity') != out.name:
        raise ValueError('Recovery authorization does not bind this existing identity')
    batch = out.parent.parent
    scope_path = batch / 'scope.json'
    if sha256(scope_path) != auth['scope_sha256']:
        raise ValueError('Existing batch scope changed')
    scope = read_json(scope_path)
    row = next(r for r in scope['identities'] if r['identity'] == out.name)
    if row['engine'] != 'ue5' or 'G025' in row['game_id']:
        raise ValueError('Identity is outside this recovery scope')
    if any(r['identity'] == out.name for r in read_json(batch / 'final_scores.json')['results']):
        raise ValueError('Persisted scores must never be remeasured')
    for pin in scope['production'] + auth['recovery_production']:
        if sha256(pin['path']) != pin['sha256']:
            raise ValueError('Production binding changed: ' + pin['path'])
    if not any(Path(pin['path']).resolve() == Path(__file__).resolve() for pin in auth['recovery_production']):
        raise ValueError('Recovery implementation is not SHA-bound')
    manifest = prepare.verify(out)
    if manifest.get('suite') != 'stage3' or manifest['engine'] != 'ue5':
        raise ValueError('Only existing Stage3 UE recordings are supported')
    if prepare.tree_hashes(Path(row['project_source'])) != read_json(out / 'engineering/original_sha256_before.json'):
        raise ValueError('Original delivery changed')
    runtime = out / 'takes/1/record'
    native = runtime / 'native/take'
    if (runtime / 'record_result.json').exists() or (runtime / 'launch_repair_binding.json').exists():
        raise ValueError('Recovery requires an unfinished original, unrepaired recording')
    if _tree(native) != auth['native_sha256']:
        raise ValueError('Original native evidence changed')
    parents = {'takes/1/plan.json': auth['plan_sha256'],
               'engineering/failure.json': auth['failure_sha256']}
    if any(sha256(out / rel) != digest for rel, digest in parents.items()):
        raise ValueError('Accepted plan or original failure changed')
    if read_json(runtime / 'record_error.json') != {'type': 'RuntimeError', 'error': 'UE native exit timeout'}:
        raise ValueError('Not the reviewed completed-shutdown timeout')
    admission = read_json(out / 'runtime/ue_admission/admission.json')
    native_record.verify_pin(admission)
    pin = read_json(admission['pin'])
    if sha256(out / 'runtime/ue_admission/build.json') != pin['build_receipt_sha256']:
        raise ValueError('Parent native build changed')
    launch, ready = read_json(native / 'launch.json'), read_json(native / 'play_started.json')
    cleanup = read_json(native / 'cleanup.json')
    if (not cleanup.get('ownership_verified') or cleanup.get('pid') != launch['pid']
            or cleanup.get('remaining_descendants') or cleanup.get('input_release_errors')
            or any(cleanup.get(k) is not True for k in ('process_cleanup_ok', 'view_cleanup_ok', 'input_cleanup_ok'))):
        raise ValueError('Original native ownership/cleanup is incomplete')
    table = process_table()
    for pid, identity in cleanup['descendants'].items():
        if int(pid) in table and tuple(table[int(pid)][1:]) == tuple(identity):
            raise ValueError('A launched native process remains active')
    if any(admission['uproject'] in row[2] and admission['editor'] in row[2] for row in table.values()):
        raise ValueError('This evaluation project is currently open')
    if (ready.get('pid') != launch['pid'] or not ready.get('native_recorder')
            or ready.get('native_input_token') != launch['native_input_token']
            or ready.get('native_input_port') != launch['port']
            or ready.get('native_input_source') != 'A3GamePlayable_native_viewport'):
        raise ValueError('Native startup identity differs')
    native_record._validate_startup_boundary(ready)
    native_record._validate_capture_surface(ready)
    native_record._validate_ui_frame_sources(native)
    plan = read_json(out / 'takes/1/plan.json')
    if (plan.get('state_entry') or {}).get('calls'):
        raise ValueError('State mutation is not normal gameplay')
    normalized, end = native_client.plan_actions(record.native_actions(plan, 'ue5'), {})
    window = read_json(runtime / 'recording_window.json')
    duration = min(manifest['budget']['recording_ms'], end + 3000)
    if window['plan_sha256'] != auth['plan_sha256'] or window['recording_ms'] != duration:
        raise ValueError('Observation window differs from the accepted plan')
    schedule, _ = capture.schedule(normalized, duration, engine='ue5')
    schedule.update(warmup_ms=round(record.UE_WARMUP_S * 1000), tolerance_ms=record.UE_LATE_TOLERANCE_MS,
                    plan={'windows': [], 'endpoints': []})
    if (read_json(native / 'capture_schedule.json') != schedule
            or read_json(native / 'action_schedule.json')['actions'] != normalized):
        raise ValueError('Native schedule differs from the original accepted plan')
    startup = read_json(native / 'startup_readiness.json')
    if (startup['marker_sha256'] != sha256(native / 'play_started.json')
            or startup['capture_schedule_sha256'] != sha256(native / 'capture_schedule.json')
            or startup['recording_ms'] != duration):
        raise ValueError('Original readiness binding differs')
    audit = audit_capture(native, schedule)
    if audit['missing_slots_ms']:
        raise ValueError('Missing predeclared native captures cannot be recovered')
    events = native_record.expand(normalized)
    requests = [r for _, r in native_record.jsonl(native / 'host_input_requests.jsonl')]
    receipts = [r for _, r in native_record.jsonl(native / 'native_input.jsonl')]
    actions = _input_actions(events, requests, receipts, ready, launch, schedule['warmup_ms'])
    boundary = _shutdown_boundary((native / 'unreal.log').read_text(errors='replace'), ready, duration, schedule['warmup_ms'])
    if (native / 'events.jsonl').exists():
        raise ValueError('Additional raw event mapping is not supported by this recovery')
    return {'manifest': manifest, 'audit': audit, 'actions': actions, 'boundary': boundary,
            'native_sha256': auth['native_sha256'], 'parent_sha256': parents, 'schedule': schedule,
            'authorization_sha256': sha256(authorization), 'cleanup': cleanup}


def recover(out, authorization):
    out = Path(out).resolve()
    runtime = out / 'takes/1/record'
    with record._record_lock(out, 1):
        proof = verify(out, authorization)
        native = runtime / 'native/take'
        archive = runtime / 'completed_shutdown_recovery'
        if archive.exists():
            raise HarnessError('Recovery already attempted; retain partial work for explicit review')
        with tempfile.TemporaryDirectory(prefix='completed-shutdown-', dir=runtime) as temporary:
            staging = Path(temporary)
            summary = record._collect(staging, native)
            (staging / 'actions.jsonl').write_text(''.join(json.dumps(a, ensure_ascii=False) + '\n' for a in proof['actions']))
            summary.update(actions=len(proof['actions']), failed_actions=[],
                           channels={n: (staging / n).stat().st_size > 0 for n in record.CHANNELS},
                           cleanup={'native': proof['cleanup']})
            write_json(staging / 'action_frame_links.json', build_links(staging))
            record._lateness(native, proof['schedule'], staging)
            for src in staging.rglob('*'):
                dst = runtime / src.relative_to(staging)
                if src.is_file() and dst.exists() and (not dst.is_file() or sha256(src) != sha256(dst)):
                    raise ValueError('Existing canonical output conflicts with recovered evidence: ' + str(dst))
            again = verify(out, authorization)
            if again != proof:
                raise ValueError('Recovery evidence changed during postprocessing')
            archive.mkdir()
            receipt = {k: v for k, v in proof.items() if k not in ('manifest', 'actions', 'schedule')}
            receipt.update(version=VERSION, native_recording_reused=True, new_recording=False,
                           authorization=str(Path(authorization).resolve()),
                           production_sha256={str(Path(__file__).resolve()): sha256(__file__)})
            write_json(archive / 'receipt.json', receipt)
            shutil.copyfile(runtime / 'record_error.json', archive / 'record_error.json')
            for src in staging.rglob('*'):
                if src.is_file():
                    dst = runtime / src.relative_to(staging)
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    if not dst.exists():
                        shutil.copyfile(src, dst)
            summary['game_events'] = record.game_events(runtime, 'ue5', out / 'runtime/project')
            summary.update(version=record.VERSION, engine='ue5', elapsed_ms=None, gui_slot=None, take=1,
                           plan_sha256=sha256(out / 'takes/1/plan.json'),
                           recorder=str(FRAMEWORK / 'engine_adapters/ue5'),
                           recovery_receipt=str(archive / 'receipt.json'))
            if not summary['frames'] or summary['failed_actions'] or _tree(native) != proof['native_sha256']:
                raise ValueError('Recovered take failed the ordinary collection gate')
            write_json(runtime / 'adapter_result.json', {'ok': True, 'payload': {'take_dir': str(native)},
                                                       'recovery_receipt': summary['recovery_receipt']})
            # The completed-result marker is committed last. No native artifact is changed.
            fd, temp = tempfile.mkstemp(prefix='record_result.', suffix='.tmp', dir=runtime)
            try:
                with os.fdopen(fd, 'w') as stream:
                    json.dump(summary, stream, ensure_ascii=False, indent=2)
                    stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
                os.replace(temp, runtime / 'record_result.json')
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)
            return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('authorization', type=Path)
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    print(json.dumps((verify if args.verify_only else recover)(args.run, args.authorization), ensure_ascii=False, indent=2))
