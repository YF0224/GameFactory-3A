"""Native project evidence judgment; import appearance is a separately frozen report.

Existing Mechanic/Gamefeel outcome judgments and original VFX tiers are retained.
Import appearance counts are never substituted for full adaptation certification.
"""
from pathlib import Path
import argparse
import base64
import hashlib
import json
import time

from .common import dump, read, sha, once
from .evaluation import JUDGE as VFX_JUDGE, REF, require_checks, model
from .scoring import reference, static_credit, score
from .outcome_groups import gameplay_source_bundle, JUDGE as OUTCOME_JUDGE, POLICY as OUTCOME_POLICY
from .vfx_groups import ref, validate_reuse
from . import evidence
from ..whitebox_eval.codex import obj, arr, S, I, B, call_codex

VERSION = 'refine.import-native-appearance.v1'
OBSERVATION = {'type':'string','enum':['OBSERVED','NOT_OBSERVED','UNVERIFIED','HARNESS_ERROR']}
APPEARANCE_JUDGE = obj({'checks':arr(obj({'task_id':S,'observation':OBSERVATION,
    'correct_target':B,'integrated_in_gameplay':B,'appearance_matches':B,
    'texture_visible':B,'texture_matches':B,'motion_visible':B,'known_basic_bug':B,
    'image_numbers':arr(I),'implementation_refs':arr(REF),'reason':S}))})
APPEARANCE_POLICY = (
    'Independent imported-asset appearance report authorized by user; not full geometry/rig/physics certification. '
    'Judge the exact asset target and description from real native game frames and full authored source. '
    'An imported target must actually appear in the running game with source-backed integration; '
    'primitive substitutes, asset names, comments, generated reference renders or unconnected files are insufficient. '
    'Do not demand exact pixels, coordinates, durations or all fine details. '
    'Texture is separately confirmed only if actual rendered material/texture is discernible and consistent with target; '
    'flat untextured primitives do not prove imported texture. '
    'Motion and CG playback require a real temporal frame sequence of the correct target, not a still or generic overlay. '
    'Missing payload is a source-delivery blocker; never certify a missing named clip as imported. '
    'Uncovered views and untriggered routes are UNVERIFIED, not product bugs. '
    'HARNESS_ERROR has no product score. Report confirmed object count / frozen task denominator; '
    'unverified and blockers remain explicit, never invented product zeros. '
    'Context frames retain their original capture IDs and cannot fabricate a task-bound action. '
    'Only actual delivered images can support a positive result. Original GLB views are references, never runtime evidence. '
    'Use exact physical source path/SHA/line/literal quote citations and actual image numbers. '
    'No tools, edits, engine launch or synthetic evidence. Return only the exact JSON schema.')


def freeze_contract(parent, root):
    tasks=read(root/'input/tasks.json')
    value={'version':VERSION,'tasks':ref(root/'input/tasks.json'),
        'source':ref(root/'input/source_manifest.json'),'policy':APPEARANCE_POLICY,
        'schema':APPEARANCE_JUDGE,'aggregation':'confirmed_count / frozen task denominator; unknowns and blockers explicit',
        'texture_denominator':[t['task_id'] for t in tasks if t.get('asset_kind') in ('3d_object','3d_scene')],
        'audio_policy':'Native recorded gunshot recognizable during legitimate pistol fire suffices for sfx001; rain evaluated separately by Qwen',
        'original_full_import_protocol_preserved':True,'created_before_runtime_judge':True}
    path=root/'import_appearance_contract.json'
    if path.exists() and read(path)!=value: raise ValueError('Frozen import appearance contract changed')
    dump(path,value)
    payloads=read(parent/'payloads.json')
    for t in tasks:
        if t['kind']!='import':continue
        item=payloads[t['task_id']]
        if item['status']=='READY' and sha(item['frozen_path'])!=item['sha256']:
            raise ValueError('Frozen import payload changed')
    return value


