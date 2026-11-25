"""Diagnosed source-bound continuation for rejected, never-recorded plans.

The author source, frozen schema/context and complete original validators remain
unchanged. Only the model can propose replacement inputs or observation waits.
"""
from . import evaluation_model_profile as eval_models
from pathlib import Path
import argparse
import fcntl
import json
import time
from . import batch, core12, endpoint_sparse
from . import mechanic_v3_runner as runner, mechanic_v3_full_scope as scope
from . import mechanic_v3_revision as revisions
from .mechanic_v3_plan_recovery import recording_started
from .mechanic_v3_plan_transport import expand, inline_schema_prompt
from .codex import call_codex, saved_model_response, validate_schema, READ_ONLY_EVAL_INSTRUCTIONS
from .protocol import sha, dump, write_operation_report

VERSION = 'mechanic-v3-diagnosed-planner-response-correction.v1'
PARENT = 'plan_v3_outcome_frame_v1'
TASK = 'plan_v3_diagnosed_response_correction_v1'
PRIOR_TASK = 'plan_v3_outcome_validation_correction_v1'
CLAIM = 'engineering/planner_response_correction/claim.json'
SUPPORTED = {
    'core12 coverage crosses an unrelated probe interval',
    'core12 coverage window lies outside the planned action timeline',
    'invalid watcher script: addons/game_mechanic/runtime_adapter.gd',
    'invalid evidence path: project/project.godot',
    'invalid evidence path: project/scripts/main.gd',
    'invalid native probe count',
}


def supported(error):
    return error in SUPPORTED or error.startswith('endpoint must follow its actual last input and declared settling observation: ')


def parent_task(root, engine=None):
    prior=Path(root)/'model_calls'/PRIOR_TASK
    if not prior.exists():return PARENT
    # Only this known exhausted correction can continue. Accepted work is never replaced.
    from . import mechanic_v3_planner_validation_recovery as first
    claim=runner.read(Path(root)/first.CLAIM)
    if claim.get('task')!=PRIOR_TASK or claim.get('maximum_correction_invocations')!=1:
        raise ValueError('Unknown earlier planner correction')
    from .mechanic_v3_planner_producer_continuation import verified_bindings
    verified_bindings(root, claim['bindings'])
    if engine is None:
        engine=runner.read(Path(root)/'input_manifest.json')['entry']['actual_engine']
    if engine not in {'godot', 'three_js'}:
        raise ValueError('Diagnosed earlier zero-probe continuation requires Godot or Three.js')
    first.qualify_parent(Path(root),engine)
    failure=runner.read(prior/'validation_error.json')
    if failure.get('exception')!='invalid native probe count':
        raise ValueError('Different exhausted planner correction needs its own repair')
    return PRIOR_TASK


def submission_schema(schema):
    import copy
    value=copy.deepcopy(schema)
    probes=value['properties']['probes']
    probes['minItems']=max(1,probes.get('minItems',0))
    return value



