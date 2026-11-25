"""Explicit Unity M source-stage dispatch for the two authorized formal CLIs.

This module does not grant native/judge admission. Each later capability must
carry its own real Unity acceptance; source freeze is never a scored column.
"""
from pathlib import Path
import argparse
import json
from . import unity_m_scope as scope, mechanic_v3_runner as runner
from . import mechanic_v3 as mechanic, mechanic_v3_outcome as outcome
from . import mechanic_v3_revision as revisions, gameness_v4 as gameness
from . import batch, core12, tiered_core, endpoint_sparse
from .codex import call_codex
from .protocol import dump, sha


def contract_sources(workspace, case, inventory, column):
    rows = [r for r in inventory['entries'] if r['in_scope'] and r['entry']['case_id'] == case]
    if not rows:raise ValueError('No frozen Unity M originals for case')
    folder = revisions.contract_dir(workspace,case) if column=='Mechanic' else workspace/'gameness_contracts'/'outcome_frame_v1'/case
    protocols=[];bindings={};parts=[]
    for row in rows:
        e=row['entry'];source_batch=Path(row['source_batch'])
        original=batch.verify_protocol(source_batch,e)
        if column=='Mechanic':
            contract,planning_source=tiered_core.load_sources(e)
            planning_source['scoring_protocol_sha256']=core12.fingerprint(original)
            proto=tiered_core.make_protocol(contract,original,planning_source)
            endpoint_sparse.freeze(proto)
            bindings[str(Path(planning_source['source_path']))]=sha(Path(planning_source['source_path']))
        else:proto=original
        protocols.append(proto)
        for name in (e['requirement'],e['frozen_rubric'],str(source_batch/'protocol_lock.json')):
            bindings[name]=sha(Path(name))
        parts.append('MODEL '+e['method']+' ORIGINAL REQUIREMENT\n'+Path(e['requirement']).read_text())
        if row['source_blocker']:
            parts.append('ORIGINAL SOURCE BLOCKER '+row['source_blocker']+'; do not invent missing implementation')
        project=Path(e['project'])
        for name,digest in sorted(row['source_hashes'].items()):
            path=project/name
            if path.suffix.lower() not in mechanic.SOURCE_SUFFIXES:continue
            if sha(path)!=digest:raise ValueError('Frozen author source changed: '+str(path))
            bindings[str(path)]=digest
            parts.append('AUTHOR '+e['method']+' '+name+' SHA256 '+digest+'\n'+''.join(
                f'{n}: {line}\n' for n,line in enumerate(path.read_text(errors='strict').splitlines(),1)))
    checks=mechanic.mechanisms if column=='Mechanic' else gameness.criteria
    expected=checks(protocols[0])
    if any(checks(p)!=expected for p in protocols[1:]):raise ValueError('Cross-model original criteria differ')
    return folder,protocols[0],'\n'.join(parts),dict(bindings=bindings,
        scope_binding=inventory['full_scope_binding'],models=[r['entry']['method'] for r in rows],
        runtime_evidence_supplied=False,old_verdict_supplied=False)


