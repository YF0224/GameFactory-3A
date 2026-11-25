"""Independent VFX groups on an immutable final candidate, using refine-tiered.v1.

This does not extend the Mechanic/Gamefeel outcome policy to VFX. All native
windows, original conditions, deterministic evidence gates and audit remain.
"""
from pathlib import Path
import argparse
import json
import shutil
import time
from .common import read,dump,sha,once,jsonl
from .session import inventory,snapshot
from . import evidence,planning
from .evaluation import require_checks,JUDGE
from ..stage1.codex import call_codex
from .outcome_groups import gameplay_source_bundle,settle_log
from .grouped_transport import prepare as transport
from .source_citations import normalize
from .scoring import static_credit,score
from .ue_native import record as native_record
from .audit import audit

VERSION='refine.vfx-shared-preconditions.v1'


def recovery_authorization(root):
    """One explicit recovery retains the original failed model attempt and report."""
    path=Path(root)/'plan_recovery_authorization.json'
    if not path.exists():return None
    auth=read(path)
    if (auth.get('version')!='vfx-plan-producer-recovery.v1' or auth.get('model_calls_added')!=1
        or auth.get('root')!=str(Path(root).resolve()) or auth.get('stage')!='plan_recovery_001'):
        raise ValueError('Invalid VFX recovery authorization')
    expected={'failure':Path(root)/'stages/plan.json','response':Path(root)/'model_calls/plan/response.json',
              'invocation':Path(root)/'model_calls/plan/invocation.json','source':Path(root)/'input/source_manifest.json',
              'tasks':Path(root)/'input/tasks.json'}
    if set(auth['parents'])!=set(expected):raise ValueError('Incomplete VFX recovery parents')
    for name,path in expected.items():
        if auth['parents'][name]!=ref(path):raise ValueError('Changed VFX recovery parent: '+name)
    if read(expected['failure'])['status']!='ERROR':raise ValueError('VFX recovery requires preserved failed plan')
    for name in ('authorization','boundary','parent_report'):
        item=auth[name]
        if sha(item['path'])!=item['sha256']:raise ValueError('Changed VFX recovery engineering lineage')
    if read(auth['boundary']['path'])['status']!='OLD_WORKER_EXITED':raise ValueError('No VFX recovery boundary')
    return auth


def model(folder,stage,prompt,schema,config,*,images=(),validator=None):
    """Explicit stdin separator; one source-bound recovery; no hidden retries."""
    folder=Path(folder);sol=config['sol'];base='plan' if stage=='plan' else 'judge'
    auth=recovery_authorization(folder) if stage=='plan' else None
    actual_stage=auth['stage'] if auth else stage
    def invoke():
        if auth:
            failure=read(folder/'stages/plan.json')
            request=prompt+'\nPrevious saved plan was rejected: '+failure['error']+(
                '. Its endpoints cited non-existent muzzle/fire, head/fire and penetration/fire actions. '
                'Encode every declared input and final wait. Do not repeat the entry-only plan. '
                'Use 1..10 probes with <=24 steps each. A long wait can be one <=6000ms step; '
                'do not pad with many tiny waits. Only genuinely uncovered tasks may be executable=false.')
        else:request=prompt
        try:
            value=call_codex(folder,name=actual_stage,prompt=request,schema=schema,model=sol['model'],
                executable=sol.get('executable','codex'),images=images,
                timeout=sol.get('timeouts',{}).get(base,1800 if base=='plan' else 900),
                max_attempts=1,response_validator=validator,explicit_stdin_separator=True)
        finally:
            call=folder/'model_calls'/actual_stage
            if (call/'prompt.txt').exists():
                delivery={'stage':actual_stage,'request':ref(call/'prompt.txt'),'schema':ref(call/'schema.json'),
                    'sources':read(folder/'input/model_source_delivery.json'),
                    'images':[dict(image_number=i+1,**ref(p)) for i,p in enumerate(images)],
                    'repair_calls_added':0,'max_attempts':1}
                for name in ('response.json','invocation.json'):
                    if (call/name).exists():delivery[name]=ref(call/name)
                dump(call/'actual_delivery.json',delivery)
        dump(folder/(actual_stage+'.json'),value)
        return value
    value=once(folder,actual_stage,invoke)
    if auth:dump(folder/'plan.json',value)
    return normalize(folder,stage,value) if stage.startswith('judge_') else value


