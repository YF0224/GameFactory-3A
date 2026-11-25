"""Publish one independently audited result, retaining other rows and all prior bytes."""
from pathlib import Path
from collections import Counter, defaultdict
import argparse, copy, datetime, hashlib, json, os, re, sys, time
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from pipeline.game_eval.whitebox_eval import integrity
from pipeline.game_eval.whitebox_eval.protocol import COLUMNS, dump, sha


def read(path): return json.loads(path.read_text())
def encoded(value): return (json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode()


def diagnostic(score,proto):
    columns={column:None for column in COLUMNS}
    details={}
    by_id={r['id']:r for r in score['checks']}
    for col in COLUMNS:
        groups=defaultdict(list)
        for spec in proto['criteria']:
            if spec['column']==col:
                group=spec['group'] if col in {COLUMNS[1],'Gameness'} else 'column'
                groups[group].append(spec)
        result={}
        for group,specs in groups.items():
            observed=[s for s in specs if by_id[s['id']]['status'] in {'PASS','FAIL'}]
            denom=sum(s.get('atom_weight',1) for s in observed)
            num=sum(s.get('atom_weight',1) for s in observed if by_id[s['id']]['status']=='PASS')
            result[group]={'score':100*num/denom if denom else None,
                'weight':specs[0].get('endpoint_weight',1),
                'counts':dict(Counter(by_id[s['id']]['status'] for s in specs))}
        defined=[v for v in result.values() if v['score'] is not None]
        columns[col]=round(sum(v['score']*v['weight'] for v in defined)/sum(v['weight'] for v in defined),2) if defined else None
        details[col]={'score':columns[col],'groups':result,'defined_groups':len(defined),'all_groups':len(result)}
    total=round(sum(columns.values())/8,2) if all(v is not None for v in columns.values()) else None
    return columns,total,details


def replace_case(text,label,cells,status):
    pattern=r'^\| '+re.escape(label)+r' \|.*$'
    if len(re.findall(pattern,text,re.M))!=1: raise ValueError('Case row is not unique: '+label)
    return re.sub(pattern,'| '+label+' | '+' | '.join(cells+[status])+' |',text,flags=re.M)



def upsert_policy_row(text, label, replacement, *, allow_missing=False):
    """Add a newly used policy/tier to the existing progress table."""
    lines = text.splitlines(keepends=True)
    indices = [i for i, line in enumerate(lines) if line.startswith('| '+label+' |')]
    if len(indices) > 1:
        raise ValueError('Policy summary row is not unique: '+label)
    if indices:
        lines[indices[0]] = replacement+'\n'
        return ''.join(lines)
    headers = [i for i, line in enumerate(lines)
               if line.startswith('| ') and '正式有效/总数' in line and '诊断样本均分' in line]
    if not headers and allow_missing:
        return text
    if len(headers) != 1:
        raise ValueError('Expected one existing policy summary table')
    end = headers[0]+1
    while end < len(lines) and lines[end].startswith('|'):
        end += 1
    lines.insert(end, replacement+'\n')
    return ''.join(lines)


def protect_formal_row(text, label):
    rows = [line for line in text.splitlines() if line.startswith('| '+label+' |')]
    if len(rows) != 1:
        raise ValueError('Case row is not unique: '+label)
    cells = [cell.strip() for cell in rows[0].split('|')[1:-1]]
    if len(cells) >= 10 and re.fullmatch(r'\d+(?:\.\d+)?', cells[9]):
        raise ValueError('Existing formal table score protected: '+label)


def _main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--attempt',type=Path,required=True)
    parser.add_argument('--stage-only',action='store_true')
    args=parser.parse_args();a=args.attempt.resolve();b=a.parents[1]
    score=read(a/'scores.json');proto=read(a/'input/pilot_rubric.json');entry=read(a/'input_manifest.json')['entry']
    if score.get('valid') is not True:
        raise ValueError('Only a valid independently audited score may publish')
    audit=integrity.audit_run(a)
    dump(a/'formal_publication_audit.json',audit)
    if not audit['valid']: raise ValueError('Independent evidence audit failed')
    cleanup=read(a/'runtime/native_cleanup.json')
    if not all(cleanup.get(k) is True for k in ['input_cleanup','view_cleanup','process_cleanup']):
        raise ValueError('Cleanup is not complete')
    publication=read(b/'versioned_publications.json');previous=copy.deepcopy(publication)
    if entry['id'] in publication['entries']: raise ValueError('Already published; verify instead of replacing')
    policy=score['scoring_protocol'];tier=proto['planning_contract']['tier']
    model=entry['id'].split('__')[0]
    label=model+' / '+entry['case_id'].split('_')[0];status=f'JUDGED（{policy}；tiered-core-v1；{tier}；后台真实输入）'
    from .unity_delivery_disclosure import describe
    disclosure = describe(entry)
    if disclosure:
        status=status[:-1]+'；授权隔离修复交付）'
    from .pending_publication import authorized_pending, _registry, summary_rows
    pending=authorized_pending(a,b,score,entry)
    if pending is None:
        for name in ('scores.md','score_new.md'):
            protect_formal_row((b/name).read_text(),label)
    pending_registry=_registry(b)
    if pending is not None:
        pending_registry['entries'][entry['id']].update(status='AUDITED',audit_status='PASSED',
            audited_at=time.time(),audit_sha256=sha(a/'formal_publication_audit.json'))
    publication['entries'][entry['id']]={'attempt':str(a.relative_to(b)),'score_sha256':sha(a/'scores.json'),
        'scoring_protocol':policy,'tier':tier,'status':status}
    if disclosure:
        publication['entries'][entry['id']]['delivery_disclosure'] = disclosure
    formal_cells=[f"{score['columns'][c]['score']:.2f}" for c in COLUMNS]+[f"{score['overall_score']:.2f}"]
    diag_cols,diag_total,details=diagnostic(score,proto)
    diag_cells=['—' if diag_cols[c] is None else f'{diag_cols[c]:.2f}' for c in COLUMNS]+['—' if diag_total is None else f'{diag_total:.2f}']
    verify=read(b/'score_verify.provenance.json')
    if pending is not None:
        verify.get('pending_audit_entries',{}).pop(label,None)
    verify['entries'][label]={'columns':diag_cols,'total':diag_total,'mechanism':details['机制完整性'],
        'gameness':details['Gameness'],'score_path':str(a/'scores.json'),'score_sha256':sha(a/'scores.json'),
        'verdict_path':str(a/'rubric_verdicts.json'),'verdict_sha256':sha(a/'rubric_verdicts.json'),
        'pilot_path':str(a/'input/pilot_rubric.json'),'pilot_sha256':sha(a/'input/pilot_rubric.json'),
        'protocol':proto['version'],'scoring_protocol':policy,'tier':tier,'original_total':score['overall_score'],
        'source_kind':'正式 effective 来源；后台真实输入','source_status':'JUDGED',
        'missing_columns': {col:'No verified PASS/FAIL observations; UNVERIFIED is excluded, not zero' for col in COLUMNS if diag_cols[col] is None},
        'evidence_limitations':'verified-only uses full-rubric PASS/FAIL and excludes UNVERIFIED; formal mechanism tiers remain separate'}
    verify['updated_at']=datetime.datetime.now().astimezone().isoformat()
    verify['source_score_count']=len(verify['entries'])
    verify['diagnostic_total_count']=sum(row.get('total') is not None for row in verify['entries'].values())
    astra_diags=[row['total'] for key,row in verify['entries'].items()
                 if key.startswith(model+' / ') and row.get('total') is not None]
    verify['methods'][model].update(valid=len(astra_diags),
        diagnostic_mean=round(sum(astra_diags)/len(astra_diags),2) if astra_diags else None)
    previous_fingerprint=verify['source_fingerprint']
    verify['source_fingerprint']=hashlib.sha256(encoded({key:{field:row.get(field)
        for field in ['score_sha256','verdict_sha256','pilot_sha256']} for key,row in verify['entries'].items()})).hexdigest()
    verify.setdefault('targeted_updates',[]).append({'entry':entry['id'],'attempt':str(a),
        'previous_source_fingerprint':previous_fingerprint,'publisher':str(Path(__file__).resolve()),
        'publisher_sha256':sha(Path(__file__)),'raw_and_historical_sources_preserved':True})
    payloads={}
    # Recompute only the selected policy/tier rows, never the historical policy means.
    selected=[(key,v) for key,v in publication['entries'].items() if v['scoring_protocol']==policy and v['tier']==tier]
    def policy_row(method):
        group=[(key,v) for key,v in selected if method=='全部' or key.startswith(method+'__')]
        vals=[];diags=[]
        for key,v in group:
            path=b/v['attempt']/'scores.json'
            if sha(path)!=v['score_sha256']: raise ValueError('Published source changed: '+key)
            vals.append(read(path)['overall_score'])
            short=key.split('__')[0]+' / '+key.split('__')[1].split('_')[0]
            row=verify['entries'].get(short,{})
            if row.get('total') is not None: diags.append(row['total'])
        return f"| {method} / {policy} / {tier} | — | — | {len(vals)} | {sum(vals)/len(vals):.2f} | {len(diags)} | "+(f'{sum(diags)/len(diags):.2f}' if diags else '—')+' |'
    policy_summaries=verify.setdefault('policy_tier_summaries',{})
    for method in (model,'全部'):
        group=[(key,v) for key,v in selected if method=='全部' or key.startswith(method+'__')]
        values=[read(b/v['attempt']/'scores.json')['overall_score'] for _,v in group]
        diagnostics=[verify['entries'].get(key.split('__')[0]+' / '+key.split('__')[1].split('_')[0],{}).get('total') for key,_ in group]
        diagnostics=[value for value in diagnostics if value is not None]
        policy_summaries[method+' / '+policy+' / '+tier]={
            'formal_count':len(values),'formal_mean':round(sum(values)/len(values),2),
            'verified_only_count':len(diagnostics),
            'verified_only_mean':round(sum(diagnostics)/len(diagnostics),2) if diagnostics else None}
    for name in ['scores.md','score_new.md','final_report.md','score_verify.md']:
        text=(b/name).read_text()
        text=replace_case(text,label,diag_cells if name=='score_verify.md' else formal_cells,
            status+('；verified-only诊断'+('完整' if diag_total is not None else '缺列') if name=='score_verify.md' else ''))
        if pending is not None:
            text=summary_rows(text,pending_registry,model,policy,tier)
        for method in [model,'全部']:
            text=upsert_policy_row(text,method+' / '+policy+' / '+tier,policy_row(method),
                allow_missing=name=='final_report.md')
        # An exact pending row is already a visible scored result. Audit only
        # changes its qualification; it must not increment scored totals twice.
        if pending is None:
            text=re.sub(r'已出分 \*\*(\d+)/300\*\*，尚无成绩 \*\*(\d+)\*\*',
                lambda m:f'已出分 **{int(m[1])+1}/300**，尚无成绩 **{int(m[2])-1}**',text)
        text=re.sub(r'可计算 verified 诊断总分 \*\*\d+/300\*\*',
            f"可计算 verified 诊断总分 **{verify['diagnostic_total_count']}/300**",text)
        if name=='scores.md':
            starts=[i for i,line in enumerate(text.splitlines()) if line.startswith('|') and (i==0 or not text.splitlines()[i-1].startswith('|'))]
            if len(starts)!=2: raise ValueError('scores.md must retain exactly two tables')
        old_case_rows=[line for line in (b/name).read_text().splitlines() if re.match(r'^\| (?:Astra|Opus|Sol|GLM|Kimi) / G\d+ \|',line) and not line.startswith('| '+label+' |')]
        new_case_rows=[line for line in text.splitlines() if re.match(r'^\| (?:Astra|Opus|Sol|GLM|Kimi) / G\d+ \|',line) and not line.startswith('| '+label+' |')]
        if old_case_rows!=new_case_rows: raise ValueError('Unrelated score row changed: '+name)
        payloads[name]=text.encode()
    payloads['versioned_publications.json']=encoded(publication)
    if pending is not None:
        payloads['pending_audits.json']=encoded(pending_registry)
    payloads['score_verify.provenance.json']=encoded(verify)
    summary=read(b/'summary.json');oldrows=copy.deepcopy(summary['entries']);found=0
    from pipeline.game_eval.whitebox_eval.reporting import capture_details
    for row in summary['entries']:
        if row['id']!=entry['id']: continue
        found+=1
        if row['valid']: raise ValueError('Previous effective score must be preserved')
        row.update(status='JUDGED',recorded_status='JUDGED',reason=None,valid=True,
            columns=score['columns'],overall_score=score['overall_score'],run=str(a),scores=str(a/'scores.json'),
            rubric_verdicts=str(a/'rubric_verdicts.json'),evidence_manifest=str(a/'evidence_manifest.json'),
            evidence_audit=str(a/'formal_publication_audit.json'),harness_error=None,frame_excluded=False,
            citation_excluded=False,status_reclassification=None,recording=capture_details(a))
    if found!=1: raise ValueError('Expected one summary row')
    if [r for r in oldrows if r['id']!=entry['id']]!=[r for r in summary['entries'] if r['id']!=entry['id']]:
        raise ValueError('Unrelated summary row changed')
    rows=summary['entries'];summary.update(valid_count=sum(r['valid'] for r in rows),remaining_count=sum(not r['valid'] for r in rows),
        status_counts=dict(Counter(r['status'] for r in rows)),invalid_cases=[r for r in summary['invalid_cases'] if r['id']!=entry['id']])
    from pipeline.game_eval.whitebox_eval.recovery_publish import _model_totals
    summary['methods']=_model_totals(rows,summary['methods'],set(summary['common_case_set']))
    payloads['summary.json']=encoded(summary)
    manifest=read(b/'run_manifest.json')
    for row in manifest['runs']:
        if row['id']!=entry['id']:continue
        selected_row=next(r for r in rows if r['id']==entry['id']);row.update(selected_row)
        for item in row.get('attempts',[]):item['active']=False
        row.setdefault('attempts',[]).append({'path':str(a),'active':True,'status':read(a/'status.json')})
    manifest.update(valid_count=summary['valid_count'],methods=summary['methods'])
    payloads['run_manifest.json']=encoded(manifest)
    revision=b/'effective_revisions'/('targeted_'+entry['id']+'_'+str(time.time_ns()));revision.mkdir(parents=True)
    before={name:sha(b/name) if (b/name).exists() else None for name in payloads}
    for name,body in payloads.items():
        if (b/name).exists():(revision/('before_'+name)).write_bytes((b/name).read_bytes())
        (revision/name).write_bytes(body)
    dump(revision/'changes.json',{'scope':entry['id'],'before_sha256':before,
        'after_sha256':{n:sha(revision/n) for n in payloads},'attempt':str(a),'score_sha256':sha(a/'scores.json'),
        'other_publications_preserved':all(publication['entries'][k]==v for k,v in previous['entries'].items())})
    for name,expected in before.items():
        if (sha(b/name) if (b/name).exists() else None)!=expected:raise ValueError('Concurrent publication changed '+name)
    if args.stage_only:
        print(json.dumps({'staged':True,'revision':str(revision),'attempt':str(a),'files':list(payloads)}));return
    for name,body in payloads.items():
        temp=b/(name+'.targeted.tmp');temp.write_bytes(body);os.replace(temp,b/name)
    from pipeline.game_eval.whitebox_eval.effective import resolve_result
    result=resolve_result(b,entry)
    if not result['valid'] or result['root']!=a: raise ValueError('Published effective result failed verification')
    dump(a/'formal_publication_receipt.json',{'published':True,'revision':str(revision),'score':score['overall_score'],
        'effective_status':result['status'],'verified_only_total':diag_total,'at':time.time()})
    print(json.dumps({'published':True,'score':score['overall_score'],'diagnostic_total':diag_total,'revision':str(revision)}))

def main(argv=None):
    import fcntl
    import contextlib
    old=sys.argv
    if argv is not None: sys.argv=[__file__,*map(str,argv)]
    try:
        parser=argparse.ArgumentParser(add_help=False)
        parser.add_argument('--attempt',type=Path,required=True)
        known,_=parser.parse_known_args()
        with (known.attempt.resolve().parents[1]/'.targeted_publication.lock').open('a+') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            _main()
    finally:
        sys.argv=old

if __name__=='__main__':main()
