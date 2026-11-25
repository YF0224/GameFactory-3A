"""Explicit native client routing; nominal route times are NOT a shared native clock."""
import copy
import json
from pathlib import Path

VERSION = 'whitebox-native-multisession.v1'
ROLES = ('A', 'B')


def enabled(protocol):
    return protocol.get('native_sessions', {}).get('version') == VERSION


def freeze(protocol, contract):
    if contract != {'version': VERSION, 'roles': list(ROLES), 'topology': 'tcp_host_two_clients',
                    'clock': 'independent_recorder_sessions'}:
        raise ValueError('Unsupported native session contract')
    protocol['native_sessions'] = copy.deepcopy(contract)


def contract():
    return {'version': VERSION, 'roles': list(ROLES), 'topology': 'tcp_host_two_clients',
            'clock': 'independent_recorder_sessions'}


def role_field(schema, *, both=False):
    schema['properties']['client_role'] = {'type': 'string', 'enum': list(ROLES) + (['BOTH'] if both else [])}
    schema['required'].append('client_role')
    return schema


def extend_schema(schema, protocol):
    if enabled(protocol):
        steps = schema['properties']['probes']['items']['properties']['steps']['items']
        for branch in steps.get('anyOf', [steps]):
            role_field(branch, both=True)
    return schema


def prompt(protocol):
    if not enabled(protocol):
        return ''
    return '''\nNATIVE MULTISESSION CONTRACT: A and B are real isolated clients connected to one TCP host.
Every step has client_role=A, B or BOTH. Non-target clients wait for that step's duration;
BOTH sends the same physical chord independently to both clients. One nominal sequential
route is used, but native recorder clocks/startup are independent (allow connection/setup
slack). Do not assume simultaneous frames or exact cross-client timing. Use existing public
keyboard controls; --replay is OFF. Read real HUD bindings, including ready/pause confirmations.
Each capture endpoint and Gameness window has client_role=A or B (the observing client).
last_action_id must be a physical input to that same client or BOTH. Use separate short
windows to inspect the other client where needed; no extra scored targets. Shared source
rubric conditions are unchanged. Preserve counts/order through actual TCP host/state events.
'''


def validate(protocol, plan, actions):
    if not enabled(protocol):
        return
    if {a.get('client_role') for a in actions if a['action'] != 'wait'} - {*ROLES, 'BOTH'}:
        raise ValueError('Unrouted native input')
    if any(not any(a['action'] != 'wait' and a.get('client_role') in {role, 'BOTH'} for a in actions)
           for role in ROLES):
        raise ValueError('Both native clients require real planned physical inputs')
    indexed = {a['action_id']: a for a in actions}
    for endpoint in plan['capture_plan']['endpoints'].values():
        if endpoint['reachability'] == 'EXECUTABLE':
            last = indexed[endpoint['last_action_id']]
            if last.get('client_role') not in {endpoint['client_role'], 'BOTH'}:
                raise ValueError('Endpoint last action belongs to another native client')


def split_actions(actions, role):
    """Keep the full nominal timeline; never execute another client's inputs."""
    if role not in ROLES:
        raise ValueError('Unknown native client')
    result = copy.deepcopy(actions)
    for row in result:
        original = row['action_id']
        row.update(action_id=role+':'+original, plan_action_id=original, session_id=role)
        if row.get('client_role', 'BOTH') not in {role, 'BOTH'}:
            row.update(action='wait')
            for key in ('key', 'x', 'y', 'to_x', 'to_y', 'button'):
                row.pop(key, None)
    return result


def validate_schedule(schedule):
    """Reject disconnected capture/window identities before native execution."""
    if any(p.get('client_role') not in ROLES for p in schedule['points']):
        raise ValueError('Capture point has no native role')
    keys = [(p['client_role'], p['at_ms']) for p in schedule['points']]
    if len(set(keys)) != len(keys):
        raise ValueError('Duplicate role-local capture slot')
    for window in schedule['plan']['windows']:
        role = window.get('client_role')
        points = [p for p in schedule['points'] if window['id'] in p['capture_ids']]
        if role not in ROLES or len(points) < 3 or any(p['client_role'] != role for p in points):
            raise ValueError('Window lacks its role-local capture points')
        stamps = sorted(p['at_ms'] for p in points)
        if (stamps[0] != window['start_ms'] or stamps[-1] != window['end_ms']
                or any(b-a > 450 for a, b in zip(stamps, stamps[1:]))):
            raise ValueError('Window capture slots do not cover its declared interval')


