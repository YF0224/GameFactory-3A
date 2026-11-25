"""Exact reversible column dictionaries for long real native event deliveries."""
from copy import deepcopy
import hashlib
import json
from .common import dump, sha

VERSION='grouped-native-rows-column-dictionaries.v1'


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))


def encode_rows(rows):
    groups={}
    for position,record in enumerate(rows):
        if set(record)!={'line','row'} or not isinstance(record['row'],dict):
            raise ValueError('Only exact physical row records may be encoded')
        keys=tuple(sorted(record['row']))
        groups.setdefault(keys,[]).append((position,record))
    tables=[]
    for keys,records in groups.items():
        constants={};variables=[]
        for key in keys:
            unique={}
            for _,record in records:
                value=record['row'][key];unique.setdefault(canonical(value),value)
            values=list(unique.values())
            if len(values)==1:constants[key]=values[0]
            else:variables.append({'field':key,'values':values})
        lookups=[{canonical(value):i for i,value in enumerate(column['values'])} for column in variables]
        encoded=[]
        for position,record in records:
            encoded.append([position,record['line']]+[lookup[canonical(record['row'][col['field']])]
                for col,lookup in zip(variables,lookups)])
        tables.append({'constants':constants,'columns':variables,'records':encoded})
    return {'encoding':VERSION,'row_count':len(rows),'tables':tables}


def decode_rows(value):
    if value['encoding']!=VERSION:raise ValueError('Unknown row encoding')
    restored={}
    for table in value['tables']:
        for record in table['records']:
            position,line,*cells=record
            if position in restored or len(cells)!=len(table['columns']):
                raise ValueError('Invalid physical row position or cell count')
            row=dict(table['constants'])
            for column,index in zip(table['columns'],cells):
                if not isinstance(index,int) or not 0<=index<len(column['values']):
                    raise ValueError('Invalid column dictionary index')
                row[column['field']]=column['values'][index]
            restored[position]={'line':line,'row':row}
    if set(restored)!=set(range(value['row_count'])):raise ValueError('Physical row lost/duplicated')
    return [restored[i] for i in range(value['row_count'])]


def prepare(root, delivered):
    """Send every delivered source/frame/channel, with exactly reversible rows."""
    original=canonical(delivered);wire=deepcopy(delivered);changed=[]
    if len(original)>600000:
        for name,channel in wire['channels'].items():
            encoded=encode_rows(channel['rows'])
            if len(canonical(encoded))<len(canonical(channel['rows'])):
                channel['rows']=encoded;changed.append(name)
    restored=deepcopy(wire)
    for name in changed:restored['channels'][name]['rows']=decode_rows(wire['channels'][name]['rows'])
    if canonical(restored)!=original:raise ValueError('Native transport is not exactly reversible')
    text=canonical(wire)
    path=root/'evidence/judge_wire_delivery.json';dump(path,wire)
    dump(root/'evidence/judge_wire_equivalence.json',{
        'version':VERSION,'original_sha256':hashlib.sha256(original.encode()).hexdigest(),
        'restored_sha256':hashlib.sha256(canonical(restored).encode()).hexdigest(),
        'wire_sha256':sha(path),'original_characters':len(original),'wire_characters':len(text),
        'encoded_channels':changed,'row_counts':{k:len(v['rows']) for k,v in delivered['channels'].items()},
        'images_unchanged':wire['images']==delivered['images'],'physical_line_numbers_preserved':True})
    instructions=('\nLOSSLESS NATIVE ROW TRANSPORT: channels.rows may use '+VERSION+'. '
        'Each table has constants applying to every record; columns have field names and exact values dictionaries. '
        'Each record is [original_position, physical_line, index_for_column_0, ...]. Restore the row by combining '
        'constants and columns[i].values[index_i]. Different tables represent different exact field sets. '
        'All original rows and physical line numbers are retained; cite physical_line, never array position. '
        'All source/frame/context/citation requirements are unchanged. Original JSON remains under evidence/judge_delivery.json.\n') if changed else '\n'
    return instructions+text
