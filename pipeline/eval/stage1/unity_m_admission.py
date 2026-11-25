"""Admit serial Unity M dispatch from a complete two-column native E2E.

Executed producer, current verifier and gate-only delta remain distinct.
"""
from pathlib import Path
import argparse
import hashlib
import json
import fcntl
from contextlib import ExitStack
from . import batch
from .protocol import sha
from .mechanic_v3_runner import exclusive_json

FIRST_IDENTITY = 'Astra__G004_desert_observatory'
VERSION = 'unity-m-complete-two-column-admission.v1'
GATE_FILES = {'unity_m_admission.py', 'unity_m_capture.py', 'unity_m_evidence.py',
              'unity_m_judge.py', 'unity_m_runtime.py'}
REQUALIFICATION_FILES = {'unity_ide_metadata.py', 'unity_m_admission.py', 'unity_m_evidence.py',
                         'unity_m_input_adapter.py', 'unity_m_judge.py',
                         'unity_m_materialization_repair.py', 'unity_native_import_metadata.py'}
REQUALIFICATION_VERSION = 'unity-m-recorded-column-requalification.v1'
REQUALIFICATION_IDENTITY = 'Sol__G004_desert_observatory'
REQUALIFICATION_COLUMN = 'Mechanic'
REQUALIFICATION_BASELINE_FILES = {'unity_m_admission.py', 'unity_m_judge.py'}


def production():
    from .gameness_v3_runtime import production_bindings
    adapter = Path(__file__).resolve().parents[3]/'engine_adapters'
    return {**production_bindings(), **{str(p):sha(p) for p in sorted(adapter.rglob('*'))
        if p.is_file() and '__pycache__' not in p.parts and p.suffix in
        {'.py','.cs','.json','.asmdef','.shader','.cginc','.h','.cpp'}}}


def admission_path(workspace, current):
    digest = hashlib.sha256(json.dumps(current,sort_keys=True).encode()).hexdigest()
    return Path(workspace)/'engineering/unity_m_two_column_admissions'/(digest+'.json')


def verify_transition(root, transition, *, expected_production=None):
    value = batch.read(transition)
    executed = value['executed_producer']
    if value.get('classification') != 'GATE_ONLY_NO_SCORING_OR_TRANSPORT_CHANGE':
        raise ValueError('Explicit gate-only production transition required')
    candidates = [root/'unity_m_judge_producer.json', root/'unity_m_judge_continuation.json',
                  *sorted((root/'unity_m_judge_continuations').glob('*.json'))]
    if not any(p.exists() and (batch.read(p).get('after_producer',batch.read(p))) == executed for p in candidates):
        raise ValueError('Actual executed original or continued producer required')
    before,after = executed['production'],production() if expected_production is None else expected_production
    if value['current_production'] != after:
        raise ValueError('Current gate verifier producer drift')
    changed = {p for p in before.keys()|after.keys() if before.get(p)!=after.get(p)}
    directory = Path(__file__).resolve().parent
    if changed != set(value['changed_files']) or not changed or any(
            Path(p).parent!=directory or Path(p).name not in GATE_FILES for p in changed):
        raise ValueError('Gate-only complete production delta required')
    for name in changed:
        archive = value['changed_files'][name]
        if name in before:
            if not archive or sha(Path(archive))!=before[name]:
                raise ValueError('Exact archived executed producer bytes required')
        elif archive is not None:
            raise ValueError('New gate dependency must be explicit')
    regression = Path(value['regression']['path'])
    if (sha(regression)!=value['regression']['sha256'] or batch.read(regression).get('exit_code')!=0
            or batch.read(regression).get('tests_passed',0)<1):
        raise ValueError('Passing gate regression required')
    return value


def evidence(workspace, identity, *, selected_columns=('Mechanic','Gameness')):
    from . import two_column_sync
    workspace = Path(workspace).resolve()
    # Same order as publication/sync; hold a coherent read of both outputs.
    with ExitStack() as stack:
        for path in (workspace/'.publication.lock',
                     two_column_sync.TARGET.parent/'.targeted_publication.lock',
                     two_column_sync.TARGET.parent/'.two_column_publication.lock'):
            handle = stack.enter_context(path.open('a+'))
            fcntl.flock(handle, fcntl.LOCK_SH | fcntl.LOCK_NB)
        return _evidence_locked(workspace, identity, selected_columns=selected_columns)


def _evidence_locked(workspace, identity, *, selected_columns=('Mechanic','Gameness')):
    from . import unity_m_judge as judge, unity_m_evidence, two_column_sync
    from engine_adapters.unity3d.playtest import native_acceptance
    workspace=Path(workspace).resolve()
    recorded=workspace/'runs'/identity
    unity_m_evidence.qualify_recorded(recorded)
    pointer=batch.read(recorded/'unity_m_evidence.json');root=Path(pointer['root'])
    config=batch.read(recorded/'unity_m_native_dispatch/configuration.json')
    accepted=Path(config['editor_acceptance']);native=batch.read(accepted)
    native_acceptance.verify(accepted,Path(config['adapter_root']),Path(native['editor']))
    sync_config=batch.read(workspace/'two_column_sync.json')
    if sync_config != dict(target=str(two_column_sync.TARGET),namespace=judge.NAMESPACE):
        raise ValueError('Exact independent Unity M publication configuration required')
    registry=two_column_sync.TARGET.with_name('unity_m_mechanic_v3_gameness_v4_publications.json')
    state=batch.read(registry)
    if state['version']!=two_column_sync.VERSION:
        raise ValueError('Current versioned Unity M registry required')
    target_text=two_column_sync.TARGET.read_text()
    if two_column_sync.merge(target_text,state['rows'],namespace=judge.NAMESPACE)!=target_text:
        raise ValueError('Actual scores table must match Unity M registry')
    bindings={str(p):sha(p) for p in [recorded/'unity_m_capture.json', recorded/'unity_m_evidence.json',
        recorded/'background_record/runner_exit.json',recorded/'background_record/verification.json',
        recorded/'recorder_acceptance_binding.json',accepted,root/'unity_m_native_pixel_proof.json']}
    columns={}
    for column in selected_columns:
        key,row,proof=judge.sync_verified(workspace,identity,column)
        current=state['rows'].get(key)
        if (not current or any(current.get(k)!=v for k,v in row.items() if k!='columns')
                or current['columns'].get(column)!=row['columns'][column]):
            raise ValueError('Both complete original columns must actually be synchronized')
        publication=judge.publication_path(workspace,identity,column)
        successful=[p for p in (workspace/'sync_receipts').glob(identity+'_'+column+'_*.json')
            if batch.read(p).get('status')=='SYNCED' and batch.read(p).get('publication')==row['columns'][column]
            and batch.read(p).get('target')==str(two_column_sync.TARGET)]
        if not successful:raise ValueError('Actual per-column successful sync receipt required')
        bindings[str(publication)]=sha(publication)
        bindings[str(sorted(successful)[0])]=sha(sorted(successful)[0])
        columns[column]=dict(registry_key=key,column=row['columns'][column],delivery=proof)
    return root,dict(identity=identity,columns=columns,bindings=bindings,
        native_cleanup_verified=True,all_original_author_sources_and_native_pixels=True,
        status='SCORED_PENDING_AUDIT',audit_passed=False)


