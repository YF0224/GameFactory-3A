"""Exact lexical tables and transparent integer streams for opt-in EVENT v3.

No binary compressor, rounding, evidence selection or inferred state. Every
relation is chosen only after matching every original literal; the caller proves
complete original UTF-8 expansion. Integer arithmetic is unbounded and exact.
"""
from collections import Counter
from decimal import Decimal, localcontext, ROUND_DOWN
import json
import re

ALPHABET = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_'
DIGITS = re.compile(r'[0-9]+')
FINITE = re.compile(r'(-?)(0|[1-9][0-9]*)(?:\.([0-9]+))?')

DESCRIPTION = (
    'Exact lexical tables v3. Reconstruct each occurrence by interleaving fragments '
    'with expanded columns, then sort by original physical line_runs (inclusive). '
    'Cite only original EVENT physical lines, never table indices. All names, roles, '
    'payloads, timestamps, repetitions, failures, whitespace and newlines are unchanged. '
    'Only listed physical lines are delivered; omissions never prove absence. '
    'All arithmetic below is exact integer/decimal arithmetic, never binary float. '
    'values lists original literal strings; constant repeats; runs are [literal,count]. '
    'dictionary expands recursively to a table; indices selects zero-based entries. '
    'integer expands integer codec and spells base-10. padded_digits additionally '
    'left-pads with zeros to widths. canonical_scaled_decimal divides integer numerators '
    'by 10^scale, emits ordinary decimal with no redundant fractional trailing zeros, '
    'then literal_overrides [zero-based-position,original-literal] replaces spellings. '
    'exact_decimal_base recursively expands a base then applies literal_overrides; '
    'overrides preserve every exceptional digit, negative zero and decimal spelling. '
    'lexical_template interleaves its fragments with recursive columns; '
    'grouped_lexical_templates expands each {fragments,count,columns} separately; '
    'indices consumes the next occurrence of the selected group. '
    'same_column aliases an exactly equal column. decimal_offset_column adds the '
    'corresponding offsets to the referenced column using exact Decimal addition. '
    'floor_decimal_column truncates the referenced decimal toward zero and adds '
    'integer_residuals. exact_key_columns forms literal tuple keys from referenced '
    'columns, optionally taking the original substring before prefix_before; '
    'first_occurrence_values maps unique keys in first-occurrence order to exact '
    'literal values. References are zero-based columns within the same template, '
    'acyclic; they describe exact literal equality, not new observations or clocks. '
    'Integer codecs: int_stream expands a stream; int_blocks partitions the flat '
    'dictionary into blocks of int_blocks integers, selects blocks by stream indices '
    'and appends stream tail. difference_order 0/1/2 applies that many cumulative '
    'sums starting from zero. delta_runs repeats [signed-delta,count], then cumulatively '
    'sums. radix64_groups stores concatenated unsigned base-64 magnitudes grouped '
    'by digit widths; widths is an integer codec in original sequence order. '
    'Consume width digits from that group per occurrence; negative_positions is '
    'a stream of zero-based negative indices; then apply difference_order. '
    'Base-64 alphabet is 0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_. '
    'Streams: empty=true yields []; constant_int repeats count times; vlq uses '
    'signed zigzag (n>=0 ->2n, n<0 ->-2n-1), least-significant five-bit digits first, '
    'alphabet indices 32..63 mean continuation with value index-32, 0..31 terminate. '
    'run_values/run_counts are VLQ strings paired as runs. default repeats count times; '
    'position_gaps (VLQ, cumulative starting at -1) locates exceptions (VLQ). '
    'Every count, index, spelling, physical line and expanded selected SHA is checked. '
    'Encoding does not alter evidence sufficiency, citation rules or byte limits.')


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def size(value):
    return len(dumps(value).encode('utf-8'))


def check(ok, message='Invalid exact EVENT numeric encoding'):
    if not ok:
        raise ValueError(message)


def runs(values):
    result = []
    for value in values:
        if result and result[-1][0] == value:
            result[-1][1] += 1
        else:
            result.append([value, 1])
    return result


def vlq(values):
    result = []
    for value in values:
        value = value*2 if value >= 0 else -value*2-1
        while value >= 32:
            result.append(ALPHABET[32 + value % 32])
            value //= 32
        result.append(ALPHABET[value])
    return ''.join(result)


