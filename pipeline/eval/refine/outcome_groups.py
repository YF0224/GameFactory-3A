"""Opt-in grouped outcome evaluation of a frozen refined delivery.

A distinct user-authorized revision; legacy refine-tiered.v1 stays unchanged.
All groups share the original repair identity and production native lease.
"""
from pathlib import Path
import argparse
import json
import re
import shutil
import subprocess
import time

from .common import dump, read, sha, once, jsonl
from .session import inventory, snapshot
from .scoring import reference, static_credit
from .evaluation import source_bundle, REF
from . import evidence
from ..stage1.codex import call_codex, obj, arr, S, I, B, validate_schema
from ..stage1.endpoint_sparse import CAPTURE_VERSION
from engine_adapters.ue5.playtest import native_record

VERSION = 'refine.grouped-outcome-frame.v2'
PLAN = obj({'summary': S, 'steps': arr(obj({'id': S, 'key': S, 'duration_ms': {'type':'integer','minimum':1,'maximum':180000},
    'task_ids': arr(S), 'purpose': S})), 'observations': arr(obj({'after_step_id': S,
    'delay_ms': I, 'task_ids': arr(S), 'reason': S})),
    'uncovered': arr(obj({'task_id': S, 'reason': S}))})
JUDGE = obj({'checks': arr(obj({'task_id': S,
    'execution': {'type':'string','enum':['NORMAL','BUG','UNVERIFIED','HARNESS_ERROR']},
    'triggered': B, 'basic_function_normal': B, 'correct_target': B,
    'known_basic_bug': B, 'outcome_visible': B, 'image_numbers': arr(I),
    'state_event_refs': arr(REF), 'reason': S}))})
POLICY = ('Maximum proved tier, never additive: 10% valid authored source wired into gameplay; '
    '50% actually triggered basic function works for correct object, no known basic bug, outcome not fully proved; '
    '100% delivered real native image(s) and minimum necessary context clearly prove the core intent in goal. '
    'No-errors or absence of testing is not normal function. Exact milliseconds, durations, distances, speeds, '
    'numeric bonuses, all boundary/alternative branches are diagnostic only, never hidden gates. '
    'A clear single native result frame can suffice. Use minimal context for causality/temporal ambiguity, '
    'never require two frames or internal fields uniformly. Wrong object/information is a basic bug. '
    'Missing coverage is UNVERIFIED, not a product defect; HARNESS_ERROR has no product score. '
    'A correct refusal needs evidence the attempted operation was processed and correctly refused.')


def compile_route(plan, tasks, budget=180000):
    """Compile only encoded physical inputs and predeclared observation slots."""
    validate_schema(plan, PLAN)
    ids = {t['task_id'] for t in tasks}
    if not plan['steps'] or len(plan['steps']) > 120:
        raise ValueError('Local route needs 1..120 explicitly encoded steps')
    actions, by_id, elapsed = [], {}, 1800
    actions.append(dict(action='wait', duration_ms=1800, action_id='system/startup',
        probe_id='system', step_id='startup', criterion_ids=[], purpose='Native startup',
        expected_observation='Real game view', planned_t_ms=0, planned_end_t_ms=1800))
    for step in plan['steps']:
        ident = step['id']
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',ident) or ident in by_id:
            raise ValueError('Unique physical step ID required')
        if not set(step['task_ids']) <= ids or len(set(step['task_ids'])) != len(step['task_ids']):
            raise ValueError('Action references a task outside the frozen group')
        if not 1 <= step['duration_ms'] <= (10000 if step['key'] else budget):
            raise ValueError('Invalid physical duration')
        row = dict(action='key' if step['key'] else 'wait',duration_ms=step['duration_ms'],
            action_id='route/'+ident,probe_id='route',step_id=ident,criterion_ids=step['task_ids'],
            purpose=step['purpose'],expected_observation='Observe actual gameplay result',
            planned_t_ms=elapsed,planned_end_t_ms=elapsed+step['duration_ms'])
        if step['key']: row['key'] = step['key']
        actions.append(row); by_id[ident]=row;elapsed=row['planned_end_t_ms']
    if elapsed+1000 > budget:
        raise ValueError('Encoded local route exceeds recording budget')
    native_record.expand(actions)  # exact accepted native physical key/chord contract
    uncovered = [r['task_id'] for r in plan['uncovered']]
    if len(set(uncovered)) != len(uncovered) or not set(uncovered) <= ids or any(not r['reason'].strip() for r in plan['uncovered']):
        raise ValueError('Invalid uncovered task IDs/reasons')
    points,covered={},set()
    for obs in plan['observations']:
        action=by_id.get(obs['after_step_id'])
        targets=set(obs['task_ids'])
        if (not action or action['action']!='key' or not targets or not targets <= set(action['criterion_ids'])
                or not 0 <= obs['delay_ms'] <= budget or not obs['reason'].strip()):
            raise ValueError('Observation must bind an actual group-related physical input')
        at=action['planned_end_t_ms']+obs['delay_ms']
        if at+200 > elapsed:
            raise ValueError('Encode a final wait through every declared observation plus 200ms')
        row=points.setdefault(at,dict(at_ms=at,capture_ids=[],criterion_ids=[]))
        for ident in sorted(targets):
            if ident not in row['criterion_ids']:
                row['criterion_ids'].append(ident);row['capture_ids'].append('endpoint/'+ident)
        covered |= targets
    if covered.intersection(uncovered) or covered | set(uncovered) != ids:
        raise ValueError('Each frozen group task must have observations or an explicit coverage gap')
    times=sorted(points)
    if not times or len(times)>60 or any(b-a<200 for a,b in zip(times,times[1:])):
        raise ValueError('Need 1..60 real capture slots, distinct slots at least 200ms apart')
    schedule=dict(version=CAPTURE_VERSION,warmup_ms=1000,tolerance_ms=350,
        points=[points[t] for t in times],plan={'endpoints':{},'windows':[]})
    endpoints=[dict(task_id=t['task_id'],executable=t['task_id'] in covered,
        reason='Predeclared local outcome observations' if t['task_id'] in covered else next(r['reason'] for r in plan['uncovered'] if r['task_id']==t['task_id']),
        rubric_quote=t['goal'],visible_conditions=[t['goal']],nonvisual_conditions=[])
        for t in tasks]
    return actions,schedule,endpoints,elapsed+1000