def create(workspace, transition):
    workspace=Path(workspace).resolve();root,proof=evidence(workspace,FIRST_IDENTITY)
    change=verify_transition(root,Path(transition));current=production()
    value=dict(version=VERSION,capability='UNITY_M_MECHANIC_V3_GAMENESS_V4_ORIGINAL_PIXELS',
        verification_production=current,executed_producer=change['executed_producer'],
        gate_transition=str(Path(transition).resolve()),gate_transition_sha256=sha(Path(transition)),
        e2e=proof,scoring_unchanged=True,model='gpt-6.1-sol')
    target=admission_path(workspace,current)
    if target.exists():
        if batch.read(target)!=value:raise ValueError('Immutable Unity M admission changed')
    else:exclusive_json(target,value)
    return target,value


def verify_recovered_transport(workspace, descriptor, *, expected_production=None):
    """A complete real recovery column plus the preserved two-column baseline.

    This accepts transport-only deltas; native and scoring code remain bound to
    the existing complete two-column native E2E. Current gate changes must be
    independently archived and regression-tested after the real recovery.
    """
    workspace=Path(workspace).resolve();v=batch.read(descriptor)
    if v.get('classification')!='REAL_COMPLETE_GAMENESS_TRANSPORT_RECOVERY':
        raise ValueError('Explicit complete recovered capability required')
    old_path=Path(v['prior_admission'])
    if sha(old_path)!=v['prior_admission_sha256']:raise ValueError('Historical admission changed')
    old=batch.read(old_path)
    if old.get('version')!=VERSION or old.get('transport_recovery'):
        raise ValueError('Original complete two-column admission required')
    old_root,old_proof=evidence(workspace,old['e2e']['identity'])
    if old_proof!=old['e2e']:raise ValueError('Preserved two-column E2E changed')
    transition=Path(old['gate_transition'])
    if sha(transition)!=old['gate_transition_sha256']:raise ValueError('Historical gate changed')
    verify_transition(old_root,transition,expected_production=old['verification_production'])
    identity=v['identity']
    if identity!='Sol__G004_desert_observatory' or v['column']!='Gameness':
        raise ValueError('Actual restricted recovery identity required')
    root,proof=evidence(workspace,identity,selected_columns=('Gameness',))
    process=Path(v['completed_process']['path'])
    if (sha(process)!=v['completed_process']['sha256'] or batch.read(process).get('exit_code')!=0):
        raise ValueError('Complete successful formal recovery process required')
    repair_path=Path(v['judge_repair']['path'])
    if sha(repair_path)!=v['judge_repair']['sha256']:raise ValueError('Executed recovery descriptor changed')
    repair=batch.read(repair_path);executed=repair['after_producer']
    candidates=list((root/'unity_m_judge_continuations').glob('*.json'))+[root/'unity_m_judge_continuation.json']
    matches=[p for p in candidates if p.exists() and batch.read(p).get('after_producer')==executed
        and batch.read(p).get('repair_path')==str(repair_path) and batch.read(p).get('repair_sha256')==sha(repair_path)]
    from .unity_m_judge import publication_path
    pub=batch.read(publication_path(workspace,identity,'Gameness'))
    if not matches or not any(pub['bindings'].get(str(p))==sha(p) for p in matches):
        raise ValueError('Actual published recovery producer binding required')
    numeric=Path(v['numeric_repair']['path'])
    if sha(numeric)!=v['numeric_repair']['sha256']:raise ValueError('Original numeric recovery changed')
    numeric_value=batch.read(numeric)
    process_value=batch.read(process)
    args=process_value.get('args',[])
    required={'--workspace':str(workspace),'--phase':'unity-m-judge','--ids':identity,
              '--column':'Gameness','--judge-repair':str(repair_path),'--numeric-event-repair':str(numeric)}
    if (len(args)<4 or args[1:4]!=['-u','-m','pipeline.eval.stage1.gameness_v4_runtime']
            or any(args.count(key)!=1 or args.index(key)+1>=len(args)
                   or args[args.index(key)+1]!=expected for key,expected in required.items())
            or not isinstance(process_value.get('pid'),int)
            or process_value.get('finished',0)<=process_value.get('started',0)):
        raise ValueError('Actual completed restricted formal judge invocation required')
    if (numeric_value['current_production']!=executed['production']
            or numeric_value['prior_admission_sha256']!=sha(old_path)
            or numeric_value['identity']!=identity or numeric_value['column']!='Gameness'
            or numeric_value.get('batch_admitted') is not False):
        raise ValueError('Exact restricted executed transport required')
    before=old['verification_production'];after=executed['production']
    changed={p for p in before.keys()|after.keys() if before.get(p)!=after.get(p)}
    from .unity_m_numeric_recovery import FILES
    if changed!=set(numeric_value['changed_files']):raise ValueError('Complete executed transport delta required')
    for p in changed:
        archive=numeric_value['changed_files'][p]
        if Path(p).parent!=Path(__file__).resolve().parent or Path(p).name not in FILES:
            raise ValueError('Recovery cannot admit changed native/scoring dependencies')
        if (p in before and (not archive or sha(Path(archive))!=before[p])) or (p not in before and archive is not None):
            raise ValueError('Exact original transport bytes required')
    for path,digest in numeric_value['continuation_failure_bindings'].items():
        if sha(Path(path))!=digest:raise ValueError('Preserved recovery failure changed')
    current=production() if expected_production is None else expected_production
    gate_changed={p for p in current.keys()|after.keys() if current.get(p)!=after.get(p)}
    if v['current_production']!=current or gate_changed!=set(v['gate_changed_files']):
        raise ValueError('Current complete recovery gate production required')
    for p in gate_changed:
        archive=v['gate_changed_files'][p]
        if Path(p)!=Path(__file__).resolve() or p not in after or not archive or sha(Path(archive))!=after[p]:
            raise ValueError('Only archived admission gate may change after real recovery')
    for spec in (v['regression'],numeric_value['regression']):
        path=Path(spec['path']);report=batch.read(path)
        if sha(path)!=spec['sha256'] or report.get('exit_code')!=0 or report.get('tests_passed',0)<1:
            raise ValueError('Passing recovery and gate regressions required')
    # Every independent new fork must have actually passed complete delivery.
    from .unity_m_runtime_reuse import VERSION as reuse_version
    judgments=[batch.read(p) for p in sorted((root/'judgments').glob('unity_m_gameness_group_*.json'))]
    if not any(r['actual_delivery'].get('runtime_reuse_version')==reuse_version for r in judgments):
        raise ValueError('Real complete unscored-runtime fork delivery required')
    return old,old_proof,proof,executed


