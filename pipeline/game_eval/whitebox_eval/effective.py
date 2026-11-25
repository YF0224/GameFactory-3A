"""One attempt, evidence audit and score selection for every batch consumer."""
from __future__ import annotations
import json
import math
import time
from pathlib import Path
from .protocol import COLUMNS, dump


def read(path):
    return json.loads(path.read_text())


def attempt_root(batch, entry):
    batch=Path(batch).resolve()
    pointer=batch/'active_attempts'/f"{entry['id']}.json"
    if not pointer.is_file():return batch/'runs'/entry['id']
    relative=read(pointer)['relative_path']
    if not isinstance(relative,str) or Path(relative).is_absolute():
        raise ValueError('attempt pointer must use a batch-relative path')
    root=(batch/relative).resolve()
    if not root.is_relative_to(batch):raise ValueError('attempt pointer escapes batch')
    return root


def current_audit(batch, entry, root, *, persist=False, force=False):
    from .integrity import VERSION, audit_for, audit_run
    audit=None if force else audit_for(batch,entry,root)
    if audit is None and (root/'scores.json').is_file():
        try:audit=audit_run(root)
        except (ValueError,KeyError,TypeError,OSError) as exc:
            audit={'version':VERSION,'source_run':str(root.resolve()),'valid':False,
                   'effective_status':'HARNESS_ERROR','reason':str(exc)}
        if persist:
            audit['id']=entry['id']
            folder=Path(batch)/'validation_audits'/entry['id']
            dump(folder/f'{time.time_ns()}.json',audit)
            dump(Path(batch)/'validation_audits'/f"{entry['id']}.json",audit)
    return audit


