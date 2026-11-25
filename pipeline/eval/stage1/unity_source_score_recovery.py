"""One bounded recovery for oversized or deadline-starved initial source requests.

Keep the failed invocation and its budget untouched. A new immutable attempt
reuses the successful mechanic review verbatim and asks only the compact columns.
"""
from pathlib import Path
import shutil
import time

from . import batch, core12, static_existence
from .protocol import dump, sha

RECEIPT = 'source_score_compact_recovery.json'


def eligible(source):
    source = Path(source)
    if any((source/name).exists() for name in (RECEIPT, 'sol_plan.json', 'background_record', 'static_source_scores.json')):
        return False
    folder = source/'model_calls/source_code_scores'
    try:
        invocation = batch.read(folder/'invocation.json')
        schema = batch.read(folder/'schema.json')
        return (invocation.get('status') == 'TIMEOUT'
                and recovery_reason(source) is not None
                and (source/'static_existence.json').is_file())
    except (OSError, KeyError, ValueError):
        return False


def recovery_reason(source):
    """A compact call starved by the first review gets one fresh linked attempt.

    A full-budget compact timeout never qualifies. The old static deadline and
    response remain immutable, and the successful mechanic review is reused.
    """
    source = Path(source)
    folder = source/'model_calls/source_code_scores'
    try:
        schema = batch.read(folder/'schema.json')
        columns = schema['properties']['checks']['properties']
        if len(columns) > 8:
            return 'Replace superseded per-atom initial-score output with one source score per existing column'
        budget = batch.read(folder/'budget.json')
        invocation = batch.read(folder/'invocation.json')
        seconds = budget['effective_timeout_seconds']
        if (set(columns) == {'column.'+str(i) for i in (0, 2, 3, 4, 5, 6, 7)}
                and type(seconds) in (int, float) and 0 < seconds < 300
                and invocation.get('status') == 'TIMEOUT'
                and invocation.get('seconds', 0) >= seconds
                and not (folder/'response.json').exists()):
            return 'One fresh static budget for compact source scores after the prior mechanic review consumed most of the original static deadline'
    except (OSError, KeyError, TypeError, ValueError):
        pass
    return None


def prepare(source):
    source = Path(source).resolve()
    ident = batch.read(source/'input_manifest.json')['entry']['id']
    for receipt in source.parent.glob(ident+'__source_scores_v2_recovery_*/'+RECEIPT):
        value = batch.read(receipt)
        if Path(value['source_attempt']).resolve() == source:
            if any(sha(source/name) != digest for name, digest in value['source_bindings'].items()):
                raise ValueError('Preserved source-score recovery source changed')
            batch.verify_inputs(receipt.parent)
            static_existence.load(receipt.parent, batch.read(receipt.parent/'input/pilot_rubric.json'))
            return receipt.parent
    if not eligible(source):
        raise ValueError('No bounded compact-source recovery is qualified')
    batch.verify_inputs(source)
    protocol = core12.verify_attempt(source, 'unity3d')
    original = static_existence.load(source, protocol)
    entry = batch.read(source/'input_manifest.json')['entry']
    from .unity_queue import published
    if published(source.parents[1], entry['id']):
        raise ValueError('Existing formal score is protected')
    root = source.parent/(entry['id']+'__source_scores_v2_recovery_'+str(time.time_ns()))
    batch.prepare(source.parents[1], entry, root, previous_attempt=source)
    # Require unchanged identities, not a rewritten fingerprint or verdict.
    if static_existence.identity(root, batch.read(root/'input/pilot_rubric.json')) != original['identity']:
        raise ValueError('Source recovery identity changed; keep both attempts and stop')
    files = ['static_existence.json']
    shutil.copy2(source/'static_existence.json', root/'static_existence.json')
    from .partial_static_existence import RECEIPT as partial_static_receipt
    if (source/partial_static_receipt).is_file():
        shutil.copy2(source/partial_static_receipt, root/partial_static_receipt)
        files.append(partial_static_receipt)
    for folder in (source/'model_calls').glob('static_existence*'):
        if folder.is_dir():
            shutil.copytree(folder, root/'model_calls'/folder.name)
            files.extend(str(p.relative_to(source)) for p in folder.rglob('*') if p.is_file())
    static_existence.load(root, protocol)
    from .route_first_capture import install_compact_policy
    install_compact_policy(root)
    files.extend('model_calls/source_code_scores/'+name for name in (
        'invocation.json', 'budget.json', 'prompt.txt', 'schema.json', 'events.jsonl', 'stderr.log')
        if (source/'model_calls/source_code_scores'/name).is_file())
    dump(root/RECEIPT, {'version': 'whitebox-source-score-compact-recovery.v1',
        'source_attempt': str(source), 'source_bindings': {name: sha(source/name) for name in files},
        'mechanic_verdict_copied_verbatim': True, 'mechanic_calls_added': 0,
        'plan_calls_added': 0, 'prior_budget_unchanged': True, 'maximum_recoveries': 1,
        'authorization': 'User 2026-10-29: bounded harness correction; normalize auxiliary format and continue real recording',
        'reason': recovery_reason(source)})
    return root