def validate_local_plan(plan, tasks, budget):
    validate_schema(plan, PLAN)
    if not plan['steps'] and not plan['observations']:
        ids=[r['task_id'] for r in plan['uncovered']]
        if (len(ids)!=len(set(ids)) or set(ids)!={t['task_id'] for t in tasks}
                or any(not r['reason'].strip() for r in plan['uncovered'])):
            raise ValueError('Empty route must explain every frozen task coverage gap')
        return
    compile_route(plan,tasks,budget)


def settle_log(path, timeout=15):
    """Wait for inherited UE daemon stdout to close before freezing its bytes."""
    path=Path(path);deadline=time.monotonic()+timeout;last=None;stable=0
    while time.monotonic()<deadline:
        stat=path.stat();now=(stat.st_size,stat.st_mtime_ns)
        writers=subprocess.run(['lsof','-t',str(path)],capture_output=True,text=True)
        if writers.returncode not in (0,1):
            raise RuntimeError('Cannot verify native engine log writers')
        stable=stable+1 if now==last and not writers.stdout.strip() else 0
        if stable>=3:return {'path':str(path),'sha256':sha(path),'bytes':stat.st_size,'no_open_writers':True}
        last=now;time.sleep(.25)
    raise RuntimeError('HARNESS_ERROR: native engine log still has writers or changing bytes')


def score_check(row, code, *, native_input, image_numbers, refs_valid):
    """Evaluate only outcome tiers, independent of legacy full-spec gates."""
    harness=row['execution']=='HARNESS_ERROR'
    normal=(row['execution']=='NORMAL' and row['triggered'] and row['basic_function_normal']
        and row['correct_target'] and not row['known_basic_bug'] and native_input
        and refs_valid and (bool(image_numbers) or bool(row['state_event_refs'])))
    full=normal and row['outcome_visible'] and bool(image_numbers)
    credit=None if harness else 100 if full else 50 if normal else 10 if code else 0
    return dict(task_id=row['task_id'],credit_percent=credit,static_credit_percent=10 if code else 0,
        verdict='PASS' if full else 'FAIL' if row['execution']=='BUG' and row['known_basic_bug'] else 'UNVERIFIED',
        execution=row['execution'],reason=row['reason'],proof_gates=dict(native_input=native_input,
        delivered_images=image_numbers,refs_valid=refs_valid,basic_normal=bool(normal),outcome_proved=bool(full)),policy=VERSION)


