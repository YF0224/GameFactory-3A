"""Recover one proven same-run omitted author file without changing the original.

Only exact bytes written by the original author tool call are admitted. Preserve
the original packaging defect and failed take; reuse its unchanged native plan.
"""
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
import copy
import hashlib
import json
import shutil
from . import batch, core12, endpoint_sparse, engine_scoped_capture
from . import mechanic_v3_native as native, mechanic_v3_revision as revisions
from . import mechanic_v3_runner as runner
from .protocol import sha, dump, write_operation_report

VERSION = 'mechanic-v3-same-original-omitted-material.v1'
CLAIM = 'mechanic_original_material_recovery_claim.json'
IDENTITY = 'GLM__G021_outpost_assault'
CONTENT_SHA = '77cddc7d2e5e3e1fcbade70520be4bfa97cba1835cb461b475d2cba84448cc3c'
LOG_SHA = '01f6af2bdd1e96be474b943a8e32cfcf4709355da4ea263a5a6cc37c68471fd5'
RELATIVE = 'scripts/ui/menus.gd'
CALL_ID = 'call_5f80d7f2f8f24d5eac837932'


def original_material(diagnosis, source):
    diagnosis=Path(diagnosis).resolve(); source=Path(source).resolve()
    value=runner.read(diagnosis); manifest=runner.read(source/'input_manifest.json')
    log=Path(value['original_log']); authored=Path(value['source_path_as_authored'])
    if (source.name!=IDENTITY or manifest['entry']['id']!=IDENTITY
            or manifest['entry']['actual_engine']!='godot'
            or log.resolve()!=Path(manifest['entry']['generation_run']).resolve()/'.generation/stages/whitebox/agent.log'
            or sha(log)!=LOG_SHA or value['original_log_sha256']!=LOG_SHA
            or value['content_sha256']!=CONTENT_SHA or value['content_bytes']!=7887
            or sha(authored)!=CONTENT_SHA or authored.is_symlink()):
        raise ValueError('Only the exact original same-run omitted file is admitted')
    lines=log.read_text().splitlines()
    event=json.loads(lines[value['event_line_1based']-1]); result=json.loads(lines[value['result_line_1based']-1])
    payload=event['payload']; outcome=result['payload']; written=outcome['result']
    content=payload['input']['content'].encode('utf-8')
    if (payload.get('toolCallId')!=CALL_ID or payload['input'].get('file_path')!=str(authored)
            or outcome.get('toolCallId')!=CALL_ID
            or str(authored) not in written.get('content','') or written.get('success') is not True
            or written.get('truncated') is not False
            or written['perf']['detail']['filesystem']['totalBytes']!=7887
            or hashlib.sha256(content).hexdigest()!=CONTENT_SHA or authored.read_bytes()!=content):
        raise ValueError('Original author write and successful tool result must match exact bytes')
    project=Path(manifest['entry']['project'])
    if (project/RELATIVE).exists() or RELATIVE in manifest['snapshot_hashes']:
        raise ValueError('The frozen original must retain its missing packaging fact')
    return content, [diagnosis,log,authored]


def validate_snapshot(original, actual, recovered_sha=CONTENT_SHA):
    expected={**original,RELATIVE:recovered_sha}
    if RELATIVE in original or actual!=expected:
        raise ValueError('Recovered snapshot must add only the proven original file')
    return expected


def verify(canonical):
    canonical=Path(canonical); claim=runner.read(canonical/CLAIM)
    if claim.get('version')!=VERSION or canonical.name!=IDENTITY:
        raise ValueError('Unknown same-original material continuation')
    for name,digest in claim['source_bindings'].items():
        if sha(Path(name))!=digest: raise ValueError('Original material parent changed: '+name)
    content,_=original_material(Path(claim['diagnosis']),canonical)
    root=Path(claim['recovery_root']); proof=runner.read(root/'original_material_recovery.json')
    if (proof['claim_sha256']!=sha(canonical/CLAIM)
            or proof['manifest_sha256']!=sha(root/'input_manifest.json')
            or proof['operation_sha256']!=sha(root/'sol_plan.json')):
        raise ValueError('Recovered material manifest or plan changed')
    before=runner.read(canonical/'input_manifest.json'); after=runner.read(root/'input_manifest.json')
    expected=copy.deepcopy(before)
    expected['snapshot_hashes']=validate_snapshot(before['snapshot_hashes'],after['snapshot_hashes'])
    expected['input_hashes']={**before['input_hashes'],'project/'+RELATIVE:CONTENT_SHA}
    if after!=expected or (root/'input/project'/RELATIVE).read_bytes()!=content:
        raise ValueError('Recovered input differs from the exact original additive snapshot')
    batch.verify_inputs(root)
    before_plan=runner.read(canonical/'sol_plan.json'); after_plan=runner.read(root/'sol_plan.json')
    before_plan['planning_identity']=after_plan['planning_identity']
    if before_plan!=after_plan: raise ValueError('Original material recovery changed actions or windows')
    return root


