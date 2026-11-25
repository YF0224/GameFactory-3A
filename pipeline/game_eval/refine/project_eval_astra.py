"""Explicitly authorized Astra whole-project reassessment; prior runs stay immutable.

Reuses formal native planning, recording, evidence and scoring. No old verdicts
are inherited. Qwen supplies acoustic observations, Astra makes every final
semantic judgment. This entry is opt-in and does not change legacy defaults.
"""
from pathlib import Path
import argparse
import copy
import json
import shutil
import time

from .common import read, dump, sha, once
from .session import snapshot, inventory
from .vfx_groups import ref, validate_reuse
from .evaluation import STATIC, JUDGE as VFX_JUDGE, require_checks
from .scoring import reference, static_credit, score
from .outcome_groups import gameplay_source_bundle, JUDGE as OUTCOME_JUDGE, POLICY, judge_result
from .project_eval import plan_project, record_project
from .project_eval_judge import (APPEARANCE_JUDGE, APPEARANCE_POLICY, checked_appearance,
    freeze_contract, delivery_with_context, save_delivery, invoke, audio_judge,
    normalize_appearance_paths)
from . import evidence
from ..whitebox_eval.codex import call_codex, obj, arr, S, B

VERSION = 'refine.astra-whole-project-reevaluation.v1'
MODEL = 'gpt-6-astra'
AUDIO_JUDGE = obj({'checks': arr(obj({'task_id': S, 'confirmed': B,
    'observation_paths': arr(S), 'reason': S}))})


def configuration(output, root):
    policy = read(root/'policy.json')
    if (policy['version'] != VERSION or policy['output'] != str(output)
            or policy['root'] != str(root) or root.parent != output/'games/G008_dock_beacon_cs'
            or policy['planner_model'] != MODEL or policy['judge_model'] != MODEL
            or policy['plan_timeout_seconds'] != 1800 or policy['recording_ms'] != 300000
            or policy['reuse_old_verdicts'] is not False):
        raise ValueError('Explicit Astra reassessment policy required')
    for name in ('configuration', 'inventory', 'authorization', 'parent_result', 'parent_publication'):
        if ref(policy[name]['path']) != policy[name]:
            raise ValueError('Reassessment binding changed: '+name)
    config = copy.deepcopy(read(output/'configuration.json'))
    config['sol'].update(model=MODEL)
    config['sol']['timeouts'] = {**config['sol'].get('timeouts', {}), 'judge': 1800}
    return policy, config


def prepare(parent, root, policy):
    def freeze():
        validate_reuse(parent)
        files = read(parent/'input/source_manifest.json')['files']
        size = sum((parent/'input/project'/p).stat().st_size for p in files)
        if shutil.disk_usage(root).free < size+8*1024**3:
            raise RuntimeError('Source freeze requires 8GiB reserve')
        if snapshot(parent/'input/project', root/'input/project') != files:
            raise ValueError('Astra source snapshot differs')
        for name in ('input/source_manifest.json','input/tasks.json','native_admission.json','original_project.json'):
            target = root/name; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(parent/name, target)
        dump(root/'reference_renders.json', {})
        dump(root/'reused_results.json', {})
        dump(root/'revision.json', {'version':VERSION, 'policy':ref(root/'policy.json'),
            'source':ref(parent/'input/source_manifest.json'), 'tasks':ref(parent/'input/tasks.json'),
            'old_results_preserved':True, 'old_verdicts_reused':0, 'repair_calls_added':0,
            'scoring':'Mechanic/Gamefeel outcome v2; VFX original refine-tiered.v1; import appearance v1'})
        return {'root':str(root), 'reused_verdicts':0}
    once(root, 'prepare', freeze)
    validate_reuse(parent)
    if inventory(root/'input/project') != read(parent/'input/source_manifest.json')['files']:
        raise ValueError('Frozen author source changed')


