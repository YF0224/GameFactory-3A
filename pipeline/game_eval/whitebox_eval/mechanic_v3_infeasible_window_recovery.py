"""One diagnosed planner continuation after an impossible observer interval.

No action, window or coverage is locally edited. Original attempts and bounded
claims remain immutable. A new independent source-only planner proposes every
physical change; the complete original validator remains authoritative.
"""
from pathlib import Path
from . import batch, core12, endpoint_sparse
from . import mechanic_v3_runner as runner, mechanic_v3_revision as revision
from . import mechanic_v3_planner_response_recovery as parent
from . import mechanic_v3_plan_recovery as schedule
from . import evaluation_model_profile as models
from .mechanic_v3_plan_transport import expand, inline_schema_prompt
from .codex import call_codex, saved_model_response, validate_schema, READ_ONLY_EVAL_INSTRUCTIONS
from .protocol import sha, dump, write_operation_report

VERSION = 'mechanic-v3-infeasible-observer-window-continuation.v1'
IDENTITY = 'GLM__G006_polar_radar_defense'
TASK = 'plan_v3_infeasible_window_correction_v1'
CLAIM = 'engineering/planner_infeasible_window/claim.json'
DONE = 'engineering/planner_infeasible_window/completion.json'
BEFORE = '000b895946e91a948df46791b0e4e4742a7f019992e88551561b5d1dc0ce69c8'
AFTER = 'f4ca4f54eff1f8570433a1720d2be7ab7c2b48f2ad60b8b0630b344ca054670b'
PREFIX = 'Original action/coverage interval has no legal stable endpoint: '


def retained_claim(root, archived_producer):
    root = Path(root); old = root/parent.CLAIM
    value = runner.read(old)
    if (value.get('version') != parent.VERSION or value.get('identity') != IDENTITY
            or value.get('task') != parent.TASK or value.get('parent_task') != parent.PARENT
            or value.get('maximum_correction_invocations') != 1):
        raise ValueError('Different bounded planner lineage')
    producer = Path(parent.__file__).resolve(); archived_producer = Path(archived_producer).resolve()
    drift = {p:d for p,d in value['bindings'].items() if sha(Path(p)) != d}
    if (drift != {str(producer): BEFORE} or sha(producer) != AFTER
            or sha(archived_producer) != BEFORE):
        raise ValueError('Planner lineage changed beyond diagnosed exact producer delta')
    if models.profile_for(root) is not None or models.model_for(root,'planner') != models.DEFAULT:
        raise ValueError('This continuation requires the unchanged default Sol')
    # Exact archived/current code is retained. The added prior-task branch is
    # unreachable here: this lineage has no PRIOR_TASK. Actual model is Sol.
    if (root/'model_calls'/parent.PRIOR_TASK).exists():
        raise ValueError('Different earlier correction needs its own repair')
    return dict(value['bindings']), {str(old):sha(old), str(producer):sha(producer),
        str(archived_producer):sha(archived_producer)}


