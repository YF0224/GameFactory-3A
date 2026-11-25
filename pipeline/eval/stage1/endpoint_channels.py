"""Bounded, endpoint-first transport of unchanged physical runtime rows."""
import json
import re
from pathlib import Path

from .action_links import physical_rows
from .protocol import sha

STATE_VERSION = 'whitebox-endpoint-channels.v1'
FULL_LOG_VERSION = 'whitebox-endpoint-channels.v2'
VERSION = 'whitebox-endpoint-channels.v3'
MULTICLIENT_VERSION = 'whitebox-endpoint-channels.v4'
BRACKET_VERSION = 'whitebox-endpoint-channels.v5'
WIDE_STATE_VERSION = 'whitebox-endpoint-channels.v6'
PRESTEP_VERSION = 'whitebox-endpoint-channels.v7'
LOSSLESS_LOG_VERSION = 'whitebox-endpoint-channels.v8'
COMPLETE_LOG_VERSION = 'whitebox-endpoint-channels.v9.complete-log'
LOG_WIRE_BYTE_LIMIT = 32000
LOG_RAW_BYTE_LIMIT = 64*1048576
WIDE_STATE_BYTE_LIMIT = 500000
WIDE_STATE_RAW_BYTE_LIMIT = 64*1048576
BYTE_LIMIT = 160000
ROW_LIMIT = 512


class EndpointCapacityError(ValueError):
    """A mandatory physical channel cannot fit the unchanged transport budget."""



# Match diagnostic messages and severity markers, rather than strings such as
# "error_count=0". Unity's unprefixed GUI warning is deliberately not an error.
ERROR = re.compile(r'\b(?:error|fatal|panic|crash(?:ed)?|assert(?:ion)?(?:failed)?)\b|'
                   r'\b\w*Exception\b|\b(?:LogError|LogException|LogAssertion)\b', re.I)
STACK = re.compile(r'^\s+\S|^\S+(?::|\.)[\w.<>]+\s*\(|'
                   r'^\(Filename:|^--- (?:End|inner)|^Rethrow as ')
WARNING = re.compile(r'^\s*(?:\[warning\]|warning\s*:|GUI Window tried to begin rendering)', re.I)


def error_lines(lines, start, stop):
    """Select original diagnostic rows and their adjacent native/managed stack.

    Never deduplicate, rewrite or renumber errors. A warning/info flood cannot
    consume the budget ahead of a later error. Ambiguous severity stays visible.
    """
    selected = {start, stop}  # Scope boundaries; these are not proof of success.
    heads = [n for n in range(start, stop+1)
             if ERROR.search(lines[n-1]) and not WARNING.search(lines[n-1])]
    for number in heads:
        selected.add(number)
        cursor = number+1
        while cursor <= stop and lines[cursor-1] and STACK.search(lines[cursor-1]):
            selected.add(cursor)
            cursor += 1
        # Debug.LogError may be the only explicit severity in a Unity block.
        # Keep its preceding message and stack too.
        if re.search(r'\b(?:LogError|LogException|LogAssertion)\b', lines[number-1]):
            cursor = number-1
            while cursor >= start and lines[cursor-1] and STACK.search(lines[cursor-1]):
                selected.add(cursor)
                cursor -= 1
            if cursor >= start and lines[cursor-1] and not WARNING.search(lines[cursor-1]):
                selected.add(cursor)
    return sorted(selected), heads



def multisession_log_scope(root):
    """Select both independent runtime scopes by immutable role/log index."""
    from .protocol import load_lines
    runtime=Path(root)/'runtime'
    log=runtime/'engine.log'
    lines=log.read_text(errors='replace').splitlines()
    index=load_lines(runtime/'log_index.jsonl')
    if len(index)!=len(lines): raise ValueError('Native log index does not cover canonical log')
    scopes, physical, delivered, heads = [], [], [], []
    for role in ('A','B'):
        numbers=[row['canonical_line'] for row in index if row['session_id']==role]
        if not numbers or numbers!=list(range(numbers[0],numbers[-1]+1)):
            raise ValueError('Native log role scope is missing or interleaved')
        starts=[n for n in numbers if '[GameFactory3APlayTest] entering Play Mode' in lines[n-1]]
        stops=[n for n in numbers if starts and n>=starts[0] and 'Input System module state changed to: Shutdown.' in lines[n-1]]
        if len(starts)!=1 or not stops: raise ValueError('Independent runtime log scope is incomplete: '+role)
        start,stop=starts[0],stops[0]
        selected,errors=error_lines(lines,start,stop)
        scopes.append({'session_id':role,'line_start':start,'line_end':stop,
                       'native_source':'sessions/'+role+'/player.log'})
        physical.extend(range(start,stop+1));delivered.extend(selected);heads.extend(errors)
    characters=sum(len(f'{n}: {lines[n-1]}\n') for n in delivered)
    if characters>16000: raise ValueError('Independent runtime error logs exceed frozen transport limit')
    return {'id':'ENGINE','path':'runtime/engine.log','session_scopes':scopes,
            'clock':'independent native log scopes; no cross-session time ordering',
            'complete':len(delivered)==len(physical),'filter':'errors-and-stacks.v1',
            'source_sha256':sha(log),'log_index_sha256':sha(runtime/'log_index.jsonl'),
            'characters':characters,'character_limit':16000,'scanned_physical_lines':len(physical),
            'error_detection_lines':heads,'all_detected_errors_delivered':True,
            'delivered_physical_lines':delivered,'omitted_physical_lines':sorted(set(physical)-set(delivered))}


# Reviewed source: the parameterless pre-step notification occurs immediately
# before Game.Step and contains no outcome/count payload. Other events remain
# substantive even if they share its name.
PRESTEP_SOURCE = 'Assets/CaravanMechanics/CaravanRuntimeAdapter.cs'
PRESTEP_SHA256 = 'b6755cd75f2dae554d083ecbad28402cb7a05787e19a2f93ad20ea83ce24bd95'


