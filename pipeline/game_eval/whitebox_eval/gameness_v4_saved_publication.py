"""Resume only a complete persisted v4 judge, without changing accepted evidence.

No source review, request, image, response, or score is regenerated. The current
original-check validators revalidate the actual accepted deliveries before publish.
"""
from pathlib import Path
from . import gameness_v4 as policy, gameness_v3_runtime as runtime
from . import gameness_v3_static as static, gameness_v3_original as original
from . import mechanic_v3_runner as runner, batch, mechanic_v3_full_scope as scope
from .codex import saved_model_response
from .gameness_v4_migration import verify_call
from .protocol import sha


def result_root(workspace, identity):
    """Use only an immutable verified publication to select a recovered take."""
    workspace = Path(workspace).resolve()
    publication = runtime.publication_path(workspace, identity)
    if not publication.exists():
        return workspace/'runs'/identity
    value = runtime.verify_publication(workspace, identity)
    score = Path(value['score_file']).resolve()
    root = score.parent
    if (not root.is_relative_to(workspace) or root.name != identity
            or root.parent.name != 'runs' or score.name != 'gameness_score.json'):
        raise ValueError('Published saved result is outside its workspace identity')
    return root


def revalidate(workspace,row):
    workspace=Path(workspace).resolve();root=result_root(workspace,row['entry']['id'])
    if runtime.workspace_policy(workspace).VERSION!=policy.VERSION:
        raise ValueError('Saved publication requires explicit original-check v4')
    entry=runner.read(root/'input_manifest.json')['entry']
    if not scope.same_original(row['entry'],entry):raise ValueError('Saved original identity differs')
    batch.verify_inputs(root)
    qualification=runner.read(root/'source_qualification.json')
    runtime.verify_bindings(qualification['source_bindings'])
    protocol=runtime.authored_rubric.protocol_for_run(root)
    from .gameness_v4_rubric import validate_protocol
    validate_protocol(workspace,entry['case_id'],protocol)
    folder=runtime.contract_dir(workspace,entry['case_id'])
    frozen=runner.read(folder/'frozen.json');contract=runner.read(folder/'contract.json')
    if sha(folder/'contract.json')!=frozen['contract_sha256']:
        raise ValueError('Frozen contract changed')
    runtime.verify_bindings(runner.read(folder/'source_binding.json')['bindings'])
    policy.validate_contract(protocol,contract)
    review=runner.read(root/'gameness_source_review.json')
    bound=runner.read(root/'gameness_source_review_binding.json')
    runtime.verify_bindings(bound['bindings'])
    if sha(Path(bound['path']))!=bound['sha256'] or runner.read(Path(bound['path']))!=review:
        raise ValueError('Saved source review changed')
    review_root=Path(bound['path']).parent
    manifest=runner.read(review_root/'source_manifest.json');rules=runner.read(review_root/'citation_rules.json')
    source_checks={};specs=policy.criteria(protocol)
    for start in range(0,len(specs),10):
        name=f'gameness_source_v1_{start//10+1:02d}'
        recovered=review.get('source_review_recoveries',{}).get(name)
        if recovered:
            if sha(Path(recovered['path']))!=recovered['sha256']:raise ValueError('Source correction changed')
            receipt=runner.read(Path(recovered['path']));runtime.verify_bindings(receipt['bindings'])
            name=runner.read(Path(recovered['path']).parent/'claim.json')['corrected_task']
        raw=runner.read(saved_model_response(review_root,name))
        static.validate(review_root,manifest,rules,contract,specs[start:start+10],raw)
        source_checks.update(raw['checks'])
    if source_checks!=review['checks']:raise ValueError('Saved source findings differ')
    runtime.acceptance_deliveries(root,scoring_policy=policy)
    checks={};deliveries=[]
    for path in sorted((root/'judgments').glob('gameness_v4_*.json')):
        judgment=runner.read(path);task=judgment['task'];response=saved_model_response(root,task)
        raw=runner.read(response)
        if raw!=judgment['raw'] or sha(response)!=judgment['response_sha256']:
            raise ValueError('Saved accepted runtime response changed')
        request=root/'requests'/task;actual=runner.read(request/'actual_delivery.json')
        if (sha(request/'actual_delivery.json')!=judgment['actual_delivery_sha256']
                or actual.get('source_review_sha256')!=sha(root/'gameness_source_review.json')
                or actual.get('scoring_protocol')!=policy.VERSION
                or actual.get('contract_sha256')!=frozen['contract_sha256']):
            raise ValueError('Saved runtime delivery binding changed')
        verify_call(root,task,actual)
        selected=runner.read(request/'selected_manifest.json');citations=runner.read(request/'citation_rules.json')
        if {i['id'] for i in selected['items'] if i['type']=='source'}!={i['id'] for i in actual['complete_author_sources']}:
            raise ValueError('Saved runtime source delivery incomplete')
        chunk=[s for s in specs if s['id'] in judgment['checks']]
        derived=original.evaluate(root,protocol,selected,citations,contract,raw,chunk,review,scoring_policy=policy)
        if derived!=judgment['checks'] or set(checks)&set(derived):raise ValueError('Saved check mismatch or duplicate')
        checks.update(derived);deliveries.append(request/'actual_delivery.json')
    score=policy.aggregate(protocol,checks)
    if score!=runner.read(root/'gameness_score.json'):raise ValueError('Saved complete score differs')
    return root,score


def resume(workspace,row):
    root,score=revalidate(workspace,row)
    with runner.held(workspace,Path(row['source_batch']),native=False) as guard:
        runtime.publish(workspace,root,score,guard)
    return runtime.verify_publication(workspace,row['entry']['id'])