def qualify(root, archived_producer):
    root=Path(root).resolve()
    if root.name != IDENTITY or schedule.recording_started(root) or (root/'source_qualification.json').exists():
        raise ValueError('Only the diagnosed never-recorded original may continue')
    if (root/'sol_plan.json').exists():
        raise ValueError('Reuse existing executable plan')
    proto, retained, fixed, original, _, bindings = parent.qualify_parent(root,'godot')
    historical, producer_proof = retained_claim(root, archived_producer)
    folder=root/'model_calls'/parent.TASK
    if (folder/'accepted_response.json').exists():
        raise ValueError('Accepted correction cannot be replaced')
    err=runner.read(folder/'validation_error.json')
    if (err.get('phase') != 'response_plan_validation' or
            not err.get('exception','').startswith('endpoint must follow its actual last input and declared settling observation: ')
            or err.get('response_sha256') != sha(folder/'response.json')):
        raise ValueError('Different planner rejection requires a separate diagnosis')
    schema=runner.read(folder/'schema.json')
    if schema != parent.submission_schema(retained):raise ValueError('Original bounded schema changed')
    inv=runner.read(folder/'invocation.json');command=inv.get('command',[])
    if (inv.get('exit_code') != 0 or inv.get('attempt') != 1 or '--model' not in command
            or command[command.index('--model')+1] != models.DEFAULT):
        raise ValueError('Actual original planner invocation is not proven')
    raw=runner.read(folder/'response.json');validate_schema(raw,schema);validate_schema(raw,retained)
    op=expand(raw,fixed);validate_schema(op,original)
    try:batch.validate_operation_plan(root,op,'godot')
    except ValueError as error:
        if str(error)!=err['exception']:raise ValueError('Original validator diagnosis changed') from error
    else:raise ValueError('Saved planner already validates; reuse it')
    try:schedule.normalize_schedule(proto,op)
    except ValueError as error:
        diagnostic=str(error)
        if not diagnostic.startswith(PREFIX):raise ValueError('Different observer failure') from error
    else:raise ValueError('Observer metadata repair is sufficient; no model call allowed')
    files=[p for p in folder.iterdir() if p.is_file()]
    files += [Path(__file__).resolve(),Path(schedule.__file__).resolve()]
    bindings.update({p:d for p,d in historical.items() if p!=str(Path(parent.__file__).resolve())})
    bindings.update(producer_proof);bindings.update({str(p.resolve()):sha(p) for p in files})
    return proto,schema,retained,fixed,original,err,diagnostic,bindings


def prompt(root, schema, error, diagnosis):
    folder=Path(root)/'model_calls'/parent.PARENT
    text=(folder/'prompt.txt').read_text()
    if not text.startswith(READ_ONLY_EVAL_INSTRUCTIONS):raise ValueError('Missing read-only source context')
    text=inline_schema_prompt(text[len(READ_ONLY_EVAL_INSTRUCTIONS):],schema,folder/'schema.json')
    return text + ('\nDIAGNOSED INFEASIBLE OBSERVER WINDOW; ONE SOURCE-ONLY CONTINUATION. '
        'The previous bounded correction is preserved and cannot execute. Local metadata '
        'normalization reproduced an empty legal endpoint interval. This new invocation '
        'must independently propose a complete executable plan from the unchanged author '
        'source, frozen criteria, schema and original budgets. Do not merely change the '
        'endpoint label: the physical actions and coverage intervals must admit an actual '
        'settling observation. Every input/mouse_move counts as physical input; waits must '
        'use an existing wait operation. Compute cumulative time from every step duration. '
        'The endpoint must be after the actual last relevant input plus its declared '
        'stable_after_ms (at least 150), and within [coverage_end_ms-500,coverage_end_ms-150]. '
        'Allow enough passive observation before the coverage ends. A smaller partial '
        'source-grounded route is sufficient; coverage of all criteria or a successful '
        'outcome is unnecessary. Preserve all original criterion identities; honestly '
        'mark unsupported routes unreachable using the unchanged schema. Do not invent '
        'watchers, actions, gameplay, source files or results. Source paths are relative '
        'to input/project with unchanged SHAs and actual physical lines. No runtime '
        'frames, product scores or prior verdicts are supplied. The full original '
        'validator applies; no local action/window edit and no score rule change.\n'
        'REPRODUCED_VALIDATOR_ERROR '+error['exception']+'\n'
        'REPRODUCED_METADATA_INFEASIBILITY '+diagnosis+'\n'
        'PREVIOUS_REJECTED_RESPONSE_AS_DIAGNOSTIC_ONLY\n'
        +(Path(root)/'model_calls'/parent.TASK/'response.json').read_text())


