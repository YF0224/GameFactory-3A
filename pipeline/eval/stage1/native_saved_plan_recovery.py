"""Source-bound continuation of a saved native plan after proven harness repairs.

Old errors/calls remain immutable. No source, plan identity, scoring or evidence
rule is changed; one optional leaf-only model correction is separately retained.
"""
import json
import re
from pathlib import Path
import shutil
import time

from . import batch, core12, codex, static_existence, plan_patches
from .protocol import dump, sha

VERSION = 'whitebox-native-saved-plan-handoff.v1'
RECEIPT = 'native_saved_plan_handoff.json'
CLAIM = 'native_saved_plan_handoff_claim.json'
PATCH_NAME = 'native_saved_plan_patch_v1'
REPLAY = 'native_saved_plan_replay.json'
REPLAY_PATH = 'model_calls/native_saved_plan_replay_v1/candidate.json'



def _timeout_patch_qualification(root, source):
    """Bind a failed *correction*, never promote it to a completed response."""
    root, source = Path(root), Path(source)
    first = root/'model_calls/plan'; retry = root/'model_calls/plan_002'
    folders = {p.name for p in (root/'model_calls').iterdir()
               if p.is_dir() and re.fullmatch(r'plan(?:_\d+)?', p.name)}
    if folders != {'plan', 'plan_002'} or any((retry/n).exists() for n in
            ('response.json','accepted_response.json','validation_error.json')):
        raise ValueError('Timeout correction must retain exactly two calls and no partial/accepted response')
    original = batch.read(first/'invocation.json')
    failure = batch.read(first/'validation_error.json')
    interrupted = batch.read(retry/'invocation.json')
    budget = batch.read(retry/'budget.json')
    allocated = budget.get('allocated_seconds', 0)
    elapsed = interrupted.get('seconds', 0)
    if (original.get('exit_code') != 0 or original.get('attempt') != 1
            or original.get('model_requested') != static_existence.MODEL
            or interrupted.get('model_requested') != static_existence.MODEL
            or interrupted.get('status') != 'TIMEOUT'
            or not 0 < allocated <= 600 or not 0 < elapsed <= allocated+2
            or budget.get('phase') != 'plan' or budget.get('attempt') != 2
            or budget.get('base_timeout_seconds') != 600
            or budget.get('effective_timeout_seconds') != 600
            or not 598 <= original.get('seconds', -600)+allocated <= 602):
        raise ValueError('Only the original bounded shared-deadline TIMEOUT correction qualifies')
    command = original.get('command', [])
    if '--model' not in command or command[command.index('--model')+1:][:1] != [static_existence.MODEL]:
        raise ValueError('First full response did not request the frozen model')
    if (failure.get('phase') != 'response_plan_validation' or failure.get('attempt') != 1
            or failure.get('response_sha256') != sha(first/'response.json')
            or (first/'accepted_response.json').exists()
            or batch.read(retry/'schema.json') != plan_patches.PATCH_SCHEMA):
        raise ValueError('Failed correction lost its original strict schema/validation binding')
    feedback = batch.read(retry/'repair_feedback.json')
    if (feedback.get('version') != plan_patches.VERSION
            or feedback.get('base_sha256') != sha(first/'response.json')
            or feedback.get('base_path') != str(source/'model_calls/plan/response.json')
            or feedback.get('original_schema') != str(source/'model_calls/plan/schema.json')):
        raise ValueError('Timeout correction feedback lost original response binding')
    if '"type":"turn.started"' not in (retry/'events.jsonl').read_text().replace(' ', ''):
        raise ValueError('Original correction dispatch has no real model turn receipt')
    paths = [p for folder in (first,retry) for p in folder.rglob('*') if p.is_file()]
    return {'version':'whitebox-native-timeout-patch-source.v1',
            'mode':'first_complete_response_only', 'failed_patch_is_accepted':False,
            'original_call_counters_preserved':True, 'model_calls_added':0,
            'bindings':{str(p.relative_to(root)):sha(p) for p in paths}}