def judge_result(folder, tasks, rows, codes, delivered):
    ids={t['task_id'] for t in tasks}
    if len(rows)!=len(ids) or {r['task_id'] for r in rows}!=ids:
        raise ValueError('Judge must cover exact frozen group IDs once')
    pictures={r['image_number']:r for r in delivered['images']}
    actual=[r for _,r in jsonl(Path(folder)/'background_record/take/actions.jsonl')]
    results=[]
    for row in rows:
        numbers=row['image_numbers']
        if len(set(numbers))!=len(numbers) or any(n not in pictures for n in numbers):
            raise ValueError('Judge cites a non-delivered native image')
        for n in numbers:
            if not ids.intersection(c.removeprefix('endpoint/').removeprefix('window/') for c in pictures[n].get('capture_ids',[])):
                raise ValueError('Judge cites an image outside its predeclared group observations')
        refs=row['state_event_refs']
        if not all(r['path'] in ('background_record/take/state_trace.jsonl','background_record/take/event_trace.jsonl')
                   and reference(folder,r) for r in refs):
            raise ValueError('Invalid physical native state/event reference')
        triggered=any(a.get('source')=='native_receiver' and a.get('phase')=='down'
            and row['task_id'] in a.get('criterion_ids',[]) for a in actual)
        results.append(score_check(row,codes[row['task_id']],native_input=triggered,image_numbers=numbers,refs_valid=True))
    return results


def refs(paths):
    return {name:{'path':str(path.resolve()),'sha256':sha(path)} for name,path in paths.items()}


def freeze_revision(parent, authorization):
    parent=Path(parent).resolve();authorization=Path(authorization).resolve();auth=read(authorization)
    paths={'tasks':parent/'input/tasks.json','source':parent/'input/source_manifest.json',
           'static':parent/'static.json','static_stage':parent/'stages/static.json',
           'admission':parent/'native_admission.json'}
    if auth['version']!=VERSION or auth['parents']!=refs(paths):
        raise ValueError('Outcome revision authorization does not bind preserved source/tasks/admission')
    if read(paths['static_stage'])['status']!='COMPLETE':raise ValueError('No completed source review')
    tasks=read(paths['tasks']);wanted=[t for t in tasks if t['kind'] in ('mechanic','gamefeel')]
    by_id={t['task_id']:t for t in wanted};grouped=[i for g in auth['groups'] for i in g['task_ids']]
    if len(grouped)!=len(set(grouped)) or set(grouped)!=set(by_id):
        raise ValueError('Group partition must preserve every mechanic and gamefeel ID exactly once')
    if any(not re.fullmatch(r'[a-z0-9_]{1,64}',g['id']) for g in auth['groups']) or len({g['id'] for g in auth['groups']})!=len(auth['groups']):
        raise ValueError('Group IDs must be unique contained names')
    groups=[dict(g,tasks=[by_id[i] for i in g['task_ids']]) for g in auth['groups']]
    revision={'version':VERSION,'policy':POLICY,'authorization':{'path':str(authorization),'sha256':sha(authorization)},
        'parents':auth['parents'],'groups':groups,'deferred_kinds':['vfx','import'],
        'source_identity':'Original final round_010 GLM candidate; ten repair rounds remain consumed',
        'repair_calls_added':0,'legacy_protocol':'refine-tiered.v1 preserved independently'}
    path=parent/'outcome_groups/revision.json'
    if path.exists():
        if read(path)!=revision:raise ValueError('Frozen grouped revision changed')
    else:dump(path,revision)
    return revision


def prepare_group(parent, group, revision):
    root=Path(parent)/'outcome_groups'/group['id'];root.mkdir(parents=True,exist_ok=True)
    def prepare():
        free=shutil.disk_usage(root).free
        manifest=read(Path(parent)/'input/source_manifest.json')['files']
        size=sum((Path(parent)/'input/project'/r).stat().st_size for r in manifest)
        if free<size+8*1024**3:raise RuntimeError('Snapshot requires 8GiB reserve')
        copied=snapshot(Path(parent)/'input/project',root/'input/project')
        if copied!=manifest:raise ValueError('Group snapshot differs from parent')
        dump(root/'input/source_manifest.json',{'files':copied})
        dump(root/'input/tasks.json',group['tasks'])
        dump(root/'native_admission.json',read(Path(parent)/'native_admission.json'))
        original=read(Path(parent)/'static.json')
        static={'checks':[r for r in original['checks'] if r['task_id'] in group['task_ids']]}
        if len(static['checks'])!=len(group['tasks']):raise ValueError('Incomplete reused static review')
        dump(root/'static.json',static)
        dump(root/'lineage.json',{'revision':{'path':str(Path(parent)/'outcome_groups/revision.json'),'sha256':sha(Path(parent)/'outcome_groups/revision.json')},'parent_bindings':revision['parents'],'group':group['id'],'reused_static':True,'new_static_model_calls':0,'repair_calls_added':0,'free_bytes':free,'snapshot_estimate_bytes':size})
        return {'folder':str(root)}
    once(root,'prepare',prepare)
    if inventory(root/'input/project')!=read(Path(parent)/'input/source_manifest.json')['files']:
        raise ValueError('Frozen group project changed')
    return root


