"""One source-bound correction of a rejected, never-recorded Unity M plan."""
from pathlib import Path
import hashlib
import json
import re
from . import batch, mechanic_v3_runner as runner
from .codex import call_codex, validate_schema, READ_ONLY_EVAL_INSTRUCTIONS
from .mechanic_v3_plan_transport import expand
from .mechanic_v3_plan_recovery import recording_started
from .protocol import sha


def supported(error):
    return error.startswith(('native step ID must be globally unique across probes: ',
        'endpoint is not the declared final observation in its coverage window: ',
        'endpoint must follow its actual last input and declared settling observation: ')) or error in {
        'core12 coverage extends past its referenced probes',
        'core12 coverage is unrelated to its referenced probe',
        'invalid native probe count',
        'launch_source must be an existing original project file',
        'Unity launch scene is not an existing delivered scene',
        'core12 coverage crosses an unrelated probe interval',
        'core12 coverage window lies outside the planned action timeline'}


def schema_supported(error):
    return re.fullmatch(r'\$\.probes\[\d+\]\.criterion_ids\[\d+\]: invalid enum value', error) is not None


def recover(root, proto):
    root=Path(root);folder=root/'model_calls/plan_v3_outcome_frame_v1'
    if (recording_started(root) or (root/'background_record').exists() or (root/'source_qualification.json').exists()
            or (root/'sol_plan.json').exists() or (folder/'accepted_response.json').exists()):
        raise ValueError('Unity plan correction requires a never-recorded rejected plan')
    errors=[folder/name for name in ('validation_error.json','schema_error.json') if (folder/name).is_file()]
    if len(errors)!=1:
        raise ValueError('One exact preserved Unity planner failure required')
    error=batch.read(errors[0]); schema_failure=errors[0].name=='schema_error.json'
    permitted=schema_supported(error.get('exception','')) if schema_failure else supported(error.get('exception',''))
    if not permitted or error.get('response_sha256')!=sha(folder/'response.json'):
        raise ValueError('Exact diagnosed Unity planner response required')
    batch.verify_inputs(root)
    proof=root/'engineering/outcome_frame_v1_plan_transport'
    schema=batch.read(folder/'schema.json');original=batch.read(proof/'original_schema.json');fixed=batch.read(proof/'fixed_context.json')
    if schema!=batch.read(proof/'submitted_schema.json'):raise ValueError('Original submitted planner schema changed')
    raw=batch.read(folder/'response.json')
    try:
        validate_schema(raw,schema)
        if schema_failure:raise RuntimeError('Original schema failure no longer reproduces')
        expanded=expand(raw,fixed);validate_schema(expanded,original)
        batch.validate_operation_plan(root,expanded,'unity3d',record_validation=False)
    except ValueError as observed:
        if str(observed)!=error['exception']:raise ValueError('Original planner diagnosis changed') from observed
    else:raise ValueError('Already valid planner output must be reused')
    invocation=batch.read(folder/'invocation.json');command=invocation['command']
    if invocation.get('exit_code')!=0 or command[command.index('--model')+1]!='gpt-6.1-sol':
        raise ValueError('Completed original Sol planner invocation required')
    full=(folder/'prompt.txt').read_text()
    if not full.startswith(READ_ONLY_EVAL_INSTRUCTIONS):raise ValueError('Original read-only instructions required')
    prompt=full[len(READ_ONLY_EVAL_INSTRUCTIONS):]+('\nONE BOUNDED SOURCE-ONLY UNITY PLAN CORRECTION. '
        'The previous complete response was rejected before any native recording. Return a complete response in the unchanged schema. '
        'Every probe ID and every step ID share one global uniqueness namespace: no step may reuse a probe ID or any other step ID. '
        'Use only the exact frozen criterion ID enums in the unchanged schema. Unity accepts at most 10 probes, each at most 24 steps; multiple targets may share a genuine physical probe. '
        'The actual cumulative action timeline starts at 1800ms. wait_until/move_until consume timeout_ms; input consumes max(100,duration_ms); other actions consume duration_ms. '
        'Every referenced probe must contain the target criterion and intersect its coverage interval; coverage windows must be ordered with start_ms < end_ms and be continuously covered by their referenced probes. '
        'last_action_id must be the actual last non-wait physical action for that target before its endpoint, followed by the declared settling wait. '
        'launch_source and launch_scene must name actual original delivered files under the unchanged original launch rules. Never invent an entry, scene or author behavior. '
        'Recompute coverage windows using the actual cumulative action timeline including earlier probes and the existing readiness offset. '
        'Each coverage interval must fit its referenced probes, and endpoints and observation windows must fit the original recording budget. '
        'Every endpoint must reference the declared final observation in its own coverage window. '
        'Keep all original source, frozen contracts, rubrics, allowed input actions and budgets. A partial legal route is sufficient. '
        'No runtime frames or scores are provided; do not claim results or add author gameplay. '
        'Only your response may propose any changed physical input, wait or observation; the full original validators run again. '
        'Original validator error: ')+error['exception']+'\nCOMPLETE REJECTED RESPONSE\n'+(folder/'response.json').read_text()
    if len((READ_ONLY_EVAL_INSTRUCTIONS+prompt).encode())>1000000:raise ValueError('Complete planner correction exceeds frozen cap')
    name='unity_m_source_plan_correction';claim_path=root/'engineering/unity_m_source_plan_correction/claim.json'
    from .gameness_v3_runtime import production_bindings
    files=[p for p in folder.iterdir() if p.is_file()]+[proof/n for n in ('original_schema.json','submitted_schema.json','fixed_context.json')]+[root/'unity_m_source_binding.json']
    claim={'version':'unity-m-source-plan-correction.v1','maximum_calls':1,'parent_error':error['exception'],
        'bindings':{str(p):sha(p) for p in files},'production':production_bindings(),
        'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),'model':'gpt-6.1-sol',
        'runtime_evidence_supplied':False,'physical_changes_only_from_model':True}
    saved=claim_path.exists()
    if saved:
        if batch.read(claim_path)!=claim:raise ValueError('Preserved planner correction binding changed')
        if not (root/'model_calls'/name/'accepted_response.json').exists():
            raise ValueError('Preserve claimed planner correction; no unchanged repeat')
    else:runner.exclusive_json(claim_path,claim)
    def validate(value):
        validate_schema(value,schema);operation=expand(value,fixed);validate_schema(operation,original)
        return batch.validate_operation_plan(root,operation,'unity3d')
    corrected=(batch.read(root/'model_calls'/name/'response.json') if saved else
        call_codex(root,name=name,prompt=prompt,schema=schema,model='gpt-6.1-sol',timeout=600,max_attempts=1,response_validator=validate))
    operation=validate(corrected)
    from .unity_m_judge import exact_json
    exact_json(claim_path.parent/'completion.json',{'parent_claim_sha256':sha(claim_path),
        'response_sha256':sha(root/'model_calls'/name/'response.json'),'original_schema_and_validators_passed':True,
        'operation':operation,'native_recording_performed':False,'scored_column':False})
    return operation