def _saved_candidate(root, source=None):
    """Reconstruct only the first completed anchored correction, never accept it.

    retry_of/feedback keep their original source paths after the immutable copy.
    The resulting candidate still has to pass every normal operation validator.
    """
    root = Path(root).resolve()
    source = Path(source).resolve() if source is not None else root
    raw = codex.saved_model_response(root, 'plan')
    original = root/'model_calls/plan/response.json'
    patch_path = root/'model_calls/plan_002/response.json'
    if raw != original or not patch_path.parent.exists():
        return raw, codex.load_plan_json(raw), None
    folders = {p.name for p in (root/'model_calls').iterdir()
               if p.is_dir() and re.fullmatch(r'plan(?:_\d+)?', p.name)}
    if folders != {'plan', 'plan_002'}:
        raise ValueError('Saved native replay requires exactly the original two plan calls')
    if not patch_path.exists():
        proof = _timeout_patch_qualification(root, source)
        return raw, codex.load_plan_json(raw), proof
    calls = [batch.read(p.parent/'invocation.json') for p in (original, patch_path)]
    if (any(c.get('exit_code') != 0 or c.get('model_requested') != static_existence.MODEL
            for c in calls) or calls[0].get('attempt') != 1 or calls[1].get('attempt') != 2
            or calls[1].get('retry_of') != str(source/'model_calls/plan')):
        raise ValueError('Saved native replay requires two completed frozen-model calls and original retry identity')
    for path, call in zip((original, patch_path), calls):
        command = call.get('command', [])
        if '--model' not in command or command[command.index('--model')+1:][:1] != [static_existence.MODEL]:
            raise ValueError('Saved native replay command model differs from frozen model')
        failure = batch.read(path.parent/'validation_error.json')
        if (failure.get('phase') != 'response_plan_validation'
                or failure.get('response_sha256') != sha(path)
                or failure.get('attempt') != call['attempt']):
            raise ValueError('Saved native replay failure is not bound to completed response')
        if (path.parent/'accepted_response.json').exists():
            raise ValueError('Saved native replay cannot replace an accepted pointer')
    if batch.read(patch_path.parent/'schema.json') != plan_patches.PATCH_SCHEMA:
        raise ValueError('Saved native replay requires the unchanged leaf patch schema')
    feedback = batch.read(patch_path.parent/'repair_feedback.json')
    if (feedback.get('version') != plan_patches.VERSION or feedback.get('base_sha256') != sha(original)
            or feedback.get('base_path') != str(source/'model_calls/plan/response.json')
            or feedback.get('original_schema') != str(source/'model_calls/plan/schema.json')):
        raise ValueError('Saved native replay feedback lost original source binding')
    candidate = plan_patches.apply(original.read_bytes(), plan_patches.loads(patch_path.read_bytes()))
    codex.validate_schema(candidate, batch.read(original.parent/'schema.json'))
    paths = [original, patch_path]
    for folder in (original.parent, patch_path.parent):
        paths += [folder/name for name in ('invocation.json', 'schema.json', 'validation_error.json')]
    paths.append(patch_path.parent/'repair_feedback.json')
    proof = {'version':'whitebox-native-saved-plan-replay.v1', 'model_calls_added':0,
             'candidate_is_accepted':False, 'source_attempt':str(source),
             'bindings':{str(p.relative_to(root)):sha(p) for p in paths}}
    return raw, candidate, proof


def _parent_bindings(source):
    from . import native_service_recovery
    if (source/native_service_recovery.RECEIPT).is_file():
        bindings = native_service_recovery.verify(source)
        parent = Path(batch.read(source/native_service_recovery.RECEIPT)['source_attempt'])
        bindings[str(parent/native_service_recovery.CLAIM)] = sha(parent/native_service_recovery.CLAIM)
        return bindings
    return {}