def gameplay_source_bundle(root):
    root=Path(root)
    files=read(root/'input/source_manifest.json')['files']
    candidates={r:digest for r,digest in files.items() if
        r.startswith(('Source/DockBeacon/','Plugins/DockUI/Source/','Plugins/DockMechanic/Source/','Config/'))
        and Path(r).suffix.lower() in {'.cpp','.h','.ini'}}
    # Automation tests remain intact/readable, but are not runtime gameplay source.
    tests=[r for r in candidates if Path(r).stem.endswith('Tests')]
    authored={r:digest for r,digest in candidates.items() if r not in tests}
    for relative,digest in authored.items():
        if sha(root/'input/project'/relative)!=digest:
            raise ValueError('Authored source digest changed')
    bundle,delivery=source_bundle(root/'input/project',authored,limit=200000)
    if delivery['omitted'] or any(r['truncated'] for r in delivery['sent']):
        raise ValueError('All authored runtime game source must be delivered untruncated')
    delivery['nonruntime_test_files']=tests
    return bundle,delivery


def revalidate_saved_plan(root, tasks, budget):
    proof=read(Path(root)/'saved_plan_recovery.json')
    for key in ('authorization','stage','response'):
        ref=proof[key]
        if sha(ref['path'])!=ref['sha256']:
            raise ValueError('Saved plan recovery provenance changed')
    completed=Path(root)/'stages/plan_revalidated_001.json'
    if completed.exists() and read(completed)['status']=='COMPLETE':
        value=read(proof['response']['path']);validate_local_plan(value,tasks,budget)
        if read(completed)['result']!=value:raise ValueError('Revalidated saved plan changed')
        return value
    if read(proof['authorization']['path'])['implementation_sha256']!=sha(__file__):
        raise ValueError('Saved plan recovery implementation changed')
    def restore():
        value=read(proof['response']['path'])
        validate_local_plan(value,tasks,budget)
        dump(Path(root)/'plan.json',value)
        dump(Path(root)/'plan_revalidation_receipt.json',{
            'original_response':proof['response'],'original_failed_stage':proof['stage'],
            'model_calls_added':0,'action_changes':0,'timing_changes':0,
            'reason':'Native expand accepts positive millisecond inputs; remove undisclosed 25ms compiler minimum.'})
        return value
    return once(root,'plan_revalidated_001',restore)


def revalidate_saved_judge(root, tasks, codes, delivered):
    proof=read(root/'saved_judge_recovery.json')
    for key in ('authorization','stage','response','manifest','delivery'):
        ref=proof[key]
        if sha(ref['path'])!=ref['sha256']:raise ValueError('Saved judge recovery provenance changed')
    def restore():
        value=read(proof['response']['path']);validate_schema(value,JUDGE)
        judge_result(root,tasks,value['checks'],codes,delivered)
        dump(root/'judge.json',value)
        dump(root/'judge_revalidation_receipt.json',{'original_response':proof['response'],
            'original_failed_stage':proof['stage'],'model_calls_added':0,'recordings_added':0,
            'response_changes':0,'reason':'Same-group predeclared images may supply necessary shared causal context.'})
        return value
    return once(root,'judge_revalidated_001',restore)


def reference_retry_context(root):
    """Deliver exact failed physical rows; never rewrite or accept invalid refs."""
    proof=read(Path(root)/'judge_reference_recovery.json')
    for ref in proof.values():
        if sha(ref['path'])!=ref['sha256']:
            raise ValueError('Judge reference recovery provenance changed')
    raw=read(proof['response']['path']);lines=[]
    for row in raw['checks']:
        for ref in row['state_event_refs']:
            if reference(root,ref):continue
            path=ref['path']
            if path not in ('background_record/take/state_trace.jsonl','background_record/take/event_trace.jsonl'):
                raise ValueError('Reference correction cannot introduce a different evidence channel')
            native=Path(root)/path;physical=native.read_text().splitlines()
            if sha(native)!=ref['sha256'] or not 1<=ref['line']<=len(physical):
                raise ValueError('Reference correction requires exact SHA and existing physical line')
            lines.append(dict(path=path,sha256=sha(native),line=ref['line'],text=physical[ref['line']-1]))
    if not lines:raise ValueError('No invalid physical quote to correct')
    return ('\nPREVIOUS RESPONSE REJECTED: quote must be a literal nonempty substring of the original '
        'physical line, including original JSON whitespace. Wire JSON encoding is not the original spelling. '
        'Reevaluate the same evidence and return valid citations; do not assume previous conclusions. '
        'Short exact value tokens may be quoted when they identify the relevant fact. '
        'Original rejected response remains preserved. Exact failed native rows:\n'+json.dumps(lines,ensure_ascii=False))