def plan_schema(root,budget):
    """Bind immutable admission metadata at the producer; original validator stays."""
    value=planning.schema('ue5',budget);fields=value['properties']['native_plan']['properties']
    for name,literal in [('engine','ue5'),('launch_scene',''),('launch_source',Path(read(Path(root)/'native_admission.json')['uproject']).name)]:
        fields[name]={'type':'string','enum':[literal]}
    from ..stage1.runtime import NATIVE_KEYS
    import re
    step=fields['probes']['items']['properties']['steps']['items']['properties']
    token='(?:'+'|'.join(re.escape(k) for k in sorted(NATIVE_KEYS))+')'
    step['key']={'type':'string','pattern':'^(?:'+token+'(?:\\+'+token+'){0,2})?$'}
    step['kind']={'type':'string','enum':['input','wait']}
    step['duration_ms']={'type':'integer','minimum':1,'maximum':6000}
    return value


def ref(p):
    p=Path(p).resolve()
    return {'path':str(p),'sha256':sha(p)}


def validate_reuse(parent):
    """Compare authored candidate to the built runtime, allowing only pinned overlays."""
    from engine_adapters.ue5.playtest.native_record import verify_pin
    parent=Path(parent);files=read(parent/'input/source_manifest.json')['files']
    if inventory(parent/'input/project')!=files:raise ValueError('Frozen candidate changed')
    admitted=read(parent/'native_admission.json');verify_pin(admitted)
    accepted=read(admitted['native_acceptance'])
    if (sha(admitted['native_acceptance'])!=admitted['native_acceptance_sha256']
        or not accepted['ok'] or accepted['pin_sha256']!=sha(admitted['pin'])):
        raise ValueError('Native reuse acceptance/pin mismatch')
    for p,d in accepted['files'].items():
        if sha(p)!=d:raise ValueError('Native acceptance evidence changed')
    overlay=read(parent/'ue_adapter_overlay.json')
    if overlay['frozen_source_manifest']!=files:raise ValueError('Runtime overlay uses different candidate')
    changes={r['path']:r for r in overlay['overlays']}
    for rel,digest in files.items():
        # Build products and the recorder's append-only runtime outputs are not authored inputs.
        # Their native executable identities are verified independently by verify_pin above.
        if any(part in {'Binaries','Intermediate','Saved','DerivedDataCache','Logs'} for part in Path(rel).parts):
            continue
        expected=digest
        if rel in changes:
            row=changes[rel]
            if row['before_sha256']!=digest or sha(row['formal_source'])!=row['after_sha256']:
                raise ValueError('Native overlay mismatch')
            expected=row['after_sha256']
        if sha(Path(admitted['project'])/rel)!=expected:raise ValueError('Runtime differs from frozen candidate: '+rel)
    original=read(parent/'original_project.json')
    if inventory(original['root'])!=original['files']:raise ValueError('Original author delivery changed')
    return admitted