def _candidate_response(root, source, replay_enabled):
    # Legacy handoffs may have an exhausted TIMEOUT retry and deliberately
    # resume their first complete response. Never retroactively qualify that
    # failed retry. A dedicated replay receipt from the first rollout is also
    # an explicit opt-in, preserving its already-frozen handoff receipt.
    if type(replay_enabled) is not bool:
        raise ValueError('Invalid saved native replay authorization')
    if not replay_enabled:
        if (root/REPLAY).exists():
            raise ValueError('Unexpected saved native replay receipt')
        return codex.saved_model_response(root, 'plan')
    raw, candidate, proof = _saved_candidate(root, source)
    if proof is None:
        if (root/REPLAY).exists():
            raise ValueError('Unexpected saved native replay receipt')
        return raw
    path = root/REPLAY_PATH
    receipt = dict(proof, response=REPLAY_PATH, sha256=sha(path))
    if batch.read(root/REPLAY) != receipt or batch.read(path) != candidate:
        raise ValueError('Saved native replay receipt or deterministic candidate changed')
    return path


def verify(root):
    root = Path(root).resolve()
    value = batch.read(root/RECEIPT)
    source = Path(value['source_attempt']).resolve()
    if (value.get('version') != VERSION or source == root
            or source.parent != root.parent or value.get('target_attempt') != str(root)
            or value.get('source_calls_and_errors_preserved') is not True
            or value.get('maximum_correction_calls') != 1
            or batch.read(source/CLAIM).get('target_attempt') != str(root)):
        raise ValueError('Invalid native saved-plan handoff')
    if sha(source/CLAIM) != value['claim_sha256']:
        raise ValueError('Saved-plan handoff claim changed')
    for name, digest in value['bindings'].items():
        if sha(source/name) != digest:
            raise ValueError('Preserved native source changed: '+name)
    for name, digest in value['copied_bindings'].items():
        if sha(root/name) != digest:
            raise ValueError('Copied native stage changed: '+name)
    repair = Path(value['engineering_repair']['path'])
    if sha(repair) != value['engineering_repair']['sha256']:
        raise ValueError('Native engineering repair proof changed')
    engine = batch.plan_engine(root)
    if engine not in {'godot','three_js'}:
        raise ValueError('Saved native handoff supports Godot/Three.js only')
    batch.verify_inputs(source)
    batch.verify_inputs(root)
    protocol = core12.verify_attempt(root, engine)
    if protocol != core12.verify_attempt(source, engine):
        raise ValueError('Saved native handoff changed frozen protocol')
    if static_existence.load(root, protocol) != static_existence.load(source, protocol):
        raise ValueError('Saved native handoff changed accepted static')
    if value.get('parent_stage_bindings', {}) != _parent_bindings(source):
        raise ValueError('Saved native handoff parent recovery lineage changed')
    if 'preserved_timeout_patch' in value:
        if value['preserved_timeout_patch'] != _timeout_patch_qualification(root, source):
            raise ValueError('Preserved failed correction qualification changed')
    _candidate_response(root, source, value.get('saved_patch_replay', (root/REPLAY).is_file()))
    return value