def checked_appearance(row,task,delivered,manifest,root=None):
    images={r['image_number']:r for r in delivered['images']}
    if any(n not in images for n in row['image_numbers']):raise ValueError('Undelivered appearance image')
    native=[images[n] for n in row['image_numbers'] if images[n]['origin']=='actual_engine']
    cited=row['implementation_refs']
    if any(not r['path'].startswith('project/') for r in cited):raise ValueError('Appearance citation is not authored source')
    if root is not None and any(not reference(Path(root)/'input',r) for r in cited):
        raise ValueError('Invalid authored appearance citation')
    missing=task.get('payload_status','READY')!='READY'
    fault=row['observation']=='HARNESS_ERROR'
    basic=bool(row['observation']=='OBSERVED' and row['correct_target'] and row['integrated_in_gameplay']
        and row['appearance_matches'] and not row['known_basic_bug'] and native and cited and not missing and not fault)
    kind=task['asset_kind']
    temporal=kind in ('motion','cg_video')
    window=manifest['audit']['windows'].get('window/'+task['task_id'],{})
    sequence=bool(len({i['t_ms'] for i in native})>=2 and window.get('complete') and window.get('continuous'))
    confirmed=bool(basic and (not temporal or sequence) and (kind!='motion' or row['motion_visible']))
    texture=bool(confirmed and kind in ('3d_object','3d_scene') and row['texture_visible'] and row['texture_matches'])
    status='HARNESS_ERROR' if fault else 'BLOCKED_MISSING_PAYLOAD' if missing else 'CONFIRMED' if confirmed else 'UNVERIFIED'
    return {'task_id':task['task_id'],'asset_kind':kind,'status':status,
        'confirmed':confirmed,'texture_confirmed':texture,'image_numbers':row['image_numbers'],
        'sequence_proved':sequence if temporal else None,'reason':row['reason'],
        'implementation_refs':cited,'policy':VERSION,'product_score':None if fault or missing else (100 if confirmed else None)}


def delivery_with_context(root,tasks,plan,manifest,references,context_tasks):
    relevant={t['task_id'] for t in tasks}
    merged={t['task_id']:t for t in tasks+context_tasks}
    delivered=evidence.delivery(root,list(merged.values()),plan['endpoints'],manifest,references)
    delivered['tasks']=tasks
    delivered['endpoints']=[e for e in plan['endpoints'] if e['task_id'] in relevant]
    delivered['context_task_ids']=[k for k in merged if k not in relevant]
    delivered['note']+=' Context images keep original capture IDs; absence is not exhaustive proof of product failure.'
    return delivered


def save_delivery(root,stage,delivered,source_delivery):
    from .grouped_transport import prepare
    dump(root/'evidence'/(stage+'_delivery.json'),delivered)
    dump(root/'evidence/judge_delivery.json',delivered)
    wire=prepare(root,delivered)
    for name in ('judge_wire_delivery.json','judge_wire_equivalence.json'):
        original=root/'evidence'/name
        dump(root/'evidence'/(stage+'_'+name),read(original))
    dump(root/'evidence'/(stage+'_source_delivery.json'),source_delivery)
    return wire


def normalize_appearance_paths(value, root):
    """Map the delivered source namespace; never repair a quote, SHA or line."""
    from copy import deepcopy
    root=Path(root).resolve();project=root/'input/project'
    allowed=read(root/'input/source_manifest.json')['files']
    normalized=deepcopy(value);mapping=[]
    for row in normalized['checks']:
        for citation in row['implementation_refs']:
            original=citation['path'];path=Path(original)
            if path.is_absolute():
                try:relative=path.resolve().relative_to(project.resolve()).as_posix()
                except ValueError:raise ValueError('Absolute citation outside delivered authored project')
            else:
                relative=original.removeprefix('project/')
            if '..' in Path(relative).parts or relative not in allowed:
                raise ValueError('Citation outside source manifest')
            updated={**citation,'path':'project/'+relative}
            if citation['sha256']!=allowed[relative] or not reference(root/'input',updated):
                raise ValueError('Physical source quote/SHA/line invalid; path normalization cannot repair it')
            mapping.append({'before':dict(citation),'after':updated})
            citation['path']=updated['path']
    return normalized,mapping


def recovery_authorization(root, stage):
    path=Path(root)/'judge_recovery.json'
    if not path.exists():return None
    spec=read(path);entry=spec.get('stages',{}).get(stage)
    if not entry:return None
    if spec['implementation_sha256']!=sha(__file__):raise ValueError('Recovery implementation changed')
    for key in ('parent_stage','parent_failure'):
        item=entry[key]
        if sha(item['path'])!=item['sha256']:raise ValueError('Recovery parent provenance changed')
    if read(entry['parent_stage']['path'])['status']!='ERROR':raise ValueError('Recovery needs preserved failed stage')
    return entry


