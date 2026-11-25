"""Read-only revalidation of equivalent original-check trial judgments into v4.

Binary/independent/reduced rubrics are rejected. Parent requests, responses,
accepted markers and frame deliveries retain their original protocol identity.
No model is called and no accepted response is manufactured by this module.
"""
from __future__ import annotations
import argparse
import copy
import fcntl
import hashlib
from pathlib import Path
from . import evaluation_model_profile as eval_models
from . import gameness_v3 as parent_policy, gameness_v4 as policy
from . import gameness_v3_runtime as runtime, gameness_v3_original as original
from . import gameness_v3_static as static
from . import mechanic_v3_runner as runner
from .gameness_v4_rubric import validate_protocol
from .codex import saved_model_response
from .protocol import sha

VERSION = 'gameness-original-trial-to-v4.v1'


def save(path,value):
    if path.exists():
        if runner.read(path)!=value:raise ValueError('Retained migration artifact differs: '+str(path))
    else:runner.exclusive_json(path,value)


def verify_call(root,task,actual):
    """Audit the actual CLI and complete source delivery without editing parent."""
    from .gameness_v4_bounded_text import verify_delivery
    verify_delivery(root,task,actual)
    folder=root/'model_calls'/task
    if not (folder/'accepted_response.json').is_file():raise ValueError('Only accepted independent judgments may migrate')
    if actual.get('persistent_original_pixel_recovery'):
        return
    invocation=runner.read(folder/'invocation.json');cmd=invocation['command']
    submitted=[str(Path(cmd[i+1]).resolve()) for i,v in enumerate(cmd[:-1]) if v=='--image']
    expected=[str((root/r['path']).resolve()) for r in actual['images']]
    if invocation.get('exit_code')!=0 or submitted!=expected:
        raise ValueError('Original actual image delivery mismatch')
    if '--model' not in cmd or cmd[cmd.index('--model')+1]!=eval_models.model_for(root,'judge'):
        raise ValueError('Original judge model differs from frozen v4 model')
    if hashlib.sha256((folder/'prompt.txt').read_bytes()).hexdigest()!=actual['prompt_sha256']:
        raise ValueError('Original prompt SHA mismatch')
    for row in actual['images']:
        if sha(root/row['path'])!=row['sha256']:raise ValueError('Original image changed')
    for row in actual.get('complete_author_sources',[]):
        file=root/row['path']
        if sha(file)!=row['sha256'] or len(file.read_text(errors='replace').splitlines())!=row['line_count']:
            raise ValueError('Original complete author source changed')
    if not actual.get('all_predeclared_frames_delivered') or not actual.get('complete_author_sources'):
        raise ValueError('Incomplete original source/frame delivery')


