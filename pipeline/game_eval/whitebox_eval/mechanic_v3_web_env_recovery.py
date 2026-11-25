"""One explicit continuation of an empty Three.js Vite-not-found launch.

Preserve the failed admission and every diagnostic. Only author-declared shared
Vite/Three dependencies are supplied; original source, plan and windows remain.
"""
import copy
import os
import shutil
from pathlib import Path
from . import batch, core12, endpoint_sparse
from . import mechanic_v3_native as native, mechanic_v3_prerecord_recovery as prerecord
from . import mechanic_v3_outcome_native as outcome_native, mechanic_v3_revision as revision
from .mechanic_v3_runner import read, exclusive_json, disk, stamp
from .protocol import sha, dump, write_operation_report

VERSION = 'mechanic-empty-web-env-prelaunch-recovery.v1'


def diagnose(source):
    source = Path(source)
    runtime = source/'runtime'
    dispatch = read(runtime/'dispatch_result.json')
    envelope = dispatch.get('envelope', {})
    payload = envelope.get('payload', {})
    errors = envelope.get('errors', [])
    if (dispatch.get('engine') != 'three_js' or envelope.get('ok') is not False
            or len(errors) != 1 or 'dev server exited with code 127:' not in errors[0]
            or 'sh: vite: command not found' not in errors[0]
            or payload.get('url') != '' or payload.get('report_path') is not None
            or payload.get('take_dir')):
        raise ValueError('Exact Vite-not-found prelaunch failure required')
    if not (source/'native_capture_admission.json').is_file():
        raise ValueError('Original failed admission required')
    for name in ('source_qualification.json', 'mechanic_score.json', 'gameness_score.json', 'scores.json'):
        if (source/name).exists():
            raise ValueError('Qualified or scored take cannot be repeated')
    for name in ('actions.jsonl', 'state_trace.jsonl', 'event_trace.jsonl', 'frame_index.jsonl'):
        if (runtime/name).stat().st_size:
            raise ValueError('Native channels already contain evidence')
    if any((runtime/'frames').iterdir()):
        raise ValueError('Native frames already exist')
    files = list((runtime/'native').rglob('*'))
    if any(p.is_dir() or p.name != 'action_plan.json' for p in files) or len(files) != 1:
        raise ValueError('Native take artifacts already exist')
    cleanup = read(runtime/'native_cleanup_error.json')
    if (cleanup.get('reason') != "KeyError('take_dir')" or cleanup.get('live_owned_engines') != []
            or 'vite: command not found' not in cleanup.get('primary_error', '')):
        raise ValueError('Expected empty prelaunch cleanup diagnostic required')
    for folder in (source/'model_calls').glob('mechanic_v3*'):
        if (folder/'accepted_response.json').exists():
            raise ValueError('Accepted product judgment cannot be repeated')
    return dispatch


def toolchain(source, environment):
    from engine_adapters.three_js.playtest.dependencies import verify_critical_packages
    source = Path(source); environment = Path(environment).resolve()
    project = source/'input/project'
    config = project/'vite.config.js'; readme = project/'README.md'
    package = read(project/'package.json')
    if (package.get('scripts', {}).get('dev') != 'vite'
            or 'A3GAME_WEB_ENV' not in config.read_text()
            or 'A3GAME_WEB_ENV' not in readme.read_text()):
        raise ValueError('Original author must declare this shared Vite environment')
    if verify_critical_packages(environment, ['vite', 'three']) or not (environment/'node_modules/.bin/vite').is_file():
        raise ValueError('Shared Vite/Three dependencies are incomplete')
    paths = [config, readme, project/'package.json', environment/'package.json', environment/'package-lock.json',
             environment/'node_modules/vite/package.json', environment/'node_modules/three/package.json',
             environment/'node_modules/.bin/vite']
    return {str(p.resolve()): sha(p) for p in paths}


