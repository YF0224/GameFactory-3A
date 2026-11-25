"""Targeted recovery publication; historical rows and score sources remain intact."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import time
from collections import Counter
from pathlib import Path

from .protocol import COLUMNS, dump, sha

VERSION = 'whitebox-targeted-recovery-publication.v1'


def clone_attempt(old, root):
    """Copy a historical take; archive inherited state without changing its source."""
    old=Path(old);root=Path(root)
    if root.exists():raise ValueError('new attempt already exists')
    shutil.copytree(old,root)
    archive=root/'inherited_attempt'
    files=[]
    for name in ('status.json','harness_error.json','scores.json','partial_scores.json','rubric_verdicts.json',
                 'attempt_manifest.json','report.md','checks.json','engine_result.json','execution.json',
                 'engine_result.validation.json','execution.validation.json','validation_history'):
        source=root/name
        if not source.exists():continue
        if source.is_file():files.append({'path':name,'sha256':sha(source)})
        else:
            files += [{'path':str(p.relative_to(root)),'sha256':sha(p)} for p in source.rglob('*') if p.is_file()]
        archive.mkdir(exist_ok=True)
        shutil.move(str(source),str(archive/name))
    inherited=archive/'attempt_manifest.json'
    manifest=json.loads(inherited.read_text()) if inherited.is_file() else {}
    manifest.update(attempt_id=root.name,previous_attempt=str(old),phase='judge_only_recovery',created_unix=time.time())
    dump(root/'attempt_manifest.json',manifest)
    dump(root/'recovery_attempt.json',{'version':VERSION,'source_attempt':str(old.resolve()),
         'operation':'judge only; unchanged historical capture and gameplay budget',
         'created_unix':time.time(),'inherited_files':files})


def freeze_baseline(batch):
    """Explicit compatibility snapshot; does not claim a new audit of prior scores."""
    batch=Path(batch)
    target=batch/'effective_baseline.json'
    if target.exists():return
    source=batch/'summary.json'
    data=json.loads(source.read_text())
    entries={}
    for row in data['entries']:
        selected=Path(row['scores'])
        entries[row['id']]={'row':copy.deepcopy(row),'score_sha256':sha(selected) if selected.is_file() else None}
    dump(target,{'version':VERSION,'source_summary_sha256':sha(source),
        'validation_scope':'previously published baseline retained, not a new evidence audit',
        'entries':entries})


def _model_totals(rows, previous, common):
    from .batch import formal_first10_mean
    result={}
    for method in previous:
        group=[r for r in rows if r['method']==method];got=[r for r in group if r['valid']]
        counts=Counter(r['status'] for r in group);failures=Counter()
        for row in group:
            if not row['valid']:failures[row.get('reason') or row['status']]+=1
            for failure in row.get('failure_reasons',[]):failures[failure['reason']]+=failure['count']
        t=copy.deepcopy(previous[method])
        t.update(completed=len(got),valid_count=len(got),expected=len(group),
            harness_error_count=counts['HARNESS_ERROR'],blocked_count=sum(n for k,n in counts.items() if k.startswith('BLOCKED')),
            delivery_review_count=counts['DELIVERY_REVIEW_REQUIRED']+counts['DELIVERY_REVIEW'],engine_mismatch_count=counts['ENGINE_MISMATCH_REVIEW'],
            incomplete_count=len(group)-len(got),status_counts=dict(counts),mean_first10=formal_first10_mean(group),
            mean_selected_cases=round(sum(r['overall_score'] for r in got)/len(got),2) if got and len(got)==len(group) else None,
            partial_mean_diagnostic_only=round(sum(r['overall_score'] for r in got)/len(got),2) if got else None,
            diagnostic_case_set=[r['case_id'] for r in got],invalid_cases=[r['id'] for r in group if not r['valid']],
            main_failure_reasons=[{'reason':k,'count':v} for k,v in failures.most_common(5)])
        relevant=[r for r in group if r['case_id'] in common]
        t['mean_common_cases']=round(sum(r['overall_score'] for r in relevant)/len(common),2) if common and len(relevant)==len(common) and all(r['valid'] for r in relevant) else None
        result[method]=t
    return result


def _commit_revision(batch, revision):
    """Resume a staged report transaction only if every byte is known."""
    record=json.loads((revision/'changes.json').read_text())
    for name,expected in record['after_hashes'].items():
        if sha(revision/name)!=expected:raise ValueError('staged publication SHA256 mismatch')
        current=sha(batch/name) if (batch/name).is_file() else None
        if current not in {record['before_hashes'][name],expected}:
            raise ValueError('concurrent report writer detected; staged publication retained')
    for name,expected in record['after_hashes'].items():
        if (batch/name).is_file() and sha(batch/name)==expected:continue
        temp=batch/(name+'.recovery.tmp');shutil.copyfile(revision/name,temp);os.replace(temp,batch/name)
    result=json.loads((batch/'summary.json').read_text())
    dump(batch/'effective_results.json',{'version':VERSION,'revision':str(revision.relative_to(batch)),
        'entries':{r['id']:{'run':r['run'],'scores':r['scores'],'status':r['status'],'valid':r['valid']} for r in result['entries']},
        'report_hashes':record['after_hashes']})
    dump(revision/'committed.json',{'version':VERSION,'completed_unix':time.time(),'report_hashes':record['after_hashes']})
    return result


def refresh_selected(batch):
    """Update selected pointers only; append successful changes and preserve all old rows."""
    from .batch import read
    from .effective import resolve_result
    from .reporting import capture_details, outcome_counts
    batch=Path(batch).resolve()
    if not (batch/'effective_baseline.json').is_file():raise ValueError('freeze the published baseline first')
    for pending in sorted((batch/'effective_revisions').glob('*')):
        if (pending/'changes.json').is_file() and not (pending/'committed.json').is_file():
            _commit_revision(batch,pending)
    previous=read(batch/'summary.json');baseline=read(batch/'effective_baseline.json')
    rows=[];changes=[]
    for entry in read(batch/'inventory.json')['entries']:
        selected=resolve_result(batch,entry,persist_audit=False)
        old=next(r for r in previous['entries'] if r['id']==entry['id'])
        if 'preserved_row' in selected:
            row=copy.deepcopy(selected['preserved_row'])
        else:
            if not selected['valid']:raise ValueError('selected recovery failed audit: '+entry['id'])
            if baseline['entries'][entry['id']]['row']['valid']:
                raise ValueError('targeted recovery cannot replace an existing valid score')
            root=selected['root'];score=selected['score'];failures=Counter()
            for check in score.get('checks',[]):
                if check.get('status') in {'FAIL','UNVERIFIED'}:failures[f"{check['status']}: {check.get('reason') or check['id']}"]+=1
            row=copy.deepcopy(old)
            row.update(status='COMPLETE',recorded_status='COMPLETE',reason=None,valid=True,failure_label=None,
                status_reclassification=None,columns=score['columns'],overall_score=score['overall_score'],
                evidence_audit=str(root/'recovery_audit.json'),frame_excluded=False,citation_excluded=False,
                failure_reasons=[{'reason':k,'count':v} for k,v in failures.most_common(5)],run=str(root),
                scores=str(selected['score_path']),rubric_verdicts=str(root/'rubric_verdicts.json'),
                evidence_manifest=str(root/'evidence_manifest.json'),harness_error=None,recording=capture_details(root),
                recovery={'version':VERSION,'source_attempt':baseline['entries'][entry['id']]['row']['run'],
                    'scoring_protocol':score['scoring_protocol'],'gameplay_budget':'unchanged historical capture',
                    'score_sha256':sha(selected['score_path'])})
            dump(root/'recovery_audit.json',selected['audit'])
        rows.append(row)
        if row!=old:changes.append({'id':entry['id'],'before':old,'after':row})
    if not changes:return previous
    for item in changes:
        if item['before']['valid']:raise ValueError('valid baseline row would change')
    result=copy.deepcopy(previous);result['entries']=rows
    result['methods']=_model_totals(rows,previous['methods'],set(previous.get('common_case_set',[])))
    result.update(valid_count=sum(r['valid'] for r in rows),remaining_count=sum(not r['valid'] for r in rows),
        status_counts=dict(Counter(r['status'] for r in rows)),
        invalid_cases=[{'id':r['id'],'status':r['status'],'reason':r.get('reason'),'run':r['run']} for r in rows if not r['valid']],
        frame_excluded_cases=[r['id'] for r in rows if r['frame_excluded']],citation_excluded_cases=[r['id'] for r in rows if r['citation_excluded']],
        outcome_classification=outcome_counts(rows))
    marker=hashlib.sha256(json.dumps(changes,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    revision=batch/'effective_revisions'/marker
    if revision.exists():raise ValueError('unfinished publication exists; inspect staged revision')
    revision.mkdir(parents=True)
    appendix=['',f'<!-- recovery:{marker} -->','',f'## 定向恢复 {time.strftime("%Y-%m-%d %H:%M:%S")}','',
        '历史条目保留；以下为新的有效 attempt。旧录制沿用历史 gameplay 预算，尚未按 300/600 秒重录。',
        '', '| Method / Case | '+' | '.join(COLUMNS+['总分','状态','有效来源'])+' |','|---|'+'---|'*11]
    for change in changes:
        row=change['after'];cells=[f"{row['columns'][c]['score']:.2f}" for c in COLUMNS]
        appendix.append('| '+row['method']+' / '+row['case_id'].split('_')[0]+' | '+' | '.join(cells+[f"{row['overall_score']:.2f}",'COMPLETE',row['scores']])+' |')
    appendix += ['', '| 模型 | 有效/总数 | 诊断均值（非正式） |','|---|---|---|']
    for method,t in result['methods'].items():
        mean=t['partial_mean_diagnostic_only'];appendix.append(f"| {method} | {t['valid_count']}/{t['expected']} | {mean if mean is not None else '—'} |")
    appendix += ['', '各模型有效样本集合可能不同，诊断均值不构成同集合正式排名。', '']
    suffix='\n'.join(appendix).encode()
    payloads={'summary.json':(json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode()}
    for name in ('scores.md','final_report.md'):
        p=batch/name
        payloads[name]=(p.read_bytes() if p.exists() else b'')+suffix
    manifest=read(batch/'run_manifest.json') if (batch/'run_manifest.json').is_file() else {'runs':[]}
    by_id={r['id']:r for r in rows}
    for index,old in enumerate(manifest['runs']):
        if any(c['id']==old['id'] for c in changes):
            updated=copy.deepcopy(old);updated.update(by_id[old['id']]);updated['attempts']=old.get('attempts',[])+[{'path':updated['run'],'active':True,'status':{'status':'COMPLETE'}}]
            for attempt in updated['attempts']:attempt['active']=attempt['path']==updated['run']
            manifest['runs'][index]=updated
    manifest.update(valid_count=result['valid_count'],methods=result['methods'])
    payloads['run_manifest.json']=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode()
    before={name:sha(batch/name) if (batch/name).is_file() else None for name in payloads}
    for name,content in payloads.items():
        if (batch/name).exists():shutil.copyfile(batch/name,revision/('before_'+name))
        (revision/name).write_bytes(content)
    dump(revision/'changes.json',{'version':VERSION,'changes':changes,'before_hashes':before,
        'after_hashes':{name:sha(revision/name) for name in payloads}})
    return _commit_revision(batch,revision)