def recover_appearance(root,stage,validator,entry):
    from ..whitebox_eval.codex import validate_schema
    recovery=entry['recovery_stage'];receipt=Path(root)/'recovery'/recovery
    def operation():
        rejected=[]
        for item in entry['responses']:
            if sha(item['path'])!=item['sha256']:raise ValueError('Saved response changed')
            try:
                value,mapping=normalize_appearance_paths(read(item['path']),root)
                validate_schema(value,APPEARANCE_JUDGE);validator(value)
            except ValueError as exc:
                rejected.append({'response':item,'error':str(exc)});continue
            dump(receipt/'receipt.json',{'source_response':item,'rejected':rejected,'path_mapping':mapping,
                'unchanged':'all judgments, booleans, image numbers, SHA, line and literal quotes',
                'no_model_call':True,'parent':entry,'normalized_response':ref(receipt/'response.json') if (receipt/'response.json').exists() else None})
            dump(receipt/'response.json',value)
            proof=read(receipt/'receipt.json');proof['normalized_response']=ref(receipt/'response.json');dump(receipt/'receipt.json',proof)
            return value
        dump(receipt/'rejected.json',rejected)
        raise ValueError('No saved response passes unchanged physical citation validation')
    value=once(root,recovery,operation)
    validator(value)
    dump(Path(root)/(stage+'.json'),value)
    return value


def invoke(root,stage,prompt,schema,config,delivered,validator):
    def call():
        value=call_codex(root,name=stage,prompt=prompt,schema=schema,model=config['sol']['model'],
            executable=config['sol'].get('executable','codex'),images=[Path(i['path']) for i in delivered['images']],
            timeout=config['sol'].get('timeouts',{}).get('judge',900),max_attempts=2,
            response_validator=validator,explicit_stdin_separator=True)
        dump(root/(stage+'.json'),value)
        return value
    recovery=recovery_authorization(root,stage)
    value=recover_appearance(root,stage,validator,recovery) if recovery else once(root,stage,call)
    validator(value)
    calls=[]
    for p in sorted((root/'model_calls').glob(stage+'*')):
        calls.append({name:ref(p/name) for name in ('prompt.txt','schema.json','invocation.json','response.json') if (p/name).exists()})
    dump(root/'evidence'/(stage+'_actual_delivery.json'),{'images':delivered['images'],'calls':calls,
        'delivery':ref(root/'evidence'/(stage+'_delivery.json')),
        'all_predeclared_relevant_frames_delivered':True})
    return value