def freeze_contract(workspace,case,inventory,column):
    folder,proto,text,binding=contract_sources(workspace,case,inventory,column)
    policy=outcome if column=='Mechanic' else gameness
    if (folder/'frozen.json').exists():
        frozen=runner.read(folder/'frozen.json')
        if (sha(folder/'contract.json')!=frozen['contract_sha256'] or
                runner.read(folder/'source_binding.json')!=binding):
            raise ValueError('Frozen source contract differs')
        value=runner.read(folder/'contract.json');policy.validate_contract(proto,value)
        return frozen
    if folder.exists() and any(folder.iterdir()):
        raise ValueError('Preserved partial contract requires exact failed-stage diagnosis; no blind repeat')
    folder.mkdir(parents=True)
    runner.disk(folder,'unity_m_'+column.lower()+'_contract',64*1024**2)
    runner.exclusive_json(folder/'source_binding.json',binding)
    runner.exclusive_json(folder/'frozen_protocol.json',proto)
    (folder/'author_sources.txt').write_text(text)
    schema=policy.contract_schema(proto);dump(folder/'planned_schema.json',schema)
    checks=mechanic.mechanisms(proto) if column=='Mechanic' else gameness.criteria(proto)
    contract_prompt=policy.CONTRACT_PROMPT
    if column=='Mechanic':
        contract_prompt=contract_prompt.replace('BOTH original author sources','all supplied original author sources').replace('for Astra and Opus','for '+', '.join(binding['models']))
    contract_prompt+='\nEvery basic_function_bugs array defines possible basic semantic errors, not observed runtime bugs, and must be nonempty. Every permitted_trigger_modes array must be nonempty. This is the unchanged source-only validator requirement; no runtime behavior is asserted. Exact numeric/timing/spatial deviations stay diagnostic only.'
    prompt=contract_prompt+'\nCHECKS\n'+json.dumps(checks,ensure_ascii=False)+'\nAUTHOR SOURCES\n'+text+'\nEXACT SCHEMA FILE '+str(folder/'planned_schema.json')
    if len(prompt.encode())>1000000:raise ValueError('Full source exceeds frozen cap; lossless recovery required')
    (folder/'input').mkdir()
    value=call_codex(folder,name='unity_m_'+column.lower()+'_source_contract',prompt=prompt,schema=schema,
        model='gpt-6.1-sol',timeout=600,max_attempts=1,
        response_validator=lambda raw:policy.validate_contract(proto,raw))
    runner.exclusive_json(folder/'contract.json',value)
    frozen=dict(version=(outcome.CONTRACT_VERSION if column=='Mechanic' else gameness.VERSION),revision='outcome_frame_v1',case_id=case,column=column,
        created=runner.stamp(),contract_sha256=sha(folder/'contract.json'),
        source_binding_sha256=sha(folder/'source_binding.json'),schema_sha256=sha(folder/'planned_schema.json'),
        model='gpt-6.1-sol',runtime_evidence_supplied=False,old_verdict_supplied=False,
        native_acceptance_granted=False,scored_column=False)
    runner.exclusive_json(folder/'frozen.json',frozen)
    print(case,column,'SOURCE_CONTRACT_FROZEN_NOT_SCORED',flush=True)
    return frozen


