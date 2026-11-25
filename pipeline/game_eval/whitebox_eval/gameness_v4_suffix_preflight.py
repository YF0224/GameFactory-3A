"""Exact evidence aliases for an ordinary accepted prefix/uninvoked suffix.

Never replace a model call. Preserve all original source lines, frames, task
identities, earlier accepted deliveries and the sequential preflight failure.
"""
from pathlib import Path
from . import mechanic_v3_runner as runner, exact_evidence_alias as alias
from .gameness_v4_raw_parent_correction import canonical_tasks
from .protocol import sha

VERSION = 'gameness-v4-ordinary-uninvoked-suffix-exact-alias.v1'
AUTH = 'engineering/gameness_ordinary_suffix_preflight.json'
REAUTH = 'engineering/gameness_ordinary_suffix_preflight_final_review_v2.json'
PRIOR_REAUTH = 'engineering/gameness_ordinary_suffix_preflight_reauthorization.json'
ERROR = 'measured judge request exceeds versioned transport limits; do not silently clip images or prompt'


def validate_order(tasks,prefix,pending):
    names=[t['task'] for t in tasks]
    if not prefix or not pending or names!=prefix+pending or len(set(names))!=len(names):
        raise ValueError('A strict accepted canonical prefix and uninvoked suffix are required')


def authorize(root,diagnosis,failure_log,repair):
    root=Path(root).resolve();diagnosis=Path(diagnosis).resolve()
    failure_log=Path(failure_log).resolve();repair=Path(repair).resolve()
    tasks=canonical_tasks(root);prefix=[];pending=[]
    for t in tasks:
        name=t['task']
        if (root/'judgments'/(name+'.json')).is_file():prefix.append(name)
        else:pending.append(name)
    validate_order(tasks,prefix,pending)
    measurement=diagnosis/'measurement.json';prompt=diagnosis/'prompt.txt';m=runner.read(measurement)
    if (m.get('model_called') is not False or m.get('task')!=pending[0]
            or m.get('prompt_bytes')!=prompt.stat().st_size or m['prompt_bytes']<=1000000
            or m.get('prompt_sha256')!=sha(prompt) or ERROR not in failure_log.read_text()
            or runner.read(repair).get('exit_code')!=0):
        raise ValueError('Exact retained uninvoked measured overflow and regression proof required')
    files=[measurement,prompt,failure_log,repair,Path(__file__).resolve(),
        Path(alias.__file__).resolve(),root/'input_manifest.json',root/'source_qualification.json',
        root/'evidence_manifest.json',root/'input/pilot_rubric.json',root/'gameness_source_review.json',
        root/'gameness_source_review_binding.json']
    for name in prefix:
        call=root/'model_calls'/name;verdict=root/'judgments'/(name+'.json')
        accepted=runner.read(call/'accepted_response.json');v=runner.read(verdict)
        actual=root/'requests'/name/'actual_delivery.json';delivery=runner.read(actual)
        response=call/accepted['path'];inv=runner.read(call/'invocation.json');cmd=inv.get('command',[])
        images=[str(Path(cmd[i+1]).resolve()) for i,a in enumerate(cmd[:-1]) if a=='--image']
        if (accepted['sha256']!=sha(response) or v['response_sha256']!=sha(response)
                or v['actual_delivery_sha256']!=sha(actual) or inv.get('exit_code')!=0
                or sha(call/'prompt.txt')!=delivery['prompt_sha256']
                or delivery.get('all_predeclared_frames_delivered') is not True
                or images!=[str((root/i['path']).resolve()) for i in delivery['images']]):
            raise ValueError('Accepted complete prefix delivery changed')
        for i in delivery['images']+delivery['complete_author_sources']:
            if sha(root/i['path'])!=i['sha256']:raise ValueError('Accepted prefix original image/source changed')
            files.append(root/i['path'])
        files.extend(p for p in call.rglob('*') if p.is_file() and p.name!='v3_delivery_verified.json')
        files.extend(p for p in (root/'requests'/name).rglob('*') if p.is_file())
        files.append(verdict)
    for name in pending:
        if (root/'model_calls'/name).exists() or (root/'judgments'/(name+'.json')).exists():
            raise ValueError('Never replace an attempted suffix task')
        claim=root/'engineering/gameness_inline_schema'/(name+'.json')
        if claim.exists():
            value=runner.read(claim)
            from .gameness_v4_production_continuation import verified_bindings
            if value.get('first_delivery') is not True or value.get('task')!=name:
                raise ValueError('Retain the original first-delivery claim')
            verified_bindings(claim,value['source_bindings']);files.append(claim)
    if not (root/'engineering/gameness_inline_schema'/(pending[0]+'.json')).exists():
        raise ValueError('Retained sequential first-delivery failure claim required')
    # Feasibility is measured on the exact failed complete request, no cap change.
    wire,proof=alias.encode(prompt.read_bytes().decode())
    if proof['submitted_bytes']>1000000 or not proof['aliases']:
        raise ValueError('Exact alias transport must fit the unchanged prompt cap')
    value=dict(version=VERSION,identity=root.name,canonical_tasks=tasks,accepted_prefix=prefix,tasks=pending,
        no_invocation_at_authorization=True,source_frames_scores_and_caps_unchanged=True,
        diagnosis=str(diagnosis),bindings={str(p.resolve()):sha(p) for p in files},
        failed_prompt_alias_feasibility=proof)
    path=root/AUTH
    if path.exists():
        if runner.read(path)!=value:raise ValueError('Immutable suffix authorization differs')
    else:runner.exclusive_json(path,value)
    return path


