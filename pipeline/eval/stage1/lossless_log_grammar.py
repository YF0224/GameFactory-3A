"""Exact, readable shared line grammar for irregularly repeated runtime logs."""
from collections import Counter
import json

VERSION = 'exact-log-physical-grammar.v1'
POSITION_VERSION = 'exact-log-physical-grammar.v2'


def encode(lines, selected, source_sha256):
    texts = list(dict.fromkeys(lines[number-1] for number in selected))
    identifiers = {text: index for index, text in enumerate(texts)}
    stream = [identifiers[lines[number-1]] for number in selected]
    rules = []
    # This bounded search only changes compression quality, never accepted rows.
    # An incompressible wire still fails the caller's unchanged byte limit.
    for _ in range(1000):
        best = Counter(zip(stream, stream[1:])).most_common(1)
        if not best or best[0][1] < 3:
            break
        pair, _ = best[0]
        symbol = len(texts) + len(rules)
        output = []
        index = 0
        while index < len(stream):
            if index+1 < len(stream) and (stream[index],stream[index+1]) == pair:
                output.append(symbol)
                index += 2
            else:
                output.append(stream[index])
                index += 1
        rules.append(list(pair))
        stream = output
    # Frequent symbol indices get short decimal spellings. Every exact text is
    # still visible in symbols; this is a textual grammar, not opaque binary.
    frequencies = Counter(stream)
    frequencies.update(symbol for pair in rules for symbol in pair)
    symbols = texts + rules
    order = sorted(range(len(symbols)), key=lambda index: (-frequencies[index],index))
    remap = {old:new for new,old in enumerate(order)}
    table = [symbols[index] if index < len(texts) else
             [remap[item] for item in symbols[index]] for index in order]
    ranges = []
    for number in selected:
        if ranges and number == ranges[-1][0]+ranges[-1][1]:
            ranges[-1][1] += 1
        else:
            ranges.append([number,1])
    wire = {'encoding':VERSION, 'source_sha256':source_sha256,
        'decode':'Each symbols[index] is either one exact text line or a pair of symbol indices. Recursively expand each symbol in order, left to right; the grammar is acyclic. Assign the resulting lines to physical_ranges [first,count], in range order. Every occurrence, repeated line and stack is retained. Cite ENGINE using original physical line numbers. Omitted raw rows are not evidence of absence or normal execution.',
        'row_count':len(selected), 'physical_ranges':ranges,
        'symbols':table, 'order':[remap[index] for index in stream]}
    positions = encode_positions(ranges)
    if len(ranges) > 128 and len(json.dumps(positions)) < len(json.dumps(ranges)):
        wire['encoding'] = POSITION_VERSION
        del wire['physical_ranges']
        wire['physical_ranges_grammar'] = positions
        wire['decode'] = wire['decode'].replace('physical_ranges [first,count]',
            'physical_ranges [first,count], reconstructed by physical_ranges_grammar')
    return wire


def decode(wire):
    if wire.get('encoding') not in (VERSION, POSITION_VERSION):
        raise ValueError('Unknown log grammar encoding')
    count = wire.get('row_count')
    if type(count) is not int or not 0 <= count <= 64*1048576+1:
        raise ValueError('Invalid log grammar row count')
    table = wire.get('symbols')
    order = wire.get('order')
    if wire['encoding'] == POSITION_VERSION:
        if 'physical_ranges' in wire:
            raise ValueError('Ambiguous log grammar physical ranges')
        ranges = decode_positions(wire.get('physical_ranges_grammar'), count)
    else:
        if 'physical_ranges_grammar' in wire:
            raise ValueError('Unexpected log grammar physical range encoding')
        ranges = wire.get('physical_ranges')
    if not all(isinstance(value,list) for value in (table,order,ranges)):
        raise ValueError('Invalid log grammar tables')
    def valid_index(index):
        return type(index) is int and 0 <= index < len(table)
    # Iterative DFS validates acyclicity and expansion lengths before emitting
    # any rows. The row bound rejects exponential malicious grammar expansion.
    sizes = {}
    visiting = set()
    for root in order:
        stack = [(root,False)]
        while stack:
            index, finish = stack.pop()
            if not valid_index(index):
                raise ValueError('Invalid log grammar symbol reference')
            if index in sizes:
                continue
            item = table[index]
            if isinstance(item,str):
                if '\n' in item or '\r' in item:
                    raise ValueError('Invalid log grammar text line')
                sizes[index] = 1
            elif isinstance(item,list) and len(item) == 2 and all(map(valid_index,item)):
                if finish:
                    sizes[index] = sum(sizes[child] for child in item)
                    visiting.remove(index)
                    if sizes[index] > count:
                        raise ValueError('Log grammar expansion exceeds row count')
                else:
                    if index in visiting:
                        raise ValueError('Cyclic log grammar')
                    visiting.add(index)
                    stack.append((index,True))
                    stack.extend((child,False) for child in reversed(item))
            else:
                raise ValueError('Invalid log grammar symbol')
    if len(sizes) != len(table) or sum(sizes[index] for index in order) != count:
        raise ValueError('Missing or extra log grammar occurrences')
    physical = []
    previous = 0
    for item in ranges:
        if (not isinstance(item,list) or len(item) != 2 or
                any(type(number) is not int for number in item)):
            raise ValueError('Invalid log grammar physical range')
        first, length = item
        if first <= previous or length < 1 or len(physical)+length > count:
            raise ValueError('Duplicate or invalid log grammar physical range')
        physical.extend(range(first,first+length))
        previous = first+length-1
    if len(physical) != count:
        raise ValueError('Missing log grammar physical occurrences')
    rows = []
    stack = list(reversed(order))
    while stack:
        index = stack.pop()
        item = table[index]
        if isinstance(item,str):
            rows.append((physical[len(rows)],item))
        else:
            stack.extend(reversed(item))
    return rows