def correct_contract(workspace,case,inventory,column):
    """One source-only response correction for an exactly reproduced validator failure."""
    from .codex import READ_ONLY_EVAL_INSTRUCTIONS, validate_schema
    import hashlib
    folder,proto,text,binding=contract_sources(workspace,case,inventory,column)
    policy=outcome if column=='Mechanic' else gameness
    call=folder/'model_calls'/('unity_m_'+column.lower()+'_source_contract')
    if (call/'accepted_response.json').exists() or (folder/'frozen.json').exists():
        raise ValueError('Accepted source contract must not be recalled')
    error=runner.read(call/'validation_error.json')
    supported=({'Frozen identity/original diagnostic requirement changed','Freeze functional bug and trigger definitions'}
        if column=='Mechanic' else {'Original Gameness identity/requirement changed','Freeze basic bugs and trigger alternatives'})
    if error.get('exception') not in supported or error.get('response_sha256')!=sha(call/'response.json'):
        raise ValueError('Exact diagnosed source validator response required')
    if runner.read(folder/'source_binding.json')!=binding:raise ValueError('Original full source changed')
    schema=runner.read(call/'schema.json')
    if schema!=policy.contract_schema(proto):raise ValueError('Original frozen schema changed')
    invocation=runner.read(call/'invocation.json');command=invocation['command']
    if invocation.get('exit_code')!=0 or command[command.index('--model')+1]!='gpt-6.1-sol':raise ValueError('Completed original model call required')
    raw=runner.read(call/'response.json');validate_schema(raw,schema)
    try:policy.validate_contract(proto,raw)
    except ValueError as observed:
        if str(observed)!=error['exception']:raise ValueError('Original source validator diagnosis changed') from observed
    else:raise ValueError('Already valid source response must be reused')
    specs=mechanic.mechanisms(proto) if column=='Mechanic' else gameness.criteria(proto)
    defects=[]
    for spec in specs:
        row=raw['checks'][spec['id']]
        mismatch=row['original_requirement_diagnostic_only']!=spec['requirement']
        empty=[key for key in ('basic_function_bugs','permitted_trigger_modes') if not row[key]]
        if mismatch or empty:
            defects.append(dict(id=spec['id'],exact_original=spec['requirement'],requirement_mismatch=mismatch,empty_definitions=empty))
    if not defects:raise ValueError('No supported source contract defect')
    full=(call/'prompt.txt').read_text()
    if not full.startswith(READ_ONLY_EVAL_INSTRUCTIONS):raise ValueError('Original instruction prefix changed')
    prompt=full[len(READ_ONLY_EVAL_INSTRUCTIONS):]+('\nONE BOUNDED SOURCE-ONLY VALIDATOR CORRECTION. Return the complete unchanged original schema for every original check. '
        'Copy original_requirement_diagnostic_only byte for byte from CHECKS.requirement. '
        'basic_function_bugs defines potential semantically wrong behavior that would invalidate this goal; it is NOT a list of observed runtime bugs. '
        'Provide at least one source-grounded basic-function bug definition and at least one permitted trigger mode for each check, as the unchanged validator requires. '
        'Do not assert that a bug occurred. No runtime evidence, scores or prior judgments are supplied. '
        'Exact timing, numeric, spatial or exhaustive-branch discrepancies remain diagnostic only and cannot become bug gates. '
        'All original IDs, groups, weights, goals and 10/50/100 rules stay unchanged. Exact diagnosed defects: ')+json.dumps(defects,ensure_ascii=False)
    if len((READ_ONLY_EVAL_INSTRUCTIONS+prompt).encode())>1000000:raise ValueError('Unchanged full-source cap exceeded')
    target=folder/'engineering/source_validator_correction.json'
    if target.exists() or (folder/'engineering/original_requirement_correction.json').exists():
        raise ValueError('Correction already claimed; retain accepted/failed response without repeat')
    claim=dict(parent={str(p):sha(p) for p in call.iterdir() if p.is_file()},source_binding_sha256=sha(folder/'source_binding.json'),
        producer_sha256=sha(Path(__file__)),prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),maximum_calls=1,locally_filled_fields=False,
        original_validator_error=error['exception'],defects=defects)
    runner.exclusive_json(target,claim)
    value=call_codex(folder,name='unity_m_'+column.lower()+'_source_validator_correction',prompt=prompt,schema=schema,
        model='gpt-6.1-sol',timeout=600,max_attempts=1,response_validator=lambda v:policy.validate_contract(proto,v))
    runner.exclusive_json(folder/'contract.json',value)
    frozen=dict(version=outcome.CONTRACT_VERSION if column=='Mechanic' else gameness.VERSION,revision='outcome_frame_v1',case_id=case,column=column,created=runner.stamp(),
        contract_sha256=sha(folder/'contract.json'),source_binding_sha256=sha(folder/'source_binding.json'),schema_sha256=sha(folder/'planned_schema.json'),
        model='gpt-6.1-sol',runtime_evidence_supplied=False,old_verdict_supplied=False,native_acceptance_granted=False,scored_column=False,
        correction=dict(path=str(target),sha256=sha(target)))
    runner.exclusive_json(folder/'frozen.json',frozen)
    print(case,column,'SOURCE_CONTRACT_FROZEN_NOT_SCORED',flush=True)
    return frozen