def split_schedule(schedule, role):
    result = copy.deepcopy(schedule)
    result['points'] = [p for p in result['points'] if p['client_role'] == role]
    result['plan']['windows'] = [w for w in result['plan']['windows'] if w['client_role'] == role]
    result['plan']['endpoints'] = {ident: endpoint for ident, endpoint in result['plan'].get('endpoints', {}).items()
                                   if endpoint['client_role'] == role}
    for endpoint in result['plan']['endpoints'].values():
        if endpoint.get('last_action_id'):
            endpoint['last_action_id'] = role+':'+endpoint['last_action_id']
    return result


def slot(role, stamp):
    return f'{role}@{stamp}'



CHANNELS = ('actions.jsonl', 'frame_index.jsonl', 'state_trace.jsonl', 'event_trace.jsonl')
CLOCK_FIELDS = ('t_ms', 'timestamp_ms', 'send_start_t_ms', 'send_end_t_ms', 'end_t_ms',
                'end_ms', 'completed_t_ms', 'capture_end_t_ms')


def _derived(folder, schedule):
    """Deterministic, independently replayable derivation from immutable raw bytes.

    Role-local zero points remove startup/warmup only. They do not establish any
    ordering between clients. Every nonempty canonical row retains its physical
    source line; original blank lines remain in the retained session file.
    """
    from .protocol import checked_path, sha
    from .action_links import physical_rows, frame_id
    folder = Path(folder)
    channels = {name: [] for name in CHANNELS}
    sources, offsets, actions, logs, log_lines = {}, {}, [], [], []
    for role in ROLES:
        take = folder/'sessions'/role
        ready = json.loads((take/'play_started.json').read_text(encoding='utf-8-sig'))
        offsets[role] = ready['recorder_elapsed_ms'] + schedule['warmup_ms']
        if not isinstance(offsets[role], (int, float)) or not __import__('math').isfinite(offsets[role]):
            raise ValueError('Invalid independent native recorder clock')
        raw_schedule = json.loads((take/'action_schedule.json').read_text())
        expected_ids = set()
        for row in raw_schedule['actions']:
            if row.get('session_id') != role or not row['action_id'].startswith(role+':'):
                raise ValueError('Raw action schedule lost session identity')
            expected_ids.add(row['action_id'])
            actions.append(copy.deepcopy(row))
        if json.loads((take/'capture_schedule.json').read_text()) != split_schedule(schedule, role):
            raise ValueError('Raw session capture schedule differs from role route')
        for path in sorted(take.rglob('*')):
            if path.is_symlink():
                raise ValueError('Native evidence must not contain symlinks')
            if path.is_file():
                sources[str(path.relative_to(folder))] = sha(path)
        for name in CHANNELS:
            for line, original in physical_rows(take/name):
                row = copy.deepcopy(original)
                if row.get('session_id', role) != role:
                    raise ValueError('Cross-role raw channel identity')
                if name == 'actions.jsonl' and row.get('action_id') and row['action_id'] not in expected_ids:
                    raise ValueError('Recorded input outside its native role schedule')
                row.update(session_id=role, client_role=role, native_line=line,
                           native_source='sessions/'+role+'/'+name,
                           native_clock='independent_recorder_session',
                           native_t_ms=original.get('t_ms', original.get('timestamp_ms')))
                for field in CLOCK_FIELDS:
                    if field in row:
                        row[field] -= offsets[role]
                if name == 'frame_index.jsonl':
                    row['frame_id'] = role+':'+frame_id(original, line)
                    pixel = checked_path(take, original['path'])
                    row['path'] = str(pixel.relative_to(folder))
                channels[name].append(row)
        log = take/'player.log'
        if not log.is_file():
            raise ValueError('Missing independent native client log')
        for line, text in enumerate(log.read_text(errors='replace').splitlines(), 1):
            logs.append('['+role+'] '+text)
            log_lines.append({'session_id':role, 'native_source':'sessions/'+role+'/player.log',
                              'native_line':line, 'canonical_line':len(logs)})
    for path in sorted((folder/'sessions/host').rglob('*')):
        if path.is_symlink():
            raise ValueError('Host evidence must not contain symlinks')
        if path.is_file():
            sources[str(path.relative_to(folder))] = sha(path)
    # Concatenation is deterministic by role then physical line, never a global
    # timestamp sort that could imply synchronization of independent clocks.
    encoded = {name: ''.join(json.dumps(row, ensure_ascii=False)+'\n' for row in rows)
               for name, rows in channels.items()}
    encoded['engine.log'] = ''.join(text+'\n' for text in logs)
    encoded['log_index.jsonl'] = ''.join(json.dumps(row)+'\n' for row in log_lines)
    encoded['action_schedule.json'] = json.dumps({'version':VERSION, 'actions':actions}, ensure_ascii=False)
    return encoded, sources, offsets


