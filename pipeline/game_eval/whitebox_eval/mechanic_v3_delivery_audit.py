"""Read-only delivery qualification of the judgments that actually produced a score.

Historic publication integrity remains separate from complete source/frame delivery.
Never rebuild a retained request or require historic code to equal current code.
"""
from pathlib import Path
import argparse
import hashlib
import json
from functools import lru_cache
from . import mechanic_v3_execution as execution, mechanic_v3_revision as revisions
from . import mechanic_v3_outcome_evidence as evidence, document_wire
from .mechanic_v3_runner import read, stamp
from .protocol import sha, dump

VERSION='mechanic-published-delivery-audit.v2'

@lru_cache(maxsize=64)
def _exact_wire(path,ident,digest):
    if sha(path)!=digest:raise ValueError('Source changed during wire audit')
    return document_wire.section(path,ident)


def task_delivery(root, artifact, manifest):
    root=Path(root);name=artifact['task'];request=root/'requests'/name
    call=root/'model_calls'/name
    context=read(request/'context_binding.json');selected=read(request/'selected_manifest.json')
    actual=read(request/'actual_delivery.json');invocation=read(call/'invocation.json')
    prompt=(call/'prompt.txt').read_text();issues=[]
    if sha(call/'prompt.txt')!=actual['prompt_sha256']:
        raise ValueError('Actual submitted prompt SHA differs')
    command=invocation.get('command',[])
    sent=[str(Path(command[n+1]).resolve()) for n,v in enumerate(command[:-1]) if v=='--image']
    wanted=[str((root/v['path']).resolve()) for v in actual['images']]
    if invocation.get('exit_code')!=0 or sent!=wanted:
        raise ValueError('Actual submitted native image list differs')
    for row in actual['images']:
        if sha(root/row['path'])!=row['sha256']:raise ValueError('Native submitted image SHA differs')
    for filename,key in [('actual_delivery.json','actual_delivery_sha256'),('accepted_response.json','accepted_response_sha256')]:
        if sha(call/filename)!=artifact[key]:raise ValueError('Accepted judgment delivery changed')
    if sha(Path(artifact['response_path']))!=artifact['response_sha256']:
        raise ValueError('Accepted response changed')
    sources={v['id']:v for v in selected['items'] if v['type']=='source'}
    expected={v['id'] for v in manifest['items'] if v['type']=='source'}
    if set(sources)!=expected:issues.append(dict(kind='MISSING_SOURCE_IDS',ids=sorted(expected-set(sources))))
    gaps=[v for v in context['omitted_source_ranges'] if v['id'] in expected]
    if gaps:issues.append(dict(kind='TRUNCATED_SOURCE',ranges=gaps))
    missing=[]
    for ident,row in sources.items():
        path=root/row['path']
        if sha(path)!=row['sha256']:raise ValueError('Original source SHA differs: '+ident)
        text=path.read_text(errors='strict')
        full='\nEVIDENCE '+ident+'\n'+''.join(f'{n}: {line}\n' for n,line in enumerate(text.splitlines(),1))
        if full not in prompt:
            marker='\nEVIDENCE '+ident+' (exact document physical lines):\n'
            if marker not in prompt or _exact_wire(path,ident,row['sha256']) not in prompt:missing.append(ident)
    if missing:issues.append(dict(kind='SOURCE_BYTES_NOT_SUBMITTED',ids=missing))
    delivered=selected.get('evidence_sets',{}).get(artifact['parent'],{}).get('frames',{})
    expected_frames=evidence.selected_ids(manifest,artifact['parent'])
    absent=expected_frames-set(delivered)
    if absent:issues.append(dict(kind='PREDECLARED_FRAMES_NOT_SUBMITTED',ids=sorted(absent)))
    if not absent and expected_frames:
        try:
            from .protocol import load_lines
            from .action_links import frame_id
            indexed={frame_id(row,index):row for index,row in enumerate(
                load_lines(root/'runtime/frame_index.jsonl'),1)}
            evidence.validate_pixels(root,selected['evidence_sets'][artifact['parent']],indexed,expected_frames)
        except Exception as error:
            issues.append(dict(kind='NATIVE_FRAME_PIXEL_DELIVERY_INVALID',error=repr(error)))
    return dict(task=name,parent=artifact['parent'],qualified=not issues,source_count=len(sources),
        frame_count=len(delivered),submitted_image_count=len(actual['images']),issues=issues,
        bindings={str(p):sha(p) for p in [root/'judgments'/(name+'.json'),request/'context_binding.json',
            request/'selected_manifest.json',request/'actual_delivery.json',call/'prompt.txt',call/'invocation.json',
            call/'accepted_response.json',Path(artifact['response_path'])]})


