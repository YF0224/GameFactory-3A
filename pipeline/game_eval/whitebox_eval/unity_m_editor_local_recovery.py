"""Exact preserved-record recovery for a native recent-scene preference insertion.

Only evidence/judge for the bound G018 record are admitted until both actual
columns publish and synchronize. Native dispatch never uses this restricted gate.
"""
from pathlib import Path
from . import batch, unity_m_admission as admission
from .protocol import sha
from .mechanic_v3_runner import exclusive_json

IDENTITY='Kimi__G018_portal_freight'
VERSION='unity-m-native-editor-recent-scene-recovery.v1'
FILES={'unity_m_input_adapter.py','unity_native_import_metadata.py',
       'unity_m_snapshot_recovery.py','unity_m_evidence.py','unity_m_admission.py',
       'unity_m_editor_local_recovery.py','prepare_unity_recorded_judge.py'}
ERROR="Unreviewed isolated migration changes: ['UserSettings/EditorUserSettings.asset']"
EXTERNAL_UE5_DRIFT={
    'engine_adapters/ue5/runtime/client.py',
    'engine_adapters/ue5/testing/client.py',
}


def reference(spec):
    path=Path(spec['path'])
    if path.is_symlink() or sha(path)!=spec['sha256']:
        raise ValueError('Editor-local immutable reference changed: '+str(path))
    return path


def verify_delta(value,prior, *, expected_production=None):
    before=prior['verification_production']
    current=admission.production() if expected_production is None else expected_production
    directory=Path(__file__).resolve().parent
    expected={str(directory/name) for name in FILES}
    changed={p for p in before.keys()|current.keys() if before.get(p)!=current.get(p)}
    external=value.get('external_production_drift',{})
    external_paths=set(external)
    repo=Path(__file__).resolve().parents[3]
    allowed_external={str((repo/name).resolve()) for name in EXTERNAL_UE5_DRIFT}
    if (current!=value['verification_production']
            or changed!=expected|external_paths
            or (external_paths and external_paths!=allowed_external)
            or set(value['changed_files'])!=expected):
        raise ValueError('Exact Editor-local verifier and restricted gate delta required')
    for name in expected:
        old=value['changed_files'][name]
        if name in before:
            if not old or sha(Path(old))!=before[name]:
                raise ValueError('Exact archived Editor-local producer bytes required')
        elif old is not None or Path(name).name!='unity_m_editor_local_recovery.py':
            raise ValueError('Only explicit Editor-local recovery dependency permitted')
    for name,drift in external.items():
        if name in expected or not isinstance(drift,dict):
            raise ValueError('External production drift overlaps restricted Editor-local delta')
        if (drift.get('before_sha256') != before.get(name)
                or drift.get('after_sha256') != current.get(name)
                or drift.get('before_sha256') == drift.get('after_sha256')):
            raise ValueError('External production drift binding changed')
    admission._check_regression(value['regression'])


def register_external_followup(workspace,parent_descriptor,regression,target):
    """Bind only the two observed, unrelated UE5 producer changes as a successor."""
    workspace=Path(workspace).resolve();parent_descriptor=Path(parent_descriptor).resolve()
    parent=batch.read(parent_descriptor)
    if (parent.get('version')!=VERSION or parent.get('identity')!=IDENTITY
            or parent.get('external_production_drift')):
        raise ValueError('Exact first-generation G018 Editor-local descriptor required')
    recorded=workspace/'runs'/IDENTITY
    verify_plan_followup(recorded,parent)
    prior=batch.read(reference(parent['prior_admission']))
    before=prior['verification_production'];current=admission.production()
    root=Path(__file__).resolve().parents[3]
    allowed={str((root/name).resolve()) for name in EXTERNAL_UE5_DRIFT}
    changed={p for p in before.keys()|current.keys() if before.get(p)!=current.get(p)}
    directory=Path(__file__).resolve().parent
    expected={str(directory/name) for name in FILES}
    if changed-expected!=allowed or not expected<=changed:
        raise ValueError('Only the two recorded external UE5 producer changes can be bound')
    reg=Path(regression).resolve();admission._check_regression(dict(path=str(reg),sha256=sha(reg)))
    drift={name:dict(before_sha256=before[name],after_sha256=current[name]) for name in sorted(allowed)}
    child=dict(parent)
    child.update(verification_production=current,external_production_drift=drift,
                 parent_descriptor=dict(path=str(parent_descriptor),sha256=sha(parent_descriptor)),
                 regression=dict(path=str(reg),sha256=sha(reg)))
    target=Path(target)
    exclusive_json(target,child)
    return target,child


