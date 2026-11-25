"""Revalidate accepted complete source delivery across exact producer updates.

The original authorization, call and delivery remain immutable. Only an explicit
archived runtime continuation may resolve drift; all source bytes, order and
actual request bytes are independently checked again by the original validators.
"""
from pathlib import Path
from . import mechanic_v3_runner as runner
from . import gameness_v4_contract_read_manifest_recovery as manifest
from . import gameness_v4_production_continuation as continuation
from .codex import READ_ONLY_EVAL_INSTRUCTIONS
from .protocol import sha


def verify_frozen_delivery(folder, reference):
    folder = Path(folder)
    parent = folder / manifest.AUTH
    if not parent.is_file():
        return manifest.verify_frozen_delivery(folder, reference)
    value = runner.read(parent)
    if (value.get('version') != manifest.VERSION
            or value.get('recovery_task') != manifest.TASK):
        raise ValueError('Unknown frozen source manifest')
    continuation.verified_bindings(parent, value['bindings'])
    if reference != value['source_authorization']:
        raise ValueError('Frozen source manifest reference differs')
    source = manifest.chunks.verify(reference)
    call = folder / 'model_calls' / manifest.TASK
    texts = [p.read_text() for p in sorted(
        (Path(reference['path']).parent / 'chunks').glob('*.txt'))]
    events = call / 'events.jsonl'
    proof = manifest.chunks.ordered_source_outputs(events.read_text(), texts)
    expected = READ_ONLY_EVAL_INSTRUCTIONS + manifest.packet(folder, reference)
    if (call / 'prompt.txt').read_bytes() != expected.encode():
        raise ValueError('Actual frozen manifest request differs')
    receipt = dict(version=manifest.VERSION,
        authorization=dict(path=str(parent), sha256=sha(parent)),
        source_sha256=source['source_sha256'],
        all_original_author_bytes_actually_delivered=True,
        original_physical_lines=True, chunk_count=len(texts),
        ordered_output_proof=proof, prompt_sha256=sha(call / 'prompt.txt'),
        events_sha256=sha(events))
    retained = call / 'actual_delivery.json'
    if not retained.is_file() or runner.read(retained) != receipt:
        raise ValueError('Retained frozen manifest actual delivery differs')
    return receipt


def verify_accepted_contract(folder):
    """Accepted source calls must still bind the frozen canonical contract."""
    folder = Path(folder)
    if not (folder / manifest.AUTH).is_file():
        return
    call = folder / 'model_calls' / manifest.TASK
    invocation = runner.read(call / 'invocation.json')
    if (invocation.get('exit_code') != 0
            or invocation.get('model_requested') != manifest.policy.MODEL):
        raise ValueError('Frozen source invocation differs')
    from .codex import saved_model_response
    if runner.read(saved_model_response(folder, manifest.TASK)) != runner.read(folder / 'contract.json'):
        raise ValueError('Frozen contract differs from accepted source response')