def prepare_plan(workspace, row):
    """Original-only frozen two-column observation route; no native/score claim."""
    import copy
    from . import batch, core12, endpoint_sparse
    from .mechanic_v3_plan_transport import plan_frozen
    from .protocol import write_operation_report
    if row['source_blocker']:
        raise ValueError('Original source blocked: '+row['source_blocker'])
    entry=copy.deepcopy(row['entry'])
    if scope.source_files(Path(entry['project']))!=row['source_hashes']:
        raise ValueError('Frozen original source changed before planning')
    folder=revisions.contract_dir(workspace,entry['case_id'])
    frozen=runner.read(folder/'frozen.json');contract=runner.read(folder/'contract.json')
    if sha(folder/'contract.json')!=frozen['contract_sha256']:
        raise ValueError('Frozen Mechanic contract changed')
    gf=workspace/'gameness_contracts'/'outcome_frame_v1'/entry['case_id']
    gfreeze=runner.read(gf/'frozen.json')
    if sha(gf/'contract.json')!=gfreeze['contract_sha256']:
        raise ValueError('Original Gameness contract must be frozen before recording')
    root=workspace/'runs'/entry['id']
    if not root.exists():
        runner.disk(workspace,'unity_m_plan_prepare',2*1024**3)
        entry['planning_policy']='tiered-core-v1'
        entry['evaluation_policy']=endpoint_sparse.VERSION
        batch.prepare(Path(row['source_batch']),entry,root,prefer_explicit_endpoint_conditions=True)
        runner.exclusive_json(root/'unity_m_source_binding.json',dict(
            scope_path=str(workspace/'scopes/unity_m_original/scope.json'),
            scope_sha256=sha(workspace/'scopes/unity_m_original/scope.json'),
            source_hashes=row['source_hashes'],original_source_provenance=row['source_provenance'],
            mechanic_frozen_sha256=sha(folder/'frozen.json'),
            gameness_frozen_sha256=sha(gf/'frozen.json'),two_column_native_accepted=False))
    batch.verify_inputs(root)
    if not (root/'unity_m_source_binding.json').is_file():
        raise ValueError('Preserved partial preparation requires explicit recovery')
    proto=core12.verify_attempt(root,'unity3d')
    outcome.validate_contract(proto,contract)
    gameness.validate_contract(proto,runner.read(gf/'contract.json'))
    if (root/'sol_plan.json').is_file():
        return root,batch.validate_operation_plan(root,runner.read(root/'sol_plan.json'),'unity3d')
    failed=root/'model_calls/plan_v3_outcome_frame_v1/validation_error.json'
    if failed.exists() or (failed.parent/'schema_error.json').exists():
        from .unity_m_plan_recovery import recover
        operation=recover(root,proto)
    else:
        operation=plan_frozen(workspace,root,proto,'unity3d',core12.plan_identity(root,proto,'unity3d'),
            contract,frozen,capture_map_complete=True)
    dump(root/'sol_plan.json',operation)
    endpoint_sparse.freeze_conditions(root,proto,operation)
    write_operation_report(root,operation)
    dump(root/'stage.json',dict(time=runner.stamp(),stage='UNITY_M_EXECUTABLE_PLAN_NOT_SCORED',revision='outcome_frame_v1'))
    print(entry['id'],'UNITY_M_EXECUTABLE_PLAN_NOT_SCORED',flush=True)
    return root,operation


