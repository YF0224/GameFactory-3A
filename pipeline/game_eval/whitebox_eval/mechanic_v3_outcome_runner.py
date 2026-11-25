"""Source-only paired outcome contracts and opt-in outcome v3 execution."""
from pathlib import Path
from . import mechanic_v3_outcome as outcome, mechanic_v3_revision as revisions
from . import mechanic_v3_runner as runner, mechanic_v3_execution as execution
from .codex import call_codex
from .protocol import dump,sha


def freeze(workspace,case,inventory):
    workspace=Path(workspace);folder=revisions.contract_dir(workspace,case)
    if revisions.revision(workspace)!=outcome.REVISION:raise ValueError('Outcome revision must be explicitly authorized')
    if (folder/'frozen.json').exists():
        frozen=runner.read(folder/'frozen.json');contract=runner.read(folder/'contract.json')
        if sha(folder/'contract.json')!=frozen['contract_sha256']:raise ValueError('Frozen outcome contract changed')
        for path,digest in runner.read(folder/'source_binding.json')['bindings'].items():
            if sha(Path(path))!=digest:raise ValueError('Frozen author source changed')
        return contract
    name='outcome_contract_v1'
    if folder.exists() and any(folder.iterdir()):
        failed=folder/'model_calls'/name
        invocation=runner.read(failed/'invocation.json')
        if ((folder/'input').exists() or invocation.get('exit_code')!=1 or invocation.get('response_present')
                or not (failed/'stderr.log').read_text().startswith('Error: No such file or directory (os error 2)')):
            raise ValueError('Preserved partial contract requires a new specific diagnosis')
        for path,digest in runner.read(folder/'source_binding.json')['bindings'].items():
            if sha(Path(path))!=digest:raise ValueError('Original contract source changed')
        rows=[row for row in inventory['entries'] if row['entry']['case_id']==case and row['historical_attempts']]
        if not rows:raise ValueError('Need bound frozen protocol for prelaunch recovery')
        proto=runner.read(Path(rows[0]['historical_attempts'][0])/'input/pilot_rubric.json')
        text=(folder/'author_sources.txt').read_text()
        runner.exclusive_json(folder/'missing_cli_cwd_recovery.json',dict(time=runner.stamp(),
            root_cause='New outcome contract runner omitted empty input cwd required by official CLI wrapper.',
            failed_invocation_sha256=sha(failed/'invocation.json'),failure_sha256=sha(failed/'stderr.log'),
            source_binding_sha256=sha(folder/'source_binding.json'),model_call_reached_service=False,
            original_request_preserved=True,new_attempt_reason='Create required empty cwd; unchanged source-only scoring semantics'))
        name='outcome_contract_v1_cwd_recovery'
    else:
        folder,proto,text=runner.contract_source(workspace,case,inventory,folder=folder)
    (folder/'input').mkdir(exist_ok=True)
    schema=outcome.contract_schema(proto);dump(folder/'planned_schema.json',schema)
    prompt=outcome.CONTRACT_PROMPT+'\nCHECKS\n'+__import__('json').dumps(runner.v3.mechanisms(proto),ensure_ascii=False)+'\nAUTHOR SOURCES\n'+text+'\nEXACT SCHEMA FILE '+str((folder/'planned_schema.json').resolve())
    if len(prompt.encode())>1000000:raise ValueError('Source packet too large; partition without clipping')
    runner.disk(folder,'outcome_contract',64*1024**2)
    contract=call_codex(folder,name=name,prompt=prompt,schema=schema,model=runner.v3.MODEL,
        timeout=600,max_attempts=1,response_validator=lambda raw:outcome.validate_contract(proto,raw))
    runner.exclusive_json(folder/'contract.json',contract)
    runner.exclusive_json(folder/'frozen.json',dict(version=outcome.CONTRACT_VERSION,revision=outcome.REVISION,
        case_id=case,created=runner.stamp(),contract_sha256=sha(folder/'contract.json'),
        source_binding_sha256=sha(folder/'source_binding.json'),schema_sha256=sha(folder/'planned_schema.json'),
        model=runner.v3.MODEL,runtime_evidence_supplied=False,old_verdict_supplied=False,
        historical_record_notice='按新结果导向契约重新评价历史实录；不声称契约早于历史录制'))
    print(case,'OUTCOME_CONTRACT_FROZEN',flush=True)
    return contract