def run_group(parent, group, revision, config):
    root=prepare_group(parent,group,revision);tasks=group['tasks']
    if (root/'result.json').exists():
        saved=read(root/'result.json')
        if (root/'evidence/manifest.json').exists():evidence.verify_manifest(root,read(root/'evidence/manifest.json'))
        return saved
    from .source_citations import normalize
    static=normalize(root,'static',read(root/'static.json'))
    dump(root/'static_normalized.json',static)
    codes={r['task_id']:static_credit(root/'input',r) for r in static['checks']}
    if group.get('blocked_reason'):
        result=dict(version=VERSION,status='BLOCKED_TRUE_MULTIPLAYER',group=group['id'],
            reason=group['blocked_reason'],checks=[dict(task_id=t['task_id'],credit_percent=None,
            static_credit_percent=10 if codes[t['task_id']] else 0,verdict='UNVERIFIED') for t in tasks])
        dump(root/'result.json',result);return result
    sol=config['sol'];budget=config.get('recording_ms',180000)
    bundle,source_delivery=gameplay_source_bundle(root)
    dump(root/'input/model_source_delivery.json',source_delivery)
    def invoke():
        prompt=('Plan ONLY this small frozen group through delivered author gameplay. Read Source/DockBeacon '
            'and Plugins/DockUI/Source under project. Start in a fresh title screen; actual default scene is empty. '
            'Do not implement gameplay or edit any files. No debug state writes, callbacks, OS input, fake peers, '
            'or engine invocation. Existing author single-client diagnostic entry may be used but is never real multiplayer. '
            'Encode actual physical keys and waits: key="" is wait; key strings lower-case letters/digits, enter, '
            'space, escape, tab, leftshift, lmb/rmb, left_arrow/right_arrow/up_arrow/down_arrow; chords joined +. '
            'Only choose keys verified in author source. F5 is unsupported; no invented substitute. '
            'Every step has unique id, positive integer duration_ms (key hold <=10000ms), related frozen task_ids and purpose; max 120 steps. '
            'The runner adds initial1800ms. observations.after_step_id must name an actual key input; '
            'delay_ms measured from its END in route clock. Declare the few real screenshots needed to prove the '
            'core outcome, e.g. before/after/context for firing or animation; no route-wide sampling. '
            'Distinct observation times >=200ms apart; <=60 total slots. Encode waits through the last observation+200ms. '
            'Keep route short, at most '+str(budget)+'ms including1800ms startup and1000ms exit. '
            'A task is either observed or listed uncovered with specific source-grounded reason. If none has a real route, return empty steps/observations and explain every task in uncovered. Partial route is valid; '
            'do not claim nonexistent steps. Steps may bind multiple related tasks and observations may share slots. '
            'Do not pad to maximum duration. '+POLICY+'\n'+json.dumps(tasks,ensure_ascii=False)+'\nAUTHOR SOURCE\n'+bundle)
        def valid(value):validate_local_plan(value,tasks,budget)
        value=call_codex(root,name='plan',prompt=prompt,schema=PLAN,model=sol['model'],
            executable=sol.get('executable','codex'),timeout=900,max_attempts=1,response_validator=valid,explicit_stdin_separator=True)
        dump(root/'plan.json',value);return value
    plan=(revalidate_saved_plan(root,tasks,budget) if (root/'saved_plan_recovery.json').exists()
          else once(root,'plan',invoke))
    if inventory(root/'input/project')!=read(Path(parent)/'input/source_manifest.json')['files']:
        raise ValueError('Source changed during group planning')
    if not plan['steps'] and not plan['observations']:
        result=dict(version=VERSION,status='SOURCE_ONLY_PENDING_RUNTIME',group=group['id'],
            checks=[dict(task_id=t['task_id'],credit_percent=10 if codes[t['task_id']] else 0,
                static_credit_percent=10 if codes[t['task_id']] else 0,verdict='UNVERIFIED',
                reason=next(r['reason'] for r in plan['uncovered'] if r['task_id']==t['task_id'])) for t in tasks],
            note='No physical route encoded; source credit only, no product bug or runtime success asserted.')
        dump(root/'result.json',result);return result
    actions,schedule,endpoints,duration=compile_route(plan,tasks,budget)
    dump(root/'native_actions.json',{'actions':actions});dump(root/'capture_schedule.json',schedule)
    def record():
        admitted=read(root/'native_admission.json');accept=read(admitted['native_acceptance'])
        if sha(admitted['native_acceptance'])!=admitted['native_acceptance_sha256'] or accept['pin_sha256']!=sha(admitted['pin']) or not accept['ok']:
            raise ValueError('Native acceptance changed')
        for path,digest in accept['files'].items():
            if sha(path)!=digest:raise ValueError('Native acceptance evidence changed')
        free=shutil.disk_usage(root).free
        if free<8*1024**3+512*1024**2:raise RuntimeError('Native recording requires 8GiB reserve')
        dump(root/'disk_before_record.json',{'free_bytes':free,'reserve_bytes':8*1024**3,'estimate_bytes':512*1024**2})
        take=root/'background_record/take'
        result=native_record.record(admitted,actions,schedule,take,duration)
        settled=settle_log(take/'engine.log');dump(root/'log_settle.json',settled)
        for name in ('verification.json','runner_exit.json','cleanup.json'):
            shutil.copy2(take/name,root/'background_record'/name)
        cleanup=read(take/'cleanup.json')
        if not all(cleanup.get(k) for k in ('input_cleanup_ok','view_cleanup_ok','process_cleanup_ok')):
            raise RuntimeError('Native cleanup incomplete')
        return result
    once(root,'record',record)
    manifest=once(root,'evidence',lambda:evidence.package(root,schedule))
    delivered=evidence.delivery(root,tasks,endpoints,manifest,{})
    dump(root/'evidence/judge_delivery.json',delivered)
    bundle,source_delivery=gameplay_source_bundle(root)
    dump(root/'evidence/judge_source_delivery.json',source_delivery)
    from .grouped_transport import prepare as prepare_transport
    wire=prepare_transport(root,delivered)
    transport_recovery=root/'judge_transport_recovery.json'
    reference_recovery=root/'judge_reference_recovery.json'
    judge_name=('judge_reference_001' if reference_recovery.exists() else
                'judge_transport_001' if transport_recovery.exists() else 'judge')
    correction=reference_retry_context(root) if reference_recovery.exists() else ''
    if transport_recovery.exists():
        proof=read(transport_recovery)
        for key,ref in proof.items():
            if sha(ref['path'])!=ref['sha256']:raise ValueError('Judge transport recovery provenance changed')
    def judge():
        prompt=('Evaluate ONLY these mechanic/gamefeel tasks under the NEW frozen outcome policy. '+POLICY+
            '\nTask goal defines core intent. Original pass_condition remains diagnostic for exact timings/numbers. '
            'Judge correct gameplay/UI object and meaning. UI success text alone cannot replace actual mechanic effect. '
            'Animations can prove visual gamefeel when their core intent is visible. No uniform state/event/log requirement. '
            'UNVERIFIED for not triggered or missing coverage. An empty image list cannot prove outcome_visible. '
            'Cite only actually delivered image_numbers and precise real state/event refs if used, never fabricate refs. '
            'Predeclared images from another task in this same group may provide necessary causal context. '
            'Local cwd is input; capture/evidence paths are in its parent. Return paths relative to group root. '
            'For state_event_refs quote a literal substring of the original physical line, preserving whitespace. '
            'Encoded wire rows may spell JSON differently; a short exact value token is sufficient. '
            'No edits or engine calls.\n'+wire+correction+'\nAUTHOR SOURCE\n'+bundle)
        def valid(value):judge_result(root,tasks,value['checks'],codes,delivered)
        value=call_codex(root,name=judge_name,prompt=prompt,schema=JUDGE,model=sol['model'],
            executable=sol.get('executable','codex'),images=[Path(r['path']) for r in delivered['images']],
            timeout=900,max_attempts=1,response_validator=valid,explicit_stdin_separator=True)
        dump(root/'judge.json',value);return value
    judged=(revalidate_saved_judge(root,tasks,codes,delivered) if (root/'saved_judge_recovery.json').exists()
            else once(root,judge_name,judge))
    if inventory(root/'input/project')!=read(Path(parent)/'input/source_manifest.json')['files']:
        raise ValueError('Source changed during group judging')
    evidence.verify_manifest(root,manifest)
    results=judge_result(root,tasks,judged['checks'],codes,delivered)
    result=dict(version=VERSION,status='SCORED_PENDING_AUDIT',group=group['id'],checks=results,
        revision_sha256=sha(Path(parent)/'outcome_groups/revision.json'),judge_sha256=sha(root/'judge.json'),
        native_evidence_sha256=sha(root/'evidence/manifest.json'),formal_whitebox_score=None,
        note='Independent new outcome revision; original attempt retained; no historical eight-column scores.')
    dump(root/'result.json',result)
    # Recompute deterministic evidence/source/input gates independently before audit status changes.
    if judge_result(root,tasks,read(root/'judge.json')['checks'],codes,delivered)!=results:
        raise ValueError('Independent recomputation differs')
    dump(root/'audit.json',{'status':'TECHNICAL_GATES_VERIFIED','semantic_audit':'PENDING',
        'result_sha256':sha(root/'result.json'),'policy':VERSION})
    return result


