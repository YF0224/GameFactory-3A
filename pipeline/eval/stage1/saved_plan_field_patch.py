"""Replay a completed, anchored first correction without another model call."""
from pathlib import Path

from .protocol import sha


def replay(response, root):
    from . import batch, plan_patches
    root, response = Path(root).resolve(), Path(response).resolve()
    base = root/'model_calls/plan/response.json'
    if response != root/'model_calls/plan_002/response.json':
        raise ValueError('Saved field correction must be the first bounded correction')
    authorization = batch.read(root/'route_metadata_repair.json')
    if (authorization.get('version') != 'whitebox-route-metadata-repair.v1'
            or not authorization.get('authorization')):
        raise ValueError('Saved correction requires explicit execution authorization')
    folders = {p for p in (root/'model_calls').glob('plan*') if p.is_dir()}
    if folders != {base.parent, response.parent}:
        raise ValueError('Later or in-flight planner calls require separate review')
    calls = [batch.read(p.parent/'invocation.json') for p in (base, response)]
    if (any(c.get('exit_code') != 0 for c in calls)
            or not calls[0].get('model_requested')
            or calls[0].get('model_requested') != calls[1].get('model_requested')):
        raise ValueError('Saved correction requires successful same-model invocations')
    failures = [p for p in (base.parent/'validation_error.json', base.parent/'schema_error.json') if p.is_file()]
    if not any(batch.read(p).get('response_sha256') == sha(base) for p in failures):
        raise ValueError('Saved correction failure is not bound to its base response')
    patch = plan_patches.loads(response.read_bytes())
    result = plan_patches.apply(base.read_bytes(), patch)
    # Normal validators still verify frozen identity, schema, source SHA, keys,
    # timeline and endpoint limitations. This only reconstructs Sol's reply.
    return result, [{'kind':'replay_saved_field_correction',
        'base':str(base.relative_to(root)), 'base_sha256':sha(base),
        'patch':str(response.relative_to(root)), 'patch_sha256':sha(response),
        'invocation_sha256':[sha(p.parent/'invocation.json') for p in (base,response)],
        'failure_sha256':{str(p.relative_to(root)):sha(p) for p in failures},
        'edits':patch['edits'], 'model_calls_added':0,
        'physical_actions_changed_by_saved_model_correction':any(
            e['path'].startswith('/probes/') for e in patch['edits'])}]
