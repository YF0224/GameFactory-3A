"""Raw Unity capture files shared by packaging and publication validation."""
from pathlib import Path
import json
import copy
import hashlib


VERSION = 'unity-recorded-capture-files.v7.runtime-initializer-provenance'
BASE_FILES = {'actions.jsonl', 'state_trace.jsonl', 'event_trace.jsonl',
              'frame_index.jsonl', 'video.mp4'}
LINK_FILES = {'action_schedule.json', 'action_frame_links.json'}


def expected_files(take, *, session=None):
    take = Path(take)
    session = session or {}
    present = {name for name in LINK_FILES if (take / name).is_file()}
    required = bool(session.get('adapter_pin', {}).get('action_provenance_acceptance'))
    if (present or required) and present != LINK_FILES:
        raise ValueError('Recorded action linkage must include both schedule and frame links')
    expected = BASE_FILES | present
    if not (take/'event_trace.jsonl').is_file() and (take/'_editor_report.json').is_file():
        report = json.loads((take/'_editor_report.json').read_text())
        channels = report.get('channels', {})
        state = take/'state_trace.jsonl'
        unsubscribed = (channels.get('events_available') is False
                        and channels.get('event_subscriptions') == 0)
        # The native writer opens the event trace on the first emission. A
        # successful subscribed take with zero emissions has no raw event file.
        # Treat this conservatively as unavailable evidence, not observed events.
        subscribed_without_rows = (report.get('ok') is True and not report.get('errors')
            and channels.get('events_available') is True
            and type(channels.get('event_subscriptions')) is int
            and channels['event_subscriptions'] > 0
            and channels.get('frames_available') is True
            and type(report.get('frames')) is int and report['frames'] > 0
            and (take/'frame_index.jsonl').is_file()
            and len([line for line in (take/'frame_index.jsonl').read_text().splitlines()
                     if line.strip()]) == report['frames'])
        if ((unsubscribed or subscribed_without_rows) and channels.get('event_rows') == 0
                and channels.get('events_capture_error') == ''
                and channels.get('states_available') is True and type(channels.get('state_rows')) is int
                and channels['state_rows'] > 0 and state.is_file()
                and len([line for line in state.read_text().splitlines() if line.strip()]) == channels['state_rows']):
            expected = (expected-{'event_trace.jsonl'}) | {'_editor_report.json'}
    if not (take/'state_trace.jsonl').is_file() and (take/'_editor_report.json').is_file():
        report = json.loads((take/'_editor_report.json').read_text())
        channels = report.get('channels', {})
        # A real native take may expose no state provider. Keep this as an
        # unavailable observation channel, never an observed empty game state.
        if (report.get('ok') is True and not report.get('errors')
                and report.get('state_snapshots') == 0
                and channels.get('states_available') is False
                and type(channels.get('state_rows')) is int and channels['state_rows'] == 0
                and channels.get('states_source') == ''
                and channels.get('frames_available') is True
                and not (take/'functional_observer_contract.json').exists()):
            expected = (expected-{'state_trace.jsonl'}) | {'_editor_report.json'}
            if (channels.get('events_available') is False
                    and channels.get('event_rows') == 0
                    and channels.get('event_subscriptions') == 0
                    and channels.get('events_capture_error') == ''):
                expected -= {'event_trace.jsonl'}
    if (take / 'capture_schedule.json').is_file():
        expected = (expected - {'video.mp4'}) | {'capture_schedule.json', 'play_started.json'}
        if (take / 'capture_missed.jsonl').is_file():
            expected.add('capture_missed.jsonl')
    if (take/'functional_observer_contract.json').is_file():
        from engine_adapters.unity3d.playtest.functional_observer import verify, load_contract, AUTO_VERSIONS
        if not verify(take)['ok']:
            raise ValueError('Functional observer contract unavailable in actual take')
        expected |= {'functional_observer_contract.json','functional_observer_readiness.json',
                     'state_source_bindings.jsonl','_editor_report.json'}
        contract = load_contract(take/'functional_observer_contract.json')
        if contract['schema'] in AUTO_VERSIONS:
            # Verified backing-field IL is required native provenance, not optional diagnostics.
            expected.add('public_auto_property_bindings.jsonl')
        for diagnostic in ('event_source_bindings.jsonl','event_subscription_cleanup.jsonl'):
            if (take/diagnostic).is_file():expected.add(diagnostic)
        if (take/'observer_lifecycle.jsonl').is_file():expected.add('observer_lifecycle.jsonl')
    runtime_files = {'runtime_initializer_entry.json','runtime_initializer_native.json'}
    present_runtime = {name for name in runtime_files if (take/name).is_file()}
    if present_runtime:
        if present_runtime != runtime_files:
            raise ValueError('Runtime initializer native provenance is incomplete')
        from engine_adapters.unity3d.playtest.runtime_initializer import verify_recording
        verify_recording(take)
        expected |= runtime_files
    missing = sorted(name for name in expected if not (take / name).is_file())
    if missing:
        raise ValueError('Recorded raw capture files are missing: ' + ', '.join(missing))
    return expected


def link_normalization_receipt(attempt, take):
    attempt, take = Path(attempt), Path(take)
    original = attempt/'recovery_source/native_action_frame_links.json'
    canonical = attempt/'runtime/action_frame_links.json'
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    if digest(original) != digest(take/'action_frame_links.json'):
        raise ValueError('Preserved native action links differ from the recording')
    expected = copy.deepcopy(json.loads(original.read_text()))
    additions = []
    channels = json.loads((attempt/'runtime/channels.json').read_text())
    for name, field, marker in [('event_trace.jsonl','events','UNAVAILABLE_EVENT_CHANNEL'),
                                ('state_trace.jsonl','states','UNAVAILABLE_STATE_CHANNEL')]:
        if not (take/name).is_file():
            canonical_channel = attempt/'runtime'/name
            if (canonical_channel.read_bytes() != b'' or channels.get(name) != marker
                    or any(link.get(field) for link in expected.get('links', []))):
                raise ValueError('Missing raw observations cannot become observed evidence: '+name)
            expected['sources'][name] = digest(canonical_channel)
            additions.append(name)
    if json.loads(canonical.read_text()) != expected:
        raise ValueError('Canonical action links changed raw action/frame/state/event associations')
    return {'schema':'unity-recorded-action-links-normalization.v1',
            'preserved_path':'recovery_source/native_action_frame_links.json','preserved_sha256':digest(original),
            'canonical_path':'runtime/action_frame_links.json','canonical_sha256':digest(canonical),
            'unavailable_empty_channel_hashes_added':additions,'all_associations_unchanged':True}
