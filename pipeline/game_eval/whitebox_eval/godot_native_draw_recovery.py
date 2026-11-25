"""One source-bound native draw recovery after a retained callback-stall diagnostic.

No author script, input, clock, capture schedule or scoring rule is changed.
The old bounded/telemetry adapters and their historical acceptances stay pinned.
"""
from pathlib import Path
import shutil
import subprocess
import time
from . import batch, endpoint_sparse, sparse_evidence
from . import mechanic_v3_runner as runner, mechanic_v3_full_scope as scope
from . import godot_native_telemetry as telemetry
from .protocol import dump, sha
from engine_adapters.godot.playtest import draw_recovery as adapter

VERSION = 'whitebox-godot-native-draw.v1'
ACCEPTANCE = 'engineering/native_draw_acceptance/godot.json'
CLAIM = 'native_draw_recovery_claim.json'
FRAMEWORK = Path(__file__).resolve().parents[3]
FIXTURE = FRAMEWORK/'test/fixtures/godot_native_draw'


def bindings():
    from .mechanic_v3_cli import production_source_bindings
    value = production_source_bindings()
    files = [Path(adapter.__file__), adapter.RECORDER,
        adapter.RECORDER.with_name('bounded_telemetry_recorder.gd'),
        adapter.RECORDER.with_name('bounded_recorder.gd'),
        adapter.RECORDER.with_name('telemetry.py'), adapter.RECORDER.with_name('scene_entry.py')]
    files += [p for p in FIXTURE.rglob('*') if p.is_file() and '.godot' not in p.parts]
    value.update({str(p.resolve()): sha(p) for p in files})
    return value


def acceptance_path(workspace, *, recorded_bindings=None):
    import hashlib, json
    digest=hashlib.sha256(json.dumps(bindings() if recorded_bindings is None else recorded_bindings,sort_keys=True).encode()).hexdigest()
    return workspace/'engineering/native_draw_acceptances'/(digest+'.json')


def admission_continuation(parent, root, repair, *, recorded_bindings=None):
    value=runner.read(repair)
    if value.get('parent_claim_sha256')!=sha(parent/CLAIM):
        raise ValueError('Original admission claim changed')
    claim=runner.read(parent/CLAIM)
    previous=Path(claim['repair']); before=runner.read(previous)
    after=bindings() if recorded_bindings is None else recorded_bindings
    if (value.get('classification')!='NATIVE_DRAW_ADMISSION_CONTINUATION'
            or value.get('parent_repair')!=str(previous)
            or value.get('parent_repair_sha256')!=sha(previous)
            or value.get('parent_claim_sha256')!=sha(parent/CLAIM)
            or value.get('root')!=str(root)
            or value.get('production_bindings')!=after
            or set(before['production_bindings'])!=set(after)
            or not value.get('scoring_semantics_unchanged') or not value.get('root_cause')):
        raise ValueError('Exact pre-native admission continuation required')
    changed={p for p in after if before['production_bindings'][p]!=after[p]}
    archives=value.get('before_archive',{})
    allowed={str(Path(__file__).resolve()), str(Path(__file__).with_name('godot_native_telemetry_reuse.py').resolve())}
    if not changed or changed!=allowed or set(archives)!=changed:
        raise ValueError('Admission continuation may change only the exact admission and acceptance handoff modules')
    for name,archive in archives.items():
        if sha(Path(archive))!=before['production_bindings'][name]:
            raise ValueError('Exact pre-admission producer bytes required')
    required=[parent/CLAIM,previous,root/'failure.json']
    if any(value.get('parent_bindings',{}).get(str(p))!=sha(p) for p in required):
        raise ValueError('Original claim, repair and lock failure must remain bound')
    telemetry.verify(before['parent_bindings']); telemetry.verify(value['parent_bindings'])
    failure=runner.read(root/'failure.json')
    if 'BlockingIOError' not in failure.get('error',''):
        raise ValueError('Only retained admission lock failure can resume without a new native attempt')
    return value


