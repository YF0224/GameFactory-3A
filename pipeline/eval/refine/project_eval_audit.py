"""Deterministic mixed-protocol G008 result replay; not a semantic model audit."""
from pathlib import Path
import argparse
import json
from .common import read,dump,sha
from .project_eval_judge import checked_appearance,ref
from .scoring import score,static_credit,reference
from . import evidence


def verify_delivery(root,stage):
    delivered=read(root/'evidence'/(stage+'_delivery.json'))
    actual=read(root/'evidence'/(stage+'_actual_delivery.json'))
    if actual['images']!=delivered['images'] or len(delivered['images'])>100:
        raise ValueError('Delivery image list changed')
    for item in delivered['images']:
        if sha(item['path'])!=item['sha256']:raise ValueError('Delivered pixels changed')
    source=read(root/'evidence'/(stage+'_source_delivery.json'))
    if source['omitted'] or any(i['truncated'] for i in source['sent']):raise ValueError('Incomplete source delivery')
    from .outcome_groups import gameplay_source_bundle
    bundle,expected_source=gameplay_source_bundle(root)
    if source!=expected_source:raise ValueError('Source delivery differs from frozen authored source')
    for call in actual['calls']:
        for item in call.values():
            if sha(item['path'])!=item['sha256']:raise ValueError('Model request/response changed')
        invocation=read(call['invocation.json']['path']);command=invocation['command']
        images=[command[i+1] for i,t in enumerate(command[:-1]) if t=='--image']
        if images!=[i['path'] for i in delivered['images']]:raise ValueError('Actual image arguments incomplete')
        if bundle not in Path(call['prompt.txt']['path']).read_text():raise ValueError('Full source not in actual prompt')
    if not actual['calls']:raise ValueError('No saved model delivery')
    return delivered


def audit(root):
    from .ue_cleanup import verify
    from .vfx_groups import validate_reuse
    from .project_eval import existing_results
    root=Path(root).resolve();parent=root.parent
    cleanup=verify(root);validate_reuse(parent)
    manifest=read(root/'evidence/manifest.json');evidence.verify_manifest(root,manifest)
    result=read(root/'result.json');tasks={t['task_id']:t for t in read(root/'input/tasks.json')}
    rows={r['task_id']:r for r in result['checks']}
    if len(rows)!=len(result['checks']) or set(rows)!=set(tasks):raise ValueError('Result identity mismatch')
    inherited=existing_results(parent)
    if inherited!=read(root/'reused_results.json'):raise ValueError('Historical result changed')
    for ident,old in inherited.items():
        if rows[ident]!={**old['check'],'history':old}:raise ValueError('Historical verdict changed')
    endpoints={r['task_id']:r for r in read(root/'plan.json')['endpoints']}
    codes={r['task_id']:static_credit(root/'input',r) for r in read(root/'static.json')['checks']}
    checked=[]
    for p in sorted(root.glob('judge_*.json')):
        stage=p.stem
        if not stage.startswith(('judge_project_vfx','judge_import_appearance')):continue
        delivery=verify_delivery(root,stage)
        for row in read(p)['checks']:
            ident=row['task_id'];task=tasks[ident];proposed=rows[ident]
            if stage=='judge_project_vfx':
                if not all(reference(root,c) for c in row['state_event_refs']+row['log_refs']):raise ValueError('Invalid VFX physical citation')
                gates=evidence.proof(root,row,endpoints[ident],manifest,None,delivery)
                replay=score(row,codes[ident],gates,needs_window=task['needs_window'])
            else:replay=checked_appearance(row,task,delivery,manifest,root)
            if any(proposed.get(k)!=v for k,v in replay.items()):raise ValueError('Saved score differs from replay')
            checked.append(ident)
    # Audio confirmed entries must be backed by actual successful native audio delivery.
    for ident,task in tasks.items():
        row=rows[ident]
        if task.get('asset_kind')=='audio' and row.get('confirmed'):
            lineage=row['evidence']
            for item in lineage.values():
                if isinstance(item,dict) and 'path' in item and sha(item['path'])!=item['sha256']:
                    raise ValueError('Audio observation provenance changed')
            delivered=read(lineage['delivery']['path'])
            if 'source_path' in delivered:
                if sha(delivered['source_path'])!=delivered['source_sha256']:raise ValueError('Historic native WAV changed')
                observation=read(lineage['observation']['path'])['parsed_observation']
                if observation['audible_pistol_like_shot']!='yes':raise ValueError('Gunshot unsupported')
                from .common import jsonl
                if not any(r.get('event')=='fire' and r.get('actor_id')==0 and r.get('weapon_id')==0
                    for _,r in jsonl(lineage['native_pistol_events']['path'])):raise ValueError('Pistol trigger missing')
            else:
                if delivered['audio']!=lineage['audio'] or sha(lineage['audio']['path'])!=lineage['audio']['sha256']:
                    raise ValueError('Native audio delivery changed')
                observation=read(lineage['observation']['path'])
                parsed=json.loads(observation['text']);key='gunshot' if task['target']['asset_name']=='pistol_shot' else 'rain'
                if parsed[key]['audible']!='yes':raise ValueError('Audio confirmation unsupported')
        if row.get('status')=='BLOCKED_MISSING_PAYLOAD' and (row.get('product_score') is not None or row.get('confirmed')):
            raise ValueError('Missing payload mis-scored')
    imports=[rows[i] for i,t in tasks.items() if t['kind']=='import']
    summary=result['import_summary']
    if summary['confirmed']!=sum(bool(r.get('confirmed')) for r in imports) or summary['denominator']!=len(imports):
        raise ValueError('Import aggregation differs')
    if summary['texture_confirmed']!=sum(bool(r.get('texture_confirmed')) for r in imports):raise ValueError('Texture aggregation differs')
    publication=read(root/'publication.json')
    if publication['result']!=ref(root/'result.json'):raise ValueError('Publication stale')
    value={'status':'PASS','scope':'deterministic provenance and score replay; semantic audit remains pending',
        'result':ref(root/'result.json'),'historical_preserved':len(inherited),'new_visual_replayed':len(checked),
        'task_identities':len(rows),'cleanup':cleanup,'semantic_audit':'PENDING','official_eight_column_total':None}
    dump(root/'deterministic_audit.json',value)
    return value


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',required=True,type=Path)
    args=parser.parse_args();print(json.dumps(audit(args.root),ensure_ascii=False))

if __name__=='__main__':main()
