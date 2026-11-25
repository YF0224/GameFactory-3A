"""One bounded resume after the repaired endpoint-channel packaging limit.

Recording and all planner/static calls are protected. Full source, plan, recorder
and cleanup qualification still runs in unity_single before wrapping the capture.
"""
from pathlib import Path
import json
import hashlib
import ast


def recovery_key(case):
    error = str(case.get('error', ''))
    if error == 'Native runtime error log exceeds per-file transport limit; errors cannot be clipped':
        return 'lossless_log_packaging_recovery_count'
    prefix = 'authored runtime source drift: '
    if error.startswith(prefix):
        from .unity_compilation_policy import generated_path
        if generated_path(error[len(prefix):]):
            return 'runtime_generated_metadata_packaging_recovery_count'
    if error.startswith('Endpoint physical rows exceed bounded transport: EVENT'):
        return 'prestep_event_packaging_recovery_count'
    if error.startswith('Endpoint physical rows exceed bounded transport: STATE'):
        return ('lossless_state_packaging_recovery_count' if case.get('wide_state_packaging_recovery_count')
                else 'wide_state_packaging_recovery_count')
    if error.startswith('Recorded raw capture files are missing: '):
        missing = set(error.split(': ', 1)[1].split(', '))
        if missing and missing <= {'state_trace.jsonl', 'event_trace.jsonl'}:
            return 'unavailable_channels_packaging_recovery_count'
    if error == 'measured judge request exceeds versioned transport limits; do not silently clip images or prompt':
        return 'request_metadata_packaging_recovery_count'
    if error == 'undeclared added runtime source: Assets/Resources/BillingMode.json':
        return 'billing_metadata_packaging_recovery_count'
    if metadata_paths(error):
        return 'endpoint_packaging_recovery_count'
    return None


def metadata_paths(error):
    """Recognize only a narrow authored-difference failure; verify every path later."""
    if not error.startswith('['):
        return set()
    try:
        paths = ast.literal_eval(error)
    except (ValueError, SyntaxError):
        return set()
    from .unity_compilation_policy import generated_path
    allowed = {'Assets/Resources/GameFactoryInputAxes.json'}
    if (not isinstance(paths, list) or not paths
            or any(not isinstance(p, str) or (p not in allowed and not generated_path(p)) for p in paths)):
        return set()
    return set(paths)


def lossless_validation(output, source):
    """Require the measured full-group transport proof for this immutable capture."""
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    receipt = json.loads((output.parent.parent/'wide_state_actual_transport_validation.json').read_text())
    package = Path(receipt['attempt'])
    provenance = json.loads((package/'recorded_capture_provenance.json').read_text())
    if Path(provenance['source_attempt']).resolve() != source.resolve():
        return False
    from . import endpoint_channels
    return (receipt.get('validation_only') is True
            and receipt.get('model_calls_added') == 0 and receipt.get('recordings_added') == 0
            and receipt.get('implementation_sha256') == digest(Path(endpoint_channels.__file__))
            and bool(receipt.get('groups'))
            and all(0 < group['state_encoded_bytes'] <= endpoint_channels.WIDE_STATE_BYTE_LIMIT
                    for group in receipt['groups'])
            and set(receipt.get('sources', {})) == {'runtime/state_trace.jsonl', 'runtime/action_frame_links.json'}
            and all(digest(package/name) == expected for name, expected in receipt['sources'].items()))