def verify_acceptance(path, *, recorded_bindings=None):
    value = runner.read(path)
    expected = {'baseline_stall', 'complete', 'early_exit'}
    if (value.get('version') != VERSION or value.get('accepted') is not True
            or value.get('production_bindings') != (bindings() if recorded_bindings is None else recorded_bindings)
            or {v.get('kind') for v in value.get('cases', [])} != expected
            or not value.get('scoring_semantics_unchanged')
            or value.get('engine_sha256') != sha(telemetry.binary(None))):
        raise ValueError('Matching full native draw acceptance required')
    telemetry.verify(value['evidence_bindings'])
    cases = {v['kind']: v for v in value['cases']}
    if (not cases['baseline_stall'].get('missing_slots_ms')
            or cases['complete'].get('missing_slots_ms') != []
            or not all(cases[k].get('actual_input') and cases[k].get('native_pixel_change')
                       and cases[k].get('cleanup') for k in expected)
            or cases['complete'].get('complete') is not True
            or cases['early_exit'].get('complete') is not False
            or not cases['early_exit'].get('missing_slots_ms')
            or cases['complete'].get('forced_draws', 0) < 1):
        raise ValueError('Native stall, complete recovery and early-exit rejection required')
    return dict(path=str(path), sha256=sha(path), production_bindings=value['production_bindings'],
                historical_recording_acceptance=True, native_draw_recovery=True)


def take(workspace, row, project, plan, output, *, baseline=False):
    if output.exists():
        if (output/'runtime').exists():
            raise ValueError('Native execution already started; preserve its result')
    else:
        output.mkdir(parents=True, exist_ok=False)
    runner.disk(workspace, 'godot_native_draw', 2*1024**3)
    executable = telemetry.binary(row)
    chosen = telemetry.adapter if baseline else adapter
    check = subprocess.run([str(executable), '--headless', '--path', str(project),
        '--script', str(chosen.RECORDER.resolve()), '--check-only'],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30)
    check_path=output/'observer_check.log'
    if check_path.exists(): check_path=output/('observer_check_'+str(time.time_ns())+'.log')
    check_path.write_bytes(check.stdout)
    if check.returncode: raise ValueError('Native draw observer compile failed: '+str(output))
    with runner.held(workspace, Path(row['source_batch']), native=True):
        from .runtime import assert_gui_available
        assert_gui_available(output, capture_backend='client_viewport')
        return chosen.record(project, output/'runtime', plan, executable, 60)


def acceptance(workspace, row):
    if row['entry']['actual_engine'] != 'godot' or not row['in_scope']:
        raise ValueError('Frozen Godot identity required')
    path = acceptance_path(workspace)
    if path.exists(): return verify_acceptance(path)
    root = workspace/'engineering/native_draw_acceptance'/str(time.time_ns())
    root.mkdir(parents=True)
    cases = []
    for kind in ('baseline_stall', 'complete', 'early_exit'):
        case = root/kind; case.mkdir()
        project = case/'project'; shutil.copytree(FIXTURE, project)
        if kind == 'early_exit':
            with (project/'project.godot').open('a') as handle:
                handle.write('\n[fixture]\nearly_exit=true\n')
        schedule = dict(version='native-sparse-capture.v1',
            points=[dict(at_ms=t, capture_ids=['fixture'], criterion_ids=[])
                    for t in range(1900, 4101, 100)], tolerance_ms=75)
        # The fixture uses the same recorder schedule fields; product schedules
        # are separately validated and must stay byte-identical to the parent.
        plan = dict(max_duration_ms=4200, recording_ms=4200, native_capture_schedule=schedule,
            watchers=[dict(id='pressed', script='res://main.gd', index=0, property='pressed')],
            probes=[dict(id='input', steps=[dict(id='enter', kind='input', key='Enter', duration_ms=80),
                dict(id='observe', kind='wait', duration_ms=2000)])])
        dump(case/'plan.json', plan)
        result = take(workspace, row, project, case/'plan.json', case/'take', baseline=kind=='baseline_stall')
        native = case/'take/runtime'
        trace = telemetry.read_rows(native/'state_trace.jsonl')
        images = telemetry.read_rows(native/'frame_index.jsonl')
        cleanup = runner.read(native/'input_view_cleanup.json')
        execution = runner.read(native/'execution.json')
        logs = telemetry.read_rows(native/'capture_telemetry.jsonl')
        times = {v.get('sample_at_ms') for v in images}
        missing = [v['at_ms'] for v in schedule['points'] if v['at_ms'] not in times]
        actual = any(v.get('values', {}).get('pressed') is True for v in trace)
        clean = all(cleanup.get(k) is True for k in ('input_cleanup','capture_callback_disconnected')) and all(
            result['cleanup'].get(k) is True for k in ('process_cleanup','view_cleanup'))
        from PIL import Image, ImageChops
        first = Image.open(native/images[0]['path']).convert('RGB') if images else None
        changed = first is not None and any(ImageChops.difference(first,
            Image.open(native/v['path']).convert('RGB')).getbbox() for v in images[1:])
        proof = dict(kind=kind, actual_input=actual, native_pixel_change=bool(changed), cleanup=clean,
            complete=execution['complete'], missing_slots_ms=missing,
            forced_draws=sum(v['reason']=='force_draw_before' for v in logs))
        dump(case/'fixture_check.json', proof); cases.append(proof)
        if (not actual or not changed or not clean or result['timeout']
                or 'SCRIPT ERROR:' in (native/'engine.log').read_text()
                or (kind=='complete' and (missing or not execution['complete']))
                or (kind!='complete' and not missing)
                or (kind=='early_exit' and execution['complete'])):
            raise ValueError('Native draw fixture failed: '+str(case))
    value = dict(version=VERSION, accepted=True, production_bindings=bindings(),
        engine_sha256=sha(telemetry.binary(row)),
        evidence_bindings={str(p.resolve()):sha(p) for p in root.rglob('*') if p.is_file() and '.godot' not in p.parts},
        cases=cases, scoring_semantics_unchanged=True, original_adapter_pins_unchanged=True)
    runner.exclusive_json(path, value)
    return verify_acceptance(path)