def file_bindings(root):
    root = Path(root)
    paths = list(root.rglob('*'))
    if root.is_symlink() or any(p.is_symlink() for p in paths):
        raise ValueError('Preserved partial must not contain symlinks')
    return {str(p.relative_to(root)): sha(p) for p in paths if p.is_file()}


def verify_plan_followup(recorded, value):
    """Admit only the exact interrupted pre-plan attempt, retaining its identity."""
    recorded = Path(recorded).resolve()
    followup = value['plan_import_followup']
    prior_path = reference(followup['initial_repair'])
    prior = batch.read(prior_path)
    if (value.get('kind') != 'native_editor_recent_scene'
            or value.get('identity') != IDENTITY or recorded.name != IDENTITY
            or prior.get('plan_import_followup') or not prior.get('native_import_followup')
            or prior.get('prior_admission') != value.get('prior_admission')
            or value.get('parent_claim_sha256') != sha(recorded/'unity_m_evidence_claim.json')):
        raise ValueError('Exact native-import successor lineage required')
    migration = verify_failure(recorded, prior)
    failure = reference(value['parent_failure'])
    error = batch.read(failure)
    trace = error.get('traceback', '')
    if (failure.parent != recorded/'unity_m_evidence_failures'
            or error.get('error') != 'Recorded plan native import bytes differ'
            or error.get('native_or_model_calls') != 0
            or 'prepare_unity_recorded_judge.py' not in trace
            or 'recorded_plan_for_judge' not in trace
            or 'unity_native_import_metadata.py' not in trace):
        raise ValueError('Exact interrupted native plan import failure required')
    claim = recorded/'unity_m_evidence_native_import_followup_claim.json'
    if (sha(claim) != followup['initial_claim_sha256']
            or batch.read(claim) != dict(repair=str(prior_path), sha256=sha(prior_path),
                                        new_native_or_model_calls=0)):
        raise ValueError('Preserved native import followup claim changed')
    if not set(prior['bindings']) <= set(value['bindings']):
        raise ValueError('All prior native capture bindings required')
    for name, digest in value['bindings'].items():
        path = Path(name)
        if path.is_symlink() or sha(path) != digest:
            raise ValueError('Preserved plan followup binding changed: '+name)
    attempt = Path(followup['partial_attempt'])
    prefix = recorded.name+'__recorded_judge_v1_'
    stamp = attempt.name.removeprefix(prefix)
    if (attempt.parent != recorded.parent.parent/'recovery_runs'
            or not attempt.name.startswith(prefix) or not stamp.isdecimal()
            or attempt.is_symlink()):
        raise ValueError('Exact original partial attempt identity required')
    archive = Path(followup['partial_archive'])
    hashes = followup['partial_hashes']
    if file_bindings(archive) != hashes:
        raise ValueError('Exact pre-plan archive changed')
    derived = recorded/'derived_judge_sources'/(recorded.name+'__recorded_urp_'+stamp)
    receipt = reference(followup['derived_receipt'])
    if (receipt != derived.with_suffix('.json')
            or file_bindings(derived) != followup['derived_hashes']):
        raise ValueError('Preserved derived input or receipt changed')
    pointer = recorded/'unity_m_evidence.json'
    if pointer.exists():
        materialized = batch.read(pointer)
        if materialized.get('root') != str(attempt):
            raise ValueError('Materialization must keep original partial identity')
        for name, digest in materialized['bindings'].items():
            if sha(Path(name)) != digest:
                raise ValueError('Materialized plan recovery binding changed')
        for name, digest in hashes.items():
            if name != 'status.json' and not name.startswith('runtime/'):
                if sha(attempt/name) != digest:
                    raise ValueError('Preserved partial input changed: '+name)
        batch.verify_inputs(attempt)
        batch.verify_runtime_sources(attempt)
        if batch.read(attempt/'recorded_capture_provenance.json')['source_attempt'] != str(recorded):
            raise ValueError('Materialized recording lineage changed')
    else:
        if file_bindings(attempt) != hashes:
            raise ValueError('Interrupted partial attempt changed before continuation')
        from .prepare_unity_recorded_judge import qualify_partial
        partial = qualify_partial(recorded, attempt, two_column_only=True)
        if (partial['stamp'] != stamp
                or partial['source_version'] != batch.read(receipt)
                or partial['source_version'].get('unity_m_input_materialization') != migration):
            raise ValueError('Partial recorded source differs from actual migration proof')
    return migration, attempt