def create_recovered(workspace, descriptor):
    old,old_proof,proof,executed=verify_recovered_transport(workspace,descriptor)
    value=dict(version=VERSION,capability='UNITY_M_MECHANIC_V3_GAMENESS_V4_ORIGINAL_PIXELS',
        verification_production=production(),executed_producer=executed,e2e=old_proof,
        transport_recovery=dict(descriptor=str(Path(descriptor).resolve()),sha256=sha(Path(descriptor)),e2e=proof),
        scoring_unchanged=True,model='gpt-6.1-sol')
    target=admission_path(workspace,value['verification_production'])
    if target.exists():
        if batch.read(target)!=value:raise ValueError('Immutable recovered admission changed')
    else:exclusive_json(target,value)
    return target,value


def _check_regression(spec):
    path=Path(spec['path']);report=batch.read(path)
    if sha(path)!=spec['sha256'] or report.get('exit_code')!=0 or report.get('tests_passed',0)<1:
        raise ValueError('Passing requalification regression required')


def _approved_requalification_delta(workspace, prior_path, prior, current):
    repair_path=Path(workspace)/'engineering/unity_m_materialization_repair.json'
    repair=batch.read(repair_path)
    prior_ref=repair.get('prior_admission',{})
    if (repair.get('version')!='unity-m-recorded-editor-settings-repair.v1'
            or repair.get('identity')!='Kimi__G013_wind_tower_grapple'
            or repair.get('new_native_calls')!=0 or repair.get('batch_admitted') is not False
            or Path(prior_ref.get('path','')).resolve()!=prior_path
            or prior_ref.get('sha256')!=sha(prior_path)):
        raise ValueError('Exact non-batch recorded materialization delta required')
    # The approved materialization producer is the baseline. Later recorded-only
    # maintenance may change only these two gates, and must bind both old bytes.
    baseline=repair.get('current_production',{})
    before=prior.get('verification_production',{})
    materialization_changed={p for p in before.keys()|baseline.keys()
                             if before.get(p)!=baseline.get(p)}
    if (not baseline or materialization_changed!=set(repair.get('changed_files',{}))
            or len(repair.get('regression',{}))==0):
        raise ValueError('Complete approved materialization production baseline required')
    from .unity_m_materialization_repair import FILES
    for name in materialization_changed:
        archive=repair['changed_files'][name]
        if (Path(name).parent!=Path(__file__).resolve().parent or Path(name).name not in FILES
                or name not in baseline
                or (name in before and (not archive or sha(Path(archive))!=before[name]))
                or (name not in before and archive is not None)):
            raise ValueError('Exact archived materialization producer required')
    regression=repair['regression'];regression_path=Path(regression['path'])
    report=batch.read(regression_path)
    if (sha(regression_path)!=regression['sha256'] or report.get('exit_code')!=0
            or report.get('tests_passed',0)<1):
        raise ValueError('Passing approved materialization regression required')
    changed={p for p in baseline.keys()|current.keys() if baseline.get(p)!=current.get(p)}
    directory=Path(__file__).resolve().parent
    expected={str(directory/name) for name in REQUALIFICATION_BASELINE_FILES}
    if changed!=expected or not set(current)>=set(baseline):
        raise ValueError('Exact recorded admission and judge maintenance delta required')
    archive_root=Path(workspace)/'engineering/archive_20261107_requalification_before_code'
    old_archives={
        'unity_m_admission.py': archive_root/'unity_m_admission.py.before',
        'unity_m_judge.py': archive_root/'unity_m_judge.py.pre_followup.before',
    }
    for name,path in old_archives.items():
        full=str(directory/name)
        if (baseline.get(full)!=sha(path)
                or current.get(full)==baseline.get(full)):
            raise ValueError('Exact archived Sol G004 requalification producer bytes required')
    return repair_path,repair


def _prior_case_e2e(workspace, identity, prior):
    if prior.get('transport_recovery'):
        recovery=prior['transport_recovery'];descriptor=Path(recovery['descriptor'])
        if sha(descriptor)!=recovery['sha256']:
            raise ValueError('Prior recovery descriptor changed')
        _,base,case,executed=verify_recovered_transport(workspace,descriptor,
            expected_production=prior['verification_production'])
        if (base!=prior['e2e'] or case!=recovery['e2e']
                or executed!=prior['executed_producer'] or case.get('identity')!=identity):
            raise ValueError('Prior recovered case E2E binding changed')
        return case
    if prior.get('e2e',{}).get('identity')!=identity:
        raise ValueError('Same-identity completed Unity M admission required')
    if prior.get('materialization_recovery'):
        from .unity_m_materialization_repair import verify_completed
        verify_completed(workspace,prior)
    else:
        transition=Path(prior['gate_transition'])
        if sha(transition)!=prior['gate_transition_sha256']:
            raise ValueError('Prior gate transition changed')
        verify_transition(workspace/'runs'/identity,transition,
            expected_production=prior['verification_production'])
    return prior['e2e']


