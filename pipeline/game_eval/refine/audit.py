"""Separate, model-free replay audit before a local refinement report is saved."""
from pathlib import Path
from .common import read, sha, dump
from .session import inventory
from . import evidence
from .scoring import static_credit, score


def audit(folder, game, proposed, *, judge_stages=None):
    folder = Path(folder)
    from ..whitebox_eval.unity_safety import capture_cleanup
    if (folder/'native_admission.json').exists() and read(folder/'native_admission.json').get('native_acceptance'):
        from .ue_cleanup import verify as ue_cleanup
        cleanup = ue_cleanup(folder)
    else:
        cleanup = capture_cleanup(folder / 'background_record')
    manifest = read(folder / 'evidence/manifest.json')
    evidence.verify_manifest(folder, manifest)
    if inventory(folder / 'input/project') != read(folder / 'input/source_manifest.json')['files']:
        raise ValueError('Audit: frozen source changed')
    original = read(folder / 'original_project.json')
    if inventory(original['root']) != original['files']:
        from ..whitebox_eval.unity_safety import SafetyStop
        raise SafetyStop('Original delivery changed before final audit')
    codes = {r['task_id']: static_credit(folder / 'input', r) for r in read(folder / 'static.json')['checks']}
    references = read(folder / 'reference_renders.json')
    for reference in references.values():
        if sha(reference['source_path']) != reference['source_sha256']:
            raise ValueError('Audit: original GLB changed')
        for image in reference['views']:
            if sha(image['path']) != image['sha256']:
                raise ValueError('Audit: original reference render changed')
    endpoints = {e['task_id']: e for e in read(folder / 'plan.json')['endpoints']}
    recomputed = []
    if judge_stages is not None and (not judge_stages or len(judge_stages) != len(set(judge_stages))
            or any(not __import__('re').fullmatch(r'judge_[a-zA-Z0-9_]+', s) for s in judge_stages)):
        raise ValueError('Audit: invalid explicit judge stages')
    deliveries = (sorted(folder.glob('evidence/judge_*_delivery.json')) if judge_stages is None else
                  [folder / 'evidence' / (s + '_delivery.json') for s in judge_stages])
    for path in deliveries:
        delivery = read(path)
        stage = path.name.removesuffix('_delivery.json')
        specs = {t['task_id']: t for t in delivery['tasks']}
        for image in delivery['images']:
            if sha(image['path']) != image['sha256']:
                raise ValueError('Audit: delivered image changed')
        if len(delivery['images']) > 100:
            raise ValueError('Audit: >100 images')
        for row in read(folder / (stage + '.json'))['checks']:
            ident = row['task_id']
            spec = specs[ident]
            gates = evidence.proof(folder, row, endpoints[ident], manifest, references.get(ident), delivery)
            result = score(row, codes[ident], gates, needs_window=spec['needs_window'],
                is_geometry=spec.get('asset_kind') in ('3d_object', '3d_scene'), is_import=spec['kind'] == 'import')
            if spec.get('asset_kind') == 'audio' and result['credit_percent'] == 100:
                result.update(credit_percent=50, verdict='UNVERIFIED',
                              limitation='No native audio evidence channel; runtime integration only')
            if spec.get('payload_status', 'READY') != 'READY':
                result.update(credit_percent=None, verdict='UNVERIFIED', blocker=spec['payload_status'])
            recomputed.append(result)
    expected = {r['task_id'] for r in read(folder / 'input/tasks.json')}
    if (len(recomputed) != len(expected) or {r['task_id'] for r in recomputed} != expected
            or recomputed != proposed):
        raise ValueError('Audit: result differs from immutable physical evidence and saved judge')
    dump(folder / 'independent_audit.json', {'status': 'PASS', 'scope': 'deterministic provenance/tier replay; not a second semantic model',
        'checked_tasks': len(recomputed), 'cleanup': cleanup, 'evidence_manifest_sha256': sha(folder / 'evidence/manifest.json'),
        'official_whitebox_publication': False})
    return True