def prepare(source, *, engineering_repair):
    source = Path(source).resolve()
    engineering_repair = Path(engineering_repair).resolve()
    repair = batch.read(engineering_repair)
    if (repair.get('non_scoring_semantics') is not True or not repair.get('root_cause')
            or not repair.get('regressions') or not repair.get('changed_files')):
        raise ValueError('Native handoff requires substantive repair and passing regression proof')
    for path, spec in repair['changed_files'].items():
        if sha(Path(path)) != spec['after_sha256'] or spec['before_sha256'] == spec['after_sha256']:
            raise ValueError('Native repair code SHA does not match proven change')
    for path, digest in repair['regressions'].items():
        if sha(Path(path)) != digest:
            raise ValueError('Native repair regression binding changed')
    if any((source/n).exists() for n in ('scores.json','runtime/frame_index.jsonl',CLAIM)):
        raise ValueError('Existing scored/recorded/claimed attempt protected')
    if not (source/'harness_error.json').is_file():
        raise ValueError('Native saved plan needs a preserved real harness failure')
    engine = batch.plan_engine(source)
    if engine not in {'godot','three_js'}:
        raise ValueError('Native handoff supports only original Godot/Three.js')
    batch.verify_inputs(source)
    proto = core12.verify_attempt(source, engine)
    static_existence.load(source, proto)
    # A complete successful model response is necessary; no interrupted output
    # is promoted to exit=0 or accepted here.
    raw, candidate, replay = _saved_candidate(source)
    timeout_patch = replay if replay is not None and replay.get('version') == 'whitebox-native-timeout-patch-source.v1' else None
    if timeout_patch is not None:
        replay = None
    parent_bindings = _parent_bindings(source)
    if not candidate.get('planning_identity'):
        raise ValueError('Native saved plan is not an original full plan response')
    root = source.parent/(source.name+'__native_saved_plan_handoff_v1')
    if root.exists():
        raise ValueError('Native recovery already exists; inspect exact saved stage')
    claim = {'version':VERSION,'source_attempt':str(source),'target_attempt':str(root),
             'engineering_repair_sha256':sha(engineering_repair),'created_unix':time.time()}
    with (source/CLAIM).open('x') as stream:
        json.dump(claim, stream, indent=2)
    root.mkdir()
    names = ['input','model_calls','input_manifest.json','static_existence.json']
    names += [n for n in ('static_format_recovery.json','cli_runtime_recovery',
                          'unsupported_input_policy.json') if (source/n).exists()]
    copied = {}
    for name in names:
        p = source/name
        if p.is_dir():
            shutil.copytree(p, root/name)
            paths = [x for x in p.rglob('*') if x.is_file()]
        else:
            shutil.copy2(p, root/name)
            paths = [p]
        copied.update({str(x.relative_to(source)):sha(x) for x in paths})
    bound = dict(copied)
    bound['harness_error.json'] = sha(source/'harness_error.json')
    bound['attempt_manifest.json'] = sha(source/'attempt_manifest.json')
    for name in ('status.json', 'execution.validation.json'):
        if (source/name).is_file():
            bound[name] = sha(source/name)
    if replay is not None:
        dump(root/REPLAY_PATH, candidate)
        dump(root/REPLAY, dict(replay, response=REPLAY_PATH, sha256=sha(root/REPLAY_PATH)))
    dump(root/RECEIPT, {'version':VERSION,'source_attempt':str(source),'target_attempt':str(root),
        'source_calls_and_errors_preserved':True,'maximum_correction_calls':1,
        'new_static_calls':0,'bindings':bound,'copied_bindings':copied,
        'parent_stage_bindings':parent_bindings,'saved_patch_replay':replay is not None,
        'claim_sha256':sha(source/CLAIM),
        'engineering_repair':{'path':str(engineering_repair),'sha256':sha(engineering_repair)}})
    if timeout_patch is not None:
        receipt = batch.read(root/RECEIPT)
        receipt['preserved_timeout_patch'] = timeout_patch
        dump(root/RECEIPT, receipt)
    attempt = batch.read(source/'attempt_manifest.json')
    attempt.update(attempt_id=root.name, previous_attempt=str(source),
                   phase='native_saved_plan_handoff', created_unix=time.time())
    dump(root/'attempt_manifest.json', attempt)
    shutil.copytree(root/'input/project', root/'runtime/project', ignore=batch.IGNORE)
    if batch.hashes(root/'runtime/project') != batch.read(root/'input_manifest.json')['snapshot_hashes']:
        raise ValueError('Native runtime snapshot differs from frozen source')
    verify(root)
    return root