def freeze_revision(parent,game):
    root=Path(parent)/'vfx_groups';tasks=planning.task_specs({**game,'repairs':[r for r in game['repairs'] if r['selection_kind']=='vfx'],'imports':[]})
    if len(tasks)!=5:raise ValueError('Expected five frozen G008 VFX tasks')
    groups=[]
    for name,selection in [('firing',[t for t in tasks if any('.'+n+'.' in t['task_id'] for n in ['0009','0011','0012'])]),
                           ('smoke',[t for t in tasks if '.0016.' in t['task_id']]),
                           ('environment',[t for t in tasks if '.environment.' in t['task_id']])]:
        if not selection:raise ValueError('Empty VFX group')
        groups.append({'id':name,'tasks':selection})
    if [t for g in groups for t in g['tasks']]!=tasks:raise ValueError('VFX grouping changed frozen task order or scope')
    revision={'version':VERSION,'scoring_policy':'refine-tiered.v1','groups':groups,
        'parent_source_manifest':ref(Path(parent)/'input/source_manifest.json'),
        'parent_static':ref(Path(parent)/'static.json'),'parent_tasks':ref(Path(parent)/'input/tasks.json'),
        'new_repair_calls':0,'imports':'deferred','outcome_policy':'Mechanic/Gamefeel only; not applied here'}
    path=root/'revision.json'
    if path.exists() and read(path)!=revision:raise ValueError('VFX revision changed')
    dump(path,revision);return revision


def prepare_group(parent,group):
    parent=Path(parent);root=parent/'vfx_groups'/group['id']
    def prepare():
        admitted=validate_reuse(parent)
        files=read(parent/'input/source_manifest.json')['files']
        size=sum((parent/'input/project'/p).stat().st_size for p in files)
        free=shutil.disk_usage(parent).free
        if free<size+8*1024**3:raise RuntimeError('VFX snapshot needs 8GiB reserve')
        if snapshot(parent/'input/project',root/'input/project')!=files:raise ValueError('VFX snapshot changed')
        dump(root/'input/source_manifest.json',{'files':files});dump(root/'input/tasks.json',group['tasks'])
        dump(root/'native_admission.json',admitted);dump(root/'original_project.json',read(parent/'original_project.json'))
        ids={t['task_id'] for t in group['tasks']}
        static={'checks':[r for r in read(parent/'static.json')['checks'] if r['task_id'] in ids]}
        require_checks(static,group['tasks']);dump(root/'static.json',static)
        dump(root/'reference_renders.json',{})
        dump(root/'lineage.json',{'revision':ref(parent/'vfx_groups/revision.json'),
            'source':ref(parent/'input/source_manifest.json'),'reused_static':ref(parent/'static.json'),
            'reused_admission':ref(parent/'native_admission.json'),'pin':ref(admitted['pin']),
            'acceptance':ref(admitted['native_acceptance']),'free_bytes':free,'snapshot_bytes':size,
            'repair_calls_added':0,'static_calls_added':0,'new_native_acceptance':False})
        return {'folder':str(root)}
    once(root,'prepare',prepare)
    validate_reuse(parent)
    if inventory(root/'input/project')!=read(parent/'input/source_manifest.json')['files']:raise ValueError('VFX input changed')
    return root