def verify(root):
    root=Path(root);claim=runner.read(root/CLAIM)
    if claim.get('version') != VERSION or claim.get('identity')!=IDENTITY or claim.get('task')!=TASK:
        raise ValueError('Different infeasible-window claim')
    for p,d in claim['bindings'].items():
        if sha(Path(p))!=d:raise ValueError('Infeasible-window binding changed: '+p)
    done=runner.read(root/DONE)
    if done['operation_sha256']!=sha(root/'sol_plan.json') or done['claim_sha256']!=sha(root/CLAIM):
        raise ValueError('Corrected operation or claim changed')
    folder=root/'model_calls'/TASK
    if not (folder/'accepted_response.json').is_file():raise ValueError('Accepted planner pointer missing')
    saved=saved_model_response(root,TASK)
    if done['response_sha256']!=sha(saved):raise ValueError('Accepted planner response changed')
    models.verify_call(root,TASK,'planner')
    fixed=runner.read(root/'engineering/outcome_frame_v1_plan_transport/fixed_context.json')
    actual=batch.validate_operation_plan(root,expand(runner.read(saved),fixed),'godot')
    if actual!=runner.read(root/'sol_plan.json'):raise ValueError('Operation differs from accepted model plan')
    return actual


def recover(workspace,row):
    workspace=Path(workspace).resolve();root=workspace/'runs'/row['entry']['id']
    repair_path=workspace/'engineering/planner_infeasible_window_repairs'/(root.name+'.json')
    repair=runner.read(repair_path)
    if (revision.revision(workspace)!='outcome_frame_v1' or not row['in_scope']
            or row['entry']['actual_engine']!='godot' or root.name!=IDENTITY
            or repair.get('classification')!='NON_SCORING_INFEASIBLE_OBSERVER_WINDOW'):
        raise ValueError('Explicit diagnosed original continuation required')
    if (root/'sol_plan.json').exists():verify(root);return root
    proto,schema,retained,fixed,original,error,diagnosis,bindings=qualify(root,repair['archived_producer'])
    contract=revision.contract_dir(workspace,row['entry']['case_id'])
    for p in [repair_path,contract/'contract.json',contract/'frozen.json']:
        bindings[str(p)]=sha(p)
    claim=dict(version=VERSION,identity=root.name,parent_task=parent.TASK,task=TASK,
        maximum_correction_invocations=1,classification=repair['classification'],
        parent_error=error['exception'],metadata_infeasibility=diagnosis,bindings=bindings,
        original_failures_claims_and_counts_preserved=True,physical_changes_only_from_model=True,
        scoring_semantics_unchanged=True,original_full_validators=True)
    if (root/CLAIM).exists():
        if runner.read(root/CLAIM)!=claim:raise ValueError('Immutable continuation claim changed')
    else:runner.exclusive_json(root/CLAIM,claim)
    text=prompt(root,schema,error,diagnosis)
    if len((READ_ONLY_EVAL_INSTRUCTIONS+text).encode())>1000000:raise ValueError('Original prompt cap exceeded')
    def validate(raw):
        validate_schema(raw,schema);validate_schema(raw,retained)
        op=expand(raw,fixed);validate_schema(op,original)
        return batch.validate_operation_plan(root,op,'godot')
    runner.configure_cli(Path(row['source_batch']));runner.disk(root,'infeasible_window_correction',256*1024**2)
    folder=root/'model_calls'/TASK
    if folder.exists():
        if not (folder/'accepted_response.json').exists():raise ValueError('Single substantive correction already attempted; preserve failure')
        if (runner.read(folder/'schema.json')!=schema or
                (folder/'prompt.txt').read_text()!=READ_ONLY_EVAL_INSTRUCTIONS+text):
            raise ValueError('Accepted independent planner context changed')
        raw=runner.read(saved_model_response(root,TASK))
    else:
        raw=call_codex(root,name=TASK,prompt=text,schema=schema,model=models.model_for(root,'planner'),
            timeout=600,max_attempts=1,explicit_stdin_separator=True,response_validator=validate)
    op=validate(raw);dump(root/'sol_plan.json',op);endpoint_sparse.freeze_conditions(root,proto,op)
    write_operation_report(root,op)
    dump(root/DONE,dict(version=VERSION,time=runner.stamp(),claim_sha256=sha(root/CLAIM),
        response_path=str(saved_model_response(root,TASK)),response_sha256=sha(saved_model_response(root,TASK)),
        operation_sha256=sha(root/'sol_plan.json'),original_full_validation=True,new_native_recording=False))
    dump(root/'stage.json',dict(time=runner.stamp(),stage='EXECUTABLE_NATIVE_PLAN',recovery=VERSION))
    return root
