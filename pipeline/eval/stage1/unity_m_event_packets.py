"""Recover blocked Unity event delivery with exact bounded physical-row packets.

Original blocked parents remain immutable. Every raw event is delivered; each
packet retains the original 512-row/160000-byte EVENT limits. STATE selection
uses the existing source-bound selector and is never expanded by this route.
"""
from pathlib import Path
import copy
import hashlib
import json
from . import batch, endpoint_channels
from .action_links import physical_rows
from .protocol import sha


def partition(rows):
    packets=[];part=[];size=0
    for line,row in rows:
        width=len(json.dumps(row,ensure_ascii=False).encode())
        if width>endpoint_channels.BYTE_LIMIT:raise ValueError('One original EVENT row exceeds frozen byte limit')
        if part and (len(part)>=endpoint_channels.ROW_LIMIT or size+width>endpoint_channels.BYTE_LIMIT):
            packets.append(part);part=[];size=0
        part.append(line);size+=width
    if part:packets.append(part)
    if [n for p in packets for n in p]!=[n for n,_ in rows]:raise ValueError('Every original physical EVENT row required')
    return packets


def packets(root,manifest,parent, *, numeric=False):
    root=Path(root);subset=manifest['evidence_sets'][parent]
    failure=subset.get('transport_blocked',{})
    if (failure.get('kind')!='INPUT_CAPACITY_EXCEEDED'
            or not failure.get('error','').startswith('Endpoint physical rows exceed bounded transport: EVENT ')
            or subset.get('endpoint_contracts')):
        raise ValueError('Only exact blocked EVENT parent without omitted endpoint contracts qualifies')
    path=root/'runtime/event_trace.jsonl';rows=physical_rows(path);blocks=partition(rows)
    if len(blocks)<2:raise ValueError('Actual multiple bounded EVENT packets required')
    link_path=root/manifest['action_frame_links']['path']
    if sha(link_path)!=manifest['action_frame_links']['sha256']:raise ValueError('Original action association changed')
    links=batch.read(link_path)
    if any(set(subset['criterion_ids']) & set(l.get('criterion_ids',[])) for l in links['links']):
        raise ValueError('This recovery requires the original whole-route fallback, not a changed scoped selection')
    result=[];states=None;union=[]
    row_map=dict(rows)
    raw_lines=path.read_text().split("\n")
    for index,lines in enumerate(blocks):
        local=copy.deepcopy(links);allowed=set(lines)
        for link in local['links']:link['events']=[n for n in link['events'] if n in allowed]
        selected_channels=endpoint_channels.select(root,local,[],{},version=endpoint_channels.LOSSLESS_LOG_VERSION)
        if states is None:states=selected_channels['delivered_channel_lines']['STATE']
        elif states!=selected_channels['delivered_channel_lines']['STATE']:
            raise ValueError('Partition must not change original bounded STATE selection')
        selected=copy.deepcopy(manifest)
        selected.update(selected_channels)
        selected['items']=[i for i in manifest['items'] if i['type'] in {'log','action','event','state'}]
        selected['delivery_sheets']=[];selected['current_evidence_set']=f'unity_m_complete_events_{index+1:02d}'
        # Supplement every physical event, including rows not linked to actions.
        selected['delivered_channel_lines']['EVENT']=lines
        selected['channel_clipping']=[x for x in selected['channel_clipping'] if x['channel']!='EVENT']
        selected['channel_clipping'].append(dict(channel='EVENT',action_id=None,criterion_ids=[],
            missing_physical_lines=[n for n,_ in rows if n not in allowed],
            reason='Delivered in another ordered bounded packet of the same retained judgment context.'))
        if index:
            selected['items']=[i for i in selected['items'] if i['id']=='EVENT']
            selected['delivered_channel_lines']['STATE']=[]
            selected['delivered_channel_lines']['ACTION']=[]
            selected['delivered_channel_lines'].pop('ENGINE',None)
        wire_binding=None
        if numeric:
            from . import event_wire
            wire_binding=event_wire.binding(event_wire.encode(path,lines,encoding=event_wire.NUMERIC_VERSION))
            selected[event_wire.FIELD]=event_wire.NUMERIC_VERSION
            selected['channel_transport']['event_wire_transport']=wire_binding
        packet,omitted=batch.packet(root,selected,False)
        if any(v['id']=='EVENT' for v in omitted):raise ValueError('Raw event packet cannot be clipped')
        if numeric:
            event_wire.verify_section(packet,path,lines,wire_binding,extended=False)
        else:
            for n in lines:
                if f'{n}: {raw_lines[n-1]}\n' not in packet:raise ValueError('Every original event line must be literally delivered')
        union.extend(lines)
        result.append(dict(selected=selected,packet=packet,omitted=omitted,
            proof=dict(index=index+1,physical_lines=lines,row_count=len(lines),
                event_json_bytes=sum(len(json.dumps(row_map[n],ensure_ascii=False).encode()) for n in lines),
                packet_sha256=hashlib.sha256(packet.encode()).hexdigest(),event_source_sha256=sha(path),
                **({'event_wire':wire_binding} if numeric else {}))))
    if union!=[n for n,_ in rows]:raise ValueError('Full original event union differs')
    return result