def request_validation(output, source):
    """Require every pending exact judge prompt to pass without an API call."""
    digest = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
    receipt = json.loads((output.parent.parent/'request_metadata_actual_validation.json').read_text())
    package = Path(json.loads((source/'active_background_judge_attempt.json').read_text())['attempt'])
    if Path(receipt['attempt']).resolve() != package.resolve():
        return False
    provenance = json.loads((package/'recorded_capture_provenance.json').read_text())
    if Path(provenance['source_attempt']).resolve() != source.resolve():
        return False
    from . import batch, endpoint_channels, frame_budget
    proto = batch.read(package/'input/pilot_rubric.json')
    manifest = batch.read(package/'evidence_manifest.json')
    pending = {name for name, _, _ in frame_budget.tasks(proto, manifest)
               if not (package/'judgments'/f'{name}.json').exists()}
    groups = receipt.get('groups', [])
    implementation = {str(Path(m.__file__).resolve()): digest(m.__file__)
                      for m in (batch, frame_budget, endpoint_channels)}
    sources = {'evidence_manifest.json', 'runtime/action_frame_links.json',
               'runtime/state_trace.jsonl', 'judgments/static.json'}
    return (receipt.get('validation_only') is True and receipt.get('model_calls_added') == 0
            and receipt.get('recordings_added') == 0 and bool(pending)
            and receipt.get('implementation') == implementation
            and set(receipt.get('sources', {})) == sources
            and all(digest(package/n) == h for n, h in receipt['sources'].items())
            and len(groups) == len(pending) and {g['name'] for g in groups} == pending
            and all(0 < g['prompt_bytes'] <= 1000000 and 0 <= g['images'] <= 100
                    and digest(package/'validation_history'/f"{g['name']}.actual_delivery.json") == g['request_receipt_sha256']
                    and not (package/'model_calls'/g['name']).exists() for g in groups))


def eligible(output, case):
    key = recovery_key(case)
    ide_error = key == 'endpoint_packaging_recovery_count'
    if case.get('status') != 'BOUNDED_FAILURE' or not key or case.get(key):
        return False
    try:
        output = Path(output)
        source = Path(json.loads((output/'single_state.json').read_text())['attempt'])
        has_package = (source/'active_background_judge_attempt.json').exists()
        if key == 'request_metadata_packaging_recovery_count':
            if not has_package or not request_validation(output, source):
                return False
        elif has_package:
            return False
        if key == 'lossless_log_packaging_recovery_count':
            from .endpoint_channels import error_lines, lossless_log_wire
            log = source/'background_record/project/Library/GameFactory3A/Editor.log'
            lines = log.read_text(errors='replace').splitlines()
            starts = [i for i,t in enumerate(lines,1) if '[GameFactory3APlayTest] entering Play Mode' in t]
            if len(starts) != 1:
                return False
            stops = [i for i,t in enumerate(lines,1) if i >= starts[0] and 'Input System module state changed to: Shutdown.' in t]
            if not stops:
                return False
            selected, _ = error_lines(lines,starts[0],stops[0])
            lossless_log_wire(log,selected)
        if key == 'runtime_generated_metadata_packaging_recovery_count':
            from .unity_ide_metadata import proof
            from .unity_compilation_policy import proof as generated_compile_proof
            name = str(case['error']).split('authored runtime source drift: ', 1)[1]
            if not (proof(source/'input/project', source/'background_record/project', name)
                    or generated_compile_proof(source, name)):
                return False
        if key == 'prestep_event_packaging_recovery_count':
            from .endpoint_channels import prestep_source_proof
            if not prestep_source_proof(source):
                return False
        if key == 'billing_metadata_packaging_recovery_count':
            from .unity_billing_metadata import proof, NAME
            project = source/'background_record/project'
            if not proof(source/'input/project', project, NAME, project/'Library/GameFactory3A/Editor.log'):
                return False
        if key == 'lossless_state_packaging_recovery_count' and not lossless_validation(output, source):
            return False
        if key == 'unavailable_channels_packaging_recovery_count':
            from .recorded_capture_files import expected_files
            expected_files(source/'background_record/take')
        if ide_error:
            from .unity_ide_metadata import proof
            from .recorded_import_review import reviewed_axis_paths
            from .unity_compilation_policy import proof as generated_compile_proof
            paths = metadata_paths(str(case.get('error', '')))
            axes = reviewed_axis_paths(source)
            if not paths or any(name not in axes and not proof(
                    source/'input/project', source/'background_record/project', name)
                    and not generated_compile_proof(source, name) for name in paths):
                return False
        verified = json.loads((source/'background_record/verification.json').read_text())
        cleanup = json.loads((source/'background_record/runner_exit.json').read_text())
        from .unity_capture_policy import qualify
        qualify(source)
        return (True
                and all(verified.get('checks',{}).get(k) is True for k in
                        ('input_cleanup','view_cleanup','process_cleanup'))
                and cleanup.get('cleanup_verified') is True and cleanup.get('policy_violations') == []
                and (source/'sol_plan.json').is_file()
                and (source/'background_record/take/frame_index.jsonl').is_file())
    except (OSError,KeyError,TypeError,ValueError):
        return False
