"""Fresh native Mechanic capture using existing production adapters/validators.

Only the opt-in v3 basic contract is appended to planner guidance. The frozen
capture policy, source/rubric identity, original input and native validator stay
unchanged. No old queue is resumed; no other column is sent for judgment.
"""
from . import evaluation_model_profile as eval_models
from pathlib import Path
from types import SimpleNamespace
import json
import copy
import shutil
from . import batch, core12, core12_planning, endpoint_sparse, sparse_native
from .protocol import dump, sha, write_operation_report
from .codex import call_codex, saved_model_response
from . import mechanic_v3 as v3
from . import mechanic_v3_revision as revisions
from .mechanic_v3_runner import read, stamp, disk, exclusive_json


def configuration(workspace,source_batch):
    for name in ('native_capture_configuration.json',):
        source=source_batch/name;dest=workspace/name
        if dest.exists() and dest.read_bytes()!=source.read_bytes():
            # The paired batches label their scope with different model names.
            # Keep the frozen workspace config unchanged and prove all execution
            # controls identical; never normalize any functional field.
            left,right=read(dest),read(source)
            if (not isinstance(left.get('scope'),str) or not isinstance(right.get('scope'),str)
                    or {k:v for k,v in left.items() if k!='scope'}!={k:v for k,v in right.items() if k!='scope'}):
                raise ValueError('Native configuration changed')
            proof=workspace/'engineering/native_configuration_compatibility'/(source_batch.name+'.json')
            value=dict(source=str(source),source_sha256=sha(source),workspace_config=str(dest),
                workspace_sha256=sha(dest),excluded_field='scope',source_scope=right['scope'],
                workspace_scope=left['scope'],execution_controls_equal=True,workspace_config_unchanged=True)
            if proof.exists() and read(proof)!=value:raise ValueError('Native compatibility source changed')
            if not proof.exists():exclusive_json(proof,value)
        if not dest.exists():shutil.copy2(source,dest)
    for engine in ('godot','three_js'):
        src=source_batch/'engineering/native_acceptance'/(engine+'.json')
        dst=workspace/'engineering/native_acceptance'/(engine+'.json');dst.parent.mkdir(parents=True,exist_ok=True)
        if dst.exists() and src.read_bytes()!=dst.read_bytes():raise ValueError('Native acceptance changed')
        if not dst.exists():shutil.copy2(src,dst)


def paired_endpoint_conditions(inventory,case):
    for counterpart in inventory['entries']:
        if counterpart['entry']['case_id']!=case or not counterpart['preferred_record']:
            continue
        source_proto=read(Path(counterpart['preferred_record'])/'input/pilot_rubric.json')
        conditions=endpoint_sparse.shared_conditions_path(Path(counterpart['source_batch']),source_proto)
        if conditions.is_file():
            return {'path':str(conditions.resolve()),'sha256':sha(conditions)}
    return None


def prepare_and_plan(workspace,row):
    entry=row['entry'];case=entry['case_id'];root=workspace/'runs'/entry['id'];source_batch=Path(row['source_batch'])
    frozen=read(revisions.contract_dir(workspace,case)/'frozen.json')
    contract=read(revisions.contract_dir(workspace,case)/'contract.json')
    if sha(revisions.contract_dir(workspace,case)/'contract.json')!=frozen['contract_sha256']:raise ValueError('Contract changed')
    configuration(workspace,source_batch)
    if row['preferred_record']:raise ValueError('Reuse qualified historical capture before requesting new recording')
    if not row['in_scope']:raise ValueError('Missing or excluded original delivery')
    disk(workspace,'native_prepare',2*1024**3)
    if not root.exists():
        entry=copy.deepcopy(entry)
        # A new identity must retain the already frozen paired full endpoint
        # conditions, rather than ask the planner to derive a second version.
        entry['endpoint_conditions']=paired_endpoint_conditions(read(workspace/'inventory.json'),case)
        if entry['endpoint_conditions'] is None:entry.pop('endpoint_conditions')
        batch.prepare(source_batch,entry,root)
    if not (root/'input_manifest.json').exists():raise ValueError('Incomplete preparation retained, diagnose substantive recovery')
    batch.verify_inputs(root)
    engine=entry['actual_engine'];proto=core12.verify_attempt(root,engine)
    v3.validate_contract(proto,contract)
    identity=core12.plan_identity(root,proto,engine)
    if (root/'sol_plan.json').exists():
        return root,batch.validate_operation_plan(root,read(root/'sol_plan.json'),engine)
    if (root/'model_calls/plan').exists():
        if not (root/'model_calls/plan/accepted_response.json').exists():
            raise ValueError('Preserved failed planner; diagnose before substantive recovery')
        operation=batch.validate_operation_plan(root,read(saved_model_response(root,'plan')),engine)
    else:
        if (root/'model_calls/plan_v3_fixed_context').exists():
            raise ValueError('Preserved compact planner response requires explicit source-bound recovery')
        from .mechanic_v3_plan_transport import plan_frozen
        operation=plan_frozen(workspace,root,proto,engine,identity,contract,frozen,capture_map_complete=True)
    dump(root/'sol_plan.json',operation);endpoint_sparse.freeze_conditions(root,proto,operation)
    write_operation_report(root,operation)
    dump(root/'stage.json',dict(time=stamp(),stage='EXECUTABLE_NATIVE_PLAN',model=eval_models.model_for(root, "planner")))
    return root,operation


def record(workspace,row,*,godot=None):
    from .mechanic_v3_runner import qualify_source
    root,operation=prepare_and_plan(workspace,row)
    if not (root/'runtime/frame_index.jsonl').exists():
        args=SimpleNamespace(godot=godot or Path.home()/'.local/bin/godot4')
        try:sparse_native.capture(root,operation,args,row['entry'])
        except BlockingIOError as error:
            dump(root/'native_lock_block.json',dict(time=stamp(),error=repr(error),
                stage='NEEDS_NATIVE_EXECUTION_LOCK',plan_preserved=True,record_complete=False,
                next_action='Recheck owner/lease; acquire unchanged formal locks after current owner releases, without restarting old queue'))
            raise
    qualification=qualify_source(root)
    qualification.update(recording='NEW_REAL_NATIVE_RECORD',notice='本专项按新冻结契约后真实原生录制；未复用旧判词',
        new_recording=True,raw_record_reused=False,view_manifest_sha256=sha(root/'evidence_manifest.json'))
    exclusive_json(root/'source_qualification.json',qualification)
    print(json.dumps(dict(identity=root.name,stage='NEW_NATIVE_RECORD_COMPLETE')),flush=True)
    return root