def create_requalification(workspace, identity, column, prior_admission, regression):
    """Grant one recorded judge operation for the explicitly qualified case."""
    workspace=Path(workspace).resolve();prior_path=Path(prior_admission).resolve()
    if isinstance(regression,(str,Path)):
        regression_path=Path(regression).resolve()
        regression=dict(path=str(regression_path),sha256=sha(regression_path))
    prior=batch.read(prior_path);current=production()
    if (identity!=REQUALIFICATION_IDENTITY or column!=REQUALIFICATION_COLUMN
            or prior.get('version')!=VERSION):
        raise ValueError('Only the frozen Sol G004 Mechanic recorded column is authorized')
    case_e2e=_prior_case_e2e(workspace,identity,prior)
    other={'Mechanic':'Gameness','Gameness':'Mechanic'}[column]
    if column in case_e2e.get('columns',{}) or 'Gameness' not in case_e2e.get('columns',{}):
        raise ValueError('A missing Mechanic column and synced Gameness baseline are required')
    repair_path,repair=_approved_requalification_delta(workspace,prior_path,prior,current)
    archives=repair['changed_files']
    _check_regression(regression)
    _,partial=evidence(workspace,identity,selected_columns=(other,))
    if partial['columns'][other]['column']!=case_e2e['columns'][other]['column']:
        raise ValueError('Existing synchronized column differs from the admission baseline')
    pointer=batch.read(workspace/'runs'/identity/'unity_m_evidence.json')
    value=dict(version=REQUALIFICATION_VERSION,identity=identity,column=column,allowed_operation='judge',
        verification_production=current,prior_admission=str(prior_path),prior_admission_sha256=sha(prior_path),
        prior_e2e=case_e2e,approved_delta=dict(path=str(repair_path),sha256=sha(repair_path)),
        source_evidence=str(workspace/'runs'/identity/'unity_m_evidence.json'),
        source_evidence_sha256=sha(workspace/'runs'/identity/'unity_m_evidence.json'),
        source_root=pointer['root'],source_root_proof_sha256=sha(Path(pointer['root'])/'unity_m_native_pixel_proof.json'),
        changed_files=archives,regression=dict(regression),other_column=other,other_column_proof=partial,
        new_native_calls=0,new_judge_operations=1)
    target=workspace/'engineering/unity_m_requalification.json'
    if target.exists():
        if batch.read(target)!=value:raise ValueError('Immutable requalification descriptor already exists')
    else:exclusive_json(target,value)
    return target,value


def requalification_path(workspace, current):
    parent=Path(workspace)/'engineering/unity_m_requalification.json'
    if parent.exists() and batch.read(parent).get('verification_production')==current:return parent
    return Path(workspace)/'engineering/unity_m_requalification_continuations'/admission_path(workspace,current).name


def _verify_recorded_continuation(workspace, value, current):
    capacity=value.get('version')=='unity-m-recorded-endpoint-capacity-continuation.v1'
    if (value.get('version') not in {'unity-m-recorded-column-requalification-continuation.v1','unity-m-recorded-endpoint-capacity-continuation.v1'}
            or value.get('verification_production')!=current):
        raise ValueError('Exact recorded continuation production required')
    ref=value['parent_requalification'];parent_path=Path(ref['path'])
    if sha(parent_path)!=ref['sha256']:raise ValueError('Immutable recorded parent changed')
    parent=batch.read(parent_path)
    expected='unity-m-recorded-column-requalification-continuation.v1' if capacity else REQUALIFICATION_VERSION
    if parent.get('version')!=expected:
        raise ValueError('One substantive recorded continuation per preserved qualification')
    if parent.get('version')=='unity-m-recorded-column-requalification-continuation.v1':
        verified=_verify_recorded_continuation(workspace,parent,parent['verification_production'])
    else:
        verified=verify_requalification(workspace,REQUALIFICATION_IDENTITY,'judge',
            descriptor=parent_path,expected_production=parent['verification_production'])
    for key in ('identity','column','allowed_operation','prior_admission','prior_admission_sha256',
                'source_evidence','source_evidence_sha256','source_root','source_root_proof_sha256',
                'other_column','other_column_proof','new_native_calls','new_judge_operations'):
        if value.get(key)!=verified[key]:raise ValueError('Recorded continuation scope changed: '+key)
    before=parent['verification_production']
    delta={p for p in before.keys()|current.keys() if before.get(p)!=current.get(p)}
    directory=Path(__file__).resolve().parent
    allowed=('unity_m_admission.py','unity_m_schema_recovery.py') if capacity else REQUALIFICATION_BASELINE_FILES
    if delta!={str(directory/n) for n in allowed} or delta!=set(value['continuation_changed_files']):
        raise ValueError('Only exact recorded admission and endpoint transport delta permitted')
    for name in delta:
        if sha(Path(value['continuation_changed_files'][name]))!=before[name]:
            raise ValueError('Exact prior recorded producer archive required')
    failures=value.get('continuation_failure_bindings',{})
    if not failures or any(sha(Path(p))!=digest for p,digest in failures.items()):
        raise ValueError('Preserved actual recorded transport failure required')
    failure_text='Measured complete runtime plus final schema exceeds window' if capacity else 'Column remains blocked by preserved parent transport: evidence_01'
    if not any(failure_text in Path(p).read_text() for p in failures):
        raise ValueError('Original blocked Mechanic endpoint failure required')
    _check_regression(value['regression'])
    return value


def create_requalification_continuation(workspace, descriptor):
    workspace=Path(workspace).resolve();value=batch.read(descriptor);current=production()
    _verify_recorded_continuation(workspace,value,current)
    target=requalification_path(workspace,current)
    if target.exists():
        if batch.read(target)!=value:raise ValueError('Immutable recorded continuation exists')
    else:exclusive_json(target,value)
    return target,value


