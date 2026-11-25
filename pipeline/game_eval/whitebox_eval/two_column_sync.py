"""Versioned, source-bound column publication into the shared historical table.

Only verified publications supply scores. Existing historical bytes outside the
owned markers are retained. Both publisher locks, archive and atomic merge apply.
"""
from pipeline.eval.stage1.paths import DATA_ROOT
from __future__ import annotations
import argparse
from contextlib import ExitStack
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from .protocol import sha, dump
from . import mechanic_v3_runner as runner
from . import evaluation_model_profile as eval_models

REPO=Path(__file__).resolve().parents[3]
TARGET=DATA_ROOT/'outputs/eval/playtest/whitebox_eval_godot_threejs_5models_20261023_retry/scores.md'
START='<!-- mechanic-v3-gameness-v4:begin -->'
END='<!-- mechanic-v3-gameness-v4:end -->'
VERSION='source-bound-two-column-publication.v1'


def atomic(path, content):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.'+path.name+'.',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as h:h.write(content);h.flush();os.fsync(h.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)


def merge(text, rows, *, namespace=None):
    if namespace not in (None,'unity-m-original-outcome-frame-v1'):raise ValueError('Unknown two-column namespace')
    start=START if namespace is None else '<!-- unity-m-mechanic-v3-gameness-v4:begin -->'
    end=END if namespace is None else '<!-- unity-m-mechanic-v3-gameness-v4:end -->'
    lines=[start,'','## Mechanic v3 / Gameness v4 两列专项成绩（未审计）','',
        '本区独立列均为 SCORED_PENDING_AUDIT；缺列未完成，不填零。区外八列表、汇总与总分均为历史口径；不计算混合版本总分。','',
        '| 模型 | case | tier | 原始身份 / 来源 SHA256 | 实际引擎 | Mechanic v3 | Gameness v4 | 独立列状态 / publication |',
        '|---|---|---|---|---|---:|---:|---|']
    for key,row in sorted(rows.items(),key=lambda x:(x[1]['method'],x[1]['case_id'],x[0])):
        columns=row['columns'];values=[];sources=[]
        for col in ('Mechanic','Gameness'):
            value=columns.get(col);values.append(f"{value['score']:.2f}" if value else '未完成')
            sources.append(f"{col}: SCORED_PENDING_AUDIT / {value['publication']} / SHA256 {value['publication_sha256']}" if value else col+': 未完成，待正式阶段闭环')
        for col in ('Mechanic','Gameness'):
            value=columns.get(col)
            if value and value.get('evaluation_model_profile'):
                profile=value['evaluation_model_profile']
                sources.append(col+': Astra plan/judge; static Sol; previous '+str(profile['baseline']['score'])+' / '+profile['baseline']['publication'])
        lines.append('| '+' | '.join([row['method'],row['case_id'],row['tier'],row['identity']+' / '+row['source_sha256'],row['engine'],*values,'; '.join(sources)])+' |')
    lines.extend(['',end]);section='\n'.join(lines)
    if text.count(start)!=text.count(end) or text.count(start)>1:raise ValueError('Ambiguous shared table markers')
    if namespace is not None:section=section.replace('两列专项成绩（未审计）','Unity M 原始项目两列专项成绩（未审计）',1)
    if start in text:
        a=text.index(start);b=text.index(end)+len(end)
        return text[:a]+section+text[b:]
    return text.rstrip('\n')+'\n\n'+section+'\n'


