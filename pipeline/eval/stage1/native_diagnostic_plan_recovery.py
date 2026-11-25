"""One source-bound diagnostic continuation after an incomplete first-error feedback.

The exhausted handoff remains intact. Only endpoint timing/last-input links and
Gameness mapping leaves can change; all routes, windows, sources and rubrics stay
exact. Every original validator still runs before acceptance and during audit.
"""
import json
from pathlib import Path
import time
from . import batch, codex, core12, native_saved_plan_recovery as saved, plan_patches, static_existence
from . import native_plan_diagnostics as diagnostics
from .protocol import dump, sha, write_operation_report

VERSION = 'whitebox-native-comprehensive-diagnostic-continuation.v1'
RECEIPT = 'native_diagnostic_plan_recovery.json'
CLAIM = 'native_diagnostic_plan_recovery_claim.json'
NAME = 'native_comprehensive_diagnostic_patch_v1'


def _predecessor(root):
    saved.verify(root)
    base = codex.saved_model_response(root, 'plan')
    folder = root/'model_calls'/saved.PATCH_NAME
    response = codex.saved_model_response(root, saved.PATCH_NAME)
    invocation = batch.read(folder/'invocation.json')
    error = batch.read(folder/'validation_error.json')
    if (invocation.get('exit_code') != 0 or invocation.get('model_requested') != static_existence.MODEL
            or error.get('response_sha256') != sha(response)
            or (folder/'accepted_response.json').exists()):
        raise ValueError('Continuation needs complete, unsuccessful prior correction with its actual validation error')
    patch = batch.read(response)
    codex.validate_schema(patch, batch.read(folder/'schema.json'))
    candidate = plan_patches.apply(base.read_bytes(), patch)
    codex.validate_schema(candidate, batch.read(root/'model_calls/plan/schema.json'))
    return base, folder, response, candidate


def register(root, *, engineering_repair):
    root, repair_path = Path(root).resolve(), Path(engineering_repair).resolve()
    if any((root/n).exists() for n in (CLAIM, RECEIPT, 'sol_plan.json','scores.json','harness_error.json',
                                      'runtime/frame_index.jsonl','native_capture_admission.json')):
        raise ValueError('Recorded, scored, marked or already claimed attempt cannot register diagnostic continuation')
    repair = batch.read(repair_path)
    if (repair.get('non_scoring_semantics') is not True or not repair.get('root_cause')
            or repair.get('diagnostic_version') != diagnostics.VERSION
            or not repair.get('regressions') or not repair.get('changed_files')):
        raise ValueError('Continuation requires tested, substantive comprehensive-diagnostic repair')
    for name, spec in repair['changed_files'].items():
        if sha(Path(name)) != spec['after_sha256'] or spec['before_sha256'] == spec['after_sha256']:
            raise ValueError('Diagnostic repair source SHA mismatch')
    for name, digest in repair['regressions'].items():
        if sha(Path(name)) != digest:raise ValueError('Diagnostic repair regression changed')
    base, folder, response, candidate = _predecessor(root)
    try:
        batch.validate_operation_plan(root, candidate, record_validation=False)
    except ValueError as error:
        diagnostics.enrich(error, batch.read(root/'input/pilot_rubric.json'), candidate)
        diagnostic = {'version':diagnostics.VERSION, 'original_validation_error':str(error),
                      'diagnostics':error.diagnostics}
    else:
        raise ValueError('Saved candidate already validates; no new correction is qualified')
    if not any(row.get('detected_issue') for row in diagnostic['diagnostics']):
        raise ValueError('No newly actionable comprehensive timing/link diagnosis')
    # Claim is permanent even if any later preparation/call fails.
    claim = {'version':VERSION, 'root':str(root), 'maximum_calls':1,
             'previous_correction_limit_unchanged':True, 'created_unix':time.time(),
             'engineering_repair':str(repair_path), 'engineering_repair_sha256':sha(repair_path)}
    with (root/CLAIM).open('x') as stream:json.dump(claim,stream,indent=2)
    predecessor = root/'model_calls/native_comprehensive_diagnostic_predecessor_v1'
    predecessor.mkdir()
    dump(predecessor/'candidate.json',candidate)
    dump(predecessor/'diagnostics.json',diagnostic)
    preserved = [p for p in folder.rglob('*') if p.is_file()]
    preserved += [p for p in (root/'model_calls/plan').rglob('*') if p.is_file()]
    preserved += [base, root/saved.RECEIPT, root/CLAIM,
                  predecessor/'candidate.json', predecessor/'diagnostics.json']
    bound = {str(p.relative_to(root)):sha(p) for p in preserved}
    dump(root/RECEIPT, {'version':VERSION, 'root':str(root), 'maximum_calls':1,
         'new_root_cause':'First-error feedback concealed other endpoint bounds, last-input links and unmapped visual windows.',
         'routes_windows_sources_rubrics_unchanged':True, 'previous_correction_limit_unchanged':True,
         'bindings':bound, 'base_path':str((predecessor/'candidate.json').relative_to(root)),
         'engineering_repair':{'path':str(repair_path), 'sha256':sha(repair_path)}})
    verify(root)
    return batch.read(root/RECEIPT)