def verify_requalification(workspace, identity, operation, *, descriptor=None, expected_production=None):
    workspace=Path(workspace).resolve();current=production() if expected_production is None else expected_production
    descriptor=Path(descriptor) if descriptor is not None else requalification_path(workspace,current)
    value=batch.read(descriptor)
    if value.get('version') in {'unity-m-recorded-column-requalification-continuation.v1','unity-m-recorded-endpoint-capacity-continuation.v1'}:
        if identity!=REQUALIFICATION_IDENTITY or operation!='judge':raise ValueError('Recorded continuation scope mismatch')
        return _verify_recorded_continuation(workspace,value,current)
    if (value.get('version')!=REQUALIFICATION_VERSION or identity!=REQUALIFICATION_IDENTITY
            or value.get('identity')!=identity or value.get('column')!=REQUALIFICATION_COLUMN
            or value.get('allowed_operation')!=operation
            or value.get('verification_production')!=current or value.get('new_native_calls')!=0
            or value.get('new_judge_operations')!=1):
        raise ValueError('Exact one-column recorded requalification required')
    prior_path=Path(value['prior_admission'])
    if sha(prior_path)!=value['prior_admission_sha256']:
        raise ValueError('Requalification baseline admission changed')
    prior=batch.read(prior_path)
    repair_path,repair=_approved_requalification_delta(workspace,prior_path,prior,current)
    approved=value.get('approved_delta',{})
    if (Path(approved.get('path','')).resolve()!=repair_path.resolve()
            or approved.get('sha256')!=sha(repair_path)
            or value.get('changed_files')!=repair['changed_files']):
        raise ValueError('Approved exact production delta binding changed')
    _check_regression(value['regression'])
    case_e2e=_prior_case_e2e(workspace,identity,prior)
    if value.get('prior_e2e')!=case_e2e:
        raise ValueError('Prior source-bound case E2E changed')
    evidence_path=Path(value['source_evidence'])
    if sha(evidence_path)!=value['source_evidence_sha256'] or evidence_path!=workspace/'runs'/identity/'unity_m_evidence.json':
        raise ValueError('Recorded evidence binding changed')
    pointer=batch.read(evidence_path)
    if pointer.get('root')!=value['source_root'] or sha(Path(pointer['root'])/'unity_m_native_pixel_proof.json')!=value['source_root_proof_sha256']:
        raise ValueError('Original pixel proof binding changed')
    _,partial=evidence(workspace,identity,selected_columns=(value['other_column'],))
    if partial!=value['other_column_proof']:
        raise ValueError('Existing synchronized column proof changed')
    return value


def complete_requalification(workspace, descriptor):
    workspace=Path(workspace).resolve();value=batch.read(descriptor)
    qualified=verify_requalification(workspace,value['identity'],'judge')
    if qualified!=value:raise ValueError('Requalification descriptor changed')
    root,proof=evidence(workspace,value['identity'])
    candidates=[root/'unity_m_judge_producer.json',root/'unity_m_judge_continuation.json',
                *sorted((root/'unity_m_judge_continuations').glob('*.json'))]
    producers=[batch.read(p).get('after_producer',batch.read(p)) for p in candidates if p.exists()]
    matching=[p for p in producers if p.get('production')==production()]
    if not matching:raise ValueError('Completed two-column E2E must execute the current full producer')
    producer=matching[0]
    result=dict(version=VERSION,capability='UNITY_M_MECHANIC_V3_GAMENESS_V4_ORIGINAL_PIXELS',
        verification_production=production(),executed_producer=producer,e2e=proof,
        requalification=dict(path=str(Path(descriptor).resolve()),sha256=sha(descriptor)),
        scoring_unchanged=True,model='gpt-6.1-sol')
    target=admission_path(workspace,result['verification_production'])
    if target.exists():
        if batch.read(target)!=result:raise ValueError('Immutable requalified admission changed')
    else:exclusive_json(target,result)
    return target,result


def verify_completed_transition(workspace, descriptor, *, expected_production=None, verification_archives=None):
    """Revalidate a completed recorded E2E across an exact label/gate delta.

    The executed producer is historical. Only this verifier and the explicit
    v4 self-identification assignment may differ; runtime/scoring/transport
    dependencies must remain byte-identical to the successful producer.
    """
    workspace=Path(workspace).resolve();value=batch.read(descriptor)
    if (value.get('version')!='unity-m-completed-requalification-transition.v1'
            or value.get('classification')!='COMPLETED_E2E_EXACT_V4_LABEL_AND_GATE_ONLY'
            or value.get('model_recalled') is not False
            or value.get('score_changed') is not False):
        raise ValueError('Explicit completed E2E label/gate transition required')
    ref=value['completed_requalification'];historical_path=Path(ref['path'])
    if sha(historical_path)!=ref['sha256']:
        raise ValueError('Historical completed qualification changed')
    historical=batch.read(historical_path);before=historical['verification_production']
    qualified=verify_requalification(workspace,REQUALIFICATION_IDENTITY,'judge',
        descriptor=historical_path,expected_production=before)
    if qualified!=historical:
        raise ValueError('Historical completed qualification differs')
    current=production() if expected_production is None else expected_production;directory=Path(__file__).resolve().parent
    delta={p for p in before.keys()|current.keys() if before.get(p)!=current.get(p)}
    expected={str(directory/n) for n in ('unity_m_admission.py','gameness_v4.py')}
    if (value.get('verification_production')!=current or delta!=expected
            or set(value.get('changed_files',{}))!=expected):
        raise ValueError('Only exact completed verifier and v4 label delta permitted')
    for name in delta:
        archive=Path(value['changed_files'][name])
        # An outer exact-delta verification can recheck an immutable historical
        # transition after this verifier changed. Its verification-side bytes
        # must also be explicit archives; never compare an old map to live code.
        comparison = Path(name)
        if expected_production is not None and sha(comparison) != current[name]:
            archived = (verification_archives or {}).get(name)
            if archived is None:
                raise ValueError('Exact historical verification producer archive required')
            comparison = Path(archived)
        if sha(archive)!=before[name] or sha(comparison)!=current[name]:
            raise ValueError('Exact archived completed producer bytes required')
    label=str(directory/'gameness_v4.py')
    old=Path(value['changed_files'][label]).read_bytes()
    assignment=b'INSTRUCTION = shared.INSTRUCTION\n'
    replacement=(b'# Keep the v4 runtime request self-identifying while preserving the frozen\n'
        b'# original-check policy and all shared scoring/schema behavior.\n'
        b"INSTRUCTION = shared.INSTRUCTION.replace('Gameness v3', 'Gameness v4')\n")
    if old.count(assignment)!=1 or old.replace(assignment,replacement)!=Path(label).read_bytes():
        raise ValueError('Only exact self-identification substitution is equivalent')
    _check_regression(value['regression'])
    root,proof=evidence(workspace,REQUALIFICATION_IDENTITY)
    candidates=[root/'unity_m_judge_producer.json',root/'unity_m_judge_continuation.json',
                *sorted((root/'unity_m_judge_continuations').glob('*.json'))]
    producers=[batch.read(p).get('after_producer',batch.read(p)) for p in candidates if p.exists()]
    executed=value.get('executed_producer')
    if (not executed or executed.get('production')!=before or executed not in producers
            or proof!=value.get('e2e')):
        raise ValueError('Actual completed historical producer and both synchronized columns required')
    return value