def verified(workspace,identity,column):
    from . import mechanic_v3_full_scope as scope, mechanic_v3_revision as revision
    from . import mechanic_v3_execution as mechanic, gameness_v3_runtime as gameness
    workspace=Path(workspace).resolve()
    config=runner.read(workspace/'two_column_sync.json') if (workspace/'two_column_sync.json').exists() else {}
    if config.get('namespace')=='unity-m-original-outcome-frame-v1':
        from .unity_m_judge import sync_verified
        return sync_verified(workspace,identity,column)
    if config.get('namespace') is not None:raise ValueError('Unknown publication namespace')
    if column=='Mechanic':
        pub=mechanic.verify_publication(workspace,identity)
        if pub['contract_revision']!='outcome_frame_v1':raise ValueError('Wrong Mechanic revision')
        from . import mechanic_v3_delivery_audit_v4 as audit, mechanic_v3 as policy
        if pub.get('qualification_recovery'):
            from .persistent_original_pixel_recovery import verify_published_replacement
            from . import mechanic_v3_delivery_audit_v3 as native_delivery
            proof=verify_published_replacement(Path(pub['score_file']).parent,pub)
            root=Path(pub['score_file']).parent;manifest=runner.read(root/'evidence_manifest.json')
            tasks=[native_delivery.task_delivery(root,runner.read(root/'judgments'/(n+'.json')),manifest) for n in proof['task_names']]
            delivery=audit.upgrade(dict(version=native_delivery.VERSION,root=str(root),tasks=tasks))
        else:delivery=audit.publication(workspace,identity)
        if not delivery['qualified']:raise ValueError('Incomplete Mechanic source/native-frame delivery')
        pubpath=revision.publication_dir(workspace)/(identity+'.json');score=pub['mechanic_score']
        root=Path(pub['score_file']).parent
        result=runner.read(Path(pub['score_file']))
        calculated=dict(policy.aggregate(runner.read(root/'input/pilot_rubric.json'),result['checks']),
            assessment_revision=pub['contract_revision'])
        if calculated!=result or calculated['score']!=score:
            raise ValueError('Mechanic aggregate mismatch')
    elif column=='Gameness':
        pub=gameness.verify_publication(workspace,identity)
        if pub['scoring_protocol']!='whitebox-gameness10-50-100.v4':raise ValueError('Only Gameness v4 may sync')
        pubpath=gameness.publication_path(workspace,identity);score=pub['gameness_score'];root=Path(pub['score_file']).parent
        if (root/'gameness_migration.json').exists():
            from . import gameness_v4_migration as migration
            receipt=migration.verify(root);migration.validate_parent(Path(receipt['parent_workspace']),identity)
        else:
            from . import gameness_v4 as policy
            # Only the exact accepted scoring judgments supply this publication.
            # Retained failed parent requests remain evidence, never score inputs.
            if pub.get('qualification_recovery'):
                from .persistent_original_pixel_recovery import verify_published_replacement
                proof=verify_published_replacement(root,pub)
                deliveries=[root/'requests'/name/'actual_delivery.json' for name in proof['task_names']]
            else:
                deliveries=gameness.acceptance_deliveries(root,scoring_policy=policy)
            from .gameness_v4_migration import verify_call
            for p in deliveries:
                verify_call(root,p.parent.name,runner.read(p))
        delivery=dict(qualified=True)
    else:raise ValueError('Unauthorized column')
    entry=runner.read(root/'input_manifest.json')['entry']
    if entry['id']!=identity or entry['method'] not in {'Astra','Opus','Sol','GLM','Kimi'} or entry['tier']!='S' or entry['actual_engine'] not in {'godot','three_js'}:
        raise ValueError('Publication outside authorized original S scope')
    # Bind to the newly frozen four-model source scope, independently of the
    # publication's immutable historical workspace.
    config=runner.read(workspace/'two_column_sync.json')
    inventory=scope.load(Path(config['scope_workspace']))
    row=next(r for r in inventory['entries'] if r['entry']['id']==identity)
    if not row['in_scope'] or not scope.same_original(entry,row['entry']):raise ValueError('Publication original differs from authorized source scope')
    if entry['method']=='Kimi':
        from .mechanic_v3_kimi_scope import verify_sources
        verify_sources(Path(config['scope_workspace']),row)
    profile=eval_models.publication_profile(root,column)
    if profile is not None:
        if pub.get('evaluation_model_profile')!=profile:
            raise ValueError('Publication does not bind its frozen evaluator profile')
        for name,digest in eval_models.binding(root).items():
            if pub['bindings'].get(name)!=digest:
                raise ValueError('Unbound evaluator profile')
    source=dict(entry={k:entry.get(k) for k in scope.FIELDS},source_hashes=row['source_hashes'])
    source_sha=hashlib.sha256(json.dumps(source,sort_keys=True).encode()).hexdigest()
    key=hashlib.sha256((identity+'\n'+source_sha).encode()).hexdigest()
    return key,dict(identity=identity,method=entry['method'],case_id=entry['case_id'],tier=entry['tier'],engine=entry['actual_engine'],
        project=entry['project'],source_sha256=source_sha,scope_binding=inventory['full_scope_binding'],columns={column:dict(
        score=score,protocol=pub['scoring_protocol'],revision=pub['contract_revision'],status=pub['status'],
        publication=str(pubpath),publication_sha256=sha(pubpath),workspace=str(workspace),
        **({'evaluation_model_profile':profile} if profile is not None else {}),
        **({'qualification_recovery':pub['qualification_recovery']} if pub.get('qualification_recovery') else {}))}),delivery


def merge_column(prior, incoming):
    """Select a higher Opus reassessment; preserve its exact frozen baseline."""
    history=prior.get('previous_publications',[])
    clean={k:v for k,v in prior.items() if k!='previous_publications'}
    profile=incoming.get('evaluation_model_profile')
    if incoming.get('qualification_recovery'):
        from .persistent_original_pixel_recovery import merge_published_original_pixel
        return merge_published_original_pixel(prior,incoming)
    if clean==incoming and not profile:
        return prior
    if (not profile or not profile.get('independent_reassessment')
            or profile.get('roles')!={'static':eval_models.DEFAULT,'planner':eval_models.ASTRA,'judge':eval_models.ASTRA}):
        raise ValueError('Existing complete column differs; explicit bound reassessment required')
    baseline=profile['baseline']
    if clean==incoming:
        if baseline not in history:
            raise ValueError('Reassessment must retain its exact frozen parent publication')
        if incoming['score']<=baseline['score']:
            # Reconcile a completed publisher that loaded the former policy.
            older=history[:history.index(baseline)]
            return dict(baseline,previous_publications=older) if older else baseline
        return prior
    if baseline!=clean:
        raise ValueError('Reassessment must replace its exact frozen parent publication')
    if incoming['score']<=baseline['score']:
        return prior
    return dict(incoming,previous_publications=[*history,clean])