def derive_capture(folder, schedule):
    """Create canonical indexes once. Never overwrite original or derived evidence."""
    from .protocol import dump, sha
    folder = Path(folder)
    encoded, sources, offsets = _derived(folder, schedule)
    destinations = [folder/name for name in encoded] + [folder/'capture_schedule.json', folder/'multisession_index.json']
    if any(path.exists() for path in destinations):
        raise ValueError('Canonical multi-session evidence already exists; preserve it')
    for name, text in encoded.items():
        (folder/name).write_text(text)
    dump(folder/'capture_schedule.json', schedule)
    record = {'version':VERSION, 'schedule':schedule, 'offsets_ms':offsets,
              'source_sha256':sources,
              'canonical_sha256':{name:sha(folder/name) for name in encoded},
              'clock':'independent role-local clocks; NO cross-session synchronization'}
    dump(folder/'multisession_index.json', record)
    from .action_links import write_links
    write_links(folder)
    return audit_capture(folder, schedule)

def audit_capture(folder, schedule):
    """Re-audit raw session clocks/pixels and their explicit canonical derivation."""
    from .protocol import sha, load_lines, checked_path
    from .sparse_evidence import audit_capture as audit_single
    folder = Path(folder)
    record = json.loads((folder/'multisession_index.json').read_text())
    if record['version'] != VERSION or record['schedule'] != schedule:
        raise ValueError('Changed multi-session capture identity')
    for name, digest in record['source_sha256'].items():
        if sha(checked_path(folder, name)) != digest:
            raise ValueError('Changed raw native session evidence: '+name)
    for name, digest in record['canonical_sha256'].items():
        if sha(checked_path(folder, name)) != digest:
            raise ValueError('Changed canonical native session evidence: '+name)
    expected, sources, offsets = _derived(folder, schedule)
    if sources != record['source_sha256'] or offsets != record['offsets_ms']:
        raise ValueError('Native source set or independent clock changed')
    if set(expected) != set(record['canonical_sha256']):
        raise ValueError('Incomplete canonical channel binding')
    if any((folder/name).read_text() != text for name, text in expected.items()):
        raise ValueError('Canonical channel differs from physical native rows')
    results, frames, slots, windows = {}, load_lines(folder/'frame_index.jsonl'), {}, {}
    if len({r['frame_id'] for r in frames}) != len(frames):
        raise ValueError('Duplicate cross-session frame identity')
    for role in ROLES:
        take = folder/'sessions'/role
        result = audit_single(take, split_schedule(schedule, role))
        if result['missing_slots_ms'] or any(not w['complete'] or not w['continuous'] for w in result['windows'].values()):
            raise ValueError('Incomplete native session sparse capture: '+role)
        results[role] = result
        for stamp, fid in result['slot_frames'].items():
            slots[slot(role, stamp)] = role+':'+fid
        for ident, window in result['windows'].items():
            windows[ident] = {**window, 'session_id':role, 'frame_ids':[role+':'+f for f in window['frame_ids']]}
        # Canonical frames must map one-to-one to unchanged source pixels/rows.
        raw = load_lines(take/'frame_index.jsonl')
        canonical = [r for r in frames if r.get('session_id') == role]
        offset = record['offsets_ms'][role]
        if len(raw) != len(canonical):
            raise ValueError('Lost native session frames')
        indexed = {r['native_line']:r for r in canonical}
        for line, original in enumerate(raw, 1):
            row = indexed[line]
            if (row['frame_id'] != role+':'+original['frame_id'] or
                    abs(row['t_ms'] - (original['t_ms']-offset)) > .001 or
                    sha(checked_path(folder,row['path'])) != sha(checked_path(take,original['path'])) or
                    row.get('sample_at_ms') != original.get('sample_at_ms')):
                raise ValueError('Cross-role or retimed native frame derivation')
    if set(record['offsets_ms']) != set(ROLES):
        raise ValueError('Missing native recorder clock')
    return {'version':schedule['version'], 'schedule_sha256':sha(folder/'capture_schedule.json'),
            'planned_screenshots':sum(r['planned_screenshots'] for r in results.values()),
            'actual_screenshots':len(frames), 'missing_slots_ms':[], 'windows':windows,
            'slot_frames':slots, 'sessions':results, 'continuous_full_route':False,
            'clock':'role-local recorder clocks, normalized independently; NOT synchronized',
            'intentional_gaps':'Only readiness, declared endpoints and short windows per client.'}