def normalized_static(root, value, tasks):
    require_checks(value, tasks)
    value = copy.deepcopy(value)
    mappings = []
    for row in value['checks']:
        for key in ('implementation_refs','entry_refs'):
            normalized, changes = normalize_appearance_paths({'checks':[{'implementation_refs':row[key]}]}, root)
            row[key] = normalized['checks'][0]['implementation_refs']; mappings.extend(changes)
        if row['implemented'] and not static_credit(root/'input',row):
            raise ValueError('Implemented claim lacks wired valid authored source')
    return value, mappings


def static_review(root, config):
    tasks = read(root/'input/tasks.json'); bundle, delivery = gameplay_source_bundle(root)
    dump(root/'input/model_source_delivery.json', delivery)
    prompt = ('Read ALL frozen tasks and all supplied authored runtime source. Independently assess whether each '
        'requested feature/asset is implemented AND wired into actual gameplay. Do not inherit any previous scores. '
        'Names/comments/placeholders alone are insufficient. Cite exact FILE project/... paths, original SHA, '
        'physical line and literal whitespace-preserving substring. Never invent a payload. No tools/edits/launch. '
        'Return only exact JSON schema.\nTASKS\n'+json.dumps(tasks,ensure_ascii=False)+
        '\nAUTHOR SOURCE\n'+bundle+'\nEXACT SCHEMA\n'+json.dumps(STATIC))
    def valid(value): normalized_static(root,value,tasks)
    def call():
        value=call_codex(root,name='static_astra',prompt=prompt,schema=STATIC,model=MODEL,
            executable=config['sol'].get('executable','codex'),timeout=1800,max_attempts=2,
            response_validator=valid,explicit_stdin_separator=True)
        dump(root/'static_astra_raw.json',value)
        return value
    raw=once(root,'static_astra',call); value,mappings=normalized_static(root,raw,tasks)
    dump(root/'static.json',value);dump(root/'static_path_mappings.json',mappings)
    return value



def effective_static(root):
    """Use only source-bound independent Astra source-tier corrections."""
    path = root/'effective_static.json'
    if not path.exists():
        return read(root/'static.json')
    receipt = read(root/'source_tier_recovery_receipt.json')
    for key in ('original_static', 'source', 'tasks', 'correction', 'effective_static'):
        item = receipt[key]
        if ref(item['path']) != item:
            raise ValueError('Source tier recovery provenance changed: '+key)
    if (receipt['original_static'] != ref(root/'static.json') or receipt['source'] != ref(root/'input/source_manifest.json')
            or receipt['tasks'] != ref(root/'input/tasks.json') or receipt['model'] != MODEL):
        raise ValueError('Source tier recovery does not bind this author source')
    original = read(root/'static.json')
    correction = read(receipt['correction']['path'])
    normalized, _ = normalized_static(root, correction,
        [t for t in read(root/'input/tasks.json') if t['task_id'] in receipt['corrected_task_ids']])
    by_id = {r['task_id']: r for r in normalized['checks']}
    merged = {'checks': [by_id.get(r['task_id'], r) for r in original['checks']]}
    if read(path) != merged:
        raise ValueError('Effective static is not the exact source-tier merge')
    return merged


