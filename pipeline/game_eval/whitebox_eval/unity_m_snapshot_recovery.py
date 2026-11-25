"""Exact recorded build-policy recovery, preserving historical native producers.

Until both actual columns complete and synchronize, only the bound existing
GLM recording may enter evidence/judge. This never grants a new native lease.
"""
from pathlib import Path
import argparse
from . import batch, unity_m_admission as admission
from .protocol import sha
from .mechanic_v3_runner import exclusive_json

IDENTITY='GLM__G039_sky_ring_flight'
VERSION='unity-m-recorded-build-policy-recovery.v1'
FILES={'unity_m_input_adapter.py','prepare_unity_recorded_judge.py',
       'unity_m_evidence.py','unity_m_admission.py','unity_m_snapshot_recovery.py',
       'unity_ide_metadata.py'}


def reference(spec):
    path=Path(spec['path'])
    if sha(path)!=spec['sha256']:
        raise ValueError('Snapshot recovery immutable reference changed: '+str(path))
    return path


def verify_delta(value,prior,*,expected_production=None):
    before=prior['verification_production'];current=admission.production() if expected_production is None else expected_production
    changed={p for p in before.keys()|current.keys() if before.get(p)!=current.get(p)}
    directory=Path(__file__).resolve().parent
    expected={str(directory/name) for name in FILES}
    if current!=value['verification_production'] or changed!=expected or set(value['changed_files'])!=expected:
        raise ValueError('Exact snapshot verifier and restricted gate delta required')
    for name in changed:
        old=value['changed_files'][name]
        if name in before:
            if not old or sha(Path(old))!=before[name]:
                raise ValueError('Exact archived snapshot producer bytes required')
        elif old is not None or Path(name).name!='unity_m_snapshot_recovery.py':
            raise ValueError('Only explicit new snapshot recovery gate permitted')
    admission._check_regression(value['regression'])


def verify_evidence_failure(recorded,value):
    recorded=Path(recorded).resolve();failure=Path(value['parent_failure'])
    if (value.get('kind')!='build_snapshot_policy' or value.get('identity')!=IDENTITY
            or recorded.name!=IDENTITY or failure.parent!=recorded/'unity_m_evidence_failures'
            or sha(failure)!=value['parent_failure_sha256']):
        raise ValueError('Exact preserved build snapshot materialization failure required')
    failed=batch.read(failure)
    if (failed.get('native_or_model_calls')!=0
            or not failed.get('error','').startswith('Unreviewed isolated migration changes: ')
            or 'materialization_proof(recorded)' not in failed.get('traceback','')):
        raise ValueError('Actual pre-materialization build policy parent failure required')
    from .unity_m_input_adapter import materialization_proof
    proof=materialization_proof(recorded)
    # The preserved parent had already accepted editor-local omissions. Only
    # the originally rejected Build paths belong in this exact comparison.
    names=sorted(row['path'] for row in proof.get('build_snapshot_exclusions',[]))
    if not proof.get('build_snapshot_exclusions') or failed['error']!='Unreviewed isolated migration changes: '+str(names):
        raise ValueError('Every originally rejected snapshot omission must be proven exactly')
    if value.get('ide_followup'):
        stage=value['ide_followup']
        failure=reference(stage['failure']);failed=batch.read(failure)
        if (failure.parent!=recorded/'unity_m_evidence_failures'
                or 'assert set(changed_authored)' not in failed.get('traceback','')
                or failed.get('native_or_model_calls')!=0):
            raise ValueError('Exact pre-copy generated IDE rejection required')
        original_claim=recorded/'unity_m_evidence_build_snapshot_repair_claim.json'
        if sha(original_claim)!=stage['original_repair_claim_sha256']:
            raise ValueError('Preserved first snapshot repair claim changed')
        from .unity_m_input_adapter import generated_migration_metadata
        original=recorded/'input/project';observed=recorded/'background_record/project'
        rows=[generated_migration_metadata(original,observed,name) for name in stage['paths']]
        if not rows or any(row is None for row in rows):
            raise ValueError('Exact generated IDE-only migration proof required')
        proof['generated_migration_metadata']=rows
    claim=recorded/'unity_m_evidence_claim.json'
    if sha(claim)!=value['parent_claim_sha256']:
        raise ValueError('Original evidence claim changed')
    for path,digest in value['bindings'].items():
        if sha(Path(path))!=digest:raise ValueError('Original native recovery binding changed: '+path)
    return proof


