"""Complete v4 static review of one proven same-run omitted author file.

Keep the failed eleven-source review immutable. A fixed parent-bound continuation
reviews all twelve sources, with no reuse of incomplete static findings.
"""
from pathlib import Path
import copy
from . import mechanic_v3_original_material_recovery as material
from . import mechanic_v3_runner as runner, qualified_history
from . import gameness_v3_static as static, gameness_v4 as policy
from .protocol import sha

VERSION = 'gameness-v4-same-original-material-source-review.v1'
CLAIM = 'gameness_original_material_source_review_claim.json'
FAILURE = 'HARNESS_ERROR: unresolved source review: expanded.G.s0008'


def validate_sources(original, restored, old_binding, project, contract_sha):
    """Admit exactly the proven additive source; all old source bytes stay exact."""
    original={str(Path(k).resolve()):v for k,v in original.items()}
    project=Path(project).resolve()
    expected_ids={'SRC:'+str(Path(k).relative_to(project)):v for k,v in original.items()}
    restored_ids={'SRC:'+k:v for k,v in restored.items()}
    expected={**expected_ids,'SRC:'+material.RELATIVE:material.CONTENT_SHA}
    if (len(original)!=11 or 'SRC:'+material.RELATIVE in expected_ids
            or restored_ids!=expected
            or old_binding.get('identity')!=material.IDENTITY
            or old_binding.get('author_sources')!=original
            or old_binding.get('source_sha256_by_id')!=expected_ids
            or old_binding.get('contract_sha256')!=contract_sha
            or old_binding.get('scoring_protocol')!=policy.VERSION):
        raise ValueError('Same-original source review must preserve all eleven sources and add only exact author material')
    return expected


def _inputs(workspace,row,source,contract_sha):
    from .gameness_v3_runtime import source_files
    workspace=Path(workspace).resolve();source=Path(source).resolve()
    if row['entry']['id']!=material.IDENTITY:
        raise ValueError('Original-material source review is identity bounded')
    proof=source/'original_material_recovery.json'
    if not proof.is_file():raise ValueError('Expected the qualified same-original material source')
    qualification=qualified_history.prior(source)
    claim_path=Path(qualification['same_original_omitted_material']['path'])
    canonical=claim_path.parent
    if claim_path.name!=material.CLAIM or material.verify(canonical).resolve()!=source:
        raise ValueError('Original material claim/source differ')
    if Path(runner.read(canonical/'input_manifest.json')['entry']['project']).resolve()!=Path(row['entry']['project']).resolve():
        raise ValueError('Original project differs from frozen row')
    old=workspace/'source_reviews'/material.IDENTITY
    failed=old/'model_calls/gameness_source_v1_02/validation_error.json'
    if runner.read(failed).get('exception')!=FAILURE:
        raise ValueError('Expected exact retained incomplete-source parent failure')
    if not (old/'model_calls/gameness_source_v1_01/accepted_response.json').is_file():
        raise ValueError('Expected retained accepted incomplete-source prefix')
    project=Path(row['entry']['project']).resolve();restored=source/'input/project'
    files=source_files(project);complete=source_files(restored)
    original={str(p):sha(p) for p in files}
    expected=validate_sources(original,{str(p.relative_to(restored)):sha(p) for p in complete},
        runner.read(old/'source_binding.json'),project,contract_sha)
    bindings={str(p.resolve()):sha(p) for p in old.rglob('*') if p.is_file() and p != old/CLAIM}
    bindings.update(original)
    bindings.update({str(p.resolve()):sha(p) for p in complete})
    bindings.update({str(p.resolve()):sha(p) for p in (
        claim_path,source/'source_qualification.json',proof,Path(__file__))})
    bindings.update(qualification['source_bindings'])
    return bindings,expected


def authorize(workspace,row,source,frozen,repair):
    workspace=Path(workspace).resolve();source=Path(source).resolve();repair=Path(repair).resolve()
    if runner.read(repair).get('exit_code')!=0:
        raise ValueError('Directed recovery regressions must pass')
    bindings,sources=_inputs(workspace,row,source,frozen['contract_sha256'])
    bindings[str(repair)]=sha(repair)
    parent=workspace/'source_reviews'/material.IDENTITY
    claim=parent/CLAIM
    value=dict(version=VERSION,identity=material.IDENTITY,source=str(source),
        parent_failure=str(parent/'model_calls/gameness_source_v1_02/validation_error.json'),
        expected_source_sha256_by_id=sources,bindings=bindings,
        review_workspace=str(workspace/'source_review_original_material_recovery'/material.IDENTITY),
        source_count=12,original_source_count=11,all_checks_rejudged=True,
        old_accepted_findings_reused=False,original_modified=False,
        classification='NON_SCORING_SAME_ORIGINAL_MATERIAL_RECOVERY')
    if claim.exists():
        if runner.read(claim)!=value:raise ValueError('Immutable original-material source review claim differs')
    else:runner.exclusive_json(claim,value)
    return claim


def review_if_recovered(workspace,row,source,original,contract,frozen):
    workspace=Path(workspace).resolve();source=Path(source).resolve()
    if row['entry']['id']!=material.IDENTITY or not (source/'original_material_recovery.json').exists():
        return None
    parent=workspace/'source_reviews'/material.IDENTITY;path=parent/CLAIM
    value=runner.read(path)
    if (value.get('version')!=VERSION or value.get('source')!=str(source)
            or value.get('review_workspace')!=str(workspace/'source_review_original_material_recovery'/material.IDENTITY)):
        raise ValueError('Original-material source review recovery differs')
    for p,digest in value['bindings'].items():
        if sha(Path(p))!=digest:raise ValueError('Original-material source review parent changed: '+p)
    # Exclude only this new immutable authorization from the original parent tree.
    current,sources=_inputs(workspace,row,source,frozen['contract_sha256'])
    current.pop(str(path),None)
    if any(value['bindings'].get(p)!=d for p,d in current.items()) or sources!=value['expected_source_sha256_by_id']:
        raise ValueError('Original-material source review input set changed')
    adjusted=copy.deepcopy(row);adjusted['entry']['project']=str(source/'input/project')
    from .gameness_v3_runtime import source_files
    review,report=static.review(Path(value['review_workspace']),adjusted,original,contract,frozen,
        source_files(source/'input/project'),scoring_policy=policy)
    if review['source_binding']['source_sha256_by_id']!=sources:
        raise ValueError('Recovered complete source review omitted author sources')
    return review,report,{**value['bindings'],str(path):sha(path)}