def validate_parent(parent_workspace,identity):
    publication=runtime.verify_publication(parent_workspace,identity)
    if publication['scoring_protocol']!=parent_policy.VERSION:raise ValueError('Migration requires original v3 trial')
    root=Path(publication['score_file']).parent
    protocol=runtime.authored_rubric.protocol_for_run(root)
    policy.criteria(protocol)  # Reject reduced/reorganized criteria.
    review=runner.read(root/'gameness_source_review.json')
    source_binding=runner.read(root/'gameness_source_review_binding.json')
    runtime.verify_bindings(source_binding['bindings'])
    review_root=Path(source_binding['path']).parent
    if sha(Path(source_binding['path']))!=source_binding['sha256']:
        raise ValueError('Original source review changed')
    case=publication['case_id'];contract_folder=runtime.contract_dir(parent_workspace,case)
    contract=runner.read(contract_folder/'contract.json');parent_policy.validate_contract(protocol,contract)
    all_source_checks={}
    source_manifest=runner.read(review_root/'source_manifest.json')
    source_rules=runner.read(review_root/'citation_rules.json')
    for call in sorted((review_root/'model_calls').glob('gameness_source_v1_*')):
        if not (call/'accepted_response.json').is_file():continue
        raw=runner.read(saved_model_response(review_root,call.name));ids=set(raw['checks'])
        specs=[s for s in policy.criteria(protocol) if s['id'] in ids]
        static.validate(review_root,source_manifest,source_rules,contract,specs,raw)
        if ids & set(all_source_checks):raise ValueError('Duplicate original source review checks')
        all_source_checks.update(raw['checks'])
    if all_source_checks!=review['checks']:raise ValueError('Incomplete/mismatched original static findings')
    runtime.acceptance_deliveries(root)
    # Preserve the parent v3 contract bytes; adapt only its protocol tag in
    # memory when revalidating identical checks with the explicit v4 policy.
    equivalent_contract=copy.deepcopy(contract)
    equivalent_contract['protocol']=policy.VERSION
    policy.validate_contract(protocol,equivalent_contract)
    checks={};tasks=[]
    for path in sorted((root/'judgments').glob('gameness_v3_*.json')):
        judgment=runner.read(path);task=judgment['task']
        response=saved_model_response(root,task)
        raw=runner.read(response)
        if raw!=judgment['raw'] or sha(response)!=judgment['response_sha256']:
            raise ValueError('Original accepted response binding mismatch')
        folder=root/'requests'/task;actual=runner.read(folder/'actual_delivery.json')
        verify_call(root,task,actual)
        manifest=runner.read(folder/'selected_manifest.json');rules=runner.read(folder/'citation_rules.json')
        source_ids={i['id'] for i in manifest['items'] if i['type']=='source'}
        if source_ids!={i['id'] for i in actual['complete_author_sources']}:
            raise ValueError('Not every original source was actually delivered')
        specs=[s for s in policy.criteria(protocol) if s['id'] in judgment['checks']]
        derived=original.evaluate(root,protocol,manifest,rules,equivalent_contract,raw,specs,review,scoring_policy=policy)
        if derived!=judgment['checks'] or set(checks)&set(derived):
            raise ValueError('Original-to-v4 per-check semantics mismatch or duplicate')
        checks.update(derived);tasks.append((path,judgment))
    score=policy.aggregate(protocol,checks);parent=runner.read(root/'gameness_score.json')
    if {k:v for k,v in score.items() if k!='scoring_protocol'}!={k:v for k,v in parent.items() if k!='scoring_protocol'}:
        raise ValueError('Original-to-v4 score/weight semantics mismatch')
    return publication,root,protocol,contract_folder,contract,review,tasks,score


def verify(root):
    receipt=runner.read(root/'gameness_migration.json')
    if receipt['version']!=VERSION or receipt['scoring_protocol']!=policy.VERSION:
        raise ValueError('Invalid v4 migration identity')
    runtime.verify_bindings(receipt['bindings'])
    parent=runtime.verify_publication(Path(receipt['parent_workspace']),root.name)
    if parent['scoring_protocol']!=parent_policy.VERSION:
        raise ValueError('Migrated parent protocol changed')
    result=runner.read(root/'gameness_score.json')
    original_score=runner.read(Path(parent['score_file']))
    if {k:v for k,v in result.items() if k!='scoring_protocol'}!={k:v for k,v in original_score.items() if k!='scoring_protocol'}:
        raise ValueError('Migrated score differs from parent independent judgment')
    return receipt