def recover_source_tier(root, config):
    """Correct existence-tier prompt contamination without repeating runtime stages."""
    authorization = read(root/'source_tier_recovery.json')
    for key in ('original_static', 'source', 'tasks', 'parent_result', 'authorization'):
        item = authorization[key]
        if ref(item['path']) != item:
            raise ValueError('Source recovery parent changed: '+key)
    if (authorization['implementation_sha256'] != sha(__file__) or
            authorization['original_static'] != ref(root/'static.json') or
            authorization['source'] != ref(root/'input/source_manifest.json') or
            authorization['tasks'] != ref(root/'input/tasks.json')):
        raise ValueError('Source recovery implementation/identity changed')
    original = read(root/'static.json')
    negative = {r['task_id'] for r in original['checks'] if not r['implemented']}
    tasks = [t for t in read(root/'input/tasks.json') if t['kind'] in ('mechanic','gamefeel','vfx') and t['task_id'] in negative]
    if sorted(t['task_id'] for t in tasks) != authorization['task_ids']:
        raise ValueError('Recovery must retain the exact affected source-tier identities')
    bundle, delivery = gameplay_source_bundle(root)
    prompt = ('Independently assess ONLY the source-existence 10% floor for every frozen task below. '
        'implemented=true means actual author implementation of the core task intent is wired into gameplay. '
        'It does NOT mean full_requirement, PASS, runtime success, no bugs, full lifecycle, all branches, '
        'exact numeric/timing/space requirements, multiplayer coverage or imported payload fidelity are proved. '
        'For example connected rescue code can establish source existence even if rescue has a defect; '
        'connected lightning or gunshot effects can establish existence despite missing lifecycle cleanup. '
        'A known defect must remain diagnostic; it does not erase existing connected author code. '
        'Only names, comments, placeholders, disconnected code, wholly wrong behavior or absent implementation '
        'do not establish existence. Do not award runtime 50/100 or infer runtime success. '
        'Use exact FILE project/... path, SHA, physical line and literal substring for implementation and entry. '
        'Explain existence separately from limitations. Return only exact JSON schema. No tools/edits/launch. '
        '\nFROZEN TASKS\n'+json.dumps(tasks,ensure_ascii=False)+'\nAUTHOR SOURCE\n'+bundle+
        '\nEXACT SCHEMA\n'+json.dumps(STATIC))
    def validator(value): normalized_static(root,value,tasks)
    def invoke_correction():
        value = call_codex(root,name='static_source_tier_recovery',prompt=prompt,schema=STATIC,model=MODEL,
            executable=config['sol'].get('executable','codex'),timeout=900,max_attempts=2,
            response_validator=validator,explicit_stdin_separator=True)
        dump(root/'static_source_tier_recovery_raw.json',value)
        return value
    corrected = once(root,'static_source_tier_recovery',invoke_correction)
    corrected, mappings = normalized_static(root,corrected,tasks)
    dump(root/'static_source_tier_recovery.json',corrected)
    dump(root/'static_source_tier_recovery_path_mappings.json',mappings)
    by_id={r['task_id']:r for r in corrected['checks']}
    merged={'checks':[by_id.get(r['task_id'],r) for r in original['checks']]}
    dump(root/'effective_static.json',merged)
    dump(root/'source_tier_recovery_receipt.json',{
        'model':MODEL,'original_static':ref(root/'static.json'), 'source':ref(root/'input/source_manifest.json'),
        'tasks':ref(root/'input/tasks.json'),'correction':ref(root/'static_source_tier_recovery.json'),
        'effective_static':ref(root/'effective_static.json'),'corrected_task_ids':sorted(by_id),
        'authorization':ref(root/'source_tier_recovery.json'),
        'semantics':'Existing connected implementation establishes 10% floor; runtime and VFX scoring unchanged',
        'runtime_calls_added':0,'recording_ms_added':0,'plan_budget_reset':False})
    effective_static(root)
    return merged


def shards(root, tasks, plan, manifest, references=None, context=None):
    groups=[]; current=[]
    for task in tasks:
        trial=current+[task]
        try: delivery_with_context(root,trial,plan,manifest,references or {},context or [])
        except ValueError as exc:
            if '100 actual images' not in str(exc) or not current: raise
            groups.append(current); current=[task]
            delivery_with_context(root,current,plan,manifest,references or {},context or [])
        else: current=trial
    if current: groups.append(current)
    return groups