def prepare(workspace,row,diagnosis,repair):
    workspace=Path(workspace).resolve(); canonical=workspace/'runs'/row['entry']['id']
    if (revisions.publication_dir(workspace)/(canonical.name+'.json')).exists():
        raise ValueError('Reuse an existing complete product judgment')
    if (canonical/CLAIM).exists():
        root=verify(canonical)
        return root,batch.validate_operation_plan(root,runner.read(root/'sol_plan.json'),'godot')
    batch.verify_inputs(canonical); content,files=original_material(diagnosis,canonical)
    if any((canonical/'model_calls').glob('mechanic_v3*')):
        raise ValueError('Do not replace any runtime judgment attempt')
    cleanup=runner.read(canonical/'runtime/native_cleanup.json')
    if not all(cleanup.get(k) is True for k in ('input_cleanup','view_cleanup','process_cleanup')):
        raise ValueError('Real cleanup of the original failed take is required')
    if 'res://'+RELATIVE not in (canonical/'runtime/engine.log').read_text():
        raise ValueError('Preserve the exact missing-file loader failure')
    repair=Path(repair).resolve()
    if runner.read(repair).get('exit_code')!=0: raise ValueError('Directed repair regressions must pass')
    files += [repair,Path(__file__).resolve(),canonical/'input_manifest.json',canonical/'attempt_manifest.json',canonical/'sol_plan.json']
    for folder in ('input','model_calls','runtime'):
        files += [p for p in (canonical/folder).rglob('*') if p.is_file()
                  and not (folder=='runtime' and 'project' in p.relative_to(canonical/folder).parts)]
    contract=revisions.contract_dir(workspace,row['entry']['case_id'])
    files += [contract/'contract.json',contract/'frozen.json']
    bindings={str(p.resolve()):sha(p) for p in files}
    fingerprint=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    recovery=workspace/'original_material_recovery'/canonical.name/fingerprint; root=recovery/'runs'/canonical.name
    runner.disk(workspace,'same_original_omitted_material_prepare',2*1024**3)
    claim=dict(version=VERSION,time=runner.stamp(),source=str(canonical),source_bindings=bindings,
        diagnosis=str(Path(diagnosis).resolve()),recovery_root=str(root),original_file_missing=True,
        added_file=dict(path=RELATIVE,sha256=CONTENT_SHA,bytes=7887),original_project_modified=False,
        no_new_author_code=True,original_attempt_and_claims_preserved=True,product_score=None)
    runner.exclusive_json(canonical/CLAIM,claim)
    root.mkdir(parents=True,exist_ok=False);native.configuration(recovery,workspace)
    shutil.copytree(canonical/'input',root/'input',symlinks=True)
    target=root/'input/project'/RELATIVE;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(content)
    before=runner.read(canonical/'input_manifest.json'); manifest=copy.deepcopy(before)
    manifest['snapshot_hashes']=validate_snapshot(before['snapshot_hashes'],batch.hashes(root/'input/project'))
    manifest['input_hashes']=batch.hashes(root/'input');dump(root/'input_manifest.json',manifest)
    shutil.copyfile(canonical/'attempt_manifest.json',root/'attempt_manifest.json')
    proto=core12.verify_attempt(root,'godot');operation=copy.deepcopy(runner.read(canonical/'sol_plan.json'))
    operation['planning_identity']=core12.plan_identity(root,proto,'godot')
    operation=batch.validate_operation_plan(root,operation,'godot')
    dump(root/'sol_plan.json',operation);endpoint_sparse.freeze_conditions(root,proto,operation)
    write_operation_report(root,operation)
    dump(root/'original_material_recovery.json',dict(version=VERSION,claim_sha256=sha(canonical/CLAIM),
        manifest_sha256=sha(root/'input_manifest.json'),operation_sha256=sha(root/'sol_plan.json'),
        original_packaging_failure_preserved=True,source_role='EXACT_SAME_RUN_AUTHOR_OMITTED_MATERIAL',
        native_acceptance='PENDING'))
    verify(canonical)
    return root,operation


def record(workspace,row,diagnosis,repair):
    root,operation=prepare(workspace,row,diagnosis,repair)
    if (root/'source_qualification.json').exists():return root
    from . import mechanic_v3_outcome_native as outcome_native,mechanic_v3_record_completion as completion
    completion.freeze(root,operation);outcome_native.prepare_runtime_snapshot(root)
    if (root/'native_capture_admission.json').exists():
        raise ValueError('Preserve the attempted material recovery and diagnose it')
    runner.disk(root,'same_original_omitted_material_native_record',2*1024**3)
    engine_scoped_capture.capture(workspace,root,operation,
        SimpleNamespace(godot=Path.home()/'.local/bin/godot4'),row['entry'])
    qualification=runner.qualify_source(root,workspace=workspace)
    canonical=Path(workspace)/'runs'/row['entry']['id'];verify(canonical)
    qualification.update(new_recording=True,raw_record_reused=False,
        same_original_omitted_material=dict(path=str(canonical/CLAIM),sha256=sha(canonical/CLAIM),
            original_packaging_failure_preserved=True),
        notice='同run作者原始遗漏文件精确恢复副本后的新增真实原生录制；原冻结目录仍缺该文件')
    qualification['source_bindings'].update({str(canonical/CLAIM):sha(canonical/CLAIM),
        str(root/'original_material_recovery.json'):sha(root/'original_material_recovery.json')})
    runner.exclusive_json(root/'source_qualification.json',qualification)
    return root
