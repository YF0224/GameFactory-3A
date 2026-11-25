"""Idempotent serial Unity evaluation using only formal evaluator implementations."""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import time
import threading
import traceback
from types import SimpleNamespace

from . import batch, unity_admission, unity_recovery, unity_safety, unity_single, unity_plan_normalization, unity_packaging_recovery, unity_capture_policy, partial_static_existence, static_judge_recovery
from .protocol import dump, sha
from . import unity_authored_entry, unity_compile_compatibility, unity_editor_compile_compatibility, unity_native_compile_recovery

MODEL_ORDER = ('Astra', 'GLM', 'Sol', 'Opus', 'Kimi')
USER_EXCLUDED = {'Sol__G015_garden_revival': 'User cancelled this case; explicit case exclusion retained'}
RESUMABLE = {'PENDING', 'RUNNING', 'WAITING_SERIAL_LOCK'}


def read(path):
    return batch.read(Path(path))


def published(batch_root, ident, *, include_saved=True):
    """Formal tables/publications/results protect a case independently of effective audit."""
    root = Path(batch_root)
    method, case = ident.split('__', 1)
    label = method+' / '+case[:4]
    publication = root/'versioned_publications.json'
    if publication.is_file() and ident in read(publication).get('entries', {}):
        return True
    # Verify-only diagnostics do not establish a formal score.
    for name in ('scores.md', 'score_new.md'):
        path = root/name
        if not path.is_file():
            continue
        for line in path.read_text().splitlines():
            if line.startswith('| '+label+' |'):
                cells = [c.strip() for c in line.strip().strip('|').split('|')]
                if len(cells) >= 11 and cells[9] not in {'—', '-', ''}:
                    try:
                        float(cells[9])
                        return True
                    except ValueError:
                        pass
    return include_saved and unity_recovery.saved_score(unity_recovery.attempts(root, ident)) is not None



def pending_publication_recovery(root, output, case):
    """One formatting repair after this queue's audited judge, with no model rerun."""
    if (case.get('status') != 'BOUNDED_FAILURE'
            or case.get('error') != 'Expected one existing policy summary table'
            or case.get('publication_recovery_count')
            or published(root, case['id'], include_saved=False)):
        return False
    single = output/'cases'/case['id']/'single_state.json'
    if not single.is_file():
        return False
    saved = read(single)
    judged = saved.get('judge_attempt')
    if not judged or judged != case.get('judge_attempt'):
        return False
    attempt = Path(judged)
    if (not (attempt/'scores.json').is_file() or not (attempt/'independent_audit.json').is_file()
            or (attempt/'formal_publication_receipt.json').exists()):
        return False
    score, audit = read(attempt/'scores.json'), read(attempt/'independent_audit.json')
    return (score.get('valid') is True and audit.get('valid') is True
            and audit.get('bindings', {}).get('scores.json') == sha(attempt/'scores.json')
            and read(attempt/'input_manifest.json')['entry']['id'] == case['id'])

def candidate_rows(root, models):
    rows = [row for row in read(Path(root)/'inventory.json')['entries']
            if row.get('method') in models and row.get('actual_engine') == 'unity3d']
    return sorted(rows, key=lambda r: (models.index(r['method']), r['id']))


def ensure_review(output, row):
    path = Path(output)/'reviews'/(row['id']+'.json')
    if not path.is_file():
        dump(path, {'id': row['id'], 'entry': row, 'source_review': {'source': row.get('project')},
                    'selected_project': row.get('project'), 'status': 'READY'})
    return path


def metrics(paths):
    result = {}
    for value in dict.fromkeys(str(p) for p in paths if p):
        root = Path(value)
        deliveries = [read(path) for path in (root/'model_calls').glob('*/actual_delivery.json')]
        maximum = max([v.get('image_count', 0) for v in deliveries] or [0])
        if maximum > 100:
            raise unity_safety.SafetyStop('Actual judge request exceeded 100 images')
        frame_file = root/'runtime/frame_index.jsonl'
        if not frame_file.is_file():
            frame_file = root/'background_record/take/frame_index.jsonl'
        result[value] = {'invocations': len(list((root/'model_calls').glob('*/invocation.json'))),
                         'judge_requests': len(deliveries),
                         'judge_images': sum(v.get('image_count', 0) for v in deliveries),
                         'maximum_judge_images': maximum,
                         'raw_frames': len(frame_file.read_text().splitlines()) if frame_file.is_file() else None}
    return result