def evaluate(parent,root,config):
    from .ue_cleanup import verify
    verify(root);validate_reuse(parent)
    tasks=read(root/'input/tasks.json'); plan=read(root/'plan.json'); manifest=read(root/'evidence/manifest.json')
    evidence.verify_manifest(root,manifest);freeze_contract(parent,root)
    endpoints={e['task_id']:e for e in plan['endpoints']}
    static = effective_static(root)
    codes={r['task_id']:static_credit(root/'input',r) for r in static['checks']}
    bundle,source_delivery=gameplay_source_bundle(root)
    result={'version':VERSION,'status':'IN_PROGRESS','checks':[], 'planner_model':MODEL,'judge_model':MODEL,
        'source':ref(root/'input/source_manifest.json'),'plan':ref(root/'plan.json'),
        'native_evidence':ref(root/'evidence/manifest.json'),'policy':ref(root/'policy.json'),
        'semantic_audit':'PENDING','official_whitebox_total':None,'reused_completed':0,
        'static_assessment':ref(root/('effective_static.json' if (root/'effective_static.json').exists() else 'static.json'))}
    def persist():
        result.update(completed_tasks=len(result['checks']),total_tasks=len(tasks),updated_unix=time.time())
        dump(root/'result.json',result)
    def attempt(stage,selection,operation):
        try:return operation()
        except Exception as exc:
            failure={'status':'HARNESS_ERROR','stage':stage,'error':f'{type(exc).__name__}: {exc}',
                'product_score':None,'last_qualified_stage':'RECORD_EVIDENCE_COMPLETE',
                'next_action':'Repair formal transport/parser with source-bound lineage; reuse saved take and accepted responses'}
            dump(root/'failures'/(stage+'.json'),failure)
            result['checks'].extend({**failure,'task_id':t['task_id'],'confirmed':False,'texture_confirmed':False} for t in selection)
            persist();return None
    persist()
    for kind,schema in [('outcome',OUTCOME_JUDGE),('vfx',VFX_JUDGE)]:
        selected=[t for t in tasks if t['kind'] in ('mechanic','gamefeel')] if kind=='outcome' else [t for t in tasks if t['kind']=='vfx']
        for index,selection in enumerate(shards(root,selected,plan,manifest),1):
            stage=f'judge_astra_{kind}_{index:03d}'
            delivered=evidence.delivery(root,selection,plan['endpoints'],manifest,{})
            wire=save_delivery(root,stage,delivered,source_delivery)
            instructions=(POLICY+' Task goal defines core intent; fine pass-condition timing/numbers diagnostic only. '
                'Judge correct gameplay/UI object and meaning. Clear native single frame can suffice. No uniform log/state requirement. '
                'UNVERIFIED for no trigger/no coverage. No synthetic peers. '
                if kind=='outcome' else
                'VFX retains original refine-tiered.v1. Actual trigger/change, correct target and normal logs for NORMAL. '
                'All frozen conditions/lifecycle constraints for PASS. Missing coverage is UNVERIFIED, not BUG. ')
            prompt=(instructions+'Independently judge; no prior scores are supplied. Cite only delivered image numbers. '
                'State/event/log paths relative to run root; exact original SHA, physical line and literal quote. '
                'Wire JSON dictionaries preserve physical line numbers but JSON spelling may differ: quote short literal tokens '
                'or consult the supplied original excerpts, never manufacture whitespace. No tools/edits/launch. '
                '\nEXACT SCHEMA\n'+json.dumps(schema)+'\n'+wire+'\nAUTHOR SOURCE\n'+bundle)
            def validator(value):
                require_checks(value,selection)
                if kind=='outcome': judge_result(root,selection,value['checks'],codes,delivered)
                else:
                    numbers={r['image_number'] for r in delivered['images']}
                    for row in value['checks']:
                        if any(not reference(root,c) for c in row['state_event_refs']+row['log_refs']):raise ValueError('Invalid VFX physical citation')
                        if any(n not in numbers for n in row['image_numbers']):raise ValueError('Undelivered image')
            judged=attempt(stage,selection,lambda:invoke(root,stage,prompt,schema,config,delivered,validator))
            if judged:
                scored=(judge_result(root,selection,judged['checks'],codes,delivered) if kind=='outcome' else
                    [score(row,codes[row['task_id']],evidence.proof(root,row,endpoints[row['task_id']],manifest,None,delivered),
                        needs_window=next(t for t in selection if t['task_id']==row['task_id'])['needs_window']) for row in judged['checks']])
                result['checks'].extend({**r,'judge':ref(root/(stage+'.json')),
                    'delivery':ref(root/'evidence'/(stage+'_delivery.json'))} for r in scored)
            persist()
    imports=[t for t in tasks if t['kind']=='import']; missing=[t for t in imports if t.get('payload_status','READY')!='READY']
    for t in missing:
        result['checks'].append({'task_id':t['task_id'],'asset_kind':t['asset_kind'],
            'status':'BLOCKED_MISSING_PAYLOAD','confirmed':False,'texture_confirmed':False,'product_score':None,
            'reason':'Frozen original task has no payload; cannot certify named clip import',
            'payload':read(parent/'payloads.json')[t['task_id']]})
    visual=[t for t in imports if t.get('asset_kind')!='audio' and t not in missing]
    refs=read(parent/'reference_renders.json')
    context=[t for t in imports if t.get('asset_kind')=='audio' and endpoints[t['task_id']]['executable']]
    for index,selection in enumerate(shards(root,visual,plan,manifest,refs,context),1):
        stage=f'judge_astra_import_{index:03d}'; delivered=delivery_with_context(root,selection,plan,manifest,refs,context)
        wire=save_delivery(root,stage,delivered,source_delivery)
        prompt=APPEARANCE_POLICY+'\nEXACT SCHEMA\n'+json.dumps(APPEARANCE_JUDGE)+'\n'+wire+'\nAUTHOR SOURCE\n'+bundle
        def validator(value):
            require_checks(value,selection)
            for row in value['checks']:
                checked_appearance(row,next(t for t in selection if t['task_id']==row['task_id']),delivered,manifest,root)
        judged=attempt(stage,selection,lambda:invoke(root,stage,prompt,APPEARANCE_JUDGE,config,delivered,validator))
        if judged:
            for row in judged['checks']:
                normalized=checked_appearance(row,next(t for t in selection if t['task_id']==row['task_id']),delivered,manifest,root)
                result['checks'].append({**normalized,'judge':ref(root/(stage+'.json')),
                    'delivery':ref(root/'evidence'/(stage+'_delivery.json'))})
        persist()
    audio=[t for t in imports if t.get('asset_kind')=='audio']
    observations=attempt('audio_observations',audio,lambda:audio_judge(parent,root,audio))
    if observations:
        dump(root/'audio_observations.json',observations)
        stage='judge_astra_audio';delivered=evidence.delivery(root,audio,plan['endpoints'],manifest,{})
        wire=save_delivery(root,stage,delivered,source_delivery)
        allowed={r['task_id']:{v['path'] for v in r['evidence'].values() if isinstance(v,dict) and 'path' in v} for r in observations}
        prompt=('You make the final audio import decision from actual Qwen acoustic observations and source/native evidence. '
            'You have NOT directly heard the audio. Do not claim otherwise. User criterion: recognizable gunshot suffices, '
            'rain separate. Legitimate actual historic native audio may be reused when clearly attributed, not prior scores. '
            'Never infer sound presence from images/code alone. Unknown/uncovered is UNVERIFIED, not product zero. '
            'Every positive decision must cite actual observation_paths from the supplied immutable acoustic observation. '
            'Do not use product_score/confirmed advisory fields as independent evidence. No tools/edits/launch. '
            '\nACOUSTIC OBSERVATIONS\n'+json.dumps(observations,ensure_ascii=False)+'\n'+wire+
            '\nAUTHOR SOURCE\n'+bundle+'\nEXACT SCHEMA\n'+json.dumps(AUDIO_JUDGE))
        def validator(value):
            require_checks(value,audio)
            for row in value['checks']:
                original=next(r for r in observations if r['task_id']==row['task_id'])
                if not set(row['observation_paths'])<=allowed[row['task_id']]:raise ValueError('Unknown audio observation path')
                if row['confirmed'] and (not original['confirmed'] or not row['observation_paths']):raise ValueError('Unsupported audio confirmation')
        judged=attempt(stage,audio,lambda:invoke(root,stage,prompt,AUDIO_JUDGE,config,delivered,validator))
        if judged:
            for row in judged['checks']:
                original=next(r for r in observations if r['task_id']==row['task_id'])
                result['checks'].append({**original,'confirmed':row['confirmed'],'status':'CONFIRMED' if row['confirmed'] else 'UNVERIFIED',
                    'product_score':100 if row['confirmed'] else None,'reason':row['reason'],'judge':ref(root/(stage+'.json')),
                    'astra_observation_paths':row['observation_paths'],'acoustic_model':'qwen3.8-omni-flash','final_judge_model':MODEL})
    ids=[r['task_id'] for r in result['checks']]
    if len(ids)!=len(set(ids)) or set(ids)!={t['task_id'] for t in tasks}:raise ValueError('Exactly46 frozen identities required')
    ir=[r for r in result['checks'] if r['task_id'] in {t['task_id'] for t in imports}]
    result['import_summary']={'confirmed':sum(bool(r.get('confirmed')) for r in ir),'denominator':len(ir),
        'unverified':sum(r.get('status')=='UNVERIFIED' for r in ir),'missing_payload':len(missing),
        'texture_confirmed':sum(bool(r.get('texture_confirmed')) for r in ir),'texture_denominator':10}
    result['status']='PARTIAL_HARNESS_ERROR' if any(r.get('status')=='HARNESS_ERROR' for r in result['checks']) else 'SCORED_PENDING_AUDIT'
    verify(root);evidence.verify_manifest(root,manifest);validate_reuse(parent);persist()
    dump(root/'publication.json',{'status':result['status'],'result':ref(root/'result.json'),
        'planner_model':MODEL,'judge_model':MODEL,'task_coverage':len(ids),'semantic_audit':'PENDING','official_whitebox_eight_column_total':None})
    return result


