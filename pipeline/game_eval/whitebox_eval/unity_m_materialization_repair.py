"""Exact no-new-native continuation for already recorded editor-local exclusions.

Restricted evidence/judge qualification cannot admit native capture or other cases.
Ordinary batch admission requires both actual completed and synced columns.
"""
from pathlib import Path
from . import batch, unity_m_admission as admission
from .protocol import sha
from .mechanic_v3_runner import exclusive_json

IDENTITY='Kimi__G013_wind_tower_grapple'
VERSION='unity-m-recorded-editor-settings-repair.v1'
FILES={'unity_m_input_adapter.py','unity_m_admission.py','unity_m_materialization_repair.py',
       'unity_m_evidence.py','unity_m_judge.py','unity_native_import_metadata.py','unity_ide_metadata.py'}
ERROR="Unreviewed isolated migration changes: ['UserSettings/EditorUserSettings.asset', 'UserSettings/Search.settings']"


def bound(spec):
    path=Path(spec['path'])
    if sha(path)!=spec['sha256']:raise ValueError('Materialization repair binding changed: '+str(path))
    return path


def verify_delta(value,prior):
    before=prior['verification_production'];current=admission.production()
    changed={p for p in before.keys()|current.keys() if before.get(p)!=current.get(p)}
    if current!=value['current_production'] or not changed or changed!=set(value['changed_files']):
        raise ValueError('Exact complete materialization producer delta required')
    for name in changed:
        p=Path(name);archive=value['changed_files'][name]
        if p.parent!=Path(__file__).parent or p.name not in FILES or name not in current:
            raise ValueError('Only materialization verifier and restricted gates may change')
        if (name in before and (not archive or sha(Path(archive))!=before[name])) or (name not in before and archive is not None):
            raise ValueError('Exact archived materialization producer required')
    regression=batch.read(bound(value['regression']))
    if regression.get('exit_code')!=0 or regression.get('tests_passed',0)<1:
        raise ValueError('Passing materialization regressions required')


def verify_baseline_failure(recorded,value):
    recorded=Path(recorded).resolve()
    failure=Path(value['parent_failure'])
    previous=recorded/'unity_m_evidence_repair_claim.json'
    if (failure.parent!=recorded/'unity_m_evidence_failures'
            or sha(failure)!=value['parent_failure_sha256']
            or batch.read(failure).get('error')!='Unknown recorded URP origin'
            or sha(previous)!=value['previous_repair_claim_sha256']):
        raise ValueError('Exact native baseline failure and consumed repair claim required')
    from .unity_m_input_adapter import materialization_proof
    migration=materialization_proof(recorded)
    before=Path(migration['isolated_project'])/'Packages/manifest.json'
    after=recorded/'background_record/project/Packages/manifest.json'
    if before.is_symlink() or after.is_symlink() or sha(before)!=sha(after):
        raise ValueError('Exact unchanged migrated native manifest required')


def verify_ide_failure(recorded,value):
    recorded=Path(recorded).resolve();failure=Path(value['parent_failure'])
    previous=recorded/'unity_m_evidence_native_baseline_repair_claim.json'
    failed=batch.read(failure)
    if (failure.parent!=recorded/'unity_m_evidence_failures'
            or sha(failure)!=value['parent_failure_sha256']
            or 'assert set(changed_authored)' not in failed.get('traceback','')
            or sha(previous)!=value['previous_repair_claim_sha256']):
        raise ValueError('Exact generated IDE parent failure and consumed claim required')
    from .unity_m_input_adapter import materialization_proof
    from .unity_ide_metadata import input_migration_proof
    materialization_proof(recorded)
    for name in ('Assembly-CSharp.csproj','Assembly-CSharp-Editor.csproj','project.sln'):
        if not input_migration_proof(recorded/'input/project',recorded/'background_record/project',name):
            raise ValueError('Exact input IDE metadata proof required: '+name)