def audio_judge(parent,root,tasks):
    """Qwen listens to the actual native WAV; no text-only sound inference."""
    if not tasks:return []
    from models.reasoning.judges import AudioJudgeModel
    take=root/'background_record/take'
    wav=take/'audio.wav'
    if not wav.exists():raise RuntimeError('Native audio channel missing; retain existing record, repair evidence')
    prompt=('Listen to this actual unmodified native game recording. Evaluate two sound objects independently. '
        'Recognizable gunshots during legitimate pistol fire suffice; do not require brass-shell tail, exact weapon or source WAV identity. '
        'For rain, require audible rain/rainstorm ambience, not music or gunfire or thunder alone. '
        'Do not infer from descriptions or code. Uncertain is unknown, not no. '
        'Return only JSON {"gunshot":{"audible":"yes|no|unknown","time_windows_seconds":[{"start":0.0,"end":1.0}],"reason":"..."},'
        '"rain":{"audible":"yes|no|unknown","time_windows_seconds":[{"start":0.0,"end":1.0}],"reason":"..."}}.')
    stage='audio_qwen'
    recovery=recovery_authorization(root,stage)
    audio_dir=root/'audio'/(recovery['recovery_stage'] if recovery else '')
    def call():
        # Read credential locally without copying it into any artifact or child environment.
        from ..judge_profiles import load_dashscope_key_file
        credentials={}
        if not load_dashscope_key_file(Path(os.environ.get('DASHSCOPE_KEY_FILE', Path.home() / '.config/gamefactory/dashscope.txt')),credentials):
            raise ValueError('DashScope key file unavailable; contents withheld')
        credential=credentials['DASHSCOPE_API_KEY']
        encoded=base64.b64encode(wav.read_bytes()).decode()
        request={'model':'qwen3.8-omni-flash','prompt':prompt,'audio':ref(wav),'sample_unchanged':True}
        dump(audio_dir/'request.json',request)
        response=AudioJudgeModel(model='qwen3.8-omni-flash',api_key=credential,max_tokens=2048,timeout_s=180).judge(
            prompt=prompt,audio_b64=[('wav',encoded)])
        dump(audio_dir/'raw_response.json',{'text':response.text,'provenance':response.provenance})
        value=json.loads(response.text)
        for key in ('gunshot','rain'):
            if value[key]['audible'] not in ('yes','no','unknown') or not isinstance(value[key]['time_windows_seconds'],list):
                raise ValueError('Invalid targeted Qwen audio observation')
        dump(audio_dir/'actual_delivery.json',{'status':'delivered','audio':ref(wav),
            'delivered_format':'wav','delivered_bytes':wav.stat().st_size,'sample_unchanged':True,
            'request':ref(audio_dir/'request.json'),'response':ref(audio_dir/'raw_response.json')})
        return value
    observed=once(root,recovery['recovery_stage'] if recovery else stage,call)
    # Prior actual gunshot observation is reusable, with explicit immutable lineage.
    prior=root.parents[2]/'engineering/audio_qwen_observation_20261104'
    prior_observation=None
    if (prior/'response.json').exists():
        prior_delivery=read(prior/'audio_actual_delivery.json')
        source=Path(prior_delivery['source_path'])
        if sha(source)!=prior_delivery['source_sha256']:raise ValueError('Prior real Qwen audio changed')
        prior_observation=read(prior/'response.json')
    events=[r for _,r in __import__('pipeline.game_eval.refine.common',fromlist=['jsonl']).jsonl(take/'event_trace.jsonl')]
    result=[]
    source=(root/'input/project/Source/DockBeacon/DockHost.cpp').read_text()
    for task in tasks:
        gun=task['target']['asset_name']=='pistol_shot'
        key='gunshot' if gun else 'rain'
        observation=observed[key]; lineage={'observation':ref(audio_dir/'raw_response.json'),'audio':ref(wav),'delivery':ref(audio_dir/'actual_delivery.json')}
        trigger=any(r.get('event')=='fire' for r in events) if gun else 'rain_loop' in source
        if gun and prior_observation and prior_observation.get('parsed_observation',{}).get('audible_pistol_like_shot')=='yes':
            from .ue_cleanup import verify
            verify(parent/'outcome_groups/basic_combat')
            prior_events=parent/'outcome_groups/basic_combat/background_record/take/event_trace.jsonl'
            if not any(r.get('event')=='fire' and r.get('actor_id')==0 and r.get('weapon_id')==0
                for _,r in __import__('pipeline.game_eval.refine.common',fromlist=['jsonl']).jsonl(prior_events)):
                raise ValueError('Historical gunshot lacks legitimate native pistol fire')
            observation={'audible':'yes','time_windows_seconds':prior_observation['parsed_observation']['evidence_time_windows_seconds'],
                'reason':prior_observation['parsed_observation']['overall_observation']}
            confirmed=True;lineage={'observation':ref(prior/'response.json'),'delivery':ref(prior/'audio_actual_delivery.json'),
                'current_take_observation':ref(audio_dir/'raw_response.json'),
                'native_pistol_events':ref(parent/'outcome_groups/basic_combat/background_record/take/event_trace.jsonl'),
                'reuse':'Historical unchanged native recording rejudged under user recognizable-gunshot criterion'}
        else:confirmed=bool(observation['audible']=='yes' and trigger)
        result.append({'task_id':task['task_id'],'asset_kind':'audio','status':'CONFIRMED' if confirmed else 'UNVERIFIED',
            'confirmed':confirmed,'texture_confirmed':False,'observation':observation,'evidence':lineage,
            'product_score':100 if confirmed else None,'policy':VERSION,
            'reason':observation['reason'],'limitation':'Audible object presence; no exact WAV identity certification'})
    return result