def qualify_parent(root, engine):
    root = Path(root).resolve(); task=parent_task(root,engine); folder = root/'model_calls'/task
    if (recording_started(root) or (root/'sol_plan.json').exists() or
            (root/'source_qualification.json').exists()):
        raise ValueError('Planner correction requires a never-recorded rejected plan')
    if (folder/'accepted_response.json').exists():
        raise ValueError('Never replan an accepted response')
    error = runner.read(folder/'validation_error.json')
    if (error.get('phase') != 'response_plan_validation' or
            not supported(error.get('exception','')) or
            error.get('response_sha256') != sha(folder/'response.json')):
        raise ValueError('Different planner failure needs its own diagnosis')
    batch.verify_inputs(root); proto = core12.verify_attempt(root, engine)
    transport = root/'engineering/outcome_frame_v1_plan_transport'
    schema = runner.read(folder/'schema.json')
    if schema != runner.read(transport/'submitted_schema.json'):
        raise ValueError('Original submitted planner schema changed')
    raw = runner.read(folder/'response.json'); validate_schema(raw, schema)
    fixed = runner.read(transport/'fixed_context.json')
    original = runner.read(transport/'original_schema.json')
    operation = expand(raw, fixed); validate_schema(operation, original)
    try:
        batch.validate_operation_plan(root, operation, engine)
    except ValueError as failure:
        if str(failure) != error['exception']:
            raise ValueError('Original planner validator diagnosis changed') from failure
    else:
        raise ValueError('Saved response now validates; reuse without a new call')
    invocation = runner.read(folder/'invocation.json'); command = invocation.get('command', [])
    if '--model' not in command or command[command.index('--model')+1] != eval_models.model_for(root, "planner"):
        raise ValueError('Original planner model differs')
    files = [folder/n for n in ('response.json','schema.json','prompt.txt','validation_error.json','invocation.json')]
    files += [transport/n for n in ('fixed_context.json','original_schema.json','submitted_schema.json')]
    files += [root/'input_manifest.json', root/'input/pilot_rubric.json']
    if task==PRIOR_TASK:
        from . import mechanic_v3_planner_validation_recovery as first
        from .mechanic_v3_planner_producer_continuation import verified_bindings
        continuation=verified_bindings(root,runner.read(root/first.CLAIM)['bindings'])
        files += [Path(p) for p in continuation]
        files += [root/first.CLAIM,Path(first.__file__).resolve()]
        files += [p for p in (root/'model_calls'/PARENT).iterdir() if p.is_file()]
    files += [p for p in (root/'input').rglob('*') if p.is_file()]
    return proto, schema, fixed, original, error, {str(p.resolve()):sha(p) for p in files}


def correction_prompt(root, schema, error):
    folder = Path(root)/'model_calls'/PARENT
    parent=Path(root)/'model_calls'/parent_task(root)
    text = (folder/'prompt.txt').read_text()
    if not text.startswith(READ_ONLY_EVAL_INSTRUCTIONS):
        raise ValueError('Original read-only planner instructions missing')
    text = text[len(READ_ONLY_EVAL_INSTRUCTIONS):]
    text = inline_schema_prompt(text, schema, folder/'schema.json')
    return text + ('\nBOUNDED SOURCE-ONLY PLANNER VALIDATION CORRECTION. '
        'The earlier response was rejected before any gameplay execution. '
        'The schema now explicitly requires at least one real probe, matching the existing native validator. '
        'Do not return an empty probe list: source-grounded partial input/observation is sufficient. '
        'Godot watcher script locators must start res:// and name an existing author .gd file. '
        'Source evidence paths must be exactly relative to input/project, without a project/ prefix. '
        'Cite the unchanged file SHA and real physical lines. Do not invent a script or watcher property. '
        'Coverage intervals use the cumulative real probe timeline, must fit the declared probes, '
        'and must not span unrelated probes. Compute times from all preceding step durations. '
        'Reachable endpoints require stable_after_ms at least 150 and must follow actual final input '
        'plus that declared settling delay, within the original legal end-of-window interval. '
        'These are existing admission rules, not product success conditions or additional scoring requirements. '
        'Unchanged validator error: '+error['exception']+'. '
        'Keep the original frozen identity, full rubrics, source and action/runtime budgets. '
        'Return a complete schema-conforming source-grounded plan. Probes and their referenced '
        'coverage must agree. Endpoints must lie within legal coverage after the actual final '
        'physical input plus the existing stability interval. A mouse_move remains physical '
        'input even with no keys held; it cannot stand in for a passive wait. If an observation '
        'wait is needed, propose an actual supported wait through the original schema. '
        'A partial real route is sufficient. Do not invent author gameplay, observations or '
        'success; no runtime frames, verdicts or scores are supplied. The tool applies the '
        'original full schema and every original action/coverage/capture validator. '
        'The previous rejected response follows as diagnostic input, not a required route.\n'
        'PREVIOUS_REJECTED_PLAN\n'+(parent/'response.json').read_text())


