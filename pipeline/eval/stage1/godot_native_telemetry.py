"""Source-bound native fixture acceptance and one diagnostic for failed captures.

This phase never qualifies a take, judges a product or publishes a score. It
preserves a failed plan and native evidence, then obtains actual callback/window
telemetry with the versioned observer under ordinary shared execution leases.
"""
from pathlib import Path
import copy
import fcntl
import json
import shutil
import subprocess
import time
from . import batch, core12, mechanic_v3_runner as runner, sparse_native
from .protocol import dump, sha
from engine_adapters.godot.playtest import telemetry as adapter

VERSION = 'whitebox-godot-native-telemetry.v1'
FRAMEWORK = Path(__file__).resolve().parents[3]
FIXTURE = FRAMEWORK/'test/fixtures/godot_capture_telemetry'
ACCEPTANCE = 'engineering/native_telemetry_acceptance/godot.json'


def bindings():
    files = [Path(__file__), Path(adapter.__file__), adapter.RECORDER,
        adapter.RECORDER.with_name('bounded_recorder.gd'),
        FRAMEWORK/'pipeline/eval/stage1/mechanic_v3_cli.py',
        adapter.RECORDER.with_name('scene_entry.py')]
    files += sorted(p for p in FIXTURE.rglob('*') if p.is_file() and '.godot' not in p.parts)
    return {str(p.resolve()): sha(p) for p in files}


def verify(references):
    for path, expected in references.items():
        if sha(Path(path)) != expected: raise ValueError('Native telemetry binding changed: '+path)


def read_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def binary(row):
    return (Path.home()/'.local/bin/godot4').resolve(strict=True)


def check_compile(project, output, executable):
    result = subprocess.run([str(executable),'--headless','--path',str(project),
        '--script',str(adapter.RECORDER.resolve()),'--check-only'],
        stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=30)
    (output/'observer_check.log').write_bytes(result.stdout)
    if result.returncode: raise ValueError('Telemetry observer compile failed; see observer_check.log')


def take(workspace, row, project, plan, output):
    output.mkdir(parents=True,exist_ok=False)
    runner.disk(workspace,'godot_native_telemetry',2*1024**3)
    executable = binary(row)
    check_compile(project,output,executable)
    with runner.held(workspace,Path(row['source_batch']),native=True):
        from .runtime import assert_gui_available
        assert_gui_available(output,capture_backend='client_viewport')
        result = adapter.record(project,output/'runtime',plan,executable,60)
    return result


def acceptance(workspace, row):
    """Verify native input/pixels and cleanup for both full and early-exit trees."""
    if row['entry']['actual_engine']!='godot' or not row['in_scope']:
        raise ValueError('Frozen in-scope Godot identity required')
    path = workspace/ACCEPTANCE
    if path.exists():
        value = runner.read(path)
        if value['production_bindings'] != bindings():
            raise ValueError('Telemetry acceptance belongs to different production code')
        verify(value['evidence_bindings'])
        return value
    root = workspace/'engineering/native_telemetry_acceptance'/str(time.time_ns())
    root.mkdir(parents=True)
    proofs = []
    for early in (False,True):
        case = root/('early_exit' if early else 'complete')
        case.mkdir()
        project = case/'project'
        shutil.copytree(FIXTURE,project)
        if early:
            with (project/'project.godot').open('a') as file:
                file.write('\n[fixture]\nearly_exit=true\n')
        plan = dict(max_duration_ms=4200,recording_ms=4200,
            watchers=[dict(id='pressed',script='res://main.gd',index=0,property='pressed')],
            probes=[dict(id='input',steps=[dict(id='enter',kind='input',key='Enter',duration_ms=80),
                dict(id='observe',kind='wait',duration_ms=2000)])])
        dump(case/'plan.json',plan)
        result = take(workspace,row,project,case/'plan.json',case/'take')
        native = case/'take/runtime'
        trace = read_rows(native/'state_trace.jsonl')
        images = read_rows(native/'frame_index.jsonl')
        cleanup = runner.read(native/'input_view_cleanup.json')
        execution = runner.read(native/'execution.json')
        telemetry = read_rows(native/'capture_telemetry.jsonl')
        if (not any(v.get('values',{}).get('pressed') is True for v in trace)
                or len(images)<2 or not cleanup['input_cleanup']
                or not cleanup['capture_callback_disconnected']
                or not result['cleanup']['view_cleanup'] or not result['cleanup']['process_cleanup']
                or not telemetry or telemetry[-1]['reason']!='cleanup_complete'
                or execution['complete'] is early or result['timeout']
                or 'SCRIPT ERROR:' in (native/'engine.log').read_text()):
            raise ValueError('Real native telemetry fixture failed: '+str(case))
        from PIL import Image,ImageChops
        first=Image.open(native/images[0]['path']).convert('RGB')
        if not any(ImageChops.difference(first,Image.open(native/v['path']).convert('RGB')).getbbox()
                   for v in images[1:]):
            raise ValueError('Real input did not alter native pixels')
        proofs.append(dict(early_exit=early,actual_input=True,native_pixel_change=True,
            complete=execution['complete'],root_valid_at_cleanup=cleanup['root_valid_at_cleanup']))
    evidence = {str(p.resolve()):sha(p) for p in root.rglob('*') if p.is_file() and '.godot' not in p.parts}
    value=dict(version=VERSION,accepted=True,production_bindings=bindings(),
        evidence_bindings=evidence,cases=proofs,fixture_is_not_product_evaluation=True,
        scoring_semantics_unchanged=True,original_adapter_pin_unchanged=True)
    runner.exclusive_json(path,value)
    return value