def verify(root):
    root = Path(root).resolve()
    value = batch.read(root/RECEIPT)
    if (value.get('version') != VERSION or value.get('root') != str(root)
            or value.get('maximum_calls') != 1 or value.get('routes_windows_sources_rubrics_unchanged') is not True
            or value.get('previous_correction_limit_unchanged') is not True):
        raise ValueError('Invalid diagnostic continuation receipt')
    claim = batch.read(root/CLAIM)
    if claim.get('root') != str(root) or claim.get('maximum_calls') != 1:
        raise ValueError('Invalid diagnostic continuation claim')
    for name, digest in value['bindings'].items():
        path = (root/name).resolve()
        if not path.is_relative_to(root) or sha(path) != digest:
            raise ValueError('Diagnostic continuation predecessor changed: '+name)
    proof = value['engineering_repair']
    if sha(Path(proof['path'])) != proof['sha256'] or claim['engineering_repair_sha256'] != proof['sha256']:
        raise ValueError('Diagnostic continuation proof changed')
    _, _, _, candidate = _predecessor(root)
    base = (root/value['base_path']).resolve()
    if not base.is_relative_to(root/'model_calls') or batch.read(base) != candidate:
        raise ValueError('Diagnostic predecessor differs from exact saved-patch application')
    batch.verify_inputs(root)
    core12.verify_attempt(root,batch.plan_engine(root))
    return value


def _apply(base, patch):
    # Permit link/timing/mapping corrections only; no replacement route, window,
    # source citation, endpoint reachability or scoring/rubric condition.
    for edit in patch['edits']:
        tokens = plan_patches.tokens(edit['path'])
        endpoint = (len(tokens)==4 and tokens[:2]==['capture_plan','endpoints']
                    and tokens[3] in {'at_ms','last_action_id','stable_after_ms'})
        mapping = (len(tokens)==4 and tokens[:2]==['capture_plan','gameness']
                   and tokens[3] in {'window_ids','reason'})
        if not (endpoint or mapping) or edit['op'] != 'replace':
            raise ValueError('Diagnostic continuation is limited to existing timing/link/mapping leaves')
    return plan_patches.apply(base.read_bytes(),patch)