def adapter_acceptance(workspace, configuration):
    """Current formal adapter, bounded shared lease, preserved native fixtures."""
    import fcntl, os, subprocess, sys
    from . import unity_safety
    from .gameness_v3_runtime import production_bindings
    config=runner.read(configuration)
    adapter=Path(__file__).resolve().parents[3]
    if Path(config['adapter_root']).resolve()!=adapter:
        raise ValueError('Unity acceptance must execute current formal adapter')
    output=Path(config['output']).resolve()
    output.relative_to(workspace)
    if output.exists():raise ValueError('Preserve existing native attempt; no blind repetition')
    control=Path(config['control_root']).resolve()
    with (control/'whitebox_production_queue.lock').open('a+') as lease:
        fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if config.get('prepackage_failed_capture'):
            from . import unity_preinput_cleanup
            failed=Path(config['prepackage_failed_capture']).resolve();failed.relative_to(workspace)
            if not config.get('package_relocation_regression'):raise ValueError('Regression required before package recovery')
            proof=runner.read(Path(config['package_relocation_regression']))
            if proof.get('exit_code')!=0 or proof.get('tests_passed',0)<1:raise ValueError('Passed package recovery regression required')
            unity_preinput_cleanup.release(config,failed)
        locks=unity_safety.locks_clear(config,check_external=True)
        receipt=workspace/'engineering'/('native_dispatch_'+str(__import__('time').time_ns())+'.json')
        runner.exclusive_json(receipt,dict(configuration=str(configuration),configuration_sha256=sha(configuration),
            pid=os.getpid(),locks=locks,production_bindings=production_bindings(),output=str(output),
            state='NATIVE_ACCEPTANCE_DISPATCHED_NOT_TWO_COLUMN_ACCEPTANCE'))
        if config.get('continue_scene_acceptance'):
            from .unity_m_native_acceptance import continue_runtime
            return continue_runtime(workspace, config)
        args=[sys.executable,'-m','engine_adapters.unity3d.playtest.native_acceptance']
        for key in ('output','adapter_root','control_root','parent_pin','fixture_root','editor',
                    'runtime_attempt','runtime_actions_20','runtime_actions_180'):
            args+=['--'+key.replace('_','-'),config[key]]
        return subprocess.call(args)


def main(argv,column='Mechanic'):
    import sys
    arguments=list(sys.argv[1:] if argv is None else argv)
    if any(arguments[n:n+2]==['--phase','unity-m-admit'] for n in range(len(arguments))):
        from .unity_m_admission import main as admit_main
        return admit_main(arguments)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace',type=Path,required=True)
    parser.add_argument('--phase',choices=['unity-m-freeze-scope','unity-m-freeze','unity-m-adapter-acceptance','unity-m-contract-correct','unity-m-plan'],required=True)
    parser.add_argument('--discovery',type=Path)
    parser.add_argument('--legacy-inventory',type=Path)
    parser.add_argument('--alternate',type=Path)
    parser.add_argument('--remote-tree',type=Path)
    parser.add_argument('--git-ref')
    parser.add_argument('--source-resume',type=Path)
    parser.add_argument('--native-configuration',type=Path)
    parser.add_argument('--cases',nargs='+')
    parser.add_argument('--ids',nargs='+')
    args=parser.parse_args(argv);workspace=args.workspace.resolve()
    if args.phase=='unity-m-freeze-scope':
        if column!='Mechanic':raise ValueError('Scope is shared; freeze it once with the Mechanic entry')
        if not all((args.discovery,args.legacy_inventory,args.alternate,args.remote_tree,args.git_ref)):
            parser.error('Complete five-model discovery and fixed remote source inputs required')
        inv=scope.freeze(workspace,args.discovery,args.legacy_inventory,args.alternate,args.remote_tree,args.git_ref,args.source_resume)
        print(json.dumps(dict(scope=inv['full_scope_binding'],identities=len(inv['active_selection']))))
        return 0
    inv=scope.load(workspace)
    if args.phase=='unity-m-adapter-acceptance':
        if column!='Mechanic' or not args.native_configuration:parser.error('Shared adapter acceptance requires Mechanic entry and configuration')
        return adapter_acceptance(workspace,args.native_configuration.resolve())
    cases=args.cases or sorted({r['entry']['case_id'] for r in inv['entries'] if r['in_scope']})
    # One workspace lock prevents concurrent duplicate source/model stages.
    import fcntl
    with (workspace/('.unity_m_'+column.lower()+'_source.lock')).open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if args.phase=='unity-m-plan':
            if column!='Mechanic' or not args.ids:parser.error('Shared plan requires Mechanic entry and explicit frozen identities')
            rows={r['entry']['id']:r for r in inv['entries'] if r['in_scope']}
            for identity in args.ids:prepare_plan(workspace,rows[identity])
            return 0
        for case in cases:
            if args.phase=='unity-m-contract-correct':correct_contract(workspace,case,inv,column)
            else:freeze_contract(workspace,case,inv,column)
    return 0