def prestep_source_proof(root):
    root = Path(root)
    source = root/'input/project'/PRESTEP_SOURCE
    manifest = root/'input_manifest.json'
    if not source.is_file() or not manifest.is_file():
        return {}
    frozen = json.loads(manifest.read_text()).get('snapshot_hashes', {})
    if frozen.get(PRESTEP_SOURCE) != PRESTEP_SHA256 or sha(source) != PRESTEP_SHA256:
        return {}
    return {'path': PRESTEP_SOURCE, 'sha256': PRESTEP_SHA256,
            'source': 'CaravanRuntimeAdapter', 'event': 'BeforeSimulationStep',
            'policy': 'Reviewed zero-argument notification before Game.Step; null payload only. Omitted notices prove no count, ordering or absence.'}


def _routine_event(row, *, allow_on_statechanged=False, prestep_source=None):
    """Only recorder heartbeats and successful input acknowledgments may be sampled."""
    payload = row.get('payload')
    if (prestep_source and row.get('event') == 'BeforeSimulationStep'
            and row.get('source') == prestep_source and row.get('clock') == 'recorder_session_monotonic'
            and payload is None):
        return ('BeforeSimulationStep', prestep_source)
    if (row.get('event') == 'StateChanged' or allow_on_statechanged and row.get('event') == 'OnStateChanged') and payload is None:
        return ('StateChanged',)
    if (row.get('event') == 'GameplayEvent' and isinstance(payload, dict)
            and payload.get('key') == 'input_accepted'
            and not ERROR.search(json.dumps(payload))):
        return ('input_accepted', payload.get('owner'), payload.get('subject'))
    return None


def _event_brackets(rows, lines, role, *, allow_on_statechanged=False, prestep_source=None):
    selected, routine = [], {}
    for line in lines:
        if line not in rows or rows[line].get('session_id') != role:
            raise ValueError('Required endpoint physical row is missing or belongs to another session: EVENT:'+str(line))
        key = _routine_event(rows[line], allow_on_statechanged=allow_on_statechanged, prestep_source=prestep_source)
        if key is None:
            selected.append(line)
        else:
            routine.setdefault(key, []).append(line)
    for values in routine.values():
        selected.extend(values[:1] + values[-1:])
    return sorted(set(selected))