def evaluate(parent,root,config):
    from .ue_cleanup import verify
    verify(root);validate_reuse(parent)
    tasks=read(root/'input/tasks.json');plan=read(root/'plan.json');manifest=read(root/'evidence/manifest.json')
    evidence.verify_manifest(root,manifest);freeze_contract(parent,root)
    endpoints={e['task_id']:e for e in plan['endpoints']}
    inherited=read(root/'reused_results.json')
    from .project_eval import existing_results
    if inherited!=existing_results(parent):raise ValueError('Inherited completed result changed')
    bundle,source_delivery=gameplay_source_bundle(root)
    static={r['task_id']:static_credit(root/'input',r) for r in read(root/'static.json')['checks']}
    reviewed=read(parent/'outcome_source_normalized.json')
    source_codes={r['task_id']:static_credit(root/'input',r) for r in reviewed['checks']}
    result={'version':'refine.project-evaluation.v1','status':'IN_PROGRESS','checks':[],
        'source':ref(root/'input/source_manifest.json'),'plan':ref(root/'plan.json'),'native_evidence':ref(root/'evidence/manifest.json'),
        'import_contract':ref(root/'import_appearance_contract.json'),'semantic_audit':'PENDING','official_whitebox_total':None,
        'reused_completed':len(inherited)}
    for task in tasks:
        if task['task_id'] in inherited:
            result['checks'].append({**inherited[task['task_id']]['check'],'history':inherited[task['task_id']]})
    def persist():
        result['updated_unix']=time.time()
        result['completed_tasks']=len(result['checks'])
        result['total_tasks']=len(tasks)
        dump(root/'result.json',result)
    persist()
    def attempt(stage, selection, operation):
        try:return operation()
        except Exception as exc:
            failure={'status':'HARNESS_ERROR','stage':stage,'error':f'{type(exc).__name__}: {exc}',
                'product_score':None,'last_qualified_stage':'RECORD_EVIDENCE_COMPLETE',
                'next_action':'Repair the saved production request/parse/delivery failure with source-bound lineage; reuse this native take'}
            dump(root/'failures'/(stage+'.json'),failure)
            for t in selection:
                result['checks'].append({**failure,'task_id':t['task_id'],'confirmed':False,'texture_confirmed':False})
            persist()
            return None
    pending=[t for t in tasks if t['task_id'] not in inherited]
    # Unsupported Mechanic inputs keep valid source credit, without claiming runtime completion.
    for t in [t for t in pending if t['kind'] in ('mechanic','gamefeel') and not endpoints[t['task_id']]['executable']]:
        result['checks'].append({'task_id':t['task_id'],'status':'SOURCE_ONLY_PENDING_RUNTIME',
            'credit_percent':10 if source_codes.get(t['task_id']) else 0,
            'execution':'UNVERIFIED','reason':endpoints[t['task_id']]['reason'],
            'source_review':ref(parent/'outcome_source_normalized.json'),'runtime_complete':False,
            'policy':'refine.grouped-outcome-frame.v2'})
    persist()
    context=[t for t in tasks if endpoints[t['task_id']]['executable'] and t.get('asset_kind')=='audio' and t['target']['asset_name']=='pistol_shot']
    # Independent VFX semantics and deterministic proof gates are unchanged.
    vfx=[t for t in pending if t['kind']=='vfx']
    if vfx:
        delivered=evidence.delivery(root,vfx,plan['endpoints'],manifest,{})
        stage='judge_project_vfx';wire=save_delivery(root,stage,delivered,source_delivery)
        prompt=('Judge these original frozen VFX conditions under refine-tiered.v1, without Mechanic/Gamefeel relaxation. '
            'Actual triggered input, actual change, correct target and normal logs required for NORMAL. '
            'All original conditions and lifecycle constraints required for PASS. Missing coverage is UNVERIFIED, not BUG. '
            'Use exact physical citations, preserving literal whitespace. Return exact schema only.\nEXACT SCHEMA\n'
            +json.dumps(VFX_JUDGE)+'\n'+wire+'\nAUTHOR SOURCE\n'+bundle)
        def validator(value):
            require_checks(value,vfx)
            for row in value['checks']:
                if any(not reference(root,c) for c in row['state_event_refs']+row['log_refs']):raise ValueError('Invalid VFX citation')
                if any(n not in {i['image_number'] for i in delivered['images']} for n in row['image_numbers']):raise ValueError('Undelivered VFX image')
        judged=attempt(stage,vfx,lambda:invoke(root,stage,prompt,VFX_JUDGE,config,delivered,validator))
        for row in judged['checks'] if judged else []:
            t=next(t for t in vfx if t['task_id']==row['task_id'])
            gates=evidence.proof(root,row,endpoints[t['task_id']],manifest,None,delivered)
            result['checks'].append({**score(row,static[t['task_id']],gates,needs_window=t['needs_window']),
                'status':'SCORED_PENDING_AUDIT','judge':ref(root/(stage+'.json'))})
        persist()
    imports=[t for t in pending if t['kind']=='import']
    missing=[t for t in imports if t.get('payload_status','READY')!='READY']
    for t in missing:
        result['checks'].append({'task_id':t['task_id'],'asset_kind':t['asset_kind'],
            'status':'BLOCKED_MISSING_PAYLOAD','confirmed':False,'texture_confirmed':False,'product_score':None,
            'reason':'Frozen original import task has no motion payload; native screenshot cannot certify missing clip import',
            'payload':read(parent/'payloads.json')[t['task_id']],'policy':VERSION})
    persist()
    visual=[t for t in imports if t.get('asset_kind')!='audio' and t not in missing]
    refs=read(parent/'reference_renders.json')
    # Judge shards are transport-sized only; there is still one project plan and one take.
    groups=[];current=[]
    for t in visual:
        candidate=current+[t]
        try:delivery_with_context(root,candidate,plan,manifest,refs,context)
        except ValueError as exc:
            if '100 actual images' not in str(exc) or not current:raise
            groups.append(current);current=[t]
        else:current=candidate
    if current:groups.append(current)
    for index,selection in enumerate(groups,1):
        stage=f'judge_import_appearance_{index:03d}'
        delivered=delivery_with_context(root,selection,plan,manifest,refs,context)
        wire=save_delivery(root,stage,delivered,source_delivery)
        prompt=APPEARANCE_POLICY+'\nEXACT OUTPUT SCHEMA\n'+json.dumps(APPEARANCE_JUDGE)+'\n'+wire+'\nAUTHOR SOURCE\n'+bundle
        def validator(value):
            require_checks(value,selection)
            for row in value['checks']:
                task=next(t for t in selection if t['task_id']==row['task_id'])
                checked_appearance(row,task,delivered,manifest,root)
        judged=attempt(stage,selection,lambda:invoke(root,stage,prompt,APPEARANCE_JUDGE,config,delivered,validator))
        for row in judged['checks'] if judged else []:
            task=next(t for t in selection if t['task_id']==row['task_id'])
            result['checks'].append({**checked_appearance(row,task,delivered,manifest,root),
                'judge':ref(root/(stage+'.json')),'delivery':ref(root/'evidence'/(stage+'_delivery.json'))})
        persist()
    audio=[t for t in imports if t['asset_kind']=='audio']
    audio_result=attempt('audio_qwen',audio,lambda:audio_judge(parent,root,audio))
    if audio_result:result['checks'].extend(audio_result)
    persist()
    ids=[r['task_id'] for r in result['checks']]
    if len(ids)!=len(set(ids)) or set(ids)!={t['task_id'] for t in tasks}:
        raise ValueError('Project result must cover all46 original task IDs once each')
    evidence.verify_manifest(root,manifest);verify(root);validate_reuse(parent)
    ir=[r for r in result['checks'] if r['task_id'] in {t['task_id'] for t in imports}]
    result['import_summary']={'confirmed':sum(r.get('confirmed',False) for r in ir),'denominator':len(imports),
        'unverified':sum(r['status']=='UNVERIFIED' for r in ir),'missing_payload':len(missing),
        'note':'Confirmed presence count / all frozen import objects; unresolved/missing not scored as product zero',
        'texture_confirmed':sum(r.get('texture_confirmed',False) for r in ir),
        'texture_denominator':len([t for t in imports if t['asset_kind'] in ('3d_object','3d_scene')])}
    result['status']='PARTIAL_HARNESS_ERROR' if any(r.get('status')=='HARNESS_ERROR' for r in result['checks']) else 'SCORED_PENDING_AUDIT'
    result['runtime_complete_tasks']=sum(r.get('runtime_complete',True) and r.get('status') not in ('BLOCKED_MISSING_PAYLOAD','UNVERIFIED') for r in result['checks'])
    persist()
    dump(root/'publication.json',{'status':result['status'],'result':ref(root/'result.json'),
        'protocols':['refine.grouped-outcome-frame.v2','refine-tiered.v1',VERSION],
        'task_coverage':len(ids),'semantic_audit':'PENDING','official_whitebox_eight_column_total':None})
    return result


def run(output):
    from .batch import exclusive,code_identity
    from .migration import verify_migration
    from .project_eval import ROOT_NAME
    output=Path(output).resolve()
    with exclusive(output.parent/(output.name+'.batch.lock')):
        verify_migration(output,code_identity())
        parent=output/'games/G008_dock_beacon_cs';root=parent/ROOT_NAME
        return evaluate(parent,root,read(output/'configuration.json'))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv)
    result=run(args.output)
    print(json.dumps({'status':result['status'],'completed_tasks':result['completed_tasks'],
        'import_summary':result.get('import_summary')},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