def diagnose(workspace,row,source,repair):
    """Exactly one diagnostic for the bound recorded harness failure."""
    source=Path(source).resolve(); repair=Path(repair).resolve()
    if source.name!=row['entry']['id'] or row['entry']['actual_engine']!='godot' or not row['in_scope']:
        raise ValueError('Frozen same-identity original Godot failure required')
    batch.verify_inputs(source)
    source_entry=runner.read(source/'input_manifest.json')['entry']
    from .mechanic_v3_full_scope import same_original
    if not same_original(source_entry,row['entry']): raise ValueError('Diagnostic original source differs')
    if any((source/n).exists() for n in ['source_qualification.json','mechanic_score.json','gameness_score.json']):
        raise ValueError('Qualified/scored capture must be reused')
    failed=runner.read(source/'runtime/execution.json')
    if failed.get('complete') is not False or failed.get('status')!='HARNESS_ERROR':
        raise ValueError('Retained incomplete HARNESS_ERROR capture required')
    previous_cleanup=runner.read(source/'runtime/process_cleanup.json')
    if not previous_cleanup.get('process_cleanup') or not previous_cleanup.get('view_cleanup'):
        raise ValueError('Original owned process/view cleanup must be proven')
    accepted=runner.read(workspace/ACCEPTANCE)
    if accepted.get('accepted') is not True or accepted['production_bindings']!=bindings():
        raise ValueError('Matching real native telemetry acceptance required')
    verify(accepted['evidence_bindings'])
    diagnosis=runner.read(repair)
    if (diagnosis.get('classification')!='NON_SCORING_NATIVE_CAPTURE_TELEMETRY'
            or diagnosis.get('source')!=str(source)
            or diagnosis.get('production_bindings')!=bindings()):
        raise ValueError('Explicit substantive telemetry repair binding required')
    verify(diagnosis['parent_bindings'])
    if not diagnosis.get('root_cause') or not diagnosis.get('scoring_semantics_unchanged'):
        raise ValueError('Retained diagnosis and unchanged scoring required')
    claim=source/'native_capture_telemetry_claim.json'
    if claim.exists(): raise ValueError('Diagnostic already claimed; preserve its result before further substantive repair')
    root=workspace/'engineering/native_capture_telemetry'/source.name/sha(repair)
    plan=runner.read(source/'runtime/recording_plan.json')
    before=runner.read(source/'sol_plan.json')
    for field in ['probes','capture_plan','watchers','max_duration_ms']:
        if plan.get(field)!=before.get(field): raise ValueError('Recorded/native executable plan differs: '+field)
    # Keep original plan and exact schedule. New telemetry never calls author methods.
    runner.disk(workspace,'godot_native_diagnostic_project',2*1024**3)
    root.mkdir(parents=True,exist_ok=False)
    runner.exclusive_json(claim,dict(version=VERSION,repair=str(repair),repair_sha256=sha(repair),
        root=str(root),maximum_attempts=1,parent_bindings=diagnosis['parent_bindings'],
        original_failed_evidence_preserved=True,scoring_semantics_unchanged=True))
    shutil.copytree(source/'input/project',root/'project',ignore=shutil.ignore_patterns('.godot'))
    dump(root/'plan.json',plan)
    try:
        result=take(workspace,row,root/'project',root/'plan.json',root/'take')
        batch.verify_inputs(source);verify(diagnosis['parent_bindings'])
        receipt=dict(version=VERSION,source=str(source),root=str(root),result=result,
            diagnostic_only=True,new_product_score=None,original_plan_actions_windows_unchanged=True,
            acceptance_sha256=sha(workspace/ACCEPTANCE),repair_sha256=sha(repair),
            evidence_bindings={str(p):sha(p) for p in (root/'take').rglob('*') if p.is_file()})
        dump(root/'diagnostic_result.json',receipt)
        return receipt
    except Exception as error:
        dump(root/'failure.json',dict(version=VERSION,error=repr(error),product_score=None,
            original_failed_evidence_preserved=True))
        raise
