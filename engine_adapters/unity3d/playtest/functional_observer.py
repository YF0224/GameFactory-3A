"""Source-bound observer availability; never infers game success from telemetry."""
import json
import re
from pathlib import Path

VERSION = 'unity-functional-observer-contract.v1'
PUBLIC_FIELDS_VERSION = 'unity-functional-observer-contract.v2.public-fields'
PUBLIC_EVENTS_VERSION = 'unity-functional-observer-contract.v3.public-events'
AUTO_PROPERTIES_VERSION = 'unity-functional-observer-contract.v4.public-auto-properties'
MUTABLE_AUTO_PROPERTIES_VERSION = 'unity-functional-observer-contract.v5.verified-auto-properties'
AUTO_VERSIONS = (AUTO_PROPERTIES_VERSION, MUTABLE_AUTO_PROPERTIES_VERSION)


def load_contract(path):
    value = json.loads(Path(path).read_text())
    fields = value.get('required_fields')
    auto = value.get('schema') in AUTO_VERSIONS
    events = value.get('schema') == PUBLIC_EVENTS_VERSION or (auto and 'public_event_paths' in value)
    explicit = value.get('schema') in (PUBLIC_FIELDS_VERSION, PUBLIC_EVENTS_VERSION, *AUTO_VERSIONS)
    expected = {'schema', 'provider_type', 'required_fields', 'require_events'} | ({'public_field_paths'} if explicit else set()) | ({'public_event_paths'} if events else set())
    if (set(value) != expected
            or value.get('schema') not in (VERSION, PUBLIC_FIELDS_VERSION, PUBLIC_EVENTS_VERSION, *AUTO_VERSIONS)
            or not isinstance(value.get('provider_type'), str)
            or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.+`]*', value['provider_type'])
            or not isinstance(fields, list) or not fields or len(fields) > 128
            or not all(isinstance(n, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', n) for n in fields)
            or len(set(fields)) != len(fields) or type(value.get('require_events')) is not bool):
        raise ValueError('Invalid functional observer availability contract')
    if explicit:
        paths = value.get('public_field_paths')
        if (not isinstance(paths, list) or not 1 <= len(paths) <= 128
                or any(not isinstance(row, dict) or set(row) != ({'name', 'path', 'auto_property_segments'} if auto else {'name', 'path'})
                       or not isinstance(row['name'], str) or row['name'] not in fields
                       or not isinstance(row['path'], str)
                       or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*){0,7}', row['path'])
                       for row in paths)
                or len({row['name'] for row in paths}) != len(paths)
                or {row['name'] for row in paths} != set(fields)):
            raise ValueError('Invalid explicit public field paths')
    if auto:
        for row in paths:
            indexes=row['auto_property_segments']
            if (not isinstance(indexes,list) or any(type(i) is not int for i in indexes)
                    or indexes!=sorted(set(indexes))
                    or any(i<0 or i>=len(row['path'].split('.')) for i in indexes)):
                raise ValueError('Invalid public auto-property segment indexes')
        if not any(row['auto_property_segments'] for row in paths):
            raise ValueError('Auto-property contract requires explicit property segments')
    if events:
        paths = value.get('public_event_paths')
        if (value['require_events'] is not True or not isinstance(paths, list) or not 1 <= len(paths) <= 32
                or any(not isinstance(row, dict) or set(row) != ({'path', 'event_name', 'auto_property_segments'} if value['schema']==MUTABLE_AUTO_PROPERTIES_VERSION else {'path', 'event_name'})
                    or not isinstance(row['path'], str)
                    or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*){0,7}', row['path'])
                    or not isinstance(row['event_name'], str)
                    or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', row['event_name']) for row in paths)
                or len({(row['path'], row['event_name']) for row in paths}) != len(paths)):
            raise ValueError('Invalid explicit public event paths')
    if events and value['schema']==MUTABLE_AUTO_PROPERTIES_VERSION:
        for row in value['public_event_paths']:
            indexes=row['auto_property_segments']
            if (not isinstance(indexes,list) or any(type(i) is not int for i in indexes)
                    or indexes!=sorted(set(indexes))
                    or any(i<0 or i>=len(row['path'].split('.')) for i in indexes)):
                raise ValueError('Invalid public event auto-property segment indexes')
    return value


def verify(take):
    take = Path(take)
    contract = load_contract(take / 'functional_observer_contract.json')
    def read(name, default):
        path = take / name
        return json.loads(path.read_text()) if path.is_file() else default
    def rows(name):
        path = take / name
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.is_file() else []
    ready = read('functional_observer_readiness.json', {})
    keys = ready.get('source_keys', [])
    bindings = rows('state_source_bindings.jsonl')
    sources = [s for row in bindings for s in row.get('sources', [])
               if s.get('type') == contract['provider_type'] and s.get('key') in keys]
    states = rows('state_trace.jsonl')
    functional = [row['state'][keys[0]] for row in states
                  if len(keys) == 1 and isinstance(row.get('state', {}).get(keys[0]), dict)]
    reports = read('_editor_report.json', {}).get('channels', {})
    checks = {
        'preinput_readiness': ready.get('schema') == 'unity-functional-observer-readiness.v1'
            and ready.get('available') is True and ready.get('gameplay_verified') is False and len(keys) == 1,
        'source_bound': bool(sources) and all(s.get('hierarchy') and s.get('binding')
            and (contract['schema'] not in (PUBLIC_FIELDS_VERSION, PUBLIC_EVENTS_VERSION, *AUTO_VERSIONS)
                 or s.get('binding') == ('explicit-public-auto-property-paths' if contract['schema'] in AUTO_VERSIONS else 'explicit-public-field-paths')) for s in sources),
        'required_fields_observed': bool(functional)
            and all(set(contract['required_fields']) <= state.keys() for state in functional),
        'events_subscribed': not contract['require_events'] or reports.get('event_subscriptions', 0) > 0,
    }
    if contract['schema'] in AUTO_VERSIONS:
        auto_bindings=rows('public_auto_property_bindings.jsonl')
        checks['verified_auto_property_bindings']=all(any(
            row.get('schema')==('unity-public-auto-property-binding.v2' if contract['schema']==MUTABLE_AUTO_PROPERTIES_VERSION else 'unity-public-auto-property-binding.v1')
            and row.get('source_key') in keys and row.get('provider_type')==contract['provider_type']
            and row.get('path')==expected['path'] and row.get('segment_index')==index
            and row.get('property')==expected['path'].split('.')[index]
            and row.get('backing_field')=='<'+row['property']+'>k__BackingField'
            and row.get('declaring_type') and row.get('getter_il_base64')
            and row.get('getter_invoked') is False
            and (row.get('readonly_auto_property_verified') is True if contract['schema']==AUTO_PROPERTIES_VERSION
                 else row.get('auto_property_verified') is True and row.get('setter_invoked') is False
                    and type(row.get('setter_present')) is bool and type(row.get('backing_readonly')) is bool
                    and isinstance(row.get('setter_il_base64'),str)
                    and (bool(row['setter_il_base64']) and row['backing_readonly'] is False if row['setter_present'] else row['setter_il_base64']=='' and row['backing_readonly'] is True))
            for row in auto_bindings)
            for expected in (contract['public_field_paths'] + (contract.get('public_event_paths',[]) if contract['schema']==MUTABLE_AUTO_PROPERTIES_VERSION else []))
            for index in expected['auto_property_segments'])
    if contract['schema'] == PUBLIC_EVENTS_VERSION or (contract['schema'] in AUTO_VERSIONS and 'public_event_paths' in contract):
        event_bindings = rows('event_source_bindings.jsonl')
        checks['explicit_event_sources_bound'] = all(any(
            row.get('schema') == 'whitebox-event-source-binding.v1'
            and row.get('provider_type') == contract['provider_type']
            and row.get('state_key') in keys
            and row.get('member_path') == expected['path']
            and row.get('event_name') == expected['event_name']
            and row.get('binding') == ('explicit-public-auto-property-event' if contract['schema']==MUTABLE_AUTO_PROPERTIES_VERSION else 'explicit-public-field-event')
            and row.get('source_key') and row.get('source_type')
            and type(row.get('owner_instance_id')) is int
            and any(source.get('key') == row.get('state_key')
                    and source.get('instance_id') == row.get('owner_instance_id')
                    and source.get('hierarchy') == row.get('hierarchy')
                    for source in sources)
            for row in event_bindings) for expected in contract['public_event_paths'])
    return {'schema': 'unity-functional-observer-verification.v1', 'ok': all(checks.values()),
            'checks': checks, 'source_keys': keys, 'functional_state_rows': len(functional),
            'event_rows': len(rows('event_trace.jsonl')), 'gameplay_verified': False}