def create_completed_transition(workspace, descriptor):
    change=verify_completed_transition(workspace,descriptor)
    value=dict(version=VERSION,capability='UNITY_M_MECHANIC_V3_GAMENESS_V4_ORIGINAL_PIXELS',
        verification_production=production(),executed_producer=change['executed_producer'],
        e2e=change['e2e'],completed_transition=dict(path=str(Path(descriptor).resolve()),
        sha256=sha(descriptor)),scoring_unchanged=True,model='gpt-6.1-sol')
    target=admission_path(workspace,value['verification_production'])
    if target.exists():
        if batch.read(target)!=value:raise ValueError('Immutable completed transition admission changed')
    else:exclusive_json(target,value)
    return target,value



NATIVE_LEASE_FILES = {'unity_m_capture.py', 'unity_m_admission.py', 'unity_m_completed_recovery.py'}


def validate_native_lease_delta(before, after, archives):
    directory = Path(__file__).resolve().parent
    changed = {p for p in before.keys()|after.keys() if before.get(p)!=after.get(p)}
    expected = {str(directory/name) for name in NATIVE_LEASE_FILES}
    if changed != expected or set(archives) != expected:
        raise ValueError('Only exact native queue wait and historical gate delta permitted')
    for name in changed:
        if name not in before or not archives[name] or sha(Path(archives[name])) != before[name]:
            raise ValueError('Exact prior admitted native lease bytes required')


def verify_native_lease_recovery(workspace, descriptor, *, expected_production=None):
    from .unity_m_completed_recovery import verify as completed
    value = batch.read(descriptor)
    current = production() if expected_production is None else expected_production
    if (value.get('version')!='unity-m-native-lease-wait-recovery.v1'
            or value.get('classification')!='NATIVE_QUEUE_LEASE_WAIT_ONLY'
            or value.get('verification_production')!=current
            or value.get('scoring_changed') is not False
            or value.get('new_native_calls_during_registration')!=0):
        raise ValueError('Explicit source-bound native lease recovery required')
    parent = Path(value['prior_admission']['path'])
    if sha(parent)!=value['prior_admission']['sha256']:
        raise ValueError('Prior complete native admission changed')
    prior = batch.read(parent)
    before = prior['verification_production']
    if (prior.get('version')!=VERSION or parent!=admission_path(workspace,before)
            or not prior.get('completed_recorded_recovery')):
        raise ValueError('Exact completed two-column parent admission required')
    validate_native_lease_delta(before,current,value['changed_files'])
    ref = prior['completed_recorded_recovery']; old = Path(ref['path'])
    if sha(old)!=ref['sha256']:
        raise ValueError('Preserved completed recovery descriptor changed')
    qualified = completed(workspace,old,expected_production=before)
    if (qualified['e2e']!=prior['e2e'] or qualified['executed_producer']!=prior['executed_producer']):
        raise ValueError('Complete historical original source/pixel two-column E2E required')
    failed = Path(value['parent_failure']['path'])
    if sha(failed)!=value['parent_failure']['sha256']:
        raise ValueError('Actual prelaunch native lease failure changed')
    failure = batch.read(failed)
    if (failure.get('stage')!='PRELAUNCH_SHARED_QUEUE_LOCK' or failure.get('exit_code')!=1
            or failure.get('error')!='BlockingIOError: [Errno 35] Resource temporarily unavailable'
            or failure.get('editor_launched') is not False
            or failure.get('native_dispatch_exists') is not False):
        raise ValueError('Actual original prelaunch shared lease failure required')
    _check_regression(value['regression'])
    return value, prior


def create_native_lease_recovery(workspace, descriptor):
    change, prior = verify_native_lease_recovery(workspace,descriptor)
    value = dict(version=VERSION,capability=prior['capability'],
        verification_production=production(),executed_producer=prior['executed_producer'],
        e2e=prior['e2e'],native_lease_recovery=dict(path=str(Path(descriptor).resolve()),sha256=sha(descriptor)),
        scoring_unchanged=True,model='gpt-6.1-sol')
    target = admission_path(workspace,value['verification_production'])
    if target.exists():
        if batch.read(target)!=value:raise ValueError('Immutable native lease recovery admission changed')
    else:exclusive_json(target,value)
    return target,value


