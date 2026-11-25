"""Qualify real captures under the user's foreground-presence authorization.

Native receipts remain immutable. Only the foreground-presence observation may
be waived; genuine input/capture checks and all cleanup gates remain mandatory.
"""
from pathlib import Path
from .protocol import dump, sha
from . import batch

VERSION = 'whitebox-unity-foreground-presence-permitted.v1'
AUTHORIZATION = 'User 2026-10-29: 在前台就在前台吧，只要能录到就行，不必理会'
RECEIPT = 'capture_foreground_qualification.json'
REQUIRED = ('adapter_success', 'no_forbidden_host_calls', 'foreground_samples_available',
    'real_frames_present', 'all_events_delivered', 'input_cleanup', 'view_cleanup',
    'process_cleanup', 'original_unchanged', 'launches_in_verified_group',
    'sparse_slots_and_sequences')


def qualify(recorded):
    recorded = Path(recorded)
    capture = recorded/'background_record'
    verification = batch.read(capture/'verification.json')
    cleanup = batch.read(capture/'runner_exit.json')
    checks = verification.get('checks', {})
    if (cleanup.get('cleanup_verified') is not True or cleanup.get('policy_violations')
            or cleanup.get('error') or any(checks.get(k) is not True for k in
                ('input_cleanup', 'view_cleanup', 'process_cleanup'))):
        raise ValueError('Native capture cleanup did not pass')
    if verification.get('ok') is True and verification.get('status') == 'CAPTURE_VERIFIED':
        return {'accepted': True, 'basis': 'unchanged_native_verification'}
    failures = sorted(k for k, value in checks.items() if value is not True)
    if (verification.get('schema') != 'unity-background-record-verification.v1'
            or verification.get('status') != 'HARNESS_ERROR' or verification.get('ok') is not False
            or failures != ['no_owned_foreground_sample']
            or any(checks.get(k) is not True for k in REQUIRED)
            or not isinstance(verification.get('frames'), int) or verification['frames'] < 1
            or verification.get('fixture_only') is not False):
        raise ValueError('Native capture failed checks beyond permitted foreground presence: '+str(failures))
    receipt = {'version': VERSION, 'accepted': True, 'authorization': AUTHORIZATION,
        'source_attempt': str(recorded.resolve()), 'waived_checks': failures,
        'verification_sha256': sha(capture/'verification.json'),
        'runner_exit_sha256': sha(capture/'runner_exit.json'),
        'native_status': verification['status'], 'native_ok': verification['ok'],
        'foreground_pids': verification.get('foreground_pids', []),
        'policy': 'Foreground presence is permitted; raw native failure, samples and cleanup receipts are preserved. No OS input or activation fallback is authorized.'}
    path = recorded/RECEIPT
    if path.exists() and batch.read(path) != receipt:
        raise ValueError('Foreground qualification receipt changed')
    if not path.exists():
        dump(path, receipt)
    return receipt


def recoverable(output, case):
    if case.get('status') != 'BOUNDED_FAILURE' or case.get('foreground_policy_recovery_count'):
        return False
    try:
        single = batch.read(Path(output)/'single_state.json')
        recorded = Path(single['attempt'])
        if (recorded/'active_background_judge_attempt.json').exists():
            return False
        value = qualify(recorded)
        return value.get('version') == VERSION and (recorded/'sol_plan.json').is_file()
    except (OSError, ValueError, KeyError, TypeError):
        return False


def audit_binding(root):
    """Recheck the separate authorization against unchanged raw receipts."""
    root = Path(root)
    provenance = root/'recorded_capture_provenance.json'
    if not provenance.is_file():
        return {}
    source = Path(batch.read(provenance)['source_attempt'])
    if not (root/RECEIPT).is_file() and not (source/RECEIPT).is_file():
        return {}
    if not (root/RECEIPT).is_file() or not (source/RECEIPT).is_file():
        raise ValueError('Foreground qualification missing from recorded/judged evidence')
    expected = batch.read(source/RECEIPT)
    if batch.read(root/RECEIPT) != expected or qualify(source) != expected:
        raise ValueError('Foreground qualification source or copy changed')
    if batch.read(provenance).get('foreground_qualification') != expected:
        raise ValueError('Capture provenance lacks foreground authorization')
    files = [root/RECEIPT, source/RECEIPT, source/'background_record/verification.json',
        source/'background_record/runner_exit.json']
    return {str(path): sha(path) for path in files}