def recorded_prerecord_lineage(source):
    """Judge-only selection of an already self-qualified unchanged native take.

    A recorded take binds its physical plan and cleanup at capture time. Later
    planning-tool code is diagnostic; it cannot authorize another recording.
    """
    from . import qualified_history as history, batch, sparse_native
    from . import mechanic_v3_prerecord_identity as identity_recovery
    from .pending_publication import cleanup_source
    source=Path(source).resolve();root=source;seen=set();chain=[];changes={}
    formal=Path(__file__).resolve().parent
    while (root/identity_recovery.CLAIM).exists():
        if str(root) in seen:raise ValueError('Cyclic recorded prerecord lineage')
        seen.add(str(root));path=root/identity_recovery.CLAIM;claim=runner.read(path)
        for name,digest in claim['source_bindings'].items():
            current=sha(Path(name))
            if current!=digest:
                if Path(name).resolve().parent!=formal or Path(name).suffix!='.py':
                    raise ValueError('Recorded prerecord data changed: '+name)
                changes[name]=dict(capture_planner_sha256=digest,current_sha256=current)
        child=Path(claim['recovery_root']).resolve()
        proof=runner.read(child/'prerecord_identity.json')
        if (proof['claim_sha256']!=sha(path) or
                proof['operation_sha256']!=sha(child/'sol_plan.json')):
            raise ValueError('Recorded prerecord claim or operation changed')
        chain.append(dict(path=str(path),sha256=sha(path),proof=str(child/'prerecord_identity.json'),
                          proof_sha256=sha(child/'prerecord_identity.json')))
        root=child
    q=history.prior(root)
    batch.verify_inputs(root);batch.verify_runtime_sources(root)
    engine=runner.read(root/'input_manifest.json')['entry']['actual_engine']
    if sparse_native.verify_acceptance(root.parents[1],engine)!=q['native_acceptance']:
        raise ValueError('Recorded prerecord native acceptance changed')
    cleanup,_=cleanup_source(root)
    if not cleanup or cleanup!=q['cleanup_bindings']:
        raise ValueError('Recorded prerecord cleanup changed')
    receipt=dict(version='mechanic-recorded-prerecord-judge-lineage.v1',source=str(source),
                 root=str(root),chain=chain,source_qualification_sha256=sha(root/'source_qualification.json'),
                 planning_tool_drift=changes,execution_allowed=False,new_recording=False)
    import hashlib
    key=hashlib.sha256(str(source).encode()).hexdigest()
    path=root/'engineering/recorded_prerecord_judge_lineages'/(key+'.json')
    if path.exists():
        if runner.read(path)!=receipt:raise ValueError('Recorded prerecord judge lineage changed')
    else:runner.exclusive_json(path,receipt)
    return root


def locate_qualified(workspace,identity, *, recorded_only=False):
    workspace=Path(workspace);canonical=workspace/'runs'/identity
    from . import godot_native_telemetry_reuse as telemetry_reuse
    if (canonical/telemetry_reuse.CLAIM).exists():
        return telemetry_reuse.verify(canonical)
    from . import mechanic_v3_original_material_recovery as material
    if (canonical/material.CLAIM).exists():
        continued=material.verify(canonical)
        if not (continued/'source_qualification.json').exists():
            raise ValueError('Original omitted material recovery requires a qualified real recording')
        return continued
    from . import mechanic_v3_user_retake as retake
    if (canonical/retake.CLAIM).exists():
        continued=retake.verify(canonical)
        if not (continued/'source_qualification.json').exists():
            raise ValueError('Authorized retake requires new qualified native recording')
        return continued
    from . import mechanic_v3_author_entry_recovery as author_entry
    if (canonical/author_entry.CLAIM).exists():
        from . import mechanic_v3_prerecord_identity as author_identity
        continued=author_entry.verify(canonical)
        if (continued/author_identity.CLAIM).exists():
            continued=author_identity.verify(continued)
        if not (continued/'source_qualification.json').exists():
            raise ValueError('Author-entry recovery requires new qualified native recording')
        return continued
    candidates=[canonical]
    for name in ('mechanic_observation_recovery_claim.json','mechanic_capture_map_recovery_claim.json','mechanic_outcome_native_claim.json','mechanic_preparation_policy_recovery_claim.json','mechanic_prerecord_recovery_claim.json'):
        if (canonical/name).exists():candidates.append(Path(runner.read(canonical/name)['recovery_root']))
    for root in candidates:
        from . import mechanic_v3_prerecord_identity as identity_recovery
        if (root/identity_recovery.CLAIM).exists():
            if recorded_only:
                return recorded_prerecord_lineage(root)
            continued=identity_recovery.verify(root)
            if (continued/'source_qualification.json').exists():return continued
        if (root/'source_qualification.json').exists():return root
    raise ValueError('No qualified real source; complete native recording first')


