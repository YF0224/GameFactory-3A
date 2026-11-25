"""Resume preserved Unity evidence without invoking a planner or recorder."""
from pathlib import Path
import time

from . import batch, integrity, static_existence, unity_safety
from .protocol import dump, sha


def attempts(batch_root, ident, extra=()):
    """Inspect bounded attempt directories, never recursively scan deliveries."""
    roots = [Path(batch_root)/name for name in ('runs', 'recovery_runs')]
    found = set()
    for folder in roots:
        for path in folder.glob(ident+'*'):
            if path.is_dir() and (path/'input_manifest.json').is_file():
                entry = batch.read(path/'input_manifest.json').get('entry', {})
                if entry.get('id') == ident:
                    found.add(path.resolve())
    for value in extra:
        path = Path(value).resolve()
        if (path/'input_manifest.json').is_file():
            if batch.read(path/'input_manifest.json').get('entry', {}).get('id') == ident:
                found.add(path)
    return sorted(found, key=lambda p: p.stat().st_mtime, reverse=True)


def saved_score(paths):
    """Protect an existing formal result even if a publication/effective view is stale."""
    for path in paths:
        score = path/'scores.json'
        if not score.is_file():
            continue
        value = batch.read(score)
        if value.get('valid') is True and isinstance(value.get('overall_score'), (int, float)):
            return {'attempt': str(path), 'score': value['overall_score'], 'sha256': sha(score),
                    'reason': 'Saved formal score protected; no automatic rejudge or republication'}
    return None


def capture_sources(paths):
    return [path for path in paths if (path/'background_record').is_dir()]


def prepared_sources(paths, diagnostics=None):
    """A generic historic evidence bundle does not establish native capture qualification.

    Leave unqualified bundles intact and report the exclusion before choosing a
    native recovery route. Qualified but broken captures still fail explicitly;
    they are never silently replaced by a new recording.
    """
    found = []
    for path in paths:
        if not ((path/'evidence_manifest.json').is_file()
                and (path/'runtime/frame_index.jsonl').is_file()
                and not (path/'scores.json').is_file()):
            continue
        if not any((path/name).is_file() for name in (
                'recorded_capture_provenance.json', 'independent_native_plan_capture_audit.json')):
            if diagnostics is not None:
                diagnostics.append({'attempt': str(path), 'reuse': False,
                    'reason': 'Generic evidence bundle has no original native qualification'})
            continue
        found.append(path)
    return found


def reusable_stages(paths, row):
    """Select only exactly bound source/plan stages; retain rejection diagnostics."""
    from . import core12
    diagnostics=[]
    for root in paths:
        if not (root/'static_existence.json').is_file():continue
        try:
            batch.verify_inputs(root)
            protocol=core12.verify_attempt(root,'unity3d')
            entry=batch.read(root/'input_manifest.json')['entry']
            admission=entry.get('native_open_admission')
            if not admission:raise ValueError('No bound native-open qualification for the frozen source')
            receipt=Path(admission['receipt'])
            opened=batch.read(receipt)
            if sha(receipt)!=admission['sha256'] or Path(opened['source_project']).resolve()!=Path(row['project']).resolve():
                raise ValueError('Admission/source identity differs')
            from engine_adapters.unity3d.playtest.background_record import check_original
            original=batch.read(Path(opened['source_snapshot']))
            if not check_original(original)['ok']:raise ValueError('Original delivery SHA changed')
            if opened['product_status']!='OPENED' or not all(opened['cleanup'].get(k) is True for k in unity_safety.CLEANUP_KEYS):
                raise ValueError('Native opening/cleanup not qualified')
            static_existence.load(root,protocol)
            if (root/'sol_plan.json').is_file():
                batch.validate_operation_plan(root,batch.read(root/'sol_plan.json'),'unity3d')
            elif (root/'model_calls/plan').exists():
                raise ValueError('Planner already attempted; original failure preserved, no implicit retry')
            elif protocol['runtime_budget']['plan_timeout_seconds']!=1800:
                raise ValueError('Old frozen budget cannot silently become a new 1800-second call')
            return root,diagnostics
        except (OSError,ValueError,KeyError,AssertionError) as exc:
            diagnostics.append({'attempt':str(root),'reason':str(exc),'reuse':False})
    return None,diagnostics