def verify_failure(recorded,value):
    if value.get('plan_import_followup'):
        return verify_plan_followup(recorded, value)[0]
    recorded=Path(recorded).resolve();failure=reference(value['parent_failure'])
    failed=batch.read(failure)
    if (value.get('kind')!='native_editor_recent_scene' or value.get('identity')!=IDENTITY
            or recorded.name!=IDENTITY or failure.parent!=recorded/'unity_m_evidence_failures'
            or failed.get('error')!=ERROR or failed.get('native_or_model_calls')!=0
            or 'materialization_proof(recorded)' not in failed.get('traceback','')
            or sha(recorded/'unity_m_evidence_claim.json')!=value['parent_claim_sha256']):
        raise ValueError('Exact preserved pre-materialization Editor-local failure required')
    required={str(recorded/name) for name in ('unity_m_capture.json','unity_m_source_binding.json',
        'input_manifest.json','unity_m_evidence_claim.json','sol_plan.json','native_actions.json',
        'capture_schedule.json','recorder_acceptance_binding.json','background_record/verification.json',
        'background_record/runner_exit.json','unity_m_native_dispatch/native_project_override.json')}
    required|={str(p) for p in (recorded/'background_record/take').rglob('*') if p.is_file()}
    if not required<=set(value['bindings']):
        raise ValueError('Complete preserved native source, pixels and cleanup bindings required')
    for name,digest in value['bindings'].items():
        path=Path(name)
        if path.is_symlink() or sha(path)!=digest:
            raise ValueError('Original Editor-local recovery binding changed: '+name)
    from .unity_m_evidence import qualify_recorded
    from .unity_m_input_adapter import materialization_proof
    from .unity_native_import_metadata import proof as native_proof
    qualify_recorded(recorded)
    migration=materialization_proof(recorded)
    rows=[row for row in migration.get('editor_local_snapshot_exclusions',[])
          if row.get('native_editor_transform')]
    if (len(rows)!=1 or rows[0]['path']!='UserSettings/EditorUserSettings.asset'
            or rows[0]['native_editor_transform']['kind']!='editor_recent_scene_guid_0_only'):
        raise ValueError('Exact native recent-scene-only omission proof required')
    metadata=native_proof(recorded,native_input_baseline=True)
    if not any(row['path']==rows[0]['path'] and row['transform']==rows[0]['native_editor_transform'] for row in metadata):
        raise ValueError('Qualified native Editor/version and inverse preference proof required')
    followup=value.get('native_import_followup')
    if followup:
        import ast
        initial=reference(followup['initial_repair'])
        initial_value=batch.read(initial)
        if (initial_value.get('native_import_followup') or initial_value.get('parent_failure')!=value['parent_failure']
                or initial_value.get('prior_admission')!=value['prior_admission']):
            raise ValueError('Exact original recent-scene repair lineage required')
        verify_failure(recorded,initial_value)
        original_claim=recorded/'unity_m_evidence_recent_scene_repair_claim.json'
        claim=batch.read(original_claim)
        if (sha(original_claim)!=followup['initial_claim_sha256']
                or claim!={'repair':str(initial),'sha256':sha(initial),'new_native_or_model_calls':0}):
            raise ValueError('Original recent-scene repair claim changed')
        latest=reference(followup['failure']);error=batch.read(latest)
        if (latest.parent!=recorded/'unity_m_evidence_failures'
                or error.get('native_or_model_calls')!=0
                or 'assert set(changed_authored)' not in error.get('traceback','')
                or 'prepare_unity_recorded_judge.py' not in error.get('traceback','')):
            raise ValueError('Exact preserved pre-copy native import failure required')
        expected={'Assets/Scripts/'+n+'.cs' for n in ('CgPlaceholderPlayer','FirstPersonController','GameManager','HudController','PortalPlacementSystem')}
        expected.update({'Assets/Settings/M_berth.mat','Assets/Settings/URP-Asset.asset',
            'Packages/manifest.json','Packages/packages-lock.json','ProjectSettings/GraphicsSettings.asset',
            'ProjectSettings/ProjectSettings.asset','ProjectSettings/QualitySettings.asset','UserSettings/EditorUserSettings.asset'})
        if ast.literal_eval(error['error'])!=sorted(expected):
            raise ValueError('Captured native import failure paths changed')
        if {r['path'] for r in metadata}!={'Assets/Settings/M_berth.mat','Assets/Settings/URP-Asset.asset',rows[0]['path']}:
            raise ValueError('Exact recorded asset and preference import proof required')
        if metadata!=followup['native_import_proof']:
            raise ValueError('Recorded package, resources, source or Editor import proof changed')
    return migration