def correct(root, *, timeout=600):
    root = Path(root).resolve()
    handoff = verify(root)
    if (root/'sol_plan.json').is_file():
        return batch.validate_operation_plan(root, batch.read(root/'sol_plan.json'))
    raw = _candidate_response(root, Path(handoff['source_attempt']),
                              handoff.get('saved_patch_replay', (root/REPLAY).is_file()))
    try:
        result = batch.validate_operation_plan(root, codex.load_plan_json(raw))
    except ValueError as error:
        folder = root/'model_calls'/PATCH_NAME
        if folder.exists():
            raise ValueError('Native correction already attempted; preserve failure and diagnose') from error
        from .native_timeline_diagnostics import enrich
        enrich(error, batch.read(root/'input/pilot_rubric.json'), codex.load_plan_json(raw))
        feedback, text = plan_patches.feedback(raw, error)
        # Separate recovery authorization does not reset the two exhausted old
        # calls or change the original schema/identity. Exactly one correction.
        text += ('\nThis is a source-bound engineering continuation after an independently tested harness repair. '
                 'One correction is authorized, not a new plan. Preserve ALL planning_identity fields exactly. '
                 'Check every directly affected endpoint last_action_id against the unchanged probes/timeline. '
                 'Do not remove actions, shorten evidence, or change frozen rubric/conditions. '
                 'The original closed schema is '+str(root/'model_calls/plan/schema.json')+'.')
        dump(root/'native_saved_plan_correction_diagnostic.json', feedback)
        def validate(patch):
            return batch.validate_operation_plan(root, plan_patches.apply(raw.read_bytes(), patch))
        patch = codex.call_codex(root, name=PATCH_NAME, prompt=text, schema=plan_patches.PATCH_SCHEMA,
            model=static_existence.MODEL, timeout=timeout, max_attempts=1, response_validator=validate)
        derived = plan_patches.apply(raw.read_bytes(), patch)
        path = plan_patches.save_application(folder, raw, patch, derived)
        # Do not rewrite the copied original acceptance/call; a distinct
        # handoff receipt binds the patch, application and resulting plan.
        dump(root/'native_saved_plan_correction.json', {'version':VERSION,
            'response':str(path.relative_to(root)),'sha256':sha(path),
            'patch_receipt_sha256':sha(folder/'patch_application.json'),
            'original_response':str(raw.relative_to(root)),'original_sha256':sha(raw)})
        result = validate(patch)
    dump(root/'sol_plan.json', result)
    from .protocol import write_operation_report
    write_operation_report(root, result)
    from . import endpoint_sparse
    endpoint_sparse.freeze_conditions(root, batch.read(root/'input/pilot_rubric.json'), result)
    batch.status(root, 'PLANNED', source_bound_handoff=True)
    return result


def audit_binding(root):
    root = Path(root).resolve()
    if not (root/RECEIPT).is_file():
        return {}
    value = verify(root)
    result = {str(root/RECEIPT):sha(root/RECEIPT)}
    source = Path(value['source_attempt'])
    result.update({str(source/name):digest for name,digest in value['bindings'].items()})
    result[str(source/CLAIM)] = value['claim_sha256']
    result.update(value.get('parent_stage_bindings', {}))
    if (root/REPLAY).is_file():
        result.update({str(root/p):sha(root/p) for p in (REPLAY, REPLAY_PATH)})
    path = root/'native_saved_plan_correction.json'
    if path.is_file():
        correction = batch.read(path)
        derived = root/correction['response']
        if not derived.resolve().is_relative_to(root/'model_calls'):
            raise ValueError('Native correction path escapes model calls')
        if (sha(derived) != correction['sha256'] or
                sha(root/correction['original_response']) != correction['original_sha256']):
            raise ValueError('Native correction source binding changed')
        plan_patches.verify_application(derived, correction)
        accepted = batch.validate_operation_plan(root, batch.read(derived), record_validation=False)
        if accepted != batch.read(root/'sol_plan.json'):
            raise ValueError('Native correction differs from executed plan')
        for p in (path, derived, derived.parent/'response.json', derived.parent/'patch_application.json',
                  derived.parent/'accepted_response.json', derived.parent/'invocation.json'):
            result[str(p)] = sha(p)
    return result
