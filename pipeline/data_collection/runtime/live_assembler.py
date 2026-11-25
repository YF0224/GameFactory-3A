"""Association and replay into Collector. Never executes a tool or infers intent."""
from __future__ import annotations
import copy
import hashlib
import json
from ..core.collector_sink import as_sink
from ..core.collector import content_block
from .observation_spool import METHODS

_REFERENCE_KEYS = {'event_id','parent_event_id','call_event_id','trigger_event_id','state_ref',
    'tool_call_id','request_id','version_id','parent_version_id','verification_event_id',
    'input_event_ids','response_event_ids','visible_event_ids'}


class LiveAssembler:
    def __init__(self, collector):
        self.sink=as_sink(collector)
        self.collector=self.sink.collector
        self.seen={}
        self.sequences={}
        self.aliases={}
        self.closed=set()
        for e in self.collector.trajectory['events']:
            if e.get('operation')=='observation_ingested':
                p,s=e['producer_id'],e['producer_sequence']
                self.seen[(p,s)]=e['envelope_sha256']
                self.sequences[p]=max(s,self.sequences.get(p,0))
                self.aliases.update(e.get('reference_aliases',{}))
                if e.get('producer_closed'): self.closed.add(p)

    def audit(self, code, **details):
        return self.sink.record_event('system','runtime',producer='capture_audit',status='unknown',
                                     audit_code=code,**details)

    def _calls(self,cid):
        return [(e,c) for e in self.collector.trajectory['events'] for c in e.get('tool_calls',[]) if c.get('tool_call_id')==cid]

    def provider_event(self,event):
        # Preserve both views without manufacturing a second assistant call.
        if event.get('kind')=='tool_call' and len(event.get('tool_calls',[]))==1:
            call=event['tool_calls'][0]
            matches=self._calls(call['tool_call_id'])
            if matches:
                same=len(matches)==1 and matches[0][1]==call
                return self.sink.record_event('system','runtime',producer=event.get('producer'),
                    operation='provider_call_observation',parent_event_id=matches[0][0]['event_id'],
                    audit_code='duplicate_call_observation' if same else 'conflicting_call_id',
                    content=[content_block('json',data=event,visibility='collector_only')])
        return self.sink.record_event(**event)

    def _refs(self,value,key=None):
        if isinstance(value,dict): return {k:self._refs(v,k) for k,v in value.items()}
        if isinstance(value,list): return [self._refs(v,key) for v in value]
        if isinstance(value,str) and key in _REFERENCE_KEYS: return self.aliases.get(value,value)
        return value

    def _alias(self,local,actual):
        if isinstance(local,str) and isinstance(actual,str): self.aliases[local]=actual
        elif isinstance(local,(list,tuple)) and isinstance(actual,(list,tuple)):
            for a,b in zip(local,actual): self._alias(a,b)
        elif isinstance(local,dict) and isinstance(actual,dict):
            for key in _REFERENCE_KEYS & local.keys() & actual.keys(): self._alias(local[key],actual[key])

    def ingest(self,envelope):
        if not isinstance(envelope,dict):
            self.audit('damaged_spool_record',reason='not_object'); return
        p,s=envelope.get('producer_id'),envelope.get('producer_sequence')
        if not isinstance(p,str) or not p or type(s) is not int or s<1:
            self.audit('damaged_spool_record',reason='invalid_identity'); return
        digest=hashlib.sha256(json.dumps(envelope,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        if (p,s) in self.seen:
            if self.seen[(p,s)]!=digest: self.audit('producer_sequence_conflict',producer_id=p,producer_sequence=s)
            return
        c=self.collector
        before=copy.deepcopy(c.trajectory)
        counters=dict(c._counters)
        aliases=dict(self.aliases)
        c.writer.suspended=True
        try:
            expected=self.sequences.get(p,0)+1
            if s!=expected:
                self.audit('producer_sequence_gap',producer_id=p,expected_sequence=expected,observed_sequence=s)
            kind=envelope.get('kind')
            if kind=='producer.closed':
                pass
            elif kind not in METHODS:
                self.audit('unknown_observation_method',producer_id=p,method=kind)
            else:
                payload=envelope.get('payload') or {}
                args=payload.get('args',[])
                kwargs=self._refs(payload.get('kwargs',{}))
                # Positional IDs for the small set of reference-taking Collector APIs.
                args=list(args)
                if args and kind in {'record_tool_result','close_request'}:
                    args[0]=self.aliases.get(args[0],args[0])
                if kind=='open_request' and args:
                    args[0]=[self.aliases.get(x,x) for x in args[0]]
                if kind=='record_workspace_change' and kwargs.get('content_path'):
                    path=c.artifact_store.resolve(kwargs['content_path']).resolve()
                    if not path.is_relative_to(c.artifact_store.root.resolve()):
                        raise ValueError('spool workspace content must reference the shared immutable blob store')
                    kwargs['content_path']=path
                if kind=='record_tool_call' and kwargs.get('tool_call_id'):
                    matches=self._calls(kwargs['tool_call_id'])
                    if matches:
                        if len(matches)!=1 or matches[0][1]['name']!=args[0] or matches[0][1]['arguments']!=args[1]:
                            self.audit('conflicting_call_id',producer_id=p,tool_call_id=kwargs['tool_call_id'])
                            actual=None
                        else:
                            actual=(matches[0][0]['event_id'],kwargs['tool_call_id'])
                    else: actual=getattr(self.sink,kind)(*args,**kwargs)
                else:
                    actual=getattr(self.sink,kind)(*args,**kwargs)
                self._alias(payload.get('local_result'),actual)
            self.sink.record_event('system','runtime',producer='observation_ingress',
                operation='observation_ingested',producer_id=p,producer_sequence=s,
                ts=envelope.get('timestamp'),ts_source='producer',envelope_sha256=digest,
                reference_aliases={k:v for k,v in self.aliases.items() if aliases.get(k)!=v},
                producer_closed=kind=='producer.closed')
            c.writer.suspended=False
            c.writer.checkpoint()  # event(s), references, dedup marker commit together
        except Exception:
            c.writer.suspended=False
            c.trajectory.clear(); c.trajectory.update(before)
            c._counters=counters
            self.aliases=aliases
            raise
        self.seen[(p,s)]=digest
        self.sequences[p]=max(s,self.sequences.get(p,0))
        if kind=='producer.closed': self.closed.add(p)
