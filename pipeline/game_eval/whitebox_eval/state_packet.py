"""Lossless JSON column transport; raw evidence and sample selection stay intact."""
from __future__ import annotations
import copy
import json


def _size(value):
    return len(json.dumps(value,ensure_ascii=False,separators=(',',':')))


def encode_sequence(rows):
    if rows and all(isinstance(row,dict) for row in rows):
        keys=list(dict.fromkeys(key for row in rows for key in row))
        columns={}
        for key in keys:
            indices=[i for i,row in enumerate(rows) if key in row]
            col={'data':encode_sequence([rows[i][key] for i in indices])}
            if len(indices)!=len(rows):col['indices']=indices
            columns[key]=col
        return {'kind':'dict','n':len(rows),'columns':columns}
    if rows and all(isinstance(row,list) for row in rows):
        return {'kind':'list','lengths':[len(row) for row in rows],
                'items':encode_sequence([value for row in rows for value in row])}
    plain={'kind':'literal','values':copy.deepcopy(rows)}
    runs=[];last=None
    for value in rows:
        # JSON text distinguishes true/1/1.0 and retains exact numeric values.
        key=json.dumps(value,ensure_ascii=False,separators=(',',':'),sort_keys=True)
        if runs and key==last:runs[-1][0]+=1
        else:runs.append([1,copy.deepcopy(value)]);last=key
    rle={'kind':'rle','runs':runs}
    return rle if _size(rle)<_size(plain) else plain


def decode_sequence(encoded):
    kind=encoded['kind']
    if kind=='literal':return copy.deepcopy(encoded['values'])
    if kind=='rle':return [copy.deepcopy(value) for count,value in encoded['runs'] for _ in range(count)]
    if kind=='list':
        flat=decode_sequence(encoded['items']);result=[];start=0
        for length in encoded['lengths']:
            result.append(flat[start:start+length]);start+=length
        if start!=len(flat):raise ValueError('column list length mismatch')
        return result
    if kind=='dict':
        rows=[{} for _ in range(encoded['n'])]
        for key,column in encoded['columns'].items():
            indices=column.get('indices',range(len(rows)))
            values=decode_sequence(column['data'])
            if len(indices)!=len(values):raise ValueError('column dict length mismatch')
            for index,value in zip(indices,values):rows[index][key]=value
        return rows
    raise ValueError('unknown state transport encoding')


DESCRIPTION=('Lossless encoding exact-state-columns.v1: samples encodes the complete state_samples sequence. '
    'kind=literal returns values; kind=rle expands each [count,value] run; '
    'kind=list partitions decoded items using lengths; kind=dict creates n rows, with each column key '
    'assigned decoded data at indices (or all row indices if indices absent). '
    'After decoding, replace each provenance_ref with provenance_tables[provenance_ref] under provenance. '
    'All original fields, values, rows and line numbers are retained. Cite STATE by original line, never a column/table index.')