def require(workspace, identity, *, acceptance_case=False, operation=None, column=None):
    if acceptance_case:
        if identity!=FIRST_IDENTITY:
            raise ValueError('Bootstrap acceptance flag cannot admit another identity')
        return dict(bootstrap=True,identity=identity)
    current=production();path=admission_path(workspace,current)
    if not path.exists():
        direct=Path(workspace)/'engineering/unity_m_g018_direct_bug_repair.json'
        if direct.exists():
            from .unity_m_direct_bug_recovery import require as require_direct
            return require_direct(workspace,identity,operation,column,direct)
        editor_plan_followups=(
            Path(workspace)/'engineering/unity_m_editor_plan_followup_ue5_external.json',
            Path(workspace)/'engineering/unity_m_editor_plan_followup.json',
        )
        editor_plan_followup=next((p for p in editor_plan_followups if p.exists()),None)
        if editor_plan_followup is not None:
            from .unity_m_editor_local_recovery import qualify
            return qualify(workspace,identity,operation,editor_plan_followup)
        editor_followup=Path(workspace)/'engineering/unity_m_editor_import_followup.json'
        if editor_followup.exists():
            from .unity_m_editor_local_recovery import qualify
            return qualify(workspace,identity,operation,editor_followup)
        editor_repair=Path(workspace)/'engineering/unity_m_editor_local_repair.json'
        if editor_repair.exists():
            from .unity_m_editor_local_recovery import qualify
            return qualify(workspace,identity,operation,editor_repair)
        snapshot_repair=Path(workspace)/'engineering/unity_m_snapshot_policy_repair.json'
        if snapshot_repair.exists():
            from .unity_m_snapshot_recovery import qualify
            return qualify(workspace,identity,operation,snapshot_repair)
        incomplete=Path(workspace)/'engineering/unity_m_incomplete_repair.json'
        if incomplete.exists() and operation=='judge':
            from .unity_m_incomplete_recovery import require as require_incomplete
            return require_incomplete(workspace,identity,column,incomplete)
        observed=Path(workspace)/'engineering/unity_m_observed_bug_repair.json'
        if observed.exists() and operation=='judge':
            from .unity_m_observed_bug_recovery import require as require_observed
            return require_observed(workspace,identity,column,observed)
        shared=Path(workspace)/'engineering/unity_m_shared_schema_repair.json'
        if shared.exists() and operation=='judge':
            from .unity_m_shared_schema_repair import require as require_shared
            return require_shared(workspace,identity,column,shared)
        requalification=requalification_path(workspace,current)
        if requalification.exists() and operation=='judge':
            value=verify_requalification(workspace,identity,'judge')
            if column!=value['column']:
                raise ValueError('Recorded requalification is bound to another column')
            return dict(restricted=True,identity=identity,column=value['column'],operation='judge',
                requalification=str(requalification),sha256=sha(requalification))
        repair=Path(workspace)/'engineering/unity_m_materialization_repair.json'
        if repair.exists() and operation in {'evidence','judge'}:
            from .unity_m_materialization_repair import qualify
            return qualify(workspace,identity,repair)
        raise ValueError('Complete matching Unity M two-column E2E admission required')
    value=batch.read(path)
    if value.get('version')!=VERSION or value.get('verification_production')!=current:
        raise ValueError('Unity M admission producer changed')
    if value.get('resume_context_recovery'):
        from .unity_m_resume_context import verify_complete
        ref=value['resume_context_recovery'];descriptor=Path(ref['path'])
        if sha(descriptor)!=ref['sha256']:
            raise ValueError('Completed resume-context recovery changed')
        proof,producer=verify_complete(workspace,descriptor)
        if proof!=value['e2e'] or producer!=value['executed_producer']:
            raise ValueError('Completed recorded resume-context E2E changed')
        return value
    if value.get('direct_bug_recovery'):
        from .unity_m_direct_bug_recovery import verify_complete
        ref=value['direct_bug_recovery'];descriptor=Path(ref['path'])
        if sha(descriptor)!=ref['sha256']:
            raise ValueError('Completed direct counterexample recovery changed')
        _,proof,producer=verify_complete(workspace,descriptor)
        if proof!=value['e2e'] or producer!=value['executed_producer']:
            raise ValueError('Completed recorded direct counterexample E2E changed')
        return value
    if value.get('editor_local_recovery'):
        from .unity_m_editor_local_recovery import verify_complete
        ref=value['editor_local_recovery'];descriptor=Path(ref['path'])
        if sha(descriptor)!=ref['sha256']:
            raise ValueError('Completed native Editor-local recovery changed')
        _,proof,producer=verify_complete(workspace,descriptor)
        if proof!=value['e2e'] or producer!=value['executed_producer']:
            raise ValueError('Completed native Editor-local E2E changed')
        return value
    if value.get('snapshot_policy_recovery'):
        from .unity_m_snapshot_recovery import verify_complete
        ref=value['snapshot_policy_recovery'];descriptor=Path(ref['path'])
        if sha(descriptor)!=ref['sha256']:raise ValueError('Snapshot recovery descriptor changed')
        _,proof,producer=verify_complete(workspace,descriptor)
        if proof!=value['e2e'] or producer!=value['executed_producer']:
            raise ValueError('Completed snapshot recovery E2E changed')
        return value
    if value.get('native_lease_recovery'):
        ref=value['native_lease_recovery'];descriptor=Path(ref['path'])
        if sha(descriptor)!=ref['sha256']:raise ValueError('Native lease recovery descriptor changed')
        _,prior=verify_native_lease_recovery(workspace,descriptor)
        if prior['e2e']!=value['e2e'] or prior['executed_producer']!=value['executed_producer']:
            raise ValueError('Native lease recovery complete historical E2E changed')
        return value
    if value.get('completed_recorded_recovery'):
        from .unity_m_completed_recovery import verify as verify_completed_recovery
        ref = value['completed_recorded_recovery']; descriptor = Path(ref['path'])
        if sha(descriptor) != ref['sha256']:
            raise ValueError('Completed recorded recovery descriptor changed')
        change = verify_completed_recovery(workspace, descriptor)
        if change['e2e'] != value['e2e'] or change['executed_producer'] != value['executed_producer']:
            raise ValueError('Completed recorded recovery admission evidence changed')
        return value
    if value.get('completed_transition'):
        ref=value['completed_transition'];descriptor=Path(ref['path'])
        if sha(descriptor)!=ref['sha256']:raise ValueError('Completed E2E transition changed')
        change=verify_completed_transition(workspace,descriptor)
        if change['e2e']!=value['e2e'] or change['executed_producer']!=value['executed_producer']:
            raise ValueError('Completed E2E admission evidence changed')
        return value
    if value.get('requalification'):
        ref=value['requalification'];descriptor=Path(ref['path'])
        if sha(descriptor)!=ref['sha256']:raise ValueError('Completed recorded qualification changed')
        qualified=verify_requalification(workspace,value['e2e']['identity'],'judge',descriptor=descriptor)
        root,proof=evidence(workspace,qualified['identity'])
        candidates=[root/'unity_m_judge_producer.json',root/'unity_m_judge_continuation.json',
                    *sorted((root/'unity_m_judge_continuations').glob('*.json'))]
        if (proof!=value['e2e'] or not any(p.exists() and batch.read(p).get('after_producer',batch.read(p))==value['executed_producer'] for p in candidates)):
            raise ValueError('Completed recorded E2E producer or evidence changed')
        return value
    if value.get('materialization_recovery'):
        from .unity_m_materialization_repair import verify_completed
        verify_completed(workspace,value)
        return value
    if value.get('transport_recovery'):
        recovery=value['transport_recovery'];descriptor=Path(recovery['descriptor'])
        if sha(descriptor)!=recovery['sha256']:raise ValueError('Recovered admission descriptor changed')
        _,old_proof,proof,executed=verify_recovered_transport(workspace,descriptor)
        if proof!=recovery['e2e'] or old_proof!=value['e2e'] or executed!=value['executed_producer']:
            raise ValueError('Complete recovered E2E changed')
        return value
    transition=Path(value['gate_transition'])
    if sha(transition)!=value['gate_transition_sha256']:
        raise ValueError('Gate transition changed')
    root,proof=evidence(workspace,value['e2e']['identity'])
    verify_transition(root,transition)
    if proof!=value['e2e']:raise ValueError('Complete original E2E qualification changed')
    return value