def classify_failure(exc):
    text = str(exc).lower()
    from .unity_editor_selection import EditorCompatibilityError, NativeAdmissionError
    if isinstance(exc, (EditorCompatibilityError, NativeAdmissionError)):
        return exc.failure_class
    if isinstance(exc, unity_safety.SafetyStop):
        return 'SAFETY'
    if isinstance(exc, unity_plan_normalization.InvalidSavedPlan):
        return 'PLAN_INVALID'
    if any(t in text for t in ('no openable unity', 'no assets/**/*.unity')):
        return 'PRODUCT'
    if any(t in text for t in ('502', '401', 'unauthorized', 'connection', 'gateway', 'service unavailable', 'timed out', 'timeout')):
        return 'ENVIRONMENT'
    # Deterministic validation/packaging defects are local repair work. They
    # must not spend the shared service/environment outage budget.
    if isinstance(exc, (ValueError, KeyError, TypeError, AssertionError, FileNotFoundError)):
        return 'LOCAL_TOOL'
    return 'HARNESS'



@contextmanager
def heartbeat(output, state, config):
    """Report blocked calls every 30s without mutating the frozen queue ledger."""
    stopped = threading.Event()
    def report():
        while not stopped.is_set():
            now = time.time()
            cases = list(state.get('cases', {}).values())
            active = next((c for c in cases if c.get('status') in {'RUNNING', 'WAITING_SERIAL_LOCK'}), {})
            phase = active.get('phase', state.get('status'))
            budget_key = {'static':'static', 'plan':'plan', 'judge':'judge', 'admission':'admission'}.get(phase)
            budget = config.get(budget_key+'_timeout_seconds') if budget_key else None
            started = active.get('phase_started_unix')
            value = {'pid':os.getpid(), 'updated_unix':now, 'queue_status':state.get('status'),
                'id':active.get('id'), 'phase':phase, 'phase_started_unix':started,
                'stage_call_budget_seconds':budget, 'phase_elapsed_seconds':now-started if started else None,
                'attempt':active.get('attempt', active.get('recorded_attempt')),
                'judge_attempt':active.get('judge_attempt'), 'counts':{s:sum(c.get('status')==s for c in cases)
                    for s in sorted({c.get('status', 'UNKNOWN') for c in cases})}}
            dump(Path(output)/'heartbeat.json', value)
            print(json.dumps({'heartbeat':value}, ensure_ascii=False), flush=True)
            stopped.wait(30)
    worker = threading.Thread(target=report, name='unity-queue-heartbeat', daemon=True)
    worker.start()
    try:
        yield
    finally:
        stopped.set()
        worker.join(timeout=2)


def review_saved_plan_failures(output, state):
    """Reclassify only verified, terminal saved-plan rejections on resume.

    No attempt, model call, action, sample or historical failure file is changed.
    The previous stop and its counter remain in an append-only receipt. Unknown
    source/identity errors and service-only timeouts keep the environment stop.
    """
    changed = []
    for ident, case in state['cases'].items():
        if (case.get('status') != 'BOUNDED_FAILURE' or case.get('failure_class') != 'HARNESS'
                or not case.get('error', '').startswith('Saved plan cannot be deterministically normalized: ')):
            continue
        single = Path(output)/'cases'/ident/'single_state.json'
        if not single.is_file():
            continue
        attempt = Path(read(single)['attempt'])
        if (case.get('recorded_attempt') != str(attempt)
                or read(attempt/'input_manifest.json')['entry']['id'] != ident):
            continue
        review = unity_plan_normalization.assessment(attempt)
        if not review.get('substantively_invalid'):
            continue
        actual = 'Saved plan cannot be deterministically normalized: '+'; '.join(
            r['error'] for r in review['responses'])
        if actual != case['error']:
            continue
        history = {k:v for k,v in case.items() if k not in {'entry','failure_history'}}
        case.setdefault('failure_history', []).append(history)
        receipt = Path(output)/'failures'/(ident+'__plan_disposition_v1.json')
        dump(receipt, {'version':'whitebox-saved-plan-disposition.v1',
            'attempt':str(attempt), 'prior_failure_class':case['failure_class'],
            'failure_class':'PLAN_INVALID', 'original_error':case['error'],
            'assessment':review, 'model_calls_added':0, 'gameplay_recorded':False,
            'reason':'Completed model output has invalid action/endpoint bindings; no deterministic repair',
            'reviewed_unix':time.time()})
        case.update(failure_class='PLAN_INVALID', plan_disposition=str(receipt),
                    reason='Terminal saved-plan rejection; preserved without a new model call or fake score')
        changed.append(ident)
    if changed:
        # Reconstruct only the actual consecutive tail, using completion times
        # (started_unix predates resumes and cannot order their outcomes).
        old_count = state['consecutive_environment_failures']
        attempted = sorted((c for c in state['cases'].values() if c.get('started_unix') is not None),
            key=lambda c:c['started_unix']+c.get('elapsed_seconds',0), reverse=True)
        tail = 0
        for case in attempted:
            if case.get('status') == 'BOUNDED_FAILURE' and case.get('failure_class') in {'ENVIRONMENT','HARNESS'}:
                tail += 1
            else:
                break
        state['consecutive_environment_failures'] = min(old_count, tail)
        state.setdefault('failure_classification_history', []).append({
            'version':'whitebox-saved-plan-disposition.v1','reviewed_unix':time.time(),
            'prior_status':state.get('status'),'prior_reason':state.get('reason'),
            'prior_consecutive_environment_failures':old_count,
            'consecutive_environment_failures':state['consecutive_environment_failures'],
            'cases':changed,'reason':'Read-only validation proved terminal invalid planner outputs; environment threshold unchanged'})
    return changed