def publication(workspace,identity):
    workspace=Path(workspace);pub=execution.verify_publication(workspace,identity)
    pubpath=revisions.publication_dir(workspace)/(identity+'.json')
    root=Path(pub['score_file']).parent;result=read(Path(pub['score_file']))
    manifest=read(root/'evidence_manifest.json');protocol=read(root/'input/pilot_rubric.json')
    # Select by exact scored checks from immutable publication-bound artifacts.
    # A later code SHA must not invalidate an already completed historic call.
    candidates=[]
    for p in sorted((root/'judgments').glob('mechanic_v3_of1_*.json')):
        if pub['bindings'].get(str(p))!=sha(p):continue
        artifact=read(p);checks=artifact.get('checks',{})
        if checks and all(k in result['checks'] and result['checks'][k]==v for k,v in checks.items()):
            candidates.append(artifact)
    tasks=[]
    for _,parent,specs in execution.partitions(protocol,manifest,prefix='mechanic_v3_of1_'):
        ids={s['id'] for s in specs}
        matching=[a for a in candidates if set(a['checks'])==ids and a['parent']==parent]
        if not matching:raise ValueError('No publication-bound artifact for actual scored checks')
        assessed=[task_delivery(root,a,manifest) for a in matching]
        # Equivalent accepted checks may have multiple retained invocations.
        # Any fully delivered accepted artifact supporting those exact checks suffices.
        tasks.append(next((a for a in assessed if a['qualified']),assessed[-1]))
    return dict(version=VERSION,time=stamp(),identity=identity,workspace=str(workspace),root=str(root),
        publication=str(pubpath),publication_sha256=sha(pubpath),mechanic_score=pub['mechanic_score'],
        qualified=all(t['qualified'] for t in tasks),tasks=tasks,
        old_publication_unchanged=True,score_based_retry_prohibited=True)


def all_scope(workspace):
    from . import mechanic_v3_full_scope as scope, mechanic_v3_cli as cli
    workspace=Path(workspace);inventory=scope.load(workspace);parent=cli.parent_workspace(inventory);rows=[]
    for row in inventory['entries']:
        if not row['in_scope']:continue
        ident=row['entry']['id']
        own=revisions.publication_dir(workspace)/(ident+'.json')
        chosen=workspace if own.exists() else parent
        if not chosen or not (revisions.publication_dir(chosen)/(ident+'.json')).exists():
            rows.append(dict(identity=ident,qualified=False,status='NO_PUBLICATION'));continue
        try:
            audited=publication(chosen,ident)
            rows.append(dict(audited,status='DELIVERY_QUALIFIED' if audited['qualified'] else 'DELIVERY_REPAIR_REQUIRED'))
        except Exception as error:rows.append(dict(identity=ident,qualified=False,status='AUDIT_ERROR',error=repr(error)))
    return dict(version=VERSION,time=stamp(),scope_binding=inventory['full_scope_binding'],rows=rows,
        selected=len(rows),published=sum(r['status']!='NO_PUBLICATION' for r in rows),
        delivery_qualified=sum(r['qualified'] for r in rows))


def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('--workspace',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args(argv)
    result=all_scope(args.workspace.resolve())
    if args.output.exists():raise ValueError('Audit receipts are immutable; choose a new timestamp')
    dump(args.output,result)
    print(json.dumps({k:v for k,v in result.items() if k!='rows'}))
    for row in result['rows']:print(json.dumps(dict(identity=row['identity'],status=row['status'],qualified=row['qualified'],error=row.get('error'))))
    return 0

if __name__=='__main__':raise SystemExit(main())