def qualify_capture(source):
    """Check immutable input, saved plan, real native receipts and recorded files."""
    source = Path(source)
    batch.verify_inputs(source)
    protocol = batch.read(source/'input/pilot_rubric.json')
    batch.validate_operation_plan(source, batch.read(source/'sol_plan.json'), 'unity3d')
    static_existence.load(source, protocol)
    cleanup = unity_safety.capture_cleanup(source/'background_record')
    verification = batch.read(source/'background_record/verification.json')
    from .unity_capture_policy import qualify
    qualify(source)
    return {'source': str(source), 'bindings': {name: sha(source/name) for name in (
        'input_manifest.json', 'input/pilot_rubric.json', 'sol_plan.json', 'static_existence.json',
        'background_record/verification.json', 'background_record/runner_exit.json')}, 'cleanup': cleanup}


def recover(config, *, source=None, prepared=None, phase=lambda *a, **k: None):
    """Judge a qualified original identity, audit, then target only its unscored row."""
    if bool(source) == bool(prepared):
        raise ValueError('Choose exactly one recorded or prepared recovery source')
    if source:
        source = Path(source).resolve()
        qualification = qualify_capture(source)
        pointer = source/'active_background_judge_attempt.json'
        if pointer.is_file():
            root = Path(batch.read(pointer)['attempt']).resolve()
        else:
            from .recorded_import_review import create_import_review
            from .prepare_unity_recorded_judge import prepare
            phase('evidence', recorded_attempt=str(source))
            create_import_review(source)
            root = prepare(source)
        dump(root/'queue_capture_qualification.json', qualification)
    else:
        root = Path(prepared).resolve()
        batch.verify_inputs(root)
        provenance = root/'recorded_capture_provenance.json'
        if provenance.is_file():
            source = Path(batch.read(provenance)['source_attempt']).resolve()
            unity_safety.capture_cleanup(source/'background_record')
        elif not (root/'independent_native_plan_capture_audit.json').is_file():
            raise ValueError('Prepared recovery lacks original native qualification')
        batch.verify_runtime_sources(root)
        bundle = batch.validate_capture_bundle(root, batch.read(root/'evidence_manifest.json'))
        if not bundle['valid']:
            raise ValueError('Prepared capture bundle failed: '+str(bundle))
    # Actual three-part cleanup must be checked before publication as well as afterwards.
    cleanup_path = root/'runtime/native_cleanup.json'
    if source:
        cleanup = unity_safety.capture_cleanup(source/'background_record')
        if not cleanup_path.exists():
            dump(cleanup_path, {key: cleanup[key] for key in unity_safety.CLEANUP_KEYS})
    if not cleanup_path.is_file() or not all(batch.read(cleanup_path).get(k) is True for k in unity_safety.CLEANUP_KEYS):
        raise unity_safety.SafetyStop('Prepared recovery lacks verified input/view/process cleanup')
    manifest=batch.read(root/'evidence_manifest.json')
    if not any(row['id']=='NATIVE_CLEANUP' for row in manifest['items']):
        manifest['items'].append({'id':'NATIVE_CLEANUP','path':'runtime/native_cleanup.json',
            'type':'document','sha256':sha(cleanup_path)})
        dump(root/'evidence_manifest.json',manifest)
    phase('judge', recorded_attempt=str(source) if source else None, judge_attempt=str(root))
    protocol = batch.read(root/'input/pilot_rubric.json')
    if not (root/'scores.json').is_file():
        from .unity_stage_timeouts import resolve
        entry=batch.read(root/'input_manifest.json')['entry']
        batch.judge(root, static_existence.MODEL, resolve(entry,protocol,'judge',config))
    from .pending_publication import deferred, publish as publish_pending
    if deferred(config):
        unity_safety.locks_clear(config)
        phase('pending_publication', judge_attempt=str(root))
        result=publish_pending(root)
        unity_safety.locks_clear(config)
        phase('SCORED_PENDING_AUDIT', **result)
        return result
    phase('audit', judge_attempt=str(root))
    audit = integrity.audit_run(root)
    dump(root/'independent_audit.json', audit)
    if not audit['valid']:
        raise ValueError('Independent recovery audit failed: '+str(audit.get('reason')))
    unity_safety.locks_clear(config)
    phase('publication', judge_attempt=str(root))
    from .targeted_publication import main as publish
    if not (root/'formal_publication_receipt.json').is_file():
        publish(['--attempt', str(root)])
    from .effective import resolve_result
    entry = batch.read(root/'input_manifest.json')['entry']
    effective = resolve_result(Path(config['batch']), entry)
    if not effective['valid'] or effective['root'].resolve() != root:
        raise ValueError('Recovery effective source does not select the audited result')
    unity_safety.locks_clear(config)
    result = {'attempt': str(root), 'score': batch.read(root/'scores.json')['overall_score'],
              'effective_source': str(effective['root']), 'finished_unix': time.time()}
    phase('COMPLETE', **result)
    return result