@contextmanager
def coordinator(config, waiting=None):
    """One production queue per shared control root, including admission/model stages."""
    control = Path(config['control_root'])
    control.mkdir(parents=True, exist_ok=True)
    with (control/'whitebox_production_queue.lock').open('a+') as stream:
        while True:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if waiting is not None:
                    waiting()
                time.sleep(15)
        stream.seek(0)
        stream.truncate()
        stream.write(str(os.getpid())+'\n')
        stream.flush()
        yield


def verify_acceptance(config):
    from engine_adapters.unity3d.playtest import native_acceptance
    path = Path(config['editor_acceptance']).resolve()
    receipt = read(path)
    native_acceptance.verify(path, Path(config['adapter_root']), Path(receipt['editor']))
    return receipt


def verified_editors(config):
    """Each Editor keeps its own native short/long acceptance and source pin."""
    from engine_adapters.unity3d.playtest import native_acceptance
    from .unity_editor_selection import editor_version
    registered = {}
    paths = [config['editor_acceptance'], *config.get('editor_acceptances', [])]
    for value in dict.fromkeys(paths):
        path = Path(value).resolve()
        receipt = read(path)
        native_acceptance.verify(path, Path(config['adapter_root']), Path(receipt['editor']))
        version = receipt.get('editor_version') or editor_version(receipt['editor'])
        if not version or version in registered and registered[version]['editor'] != receipt['editor']:
            raise ValueError('Ambiguous verified Editor registration')
        registered[version] = {'path':str(path), 'sha256':sha(path), 'editor':receipt['editor'],
                               'editor_version':version}
    return registered