def verify_projects(root):
    """Verify each actually executed project, accepted metadata and added observers."""
    from . import batch
    from .protocol import checked_path, sha
    root=Path(root)
    receipt=batch.read(root/'runtime/multisession_sources.json')
    from .unity_native_pair_sources import VERSION as SOURCE_VERSION, verify as verify_sources
    if receipt.get('schema') == SOURCE_VERSION:
        return verify_sources(root)
    meta=batch.read(root/'input_manifest.json')
    baseline=meta['snapshot_hashes']
    if receipt['version']!=VERSION or receipt['baseline_sha256']!=baseline:
        raise ValueError('Native project baseline differs from frozen planning source')
    acceptance=Path(receipt['native_acceptance'])
    required={'result.json','verification.json','cleanup.json','multisession_index.json',
              'source_binding.json','capture_schedule.json','client_snapshots.json'}
    if not required.issubset(receipt['acceptance_bindings']):
        raise ValueError('Native source acceptance bindings incomplete')
    for name,digest in receipt['acceptance_bindings'].items():
        if sha(checked_path(acceptance,name))!=digest:
            raise ValueError('Native source acceptance binding changed: '+name)
    if (batch.read(acceptance/'result.json').get('ok') is not True
            or not all(batch.read(acceptance/'verification.json')['checks'].values())
            or not all(batch.read(acceptance/'cleanup.json')[k] for k in
                       ('input_cleanup','view_cleanup','process_cleanup'))):
        raise ValueError('Native source acceptance/cleanup invalid')
    audit_capture(acceptance,batch.read(acceptance/'capture_schedule.json'))
    observed=batch.read(Path(receipt['observer_binding']))
    if sha(Path(receipt['observer_binding']))!=receipt['observer_binding_sha256']:
        raise ValueError('Accepted observer receipt changed')
    observer=observed['files']
    expected_metadata={}
    expected_generated={}
    approved={'Packages/manifest.json','Packages/packages-lock.json','ProjectSettings/ProjectVersion.txt',
              'ProjectSettings/ShaderGraphSettings.asset','ProjectSettings/UnityConnectSettings.asset'}
    accepted_before=batch.read(acceptance/'client_snapshots.json')
    for role in ROLES:
        if accepted_before[role]['files_sha256']!=baseline:
            raise ValueError('Native import acceptance used another source')
        imported=batch.hashes(acceptance/('project_'+role))
        changes={n:imported.get(n) for n,digest in baseline.items() if imported.get(n)!=digest}
        if set(changes)-approved or any(v is None for v in changes.values()):
            raise ValueError('Native import acceptance contains authored changes')
        expected_metadata[role]=changes
        generated={}
        for name,digest in imported.items():
            if name in baseline:continue
            path=Path(name)
            if ((path.parts[0]=='ProjectSettings' and len(path.parts)==2 and path.suffix=='.asset')
                    or (path.parts[0]=='UserSettings' and path.suffix in {'.asset','.settings','.dwlt'})):
                generated[name]=digest
        expected_generated[role]=generated
    if receipt['accepted_import_sha256']!=expected_metadata:
        raise ValueError('Native import metadata acceptance changed')
    for role in ROLES:
        spec=receipt['projects'][role]
        project=(root/spec['path']).resolve()
        if Path(spec['path']).is_absolute() or not project.is_relative_to(root.resolve()) or not project.is_dir():
            raise ValueError('Invalid executed project path: '+role)
        current=batch.hashes(project)
        executed=batch.hashes(Path(receipt['capture_root'])/('project_'+role))
        if current!=spec['files_sha256'] or executed!=current:
            raise ValueError('Executed native project source changed: '+role)
        for name,digest in baseline.items():
            if current.get(name)!=expected_metadata[role].get(name,digest):
                raise ValueError('Native authored source drift: '+role+':'+name)
        for name,digest in current.items():
            if name in baseline:continue
            if name.endswith('.meta'):continue
            if expected_generated[role].get(name)==digest:continue
            if name=='Assets/GameFactory3AEvaluation/installation.json':
                if batch.read(project/name)!={'schema':'unity-observer-installation.v1','files':observer}:
                    raise ValueError('Observer installation receipt changed: '+role)
                continue
            if observer.get(name)!=digest:
                raise ValueError('Unaccepted native observer/addition: '+role+':'+name)
        if any(current.get(name)!=digest for name,digest in observer.items()):
            raise ValueError('Accepted observer missing/changed: '+role)
    return {'valid':True,'roles':list(ROLES),'clock':'independent recorder sessions',
            'source_receipt_sha256':sha(root/'runtime/multisession_sources.json')}