def qualify(workspace,identity,operation,descriptor,*,expected_production=None):
    workspace=Path(workspace).resolve();value=batch.read(descriptor)
    if (identity!=IDENTITY or operation not in {'evidence','judge'}
            or value.get('version')!=VERSION or value.get('identity')!=IDENTITY
            or value.get('classification')!='RECORDED_BUILD_POLICY_AND_TEXT_DIGEST_ONLY'
            or value.get('scoring_changed') is not False or value.get('new_native_calls')!=0):
        raise ValueError('Only exact recorded GLM evidence/judge recovery is admitted')
    parent=reference(value['prior_admission']);prior=batch.read(parent)
    if (prior.get('version')!=admission.VERSION or not prior.get('native_lease_recovery')
            or parent!=admission.admission_path(workspace,prior['verification_production'])):
        raise ValueError('Exact preceding complete two-column native admission required')
    verify_delta(value,prior,expected_production=expected_production)
    old=reference(prior['native_lease_recovery'])
    _,baseline=admission.verify_native_lease_recovery(workspace,old,
        expected_production=prior['verification_production'])
    if baseline['e2e']!=prior['e2e'] or baseline['executed_producer']!=prior['executed_producer']:
        raise ValueError('Historical complete actual native source/pixel E2E changed')
    recorded=workspace/'runs'/IDENTITY
    from .unity_m_evidence import qualify_recorded
    qualify_recorded(recorded)
    proof=verify_evidence_failure(recorded,value)
    required={str(recorded/name) for name in (
        'unity_m_capture.json','unity_m_source_binding.json','unity_m_evidence_claim.json',
        'background_record/verification.json','background_record/runner_exit.json',
        'recorder_acceptance_binding.json','unity_m_native_dispatch/native_project_override.json')}
    if not required<=set(value['bindings']):
        raise ValueError('Complete preserved native source/cleanup/claim bindings required')
    return dict(version=VERSION,identity=IDENTITY,restricted_operations=['evidence','judge'],
        descriptor=str(Path(descriptor).resolve()),descriptor_sha256=sha(descriptor),
        materialization=proof,prior_admission=value['prior_admission'])


def verify_complete(workspace,descriptor,*,expected_production=None):
    value=batch.read(descriptor);repair=reference(value['repair'])
    qualification=qualify(workspace,IDENTITY,'judge',repair,expected_production=expected_production)
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
        if not any(line.startswith(marker) and line.endswith(' SYNCED')
                   for line in process.get('final_stdout','').splitlines()):
            raise ValueError('Actual column publish and sync output required')
        columns.add(column)
    if len(value['completed_processes'])!=2 or columns!={'Mechanic','Gameness'}:
        raise ValueError('Both distinct real columns required for broader admission')
    root,proof=admission.evidence(workspace,IDENTITY)
    producer=batch.read(root/'unity_m_judge_producer.json')
    if producer['production']!=(admission.production() if expected_production is None else expected_production):
        raise ValueError('Actually executed complete snapshot recovery producer required')
    return qualification,proof,producer


def create(workspace,descriptor):
    _,proof,producer=verify_complete(workspace,descriptor)
    value=dict(version=admission.VERSION,capability='UNITY_M_MECHANIC_V3_GAMENESS_V4_ORIGINAL_PIXELS',
        verification_production=admission.production(),executed_producer=producer,e2e=proof,
        snapshot_policy_recovery=dict(path=str(Path(descriptor).resolve()),sha256=sha(descriptor)),
        scoring_unchanged=True,model='gpt-6.1-sol')
    path=admission.admission_path(workspace,value['verification_production'])
    if path.exists():
        if batch.read(path)!=value:raise ValueError('Immutable snapshot recovery admission changed')
    else:exclusive_json(path,value)
    return path,value


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace',type=Path,required=True)
    parser.add_argument('--complete',type=Path,required=True)
    args=parser.parse_args(argv)
    path,_=create(args.workspace,args.complete)
    print('UNITY_M_SNAPSHOT_RECOVERY_COMPLETE',path,flush=True)
    return 0

if __name__=='__main__':raise SystemExit(main())


def verify_materialized_followup(recorded, value):
    """Continue the exact pre-delivery runtime verifier checkpoint, never recopy."""
    recorded = Path(recorded).resolve()
    stage = value['runtime_ide_followup']
    failure = reference(stage['failure'])
    failed = batch.read(failure)
    attempt = Path(stage['partial_attempt']).resolve()
    if (failure.parent != recorded/'unity_m_evidence_failures'
            or failed.get('error') != 'authored runtime source drift: .vscode/settings.json'
            or 'batch.verify_runtime_sources(attempt)' not in failed.get('traceback', '')
            or failed.get('native_or_model_calls') != 0
            or attempt.parent != recorded.parents[1]/'recovery_runs'
            or not attempt.name.startswith(recorded.name+'__recorded_judge_v1_')
            or batch.read(attempt/'attempt_manifest.json').get('previous_attempt') != str(recorded)):
        raise ValueError('Exact preserved materialized runtime IDE checkpoint required')
    if sha(recorded/'unity_m_evidence_build_ide_repair_claim.json') != stage['original_repair_claim_sha256']:
        raise ValueError('Original materialized IDE claim changed')
    for name, digest in stage['bindings'].items():
        if sha(Path(name)) != digest:
            raise ValueError('Preserved materialized raw evidence changed: '+name)
    provenance = batch.read(attempt/'recorded_capture_provenance.json')
    if provenance.get('source_attempt') != str(recorded):
        raise ValueError('Wrong materialized native capture source')
    for row in provenance['raw_identical_copies']:
        destination = attempt/(row.get('preserved_path') or 'runtime/'+row['path'])
        if sha(Path(row['source'])) != row['sha256'] or sha(destination) != row['sha256']:
            raise ValueError('Preserved original native bytes differ')
    batch.verify_inputs(attempt)
    batch.verify_runtime_sources(attempt)
    if not (recorded/'unity_m_evidence.json').exists():
        if any((attempt/n).exists() for n in ('evidence_manifest.json','model_calls','judgments','source_qualification.json')):
            raise ValueError('Runtime IDE checkpoint already advanced; diagnose its own last stage')
    return attempt
