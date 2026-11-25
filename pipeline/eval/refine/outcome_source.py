"""Independent source-existence review for the opt-in grouped outcome policy.

Legacy full-spec static responses, native records and original result files remain
immutable. Derived results bind the new source review and recompute the same
runtime gates, so source existence never manufactures runtime success.
"""
from pathlib import Path
import argparse
import json
from .common import read,dump,sha,once
from .session import inventory
from .evaluation import STATIC,require_checks
from .scoring import static_credit,reference
from .source_citations import normalize
from .outcome_groups import VERSION,POLICY,gameplay_source_bundle,judge_result
from . import evidence
from ..stage1.codex import call_codex,validate_schema


def ref(path):
    path=Path(path).resolve()
    return {'path':str(path),'sha256':sha(path)}


def validate_review(parent,tasks,value):
    validate_schema(value,STATIC)
    require_checks(value,tasks)
    for row in value['checks']:
        cited=row['implementation_refs']+row['entry_refs']
        if any(not r['path'].startswith('project/') or not reference(Path(parent)/'input',r) for r in cited):
            raise ValueError('Outcome source review requires valid original source citations')
        if row['implemented'] and not static_credit(Path(parent)/'input',row):
            raise ValueError('Implemented source needs actual implementation and entry binding')


def reconcile(parent,review):
    parent=Path(parent);root=parent/'outcome_groups'
    original=read(root/'report.json');revision=read(root/'revision.json')
    tasks=[t for group in revision['groups'] for t in group['tasks']]
    validate_review(parent,tasks,review)
    codes={r['task_id']:static_credit(parent/'input',r) for r in review['checks']}
    source_rows={r['task_id']:r for r in review['checks']}
    report={'version':VERSION,'source_policy':POLICY,'source_review':ref(parent/'outcome_source.json'),
            'parent_report':ref(root/'report.json'),'groups':{},'formal_whitebox_score':None,
            'note':'Derived source-existence correction; all original results and failed attempts preserved; semantic audit pending.'}
    by_group={g['id']:g for g in revision['groups']}
    for name,old in original['groups'].items():
        folder=root/name
        if old['status'] not in ('SCORED_PENDING_AUDIT','SOURCE_ONLY_PENDING_RUNTIME','BLOCKED_TRUE_MULTIPLAYER'):
            report['groups'][name]=old;continue
        if read(folder/'result.json')!=old:raise ValueError('Original published group result differs')
        result={**old,'original_result':ref(folder/'result.json'),'source_review':report['source_review']}
        if old['status']=='SCORED_PENDING_AUDIT':
            manifest=read(folder/'evidence/manifest.json');evidence.verify_manifest(folder,manifest)
            if sha(folder/'judge.json')!=old['judge_sha256']:
                raise ValueError('Previously published runtime judge changed')
            judged=read(folder/'judge.json')
            checks=judge_result(folder,by_group[name]['tasks'],judged['checks'],codes,
                                read(folder/'evidence/judge_delivery.json'))
            # A new source decision cannot upgrade 50/100 or invent native execution.
            current_by_id={c['task_id']:c for c in checks}
            for previous in old['checks']:
                if previous['credit_percent'] in (50,100) and current_by_id[previous['task_id']]['credit_percent']!=previous['credit_percent']:
                    raise ValueError('Source reconciliation changed a runtime tier')
        else:
            checks=[]
            for previous in old['checks']:
                ident=previous['task_id'];code=10 if codes[ident] else 0
                check={**previous,'static_credit_percent':code,'source_reason':source_rows[ident]['binding_explanation']}
                if old['status']=='SOURCE_ONLY_PENDING_RUNTIME':check['credit_percent']=code
                checks.append(check)
        for c in checks:c['source_evidence']=source_rows[c['task_id']]
        result['checks']=checks
        dest=folder/'result_source_001.json'
        if dest.exists() and read(dest)!=result:raise ValueError('Conflicting source-derived result')
        dump(dest,result)
        dump(folder/'audit_source_001.json',{'status':'TECHNICAL_GATES_VERIFIED','semantic_audit':'PENDING',
            'original_result':result['original_result'],'source_review':report['source_review'],'result':ref(dest)})
        report['groups'][name]=result
    dump(root/'report_source_001.json',report)
    dump(root/'active_report.json',ref(root/'report_source_001.json'))
    lines=['# G008 grouped outcome evaluation','',
        'Mechanic/Gamefeel only. Independent refined-candidate evaluation; all scored results are unaudited.',
        '10% = valid wired source; 50% = observed basic normal function; 100% = native result proves core intent.',
        'Source-only, native-judged and true-multiplayer blocks are reported separately. No eight-column total.','',
        '| Group | Task | Source | Proved tier | Status | Reason |','|---|---|---:|---:|---|---|']
    for name,result in report['groups'].items():
        for c in result.get('checks',[]):
            score=c.get('credit_percent');reason=c.get('reason',result.get('reason','')).replace('|','/').replace('\n',' ')
            lines.append(f"| {name} | {c['task_id']} | {c.get('static_credit_percent','—')}% | {str(score)+'%' if score is not None else '—'} | {result['status']} | {reason} |")
    (root/'report.md').write_text('\n'.join(lines)+'\n')
    return report