def unvlq(text, limit):
    check(isinstance(text, str))
    result, value, shift = [], 0, 0
    for char in text:
        check(char in ALPHABET)
        digit = ALPHABET.index(char)
        value += (digit % 32) << shift
        if digit >= 32:
            shift += 5
        else:
            result.append(value//2 if value % 2 == 0 else -(value+1)//2)
            check(len(result) <= limit)
            value, shift = 0, 0
    check(shift == 0, 'Truncated EVENT VLQ')
    return result


def stream(values):
    if not values:
        return {'empty': True}
    if len(set(values)) == 1:
        return {'constant_int': values[0], 'count': len(values)}
    options = [{'vlq': vlq(values)}]
    default = Counter(values).most_common(1)[0][0]
    positions, exceptions, last = [], [], -1
    for index, value in enumerate(values):
        if value != default:
            positions.append(index-last)
            exceptions.append(value)
            last = index
    options.append({'default': default, 'count': len(values),
                    'position_gaps': vlq(positions), 'exceptions': vlq(exceptions)})
    rr = runs(values)
    options.append({'run_values': vlq([v for v, n in rr]),
                    'run_counts': vlq([n for v, n in rr])})
    return min(options, key=size)


def unstream(spec, limit):
    check(isinstance(spec, dict))
    keys = set(spec)
    if keys == {'empty'}:
        check(spec['empty'] is True)
        return []
    if keys == {'vlq'}:
        return unvlq(spec['vlq'], limit)
    if keys in ({'constant_int', 'count'}, {'default', 'count', 'position_gaps', 'exceptions'}):
        count = spec['count']
        check(type(count) is int and 0 <= count <= limit)
        value = spec.get('constant_int', spec.get('default'))
        check(type(value) is int)
        result = [value]*count
        if 'default' in spec:
            gaps = unvlq(spec['position_gaps'], count)
            vals = unvlq(spec['exceptions'], count)
            check(len(gaps) == len(vals))
            index = -1
            for gap, value in zip(gaps, vals):
                index += gap
                check(gap > 0 and 0 <= index < count)
                result[index] = value
        return result
    check(keys == {'run_values', 'run_counts'})
    vals, counts = unvlq(spec['run_values'], limit), unvlq(spec['run_counts'], limit)
    check(len(vals) == len(counts) and all(c > 0 for c in counts) and sum(counts) <= limit)
    return [v for v, count in zip(vals, counts) for _ in range(count)]


def differences(values):
    return [values[0]] + [b-a for a, b in zip(values, values[1:])]


def radix(value):
    result = ''
    while value:
        value, digit = divmod(value, 64)
        result = ALPHABET[digit]+result
    return result or '0'


def integers(values, *, allow_radix=True):
    if not values:
        return {'int_stream': {'empty': True}, 'difference_order': 0}
    deltas = differences(values)
    options = [{'delta_runs': runs(deltas)}]
    arr = values
    for order in range(3):
        if order:
            arr = differences(arr)
        options.append({'int_stream': stream(arr), 'difference_order': order})
        for width in (2, 4, 8, 16):
            blocks = [tuple(arr[i:i+width]) for i in range(0, len(arr)-width+1, width)]
            table = list(dict.fromkeys(blocks))
            if not blocks or len(table) > len(blocks)*0.7:
                continue
            lookup = {block: i for i, block in enumerate(table)}
            options.append({'int_blocks': width, 'difference_order': order,
                'dictionary': stream([x for block in table for x in block]),
                'indices': stream([lookup[b] for b in blocks]),
                'tail': stream(arr[len(blocks)*width:])})
        if allow_radix:
            texts = [radix(abs(v)) for v in arr]
            widths = [len(s) for s in texts]
            groups = {}
            for width, text in zip(widths, texts):
                groups.setdefault(str(width), []).append(text)
            options.append({'radix64_groups': {k: ''.join(v) for k, v in groups.items()},
                'widths': integers(widths, allow_radix=False),
                'negative_positions': stream([i for i, v in enumerate(arr) if v < 0]),
                'difference_order': order})
    return min(options, key=size)


def integer_values(spec, count, depth=0):
    check(depth < 20 and isinstance(spec, dict))
    keys, order = set(spec), spec.get('difference_order', 0)
    check(type(count) is int and count >= 0 and type(order) is int and order in (0, 1, 2))
    if keys == {'delta_runs'}:
        result = []
        for run in spec['delta_runs']:
            check(isinstance(run, list) and len(run) == 2)
            value, repeats = run
            check(type(value) is int and type(repeats) is int and 0 < repeats <= count-len(result))
            result.extend([value]*repeats)
        order = 1
    elif keys == {'int_stream', 'difference_order'}:
        result = unstream(spec['int_stream'], count)
    elif keys == {'int_blocks', 'difference_order', 'dictionary', 'indices', 'tail'}:
        width = spec['int_blocks']
        check(type(width) is int and width in (2, 4, 8, 16))
        flat = unstream(spec['dictionary'], count)
        check(len(flat) % width == 0)
        table = [flat[i:i+width] for i in range(0, len(flat), width)]
        indices = unstream(spec['indices'], count//width)
        check(all(0 <= i < len(table) for i in indices))
        result = [v for i in indices for v in table[i]] + unstream(spec['tail'], width-1)
    elif keys == {'radix64_groups', 'widths', 'negative_positions', 'difference_order'}:
        groups = spec['radix64_groups']
        check(isinstance(groups, dict) and all(isinstance(v, str) for v in groups.values()))
        widths = integer_values(spec['widths'], count, depth+1)
        positions = unstream(spec['negative_positions'], count)
        check(positions == sorted(set(positions)) and all(0 <= p < count for p in positions))
        negative, cursors, result = set(positions), {k: 0 for k in groups}, []
        for i, width in enumerate(widths):
            key = str(width)
            check(type(width) is int and width > 0 and key in groups)
            start = cursors[key]
            text = groups[key][start:start+width]
            check(len(text) == width and all(ch in ALPHABET for ch in text))
            value = 0
            for char in text:
                value = value*64+ALPHABET.index(char)
            result.append(-value if i in negative else value)
            cursors[key] += width
        check(all(cursors[k] == len(v) for k, v in groups.items()))
    else:
        raise ValueError('Unknown EVENT integer codec')
    check(len(result) == count and all(type(v) is int for v in result))
    for _ in range(order):
        total, expanded = 0, []
        for value in result:
            total += value
            expanded.append(total)
        result = expanded
    return result


def decimal_spelling(value, scale):
    digits = str(abs(value)).zfill(scale+1)
    spelling = ('-' if value < 0 else '') + (digits[:-scale]+'.'+digits[-scale:] if scale else digits)
    return spelling.rstrip('0').rstrip('.') if scale else spelling


def numeric_column(values, scale):
    # Truncation is only a base representation; every different original literal
    # is retained below as an override, including all exceptional precision.
    nums = []
    for value in values:
        match = FINITE.fullmatch(value)
        frac = (match[3] or '')[:scale].ljust(scale, '0')
        nums.append(int(match[1]+match[2]+frac))
    canonical = [decimal_spelling(n, scale) for n in nums]
    return {'canonical_scaled_decimal': {'scale': scale, 'integers': integers(nums)},
            'literal_overrides': [[i, v] for i, (v, normal) in enumerate(zip(values, canonical)) if v != normal]}


def column(values, level=0):
    if not values:
        return {'values': []}
    if len(set(values)) == 1:
        return {'constant': values[0]}
    options = [{'values': values}, {'runs': runs(values)}]
    matches = [FINITE.fullmatch(v) for v in values]
    finite = all(matches)
    table = list(dict.fromkeys(values))
    # Repeated decimal observations use one exact literal table. Do not spend
    # repeated full-stream numeric/template searches on identical spellings.
    if finite and level < 3 and len(table) < len(values)*0.8 and any('.' in v for v in values):
        lookup = {v: i for i, v in enumerate(table)}
        return {'dictionary': column(table, level+1),
                'indices': integers([lookup[v] for v in values])}
    if finite:
        widths = [len(m[3] or '') for m in matches]
        scale = max(widths)
        options.append(numeric_column(values, scale))
        percentile = sorted(widths)[int(len(widths)*0.99)]
        if percentile < scale:
            options.append(numeric_column(values, percentile))
        if all(DIGITS.fullmatch(v) for v in values):
            options.append({'padded_digits': integers([int(v) for v in values]),
                            'widths': integers([len(v) for v in values])})
        if all(str(int(v)) == v for v in values if '.' not in v) and all('.' not in v for v in values):
            options.append({'integer': integers([int(v) for v in values])})
    if level < 3:
        if len(table) < len(values):
            lookup = {v: i for i, v in enumerate(table)}
            options.append({'dictionary': column(table, level+1),
                            'indices': integers([lookup[v] for v in values])})
        groups = {}
        split = [] if finite else [re.split(r'([0-9]+)', value) for value in values]
        for parts in split:
            groups.setdefault(tuple(parts[::2]), []).append(parts[1::2])
        if len(groups) == 1:
            fragments, rows = next(iter(groups.items()))
            if rows[0]:
                options.append({'lexical_template': list(fragments),
                                'columns': [column(list(c), level+1) for c in zip(*rows)]})
        elif 1 < len(groups) < min(len(values)//2, 100):
            lookup = {key: i for i, key in enumerate(groups)}
            options.append({'grouped_lexical_templates': [
                {'fragments': list(fr), 'count': len(rows),
                 'columns': [column(list(c), level+1) for c in zip(*rows)]}
                for fr, rows in groups.items()],
                'indices': integers([lookup[tuple(parts[::2])] for parts in split])})
    return min(options, key=size)


def overrides(values, entries):
    check(isinstance(entries, list))
    seen = set()
    for entry in entries:
        check(isinstance(entry, list) and len(entry) == 2)
        index, literal = entry
        check(type(index) is int and 0 <= index < len(values) and index not in seen and isinstance(literal, str))
        seen.add(index)
        values[index] = literal
    return values


def expand(spec, count, depth=0):
    check(isinstance(spec, dict) and depth < 24)
    keys = set(spec)
    if keys == {'constant'}:
        values = [spec['constant']]*count
    elif keys == {'values'}:
        check(isinstance(spec['values'], list))
        values = spec['values'][:]
    elif keys == {'runs'}:
        values = []
        for run in spec['runs']:
            check(isinstance(run, list) and len(run) == 2)
            literal, repeats = run
            check(type(repeats) is int and 0 < repeats <= count-len(values))
            values.extend([literal]*repeats)
    elif keys == {'dictionary', 'indices'}:
        indices = integer_values(spec['indices'], count)
        table_count = max(indices, default=-1)+1
        check(0 <= table_count <= count and all(i >= 0 for i in indices))
        table = expand(spec['dictionary'], table_count, depth+1)
        values = [table[i] for i in indices]
    elif keys == {'integer'}:
        values = [str(v) for v in integer_values(spec['integer'], count)]
    elif keys == {'padded_digits', 'widths'}:
        nums, widths = integer_values(spec['padded_digits'], count), integer_values(spec['widths'], count)
        check(all(n >= 0 and 0 < w <= 10000 for n, w in zip(nums, widths)))
        values = [str(n).zfill(w) for n, w in zip(nums, widths)]
    elif keys == {'canonical_scaled_decimal', 'literal_overrides'}:
        inner = spec['canonical_scaled_decimal']
        check(isinstance(inner, dict) and set(inner) == {'scale', 'integers'})
        scale = inner['scale']
        check(type(scale) is int and 0 <= scale <= 10000)
        values = overrides([decimal_spelling(v, scale) for v in integer_values(inner['integers'], count)], spec['literal_overrides'])
    elif keys == {'exact_decimal_base', 'literal_overrides'}:
        values = overrides(expand(spec['exact_decimal_base'], count, depth+1), spec['literal_overrides'])
    elif keys == {'lexical_template', 'columns'}:
        values = interleave(spec['lexical_template'], spec['columns'], count, depth+1)
    elif keys == {'grouped_lexical_templates', 'indices'}:
        templates = spec['grouped_lexical_templates']
        check(isinstance(templates, list) and len(templates) <= count)
        groups = []
        for template in templates:
            check(set(template) == {'fragments', 'count', 'columns'} and type(template['count']) is int and 0 < template['count'] <= count)
            groups.append(interleave(template['fragments'], template['columns'], template['count'], depth+1))
        indices = integer_values(spec['indices'], count)
        pointers, values = [0]*len(groups), []
        for index in indices:
            check(0 <= index < len(groups) and pointers[index] < len(groups[index]))
            values.append(groups[index][pointers[index]])
            pointers[index] += 1
        check(pointers == [len(g) for g in groups])
    else:
        raise ValueError('Unknown EVENT lexical codec')
    check(len(values) == count and all(isinstance(v, str) for v in values))
    return values


def interleave(fragments, specs, count, depth=0):
    check(isinstance(fragments, list) and all(isinstance(v, str) for v in fragments) and isinstance(specs, list) and len(fragments) == len(specs)+1)
    values = [expand(c, count, depth+1) for c in specs]
    return [''.join(fragments[j]+c[i] for j, c in enumerate(values))+fragments[-1] for i in range(count)]


def exact_add(a, b):
    with localcontext() as ctx:
        ctx.prec = max(50, len(a)+len(b)+10)
        return str(Decimal(a)+Decimal(b))


def truncate(value):
    return int(Decimal(value).to_integral_value(rounding=ROUND_DOWN))


def template_columns(fragments, values):
    """Only observed exact literal equalities can create cross-column relations."""
    specs = [column(v) for v in values]
    # Dependency direction is explicit and acyclic; choose equality to earlier
    # columns, then timestamp representations whose base is never rewritten.
    for i, vals in enumerate(values):
        for j in range(i):
            if vals == values[j] and size({'same_column': j}) < size(specs[i]):
                specs[i] = {'same_column': j}
    fields = {fr: i for i, fr in enumerate(fragments[:-1])}
    native = fields.get(', "native_t_ms": ')
    host = fields.get(', "host_ms": ')
    time = fields.get('{"t_ms": ')
    if native is not None and host is not None and native != host:
        try:
            residuals = [int(n)-truncate(h) for n, h in zip(values[native], values[host])]
            candidate = {'floor_decimal_column': host, 'integer_residuals': integers(residuals)}
            if all(str(truncate(h)+r) == n for n, h, r in zip(values[native], values[host], residuals)) and size(candidate) < size(specs[native]):
                specs[native] = candidate
        except (ValueError, ArithmeticError):
            pass
    if time is not None and native is not None:
        try:
            with localcontext() as ctx:
                ctx.prec = max(50, max(map(len, values[time]+values[native]))*2+10)
                offsets = [str(Decimal(t)-Decimal(n)) for t, n in zip(values[time], values[native])]
            candidate = {'decimal_offset_column': native, 'offsets': column(offsets)}
            if all(exact_add(n, o) == t for n, o, t in zip(values[native], offsets, values[time])) and size(candidate) < size(specs[time]):
                specs[time] = candidate
        except (ValueError, ArithmeticError):
            pass
    # A key is a literal lookup, never an inferred simulated time. No conflicts
    # permitted; original full strings and every value are checked before use.
    state, event, sim = (fields.get(', "state_seq": '), fields.get(', "source_event_id": '), fields.get(', "simulated_sec": '))
    if None not in (state, event, sim):
        lookup = {}
        for seq, event_id, val in zip(values[state], values[event], values[sim]):
            key = (seq, event_id.split('e')[0])
            if key in lookup and lookup[key] != val:
                break
            lookup[key] = val
        else:
            candidate = {'exact_key_columns': [{'column': state}, {'column': event, 'prefix_before': 'e'}],
                         'first_occurrence_values': column(list(lookup.values()))}
            if size(candidate) < size(specs[sim]):
                specs[sim] = candidate
    # Exact expansion also rejects any accidental relation cycle before return.
    check(expand_template_columns(specs, len(values[0]) if values else 0) == values)
    return specs


def expand_template_columns(specs, count):
    check(isinstance(specs, list))
    ready, pending = {}, set(range(len(specs)))
    while pending:
        before = len(pending)
        for index in list(pending):
            spec = specs[index]
            check(isinstance(spec, dict))
            keys = set(spec)
            refs = []
            if keys == {'same_column'}:
                refs = [spec['same_column']]
            elif keys == {'decimal_offset_column', 'offsets'}:
                refs = [spec['decimal_offset_column']]
            elif keys == {'floor_decimal_column', 'integer_residuals'}:
                refs = [spec['floor_decimal_column']]
            elif keys == {'exact_key_columns', 'first_occurrence_values'}:
                check(isinstance(spec['exact_key_columns'], list) and spec['exact_key_columns'])
                for part in spec['exact_key_columns']:
                    check(isinstance(part, dict) and set(part) in ({'column'}, {'column', 'prefix_before'}))
                    if 'prefix_before' in part:
                        check(isinstance(part['prefix_before'], str) and part['prefix_before'])
                refs = [p['column'] for p in spec['exact_key_columns']]
            check(all(type(r) is int and 0 <= r < len(specs) for r in refs))
            if any(r not in ready for r in refs):
                continue
            if keys == {'same_column'}:
                vals = ready[refs[0]][:]
            elif keys == {'decimal_offset_column', 'offsets'}:
                vals = [exact_add(a, b) for a, b in zip(ready[refs[0]], expand(spec['offsets'], count))]
            elif keys == {'floor_decimal_column', 'integer_residuals'}:
                vals = [str(truncate(a)+b) for a, b in zip(ready[refs[0]], integer_values(spec['integer_residuals'], count))]
            elif keys == {'exact_key_columns', 'first_occurrence_values'}:
                key_values = [tuple(ready[p['column']][i].split(p['prefix_before'])[0] if 'prefix_before' in p else ready[p['column']][i] for p in spec['exact_key_columns']) for i in range(count)]
                unique = list(dict.fromkeys(key_values))
                table = expand(spec['first_occurrence_values'], len(unique))
                lookup = dict(zip(unique, table))
                vals = [lookup[k] for k in key_values]
            else:
                vals = expand(spec, count)
            check(len(vals) == count)
            ready[index] = vals
            pending.remove(index)
        check(len(pending) < before, 'Cyclic EVENT exact column references')
    return [ready[i] for i in range(len(specs))]