def product_failure_result(folder, game):
    """Actual native compilation failure is a terminal benchmark outcome, not a tool error."""
    folder = Path(folder)
    tasks = read(folder / 'input/tasks.json')
    codes = {r['task_id']: static_credit(folder / 'input', r) for r in read(folder / 'static.json')['checks']}
    return {'version': 'refine.report.v1', 'game_id': game['game_id'], 'status': 'EVALUATED',
        'pipeline_completed': True, 'product_status': 'COMPILE_FAILED', 'formal_whitebox_score': None,
        'checks': [{'task_id': t['task_id'], 'verdict': 'UNVERIFIED', 'execution': 'NOT_RUN',
            'credit_percent': (None if t.get('payload_status', 'READY') != 'READY' else 10 if codes[t['task_id']] else 0),
            'static_credit_percent': 10 if codes[t['task_id']] else 0,
            'blocker': t.get('payload_status') if t.get('payload_status', 'READY') != 'READY' else 'PRODUCT_COMPILE_ERROR',
            'reason': 'Actual native import failed with product C# errors; runtime tiers not earned. Static credit only.'}
            for t in tasks],
        'native_admission': read(folder / 'native_admission.json'),
        'note': 'Completed benchmark failure path. No plan/record/judge was fabricated or required for an unbuildable product; no historic scores changed.'}


def audit_product_failure(folder, game, proposed):
    folder = Path(folder)
    admission = read(folder / 'native_admission.json')
    if (admission.get('status') != 'PRODUCT_FAILURE' or sha(admission['receipt']) != admission['receipt_sha256']
            or sha(admission['editor_log']) != admission['editor_log_sha256']):
        raise ValueError('Product-failure audit: native receipt/log missing or changed')
    record = read(admission['receipt'])
    snapshot_path = Path(record['source_snapshot'])
    snapshot = read(snapshot_path)
    if (sha(snapshot_path) != admission.get('source_snapshot_sha256')
            or Path(snapshot['source']).resolve() != (folder / 'input/project').resolve()
            or Path(record['source_project']).resolve() != (folder / 'input/project').resolve()
            or any(sha(folder / 'input/project' / name) != value for name, value in snapshot['files_sha256'].items())
            or not snapshot['files_sha256']):
        raise ValueError('Product-failure audit: native import is not bound to evaluated source')
    from ..whitebox_eval.unity_editor_selection import failure_classification
    log = Path(admission['editor_log']).read_text(errors='replace')
    if (record.get('product_status') != 'NATIVE_OPEN_FAILED' or record.get('failure_class') != 'PRODUCT'
            or failure_classification(log) != 'PRODUCT' or record.get('execution', {}).get('timed_out')
            or record.get('source_unchanged', {}).get('ok') is not True):
        raise ValueError('Product-failure audit: not a proven native product compilation failure')
    if not all(record.get('cleanup', {}).get(k) is True for k in ('input_cleanup','view_cleanup','process_cleanup')):
        raise ValueError('Product-failure audit: cleanup uncertain')
    if inventory(folder / 'input/project') != read(folder / 'input/source_manifest.json')['files']:
        raise ValueError('Product-failure audit: evaluated source changed')
    original = read(folder / 'original_project.json')
    if inventory(original['root']) != original['files']:
        raise ValueError('Product-failure audit: original delivery changed')
    if proposed != product_failure_result(folder, game):
        raise ValueError('Product-failure audit: wrong static scores or fabricated runtime credit')
    dump(folder / 'independent_audit.json', {'status':'PASS', 'scope':'native product compilation failure + static credit replay',
        'checked_tasks':len(proposed['checks']), 'native_receipt_sha256':sha(admission['receipt']),
        'editor_log_sha256':sha(admission['editor_log']), 'runtime_executed':False, 'official_whitebox_publication':False})
    return True