def run(output,root,phase='all'):
    from .batch import exclusive,code_identity
    from .migration import verify_migration
    from ..whitebox_eval.engine_execution import lease
    output=Path(output).resolve();root=Path(root).resolve();parent=root.parent
    with exclusive(output.parent/(output.name+'.batch.lock')):
        verify_migration(output,code_identity());policy,config=configuration(output,root)
        prepare(parent,root,policy)
        if phase=='source-tier':
            recover_source_tier(root,config)
            from .project_eval_astra_audio import prepare_segmented_audio
            prepare_segmented_audio(root)
            result=evaluate(parent,root,config)
            print(json.dumps({'phase':result['status'],'completed_tasks':result['completed_tasks']}),flush=True)
            return result
        print(json.dumps({'phase':'ASTRA_STATIC','root':str(root),'model':MODEL}),flush=True)
        static_review(root,config)
        plan,schedule=plan_project(root,policy)
        print(json.dumps({'phase':'PLAN_VALIDATED','duration_ms':plan['native_plan']['max_duration_ms'],
            'executable_tasks':sum(e['executable'] for e in plan['endpoints'])}),flush=True)
        if phase=='plan':return
        marker=root/'stages/record.json'
        if marker.exists():record_project(parent,root,plan,schedule,config,policy)
        else:
            with lease(Path(config['unity']['control_root']),'ue5',output,
                output/'engine_execution'/(str(time.time_ns())+'_astra_reassessment.json'),policy=config['engine_execution_policy']):
                record_project(parent,root,plan,schedule,config,policy)
        manifest=once(root,'evidence',lambda:evidence.package(root,schedule));evidence.verify_manifest(root,manifest)
        print(json.dumps({'phase':'RECORD_EVIDENCE_COMPLETE'}),flush=True)
        if phase=='record':return
        result=evaluate(parent,root,config)
        print(json.dumps({'phase':result['status'],'completed_tasks':result['completed_tasks']}),flush=True)
        return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--root',required=True,type=Path);parser.add_argument('--phase',choices=['all','plan','record','source-tier'],default='all')
    args=parser.parse_args()
    try:run(args.output,args.root,args.phase)
    except Exception as exc:
        dump(args.root/'failure.json',{'status':'HARNESS_ERROR','error':f'{type(exc).__name__}: {exc}',
            'product_score':None,'preserve_attempts':True,'updated_unix':time.time()})
        raise

if __name__=='__main__':main()