def reconcile_preinput_cleanup(workspace, identity, configuration):
    """Release only a proven dead, pre-runtime owned capture; never score it."""
    from .unity_axis_recovery import reconcile_interrupted_cleanup
    workspace=Path(workspace).resolve();root=(workspace/'runs'/identity).resolve()
    if root.parent!=workspace/'runs':raise ValueError('Exact workspace run required')
    config=batch.read(Path(configuration))
    if config!=batch.read(root/'unity_m_native_dispatch/configuration.json'):
        raise ValueError('Exact failed dispatch configuration required')
    capture=root/'background_record'
    if (capture/'take/play_started.json').exists():
        raise ValueError('Pre-runtime cleanup cannot qualify a started capture')
    control=Path(config['control_root'])
    with ExitStack() as stack:
        for path in (workspace/'.unity_m_native.lock',control/'whitebox_production_queue.lock'):
            handle=stack.enter_context(path.open('a+'))
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        result=reconcile_interrupted_cleanup(root/'unity_m_native_dispatch',root,config)
    if result is None:raise ValueError('No matching cleanup stop marker')
    return result,batch.read(result)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workspace',type=Path,required=True)
    p.add_argument('--phase',choices=['unity-m-admit'],required=True)
    route=p.add_mutually_exclusive_group(required=True)
    route.add_argument('--reconcile-preinput-cleanup',nargs=2,metavar=('IDENTITY','CONFIGURATION'))
    route.add_argument('--postexit-resource-release',nargs=3,metavar=('IDENTITY','CONFIGURATION','REPAIR'))
    route.add_argument('--native-lease-recovery',type=Path)
    route.add_argument('--snapshot-policy-recovery',type=Path)
    route.add_argument('--editor-local-recovery',type=Path)
    route.add_argument('--recorded-resume-context-repair',type=Path)
    route.add_argument('--completed-resume-context-recovery',type=Path)
    route.add_argument('--recorded-direct-bug-repair',type=Path)
    route.add_argument('--completed-direct-bug-recovery',type=Path)
    route.add_argument('--completed-recorded-recovery',type=Path)
    route.add_argument('--recorded-incomplete-repair',type=Path)
    route.add_argument('--recorded-shared-schema-repair',type=Path)
    route.add_argument('--gate-transition',type=Path)
    route.add_argument('--transport-recovery',type=Path)
    route.add_argument('--materialization-recovery',type=Path)
    route.add_argument('--requalification-plan',nargs=3,metavar=('IDENTITY','COLUMN','PRIOR_ADMISSION'))
    p.add_argument('--regression',type=Path)
    route.add_argument('--completed-requalification-transition',type=Path)
    route.add_argument('--complete-requalification',type=Path)
    route.add_argument('--requalification-continuation',type=Path)
    a=p.parse_args(argv)
    if a.postexit_resource_release:
        from .unity_postexit_cleanup import release
        path,value=release(a.workspace,*a.postexit_resource_release)
        print('UNITY_M_POSTEXIT_RESOURCES_RELEASED_CAPTURE_STILL_INVALID',path,flush=True)
        return 0
    elif a.recorded_resume_context_repair:
        from .unity_m_resume_context import register
        path,value=register(a.workspace,a.recorded_resume_context_repair)
        print('UNITY_M_G018_RESUME_CONTEXT_REPAIR_RESTRICTED',path,flush=True)
        return 0
    elif a.completed_resume_context_recovery:
        from .unity_m_resume_context import create
        path,value=create(a.workspace,a.completed_resume_context_recovery)
    elif a.recorded_direct_bug_repair:
        from .unity_m_direct_bug_recovery import register
        path,value=register(a.workspace,a.recorded_direct_bug_repair)
        print('UNITY_M_G018_DIRECT_BUG_REPAIR_RESTRICTED',path,flush=True)
        return 0
    elif a.completed_direct_bug_recovery:
        from .unity_m_direct_bug_recovery import create
        path,value=create(a.workspace,a.completed_direct_bug_recovery)
    elif a.editor_local_recovery:
        from .unity_m_editor_local_recovery import create
        path,value=create(a.workspace,a.editor_local_recovery)
    elif a.snapshot_policy_recovery:
        from .unity_m_snapshot_recovery import create as create_snapshot_recovery
        path,value=create_snapshot_recovery(a.workspace,a.snapshot_policy_recovery)
    elif a.native_lease_recovery:
        path,value=create_native_lease_recovery(a.workspace,a.native_lease_recovery)
    elif a.completed_recorded_recovery:
        from .unity_m_completed_recovery import create as create_completed_recovery
        path,value=create_completed_recovery(a.workspace,a.completed_recorded_recovery)
    elif a.recorded_incomplete_repair:
        from .unity_m_incomplete_recovery import register
        path,value=register(a.workspace,a.recorded_incomplete_repair)
        print('UNITY_M_RECORDED_INCOMPLETE_REPAIR_RESTRICTED',path,flush=True)
        return 0
    elif a.recorded_shared_schema_repair:
        from .unity_m_shared_schema_repair import register
        if batch.read(a.recorded_shared_schema_repair).get('version')=='unity-m-observed-counterexample-correction.v1':
            from .unity_m_observed_bug_recovery import register
        path,value=register(a.workspace,a.recorded_shared_schema_repair)
        print('UNITY_M_RECORDED_SHARED_SCHEMA_REPAIR_RESTRICTED',path,flush=True)
        return 0
    elif a.reconcile_preinput_cleanup:
        if a.regression:p.error('Cleanup reconciliation uses existing immutable process evidence')
        path,value=reconcile_preinput_cleanup(a.workspace,*a.reconcile_preinput_cleanup)
        print('UNITY_M_FAILED_CAPTURE_CLEANUP_RECONCILED_NOT_SCORED',path,flush=True)
        return 0
    elif a.requalification_plan:
        if not a.regression: p.error('--regression is required with --requalification-plan')
        path,value=create_requalification(a.workspace,*a.requalification_plan,a.regression)
    elif a.requalification_continuation:
        if a.regression:p.error('Regression must be bound in continuation descriptor')
        path,value=create_requalification_continuation(a.workspace,a.requalification_continuation)
    elif a.completed_requalification_transition:
        if a.regression:p.error('Regression must be bound in completed transition descriptor')
        path,value=create_completed_transition(a.workspace,a.completed_requalification_transition)
    elif a.complete_requalification:
        if a.regression: p.error('--regression is only valid with --requalification-plan')
        path,value=complete_requalification(a.workspace,a.complete_requalification)
    elif a.materialization_recovery:
        if a.regression: p.error('--regression is only valid with --requalification-plan')
        from .unity_m_materialization_repair import create_completed
        path,value=create_completed(a.workspace,a.materialization_recovery)
    else:
        if a.regression: p.error('--regression is only valid with --requalification-plan')
        path,value=(create_recovered(a.workspace,a.transport_recovery) if a.transport_recovery else create(a.workspace,a.gate_transition))
    print('UNITY_M_TWO_COLUMN_E2E_ADMITTED',path,flush=True)
    return 0