def run_new(config, output, row, phase):
    output.mkdir(parents=True, exist_ok=True)
    cfg_path = output/'configuration.json'
    if not cfg_path.exists():
        dump(cfg_path, config)
    elif read(cfg_path) != config:
        saved = read(cfg_path)
        expected = dict(config, editor_acceptance=saved.get('editor_acceptance'))
        allowed = {config['editor_acceptance'], *config.get('editor_acceptances', [])}
        if saved != expected or saved.get('editor_acceptance') not in allowed:
            raise ValueError('Saved case configuration changed; preserve existing output')
    state_path = output/'single_state.json'
    if not state_path.exists():
        opened = output/'opened_candidate.json'
        if not opened.is_file():
            phase('admission')
            acceptance = verify_acceptance(config)
            registered = verified_editors(config)
            review_path = ensure_review(output, row)
            from .unity_authored_entry import load as load_authored_entry
            authored = load_authored_entry(config['batch'], row['id'], row['project']) if config.get('batch') else None
            candidate = unity_admission.review_project(read(review_path), {'id': row['id']}, registered, Path(acceptance['editor']), **({'authored_entry':authored} if authored else {}))
            if candidate['status'] != 'READY':
                if candidate.get('failure_class') == 'EDITOR_COMPATIBILITY':
                    from .unity_editor_selection import EditorCompatibilityError
                    dump(output/'editor_compatibility_block.json', candidate)
                    raise EditorCompatibilityError(candidate['reason'])
                return {'status': 'SKIPPED_PRODUCT', 'reason': candidate.get('reason'), 'admission': candidate}
            compatibility = unity_compile_compatibility.load(config['batch'], row['id'], candidate['selected_project']) if config.get('batch') else None
            if compatibility:
                candidate['import_compatibility'] = compatibility
            from .unity_editor_compile_compatibility import load as load_editor_compatibility
            editor_compatibility = load_editor_compatibility(config['batch'], row['id'], candidate['selected_project']) if config.get('batch') else None
            if editor_compatibility:
                candidate['editor_compile_compatibility'] = editor_compatibility
            native_compile = unity_native_compile_recovery.load(config['batch'], row['id'], candidate['selected_project']) if config.get('batch') else None
            if native_compile:
                candidate['native_compile_recovery'] = native_compile
            candidate.update(review_path=str(review_path), review_sha256=sha(review_path))
            runner = SimpleNamespace(batch=batch, sha=sha, dump=dump, MIGRATION=Path(config['snapshot_root']),
                ROOT=Path(config['adapter_root']), open_timeout_seconds=config.get('admission_timeout_seconds', 300),
                input_system_package_root=config.get('input_system_package_root'),
                locks_clear=lambda: unity_safety.locks_clear(config))
            candidate = unity_admission.prepare_source(candidate, read(review_path), runner, Path(config['admission_root']))
            dump(opened, candidate)
        selected = read(opened)['native_editor_acceptance']['path']
        if selected not in {config['editor_acceptance'], *config.get('editor_acceptances', [])}:
            raise ValueError('Opened project Editor acceptance is not in this queue configuration')
        selected_config = dict(config, editor_acceptance=selected)
        if read(cfg_path) != selected_config:
            dump(output/'editor_selection.json', {
                'version':'whitebox-verified-editor-selection.v1',
                'queue_configuration_sha256':sha(Path(config['_configuration_path'])),
                'native_acceptance':read(opened)['native_editor_acceptance'],
                'delivery_format':read(opened).get('delivery_format'),
                'no_attempt_or_model_call_before_selection':True})
            dump(cfg_path, selected_config)
    previous_observer=unity_single.PHASE_OBSERVER
    unity_single.PHASE_OBSERVER=phase
    try:
        unity_single.main(['--output',str(output)]+(['--resume'] if state_path.exists() else []))
    finally:
        unity_single.PHASE_OBSERVER=previous_observer
    state = read(state_path)
    if state.get('phase') == 'SCORED_PENDING_AUDIT' and state.get('provisional') is True:
        return {**state, 'status':'SCORED_PENDING_AUDIT'}
    if state.get('phase') != 'COMPLETE' or state.get('valid') is not True:
        raise ValueError('Single evaluation returned without audited publication or explicit pending score')
    return {'status': 'COMPLETE', **state}


