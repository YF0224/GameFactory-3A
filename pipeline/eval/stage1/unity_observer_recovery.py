"""Explicit G005 observer-repair take: immutable plan, failed take and judge retained."""
import shutil
import time
from pathlib import Path

from . import batch, core12, unity_plan_normalization
from .protocol import dump, sha

VERSION = 'unity-g005-observer-recovery.v1'
RECEIPT = 'observer_capture_recovery.json'
CASE = 'Sol__G005_broken_realm_echo'
FIELDS = ['screen', 'run', 'scene', 'paused', 'hp', 'maxHP', 'sta', 'sp', 'aw', 'cd', 'enemies']


def qualify(source):
    source = Path(source).resolve()
    if batch.read(source/'input_manifest.json')['entry']['id'] != CASE or (source/'scores.json').exists():
        raise ValueError('Observer recovery is only for unscored G005')
    v = batch.read(source/'background_record/verification.json')
    c = batch.read(source/'background_record/runner_exit.json')
    if (v.get('ok') is not True or v.get('status') != 'CAPTURE_VERIFIED'
            or not all(v['checks'].values()) or c.get('cleanup_verified') is not True
            or c.get('policy_violations') != [] or c.get('error') is not None):
        raise ValueError('Preserved native take must be captured and safely cleaned up')
    judged = Path(batch.read(source/'active_background_judge_attempt.json')['attempt']).resolve()
    diagnosis = batch.read(judged/'rerun_failure_diagnosis.json')
    status = batch.read(judged/'status.json')
    if (status.get('status') != 'HARNESS_ERROR' or status.get('phase') != 'aggregation'
            or diagnosis.get('source_attempt') != str(source)
            or diagnosis.get('judge_attempt') != str(judged)
            or diagnosis.get('formal_score') is not None or diagnosis.get('published') is not False
            or diagnosis.get('execution_counts', {}).get('HARNESS_ERROR', 0) <= 0
            or (judged/'scores.json').exists()):
        raise ValueError('Requires preserved observer-failed judge, never a low-score retry')
    take = source/'background_record/take'
    import json
    states = [json.loads(line) for line in (take/'state_trace.jsonl').read_text().splitlines() if line.strip()]
    if not states or any(isinstance(value, dict) and {'hp', 'screen'} <= value.keys()
            for row in states for value in row.get('state', {}).values()):
        raise ValueError('Functional source state already present or raw state unavailable; inspect instead of rerun')
    event = take/'event_trace.jsonl'
    if event.is_file() and event.read_text().strip():
        raise ValueError('Existing functional event evidence requires review, not an automatic take')
    paths = [source/'background_record/verification.json', source/'background_record/runner_exit.json',
        source/'background_record/take/state_trace.jsonl', source/'background_record/take/actions.jsonl',
        source/'active_background_judge_attempt.json', judged/'rerun_failure_diagnosis.json', judged/'status.json']
    paths += sorted((judged/'judgments').glob('*.json'))
    return {str(path): sha(path) for path in paths}


def contract(source):
    project = Path(source)/'input/project'
    refs = ['Assets/UI/RealmUI.cs', 'Assets/Mechanics/RealmRuntime.cs']
    ui, runtime = [(project/name).read_text() for name in refs]
    if ('public IRealmRuntime Runtime;' not in ui or 'RealmSnapshot GetStateSnapshot()' not in runtime
            or 'event Action<RealmEvent> EventRaised' not in runtime):
        raise ValueError('Public G005 observer source contract changed; review required')
    return ({'schema': 'unity-functional-observer-contract.v1', 'provider_type': 'BrokenRealm.Mechanics.RealmRuntime',
             'required_fields': FIELDS, 'require_events': True},
            {name: sha(project/name) for name in refs})


def audit_binding(root):
    root = Path(root).resolve()
    recorded = Path(batch.read(root/'recorded_capture_provenance.json')['source_attempt']).resolve() \
        if (root/'recorded_capture_provenance.json').exists() else root
    from .unity_public_field_recovery import RECEIPT as public_receipt, audit_binding as public_audit
    if (recorded/public_receipt).is_file():
        return public_audit(root)
    receipt = recorded/RECEIPT
    if not receipt.is_file():
        return {}
    value = batch.read(receipt)
    source = Path(value['source_attempt']).resolve()
    if (value.get('version') != VERSION or source == recorded or source.parent != recorded.parent
            or (source/RECEIPT).exists() or value.get('plan_model_calls_added') != 0
            or value.get('physical_actions_changed') is not False):
        raise ValueError('Invalid observer repair lineage')
    if value['qualification_sha256'] != qualify(source):
        raise ValueError('Observer failure qualification changed')
    expected, refs = contract(source)
    if (batch.read(recorded/'functional_observer_contract.json') != expected
            or value['source_contract_sha256'] != refs):
        raise ValueError('Observer source contract changed')
    result = {str(receipt): sha(receipt), **value['qualification_sha256']}
    copied = value['copied_files_sha256']
    if not {'sol_plan.json', 'input_manifest.json', 'input/pilot_rubric.json'} <= copied.keys():
        raise ValueError('Observer recovery missing frozen input bindings')
    for name, digest in copied.items():
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Invalid observer preserved path')
        for parent in (source, recorded):
            if sha(parent/relative) != digest:
                raise ValueError('Observer recovery frozen file changed: '+name)
            result[str(parent/relative)] = digest
    acceptance = Path(value['editor_acceptance'])
    if sha(acceptance) != value['editor_acceptance_sha256']:
        raise ValueError('Observer acceptance changed')
    result[str(acceptance)] = sha(acceptance)
    result[str(recorded/'functional_observer_contract.json')] = sha(recorded/'functional_observer_contract.json')
    return result