def correct(root, *, timeout=600):
    root = Path(root).resolve()
    value = verify(root)
    base = root/value['base_path']
    folder = root/'model_calls'/NAME
    def validate(patch):
        return batch.validate_operation_plan(root,_apply(base,patch))
    if (root/'sol_plan.json').exists():
        audit_binding(root)
        return batch.validate_operation_plan(root,batch.read(root/'sol_plan.json'))
    if folder.exists():
        if not (folder/'accepted_response.json').is_file():
            raise ValueError('Diagnostic correction was already dispatched; preserve failure, no retry')
        patch = batch.read(codex.saved_model_response(root,NAME))
        result = validate(patch)
    else:
        diagnostic = batch.read(base.parent/'diagnostics.json')
        error = ValueError(diagnostic['original_validation_error'])
        error.diagnostics = diagnostic['diagnostics']
        feedback, text = plan_patches.feedback(base,error)
        dump(root/'native_comprehensive_feedback.json',feedback)
        text += ('\nA separately tested comprehensive-diagnostic engineering repair qualifies exactly ONE continuation. '
            'The previous call counts and failures remain immutable. This new bounded call is not a new route. '
            'ONLY replace existing capture_plan.endpoints.<id>.at_ms/last_action_id/stable_after_ms or '
            'capture_plan.gameness.<id>.window_ids/reason leaves. Keep all probes, input steps, durations, coverage, '
            'windows, source references, reachability, legal routes, rubric and planning_identity EXACTLY unchanged. '
            'Review ALL endpoint diagnostics and ALL unmapped windows together; original strict validation is final. '
            'Never claim native results or weaken original scoring/evidence obligations. Original closed schema: '
            +str(root/'model_calls/plan/schema.json'))
        patch = codex.call_codex(root,name=NAME,prompt=text,schema=plan_patches.PATCH_SCHEMA,
            model=static_existence.MODEL,timeout=timeout,max_attempts=1,response_validator=validate)
        result = validate(patch)
    derived = _apply(base,patch)
    path = plan_patches.save_application(folder,base,patch,derived)
    dump(root/'native_comprehensive_plan_correction.json', {'version':VERSION,
        'response':str(path.relative_to(root)), 'sha256':sha(path),
        'patch_receipt_sha256':sha(folder/'patch_application.json')})
    dump(root/'sol_plan.json',result)
    write_operation_report(root,result)
    from . import endpoint_sparse
    endpoint_sparse.freeze_conditions(root,batch.read(root/'input/pilot_rubric.json'),result)
    batch.status(root,'PLANNED',comprehensive_diagnostic_continuation=True)
    return result


def audit_binding(root):
    root = Path(root).resolve()
    if not (root/RECEIPT).exists():return {}
    value = verify(root)
    bindings = {str(root/name):digest for name,digest in value['bindings'].items()}
    bindings[str(root/RECEIPT)] = sha(root/RECEIPT)
    correction_path = root/'native_comprehensive_plan_correction.json'
    if not correction_path.exists():
        raise ValueError('Diagnostic continuation has no accepted correction')
    correction = batch.read(correction_path)
    path = (root/correction['response']).resolve()
    if (correction.get('version') != VERSION or not path.is_relative_to(root/'model_calls'/NAME)
            or sha(path) != correction['sha256']):
        raise ValueError('Diagnostic accepted plan source changed')
    plan_patches.verify_application(path,correction)
    base = root/value['base_path']
    response = codex.saved_model_response(root,NAME)
    invocation = batch.read(path.parent/'invocation.json')
    if (response != path.parent/'response.json' or invocation.get('exit_code') != 0
            or invocation.get('model_requested') != static_existence.MODEL):
        raise ValueError('Diagnostic correction lacks its actual successful bounded model response')
    patch = batch.read(response)
    codex.validate_schema(patch,plan_patches.PATCH_SCHEMA)
    candidate = _apply(base,patch)
    accepted = batch.validate_operation_plan(root,candidate,record_validation=False)
    if batch.read(path) != candidate or batch.read(root/'sol_plan.json') != accepted:
        raise ValueError('Diagnostic correction differs from actual accepted operation plan')
    for p in (path, correction_path, path.parent/'response.json',path.parent/'patch_application.json',
              path.parent/'accepted_response.json',path.parent/'invocation.json'):
        bindings[str(p)] = sha(p)
    return bindings