def prepare_cases(root, config, output, state, models, *, resume=False, dry_run=False):
    """Select work in memory; dry_run never publishes or saves queue/inventory files."""
    rows = candidate_rows(root, models)
    for row in rows:
        ident = row['id']
        case = state['cases'].setdefault(ident, {'id': ident, 'status': 'PENDING'})
        from .pending_publication import deferred, publish as publish_pending
        own_saved = case.get('judge_attempt')
        if (resume and not dry_run and deferred(config) and own_saved
                and (Path(own_saved)/'scores.json').is_file()
                and not published(root,ident,include_saved=False)
                and read(Path(own_saved)/'input_manifest.json')['entry']['id'] == ident
                and read(Path(own_saved)/'scores.json').get('valid') is True):
            result=publish_pending(Path(own_saved))
            case.update(result, entry=row, judge_attempt=own_saved,
                        reason='Saved judge synchronized as explicitly unaudited; no repeat model/record call')
        elif resume and pending_publication_recovery(root, output, case):
            history = {k:v for k,v in case.items() if k not in {'entry','failure_history'}}
            case.setdefault('failure_history', []).append(history)
            case.update(status='PENDING', entry=row, publication_recovery_count=1,
                recovery_reason='One deterministic final-report format repair; audited saved judge reused, no model/record call')
        elif published(root, ident):
            case.update(status='SKIP_SCORED', reason='Existing table/publication/saved formal result protected')
        elif ident in USER_EXCLUDED or ident in config.get('excluded_cases', {}):
            case.update(status='SKIP_USER_EXCLUDED', reason=config.get('excluded_cases', {}).get(ident, USER_EXCLUDED.get(ident)))
        elif ident.startswith('Astra__G038_'):
            case.update(status='SKIP_USER_EXCLUDED', reason='User-directed delivery compile skip')
        elif (resume and case['status'] == 'BOUNDED_FAILURE'
                and case.get('error') == 'Prepared recovery lacks original native qualification'
                and not case.get('recorded_attempt') and not case.get('pre_native_repair_count')):
            # The previous selector confused a generic bundle with native evidence.
            # No model/record stage was started by this queue; repair that selection once.
            source = Path(case['recovery_source'])
            if not unity_recovery.prepared_sources([source]) and not (output/'cases'/ident/'single_state.json').exists():
                history = {k: v for k, v in case.items() if k not in {'entry', 'failure_history'}}
                case.setdefault('failure_history', []).append(history)
                case.update(status='PENDING', entry=row, pre_native_repair_count=1,
                    recovery_reason='Native qualification selector corrected before any new model/record call')
                state['consecutive_environment_failures'] = max(0, state['consecutive_environment_failures']-1)
        elif resume and unity_capture_policy.recoverable(output/'cases'/ident, case):
            history = {k:v for k,v in case.items() if k not in {'entry','failure_history'}}
            case.setdefault('failure_history', []).append(history)
            case.update(status='PENDING', entry=row, foreground_policy_recovery_count=1,
                recovery_reason='Explicit user permission for foreground presence; reuse unchanged real capture without rerecording or model calls')
            state['consecutive_environment_failures'] = max(0, state['consecutive_environment_failures']-1)
        elif resume and unity_native_compile_recovery.eligible(config['batch'], output/'cases'/ident, case, row):
            history = {k: v for k, v in case.items() if k not in {'entry', 'failure_history'}}
            case.setdefault('failure_history', []).append(history)
            case.update(status='PENDING', entry=row, native_compile_recovery_count=1,
                recovery_reason='One evidence-bound isolated compilation compatibility repair; original gameplay and prior failure retained')
        elif resume and unity_compile_compatibility.tool_repair_eligible(output/'cases'/ident, case):
            history = {k: v for k, v in case.items() if k not in {'entry', 'failure_history'}}
            case.setdefault('failure_history', []).append(history)
            case.update(status='PENDING', entry=row, import_compatibility_tool_repair_count=1,
                recovery_reason='Evaluator repair: apply reviewed imports before input migration; prior SHA failure retained')
        elif resume and unity_editor_compile_compatibility.eligible(config['batch'], output/'cases'/ident, case, row):
            history = {k: v for k, v in case.items() if k not in {'entry', 'failure_history'}}
            case.setdefault('failure_history', []).append(history)
            case.update(status='PENDING', entry=row, authored_entry_compile_compatibility_recovery_count=1,
                recovery_reason='Tuanjie-only optional authored Editor helper compatibility; BuildScene entry and runtime gameplay unchanged')
        elif resume and unity_compile_compatibility.eligible(config, output/'cases'/ident, case, row):
            history = {k:v for k,v in case.items() if k not in {'entry','failure_history'}}
            case.setdefault('failure_history', []).append(history)
            case.update(status='PENDING', entry=row, import_compatibility_recovery_count=1,
                recovery_reason='One SHA-bound namespace-import-only compatibility repair in isolated snapshot; native scene open required; prior failure retained')
        elif resume and unity_authored_entry.input_bus_recovery(config, output/'cases'/ident, case, row):
            history = {k:v for k,v in case.items() if k not in {'entry','failure_history'}}
            case.setdefault('failure_history', []).append(history)
            case.update(status='PENDING', entry=row, input_bus_migration_recovery_count=1,
                recovery_reason='One proven native input migration repair: preserve authored Input.ConsumeEdges bus; prior failed native receipt retained')
        elif resume and unity_authored_entry.eligible(config, output/'cases'/ident, case, row):
            history = {k:v for k,v in case.items() if k not in {'entry','failure_history'}}
            case.setdefault('failure_history', []).append(history)
            case.update(status='PENDING', entry=row, authored_scene_entry_recovery_count=1,
                recovery_reason='One SHA-bound delivered scene builder in isolated admission; no invented scene or gameplay; prior missing-scene result retained')
        elif resume and unity_packaging_recovery.eligible(output/'cases'/ident, case):
            history = {k:v for k,v in case.items() if k not in {'entry','failure_history'}}
            case.setdefault('failure_history', []).append(history)
            recovery_key = unity_packaging_recovery.recovery_key(case)
            case.update(status='PENDING', entry=row, **{recovery_key:1},
                recovery_reason='One bounded resume after proven packaging repair; qualified raw capture reused without recording/model calls')
        elif (resume and case['status'] == 'BOUNDED_FAILURE'
                and not case.get('partial_observation_recovery_count')
                and case.get('error') == 'Normal gameplay plan cannot have zero capture points'):
            from .partial_observation_recovery import ready_for_bounded_resume
            single = output/'cases'/ident/'single_state.json'
            if single.is_file() and ready_for_bounded_resume(Path(read(single)['attempt'])):
                history = {k:v for k,v in case.items() if k not in {'entry','failure_history'}}
                case.setdefault('failure_history',[]).append(history)
                case.update(status='PENDING',entry=row,partial_observation_recovery_count=1,
                    recovery_reason='One preinput observation schedule recovery; immutable accepted source retained, no new model calls or gameplay inputs')
        elif (resume and case['status'] == 'BOUNDED_FAILURE'
                and not case.get('plan_normalization_recovery_count')
                and (output/'cases'/ident/'single_state.json').is_file()
                and unity_plan_normalization.ready_for_bounded_resume(
                    Path(read(output/'cases'/ident/'single_state.json')['attempt']))):
            history = {k:v for k,v in case.items() if k not in {'entry','failure_history'}}
            case.setdefault('failure_history', []).append(history)
            case.update(status='PENDING', entry=row, plan_normalization_recovery_count=1,
                recovery_reason='Deterministic saved-plan format recovery; zero new model calls; original identity and evidence checks retained')
        elif (resume and case['status'] == 'BOUNDED_FAILURE'
                and not case.get('partial_static_recovery_count')
                and (output/'cases'/ident/'single_state.json').is_file()
                and partial_static_existence.eligible(
                    Path(read(output/'cases'/ident/'single_state.json')['attempt']))):
            history = {k:v for k,v in case.items() if k not in {'entry','failure_history'}}
            case.setdefault('failure_history', []).append(history)
            case.update(status='PENDING', entry=row, partial_static_recovery_count=1,
                recovery_reason='One conservative saved-static recovery: withdraw unbound EXISTS to UNKNOWN; raw Sol replies and source references preserved; no mechanic model call')
        elif (resume and case['status'] == 'BOUNDED_FAILURE'
                and not case.get('static_partition_recovery_count') and case.get('judge_attempt')
                and static_judge_recovery.eligible(Path(case['judge_attempt']))):
            history = {k:v for k,v in case.items() if k not in {'entry','failure_history'}}
            case.setdefault('failure_history', []).append(history)
            case.update(status='PENDING', entry=row, static_partition_recovery_count=1,
                recovery_reason='One fixed-size static transport repair; unchanged rubric/capture, completed dynamic model responses reused')
        elif (resume and case['status'] == 'BOUNDED_FAILURE'
                and not case.get('source_score_compact_repair_count')):
            from .unity_source_score_recovery import eligible
            single = output/'cases'/ident/'single_state.json'
            if single.is_file() and eligible(Path(read(single)['attempt'])):
                history = {k: v for k, v in case.items() if k not in {'entry', 'failure_history'}}
                case.setdefault('failure_history', []).append(history)
                case.update(status='PENDING', entry=row, source_score_compact_repair_count=1,
                    recovery_reason='One bounded recovery for oversized or deadline-starved source-score request; successful mechanic review reused')
                state['consecutive_environment_failures'] = max(0, state['consecutive_environment_failures']-1)
        elif case['status'] in RESUMABLE:
            case.update(status='PENDING', entry=row)
    return rows


