"""Source-bound Unity take-clock metadata, never clock conversion or inference.

Only these two reviewed, exact native source revisions qualify. Their recorder
passes _takeStartSeconds into the internal input driver; frame/state/event/action
stamps all use (EditorApplication.timeSinceStartup - _takeStartSeconds) * 1000.
No host-clock alignment, pair-session merge or unknown source is authorized here.
"""
import copy
import json
import math
from pathlib import Path
from .protocol import dump, sha

VERSION = 'unity-native-internal-take-clock-binding.v1'
RECEIPT = 'native_clock_binding.json'
CLOCK = 'recorder_session_monotonic'
REVIEWED_SOURCES = {
    'GameFactory3APlayTestRecorder.cs': '153c7d4f30a4489eafd150213495aa816412ac6ef27dbe7a25e61df1e29bcb0d',
    'GameFactory3AInputDriver.cs': '2ed89bf1b1a2ae433c9c537d83a5f64befb0a05cf506c76c1f41e650e0e89e99',
}
CHANNELS = ('actions.jsonl', 'state_trace.jsonl', 'event_trace.jsonl', 'frame_index.jsonl')


def read(path):
    return json.loads(path.read_text())


def prove(root):
    """Recheck exact native origins; unknown/incomplete bindings fail closed."""
    root = Path(root).resolve()
    provenance = root/'recorded_capture_provenance.json'
    source = Path(read(provenance)['source_attempt']).resolve()
    native = source/'background_record'
    if (root/'runtime/multisession_index.json').exists():
        raise ValueError('Native single-take clock binding cannot merge independent sessions')
    if read(root/'runtime/engine_result.json').get('engine') != 'unity3d':
        raise ValueError('Native clock binding requires recorded Unity evidence')
    verification = native/'verification.json'
    verdict = read(verification)
    required = ('adapter_success', 'real_frames_present', 'all_events_delivered',
                'input_cleanup', 'view_cleanup', 'process_cleanup', 'original_unchanged')
    if verdict.get('ok') is not True or any(verdict.get('checks', {}).get(k) is not True for k in required):
        raise ValueError('Native clock source capture is not qualified')
    report, marker = native/'take/report.json', native/'take/play_started.json'
    if (read(report).get('editor_report', {}).get('clock') != 'EditorApplication.timeSinceStartup'
            or read(marker).get('input_transport') != 'internal'):
        raise ValueError('Unreviewed native clock or external input transport')
    bindings = {str(p): sha(p) for p in (provenance, verification, report, marker, root/'runtime/engine_result.json')}
    for name, digest in REVIEWED_SOURCES.items():
        path = native/'project/Assets/GameFactory3AEvaluation/Editor'/name
        if sha(path) != digest:
            raise ValueError('Native clock source revision is not reviewed: '+name)
        bindings[str(path)] = digest
    copied = {entry['path']: entry for entry in read(provenance)['raw_identical_copies']}
    counts = {}
    for name in CHANNELS:
        canonical, original = root/'runtime'/name, native/'take'/name
        entry = copied[name]
        if (Path(entry['source']).resolve() != original.resolve()
                or sha(original) != entry['sha256'] or sha(canonical) != entry['sha256']):
            raise ValueError('Native clock raw source binding changed: '+name)
        rows = [json.loads(line) for line in canonical.read_text().splitlines() if line.strip()]
        if not rows:
            raise ValueError('Native clock proof needs all four actual channels: '+name)
        for row in rows:
            if (not isinstance(row, dict) or row.get('session_id') is not None
                    or type(row.get('t_ms')) not in (float, int)
                    or not math.isfinite(row['t_ms']) or row['t_ms'] < 0):
                raise ValueError('Invalid single-take native row: '+name)
            if row.get('clock') not in (None, CLOCK):
                raise ValueError('Conflicting native clock: '+name)
            if name in ('frame_index.jsonl', 'event_trace.jsonl') and row.get('clock') != CLOCK:
                raise ValueError('Missing explicit native recorder clock: '+name)
            if name == 'actions.jsonl' and row.get('source') != 'internal_driver':
                raise ValueError('External/unknown action clock cannot inherit internal take clock')
        counts[name] = len(rows)
        bindings[str(canonical)] = bindings[str(original)] = entry['sha256']
    return {'version': VERSION, 'clock': CLOCK, 'source_attempt': str(source),
            'bindings': bindings, 'raw_row_counts': counts,
            'timestamp_values_changed': False, 'clock_conversion': False,
            'independent_sessions_merged': False, 'scoring_rules_changed': False}


def declare(root):
    root = Path(root)
    proof = prove(root)
    destination = root/RECEIPT
    if destination.exists() and read(destination) != proof:
        raise ValueError('Existing native clock declaration differs; preserve and diagnose')
    if not destination.exists():
        dump(destination, proof)
    return proof


def apply(root, manifest):
    """Install proven metadata only; do not edit rows, IDs, images or model text."""
    root = Path(root)
    if read(root/RECEIPT) != prove(root):
        raise ValueError('Native clock proof is stale or modified')
    if manifest.get('clock') not in ('session_monotonic', CLOCK):
        raise ValueError('Native clock binding cannot override another declared timeline')
    result = copy.deepcopy(manifest)
    result['clock'] = CLOCK
    result['native_clock_binding'] = {'path': RECEIPT, 'sha256': sha(root/RECEIPT)}
    return result


def validate(root, manifest):
    root = Path(root)
    if manifest.get('native_clock_binding') is not None or (root/RECEIPT).exists():
        if apply(root, manifest) != manifest:
            raise ValueError('Evidence manifest did not install its exact native clock declaration')