def encode_positions(ranges):
    """Readable shared grammar of exact (gap after previous end, count) pairs."""
    pairs = []
    previous = 0
    for first, length in ranges:
        pairs.append((first-previous, length))
        previous = first+length-1
    terminals = list(dict.fromkeys(pairs))
    identifiers = {pair: index for index, pair in enumerate(terminals)}
    stream = [identifiers[pair] for pair in pairs]
    rules = []
    for _ in range(1000):
        best = Counter(zip(stream, stream[1:])).most_common(1)
        if not best or best[0][1] < 3:
            break
        pair, _ = best[0]
        symbol = len(terminals)+len(rules)
        output = []
        index = 0
        while index < len(stream):
            if index+1 < len(stream) and (stream[index], stream[index+1]) == pair:
                output.append(symbol)
                index += 2
            else:
                output.append(stream[index])
                index += 1
        rules.append(list(pair))
        stream = output
    return {'decode': 'Terminal indices start at 0. Each terminal is [gap,count]. '
            'Rule i has index len(terminals)+i and concatenates its two earlier symbols. '
            'Expand order left to right into exactly range_count terminals. Starting previous_end=0, '
            'each terminal gives first=previous_end+gap, physical range [first,count], '
            'then previous_end=first+count-1. Retain every original occurrence and physical line.',
            'range_count': len(ranges), 'terminals': [list(pair) for pair in terminals],
            'rules': rules, 'order': stream}


def decode_positions(wire, row_count):
    if not isinstance(wire, dict):
        raise ValueError('Invalid log position grammar')
    count = wire.get('range_count')
    terminals, rules, order = (wire.get(key) for key in ('terminals','rules','order'))
    if (type(count) is not int or not 0 <= count <= row_count or
            not all(isinstance(value,list) for value in (terminals,rules,order))):
        raise ValueError('Invalid log position grammar tables')
    if (len(terminals) > count or len(rules) > count or len(order) > count):
        raise ValueError('Log position grammar exceeds range count')
    sizes = []
    rows = []
    for pair in terminals:
        if (not isinstance(pair,list) or len(pair) != 2 or
                any(type(value) is not int or value < 1 for value in pair)):
            raise ValueError('Invalid log position terminal')
        sizes.append(1)
        rows.append(pair[1])
    for pair in rules:
        if (not isinstance(pair,list) or len(pair) != 2 or
                any(type(value) is not int or not 0 <= value < len(sizes) for value in pair)):
            raise ValueError('Invalid or cyclic log position rule')
        size = sum(sizes[value] for value in pair)
        row_size = sum(rows[value] for value in pair)
        if size > count or row_size > row_count:
            raise ValueError('Log position grammar expansion exceeds bounds')
        sizes.append(size)
        rows.append(row_size)
    if (any(type(value) is not int or not 0 <= value < len(sizes) for value in order) or
            sum(sizes[value] for value in order) != count or
            sum(rows[value] for value in order) != row_count):
        raise ValueError('Log position grammar occurrence count differs')
    ranges = []
    previous = 0
    seen = set()
    stack = list(reversed(order))
    while stack:
        index = stack.pop()
        seen.add(index)
        if index < len(terminals):
            gap, length = terminals[index]
            first = previous+gap
            ranges.append([first,length])
            previous = first+length-1
        else:
            stack.extend(reversed(rules[index-len(terminals)]))
    if len(seen) != len(sizes):
        raise ValueError('Unused log position grammar symbols')
    return ranges