def run_queue(root, config, output, models, *, resume=False, limit=0, dry_run=False, service_recovery_probe=None, rerecord_foreground_case=None):
    output.mkdir(parents=True, exist_ok=True)
    ledger = output/'queue_state.json'
    if ledger.is_file() and not resume:
        raise ValueError('Queue already exists; use --resume-queue; prior attempts are protected')
    config_sha = sha(Path(config['_configuration_path']))
    state = read(ledger) if ledger.is_file() else {'version': 'whitebox-formal-unity-queue.v2', 'cases': {},
        'started_unix': time.time(), 'configuration_sha256': config_sha, 'consecutive_environment_failures': config.get('inherited_environment_failures', 0)}
    if state['configuration_sha256'] != config_sha:
        raise ValueError('Queue configuration changed; preserve its frozen attempts')
    def save():
        state.update(updated_unix=time.time(), pid=os.getpid())
        dump(ledger, state)
        from .unity_progress import refresh
        refresh(root, output)
    if resume:
        review_saved_plan_failures(output, state)
    if (resume and state.get('status') == 'STOPPED_ENVIRONMENT_FAILURES'
            and state['consecutive_environment_failures'] >= config.get('environment_failure_stop_threshold', 3)):
        if dry_run:
            return state
        from .unity_service_recovery import authorize
        with coordinator(config):
            verify_acceptance(config)
            authorize(output, config, state, service_recovery_probe)
            dump(ledger, state)
    if rerecord_foreground_case and not dry_run:
        from .unity_capture_retry import authorize as authorize_capture
        with coordinator(config):
            verify_acceptance(config)
            authorize_capture(output, config, state, rerecord_foreground_case)
            dump(ledger, state)
    state.update(models=models, status='RUNNING')
    rows = prepare_cases(root, config, output, state, models, resume=resume, dry_run=dry_run)
    save()
    if dry_run:
        return state
    def waiting_for_lease():
        state.update(status='WAITING_SERIAL_LEASE', reason='Another production evaluator owns the shared Unity lease')
        save()
    with coordinator(config, waiting_for_lease), heartbeat(output, state, config):
        state.update(status='RUNNING')
        state.pop('reason', None)
        save()
        try:
            verify_acceptance(config)
        except Exception as exc:
            state.update(status='STOPPED_ACCEPTANCE',reason=str(exc))
            save()
            raise
        # Within each model, finish saved stages before opening another project.
        # Easy first pass precedes bounded repair revisits across the five models.
        deferred = set(config.get('deferred_cases', []))
        rows.sort(key=lambda row: (row['id'] in deferred, models.index(row['method']),
            0 if (output/'cases'/row['id']/'single_state.json').is_file() else 1, row['id']))
        attempted = 0
        for row in rows:
            ident = row['id']
            case = state['cases'][ident]
            if case['status'] != 'PENDING':
                continue
            if limit and attempted >= limit:
                break
            while True:
                try:
                    unity_safety.locks_clear(config, check_external=True)
                    break
                except unity_safety.SafetyStop as exc:
                    state.update(status='STOPPED_CLEANUP_UNCERTAIN',reason=str(exc))
                    save()
                    raise
                except BlockingIOError as busy:
                    case.update(status='WAITING_SERIAL_LOCK', reason=str(busy))
                    save()
                    time.sleep(15)
            # Scores can have appeared while waiting for another conversation.
            if published(root, ident, include_saved=not case.get('publication_recovery_count')):
                case.update(status='SKIP_SCORED', reason='Formal result appeared during serial wait')
                save()
                continue
            case.update(status='RUNNING', started_unix=case.get('started_unix', time.time()))
            attempted += 1
            def phase(name, **details):
                now = time.time()
                if case.get('phase_started_unix'):
                    previous = case.get('phase', 'unknown')
                    durations = case.setdefault('stage_seconds', {})
                    durations[previous] = durations.get(previous, 0)+now-case['phase_started_unix']
                case.update(phase=name, phase_started_unix=now, **details)
                save()
            try:
                paths = unity_recovery.attempts(root, ident, config.get('recovery_attempts', []))
                recovery_review = []
                prepared = unity_recovery.prepared_sources(paths, recovery_review)
                case['recovery_qualification_review'] = recovery_review
                captures = unity_recovery.capture_sources(paths)
                case_output = output/'cases'/ident
                reusable,diagnostics=unity_recovery.reusable_stages(paths,row)
                case['stage_reuse_review']=diagnostics
                if (case_output/'single_state.json').exists():
                    case.update(run_new(config, case_output, row, phase))
                elif prepared:
                    case['recovery_source'] = str(prepared[0])
                    result=unity_recovery.recover(config, prepared=prepared[0], phase=phase)
                    case.update(status=result.get('status','COMPLETE'), **{k:v for k,v in result.items() if k!='status'})
                elif captures:
                    # A failed/incompatible capture is retained, never silently replaced with a new recording.
                    case['recovery_source'] = str(captures[0])
                    result=unity_recovery.recover(config, source=captures[0], phase=phase)
                    case.update(status=result.get('status','COMPLETE'), **{k:v for k,v in result.items() if k!='status'})
                elif reusable:
                    case_output.mkdir(parents=True,exist_ok=True)
                    dump(case_output/'configuration.json',config)
                    dump(case_output/'single_state.json',{'attempt':str(reusable),'phase':'qualified_stage_reuse',
                        'started_unix':time.time(),'reuse_without_model_call':True})
                    case.update(run_new(config,case_output,row,phase))
                elif row.get('required_real_clients', 1) > 1:
                    case.update(status='BLOCKED_MULTICLIENT', reason='Production dual-client capture guard; no single-client substitute')
                else:
                    case.update(run_new(config, case_output, row, phase))
                state['consecutive_environment_failures'] = 0
            except Exception as exc:
                kind = classify_failure(exc)
                case.update(status='BOUNDED_FAILURE', failure_class=kind, error=str(exc), traceback=traceback.format_exc())
                dump(output/'failures'/(ident+'.json'), case)
                if kind in {'ENVIRONMENT', 'HARNESS'}:
                    state['consecutive_environment_failures'] += 1
                else:
                    state['consecutive_environment_failures'] = 0
                if kind == 'SAFETY':
                    state.update(status='STOPPED_CLEANUP_UNCERTAIN', reason=str(exc))
                    save()
                    raise
            finally:
                case['elapsed_seconds'] = time.time()-case['started_unix']
                single = output/'cases'/ident/'single_state.json'
                if single.exists():
                    latest = read(single)
                    case.update(recorded_attempt=latest.get('attempt'), judge_attempt=latest.get('judge_attempt'))
                case['metrics'] = metrics([case.get(k) for k in ('recorded_attempt', 'judge_attempt')])
                save()
            # Strict cleanup remains the default. Explicit user policy records
            # failed cleanup receipts without stopping other cases; locks and
            # live GUI-engine exclusion remain enforced at the next admission.
            owned = case.get('recorded_attempt')
            capture = Path(owned)/'background_record' if owned else None
            try:
                if owned and (Path(owned)/'background_record').exists():
                    capture = Path(owned)/'background_record'
                    if not (capture/'verification.json').exists() and not (capture/'preinput_cleanup_qualification.json').exists():
                        from .unity_preinput_cleanup import release
                        # This proof only qualifies an exact reviewed refusal before
                        # input/view mutation. Every other incomplete capture stops.
                        case['preinput_cleanup'] = release(config, capture)
                    unity_safety.capture_cleanup(capture)
                case['cleanup'] = unity_safety.check(config)
            except Exception as exc:
                from .unity_cleanup_policy import report_only, archive_marker, capture_report
                if not report_only(config):
                    state.update(status='STOPPED_CLEANUP_UNCERTAIN', reason=str(exc))
                    save()
                    raise
                archived = archive_marker(config)
                case['cleanup'] = capture_report(config, capture if capture and capture.exists() else None, error=exc)
                if archived:
                    case['cleanup']['marker_archive'] = archived
                case['cleanup_warning'] = str(exc)
            save()
            if state['consecutive_environment_failures'] >= config.get('environment_failure_stop_threshold', 3):
                state.update(status='STOPPED_ENVIRONMENT_FAILURES', reason='Consecutive bounded environment/harness failures reached configured threshold')
                save()
                return state
        state.update(status='UNITY_QUEUE_EXHAUSTED' if all(v['status'] != 'PENDING' for v in state['cases'].values()) else 'READY_RESUME', finished_unix=time.time())
        save()
    return state


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch', type=Path, required=True)
    parser.add_argument('--configuration', type=Path, required=True)
    parser.add_argument('--models', nargs='+', choices=MODEL_ORDER, default=list(MODEL_ORDER))
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--service-recovery-probe', type=Path)
    parser.add_argument('--rerecord-foreground-case')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    root = args.batch.resolve()
    config = read(args.configuration)
    if Path(config['batch']).resolve() != root:
        raise ValueError('Configuration batch mismatch')
    for key in ('adapter_root', 'control_root', 'editor_acceptance', 'snapshot_root', 'admission_root', 'queue_output'):
        if not config.get(key) or not Path(config[key]).is_absolute():
            raise ValueError('Missing explicit absolute production configuration: '+key)
    if config.get('plan_timeout_seconds', 1800) != 1800:
        raise ValueError('New Unity plans require the authorized independent 1800-second budget')
    config['_configuration_path'] = str(args.configuration.resolve())
    state = run_queue(root, config, Path(config['queue_output']), args.models, resume=args.resume,
                      limit=args.limit, dry_run=args.dry_run, service_recovery_probe=args.service_recovery_probe, rerecord_foreground_case=args.rerecord_foreground_case)
    print(json.dumps({'queue': str(Path(config['queue_output'])/'queue_state.json'), 'status': state['status'],
                      'counts': {key: sum(v['status'] == key for v in state['cases'].values())
                                 for key in sorted({v['status'] for v in state['cases'].values()})}}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