def migrate(workspace,parent_workspace,identity,*,acceptance_case=False):
    workspace=workspace.resolve();parent_workspace=parent_workspace.resolve()
    if workspace==parent_workspace:raise ValueError('Preserve parent workspace')
    inventory=runtime.load(workspace)
    if runtime.workspace_policy(workspace).VERSION!=policy.VERSION:raise ValueError('Explicit v4 workspace required')
    if runtime.publication_path(workspace,identity).exists():
        publication=runtime.verify_publication(workspace,identity)
        if acceptance_case:runtime.accept_real_case(workspace,identity,runtime.production_bindings())
        return publication
    if not acceptance_case:runtime.production_gate(workspace,capability='equivalent_migration')
    before=runtime.production_bindings()
    rows={r['entry']['id']:r for r in inventory['entries'] if r['in_scope']}
    row=rows[identity];runner.disk(workspace,'gameness_v4_migration_revalidation',1024**3)
    lock=workspace/'locks'/('gameness_v4_'+identity+'.lock');lock.parent.mkdir(parents=True,exist_ok=True)
    with lock.open('a+') as handle:
        fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        parent,oldroot,protocol,oldfolder,oldcontract,review,tasks,score=validate_parent(parent_workspace,identity)
        validate_protocol(workspace,row['entry']['case_id'],protocol)
        if runtime.source_protocol(row,workspace)[0]!=protocol:
            # Capture metadata outside Gameness is not a new Gameness rubric.
            if policy.criteria(runtime.source_protocol(row,workspace)[0])!=policy.criteria(protocol):
                raise ValueError('Migration source identity/rubric differs')
        folder=runtime.contract_dir(workspace,row['entry']['case_id']);folder.mkdir(parents=True,exist_ok=True)
        contract=copy.deepcopy(oldcontract);contract['protocol']=policy.VERSION
        policy.validate_contract(protocol,contract)
        for name in ('frozen_protocol.json','source_binding.json'):
            save(folder/name,runner.read(oldfolder/name))
        save(folder/'contract.json',contract)
        if not (folder/'frozen.json').exists():
            save(folder/'frozen.json',dict(protocol=policy.VERSION,revision=policy.REVISION,case_id=row['entry']['case_id'],
                created=runner.stamp(),contract_sha256=sha(folder/'contract.json'),source_binding_sha256=sha(folder/'source_binding.json'),
                original_protocol_sha256=sha(folder/'frozen_protocol.json'),model=policy.MODEL,runtime_evidence_supplied=False,
                old_verdict_supplied=False,source_only_common_standard=True,
                migration=dict(parent_contract=str(oldfolder/'contract.json'),parent_contract_sha256=sha(oldfolder/'contract.json'),
                    parent_frozen=str(oldfolder/'frozen.json'),parent_frozen_sha256=sha(oldfolder/'frozen.json'),
                    change='Protocol identity only; all pre-runtime goals/bugs/contexts and original checks unchanged; no new contract model call')))
        source=Path(runner.read(oldroot/'source_qualification.json')['source'])
        root=runtime.prepare(workspace,row,source)
        for name in ('gameness_source_review.json','gameness_source_review_binding.json','gameness_coverage.json'):
            save(root/name,runner.read(oldroot/name))
        bindings=dict(parent['bindings'])
        for path in [runtime.publication_path(parent_workspace,identity),oldfolder/'contract.json',oldfolder/'frozen.json']:
            bindings[str(path)]=sha(path)
        for n,(path,judgment) in enumerate(tasks,1):
            task=f'gameness_v4_of1_{n:02d}_migrated';parent_task=judgment['task']
            original_delivery=oldroot/'requests'/parent_task/'actual_delivery.json'
            save(root/'requests'/task/'actual_delivery.json',runner.read(original_delivery))
            save(root/'judgments'/(task+'.json'),dict(protocol=policy.VERSION,task=task,raw=judgment['raw'],checks=judgment['checks'],
                actual_delivery_sha256=sha(root/'requests'/task/'actual_delivery.json'),response_path=judgment['response_path'],
                response_sha256=judgment['response_sha256'],migration=dict(parent_judgment=str(path),parent_judgment_sha256=sha(path),
                    actual_delivery_origin=str(original_delivery),actual_delivery_origin_sha256=sha(original_delivery),
                    notice='Original independent three-tier model call revalidated; no new invocation or delivery')))
        save(root/'gameness_score.json',score)
        save(root/'gameness_migration.json',dict(version=VERSION,scoring_protocol=policy.VERSION,parent_workspace=str(parent_workspace),
            parent_publication=str(runtime.publication_path(parent_workspace,identity)),bindings=bindings,
            verification='Every original source review/physical reference, runtime accepted response, actual image/source delivery, per-check credit and group weight revalidated',
            model_recalled=False,new_recording=False,new_judgment=False,score_changed=False,
            semantic_equivalence='Only protocol version identity changes from original-check outcome-frame v3 trial to v4; all original criteria and evidence gates identical'))
        verify(root)
        with runner.held(workspace,Path(row['source_batch']),native=False) as guard:
            runtime.publish(workspace,root,score,guard)
        if acceptance_case:runtime.accept_real_case(workspace,identity,before)
        return runtime.verify_publication(workspace,identity)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace',type=Path,required=True)
    parser.add_argument('--parent-workspace',type=Path,required=True)
    parser.add_argument('--identity',required=True)
    parser.add_argument('--acceptance-case',action='store_true')
    args=parser.parse_args(argv)
    migrate(args.workspace,args.parent_workspace,args.identity,acceptance_case=args.acceptance_case)
    return 0


if __name__=='__main__':raise SystemExit(main())