def prepare(workspace, row, environment):
    workspace = Path(workspace).resolve(); environment = Path(environment).resolve()
    source = workspace/'runs'/row['entry']['id']
    if not row.get('in_scope') or row['entry']['actual_engine'] != 'three_js':
        raise ValueError('Frozen original Three.js identity required')
    if (revision.publication_dir(workspace)/(source.name+'.json')).exists():
        raise ValueError('Published Mechanic must be reused')
    if (source/prerecord.CLAIM).exists():
        claim = read(source/prerecord.CLAIM)
        if claim.get('version') != VERSION or claim.get('shared_environment') != str(environment):
            raise ValueError('Different existing recovery must be preserved')
        return prerecord.verify(workspace, row)
    batch.verify_inputs(source); diagnose(source)
    environment_bindings = toolchain(source, environment)
    paths = [Path(__file__), source/'input_manifest.json', source/'attempt_manifest.json',
             source/'sol_plan.json', source/'native_capture_admission.json']
    for folder in ('input', 'model_calls', 'requests', 'failures', 'runtime'):
        paths.extend(p for p in (source/folder).rglob('*') if p.is_file()
                     and not (folder == 'runtime' and 'project' in p.relative_to(source/'runtime').parts))
    contract = revision.contract_dir(workspace, row['entry']['case_id'])
    paths.extend((contract/'contract.json', contract/'frozen.json'))
    bindings = {str(p.resolve()): sha(p) for p in paths}
    bindings.update(environment_bindings)
    recovery = workspace/'prerecord_recovery'/source.name/core12.fingerprint(bindings)
    root = recovery/'runs'/source.name
    disk(workspace, 'empty_web_env_prelaunch_continuation', 2*1024**3)
    claim = dict(version=VERSION, time=stamp(), source=str(source), source_bindings=bindings,
                 recovery_root=str(root), shared_environment=str(environment),
                 root_cause='Author-declared shared dependency environment was absent; Vite exited 127 before any native take.',
                 original_failed_admission_preserved=True, native_actions_before_repair=0, native_frames_before_repair=0,
                 actions_windows_coverage_unchanged=True, scoring_contract_unchanged=True, model_call_repeated=False)
    exclusive_json(source/prerecord.CLAIM, claim)
    root.mkdir(parents=True, exist_ok=False); native.configuration(recovery, workspace)
    shutil.copytree(source/'input', root/'input', symlinks=True)
    for name in ('input_manifest.json', 'attempt_manifest.json'):
        shutil.copyfile(source/name, root/name)
    proto = core12.verify_attempt(root, 'three_js'); before = read(source/'sol_plan.json')
    operation = copy.deepcopy(before); operation['planning_identity'] = core12.plan_identity(root, proto, 'three_js')
    operation = batch.validate_operation_plan(root, operation, 'three_js')
    expected = copy.deepcopy(before); expected['planning_identity'] = operation['planning_identity']
    if operation != expected:
        raise ValueError('Environment continuation changed actions, coverage or capture windows')
    dump(root/'sol_plan.json', operation); endpoint_sparse.freeze_conditions(root, proto, operation)
    write_operation_report(root, operation)
    exclusive_json(root/'prerecord_recovery.json', dict(claim, claim_sha256=sha(source/prerecord.CLAIM),
                   operation_sha256=sha(root/'sol_plan.json'), full_current_validator_passed=True,
                   new_native_recording=False, native_record_acceptance='PENDING'))
    return prerecord.verify(workspace, row)


def record(workspace, row, environment):
    root = prepare(workspace, row, environment)
    if (root/'source_qualification.json').exists():
        return root
    # Exactly one capture under the explicit frozen environment. The ordinary
    # native admission, resource leases, single-use guard and cleanup all apply.
    previous = os.environ.get('A3GAME_WEB_ENV')
    os.environ['A3GAME_WEB_ENV'] = str(Path(environment).resolve())
    try:
        actual = outcome_native.record(workspace, row)
        if actual != root:
            raise ValueError('Native capture selected a different continuation')
        return actual
    finally:
        if previous is None:
            os.environ.pop('A3GAME_WEB_ENV', None)
        else:
            os.environ['A3GAME_WEB_ENV'] = previous