def recover(workspace, identity):
    workspace = Path(workspace).resolve(); inventory = scope.load(workspace)
    rows = [r for r in inventory['entries'] if r['in_scope'] and r['entry']['id'] == identity]
    if len(rows) != 1 or revisions.revision(workspace) != 'outcome_frame_v1':
        raise ValueError('One frozen outcome-frame original required')
    row = rows[0]; engine = row['entry']['actual_engine']; root = workspace/'runs'/identity
    claim_path = root/CLAIM
    if (root/'sol_plan.json').exists():
        claim = runner.read(claim_path)
        for name,digest in claim['bindings'].items():
            if sha(Path(name)) != digest:raise ValueError('Correction lineage changed: '+name)
        receipt = runner.read(root/'engineering/planner_response_correction/completion.json')
        if receipt['operation_sha256'] != sha(root/'sol_plan.json'):
            raise ValueError('Corrected operation changed')
        batch.validate_operation_plan(root, runner.read(root/'sol_plan.json'), engine)
        return root
    proto,retained_schema,fixed,original,error,bindings = qualify_parent(root, engine)
    schema=submission_schema(retained_schema)
    contract = revisions.contract_dir(workspace,row['entry']['case_id'])
    files = [contract/'contract.json', contract/'frozen.json',Path(__file__).resolve()]
    bindings.update({str(p.resolve()):sha(p) for p in files})
    claim = dict(version=VERSION,identity=identity,parent_task=parent_task(root,engine),task=TASK,
        classification='NON_SCORING_SOURCE_BOUND_PLANNER_VALIDATION_CORRECTION',
        parent_error=error['exception'],bindings=bindings,maximum_correction_invocations=1,
        original_failure_preserved=True,original_schema_and_validators_unchanged=True,
        schema_refinement='minItems=1 mirrors the existing native probe validator',
        physical_changes_only_from_model=True,no_runtime_or_old_scores_supplied=True)
    if claim_path.exists():
        if runner.read(claim_path) != claim:raise ValueError('Existing planner correction binding changed')
    else:runner.exclusive_json(claim_path,claim)
    prompt = correction_prompt(root,schema,error)
    if len((READ_ONLY_EVAL_INSTRUCTIONS+prompt).encode()) > 1000000:
        raise ValueError('Complete correction packet exceeds unchanged transport cap')
    def validate(raw):
        validate_schema(raw,schema); validate_schema(raw,retained_schema); operation = expand(raw,fixed)
        validate_schema(operation,original)
        return batch.validate_operation_plan(root,operation,engine)
    folder = root/'model_calls'/TASK
    runner.configure_cli(Path(row['source_batch'])); runner.disk(root,'planner_response_correction',256*1024**2)
    if folder.exists():
        if not (folder/'accepted_response.json').exists():
            raise ValueError('Bounded planner correction already attempted; preserve failure')
        if (runner.read(folder/'schema.json') != schema or
                (folder/'prompt.txt').read_text() != READ_ONLY_EVAL_INSTRUCTIONS+prompt):
            raise ValueError('Accepted correction request changed')
        raw = runner.read(saved_model_response(root,TASK))
    else:
        raw = call_codex(root,name=TASK,prompt=prompt,schema=schema,model=eval_models.model_for(root, "planner"),
            timeout=600,max_attempts=1,explicit_stdin_separator=True,response_validator=validate)
    operation = validate(raw)
    dump(root/'sol_plan.json',operation); endpoint_sparse.freeze_conditions(root,proto,operation)
    write_operation_report(root,operation)
    dump(root/'engineering/planner_response_correction/completion.json',dict(
        version=VERSION,time=runner.stamp(),claim_sha256=sha(claim_path),
        response_path=str(saved_model_response(root,TASK)),response_sha256=sha(saved_model_response(root,TASK)),
        operation_sha256=sha(root/'sol_plan.json'),original_full_validation=True,new_native_recording=False))
    dump(root/'stage.json',dict(time=runner.stamp(),stage='EXECUTABLE_NATIVE_PLAN',recovery=VERSION))
    return root


def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('--workspace',type=Path,required=True)
    parser.add_argument('--identity',required=True);args=parser.parse_args(argv);workspace=args.workspace.resolve()
    with (workspace/'locks'/('outcome_frame_v1_'+args.identity+'.lock')).open('a+') as handle:
        fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:root=recover(workspace,args.identity)
        except Exception as error:
            dump(workspace/'failures'/(args.identity+'_planner_response_correction_'+str(time.time_ns())+'.json'),dict(
                time=runner.stamp(),category='HARNESS_ERROR',exception=repr(error),product_score=None))
            raise
    print(json.dumps(dict(identity=args.identity,stage='EXECUTABLE_NATIVE_PLAN',root=str(root))),flush=True)
    return 0


if __name__ == '__main__':raise SystemExit(main())
