"""Codely stream-json formatter fields verified against installed CLI (2026-09-10).

emitToolUse: tool_name/tool_id/parameters; emitToolResult: tool_id/status plus
every other actual field (output, error, exit_code, ...) — no silent loss.
Autosave is intentionally not used as an incremental event source.
"""
from .base import AgentAdapter
from .codex import CodexNormalizer
from ..core.collector import content_block


class CodelyAdapter(AgentAdapter):
    provider='codely'
    def __init__(self, executable='codely', extra_args=()):
        self.executable,self.extra_args=executable,list(extra_args)
    def start(self,prompt,*,cwd,env=None):
        return self._spawn([self.executable,'--output-format','stream-json',*self.extra_args,'--prompt',prompt],cwd,env)
    def normalizer(self): return CodelyNormalizer()


class CodelyNormalizer:
    def __init__(self):
        self.session_id=None; self.model=None
        self._assistant_text=''; self._reasoning_text=''; self._pending_common=None
    def normalize(self,e):
        typ=e.get('type')
        prior = self.finish() if typ=='init' else []
        if typ=='init':
            self.session_id=e.get('session_id'); self.model=e.get('model')
        common={'producer':'codely','provider_event':typ,'session_id':self.session_id,'model':self.model}
        if e.get('timestamp'): common.update(ts=e['timestamp'],ts_source='provider')
        if typ=='message' and e.get('role') in {'assistant','user','system'}:
            role=e.get('role'); text=e.get('content','')
            if role=='assistant' and e.get('delta'):
                # The CLI streams assistant text as many tiny deltas (most are
                # empty); record nothing per delta and emit ONE merged message
                # when the turn ends (tool_use/tool_result/result/user turn).
                # Reasoning tokens arrive in reasoning_content; they are kept
                # under the autosave importer's restricted policy.
                if self._pending_common is None: self._pending_common=dict(common)
                self._assistant_text+=text or ''
                self._reasoning_text+=e.get('reasoning_content') or ''
                return []
            message=dict(source=role,kind='message',
                content=[content_block('text',data=text or '',visibility='collector_only')],**common)
            if role=='assistant' and e.get('reasoning_content'):
                from .codely_reasoning import reasoning_record
                message['raw_reasoning']=reasoning_record(e['reasoning_content'])
            return self._flush(common)+[message]
        events=prior+self._flush(common)
        if typ=='tool_use':
            cid=e.get('tool_id')
            events.append(CodexNormalizer.call(f'codely:{self.session_id}:{cid}' if cid else None,e.get('tool_name'),e.get('parameters'),
                {**common,'provider_call_id':cid,'observation_view':'provider_call'}))
            return events
        if typ=='tool_result':
            cid=e.get('tool_id')
            # Keep every actual result field, not a curated subset: only the
            # identity/lifecycle fields lifted elsewhere are excluded.
            payload={k:v for k,v in e.items() if k not in {'type','tool_id','status','timestamp'}}
            events.append(CodexNormalizer.result(f'codely:{self.session_id}:{cid}' if cid else None,
                payload,e.get('status','unknown'),
                {**common,'provider_call_id':cid,'observation_view':'provider_result'}))
            return events
        if typ in {'init','result','stats','error','agent_start','agent_finish'}:
            events.append(dict(source='system',kind='runtime',content=[content_block('json',data=e,visibility='collector_only')],**common))
            return events
        events.append(CodexNormalizer.unknown(e,common))
        return events
    def finish(self):
        """Flush observed deltas at EOF/interruption; never synthesize a result."""
        return self._flush({})

    def _flush(self,common):
        if not self._assistant_text and not self._reasoning_text: return []
        common=self._pending_common or common
        self._pending_common=None
        text=self._assistant_text; reasoning=self._reasoning_text
        self._assistant_text=''; self._reasoning_text=''
        event=dict(source='assistant',kind='message',
            content=[content_block('text',data=text,visibility='collector_only')] if text else [],
            **common)
        if reasoning:
            # Same restricted-retention policy as the autosave importer:
            # provider thinking is archived but never used as training input.
            event['raw_reasoning']={'visibility':'collector_only','content':reasoning,
                'policy':'retained_restricted_not_training_input'}
        return [event]