def verify_parent(workspace, row, parent):
    result = runner.read(parent/'diagnostic_result.json')
    source = Path(result['source']).resolve()
    if (result.get('version') != telemetry.VERSION or result.get('diagnostic_only') is not True
            or result.get('root') != str(parent) or source.name != row['entry']['id']
            or row['entry']['actual_engine'] != 'godot' or not row['in_scope']):
        raise ValueError('Same frozen retained telemetry diagnostic required')
    telemetry.verify(result['evidence_bindings'])
    oldclaim = runner.read(source/'native_capture_telemetry_claim.json')
    if oldclaim.get('root') != str(parent) or sha(Path(oldclaim['repair'])) != oldclaim['repair_sha256']:
        raise ValueError('Retained diagnostic claim differs')
    telemetry.verify(oldclaim['parent_bindings'])
    batch.verify_inputs(source)
    if not scope.same_original(runner.read(source/'input_manifest.json')['entry'], row['entry']):
        raise ValueError('Frozen original source differs')
    native = parent/'take/runtime'
    process = runner.read(native/'process_cleanup.json')
    if not process.get('process_cleanup') or not process.get('view_cleanup') or process.get('timeout'):
        raise ValueError('Retained owned native cleanup required')
    logs = telemetry.read_rows(native/'capture_telemetry.jsonl')
    stalled = any(b['t_ms']-a['t_ms']>=900 and b['ticks']>a['ticks']
        and b['callbacks']==a['callbacks'] and b['engine_frames_drawn']==a['engine_frames_drawn']
        for a,b in zip(logs,logs[1:]))
    schedule = runner.read(parent/'plan.json')['native_capture_schedule']
    audit = sparse_evidence.audit_capture(native, schedule)
    if not stalled or not audit['missing_slots_ms']:
        raise ValueError('Actual stalled native draw and missing frozen screenshots required')
    return source


def verify_recovery_claim(workspace, row, diagnostic, result, *, recorded_bindings=None):
    parent = Path(result['parent_diagnostic']).resolve()
    source = verify_parent(workspace, row, parent)
    claim = runner.read(parent/CLAIM)
    repair = Path(claim['repair']); fix = runner.read(repair)
    effective=repair
    if result.get('admission_continuation'):
        effective=Path(result['admission_continuation'])
        fix=admission_continuation(parent,diagnostic,effective,recorded_bindings=recorded_bindings)
        receipt=runner.read(diagnostic/'native_draw_admission_continuation.json')
        if receipt.get('repair_sha256')!=sha(effective) or not receipt.get('no_native_started_before_continuation'):
            raise ValueError('Immutable admission-only receipt required')
    if (claim.get('version') != VERSION or claim.get('root') != str(diagnostic)
            or claim.get('maximum_attempts') != 1 or claim.get('source') != str(source)
            or sha(repair) != claim.get('repair_sha256')
            or result.get('repair_sha256') != sha(effective)
            or fix.get('production_bindings') != (bindings() if recorded_bindings is None else recorded_bindings)
            or fix.get('parent_diagnostic') != str(parent)
            or not fix.get('scoring_semantics_unchanged') or not fix.get('root_cause')
            or not fix.get('parent_bindings')):
        raise ValueError('Exact bounded native draw recovery claim required')
    telemetry.verify(fix['parent_bindings'])
    return source