def sync(workspace,identity,column,*,workspace_locked=False):
    workspace=Path(workspace).resolve();config_path=workspace/'two_column_sync.json'
    if not config_path.exists():return dict(status='NOT_CONFIGURED')
    config=runner.read(config_path);target=Path(config['target']).resolve()
    if target!=TARGET:raise ValueError('Shared score target must match explicit user authorization')
    receipt_path=workspace/'sync_receipts'/(identity+'_'+column+'_'+str(time.time_ns())+'.json')
    publication=None
    try:
        with ExitStack() as stack:
            locks=[] if workspace_locked else [workspace/'.publication.lock']
            locks += [target.parent/'.targeted_publication.lock',target.parent/'.two_column_publication.lock']
            for path in locks:
                h=stack.enter_context(path.open('a+'));fcntl.flock(h,fcntl.LOCK_EX|fcntl.LOCK_NB)
            key,row,delivery=verified(workspace,identity,column);publication=row['columns'][column]
            evaluated_publication=publication
            selection_policy='HIGHER_ONLY' if publication.get('evaluation_model_profile') else 'ORIGINAL_PUBLICATION'
            namespace=config.get('namespace')
            registry=target.with_name('unity_m_mechanic_v3_gameness_v4_publications.json' if namespace=='unity-m-original-outcome-frame-v1' else 'mechanic_v3_gameness_v4_publications.json')
            state=runner.read(registry) if registry.exists() else dict(version=VERSION,rows={})
            if state['version']!=VERSION:raise ValueError('Unknown shared publication registry')
            current=state['rows'].get(key)
            if current:
                if {k:v for k,v in current.items() if k!='columns'}!={k:v for k,v in row.items() if k!='columns'}:raise ValueError('Source identity changed')
                prior=current['columns'].get(column)
                if prior:
                    publication=merge_column(prior,publication)
                    row['columns'][column]=publication
                row['columns']={**current['columns'],**row['columns']}
            if selection_policy=='HIGHER_ONLY':
                baseline=evaluated_publication['evaluation_model_profile']['baseline']
                if evaluated_publication['score']<=baseline['score'] or not current or not current['columns'].get(column):
                    baseline_key,baseline_row,_=verified(Path(baseline['workspace']),identity,column)
                    if (baseline_key!=key or baseline_row['columns'][column]!=baseline
                            or {k:v for k,v in baseline_row.items() if k!='columns'}!={k:v for k,v in row.items() if k!='columns'}):
                        raise ValueError('Retained baseline failed exact source/publication verification')
                    if not current or not current['columns'].get(column):
                        publication=merge_column(baseline,evaluated_publication)
                        row['columns'][column]=publication
                decision=('HIGHER_REASSESSMENT_SELECTED' if evaluated_publication['score']>baseline['score']
                          else 'BASELINE_RETAINED_NOT_HIGHER')
            else:
                decision='ORIGINAL_PUBLICATION_SELECTED'
            state['rows'][key]=row
            before=target.read_bytes();text=merge(before.decode(),state['rows'],namespace=namespace);after=text.encode()
            changed=after!=before
            if changed:
                archive=target.parent/'two_column_archives'/str(time.time_ns());archive.mkdir(parents=True)
                atomic(archive/'scores.md',before)
                if registry.exists():atomic(archive/registry.name,registry.read_bytes())
                if sha(target)!=hashlib.sha256(before).hexdigest():raise ValueError('Shared scores changed while merging')
                atomic(registry,(json.dumps(state,ensure_ascii=False,indent=2)+'\n').encode())
                atomic(target,after)
            receipt=dict(status='SYNCED',version=VERSION,identity=identity,column=column,publication=publication,
                target=str(target),before_sha256=hashlib.sha256(before).hexdigest(),after_sha256=sha(target),
                changed=changed,source_sha256=row['source_sha256'],delivery=delivery,time=runner.stamp(),
                selection_policy=selection_policy,decision=decision,evaluated_publication=evaluated_publication)
    except Exception as error:
        receipt=dict(status='SYNC_PENDING',identity=identity,column=column,target=str(target),publication=publication,
            error=repr(error),time=runner.stamp(),next_action='Preserve complete workspace publication; resolve specific lock/validation failure and sync only; do not rerun models')
    dump(receipt_path,receipt)
    return receipt


def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--workspace',type=Path,required=True);p.add_argument('--column',choices=['Mechanic','Gameness'],required=True);p.add_argument('--identities',nargs='+',required=True);args=p.parse_args(argv)
    failed=False
    for identity in args.identities:
        value=sync(args.workspace,identity,args.column);print(json.dumps({k:v for k,v in value.items() if k!='delivery'},ensure_ascii=False),flush=True);failed |= value['status']!='SYNCED'
    return int(failed)

if __name__=='__main__':raise SystemExit(main())