def authorize_preplan_recovery(parent, saved, authorization):
    """Bind packaging/validator repairs to preserved failures without resetting calls."""
    authorization=Path(authorization).resolve();auth=read(authorization)
    if auth['version']!='grouped-preplan-recovery.v1' or auth['implementation_sha256']!=sha(__file__):
        raise ValueError('Recovery must bind the repaired implementation')
    ref=auth['parent_report']
    if sha(ref['path'])!=ref['sha256']:
        raise ValueError('Recovery parent report changed')
    original=read(ref['path'])
    if original['version']!=VERSION or saved['version']!=VERSION:
        raise ValueError('Recovery protocol mismatch')
    allowed=auth['group_ids']
    if not allowed or len(set(allowed))!=len(allowed):
        raise ValueError('Explicit unique recovery groups required')
    binding={'path':str(authorization),'sha256':sha(authorization)}
    for ident in allowed:
        if not re.fullmatch(r'[a-z0-9_]{1,64}',ident):
            raise ValueError('Invalid recovery group')
        old=original['groups'][ident];current=saved['groups'][ident]
        saved_plan=auth.get('saved_plans',{}).get(ident)
        saved_judge=auth.get('saved_judges',{}).get(ident)
        retry_judge=auth.get('retry_judges',{}).get(ident)
        retry_reference=auth.get('retry_reference_judges',{}).get(ident)
        special=saved_plan or saved_judge or retry_judge or retry_reference
        expected=special['parent_error'] if special else auth['parent_error']
        if old['status']!='HARNESS_ERROR' or old.get('error')!=expected:
            raise ValueError('Recovery does not match the saved packaging/validation failure')
        root=Path(parent)/'outcome_groups'/ident
        receipt=root/'recoveries'/(binding['sha256']+'.json')
        contents={'authorization':binding,'parent_failure':old}
        if receipt.exists():
            if read(receipt)!=contents:raise ValueError('Conflicting recovery lineage')
            continue
        if current!=old:
            raise ValueError('Recovery requires the exact preserved parent failure')
        if saved_plan:
            for key in ('stage','response','invocation'):
                ref=saved_plan[key]
                if sha(ref['path'])!=ref['sha256']:
                    raise ValueError('Saved model response/failure changed')
            stage=read(saved_plan['stage']['path']);invocation=read(saved_plan['invocation']['path'])
            if (Path(saved_plan['stage']['path']).resolve()!=(root/'stages/plan.json').resolve()
                    or stage['status']!='ERROR' or stage.get('error')!=expected
                    or invocation.get('exit_code')!=0 or not invocation.get('response_present')):
                raise ValueError('Saved-plan recovery requires a completed model response and exact validator failure')
            if (root/'stages/record.json').exists() or (root/'plan.json').exists():
                raise ValueError('Saved-plan recovery cannot replace an executable plan or recording')
            value=read(saved_plan['response']['path'])
            validate_local_plan(value,read(root/'input/tasks.json'),auth['recording_ms'])
            dump(root/'saved_plan_recovery.json',{'authorization':binding,
                'stage':saved_plan['stage'],'response':saved_plan['response']})
        elif saved_judge or retry_judge or retry_reference:
            special=saved_judge or retry_judge or retry_reference
            for key,ref in special.items():
                if key=='parent_error':continue
                if sha(ref['path'])!=ref['sha256']:raise ValueError('Judge failure/evidence recovery binding changed')
            stage=read(special['stage']['path']);invocation=read(special['invocation']['path'])
            if (Path(special['stage']['path']).resolve()!=(root/'stages/judge.json').resolve()
                    or stage['status']!='ERROR' or stage.get('error')!=expected
                    or read(root/'stages/record.json')['status']!='COMPLETE'):
                raise ValueError('Judge recovery requires the preserved native record and exact failed stage')
            evidence.verify_manifest(root,read(special['manifest']['path']))
            if retry_reference:
                if (expected!='ValueError: Invalid physical native state/event reference'
                        or invocation.get('exit_code')!=0 or not invocation.get('response_present')
                        or Path(special['response']['path']).resolve()!=(root/'model_calls/judge/response.json').resolve()
                        or Path(special['manifest']['path']).resolve()!=(root/'evidence/manifest.json').resolve()
                        or Path(special['delivery']['path']).resolve()!=(root/'evidence/judge_delivery.json').resolve()):
                    raise ValueError('Reference retry requires the actual invalid response and unchanged evidence')
                validate_schema(read(special['response']['path']),JUDGE)
                dump(root/'judge_reference_recovery.json',dict(authorization=binding,**{
                    key:special[key] for key in ('stage','response','invocation','manifest','delivery')}))
                reference_retry_context(root)
            elif saved_judge:
                if invocation.get('exit_code')!=0 or not invocation.get('response_present'):
                    raise ValueError('Saved judge recovery requires an actual completed model response')
                validate_schema(read(special['response']['path']),JUDGE)
                dump(root/'saved_judge_recovery.json',dict(authorization=binding,**{
                    key:special[key] for key in ('stage','response','manifest','delivery')}))
            else:
                if (invocation.get('exit_code')!=1 or invocation.get('response_present')
                        or 'input_too_large' not in Path(special['stderr']['path']).read_text()):
                    raise ValueError('Transport recovery requires exact input-too-large failure without a response')
                dump(root/'judge_transport_recovery.json',dict(authorization=binding,**{
                    key:special[key] for key in ('stage','invocation','stderr','manifest','delivery')}))
        elif (root/'stages/plan.json').exists() or any((root/'model_calls').glob('*')):
            raise ValueError('Preplan recovery cannot reset an existing model attempt')
        dump(receipt,contents)
    return {ident for ident in allowed if saved['groups'][ident]==original['groups'][ident]}