def compact_omission_context(value):
    """Losslessly encode omitted physical line lists, never evidence or citations."""
    if isinstance(value, list):
        return [compact_omission_context(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        if key in {'missing_physical_lines', 'undelivered_event_lines',
                   'undelivered_state_lines', 'omitted_physical_lines'}:
            if not isinstance(item, list) or any(type(n) is not int for n in item):
                raise ValueError('Omission metadata requires physical integer line numbers')
            ranges = []
            for number in item:
                if ranges and number == ranges[-1][1]+1:
                    ranges[-1][1] = number
                else:
                    ranges.append([number, number])
            result[key+'_ranges'] = ranges
            result[key+'_count'] = len(item)
        else:
            result[key] = compact_omission_context(item)
    return result


def compact_line_lists(value):
    """Losslessly encode verbose physical-line metadata for judge transport.

    These lists describe the delivery boundary only; they are not evidence and
    are never used as citation IDs.  Inclusive ranges preserve every integer,
    including irregular gaps, while avoiding a megabyte-scale repeated list in
    the model request.
    """
    line_keys = {'delivered_physical_lines', 'error_detection_lines',
                 'missing_physical_lines', 'undelivered_event_lines',
                 'undelivered_state_lines', 'omitted_physical_lines'}
    if isinstance(value, list):
        return [compact_line_lists(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        if key in line_keys:
            if not isinstance(item, list) or any(type(n) is not int for n in item):
                raise ValueError('Line-list metadata requires physical integer line numbers')
            # Omission lists often contain a regular stride (for example a
            # repeated adapter block every 25 physical lines).  Inclusive
            # ranges preserve those rows, but can still expand to thousands
            # of range objects.  Encode arithmetic runs only when that is
            # smaller; the decoder below retains the old range format.
            ranges = []
            for number in item:
                if ranges and number == ranges[-1][1] + 1:
                    ranges[-1][1] = number
                else:
                    ranges.append([number, number])
            runs = []
            index = 0
            while index < len(item):
                end = index
                stride = item[index + 1] - item[index] if index + 1 < len(item) else 1
                while end + 1 < len(item) and item[end + 1] - item[end] == stride:
                    end += 1
                runs.append([item[index], item[end], stride])
                index = end + 1
            # Group equal-width ranges with an arithmetic start offset.
            # [first_start, first_end, stride, count] reconstructs count
            # inclusive ranges, retaining irregular gaps between groups.
            blocks = []
            index = 0
            while index < len(ranges):
                first, last = ranges[index]
                end = index
                stride = ranges[index + 1][0] - first if index + 1 < len(ranges) else 1
                while (end + 1 < len(ranges)
                       and ranges[end + 1][1] - ranges[end + 1][0] == last - first
                       and ranges[end + 1][0] - ranges[end][0] == stride):
                    end += 1
                blocks.append([first, last, stride, end - index + 1])
                index = end + 1
            ordered = all(a < b for a,b in zip(item,item[1:]))
            candidates = [('ranges', ranges)]
            if ordered:
                candidates += [('runs', runs), ('blocks', blocks)]
            if len(ranges) > 128 and ordered:
                from .lossless_log_grammar import encode_positions
                grammar = encode_positions([[first,last-first+1] for first,last in ranges])
                candidates.append(('grammar', grammar))
            encoding, encoded = min(candidates, key=lambda candidate:
                len(json.dumps(candidate[1], separators=(',', ':'))))
            result[key + '_' + encoding] = encoded
            result[key + '_count'] = len(item)
        else:
            result[key] = compact_line_lists(item)
    return result


def expand_line_ranges(value):
    """Test/audit helper proving the transport representation is reversible."""
    if isinstance(value, list):
        return [expand_line_ranges(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    consumed = set()
    for key, item in value.items():
        if key.endswith('_grammar') and key[:-8] + '_count' in value:
            from .lossless_log_grammar import decode_positions
            base = key[:-8]
            ranges = decode_positions(item, value[base+'_count'])
            result[base] = [n for first,count in ranges for n in range(first,first+count)]
            consumed.update({key, base+'_count'})
        elif key.endswith('_blocks') and key[:-7] + '_count' in value:
            base = key[:-7]
            expanded = []
            for first, last, stride, count in item:
                if (any(type(number) is not int for number in (first, last, stride, count))
                        or last < first or stride <= 0 or count <= 0):
                    raise ValueError('Invalid line-list arithmetic block')
                for index in range(count):
                    expanded.extend(range(first + index * stride, last + index * stride + 1))
            if len(expanded) != value[base + '_count']:
                raise ValueError('Line-list block/count mismatch')
            result[base] = expanded
            consumed.update({key, base + '_count'})
        elif key.endswith('_runs') and key[:-5] + '_count' in value:
            base = key[:-5]
            expanded = []
            for first, last, stride in item:
                if type(first) is not int or type(last) is not int or type(stride) is not int or stride <= 0:
                    raise ValueError('Invalid line-list arithmetic run')
                if last < first or (last - first) % stride:
                    raise ValueError('Line-list arithmetic run does not terminate exactly')
                expanded.extend(range(first, last + 1, stride))
            if len(expanded) != value[base + '_count']:
                raise ValueError('Line-list run/count mismatch')
            result[base] = expanded
            consumed.update({key, base + '_count'})
        elif key.endswith('_ranges') and key[:-7] + '_count' in value:
            base = key[:-7]
            expanded = []
            for start, end in item:
                expanded.extend(range(start, end + 1))
            if len(expanded) != value[base + '_count']:
                raise ValueError('Line-list range/count mismatch')
            result[base] = expanded
            consumed.update({key, base + '_count'})
        elif key not in consumed:
            result[key] = expand_line_ranges(item)
    return result


def compact_metadata_strings(context):
    """Dictionary encode repeated metadata strings; actual evidence stays verbatim."""
    from collections import Counter
    counts = Counter()
    def collect(value):
        if isinstance(value,str) and len(value)>=40: counts[value]+=1
        elif isinstance(value,list):
            for item in value: collect(item)
        elif isinstance(value,dict):
            for item in value.values(): collect(item)
    collect(context)
    strings = [text for text,count in counts.items() if count>1]
    indices = {text:index for index,text in enumerate(strings)}
    integer_runs_used = False
    def encode(value):
        nonlocal integer_runs_used
        if isinstance(value,str) and value in indices: return {'metadata_text_ref':indices[value]}
        if isinstance(value,list):
            if len(value) > 8 and all(type(number) is int for number in value):
                runs = []
                index = 0
                while index < len(value):
                    end = index
                    stride = value[index+1]-value[index] if index+1 < len(value) else 0
                    while end+1 < len(value) and value[end+1]-value[end] == stride:
                        end += 1
                    runs.append([value[index], stride, end-index+1])
                    index = end+1
                encoded = {'metadata_integer_runs': runs, 'value_count': len(value)}
                if len(json.dumps(encoded)) < len(json.dumps(value)):
                    integer_runs_used = True
                    return encoded
            if (len(value) > 8 and all(isinstance(row, list) and row for row in value)
                    and len({len(row) for row in value}) == 1
                    and all(type(number) is int for row in value for number in row)):
                columns = []
                for column in zip(*value):
                    runs = []
                    index = 0
                    while index < len(column):
                        end = index
                        stride = column[index+1]-column[index] if index+1 < len(column) else 0
                        while end+1 < len(column) and column[end+1]-column[end] == stride:
                            end += 1
                        runs.append([column[index], stride, end-index+1])
                        index = end+1
                    columns.append(runs)
                encoded = {'metadata_integer_columns': columns, 'row_count': len(value)}
                if len(json.dumps(encoded)) < len(json.dumps(value)):
                    return encoded
            if len(value)>1 and all(isinstance(item,dict) for item in value):
                schemas=[];schema_ids={};records=[]
                for item in value:
                    keys=tuple(item)
                    if keys not in schema_ids:
                        schema_ids[keys]=len(schemas);schemas.append(list(keys))
                    records.append([schema_ids[keys],[encode(v) for v in item.values()]])
                return {'metadata_record_keys':schemas,'metadata_records':records}
            return [encode(item) for item in value]
        if isinstance(value,dict): return {key:encode(item) for key,item in value.items()}
        return value
    encoded_context = encode(context)
    result = {'encoding':'whitebox-metadata-string-table.v1',
        'decode':'Replace each single-key metadata_text_ref object with the exact string at that index in metadata_strings. Only metadata is encoded; evidence and citation IDs in raw rows are unchanged.',
        'record_decode':'For each [schema_index,values] in metadata_records, zip metadata_record_keys[schema_index] with decoded values to reconstruct the original dictionary; record order is unchanged.',
        'integer_decode':'metadata_integer_columns holds columns of [first,stride,count] runs; expand each run as first+i*stride for i=0..count-1, then transpose columns into exactly row_count rows.',
        'metadata_strings':strings,'context':encoded_context}
    if integer_runs_used:
        result['encoding'] = 'whitebox-metadata-string-table.v2'
        result['integer_list_decode'] = ('metadata_integer_runs holds ordered [first,stride,count] runs; '
            'expand each run as first+i*stride for i=0..count-1 and concatenate to exactly value_count integers. '
            'Retain order, repetitions and original physical line numbers; never sort or deduplicate.')
    return result


def expand_metadata_strings(wire):
    # Reconstruct exact metadata; raw evidence and citation rules are separate.
    def decode(value):
        if isinstance(value, list):
            return [decode(item) for item in value]
        if not isinstance(value, dict):
            return value
        if set(value) == {'metadata_text_ref'}:
            return wire['metadata_strings'][value['metadata_text_ref']]
        if set(value) == {'metadata_integer_runs', 'value_count'}:
            count = value['value_count']
            runs = value['metadata_integer_runs']
            if (wire.get('encoding') != 'whitebox-metadata-string-table.v2'
                    or type(count) is not int or count < 0 or not isinstance(runs, list)):
                raise ValueError('Invalid metadata integer runs envelope')
            total = 0
            for run in runs:
                if (not isinstance(run, list) or len(run) != 3
                        or any(type(number) is not int for number in run) or run[2] <= 0):
                    raise ValueError('Invalid metadata integer run')
                total += run[2]
            if total != count:
                raise ValueError('Metadata integer run length mismatch')
            return [first+i*stride for first,stride,length in runs for i in range(length)]
        if set(value) == {'metadata_integer_columns', 'row_count'}:
            columns = [[first+i*stride for first,stride,count in runs for i in range(count)]
                       for runs in value['metadata_integer_columns']]
            if any(len(column) != value['row_count'] for column in columns):
                raise ValueError('Metadata integer column length mismatch')
            return [list(row) for row in zip(*columns)]
        if set(value) == {'metadata_record_keys', 'metadata_records'}:
            result = []
            for schema, values in value['metadata_records']:
                keys = value['metadata_record_keys'][schema]
                if len(keys) != len(values):
                    raise ValueError('Metadata record length mismatch')
                result.append(dict(zip(keys, map(decode, values))))
            return result
        return {key: decode(item) for key,item in value.items()}
    return decode(wire['context'])



def lossless_log_wire(path, selected):
    """Reversible text dictionary + arithmetic physical-line runs, not deduplication.

    Every selected occurrence and its original line number is reconstructed.
    Raw source bytes and all unselected rows remain in the immutable source log.
    """
    path = Path(path)
    if path.stat().st_size > LOG_RAW_BYTE_LIMIT:
        from .streamed_log_lines import IndexedLines
        lines = IndexedLines(path, LOG_RAW_BYTE_LIMIT)
    else:
        lines = path.read_text(errors='replace').splitlines()
    if (selected != sorted(set(selected)) or any(type(n) is not int or n < 1 or n > len(lines) for n in selected)):
        raise ValueError('Invalid lossless log physical lines')
    groups = {}
    for n in selected:
        groups.setdefault(lines[n-1], []).append(n)
    records = []
    for text, numbers in groups.items():
        runs = []; i = 0
        while i < len(numbers):
            j = i + 1
            stride = numbers[j]-numbers[i] if j < len(numbers) else 1
            while j+1 < len(numbers) and numbers[j+1]-numbers[j] == stride:
                j += 1
            end = min(j, len(numbers)-1)
            runs.append([numbers[i], numbers[end], stride]); i = end+1
        records.append([text, runs])
    wire = {'encoding':'exact-log-physical-runs.v1', 'source_sha256':sha(path),
        'decode':'For each [text,runs], expand every [first,last,stride] inclusively into (physical_line,text). Sort by physical_line. Every occurrence is retained, including repetitions. Cite ENGINE using original physical lines, not table indices. Omitted raw rows are not evidence of absence or normal execution.',
        'row_count':len(selected), 'records':records}
    if len(json.dumps(wire,ensure_ascii=False,separators=(',',':')).encode()) > LOG_WIRE_BYTE_LIMIT:
        # A repeated exception stack can have irregular physical gaps. Sharing
        # the exact contiguous block avoids repeating its position runs once per
        # stack line. No source occurrence, selected line, or error is removed.
        blocks = {}
        text = []
        first = previous = None
        for number in selected:
            if previous is not None and number != previous + 1:
                blocks.setdefault(tuple(text), []).append(first)
                text = []
                first = None
            if first is None:
                first = number
            text.append(lines[number-1])
            previous = number
        if text:
            blocks.setdefault(tuple(text), []).append(first)
        block_records = []
        for text, starts in blocks.items():
            runs = []
            i = 0
            while i < len(starts):
                j = i + 1
                stride = starts[j]-starts[i] if j < len(starts) else 1
                while j+1 < len(starts) and starts[j+1]-starts[j] == stride:
                    j += 1
                end = min(j, len(starts)-1)
                runs.append([starts[i], starts[end], stride])
                i = end+1
            block_records.append([list(text), runs])
        wire = {'encoding':'exact-log-physical-blocks.v1', 'source_sha256':sha(path),
            'decode':'For each [lines,start_runs], expand every [first,last,stride] inclusively into original physical block starts. For each start, emit (start+offset,lines[offset]) for every line in the block. Sort by physical_line. Every occurrence is retained, including repetitions and all stack lines. Cite ENGINE using original physical lines, not table indices. Omitted raw rows are not evidence of absence or normal execution.',
            'row_count':len(selected), 'records':block_records}
        if len(json.dumps(wire,ensure_ascii=False,separators=(',',':')).encode()) > LOG_WIRE_BYTE_LIMIT:
            from .lossless_log_grammar import encode
            wire = encode(lines, selected, sha(path))
            if len(json.dumps(wire,ensure_ascii=False,separators=(',',':')).encode()) > LOG_WIRE_BYTE_LIMIT:
                raise ValueError('Native runtime error log exceeds lossless wire limit; errors cannot be clipped')
    if decode_log_wire(wire) != [(n, lines[n-1]) for n in selected]:
        raise ValueError('Lossless log reconstruction differs from physical source')
    return wire


def decode_log_wire(wire):
    encoding = wire.get('encoding')
    if encoding in {'exact-log-physical-grammar.v1', 'exact-log-physical-grammar.v2'}:
        from .lossless_log_grammar import decode
        return decode(wire)
    if encoding not in {'exact-log-physical-runs.v1', 'exact-log-physical-blocks.v1'}:
        raise ValueError('Unknown log wire encoding')
    result = []
    for text, runs in wire['records']:
        lines = [text] if encoding == 'exact-log-physical-runs.v1' else text
        if not isinstance(lines,list) or not lines or any(not isinstance(line,str) for line in lines):
            raise ValueError('Invalid log physical block')
        for first, last, stride in runs:
            if any(type(n) is not int for n in (first,last,stride)) or first < 1 or last < first or stride < 1 or (last-first)%stride:
                raise ValueError('Invalid log physical run')
            result.extend((n+offset,line) for n in range(first,last+1,stride)
                          for offset,line in enumerate(lines))
    result.sort()
    if len(result) != wire['row_count'] or len({n for n,_ in result}) != len(result):
        raise ValueError('Duplicate or missing log physical occurrence')
    return result


def select(root, links, criterion_ids, contracts, *, version=BRACKET_VERSION, event_wire=False, extended_event_rows=False, event_encoding=None):
    if type(event_wire) is not bool:
        raise ValueError('EVENT wire opt-in must be boolean')
    if type(extended_event_rows) is not bool or (extended_event_rows and not event_wire):
        raise ValueError('Extended EVENT rows require exact wire transport')
    if version == COMPLETE_LOG_VERSION and event_wire:
        raise ValueError('EVENT wire requires full endpoint channels, not log-only transport')
    if version == COMPLETE_LOG_VERSION:
        return complete_runtime_log(root, links, criterion_ids, contracts)
    if version not in {STATE_VERSION, FULL_LOG_VERSION, VERSION, MULTICLIENT_VERSION, BRACKET_VERSION, WIDE_STATE_VERSION, PRESTEP_VERSION, LOSSLESS_LOG_VERSION}:
        raise ValueError('Unknown endpoint channel transport version')
    root = Path(root)
    multi = (root/'runtime/multisession_index.json').is_file()
    if multi and version in {VERSION, BRACKET_VERSION, WIDE_STATE_VERSION, PRESTEP_VERSION, LOSSLESS_LOG_VERSION}:
        version = MULTICLIENT_VERSION
    if version == MULTICLIENT_VERSION and not multi:
        raise ValueError('Role-local endpoint transport requires native multisession evidence')
    prestep = prestep_source_proof(root) if version in {PRESTEP_VERSION, LOSSLESS_LOG_VERSION} else {}
    prestep_source = prestep.get('source')
    identifiers = set(criterion_ids)
    scoped = [row for row in links['links'] if identifiers.intersection(row.get('criterion_ids', []))]
    if not scoped:
        scoped = links['links']
    channels = {name:dict(physical_rows(root/'runtime'/filename)) for name,filename in
                [('ACTION','actions.jsonl'),('STATE','state_trace.jsonl'),('EVENT','event_trace.jsonl')]}
    frames = dict(physical_rows(root/'runtime/frame_index.jsonl'))
    frame_times = {row.get('frame_id', f'FRAME:{line:05d}'):row['t_ms'] for line,row in frames.items()}
    required = {name:[] for name in channels}
    bindings = {}
    for ident, contract in contracts.items():
        last = contract['last_action']
        required['ACTION'].extend(last.get('action_lines') or [])
        events = list(last.get('events') or [])
        states = list(last.get('states') or [])
        if version == MULTICLIENT_VERSION:
            role = contract.get('client_role')
            if role not in {'A','B'} or last.get('session_id') != role:
                raise ValueError('Endpoint state brackets lack their physical session')
            for line in states:
                if line not in channels['STATE'] or channels['STATE'][line].get('session_id') != role:
                    raise ValueError('Required endpoint physical row is missing or belongs to another session: STATE:'+str(line))
            # Keep the action's original before/after samples and endpoint brackets.
            # The full source list remains in contracts and raw action links; optional
            # intervening samples and their omitted physical lines are audited below.
            states = states[:1] + states[-1:]
            events = _event_brackets(channels['EVENT'], events, role)
        if version in {BRACKET_VERSION, WIDE_STATE_VERSION, PRESTEP_VERSION, LOSSLESS_LOG_VERSION}:
            # A hold can span hundreds of state samples. Its original before/after
            # rows and the endpoint brackets are mandatory; intermediate rows
            # remain in raw files and are delivered opportunistically with exact
            # omitted-line records. Missing physical sources still fail closed.
            if any(line not in channels['STATE'] for line in states):
                raise ValueError('Required endpoint physical row is missing: STATE')
            states = states[:1] + states[-1:]
        if version in {WIDE_STATE_VERSION, PRESTEP_VERSION, LOSSLESS_LOG_VERSION}:
            # Null-payload change notifications cannot prove values or counts.
            # Keep their real boundary rows and every substantive event instead
            # of filling a packet with a per-update notification flood.
            events = _event_brackets(channels['EVENT'], events, None, allow_on_statechanged=True, prestep_source=prestep_source)
        if contract['reachability'] == 'EXECUTABLE':
            for frame in contract['frame_ids']:
                when = frame_times[frame]
                before = [line for line,row in channels['STATE'].items() if row['t_ms'] <= when
                          and (not contract.get('client_role') or row.get('session_id') == contract['client_role'])]
                after = [line for line,row in channels['STATE'].items() if row['t_ms'] >= when
                         and (not contract.get('client_role') or row.get('session_id') == contract['client_role'])]
                states.extend(before[-1:] + after[:1])
        states = list(dict.fromkeys(states))
        required['STATE'].extend(states)
        required['EVENT'].extend(events)
        bindings[ident] = {'last_action_id':contract['last_action_id'], 'state_lines':sorted(states),
                           'action_lines':last.get('action_lines') or [], 'event_lines':events}
    if version in {MULTICLIENT_VERSION, WIDE_STATE_VERSION, PRESTEP_VERSION, LOSSLESS_LOG_VERSION}:
        # Gameplay transitions and rejections in the entire scoped route take
        # priority over heartbeat floods, including events before the last action.
        for link in scoped:
            validated = _event_brackets(channels['EVENT'], link['events'], link.get('session_id'),
                allow_on_statechanged=version in {WIDE_STATE_VERSION, PRESTEP_VERSION, LOSSLESS_LOG_VERSION}, prestep_source=prestep_source)
            required['EVENT'].extend(line for line in validated
                if _routine_event(channels['EVENT'][line], allow_on_statechanged=version in {WIDE_STATE_VERSION, PRESTEP_VERSION, LOSSLESS_LOG_VERSION}, prestep_source=prestep_source) is None)
    selection, clipping = {}, []
    for name, field in [('ACTION','action_lines'),('STATE','states'),('EVENT','events')]:
        rows = channels[name]
        selected, selected_set, used = [], set(), 0
        wide_state = name == 'STATE' and version in {WIDE_STATE_VERSION, PRESTEP_VERSION, LOSSLESS_LOG_VERSION}
        wide_event = name == 'EVENT' and event_wire
        byte_limit = WIDE_STATE_RAW_BYTE_LIMIT if (wide_state or wide_event) else BYTE_LIMIT

        def append(line, mandatory=False):
            nonlocal used
            if line in selected_set:
                return
            if line not in rows:
                if mandatory:
                    raise ValueError('Required endpoint physical row is missing: '+name+':'+str(line))
                return
            size = len(json.dumps(rows[line], ensure_ascii=False).encode())
            if used+size > byte_limit or (not (wide_event and extended_event_rows) and len(selected) >= ROW_LIMIT):
                if mandatory:
                    raise EndpointCapacityError('Endpoint physical rows exceed bounded transport: '+name+f' (bytes={used+size}, rows={len(selected)+1}, line={line})')
                return
            selected.append(line)
            selected_set.add(line)
            used += size

        for line in dict.fromkeys(required[name]):
            append(line, mandatory=True)
        mandatory_lines = set(selected)
        # Reserve raw-memory headroom for optional rows without letting a wide
        # observer's intermediate samples dominate an otherwise compact packet.
        if wide_state:
            byte_limit = min(WIDE_STATE_RAW_BYTE_LIMIT, used+1048576)
        for link in scoped:
            values = link[field]
            for line in values[:1] + values[-1:]:
                append(line)
        physical = list(rows)
        for index in range(min(24,len(physical))):
            append(physical[round(index*(len(physical)-1)/max(1,min(24,len(physical))-1))])
        for index in range(max([len(link[field]) for link in scoped] or [0])):
            for link in scoped:
                if index < len(link[field]):
                    append(link[field][index])
        if wide_state:
            from .batch import compact_state_samples
            def wire_size():
                samples = [dict(rows[line], line=line) for line in sorted(selected)]
                return len(json.dumps(compact_state_samples(samples),
                    ensure_ascii=False, separators=(',', ':')).encode())
            # Check the exact same lossless encoding delivered in batch.packet.
            # All mandatory physical brackets remain; only optional rows can go.
            encoded_bytes = wire_size()
            optional = [line for line in reversed(selected) if line not in mandatory_lines]
            while encoded_bytes > WIDE_STATE_BYTE_LIMIT and optional:
                selected.remove(optional.pop(0))
                encoded_bytes = wire_size()
            if encoded_bytes > WIDE_STATE_BYTE_LIMIT:
                raise ValueError('Endpoint lossless state packet exceeds bounded transport: '
                    f'STATE (encoded_bytes={encoded_bytes}, rows={len(selected)})')
        if wide_event:
            from .event_wire import encode as encode_event, binding as event_binding
            # Every original row is counted and cited, never a packed-row substitution.
            # Only the explicit authorized EVENT policy removes its cumulative cap.
            # Only EVENT wire bytes replace its verbose JSON serialization bytes.
            event_path = root/'runtime/event_trace.jsonl'
            def event_size():
                return event_binding(encode_event(event_path, sorted(selected),
                    **({'encoding': event_encoding} if event_encoding is not None else {})))
            event_delivery = event_size()
            optional = [line for line in reversed(selected) if line not in mandatory_lines]
            while event_delivery['wire_bytes'] > BYTE_LIMIT and optional:
                selected.remove(optional.pop(0))
                event_delivery = event_size()
            if event_delivery['wire_bytes'] > BYTE_LIMIT:
                raise EndpointCapacityError('Endpoint lossless EVENT packet exceeds bounded transport: '
                    f"EVENT (encoded_bytes={event_delivery['wire_bytes']}, rows={len(selected)})")
        selection[name] = sorted(selected)
        # Optional capacity handling above can remove selected rows; construct a
        # fresh membership view here so omissions retain their original order
        # and exact physical lines without a quadratic list lookup.
        delivered_lines = set(selected)
        for link in scoped:
            missing = [line for line in link[field] if line not in delivered_lines]
            if missing:
                clipping.append({'channel':name, 'action_id':link['action_id'],
                    'criterion_ids':link.get('criterion_ids', []), 'missing_physical_lines':missing,
                    'reason':'Bounded endpoint-first transport; required endpoint rows are never clipped.'})
    transport = {'version':version, 'byte_limit':BYTE_LIMIT, 'row_limit':ROW_LIMIT,
                 'endpoint_bindings':bindings}
    if extended_event_rows:
        from .event_wire import ROW_POLICY_FIELD, ROW_POLICY_VERSION
        transport[ROW_POLICY_FIELD] = ROW_POLICY_VERSION
    if event_wire:
        transport['event_wire_transport'] = event_delivery
    if version in {WIDE_STATE_VERSION, PRESTEP_VERSION, LOSSLESS_LOG_VERSION}:
        transport.update(state_byte_limit=WIDE_STATE_BYTE_LIMIT,
            state_raw_byte_limit=WIDE_STATE_RAW_BYTE_LIMIT,
            state_encoded_bytes=encoded_bytes,
            state_wire_policy='Unchanged physical rows bounded by exact lossless state wire bytes; 64 MiB raw-memory limit. Prior versions retain their original limits.',
            routine_event_policy='Null-payload StateChanged/OnStateChanged and successful input acknowledgments use real boundary rows; all substantive scoped events retained. Omitted rows never prove counts/order/absence.')
    if version in {BRACKET_VERSION, WIDE_STATE_VERSION, PRESTEP_VERSION, LOSSLESS_LOG_VERSION}:
        transport['required_state_policy'] = 'action-before-after-and-endpoint-brackets.v1'
        transport['intermediate_states'] = 'Optional unchanged physical rows; omitted lines are recorded, never runtime absence or proof of unobserved counts/order.'
    if version in {PRESTEP_VERSION, LOSSLESS_LOG_VERSION}:
        transport['prestep_source_proof'] = prestep
        transport['routine_event_policy'] += ' Source-bound zero-argument pre-simulation notices also retain physical boundary rows; all substantive events are retained.'
    log = root/'runtime/engine.log'
    if (version in {VERSION, MULTICLIENT_VERSION, BRACKET_VERSION, WIDE_STATE_VERSION, PRESTEP_VERSION, LOSSLESS_LOG_VERSION} or version == FULL_LOG_VERSION and contracts) and log.is_file():
        lines = log.read_text(errors='replace').splitlines()
        starts = [number for number,line in enumerate(lines,1) if '[GameFactory3APlayTest] entering Play Mode' in line]
        if (root/'runtime/multisession_index.json').is_file():
            if version not in {VERSION, MULTICLIENT_VERSION, BRACKET_VERSION, WIDE_STATE_VERSION, PRESTEP_VERSION, LOSSLESS_LOG_VERSION}: raise ValueError('Independent native logs require endpoint channels v3')
            scope=multisession_log_scope(root)
            selection['ENGINE']=scope['delivered_physical_lines']
            transport['runtime_log_scope']=scope
            clipping.append({'channel':'ENGINE','action_id':None,'criterion_ids':sorted(identifiers),
                'missing_physical_lines':scope['omitted_physical_lines'],'runtime_log_scope':scope,
                'reason':'Both role-local native runtime scopes checked for errors and stacks; raw logs retained.'})
            starts=[]
        if starts:
            stops = [number for number,line in enumerate(lines,1) if number >= starts[0]
                     and 'Input System module state changed to: Shutdown.' in line]
            if len(starts) != 1 or not stops:
                raise ValueError('Native runtime log scope is ambiguous or incomplete')
            physical = list(range(starts[0],stops[0]+1))
            delivered, heads = (error_lines(lines, physical[0], physical[-1])
                                if version in {VERSION, MULTICLIENT_VERSION, BRACKET_VERSION, WIDE_STATE_VERSION, PRESTEP_VERSION, LOSSLESS_LOG_VERSION} else (physical, []))
            characters = sum(len(f'{number}: {lines[number-1]}\n') for number in delivered)
            if characters > 16000 and version != LOSSLESS_LOG_VERSION:
                raise ValueError('Complete native runtime log exceeds frozen per-file transport limit'
                                 if version == FULL_LOG_VERSION else
                                 'Native runtime error log exceeds per-file transport limit; errors cannot be clipped')
            wire = lossless_log_wire(log, delivered) if version == LOSSLESS_LOG_VERSION else None
            selection['ENGINE'] = delivered
            transport['runtime_log_scope'] = {'id':'ENGINE','path':'runtime/engine.log',
                'line_start':physical[0],'line_end':physical[-1],'complete':True,
                'characters':characters,'character_limit':16000}
            if version in {VERSION, MULTICLIENT_VERSION, BRACKET_VERSION, WIDE_STATE_VERSION, PRESTEP_VERSION, LOSSLESS_LOG_VERSION}:
                missing = sorted(set(physical)-set(delivered))
                transport['runtime_log_scope'].update(
                    complete=not missing, filter='errors-and-stacks.v1',
                    source_sha256=sha(log), scanned_physical_lines=len(physical),
                    error_detection_lines=heads, all_detected_errors_delivered=True,
                    delivered_physical_lines=delivered, omitted_physical_lines=missing)
                if wire is not None:
                    transport['runtime_log_scope'].update(wire_version=wire['encoding'], wire_bytes=len(json.dumps(wire,ensure_ascii=False,separators=(',',':')).encode()), wire_byte_limit=LOG_WIRE_BYTE_LIMIT)
                clipping.append({'channel':'ENGINE', 'action_id':None, 'criterion_ids':sorted(identifiers),
                    'missing_physical_lines':missing, 'runtime_log_scope':transport['runtime_log_scope'],
                    'reason':'Error/exception/assert/crash messages and adjacent stacks plus scope boundaries only. '
                             'Warnings and informational rows are omitted from the judge packet; full raw log is retained. '
                             'No detected error is not proof of gameplay success or of warning-free execution.'})
    return {'delivered_channel_lines':selection, 'channel_clipping':clipping,
            'scoped_action_ids':[row['action_id'] for row in scoped],
            'channel_transport':transport}


def complete_runtime_log(root, links, criterion_ids, contracts):
    """Deliver every unchanged physical runtime log row under the existing wire cap.

    v8 retains its original error-only selection. v9 changes only ENGINE delivery:
    no state/event conversion, gameplay inference, image or citation rule change.
    """
    root = Path(root)
    if (root/'runtime/multisession_index.json').exists():
        raise ValueError('Complete log delivery requires a single qualified native session')
    result = select(root, links, criterion_ids, contracts, version=LOSSLESS_LOG_VERSION)
    transport = result['channel_transport']
    scope = transport.get('runtime_log_scope')
    if not scope:
        raise ValueError('Complete native runtime log scope is unavailable')
    physical = list(range(scope['line_start'], scope['line_end']+1))
    log = root/'runtime/engine.log'
    wire = lossless_log_wire(log, physical)  # Same 32k wire /64MiB raw hard limits.
    lines = log.read_text(errors='replace').splitlines()
    scope.update(complete=True, filter='complete-runtime-lossless.v1',
        characters=sum(len(f'{n}: {lines[n-1]}\n') for n in physical),
        delivered_physical_lines=physical, omitted_physical_lines=[],
        wire_version=wire['encoding'],
        wire_bytes=len(json.dumps(wire,ensure_ascii=False,separators=(',',':')).encode()),
        wire_byte_limit=LOG_WIRE_BYTE_LIMIT)
    result['delivered_channel_lines']['ENGINE'] = physical
    transport['version'] = COMPLETE_LOG_VERSION
    for row in result['channel_clipping']:
        if row['channel'] == 'ENGINE':
            row.update(missing_physical_lines=[], runtime_log_scope=scope,
                reason='Complete unchanged native runtime log scope delivered losslessly, including all errors, warnings, informational rows and stacks. No log row is converted into state/event or inferred success.')
    return result


def checked_complete_log_screen(root, subset, items, criterion_id):
    """Validate the error-screen component of a complete raw log, never success."""
    transport = subset.get('channel_transport', {})
    scope = transport.get('runtime_log_scope', {})
    if (criterion_id not in transport.get('endpoint_bindings', {})
            or scope.get('filter') != 'complete-runtime-lossless.v1'
            or scope.get('complete') is not True
            or scope.get('all_detected_errors_delivered') is not True
            or scope.get('error_detection_lines') != []):
        return False
    item = next((i for i in items if i['id'] == 'ENGINE'), None)
    if not item or item['type'] != 'log' or item['path'] != 'runtime/engine.log':
        return False
    log = Path(root)/item['path']
    if not log.is_file() or sha(log) != item['sha256'] or sha(log) != scope.get('source_sha256'):
        return False
    lines = log.read_text(errors='replace').splitlines()
    starts = [n for n,line in enumerate(lines,1) if '[GameFactory3APlayTest] entering Play Mode' in line]
    stops = [n for n,line in enumerate(lines,1) if starts and n >= starts[0] and 'Input System module state changed to: Shutdown.' in line]
    if len(starts) != 1 or not stops:
        return False
    first,last = starts[0],stops[0]
    physical = list(range(first,last+1))
    if (scope.get('line_start') != first or scope.get('line_end') != last
            or scope.get('scanned_physical_lines') != len(physical)
            or scope.get('delivered_physical_lines') != physical
            or scope.get('omitted_physical_lines') != []
            or subset.get('delivered_channel_lines',{}).get('ENGINE') != physical
            or error_lines(lines,first,last)[1]):
        return False
    try:
        wire = lossless_log_wire(log,physical)
    except (OSError,ValueError,KeyError,TypeError):
        return False
    return (scope.get('wire_version') == wire['encoding']
        and scope.get('wire_bytes') == len(json.dumps(wire,ensure_ascii=False,separators=(',',':')).encode())
        and scope.get('wire_byte_limit') == LOG_WIRE_BYTE_LIMIT)


def checked_error_screen(root, manifest, criterion_id):
    """Validate a delivered, empty error screen without inventing a log citation.

    This proves only the error-screen component. Real action and changing
    gameplay evidence, plus the judge's NORMAL verdict, remain mandatory.
    """
    root = Path(root)
    for subset in manifest.get('evidence_sets', {}).values():
        if subset.get('channel_transport',{}).get('version') == COMPLETE_LOG_VERSION:
            if checked_complete_log_screen(root,subset,manifest['items'],criterion_id):
                return True
            continue
        transport = subset.get('channel_transport', {})
        scope = transport.get('runtime_log_scope', {})
        if (transport.get('version') not in {VERSION, MULTICLIENT_VERSION, BRACKET_VERSION, WIDE_STATE_VERSION, PRESTEP_VERSION, LOSSLESS_LOG_VERSION}
                or criterion_id not in transport.get('endpoint_bindings', {})
                or scope.get('filter') != 'errors-and-stacks.v1'
                or scope.get('all_detected_errors_delivered') is not True
                or scope.get('error_detection_lines') != []):
            continue
        item = next((item for item in manifest['items'] if item['id'] == scope.get('id')), None)
        if item is None or item['type'] != 'log' or item['path'] != 'runtime/engine.log':
            continue
        log = root/item['path']
        if not log.is_file() or sha(log) != item['sha256'] or sha(log) != scope.get('source_sha256'):
            continue
        if scope.get('session_scopes'):
            try:expected=multisession_log_scope(root)
            except (OSError,ValueError,KeyError,TypeError):continue
            if (scope==expected and not expected['error_detection_lines']
                    and expected['delivered_physical_lines']==subset.get('delivered_channel_lines',{}).get(item['id'])):
                return True
            continue
        lines = log.read_text(errors='replace').splitlines()
        starts = [n for n, line in enumerate(lines, 1) if '[GameFactory3APlayTest] entering Play Mode' in line]
        stops = [n for n, line in enumerate(lines, 1) if starts and n >= starts[0]
                 and 'Input System module state changed to: Shutdown.' in line]
        if len(starts) != 1 or not stops:
            continue
        start, stop = starts[0], stops[0]
        if (scope.get('line_start') != start or scope.get('line_end') != stop
                or scope.get('scanned_physical_lines') != stop-start+1):
            continue
        delivered, errors = error_lines(lines, start, stop)
        if (errors or delivered != scope.get('delivered_physical_lines')
                or delivered != subset.get('delivered_channel_lines', {}).get(item['id'])):
            continue
        return True
    return False
