"""One source-bound native continuation after a diagnosed wrong author entry.

A failed loader is not a product score. Keep its complete take and model call;
reuse the unchanged validated actions after matching native launcher acceptance.
"""
from pathlib import Path
from types import SimpleNamespace
import copy
import hashlib
import json
import shutil
from . import batch, core12, endpoint_sparse, engine_scoped_capture
from . import mechanic_v3_native as native, mechanic_v3_revision as revisions
from .mechanic_v3_runner import read, exclusive_json, disk, stamp, qualify_source
from .protocol import sha, dump, write_operation_report

VERSION='mechanic-author-entry-native-recovery.v1'
CLAIM='mechanic_author_entry_recovery_claim.json'


def diagnosed_loader_failure(source):
    source=Path(source)
    selection=read(source/'runtime/launch_selection.json')
    if selection.get('author_entry') or selection.get('url_path')!='/':
        raise ValueError('Not the diagnosed legacy root entry')
    log=(source/'runtime/dev_server.log').read_text()
    if 'ENOENT' not in log or "data:text/css," not in log or '[vite]' not in log:
        raise ValueError('Exact recorded loader failure required')
    cleanup=read(source/'runtime/native_cleanup.json')
    if not all(cleanup.get(k) is True for k in ('input_cleanup','view_cleanup','process_cleanup')):
        raise ValueError('Actual input/view/process cleanup required')
    calls=list((source/'model_calls').glob('mechanic_v3*/response.json'))
    if not calls or not any(any(c.get('basic_function',{}).get('status')=='HARNESS_ERROR'
            for c in read(p).get('checks',{}).values()) for p in calls):
        raise ValueError('Preserved independent HARNESS_ERROR diagnosis required')
    if any((p.parent/'accepted_response.json').exists() for p in calls):
        raise ValueError('Cannot replace an accepted product judgment')
    from engine_adapters.three_js.playtest.launch import resolve_launch
    launch=resolve_launch(source/'input/project')
    if not launch.get('author_entry') or Path(launch['entry']).parent==(source/'input/project').resolve():
        raise ValueError('Existing original declared nested entry required')
    return launch


def verify(source):
    source=Path(source);claim=read(source/CLAIM)
    if claim['version']!=VERSION:raise ValueError('Unknown author-entry continuation')
    for path,digest in claim['source_bindings'].items():
        if sha(Path(path))!=digest:raise ValueError('Author-entry recovery parent changed: '+path)
    root=Path(claim['recovery_root']);proof=read(root/'author_entry_recovery.json')
    if proof['claim_sha256']!=sha(source/CLAIM) or proof['operation_sha256']!=sha(root/'sol_plan.json'):
        raise ValueError('Author-entry continuation plan changed')
    batch.verify_inputs(root)
    return root


def prepare(workspace,row):
    workspace=Path(workspace).resolve();source=workspace/'runs'/row['entry']['id']
    if (revisions.publication_dir(workspace)/(source.name+'.json')).exists():
        raise ValueError('Existing published Mechanic must be reused')
    if row['entry']['actual_engine']!='three_js':raise ValueError('Three.js loader recovery only')
    if (source/CLAIM).exists():
        root=verify(source)
        return root,batch.validate_operation_plan(root,read(root/'sol_plan.json'),'three_js')
    batch.verify_inputs(source);launch=diagnosed_loader_failure(source)
    acceptance=workspace/'engineering/three_js_launch_native_acceptance.json';accepted=read(acceptance)
    if not accepted.get('accepted') or accepted.get('production_sources')!=engine_scoped_capture.sources('three_js'):
        raise ValueError('Matching complete launcher native acceptance required')
    for path,digest in accepted['evidence_bindings'].items():
        if sha(Path(path))!=digest:raise ValueError('Native acceptance evidence changed')
    paths=[Path(__file__),acceptance,source/'input_manifest.json',source/'attempt_manifest.json',
           source/'sol_plan.json',source/'source_qualification.json',source/'evidence_manifest.json',source/'trace_summary.json']
    for folder in ('input','model_calls','requests','failures','runtime'):
        paths.extend(p for p in (source/folder).rglob('*') if p.is_file()
                     and not (folder=='runtime' and 'project' in p.relative_to(source/'runtime').parts))
    contract=revisions.contract_dir(workspace,row['entry']['case_id'])
    paths.extend((contract/'contract.json',contract/'frozen.json'))
    bindings={str(p.resolve()):sha(p) for p in paths}
    fingerprint=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()
    recovery=workspace/'author_entry_recovery'/source.name/fingerprint;root=recovery/'runs'/source.name
    disk(workspace,'author_entry_recovery_prepare',2*1024**3)
    claim=dict(version=VERSION,time=stamp(),source=str(source),source_bindings=bindings,
               recovery_root=str(root),author_launch=launch,
               reason='Native wrong root entry caused a recorded Vite CSS loader failure; author-declared original nested entry passed matching native acceptance.',
               original_failed_take_and_claims_preserved=True,source_actions_windows_unchanged=True,
               product_score=None,model_request_repeated=False)
    exclusive_json(source/CLAIM,claim)
    root.mkdir(parents=True,exist_ok=False);native.configuration(recovery,workspace)
    shutil.copytree(source/'input',root/'input',symlinks=True)
    for name in ('input_manifest.json','attempt_manifest.json'):shutil.copyfile(source/name,root/name)
    proto=core12.verify_attempt(root,'three_js');before=read(source/'sol_plan.json');operation=copy.deepcopy(before)
    operation['planning_identity']=core12.plan_identity(root,proto,'three_js')
    operation=batch.validate_operation_plan(root,operation,'three_js')
    expected=copy.deepcopy(before);expected['planning_identity']=operation['planning_identity']
    if operation!=expected:raise ValueError('Author-entry recovery changed actions or observation windows')
    dump(root/'sol_plan.json',operation);endpoint_sparse.freeze_conditions(root,proto,operation)
    write_operation_report(root,operation)
    exclusive_json(root/'author_entry_recovery.json',dict(version=VERSION,
        claim_sha256=sha(source/CLAIM),operation_sha256=sha(root/'sol_plan.json'),
        original_actions_windows_source_unchanged=True,full_current_validator_passed=True,
        native_record_and_judge_acceptance='PENDING'))
    return root,operation


def record(workspace,row):
    root,operation=prepare(workspace,row)
    if (root/'source_qualification.json').exists():return root
    from . import mechanic_v3_outcome_native as outcome_native,mechanic_v3_record_completion as completion
    completion.freeze(root,operation);outcome_native.prepare_runtime_snapshot(root)
    if (root/'native_capture_admission.json').exists():raise ValueError('Retained attempted recovery requires diagnosis')
    disk(root,'author_entry_native_record',2*1024**3)
    engine_scoped_capture.capture(workspace,root,operation,
                                 SimpleNamespace(godot=Path.home()/'.local/bin/godot4'),row['entry'])
    qualification=qualify_source(root,workspace=workspace)
    qualification.update(new_recording=True,raw_record_reused=False,
        notice='作者原始声明入口工具修复后新增真实原生录制',
        author_entry_recovery_sha256=sha(root/'author_entry_recovery.json'),
        view_manifest_sha256=sha(root/'evidence_manifest.json'))
    exclusive_json(root/'source_qualification.json',qualification)
    return root