def run(output, authorization, recovery=None):
    from .batch import exclusive,code_identity
    from .migration import verify_migration
    from ..stage1.engine_execution import lease
    output=Path(output).resolve();config=read(output/'configuration.json')
    with exclusive(output.parent/(output.name+'.batch.lock')):
        verify_migration(output,code_identity())
        inv=read(output/'inventory.json')
        if len(inv['games'])!=1 or inv['games'][0]['project']['engine']!='ue5':raise ValueError('Grouped runner requires frozen single UE candidate')
        parent=output/'games'/inv['games'][0]['game_id']
        revision=freeze_revision(parent,authorization)
        report=parent/'outcome_groups/report.json'
        saved=read(report) if report.exists() else {'version':VERSION,'groups':{},'deferred_kinds':['vfx','import']}
        recovered=authorize_preplan_recovery(parent,saved,recovery) if recovery else set()
        with lease(Path(config['unity']['control_root']),'ue5',output,
                   output/'engine_execution'/(str(time.time_ns())+'_outcome_groups.json'),policy=config['engine_execution_policy']):
            for group in revision['groups']:
                if (parent/'outcome_groups/stop_between_groups.json').exists():
                    print('Engineering stop requested at clean group boundary',flush=True)
                    break
                # Never repeat an unchanged tool failure. Other independent groups keep moving.
                prior=saved['groups'].get(group['id'],{})
                if prior.get('status')=='HARNESS_ERROR' and group['id'] not in recovered:continue
                try:
                    result=run_group(parent,group,revision,config)
                except Exception as exc:
                    result={'status':'HARNESS_ERROR','error':f'{type(exc).__name__}: {exc}',
                        'task_ids':group['task_ids'],'product_score':None,'next_action':'Preserve exact failed phase; source-bound engineering repair before any retry.'}
                saved['groups'][group['id']]=result
                saved['updated_unix']=time.time();dump(report,saved)
                print(json.dumps({'group':group['id'],'status':result['status'],'error':result.get('error')},ensure_ascii=False),flush=True)
                from ..stage1.engine_execution import check_idle,active_scope
                check_idle(active_scope())
    return saved


def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--authorization',type=Path,required=True)
    p.add_argument('--recovery',type=Path)
    a=p.parse_args(argv);run(a.output,a.authorization,a.recovery)

if __name__=='__main__':main()
