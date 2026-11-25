"""Replay a saved Sol correction that fills an empty, uncredited Unity route.

Never replaces an existing route or invents controls. All executable steps come
from the preserved correction; normal source/identity/input validators still run.
"""
import copy
from pathlib import Path

from .protocol import sha

VERSION = 'whitebox-empty-probe-patch-recovery.v1'


def replay(response, root):
    from . import batch, plan_patches, runtime
    from .codex import validate_schema
    root, response = Path(root).resolve(), Path(response).resolve()
    folder = response.parent
    if folder.parent != root/'model_calls' or folder.name != 'plan_002':
        raise ValueError('Empty-route recovery requires the first bounded correction')
    policy = root/'route_metadata_repair.json'
    authorization = batch.read(policy)
    if (authorization.get('version') != 'whitebox-route-metadata-repair.v1'
            or not authorization.get('authorization')):
        raise ValueError('Empty-route recovery requires explicit execution authorization')
    base = root/'model_calls/plan/response.json'
    raw = base.read_bytes()
    original, patch = plan_patches.loads(raw), plan_patches.loads(response.read_bytes())
    validate_schema(patch, plan_patches.PATCH_SCHEMA)
    if patch['base_sha256'] != sha(base) or original.get('engine') != 'unity3d' or original.get('probes') != []:
        raise ValueError('Empty-route correction base differs or already contains a route')
    failure = batch.read(base.parent/'validation_error.json')
    if (failure.get('exception') != 'invalid native probe count'
            or failure.get('response_sha256') != sha(base)):
        raise ValueError('Empty-route failure is not bound to the preserved response')
    calls = [batch.read(path.parent/'invocation.json') for path in (base, response)]
    if (any(call.get('exit_code') != 0 for call in calls)
            or calls[0].get('model_requested') != calls[1].get('model_requested')
            or not calls[0].get('model_requested')):
        raise ValueError('Correction requires successful same-model invocations')
    folders = [p for p in (root/'model_calls').glob('plan*') if p.is_dir()]
    if set(folders) != {base.parent, folder}:
        raise ValueError('Later or in-flight planner calls require separate review')
    coverage = original.get('coverage')
    windows = coverage.values() if isinstance(coverage, dict) else coverage
    endpoints = original.get('capture_plan', {}).get('endpoints', {})
    if (not windows or not endpoints or any(w.get('status') != 'UNVERIFIED' for w in windows)
            or any(e.get('reachability') != 'UNREACHABLE' for e in endpoints.values())):
        raise ValueError('Empty-route recovery cannot introduce endpoint completion claims')
    edits = patch['edits']
    route_edits = [e for e in edits if e['path'] == '/probes']
    if len(route_edits) != 1:
        raise ValueError('Correction must fill exactly the empty probes field')
    route_edit = route_edits[0]
    if route_edit['op'] != 'replace' or plan_patches.loads(route_edit['before_json']) != []:
        raise ValueError('Correction must be anchored to an empty route')
    other = [e for e in edits if e is not route_edit]
    for edit in other:
        if edit['op'] != 'replace' or edit['before_json'] != edit['value_json']:
            raise ValueError('Empty-route correction cannot change other fields')
    ignored_noops = []
    for edit in other:
        try:
            plan_patches.apply(raw, dict(base_sha256=patch['base_sha256'], edits=[edit]))
        except ValueError:
            # A self-replacement cannot change the base. A saved correction may
            # misremember this ancillary budget, but must not overwrite it. Only
            # this scalar budget no-op can be discarded; never ignore a real
            # edit or a stale anchor on any physical/control/source field.
            if (edit['path'] != '/max_duration_ms'
                    or not (root/'unsupported_input_policy.json').is_file()
                    or type(original.get('max_duration_ms')) is not int
                    or type(plan_patches.loads(edit['value_json'])) is not int):
                raise
            ignored_noops.append({'path':edit['path'],
                'before_json':edit['before_json'], 'value_json':edit['value_json'],
                'retained_original_value':original['max_duration_ms'],
                'reason':'discard_stale_budget_self_replacement_without_applying_it'})
    probes = plan_patches.loads(route_edit['value_json'])
    if not isinstance(probes, list) or not 1 <= len(probes) <= 10:
        raise ValueError('Unbounded corrected route')
    retained = copy.deepcopy(probes)
    defaults = dict(watch='', op='eq', value=0, target_watch='', timeout_ms=0)
    probe_keys = {'id','purpose','criterion_ids','preconditions','steps'}
    step_keys = {'id','kind','key','duration_ms','purpose','expected_observation', *defaults}
    aliases = {'ENTER':'Enter','RETURN':'Return','ESC':'Esc','ESCAPE':'Escape','SPACE':'Space',
               'SHIFT':'Shift','TAB':'Tab','LEFT':'Left','RIGHT':'Right','UP':'Up','DOWN':'Down'}
    for probe in probes:
        if set(probe) != probe_keys or probe['criterion_ids'] != []:
            raise ValueError('Corrected observation route must claim no criteria')
        hints = probe['preconditions']
        if (not isinstance(hints, list) or not all(isinstance(x, str) and x.strip() for x in hints)):
            raise ValueError('Executable state predicates cannot be discarded')
        # Text is not an executable predicate in the native adapter. Preserve it
        # as a planner hint, not as an observed/prevalidated startup condition.
        if hints:
            probe['purpose'] += '\nUNVERIFIED planner startup hints: '+'; '.join(hints)
        probe['preconditions'] = []
        if not isinstance(probe['steps'], list) or not 1 <= len(probe['steps']) <= 24:
            raise ValueError('Unbounded corrected steps')
        for step in probe['steps']:
            if set(step)-step_keys or not {'id','kind','duration_ms','purpose','expected_observation'} <= set(step):
                raise ValueError('Corrected step contains unknown or missing physical fields')
            if step['kind'] == 'key_press':
                step['kind'] = 'input'
            if step['kind'] not in {'input','wait'}:
                raise ValueError('Empty-route recovery only supports declared keyboard/wait actions')
            if step['kind'] == 'input':
                key = step.get('key')
                if not isinstance(key, str):
                    raise ValueError('Missing declared key')
                step['key'] = '+'.join(aliases.get(k,k) for k in key.split('+'))
                if not 1 <= len(step['key'].split('+')) <= 3 or any(k not in runtime.NATIVE_KEYS for k in step['key'].split('+')):
                    raise ValueError('Unknown corrected physical key')
            else:
                if step.get('key', '') != '':
                    raise ValueError('Wait must not hide an input key')
                step['key'] = ''
            for key, value in defaults.items():
                if key in step and step[key] != value:
                    raise ValueError('State-dependent action cannot become unconditional')
                step.setdefault(key, value)
            if type(step['duration_ms']) is not int or not 0 <= step['duration_ms'] <= 6000:
                raise ValueError('Unbounded corrected action duration')
    result = copy.deepcopy(original)
    result['probes'] = probes
    bindings = [base, base.parent/'invocation.json', base.parent/'schema.json',
                base.parent/'validation_error.json', response, folder/'invocation.json', folder/'schema.json', policy]
    if ignored_noops:
        bindings.append(root/'unsupported_input_policy.json')
    return result, [{'kind':'replay_saved_empty_probe_correction', 'version':VERSION,
        'bindings':{str(p.relative_to(root)):sha(p) for p in bindings},
        'ignored_nonmutating_budget_edits':ignored_noops,
        'original_corrected_probes':retained, 'normalized_probes':copy.deepcopy(probes),
        'new_model_calls':0, 'endpoint_credit_claims_added':False,
        'startup_hints_verified':False, 'controls_and_durations_from_saved_correction':True}]