def run_group(parent,group,game,config):
    root=prepare_group(parent,group);tasks=group['tasks']
    if (root/'result.json').exists():
        saved=read(root/'result.json');audit(root,game,saved['checks'],judge_stages=['judge_001']);return saved
    static=normalize(root,'static',read(root/'static.json'))
    codes={r['task_id']:static_credit(root/'input',r) for r in static['checks']}
    bundle,delivery=gameplay_source_bundle(root);dump(root/'input/model_source_delivery.json',delivery)
    admitted=read(root/'native_admission.json');budget=config.get('recording_ms',180000)
    prompt=('Return only the executable JSON; all author source is delivered below. Do not invoke tools. '
        'Native engine=ue5, launch_source=DockBeacon.uproject exactly, launch_scene empty. '
        'Use at most10 probes and24 steps per probe, each wait/input <=6000ms. '
        'Use a few ordinary long waits; do not pad to24 steps. '
        'Plan ONLY these frozen VFX tasks through original author gameplay, no edits or engine calls. '
        'Start fresh title. Enter uses title-to-room; read real source for the subsequent original entry. '
        'Single-client diagnostic entry never proves true multiplayer. No fabricated events, callbacks, source changes, '
        'OS input or inferred mouse support. Supported only canonical native key chords/wait; uppercase letters/digits, '
        'Enter,Space,Escape,Shift,Tab,Left,Right,Up,Down. '
        'Function keys are unsupported; never invent substitutes. Local partial route is enough; mark genuinely '
        'unreachable items executable=false with reason, empty last_action_id and at_ms=0. Every task exactly once. '
        'Native plan watchers=[]; state_channel=adapter_discovery. Task criterion_ids must be on relevant real input. '
        'last_action_id=probeID/stepID identifies its LAST non-wait task input. Initial1800ms added by native_actions. '
        'Endpoint at_ms >= input planned_end_t_ms+stable_after_ms, stable_after_ms>=150. '
        'Declare continuous window600..4000ms sampled every200ms, beginning no earlier than real trigger start, '
        'ending no later than endpoint. Do not insist on entire game completion; task failures are valid evidence. '
        'Predeclare actual trigger/effect/recovery window, no blind route-wide capture. Reserve explicit wait through '
        'last endpoint+200ms; set max_duration_ms>=last endpoint+1000ms and >=sum(step durations)+2500ms. '
        'Step IDs globally unique, no key input hidden in prose. Identical sample times merge; distinct times>=100ms. rubric_quote literal substring '
        'of original pass_condition. launch_scene must stay empty. Encoded total budget '+str(budget)+'ms.\n'
        +json.dumps({'tasks':tasks,'static':static,'launch_scene':admitted['scene']},ensure_ascii=False)
        +'\nAUTHOR SOURCE\n'+bundle)
    def valid_plan(value):
        if value['native_plan']['launch_scene']!=admitted['scene']:raise ValueError('VFX launch scene changed')
        actions,schedule=planning.compile_plan(value,root/'input/project','ue5',tasks,budget,root/'capture_schedule.json')
        from engine_adapters.ue5.playtest.native_record import expand
        expand(actions)
    plan=model(root,'plan',prompt,plan_schema(root,budget),config,validator=valid_plan)
    actions,schedule=planning.compile_plan(plan,root/'input/project','ue5',tasks,budget,root/'capture_schedule.json')
    dump(root/'native_actions.json',{'actions':actions})
    def record():
        free=shutil.disk_usage(root).free
        estimate=max(512*1024**2,len(schedule['points'])*1280*720*4*2)
        dump(root/'disk_before_record.json',{'free_bytes':free,'estimate_bytes':estimate,'reserve_bytes':8*1024**3})
        if free<estimate+8*1024**3:raise RuntimeError('VFX record needs 8GiB reserve')
        validate_reuse(parent)
        result=native_record(root,plan,schedule,config)
        settle_log(root/'background_record/take/engine.log')
        return result
    once(root,'record',record)
    manifest=once(root,'evidence',lambda:evidence.package(root,schedule))
    delivered=evidence.delivery(root,tasks,plan['endpoints'],manifest,{})
    dump(root/'evidence/judge_001_delivery.json',delivered)
    dump(root/'evidence/judge_delivery.json',delivered)
    dump(root/'evidence/judge_source_delivery.json',delivery)
    wire=transport(root,delivered)
    prompt=('Judge ONLY these frozen VFX tasks under their ORIGINAL refine-tiered.v1 conditions. '
        'Mechanic/Gamefeel outcome relaxation is NOT applicable. Use all delivered continuous native window frames. '
        'Actual legal fire, head hit, penetration, smoke or lightning must be established for the correct object. '
        'NORMAL requires actually triggered working basic functionality, real native input, state/event change and normal logs; '
        'no-errors alone is insufficient. PASS/all_conditions_met require original endpoint and nonvisual conditions, '
        'including original lifecycle constraints; retain NORMAL when full rubric remains UNVERIFIED. '
        'Missing coverage is UNVERIFIED, not a product BUG. HARNESS_ERROR has no product zero. '
        'Exact physical state/event/log references path/SHA/line/quote, and actual delivered image numbers only. '
        'Quote a literal substring of ORIGINAL physical line, preserving whitespace. A short exact value token is valid. '
        'Encoded transport may spell JSON differently. The input cwd parent is the group root; return paths relative to '
        'group root without ../. No edits, engine calls or synthetic evidence.\n'+wire+'\nAUTHOR SOURCE\n'+bundle)
    def valid_judge(value):
        require_checks(value,tasks)
        # Physical references remain strict. Semantic failure/uncovered is valid evidence.
        from .scoring import reference
        for row in value['checks']:
            for cite in row['state_event_refs']+row['log_refs']:
                if not reference(root,cite):raise ValueError('Invalid literal VFX physical citation')
            if any(n not in {i['image_number'] for i in delivered['images']} for n in row['image_numbers']):raise ValueError('Undelivered VFX image')
    judged=model(root,'judge_001',prompt,JUDGE,config,images=[Path(r['path']) for r in delivered['images']],validator=valid_judge)
    evidence.verify_manifest(root,manifest)
    endpoints={e['task_id']:e for e in plan['endpoints']}
    scored=[score(row,codes[row['task_id']],evidence.proof(root,row,endpoints[row['task_id']],manifest,None,delivered),needs_window=True) for row in judged['checks']]
    audit(root,game,scored,judge_stages=['judge_001'])
    result={'version':VERSION,'group':group['id'],'status':'SCORED_PENDING_AUDIT','checks':scored,
        'source':ref(root/'input/source_manifest.json'),'judge':ref(root/'judge_001.json'),
        'native_evidence':ref(root/'evidence/manifest.json'),'technical_audit':ref(root/'independent_audit.json'),
        'semantic_audit':'PENDING','scoring_policy':'refine-tiered.v1','formal_whitebox_score':None}
    dump(root/'result.json',result);return result