def qualify(workspace,identity,descriptor):
    workspace=Path(workspace).resolve();value=batch.read(descriptor)
    if (value.get('version')!=VERSION or identity!=IDENTITY or value.get('identity')!=identity
            or value.get('new_native_calls')!=0 or value.get('batch_admitted') is not False):
        raise ValueError('Exact recorded-only materialization continuation required')
    prior=batch.read(bound(value['prior_admission']))
    if prior.get('version')!=admission.VERSION or not prior.get('transport_recovery'):
        raise ValueError('Completed transport-qualified two-column baseline required')
    verify_delta(value,prior)
    if any(Path(n).name=='unity_native_import_metadata.py' for n in value['changed_files']):
        verify_baseline_failure(workspace/'runs'/identity,value['baseline_continuation'])
    if any(Path(n).name=='unity_ide_metadata.py' for n in value['changed_files']):
        verify_ide_failure(workspace/'runs'/identity,value['ide_continuation'])
    recovery=prior['transport_recovery'];old_descriptor=bound(dict(path=recovery['descriptor'],sha256=recovery['sha256']))
    _,old,complete,executed=admission.verify_recovered_transport(workspace,old_descriptor,
        expected_production=prior['verification_production'])
    if old!=prior['e2e'] or complete!=recovery['e2e'] or executed!=prior['executed_producer']:
        raise ValueError('Historical complete actual E2E changed')
    recorded=workspace/'runs'/identity
    failure=bound(value['parent_failure'])
    if (failure.parent!=recorded/'unity_m_evidence_failures' or batch.read(failure).get('error')!=ERROR
            or batch.read(failure).get('native_or_model_calls')!=0):
        raise ValueError('Actual editor-local materialization parent failure required')
    for name,digest in value['bindings'].items():
        if sha(Path(name))!=digest:raise ValueError('Original record/source/claim changed')
    required={str(recorded/n) for n in ('unity_m_capture.json','unity_m_source_binding.json',
        'unity_m_evidence_claim.json','background_record/verification.json','background_record/runner_exit.json')}
    if not required<=set(value['bindings']):raise ValueError('Complete existing capture bindings required')
    from .unity_m_evidence import qualify_recorded
    from .unity_m_input_adapter import materialization_proof
    qualify_recorded(recorded);proof=materialization_proof(recorded)
    if ({r['path'] for r in proof.get('editor_local_snapshot_exclusions',[])}!=
            {'UserSettings/EditorUserSettings.asset','UserSettings/Search.settings'}):
        raise ValueError('Exact native-recorded editor exclusions required')
    return dict(version=VERSION,identity=identity,restricted_operations=['evidence','judge'],
        descriptor=str(Path(descriptor).resolve()),descriptor_sha256=sha(descriptor),
        materialization=proof,prior_admission=value['prior_admission'])


def completed(workspace,descriptor):
    value=batch.read(descriptor);repair=bound(value['repair']);qualification=qualify(workspace,IDENTITY,repair)
    processes=value['completed_processes']
    if len(processes)!=2:raise ValueError('Both actual completed column processes required')
    columns=set()
    for item in processes:
        process=batch.read(bound(item));args=process.get('args',[])
        required={'--workspace':str(Path(workspace).resolve()),'--phase':'unity-m-judge','--ids':IDENTITY}
        if (process.get('exit_code')!=0 or process.get('finished',0)<=process.get('started',0)
                or args[1:4]!=['-u','-m','pipeline.game_eval.whitebox_eval.mechanic_v3_cli']
                or any(args.count(k)!=1 or args.index(k)+1>=len(args) or args[args.index(k)+1]!=v for k,v in required.items())
                or args.count('--column')!=1):raise ValueError('Actual formal completed judge required')
        columns.add(args[args.index('--column')+1])
    if columns!={'Mechanic','Gameness'}:raise ValueError('Both distinct columns required')
    root,proof=admission.evidence(workspace,IDENTITY)
    producer=batch.read(root/'unity_m_judge_producer.json')
    if producer['production']!=admission.production():raise ValueError('Actual materialization E2E producer changed')
    return qualification,proof,producer


def create_completed(workspace,descriptor):
    qualification,proof,producer=completed(workspace,descriptor)
    value=dict(version=admission.VERSION,capability='UNITY_M_MECHANIC_V3_GAMENESS_V4_ORIGINAL_PIXELS',
        verification_production=admission.production(),executed_producer=producer,e2e=proof,
        materialization_recovery=dict(descriptor=str(Path(descriptor).resolve()),sha256=sha(descriptor),qualification=qualification),
        scoring_unchanged=True,model='gpt-6.1-sol')
    path=admission.admission_path(workspace,value['verification_production'])
    if path.exists():
        if batch.read(path)!=value:raise ValueError('Immutable materialization admission changed')
    else:exclusive_json(path,value)
    return path,value


def verify_completed(workspace,value):
    recovery=value['materialization_recovery']
    descriptor=bound(dict(path=recovery['descriptor'],sha256=recovery['sha256']))
    qualification,proof,producer=completed(workspace,descriptor)
    if qualification!=recovery['qualification'] or proof!=value['e2e'] or producer!=value['executed_producer']:
        raise ValueError('Completed materialization E2E changed')
