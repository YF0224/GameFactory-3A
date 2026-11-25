"""Explicit user policy for reporting cleanup failures without halting the queue.

This policy never qualifies a failed recording, changes raw cleanup flags, or
releases execution locks. The native recorder still closes its owned Editor.
"""
from pathlib import Path
import json
import time

from .protocol import dump, sha

VERSION = 'whitebox-cleanup-policy.v1'


def policy_path(config):
    return Path(config['batch'])/'unity_cleanup_policy.json'


def report_only(config):
    if not config.get('batch'):
        return False
    path = policy_path(config)
    if not path.is_file():
        return False
    value = json.loads(path.read_text())
    if (value.get('version') != VERSION
            or value.get('mode') not in {'strict', 'report_only'}):
        raise ValueError('Invalid explicit Unity cleanup policy')
    return value['mode'] == 'report_only'


def archive_marker(config):
    """Archive a marker for this batch; do not synthesize successful cleanup."""
    marker = Path(config['control_root'])/'background_record_cleanup_block.json'
    if not marker.exists():
        return None
    if not report_only(config):
        raise ValueError('Cleanup marker archival requires explicit report-only policy')
    raw = marker.read_bytes()
    value = json.loads(raw)
    capture = Path(value['output']).resolve()
    root = Path(config['batch']).resolve()
    if not capture.is_relative_to(root) or capture.name != 'background_record':
        raise ValueError('Cleanup marker belongs to another batch')
    archive = marker.parent/'cleanup_recovery_history'/str(time.time_ns())
    archive.mkdir(parents=True, exist_ok=False)
    saved = archive/'original_marker.json'
    saved.write_bytes(raw)
    receipt = {'version':VERSION, 'mode':'report_only', 'capture':str(capture),
        'original_marker':str(saved), 'original_marker_sha256':sha(saved),
        'policy':str(policy_path(config)), 'policy_sha256':sha(policy_path(config)),
        'cleanup_qualified':False, 'archived_unix':time.time()}
    dump(archive/'report_only_receipt.json', receipt)
    if marker.read_bytes() != raw:
        raise ValueError('Cleanup marker changed while archiving')
    marker.unlink()
    return receipt


def capture_report(config, capture, *, error=None):
    """Keep observed true/false/missing flags and the original failure reason."""
    if not report_only(config):
        raise ValueError('Cleanup report requires explicit report-only policy')
    capture = Path(capture).resolve() if capture else None
    result = {'version':VERSION, 'mode':'report_only', 'checked_unix':time.time(),
        'capture':str(capture) if capture else None, 'cleanup_qualified':False,
        'policy_sha256':sha(policy_path(config)), 'errors':[]}
    if error is not None:
        result['errors'].append({'type':type(error).__name__, 'error':str(error)})
    if capture:
        for name in ('verification.json', 'runner_exit.json'):
            path = capture/name
            if not path.is_file():
                result['errors'].append({'type':'MissingReceipt', 'path':str(path)})
                continue
            try:
                value = json.loads(path.read_text())
            except (ValueError, OSError) as exc:
                result['errors'].append({'type':type(exc).__name__, 'error':str(exc), 'path':str(path)})
                continue
            result[name] = {'path':str(path), 'sha256':sha(path)}
            if name == 'verification.json':
                checks = value.get('checks', {})
                result.update({k:checks.get(k) for k in
                    ('input_cleanup', 'view_cleanup', 'process_cleanup')})
            else:
                result['runner_cleanup_verified'] = value.get('cleanup_verified')
                result['policy_violations'] = value.get('policy_violations')
        dump(capture/'cleanup_report_only.json', result)
    return result