def qualify(workspace,identity,operation,descriptor, *, expected_production=None):
    workspace=Path(workspace).resolve();value=batch.read(descriptor)
    if (identity!=IDENTITY or operation not in {'evidence','judge'}
            or value.get('version')!=VERSION or value.get('identity')!=IDENTITY
            or value.get('new_native_calls')!=0 or value.get('batch_admitted') is not False
            or value.get('scoring_changed') is not False):
        raise ValueError('Only exact recorded Kimi G018 evidence/judge recovery is admitted')
    parent_ref=value.get('parent_descriptor')
    if parent_ref:
        parent_path=reference(parent_ref);parent=batch.read(parent_path)
        child=dict(value);child.pop('parent_descriptor',None);child.pop('external_production_drift',None)
        child.pop('verification_production',None);child.pop('regression',None)
        original=dict(parent);original.pop('verification_production',None)
        original.pop('regression',None)
        if child!=original:
            raise ValueError('External drift successor changed its immutable parent recovery')
    parent=reference(value['prior_admission']);prior=batch.read(parent)
    if (prior.get('version')!=admission.VERSION or not prior.get('snapshot_policy_recovery')
            or parent!=admission.admission_path(workspace,prior['verification_production'])):
        raise ValueError('Exact preceding complete two-column snapshot admission required')
    verify_delta(value,prior,expected_production=expected_production)
    from .unity_m_snapshot_recovery import verify_complete as historical
    completed=reference(prior['snapshot_policy_recovery'])
    _,proof,producer=historical(workspace,completed,expected_production=prior['verification_production'])
    if proof!=prior['e2e'] or producer!=prior['executed_producer']:
        raise ValueError('Historical complete actual snapshot producer/source/pixel E2E changed')
    migration=verify_failure(workspace/'runs'/IDENTITY,value)
    return dict(version=VERSION,identity=IDENTITY,restricted_operations=['evidence','judge'],
        descriptor=str(Path(descriptor).resolve()),descriptor_sha256=sha(descriptor),
        materialization=migration,prior_admission=value['prior_admission'])


def verify_complete(workspace,descriptor):
    value=batch.read(descriptor);repair=reference(value['repair'])
    qualification=qualify(workspace,IDENTITY,'judge',repair)
    columns=set()
    for spec in value['completed_processes']:
        process=batch.read(reference(spec));args=process.get('args',[])
        required={'--workspace':str(Path(workspace).resolve()),'--phase':'unity-m-judge','--ids':IDENTITY}
        if (process.get('exit_code')!=0 or process.get('finished',0)<=process.get('started',0)
                or args[1:4]!=['-u','-m','pipeline.game_eval.whitebox_eval.mechanic_v3_cli']
                or any(args.count(k)!=1 or args.index(k)+1>=len(args) or args[args.index(k)+1]!=v for k,v in required.items())
                or args.count('--column')!=1):
            raise ValueError('Both actual completed formal judge processes required')
        column=args[args.index('--column')+1]
        marker='UNITY_M_COLUMN_PUBLISHED '+IDENTITY+' '+column+' '
        if not any(line.startswith(marker) and line.endswith(' SYNCED') for line in process.get('final_stdout','').splitlines()):
            raise ValueError('Actual column publication and sync output required')
        columns.add(column)
    if len(value['completed_processes'])!=2 or columns!={'Mechanic','Gameness'}:
        raise ValueError('Both distinct real columns required for broader admission')
    root,proof=admission.evidence(workspace,IDENTITY)
    producer=batch.read(root/'unity_m_judge_producer.json')
    if producer['production']!=admission.production():
        raise ValueError('Actually executed complete Editor-local recovery producer required')
    return qualification,proof,producer


def create(workspace,descriptor):
    _,proof,producer=verify_complete(workspace,descriptor)
    value=dict(version=admission.VERSION,capability='UNITY_M_MECHANIC_V3_GAMENESS_V4_ORIGINAL_PIXELS',
        verification_production=admission.production(),executed_producer=producer,e2e=proof,
        editor_local_recovery=dict(path=str(Path(descriptor).resolve()),sha256=sha(descriptor)),
        scoring_unchanged=True,model='gpt-6.1-sol')
    path=admission.admission_path(workspace,value['verification_production'])
    if path.exists():
        if batch.read(path)!=value:raise ValueError('Immutable Editor-local recovery admission changed')
    else:exclusive_json(path,value)
    return path,value