def run(output):
    from .batch import exclusive,code_identity
    from .migration import verify_migration
    from ..stage1.engine_execution import lease,check_idle,active_scope
    output=Path(output).resolve();config=read(output/'configuration.json')
    with exclusive(output.parent/(output.name+'.batch.lock')):
        verify_migration(output,code_identity());inv=read(output/'inventory.json')
        if len(inv['games'])!=1 or inv['games'][0]['game_id']!='G008_dock_beacon_cs':raise ValueError('Only final G008 is authorized')
        game=inv['games'][0];parent=output/'games'/game['game_id'];revision=freeze_revision(parent,game)
        root=parent/'vfx_groups';report=read(root/'report.json') if (root/'report.json').exists() else {'version':VERSION,'groups':{},'imports':'deferred'}
        with lease(Path(config['unity']['control_root']),'ue5',output,
            output/'engine_execution'/(str(time.time_ns())+'_vfx_groups.json'),policy=config['engine_execution_policy']):
            for group in revision['groups']:
                if (root/'stop_between_groups.json').exists():break
                if report['groups'].get(group['id'],{}).get('status')=='HARNESS_ERROR':
                    if recovery_authorization(root/group['id']) is None:continue
                try:result=run_group(parent,group,game,config)
                except Exception as exc:
                    result={'status':'HARNESS_ERROR','error':f'{type(exc).__name__}: {exc}',
                        'task_ids':[t['task_id'] for t in group['tasks']],'product_score':None,
                        'next_action':'Source-bound engineering repair; preserve phase, requests and native records.'}
                report['groups'][group['id']]=result;report['updated_unix']=time.time();dump(root/'report.json',report)
                print(json.dumps({'group':group['id'],'status':result['status'],'error':result.get('error')},ensure_ascii=False),flush=True)
                check_idle(active_scope())
    return report


def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    run(parser.parse_args(argv).output)

if __name__=='__main__':main()