def judge(workspace,identity,inventory):
    root=locate_qualified(workspace,identity)
    return execution.judge_and_publish(Path(workspace),root,inventory)


def main(argv=None):
    """Explicit separate-revision runner; never resumes the old v2 queue."""
    import argparse
    import fcntl
    from concurrent.futures import ThreadPoolExecutor, as_completed
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace',required=True,type=Path)
    parser.add_argument('--phase',required=True,choices=['freeze','plan','record','judge','repair-launch'])
    parser.add_argument('--identities',nargs='+',required=True,
                        help='Frozen case IDs for freeze; frozen model/case identities for judge')
    parser.add_argument('--workers',type=int,default=2,choices=[1,2])
    args=parser.parse_args(argv);workspace=args.workspace.resolve()
    if revisions.revision(workspace)!=outcome.REVISION:raise ValueError('Explicit active outcome revision required')
    if args.phase=='record' and args.workers!=1:raise ValueError('Native recordings must be serialized')
    from .mechanic_v3_scope import load_inventory, allowed_identities
    inventory=load_inventory(workspace)
    entries={row['entry']['id']:row for row in inventory['entries']}
    allowed=allowed_identities(inventory,'record' if args.phase=='repair-launch' else args.phase)
    if len(set(args.identities))!=len(args.identities) or set(args.identities)-set(allowed):
        raise ValueError('Duplicate or non-frozen identity')
    runner.configure_cli(Path(next(iter(entries.values()))['source_batch']))
    lockdir=workspace/'locks';lockdir.mkdir(exist_ok=True)
    def invoke(identity):
        name=('outcome_contract_' if args.phase=='freeze' else 'outcome_frame_v1_')+identity+'.lock'
        with (lockdir/name).open('a+') as handle:
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            if args.phase in {'plan','record','repair-launch'}:
                from . import mechanic_v3_outcome_native as native
                from . import mechanic_v3_author_entry_recovery as author_entry
                if args.phase=='repair-launch':
                    value=author_entry.prepare(workspace,entries[identity])
                elif (workspace/'runs'/identity/author_entry.CLAIM).exists():
                    value=(author_entry.prepare if args.phase=='plan' else author_entry.record)(workspace,entries[identity])
                else:
                    value=(native.prepare if args.phase=='plan' else native.record)(workspace,entries[identity])
                root=value[0] if isinstance(value,tuple) else value
                return {'identity':identity,'phase':args.phase,'root':str(root),'complete':True}
            value=(freeze if args.phase=='freeze' else judge)(workspace,identity,inventory)
            return {'identity':identity,'phase':args.phase,'score':value.get('score'),'complete':True}
    failures=[]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        tasks={pool.submit(invoke,identity):identity for identity in args.identities}
        for task in as_completed(tasks):
            try:print(__import__('json').dumps(task.result(),ensure_ascii=False),flush=True)
            except Exception as error:
                failure=dict(time=runner.stamp(),identity=tasks[task],phase=args.phase,
                    revision=outcome.REVISION,error=repr(error),product_score=None,
                    next_action='Inspect preserved source, invocation and validation failure; no unchanged retries')
                path=workspace/'engineering/outcome_frame_v1/runner_failures'/(str(__import__('time').time_ns())+'.json')
                dump(path,failure);failures.append(failure)
                print(__import__('json').dumps(failure,ensure_ascii=False),flush=True)
    return 1 if failures else 0


if __name__=='__main__':raise SystemExit(main())