def prepare(source, acceptance, cleanup):
    # Explicit frozen planning inputs; capture retry no longer exports this list.
    PRESERVED = ('input_manifest.json', 'input', 'model_calls', 'sol_plan.json',
        'static_source_scores.json', 'static_code_scores.json', 'static_existence.json',
        'capture_route_contract.json', 'endpoint_conditions_receipt.json', 'plan_normalization.json',
        'planning_prompt_policy.json', 'planning_prompt_template.py', 'planning_prompt_transform.json',
        'planning_retry_feedback.json', 'selection_provenance.json', 'operation_report.md')
    source, acceptance = Path(source).resolve(), Path(acceptance).resolve()
    qualification = qualify(source)
    if (source/RECEIPT).exists():
        raise ValueError('Nested observer recovery prohibited')
    for previous in source.parent.glob(CASE+'__observer_recovery_v1_*/'+RECEIPT):
        if batch.read(previous).get('source_attempt') == str(source):
            raise ValueError('Observer recovery already exists; resume without another take')
    batch.verify_inputs(source)
    core12.verify_attempt(source, 'unity3d')
    unity_plan_normalization.verify(source)
    observer_contract, refs = contract(source)
    root = source.parent/(CASE+'__observer_recovery_v1_'+str(time.time_ns()))
    root.mkdir()
    bindings = {}
    for name in PRESERVED:
        path = source/name
        if path.is_dir():
            shutil.copytree(path, root/name)
            files = path.rglob('*')
        elif path.is_file():
            shutil.copy2(path, root/name)
            files = [path]
        else:
            continue
        bindings.update({str(p.relative_to(source)): sha(p) for p in files if p.is_file()})
    dump(root/'functional_observer_contract.json', observer_contract)
    dump(root/RECEIPT, {'version': VERSION, 'source_attempt': str(source),
        'reason': 'Repair demonstrated missing functional observer; no gameplay, plan or rubric changes.',
        'qualification_sha256': qualification, 'copied_files_sha256': bindings, 'source_contract_sha256': refs,
        'editor_acceptance': str(acceptance), 'editor_acceptance_sha256': sha(acceptance),
        'preflight_cleanup': cleanup, 'plan_model_calls_added': 0, 'physical_actions_changed': False,
        'created_unix': time.time()})
    audit_binding(root)
    batch.verify_inputs(root)
    core12.verify_attempt(root, 'unity3d')
    unity_plan_normalization.verify(root)
    return root


def main():
    import argparse
    import fcntl
    from . import unity_single, unity_safety
    from .effective import resolve_result
    from engine_adapters.unity3d.playtest import native_acceptance, functional_observer
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--editor-acceptance', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    config = batch.read(output/'configuration.json')
    control = Path(config['control_root'])
    with (control/'whitebox_production_queue.lock').open('a+') as lease:
        fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        unity_safety.locks_clear(config, check_external=True)
        state = batch.read(output/'single_state.json')
        source = Path(state['attempt']).resolve()
        if (source/RECEIPT).is_file():
            raise ValueError('Observer recovery already selected; use normal --resume, never create another take')
        entry = batch.read(source/'input_manifest.json')['entry']
        if resolve_result(Path(config['batch']), entry)['valid']:
            raise ValueError('Existing effective score protected')
        acceptance = args.editor_acceptance.resolve()
        receipt = batch.read(acceptance)
        native_acceptance.verify(acceptance, Path(config['adapter_root']), Path(receipt['editor']))
        # The current 20s/180s acceptance must actually exercise public-runtime
        # observations, not merely accept the old direct-MonoBehaviour fixture.
        for stage in receipt['stages']:
            verification = Path(stage['verification']['path'])
            if batch.read(verification)['checks'].get('functional_observer_available') is not True:
                raise ValueError('Acceptance does not exercise functional observer availability')
            take = verification.parent/'take'
            if (not functional_observer.verify(take)['ok']
                    or functional_observer.load_contract(take/'functional_observer_contract.json')['provider_type'] != 'PublicRuntimeCore'):
                raise ValueError('Acceptance did not exercise the public nested runtime')
        native_audit = acceptance.parent.parent/'public_runtime_native_audit.json'
        audit = batch.read(native_audit)
        if audit.get('ok') is not True or [s['duration'] for s in audit['stages']] != [20, 180]:
            raise ValueError('Native nested runtime alias/clock/lifecycle audit required')
        cleanup = unity_single.check_cleanup(config, source/'background_record')
        root = prepare(source, acceptance, cleanup)
        dump(root/'observer_native_qualification.json', {'acceptance': str(acceptance),
            'acceptance_sha256': sha(acceptance), 'native_audit': str(native_audit),
            'native_audit_sha256': sha(native_audit)})
        stamp = str(time.time_ns())
        dump(output/'state_history'/('before_observer_recovery_'+stamp+'.json'), state)
        dump(output/'configuration_history'/('before_observer_recovery_'+stamp+'.json'), config)
        config['editor_acceptance'] = str(acceptance)
        dump(output/'configuration.json', config)
        unity_single.phase(output, 'observer_recovery', attempt=str(root), previous_attempt=str(source),
                           plan_model_calls_added=0)
        try:
            unity_single.complete_capture(output, root)
        except BaseException as exc:
            unity_single.phase(output, 'HARNESS_ERROR', attempt=str(root), reason=str(exc))
            raise


if __name__ == '__main__':
    main()