def recover(workspace, row, parent, repair):
    parent, repair = Path(parent).resolve(), Path(repair).resolve()
    source = verify_parent(workspace, row, parent)
    accepted = verify_acceptance(acceptance_path(workspace))
    fix = runner.read(repair)
    resumed=(parent/CLAIM).exists()
    if resumed:
        claim=runner.read(parent/CLAIM);root=Path(claim['root'])
        fix=admission_continuation(parent,root,repair)
        if (root/'take/runtime').exists():
            raise ValueError('Native recovery already executed; reuse its immutable result')
        expected=dict(version=VERSION,repair=str(repair),repair_sha256=sha(repair),
            no_native_started_before_continuation=True,maximum_new_native_attempts=1)
        continuation=root/'native_draw_admission_continuation.json'
        if continuation.exists():
            if runner.read(continuation)!=expected: raise ValueError('Admission continuation already bound')
        else: runner.exclusive_json(continuation,expected)
    else:
        if (fix.get('classification') != 'BOUNDED_NATIVE_DRAW_RECOVERY'
                or fix.get('parent_diagnostic') != str(parent)
                or fix.get('source') != str(source) or fix.get('production_bindings') != (bindings() if recorded_bindings is None else recorded_bindings)
                or not fix.get('root_cause') or not fix.get('scoring_semantics_unchanged')
                or not fix.get('parent_bindings')):
            raise ValueError('Explicit substantive source-bound native draw repair required')
        telemetry.verify(fix['parent_bindings'])
        if any((workspace/'runs'/source.name/n).exists() for n in ('native_telemetry_reuse_claim.json','mechanic_score.json')):
            raise ValueError('Existing qualified/scored native stages must be reused')
        root = workspace/'engineering/native_draw_recovery'/source.name/sha(repair)
        runner.disk(workspace, 'native_draw_project', 2*1024**3)
        root.mkdir(parents=True, exist_ok=False)
        runner.exclusive_json(parent/CLAIM, dict(version=VERSION, source=str(source), root=str(root),
            repair=str(repair), repair_sha256=sha(repair), maximum_attempts=1,
            parent_diagnostic=str(parent), parent_bindings=fix['parent_bindings']))
        shutil.copytree(source/'input/project', root/'project', ignore=shutil.ignore_patterns('.godot'))
        shutil.copy2(parent/'plan.json', root/'plan.json')
    if sha(root/'plan.json') != sha(source/'runtime/recording_plan.json'):
        raise ValueError('Original native plan changed')
    try:
        result = take(workspace, row, root/'project', root/'plan.json', root/'take')
        batch.verify_inputs(source); telemetry.verify(fix['parent_bindings'])
        if batch.hashes(root/'project') != runner.read(source/'input_manifest.json')['snapshot_hashes']:
            raise ValueError('Author project changed')
        value = dict(version=VERSION, source=str(source), root=str(root), result=result,
            parent_diagnostic=str(parent), diagnostic_only=True, new_product_score=None,
            **(dict(admission_continuation=str(repair)) if resumed else {}),
            original_plan_actions_windows_unchanged=True,
            acceptance_sha256=accepted['sha256'], repair_sha256=sha(repair),
            evidence_bindings={str(p):sha(p) for p in (root/'take').rglob('*') if p.is_file()})
        runner.exclusive_json(root/'diagnostic_result.json', value)
        return value
    except Exception as error:
        failure_path=root/'failure.json'
        if failure_path.exists(): failure_path=root/'failures'/(str(time.time_ns())+'.json')
        dump(failure_path, dict(version=VERSION, error=repr(error), product_score=None,
            original_failed_evidence_preserved=True))
        raise