def run(output):
    from .batch import exclusive,code_identity
    from .migration import verify_migration
    output=Path(output).resolve()
    with exclusive(output.parent/(output.name+'.batch.lock')):
        verify_migration(output,code_identity())
        inv=read(output/'inventory.json')
        if len(inv['games'])!=1:raise ValueError('Single frozen candidate required')
        parent=output/'games'/inv['games'][0]['game_id']
        revision=read(parent/'outcome_groups/revision.json')
        if revision['version']!=VERSION:raise ValueError('Wrong outcome revision')
        tasks=[t for group in revision['groups'] for t in group['tasks']]
        frozen=read(parent/'input/source_manifest.json')['files']
        if inventory(parent/'input/project')!=frozen:raise ValueError('Frozen author source changed')
        bundle,delivery=gameplay_source_bundle(parent)
        dump(parent/'outcome_groups/outcome_source_delivery.json',delivery)
        sol=read(output/'configuration.json')['sol']
        def invoke():
            prompt=('Review ONLY source existence for this new frozen outcome policy. '+POLICY+
                '\nimplemented=true means core implementation exists AND is actually wired to the original gameplay entry. '
                'It does NOT mean every pass_condition, timing, precision, boundary, animation detail or runtime outcome passed. '
                'Partial but valid wired core implementation receives source credit; names/comments/placeholders alone do not. '
                'Do not inherit the old full-spec implemented=false. Do not assume any runtime result. '
                'Preserve exact frozen task IDs once each. Give implementation_refs AND entry_refs for true implementation, '
                'paths project/... with actual SHA, original physical line and a literal nonempty single-line substring. '
                'No edits, engine invocation or fabricated citations.\n'+json.dumps(tasks,ensure_ascii=False)+'\nAUTHOR SOURCE\n'+bundle)
            def valid(value):
                dump(parent/'outcome_source.json',value)
                normalized=normalize(parent,'outcome_source',value)
                validate_review(parent,tasks,normalized)
            value=call_codex(parent,name='outcome_source',prompt=prompt,schema=STATIC,model=sol['model'],
                executable=sol.get('executable','codex'),timeout=900,max_attempts=1,
                response_validator=valid,explicit_stdin_separator=True)
            dump(parent/'outcome_source.json',value)
            return value
        value=once(parent,'outcome_source',invoke)
        normalized=normalize(parent,'outcome_source',value)
        validate_review(parent,tasks,normalized)
        dump(parent/'outcome_source_normalized.json',normalized)
        if inventory(parent/'input/project')!=frozen:raise ValueError('Source changed during review')
        return reconcile(parent,normalized)


def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    run(parser.parse_args(argv).output)

if __name__=='__main__':main()