def resolve_result(batch, entry, *, persist_audit=False):
    from . import runtime
    from .batch import supported_entry
    batch=Path(batch).resolve();root=attempt_root(batch,entry)
    publication_path=batch/'versioned_publications.json'
    if publication_path.is_file():
        publication=read(publication_path).get('entries',{}).get(entry['id'])
        if publication:
            from .protocol import checked_path,sha
            score_path=checked_path(batch,publication['attempt']+'/scores.json')
            if sha(score_path)!=publication['score_sha256']:
                raise ValueError('versioned published score SHA mismatch')
            root=score_path.parent
            score=read(score_path)
            if score.get('scoring_protocol')!=publication['scoring_protocol'] or score.get('valid') is not True:
                raise ValueError('versioned published policy or validity mismatch')
            audit=current_audit(batch,entry,root,persist=persist_audit)
            if not audit or not audit.get('valid'):
                raise ValueError('versioned publication has no valid independent evidence audit')
            return {'root':root,'state':read(root/'status.json'),'recorded_status':'JUDGED',
                'status':'JUDGED','reason':None,'status_reclassification':None,'audit':audit,
                'score':score,'valid':True,'score_path':score_path,'publication':publication}
    baseline=batch/'effective_baseline.json'
    if baseline.is_file() and not (batch/'active_attempts'/f"{entry['id']}.json").exists():
        saved=read(baseline)['entries'].get(entry['id'])
        if saved:
            row=saved['row']
            selected=Path(row['scores'])
            score=read(selected) if selected.is_file() else None
            from .protocol import sha
            if score is not None and sha(selected)!=saved.get('score_sha256'):
                raise ValueError('preserved effective score SHA256 mismatch: '+entry['id'])
            if row['valid'] and (score is None or score.get('overall_score')!=row['overall_score'] or score.get('columns')!=row['columns']):
                raise ValueError('preserved effective score differs from published baseline')
            eligible=supported_entry(entry) and bool(entry.get('project')) and not entry.get('engine_mismatch')
            if eligible or not row['valid']:
                return {'root':Path(row['run']),'state':{'status':row['recorded_status']},
                    'recorded_status':row['recorded_status'],'status':row['status'],'reason':row.get('reason'),
                    'status_reclassification':row.get('status_reclassification'),'audit':None,
                    'score':score,'valid':row['valid'],'score_path':selected,'preserved_row':row,
                    'validation_scope':'preserved published baseline; not re-audited under new validator'}

    state=read(root/'status.json') if (root/'status.json').is_file() else {
        'status':'PENDING' if supported_entry(entry) else entry.get('status','PENDING')}
    recorded=state['status'];effective=recorded;reason=state.get('reason');reclassification=None
    if recorded=='BLOCKED_ENGINE_COLLECTOR' and reason:
        effective=runtime.collector_failure_status(reason)
        if effective!=recorded:
            reclassification={'from':recorded,'to':effective,
                'rule':'environment preflight failure is a harness error, not a missing collector',
                'raw_status_preserved':True}
    audit=current_audit(batch,entry,root,persist=persist_audit)
    # Delivery eligibility remains authoritative even if a historical take passes audit.
    if entry.get('engine_mismatch'):
        effective='ENGINE_MISMATCH_REVIEW'
        reason=reason or 'Delivered engine differs from required engine; no substitution.'
    elif not entry.get('project'):
        effective='DELIVERY_REVIEW_REQUIRED'
        reason=reason or 'Missing project marker requires delivery/location review, not a zero.'
    elif not supported_entry(entry):
        effective='BLOCKED_ENGINE_COLLECTOR';reason=reason or 'Unsupported engine collector'
    elif audit:
        effective='COMPLETE' if audit.get('valid') else audit.get('effective_status','HARNESS_ERROR')
        if audit.get('valid') and (root/'scores.json').is_file() and read(root/'scores.json').get('scoring_protocol') in {'whitebox-static10-runtime90.v1','whitebox-mechanic10-50-100.v1','whitebox-mechanic10-50-100.v2'}:
            effective='JUDGED'
        if not audit.get('valid'):
            reason=audit.get('reason') or json.dumps({
                'capture_issues':audit.get('capture',{}).get('issues',[]),
                'source_issues':audit.get('source_integrity',{}).get('issues',[]),
                'citation_failures':len(audit.get('citation_failures',[])),
                'verdicts_requiring_review':len(audit.get('verdicts_requiring_review',[]))},ensure_ascii=False)
    score=read(root/'scores.json') if (root/'scores.json').is_file() else None
    def numeric(v):
        return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) and 0<=v<=100
    valid=bool(effective in {'COMPLETE','JUDGED'} and audit and audit.get('valid') and score and score.get('valid') is True
        and numeric(score.get('overall_score'))
        and all(numeric(score.get('columns',{}).get(c,{}).get('score')) for c in COLUMNS)
        and not (root/'take_invalidated.json').exists())
    if effective in {'COMPLETE','JUDGED'} and not valid:
        effective='DELIVERY_REVIEW_REQUIRED'
        reason=(score or {}).get('invalid_reason') or 'Completed score missing/invalid or take invalidated'
    if not valid and not reason:reason=(score or {}).get('invalid_reason') or effective
    return {'root':root,'state':state,'recorded_status':recorded,'status':effective,
            'reason':reason,'status_reclassification':reclassification,
            'audit':audit,'score':score,'valid':valid,'score_path':root/'scores.json'}


def audit_effective(batch, entry):
    """Audit the selected source; retain explicit scope for historical publications."""
    from .protocol import sha
    selected=resolve_result(batch,entry,persist_audit=True)
    if 'preserved_row' not in selected:return selected['audit']
    row=selected['preserved_row']
    return {'version':'preserved-effective-baseline.v1','valid':selected['valid'],
        'effective_status':selected['status'],'source_run':str(selected['root']),
        'effective_score':str(selected['score_path']),
        'effective_score_sha256':sha(selected['score_path']) if selected['score_path'].is_file() else None,
        'validation_scope':selected['validation_scope'],'historical_audit':row.get('evidence_audit'),
        'rule':'published score source and hash checked; no claim of new raw-evidence validation'}
