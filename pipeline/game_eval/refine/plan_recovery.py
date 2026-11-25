"""One explicitly authorized, source-bound recovery of a rejected Stage3 plan.

The failed plan/response and its attempt are immutable. This is a separately
counted engineering recovery, never a repair conversation or automatic retry.
"""
from pathlib import Path
import json
from .common import read, sha, dump, once
from ..whitebox_eval.codex import call_codex, validate_schema
from ..whitebox_eval.runtime import NATIVE_KEYS

VERSION = 'refine.rejected-plan-recovery.v1'


def recover(folder, prompt, schema, config, validator):
    folder = Path(folder)
    auth_path = folder / 'plan_recovery_authorization.json'
    auth = read(auth_path)
    if (auth.get('version') != VERSION or auth.get('max_recoveries') != 1
            or auth.get('model') != config['sol']['model']
            or type(auth.get('timeout_seconds')) is not int
            or not 1 <= auth['timeout_seconds'] <= 1800):
        raise ValueError('Rejected-plan recovery needs one explicit bounded model authorization')
    required = {'failure': folder/'stages/plan.json',
                'response': folder/'model_calls/plan/response.json',
                'invocation': folder/'model_calls/plan/invocation.json',
                'validation': folder/'model_calls/plan/validation_error.json',
                'source': folder/'input/source_manifest.json',
                'tasks': folder/'input/tasks.json',
                'admission': folder/'native_admission.json'}
    if set(auth.get('parents', {})) != set(required):
        raise ValueError('Recovery parent bindings are incomplete')
    for name, path in required.items():
        if auth['parents'][name] != {'path': str(path.resolve()), 'sha256': sha(path)}:
            raise ValueError('Recovery parent changed: ' + name)
    failure, invocation = read(required['failure']), read(required['invocation'])
    if (failure['status'] != 'ERROR' or invocation.get('exit_code') != 0
            or invocation.get('model_requested') != auth['model']
            or read(required['validation']).get('response_sha256') != sha(required['response'])):
        raise ValueError('Recovery requires a completed model response rejected by validation')
    admitted = read(required['admission'])
    if config.get('ue_native_backend') != 'dock_native_sparse.v1' or admitted.get('scene') != '':
        raise ValueError('This recovery only supports the accepted UE default-map backend')
    # Metadata guidance corrects the failed producer contract; the original
    # native validator, endpoints, windows, rubric and scoring gates all remain.
    instructions = (
        '\nEXPLICIT ENGINEERING RECOVERY OF THE SAVED REJECTED PLAN. The previous response is at '
        '../model_calls/plan/response.json; it admitted its action route was incomplete. '
        'Return a NEW COMPLETE executable plan in the same output schema. Do not copy dangling action IDs. '
        'A small honest partial-coverage route is sufficient: prefer a few reachable tasks and mark other tasks '
        'executable=false with a reason that this route does not cover them, rather than inventing actions or '
        'claiming a product defect. Every frozen task still needs its original conditions extracted. '
        'Use concise strings; no padding steps, unencoded future route or placeholder sequence. '
        'EXACT METADATA: native_plan.engine="ue5", launch_scene="", '
        'launch_source="DockBeacon.uproject", watchers=[]. The accepted launch uses the author default map '
        'from Config/DefaultEngine.ini; empty scene means use that map, not a missing scene. '
        'The ORIGINAL native validator accepts these case-sensitive physical keys only: '
        + json.dumps(sorted(NATIVE_KEYS)) + '. Use Enter, E, Q, J, W etc.; lower-case aliases in the earlier '
        'backend note are not legal planner keys. Only input chords and wait steps. '
        'Do not treat local diagnostic mode as true multiplayer. This recovery adds no repair attempt. '
        'Keep the original recording budget and original task/rubric IDs. '
        'Declare only last_action_id values present in the returned action route and criterion binding; '
        'include explicit final waits through every endpoint/window. Return only the schema JSON.\n')
    binding = {'version': VERSION, 'authorization_sha256': sha(auth_path),
               'parents': auth['parents'], 'model': auth['model'],
               'prior_plan_attempts': 1, 'recovery_attempt': 1,
               'total_plan_calls_if_started': 2, 'repair_calls_added': 0,
               'timeout_seconds': auth['timeout_seconds']}
    binding_path = folder/'plan_recovery/binding.json'
    if binding_path.exists():
        if read(binding_path) != binding:
            raise ValueError('Rejected-plan recovery identity changed')
    else:
        dump(binding_path, binding)
    def invoke():
        result = call_codex(folder, name='plan_recovery_001', prompt=prompt+instructions,
                            schema=schema, model=auth['model'],
                            executable=config['sol'].get('executable', 'codex'),
                            timeout=auth['timeout_seconds'], max_attempts=1,
                            response_validator=validator)
        dump(folder/'plan_recovery/accepted_plan.json', result)
        dump(folder/'plan_recovery/result_binding.json', {
            'accepted_plan_sha256': sha(folder/'plan_recovery/accepted_plan.json'),
            'authorization_sha256': sha(auth_path)})
        return result
    result = once(folder, 'plan_recovery_001', invoke)
    accepted = folder/'plan_recovery/accepted_plan.json'
    if (read(accepted) != result or read(folder/'plan_recovery/result_binding.json') != {
            'accepted_plan_sha256': sha(accepted), 'authorization_sha256': sha(auth_path)}):
        raise ValueError('Recovered plan binding changed')
    validate_schema(result, schema)
    validator(result)
    dump(folder/'plan.json', result)
    return result