def stable_source_review(root):
    """Verify all artifacts; project out only timestamped verification receipts."""
    root=Path(root).resolve();path=root/'gameness_source_review_binding.json'
    current=runner.read(path);review=root/'gameness_source_review.json'
    if (current.get('path') is None or not Path(current['path']).is_file()
            or current.get('sha256')!=sha(Path(current['path']))
            or runner.read(Path(current['path']))!=runner.read(review)
            or not current.get('bindings')):
        raise ValueError('Final source-review binding does not resolve to its exact review')
    stable={};markers={};review_root=Path(current['path']).parent.resolve()
    for bound,digest in current['bindings'].items():
        p=Path(bound).resolve()
        if sha(p)!=digest:raise ValueError('Final source-review artifact changed: '+bound)
        if p.name=='v3_delivery_verified.json':
            if (p.parent.parent!=review_root/'model_calls'
                    or not p.parent.name.startswith('gameness_source_v1_')):
                raise ValueError('Unexpected diagnostic receipt location')
            marker=runner.read(p);call=p.parent
            if (marker.get('valid') is not True or marker.get('images_verified')!=0
                    or marker.get('prompt_sha256')!=sha(call/'prompt.txt')
                    or marker.get('invocation_sha256')!=sha(call/'invocation.json')
                    or runner.read(call/'invocation.json').get('exit_code')!=0):
                raise ValueError('Diagnostic receipt does not verify its unchanged source call')
            markers[str(p)]={k:v for k,v in marker.items() if k!='time'}
        else:stable[bound]=digest
    return dict(path=current['path'],sha256=current['sha256'],bindings=stable,
        diagnostic_receipts=markers)


def reauthorize_final_source_review(root,repair_path):
    """Retain an exact parent; admit only never-invoked suffixes once."""
    root=Path(root).resolve();auth=root/AUTH;path=root/REAUTH
    value=runner.read(auth);tasks=canonical_tasks(root)
    if (value.get('version')!=VERSION or value.get('identity')!=root.name
            or value.get('canonical_tasks')!=tasks):
        raise ValueError('Original immutable suffix authorization is invalid')
    validate_order(tasks,value['accepted_prefix'],value['tasks'])
    binding_path=(root/'gameness_source_review_binding.json').resolve()
    binding_key=str(binding_path);old=value['bindings'].get(binding_key)
    if not old:raise ValueError('Original source-review binding required')
    code_path=str(Path(__file__).resolve())
    for bound,digest in value['bindings'].items():
        if bound not in (binding_key,code_path) and sha(Path(bound))!=digest:
            raise ValueError('Unrelated suffix authorization drift: '+bound)
    repair_path=Path(repair_path).resolve();repair=runner.read(repair_path)
    before=Path(repair['before_path']).resolve();regression=Path(repair['regression_log']).resolve()
    if (value['bindings'].get(code_path)!=repair.get('before_sha256')
            or sha(before)!=repair.get('before_sha256') or sha(Path(__file__))!=repair.get('after_sha256')
            or sha(regression)!=repair.get('regression_sha256') or repair.get('exit_code')!=0
            or repair.get('tests_passed',0)<1):
        raise ValueError('Exact production continuation and passing regression proof required')
    stable=stable_source_review(root)
    for name in value['accepted_prefix']:
        if not (root/'judgments'/(name+'.json')).is_file():
            raise ValueError('Accepted prefix changed during reauthorization')
    if not path.exists():
        for name in value['tasks']:
            if ((root/'model_calls'/name).exists()
                    or (root/'judgments'/(name+'.json')).exists()):
                raise ValueError('Suffix task was invoked; cannot reauthorize it')
    receipt=dict(version='gameness-v4-ordinary-uninvoked-suffix-final-review.v2',
        identity=root.name,original_authorization=str(auth),original_authorization_sha256=sha(auth),
        changed_binding=binding_key,previous_sha256=old,
        accepted_prefix=value['accepted_prefix'],uninvoked_tasks=value['tasks'],
        source_review_sha256=sha(root/'gameness_source_review.json'),stable_source_review_binding=stable,
        repair_receipt=str(repair_path),repair_receipt_sha256=sha(repair_path),
        no_model_invocation=True,other_bindings_unchanged=True)
    prior=root/PRIOR_REAUTH
    if prior.exists():receipt.update(prior_reauthorization=str(prior),prior_reauthorization_sha256=sha(prior))
    if path.exists():
        if runner.read(path)!=receipt:raise ValueError('Immutable source-review reauthorization differs')
    else:runner.exclusive_json(path,receipt)
    return path


def apply(root,name,body):
    root=Path(root).resolve();path=root/AUTH
    if not path.exists():return body,None
    value=runner.read(path)
    if (value.get('version')!=VERSION or value.get('identity')!=root.name
            or value.get('canonical_tasks')!=canonical_tasks(root)):
        raise ValueError('Canonical exact suffix recovery changed')
    validate_order(value['canonical_tasks'],value['accepted_prefix'],value['tasks'])
    reauth_path=root/REAUTH
    preliminary=runner.read(reauth_path) if reauth_path.exists() else None
    reauth=reauthorize_final_source_review(root,preliminary['repair_receipt']) if preliminary else None
    if reauth is not None:reauth=runner.read(reauth)
    for p,digest in value['bindings'].items():
        if sha(Path(p))==digest:continue
        code_continuation=(reauth is not None and p==str(Path(__file__).resolve()))
        if code_continuation:continue  # Exact before/after bytes checked by reauthorization.
        if (reauth is None or p!=reauth.get('changed_binding')
                or stable_source_review(root)!=reauth.get('stable_source_review_binding')):
            raise ValueError('Exact suffix recovery parent changed: '+p)
    if reauth is not None:
        if (reauth.get('version')!='gameness-v4-ordinary-uninvoked-suffix-final-review.v2'
                or reauth.get('original_authorization_sha256')!=sha(path)
                or reauth.get('identity')!=root.name
                or reauth.get('accepted_prefix')!=value['accepted_prefix']
                or reauth.get('uninvoked_tasks')!=value['tasks']
                or reauth.get('source_review_sha256')!=sha(root/'gameness_source_review.json')
                or reauth.get('repair_receipt_sha256')!=sha(Path(reauth['repair_receipt']))
                or reauth.get('no_model_invocation') is not True
                or reauth.get('other_bindings_unchanged') is not True):
            raise ValueError('Final source-review reauthorization is not bound to this suffix')
    if name in value['accepted_prefix']:return body,None
    if name not in value['tasks']:raise ValueError('Task outside canonical uninvoked suffix')
    wire,proof=alias.encode(body)
    if alias.decode(wire)!=body:raise ValueError('Exact suffix body reconstruction differs')
    folder=root/'requests'/name/'exact_evidence_transport'
    for filename,text in [('original_body.txt',body),('submitted_body.txt',wire)]:
        p=folder/filename
        if p.exists() and p.read_bytes()!=text.encode():raise ValueError('Retained suffix exact body changed')
        if not p.exists():p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(text.encode())
    proof.update(authorization_path=str(path),authorization_sha256=sha(path))
    if reauth is not None:
        proof.update(reauthorization_path=str(reauth_path),reauthorization_sha256=sha(reauth_path))
    dest=folder/'equivalence.json'
    if dest.exists():
        if runner.read(dest)!=proof:raise ValueError('Retained suffix equivalence changed')
    else:runner.exclusive_json(dest,proof)
    return wire,dict(path=str(dest.relative_to(root)),sha256=sha(dest),
        original_body_sha256=proof['original_sha256'],exact_expansion=True)
